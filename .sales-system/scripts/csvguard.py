#!/usr/bin/env python3
"""
csvguard.py — keeps the sales registries safe, in whichever format they're stored.

A registry lives as either .csv or .xlsx, set per project by `storage_format:` in
00-Config/config.md. This script is the single entry point for both: it reads, validates,
repairs, and writes through a format layer, so every skill uses the same commands
regardless. For .xlsx it delegates presentation to sheetstyle.py.

The premise of this system is that a salesperson can open leads.csv in Excel,
change things, and save. Excel is not gentle about that: it rewrites ISO dates
into locale dates, coerces IDs that look numeric, adds currency symbols and
thousands separators, strips leading zeros, and sometimes adds a BOM.

Rather than telling the user "don't do that", every skill runs this first and
repairs the damage. User-added columns are always preserved — if someone adds a
"my notes" column, it survives.

Usage:
  csvguard.py --check-all <project_root>
  csvguard.py --check <csv_path>
  csvguard.py --repair <csv_path>            # writes a backup first
  csvguard.py --next-id <csv_path>
  csvguard.py --append <csv_path> --json '{"company":"Acme",...}'
  csvguard.py --upsert <path> --key crm_id --json-file <records.json>
  csvguard.py --init <path> --schema <schema_name> --project <root>
  csvguard.py --convert <path> [--to xlsx|csv]
  csvguard.py --convert-all <project_root> --to xlsx
  csvguard.py --restyle <path.xlsx>       # reapply the Excel styling contract
  csvguard.py --sync-query <project_root> [--registry leads]
  csvguard.py --verify-sync <project_root> --registry leads --crm-json <snapshot.json>

Paths are format-agnostic: pass leads.csv and it will find leads.xlsx if that's what
exists.

Exit codes: 0 clean/repaired, 1 problems needing a human, 2 usage error.

Two things here are about *not losing data*, and they matter more than the tidying:

  - Every full-file write is diffed against what it is about to replace. A write that
    deletes rows, blanks cells, reopens closed records or churns a fifth of the file is
    refused with a summary until someone passes --force. Rebuild scripts are the main
    way live edits get silently reverted, and they always look correct afterwards.
  - Bulk loading goes through --upsert, which matches on a stable key and owns the IDs,
    so a re-run can never renumber rows and orphan everything pointing at them.
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
from datetime import datetime, date, timedelta

SYSTEM_DIR = ".sales-system"
SCHEMA_DIR = os.path.join(SYSTEM_DIR, "schemas")
BACKUP_DIR = os.path.join(SYSTEM_DIR, "backups")

# ---------------------------------------------------------------- schema load


def find_project_root(start):
    """Walk up from a path until we find the folder holding .sales-system."""
    p = os.path.abspath(start)
    if os.path.isfile(p):
        p = os.path.dirname(p)
    while True:
        if os.path.isdir(os.path.join(p, SYSTEM_DIR)):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


PROFILE_DIR = os.path.join(SYSTEM_DIR, "crm-profile")


def load_picklist_overrides(root):
    """The shipped schemas carry generic placeholder values. A real org's CRM has its
    own — 'Replied to Sequence', 'Closed Won - Renewal', whatever. configure-project
    writes those to crm-profile/picklists.json so validation matches reality instead of
    flagging every real record as invalid."""
    p = os.path.join(root, PROFILE_DIR, "picklists.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"warning: couldn't read {p} ({e}); using generic values", file=sys.stderr)
        return {}


def load_schemas(root):
    out = {}
    d = os.path.join(root, SCHEMA_DIR)
    if not os.path.isdir(d):
        return out
    overrides = load_picklist_overrides(root)
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                s = json.load(f)
            reg = overrides.get(s["registry"], {})
            if reg:
                allowed = set(s.get("picklists_overridable", []))
                for col in s["columns"]:
                    vals = reg.get(col["name"])
                    if not vals:
                        continue
                    if allowed and col["name"] not in allowed:
                        print(f"warning: {s['registry']}.{col['name']} is not marked "
                              f"overridable; ignoring profile override", file=sys.stderr)
                        continue
                    col["values"] = list(vals)
                    col["type"] = "enum"
            out[s["registry"]] = s
    return out


def schema_for_file(csv_path, root=None):
    """Match on the path stem so a registry resolves whether it's stored .csv or .xlsx."""
    root = root or find_project_root(csv_path)
    if not root:
        return None, None
    rel = os.path.relpath(os.path.abspath(csv_path), root).replace(os.sep, "/")
    stem = os.path.splitext(rel)[0]
    for s in load_schemas(root).values():
        if s.get("path") == rel or os.path.splitext(s.get("path", ""))[0] == stem:
            return s, root
    return None, root


# ------------------------------------------------------ storage format layer
# A registry lives as either .csv or .xlsx. The choice is per-project, set during
# setup and recorded in 00-Config/config.md. Everything above this line works in
# canonical strings and neither knows nor cares which is on disk.


def storage_format(root):
    """Read `storage_format:` from config. Default csv — the format that needs no library."""
    cfg = os.path.join(root, "00-Config", "config.md")
    if os.path.exists(cfg):
        try:
            with open(cfg, encoding="utf-8") as f:
                m = re.search(r"^\s*[-*]?\s*storage[_ ]format\s*:\s*(\w+)",
                              f.read(), re.MULTILINE | re.IGNORECASE)
            if m and m.group(1).lower() in ("csv", "xlsx", "excel"):
                return "xlsx" if m.group(1).lower() in ("xlsx", "excel") else "csv"
        except OSError:
            pass
    return "csv"


def resolve_path(path, root=None):
    """Return the file that actually exists for this registry, whichever format it's in."""
    if os.path.exists(path):
        return path
    stem = os.path.splitext(path)[0]
    for ext in (".xlsx", ".csv"):
        if os.path.exists(stem + ext):
            return stem + ext
    return path


def _sheetstyle():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sheetstyle
    return sheetstyle


def read_table(path, schema=None):
    if path.lower().endswith(".xlsx"):
        return _sheetstyle().read_xlsx(path, schema)
    return read_csv(path)


LOCK_DIR = os.path.join(SYSTEM_DIR, "locks")
LOCK_STALE_SECONDS = 600


def _lock_path(path, root):
    root = root or find_project_root(path) or os.path.dirname(path)
    d = os.path.join(root, LOCK_DIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, os.path.basename(path) + ".lock")


def acquire_lock(path, root=None):
    """Advisory lease so two sessions on a shared drive don't interleave writes.
    Best-effort by design — sync layers add seconds of lag no lockfile can close —
    but it turns the common collision into a polite retry instead of lost rows."""
    import time, getpass, socket
    lp = _lock_path(path, root)
    for attempt in range(3):
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                json.dump({"owner": getpass.getuser(), "host": socket.gethostname(),
                           "ts": time.time()}, f)
            return lp
        except FileExistsError:
            try:
                with open(lp, encoding="utf-8") as f:
                    info = json.load(f)
                age = time.time() - float(info.get("ts", 0))
            except Exception:
                info, age = {}, LOCK_STALE_SECONDS + 1
            if age > LOCK_STALE_SECONDS:
                try:
                    os.remove(lp)   # stale — a crashed or abandoned session
                    continue
                except OSError:
                    pass
            if attempt < 2:
                time.sleep(2)
                continue
            raise RuntimeError(
                f"{os.path.basename(path)} is locked by "
                f"{info.get('owner','another session')}@{info.get('host','?')} "
                f"({age:.0f}s ago). Retry shortly; if that session crashed, the lock "
                f"goes stale after {LOCK_STALE_SECONDS//60} minutes.")


def release_lock(lp):
    try:
        if lp and os.path.exists(lp):
            os.remove(lp)
    except OSError:
        pass


def excel_has_open(path):
    """Excel drops a hidden ~$ owner file next to a workbook it has open. Writing
    underneath a live Excel session loses whichever side saves second."""
    d, b = os.path.split(path)
    return os.path.exists(os.path.join(d, "~$" + b))


# ------------------------------------------------------- the destructive-write guard
# Validation proves a registry is well-formed. It cannot prove it is *right*. The way
# rows get lost in practice is a script that rebuilds the file from a snapshot it loaded
# an hour ago — every row valid, every row wrong, and nothing to notice it afterwards
# because the result validates clean.
#
# So every full-file write is compared against the file it is replacing, and refused if
# the change has the shape of an accident. Thresholds are deliberately loose: this is
# meant to catch a rebuild, not to nag about editing.

ROW_LOSS_LIMIT = 0.10      # fraction of existing rows that may disappear
ROW_LOSS_FLOOR = 2         # ...and at least this many, so a 4-row file isn't touchy
CHURN_LIMIT = 0.20         # fraction of surviving rows that may change value
CHURN_FLOOR = 10           # ...and at least this many
CLEAR_LIMIT = 20           # non-empty cells that may be blanked
REOPEN_LIMIT = 0           # closed records that may silently return to an open state


class DestructiveWrite(RuntimeError):
    """Raised instead of replacing a registry with something that looks like a mistake."""


def _key_index(header):
    return header.index("id") if "id" in header else 0


def diff_tables(old_header, old_rows, new_header, new_rows, schema):
    """Describe what replacing old with new would actually do. Matched on id, because
    position is not identity — a sort order change is not a rewrite."""
    oi, ni = _key_index(old_header), _key_index(new_header)
    old_by = {r[oi]: r for r in old_rows if oi < len(r) and r[oi]}
    new_by = {r[ni]: r for r in new_rows if ni < len(r) and r[ni]}

    removed = [k for k in old_by if k not in new_by]
    added = [k for k in new_by if k not in old_by]

    # Compare only columns present in both, and never the derived ones — those are
    # recomputed constantly and their churn says nothing about data loss.
    derived = {c["name"] for c in (schema or {}).get("columns", [])
               if c.get("owner") == "derived"}
    shared = [h for h in old_header if h in new_header and h not in derived]
    oidx = {h: i for i, h in enumerate(old_header)}
    nidx = {h: i for i, h in enumerate(new_header)}

    changed, cleared, samples = [], [], []
    for k, orow in old_by.items():
        nrow = new_by.get(k)
        if nrow is None:
            continue
        diffs = []
        for h in shared:
            a = orow[oidx[h]] if oidx[h] < len(orow) else ""
            b = nrow[nidx[h]] if nidx[h] < len(nrow) else ""
            if a == b:
                continue
            diffs.append((h, a, b))
            if a and not b:
                cleared.append((k, h))
        if diffs:
            changed.append(k)
            if len(samples) < 8:
                h, a, b = diffs[0]
                extra = f" (+{len(diffs) - 1} more field{'s' if len(diffs) > 2 else ''})" if len(diffs) > 1 else ""
                samples.append(f"{k}  {h}: {a!r} -> {b!r}{extra}")

    # A closed record going back to an open state is almost always a stale snapshot
    # overwriting a decision someone made. The archive policy already names the closed
    # states for each registry, so reuse it rather than inventing a second list.
    pol = (schema or {}).get("archive") or {}
    wc, wv = pol.get("when_column"), set(pol.get("when_values") or [])
    reopened = []
    if wc and wv and wc in oidx and wc in nidx:
        for k, orow in old_by.items():
            nrow = new_by.get(k)
            if nrow is None:
                continue
            was = orow[oidx[wc]] if oidx[wc] < len(orow) else ""
            now = nrow[nidx[wc]] if nidx[wc] < len(nrow) else ""
            if was in wv and now and now not in wv:
                reopened.append(f"{k}  {wc}: {was!r} -> {now!r}")

    return {"old_count": len(old_rows), "new_count": len(new_rows),
            "removed": removed, "added": added, "changed": changed,
            "cleared": cleared, "reopened": reopened, "samples": samples,
            "closed_column": wc}


def guard_write(path, header, rows, schema, force=False):
    """Refuse a write that looks like an accident. Returns a note when the write is
    large but allowed, so the caller can mention it."""
    if not os.path.exists(path):
        return None
    try:
        old_header, old_rows = read_table(path, schema)
    except Exception:
        return None          # unreadable current file: nothing to compare against
    if not old_rows:
        return None
    d = diff_tables(old_header, old_rows, header, rows, schema)
    n = max(1, d["old_count"])
    reasons = []
    if len(d["removed"]) > max(ROW_LOSS_FLOOR, int(n * ROW_LOSS_LIMIT)):
        reasons.append(f"{len(d['removed'])} of {n} rows would disappear")
    if len(d["changed"]) > max(CHURN_FLOOR, int(n * CHURN_LIMIT)):
        reasons.append(f"{len(d['changed'])} of {n} rows would change value")
    if len(d["cleared"]) > CLEAR_LIMIT:
        reasons.append(f"{len(d['cleared'])} non-empty cells would be blanked")
    if len(d["reopened"]) > REOPEN_LIMIT:
        # Rarely legitimate and expensive when it isn't: a stale snapshot writing over
        # a decision someone made. Worth stopping on even for one row.
        reasons.append(f"{len(d['reopened'])} closed record(s) would reopen")

    if not reasons:
        return None

    lines = [f"REFUSING TO WRITE {os.path.basename(path)} — this looks like an accident, "
             f"not an edit:"]
    for r in reasons:
        lines.append(f"  · {r}")
    lines.append(f"  {d['old_count']} rows now, {d['new_count']} after; "
                 f"{len(d['added'])} added, {len(d['removed'])} removed, "
                 f"{len(d['changed'])} changed")
    if d["samples"]:
        lines.append("  what would change:")
        for s in d["samples"]:
            lines.append(f"    {s}")
        if len(d["changed"]) > len(d["samples"]):
            lines.append(f"    ... and {len(d['changed']) - len(d['samples'])} more rows")
    if d["reopened"]:
        lines.append("  closed records reopening:")
        for s in d["reopened"][:5]:
            lines.append(f"    {s}")
    if d["removed"]:
        lines.append(f"  rows dropped: {', '.join(sorted(d['removed'])[:10])}"
                     + (" ..." if len(d["removed"]) > 10 else ""))
    lines.append("")
    lines.append("  If this is a rebuild from an old snapshot, it will revert live edits "
                 "and validate clean afterwards.")
    lines.append("  Check the diff above. To proceed anyway: pass --force "
                 "(or set SALESOS_FORCE_WRITE=1).")
    if force:
        return "\n".join(lines[:-2] + ["  Proceeding because --force was given."])
    raise DestructiveWrite("\n".join(lines))


def _forced(force):
    return bool(force) or os.environ.get("SALESOS_FORCE_WRITE", "") not in ("", "0", "no")


def write_table(path, header, rows, schema=None, root=None, backup=False,
                guard=True, force=False):
    if path.lower().endswith(".xlsx") and excel_has_open(path):
        raise RuntimeError(
            f"{os.path.basename(path)} appears to be open in Excel (a ~$ lock file is "
            f"present). Close it there first — writing underneath a live Excel session "
            f"means one side's changes get lost.")
    if guard:
        note = guard_write(path, header, rows, schema, force=_forced(force))
        if note:
            print(note, file=sys.stderr)
    lp = acquire_lock(path, root)
    try:
        if backup and os.path.exists(path):
            _backup(path)
        if path.lower().endswith(".xlsx"):
            if not schema:
                raise ValueError("writing .xlsx needs a schema")
            root = root or find_project_root(path)
            _sheetstyle().write_xlsx(path, header, rows, schema,
                                     load_picklist_overrides(root) if root else None)
        else:
            write_csv(path, header, rows, backup=False)
    finally:
        release_lock(lp)


# ------------------------------------------------------------- normalisation

DATE_PATTERNS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y",
    "%Y/%m/%d", "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y",
    "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
]
# Excel sometimes writes a raw serial number if the cell got retyped.
EXCEL_EPOCH = date(1899, 12, 30)


def norm_date(v):
    """Return (iso_string, changed, ok)."""
    s = (v or "").strip()
    if not s:
        return "", False, True
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s, False, True
    # Excel serial date
    if re.fullmatch(r"\d{5}(\.\d+)?", s):
        try:
            n = int(float(s))
            if 20000 < n < 80000:  # ~1954 to ~2119, plausible dates only
                d = EXCEL_EPOCH.toordinal() + n
                return date.fromordinal(d).isoformat(), True, True
        except (ValueError, OverflowError):
            pass
    s2 = s.split("T")[0] if "T" in s and len(s) > 10 else s
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(s, fmt).date().isoformat(), True, True
        except ValueError:
            continue
    for fmt in DATE_PATTERNS:
        try:
            return datetime.strptime(s2, fmt).date().isoformat(), True, True
        except ValueError:
            continue
    return s, False, False


MONEY_STRIP = re.compile(r"[^0-9.\-]")


def norm_money(v):
    s = (v or "").strip()
    if not s:
        return "", False, True
    neg = s.startswith("(") and s.endswith(")")   # accounting negatives
    cleaned = MONEY_STRIP.sub("", s)
    if cleaned in ("", "-", "."):
        return s, False, False
    try:
        n = float(cleaned)
    except ValueError:
        return s, False, False
    if neg:
        n = -abs(n)
    out = f"{n:.2f}".rstrip("0").rstrip(".")
    if out in ("", "-"):
        out = "0"
    return out, out != s, True


def norm_number(v):
    s = (v or "").strip()
    if not s:
        return "", False, True
    cleaned = s.replace(",", "").replace(" ", "").rstrip("%")
    try:
        f = float(cleaned)
    except ValueError:
        return s, False, False
    out = str(int(f)) if f == int(f) else str(f)
    return out, out != s, True


TRUE_SET = {"true", "yes", "y", "1", "x", "TRUE"}
FALSE_SET = {"false", "no", "n", "0", ""}


def norm_bool(v):
    s = (v or "").strip()
    if s.lower() in TRUE_SET:
        return "yes", s != "yes", True
    if s.lower() in FALSE_SET:
        return ("no", s != "no", True) if s else ("", False, True)
    return s, False, False


def norm_id(v, prefix, width):
    s = (v or "").strip()
    if not s:
        return "", False, True
    if re.fullmatch(rf"{re.escape(prefix)}-\d{{{width}}}", s):
        return s, False, True
    # Excel turned "LEAD-0012" into 12, or dropped the padding
    m = re.fullmatch(r"(?:%s-?)?(\d+)" % re.escape(prefix), s, re.IGNORECASE)
    if m:
        out = f"{prefix}-{int(m.group(1)):0{width}d}"
        return out, out != s, True
    return s, False, False


def norm_enum(v, values):
    s = (v or "").strip()
    if not s:
        return "", False, True
    for allowed in values:
        if s.lower() == allowed.lower():
            return allowed, s != allowed, True
    return s, False, False


def norm_text(v):
    s = (v or "")
    out = s.strip().replace("\r\n", "\n").replace("\r", "\n")
    out = re.sub(r"[ \t]+\n", "\n", out)
    return out, out != s, True


# ------------------------------------------------------------------ core ops


def read_csv(path):
    """Read tolerantly: handle BOM, blank trailing rows, ragged rows."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [], []
    header = [h.strip() for h in rows[0]]
    body = []
    for r in rows[1:]:
        if not any((c or "").strip() for c in r):
            continue
        if len(r) < len(header):
            r = r + [""] * (len(header) - len(r))
        body.append(r)
    return header, body


def process(path, schema, repair=False):
    """Validate and optionally normalise. Returns (fixes, problems, header, rows)."""
    header, body = read_table(path, schema)
    fixes, problems = [], []

    cols = schema["columns"]
    names = [c["name"] for c in cols]
    prefix = schema.get("id_prefix", "REC")
    width = schema.get("id_width", 4)

    # --- header reconciliation. Extra columns the user added are kept, at the end.
    missing = [n for n in names if n not in header]
    extra = [h for h in header if h not in names and h]
    if missing:
        fixes.append(f"added missing column(s): {', '.join(missing)}")
    if extra:
        fixes.append(f"kept your extra column(s): {', '.join(extra)}")

    new_header = names + extra
    idx = {h: i for i, h in enumerate(header)}
    rebuilt = []
    for r in body:
        rebuilt.append([r[idx[h]] if h in idx and idx[h] < len(r) else "" for h in new_header])

    # --- per-cell normalisation
    spec = {c["name"]: c for c in cols}
    for ri, row in enumerate(rebuilt):
        line = ri + 2  # 1-based, plus header
        for ci, cname in enumerate(new_header):
            c = spec.get(cname)
            if not c:
                row[ci], _, _ = norm_text(row[ci])
                continue
            t = c.get("type", "text")
            v = row[ci]
            if t == "id":
                nv, ch, ok = norm_id(v, prefix, width)
            elif t == "date":
                nv, ch, ok = norm_date(v)
            elif t == "money":
                nv, ch, ok = norm_money(v)
            elif t == "number":
                nv, ch, ok = norm_number(v)
            elif t == "bool":
                nv, ch, ok = norm_bool(v)
            elif t == "enum":
                nv, ch, ok = norm_enum(v, c.get("values", []))
            else:
                nv, ch, ok = norm_text(v)
            row[ci] = nv
            if ch:
                fixes.append(f"row {line} · {cname}: {v!r} -> {nv!r}")
            if not ok:
                if t == "enum":
                    problems.append(
                        f"row {line} · {cname}: {v!r} is not one of "
                        f"{', '.join(c.get('values', []))}")
                else:
                    problems.append(f"row {line} · {cname}: can't read {v!r} as {t}")
            # Blank ids are not a problem — the id pass below fills them in.
            if c.get("required") and not nv and t != "id":
                problems.append(f"row {line} · {cname} is required but empty")

    # --- ids: fill blanks, catch duplicates
    if "id" in new_header:
        i = new_header.index("id")
        seen, used = {}, set()
        for row in rebuilt:
            if row[i]:
                used.add(row[i])
        nxt = next_free(used, prefix, width)
        for ri, row in enumerate(rebuilt):
            if not row[i]:
                row[i] = f"{prefix}-{nxt:0{width}d}"
                fixes.append(f"row {ri + 2}: assigned id {row[i]}")
                used.add(row[i])
                nxt += 1
            if row[i] in seen:
                problems.append(
                    f"row {ri + 2}: id {row[i]} duplicates row {seen[row[i]]} — "
                    f"two records can't share an id")
            else:
                seen[row[i]] = ri + 2

    if repair and (fixes or missing or extra):
        # Exempt from the destructive-write guard: normalisation touches cells but never
        # identity — no row is dropped, no value is blanked, nothing reopens. Guarding it
        # would fire on the first import of a file full of Excel-mangled dates, which is
        # exactly when the user least wants an argument.
        write_table(path, new_header, rebuilt, schema=schema, backup=True, guard=False)

    return fixes, problems, new_header, rebuilt


def next_free(used, prefix, width):
    n = 0
    for u in used:
        m = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", u)
        if m:
            n = max(n, int(m.group(1)))
    return n + 1


# -------------------------------------------------------------- identity across systems
# This system is CRM-agnostic and stays that way: nothing assumes a vendor. But
# individual CRMs have quirks that silently corrupt an import, and the only honest way to
# handle one is to name the CRM, describe the quirk, and apply the handling to that CRM
# alone. Everything not listed gets the generic behaviour, which is to leave values alone.
#
# `crm` in crm-profile/field-map.json selects the dialect. With no profile, or a CRM with
# no entry here, every vendor-specific branch below is a no-op.

CRM_DIALECTS = {
    "salesforce": {
        "id_field": "Id",
        "modified_fields": ["LastModifiedDate", "SystemModstamp"],
        "query_language": "soql",
        # Two forms of every record ID are in circulation: reports and the UI export 15
        # characters, the API returns 18. Compared raw they never match, which imports
        # every record twice.
        "id_form": "salesforce_15_18",
        # Custom fields end __c and managed packages namespace them
        # (SalesLoft1__Active_Lead__c); neither shows up in the report label.
        "field_suffix": "__c",
        "namespace_separator": "__",
    },
    "hubspot": {
        "id_field": "hs_object_id",
        "modified_fields": ["hs_lastmodifieddate", "lastmodifieddate", "updatedAt"],
        "id_aliases": ["id", "vid", "objectId", "Record ID"],
    },
    "dynamics": {
        "id_field": "id",
        "modified_fields": ["modifiedon"],
        "id_aliases": ["accountid", "opportunityid", "leadid", "contactid"],
    },
    "pipedrive": {"id_field": "id", "modified_fields": ["update_time"]},
    "zoho": {"id_field": "id", "modified_fields": ["Modified_Time"]},
    "close": {"id_field": "id", "modified_fields": ["date_updated"]},
    "sugar": {"id_field": "id", "modified_fields": ["date_modified"]},
}

GENERIC_DIALECT = {
    "id_field": "id",
    # Enough shapes to cover a CRM nobody has written a dialect for. Matched
    # case-insensitively, and only ever as a fallback.
    "modified_fields": ["last_modified", "lastmodified", "modified", "updated_at",
                        "updatedat", "date_modified", "modified_date", "last_modified_date"],
    "id_aliases": ["record_id", "recordid", "object_id", "objectid"],
    "query_language": None,
    "id_form": None,
    "field_suffix": None,
    "namespace_separator": None,
}

DIALECT_KEYS = ("id_field", "modified_fields", "id_aliases", "query_language",
                "id_form", "field_suffix", "namespace_separator")


def dialect_for(root_or_map):
    """Resolve the CRM dialect. field-map.json may override any key explicitly, which is
    how a CRM with no entry above — or an org whose API has been customised — gets
    handled without a code change."""
    fm = root_or_map if isinstance(root_or_map, dict) else load_field_map(root_or_map)
    d = dict(GENERIC_DIALECT)
    vendor = CRM_DIALECTS.get(str(fm.get("crm", "")).strip().lower(), {})
    for k, v in vendor.items():
        # The vendor's names for identifiers and timestamps are additions, not
        # replacements — an export may still use the generic label, and recognising both
        # costs nothing.
        if k in ("id_aliases", "modified_fields"):
            d[k] = list(v) + [x for x in d[k] if x not in v]
        else:
            d[k] = v
    for k in DIALECT_KEYS:
        if fm.get(k):
            d[k] = fm[k]
    return d


# Set once per run from the project's profile, so call sites don't each have to thread it
# through. Stays generic when there's no CRM at all.
_DIALECT = dict(GENERIC_DIALECT)


def set_dialect(root_or_map):
    global _DIALECT
    _DIALECT = dialect_for(root_or_map)
    return _DIALECT


SFID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"


def sf_checksum(id15):
    """The last three characters of an 18-character Salesforce ID encode which of the
    first fifteen are uppercase — five bits per chunk, one character per chunk."""
    out = []
    for chunk in (id15[0:5], id15[5:10], id15[10:15]):
        n = 0
        for j, ch in enumerate(chunk):
            if ch.isupper() and ch.isalpha():
                n |= 1 << j
        out.append(SFID_ALPHABET[n])
    return "".join(out)


def crm_key(v, dialect=None):
    """A comparable form of a CRM record id. Every match in this system goes through
    here; nothing compares crm_id directly.

    **The default is to change nothing.** An ID is an opaque string, and guessing at its
    structure is how unrelated records get merged. Only a CRM whose dialect declares an
    `id_form` gets anything else, and Salesforce is currently the only one that does.

    Even there, truncating any 18-character string to 15 would be wrong — plenty of
    systems use 18-character IDs whose difference lives in the last three characters. So
    the suffix has to verify as the Salesforce checksum of the first fifteen, which a
    non-Salesforce ID has no reason to satisfy."""
    s = (v or "").strip()
    d = dialect if dialect is not None else _DIALECT
    if d.get("id_form") == "salesforce_15_18":
        if len(s) == 18 and s.isalnum() and sf_checksum(s[:15]) == s[15:].upper():
            return s[:15]
    return s


def best_crm_id(existing, incoming):
    """Keep the more informative of two forms of the same id. Only meaningful where a
    CRM has long and short forms — elsewhere the two are equal or unrelated and this
    returns the incoming value unchanged."""
    e, i = (existing or "").strip(), (incoming or "").strip()
    if crm_key(e) != crm_key(i):
        return i or e
    return e if len(e) >= len(i) else i


def load_field_map(root):
    p = os.path.join(root, PROFILE_DIR, "field-map.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"warning: couldn't read field-map.json ({e})", file=sys.stderr)
        return {}


def column_owner(col):
    """Who is allowed to write this column. Declared per column in the schema; the
    default is 'local', because a field nobody has classified is safer left alone than
    overwritten by an import."""
    return col.get("owner", "local")


def schema_by_registry(root, registry):
    s = load_schemas(root).get(registry)
    if not s:
        raise SystemExit(f"error: no schema named {registry!r}. "
                         f"Have: {', '.join(sorted(load_schemas(root))) or '(none)'}")
    return s


# ------------------------------------------------------------------------ upsert
# The only supported way to bulk-load. It matches on a stable key and mints IDs itself,
# so a re-run updates rows in place instead of rebuilding them — which is what stops a
# refresh renumbering every row and orphaning everything that pointed at them.


def upsert(path, schema, records, key="crm_id", root=None, only_owner=None,
           allow_clear=False, stamp=True, force=False):
    """Merge records into a registry. Returns (updated, inserted, skipped, changes)."""
    set_dialect(root or find_project_root(path) or {})
    if not os.path.exists(path):
        write_table(path, [c["name"] for c in schema["columns"]], [], schema=schema,
                    root=root, guard=False)
    header, rows = read_table(path, schema)
    idx = {h: i for i, h in enumerate(header)}
    if key not in idx:
        raise SystemExit(f"error: {os.path.basename(path)} has no {key!r} column to match on")

    spec = {c["name"]: c for c in schema["columns"]}
    writable = set(header)
    if only_owner:
        allowed = set(only_owner if isinstance(only_owner, (list, set, tuple)) else [only_owner])
        writable = {h for h in header
                    if h not in spec or column_owner(spec[h]) in allowed}
        writable |= {key, "crm_id", "sync_status", "last_synced", "crm_last_modified",
                     "last_updated"}
        writable &= set(header)

    ki = idx[key]
    by_key = {}
    for r in rows:
        k = crm_key(r[ki]) if ki < len(r) else ""
        if k:
            by_key.setdefault(k, r)

    idi = idx.get("id")
    used = {r[idi] for r in rows if idi is not None and idi < len(r) and r[idi]}
    prefix, width = schema.get("id_prefix", "REC"), schema.get("id_width", 4)
    nxt = next_free(used, prefix, width)
    today = date.today().isoformat()

    updated, inserted, skipped, changes = 0, 0, 0, []
    for rec in records:
        k = crm_key(rec.get(key, ""))
        if not k:
            skipped += 1
            continue
        row = by_key.get(k)
        if row is None:
            row = [""] * len(header)
            if idi is not None:
                row[idi] = f"{prefix}-{nxt:0{width}d}"
                used.add(row[idi])
                nxt += 1
            rows.append(row)
            by_key[k] = row
            inserted += 1
            touched = None
        else:
            touched = []

        for f, v in rec.items():
            if f not in idx or f == "id":
                continue
            if f not in writable:
                continue
            v = "" if v is None else str(v)
            cur = row[idx[f]]
            if f == "crm_id":
                v = best_crm_id(cur, v)
            if v == "" and cur and not allow_clear:
                continue          # an absent field in a feed is silence, not a deletion
            if v == cur:
                continue
            row[idx[f]] = v
            if touched is not None:
                touched.append(f)

        if touched:
            updated += 1
            if len(changes) < 40:
                rid = row[idi] if idi is not None else k
                changes.append(f"{rid}: {', '.join(touched[:6])}"
                               + (" ..." if len(touched) > 6 else ""))
        if stamp:
            for col, val in (("last_synced", today), ("last_updated", today)):
                if col in idx and (touched or touched is None):
                    row[idx[col]] = val
            if "sync_status" in idx and (touched or touched is None):
                row[idx["sync_status"]] = "synced"
            if "crm_last_modified" in idx and rec.get("crm_last_modified"):
                row[idx["crm_last_modified"]] = str(rec["crm_last_modified"])

    write_table(path, header, rows, schema=schema, root=root, backup=True, force=force)
    return updated, inserted, skipped, changes


# --------------------------------------------------------------- sync verification
# CONVENTIONS §7 describes drift. This computes it. The comparison lives here and the
# CRM read lives in the skill, because the CRM is reachable only through a connector the
# agent holds — so the skill fetches a snapshot and hands it over as JSON.


def verify_fields(schema):
    """Columns worth comparing: explicitly marked, or CRM-owned and cheap to compare."""
    marked = [c["name"] for c in schema["columns"] if c.get("verify")]
    if marked:
        return marked
    return [c["name"] for c in schema["columns"]
            if column_owner(c) == "crm" and c.get("type") in
            ("text", "enum", "date", "money", "number")][:8]


def sync_query(root, registry):
    """Print what to pull from the CRM in order to verify this registry."""
    schema = schema_by_registry(root, registry)
    fm = load_field_map(root)
    obj = (fm.get("objects", {}) or {}).get(registry, {})
    fields = obj.get("fields", {})
    if not obj:
        print(f"{registry}: no CRM mapping in crm-profile/field-map.json — "
              f"this registry is local-only, nothing to verify.")
        return 0
    d = dialect_for(fm)
    want = ["crm_id"] + [f for f in verify_fields(schema) if f in fields]
    api = []
    for f in want:
        a = fields.get(f)
        if a and a not in api:
            api.append(a)
    # The record's own identifier and its last-modified stamp are what make drift
    # computable, and neither is usually in the field map. Fall back to the dialect's
    # names for them — but only where the profile hasn't already named one, or the query
    # ends up asking for the same column twice under two names.
    if not fields.get("crm_id") and d["id_field"]:
        api.append(d["id_field"])
    if not fields.get("crm_last_modified") and d["modified_fields"]:
        api.append(d["modified_fields"][0])
    print(f"object:   {obj.get('crm_object', registry)}")
    print(f"filter:   {obj.get('default_filter', '(none recorded)')}")
    print(f"fields:   {', '.join(api)}")
    print(f"local:    {', '.join(want)}")
    print()
    if d["query_language"] == "soql":
        where = obj.get("default_filter")
        print(f"SELECT {', '.join(api)} FROM {obj.get('crm_object', registry)}"
              + (f" WHERE {where}" if where else ""))
        print()
    else:
        # No query language declared: say what's needed and let the connector's own
        # tools decide how to ask for it. Inventing a query for an unknown API produces
        # something that looks authoritative and doesn't run.
        print(f"Fetch those fields for every {obj.get('crm_object', registry)} record "
              f"matching the filter, however this connector does that.")
        print()
    print("Hand the result back as a JSON list, keyed by either the CRM field names or "
          "the local column names — both are understood:")
    print(f"  csvguard.py --verify-sync <project> --registry {registry} "
          f"--crm-json <snapshot.json>")
    return 0


def _to_local(rec, fields, schema, dialect=None):
    """Accept a CRM record keyed by API names, local names, or a mix.

    The mapped fields come from the profile and are already CRM-agnostic. The two that
    usually aren't mapped — the record's identifier and its last-modified stamp — are
    resolved from the dialect, falling back to a case-insensitive match against a generic
    list so an unrecognised CRM still works."""
    d = dialect if dialect is not None else _DIALECT

    def flat(s):
        # 'Record ID', 'record_id' and 'recordId' are the same column with three export
        # conventions applied to it.
        return re.sub(r"[^0-9a-z]+", "", str(s).lower())

    rev = {v: k for k, v in (fields or {}).items()}
    names = {c["name"] for c in schema["columns"]}
    id_names = {flat(x) for x in
                [d.get("id_field"), "crm_id"] + list(d.get("id_aliases") or []) if x}
    mod_names = {flat(x) for x in
                 list(d.get("modified_fields") or []) + ["crm_last_modified"]}
    out = {}
    for k, v in rec.items():
        if k in rev:
            out[rev[k]] = v
        elif k in names:
            out[k] = v
        elif flat(k) in id_names:
            out.setdefault("crm_id", v)
        elif flat(k) in mod_names:
            out.setdefault("crm_last_modified", v)
    return out


def _same(a, b, col):
    """Compare the way a human would: 120000 == $120,000.00, and a timestamp's date part
    is enough for a date column."""
    a, b = (a or "").strip(), ("" if b is None else str(b)).strip()
    t = (col or {}).get("type", "text")
    if t in ("money", "number"):
        na, _, oka = (norm_money(a) if t == "money" else norm_number(a))
        nb, _, okb = (norm_money(b) if t == "money" else norm_number(b))
        if oka and okb:
            try:
                return abs(float(na or 0) - float(nb or 0)) < 0.005
            except ValueError:
                pass
        return na == nb
    if t == "date":
        na, _, _ = norm_date(a)
        nb, _, _ = norm_date(b)
        return na == nb
    if t == "bool":
        return norm_bool(a)[0] == norm_bool(b)[0]
    return a.strip().lower() == b.strip().lower()


def verify_sync(root, registry, crm_records, verbose=False):
    """Compare a CRM snapshot against the local registry. Reports drift in both
    directions, because both happen and they need opposite responses."""
    schema = schema_by_registry(root, registry)
    path = resolve_path(os.path.join(root, schema["path"]), root)
    if not os.path.exists(path):
        print(f"{registry}: no local registry yet — nothing to compare")
        return 0
    fm = load_field_map(root)
    d = set_dialect(fm)
    fields = ((fm.get("objects", {}) or {}).get(registry, {}) or {}).get("fields", {})
    spec = {c["name"]: c for c in schema["columns"]}

    header, rows = read_table(path, schema)
    idx = {h: i for i, h in enumerate(header)}
    if "crm_id" not in idx:
        print(f"{registry}: not a synced registry (no crm_id column)")
        return 0

    incoming = {}
    for rec in crm_records:
        loc = _to_local(rec, fields, schema, d)
        k = crm_key(loc.get("crm_id", ""))
        if k:
            incoming[k] = loc

    compare = [f for f in verify_fields(schema) if f in idx]
    drift, ahead, conflict, gone, unmatched, local_only = [], [], [], [], [], 0
    verified = 0
    seen = set()

    # A snapshot is usually pulled with the profile's default filter, which normally
    # excludes closed records. A closed row missing from it is expected, not a warning —
    # and warnings people learn to expect are warnings they stop reading.
    pol = schema.get("archive") or {}
    closed_col, closed_vals = pol.get("when_column"), set(pol.get("when_values") or [])
    closed_absent = 0

    for r in rows:
        cid = r[idx["crm_id"]] if idx["crm_id"] < len(r) else ""
        rid = r[idx["id"]] if "id" in idx and idx["id"] < len(r) else "(no id)"
        if not cid:
            local_only += 1
            continue
        k = crm_key(cid)
        seen.add(k)
        crm = incoming.get(k)
        if crm is None:
            state = (r[idx[closed_col]] if closed_col in idx
                     and idx[closed_col] < len(r) else "")
            if state and state in closed_vals:
                closed_absent += 1
            else:
                gone.append(f"{rid}  {cid} — not in the CRM snapshot (deleted, "
                            f"reassigned, or outside the filter you pulled)")
            continue

        # Direction. crm_last_modified is the CRM's timestamp as at our last sync; if the
        # CRM's timestamp has moved past it, the change came from over there.
        base = (r[idx["crm_last_modified"]] if "crm_last_modified" in idx
                and idx["crm_last_modified"] < len(r) else "")
        now = str(crm.get("crm_last_modified", "") or "")
        crm_moved = bool(base and now and now > base)
        synced_at = (r[idx["last_synced"]] if "last_synced" in idx
                     and idx["last_synced"] < len(r) else "")
        touched = (r[idx["last_updated"]] if "last_updated" in idx
                   and idx["last_updated"] < len(r) else "")
        local_moved = bool(synced_at and touched and touched > synced_at)
        status = (r[idx["sync_status"]] if "sync_status" in idx
                  and idx["sync_status"] < len(r) else "")
        if status == "pending-push":
            local_moved = True

        diffs = []
        for f in compare:
            lv = r[idx[f]] if idx[f] < len(r) else ""
            if f not in crm:
                continue
            if not _same(lv, crm.get(f), spec.get(f)):
                diffs.append((f, lv, "" if crm.get(f) is None else str(crm.get(f))))
        if not diffs:
            verified += 1
            continue

        for f, lv, cv in diffs:
            line = f"{rid}  {f}: local {lv!r} -> CRM {cv!r}"
            if crm_moved and local_moved:
                conflict.append(line + f"  (both changed; CRM at {now})")
            elif crm_moved:
                drift.append(line + f"  (CRM changed {now[:10]})")
            elif local_moved or (base and now and now == base):
                ahead.append(line + "  (changed here, never pushed)")
            else:
                unmatched.append(line + "  (no sync baseline — direction unknown)")

    new_in_crm = [k for k in incoming if k not in seen]

    print(f"{registry}: {len(rows)} rows, {verified} verified"
          + (f", {local_only} local-only" if local_only else "")
          + (f", {closed_absent} closed and outside the pull" if closed_absent else ""))
    for label, items in (("DRIFT", drift), ("AHEAD", ahead), ("CONFLICT", conflict),
                         ("UNKNOWN", unmatched), ("MISSING", gone)):
        cap = 200 if verbose else 25
        for line in items[:cap]:
            print(f"  {label:<9} {line}")
        if len(items) > cap:
            print(f"  {label:<9} ... and {len(items) - cap} more")
    if new_in_crm:
        print(f"  NEW       {len(new_in_crm)} record(s) in the CRM with no local row "
              f"— run crm_sync.py --refresh to bring them in")

    total = len(drift) + len(ahead) + len(conflict) + len(unmatched)
    if not total and not gone and not new_in_crm:
        print("  in sync.")
        return 0
    print()
    if drift:
        print(f"  DRIFT ({len(drift)}) — someone changed the CRM. Refresh to accept, or "
              f"push if your value is the right one.")
    if ahead:
        print(f"  AHEAD ({len(ahead)}) — changed here and never pushed. A push failed or "
              f"was skipped; the CRM is currently wrong.")
    if conflict:
        print(f"  CONFLICT ({len(conflict)}) — both sides changed. Per CONVENTIONS §7 "
              f"this needs you; don't let anything pick a winner.")
    if unmatched:
        print(f"  UNKNOWN ({len(unmatched)}) — these rows predate sync timestamps, so "
              f"the direction can't be derived. Treat as conflicts until refreshed.")
    return 1


def _backup(path):
    root = find_project_root(path)
    if not root:
        return
    bdir = os.path.join(root, BACKUP_DIR)
    os.makedirs(bdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, os.path.join(bdir, f"{os.path.basename(path)}.{stamp}.bak"))
    prune_backups(bdir, os.path.basename(path))


def write_csv(path, header, rows, backup=False):
    if backup and os.path.exists(path):
        _backup(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, path)


def prune_backups(bdir, base, keep=20):
    files = sorted(f for f in os.listdir(bdir) if f.startswith(base + "."))
    for f in files[:-keep]:
        try:
            os.remove(os.path.join(bdir, f))
        except OSError:
            pass


# -------------------------------------------------------------------- report


def report(path, fixes, problems, quiet_when_clean=True):
    rel = os.path.basename(path)
    if not fixes and not problems:
        if not quiet_when_clean:
            print(f"  {rel}: clean")
        return 0
    print(f"\n{rel}")
    for f in fixes[:40]:
        print(f"  fixed   {f}")
    if len(fixes) > 40:
        print(f"  fixed   ... and {len(fixes) - 40} more")
    for p in problems[:40]:
        print(f"  NEEDS YOU  {p}")
    if len(problems) > 40:
        print(f"  NEEDS YOU  ... and {len(problems) - 40} more")
    return 1 if problems else 0


# ---------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--check")
    ap.add_argument("--repair")
    ap.add_argument("--check-all")
    ap.add_argument("--next-id")
    ap.add_argument("--append")
    ap.add_argument("--upsert", help="Registry to merge records into, matched on --key")
    ap.add_argument("--key", default="crm_id", help="Match column for --upsert")
    ap.add_argument("--json")
    ap.add_argument("--json-file", help="Same as --json, read from a file")
    ap.add_argument("--only-owner", help="Comma-separated column owners --upsert may "
                                         "write (crm, local, derived)")
    ap.add_argument("--allow-clear", action="store_true",
                    help="Let an empty incoming value blank an existing one")
    ap.add_argument("--force", action="store_true",
                    help="Proceed past the destructive-write guard")
    ap.add_argument("--sync-query", help="Project root: print what to pull from the CRM")
    ap.add_argument("--verify-sync", dest="verify_sync",
                    help="Project root: compare a CRM snapshot against local")
    ap.add_argument("--registry", help="Registry name for --sync-query / --verify-sync")
    ap.add_argument("--crm-json", dest="crm_json", help="CRM snapshot for --verify-sync")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--init")
    ap.add_argument("--schema")
    ap.add_argument("--project")
    ap.add_argument("--archive", help="Project root: move closed/aged rows to 99-Archive")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--convert", help="Registry to convert between .csv and .xlsx")
    ap.add_argument("--to", choices=["csv", "xlsx"])
    ap.add_argument("--convert-all", help="Project root: convert every registry")
    ap.add_argument("--restyle", help="Reapply the Excel styling contract")
    a = ap.parse_args()

    # ---- init a registry from its schema (headers only)
    if a.init:
        root = a.project or find_project_root(a.init)
        if not root:
            print("error: can't find the project root (.sales-system)", file=sys.stderr)
            return 2
        schemas = load_schemas(root)
        s = schemas.get(a.schema)
        if not s:
            print(f"error: no schema named {a.schema!r}. "
                  f"Have: {', '.join(sorted(schemas)) or '(none)'}", file=sys.stderr)
            return 2
        # Plumbing registries (sync log, indexes) stay CSV whatever the project
        # setting says — they're append-only and nobody opens them.
        fmt = storage_format(root) if s.get("browsable", True) else "csv"
        target = a.init
        if os.path.splitext(target)[1].lower() not in (".csv", ".xlsx"):
            target = target + "." + fmt
        else:
            target = os.path.splitext(target)[0] + "." + fmt
        a.init = target
        if os.path.exists(a.init) or os.path.exists(resolve_path(a.init, root)):
            print(f"{os.path.basename(resolve_path(a.init, root))} already exists — leaving it alone")
            return 0
        write_table(a.init, [c["name"] for c in s["columns"]], [], schema=s, root=root)
        print(f"created {a.init} with {len(s['columns'])} columns")
        return 0

    # ---- sync verification. The CRM read belongs to the skill; the comparison is here.
    if a.sync_query:
        root = os.path.abspath(a.sync_query)
        regs = [a.registry] if a.registry else [
            n for n, s in sorted(load_schemas(root).items())
            if any(c["name"] == "crm_id" for c in s["columns"]) and s.get("browsable", True)]
        for i, reg in enumerate(regs):
            if i:
                print()
            sync_query(root, reg)
        return 0

    if a.verify_sync:
        root = os.path.abspath(a.verify_sync)
        if not a.registry:
            print("error: --verify-sync needs --registry", file=sys.stderr)
            return 2
        if not (a.crm_json or a.json):
            print("error: --verify-sync needs --crm-json <file> (or --json). Run "
                  "--sync-query first to see what to pull.", file=sys.stderr)
            return 2
        if a.crm_json:
            with open(a.crm_json, encoding="utf-8") as f:
                payload = json.load(f)
        else:
            payload = json.loads(a.json)
        if isinstance(payload, dict):
            payload = (payload.get("records") or payload.get("rows")
                       or payload.get("data") or [])
        return verify_sync(root, a.registry, payload, verbose=a.verbose)

    # ---- resolve schema for the remaining ops
    target = a.check or a.repair or a.next_id or a.append or a.upsert
    if target:
        real = resolve_path(target, a.project)
        if real != target:
            if a.check == target: a.check = real
            if a.repair == target: a.repair = real
            if a.next_id == target: a.next_id = real
            if a.append == target: a.append = real
            if a.upsert == target: a.upsert = real
            target = real
        if not os.path.exists(target) and not (a.append or a.upsert):
            print(f"error: {target} not found", file=sys.stderr)
            return 2
        s, root = schema_for_file(target, a.project)
        if not s:
            print(f"error: {os.path.basename(target)} has no schema in "
                  f".sales-system/schemas — is it a registry file?", file=sys.stderr)
            return 2

    if a.next_id:
        header, body = read_table(a.next_id, s)
        used = set()
        if "id" in header:
            i = header.index("id")
            used = {r[i] for r in body if i < len(r) and r[i]}
        w = s.get("id_width", 4)
        print(f"{s.get('id_prefix', 'REC')}-{next_free(used, s.get('id_prefix', 'REC'), w):0{w}d}")
        return 0

    if a.append:
        if not a.json:
            print("error: --append needs --json", file=sys.stderr)
            return 2
        rec = json.loads(a.json)
        if not os.path.exists(a.append):
            write_table(a.append, [c["name"] for c in s["columns"]], [], schema=s)
        header, body = read_table(a.append, s)
        unknown = [k for k in rec if k not in header]
        if unknown:
            print(f"error: unknown field(s) {', '.join(unknown)}. "
                  f"Valid: {', '.join(header)}", file=sys.stderr)
            return 2
        if "id" in header and not rec.get("id"):
            i = header.index("id")
            used = {r[i] for r in body if i < len(r) and r[i]}
            w = s.get("id_width", 4)
            rec["id"] = f"{s.get('id_prefix', 'REC')}-{next_free(used, s.get('id_prefix', 'REC'), w):0{w}d}"
        body.append([rec.get(h, "") for h in header])
        write_table(a.append, header, body, schema=s, backup=True, force=a.force)
        fixes, problems, h2, r2 = process(a.append, s, repair=True)
        print(rec.get("id", "(no id)"))
        for p in problems:
            print(f"  NEEDS YOU  {p}", file=sys.stderr)
        return 1 if problems else 0

    if a.upsert:
        payload = a.json
        if a.json_file:
            with open(a.json_file, encoding="utf-8") as f:
                payload = f.read()
        if not payload:
            print("error: --upsert needs --json or --json-file", file=sys.stderr)
            return 2
        recs = json.loads(payload)
        if isinstance(recs, dict):
            recs = recs.get("records") or recs.get("rows") or recs.get("data") or [recs]
        if os.path.splitext(a.upsert)[1].lower() not in (".csv", ".xlsx"):
            a.upsert += "." + (storage_format(root) if s.get("browsable", True) else "csv")
        owners = [o.strip() for o in a.only_owner.split(",")] if a.only_owner else None
        u, i, sk, changes = upsert(a.upsert, s, recs, key=a.key, root=root,
                                   only_owner=owners, allow_clear=a.allow_clear,
                                   force=a.force)
        print(f"{os.path.basename(a.upsert)}: {i} inserted, {u} updated, "
              f"{len(recs) - i - u - sk} unchanged"
              + (f", {sk} skipped (no {a.key})" if sk else ""))
        for c in changes[:20]:
            print(f"  {c}")
        if len(changes) > 20:
            print(f"  ... and {len(changes) - 20} more rows changed")
        fixes, problems, _, _ = process(a.upsert, s, repair=True)
        for p in problems[:20]:
            print(f"  NEEDS YOU  {p}", file=sys.stderr)
        return 1 if problems else 0

    if a.check or a.repair:
        p = a.check or a.repair
        fixes, problems, _, _ = process(p, s, repair=bool(a.repair))
        return report(p, fixes, problems, quiet_when_clean=False)

    if a.archive:
        root = os.path.abspath(a.archive)
        schemas = load_schemas(root)
        today = date.today()
        arch_dir = os.path.join(root, "99-Archive")
        total = 0
        # Pass 1: registries with their own policy. Pass 2: children that follow a
        # parent (quote lines go wherever their quote went).
        deferred = []
        archived_parent_ids = {}
        for name, s in sorted(schemas.items()):
            pol = s.get("archive")
            if not pol:
                continue
            if pol.get("follow"):
                deferred.append((name, s, pol))
                continue
            p = resolve_path(os.path.join(root, s["path"]), root)
            if not os.path.exists(p):
                continue
            header, rows = read_table(p, s)
            i = {n: k for k, n in enumerate(header)}
            wc, wv = pol.get("when_column"), set(pol.get("when_values", []))
            ac, keep = pol.get("age_column"), int(pol.get("keep_days", 365))
            cutoff = (today - timedelta(days=keep)).isoformat()
            keep_rows, move = [], []
            for r in rows:
                closed = (not wc) or (wc in i and r[i[wc]] in wv)
                aged = ac in i and (r[i[ac]] or "") != "" and r[i[ac]] < cutoff
                (move if (closed and aged) else keep_rows).append(r)
            if not move:
                continue
            total += len(move)
            if "id" in i:
                archived_parent_ids.setdefault(name, set()).update(
                    r[i["id"]] for r in move)
            print(f"  {name}: {len(move)} row(s) -> 99-Archive "
                  f"({len(keep_rows)} stay){' [dry run]' if a.dry_run else ''}")
            if a.dry_run:
                continue
            ext = os.path.splitext(p)[1]
            by_year = {}
            for r in move:
                y = (r[i[ac]] or "")[:4] or "undated"
                by_year.setdefault(y, []).append(r)
            for y, chunk in by_year.items():
                dst = os.path.join(arch_dir, f"{name}-{y}{ext}")
                if os.path.exists(dst):
                    h2, r2 = read_table(dst, s)
                    have = {row[0] for row in r2}
                    r2 += [row for row in chunk if row[0] not in have]
                    write_table(dst, header, r2, schema=s, root=root)
                else:
                    write_table(dst, header, chunk, schema=s, root=root)
            # Removing rows is the whole point here, and they've just been written to
            # 99-Archive, so the guard would only be objecting to a deliberate move.
            write_table(p, header, keep_rows, schema=s, root=root, backup=True, guard=False)
        for name, s, pol in deferred:
            parent = pol["follow"]["registry"]
            key = pol["follow"]["key"]
            gone = archived_parent_ids.get(parent, set())
            if not gone:
                continue
            p = resolve_path(os.path.join(root, s["path"]), root)
            if not os.path.exists(p):
                continue
            header, rows = read_table(p, s)
            i = {n: k for k, n in enumerate(header)}
            keep_rows = [r for r in rows if r[i[key]] not in gone]
            move = [r for r in rows if r[i[key]] in gone]
            if not move:
                continue
            total += len(move)
            print(f"  {name}: {len(move)} row(s) follow archived {parent}"
                  f"{' [dry run]' if a.dry_run else ''}")
            if a.dry_run:
                continue
            ext = os.path.splitext(p)[1]
            dst = os.path.join(arch_dir, f"{name}-{today.year}{ext}")
            if os.path.exists(dst):
                h2, r2 = read_table(dst, s)
                r2 += move
                write_table(dst, header, r2, schema=s, root=root)
            else:
                write_table(dst, header, move, schema=s, root=root)
            # Removing rows is the whole point here, and they've just been written to
            # 99-Archive, so the guard would only be objecting to a deliberate move.
            write_table(p, header, keep_rows, schema=s, root=root, backup=True, guard=False)
        if total == 0:
            print("nothing eligible for archive")
        else:
            print(f"\n{total} row(s) {'would move' if a.dry_run else 'moved'}. "
                  f"Archives keep the same schema and styling — open them like any "
                  f"other registry.")
        return 0

    if a.restyle:
        p = resolve_path(a.restyle, a.project)
        s, root = schema_for_file(p, a.project)
        if not s:
            print(f"error: no schema matches {p}", file=sys.stderr)
            return 2
        if not p.lower().endswith(".xlsx"):
            print(f"{os.path.basename(p)} is a CSV — nothing to style. "
                  f"Use --convert to move it to .xlsx first.")
            return 0
        n = _sheetstyle().restyle(p, s, load_picklist_overrides(root))
        print(f"restyled {os.path.basename(p)} ({n} rows)")
        return 0

    if a.convert:
        src_p = resolve_path(a.convert, a.project)
        s, root = schema_for_file(src_p, a.project)
        if not s:
            print(f"error: no schema matches {src_p}", file=sys.stderr)
            return 2
        if not os.path.exists(src_p):
            print(f"error: {src_p} not found", file=sys.stderr)
            return 2
        to = a.to or ("csv" if src_p.lower().endswith(".xlsx") else "xlsx")
        if to == "xlsx" and not s.get("browsable", True):
            print(f"note: {s['registry']} is machine plumbing — it's append-only and "
                  f"nobody opens it, so CSV is the better format. Converting anyway "
                  f"because you asked.")
        dst = os.path.splitext(src_p)[0] + "." + to
        if os.path.abspath(dst) == os.path.abspath(src_p):
            print(f"{os.path.basename(src_p)} is already .{to}")
            return 0
        fixes, problems, header, rows = process(src_p, s, repair=False)
        write_table(dst, header, rows, schema=s, root=root)
        print(f"{os.path.basename(src_p)} -> {os.path.basename(dst)}  ({len(rows)} rows)")
        for p_ in problems:
            print(f"  NEEDS YOU  {p_}")
        print(f"  original kept at {os.path.basename(src_p)} — delete it once you're happy")
        return 1 if problems else 0

    if a.convert_all:
        root = os.path.abspath(a.convert_all)
        to = a.to or storage_format(root)
        schemas = load_schemas(root)
        moved = 0
        skipped = []
        for name, s in sorted(schemas.items()):
            cur = resolve_path(os.path.join(root, s["path"]), root)
            if not os.path.exists(cur):
                continue
            if to == "xlsx" and not s.get("browsable", True):
                skipped.append(os.path.basename(cur))
                continue
            if cur.lower().endswith("." + to):
                continue
            dst = os.path.splitext(cur)[0] + "." + to
            fixes, problems, header, rows = process(cur, s, repair=False)
            write_table(dst, header, rows, schema=s, root=root)
            print(f"  {os.path.basename(cur)} -> {os.path.basename(dst)} ({len(rows)} rows)")
            moved += 1
        print(f"\nConverted {moved} registries to .{to}. Originals kept — "
              f"delete them once you've checked.")
        if skipped:
            print(f"Left as CSV (machine plumbing, never browsed): {', '.join(skipped)}")
        return 0

    if a.check_all:
        root = os.path.abspath(a.check_all)
        schemas = load_schemas(root)

        # Sync-conflict copies: OneDrive/SharePoint/Drive resolve simultaneous edits by
        # forking the file. Nothing reads the fork, so edits in it are silently lost
        # unless someone notices. Surface them loudly.
        conflict_pat = re.compile(r"(-copy|\s\(\d+\)|conflicted copy|-conflict)",
                                  re.IGNORECASE)
        stems = {os.path.splitext(os.path.basename(s["path"]))[0].lower()
                 for s in schemas.values()}
        found = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                base, ext = os.path.splitext(fn)
                if ext.lower() not in (".csv", ".xlsx"):
                    continue
                if conflict_pat.search(base) and any(
                        base.lower().startswith(st) for st in stems):
                    found.append(os.path.relpath(os.path.join(dirpath, fn), root))
        if found:
            print("SYNC CONFLICT COPIES — a registry was edited in two places and the "
                  "sync layer forked it. These files are read by nothing; any edits in "
                  "them are currently lost:")
            for f in found:
                print(f"  · {f}")
            print("  Merge each into the real registry, then delete the copy.\n")

        # CRM profile staleness: picklists drift as admins change the org, and a stale
        # profile silently rejects real records.
        fp = os.path.join(root, PROFILE_DIR, "field-map.json")
        if os.path.exists(fp):
            try:
                from datetime import date as _d
                gen = json.load(open(fp, encoding="utf-8")).get("generated", "")
                if gen:
                    age = (_d.today() - _d.fromisoformat(gen)).days
                    if age > 90:
                        print(f"note: the CRM profile was generated {age} days ago — "
                              f"picklists may have drifted. Re-run configure-project "
                              f"to refresh it.\n")
            except (ValueError, json.JSONDecodeError, OSError):
                pass
        if not schemas:
            print("No schemas found — has the project been configured?")
            return 1
        worst, checked = 0, 0
        print(f"Checking {len(schemas)} registries under {root}")
        for name, s in sorted(schemas.items()):
            p = resolve_path(os.path.join(root, s["path"]), root)
            if not os.path.exists(p):
                continue
            checked += 1
            fixes, problems, _, _ = process(p, s, repair=True)
            worst = max(worst, report(p, fixes, problems))
        if checked == 0:
            print("  no registry files created yet")
        elif worst == 0:
            print("\nAll registries clean.")
        else:
            print("\nSome rows need a human decision — see NEEDS YOU above.")
        return worst

    ap.print_help()
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DestructiveWrite as e:
        print(f"\n{e}\n", file=sys.stderr)
        sys.exit(1)
