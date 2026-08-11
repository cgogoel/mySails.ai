# Folder Sales OS

A complete sales management system that runs on files you can open. Registries are
CSV or styled Excel workbooks (dropdowns from your CRM's real picklists, risk
colouring, frozen headers); narrative lives in Markdown; thirteen skills do the work.

**Modules:** project setup with CRM introspection · leads · opportunities · renewals ·
channel partners (two-tier, deal-reg conflict checking) · competitors (battlecards from
your real win/loss record) · market signals · demand gen + thought leadership · content
tailoring · quote generation (price-list guard rails) · daily brief · weekly brief ·
forecast dashboards (engagement-ranked, goals-framed).

**Design principles:** the folder is the database; CRM pulls are automatic but pushes
always require confirmation; contactability and sequence gates protect customer
relationships; numbers from small samples are refused rather than reported.

## Install

**Claude Code (CLI):**

```
/plugin marketplace add cgogoel/mySails.ai
/plugin install folder-sales-os
```

**Cowork (desktop app):** Cowork has no `/plugin` command — it installs from a
`.plugin` file. Clone this repo and package it:

```
git clone https://github.com/cgogoel/mySails.ai.git
cd mySails.ai && zip -r /tmp/folder-sales-os.plugin . -x "*.git*" "*.DS_Store"
```

Then open the `.plugin` file in a Cowork chat and press Install on the card.

Either way, connect a folder and say **"set up my sales project"**. Setup installs the
support layer into that folder on first run, so an empty folder is fine.

## Layout

- `skills/` — the thirteen skills
- `.sales-system/` — the generic support layer: schemas, scripts, conventions.
  Contains no org data. `configure-project` copies this into each new project folder
  on first run and never overwrites an existing copy.
- `.claude-plugin/` — plugin and marketplace manifests

`.sales-system/scripts/make_template.py` packages `.sales-system/` into
`sales-system-template.zip` on demand. That zip is a build artifact and is not
committed.

## What is not in this repo

Working data — lead and opportunity registries, quotes, briefs, the CRM profile,
company config — lives in numbered folders (`00-Config/` … `99-Archive/`) alongside
this repo and is excluded by `.gitignore`. It never belongs in version control.

Status: pre-release. Built with Claude Cowork.

## License

MIT — see [LICENSE](LICENSE).
