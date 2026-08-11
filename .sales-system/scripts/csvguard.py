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
  csvguard.py --init <path> --schema <schema_name> --project <root>
  csvguard.py --convert <path> [--to xlsx|csv]
  csvguard.py --convert-all <project_root> --to xlsx
  csvguard.py --restyle <path.xlsx>       # reapply the Excel styling contract

Paths are format-agnostic: pass leads.csv and it will find leads.xlsx if that's what
exists.

Exit codes: 0 clean/repaired, 1 problems needing a human, 2 usage error.
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


def write_table(path, header, rows, schema=None, root=None, backup=False):
    if path.lower().endswith(".xlsx") and excel_has_open(path):
        raise RuntimeError(
            f"{os.path.basename(path)} appears to be open in Excel (a ~$ lock file is "
            f"present). Close it there first — writing underneath a live Excel session "
            f"means one side's changes get lost.")
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
        write_table(path, new_header, rebuilt, schema=schema, backup=True)

    return fixes, problems, new_header, rebuilt


def next_free(used, prefix, width):
    n = 0
    for u in used:
        m = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", u)
        if m:
            n = max(n, int(m.group(1)))
    return n + 1


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
    ap.add_argument("--json")
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

    # ---- resolve schema for the remaining ops
    target = a.check or a.repair or a.next_id or a.append
    if target:
        real = resolve_path(target, a.project)
        if real != target:
            if a.check == target: a.check = real
            if a.repair == target: a.repair = real
            if a.next_id == target: a.next_id = real
            if a.append == target: a.append = real
            target = real
        if not os.path.exists(target) and not a.append:
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
        write_table(a.append, header, body, schema=s, backup=True)
        fixes, problems, h2, r2 = process(a.append, s, repair=True)
        print(rec.get("id", "(no id)"))
        for p in problems:
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
            write_table(p, header, keep_rows, schema=s, root=root, backup=True)
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
            write_table(p, header, keep_rows, schema=s, root=root, backup=True)
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
    sys.exit(main())
