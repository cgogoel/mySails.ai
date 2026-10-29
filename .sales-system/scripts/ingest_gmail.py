#!/usr/bin/env python3
"""
ingest_gmail.py — turn a mailbox read into the activity ingest, without hand-built JSON.

The daily brief's mail read is the step that most often went wrong in the field, and not
because the rule was unclear. The run had to (1) query the mailbox, (2) work out a date,
a direction and a counterpart for every message, (3) guess a deal id from a domain map,
(4) write a JSON payload by hand, and (5) remember to call --ingest. Under time pressure
runs did (1), skipped the rest, and wrote "ingest not run" in the brief — for a month.
Steps 2 to 5 are mechanical, so they live here.

What a run hands in is whatever the connector returned, with the day it asked about:

  {"user_emails": ["me@example.com"],                  # optional; config owner is used
   "days": [                                           # one entry per query that ran
     {"date": "2026-10-28", "folder": "sent",  "response": <search_threads result>},
     {"date": "2026-10-28", "folder": "received", "response": <search_threads result>}],
   "threads": [<get_thread result>, ...],              # optional: dated, exact
   "rows": [["2026-10-28", "out", "jane@acme.com", "Pricing"], ...]}   # optional tuples

`rows` may also be objects ({date, direction, address, subject}), or the input may be a
.tsv of `date<TAB>direction<TAB>address<TAB>subject`. Use whichever the run already has;
the raw `response` is preferred because nothing has to be transcribed.

Why per-day queries (see the daily-brief skill, *Mailbox connector notes*): this Gmail
connector's thread search returns no message dates in either view and no page token, so
the only trustworthy date for a search hit is the day the query was bounded to, and the
only way to get everything is a window small enough to fit one page. A day whose query
returned the page size exactly (50) is SATURATED — split it, don't trust it. A weekday
whose queries both came back empty is SUSPECT — the connector has been seen to return {}
for days that had mail; re-run it once and pass the day to --confirm-empty if it is
genuinely empty.

"received", not "inbox": the received-mail query is `-in:sent`, never `in:inbox`. A user who
archives, or whose filters skip the inbox, keeps most customer replies outside it — in one
live mailbox every customer reply on a given day was archived, and an `in:inbox` read
recorded zero inbound for a month of briefs. `inbox` is still accepted as a folder name. Both are recorded in the cache meta and surface in the Preflight line.

One-sided days. A day with sent mail and no received mail is SUSPECT too, the same as a day
with none. On 2026-10-29 a live run read 9 outbound and 0 inbound for the day and its
Preflight said OK; the mailbox held 35 received threads that day, three of them customer
replies. The received query had come back short. A working day
on which the user wrote to customers and nobody wrote back is possible, but rare enough that
re-running that one query is the cheap check. `--confirm-empty` accepts these days too.

Every weekday in the window must have both a `sent` and a received query in `days`; one that
is missing is listed in `unqueried` and fails the Preflight. Without that, a run that only
queried the sent folder looks the same as a quiet inbox.

Who counts as "us". `owner_aliases:` in config.md adds the user's other addresses (an old
company domain, a shared sales@ alias they send from); `internal_domains:` adds colleagues'
domains beyond the owner's own. Both are comma-separated. A company that renamed itself keeps
the old domain in live use for years, and without it colleagues on the old domain read as
customers.

Deal attribution is not done here. activity_sync's ingest resolves every event — deal
contact address, lead address, then a domain that names exactly one open deal — so mail,
calendar and CRM events are all matched by one implementation.

Usage:
  ingest_gmail.py <project> --input read.json --since 2026-10-28 --until 2026-10-29
                  [--confirm-empty 2026-10-26,...] [--user-email me@x.com] [--dry-run] [--json]

  --since is inclusive, --until exclusive (Gmail's after:/before:). The window becomes
  the gmail source's watermark, so state the window that was actually read.

Exit: 0 ingested (warnings may be printed); 1 nothing usable / bad input; 2 usage.
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PAGE_MAX = 50
_ADDR = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def _addr(s):
    m = _ADDR.search(s or "")
    return m.group(0).lower() if m else ""


def _addrs(v):
    if not v:
        return []
    if isinstance(v, str):
        v = re.split(r"[,;]", v)
    return [a for a in (_addr(x) for x in v) if a]


def _day(s):
    s = (s or "").strip()
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else ""


def weekdays(since, until):
    d, end = date.fromisoformat(since), date.fromisoformat(until)
    while d < end:
        if d.weekday() < 5:
            yield d.isoformat()
        d += timedelta(days=1)


def _csv_config(project, key):
    import activity_sync as A
    raw = A.config_value(project, key, "") or ""
    return [x.strip().lower() for x in re.split(r"[,;\s]+", raw) if x.strip()]


class Read:
    def __init__(self, user_emails, internal_domains=()):
        self.user = [u.lower() for u in user_emails if u]
        self.user_domains = {u.split("@")[-1] for u in self.user if "@" in u}
        self.user_domains.update(d.lstrip("@").lower() for d in internal_domains if d)
        self.events = {}            # (date, dir, addr) -> subject
        self.per_day = {}           # date -> {"in": n, "out": n, "queried": set()}
        self.saturated, self.internal, self.no_counterpart = [], 0, 0

    def mine(self, a):
        return a in self.user

    def internal_addr(self, a):
        return a.split("@")[-1] in self.user_domains

    def day(self, d):
        return self.per_day.setdefault(d, {"in": 0, "out": 0, "queried": set()})

    def add(self, d, direction, addr, subject):
        if not d or direction not in ("in", "out"):
            return
        if not addr:
            self.no_counterpart += 1
            return
        if self.mine(addr) or self.internal_addr(addr):
            self.internal += 1
            return
        k = (d, direction, addr)
        if k not in self.events:
            self.events[k] = (subject or "")[:120]
            self.day(d)[direction] += 1

    def message(self, m, fallback_day, folder=None):
        """One message. Its own date when the connector gave one, else the query day."""
        d = _day(m.get("date") or m.get("internalDateIso") or "") or fallback_day
        sender = _addr(m.get("sender") or m.get("from") or "")
        subj = m.get("subject") or ""
        if sender and self.mine(sender):
            for a in _addrs(m.get("toRecipients")) + _addrs(m.get("ccRecipients")) + \
                    _addrs(m.get("to")) + _addrs(m.get("cc")):
                self.add(d, "out", a, subj)
            return "out"
        if sender:
            self.add(d, "in", sender, subj)
            return "in"
        return None

    def search_day(self, d, folder, resp):
        """A search hit tells us a message in this folder fell on this day — not which of
        the (at most five, oldest-first) previewed messages it was. So: in a sent-folder
        hit, the user's own previewed messages give the recipients; in an inbox hit, the
        external senders do. When the preview holds none (the matching message is newer
        than the five shown), the thread's external participants stand in, dated today."""
        self.day(d)["queried"].add(folder)
        threads = (resp or {}).get("threads") or []
        if len(threads) >= PAGE_MAX:
            self.saturated.append(f"{d} {folder}")
        want = "out" if folder == "sent" else "in"     # "received" / "inbox" / anything else
        for t in threads:
            msgs = t.get("messages") or []
            got = False
            for m in msgs:
                sender = _addr(m.get("sender") or "")
                if (want == "out") == bool(sender and self.mine(sender)):
                    # Search previews carry no dates: the query day is the date. A dated
                    # message (some connector versions) keeps its own.
                    self.message(m, d)
                    got = True
            if not got and msgs:
                people = set()
                for m in msgs:
                    people.update(_addrs(m.get("toRecipients")) + _addrs(m.get("ccRecipients"))
                                  + [_addr(m.get("sender") or "")])
                subj = next((m.get("subject") for m in msgs if m.get("subject")), "")
                for a in sorted(p for p in people if p):
                    self.add(d, want, a, subj)

    def thread(self, t):
        for m in (t or {}).get("messages") or []:
            if _day(m.get("date") or ""):
                self.message(m, "")

    def row(self, r):
        if isinstance(r, dict):
            d, direction = _day(r.get("date")), (r.get("direction") or "").lower()[:3]
            a = _addr(r.get("address") or r.get("counterpart_email") or "")
            s = r.get("subject") or r.get("detail") or ""
        else:
            r = list(r) + ["", "", "", ""]
            d, direction, a, s = _day(r[0]), str(r[1]).lower()[:3], _addr(r[2]), r[3]
        direction = {"inb": "in", "in": "in", "out": "out", "sen": "out"}.get(direction, "")
        self.add(d, direction, a, s)


def load_input(path):
    if path.endswith(".tsv"):
        with open(path, encoding="utf-8") as f:
            return {"rows": [r for r in csv.reader(f, delimiter="\t") if r and r[0][:1].isdigit()]}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {"rows": data} if isinstance(data, list) else data


def build(project, data, since, until, confirm_empty=(), extra_users=()):
    import activity_sync as A
    _, owner_email = A.user_identity(project)
    users = list(dict.fromkeys([*([owner_email] if owner_email else []),
                                *(data.get("user_emails") or []), *extra_users,
                                *_csv_config(project, "owner_aliases")]))
    if not users:
        raise SystemExit("error: no user address — set `owner: Name <email>` in "
                         "00-Config/config.md or pass --user-email. Direction cannot be "
                         "derived without it.")
    rd = Read(users, _csv_config(project, "internal_domains"))
    for d in data.get("days") or []:
        rd.search_day(_day(d.get("date")), (d.get("folder") or "inbox").lower(),
                      d.get("response"))
    for t in data.get("threads") or []:
        rd.thread(t)
    for r in data.get("rows") or []:
        rd.row(r)

    in_window = {k: v for k, v in rd.events.items() if since <= k[0] < until}
    outside = len(rd.events) - len(in_window)
    events = [{"date": d, "kind": "email", "direction": direction,
               "from": (users[0] if direction == "out" else addr),
               "counterpart_email": addr, "detail": subj}
              for (d, direction, addr), subj in sorted(in_window.items())]

    confirm = set(confirm_empty)
    today = date.today().isoformat()
    pd = lambda d, k: rd.per_day.get(d, {}).get(k, 0)    # noqa: E731
    suspect = [d for d in weekdays(since, until)
               if d not in confirm and pd(d, "in") + pd(d, "out") == 0 and d < today]
    # Sent mail but nothing received: the received query came back short (see the
    # docstring). Today counts too — the user is writing, so the inbox is not asleep.
    one_sided = [d for d in weekdays(since, until)
                 if d not in confirm and pd(d, "out") > 0 and pd(d, "in") == 0]
    unqueried = []
    if data.get("days"):
        for d in weekdays(since, until):
            if d > today:
                continue
            q = rd.per_day.get(d, {}).get("queried", set())
            if "sent" not in q:
                unqueried.append(f"{d} sent")
            if not (q - {"sent"}):
                unqueried.append(f"{d} received")
    n_in = sum(1 for e in events if e["direction"] == "in")
    n_out = len(events) - n_in
    read = {"in": n_in, "out": n_out, "days": len(list(weekdays(since, until))),
            "suspect_empty_days": suspect, "one_sided_days": one_sided,
            "unqueried": unqueried, "saturated": rd.saturated,
            "internal_dropped": rd.internal, "no_counterpart": rd.no_counterpart,
            "outside_window": outside, "confirmed_empty": sorted(confirm)}
    payload = {"source": "gmail", "user_emails": users,
               "window": {"since": since, "until": until}, "read": read, "events": events}
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("project")
    ap.add_argument("--input", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", required=True)
    ap.add_argument("--confirm-empty", default="")
    ap.add_argument("--user-email", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    project = os.path.abspath(a.project)
    for v in (a.since, a.until):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            print(f"error: dates are YYYY-MM-DD, got {v!r}", file=sys.stderr)
            return 2
    if a.since >= a.until:
        print("error: --until is exclusive and must be after --since", file=sys.stderr)
        return 2
    try:
        data = load_input(a.input)
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: could not read {a.input}: {e}", file=sys.stderr)
        return 1
    confirm = [x.strip() for x in a.confirm_empty.split(",") if x.strip()]
    payload = build(project, data, a.since, a.until, confirm, a.user_email)
    r = payload["read"]

    import activity_sync as A
    out_p = os.path.join(A.cache_dir(project), f"gmail-ingest-{a.since}-{a.until}.json")
    A.save_json(out_p, payload)
    print(f"gmail read {a.since} .. {a.until} (exclusive): {r['in']} inbound and "
          f"{r['out']} outbound counterpart-messages, {r['internal_dropped']} internal "
          f"dropped; payload {os.path.relpath(out_p, project)}")
    if r["suspect_empty_days"]:
        print(f"SUSPECT: no mail in either folder on weekday(s) "
              f"{', '.join(r['suspect_empty_days'])}. This connector has returned {{}} for "
              "days that had mail. Re-run those days' queries once; if still empty, "
              "re-run this with --confirm-empty.")
    if r["one_sided_days"]:
        print(f"SUSPECT: sent mail but nothing received on {', '.join(r['one_sided_days'])}. "
              "The received query most likely came back short. Re-run that day's "
              "`-in:sent` query once; if it is still empty of outside senders, re-run this "
              "with --confirm-empty.")
    if r["unqueried"]:
        print(f"UNQUERIED: no query was handed in for {', '.join(r['unqueried'])}. Every "
              "weekday in the window needs both a sent and a received query.")
    if r["saturated"]:
        print(f"SATURATED: {', '.join(r['saturated'])} returned a full page ({PAGE_MAX}). "
              "There is no page token — split that day (e.g. by `category:` or by "
              "`after:`/`before:` epoch seconds) and re-run, or the rest is unread.")
    if r["out"] == 0 and r["days"] >= 2:
        print("WARNING: zero outbound over a multi-day window. Over a working week that is "
              "a failed sent-folder query, not a quiet user.")
    if r["in"] == 0 and r["days"] >= 2:
        print("WARNING: zero inbound over a multi-day window. Check the received query is "
              "`-in:sent …`, not `in:inbox` — archived replies live outside the inbox.")
    if not payload["events"]:
        print("nothing to ingest")
        if a.json:
            print(json.dumps({"read": r, "ingested": False}))
        return 1 if not data else 0
    if a.dry_run:
        print("dry run: not ingested")
        return 0
    rc = A.ingest(project, payload)
    if a.json:
        meta = A.load_json(A.cache_paths(project)[1], {})
        print(json.dumps({"read": r, "ingested": rc == 0,
                          "gmail": (meta.get("sources") or {}).get("gmail")}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
