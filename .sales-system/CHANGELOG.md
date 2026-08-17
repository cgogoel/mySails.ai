# Support layer changelog

What changed in each release of the generic layer, newest first. `upgrade.py` prints the entries
between a folder's version and the one it's moving to, so someone upgrading finds out what they
gained — and, more importantly, what quietly means something different now.

The format is one `## YYYY-MM-DD` heading per template version, matching `VERSION.json`.

## 2026-08-17

**The scripts were never running. Everything else in this entry follows from that.**

- **Every skill now resolves the scripts through `.sales-system/find_scripts.py`** instead of
  interpolating `$CLAUDE_PLUGIN_ROOT`. That variable is set in Claude Code and **empty in Cowork's
  bash sandbox**, where the path collapsed to `/.sales-system/scripts/csvguard.py`, python exited 2
  on a line the skill was told to run first, and the skill carried on and produced a normal-looking
  brief. **In any folder used through Cowork, every scripted step in all fourteen skills has been a
  no-op.** Registry repair, CRM drift verification and activity ingest never ran. If you have been
  reading briefs or forecasts from such a folder, they were built on unrepaired registries that
  were never checked against your CRM. Re-run them.
- **New file in your folder: `.sales-system/find_scripts.py`.** The only executable that ships into
  the folder rather than the plugin, because the project folder is the one path a skill always
  knows. It resolves outward, caches the answer in `00-Config/paths.json`, honours
  `SALES_SYSTEM_SCRIPTS`, and **exits non-zero rather than returning an empty string** — the skills
  now stop instead of producing an artifact that looks like it did the work.
- **`upgrade.py --apply` had the same bug**, calling `csvguard.py` at the in-folder path that
  stopped existing when the scripts moved. So the migration step that adds new schema columns to
  existing registries has been silently doing nothing since 2026-08-13. **If you upgraded a folder
  between then and now, its registries may be missing columns the schemas declare.** Re-run
  `csvguard.py --check-all <project>` and the columns arrive.
- **New: `setup_status.py --doctor <project>`**, and a `scripts-runnable` step in the Foundation
  section of the setup checklist. It runs one script and looks at the exit code. The whole six-day
  failure above would have surfaced on day one from that.
- **Fixed: the `system-layer` setup step was checking for `.sales-system/CONVENTIONS.md`**, which
  moved into the plugin, so it read as incomplete in precisely the folders that were correct.

**`engagement_score` and `engagement_trend` were wrong, not just missing.**

- **`activity_sync.py` was discarding inbound email.** Dedup erased direction before building an
  event key, so an outbound message and a reply to it on the same day, with the same person, on the
  same deal collapsed into one event — and the survivor was whichever arrived first in the payload,
  in practice the outbound. Direction is now part of the key. Cross-source dedup is unchanged: two
  reports of the same message always agree on direction.
- **The cost was one-sided.** `email_in` is weighted 7.0 against `email_out` at 1.5, and inbound is
  what gates `Heating` and `Warm`. Collapsing the pair turned a 7.0 into a 1.5 and deleted the
  inbound term — so **a two-way conversation read as chasing**, hitting hardest on exactly the
  engaged deals the score exists to surface. One real ingest of 94 events destroyed 15 inbound
  events across 7 deals; a $175k Commit deal with replies in both weeks scored Steady with zero
  inbound.
- **Your existing activity cache is discarded automatically.** It cannot be repaired — the replies
  were never stored. The next ingest detects the old format, wipes it, and says so. **Give it a
  full 90-day history window, not an incremental one**, or scores will be based on that window
  alone. `engagement.py` warns if it reads a pre-fix cache.
- **New: `activity_sync.py --selftest`**, run by `--doctor`, covering both directions of the dedup
  rule so this cannot silently regress.

## 2026-08-14

**Deals now track who is on them, and which of those people actually reply.**

- **New registry** `07-Opportunities/opportunity-contacts.csv`, one row per person per deal.
  Created empty; every skill tolerates it being absent, so nothing breaks in a folder that hasn't
  built it yet. Build it with `contacts_sync.py --plan` then `--build`.
- **`contacts_engaged` now means "has replied", and is populated.** It was declared and never
  written by anything, which is why `single-threaded` — a flag the opportunity skill advertises —
  had never fired in any folder. It read a blank column and evaluated to nothing, so deals with one
  contact carrying them were reported healthy. If you have ever relied on the absence of that flag,
  it was never evidence of anything.
- **New column `contacts_attached`** — everyone on the deal, from contact roles and activity
  together. The gap between attached and engaged is the interesting number; attachment alone is not
  a risk signal.
- **Four new relationship risk flags** in `risk_flags`: `single-threaded`, `no-reply-ever`,
  `ghost-roles`, `auto-reply-only`. They stay out of `close_plan_gaps`, which is hygiene.
- **New `activity` block in `crm-profile/field-map.json`**, naming the objects behind contact
  roles, email and meetings. `configure-project` introspects and confirms it. Nothing in the
  template names a CRM object.
- **`replied` and `meeting_held` are nullable on purpose.** Blank means the org's logging cannot
  establish direction — which is common — and everything downstream says so rather than reporting
  a false negative.
- **csvguard now coerces placeholder text to empty** in typed columns. `(set)`, `N/A`, `TBD` and a
  bare dash in a number or date column used to fail validation on every subsequent write, including
  writes that never touched the offending row. They now normalise to empty, reported as a repair.

## Earlier

Releases before 2026-08-14 predate this file. `manifests/` holds the published file hashes for each
of them, which is what still lets an upgrade tell an edited file from an untouched one.
