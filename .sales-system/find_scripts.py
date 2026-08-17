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

    # Last, and deliberately last. Folders set up before the scripts moved into the plugin
    # still have a copy here. It is last month's guard, and running an old guard against
    # current data is precisely the accident the guard exists to prevent — so it is a
    # fallback of last resort and it announces itself.
    out.append((_norm(os.path.join(project, ".sales-system", "scripts")),
                "in-folder legacy copy (stale)"))

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
        if why == "in-folder legacy copy (stale)":
            if best is None:
                best = (path, why)   # keep it, but only if nothing else answered
            continue
        # Among real plugin copies, the newest support layer wins. Two installed versions
        # of the plugin is a normal state during an upgrade and picking the older one
        # silently is the same class of bug as this file exists to prevent.
        if best is None or best[1] == "in-folder legacy copy (stale)" or \
                _template_version(path) > _template_version(best[0]):
            best = (path, why)
        if why in ("SALES_SYSTEM_SCRIPTS", "CLAUDE_PLUGIN_ROOT"):
            break   # an explicit answer is not a candidate to be ranked

    if not best:
        return None, None
    if best[1] == "in-folder legacy copy (stale)":
        print("warning: falling back to the in-folder copy of the scripts at "
              f"{best[0]}. These are not updated with the plugin and may be months behind. "
              "Run update-system, or set SALES_SYSTEM_SCRIPTS.", file=sys.stderr)
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
