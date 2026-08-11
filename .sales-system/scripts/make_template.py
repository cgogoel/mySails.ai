#!/usr/bin/env python3
"""Package the canonical .sales-system into a portable template zip.

The skills reference scripts and schemas that live in this folder; a colleague
installing the skills at another company has none of them, and regenerating ~2,500
lines from memory produces something different every time. This zip is the single
source: on a fresh install, configure-project unpacks it instead of improvising.

Excluded on purpose: crm-profile (per-org), brand.json (per-org), backups, locks,
cache. What ships is exactly the generic layer.

Usage: make_template.py <project_root> [--out sales-system-template.zip]
"""
import json
import os
import sys
import zipfile
from datetime import date


def main():
    root = os.path.abspath(sys.argv[1])
    out = (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv
           else os.path.join(root, "sales-system-template.zip"))
    ss = os.path.join(root, ".sales-system")
    with open(os.path.join(ss, "VERSION.json"), "w", encoding="utf-8") as f:
        json.dump({"template_version": date.today().isoformat(),
                   "note": "unpack into <project>/.sales-system/, then run configure-project"},
                  f, indent=2)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ("scripts", "schemas"):
            d = os.path.join(ss, sub)
            for fn in sorted(os.listdir(d)):
                if fn.endswith((".py", ".json")) and not fn.startswith("patch_"):
                    z.write(os.path.join(d, fn), f".sales-system/{sub}/{fn}")
                    n += 1
        for fn in ("CONVENTIONS.md", "VERSION.json"):
            z.write(os.path.join(ss, fn), f".sales-system/{fn}")
            n += 1
    print(f"{out}: {n} files. No org data — safe to share.")


if __name__ == "__main__":
    main()
