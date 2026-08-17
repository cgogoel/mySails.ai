#!/usr/bin/env python3
"""
engagement.py — score how engaged a deal actually is, and which way it's moving.

"Heating" and "Cooling" have to mean something specific or they become vibes with a
label. Two principles do most of the work here.

**Inbound outweighs outbound.** Outbound email measures how hard a rep is trying;
replies, meetings, and inbound mail measure whether the customer cares. A deal with
twelve outbound emails and no reply is not engaged — it's being chased. Weighting these
the same is the single most common way engagement scores mislead.

**Direction beats level.** A large deal ticking over steadily and a small one
accelerating look nothing alike on a raw activity count, but the second is the one to
pay attention to this week. The trend compares a recent window against the window
before it, so a deal that was busy last month and silent this week reads as Cooling
rather than Active.

Usage:
  engagement.py --score <project_root> [--window 14] [--apply]
  engagement.py --explain <project_root> --opp OPP-0031

--apply writes engagement_score, engagement_trend and the activity counts back to the
opportunity registry. Without it, nothing is written.

Activity is read from 03-Market-style CRM exports if present, otherwise from an
activity cache the brief skills maintain at .sales-system/cache/activity.json:

  {"OPP-0031": [{"date":"2026-08-05","kind":"meeting|email_in|email_out|note|
                  stage_change|quote","detail":"..."}]}
"""

import argparse
import json
import math
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _cache_file(root):
    """Per-machine cache via activity_sync; falls back to the old in-project path so
    existing setups keep working."""
    try:
        from activity_sync import cache_paths
        p, _ = cache_paths(root)
        if os.path.exists(p):
            return p
    except ImportError:
        pass
    legacy = os.path.join(root, ".sales-system", "cache", "activity.json")
    return legacy

# What each kind of activity is worth. The gap between email_in and email_out is the
# opinionated part and it's deliberate — see the module docstring.
WEIGHTS = {
    "meeting": 10.0,       # someone gave up time
    "email_in": 7.0,       # they replied. the strongest routine signal
    "reply": 7.0,
    "quote": 6.0,          # commercial motion
    "stage_change": 5.0,
    "note": 2.0,           # someone bothered to write it down
    "call": 4.0,
    "email_out": 1.5,      # effort, not interest
    "task": 1.0,
}

HALF_LIFE_DAYS = 7.0       # a touch is worth half as much a week later

# Deal types move on different clocks. A renewal that's quiet for three weeks is usually
# fine — the customer is using the product and nobody needs to talk. A new-business deal
# in the same state is dying. Scoring them identically makes every renewal look Cooling
# and trains people to ignore the column.
WINDOW_MULTIPLIER = {"renewal": 2.5, "existing business": 2.0, "expansion": 1.5}
COLD_AFTER = {"renewal": 75, "existing business": 60, "_default": 30}


def deal_profile(deal_type):
    t = (deal_type or "").strip().lower()
    return (WINDOW_MULTIPLIER.get(t, 1.0),
            COLD_AFTER.get(t, COLD_AFTER["_default"]))


def decay(days_ago):
    return 0.5 ** (max(0.0, days_ago) / HALF_LIFE_DAYS)


def window_score(events, end, days):
    """Recency-weighted score for the `days` ending at `end`."""
    start = end - timedelta(days=days)
    total = 0.0
    counts = {}
    for e in events:
        try:
            d = date.fromisoformat(e["date"][:10])
        except (ValueError, KeyError, TypeError):
            continue
        if not (start < d <= end):
            continue
        kind = (e.get("kind") or "task").lower()
        total += WEIGHTS.get(kind, 1.0) * decay((end - d).days)
        counts[kind] = counts.get(kind, 0) + 1
    return total, counts


def classify(cur, prior, counts, days_since_any, cold_after=30, quiet_ok=14):
    """Return (trend, score 0-100).

    Cold is decided by silence, not by arithmetic — a deal with no contact for a month
    is cold whatever last month's ratio says."""
    if days_since_any is None or days_since_any > cold_after:
        return "Cold", min(10, round(cur))

    # Raw score, compressed so a handful of good touches lands mid-range and
    # runaway activity can't dominate the ranking.
    score = round(100 * (1 - math.exp(-cur / 18.0)))

    inbound = counts.get("email_in", 0) + counts.get("reply", 0) + counts.get("meeting", 0)
    outbound_only = cur > 0 and inbound == 0

    if prior <= 0.5:
        # No prior baseline: new or newly revived. Call it on absolute activity.
        trend = "Heating" if (cur >= 12 and inbound) else ("Warm" if cur >= 5 else "Steady")
    else:
        ratio = cur / prior
        if ratio >= 1.4 and inbound:
            trend = "Heating"
        elif ratio <= 0.6:
            trend = "Cooling"
        elif cur >= 15 and inbound:
            trend = "Warm"
        else:
            trend = "Steady"

    # Chasing is not engagement. A deal where only we are talking cannot read as Heating.
    if outbound_only and trend in ("Heating", "Warm"):
        trend = "Steady"
    if days_since_any > quiet_ok and trend in ("Heating", "Warm"):
        trend = "Cooling"
    return trend, score


def score_all(activity, as_of=None, window=14, deal_types=None):
    """deal_types maps id -> the deal's type, so renewals get a longer window."""
    as_of = as_of or date.today()
    deal_types = deal_types or {}
    out = {}
    for key, events in activity.items():
        mult, cold_after = deal_profile(deal_types.get(key))
        w = int(round(window * mult))
        cur, counts = window_score(events, as_of, w)
        prior, _ = window_score(events, as_of - timedelta(days=w), w)
        dates = []
        for e in events:
            try:
                dates.append(date.fromisoformat(e["date"][:10]))
            except (ValueError, KeyError, TypeError):
                pass
        last = max(dates) if dates else None
        days_since = (as_of - last).days if last else None
        trend, score = classify(cur, prior, counts, days_since,
                                cold_after=cold_after,
                                quiet_ok=int(round(14 * mult)))
        inbound_dates = [
            date.fromisoformat(e["date"][:10]) for e in events
            if (e.get("kind") or "").lower() in ("email_in", "reply", "meeting")
            and e.get("date")
        ]
        out[key] = {
            "engagement_score": score,
            "engagement_trend": trend,
            "meetings_recent": counts.get("meeting", 0),
            "emails_in_recent": counts.get("email_in", 0) + counts.get("reply", 0),
            "emails_out_recent": counts.get("email_out", 0),
            "last_activity_date": last.isoformat() if last else "",
            "last_inbound_date": max(inbound_dates).isoformat() if inbound_dates else "",
            "_cur": round(cur, 1), "_prior": round(prior, 1),
            "_days_since": days_since, "_window": w, "_type": deal_types.get(key, ""),
        }
    return out


def _warn_if_stale_cache(root):
    """A cache written before the email-direction fix is not merely old, it is wrong: any
    day with traffic both ways kept one event and dropped the other, and in practice the
    one dropped was the reply. Scoring it produces confident, plausible, too-cold numbers.
    Say so rather than letting the column look normal."""
    try:
        from activity_sync import CACHE_FORMAT, cache_paths, load_json
    except ImportError:
        return
    _, meta_p = cache_paths(root)
    meta = load_json(meta_p, {})
    if meta and meta.get("cache_format", 1) < CACHE_FORMAT:
        print("WARNING: the activity cache predates the fix for dropped inbound email. "
              "Replies that landed on the same day as an outbound message were discarded, "
              "so emails_in_recent is understated and trends read colder than reality. "
              "Run:  activity_sync.py --rebuild <project>  then re-ingest a full history "
              "window before trusting these scores.", file=sys.stderr)


def load_activity(root):
    p = _cache_file(root)
    if not os.path.exists(p):
        return {}
    _warn_if_stale_cache(root)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"warning: couldn't read activity cache ({e})", file=sys.stderr)
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score")
    ap.add_argument("--explain")
    ap.add_argument("--opp")
    ap.add_argument("--window", type=int, default=14)
    ap.add_argument("--as-of")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.score or a.explain or ".")
    as_of = date.fromisoformat(a.as_of) if a.as_of else date.today()

    deal_types = {}
    try:
        import csvguard as G
        op = G.resolve_path(os.path.join(root, "07-Opportunities/opportunities.csv"), root)
        sch, _ = G.schema_for_file(op, root)
        if sch and os.path.exists(op):
            h, rows = G.read_table(op, sch)
            i = {n: k for k, n in enumerate(h)}
            if "type" in i:
                deal_types = {r[i["id"]]: r[i["type"]] for r in rows}
    except Exception:
        pass

    activity = load_activity(root)
    if not activity:
        print("No activity cache. Run the brief or forecast skill first — it ingests "
              "CRM activity, email and calendar via activity_sync.py before scoring.")
        return 1
    scored = score_all(activity, as_of, a.window, deal_types)

    if a.explain:
        k = a.opp
        if k not in scored:
            print(f"no activity recorded for {k}", file=sys.stderr)
            return 1
        s = scored[k]
        print(f"{k}: {s['engagement_trend']} (score {s['engagement_score']})")
        print(f"  window score {s['_cur']} vs prior window {s['_prior']}")
        print(f"  meetings {s['meetings_recent']} · replies in {s['emails_in_recent']} "
              f"· sent {s['emails_out_recent']}")
        print(f"  last activity {s['last_activity_date'] or 'never'} "
              f"({s['_days_since']} days ago)" if s["_days_since"] is not None else "")
        for e in sorted(activity[k], key=lambda x: x.get("date", ""), reverse=True)[:8]:
            print(f"    {e.get('date','')}  {e.get('kind',''):<13} {e.get('detail','')[:56]}")
        return 0

    order = {"Heating": 0, "Warm": 1, "Steady": 2, "Cooling": 3, "Cold": 4}
    print(f"{'deal':12} {'trend':<9} {'score':>5} {'mtg':>4} {'in':>3} {'out':>4} {'win':>4}  last")
    for k, s in sorted(scored.items(),
                       key=lambda kv: (order[kv[1]["engagement_trend"]],
                                       -kv[1]["engagement_score"])):
        print(f"{k:12} {s['engagement_trend']:<9} {s['engagement_score']:>5} "
              f"{s['meetings_recent']:>4} {s['emails_in_recent']:>3} "
              f"{s['emails_out_recent']:>4} {s['_window']:>3}d  {s['last_activity_date'] or '—'}")

    if a.apply:
        import csvguard as G
        p = G.resolve_path(os.path.join(root, "07-Opportunities/opportunities.csv"), root)
        s, _ = G.schema_for_file(p, root)
        if not s or not os.path.exists(p):
            print("\nno opportunity registry to write to", file=sys.stderr)
            return 1
        header, rows = G.read_table(p, s)
        i = {n: k for k, n in enumerate(header)}
        fields = ["engagement_score", "engagement_trend", "meetings_recent",
                  "emails_in_recent", "emails_out_recent", "last_inbound_date"]
        n = 0
        for row in rows:
            v = scored.get(row[i["id"]])
            if not v:
                continue
            for f in fields:
                if f in i:
                    row[i[f]] = str(v[f])
            n += 1
        G.write_table(p, header, rows, schema=s, root=root, backup=True)
        print(f"\nwrote engagement to {n} opportunit{'y' if n == 1 else 'ies'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
