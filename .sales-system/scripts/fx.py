#!/usr/bin/env python3
"""
fx.py — currency conversion for the registries, so totals can be added up at all.

Every money column in this system is a bare number in the record's own currency
(CONVENTIONS §8a). That is correct for the record and useless for a total: a €80K deal
and a $120K deal do not make "200K" of anything. This script adds the missing half — a
dated rate table in the folder, and a `converted_*` column on every record holding the
same money expressed in the folder's base currency, which is what forecasts, goal
attainment, pipeline totals and coverage actually sum.

Three things here are load-bearing.

**The rate direction.** `rate_to_base` is a multiplier: amount × rate_to_base = amount in
base currency. It is deliberately not the number most CRMs store. Salesforce's
`CurrencyType.ConversionRate` is the reciprocal — units of the foreign currency per one
unit of the corporate currency — so EUR sits at 0.91 in a USD org and a €80K deal is
$87,912, not $72,800. Both numbers are kept: the multiplier in `rate_to_base`, the source's
own figure verbatim in `source_rate` beside the convention it follows. Inverting this by
accident is the single most likely way this feature produces confident wrong totals, which
is why it is written down in three places.

**Closed records freeze.** Once a deal is Closed Won or Closed Lost, its converted amount
is never recomputed. Last quarter's attainment has to be the same number every time it is
read; a closed figure that drifts with the spot rate turns a settled result into a moving
one. Open records reconvert at the current rate on every run — including a deal whose close
date has slipped, because that deal is still live pipeline and belongs in the forecast at
today's rate, not at the rate of a date it failed to close on. The freeze is on state, not
on the calendar. Each schema declares its own closed states in its `fx` block.

**A missing conversion is blank, never zero.** No currency on the record, or no rate for
that currency, and `converted_*` stays empty and gets reported. A zero would pass silently
through every sum in the system and quietly shrink the forecast, which is the failure mode
this whole file exists to prevent — not the one it should introduce.

**Where the rates come from is separate from which ones convert.** The table holds every
source side by side — the CRM's currency setup, a public market feed, anything entered by
hand — and `rate_source:` in config.md names the one that converts. Default CRM, because
totals that reconcile against the system of record are worth more than totals that are
marginally more accurate and match nothing. The others are not decoration: `--check`
compares them and reports the gap, which is the only way anyone finds out that a CRM
currency table last touched a year ago has been quietly converting several percent out.

Usage:
  fx.py --pull <project> --json-file rates.json   # load rates from a CRM snapshot
  fx.py --pull <project> --json '{"base":"USD","convention":"units-of-currency-per-base",
                                  "rates":{"EUR":0.91,"GBP":0.80},"source":"CRM"}'
  fx.py --fetch <project> [--provider ecb|erapi] [--date 2026-03-31] [--symbols EUR,GBP]
  fx.py --convert <project> [--registry opportunities] [--dry-run]
  fx.py --check <project>            # what cannot be converted, rate drift, staleness
  fx.py --backfill-currency <project> [--registry X] [--currency USD] [--dry-run]
  fx.py --refreeze <project> --registry opportunities --id OPP-0003
  fx.py --rates <project>                          # print every rate on file

config.md keys: base_currency (required), rate_source (crm | market | manual, default
crm), rate_drift_threshold (percent, default 2), rate_staleness_days (default 30).

--fetch is the only command here that touches the network. Everything else works offline.

Exit codes: 0 clean, 1 something needs a human, 2 usage error.
"""

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csvguard  # noqa: E402

RATES_REGISTRY = "fx_rates"
DEFAULT_CONVENTION = "units-of-currency-per-base"


# --------------------------------------------------------------- configuration

def _config_value(root, key, pattern=r"[^\s#]+"):
    cfg = os.path.join(root, "00-Config", "config.md")
    if not os.path.exists(cfg):
        return None
    import re
    try:
        with open(cfg, encoding="utf-8") as f:
            m = re.search(rf"^\s*[-*]?\s*{key}\s*:\s*({pattern})",
                          f.read(), re.MULTILINE | re.IGNORECASE)
    except OSError:
        return None
    return m.group(1) if m else None


def base_currency(root):
    """The currency every converted_* column is expressed in. From 00-Config/config.md.

    No default. A folder that has not said what its base currency is has not made the
    decision, and picking one for it would put a number in a column that means something
    it was never told to mean."""
    v = _config_value(root, "base[_ ]currency", r"[A-Za-z]{3}")
    return v.upper() if v else None


# `rate_source:` decides which source's rows the conversion actually uses. Rows from the
# other sources are kept in the same table rather than discarded, because the comparison
# between them is the point: a CRM currency table nobody has touched in a year still
# converts, silently and wrongly, and the only way to find out is to hold a second opinion
# beside it. Default CRM — the rates your CRM reports from are the rates your folder's
# totals should reconcile against, even when the market disagrees with both.
SOURCE_ALIASES = {"crm": "CRM", "salesforce": "CRM",
                  "market": "API", "api": "API", "public": "API", "ecb": "API",
                  "manual": "Manual", "hand": "Manual"}


def rate_source(root):
    v = (_config_value(root, "rate[_ ]source", r"[A-Za-z]+") or "").lower()
    return SOURCE_ALIASES.get(v, "CRM")


def _config_number(root, key, default):
    v = _config_value(root, key, r"[0-9.]+")
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def drift_threshold(root):
    """Percent difference between the authoritative rate and the market before it is worth
    saying out loud. Two percent on a $2M pipeline is $40,000."""
    return _config_number(root, "rate[_ ]drift[_ ]threshold", 2.0)


def staleness_days(root):
    return int(_config_number(root, "rate[_ ]staleness[_ ]days", 30))


def require_base(root):
    b = base_currency(root)
    if not b:
        sys.exit("error: no `base_currency:` in 00-Config/config.md. Add one — e.g.\n"
                 "  - base_currency: USD\n"
                 "It is the currency every converted amount, forecast total and goal "
                 "attainment figure will be expressed in, so it is a decision for the "
                 "user, not a default.")
    return b


def registry_path(root, schema):
    """The file this registry actually lives in. If it does not exist yet, the folder's
    storage_format decides the extension, the same rule csvguard --init follows — so a
    folder set to Excel does not acquire one stray CSV the first time rates are pulled."""
    p = csvguard.resolve_path(os.path.join(root, schema["path"]), root)
    if os.path.exists(p):
        return p
    fmt = csvguard.storage_format(root) if schema.get("browsable", True) else "csv"
    return os.path.splitext(p)[0] + "." + fmt


def rates_path(root):
    s = csvguard.load_schemas(root).get(RATES_REGISTRY)
    if not s:
        sys.exit(f"error: no {RATES_REGISTRY} schema in .sales-system/schemas/. "
                 f"The support layer is older than these skills — run update-system.")
    return registry_path(root, s), s


# ------------------------------------------------------------------ rate table

def load_rates(root, source=None):
    """{currency: [rows sorted by effective_from]}. `source` filters to one provider's
    rows; None returns everything, which is what the drift audit compares."""
    path, schema = rates_path(root)
    if not os.path.exists(path):
        return {}, path, schema
    header, rows = csvguard.read_table(path, schema)
    idx = {h: i for i, h in enumerate(header)}
    out = {}
    for r in rows:
        def g(c):
            return r[idx[c]].strip() if c in idx and idx[c] < len(r) else ""
        if not g("currency") or not g("rate_to_base"):
            continue
        try:
            rate = float(g("rate_to_base"))
        except ValueError:
            continue
        src = g("source") or "CRM"
        if source and src != source:
            continue
        out.setdefault(g("currency").upper(), []).append({
            "id": g("id"), "currency": g("currency").upper(),
            "base_currency": g("base_currency").upper(),
            "rate_to_base": rate, "effective_from": g("effective_from"),
            "source": src, "pulled_date": g("pulled_date"),
        })
    for k in out:
        out[k].sort(key=lambda x: x["effective_from"] or "0000-00-00")
    return out, path, schema


def rate_on(rates, cur, base, when, others=None):
    """(rate, effective_from, warning). The rate in force on `when`, or the oldest known
    rate if `when` predates the table — flagged, because converting a 2024 deal at a 2026
    rate is a defensible fallback and an indefensible silence."""
    cur = (cur or "").upper()
    if not cur:
        return None, "", "no currency on the record"
    if cur == base:
        return 1.0, when, ""
    hist = [r for r in rates.get(cur, []) if r["base_currency"] in ("", base)]
    if not hist:
        # Refusing to convert while holding a perfectly good rate from a source the folder
        # has not been told to trust is correct and infuriating unless it says so.
        alt = sorted({r["source"] for r in (others or {}).get(cur, [])
                      if r["base_currency"] in ("", base)})
        if alt:
            return None, "", (f"no rate on file for {cur} from the authoritative source; "
                              f"there is one from {', '.join(alt)} — set `rate_source:` in "
                              f"00-Config/config.md if that is the one to convert with")
        return None, "", f"no rate on file for {cur}"
    applicable = [r for r in hist if r["effective_from"] and r["effective_from"] <= when]
    if applicable:
        r = applicable[-1]
        return r["rate_to_base"], r["effective_from"], ""
    r = hist[0]
    return (r["rate_to_base"], r["effective_from"],
            f"no {cur} rate as early as {when}; used the oldest on file "
            f"({r['effective_from']})")


def cmd_pull(root, payload, dry_run=False):
    """Merge a rate snapshot into the table. A rate that has not moved does not create a
    row — it just re-stamps pulled_date, so the history stays a history of changes."""
    base = require_base(root)
    path, schema = rates_path(root)
    today = date.today().isoformat()
    conv = payload.get("convention", DEFAULT_CONVENTION)
    src = payload.get("source", "CRM")
    snap_base = (payload.get("base") or base).upper()
    if snap_base != base:
        sys.exit(f"error: snapshot is against {snap_base} but this folder's base_currency "
                 f"is {base}. Convert the snapshot or change the folder's base — do not "
                 f"mix two bases in one rate table.")

    incoming = {}
    for cur, raw in (payload.get("rates") or {}).items():
        cur = cur.upper()
        try:
            raw = float(raw)
        except (TypeError, ValueError):
            print(f"  skipped {cur}: {raw!r} is not a number", file=sys.stderr)
            continue
        if raw == 0:
            print(f"  skipped {cur}: a rate of zero would blank every amount in it",
                  file=sys.stderr)
            continue
        if conv == "units-of-base-per-currency":
            to_base = raw
        else:                                    # Salesforce and most CRM currency tables
            to_base = 1.0 / raw
        incoming[cur] = (round(to_base, 8), raw)

    # Scoped to this source. A market fetch must not read a CRM row as "the previous rate"
    # and decide nothing changed, nor overwrite it as a same-day correction — the two are
    # parallel opinions and each keeps its own history.
    existing, _, _ = load_rates(root, source=src)
    header, rows = (csvguard.read_table(path, schema) if os.path.exists(path)
                    else ([c["name"] for c in schema["columns"]], []))
    idx = {h: i for i, h in enumerate(header)}
    eff = payload.get("effective_from") or today
    added, revised, unchanged = [], [], []
    for cur, (to_base, raw) in sorted(incoming.items()):
        hist = [r for r in existing.get(cur, []) if r["base_currency"] in ("", base)]
        latest = hist[-1] if hist else None
        if latest and abs(latest["rate_to_base"] - to_base) < 1e-9:
            unchanged.append(cur)
            for r in rows:
                if r[idx["id"]] == latest["id"] and "pulled_date" in idx:
                    r[idx["pulled_date"]] = today
                    if "last_updated" in idx:
                        r[idx["last_updated"]] = today
            continue
        # A second rate for a day that already has one is a correction, not history. Two
        # rows sharing an effective_from cannot be ordered by date, and the older of them
        # would be closed off the day *before* it started — a row that is live for minus
        # one day. Overwrite in place instead.
        target = None
        if latest and latest["effective_from"] == eff:
            target = next((r for r in rows if r[idx["id"]] == latest["id"]), None)
        if target is None:
            target = [""] * len(header)
            rows.append(target)
            added.append(f"{cur} = {to_base:.6f} {base} per 1 {cur} (source said {raw})")
        else:
            revised.append(f"{cur} = {to_base:.6f} {base} per 1 {cur} "
                           f"(was {latest['rate_to_base']:.6f}, same day — corrected)")
        for c, v in (("currency", cur), ("base_currency", base),
                     ("rate_to_base", f"{to_base:.8f}".rstrip("0").rstrip(".")),
                     ("effective_from", eff),
                     ("source", src), ("source_rate", str(raw)),
                     ("source_convention", conv), ("pulled_date", today),
                     ("last_updated", today)):
            if c in idx:
                target[idx[c]] = v

    rows = _restate_effective_to(header, rows)
    _assign_ids(header, rows, schema)
    summary = (f"{len(added)} new rate row(s), {len(revised)} corrected in place, "
               f"{len(unchanged)} unchanged")
    if dry_run:
        print(f"would write: {summary}")
        for a in added:
            print("  +", a)
        for a in revised:
            print("  ~", a)
        return 0
    csvguard.write_table(path, header, rows, schema=schema, root=root, backup=True,
                         guard=False)
    print(f"{os.path.basename(path)}: {summary}")
    for a in added:
        print("  +", a)
    for a in revised:
        print("  ~", a)
    if added or revised:
        print("\nRates changed. Run `fx.py --convert` to bring open records onto them; "
              "closed records keep the rate they were frozen at.")
    return 0


# -------------------------------------------------------------- public rate sources
# An alternative to the CRM's currency table, for orgs whose table is maintained by hand
# once a year and is quietly several percent out. Both providers below are keyless. Both
# quote the same way round as Salesforce — units of the foreign currency per one unit of
# the base — so the same inversion applies and is done in one place, cmd_pull.
#
# ECB is the default because it is the only free source with a **historical** endpoint,
# and history is what this system needs: closed records freeze at the rate in force on
# their close date, so backfilling a settled quarter correctly requires asking what March
# was, not what today is. Its cost is coverage — the ECB publishes around thirty
# currencies and only on TARGET business days. exchangerate-api covers 169 and fills the
# gaps, latest-only.

PROVIDERS = {
    "ecb": {
        "label": "ECB reference rates (via Frankfurter)",
        "latest": "https://api.frankfurter.dev/v1/latest?base={base}",
        "historical": "https://api.frankfurter.dev/v1/{date}?base={base}",
        "rates_key": "rates",
        "date_key": "date",
        "note": "European Central Bank reference rates. ~30 currencies, TARGET business "
                "days only. Published around 16:00 CET; a request before that returns the "
                "previous business day, which is why the response's own date is stored "
                "rather than today's.",
    },
    "erapi": {
        "label": "exchangerate-api open access",
        "latest": "https://open.er-api.com/v6/latest/{base}",
        "historical": None,
        "rates_key": "rates",
        "date_key": None,
        "note": "169 currencies, updated daily, no historical rates on the free tier.",
    },
}
DEFAULT_PROVIDER = "ecb"
FALLBACK_PROVIDER = "erapi"


def _http_json(url, timeout=20):
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url, headers={
        "User-Agent": "folder-sales-os/fx.py (+https://github.com/cgogoel/mySails.ai)",
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} from {url}"
    except urllib.error.URLError as e:
        return None, (f"could not reach {url} ({e.reason}). If this machine is offline or "
                      f"behind a proxy, pull the rates by hand with --pull instead — "
                      f"nothing here needs the network except this command.")
    except (ValueError, TimeoutError) as e:
        return None, f"unreadable response from {url}: {e}"


def fetch_market_rates(base, symbols=None, on=None, provider=DEFAULT_PROVIDER,
                       allow_fallback=True):
    """Returns (rates, as_of_date, provider_label, notes). `rates` is in the providers'
    shared convention — units of the currency per one unit of base — so it hands straight
    to cmd_pull without a second inversion."""
    notes = []
    spec = PROVIDERS.get(provider)
    if not spec:
        return None, None, None, [f"unknown provider {provider!r}; "
                                  f"have {', '.join(PROVIDERS)}"]
    if on and not spec["historical"]:
        return None, None, None, [
            f"{spec['label']} has no historical endpoint, so it cannot answer for {on}. "
            f"Use --provider ecb for a past date."]
    url = (spec["historical"].format(base=base, date=on) if on
           else spec["latest"].format(base=base))
    data, err = _http_json(url)
    if err:
        return None, None, None, [err]
    rates = {k.upper(): v for k, v in (data.get(spec["rates_key"]) or {}).items()}
    if not rates:
        return None, None, None, [f"{spec['label']} returned no rates for base {base}"]
    as_of = (data.get(spec["date_key"]) if spec["date_key"] else None) or (on or
                                                                          date.today().isoformat())
    if spec["date_key"] and on and as_of != on:
        notes.append(f"asked {spec['label']} for {on} and it answered for {as_of} — "
                     f"{on} was not a publication day. The rate is stored under {as_of}.")

    if symbols:
        want = {c.upper() for c in symbols}
        missing = sorted(w for w in want if w not in rates and w != base)
        rates = {k: v for k, v in rates.items() if k in want}
        if missing and allow_fallback and provider != FALLBACK_PROVIDER and not on:
            alt, _, alt_label, alt_notes = fetch_market_rates(
                base, symbols=missing, provider=FALLBACK_PROVIDER, allow_fallback=False)
            notes += alt_notes
            if alt:
                got = {k: v for k, v in alt.items() if k in set(missing)}
                if got:
                    rates.update(got)
                    notes.append(f"{', '.join(sorted(got))} not published by "
                                 f"{spec['label']}; taken from {alt_label} instead. Two "
                                 f"providers in one pull means these rows are not "
                                 f"strictly comparable with the others.")
            missing = [m for m in missing if m not in rates]
        if missing:
            notes.append(f"no rate available for {', '.join(missing)} from any source — "
                         f"records in those currencies stay unconverted.")
    return rates, as_of, spec["label"], notes


def currencies_in_use(root):
    """Which currencies the folder actually holds money in. Fetching the provider's whole
    table would work and would also fill the rate registry with 160 rows nobody has a deal
    in, burying the three that matter."""
    found = set()
    for _, schema in fx_registries(root):
        path = registry_path(root, schema)
        if not os.path.exists(path):
            continue
        header, rows = csvguard.read_table(path, schema)
        idx = {h: i for i, h in enumerate(header)}
        ccol = schema["fx"].get("currency_column", "currency")
        if ccol not in idx:
            continue
        for r in rows:
            v = (r[idx[ccol]] or "").strip().upper()
            if v:
                found.add(v)
    return found


def cmd_fetch(root, symbols=None, on=None, provider=DEFAULT_PROVIDER, dry_run=False):
    """Fetch market rates and store them beside whatever else is in the table.

    This does not decide anything. Whether these rates are the ones that convert is
    `rate_source:` in config.md; by default they sit alongside the CRM's as a second
    opinion, and --check reports where the two disagree."""
    base = require_base(root)
    want = {c.upper() for c in (symbols or [])} or (currencies_in_use(root)
                                                    | set(load_rates(root)[0]))
    want.discard(base)
    if not want:
        print(f"nothing to fetch — no currency other than {base} appears anywhere in this "
              f"folder. Name one with --symbols if you want the rate on file in advance.")
        return 0
    rates, as_of, label, notes = fetch_market_rates(base, sorted(want), on=on,
                                                    provider=provider)
    for n in notes:
        print(f"note: {n}", file=sys.stderr)
    if not rates:
        return 1
    print(f"{label}: {len(rates)} rate(s) as at {as_of}")
    rc = cmd_pull(root, {"base": base, "convention": DEFAULT_CONVENTION, "source": "API",
                         "effective_from": as_of, "rates": rates}, dry_run=dry_run)
    authoritative = rate_source(root)
    if authoritative != "API" and not dry_run:
        print(f"\nStored as a second opinion — `rate_source:` is {authoritative}, so these "
              f"are not what converts. `fx.py --check` reports where the two disagree; "
              f"set `rate_source: market` in 00-Config/config.md to convert with them.")
    return rc


def _assign_ids(header, rows, schema):
    """Fill blank ids. csvguard only does this on --repair and --upsert, and a rate row
    written without one is a row nothing can reference — including the record that was
    converted using it."""
    idx = {h: i for i, h in enumerate(header)}
    if "id" not in idx:
        return
    i = idx["id"]
    prefix = schema.get("id_prefix", "REC")
    width = schema.get("id_width", 4)
    used = {r[i] for r in rows if r[i]}
    nxt = csvguard.next_free(used, prefix, width)
    for r in rows:
        if not r[i]:
            r[i] = f"{prefix}-{nxt:0{width}d}"
            used.add(r[i])
            nxt += 1


def _restate_effective_to(header, rows):
    """Close each superseded rate the day before its successor starts, and set status."""
    idx = {h: i for i, h in enumerate(header)}
    if "currency" not in idx:
        return rows
    from datetime import datetime, timedelta
    by_cur = {}
    for r in rows:
        # Grouped by source as well as currency. Two providers quoting EUR are two
        # opinions running in parallel, not a history — letting a market rate close off a
        # CRM rate would leave the authoritative row marked Superseded by something the
        # folder has not been told to trust.
        key = (r[idx["currency"]].upper(),
               (r[idx["source"]] if "source" in idx else "") or "CRM")
        by_cur.setdefault(key, []).append(r)
    for cur, group in by_cur.items():
        group.sort(key=lambda r: r[idx["effective_from"]] or "0000-00-00")
        for i, r in enumerate(group):
            nxt = group[i + 1] if i + 1 < len(group) else None
            if "effective_to" in idx:
                if nxt and nxt[idx["effective_from"]]:
                    try:
                        d = datetime.strptime(nxt[idx["effective_from"]], "%Y-%m-%d").date()
                        r[idx["effective_to"]] = (d - timedelta(days=1)).isoformat()
                    except ValueError:
                        r[idx["effective_to"]] = ""
                else:
                    r[idx["effective_to"]] = ""
            if "status" in idx:
                r[idx["status"]] = "Superseded" if nxt else "Current"
    return rows


# ------------------------------------------------------------------ conversion

def fx_registries(root):
    """Every schema that declares an `fx` block, in a stable order."""
    out = []
    for name, s in sorted(csvguard.load_schemas(root).items()):
        if s.get("fx"):
            out.append((name, s))
    return out


def is_frozen(row, idx, fx, today):
    """Closed states freeze. A date column may additionally freeze a record whose period
    is simply over — goals work that way, deals deliberately do not."""
    fr = fx.get("freeze") or {}
    col = fr.get("column")
    if col and col in idx:
        v = (row[idx[col]] or "").strip()
        if v and v in (fr.get("values") or []):
            return True
    dcol = fr.get("after_date_column")
    if dcol and dcol in idx:
        v = (row[idx[dcol]] or "").strip()
        if v and v < today:
            return True
    return False


def convert_registry(root, name, schema, rates, base, dry_run=False, verbose=False,
                     others=None):
    """Returns (records_to_write, report_lines, problem_lines)."""
    fx = schema["fx"]
    path = registry_path(root, schema)
    if not os.path.exists(path):
        return [], [], []
    header, rows = csvguard.read_table(path, schema)
    idx = {h: i for i, h in enumerate(header)}
    if "id" not in idx:
        return [], [], [f"{name}: no id column to write back against"]

    today = date.today().isoformat()
    ccol = fx.get("currency_column", "currency")
    pairs = [(p["from"], p["to"]) for p in fx.get("convert", [])
             if p["from"] in idx and p["to"] in idx]
    if not pairs or ccol not in idx:
        return [], [], [f"{name}: missing the fx columns — run "
                        f"`csvguard.py --repair` on {os.path.basename(path)} first"]

    basis_col = fx.get("rate_date_column")
    recs, report, problems = [], [], []
    n_open = n_frozen = n_new_freeze = n_blank = 0

    # A freeze state that does not exist in this org's picklist never fires, and nothing
    # ever freezes — which looks exactly like working correctly until a closed quarter
    # silently rewrites itself. The schemas ship generic closed-state names and an org's
    # real ones can differ ("Won", "Closed Won - Renewal"); schemas live in the folder
    # precisely so the fx block can be edited to match.
    fr = fx.get("freeze") or {}
    fcol, fvals = fr.get("column"), fr.get("values") or []
    if fcol and fvals:
        spec = next((c for c in schema["columns"] if c["name"] == fcol), None)
        allowed = (spec or {}).get("values") or []
        if allowed and not set(fvals) & set(allowed):
            problems.append(
                f"{name}: none of the freeze states {fvals} exist in {fcol}, whose values "
                f"are {allowed}. Nothing in this registry will ever freeze — edit "
                f"`fx.freeze.values` in schemas/{name}.json to your org's closed states.")
        elif allowed:
            absent = [v for v in fvals if v not in allowed]
            if absent:
                problems.append(f"{name}: freeze state(s) {absent} are not in {fcol}'s "
                                f"values; they will never match.")

    for row in rows:
        rid = row[idx["id"]]
        if not rid:
            continue
        cur = (row[idx[ccol]] or "").strip().upper()
        frozen = is_frozen(row, idx, fx, today)
        has_conv = any((row[idx[t]] or "").strip() for _, t in pairs)
        stored_rate = (row[idx["fx_rate"]] or "").strip() if "fx_rate" in idx else ""
        stored_base = ((row[idx["converted_currency"]] or "").strip().upper()
                       if "converted_currency" in idx else "")

        # ---- already frozen and already converted: never recompute. Audit only.
        if frozen and has_conv and stored_rate:
            n_frozen += 1
            if stored_base and stored_base != base:
                problems.append(
                    f"{name} {rid}: frozen at base {stored_base}, folder base is now "
                    f"{base}. Left alone — a closed figure is not reinterpreted. Use "
                    f"--refreeze if the change is deliberate.")
            try:
                r = float(stored_rate)
                for src, dst in pairs:
                    a = (row[idx[src]] or "").strip()
                    c = (row[idx[dst]] or "").strip()
                    if a and c and abs(float(a) * r - float(c)) > 0.02:
                        problems.append(
                            f"{name} {rid}: {src} is {a} but {dst} is {c}, which is not "
                            f"{a} x {r}. The amount changed after the record froze. "
                            f"Use --refreeze {rid} if the new amount is right.")
                # The frozen rate has to still belong to the currency on the record. Edit
                # a closed deal from USD to EUR and the amount check above still passes —
                # 45000 x 1 is 45000 whatever the label says — so the number reads as
                # audited while being converted at the wrong currency's rate.
                asof = ((row[idx["fx_rate_date"]] or "").strip()
                        if "fx_rate_date" in idx else "") or today
                expect, _, _ = rate_on(rates, cur, base, asof, others)
                if expect is not None and abs(expect - r) > max(1e-6, expect * 1e-6):
                    problems.append(
                        f"{name} {rid}: frozen at {r:g} but the {cur or '(blank)'} rate on "
                        f"{asof} is {expect:g}. Either the currency was changed after the "
                        f"record closed or a rate row was edited retroactively. Left "
                        f"alone — use --refreeze {rid} to recompute deliberately.")
            except ValueError:
                pass
            continue

        # ---- work out the rate
        if frozen:
            when = ((row[idx[basis_col]] or "").strip()
                    if basis_col and basis_col in idx else "") or today
            when = min(when, today)
        else:
            when = today

        rate, eff, warn = rate_on(rates, cur, base, when, others)
        rec = {"id": rid}
        if rate is None:
            n_blank += 1
            for _, dst in pairs:
                rec[dst] = ""
            for c in ("fx_rate", "fx_rate_date", "converted_currency"):
                if c in idx:
                    rec[c] = ""
            if "fx_frozen" in idx:
                rec["fx_frozen"] = "yes" if frozen else "no"
            problems.append(f"{name} {rid}: not converted — {warn}")
            recs.append(rec)
            continue
        if warn:
            problems.append(f"{name} {rid}: {warn}")

        for src, dst in pairs:
            a = (row[idx[src]] or "").strip()
            if not a:
                rec[dst] = ""
                continue
            try:
                rec[dst] = f"{round(float(a) * rate, 2):.2f}".rstrip("0").rstrip(".")
            except ValueError:
                rec[dst] = ""
                problems.append(f"{name} {rid}: {src} {a!r} is not a number")
        if "fx_rate" in idx:
            rec["fx_rate"] = f"{rate:.8f}".rstrip("0").rstrip(".")
        if "fx_rate_date" in idx:
            rec["fx_rate_date"] = eff or when
        if "converted_currency" in idx:
            rec["converted_currency"] = base
        if "fx_frozen" in idx:
            rec["fx_frozen"] = "yes" if frozen else "no"
        recs.append(rec)
        if frozen:
            n_new_freeze += 1
        else:
            n_open += 1
        if verbose:
            report.append(f"  {rid}: {cur} -> {base} at {rate:.6f}"
                          + (" [freezing]" if frozen else ""))

    head = (f"{name}: {n_open} open reconverted, {n_new_freeze} newly frozen, "
            f"{n_frozen} already frozen and left alone"
            + (f", {n_blank} could not be converted" if n_blank else ""))
    return recs, [head] + report, problems


def write_back(root, name, schema, recs, force=False):
    path = registry_path(root, schema)
    if not recs:
        return 0
    up, ins, skip, changes = csvguard.upsert(
        path, schema, recs, key="id", root=root, only_owner="derived",
        allow_clear=True, stamp=False, force=force)
    return up


def cmd_convert(root, only=None, dry_run=False, verbose=False, force=False):
    base = require_base(root)
    src = rate_source(root)
    rates, rpath, _ = load_rates(root, source=src)
    everything, _, _ = load_rates(root)
    if not rates and not os.path.exists(rpath):
        print(f"note: no rate table yet at {os.path.relpath(rpath, root)}. Anything "
              f"already in {base} still converts at 1; anything else will be reported "
              f"as unconvertible until you run --pull or --fetch.", file=sys.stderr)
    for line in staleness_notes(root, rates, src):
        print(f"note: {line}", file=sys.stderr)
    problems, rc = [], 0
    for name, schema in fx_registries(root):
        if only and name != only:
            continue
        recs, report, probs = convert_registry(root, name, schema, rates, base,
                                               dry_run=dry_run, verbose=verbose,
                                               others=everything)
        for line in report:
            print(line)
        problems += probs
        if recs and not dry_run:
            write_back(root, name, schema, recs, force=force)
    if problems:
        rc = 1
        print(f"\n{len(problems)} thing(s) need a human:", file=sys.stderr)
        for p in problems[:40]:
            print("  -", p, file=sys.stderr)
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more", file=sys.stderr)
    if dry_run:
        print("\n(dry run — nothing written)")
    return rc


def staleness_notes(root, rates, src):
    """A rate table nobody has refreshed converts just as confidently as a fresh one. This
    is the only thing that tells the difference, so it runs on every conversion rather
    than waiting to be asked."""
    if not rates:
        return []
    days = staleness_days(root)
    today = date.today()
    newest = ""
    for hist in rates.values():
        for r in hist:
            newest = max(newest, r["effective_from"] or "")
    if not newest:
        return []
    try:
        age = (today - date.fromisoformat(newest)).days
    except ValueError:
        return []
    if age <= days:
        return []
    how = ("query your CRM's currency table and run --pull" if src == "CRM"
           else "run --fetch")
    return [f"the newest {src} rate is {age} days old ({newest}), past the {days}-day "
            f"staleness window. Every open record is converting at it. To refresh, {how}."]


def drift_report(root, base):
    """Compare the rate that converts against every other opinion in the table.

    This is the case for holding more than one source. A CRM currency table maintained by
    hand once a year keeps converting, silently, at whatever it last said; the only way to
    learn it is wrong is to have a second number beside it. Reported, never applied — which
    source is authoritative is a decision in config.md, not something a drift check gets to
    overrule."""
    src = rate_source(root)
    everything, _, _ = load_rates(root)
    thresh = drift_threshold(root)
    lines, worst = [], 0.0
    for cur, hist in sorted(everything.items()):
        if cur == base:
            continue
        live = [r for r in hist if r["source"] == src]
        if not live:
            continue
        mine = live[-1]
        for other_src in sorted({r["source"] for r in hist if r["source"] != src}):
            theirs = [r for r in hist if r["source"] == other_src][-1]
            if not theirs["rate_to_base"]:
                continue
            diff = (mine["rate_to_base"] - theirs["rate_to_base"]) / theirs["rate_to_base"]
            worst = max(worst, abs(diff) * 100)
            if abs(diff) * 100 < thresh:
                continue
            direction = "over" if diff > 0 else "under"
            lines.append(
                f"{cur}: {src} says {mine['rate_to_base']:.6f} (from "
                f"{mine['effective_from']}), {other_src} says {theirs['rate_to_base']:.6f} "
                f"(from {theirs['effective_from']}) — {src} is {abs(diff)*100:.1f}% "
                f"{direction}, so every open {cur} record is converting {direction} by "
                f"that much")
    return lines, worst, src


def cmd_check(root):
    """Same analysis, no writes. What a brief or forecast should run before totalling."""
    base = require_base(root)
    src = rate_source(root)
    rates, rpath, _ = load_rates(root, source=src)
    everything, _, _ = load_rates(root)
    problems, mixed = [], {}
    for name, schema in fx_registries(root):
        path = registry_path(root, schema)
        if not os.path.exists(path):
            continue
        header, rows = csvguard.read_table(path, schema)
        idx = {h: i for i, h in enumerate(header)}
        ccol = schema["fx"].get("currency_column", "currency")
        if ccol not in idx:
            problems.append(f"{name}: no {ccol} column — run csvguard.py --repair")
            continue
        seen = {}
        for row in rows:
            if not any(c.strip() for c in row):
                continue
            cur = (row[idx[ccol]] or "").strip().upper() or "(blank)"
            seen[cur] = seen.get(cur, 0) + 1
        if seen:
            mixed[name] = seen
        _, _, probs = convert_registry(root, name, schema, rates, base, others=everything)
        problems += probs

    print(f"base currency: {base}")
    print(f"rate source:   {src}" + ("  (config default — set `rate_source:` to change)"
                                     if not _config_value(root, "rate[_ ]source",
                                                          r"[A-Za-z]+") else ""))
    print(f"rate table:    {os.path.relpath(rpath, root)}"
          + ("" if os.path.exists(rpath) else " (does not exist yet)"))
    for cur, hist in sorted(rates.items()):
        r = hist[-1]
        print(f"  1 {cur} = {r['rate_to_base']:.6f} {base}  "
              f"(from {r['effective_from']}, {r['source'] or 'unknown source'})")
    other_srcs = sorted({r["source"] for h in everything.values() for r in h
                         if r["source"] != src})
    if other_srcs:
        print(f"  also on file, not converting: {', '.join(other_srcs)}")
    for name, seen in mixed.items():
        parts = ", ".join(f"{c} x{n}" for c, n in sorted(seen.items()))
        flag = "  <- mixed book" if len([c for c in seen if c != "(blank)"]) > 1 else ""
        print(f"{name}: {parts}{flag}")

    stale = staleness_notes(root, rates, src)
    drift, worst, _ = drift_report(root, base)
    if drift:
        print(f"\nrate drift — {src} against the other rates on file "
              f"(threshold {drift_threshold(root):g}%):")
        for d in drift:
            print("  !", d)
        print("  Nothing has been changed. Either refresh the authoritative source or "
              "switch `rate_source:` — this check reports, it does not decide.")
    elif len(other_srcs):
        print(f"\nno rate drift beyond {drift_threshold(root):g}% "
              f"(worst gap {worst:.1f}%).")
    else:
        print("\nno second source on file to check drift against — `fx.py --fetch` adds "
              "market rates as a second opinion without changing what converts.")
    for line in stale:
        print("\nstale: " + line)

    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for p in problems[:60]:
            print("  -", p, file=sys.stderr)
        return 1
    print("\nnothing unconvertible.")
    return 0


def cmd_backfill(root, only=None, currency=None, dry_run=False, force=False):
    """Fill a blank currency column explicitly. Separate from --convert on purpose: a
    blank currency is missing information, and turning it into the base currency is an
    assertion about the data that someone should have to make on purpose."""
    base = require_base(root)
    cur = (currency or base).upper()
    total = 0
    for name, schema in fx_registries(root):
        if only and name != only:
            continue
        path = registry_path(root, schema)
        if not os.path.exists(path):
            continue
        header, rows = csvguard.read_table(path, schema)
        idx = {h: i for i, h in enumerate(header)}
        ccol = schema["fx"].get("currency_column", "currency")
        if ccol not in idx or "id" not in idx:
            continue
        money_cols = [p["from"] for p in schema["fx"]["convert"] if p["from"] in idx]
        recs = []
        for row in rows:
            rid = row[idx["id"]]
            if not rid or (row[idx[ccol]] or "").strip():
                continue
            if not any((row[idx[m]] or "").strip() for m in money_cols):
                continue      # no money on the row, nothing to denominate
            recs.append({"id": rid, ccol: cur})
        if not recs:
            continue
        total += len(recs)
        print(f"{name}: {len(recs)} row(s) with money and no currency -> {cur}")
        if not dry_run:
            owner = csvguard.column_owner(
                next(c for c in schema["columns"] if c["name"] == ccol))
            csvguard.upsert(path, schema, recs, key="id", root=root,
                            only_owner=owner, stamp=False, force=force)
    if dry_run:
        print("(dry run — nothing written)")
    elif total:
        print(f"\n{total} row(s) stamped {cur}. Run --convert to fill the converted "
              f"columns.")
    else:
        print("nothing to backfill.")
    return 0


def cmd_refreeze(root, registry, ids, dry_run=False, force=False):
    """Deliberately recompute a frozen record. The one door through the freeze, and it
    needs an id — there is no 'refreeze everything', because that is just an unfreeze."""
    base = require_base(root)
    rates, _, _ = load_rates(root, source=rate_source(root))
    schemas = dict(fx_registries(root))
    if registry not in schemas:
        sys.exit(f"error: {registry} has no fx block. One of: {', '.join(schemas)}")
    schema = schemas[registry]
    path = registry_path(root, schema)
    header, rows = csvguard.read_table(path, schema)
    idx = {h: i for i, h in enumerate(header)}
    wanted = set(ids)
    recs = []
    for row in rows:
        if row[idx["id"]] not in wanted:
            continue
        rec = {"id": row[idx["id"]]}
        for p in schema["fx"]["convert"]:
            rec[p["to"]] = ""
        for c in ("fx_rate", "fx_rate_date", "converted_currency"):
            if c in idx:
                rec[c] = ""
        recs.append(rec)
    found = {r["id"] for r in recs}
    for missing in wanted - found:
        print(f"warning: {missing} not found in {registry}", file=sys.stderr)
    if not recs:
        return 1
    print(f"clearing the frozen conversion on {len(recs)} record(s): "
          f"{', '.join(sorted(found))}")
    if dry_run:
        print("(dry run — nothing written)")
        return 0
    csvguard.upsert(path, schema, recs, key="id", root=root, only_owner="derived",
                    allow_clear=True, stamp=False, force=force)
    return cmd_convert(root, only=registry, force=force)


def cmd_rates(root):
    base = base_currency(root) or "?"
    src = rate_source(root)
    rates, path, _ = load_rates(root)
    if not rates:
        print(f"no rates on file ({os.path.relpath(path, root)})")
        return 1
    print(f"base currency: {base}   (multiply by rate_to_base to get {base})")
    print(f"rate source:   {src}   (* = in force, > = the row that converts)")
    for cur, hist in sorted(rates.items()):
        for source in sorted({r["source"] for r in hist}):
            group = [r for r in hist if r["source"] == source]
            for r in group:
                current = r is group[-1]
                mark = (">" if source == src else "*") if current else " "
                print(f" {mark} {cur:>4}  {r['rate_to_base']:>12.8f}  from "
                      f"{r['effective_from']}  {source}")
    return 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--pull", metavar="PROJECT")
    ap.add_argument("--fetch", metavar="PROJECT",
                    help="Fetch rates from a public source instead of the CRM")
    ap.add_argument("--provider", default=DEFAULT_PROVIDER,
                    choices=sorted(PROVIDERS),
                    help="Public rate source for --fetch (default: ecb)")
    ap.add_argument("--date", help="Fetch the rate in force on this date (ECB only)")
    ap.add_argument("--symbols",
                    help="Comma-separated currencies to fetch. Default: every currency "
                         "the folder actually holds money in.")
    ap.add_argument("--convert", metavar="PROJECT")
    ap.add_argument("--check", metavar="PROJECT")
    ap.add_argument("--backfill-currency", dest="backfill", metavar="PROJECT")
    ap.add_argument("--refreeze", metavar="PROJECT")
    ap.add_argument("--rates", metavar="PROJECT")
    ap.add_argument("--registry")
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--currency")
    ap.add_argument("--json")
    ap.add_argument("--json-file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    if a.pull:
        payload = None
        if a.json_file:
            with open(a.json_file, encoding="utf-8") as f:
                payload = json.load(f)
        elif a.json:
            payload = json.loads(a.json)
        if not payload:
            sys.exit("error: --pull needs --json or --json-file holding "
                     '{"base":"USD","convention":"units-of-currency-per-base",'
                     '"rates":{"EUR":0.91}}')
        return cmd_pull(os.path.abspath(a.pull), payload, dry_run=a.dry_run)
    if a.fetch:
        syms = [c.strip() for c in a.symbols.split(",")] if a.symbols else None
        return cmd_fetch(os.path.abspath(a.fetch), symbols=syms, on=a.date,
                         provider=a.provider, dry_run=a.dry_run)
    if a.convert:
        return cmd_convert(os.path.abspath(a.convert), only=a.registry,
                           dry_run=a.dry_run, verbose=a.verbose, force=a.force)
    if a.check:
        return cmd_check(os.path.abspath(a.check))
    if a.backfill:
        return cmd_backfill(os.path.abspath(a.backfill), only=a.registry,
                            currency=a.currency, dry_run=a.dry_run, force=a.force)
    if a.refreeze:
        if not a.registry or not a.id:
            sys.exit("error: --refreeze needs --registry and at least one --id")
        return cmd_refreeze(os.path.abspath(a.refreeze), a.registry, a.id,
                            dry_run=a.dry_run, force=a.force)
    if a.rates:
        return cmd_rates(os.path.abspath(a.rates))
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
