#!/usr/bin/env python3
"""
floor_check.py — the 30-day follow-up floor, computed rather than estimated. Read-only.

Two rules in task-rules: *Follow-up guarantee* (no open new-business deal the user owns
goes 30 days without an outbound touch from us) and *Lead contact guarantee* (the same
for leads). Until this script the brief computed them in prose, from whatever the run
had in context, and when the ingest did not run the brief printed "floor not
recomputed" — for a month, in one live folder, while the real count went from 2 to 23.
A number that is cheap to produce gets produced; this makes it cheap.

Run it AFTER the day's activity ingest and `activity_sync.py --lead-touch`, because it
reads what those wrote. It also refuses to look authoritative on a stale cache: when the
newest event is older than activity_sync.STALE_DAYS it says so on its first line.

Deals in scope: owner is the folder's user (`owner:` in config.md); stage open, and not
excluded by the profile's own opportunity `default_filter` (a `StageName != 'X'` there
means X is not pipeline — Pursuit in one live org); not a renewal (type is the profile's
renewal marker, `Renewal` / `Existing Business`, or an id in 08-Renewals); not on hold.
Touch = the latest outbound event in the activity cache (email_out, meeting, call), and
opportunity-contacts.last_outbound_date where that registry exists. Whose touch counts
is `followup_deal_touch:` in config.md — `any` (default: anyone on our side, named) or
`own` (the user's own mailbox, calendar and CRM activity only).

Leads in scope: owner is the user; status not terminal, not partner-held and not Nurture
(a long-cycle pool — counted in the skip line, never silently dropped), or exactly the
statuses in `lead_floor_statuses:` when config.md names them; clock not paused (contactable
no, in an active sequence, hold_until in the future). Clock = last_outbound_date, which
--lead-touch writes, colleagues' touches included and named in last_outbound_by. Blank is
a breach ("no recorded touch"), per the rule.

Usage:
  floor_check.py <project> [--today YYYY-MM-DD] [--window 30] [--json] [--limit 25]

Writes .sales-system/cache/floor-latest.json (the run_integrity evidence that the floor
was computed this run). Exit 0 always, unless the registries cannot be read (1).
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT_KINDS = {"email_out", "meeting", "call"}
RENEWAL_TYPES = {"renewal", "existing business"}
YES = {"yes", "true", "1", "y"}


def D(v):
    s = str(v or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def excluded_stages(fm):
    flt = ((fm.get("objects") or {}).get("opportunities") or {}).get("default_filter") or ""
    out = set(re.findall(r"StageName\s*!=\s*'([^']+)'", flt, re.I))
    for grp in re.findall(r"StageName\s+NOT\s+IN\s*\(([^)]*)\)", flt, re.I):
        out.update(re.findall(r"'([^']+)'", grp))
    return {s.lower() for s in out}


def renewal_marker(root, fm):
    vals = set(RENEWAL_TYPES)
    for src in (fm.get("renewals") or {}, ((fm.get("objects") or {}).get("renewals") or {})):
        v = ((src.get("renewal_identification") or {}).get("type_value") or "")
        if v:
            vals.add(v.strip().lower())
    return vals


def compute(root, today=None, window=30, limit=25):
    import csvguard as G
    import activity_sync as A
    today = today or date.today()
    cut = today - timedelta(days=window)
    fm = G.load_field_map(root) or {}
    owner, _ = A.user_identity(root)
    if not owner:
        raise SystemExit("error: no `owner:` in 00-Config/config.md — the floor is about the "
                         "user's own book and cannot be computed without knowing who that is.")
    touch_mode = (A.config_value(root, "followup_deal_touch", "any") or "any").lower()
    cache = A.load_json(A.cache_paths(root)[0], {})
    st_newest = max((e.get("date", "") for v in cache.values() for e in v), default="")
    lc = A.load_json(A.lead_cache_path(root), {})
    st_newest = max([st_newest] + [e.get("date", "") for v in lc.values() for e in v])
    stale_age = (today - D(st_newest)).days if D(st_newest) else None

    # ---- deals
    i, rows = A._registry_rows(root, "07-Opportunities/opportunities.csv")
    if not i:
        raise SystemExit("error: no opportunity registry")
    g = lambda r, c: (r[i[c]] if c in i else "")
    skip_stages = excluded_stages(fm)
    renew = renewal_marker(root, fm)
    ri, rrows = A._registry_rows(root, "08-Renewals/renewals.csv")
    renewal_ids = {r[ri["renewal_opp_id"]] for r in rrows if "renewal_opp_id" in ri}
    ci, crows = A._registry_rows(root, "07-Opportunities/opportunity-contacts.csv")
    contact_touch = {}
    if "opportunity_id" in ci and "last_outbound_date" in ci:
        for r in crows:
            d = D(r[ci["last_outbound_date"]])
            if d:
                oid = r[ci["opportunity_id"]]
                contact_touch[oid] = max(contact_touch.get(oid, d), d)

    exempt = {"renewal": 0, "on hold": 0, "excluded stage": 0}
    deals, breaches = 0, []
    for r in rows:
        if g(r, "owner").strip() != owner:
            continue
        stage = g(r, "stage")
        if stage.startswith("Closed"):
            continue
        if stage.lower() in skip_stages:
            exempt["excluded stage"] += 1
            continue
        if g(r, "type").strip().lower() in renew or g(r, "id") in renewal_ids:
            exempt["renewal"] += 1
            continue
        if g(r, "on_hold").strip().lower() in YES:
            exempt["on hold"] += 1
            continue
        deals += 1
        last, by = None, ""
        for e in cache.get(g(r, "id"), []):
            if e.get("kind") not in OUT_KINDS:
                continue
            if touch_mode == "own" and e.get("by") and e.get("by") != owner:
                continue
            d = D(e.get("date"))
            if d and (last is None or d > last):
                last, by = d, (e.get("by") or "")
        ct = contact_touch.get(g(r, "id"))
        if ct and (last is None or ct > last):
            last, by = ct, ""
        if last is None or last < cut:
            try:
                amt = float(g(r, "amount") or 0)
            except ValueError:
                amt = 0.0
            breaches.append({"id": g(r, "id"), "account": g(r, "account_name"),
                             "stage": stage, "amount": amt, "currency": g(r, "currency"),
                             "last_touch": last.isoformat() if last else None,
                             "by": by, "days": (today - last).days if last else None,
                             "partner_worked": bool(g(r, "partner_id").strip())})
    # Oldest first (no recorded touch is oldest of all), then largest.
    breaches.sort(key=lambda b: (b["last_touch"] or "0000", -b["amount"]))

    # ---- leads
    i, rows = A._registry_rows(root, "06-Leads/leads.csv")
    g = lambda r, c: (r[i[c]] if c in i else "")
    lskip = {"not contactable": 0, "in sequence": 0, "on hold": 0, "partner-held": 0,
             "nurture": 0}
    explicit = [x.strip().lower() for x in
                A.config_value(root, "lead_floor_statuses", "").split(",") if x.strip()]
    leads, ok, lbreach = 0, 0, []
    for r in rows:
        if g(r, "owner").strip() != owner:
            continue
        status = g(r, "status").strip().lower()
        if explicit:
            # The folder says exactly which statuses the guarantee covers.
            if status not in explicit:
                continue
        else:
            if status in A.LEAD_TERMINAL:
                continue
            if "partner" in status:
                # Passed to a partner: someone else is writing to this person (lead-tracking,
                # "the clock pauses").
                lskip["partner-held"] += 1
                continue
            if status == "nurture":
                # A long-cycle pool by design, worked by marketing cadence rather than a rep's
                # 30-day clock. Counted, never silently dropped; `lead_floor_statuses:` puts
                # it back in for a folder that wants it.
                lskip["nurture"] += 1
                continue
        if g(r, "contactable").strip().lower() in ("no", "false", "0", "n"):
            lskip["not contactable"] += 1
            continue
        if g(r, "in_sequence").strip().lower() in YES or \
                g(r, "status").strip().lower() == "in sequence":
            lskip["in sequence"] += 1
            continue
        hu = D(g(r, "hold_until"))
        if hu and hu > today:
            lskip["on hold"] += 1
            continue
        leads += 1
        lo = D(g(r, "last_outbound_date"))
        if lo and lo >= cut:
            ok += 1
        else:
            lbreach.append({"id": g(r, "id"),
                            "name": f"{g(r, 'first_name')} {g(r, 'last_name')}".strip(),
                            "company": g(r, "company"),
                            "last_touch": lo.isoformat() if lo else None,
                            "by": g(r, "last_outbound_by"),
                            "days": (today - lo).days if lo else None})
    lbreach.sort(key=lambda b: b["last_touch"] or "0000")

    base = lambda k: A.config_value(root, k, "")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "today": today.isoformat(), "window_days": window, "owner": owner,
        "deal_touch_counts": touch_mode,
        "cache_newest_event": st_newest or None, "cache_age_days": stale_age,
        "cache_stale": stale_age is None or stale_age > A.STALE_DAYS,
        "deals": {"eligible": deals, "past_window": len(breaches),
                  "no_recorded_touch": sum(1 for b in breaches if not b["last_touch"]),
                  "exempt": exempt, "baseline": base("followup_backlog_at_enable"),
                  "baseline_date": base("followup_baseline"),
                  "breaches": breaches[:limit], "more": max(0, len(breaches) - limit)},
        "leads": {"eligible": leads, "past_window": len(lbreach), "within": ok,
                  "no_recorded_touch": sum(1 for b in lbreach if not b["last_touch"]),
                  "skipped": lskip, "baseline": base("lead_followup_backlog_at_enable"),
                  "baseline_date": base("lead_followup_baseline"),
                  "breaches": lbreach[:limit], "more": max(0, len(lbreach) - limit)},
    }


def summary_line(res):
    d, l = res["deals"], res["leads"]
    s = (f"floor: deals {d['past_window']} of {d['eligible']} past {res['window_days']} days"
         + (f" (baseline {d['baseline']} on {d['baseline_date']})" if d["baseline"] else "")
         + f"; leads {l['past_window']} of {l['eligible']}"
         + (f" (baseline {l['baseline']} on {l['baseline_date']})" if l["baseline"] else ""))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("today_pos", nargs="?", help=argparse.SUPPRESS)  # old positional form
    ap.add_argument("--today")
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.project)
    t = a.today or a.today_pos
    res = compute(root, date.fromisoformat(t) if t else None, a.window, a.limit)
    import activity_sync as A
    A.save_json(os.path.join(A.cache_dir(root), "floor-latest.json"), res)
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    if res["cache_stale"]:
        print(f"STALE CACHE: newest event {res['cache_newest_event'] or 'none'}"
              f" ({res['cache_age_days']} days). These counts are upper bounds until the "
              "ingest runs.")
    print(summary_line(res))
    d = res["deals"]
    ex = ", ".join(f"{v} {k}" for k, v in d["exempt"].items() if v)
    if ex:
        print(f"  exempt: {ex}")
    for b in d["breaches"]:
        print(f"  {b['id']} {b['account']} | {b['stage']} | {b['amount']:,.0f} {b['currency']} | "
              + (f"last {b['last_touch']} ({b['days']}d){' by ' + b['by'] if b['by'] else ''}"
                 if b["last_touch"] else "no recorded touch")
              + (" | PARTNER-WORKED: check partner domains before calling it quiet"
                 if b["partner_worked"] else ""))
    if d["more"]:
        print(f"  … {d['more']} more")
    l = res["leads"]
    sk = ", ".join(f"{v} {k}" for k, v in l["skipped"].items() if v)
    print(f"leads: {l['within']} within the window" + (f"; skipped {sk}" if sk else ""))
    for b in l["breaches"]:
        print(f"  {b['id']} {b['name']} | {b['company']} | "
              + (f"last {b['last_touch']} ({b['days']}d){' by ' + b['by'] if b['by'] else ''}"
                 if b["last_touch"] else "no recorded touch"))
    if l["more"]:
        print(f"  … {l['more']} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
