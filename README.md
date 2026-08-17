# Filesystem-Based Sales OS

A complete sales management system that runs on files you can open. Registries are
styled Excel workbooks or CSV for ease of browsing/editing. Sync with your CRM or run 
without a CRM. Designed for use on a local file-system folder but there is experimental
support for running in a shared drive for multiple users collaborating on a single folder.

**Modules:** project setup with optional CRM sync · leads · opportunities · renewals ·
channel partners (two-tier, deal-reg conflict checking) · competitors (battlecards from
your real win/loss record) · market signals · demand gen + thought leadership · content
tailoring · quote generation (with guard rails) · daily brief · weekly brief ·
forecast dashboards (engagement-ranked based on your email traffic & calendar, goals-framed).

**Design principles:** the folder is the database; you should be able to open your opportunities,
leads, tasks, and other data directly in Excel and filter/search/edit if needed. Most of the time 
the agent should keep your opportunities up to date with interactions and updates, minimal 
manual editing required. If you integrate with CRM pulls are automatic but pushes always require 
confirmation; safe syncing with CRM is built in. 

**Who is it for?** 
- Contributors on a larger team w/ existing CRM: I have been using the plugin as a complement
to my existing CRM system (Salesforce) through the CRM integration option. It can assist you
in ensuring your Salesforce is up to date, you are following up on opportunities and leads you own,
and assist you in drafting/customizing content for your opportunities. If additional modules 
are used it can also track news on your accounts, build competitive battle cards per account,
build quotes, draft demand generation content (blogs, social posts), and build custom
forecasts/briefs for you (say before your weekly Forecast call).

- Small teams w/o a CRM: Save money and time by automating your CRM locally on your filesystem.
Instead of subscribing and paying money for an overly complicated cloud CRM like Salesforce,
have your CRM set up locally with views in software you already use like Excel. The agent helps
to keep everything up to date and ensure you are following through properly on every lead, opportunity,
and are keeping up to date with the latest news/market signals applicable to you. 

**Guided setup.** It's a checklist at `00-Config/setup-checklist.csv` with an HTML
progress dashboard, walked module by module, with each field mapping confirmed against
real records before anything depends on it. Pause whenever; completion is derived from
evidence in the folder rather than from memory of having done it.

## Install

Plugins require a paid Claude plan (Pro, Max, Team, or Enterprise).

### Cowork / Claude desktop app

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

## Updating

### 1. Turn on auto-sync for the marketplace

Third-party marketplaces have auto-update **off by default** (only Anthropic's are on), so
nothing refreshes on its own. Until you turn it on, the plugin listing keeps showing
whatever version it cached when you added it, and the **Update** control sits greyed out —
because as far as Cowork knows, that stale version *is* the latest.

1. **Customize** → **Plugins** → the **Personal** tab.
2. Select the **mySails.ai** marketplace — the marketplace entry, not the plugin under it.
   This is the step people miss: refreshing happens at the marketplace level and the
   installed plugin follows.
3. Turn on **auto-sync**.

To pull an update right now rather than waiting, use the same marketplace entry's refresh /
update action. In Claude Code the equivalent is:

```
/plugin marketplace update cgogoel-marketplace
/reload-plugins
```

If the plugin still won't offer the new version, remove the marketplace and re-add
`cgogoel/mySails.ai`. Removing a marketplace uninstalls the plugins that came from it, so
reinstall afterwards — no data is at risk, since nothing lives in the plugin.

A plugin installed by uploading the `.plugin` file has no marketplace behind it and can
never offer an update. That one needs uninstall and re-upload.

Updating the plugin brings every skill **and every script** forward at once, because scripts
run from the plugin rather than from your folders. That's most of the update.

### 2. Reconcile customizations with the latest updates

The one thing a plugin update can't do is reconcile a folder's schemas, because you're
allowed to edit those. In a session on that folder, say **"update my sales system"**, or run
it directly:

```bash
R=$(python3 "<project>/.sales-system/find_scripts.py" --plugin-root)
python3 "$R/skills/update-system/scripts/upgrade.py" --check <project>
python3 "$R/skills/update-system/scripts/upgrade.py" --apply <project>
```

The upgrader ships inside the `update-system` skill, so there's only ever one copy and it
always matches the skills beside it. Working from a clone of this repo,
`~/mySails.ai/skills/update-system/scripts/upgrade.py` does the same job — a way to update a
folder without waiting on the plugin manager at all.

## Layout

- `skills/` — the fourteen skills, including `update-system` which carries the upgrader
- `.sales-system/` — the generic support layer: schemas, scripts, conventions. Contains
  no org data. Scripts and `CONVENTIONS.md` run from here and are never copied into a
  project folder, so updating the plugin updates every folder's behaviour at once. Only
  `schemas/` is copied out, because those are yours to edit.
- `.sales-system/MANIFEST.json` and `manifests/` — a hash per shipped file for this
  release and every past one. This is what lets an upgrade tell a file you edited from
  one that hasn't been touched since install. Both are generated by `make_template.py`
  and committed.
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
