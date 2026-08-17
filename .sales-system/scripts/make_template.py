#!/usr/bin/env python3
"""Package the canonical .sales-system into a portable template zip.

The skills reference scripts and schemas that live in this folder; a colleague
installing the skills at another company has none of them, and regenerating ~2,500
lines from memory produces something different every time. This zip is the single
source: on a fresh install, configure-project unpacks it instead of improvising.

Excluded on purpose: crm-profile (per-org), brand.json (per-org), backups, locks,
cache. What ships is exactly the generic layer.

Also writes MANIFEST.json — a hash per shipped file. That's what lets upgrade.py
later tell "the user edited this" from "this hasn't been touched since install",
which is the difference between a safe upgrade and one that quietly discards
someone's work.

Usage: make_template.py <project_root> [--out sales-system-template.zip] [--version YYYY-MM-DD]

Version defaults to today. Two releases on one day collide — the second would rewrite the
first's entry in manifests/, and upgrade.py uses those entries as the baseline that tells an
edited file from an untouched one, so folders already installed from the first release would
lose the ability to detect their own edits. Rather than corrupt that quietly, packaging refuses
when an existing release manifest would change, and asks for an explicit --version. Pass
--force to overwrite anyway, which is right for a version you have built but not yet shipped
and wrong for one anybody has installed.
"""
import hashlib
import json
import os
import sys
import zipfile
from datetime import date

MANIFEST = "MANIFEST.json"


def shipped_files(ss):
    """Everything the template owns, as paths relative to .sales-system/."""
    out = []
    for sub in ("scripts", "schemas"):
        d = os.path.join(ss, sub)
        for fn in sorted(os.listdir(d)):
            if fn.endswith((".py", ".json")) and not fn.startswith("patch_"):
                out.append(f"{sub}/{fn}")
    out += ["CONVENTIONS.md", "VERSION.json"]
    # The one executable that ships INTO the folder rather than running from the plugin.
    # It has to: it is what tells a skill where the plugin's scripts are, and the only path
    # a skill reliably knows is the project folder it was handed. Leaving it out of the
    # manifest is how the last round of scripts became undetectable to upgrade.py.
    if os.path.exists(os.path.join(ss, "find_scripts.py")):
        out.append("find_scripts.py")
    # Shipped so upgrade.py can tell someone what a version actually changed. A number
    # that quietly starts meaning something else between releases is how people stop
    # trusting a tool, and the only defence is saying so at the moment they upgrade.
    if os.path.exists(os.path.join(ss, "CHANGELOG.md")):
        out.append("CHANGELOG.md")
    return out


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    root = os.path.abspath(sys.argv[1])
    out = (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
           else os.path.join(root, "sales-system-template.zip"))
    ss = os.path.join(root, ".sales-system")
    version = (sys.argv[sys.argv.index("--version") + 1] if "--version" in sys.argv
               else date.today().isoformat())
    with open(os.path.join(ss, "VERSION.json"), "w", encoding="utf-8") as f:
        json.dump({"template_version": version,
                   "note": "unpack into <project>/.sales-system/, then run configure-project"},
                  f, indent=2)

    files = shipped_files(ss)
    prior = os.path.join(ss, "manifests", f"{version}.json")
    prior_hashes = None
    if os.path.exists(prior):
        try:
            with open(prior, encoding="utf-8") as f:
                prior_hashes = json.load(f).get("files", {})
        except (OSError, json.JSONDecodeError):
            prior_hashes = None

    manifest = {"template_version": version,
                "note": "sha256 per shipped file, written at package time. upgrade.py "
                        "compares against it to tell an edited file from an untouched "
                        "one. Not a security control — just provenance.",
                "files": {rel: sha(os.path.join(ss, rel)) for rel in files}}
    if (prior_hashes is not None and prior_hashes != manifest["files"]
            and "--force" not in sys.argv):
        changed = sorted(set(prior_hashes) ^ set(manifest["files"])) or sorted(
            k for k in manifest["files"]
            if prior_hashes.get(k) != manifest["files"][k])
        sys.exit(
            f"refusing to repackage {version}: a release manifest for that version already "
            f"exists and {len(changed)} file(s) differ from it "
            f"({', '.join(changed[:5])}{' ...' if len(changed) > 5 else ''}).\n"
            f"Rewriting it would leave folders installed from the first {version} unable to "
            f"tell their own edits from shipped files. Pass --version with a new date, or "
            f"--force if this version has been built but never shipped.")

    with open(os.path.join(ss, MANIFEST), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    # Keep every released version's hashes, and ship them. A folder installed from an
    # older release has no manifest of its own, but it does know which version it is —
    # so upgrade.py can look the baseline up here and still tell an edited file from an
    # untouched one. Without this, every upgrade from before manifests existed has to
    # assume the worst about every file and ends up delivering nothing.
    hist = os.path.join(ss, "manifests")
    os.makedirs(hist, exist_ok=True)
    with open(os.path.join(hist, f"{version}.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    past = sorted(f for f in os.listdir(hist) if f.endswith(".json"))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files + [MANIFEST] + [f"manifests/{p}" for p in past]:
            z.write(os.path.join(ss, rel), f".sales-system/{rel}")
    print(f"{out}: {len(files) + 1} files + {len(past)} release manifest(s), "
          f"template_version {version}. No org data — safe to share.")


if __name__ == "__main__":
    main()
