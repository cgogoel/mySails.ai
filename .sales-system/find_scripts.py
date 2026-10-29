#!/usr/bin/env python3
"""
find_scripts.py — tell a skill where the sales-system scripts actually are.

Scripts live in the plugin, not in the project folder. The skills used to reach them by
interpolating `$CLAUDE_PLUGIN_ROOT`, which is fine in Claude Code and **empty in Cowork's
bash sandbox**. An empty variable does not fail loudly: the path collapses to
`/.sales-system/scripts/csvguard.py`, python exits 2, the skill carries on, and the brief
comes out looking entirely normal without ever having run the registry repair or the CRM
drift check it claims to have run. That failure mode went unnoticed for six days in a live
folder. This script exists so it cannot happen again.

The trick is which end you resolve from. A skill never reliably knows the plugin's path —
that is the whole problem — but it always knows the **project folder**, because that is the
folder the user connected and the argument every command already takes. So this file ships
into `<project>/.sales-system/` and resolves outward from a location that is always known.

Usage from a skill, as the first scripted step:

    S=$(python3 "<project>/.sales-system/find_scripts.py") || exit 1
    python3 "$S/csvguard.py" --check-all "<project>"

Exit status is the contract: 0 and one line of path on stdout, or 1 and an explanation on
stderr. Never a silent empty string.

**The device copy.** In a split setup — the skill runs in one environment (a cloud
session, where the plugin is installed) and reaches the folder through a shell on another
machine (the user's computer) — the plugin is not on the machine where the folder is, so
nothing above can find it there. The scripts have to be in the folder. `update-system`
installs them as a *device copy*: `.sales-system/scripts/` plus `DEVICE-COPY.json`, which
records the plugin version and a hash per file. This resolver verifies those hashes and
the folder's template version, and a verified copy is a normal, silent answer — not the
"stale fallback" warning it used to print, which live runs read as a failure for a month
and answered by skipping every scripted step. An unverified copy (no marker, an edited
file, a version behind the folder) still warns, and says exactly which.

Other modes:
    find_scripts.py [project]              resolve, cache, print the scripts dir
    find_scripts.py --plugin-root          print the plugin root instead
    find_scripts.py --explain              show every candidate and why it was taken
    find_scripts.py --no-cache             do not read or write 00-Config/paths.json
"""

import glob
import json
import os
import sys

CACHE_REL = os.path.join("00-Config", "paths.json")

# A directory is the scripts directory if this is in it. csvguard is the one script every
# skill runs, so a candidate without it is useless even if it looks right.
SENTINEL = "csvguard.py"


def _norm(p):
    return os.path.abspath(os.path.expanduser(p))


def _valid(d):
    return bool(d) and os.path.isfile(os.path.join(d, SENTINEL))


def _template_version(scripts_dir):
    """Version of the support layer a candidate belongs to, for ranking. Missing sorts
    lowest, so a plugin copy that carries a VERSION.json always beats one that doesn't."""
    try:
        with open(os.path.join(scripts_dir, os.pardir, "VERSION.json"), encoding="utf-8") as f:
            return json.load(f).get("template_version", "")
    except (OSError, json.JSONDecodeError):
        return ""


DEVICE_MARKER = "DEVICE-COPY.json"
LEGACY_WHY = "in-folder copy"


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_device_copy(scripts_dir):
    """(ok, detail). ok is True only for a device copy whose every recorded file is
    present and unmodified, and whose template version matches the folder's own
    VERSION.json — i.e. the scripts are byte-for-byte the plugin release the folder was
    upgraded to."""
    marker = os.path.join(scripts_dir, DEVICE_MARKER)
    try:
        with open(marker, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False, ("no DEVICE-COPY.json — this is an old or hand-copied set of scripts, "
                       "not one update-system installed")
    bad = []
    for rel, want in (m.get("files") or {}).items():
        p = os.path.join(scripts_dir, os.pardir, rel)
        if not os.path.isfile(p):
            bad.append(f"{rel} missing")
        elif _sha(p) != want:
            bad.append(f"{rel} modified")
    folder_v = _template_version(scripts_dir)
    if m.get("template_version") and folder_v and m["template_version"] != folder_v:
        bad.append(f"copy is template {m['template_version']}, folder is {folder_v}")
    if bad:
        return False, "; ".join(bad[:5]) + (f" (+{len(bad) - 5} more)" if len(bad) > 5 else "")
    return True, (f"device copy of plugin {m.get('plugin_version', '?')}, template "
                  f"{m.get('template_version', '?')}, {len(m.get('files') or {})} files verified")


def _candidates(project):
    """(path, why) in priority order. Nothing is touched on disk here."""
    out = []

    env = os.environ.get("SALES_SYSTEM_SCRIPTS")
    if env:
        out.append((_norm(env), "SALES_SYSTEM_SCRIPTS"))

    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if root:
        out.append((_norm(os.path.join(root, ".sales-system", "scripts")),
                    "CLAUDE_PLUGIN_ROOT"))

    # Cowork mounts installed plugins as a sibling of the connected folder. Walk up a few
    # levels: which level depends on how the user connected the folder, and guessing one
    # is how this breaks again on the next layout change.
    d = project
    for _ in range(4):
        for c in sorted(glob.glob(os.path.join(d, ".remote-plugins", "*", ".sales-system", "scripts"))):
            out.append((_norm(c), "Cowork .remote-plugins"))
        d = os.path.dirname(d)
        if d in ("/", ""):
            break

    home = os.path.expanduser("~")
    for pat in (
        os.path.join(home, ".remote-plugins", "*", ".sales-system", "scripts"),
        os.path.join(home, ".claude", "plugins", "*", ".sales-system", "scripts"),
        os.path.join(home, ".claude", "plugins", "*", "*", ".sales-system", "scripts"),
        os.path.join(home, ".claude", "plugins", "repos", "*", "*", ".sales-system", "scripts"),
        os.path.join(home, ".claude", "plugins", "marketplaces", "*", "*", ".sales-system", "scripts"),
    ):
        for c in sorted(glob.glob(pat)):
            out.append((_norm(c), "plugin cache"))

    # Last. Either a verified device copy (see the module docstring — the normal answer in
    # a split setup) or an old in-folder copy from before scripts moved into the plugin,
    # which is last month's guard and announces itself as such.
    out.append((_norm(os.path.join(project, ".sales-system", "scripts")), LEGACY_WHY))

    seen, uniq = set(), []
    for p, why in out:
        if p not in seen:
            seen.add(p)
            uniq.append((p, why))
    return uniq


def _cached(project):
    p = os.path.join(project, CACHE_REL)
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f).get("scripts_dir")
    except (OSError, json.JSONDecodeError):
        return None
    return d if _valid(d) else None


def _write_cache(project, scripts_dir, source):
    """Record where it was found, so the next run is a read rather than a filesystem sweep
    and so a human can see what the skills are actually executing."""
    p = os.path.join(project, CACHE_REL)
    if not os.path.isdir(os.path.dirname(p)):
        return
    payload = {
        "scripts_dir": scripts_dir,
        "plugin_root": os.path.abspath(os.path.join(scripts_dir, os.pardir, os.pardir)),
        "template_version": _template_version(scripts_dir),
        "resolved_from": source,
        "note": "Written by .sales-system/find_scripts.py. Safe to delete — it is a cache, "
                "and it is re-resolved whenever the recorded path stops working. Set "
                "SALES_SYSTEM_SCRIPTS to override.",
    }
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp, p)
    except OSError:
        pass  # A read-only folder is not a reason to fail the resolve.


def find_scripts(project, use_cache=True, explain=False):
    """Return (scripts_dir, source) or (None, None). Importable, so the scripts can locate
    each other the same way the skills do."""
    project = _norm(project)

    if use_cache:
        hit = _cached(project)
        if hit and _norm(hit) == _norm(os.path.join(project, ".sales-system", "scripts")) \
                and not verify_device_copy(hit)[0]:
            hit = None   # re-resolve so the warning is printed, never cached silence
        if hit:
            if explain:
                print(f"  cache      {hit}  TAKEN", file=sys.stderr)
            return hit, "cache"

    best = None
    for path, why in _candidates(project):
        ok = _valid(path)
        if explain:
            print(f"  {'ok  ' if ok else 'miss'}  {why:28} {path}", file=sys.stderr)
        if not ok:
            continue
        if why == LEGACY_WHY:
            if best is None:
                best = (path, why)   # keep it, but only if nothing else answered
            continue
        # Among real plugin copies, the newest support layer wins. Two installed versions
        # of the plugin is a normal state during an upgrade and picking the older one
        # silently is the same class of bug as this file exists to prevent.
        if best is None or best[1] == LEGACY_WHY or \
                _template_version(path) > _template_version(best[0]):
            best = (path, why)
        if why in ("SALES_SYSTEM_SCRIPTS", "CLAUDE_PLUGIN_ROOT"):
            break   # an explicit answer is not a candidate to be ranked

    if not best:
        return None, None
    if best[1] == LEGACY_WHY:
        ok, detail = verify_device_copy(best[0])
        if ok:
            if explain:
                print(f"  device copy verified: {detail}", file=sys.stderr)
            return best[0], "device copy (verified)"
        print("warning: using the in-folder scripts at "
              f"{best[0]}, which could NOT be verified against a plugin release: {detail}. "
              "Run update-system (in a split setup: with --device-copy) to install a "
              "verified copy.", file=sys.stderr)
        return best[0], "in-folder copy (unverified)"
    return best


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}

    if args:
        project = args[0]
    else:
        # Default: this file sits at <project>/.sales-system/find_scripts.py, so the
        # project is two levels up. That is what makes the skill invocation a one-liner.
        project = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)

    explain = "--explain" in flags
    if explain:
        print(f"project: {_norm(project)}", file=sys.stderr)
        print(f"CLAUDE_PLUGIN_ROOT={os.environ.get('CLAUDE_PLUGIN_ROOT', '') or '(empty)'}",
              file=sys.stderr)

    scripts, source = find_scripts(project, use_cache="--no-cache" not in flags,
                                   explain=explain)
    if not scripts:
        print(
            "STOP: the sales-system scripts could not be found, so nothing that follows "
            "would actually run.\n"
            f"  project        {_norm(project)}\n"
            f"  CLAUDE_PLUGIN_ROOT  {os.environ.get('CLAUDE_PLUGIN_ROOT', '') or '(empty — normal in Cowork)'}\n"
            "  Fix: set SALES_SYSTEM_SCRIPTS to the directory containing csvguard.py, or "
            "reinstall the plugin, then retry.\n"
            "  Do not continue — a brief built without registry repair and drift "
            "verification is not the same artifact.",
            file=sys.stderr)
        return 1

    if source != "cache" and "--no-cache" not in flags:
        _write_cache(_norm(project), scripts, source)

    if "--plugin-root" in flags:
        print(os.path.abspath(os.path.join(scripts, os.pardir, os.pardir)))
    else:
        print(scripts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
