#!/usr/bin/env python3
"""
upgrade.py — bring a project folder's support layer up to the version the plugin ships.

Two things carry a version and they update by different means. The **plugin** — the
skills — is the plugin manager's job. The **support layer** inside each project folder
is not: `configure-project` copies it in once at setup and then deliberately never
overwrites it, because a user may have edited a schema and clobbering that silently
loses their work. Which is correct, and left no way to move a live folder forward.

This is that way. It is careful about exactly one thing: telling a file the user changed
from a file that has not been touched since it was installed.

  --check   say what would change, touch nothing
  --apply   do it, after backing the whole layer up

How a file is classified:

  ADD      the folder doesn't have it yet
  SAME     already identical to the shipped copy
  UPDATE   unchanged since install, so replacing it loses nothing
  MERGE    an edited schema — new columns come in, your edits and columns stay
  KEEP     an edited script or document — left alone, new copy written alongside as
           <name>.new for you to diff

Provenance comes from MANIFEST.json, a hash per shipped file written at package time.
Folders installed before manifests existed have no baseline, so nothing can be proven
untouched; those are handled conservatively and the report says so plainly.

Never touched, whatever happens: crm-profile/, brand.json, backups/, cache/, locks/, and
anything else the template doesn't own. Your data lives outside this folder entirely.

Usage:
  upgrade.py --check <project> [--from <plugin>/.sales-system]
  upgrade.py --apply <project> [--from ...] [--no-migrate]

Run the **plugin's** copy of this script, not the project's — the project's copy is the
old version, and the source defaults to whichever .sales-system the running script sits in:

  python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/upgrade.py" --check <project>

Exit codes: 0 nothing to do / applied cleanly, 1 changes pending or needing a human,
2 usage error.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MANIFEST = "MANIFEST.json"
# Directories and files the template owns. Everything else in .sales-system/ belongs to
# the org and is never considered.
OWNED_DIRS = ("scripts", "schemas")
OWNED_FILES = ("CONVENTIONS.md", "VERSION.json")
PRESERVE = ("crm-profile", "brand.json", "backups", "cache", "locks")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def owned(ss):
    out = []
    for sub in OWNED_DIRS:
        d = os.path.join(ss, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith((".py", ".json")) and not fn.startswith("patch_"):
                out.append(f"{sub}/{fn}")
    for fn in OWNED_FILES:
        if os.path.exists(os.path.join(ss, fn)):
            out.append(fn)
    return out


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def version_of(ss):
    return (read_json(os.path.join(ss, "VERSION.json"), {}) or {}).get(
        "template_version", "unknown")


# ------------------------------------------------------------------- schema merging
# A schema the user has edited still has to gain whatever the new version added, or the
# upgrade achieves nothing for exactly the person who engaged with the system most.


def merge_schema(local, new):
    """New definition wins on structure; the user's additions survive. Returns
    (merged, notes)."""
    notes = []
    merged = json.loads(json.dumps(new))

    lcols = {c["name"]: c for c in local.get("columns", [])}
    ncols = {c["name"]: c for c in new.get("columns", [])}

    for name, col in merged_columns(merged):
        lc = lcols.get(name)
        if not lc:
            continue
        # Enum values the user added — often their CRM's real picklist typed straight
        # into the schema rather than into crm-profile/picklists.json.
        if col.get("type") == "enum" and lc.get("type") == "enum":
            extra = [v for v in lc.get("values", []) if v not in col.get("values", [])]
            if extra:
                col["values"] = list(col.get("values", [])) + extra
                notes.append(f"kept your extra {name} values: {', '.join(extra)}")
        # An explicit ownership or verify choice the user made is a decision, not noise.
        for key in ("owner", "verify"):
            if key in lc and lc[key] != col.get(key) and key in col:
                col[key] = lc[key]
                notes.append(f"kept your {name}.{key} = {lc[key]!r}")

    added = [n for n in ncols if n not in lcols]
    if added:
        notes.append(f"added new column(s): {', '.join(added)}")

    # Columns the user added themselves go at the end, same rule the guard uses for
    # user-added columns in a registry.
    extra_cols = [c for c in local.get("columns", []) if c["name"] not in ncols]
    if extra_cols:
        merged["columns"] = merged["columns"] + extra_cols
        notes.append(f"kept your column(s): {', '.join(c['name'] for c in extra_cols)}")

    # Top-level keys the user added (a custom archive policy, an extra note).
    for k, v in local.items():
        if k == "columns":
            continue
        if k not in new:
            merged[k] = v
            notes.append(f"kept your {k!r} setting")
        elif new[k] != v and k in ("archive", "path", "id_prefix", "id_width"):
            merged[k] = v
            notes.append(f"kept your {k!r} = {json.dumps(v)[:60]}")

    return merged, notes


def merged_columns(schema):
    for c in schema.get("columns", []):
        yield c["name"], c


# ------------------------------------------------------------------------ planning


def baseline_for(src, dst):
    """The hashes this folder had when it was installed.

    Its own MANIFEST.json if it has one. Otherwise the released manifest for whatever
    version VERSION.json says it is — the plugin ships every past release's hashes for
    exactly this reason. Only when neither exists is provenance genuinely unknown.

    Returns (shipped, on_disk, where): `shipped` is what the template published, and
    `on_disk` is what this folder actually had after the last upgrade, which differs for
    a merged schema or a file we left alone."""
    own = read_json(os.path.join(dst, MANIFEST), {}) or {}
    if own.get("files"):
        return own["files"], own.get("local") or {}, "this folder's own manifest"
    v = version_of(dst)
    past = read_json(os.path.join(src, "manifests", f"{v}.json"), {}) or {}
    if past.get("files"):
        return past["files"], {}, f"the published manifest for {v}"
    return None, {}, None


def plan(src, dst):
    """Classify every file the template owns."""
    baseline, on_disk, _source = baseline_for(src, dst)
    actions = []
    for rel in owned(src):
        s = os.path.join(src, rel)
        d = os.path.join(dst, rel)
        new_hash = sha(s)
        if not os.path.exists(d):
            actions.append((rel, "ADD", "not installed yet", None))
            continue
        cur = sha(d)
        if cur == new_hash:
            actions.append((rel, "SAME", "already current", None))
            continue
        # A merged schema, or a file deliberately left alone, will never match the
        # shipped copy again — that's the point of it. It's still settled as long as
        # neither side has moved since the last upgrade reconciled them.
        if cur == on_disk.get(rel) and (baseline or {}).get(rel) == new_hash:
            actions.append((rel, "SAME", "reconciled already, neither side has moved",
                            None))
            continue
        # Pure metadata about the layer itself. Nobody edits these, and keeping a stale
        # one would leave the folder lying about its own version.
        if rel in ("VERSION.json", MANIFEST):
            actions.append((rel, "UPDATE", "version metadata", None))
            continue
        base = (baseline or {}).get(rel)
        if base and cur == base:
            actions.append((rel, "UPDATE", "unchanged since install", None))
        elif base:
            actions.append((rel, *_edited(rel, "you edited this")))
        else:
            # Provenance genuinely unknown: no manifest, and no published one for this
            # version either. Assume the file was edited — the cautious reading.
            actions.append((rel, *_edited(rel, "no baseline to compare against")))
    # Files the folder has that the new version dropped.
    for rel in owned(dst):
        if not os.path.exists(os.path.join(src, rel)):
            actions.append((rel, "GONE", "no longer part of the template", None))
    return actions, baseline is not None


def _edited(rel, why):
    if rel.startswith("schemas/"):
        return "MERGE", why, None
    return "KEEP", why, f"{rel}.new"


# ------------------------------------------------------------------------- applying


def backup(dst, old_v, new_v):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(dst, "backups", f"upgrade-{old_v}-to-{new_v}-{stamp}")
    os.makedirs(bdir, exist_ok=True)
    for rel in owned(dst) + [MANIFEST]:
        s = os.path.join(dst, rel)
        if not os.path.exists(s):
            continue
        t = os.path.join(bdir, rel)
        os.makedirs(os.path.dirname(t), exist_ok=True)
        shutil.copy2(s, t)
    return bdir


def apply(src, dst, actions, migrate=True, project=None):
    old_v, new_v = version_of(dst), version_of(src)
    bdir = backup(dst, old_v, new_v)
    print(f"backed up the current layer to "
          f"{os.path.relpath(bdir, project or dst)}\n")

    merged_notes = []
    for rel, action, why, alt in actions:
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if action in ("SAME", "GONE"):
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        if action in ("ADD", "UPDATE"):
            shutil.copy2(s, d)
        elif action == "MERGE":
            local, new = read_json(d), read_json(s)
            if local is None or new is None:
                shutil.copy2(s, d)
                merged_notes.append((rel, ["unreadable as JSON — replaced; "
                                           "your copy is in the backup"]))
                continue
            merged, notes = merge_schema(local, new)
            with open(d, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
                f.write("\n")
            merged_notes.append((rel, notes))
        elif action == "KEEP":
            shutil.copy2(s, os.path.join(dst, alt))

    # Record both sides: what the template shipped, and what this folder actually ended
    # up with. They differ wherever a schema was merged or a file was left alone, and
    # keeping both is what lets the next run tell "already reconciled" from "changed
    # again since".
    with open(os.path.join(dst, MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"template_version": new_v,
                   "upgraded_from": old_v,
                   "upgraded_at": datetime.now().isoformat(timespec="seconds"),
                   "note": "`files` is what the template published; `local` is what this "
                           "folder holds. Where they differ, the difference is yours and "
                           "upgrade.py will preserve it.",
                   "files": {rel: sha(os.path.join(src, rel)) for rel in owned(src)},
                   "local": {rel: sha(os.path.join(dst, rel)) for rel in owned(src)
                             if os.path.exists(os.path.join(dst, rel))}},
                  f, indent=2)
        f.write("\n")

    for rel, notes in merged_notes:
        print(f"merged {rel}")
        for n in notes:
            print(f"    {n}")
    if merged_notes:
        print()

    kept = [(rel, alt) for rel, a, _w, alt in actions if a == "KEEP"]
    if kept:
        print("Left alone because you'd changed them — the new version is alongside:")
        for rel, alt in kept:
            print(f"    {rel}   ->  {os.path.basename(alt)}")
        print("  Diff each and merge what you want. Until you do, this folder is "
              "running your version of that file.")
        print()

    if migrate and project:
        print("migrating the registries (new columns get added in place)...")
        guard = os.path.join(dst, "scripts", "csvguard.py")
        r = subprocess.run([sys.executable, guard, "--check-all", project],
                           capture_output=True, text=True)
        out = (r.stdout or "").strip()
        print("\n".join("  " + ln for ln in out.splitlines()[-25:]) or "  (nothing to do)")
        if r.returncode == 1:
            print("\n  Some rows need a human decision — see NEEDS YOU above. That's the "
                  "guard asking, not the upgrade failing.")
    return 0


# --------------------------------------------------------------------------- report


def report(src, dst, actions, has_baseline, project):
    old_v, new_v = version_of(dst), version_of(src)
    by = {}
    for rel, action, why, alt in actions:
        by.setdefault(action, []).append((rel, why))

    print(f"\nSupport layer in {os.path.basename(os.path.abspath(project))}: "
          f"{old_v}  ->  {new_v}")
    if old_v == new_v and not any(a in by for a in ("ADD", "UPDATE", "MERGE", "KEEP")):
        print("Already current — nothing to do.\n")
        return 0

    order = [("ADD", "new, will be installed"),
             ("UPDATE", "unchanged since install, safe to replace"),
             ("MERGE", "you edited these schemas — new columns in, your edits kept"),
             ("KEEP", "you edited these — left alone, new copy written alongside"),
             ("GONE", "no longer part of the template — left in place"),
             ("SAME", "already current")]
    for action, label in order:
        items = by.get(action, [])
        if not items:
            continue
        if action == "SAME":
            print(f"\n  {len(items)} file(s) already current")
            continue
        print(f"\n  {action}  — {label}")
        for rel, why in items[:25]:
            print(f"      {rel}")
        if len(items) > 25:
            print(f"      ... and {len(items) - 25} more")

    if not has_baseline:
        print("\n  This folder was installed before file hashes were recorded, so "
              "nothing here\n  can be proven untouched. Schemas are merged rather than "
              "replaced, and every\n  current file is copied to backups/ first. After "
              "this upgrade a baseline exists\n  and the next one will be exact.")

    print(f"\n  Never touched: {', '.join(PRESERVE)} — and your registries, notes and "
          f"briefs\n  live outside this folder entirely.")
    print(f"\n  To apply:  python3 {os.path.abspath(__file__)} --apply {project}\n")
    return 1


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--check")
    ap.add_argument("--apply")
    ap.add_argument("--from", dest="src",
                    help="The .sales-system to upgrade from. Defaults to the one this "
                         "script lives in.")
    ap.add_argument("--no-migrate", action="store_true",
                    help="Skip the registry migration afterwards")
    a = ap.parse_args()

    project = os.path.abspath(a.check or a.apply or "")
    if not project:
        ap.print_help()
        return 2
    dst = os.path.join(project, ".sales-system")
    if not os.path.isdir(dst):
        print(f"error: {project} has no .sales-system — it's not set up yet. Run "
              f"configure-project instead.", file=sys.stderr)
        return 2

    src = os.path.abspath(a.src) if a.src else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    if os.path.abspath(src) == os.path.abspath(dst):
        print("error: the source and the target are the same folder.\n"
              "  Run the plugin's copy of this script, not the project's — the "
              "project's is the old\n  version. Try:\n"
              '    python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/upgrade.py" '
              f"--check {project}", file=sys.stderr)
        return 2
    if not os.path.exists(os.path.join(src, "CONVENTIONS.md")):
        print(f"error: {src} doesn't look like a .sales-system", file=sys.stderr)
        return 2

    actions, has_baseline = plan(src, dst)
    if a.check:
        return report(src, dst, actions, has_baseline, project)

    report(src, dst, actions, has_baseline, project)
    return apply(src, dst, actions, migrate=not a.no_migrate, project=project)


if __name__ == "__main__":
    sys.exit(main())
