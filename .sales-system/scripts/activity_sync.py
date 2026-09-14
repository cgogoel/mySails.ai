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
  with an account/domain hint for matching against the opportunity registry. An event
  that matches no deal is then tried against the lead registry by the counterpart's
  email address, and lands in a separate lead cache — separate because engagement.py
  scores every key of the deal cache, and a lead is not a deal. CRM activity arrives
  tagged with the CRM's own record ids (`opp_crm_id` — WhatId, `lead_crm_id` — WhoId
  in Salesforce terms) and is resolved through the registries' `crm_id` column here,
  so the fetch never has to build that mapping itself.
- **Watermarks.** Each source records how far it has synced, so the next run fetches a
  bounded window instead of re-reading history.
- **The CRM read is prescribed, not improvised.** `--plan` prints the activity query
  for the window — every activity linked to an open deal OR to a lead the user owns,
  bounded the way the profile says — because for its first month the CRM source was
  never ingested at all: the mail read was prescribed, the CRM read said "per the
  profile", and a fetch nobody spelled out is a fetch nobody ran. Leads paid most: a
  colleague's logged calls and cadence sends exist only as CRM activity, so every
  handed-over lead read as never touched.
- **What the folder knows and the CRM does not.** `--log` records one event the user
  reported — a call, a meeting off the calendar, a note — against a LEAD or an OPP,
  through the same dedup, so the clocks move on the user's own word and not only on
  what a connector happened to see. Whether that event is also logged to the CRM is a
  skill's offer and the user's yes (CONVENTIONS §7); `--log` records the CRM activity
  id when there is one so a later ingest recognises its own copy.

The cache lives INSIDE the project folder, at .sales-system/cache/. It used to live in
the machine's temp directory, to keep a shared drive from syncing two users' caches
over each other — and that reasoning was sound until the scripts started running in
sandboxes whose temp directory is created per session and discarded after it. Every
scheduled brief then began from an empty cache, read every deal and lead as never
touched, and drafted nothing. A cache that does not survive the night is not a cache.

Inside the folder it persists, and the shared-drive case is handled by the shape of
the data rather than by hiding it: ingest merges into what is there and dedups by
event identity, so two users' ingests produce the union of their evidence — which,
on a team folder, is the right answer — and writes are atomic replaces. A cache that
was left in temp by an older version is migrated in on first use.

Input format (what a skill hands to --ingest):
  {"source": "crm|gmail|calendar",         # "crm" for the CRM activity read, whatever the vendor
   "user_emails": ["user@example.com"],
   "events": [
     {"date": "2026-08-05", "kind": "meeting|call|note|stage_change|quote|email",
      "opp_id": "OPP-0031",                # if the source knew the local id
      "lead_id": "LEAD-0107",              # or this, if it knew the lead
      "opp_crm_id": "006...",              # CRM activity: the deal's CRM id (WhatId)
      "lead_crm_id": "00Q...",             # CRM activity: the lead's CRM id (WhoId)
      "account": "Acme Corp",              # else, hints for matching
      "counterpart_email": "jane@acme.com",
      "from": "jane@acme.com",             # email only; direction derived
      "direction": "in|out",               # email only; where the CRM records it explicitly
      "by": "Cortney Lee",                 # who on our side did it, where the source says
      "crm_id": "00T...",                  # the CRM's id for this activity, where it has one
      "detail": "POC wrap-up"}]}

  An email whose direction cannot be established — no `from`, no `direction` — is kept
  as kind `email`: it counts for engagement and dedups against a mailbox copy, but it
  moves neither clock, because a guess at direction is worse than a blank.

Usage:
  activity_sync.py --plan <project> [--since YYYY-MM-DD]   # the CRM activity read for the window
  activity_sync.py --ingest <project> --input events.json
  activity_sync.py --log <project> --record LEAD-0107|OPP-0031 --kind call|meeting|note|email_out|email_in
                   --date YYYY-MM-DD [--who addr] [--by name] [--detail text] [--crm-activity-id id]
  activity_sync.py --status <project>
  activity_sync.py --lead-touch <project>  # write last_outbound/inbound_date (+ _by) onto leads
  activity_sync.py --status <project> --json   # machine-readable: sources, counts, needs_full_window
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


def _legacy_cache_dir(root):
    """Where versions before 2026-09-04 kept the cache: the machine's temp directory,
    keyed by project path. Read once for migration, never written."""
    key = hashlib.sha1(os.path.abspath(root).encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"sales-system-{key}")


def cache_dir(root):
    """The project's own cache directory. In the folder, so it survives the session —
    see the module docstring for why it moved. Migrates a temp-directory cache from an
    older version the first time it is asked for, so nothing already ingested is lost."""
    d = os.path.join(root, ".sales-system", "cache")
    os.makedirs(d, exist_ok=True)
    legacy = _legacy_cache_dir(root)
    if os.path.isdir(legacy):
        for fn in ("activity.json", "activity-meta.json", "activity-leads.json"):
            src, dst = os.path.join(legacy, fn), os.path.join(d, fn)
            if os.path.exists(src) and not os.path.exists(dst):
                try:
                    import shutil
                    shutil.copyfile(src, dst)
                    print(f"migrated {fn} from the temp-directory cache into the project")
                except OSError:
                    pass
    return d


def cache_paths(root):
    d = cache_dir(root)
    return os.path.join(d, "activity.json"), os.path.join(d, "activity-meta.json")


def lead_cache_path(root):
    """Lead events live beside the deal cache, not inside it. engagement.py scores and
    prints every key of activity.json and --apply writes them onto the opportunity
    registry; a LEAD key in there would be scored as a deal and reported as one."""
    return os.path.join(cache_dir(root), "activity-leads.json")


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


LEAD_TERMINAL = {"disqualified", "do not contact", "junk", "qualified",
                 "customer or partner"}


def load_lead_index(root):
    """email -> lead id. Leads are matched on the person's address, never on the
    company: a lead is one person, and two leads at one company are two clocks. Where
    one address appears on several rows, a lead still being worked wins over one that
    has ended; among those, the newest wins."""
    try:
        import csvguard as G
        p = G.resolve_path(os.path.join(root, "06-Leads/leads.csv"), root)
        s, _ = G.schema_for_file(p, root)
        if not s or not os.path.exists(p):
            return {}
        h, rows = G.read_table(p, s)
    except Exception:
        return {}
    i = {n: k for k, n in enumerate(h)}
    if "email" not in i or "id" not in i:
        return {}
    out = {}
    for r in rows:
        em = (r[i["email"]] or "").strip().lower()
        if not em:
            continue
        rec = {"id": r[i["id"]],
               "open": (r[i["status"]] if "status" in i else "").strip().lower()
               not in LEAD_TERMINAL,
               "created": r[i["created_date"]] if "created_date" in i else ""}
        old = out.get(em)
        if old is None or (rec["open"] and not old["open"]) or \
                (rec["open"] == old["open"] and rec["created"] > old["created"]):
            out[em] = rec
    return {em: rec["id"] for em, rec in out.items()}


def _lead_registry_exists(root):
    try:
        import csvguard as G
        p = G.resolve_path(os.path.join(root, "06-Leads/leads.csv"), root)
        return os.path.exists(p)
    except Exception:
        return False


def _registry_rows(root, rel):
    """(header-index, rows) for a registry, or ({}, []) when it isn't there."""
    try:
        import csvguard as G
        p = G.resolve_path(os.path.join(root, rel), root)
        s, _ = G.schema_for_file(p, root)
        if not s or not os.path.exists(p):
            return {}, []
        h, rows = G.read_table(p, s)
        return {n: k for k, n in enumerate(h)}, rows
    except Exception:
        return {}, []


def load_crm_maps(root):
    """CRM record id -> local id, for both registries, plus lead id -> the person's
    address. CRM activity arrives linked to records by the CRM's own ids, and the fetch
    should not have to know that OPP-0031 is 006Xx000001abcd — the registry knows.

    Ids are compared through csvguard.crm_key, so where the CRM has two forms of one id
    (Salesforce's 15 and 18 characters) either form matches. Where two local rows carry
    the same CRM id — a re-imported lead, a duplicated deal — the open one wins, then the
    newest, the same way the email index chooses."""
    import csvguard as G
    G.set_dialect(root)
    opp_by_crm, lead_by_crm, lead_email = {}, {}, {}
    i, rows = _registry_rows(root, "07-Opportunities/opportunities.csv")
    if "crm_id" in i and "id" in i:
        for r in rows:
            k = G.crm_key(r[i["crm_id"]])
            if not k:
                continue
            is_open = not (r[i["stage"]] if "stage" in i else "").startswith("Closed")
            old = opp_by_crm.get(k)
            if old is None or (is_open and not old[1]):
                opp_by_crm[k] = (r[i["id"]], is_open)
    i, rows = _registry_rows(root, "06-Leads/leads.csv")
    if "crm_id" in i and "id" in i:
        for r in rows:
            lead_email[r[i["id"]]] = (r[i["email"]] if "email" in i else "").strip().lower()
            k = G.crm_key(r[i["crm_id"]])
            if not k:
                continue
            is_open = (r[i["status"]] if "status" in i else "").strip().lower() \
                not in LEAD_TERMINAL
            created = r[i["created_date"]] if "created_date" in i else ""
            old = lead_by_crm.get(k)
            if old is None or (is_open and not old[1]) or \
                    (is_open == old[1] and created > old[2]):
                lead_by_crm[k] = (r[i["id"]], is_open, created)
    return ({k: v[0] for k, v in opp_by_crm.items()},
            {k: v[0] for k, v in lead_by_crm.items()}, lead_email)


def attribute(e, by_name, lead_by_email, norm_name, opp_by_crm=None, lead_by_crm=None,
              crm_key=None):
    """Which record an event belongs to: ("opp", id), ("lead", id) or (None, None).
    Deals win — a converted lead's traffic belongs to the deal it became. A CRM id on
    the event (`opp_crm_id` / `lead_crm_id`) resolves through the registries; it ranks
    with the local id of the same kind, above the name and address hints."""
    ck = crm_key or (lambda s: (s or "").strip())
    opp = (e.get("opp_id") or "").strip()
    if not opp and opp_by_crm:
        opp = opp_by_crm.get(ck(e.get("opp_crm_id")), "")
    if not opp:
        hit = by_name.get(norm_name(e.get("account", "")))
        if hit:
            opp = hit["id"]
    if opp:
        return "opp", opp
    lead = (e.get("lead_id") or "").strip()
    if not lead and lead_by_crm:
        lead = lead_by_crm.get(ck(e.get("lead_crm_id")), "")
    if not lead:
        for addr in (e.get("counterpart_email"), e.get("from")):
            lead = lead_by_email.get((addr or "").strip().lower(), "")
            if lead:
                break
    if lead:
        return "lead", lead
    return None, None


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


_DIR_IN = {"in", "inbound", "incoming", "received", "true", "1"}
_DIR_OUT = {"out", "outbound", "outgoing", "sent", "false", "0"}


def classify_email(e, user_emails):
    """Direction, in this order: the sender against the user's addresses (a mailbox
    always knows who sent it); an explicit `direction` the CRM recorded (the profile's
    `email_direction_semantics` says whether it has one); else whatever kind the event
    already carried — a bare `email` stays bare, and moves no clock."""
    frm = (e.get("from") or "").strip().lower()
    if frm and user_emails:
        return "email_in" if not any(u in frm for u in user_emails) else "email_out"
    d = str(e.get("direction") or "").strip().lower()
    if d in _DIR_IN:
        return "email_in"
    if d in _DIR_OUT:
        return "email_out"
    k = (e.get("kind") or "").lower()
    return k if k in ("email_in", "email_out", "reply") else (k or "email")


def _record(e, who):
    """The stored shape. `by` and `crm_id` are kept only when present — most mailbox
    events have neither, and an absent key reads the same as a blank one downstream."""
    rec = {"date": (e.get("date") or "")[:10], "kind": e["kind"],
           "who": (who or "").strip().lower(), "detail": (e.get("detail") or "")[:120]}
    if e.get("by"):
        rec["by"] = str(e["by"]).strip()[:60]
    if e.get("crm_id"):
        rec["crm_id"] = str(e["crm_id"]).strip()
    return rec


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

    import csvguard as G
    user_emails = [u.strip().lower() for u in payload.get("user_emails", [])]
    by_name, _ = load_opp_index(root)
    lead_by_email = load_lead_index(root)
    opp_by_crm, lead_by_crm, lead_email = load_crm_maps(root)
    lead_p = lead_cache_path(root)
    leads = load_json(lead_p, {})
    from partner_conflict import norm_name

    seen = {event_key(e.get("date"), e.get("kind"), e.get("who"), key)
            for store in (cache, leads) for key, events in store.items() for e in events}
    added = lead_added = dup = unattributed = 0
    who_missing = 0

    for e in payload.get("events", []):
        kind = (e.get("kind") or "").lower()
        if kind in ("email", "email_in", "email_out", "reply"):
            e["kind"] = classify_email(e, user_emails)

        what, rid = attribute(e, by_name, lead_by_email, norm_name,
                              opp_by_crm, lead_by_crm, G.crm_key)
        if not rid:
            unattributed += 1
            continue

        who = (e.get("counterpart_email") or e.get("from") or "")
        if what == "lead" and not who.strip():
            # A CRM activity names the lead by id, not by address. The registry knows
            # the address, and dedup against the mailbox copy of the same email needs
            # the two reports to agree on who it was with.
            who = lead_email.get(rid, "")
            if not who:
                who_missing += 1
        k = event_key(e.get("date"), e["kind"], who, rid)
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        rec = _record(e, who)
        if what == "opp":
            cache.setdefault(rid, []).append(rec)
            added += 1
        else:
            leads.setdefault(rid, []).append(rec)
            lead_added += 1

    src = payload.get("source", "unknown")
    meta["cache_format"] = CACHE_FORMAT
    meta["sources"][src] = {"last_sync": date.today().isoformat(),
                            "last_added": added, "last_lead_added": lead_added,
                            "last_dupes": dup}
    meta["unattributed"] = meta.get("unattributed", 0) + unattributed
    if _lead_registry_exists(root):
        # Indexed means "the lead registry was consulted", not "leads had addresses":
        # a registry with no emails yet must not leave needs_full_window stuck on true.
        meta["leads_indexed"] = date.today().isoformat()
    save_json(cache_p, cache)
    save_json(lead_p, leads)
    save_json(meta_p, meta)
    print(f"{src}: +{added} deal events, +{lead_added} lead events, {dup} duplicates "
          f"collapsed, {unattributed} unattributable (no matching deal or lead)")
    if unattributed:
        print("  unattributable events are dropped — if that number is large, account "
              "names, CRM ids or lead addresses in the source don't match the registry "
              "and matching needs a look")
    if who_missing:
        print(f"  {who_missing} lead event(s) carry no counterpart address and the lead "
              "row has none either — stored, but a mailbox copy of the same message "
              "would not dedup against them")
    return 0


def is_crm_source(name, root=None):
    """Whether a source name is the CRM. `crm` is the canonical name; the vendor's own
    name (whatever the profile's `crm` says, or a dialect name) is accepted so that a
    payload labelled the old way still counts."""
    n = (name or "").strip().lower()
    if n == "crm":
        return True
    try:
        import csvguard as G
        vendors = set(G.CRM_DIALECTS)
        if root:
            v = str((G.load_field_map(root) or {}).get("crm", "")).strip().lower()
            if v:
                vendors.add(v)
        return n in vendors
    except Exception:
        return n in {"salesforce", "hubspot", "dynamics", "pipedrive", "zoho", "close",
                     "sugar"}


def log_event(root, record, kind, date_s, who="", by="", detail="", crm_activity_id=""):
    """Record one event the user reported — a call, an off-calendar meeting, a note —
    against a LEAD or an OPP. Same key, same dedup, same stores as --ingest, so a call
    the user mentions on Tuesday and the CRM copy of it that arrives on Wednesday are
    one event. For a lead the touch dates are rewritten in the same call, because the
    whole point of recording a call is that the clock moves."""
    record = (record or "").strip().upper()
    kind = (kind or "").strip().lower()
    if kind not in ("call", "meeting", "note", "email_out", "email_in", "quote",
                    "stage_change", "task"):
        print(f"kind {kind!r} is not one the cache knows (call, meeting, note, "
              "email_out, email_in, quote, stage_change, task)")
        return 2
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_s or ""):
        print("--date must be YYYY-MM-DD")
        return 2
    cache_p, meta_p = cache_paths(root)
    lead_p = lead_cache_path(root)
    if record.startswith("LEAD-"):
        store_p, what = lead_p, "lead"
        _, _, lead_email = load_crm_maps(root)
        if not who:
            who = lead_email.get(record, "")
    elif record.startswith("OPP-"):
        store_p, what = cache_p, "opp"
    else:
        print(f"--record must be a LEAD-nnnn or OPP-nnnn id, not {record!r}")
        return 2
    store = load_json(store_p, {})
    e = {"date": date_s, "kind": kind, "detail": detail, "by": by, "crm_id": crm_activity_id}
    k = event_key(date_s, kind, who, record)
    existing = next((x for x in store.get(record, [])
                     if event_key(x.get("date"), x.get("kind"), x.get("who"), record) == k),
                    None)
    if existing is not None:
        # Already known — from a connector, or logged before. Enrich rather than add:
        # the CRM id and the author are the two things a second report can teach.
        changed = False
        for fld in ("by", "crm_id"):
            if e.get(fld) and not existing.get(fld):
                existing[fld] = str(e[fld]).strip()
                changed = True
        if changed:
            save_json(store_p, store)
        print(f"{record}: {kind} on {date_s} was already in the cache"
              + (" — added the " + ", ".join(f for f in ("by", "crm_id") if e.get(f))
                 if changed else "") + "; nothing double-counted")
    else:
        store.setdefault(record, []).append(_record(e, who))
        save_json(store_p, store)
        meta = load_json(meta_p, {"sources": {}, "unattributed": 0})
        meta["cache_format"] = CACHE_FORMAT
        m = meta["sources"].setdefault("manual", {"last_added": 0, "last_lead_added": 0,
                                                  "last_dupes": 0})
        m["last_sync"] = date.today().isoformat()
        m["last_added" if what == "opp" else "last_lead_added"] = \
            m.get("last_added" if what == "opp" else "last_lead_added", 0) + 1
        save_json(meta_p, meta)
        print(f"{record}: recorded {kind} on {date_s}"
              + (f" with {who}" if who else "") + (f" by {by}" if by else ""))
    if what == "lead":
        return lead_touch(root)
    print("  deal clocks: run `engagement.py --apply` (or the next brief will) to rescore")
    return 0


def lead_touch(root, as_json=False):
    """Write last_outbound_date and last_inbound_date onto the lead registry from the
    lead cache. These are the columns the lead follow-up rules read; nothing else in
    the folder can say when *we* last wrote to a lead. last_activity_date cannot — it
    is CRM-calculated, carries import stamps, and stops moving when the CRM stops
    logging, which is why the rules were moved off it.

    Blank, never a fabricated date, where the cache holds nothing for a lead. A lead
    with both columns blank after a full-window ingest has genuinely never been
    touched in that window, and the brief reports it as unbaselined, not breaching."""
    import csvguard as G
    leads = load_json(lead_cache_path(root), {})
    meta = load_json(cache_paths(root)[1], {})
    schema = G.schema_by_registry(root, "leads")
    path = G.resolve_path(os.path.join(root, schema["path"]), root)
    if not os.path.exists(path):
        print("no lead registry to write to")
        return 1
    header, rows = G.read_table(path, schema)
    i = {h: k for k, h in enumerate(header)}
    for col in ("last_outbound_date", "last_inbound_date"):
        if col not in i:
            print(f"the lead registry predates {col} — run `csvguard.py --repair` on it "
                  "first so the column exists, then re-run")
            return 1
    if not meta.get("leads_indexed"):
        print("no ingest has run with a lead registry present — the cache holds no lead "
              "events. Re-ingest a full history window (90 days) before trusting these "
              "columns; until then every lead reads as never touched.")
    # `last_outbound_by` arrived with the CRM activity read: a colleague's logged call or
    # cadence send counts as the company's touch — the clock measures whether this
    # person has been left alone — and the name is what lets the user judge whether to
    # continue that thread. Blank means the touch came from the user's own mailbox or
    # calendar, i.e. the user. Older registries lack the column; --repair adds it.
    has_by = "last_outbound_by" in i
    out_kinds = {"email_out", "meeting", "call"}
    touched = 0
    summary = {"leads_with_events": len(leads), "written": 0}
    for r in rows:
        ev = leads.get(r[i["id"]], [])
        outs = [e for e in ev if e.get("kind") in out_kinds]
        last_out = max(outs, key=lambda e: e.get("date", ""), default=None)
        out = last_out["date"] if last_out else ""
        by = (last_out.get("by") or "") if last_out else ""
        inn = max((e["date"] for e in ev if e.get("kind") == "email_in"), default="")
        if r[i["last_outbound_date"]] != out or r[i["last_inbound_date"]] != inn or \
                (has_by and r[i["last_outbound_by"]] != by):
            r[i["last_outbound_date"]], r[i["last_inbound_date"]] = out, inn
            if has_by:
                r[i["last_outbound_by"]] = by
            touched += 1
    if touched:
        G.write_table(path, header, rows, schema=schema, root=root, backup=True)
    summary["written"] = touched
    if as_json:
        print(json.dumps(summary))
    else:
        print(f"lead touch dates: {touched} row(s) updated from {len(leads)} lead(s) "
              f"with cached events" if touched else
              f"lead touch dates already current ({len(leads)} lead(s) with events)")
    return 0


def status(root, as_json=False):
    cache_p, meta_p = cache_paths(root)
    cache = load_json(cache_p, {})
    meta = load_json(meta_p, {"sources": {}})
    leads = load_json(lead_cache_path(root), {})
    n = sum(len(v) for v in cache.values())
    ln = sum(len(v) for v in leads.values())
    sources = meta.get("sources", {})
    # The CRM read is judged on its own, because the other sources cannot stand in for
    # it: a mailbox sees the user's traffic, the CRM is the only source that sees a
    # colleague's. A profile that names a CRM and a cache that has never taken a CRM
    # payload is a cache with a hole in it, whatever the mail counts say.
    try:
        import csvguard as G
        has_crm = bool(str((G.load_field_map(root) or {}).get("crm", "")).strip())
    except Exception:
        has_crm = False
    crm_synced = any(is_crm_source(s, root) for s in sources)
    if as_json:
        # needs_full_window is the one bit the brief must act on: no source has ever
        # synced, or the lead registry has never been indexed. A brief that sees True and
        # proceeds to evaluate follow-up rules will read the whole book as untouched.
        # needs_crm_full_window is its per-source twin: the CRM activity read has never
        # been ingested, so its first ingest must cover the full history window even
        # though mail and calendar are current.
        print(json.dumps({"cache": cache_p, "deal_events": n, "deals": len(cache),
                          "lead_events": ln, "leads": len(leads),
                          "sources": sources,
                          "leads_indexed": meta.get("leads_indexed"),
                          "cache_format": meta.get("cache_format", 1 if cache else None),
                          "needs_full_window": not sources
                                               or not meta.get("leads_indexed"),
                          "crm_activity_synced": crm_synced,
                          "needs_crm_full_window": has_crm and not crm_synced}))
        return 0
    print(f"cache: {cache_p}")
    print(f"{n} events across {len(cache)} deals; {ln} events across {len(leads)} leads")
    if cache and not meta.get("leads_indexed"):
        print("  lead events: none — this cache predates lead attribution. Re-ingest a "
              "full history window so the lead follow-up rules have a touch date to read.")
    for s, m in sources.items():
        print(f"  {s:12} last sync {m.get('last_sync','never')} "
              f"(+{m.get('last_added',0)} deal, +{m.get('last_lead_added',0)} lead, "
              f"{m.get('last_dupes',0)} dupes)")
    if not sources:
        print("  no sources have synced yet — engagement will read everything as Cold "
              "until a brief or forecast ingests activity")
    elif has_crm and not crm_synced:
        print("  CRM activity: NEVER ingested. Mail and calendar see only the user's own "
              "traffic; a colleague's logged calls and cadence sends exist only in the "
              "CRM, so every lead they worked reads as never touched. Run `--plan`, "
              "fetch a full history window (90 days), ingest it as source `crm`.")
    if cache and meta.get("cache_format", 1) < CACHE_FORMAT:
        print(f"  WARNING: cache format {meta.get('cache_format', 1)}, current is "
              f"{CACHE_FORMAT}. This cache was written by a version that discarded a reply "
              "whenever it fell on the same day as an outbound email, so inbound counts "
              "here are too low and engagement trends read colder than reality. The next "
              "ingest discards and rebuilds it; give it a full history window.")
    return 0


KIND_GUIDE = """How each CRM record becomes an event (`kind`):
  a logged call                      -> "call"
  a meeting / calendar-type record   -> "meeting"
  an email (captured or logged)      -> "email", with "direction": "in"|"out" where the
                                        CRM records it, or "from" where it records the
                                        sender (a From: line in the body counts); neither
                                        known -> leave it "email" (counts for engagement,
                                        moves no clock — never guess)
  a cadence / sequence / list email  -> "email" with "direction": "out" — a sequence only
                                        ever sends, so this one is not a guess
  anything else a human typed        -> "note"
  auto-captured noise per the profile (portal alerts, support tickets, tooling mail) -> drop
Each event carries: date, kind, opp_crm_id (the deal link) or lead_crm_id (the lead link),
counterpart_email where the record has one, by = the owner's name, crm_id = the record's id,
detail = the subject. Hand the whole window back as ONE payload with "source": "crm"."""


def _scope(root):
    """`scope:` from config.md — own or team. Read here only to word the owner clause;
    the skill applies it, the way it does for every other CRM pull."""
    try:
        with open(os.path.join(root, "00-Config", "config.md"), encoding="utf-8") as f:
            m = re.search(r"^\s*-?\s*scope:\s*(\w+)", f.read(), re.M)
            return (m.group(1).lower() if m else "own")
    except OSError:
        return "own"


def _open_filters(root):
    """The profile's own default filters for the two registries, so the query the plan
    prints excludes what the registry import excludes (converted leads, deleted rows)."""
    import csvguard as G
    fm = G.load_field_map(root) or {}
    objs = fm.get("objects") or {}
    return ((objs.get("leads") or {}).get("default_filter") or "",
            (objs.get("opportunities") or {}).get("default_filter") or "")


def plan(root, since=None):
    """Print the CRM activity read for the window: every activity linked to an open deal
    OR to a lead in the registry, bounded by date the way the profile's query rules
    demand. Writes the id lists to the cache directory for a CRM that has no way to
    express "linked to one of these" in a query.

    Why this exists: the mailbox read is spelled out in the brief and it runs every
    morning; the CRM read said "per the profile" and never ran once. A fetch that is
    not written down is a fetch that does not happen."""
    import csvguard as G
    fm = G.load_field_map(root) or {}
    d = G.dialect_for(fm)
    crm = str(fm.get("crm", "")).strip()
    _, meta_p = cache_paths(root)
    meta = load_json(meta_p, {"sources": {}})
    last = max((m.get("last_sync", "") for s, m in meta.get("sources", {}).items()
                if is_crm_source(s, root)), default="")
    if not since:
        if last:
            from datetime import timedelta
            since = (date.fromisoformat(last) - timedelta(days=1)).isoformat()
        else:
            from datetime import timedelta
            since = (date.today() - timedelta(days=90)).isoformat()
    first = not last

    opp_by_crm, lead_by_crm, _ = load_crm_maps(root)
    # Only open deals and leads still being worked: closed deals' history is already in
    # the cache or is not worth the query cost, and a disqualified lead has no clock.
    i, rows = _registry_rows(root, "07-Opportunities/opportunities.csv")
    open_opps = [r[i["crm_id"]] for r in rows if "crm_id" in i and r[i["crm_id"]]
                 and not (r[i["stage"]] if "stage" in i else "").startswith("Closed")]
    i, rows = _registry_rows(root, "06-Leads/leads.csv")
    live_leads = [r[i["crm_id"]] for r in rows if "crm_id" in i and r[i["crm_id"]]
                  and (r[i["status"]] if "status" in i else "").strip().lower()
                  not in LEAD_TERMINAL]
    ids_p = os.path.join(cache_dir(root), "activity-plan.json")
    save_json(ids_p, {"since": since, "first_crm_ingest": first,
                      "opportunity_crm_ids": open_opps, "lead_crm_ids": live_leads})

    print(f"CRM activity read — {crm or 'CRM not named in the profile'}")
    print(f"  window: since {since}" + ("  (FIRST CRM INGEST: this is the full 90-day "
                                        "history window, not an increment)" if first
                                        else f"  (last CRM sync {last}, minus a day of "
                                             "overlap; dedup absorbs the overlap)"))
    print(f"  cover: {len(open_opps)} open opportunities and {len(live_leads)} live leads "
          f"by CRM id (lists written to {os.path.relpath(ids_p, root)})")
    if not crm:
        print("\nNo CRM in the profile — nothing to fetch. If there is a CRM, run "
              "configure-project so the profile names it.")
        return 1

    lead_filter, opp_filter = _open_filters(root)
    block = fm.get("activity") or {}
    vendor = d.get("activity") or {}
    rules = ((fm.get("objects") or {}).get("activity") or {}).get("query_rules") or []
    if rules:
        print("\n  bounds the profile records (honour every one):")
        for r in rules:
            print(f"    - {r.get('rule')}" + (f"  [{r.get('why')}]" if r.get("why") else ""))

    if block.get("email_object") or block.get("meeting_object"):
        print("\nObjects, from the profile's `activity` block:")
        for title, obj, fld in (("email", block.get("email_object"),
                                 block.get("email_fields") or {}),
                                ("meetings", block.get("meeting_object"),
                                 block.get("meeting_fields") or {})):
            if not obj:
                print(f"  {title}: not recorded — that evidence will be missing")
                continue
            print(f"  {title}: {obj}")
            print(f"    deal link {fld.get('opportunity_link') or '?'} · lead link "
                  f"{fld.get('lead_link') or '?'} · account link "
                  f"{fld.get('account_link') or '?'} · date {fld.get('date') or '?'}")
            if not fld.get("lead_link"):
                print("    lead_link is blank — lead activity CANNOT be read until "
                      "configure-project fills it. Say so in the brief.")
        sem = block.get("email_direction_semantics") or "none"
        print(f"  email direction: {sem}" + ("  — pass `direction` per record"
                                              if sem == "boolean_incoming" else
                                              "  — pass `from`; else leave kind `email`"))
    if vendor:
        # Printed whether or not the canonical block exists: the block names where email
        # and meetings live, but a logged call, a cadence step, a typed note — the
        # activity a colleague leaves on a lead — sits on the CRM's generic activity
        # object, and the block has no slot for it.
        print(f"\nObjects, from the {crm} dialect"
              + (" — the logged calls, cadence steps and notes the block above does not "
                 "name:" if block.get("email_object") or block.get("meeting_object") else
                 " (the profile has no canonical `activity` block; configure-project can "
                 "add one):"))
        for key in ("task", "event"):
            o = vendor.get(key) or {}
            if not o:
                continue
            fields = [v for k, v in o.items() if k != "object" and v]
            print(f"  {o.get('object')}: SELECT {', '.join(dict.fromkeys(fields))}")
        if d.get("query_language") == "soql":
            lf = lead_filter or "IsConverted = false"
            of = opp_filter or "IsDeleted = false"
            if "isclosed" not in of.lower():
                of = "IsClosed = false AND " + of
            from datetime import timedelta
            tomorrow = (date.today() + timedelta(days=1)).isoformat()
            print("\n  the two reads, as SOQL — semi-joins, so no id lists are pasted in:")
            # Tasks are bounded on modification; Events on when they happened, with a
            # ceiling, because recurring series scheduled decades out are a real thing
            # and a future meeting is not evidence of anything.
            for key, bound in (("task", f"LastModifiedDate >= {since}T00:00:00Z"),
                               ("event", f"StartDateTime >= {since}T00:00:00Z AND "
                                         f"StartDateTime < {tomorrow}T00:00:00Z")):
                o = vendor.get(key) or {}
                if not o:
                    continue
                fields = ", ".join(dict.fromkeys(v for k, v in o.items()
                                                 if k != "object" and v))
                print(f"    SELECT {fields} FROM {o['object']}\n"
                      f"      WHERE {bound}\n"
                      f"        AND ({o.get('what','WhatId')} IN (SELECT Id FROM Opportunity "
                      f"WHERE {of})\n"
                      f"          OR {o.get('who','WhoId')} IN (SELECT Id FROM Lead "
                      f"WHERE {lf}))")
            print("    Page to exhaustion. If the connector rejects Who.Email, drop it — "
                  "the ingest fills a lead's\n    address from the registry.")
            scope = _scope(root)
            print(f"    Scope is `{scope}`: " + (
                "add the owner clause (the user's CRM user id) to BOTH sub-selects"
                if scope == "own" else
                "add `OwnerId IN (<the ids in 00-Config/team.csv>)` to BOTH sub-selects,"
                "\n    the same way the registry pull is scoped")
                + " — never to the activity\n    itself: a colleague's call on your lead "
                "has their OwnerId, and it is exactly what you are here for.")
            if len(live_leads) > 2000 or first:
                print(f"    Volume: {len(live_leads)} live leads"
                      + (" and a first, 90-day read" if first else "")
                      + ". If the connector times out, slice the window\n    (14 days at "
                      "a time, oldest first) and ingest each slice as it lands — dedup makes "
                      "the overlap\n    free and a partial read is still an honest one, as "
                      "long as the brief says which slices ran.")
    if not vendor and not (block.get("email_object") or block.get("meeting_object")):
        print(f"\nNo activity objects are known for {crm}: the profile has no `activity` "
              "block and no dialect declares defaults. Run configure-project to "
              "introspect which object holds calls, emails and meetings and which field "
              "links each to a lead and to an opportunity; until then lead activity is "
              "unreadable and the brief must say so.")
        return 1

    print()
    print(KIND_GUIDE)
    print(f"\nThen:\n  activity_sync.py --ingest {root} --input crm-activity.json\n"
          f"  activity_sync.py --lead-touch {root}")
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

    # Attribution: deals win, then leads by the person's address, then nothing.
    by_name = {"acme": {"id": "OPP-1"}}
    leads = {"jane@acme.com": "LEAD-7", "bob@other.com": "LEAD-9"}
    ident = lambda s: (s or "").strip().lower()
    check("deal wins over lead",
          attribute({"account": "Acme", "from": "jane@acme.com"}, by_name, leads, ident),
          ("opp", "OPP-1"))
    check("lead by counterpart email",
          attribute({"account": "Nobody Inc", "counterpart_email": "Bob@Other.com"},
                    by_name, leads, ident), ("lead", "LEAD-9"))
    check("unattributed stays unattributed",
          attribute({"account": "Nobody Inc", "from": "x@y.com"}, by_name, leads, ident),
          (None, None))

    # CRM activity is linked by the CRM's ids. Both forms of a Salesforce id must
    # resolve, a deal link beats a lead link, and a CRM id nobody has beats nothing.
    import csvguard as G
    sf = G.dialect_for({"crm": "salesforce"})
    ck = lambda s: G.crm_key(s, sf)
    id15 = "00Q5e00000AbCdE"
    id18 = id15 + G.sf_checksum(id15)
    opp_crm = {ck("0065e00000XyZzZ"): "OPP-1"}
    lead_crm = {ck(id15): "LEAD-7"}
    check("lead by CRM id, 18-char form",
          attribute({"lead_crm_id": id18}, {}, {}, ident, opp_crm, lead_crm, ck),
          ("lead", "LEAD-7"))
    check("deal link beats lead link",
          attribute({"lead_crm_id": id15, "opp_crm_id": "0065e00000XyZzZ"}, {}, {}, ident,
                    opp_crm, lead_crm, ck), ("opp", "OPP-1"))
    check("unknown CRM id stays unattributed",
          attribute({"lead_crm_id": "00Q000000000000"}, {}, {}, ident, opp_crm, lead_crm,
                    ck), (None, None))

    # Direction from a CRM flag, and the honest blank when nothing says.
    check("direction flag inbound", classify_email({"direction": "in", "kind": "email"}, []),
          "email_in")
    check("no direction stays bare email",
          classify_email({"kind": "email"}, ["@example.com"]), "email")
    check("sender beats flag", classify_email({"from": "rep@example.com", "direction": "in"},
                                              ["@example.com"]), "email_out")

    # A logged call and the CRM's later copy of it are one event; the copy can teach
    # the cache who made it, but never adds a second row.
    k1 = event_key("2026-09-10", "call", "jane@acme.com", "LEAD-7")
    k2 = event_key("2026-09-10", "call", "Jane@Acme.com", "LEAD-7")
    check("manual log and CRM copy share a key", k1, k2)
    rec = _record({"date": "2026-09-10", "kind": "call", "by": " Cortney ", "crm_id": ""},
                  "jane@acme.com")
    check("by kept, blank crm_id dropped", (rec.get("by"), "crm_id" in rec),
          ("Cortney", False))

    total = 18
    for f in fails:
        print(f"FAIL {f}", file=sys.stderr)
    print(f"activity_sync selftest: {total - len(fails)}/{total} passed")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ingest"); ap.add_argument("--input")
    ap.add_argument("--status"); ap.add_argument("--rebuild")
    ap.add_argument("--lead-touch"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--plan"); ap.add_argument("--since")
    ap.add_argument("--log"); ap.add_argument("--record"); ap.add_argument("--kind")
    ap.add_argument("--date"); ap.add_argument("--who", default="")
    ap.add_argument("--by", default=""); ap.add_argument("--detail", default="")
    ap.add_argument("--crm-activity-id", default="")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.plan:
        return plan(os.path.abspath(a.plan), a.since)
    if a.log:
        if not (a.record and a.kind and a.date):
            print("--log needs --record, --kind and --date")
            return 2
        return log_event(os.path.abspath(a.log), a.record, a.kind, a.date, a.who, a.by,
                         a.detail, a.crm_activity_id)
    if a.lead_touch:
        return lead_touch(os.path.abspath(a.lead_touch), a.json)
    if a.ingest:
        with open(a.input, encoding="utf-8") as f:
            return ingest(os.path.abspath(a.ingest), json.load(f))
    if a.status:
        return status(os.path.abspath(a.status), a.json)
    if a.rebuild:
        cache_p, meta_p = cache_paths(os.path.abspath(a.rebuild))
        for p in (cache_p, meta_p, lead_cache_path(os.path.abspath(a.rebuild))):
            if os.path.exists(p):
                os.remove(p)
        print("cache cleared — skills should re-ingest a full history window")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
