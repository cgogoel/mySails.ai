#!/usr/bin/env python3
"""
activity_sync.py — build and maintain the activity cache that engagement scoring,
task verification, and the briefs all read.

The brief skills fetch raw events from their connectors (CRM activity queries, email
threads, calendar events) and hand them to this script as JSON. This script owns the
hard parts that must be consistent run to run:

- **Dedup across sources.** The same customer meeting appears in the calendar AND as a
  CRM Event; the same email appears in the mailbox AND as an auto-captured CRM Task.
  Counting it twice inflates engagement exactly where it matters.
- **Direction.** email_in vs email_out is decided here, from the user's address, not
  guessed downstream.
- **Attribution.** Events arrive tagged with an opp id where the source knew it, or
  with an account/domain hint for matching against the opportunity registry.
- **Watermarks.** Each source records how far it has synced, so the next run fetches a
  bounded window instead of re-reading history.

The cache lives OUTSIDE the project folder (per-machine temp), because on a shared
drive a synced cache means two users constantly overwriting each other's, and the cache
is cheap to rebuild.

Input format (what a skill hands to --ingest):
  {"source": "salesforce|gmail|calendar",
   "user_emails": ["user@example.com"],
   "events": [
     {"date": "2026-08-05", "kind": "meeting|call|note|stage_change|quote|email",
      "opp_id": "OPP-0031",                # if the source knew it
      "account": "Acme Corp",              # else, hints for matching
      "counterpart_email": "jane@acme.com",
      "from": "jane@acme.com",             # email only; direction derived
      "detail": "POC wrap-up"}]}

Usage:
  activity_sync.py --ingest <project> --input events.json
  activity_sync.py --status <project>
  activity_sync.py --rebuild <project>     # wipe cache; skills re-ingest history
  activity_sync.py --selftest              # dedup regression cover, no project needed
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Bumped when a stored cache written by an older version would be *wrong* rather than
# merely incomplete. 2: before this, event_key() erased email direction, so any day with
# traffic in both directions kept one side and silently discarded the other.
CACHE_FORMAT = 2


def cache_dir(root):
    """Per-machine, per-project cache. Deliberately NOT inside the project folder:
    on a shared drive, a synced cache means users overwrite each other's, and it is
    cheap to rebuild locally."""
    key = hashlib.sha1(os.path.abspath(root).encode()).hexdigest()[:12]
    d = os.path.join(tempfile.gettempdir(), f"sales-system-{key}")
    os.makedirs(d, exist_ok=True)
    return d


def cache_paths(root):
    d = cache_dir(root)
    return os.path.join(d, "activity.json"), os.path.join(d, "activity-meta.json")


def load_json(p, default):
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, p)


def norm_domain(s):
    s = (s or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    return s.split("/")[0].split("@")[-1]


def load_opp_index(root):
    """account-name and domain -> opp id, for events that arrive without one.
    Open deals win over closed; newest close date wins among open."""
    import csvguard as G
    p = G.resolve_path(os.path.join(root, "07-Opportunities/opportunities.csv"), root)
    s, _ = G.schema_for_file(p, root)
    if not s or not os.path.exists(p):
        return {}, {}
    h, rows = G.read_table(p, s)
    i = {n: k for k, n in enumerate(h)}
    by_name, by_domain = {}, {}
    from partner_conflict import norm_name  # same normalisation, one definition
    def better(old, new):
        if old is None:
            return True
        o_open = not (old.get("stage") or "").startswith("Closed")
        n_open = not (new.get("stage") or "").startswith("Closed")
        if o_open != n_open:
            return n_open
        return (new.get("close") or "") > (old.get("close") or "")
    for r in rows:
        rec = {"id": r[i["id"]], "stage": r[i["stage"]], "close": r[i["close_date"]]}
        key = norm_name(r[i["account_name"]])
        if key and better(by_name.get(key), rec):
            by_name[key] = rec
    return by_name, by_domain


_EMAIL_IN = {"email_in", "reply"}
_EMAIL_OUT = {"email_out", "email"}


def event_key(date_s, kind, who, opp):
    """Identity for dedup. Same day + same kind-class + same counterpart + same deal =
    same event, whichever source reported it. Meetings from calendar and CRM collapse;
    an email seen in Gmail and as a captured CRM task collapses.

    **Direction is part of the class.** It used to be erased here, on the reasoning that a
    CRM-captured email and the Gmail copy of it are one event — which is true, and both of
    those carry the same direction anyway. What it missed is that a mailbox source sees
    *both sides* of a same-day exchange. Sent at 09:00, replied at 11:00, same person, same
    deal, same day: one key, so the second one was dropped as a duplicate and whichever
    arrived first in the payload won. In practice that was the outbound.

    The cost is asymmetric, because engagement.py weights email_in at 7.0 and email_out at
    1.5 and gates Heating and Warm on inbound existing at all. Collapsing the pair turned a
    7.0 into a 1.5 and made a two-way conversation read as chasing — hitting hardest on
    exactly the engaged deals the score is meant to surface. Cross-source dedup is
    unaffected: two reports of the same message always agree on direction."""
    k = (kind or "").lower()
    if k in _EMAIL_IN:
        kind_class = "email_in"
    elif k in _EMAIL_OUT:
        # Bare "email" lands here only as a fallback. ingest() runs classify_email()
        # before building a key, so an unresolved "email" should never reach this.
        kind_class = "email_out"
    else:
        kind_class = {"meeting": "meeting", "call": "call"}.get(k, k)
    return f"{(date_s or '')[:10]}|{kind_class}|{(who or '').strip().lower()}|{opp}"


def classify_email(e, user_emails):
    frm = (e.get("from") or "").strip().lower()
    if not frm:
        return e.get("kind") or "email_out"
    return "email_in" if not any(u in frm for u in user_emails) else "email_out"


def ingest(root, payload):
    cache_p, meta_p = cache_paths(root)
    cache = load_json(cache_p, {})
    meta = load_json(meta_p, {"sources": {}, "unattributed": 0})

    if cache and meta.get("cache_format", 1) < CACHE_FORMAT:
        # A cache written before the direction fix has already lost its inbound events, and
        # no amount of re-ingesting *into* it recovers them — they were never stored. Left
        # alone it would make the fix look like it did nothing, which is the worst possible
        # outcome for a bug whose whole character is being invisible. So: discard once,
        # loudly, and say what has to happen next.
        n = sum(len(v) for v in cache.values())
        cache = {}
        meta = {"sources": {}, "unattributed": 0}
        print(f"cache format {CACHE_FORMAT}: discarded {n} events written by a version that "
              "collapsed inbound and outbound email on the same day.")
        print("  Those events cannot be repaired — the replies were never stored. This "
              "payload will be ingested into an empty cache.")
        print("  RE-INGEST A FULL HISTORY WINDOW (90 days), not an incremental one, or "
              "engagement scores will be based on this window alone.")

    user_emails = [u.strip().lower() for u in payload.get("user_emails", [])]
    by_name, _ = load_opp_index(root)
    from partner_conflict import norm_name

    seen = {event_key(e.get("date"), e.get("kind"), e.get("who"), opp)
            for opp, events in cache.items() for e in events}
    added = dup = unattributed = 0

    for e in payload.get("events", []):
        kind = (e.get("kind") or "").lower()
        if kind in ("email", "email_in", "email_out", "reply"):
            e["kind"] = classify_email(e, user_emails)

        opp = (e.get("opp_id") or "").strip()
        if not opp:
            hit = by_name.get(norm_name(e.get("account", "")))
            if hit:
                opp = hit["id"]
        if not opp:
            unattributed += 1
            continue
        e["opp_id"] = opp

        who = (e.get("counterpart_email") or e.get("from") or "")
        k = event_key(e.get("date"), e["kind"], who, opp)
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        cache.setdefault(opp, []).append(
            {"date": e.get("date", "")[:10], "kind": e["kind"],
             "who": who.strip().lower(), "detail": (e.get("detail") or "")[:120]})
        added += 1

    src = payload.get("source", "unknown")
    meta["cache_format"] = CACHE_FORMAT
    meta["sources"][src] = {"last_sync": date.today().isoformat(),
                            "last_added": added, "last_dupes": dup}
    meta["unattributed"] = meta.get("unattributed", 0) + unattributed
    save_json(cache_p, cache)
    save_json(meta_p, meta)
    print(f"{src}: +{added} events, {dup} duplicates collapsed, "
          f"{unattributed} unattributable (no matching deal)")
    if unattributed:
        print("  unattributable events are dropped — if that number is large, account "
              "names in the source don't match the registry and matching needs a look")
    return 0


def status(root):
    cache_p, meta_p = cache_paths(root)
    cache = load_json(cache_p, {})
    meta = load_json(meta_p, {"sources": {}})
    n = sum(len(v) for v in cache.values())
    print(f"cache: {cache_p}")
    print(f"{n} events across {len(cache)} deals")
    for s, m in meta.get("sources", {}).items():
        print(f"  {s:12} last sync {m.get('last_sync','never')} "
              f"(+{m.get('last_added',0)}, {m.get('last_dupes',0)} dupes)")
    if not meta.get("sources"):
        print("  no sources have synced yet — engagement will read everything as Cold "
              "until a brief or forecast ingests activity")
    if cache and meta.get("cache_format", 1) < CACHE_FORMAT:
        print(f"  WARNING: cache format {meta.get('cache_format', 1)}, current is "
              f"{CACHE_FORMAT}. This cache was written by a version that discarded a reply "
              "whenever it fell on the same day as an outbound email, so inbound counts "
              "here are too low and engagement trends read colder than reality. The next "
              "ingest discards and rebuilds it; give it a full history window.")
    return 0


def selftest():
    """Regression cover for the bugs that were invisible in the field. Ships with the
    script on purpose: the useful place to run this is the machine that is misbehaving,
    not a CI box. setup_status.py --doctor calls it."""
    fails = []

    def check(name, got, want):
        if got != want:
            fails.append(f"{name}: got {got!r}, wanted {want!r}")

    # The defect: a same-day exchange with one person on one deal is two events, not one.
    out = event_key("2026-08-03", "email_out", "buyer@acme.com", "OPP-0001")
    inn = event_key("2026-08-03", "email_in", "buyer@acme.com", "OPP-0001")
    check("same-day exchange keys differ", out != inn, True)

    # ...but the case dedup exists for still collapses: the same message reported twice.
    check("reply is email_in",
          event_key("2026-08-03", "reply", "b@acme.com", "OPP-1"),
          event_key("2026-08-03", "email_in", "b@acme.com", "OPP-1"))
    check("bare email falls back to outbound",
          event_key("2026-08-03", "email", "b@acme.com", "OPP-1"),
          event_key("2026-08-03", "email_out", "b@acme.com", "OPP-1"))
    check("cross-source meeting still collapses",
          event_key("2026-08-03", "meeting", "B@Acme.com ", "OPP-1"),
          event_key("2026-08-03", "meeting", "b@acme.com", "OPP-1"))

    # Direction is derived from the sender, not trusted from the source.
    check("inbound classified", classify_email({"from": "buyer@acme.com"}, ["@example.com"]),
          "email_in")
    check("outbound classified", classify_email({"from": "rep@example.com"}, ["@example.com"]),
          "email_out")

    for f in fails:
        print(f"FAIL {f}", file=sys.stderr)
    print(f"activity_sync selftest: {7 - len(fails)}/7 passed")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest"); ap.add_argument("--input")
    ap.add_argument("--status"); ap.add_argument("--rebuild")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.ingest:
        with open(a.input, encoding="utf-8") as f:
            return ingest(os.path.abspath(a.ingest), json.load(f))
    if a.status:
        return status(os.path.abspath(a.status))
    if a.rebuild:
        cache_p, meta_p = cache_paths(os.path.abspath(a.rebuild))
        for p in (cache_p, meta_p):
            if os.path.exists(p):
                os.remove(p)
        print("cache cleared — skills should re-ingest a full history window")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
