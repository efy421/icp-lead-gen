#!/usr/bin/env python3
"""
verify_icp.py — THE ONLY SANCTIONED WAY TO QUALIFY ICP LEADS.

Reads a candidates CSV (pipe or comma separated, must have LinkedIn URL + Company),
verifies real headcount via Apify, detects AI-service vendors, dedupes against the
prior-URL blocklist, and writes a scored output.

USAGE:
    python3 verify_icp.py <input.csv> <output.csv> [--min-emp 5] [--max-emp 0]

    --min-emp 5    minimum employees (5 = "5+", the default band)
    --max-emp 0    maximum employees; 0 = no ceiling

WHY THIS EXISTS:
    Worker-claimed employee counts are unreliable. Measured on a 20-lead sample:
    6 of 8 resolvable leads had OVERSTATED headcount, and only 6 of 20 were
    actually inside the 5-10 band. Never trust a claimed count. Always run this.

APIFY KEYS: reads firstmate/apify_keys_pool.txt ONLY. It refuses to run if the
client (branding_pirates) key is referenced anywhere in the environment.
"""
import json, csv, re, sys, os, subprocess, itertools, argparse

HOME = os.path.expanduser("~")
BASE = f"{HOME}/firstmate"
POOL = f"{BASE}/apify_keys_pool.txt"
BLOCKLISTS = [f"{BASE}/PRIOR_SLUGS_v13.txt", f"{BASE}/PRIOR_NAMES_v13.txt"]
CLIENT_KEY_MARKER = "branding_pirates"

# ---------- guards ----------
if CLIENT_KEY_MARKER in json.dumps({k: v for k, v in os.environ.items()}):
    sys.exit("ABORT: a client (branding_pirates) Apify key is present in the "
             "environment. Refusing to run. Use firstmate/apify_keys_pool.txt.")

TOKS = [l.strip() for l in open(POOL) if l.strip()] if os.path.exists(POOL) else []
if not TOKS:
    sys.exit(f"ABORT: no free Apify keys found at {POOL}. Ask the user to add "
             "more free keys — never fall back to a client/paid key.")
_rot = itertools.cycle(TOKS)

# ---------- apify ----------
def run_actor(payload, wait=420):
    tok = next(_rot)
    url = (f"https://api.apify.com/v2/acts/harvestapi~linkedin-company/runs"
           f"?token={tok}&waitForFinish={wait}")
    p = subprocess.run(["curl", "-s", "-m", str(wait + 60), "-X", "POST", url,
                        "-H", "Content-Type: application/json",
                        "-d", json.dumps(payload)], capture_output=True, text=True)
    try:
        d = json.loads(p.stdout).get("data", {})
    except Exception:
        return []
    if d.get("status") != "SUCCEEDED":
        return []
    ds = d.get("defaultDatasetId")
    if not ds:
        return []
    p2 = subprocess.run(["curl", "-s", "-m", "60",
                         f"https://api.apify.com/v2/datasets/{ds}/items?token={tok}"],
                        capture_output=True, text=True)
    try:
        it = json.loads(p2.stdout)
    except Exception:
        return []
    return it if isinstance(it, list) else it.get("items", [])

def fetch_site(url):
    p = subprocess.run(["curl", "-sL", "-m", "20", "-A",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        url], capture_output=True, text=True, errors="ignore")
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", p.stdout, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", t)

# A business selling AI services is a COMPETITOR, not a lead. Hard exclusion.
AI = re.compile(r"ai[- ]powered|ai automation|ai agent|artificial intelligence|\bllm\b|"
                r"chatbot|machine learning|generative ai|ai consult|we build ai|"
                r"ai copilot|ai strategy|ai solutions|ai-driven|ai development", re.I)

def slug(u):
    m = re.search(r"linkedin\.com/in/([A-Za-z0-9_.%-]+)", u or "", re.I)
    return m.group(1).rstrip("/").lower() if m else None

def norm_company(c):
    """Apify returns cleaned names ('ConsumerDNA' for 'ConsumerDNA, LLC').
    Match on a normalised key, with a longest-prefix fallback, so
    punctuation/legal suffixes never break the lookup."""
    c = re.sub(r"[\.,]\s*(llc|inc|ltd|co|corp|llp|plc)\b", "", (c or "").lower())
    c = re.sub(r"[^a-z0-9]+", " ", c).strip()
    return " ".join(c.split())

def norm_name(n):
    n = re.sub(r"[^a-z ]", " ", (n or "").lower())
    n = re.sub(r"\b(jr|sr|ii|iii|md|cpa|mba)\b", "", n)
    return " ".join(sorted(n.split()))

def load_prior():
    S, N = set(), set()
    for f in BLOCKLISTS:
        if not os.path.exists(f):
            continue
        for line in open(f, encoding="utf-8"):
            v = line.strip().lower()
            if not v:
                continue
            (S if "/" in v or "-" in v else N).add(v)
    return S, N

def parse_row(line):
    if "|" in line:
        return [x.strip() for x in line.split("|")]
    return next(csv.reader([line]))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input"); ap.add_argument("output")
    ap.add_argument("--min-emp", type=int, default=5)
    ap.add_argument("--max-emp", type=int, default=0, help="0 = no ceiling")
    a = ap.parse_args()

    prior_s, prior_n = load_prior()
    prior_nn = {norm_name(x) for x in prior_n}; prior_nn.discard("")
    print(f"blocklist: {len(prior_s)} slugs / {len(prior_n)} names")

    rows, seen, seen_nn = [], set(), set()
    raw = open(a.input, encoding="utf-8", errors="ignore")
    for line in raw:
        line = line.strip()
        if not line or line.upper() == "DONE" or line.startswith("#"):
            continue
        if "linkedin.com/in/" not in line:
            continue
        p = parse_row(line)
        if len(p) < 4:
            continue
        s = slug(p[3])
        if not s:
            continue
        nm, k = p[0].strip().lower(), norm_name(p[0])
        if s in prior_s or nm in prior_n or (k and k in prior_nn) or s in seen or (k and k in seen_nn):
            continue
        seen.add(s); seen_nn.add(k)
        while len(p) < 10:
            p.append("")
        rows.append(dict(zip(["Name","Company","Title","LinkedIn URL","City","State",
                              "Employees","Niche","ICP_Score","Notes"], p[:10])))
    print(f"input: {len(rows)} deduped candidates")

    names = list({r["Company"].strip() for r in rows if r["Company"].strip()})
    print(f"resolving {len(names)} companies via Apify (name search — never guess slugs)...")
    found, B = {}, 8
    for i in range(0, len(names), B):
        for it in run_actor({"searches": names[i:i + B]}):
            nm = it.get("name") or ""
            found[nm.strip().lower()] = it
            found[norm_company(nm)] = it
    # longest-prefix fallback: worker wrote "ConsumerDNA, LLC", API returned "ConsumerDNA"
    def lookup(company):
        key = norm_company(company)
        if key in found:
            return found[key]
        cands = [k for k in found if k and (key.startswith(k) or k.startswith(key))]
        if cands:
            return found[max(cands, key=len)]
        return {}
    print(f"resolved {len(names) - sum(1 for n in names if not lookup(n))}/{len(names)}")

    out = []
    for r in rows:
        c = lookup(r["Company"])
        rng = c.get("employeeCountRange") or {}
        try:
            emp = int(c.get("employeeCount"))
        except Exception:
            emp = None
        r["emp_verified"] = emp if emp is not None else ""
        r["emp_range"] = f"{rng.get('start')}-{rng.get('end')}" if rng else ""
        r["company_followers"] = c.get("followerCount") or ""
        r["company_url"] = c.get("linkedinUrl") or ""
        r["founded"] = (c.get("foundedOn") or {}).get("year") or ""
        site = c.get("website") or ""
        ai = ""
        if site.startswith("http"):
            try:
                ai = "; ".join(sorted({m.group(0) for m in AI.finditer(fetch_site(site))})[:3])
            except Exception:
                ai = ""
        r["ai_vendor"] = ai
        keep = (emp is not None and emp >= a.min_emp
                and (a.max_emp == 0 or emp <= a.max_emp) and not ai)
        r["verified_pass"] = "PASS" if keep else "FAIL"
        out.append(r)

    cols = ["Name","Company","Title","LinkedIn URL","City","State","Employees","Niche",
            "ICP_Score","emp_verified","emp_range","company_followers","company_url",
            "founded","ai_vendor","verified_pass","Notes"]
    with open(a.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in out:
            w.writerow({c: r.get(c, "") for c in cols})

    p = [r for r in out if r["verified_pass"] == "PASS"]
    txt = os.path.splitext(a.output)[0] + "_linkedin.txt"
    with open(txt, "w", encoding="utf-8") as f:
        for r in p:
            f.write(r["LinkedIn URL"] + "\n")

    print(f"\n=== {len(p)}/{len(out)} PASS ({a.min_emp}+ employees, non-AI) ===")
    print(f"  resolved      : {sum(1 for r in out if r['emp_verified'] != '')}/{len(out)}")
    print(f"  AI vendors    : {sum(1 for r in out if r['ai_vendor'])} (excluded)")
    print(f"  wrote {a.output}\n  wrote {txt}")

if __name__ == "__main__":
    main()