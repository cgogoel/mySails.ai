---
name: "update-system"
description: "Update the sales system — check whether the installed plugin is behind the latest release, whether a project folder's schemas are behind the plugin, and bring both forward. Explains the marketplace auto-sync setting, since third-party marketplaces ship with auto-update off and that presents as a greyed-out Update control that reads as 'you are current'. Use whenever the user asks to update or upgrade the sales system or plugin, asks whether they are on the latest version, asks what is new or what changed, says the update button is greyed out or an update is not appearing, says a skill referenced something their folder does not have, mentions a version mismatch, or when another sales skill reports the support layer is out of date."
---

# Update System

Two things carry a version and they move by different means. Say which is which before
doing anything, because the fix is different for each and people reasonably assume there's
one update button.

| | What it is | How it updates |
|---|---|---|
| **The plugin** | The skills, and the scripts they run | The marketplace, through the plugin manager |
| **The folder** | `.sales-system/schemas/` in each project, plus the CRM profile | `upgrade.py` in this skill |

Scripts live in the plugin and run from there, so **updating the plugin updates all
behaviour everywhere at once**. What a folder holds is its schemas — which the user is
allowed to edit — and those need reconciling rather than replacing. That's the only reason
a second step exists.

## Step 1 — Is the plugin itself behind?

This is the check nothing else can do, and the one that catches the confusing failure.

Read `repository` from `.claude-plugin/plugin.json`, then fetch that repo's latest release
and compare against the installed `version`:

```
https://api.github.com/repos/<owner>/<repo>/releases/latest
```

Read-only. Nothing is fetched into the folder and nothing is written. **If it fails —
offline, private repo, rate limit, a fork with no releases — say so in one line and move
on.** A version check that blocks work is worse than no version check.

If the installed version is behind, the fix is the marketplace, not the plugin entry:

> You're on 0.2.1 and 0.3.0 is out. Refreshing is at **Customize → Plugins → Personal
> tab → the mySails.ai marketplace entry** — the marketplace, not the plugin listed under
> it. Turn on **auto-sync** while you're there and this stops needing doing.

**Explain the greyed-out Update control if it comes up**, because it is genuinely
misleading: third-party marketplaces ship with auto-update off, so the catalog is whatever
was cached when it was added. The control greys out because the cached listing says you're
current — not because you are. In Claude Code the equivalent is
`/plugin marketplace update <marketplace-name>` then `/reload-plugins`.

A plugin installed by uploading the `.plugin` file has no marketplace behind it and can
never offer an update; that one needs uninstall and re-upload.

## Step 2 — Is the folder behind the plugin?

This skill is the one that has to work in a folder that is *already* broken, so it resolves
the plugin longhand rather than relying on `find_scripts.py` — the folder being upgraded may
predate it. Every other skill uses the one-liner; this one earns the exception.

```bash
R=$(python3 "<project>/.sales-system/find_scripts.py" --plugin-root 2>/dev/null)
if [ -z "$R" ]; then
  for c in "${SALES_SYSTEM_SCRIPTS%/.sales-system/scripts}" \
           "$CLAUDE_PLUGIN_ROOT" \
           "$(dirname "<project>")"/.remote-plugins/*/ \
           "$HOME"/.claude/plugins/*/ "$HOME"/.claude/plugins/*/*/; do
    [ -n "$c" ] && [ -f "$c/skills/update-system/scripts/upgrade.py" ] && { R="$c"; break; }
  done
fi
[ -n "$R" ] || { echo "STOP: cannot locate the installed plugin. Set SALES_SYSTEM_SCRIPTS and retry."; exit 1; }
python3 "$R/skills/update-system/scripts/upgrade.py" --check <project>
```

**Never write `$CLAUDE_PLUGIN_ROOT` straight into a command.** It is empty in Cowork's bash
sandbox, the path collapses to `/`, python exits 2, and the skill carries on as if the step had
worked. That is how fourteen skills spent six days running no scripts at all in a live folder
while producing perfectly normal-looking output.

There is only one copy of `upgrade.py` and it ships with these skills, so it always agrees with
them.

**A folder missing `.sales-system/find_scripts.py` is the case this step exists for.** It
predates the resolver, which means every scripted step in every other skill has been failing
silently in it. `--apply` installs the resolver as an `ADD`. Say that plainly when reporting
what the upgrade did: it is the most consequential thing in the release and it is invisible.

`--check` writes nothing. It classifies every file the folder holds:

| | Meaning |
|---|---|
| `ADD` | Not installed yet |
| `SAME` | Already current, or reconciled earlier with neither side moving since |
| `UPDATE` | Byte-identical to what was published at install, so replacing it loses nothing |
| `MERGE` | A schema the user edited. New columns arrive; their columns, extra enum values and ownership choices stay |
| `KEEP` | Edited and not safely mergeable. Left alone, new version written alongside as `<name>.new` |

Report it in their terms, not the script's. "One schema you'd added a column to gets
merged; everything else is a straight update" beats pasting the table.

Then apply:

```bash
python3 "$R/skills/update-system/scripts/upgrade.py" --apply <project>
```

It backs up what it's about to replace, applies, and runs `csvguard --check-all` so new
schema columns reach registries that already exist.

## Step 3 — Say what actually happened

- **Anything reported `KEEP` means that folder is still running the user's version of that
  file.** Say so explicitly and point at the `.new` copy. Silently leaving someone on an old
  file while announcing a successful update is the same class of mistake as a silent revert.
- **Name what they gain**, not the version numbers. "This adds the drift check against your
  CRM and the guard that refuses a write which would revert live edits" is the answer to
  "what did that do."
- **Lead with anything whose meaning changed.** `--check` prints the changelog entries between
  their version and the new one, under "What changes, in what it means to you". A column that
  starts measuring something different from last month matters more than five new files, and it
  is the one thing they cannot discover by looking. Say it in your own words before listing
  anything else.
- If a merge kept something of theirs, name it: "kept your `Legal Review` stage and your
  `exec_sponsor_internal` column."

### Folders set up before scripts moved into the plugin

Those still contain `.sales-system/scripts/`. Nothing reads them now. They're inert sitting
there and actively dangerous if someone runs one, because they're last month's versions —
running an old guard against current data is precisely the accident the guard exists to
prevent.

`--check` reports them. Removing them is opt-in and needs the user's yes, because it's a
deletion inside their folder:

```bash
python3 "$R/skills/update-system/scripts/upgrade.py" --apply <project> --prune-scripts
```

They're copied to `backups/retired-scripts-<stamp>/` first, not destroyed.

## When another skill sends you here

`csvguard --check-all` prints a one-line note when a folder's support layer is older than
the plugin's, and every skill runs that before touching data. So a user may arrive
mid-brief having been told their folder is behind.

**Don't hijack what they were doing.** Offer the update, and if they'd rather finish the
brief first, say fine and be specific about what's unavailable meanwhile — a folder that's
behind still works, it just can't do the newest things.

## What is never touched

`crm-profile/`, `brand.json`, `backups/`, `cache/`, `locks/`, and every registry, note,
brief and quote. Those live outside the support layer entirely. Say this plainly when
offering an update — "will this touch my data" is the reasonable first question and the
answer is no.

## Version compatibility

`plugin.json` carries `requires_template`: the minimum support-layer version these skills
need. The check is one-directional on purpose:

- **Skills newer than the folder** — they call scripts and columns that aren't there.
  Actually broken, and this is what the floor prevents.
- **Folder newer than the skills** — old skills use old commands, which still exist.
  Fine, just not using everything available.

So it's a floor, not a match, and the two version schemes stay different because they
measure different things: the plugin is semver, the support layer is dated.
