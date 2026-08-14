# Support layer changelog

What changed in each release of the generic layer, newest first. `upgrade.py` prints the entries
between a folder's version and the one it's moving to, so someone upgrading finds out what they
gained — and, more importantly, what quietly means something different now.

The format is one `## YYYY-MM-DD` heading per template version, matching `VERSION.json`.

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
