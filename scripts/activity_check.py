#!/usr/bin/env python3
"""Activity check — is this lead ACTIVE on LinkedIn within 90 days?
Mirrors the ACTIVE / SEMI_ACTIVE / INACTIVE model from lead-verification-pipeline.

Rules (same as the BP pipeline):
  posts_in_90d >= 3  -> ACTIVE
  posts_in_90d 1-2   -> SEMI_ACTIVE
  posts_in_90d == 0  -> INACTIVE
  no posts returned  -> NO_RESULT (private profile / never posted / rate-limited)
"""
import json, datetime, subprocess, itertools, os

BASE = "/home/irfan/firstmate"
POOL = f"{BASE}/apify_keys_pool.txt"
_rot = itertools.cycle([l.strip() for l in open(POOL) if l.strip()])
ACTOR = "harvestapi~linkedin-profile-posts"


def fetch_activity(urls, days=90, max_posts=20, wait=400, chunk=1):
    """Returns {slug: dict(latest, n90, total, status)}"""
    out = {u: {"latest": None, "n90": 0, "total": 0, "status": "NO_RESULT"}
           for u in urls}
    if not urls:
        return out
    # ONE URL PER REQUEST. The actor rate-limits and silently returns 0 posts
    # for later URLs in a batch — a 4-URL batch returned ACTIVE profiles as
    # NO_RESULT. Verified: same URL on a fresh key returns full posts.
    # Round-robin tokens so each profile gets a clean attempt.
    results = {}
    for u in urls:
        results.update(_fetch_chunk([u], days, max_posts, wait))
    return results


def _fetch_chunk(urls, days, max_posts, wait):
    out = {u: {"latest": None, "n90": 0, "total": 0, "status": "NO_RESULT"}
           for u in urls}
    tok = next(_rot)
    payload = {"targetUrls": urls, "maxPosts": max_posts}
    p = subprocess.run(["curl", "-s", "-m", str(wait + 60), "-X", "POST",
        f"https://api.apify.com/v2/acts/{ACTOR}/runs?token={tok}&waitForFinish={wait}",
        "-H", "Content-Type: application/json", "-d", json.dumps(payload)],
        capture_output=True, text=True)
    try:
        d = json.loads(p.stdout).get("data", {})
    except Exception:
        return out
    if d.get("status") != "SUCCEEDED":
        return out
    ds = d.get("defaultDatasetId")
    if not ds:
        return out
    p2 = subprocess.run(["curl", "-s", "-m", "90",
        f"https://api.apify.com/v2/datasets/{ds}/items?token={tok}"],
        capture_output=True, text=True)
    try:
        items = json.loads(p2.stdout)
    except Exception:
        return out
    if isinstance(items, dict):
        items = items.get("items", [])

    cut = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    buckets = {}
    for it in items:
        q = it.get("query") or {}
        tgt = q.get("targetUrl") or (it.get("author") or {}).get("linkedinUrl") or ""
        slug = tgt.rstrip("/").split("/")[-1].lower()
        if not slug:
            continue
        pa = it.get("postedAt") or {}
        if isinstance(pa, str):
            pa = {"date": pa}
        raw = pa.get("date")
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
    for slug, b in buckets.items():
        n = b["n90"]
        b["status"] = "ACTIVE" if n >= 3 else ("SEMI_ACTIVE" if n >= 1 else "INACTIVE")
        b["latest_date"] = b["latest"].date().isoformat() if b["latest"] else ""
        for u in urls:
            if u.rstrip("/").split("/")[-1].lower() == slug:
                out[u] = b
    return out


if __name__ == "__main__":
    urls = [l.strip() for l in open("/tmp/act_urls.txt") if l.strip()]
    res = fetch_activity(urls)
    print(f"{'PROFILE':30} {'N90':>4} {'TOTAL':>6} {'LATEST':12} STATUS")
    print("-" * 72)
    for u in urls:
        r = res[u]
        print(f"{u.split('/')[-1][:30]:30} {r['n90']:>4} {r['total']:>6} "
              f"{r.get('latest_date','-'):12} {r['status']}")