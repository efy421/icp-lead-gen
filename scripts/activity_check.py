#!/usr/bin/env python3
"""
Activity check — is this lead ACTIVE on LinkedIn within 90 days?

GATE (per user, 2026-10-12): 1+ post in 90 days = ACTIVE. 0 = INACTIVE.
There is no "semi" tier — a single post inside the window clears the lead.

  ACTIVE      >=1 post in the last 90 days
  INACTIVE    0 posts in the last 90 days (last post is older, or none)
  NO_RESULT   run did not complete, or profile has no retrievable posts

CRITICAL IMPLEMENTATION NOTE — read before changing:
The actor returns PARTIAL datasets when the run does not finish before
`waitForFinish` expires, and it does so SILENTLY (status=SUCCEEDED). An
8-URL batch at waitForFinish=400 returned 0 posts for later profiles, which
is indistinguishable from "never posted". Same batch at 700 returned 7/8.
=> Keep the generous timeout. Do NOT shorten it and do not treat a short
   dataset as proof of inactivity.
"""
import json, datetime, subprocess, itertools, os

BASE = "/home/irfan/firstmate"
POOL = f"{BASE}/apify_keys_pool.txt"
_rot = itertools.cycle([l.strip() for l in open(POOL) if l.strip()])
ACTOR = "harvestapi~linkedin-profile-posts"
DAYS = 90
BATCH = 8
WAIT = 700          # generous: partial results are silent, not an error
MAXPOSTS = 20


PAGE = 100          # items per dataset page request


def _fetch_dataset_items(ds, tok, max_pages=40):
    """Page through a dataset instead of downloading it in one shot.

    A single GET on a large dataset truncates mid-JSON (observed at ~280KB and
    ~393KB), which silently drops records. Paging with ?offset=&limit= keeps
    each response small and makes truncation obvious (a short page ends the
    loop early) rather than corrupting the result.
    """
    items, offset, truncated_pages = [], 0, 0
    for _ in range(max_pages):
        tmp = f"/tmp/_pg_{os.getpid()}_{offset}.json"
        subprocess.run(["curl", "-s", "--compressed", "-m", "120", "-o", tmp,
            f"https://api.apify.com/v2/datasets/{ds}/items"
            f"?token={tok}&offset={offset}&limit={PAGE}&clean=1"],
            capture_output=True)
        raw = open(tmp, encoding="utf-8", errors="ignore").read()
        if os.path.exists(tmp):
            os.remove(tmp)
        page = None
        try:
            page = json.loads(raw)
        except Exception:
            dec = json.JSONDecoder()
            try:
                page, _ = dec.raw_decode(raw)   # salvage a partial page
                truncated_pages += 1
            except Exception:
                break
        if isinstance(page, dict):
            page = page.get("items", [])
        if not isinstance(page, list) or not page:
            break
        items.extend(x for x in page if isinstance(x, dict))
        if len(page) < PAGE:
            break                              # short page = last page
        offset += PAGE
    if truncated_pages:
        print(f"  note: salvaged {truncated_pages} truncated page(s)")
    return items


def fetch_activity(urls, days=DAYS, max_posts=MAXPOSTS, wait=WAIT, batch=BATCH):
    """Returns {url: {latest_date, n90, total, status}}"""
    out = {u: {"latest": None, "n90": 0, "total": 0, "status": "NO_RESULT",
               "run_ok": False}
           for u in urls}
    if not urls:
        return out

    for i in range(0, len(urls), batch):
        chunk = urls[i:i + batch]
        tok = next(_rot)
        payload = {"targetUrls": chunk, "maxPosts": max_posts}
        p = subprocess.run(["curl", "-s", "--compressed", "-m", str(wait + 60),
            "-X", "POST",
            f"https://api.apify.com/v2/acts/{ACTOR}/runs?token={tok}&waitForFinish={wait}",
            "-H", "Content-Type: application/json", "-d", json.dumps(payload)],
            capture_output=True, text=True)
        try:
            d = json.loads(p.stdout).get("data", {})
        except Exception:
            continue
        if d.get("status") != "SUCCEEDED":
            continue
        ds = d.get("defaultDatasetId")
        if not ds:
            continue
        items = _fetch_dataset_items(ds, tok)
        if not items:
            continue

        cut = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        buckets = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            q = it.get("query") or {}
            tgt = q.get("targetUrl") or (it.get("author") or {}).get("linkedinUrl") or ""
            slug = tgt.rstrip("/").split("/")[-1].lower()
            if not slug:
                continue
            pa = it.get("postedAt") or {}
            raw = pa.get("date") if isinstance(pa, dict) else str(pa)
            if not raw:
                continue
            try:
                dt = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except Exception:
                continue
            b = buckets.setdefault(slug, {"latest": None, "n90": 0, "total": 0})
            b["total"] += 1
            if b["latest"] is None or dt > b["latest"]:
                b["latest"] = dt
            if dt >= cut:
                b["n90"] += 1

        for u in chunk:
            slug = u.rstrip("/").split("/")[-1].lower()
            b = buckets.get(slug)
            if not b:
                continue          # left as NO_RESULT — run completed, profile returned nothing
            # GATE: one post inside the window clears the lead
            b["status"] = "ACTIVE" if b["n90"] >= 1 else "INACTIVE"
            b["latest_date"] = b["latest"].date().isoformat() if b["latest"] else ""
            b["run_ok"] = True
            out[u] = b
    return out


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/act_urls.txt"
    urls = [l.strip() for l in open(path) if l.strip()]
    res = fetch_activity(urls)
    print(f"{'PROFILE':30} {'N90':>4} {'TOT':>4} {'LATEST':12} STATUS")
    print("-" * 70)
    for u in urls:
        r = res[u]
        print(f"{u.split('/')[-1][:30]:30} {r['n90']:>4} {r['total']:>4} "
              f"{r.get('latest_date', '-'):12} {r['status']}")
    from collections import Counter
    print("\nsummary:", dict(Counter(r["status"] for r in res.values())))