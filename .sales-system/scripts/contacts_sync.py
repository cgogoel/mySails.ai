#!/usr/bin/env python3
"""
contacts_sync.py — who is actually on a deal, and which of them answer.

The opportunity registry holds one row per deal, so it cannot hold a list of people.
That gap is why `single-threaded` — a flag the opportunity skill promises — could never
fire: it read a count that nothing populated, evaluated to nothing, and reported a clean
bill of health on deals with one contact carrying them. An absent answer that looks like
a right answer is the worst failure mode a system like this has.

This script builds `07-Opportunities/opportunity-contacts.csv` and derives the rollups and
relationship risk flags from it. Three things make it harder than counting contact roles,
all of them observed in live orgs rather than imagined:

1. **The contact-role list and the people talking to you are different sets.** A deal can
   show two official contacts while thirteen people appear in its activity, none of the
   three busiest among the official two. Importing roles alone produces a confident,
   precise, wrong answer. Contacts are therefore unioned from both, and `source` records
   which side each came from.

2. **Auto-replies look exactly like engagement.** An out-of-office proves a mailbox
   exists, not that a person is behind it — and folding one into `replied` marks a
   departed contact's still-running mailbox as an engaged human. They are counted
   separately and produce their own state, because "verify this person" is a different
   action from "chase this person".

3. **Direction is not always knowable.** The activity object most orgs actually populate
   often has no direction field at all. Where the org cannot establish it, `replied` stays
   BLANK and `engagement` is `undetermined`. Forcing an unknown to `no` manufactures a
   risk flag out of a logging gap, which is the same mistake as the one above wearing
   different clothes.

Nothing here names a CRM. The objects and fields come from the `activity` block in
`crm-profile/field-map.json`, which configure-project builds by introspection.

Usage:
  contacts_sync.py --plan   <project>                    # what to query, per the profile
  contacts_sync.py --build  <project> --input payload.json [--dry-run]
  contacts_sync.py --rollup <project>                    # recompute from the registry alone
  contacts_sync.py --flags  <project> [--json] [--open-only]

Exit codes: 0 fine, 1 needs a human, 2 usage error.
"""

import argparse
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csvguard as G

REGISTRY = "opportunity_contacts"

# Defaults used only where the profile hasn't recorded the org's own. SQL-style `%`
# wildcards, because that is how these get written in a CRM query and copying them across
# should not need translating.
DEFAULT_AUTO_REPLY = ["Automatic reply%", "Automatic Reply%", "Auto Reply%",
                      "AutoReply%", "Out of office%", "Out of Office%",
                      "Autosvar%", "Réponse automatique%"]
DEFAULT_BOUNCE = ["Undeliverable%", "Delivery Status Notification%",
                  "Mail Delivery%", "Returned mail%", "Address not found%",
                  "Delivery has failed%"]
DEFAULT_MEETING_SUBJECTS = {"accepted": ["Accepted:%"],
                            "invitation": ["Invitation:%", "Invite:%"],
                            "declined": ["Declined:%"]}


# ------------------------------------------------------------------ profile plumbing


def activity_block(root):
    """The `activity` block from the CRM profile. Absent is a normal state — a folder
    upgraded before this existed has none, and every caller has to cope."""
    return (G.load_field_map(root) or {}).get("activity") or {}


def like_to_re(patterns):
    """SQL LIKE patterns to one case-insensitive regex. `%` is any run of characters."""
    parts = []
    for p in patterns or []:
        p = (p or "").strip()
        if not p:
            continue
        parts.append("".join(".*" if ch == "%" else re.escape(ch) for ch in p))
    if not parts:
        return None
    return re.compile("|".join(f"(?:{p})" for p in parts), re.IGNORECASE)


def matches(text, rx):
    return bool(rx and text and rx.match(text.strip()))


def _get(rec, path):
    """Read a possibly-dotted key. Query results nest ('Who.Email'); exports don't."""
    if not path:
        return None
    cur = rec
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def canonise(rec, mapping):
    """Fill canonical keys from the org's API field names, without disturbing keys the
    caller already supplied in canonical form. Both shapes arrive in practice: a skill
    that shaped the payload, and a raw query result pasted straight in."""
    out = dict(rec)
    for canon, api in mapping.items():
        if out.get(canon) not in (None, "", []):
            continue
        v = _get(rec, api)
        if v not in (None, ""):
            out[canon] = v
    return out


ROLE_MAP_KEYS = {"role_crm_id": "id", "opportunity_crm_id": "opportunity",
                 "contact_crm_id": "contact", "role": "role", "is_primary": "primary",
                 "name": "name", "title": "title", "email": "email"}
EMAIL_MAP_KEYS = {"date": "date", "subject": "subject", "from": "from", "to": "to",
                  "incoming": "direction_flag", "opportunity_crm_id": "opportunity_link",
                  "account_crm_id": "account_link"}
MEETING_MAP_KEYS = {"date": "date", "subject": "subject", "attendees": "attendee",
                    "opportunity_crm_id": "opportunity_link",
                    "account_crm_id": "account_link"}


def mapper(block, key, keys):
    fields = (block.get(key) or {})
    return {canon: fields[api] for canon, api in keys.items() if fields.get(api)}


# ------------------------------------------------------------------------- utilities


def as_list(v):
    if v in (None, ""):
        return []
    if isinstance(v, list):
        return [x for x in v if x]
    return [x.strip() for x in re.split(r"[;,]", str(v)) if x.strip()]


def emails_in(v):
    """Pull addresses out of whatever shape a recipient field arrived in."""
    out = []
    for item in as_list(v):
        for m in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", str(item)):
            out.append(m.lower())
    return out


def one_email(v):
    got = emails_in(v)
    return got[0] if got else ""


def iso(v):
    return G.norm_date(str(v) if v is not None else "")[0][:10]


def truthy(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "yes", "y", "1")


def norm_person(name):
    return re.sub(r"[^a-z ]", "", (name or "").lower()).strip()


# ------------------------------------------------------------------- opportunity index


def opp_index(root):
    """crm_id -> the handful of deal facts the derivations need."""
    schema = G.schema_by_registry(root, "opportunities")
    path = G.resolve_path(os.path.join(root, schema["path"]), root)
    if not os.path.exists(path):
        return {}, {}, schema
    header, rows = G.read_table(path, schema)
    i = {h: k for k, h in enumerate(header)}
    by_crm, by_id = {}, {}
    for r in rows:
        def cell(name):
            return r[i[name]] if name in i and i[name] < len(r) else ""
        rec = {"id": cell("id"), "name": cell("name"),
               "account_name": cell("account_name"), "stage": cell("stage"),
               "created_date": cell("created_date"), "close_date": cell("close_date"),
               "crm_id": cell("crm_id")}
        rec["open"] = not (rec["stage"] or "").lower().startswith("closed")
        by_id[rec["id"]] = rec
        k = G.crm_key(rec["crm_id"])
        if k:
            by_crm[k] = rec
    return by_crm, by_id, schema


def in_window(rec, when):
    """Was this dated inside the deal's life? Used only for account-linked evidence,
    where the activity names the customer but not which of their deals."""
    if not when:
        return False
    start = rec.get("created_date") or ""
    end = rec.get("close_date") or ""
    today = date.today().isoformat()
    if end and end < today and not rec.get("open"):
        latest = end
    else:
        latest = max(end, today) if end else today
    if start and when < start:
        return False
    return when <= latest


def stage_rank(stage, values):
    """How far through the org's own stage list this is, 0.0 to 1.0. The list comes from
    the profile's picklists where there is one, so it is the org's process rather than a
    guess. Closed stages are excluded from the ordering."""
    live = [v for v in (values or []) if not v.lower().startswith("closed")]
    if not live or not stage:
        return None
    for n, v in enumerate(live):
        if v.lower() == stage.lower():
            return n / max(1, len(live) - 1)
    return None


# ----------------------------------------------------------------------- the build


class Contact:
    def __init__(self, opp_id, email, name=""):
        self.opp_id = opp_id
        self.email = (email or "").lower()
        self.name = name
        self.title = ""
        self.role = ""
        self.role_crm_id = ""
        self.contact_crm_id = ""
        self.is_primary = ""
        self.from_role = False
        self.from_activity = False
        self.dates = []
        self.outbound = 0
        self.replies = 0
        self.auto_replies = 0
        self.bounces = 0
        self.reply_dates = []
        self.outbound_dates = []
        self.meetings = 0
        self.meeting_dates = []
        self.meeting_rung = ""
        self.direction_seen = False


RUNGS = ["opportunity-linked", "account-dated", "invite-accepted"]


def build(root, payload, dry_run=False):
    block = activity_block(root)
    if not block:
        print("No `activity` block in crm-profile/field-map.json.\n"
              "  This is what tells the system which objects hold contact roles, email\n"
              "  and meetings in your CRM, and whether direction can be established at\n"
              "  all. Run configure-project to introspect and confirm it, then re-run.\n"
              "  Building without it would mean guessing at object names, and a wrong\n"
              "  guess here produces an empty answer that reads as a clean one.")
        return 1

    semantics = (block.get("email_direction_semantics") or "none").strip().lower()
    auto_rx = like_to_re(block.get("auto_reply_subject_patterns") or DEFAULT_AUTO_REPLY)
    bounce_rx = like_to_re(block.get("bounce_subject_patterns") or DEFAULT_BOUNCE)
    subj = dict(DEFAULT_MEETING_SUBJECTS)
    subj.update(block.get("meeting_subject_patterns") or {})
    accepted_rx = like_to_re(subj.get("accepted"))

    by_crm, by_id, opp_schema = opp_index(root)
    if not by_crm and not by_id:
        print("The opportunity registry is empty or missing — nothing to attach contacts "
              "to. Load opportunities first.")
        return 1

    user_emails = {e.lower() for e in payload.get("user_emails", []) if e}
    if not user_emails:
        print("REFUSING TO BUILD — the payload has no `user_emails`.\n")
        print("  Without knowing which addresses are yours, every message looks like it "
              "came from\n  a customer: you end up as a contact on your own deals, your "
              "colleagues on the\n  thread become 'contacts', and direction cannot be "
              "inferred where the CRM doesn't\n  record it. The registry would fill up "
              "with plausible nonsense.\n")
        print('  Add: "user_emails": ["you@yourcompany.com"] — every address you send '
              'from.')
        return 1
    # Colleagues copied on a customer thread are not contacts on the deal. Counting them
    # inflates contacts_attached with your own side and can make a single-threaded deal
    # look comfortably multi-threaded, which is the exact error this whole feature exists
    # to stop.
    internal = {d.lower() for d in (payload.get("internal_domains") or [])}
    internal |= {a.split("@")[-1] for a in user_emails if "@" in a}

    def is_internal(addr):
        return addr in user_emails or addr.split("@")[-1] in internal

    accounts = {G.crm_key(k): [G.crm_key(x) for x in as_list(v)]
                for k, v in (payload.get("accounts") or {}).items()}

    contacts = {}          # (opp_id, email-or-name key) -> Contact
    ambiguous = skipped = 0

    def resolve(rec, when):
        """Which deal does this activity belong to? Returns (opp record, how)."""
        nonlocal ambiguous
        direct = by_crm.get(G.crm_key(rec.get("opportunity_crm_id") or ""))
        if direct:
            return direct, "opportunity-linked"
        acct = G.crm_key(rec.get("account_crm_id") or "")
        if not acct:
            return None, ""
        cands = [by_crm[k] for k in accounts.get(acct, []) if k in by_crm]
        live = [c for c in cands if c["open"] and in_window(c, when)]
        if len(live) == 1:
            return live[0], "account-dated"
        if len(live) > 1:
            # Two open deals at the same customer and activity that names only the
            # customer. Attaching it to either would be a coin toss reported as a fact.
            ambiguous += 1
        return None, ""

    def get(opp_id, email, name=""):
        key = (opp_id, (email or "").lower() or f"name:{norm_person(name)}")
        if key not in contacts:
            contacts[key] = Contact(opp_id, email, name)
        c = contacts[key]
        if name and not c.name:
            c.name = name
        return c

    # --- contact roles: who the CRM thinks is on the deal
    rmap = mapper(block, "contact_role_fields", ROLE_MAP_KEYS)
    for raw in payload.get("contact_roles", []):
        r = canonise(raw, rmap)
        opp = by_crm.get(G.crm_key(r.get("opportunity_crm_id") or ""))
        if not opp:
            skipped += 1
            continue
        c = get(opp["id"], one_email(r.get("email")), str(r.get("name") or ""))
        c.from_role = True
        c.role_crm_id = str(r.get("role_crm_id") or "")
        c.contact_crm_id = str(r.get("contact_crm_id") or "")
        c.title = str(r.get("title") or c.title)
        c.role = str(r.get("role") or c.role)
        c.is_primary = "yes" if truthy(r.get("is_primary")) else "no"

    # --- email: who is actually talking, and in which direction
    emap = mapper(block, "email_fields", EMAIL_MAP_KEYS)
    for raw in payload.get("emails", []):
        e = canonise(raw, emap)
        when = iso(e.get("date"))
        opp, _how = resolve(e, when)
        if not opp:
            skipped += 1
            continue
        subject = str(e.get("subject") or "")
        frm = one_email(e.get("from"))
        tos = [a for a in emails_in(e.get("to")) if not is_internal(a)]

        if semantics == "boolean_incoming" and e.get("incoming") is not None:
            incoming, known = truthy(e.get("incoming")), True
        elif semantics == "subject_heuristic":
            incoming = (bool(re.match(r"\s*re\s*:", subject, re.I))
                        and not is_internal(frm))
            known = True
        elif frm and user_emails:
            # The direction field is absent but the sender is not: if the sender is the
            # user, this went out. That is a fact about the message, not a heuristic.
            incoming, known = not is_internal(frm), True
        else:
            incoming, known = False, False

        counterparts = [frm] if (incoming and frm) else tos
        if not counterparts and frm and not is_internal(frm):
            counterparts = [frm]
        for addr in counterparts:
            if not addr or is_internal(addr):
                continue
            c = get(opp["id"], addr)
            c.from_activity = True
            c.dates.append(when)
            if known:
                c.direction_seen = True
            if not known:
                continue
            if incoming:
                if matches(subject, bounce_rx):
                    c.bounces += 1
                elif matches(subject, auto_rx):
                    c.auto_replies += 1
                elif matches(subject, accepted_rx):
                    # Calendar traffic captured as email. Meeting evidence, not a reply —
                    # counting an acceptance as a reply overstates the relationship.
                    if not c.meeting_rung:
                        c.meeting_rung = "invite-accepted"
                    c.meetings += 1
                    c.meeting_dates.append(when)
                else:
                    c.replies += 1
                    c.reply_dates.append(when)
            else:
                c.outbound += 1
                c.outbound_dates.append(when)

    # --- meetings: strongest evidence where it exists, which is rarer than anyone expects
    mmap = mapper(block, "meeting_fields", MEETING_MAP_KEYS)
    for raw in payload.get("meetings", []):
        m = canonise(raw, mmap)
        when = iso(m.get("date"))
        opp, how = resolve(m, when)
        if not opp:
            skipped += 1
            continue
        for addr in emails_in(m.get("attendees")):
            if is_internal(addr):
                continue
            c = get(opp["id"], addr)
            c.from_activity = True
            c.dates.append(when)
            c.meetings += 1
            c.meeting_dates.append(when)
            if not c.meeting_rung or RUNGS.index(how) < RUNGS.index(c.meeting_rung):
                c.meeting_rung = how

    have_meeting_source = bool(block.get("meeting_object")) or bool(payload.get("meetings"))
    records = [as_record(c, by_id, semantics, have_meeting_source)
               for c in contacts.values()]

    print(f"{len(records)} contact row(s) across "
          f"{len({c.opp_id for c in contacts.values()})} deal(s)")
    only_role = sum(1 for c in contacts.values() if c.from_role and not c.from_activity)
    only_act = sum(1 for c in contacts.values() if c.from_activity and not c.from_role)
    print(f"  {only_role} on a contact role with no activity, "
          f"{only_act} in the activity record only")
    if only_act:
        print("  — the second number is the point of this: those people are working the "
              "deal and the CRM does not list them on it")
    if ambiguous:
        print(f"  {ambiguous} activity record(s) named a customer with more than one open "
              f"deal and were left unattached rather than guessed at")
    if skipped:
        print(f"  {skipped} record(s) matched no deal in the registry")
    undetermined = sum(1 for r in records if r["reply_evidence"] == "none")
    inferred = sum(1 for r in records if r["reply_evidence"] == "sender-inferred")
    if undetermined:
        print(f"  {undetermined} contact(s) have messages but no determinable direction — "
              f"`replied` stays blank and engagement reads `undetermined` for them. That "
              f"is the honest answer, not a failed import.")
    if inferred and semantics == "none":
        print(f"  {inferred} contact(s) had direction taken from the sender address "
              f"instead. The profile records this org as having no direction flag, and "
              f"that is still true — but a message that says who sent it settles the "
              f"question on its own, and `reply_evidence` says so per row.")

    if dry_run:
        print("\ndry run — nothing written")
        return 0

    schema = G.schema_by_registry(root, REGISTRY)
    path = G.resolve_path(os.path.join(root, schema["path"]), root)
    u, i, sk, _ch = G.upsert(path, schema, records, key="crm_id", root=root,
                             only_owner=None, allow_clear=True)
    print(f"\n{os.path.basename(path)}: {i} new, {u} updated"
          + (f", {sk} skipped with no key" if sk else ""))
    return rollup(root)


def as_record(c, by_id, semantics, have_meeting_source):
    opp = by_id.get(c.opp_id, {})
    dates = sorted(d for d in c.dates if d)
    # Determinable is a property of the ORG's logging, not of this person's traffic. A
    # contact with no messages at all has demonstrably not replied — calling that
    # "undeterminable" would hide every never-contacted person behind a shrug, which is
    # the opposite of the honesty this column exists for.
    determinable = (semantics in ("boolean_incoming", "subject_heuristic")
                    or c.direction_seen)

    if not (c.dates or c.outbound or c.replies):
        # No messages with this person at all. "Has not replied" is trivially true and
        # saying so beats a blank that reads as a shrug — never-contacted is one of the
        # more actionable states there is.
        replied, evidence, determinable = "no", "no-activity", True
    elif not determinable:
        replied, evidence = "", "none"
    else:
        replied = "yes" if c.replies else "no"
        evidence = ("direction-flag" if semantics == "boolean_incoming" else
                    "subject-heuristic" if semantics == "subject_heuristic" else
                    "sender-inferred")

    if c.bounces and not c.replies:
        engagement = "bounced"
    elif c.replies:
        engagement = "engaged"
    elif not determinable and (c.outbound or c.dates):
        engagement = "undetermined"
    elif c.auto_replies:
        engagement = "auto-reply-only"
    elif c.outbound:
        engagement = "contacted-no-reply"
    else:
        engagement = "never-contacted"

    if c.meetings:
        meeting_held, rung = "yes", (c.meeting_rung or "invite-accepted")
    elif have_meeting_source:
        meeting_held, rung = "no", "none"
    else:
        meeting_held, rung = "", "none"

    source = "both" if (c.from_role and c.from_activity) else (
        "contact-role" if c.from_role else "activity-only")

    return {
        "opportunity_id": c.opp_id,
        "opportunity_name": opp.get("name", ""),
        "contact_crm_id": c.contact_crm_id,
        "role_crm_id": c.role_crm_id,
        "name": c.name,
        "title": c.title,
        "email": c.email,
        "role": c.role,
        "is_primary": c.is_primary,
        "source": source,
        "first_touch_date": dates[0] if dates else "",
        "last_outbound_date": max(c.outbound_dates) if c.outbound_dates else "",
        # Counts are blank, not zero, where direction could not be established. A zero
        # outbound on a deal you have been emailing all quarter is a lie the file tells
        # every reader afterwards.
        "outbound_count": str(c.outbound) if determinable else "",
        "replied": replied,
        "reply_evidence": evidence,
        "last_reply_date": max(c.reply_dates) if c.reply_dates else "",
        "replies_count": str(c.replies) if determinable else "",
        "auto_replies_count": str(c.auto_replies) if determinable else "",
        "meeting_held": meeting_held,
        "meeting_evidence": rung,
        "last_meeting_date": max(c.meeting_dates) if c.meeting_dates else "",
        "meetings_count": str(c.meetings),
        "engagement": engagement,
        # Stable across rebuilds: the contact-role record where the CRM has one, and
        # otherwise the deal plus the address. Without this an activity-only contact is a
        # new row on every run and the registry grows a duplicate per sync.
        "crm_id": c.role_crm_id or f"{c.opp_id}|{c.email or norm_person(c.name)}",
    }


# ---------------------------------------------------------------------- rollup & flags


def read_contacts(root):
    schema = G.load_schemas(root).get(REGISTRY)
    if not schema:
        return None, [], None
    path = G.resolve_path(os.path.join(root, schema["path"]), root)
    if not os.path.exists(path):
        return schema, [], path
    header, rows = G.read_table(path, schema)
    i = {h: k for k, h in enumerate(header)}
    out = []
    for r in rows:
        out.append({h: (r[i[h]] if i[h] < len(r) else "") for h in header})
    return schema, out, path


def rollup(root):
    """Write contacts_attached and contacts_engaged back onto the deals.

    Both are blank rather than zero when the registry holds nothing for a deal. A zero
    would claim the deal has nobody on it; blank says nobody has looked."""
    schema, rows, path = read_contacts(root)
    if schema is None:
        print("no opportunity_contacts schema in this folder — nothing to roll up")
        return 0
    if not rows:
        print(f"{os.path.basename(path or 'opportunity-contacts')} is empty — "
              f"contacts_attached and contacts_engaged left blank, which is what tells "
              f"the skill not to report on threading")
        return 0

    attached, engaged, undet = {}, {}, {}
    for r in rows:
        o = r.get("opportunity_id", "")
        if not o:
            continue
        attached[o] = attached.get(o, 0) + 1
        if r.get("replied", "").lower() in ("yes", "true", "1"):
            engaged[o] = engaged.get(o, 0) + 1
        elif not r.get("replied", ""):
            undet[o] = undet.get(o, 0) + 1

    oschema = G.schema_by_registry(root, "opportunities")
    opath = G.resolve_path(os.path.join(root, oschema["path"]), root)
    if not os.path.exists(opath):
        print("no opportunity registry to write to")
        return 1
    header, orows = G.read_table(opath, oschema)
    i = {h: k for k, h in enumerate(header)}
    if "contacts_attached" not in i or "contacts_engaged" not in i:
        print("the opportunity registry predates these columns — run "
              "`csvguard.py --repair` on it first so they exist, then re-run")
        return 1
    touched = 0
    for r in orows:
        oid = r[i["id"]]
        if oid not in attached:
            continue
        a = str(attached[oid])
        # Every contact on the deal is undeterminable: a count of engaged contacts would
        # be a fiction, so say nothing rather than zero.
        e = "" if undet.get(oid, 0) == attached[oid] else str(engaged.get(oid, 0))
        if r[i["contacts_attached"]] != a or r[i["contacts_engaged"]] != e:
            r[i["contacts_attached"]], r[i["contacts_engaged"]] = a, e
            touched += 1
    G.write_table(opath, header, orows, schema=oschema, root=root, backup=True)
    print(f"rolled up onto {touched} deal(s): contacts_attached, contacts_engaged"
          if touched else
          f"contacts_attached and contacts_engaged already match the registry "
          f"({len(attached)} deal(s) with contacts)")
    return 0


FLAG_NOTES = {
    "single-threaded": "one person replies. The most common way a good deal dies is the "
                       "champion leaving, and it is preventable with notice",
    "no-reply-ever": "outbound logged, contacts present, no genuine reply. Different "
                     "from stalled: stalled went quiet, this never started",
    "ghost-roles": "the people on the contact-role list are not the people carrying this "
                   "deal. The CRM structure and the real relationship have come apart",
    "auto-reply-only": "every inbound is machine-generated. Verify the people before "
                       "spending more outreach on them",
}


def flags(root, as_json=False, open_only=True):
    schema, rows, _p = read_contacts(root)
    if schema is None or not rows:
        msg = ("No contact data in this folder, so the threading flags cannot be "
               "computed. Say that rather than reporting no risk — they are different "
               "statements.")
        print(json.dumps({"available": False, "note": msg}) if as_json else msg)
        return 0

    _bc, by_id, oschema = opp_index(root)
    stages = next((c.get("values") for c in oschema["columns"]
                   if c["name"] == "stage"), [])

    per_opp = {}
    for r in rows:
        per_opp.setdefault(r.get("opportunity_id", ""), []).append(r)

    out = {}
    for oid, people in sorted(per_opp.items()):
        opp = by_id.get(oid)
        if not opp or (open_only and not opp["open"]):
            continue
        rank = stage_rank(opp["stage"], stages)
        replied = [p for p in people if p.get("replied", "").lower() == "yes"]
        undet = [p for p in people if not p.get("replied", "")]
        outbound = sum(int(p.get("outbound_count") or 0) for p in people)
        autos = sum(int(p.get("auto_replies_count") or 0) for p in people)
        role_people = [p for p in people if p.get("source") in ("contact-role", "both")]
        activity_people = [p for p in people if p.get("source") in ("activity-only", "both")]
        met = [p for p in people if p.get("meeting_held", "").lower() == "yes"]

        f, why = [], []
        determinable = len(undet) < len(people)
        if determinable and len(replied) == 1 and (rank is None or rank >= 0.34):
            f.append("single-threaded")
            why.append(f"only {replied[0].get('name') or replied[0].get('email')} replies"
                       + (f" ({len(people)} contacts on the deal)" if len(people) > 1 else ""))
        # A meeting means the relationship started, whatever the mailbox says. Firing
        # "never started" on a deal that has had a demo is the kind of wrong that gets
        # every other flag ignored.
        if determinable and not replied and not met and outbound and people:
            f.append("no-reply-ever")
            why.append(f"{outbound} message(s) out, no genuine reply and no meeting from "
                       f"any of {len(people)} contact(s)")
        if role_people and activity_people:
            silent_roles = all(p.get("source") == "contact-role" for p in role_people)
            outsiders_reply = (not any(p in replied for p in role_people)
                               and any(p in replied for p in activity_people
                                       if p.get("source") == "activity-only"))
            if silent_roles or outsiders_reply:
                f.append("ghost-roles")
                why.append(
                    f"{len(role_people)} contact role(s) "
                    + ("appear in no activity at all" if silent_roles
                       else "and none of them reply; the people carrying this deal are "
                            "not on the list"))
        if determinable and not replied and autos:
            f.append("auto-reply-only")
            why.append(f"{autos} inbound message(s), all machine-generated")

        if f:
            out[oid] = {"opportunity": opp["name"], "account": opp["account_name"],
                        "stage": opp["stage"], "flags": f, "evidence": "; ".join(why),
                        "contacts": len(people), "engaged": len(replied),
                        "undetermined": len(undet)}

    if as_json:
        print(json.dumps({"available": True, "opportunities": out}, indent=1))
        return 0

    if not out:
        print(f"No threading flags across {len(per_opp)} deal(s) with contact data.")
        return 0
    print(f"{len(out)} deal(s) flagged on relationship risk. These are risk, not hygiene "
          f"— keep them out of close_plan_gaps.\n")
    for oid, d in out.items():
        print(f"{oid}  {d['opportunity']} — {d['stage']}")
        print(f"    {';'.join(d['flags'])}")
        print(f"    {d['evidence']}")
        if d["undetermined"]:
            print(f"    {d['undetermined']} of {d['contacts']} contact(s) have no "
                  f"determinable direction — treat the counts as a floor")
        print()
    for name in sorted({x for d in out.values() for x in d["flags"]}):
        print(f"  {name}: {FLAG_NOTES[name]}")
    return 0


# ------------------------------------------------------------------------------ plan


def plan(root):
    block = activity_block(root)
    if not block:
        print("crm-profile/field-map.json has no `activity` block.\n")
        print("Without it nothing here knows which object holds contact roles, which "
              "holds email,\nwhich holds meetings, or whether this org records message "
              "direction at all.\n")
        print("configure-project builds it by introspection and confirms it with you, "
              "including the\ncase where the answer is 'this CRM cannot tell you "
              "direction' — which is a real\nanswer and changes what the flags are "
              "allowed to claim.")
        return 1

    d = G.dialect_for(G.load_field_map(root))
    soql = d.get("query_language") == "soql"
    ro, ef, mf = (block.get("contact_role_fields") or {},
                  block.get("email_fields") or {}, block.get("meeting_fields") or {})

    def section(title, obj, fields, note=""):
        print(f"{title}")
        if not obj:
            print("  not recorded in the profile — this evidence will be missing\n")
            return
        names = [v for v in fields.values() if v]
        print(f"  object: {obj}")
        print(f"  fields: {', '.join(names) or '(none recorded)'}")
        if soql and names:
            print(f"  SELECT {', '.join(dict.fromkeys(names))} FROM {obj}")
        if note:
            print(f"  {note}")
        print()

    section("1. Contact roles — who the CRM says is on the deal",
            block.get("contact_role_object"), ro,
            "Necessary and not sufficient. Being on this list says nothing about "
            "whether\n  someone answers.")
    section("2. Email — who is talking, and which way",
            block.get("email_object"), ef,
            f"direction semantics: {block.get('email_direction_semantics') or 'none'}")
    section("3. Meetings — the strongest evidence, and usually the sparsest",
            block.get("meeting_object"), mf,
            "Most orgs link very few meetings to an opportunity. Pull account-linked "
            "ones too\n  and pass an `accounts` map; the account-dated rung is recorded "
            "as weaker evidence.")

    sem = (block.get("email_direction_semantics") or "none").lower()
    if sem == "none":
        print("This org has no usable direction flag. `replied` will be blank and "
              "engagement\n`undetermined` throughout — which is the correct output, not "
              "a broken one.\n")
    print("Hand the result back as:")
    print(json.dumps({"user_emails": ["you@yourcompany.com"],
                      "accounts": {"<account crm id>": ["<opportunity crm id>"]},
                      "contact_roles": ["<records>"], "emails": ["<records>"],
                      "meetings": ["<records>"]}, indent=1))
    print("\nRecords may use your CRM's field names (the profile maps them) or the "
          "canonical\nkeys. Then:")
    print(f"  contacts_sync.py --build {root} --input payload.json")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan")
    ap.add_argument("--build")
    ap.add_argument("--rollup")
    ap.add_argument("--flags")
    ap.add_argument("--input")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all-stages", action="store_true",
                    help="Include closed deals in --flags")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    root = os.path.abspath(a.plan or a.build or a.rollup or a.flags or "")
    if not root or not os.path.isdir(os.path.join(root, G.SYSTEM_DIR)):
        print("error: pass a project root that contains .sales-system", file=sys.stderr)
        return 2
    G.set_dialect(root)

    if a.plan:
        return plan(root)
    if a.build:
        if not a.input:
            print("error: --build needs --input payload.json", file=sys.stderr)
            return 2
        with open(a.input, encoding="utf-8") as f:
            return build(root, json.load(f), dry_run=a.dry_run)
    if a.rollup:
        return rollup(root)
    if a.flags:
        return flags(root, as_json=a.json, open_only=not a.all_stages)
    ap.print_help()
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except G.DestructiveWrite as e:
        print(f"\n{e}\n", file=sys.stderr)
        sys.exit(1)
