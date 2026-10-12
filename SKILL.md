---
name: icp-lead-gen
description: Use when the user asks for ICP leads, a lead list, agency-founder contacts, prospect sourcing, or "get me N leads" for 8085.ai or any lead-gen task — covers employee-count verification, duplicate removal, and AI-vendor exclusion. Triggers on "ICP list", "get me leads", "find leads", "lead generation", "8085 ICP", "agency founders", "prospect list", "more leads".
---

# ICP Lead Generation (verified, no hallucination)

This skill exists because **unverified lead lists are worse than no list**.
Measured on a 20-lead sample: 6 of 8 resolvable leads had **overstated**
headcount, and only 6 of 20 were actually inside the requested band. Lead lists
that "look right" but were never machine-verified are the main failure mode this
prevents.

## The one rule that matters

**Never deliver an employee count, founder title, or ICP score that came from a
worker, a search snippet, or your own inference. Every lead must be run through
`verify_icp.py`, which checks real LinkedIn data via Apify.**

If verification wasn't run, say so explicitly in the deliverable. Never present
worker-claimed data as verified.

## Workflow

### Step 1 — Confirm the band before researching
Ask (or read from prior context) the employee band. Historical note: 8085.ai
moved from "exactly 5-10" to **"5+ employees, no ceiling"** on 2026-10-12,
because strict 5-10 yielded only ~7% of researched leads while 5+ yielded ~40%.
Default to 5+ if unclear. Do not silently pick a band.

### Step 2 — Research candidates
Use `Task` subagents or `herdr` pane workers for volume. Each worker prompt MUST
include all of these, or the batch fails:
- **Never write to `/tmp`.** Use `/home/irfan/firstmate/scratch/`. A `/tmp`
  write triggers a permission dialog that blocks the TUI and hangs the worker
  permanently — this has killed batches.
- **Record the real LinkedIn `/company/<slug>` URL** in each lead's Notes
  (`company_url = ...`). Never let anyone guess a slug.
- **Write output every 10 leads**, not once at the end. Partial files survive a
  wedge; a single end-of-task write does not.
- Dedupe every candidate against the current blocklist files.

Worker output schema (pipe-separated), one row per lead:
```
Name | Company | Title | LinkedIn URL | City | State | Employees | Niche | ICP_Score | Notes
```
End the worker file with a line containing exactly `DONE`.

### Step 3 — Verify (mandatory, never skip)
```bash
python3 ~/.config/opencode/skills/icp-lead-gen/scripts/verify_icp.py \
    <candidates.csv> <output.csv> --min-emp 5
```
This resolves real headcount via Apify, detects AI-service vendors, dedupes,
and writes both a scored CSV and a `_linkededin.txt` of passing URLs.
Re-running is cheap (~$0.02 per 8 companies).

### Step 4 — Report honestly
State, without spin:
- how many candidates were researched
- how many were verified PASS vs FAIL
- the actual employee distribution
- any unresolved companies (Apify could not resolve them)

**Never pad a short result to hit a number.** If only 6 of 20 pass, deliver 6
and say the hit rate is 30%. Delivering 20 where 14 are unverified is exactly
the failure this skill exists to stop.

## What verify_icp.py enforces

| Check | Method | Why |
|---|---|---|
| Headcount | Apify `harvestapi~linkedin-company` | worker claims were 75% wrong |
| Company resolution | actor's `searches` field (by NAME) | 81% match; guessing slugs only 40% |
| AI-vendor exclusion | curl the site, regex for AI-service language | competitors, not leads |
| Duplicate removal | globs **every** `PRIOR_SLUGS_v*.txt` / `PRIOR_NAMES_v*.txt` (v11..v14+), slug AND normalized name | batches are versioned, so a hardcoded filename silently dedupes against a stale list. Name-matching caught real dupes that slug-matching missed |
| Key safety | aborts if a client key is in env; reads only `apify_keys_pool.txt` | client key cost $0.056 once |

## Apify accounts — HARD RULE

**NEVER use `/home/irfan/branding_pirates_2lead_test/.apify_token`.** That is
the **client's paid STARTER account**. It is `chmod 000` so reads fail loudly.

**Only** `~/firstmate/apify_keys_pool.txt` — four FREE accounts, one per line,
round-robined by the script. If they run low, **ask the user for more free
keys**; never fall back to the client key. Current pool spends ~$0.57 of $20
monthly capacity, so topping up is rarely needed.

## Known data caveats

- **`employeeCount` from LinkedIn is indexed profiles, not payroll headcount.**
  It under-reports. A company showing `employeeCountRange: 2-10` with 6 indexed
  is reliable; one showing `11-50` with 6 indexed may really be 11+. Report the
  range alongside the count.
- **Company followers** is the "less-known" proxy. Under ~1,500 = genuinely
  boutique. Report the count so the user can filter.
- **Unresolved companies** (Apify found no page) are NOT passes. Keep them in a
  separate "unverified" bucket, never mixed into a verified deliverable.
- **Company names come back cleaned** (`ConsumerDNA`, not `ConsumerDNA, LLC`), so
  exact-match lookups fail. The script strips legal suffixes and falls back to a
  longest-prefix match — do not "simplify" that back to exact match.
- **Deliverable naming convention**: `fresh_8085_icp_v<N>.csv` paired with
  `fresh_8085_v<N>_linkedin.txt`, N incrementing per batch. These two filenames are
  also how dedupe discovers them, so renaming breaks future duplicate protection.

## Historical note — which batches are actually trustworthy

| Batch | Headcount source | Usable? |
|---|---|---|
| v10, v11, v12 | worker-claimed | **No.** Unverified. Apify later showed 6 of 8 resolvable leads overstated; 36 of 55 were actually under 5 employees. Treat as research candidates only. |
| v13 | worker-claimed | **No.** Same problem — of 55 resolvable, only 6 were in the 5-10 band. |
| v14 | Apify `employeeCount` | **Yes.** First batch where every lead passed machine verification. |

## Anti-hallucination checklist before delivering

- [ ] Every delivered lead went through `verify_icp.py`
- [ ] Zero leads with `ai_vendor` non-empty
- [ ] Zero duplicates vs blocklist (slug AND normalized name)
- [ ] Actual pass count and hit rate stated plainly
- [ ] Employee counts came from Apify, not from workers or snippets
- [ ] Any unresolved leads quarantined and labelled
- [ ] If fewer than requested passed, said so — no padding