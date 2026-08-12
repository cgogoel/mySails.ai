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

**Keeping the folder honest.** A registry that validates clean can still be wrong, and
that's the failure mode that costs real money — a rebuild from a stale snapshot reverting
a day's decisions, or someone changing the CRM out of band. So:

- **Drift detection.** `csvguard.py --verify-sync` compares each synced registry against
  the CRM and reports which side moved: DRIFT (they changed it), AHEAD (you did and never
  pushed), CONFLICT (both). Briefs and forecasts open with it.
- **A destructive-write guard.** Every full-file write is diffed against what it replaces
  and refused — with the diff — if rows would vanish, cells would be blanked, or a closed
  deal would reopen.
- **Seed and refresh are different verbs.** `crm_sync.py --seed` refuses to run against a
  registry that already has rows; `--refresh` merges only CRM-owned columns, so notes,
  risk flags and everything derived survive it, and IDs are never renumbered.
- **Bulk import that knows what CRM exports get wrong** — cp1252, US-locale dates, mixed
  booleans, field labels vs API names, totals footers.

CRM-specific quirks are declared per CRM rather than assumed — the record identifier and
timestamp fields, the query language, custom-field suffixes, and whether record IDs have
more than one form (Salesforce's 15- vs 18-character IDs are currently the only case).
An unrecognised CRM, or none, gets generic behaviour, and any org can override the lot
from its own `field-map.json`.

**Setup is resumable.** It's a checklist at `00-Config/setup-checklist.csv` with an HTML
progress dashboard, walked module by module, with each field mapping confirmed against
real records before anything depends on it. Pause whenever; completion is derived from
evidence in the folder rather than from memory of having done it.

## Install

Plugins require a paid Claude plan (Pro, Max, Team, or Enterprise).

### Cowork / Claude desktop app

Cowork has no `/plugin` command, and dragging a file into the chat will not install
anything — it just attaches the file. Add this repo as a marketplace instead:

1. Open the **Cowork** tab, then click **Customize** in the left sidebar.
2. Go to the **Plugins** tab.
3. Under **Personal plugins**, click **+** → **Add marketplace** → **Add from a
   repository**, and enter `cgogoel/mySails.ai`.
4. Install **folder-sales-os** from the marketplace that appears.

Alternatively, download the packaged plugin and upload it from that same **Plugins**
tab — not by dragging it into a conversation:

**[⬇ folder-sales-os.plugin](https://github.com/cgogoel/mySails.ai/releases/latest/download/folder-sales-os.plugin)**

### Claude Code (CLI)

```
/plugin marketplace add cgogoel/mySails.ai
/plugin install folder-sales-os
```

The `owner/repo` shorthand clones over SSH by default. If you don't have SSH keys set
up for GitHub, set `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1` first.

### Then

Connect a folder and say **"set up my sales project"**. Setup installs the support
layer into that folder on first run, so an empty folder is fine.

## Layout

- `skills/` — the thirteen skills
- `.sales-system/` — the generic support layer: schemas, scripts, conventions.
  Contains no org data. `configure-project` copies this into each new project folder
  on first run and never overwrites an existing copy.
- `.claude-plugin/` — plugin and marketplace manifests

`.sales-system/scripts/make_template.py` packages `.sales-system/` into
`sales-system-template.zip` on demand. That zip is a build artifact and is not
committed.

## Cutting a release

Bump `version` in `.claude-plugin/plugin.json`, then:

```
git tag v0.1.0 && git push origin v0.1.0
```

`.github/workflows/release.yml` checks the tag against the manifest version,
validates the plugin structure, builds the `.plugin` from git-tracked files only,
and publishes it as a release asset. The download link above always points at the
newest release, so it never needs updating.

## What is not in this repo

Working data — lead and opportunity registries, quotes, briefs, the CRM profile,
company config — lives in numbered folders (`00-Config/` … `99-Archive/`) alongside
this repo and is excluded by `.gitignore`. It never belongs in version control.

Status: pre-release. Built with Claude Cowork.

## License

MIT — see [LICENSE](LICENSE).
