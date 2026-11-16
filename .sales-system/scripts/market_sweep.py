#!/usr/bin/env python3
"""
market_sweep.py — the daily brief's news sweep, planned and evidenced.

From 2026-10-29 to 2026-11-16 one live folder's daily brief carried no web news and no
newsletter summaries, and nothing noticed. Three causes, each closed here:

  1. Nothing enforced the sweep. run_integrity.py checked every other step's evidence;
     this one had none, was "run last and kept short", and printed nothing on a quiet
     morning — so a missing section looked exactly like a quiet one. The watchlist's
     last_checked had not moved since August. Now `--record` writes the evidence,
     run_integrity.py requires it (step `market_sweep`), and `--record` stamps
     last_checked on every watchlist row swept.
  2. Newsletters were never fetched. The sweep read "messages since the last brief",
     which meant the activity ingest, which excludes Gmail's Promotions category — where
     Gmail files nearly every newsletter. `--plan` builds the sweep's own query from the
     watchlist's Newsletter (and mail-delivered Feed) senders, with no category filter.
  3. The search budget left out what the user watches. Competitors were never searched,
     nor customers outside the renewal window, nor most prospects. `--plan` builds four
     groups — competitors (all, every run), customers and prospects (a daily tier plus a
     weekday rotation that covers everyone weekly), and market themes — and `--begin`
     (through `overdue()`) flags any account not searched in 7 days.

Commands:

  --plan    <project> [--meeting NAME ...] [--today D] [--json]
            What to read and search this run. Writes cache/market-sweep-plan.json so
            --record can compare what was done against what was due.
  --record  <project> --json <payload.json | -> [--today D]
            The evidence. Payload (all keys optional except `searched`):
              {"newsletters": {"issues_read": 3, "senders": ["news@x.com"], "kept": 1},
               "searched": {"competitors": ["COMP-0001", ...],
                            "customers":   ["<key from the plan>", ...],
                            "prospects":   ["<key>", ...],
                            "themes":      ["WATCH-0007", ...]},
               "searches_run": {"competitors": 4, "customers": 6, ...},
               "kept": {"customers": 0, "prospects": 1, "competitors": 0, "themes": 0},
               "signals_logged": ["SIG-0042"]}
            Stores the run, advances last-searched per account, stamps last_checked on
            every watchlist row swept, and prints the coverage line.
  --line    <project>         the coverage line of the latest record
  --status  <project> [--json]  accounts overdue (not searched in 7 days), last run

Exit codes: 0 ok; 1 --record found plan items not covered (recorded anyway, reported as
gaps, and run_integrity fails the run on them); 2 usage.

Config (00-Config/config.md, flat keys, all optional — defaults shown):
  news_sweep_required: true            news_sweep_window_days: 3
  news_sweep_newsletters: true         news_sweep_competitors: all     (all | off)
  news_sweep_customers: tiered         news_sweep_prospects: tiered    (tiered | daily | off)
  news_sweep_market_themes: true       news_sweep_customer_renewal_days: 90
  news_sweep_prospect_close_days: 60   news_sweep_prospect_top_n: 10
  news_sweep_quiet_morning: coverage_line   (coverage_line | silent)
  news_sweep_content_lens: label            (label | off)
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import activity_sync as A  # noqa: E402

RECORD = "market-sweep.json"
PLAN = "market-sweep-plan.json"
OVERDUE_DAYS = 7
GROUPS = ("competitors", "customers", "prospects", "themes")
LABEL = {"competitors": "competitors", "customers": "customers", "prospects": "prospects",
         "themes": "market themes"}

DEFAULTS = {
    "news_sweep_required": "true",
    "news_sweep_window_days": "3",
    "news_sweep_newsletters": "true",
    "news_sweep_competitors": "all",
    "news_sweep_customers": "tiered",
    "news_sweep_prospects": "tiered",
    "news_sweep_market_themes": "true",
    "news_sweep_customer_renewal_days": "90",
    "news_sweep_prospect_close_days": "60",
    "news_sweep_prospect_top_n": "10",
    "news_sweep_quiet_morning": "coverage_line",
    "news_sweep_content_lens": "label",
}
# The order configure-project writes them and update-system adds them in.
KEY_ORDER = list(DEFAULTS)

THEME_KINDS = {"theme", "regulation", "technology", "publication", "person", "event"}
SOURCE_KINDS = {"newsletter", "feed"}
ACCOUNT_KINDS = {"account", "prospect"}
CLOSED_RENEWAL = {"churned", "renewed", "auto-renewed"}
LEAD_OUT = {"disqualified", "do not contact", "junk", "customer or partner"}
YES = {"yes", "true", "1", "y", "on"}

# Terms that make a company-name query a news query rather than a homepage lookup.
LOOK_FOR = {
    "competitors": "funding, acquisition, product or pricing change, federal award, "
                   "leadership move",
    "customers": "breach or incident, leadership change, budget cut, reorganisation, "
                 "new mobile programme",
    "prospects": "breach or incident, leadership change, budget cut, reorganisation, "
                 "new mobile programme, RFP/RFI, contract award",
}
QUERY_TERMS = {
    "competitors": "funding OR acquisition OR launch OR pricing OR contract OR CEO",
    "customers": "mobile OR security OR breach OR CIO OR CISO OR budget",
    "prospects": "mobile OR security OR breach OR contract OR RFP OR CIO OR CISO",
}


# ------------------------------------------------------------------------- config

def cfg(root, key):
    """config_value with the shipped default, and a trailing `# comment` ignored —
    config.md documents the allowed values beside each key."""
    raw = A.config_value(root, key, DEFAULTS.get(key, ""))
    raw = re.sub(r"\s+#.*$", "", str(raw)).strip()
    return raw or DEFAULTS.get(key, "")


def cfg_bool(root, key):
    return cfg(root, key).lower() in YES


def cfg_int(root, key):
    try:
        return int(cfg(root, key))
    except ValueError:
        return int(DEFAULTS[key])


def required(root):
    return cfg_bool(root, "news_sweep_required")


# ---------------------------------------------------------------------- helpers

def now():
    return datetime.now(timezone.utc)


def D(v):
    s = str(v or "").strip()[:10]
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def norm(name):
    """Account key: the name a human would recognise as the same organisation.
    Rotation and last-searched are kept per account, not per record — one account with
    three deals and two leads is one search, on one weekday."""
    s = (name or "").lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9& ]+", " ", s)
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|the|plc|gmbh|lp|llp)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def slot_of(key, n):
    """Stable, even weekday slot. sha1 rather than hash(): Python salts str hashes per
    process, and a rotation that reshuffles every run is not a rotation."""
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % n


def rows(root, rel):
    i, rs = A._registry_rows(root, rel)
    return i, rs


def getter(i):
    return lambda r, c: (str(r[i[c]]).strip() if c in i and i[c] < len(r) and r[i[c]] is not None
                         else "")


def brief_slots(root):
    """The brief's weekdays in order (Mon=0). The rotation spreads accounts across them."""
    try:
        import run_integrity as R
        return sorted(R.brief_days(root))
    except Exception:
        return [0, 1, 2, 3, 4]


def load_record(root):
    return A.load_json(os.path.join(A.cache_dir(root), RECORD),
                       {"runs": [], "last_searched": {}, "first_run": ""})


def save_record(root, data):
    data["runs"] = data["runs"][-60:]
    A.save_json(os.path.join(A.cache_dir(root), RECORD), data)


def last_brief_date(root, today):
    """Where the newsletter query starts: the previous sweep's day, else the previous daily
    brief's, else the window. Inclusive of that day — a newsletter that landed at 07:00 on a
    day the brief ran at 06:30 has not been read."""
    rec = load_record(root)
    days = [r.get("date", "") for r in rec.get("runs", []) if r.get("date", "") < today.isoformat()]
    if days:
        return D(max(days))
    import glob
    have = []
    for p in glob.glob(os.path.join(root, "09-Briefs", "Daily", "*-daily-brief*.md")):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", os.path.basename(p))
        if m and m.group(1) < today.isoformat():
            have.append(m.group(1))
    if have:
        return D(max(have))
    return today - timedelta(days=cfg_int(root, "news_sweep_window_days"))


# ------------------------------------------------------------------------ groups

def partner_names(root):
    i, rs = rows(root, "11-Partners/partners.csv")
    g = getter(i)
    return {norm(g(r, "name")) for r in rs if g(r, "name")}


def excluded_stages(root):
    try:
        import csvguard as G
        import floor_check as F
        return F.excluded_stages(G.load_field_map(root) or {})
    except Exception:
        return set()


def renewal_types(root):
    try:
        import csvguard as G
        import floor_check as F
        return F.renewal_marker(root, G.load_field_map(root) or {})
    except Exception:
        return {"renewal", "existing business"}


def meetings_today(root, today, extra=()):
    """Accounts with a meeting today: names the run passes (--meeting), plus meeting events
    dated today in the activity cache, mapped back to their deal's or lead's account."""
    out = {norm(x) for x in extra if norm(x)}
    t = today.isoformat()
    cache = A.load_json(A.cache_paths(root)[0], {})
    lc = A.load_json(A.lead_cache_path(root), {})
    opp_ids = {k for k, v in cache.items() if any(e.get("kind") == "meeting" and
                                                    (e.get("date") or "")[:10] == t for e in v)}
    lead_ids = {k for k, v in lc.items() if any(e.get("kind") == "meeting" and
                                                  (e.get("date") or "")[:10] == t for e in v)}
    if opp_ids:
        i, rs = rows(root, "07-Opportunities/opportunities.csv")
        g = getter(i)
        out |= {norm(g(r, "account_name")) for r in rs if g(r, "id") in opp_ids}
    if lead_ids:
        i, rs = rows(root, "06-Leads/leads.csv")
        g = getter(i)
        out |= {norm(g(r, "company")) for r in rs if g(r, "id") in lead_ids}
    out.discard("")
    return out


def watch_rows(root):
    i, rs = rows(root, "03-Market/watchlist.csv")
    g = getter(i)
    out = []
    for r in rs:
        if g(r, "enabled").lower() not in YES:
            continue
        out.append({"id": g(r, "id"), "term": g(r, "term"), "kind": g(r, "kind").lower(),
                    "lens": (g(r, "lens") or "deal").lower(), "cadence": g(r, "cadence").lower(),
                    "sources": [s.strip() for s in g(r, "sources").split(";") if s.strip()],
                    "linked_account": g(r, "linked_account"), "linked_id": g(r, "linked_id"),
                    "why": g(r, "why")})
    return out, bool(i)


def build(root, today, meeting_names=()):
    """The four groups. Each entry: key, name, ids (records it stands for), tier
    (daily | rotation | overdue), reason."""
    slots = brief_slots(root)
    wd = today.weekday()
    pos = slots.index(wd) if wd in slots else None
    meet = meetings_today(root, today, meeting_names)
    rec = load_record(root)
    last = rec.get("last_searched", {})
    first = D(rec.get("first_run"))

    def overdue(gk, key):
        """Not searched in more than OVERDUE_DAYS — searched exactly a week ago is the
        rotation coming round, not a miss. Never searched counts only once the sweep has
        been recording that long — the first week after upgrading is the rotation's first
        lap, not a backlog."""
        ls = D(last.get(f"{gk}:{key}"))
        if ls:
            return (today - ls).days > OVERDUE_DAYS
        return bool(first and (today - first).days > OVERDUE_DAYS)

    def tier_of(gk, key, daily_reason, mode):
        if mode == "daily":
            return "daily", "searched daily (config)"
        if daily_reason:
            return "daily", daily_reason
        if overdue(gk, key):
            return "overdue", f"not searched in {OVERDUE_DAYS}+ days"
        n = len(slots)
        if pos is not None and slot_of(key, n) == pos:
            return "rotation", "today's rotation"
        return None, ""

    wl, has_wl = watch_rows(root)
    lens_mode = cfg(root, "news_sweep_content_lens").lower()
    groups = {g: [] for g in GROUPS}

    # ---- competitors: every row, every run
    if cfg(root, "news_sweep_competitors").lower() != "off":
        i, rs = rows(root, "04-Competitors/competitors.csv")
        g = getter(i)
        for r in rs:
            if not g(r, "name"):
                continue
            groups["competitors"].append({
                "key": g(r, "id") or norm(g(r, "name")), "name": g(r, "name"),
                "aliases": g(r, "aliases"), "ids": [g(r, "id")], "tier": "daily",
                "reason": "every competitor, every run",
                "query": f"\"{g(r, 'name')}\" {QUERY_TERMS['competitors']}"})

    # ---- customers: active contracts in renewals (customers registry when renewals is off)
    cust = {}
    cmode = cfg(root, "news_sweep_customers").lower()
    rdays = cfg_int(root, "news_sweep_customer_renewal_days")
    if cmode != "off":
        i, rs = rows(root, "08-Renewals/renewals.csv")
        g = getter(i)
        for r in rs:
            name = g(r, "account_name")
            if not name or g(r, "status").lower() in CLOSED_RENEWAL:
                continue
            end = D(g(r, "contract_end_date"))
            if end and end < today:
                continue
            c = cust.setdefault(norm(name), {"name": name, "ids": [], "end": None})
            c["ids"].append(g(r, "id"))
            if end and (c["end"] is None or end < c["end"]):
                c["end"] = end
        if not rs:
            i, rs = rows(root, "02-Context/Customers/customers.csv")
            g = getter(i)
            for r in rs:
                name = g(r, "account_name")
                end = D(g(r, "contract_end"))
                if not name or (end and end < today):
                    continue
                c = cust.setdefault(norm(name), {"name": name, "ids": [], "end": end})
                c["ids"].append(g(r, "id"))

    # ---- prospects: open opportunities (not excluded stages, not renewals, not partners)
    #      and leads not disqualified
    pros = {}
    pmode = cfg(root, "news_sweep_prospects").lower()
    if pmode != "off":
        skip = excluded_stages(root)
        renew = renewal_types(root)
        partners = partner_names(root)
        i, rs = rows(root, "07-Opportunities/opportunities.csv")
        g = getter(i)
        for r in rs:
            name, stage = g(r, "account_name"), g(r, "stage")
            if not name or stage.startswith("Closed") or stage.lower() in skip:
                continue
            if g(r, "type").lower() in renew or norm(name) in partners:
                continue
            k = norm(name)
            if k in cust:
                continue
            try:
                amt = float((g(r, "converted_amount") or g(r, "amount") or "0").replace(",", ""))
            except ValueError:
                amt = 0.0
            close = D(g(r, "close_date"))
            p = pros.setdefault(k, {"name": name, "ids": [], "close": None, "amount": 0.0})
            p["ids"].append(g(r, "id"))
            p["amount"] = max(p["amount"], amt)
            if close and (p["close"] is None or close < p["close"]):
                p["close"] = close
        top = sorted(pros, key=lambda k: -pros[k]["amount"])[:cfg_int(root, "news_sweep_prospect_top_n")]
        top = {k for k in top if pros[k]["amount"] > 0}
        i, rs = rows(root, "06-Leads/leads.csv")
        g = getter(i)
        for r in rs:
            name = g(r, "company")
            st = g(r, "status").lower()
            if not name or st in LEAD_OUT or g(r, "converted_opp_id"):
                continue
            k = norm(name)
            if not k or k in cust or k in partners:
                continue
            p = pros.setdefault(k, {"name": name, "ids": [], "close": None, "amount": 0.0})
            p["ids"].append(g(r, "id"))

    # ---- watchlist Account / Prospect rows fold into those groups
    wl_daily = set()
    for w in wl:
        if w["kind"] not in ACCOUNT_KINDS:
            continue
        name = w["linked_account"] or w["term"]
        k = norm(name)
        if not k:
            continue
        if k in cust or (w["kind"] == "account" and k not in pros):
            if cmode == "off":
                continue
            c = cust.setdefault(k, {"name": name, "ids": [], "end": None})
            c["ids"].append(w["id"])
        else:
            if pmode == "off":
                continue
            p = pros.setdefault(k, {"name": name, "ids": [], "close": None, "amount": 0.0})
            p["ids"].append(w["id"])
        if w["cadence"] == "daily":
            wl_daily.add(k)

    for k, c in sorted(cust.items()):
        reason = ""
        if c["end"] and (c["end"] - today).days <= rdays:
            reason = f"renewal {c['end'].isoformat()} (inside {rdays} days)"
        elif k in meet:
            reason = "meeting today"
        elif k in wl_daily:
            reason = "watchlist row, cadence Daily"
        tier, why = tier_of("customers", k, reason, cmode)
        if tier:
            groups["customers"].append({"key": k, "name": c["name"], "ids": c["ids"], "tier": tier,
                                        "reason": why,
                                        "query": f"\"{c['name']}\" {QUERY_TERMS['customers']}"})
    if pmode != "off":
        cdays = cfg_int(root, "news_sweep_prospect_close_days")
        for k, p in sorted(pros.items()):
            reason = ""
            if p["close"] and 0 <= (p["close"] - today).days <= cdays:
                reason = f"closing {p['close'].isoformat()} (inside {cdays} days)"
            elif p["close"] and p["close"] < today:
                reason = f"close date {p['close'].isoformat()} already past"
            elif k in top:
                reason = "top deals by amount"
            elif k in meet:
                reason = "meeting today"
            elif k in wl_daily:
                reason = "watchlist row, cadence Daily"
            tier, why = tier_of("prospects", k, reason, pmode)
            if tier:
                groups["prospects"].append({"key": k, "name": p["name"], "ids": p["ids"],
                                            "tier": tier, "reason": why,
                                            "query": f"\"{p['name']}\" {QUERY_TERMS['prospects']}"})

    # ---- market themes: Daily and Weekly subject rows, every run
    if cfg_bool(root, "news_sweep_market_themes"):
        for w in wl:
            if w["kind"] not in THEME_KINDS or w["cadence"] not in ("daily", "weekly"):
                continue
            if w["lens"] == "content" and lens_mode == "off":
                continue
            groups["themes"].append({"key": w["id"], "name": w["term"], "ids": [w["id"]],
                                     "tier": "daily", "lens": w["lens"],
                                     "reason": f"watchlist {w['kind']}, {w['cadence']}",
                                     "query": w["term"]})
        # A web Feed is a source, not a subject: checked for anything touching the other
        # groups, with a site-restricted search. A mail-delivered Feed is read with the
        # newsletters instead.
        for w in wl:
            if w["kind"] != "feed" or w["cadence"] not in ("daily", "weekly"):
                continue
            web = [s for s in w["sources"] if "@" not in s]
            if not web or any("@" in s for s in w["sources"]):
                continue
            sites = " OR ".join("site:" + re.sub(r"^https?://", "", s).split("/")[0] for s in web)
            groups["themes"].append({"key": w["id"], "name": w["term"], "ids": [w["id"]],
                                     "tier": "daily", "lens": w["lens"],
                                     "reason": f"watchlist feed, {w['cadence']}",
                                     "query": sites})

    # ---- newsletters: their own query, every Gmail category
    news = {"enabled": cfg_bool(root, "news_sweep_newsletters"), "rows": [], "query": "",
            "since": ""}
    if news["enabled"]:
        senders, ids = [], []
        for w in wl:
            if w["kind"] not in SOURCE_KINDS:
                continue
            mail = [s for s in w["sources"] if "@" in s]
            if not mail:
                continue          # a web Feed: searched as a source, not fetched by mail
            senders += mail
            ids.append(w["id"])
            news["rows"].append({"id": w["id"], "name": w["term"], "senders": mail})
        if senders:
            since = last_brief_date(root, today)
            news["since"] = since.isoformat()
            news["query"] = (f"from:({' OR '.join(dict.fromkeys(senders))}) "
                             f"after:{since.strftime('%Y/%m/%d')}")
    return groups, news, has_wl


def plan(root, today, meeting_names=(), as_json=False):
    groups, news, has_wl = build(root, today, meeting_names)
    window = cfg_int(root, "news_sweep_window_days")
    out = {"date": today.isoformat(), "planned_at": now().isoformat(timespec="seconds"),
           "window_days": window, "since": (today - timedelta(days=window)).isoformat(),
           "newsletters": news, "groups": groups, "watchlist": has_wl,
           "content_lens": cfg(root, "news_sweep_content_lens"),
           "quiet_morning": cfg(root, "news_sweep_quiet_morning")}
    A.save_json(os.path.join(A.cache_dir(root), PLAN), out)
    if as_json:
        print(json.dumps(out, indent=1))
        return 0
    print(f"news sweep plan {today.isoformat()} — window {window} days "
          f"(since {out['since']})")
    if not has_wl:
        print("  no watchlist: no newsletter or theme sweep. Competitor, customer and prospect "
              "searches still run from their registries.")
    if news["enabled"]:
        if news["query"]:
            print(f"\nNEWSLETTERS — {len(news['rows'])} source(s). Search mail with exactly this "
                  "query (no category filter — Gmail files newsletters in Promotions), then open "
                  "every issue with get_thread/get_message and read the body:")
            print(f"  {news['query']}")
        else:
            print("\nNEWSLETTERS — no enabled Newsletter rows with a sender address.")
    else:
        print("\nNEWSLETTERS — off (news_sweep_newsletters: false)")
    for gk in GROUPS:
        items = groups[gk]
        tiers = {t: sum(1 for x in items if x["tier"] == t) for t in ("daily", "rotation", "overdue")}
        head = f"\n{LABEL[gk].upper()} — {len(items)} to search"
        if gk in ("customers", "prospects"):
            head += f" ({tiers['daily']} daily, {tiers['rotation']} rotation" + \
                    (f", {tiers['overdue']} overdue" if tiers["overdue"] else "") + ")"
        print(head)
        if gk in LOOK_FOR:
            print(f"  look for: {LOOK_FOR[gk]}")
        for x in items:
            lens = f" [lens {x['lens']}]" if x.get("lens") in ("content", "both") else ""
            print(f"  {x['key']:<28} {x['name'][:40]:<40} {x['tier']:<8} {x['reason']}{lens}")
    print("\nRecord what was done with --record; the keys above are what it expects back.")
    return 0


# ----------------------------------------------------------------------- record

def stamp_watchlist(root, ids, today):
    """last_checked on every watchlist row swept, whether or not it produced anything —
    a clock frozen since August would have flagged the silent sweep months ago."""
    ids = {x for x in ids if x}
    if not ids:
        return 0
    try:
        import csvguard as G
        schema = G.schema_by_registry(root, "market_watchlist")
        path = G.resolve_path(os.path.join(root, schema["path"]), root)
        if not os.path.exists(path):
            return 0
        header, rs = G.read_table(path, schema)
        i = {h: k for k, h in enumerate(header)}
        if "last_checked" not in i:
            return 0
        n = 0
        for r in rs:
            if r[i["id"]] in ids and r[i["last_checked"]] != today.isoformat():
                r[i["last_checked"]] = today.isoformat()
                if "last_updated" in i:
                    r[i["last_updated"]] = today.isoformat()
                n += 1
        if n:
            G.write_table(path, header, rs, schema=schema, root=root, backup=True)
        return n
    except Exception as e:  # never lose the record over a stamp
        print(f"warning: could not stamp watchlist last_checked: {e}", file=sys.stderr)
        return 0


def coverage_line(run):
    nl = run.get("newsletters") or {}
    c = run.get("counts") or {}
    kept = sum((run.get("kept") or {}).values()) + (nl.get("kept") or 0)
    bits = []
    if nl.get("enabled", True):
        bits.append(f"{nl.get('issues_read', 0)} newsletter issue(s) read")
    for gk in GROUPS:
        g = c.get(gk) or {}
        if not g.get("planned") and not g.get("searched"):
            continue
        if gk in ("customers", "prospects"):
            bits.append(f"{g.get('searched', 0)} {LABEL[gk]} searched "
                        f"({g.get('daily', 0)} daily, {g.get('rotation', 0)} rotated)")
        else:
            bits.append(f"{g.get('searched', 0)} {LABEL[gk]} searched")
    tail = f"{kept} item(s) kept" if kept else "nothing passed"
    gaps = run.get("gaps") or {}
    gap_n = sum(len(v) for v in gaps.values())
    if gap_n:
        tail += f"; {gap_n} planned search(es) not done"
    return "News sweep: " + ", ".join(bits) + " — " + tail + "."


def record(root, payload, today):
    data = load_record(root)
    pl = A.load_json(os.path.join(A.cache_dir(root), PLAN), {})
    if pl.get("date") != today.isoformat():
        groups, news, _ = build(root, today)
        pl = {"date": today.isoformat(), "groups": groups, "newsletters": news}
    searched = payload.get("searched") or {}
    nl_in = payload.get("newsletters") or {}
    counts, gaps = {}, {}
    for gk in GROUPS:
        planned = pl["groups"].get(gk, [])
        done = set(searched.get(gk) or [])
        pk = {x["key"] for x in planned}
        missing = sorted(pk - done)
        if missing:
            gaps[gk] = missing
        counts[gk] = {"planned": len(planned), "searched": len(done),
                      "daily": sum(1 for x in planned if x["key"] in done and x["tier"] == "daily"),
                      "rotation": sum(1 for x in planned if x["key"] in done and
                                      x["tier"] in ("rotation", "overdue")),
                      "extra": len(done - pk)}
        for k in done:
            data["last_searched"][f"{gk}:{k}"] = today.isoformat()
    news_planned = pl.get("newsletters") or {}
    nl = {"enabled": bool(news_planned.get("enabled", True)),
          "query": news_planned.get("query", ""),
          "sources": len(news_planned.get("rows") or []),
          "issues_read": int(nl_in.get("issues_read") or 0),
          "kept": int(nl_in.get("kept") or 0),
          "senders": nl_in.get("senders") or []}
    # A planned newsletter query with no `newsletters` block in the payload was not run:
    # "0 issues read" has to be said, not implied by an absent key.
    if nl["enabled"] and nl["query"] and not payload.get("newsletters"):
        gaps["newsletters"] = ["newsletter query not reported"]
    run = {"date": today.isoformat(), "recorded_at": now().isoformat(timespec="seconds"),
           "newsletters": nl, "counts": counts, "gaps": gaps,
           "searches_run": payload.get("searches_run") or {},
           "kept": payload.get("kept") or {},
           "signals_logged": payload.get("signals_logged") or []}
    # Watchlist rows swept: every newsletter source queried, every theme searched, every
    # folded Account/Prospect row whose account was searched.
    swept = set()
    if nl["enabled"] and nl["query"] and payload.get("newsletters"):
        swept |= {r["id"] for r in news_planned.get("rows") or []}
    swept |= set(searched.get("themes") or [])
    for gk in ("customers", "prospects"):
        done = set(searched.get(gk) or [])
        for x in pl["groups"].get(gk, []):
            if x["key"] in done:
                swept |= {i for i in x["ids"] if str(i).startswith("WATCH")}
    run["watchlist_stamped"] = stamp_watchlist(root, swept, today)
    run["line"] = coverage_line(run)
    if not data.get("first_run"):
        data["first_run"] = today.isoformat()
    data["runs"].append(run)
    save_record(root, data)
    print(run["line"])
    if run["watchlist_stamped"]:
        print(f"watchlist last_checked stamped on {run['watchlist_stamped']} row(s)")
    for gk, miss in gaps.items():
        print(f"GAP: {LABEL.get(gk, gk)} planned but not done: {', '.join(miss[:8])}"
              + (" …" if len(miss) > 8 else ""))
    return 1 if gaps else 0


# ----------------------------------------------------------------------- status

def overdue(root, today):
    """Accounts in the customer and prospect books not searched in OVERDUE_DAYS, for
    run_integrity --begin. Empty until the sweep has been recording a full week."""
    data = load_record(root)
    first = D(data.get("first_run"))
    if not first or (today - first).days <= OVERDUE_DAYS:
        return []
    groups, _, _ = build(root, today)
    return [f"{x['name']}" for gk in ("customers", "prospects") for x in groups[gk]
            if x["tier"] == "overdue"]


def latest(root):
    runs = load_record(root).get("runs") or []
    return runs[-1] if runs else None


def status(root, today, as_json=False):
    last = latest(root)
    od = overdue(root, today)
    out = {"last_run": last.get("date") if last else None,
           "last_line": last.get("line") if last else None,
           "overdue": od, "required": required(root)}
    if as_json:
        print(json.dumps(out))
    else:
        print(f"last sweep: {out['last_run'] or 'never'}")
        if last:
            print(f"  {last['line']}")
        print(f"overdue (not searched in {OVERDUE_DAYS}+ days): "
              + (", ".join(od) if od else "none"))
    return 0


# ------------------------------------------------------------------- config add

def missing_config_keys(root):
    p = os.path.join(root, "00-Config", "config.md")
    try:
        text = open(p, encoding="utf-8").read()
    except OSError:
        return None
    return [k for k in KEY_ORDER if not re.search(rf"^\s*-?\s*{re.escape(k)}\s*:", text, re.M)]


CONFIG_NOTES = {
    "news_sweep_competitors": "all | off",
    "news_sweep_customers": "tiered | daily | off",
    "news_sweep_prospects": "tiered | daily | off",
    "news_sweep_quiet_morning": "coverage_line | silent",
    "news_sweep_content_lens": "label | off",
}


def config_block(keys=None):
    keys = keys or KEY_ORDER
    lines = []
    for k in keys:
        note = CONFIG_NOTES.get(k)
        lines.append(f"- {k}: {DEFAULTS[k]}" + (f"   # {note}" if note else ""))
    return "\n".join(lines)


def add_config_keys(root, dry=False):
    """Add any missing news_sweep_* key with its default to config.md — appended under a
    '### News sweep (daily brief)' heading, never rewriting what is there."""
    miss = missing_config_keys(root)
    if miss is None or not miss:
        return miss or []
    if dry:
        return miss
    p = os.path.join(root, "00-Config", "config.md")
    text = open(p, encoding="utf-8").read()
    block = config_block(miss)
    if "### News sweep" not in text:
        block = "\n### News sweep (daily brief)\n\n" + block
    with open(p, "w", encoding="utf-8") as f:   # truncate-and-write: no unlink needed
        f.write(text.rstrip("\n") + "\n" + block + "\n")
    return miss


# ------------------------------------------------------------------------- main

def selftest():
    fails = []
    keys = [f"acct{i}" for i in range(500)]
    counts = [0] * 5
    for k in keys:
        counts[slot_of(k, 5)] += 1
    if max(counts) - min(counts) > 40:
        fails.append(f"rotation uneven: {counts}")
    if slot_of("acme", 5) != slot_of("acme", 5):
        fails.append("rotation not stable")
    if norm("Acme, Inc.") != norm("ACME Inc") or norm("The Acme Company") != "acme":
        fails.append(f"norm: {norm('Acme, Inc.')!r} {norm('The Acme Company')!r}")
    for f in fails:
        print("FAIL", f)
    print("selftest ok" if not fails else f"{len(fails)} failure(s)")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan"); ap.add_argument("--record"); ap.add_argument("--line")
    ap.add_argument("--status"); ap.add_argument("--add-config")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--meeting", action="append", default=[])
    ap.add_argument("--json", nargs="?", const=True, default=None)
    ap.add_argument("--today")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    today = D(a.today) or date.today()
    if a.selftest:
        return selftest()
    if a.plan:
        return plan(os.path.abspath(a.plan), today, a.meeting, a.json is True)
    if a.record:
        if not isinstance(a.json, str):
            print("--record needs --json <payload file | ->", file=sys.stderr)
            return 2
        raw = sys.stdin.read() if a.json == "-" else (
            open(a.json, encoding="utf-8").read() if os.path.exists(a.json) else a.json)
        try:
            payload = json.loads(raw)
        except ValueError as e:
            print(f"payload is not JSON: {e}", file=sys.stderr)
            return 2
        return record(os.path.abspath(a.record), payload, today)
    if a.line:
        r = latest(os.path.abspath(a.line))
        print(r["line"] if r else "News sweep: no run recorded.")
        return 0
    if a.status:
        return status(os.path.abspath(a.status), today, a.json is True)
    if a.add_config:
        miss = add_config_keys(os.path.abspath(a.add_config), a.dry_run)
        if miss is None:
            print("no 00-Config/config.md")
            return 1
        print(("would add: " if a.dry_run else "added: ") + ", ".join(miss) if miss
              else "news_sweep keys already present")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
