# Sales system conventions

Every skill in this system reads this file before touching data. It exists so that ten
different skills, run weeks apart, produce a folder that still looks like one coherent thing.

If you are a human reading this: you don't need to. Open `README.md` in the project root
instead. This file is the rulebook the skills follow.

---

## 0. What lives where

Two things carry a version and they move independently. Knowing which is which prevents most
of the confusion around updating.

| | Holds | Lives in | Updated by |
|---|---|---|---|
| **The plugin** | The skills, every script, this file | `$CLAUDE_PLUGIN_ROOT` | The marketplace |
| **The folder** | Registries, notes, briefs, `schemas/`, `crm-profile/`, `brand.json` | The connected project folder | `update-system` |

**Scripts run from the plugin, never from the project folder.** Every invocation in every
skill is:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/csvguard.py" --check-all <project>
```

If `$CLAUDE_PLUGIN_ROOT` is unset, resolve it from the running skill's own path: a
`SKILL.md` sits at `<plugin>/skills/<name>/`, so the plugin root is two levels above it.

This is a deliberate reversal of the original design, which copied the whole layer into
every folder. That left each folder holding its own ageing copy of the scripts — including
a copy of the upgrader, so the thing meant to fix staleness was itself stale. Now there is
one copy of each script, it ships with the skills that call it, and updating the plugin
updates every folder's behaviour at once.

**Schemas are the exception and stay in the folder**, because they're meant to be edited —
add a column, extend an enum to match your CRM. That's the one thing an upgrade has to
reconcile rather than replace, and it's why `update-system` exists at all.

`plugin.json` carries `requires_template`, the minimum support-layer version the skills
need. The check is one-directional: skills newer than a folder call things that aren't
there and break; a folder newer than the skills is merely not fully used. A floor, not a
match.

## 1. The folder is the database

There is no hidden state. Everything the system knows lives in files the user can open,
read, and edit. If a skill needs to remember something, it writes it to a file in a folder
where a human would think to look for it.

Two consequences worth internalising:

- **Never store something only in a chat response.** If it matters tomorrow, it goes in a file.
- **Never write a file the user can't make sense of.** No opaque keys, no serialised blobs,
  no filenames like `data_v2_final.json`.

## 2. Two kinds of files

**Registries** are CSVs. One row per thing, one file per type of thing. They hold the
structured facts: who, how much, what stage, when. They are the files the user opens in Excel.

**Records and documents** are Markdown. They hold the narrative: call notes, research,
battlecards, briefs. They're readable in any text editor and in Finder's preview pane.

A lead has a row in `leads.csv` and, once there's anything to say about them, a note at
`06-Leads/Notes/LEAD-0042-jane-doe.md`. The row is the index; the note is the story. Link
them by putting the ID in the note's filename and frontmatter.

Drafts awaiting approval are a third case: they live in `01-Tasks/Drafts/` named
`TASK-00042-followup-acme.md`, with the task row pointing at them via `draft_path`. Keeping them
in one place means the user can review a morning's worth of drafts by opening one folder.

Never put a paragraph of narrative in a CSV cell. Never put a number that needs summing in a
Markdown file.

## 3. Registry rules

### Two storage formats, one interface

A registry lives as either **`.csv`** or **`.xlsx`**, chosen at setup and recorded as
`storage_format:` in `00-Config/config.md`. `csvguard.py` handles both through the same
commands — pass `leads.csv` and it finds `leads.xlsx` if that's what exists. **Never write a
registry file directly**; always go through the guard, or the styling contract and validation
are lost.

| | `csv` | `xlsx` |
|---|---|---|
| Opens as | Raw text | A finished-looking table |
| Greppable / diffable | Yes | No |
| Excel mangles values | Constantly; the guard repairs it | No — cells carry real types |
| Guides data entry | No | Dropdowns of the org's real picklist values |
| Needs a library | No | `openpyxl` |

The honest trade: `xlsx` is far better to work in and worse to inspect from a terminal. `csv`
is the safer default and the one that works everywhere.

Machine plumbing — the sync log, indexes, anything append-only that nobody opens — stays CSV
regardless of the setting. Schemas mark this with `browsable: false`. Turning a log file into
a binary buys nothing.

Converting is safe and reversible:

```bash
python3 <project>/.sales-system/scripts/csvguard.py --convert-all <project> --to xlsx
python3 <project>/.sales-system/scripts/csvguard.py --convert <path> --to csv
```

Originals are kept until the user deletes them.

### The xlsx styling contract

Everything below is derived from the schema, applied on every write, and idempotent — which
is what keeps a file readable after weeks of editing rather than decaying into a grid.

- Header frozen, filtered, and styled; each header carries the schema's note as a cell comment,
  so the guidance is where someone needs it
- Column widths by type; prose columns wrapped and wide, dates and money narrow
- Real date and currency cells, so sorting and filtering behave
- **Dropdowns on picklist columns**, populated from `crm-profile/picklists.json` — the user
  picks from the values their CRM actually accepts and can't type an invalid one
- Colour on status, health, and risk values, and on genuinely overdue dates
- `id` and derived columns shaded, to signal that editing them achieves nothing

Writes update in place, so a person's own highlighting survives. Run `--restyle <path>` if a
sheet has been mangled.

Colour is deliberately muted and applied only where it carries meaning. A sheet where
everything shouts is a sheet nobody reads, and colouring every past date — including
`created_date`, where being in the past is normal — teaches people to ignore the colour.

### Rules that apply to both formats

These exist because the user edits these files in Excel, and Excel is careless with CSVs.
`.sales-system/scripts/csvguard.py` enforces and repairs them. Under `xlsx` most of the
repairs stop being necessary, because a real date cell can't be reformatted into ambiguity
and a real number can't acquire a currency symbol — but the rules still define the canonical
form the data is normalised to.

- **One header row.** No title rows, no merged cells, no blank spacer rows, no totals row at
  the bottom. Totals belong in a brief, not in the data.
- **Column one is `id`.** Format `PREFIX-0001`. Stable forever, never reused, never renumbered.
  If a row is deleted its ID retires with it.
- **Dates are `YYYY-MM-DD`.** Always. Excel will mangle these; the guard repairs them.
- **Money is a bare number.** `120000`, not `$120,000.00`. Currency is a separate column.
- **No formulas.** A formula in a source file breaks every non-Excel reader. If the user wants
  a calculated view, generate a separate report file.
- **Empty means unknown, not zero.** Don't fill blanks with `0` or `N/A` or `TBD`.
- **Multi-value fields are semicolon-separated** — `single-threaded;no-close-plan`. Not commas.
- **Enum columns have fixed values** listed in the schema. Match case-insensitively when
  reading, write the canonical casing.

### User-added columns are sacred

If someone adds a `My Own Notes` column, it stays. The guard preserves unknown columns by
moving them to the end rather than dropping them. Never delete a column you don't recognise —
assume the user put it there on purpose.

### Always run the guard first

Before reading any registry:

```bash
python3 <project>/.sales-system/scripts/csvguard.py --check-all <project>
```

Or for one file: `--check <path>` to inspect, `--repair <path>` to fix in place (it backs up
to `.sales-system/backups/` first, keeping the last 20 versions per file).

To add a row, use `--append <path> --json '{...}'` rather than writing CSV by hand. It
allocates the next ID, validates fields against the schema, and backs up before writing.
To get an ID without writing: `--next-id <path>`.

To add or update *many* rows, use `--upsert`, never a loop of appends and never a rewrite:

```bash
csvguard.py --upsert <project>/06-Leads/leads --key crm_id --json-file records.json
```

It matches on the key, updates matched rows in place, mints IDs only for genuinely new
ones, and never renumbers. This matters more than it sounds: **an ID is a promise**. Tasks,
notes and cross-references all point at it, so a bulk load that reassigns IDs by position
orphans every one of them silently.

Report repairs to the user in one line — "tidied up three dates Excel had reformatted" — and
move on. Don't lecture them about CSV hygiene. The whole point is that they don't have to
think about it.

### The destructive-write guard

Validation proves a registry is well-formed. It cannot prove it is *right*, and the way
data actually gets lost here is a script that rebuilds the file from a snapshot taken
earlier — every row valid, every row stale. The result validates perfectly clean
afterwards, because it is clean. It's just wrong.

So every full-file write is diffed against the file it replaces, matched on `id`, and
refused if the change has the shape of an accident:

| Trips on | Because |
|---|---|
| More than 10% (min 2) of rows disappearing | Rows don't vanish during an edit |
| More than 20% (min 10) of rows changing value | A fifth of the book moving at once is a rebuild |
| More than 20 non-empty cells being blanked | A feed missing a column looks exactly like this |
| **Any** closed record returning to an open state | A stale snapshot overwriting a decision |

The refusal prints the diff. Read it before doing anything else — if it's a rebuild from an
old snapshot, forcing past it reverts live edits and leaves no trace. To proceed anyway:
`--force`, or `SALESOS_FORCE_WRITE=1` for a script.

Two paths are deliberately exempt, and nothing else should be: normalisation repairs (they
touch cells but never identity — no row dropped, no value blanked) and archiving (removing
rows is the point, and they've just been written to `99-Archive`).

### Column ownership

Every column in every schema declares an `owner`:

| `owner` | Meaning | On a refresh |
|---|---|---|
| `crm` | The CRM is the source of truth | Overwritten |
| `local` | Authored here — `notes`, `health`, judgement calls | Never touched |
| `derived` | Computed here from activity, dates or pipeline | Never touched, and its churn is not evidence of data loss |

`local` is the default, because a field nobody has classified is safer left alone than
overwritten by an import. This is the knowledge that used to live only inside whatever
import script a session happened to write.

## 3a. Scope: whose pipeline is this?

`00-Config/config.md` carries a `scope` field that is either `individual` or `team`. It changes
how every skill behaves, so read it before pulling or summarising anything.

**`individual`** — the folder holds one seller's book. CRM pulls filter to their user ID. The
`owner` column exists but is nearly always the same person, so don't clutter output with it.
Briefs speak in the first person: "you have three deals slipping."

**`team`** — the folder holds a whole team's book, and `00-Config/team.csv` lists the reps.
Then:

- CRM pulls filter by the team's user IDs (or the manager's role hierarchy), not one person.
- `owner` becomes a real dimension. Roll-ups break out by rep, and coverage and quota
  attainment are computed per rep against `team.csv`, not just in aggregate.
- Briefs speak about the team: "Dana has three deals slipping; the team is 68% to number."
- Flag rep-level anomalies a manager would want — someone with no activity this week, a rep
  whose forecast moved more than the rest, an unowned record.
- Never write to a record owned by someone else without saying whose it is first.

A team-scoped folder can still answer individual questions ("show me just my deals"), but an
individual-scoped folder genuinely lacks the data to answer team ones. When in doubt about which
a user wants, ask — and if they're in an ops or management role, `team` is the likelier default.

## 3b. Tasks — the layer that spans every module

Tracking data is inert. Tasks are how the system turns what it knows into what happens next, and
they are deliberately **one registry, not one per module**: `01-Tasks/tasks.csv`. A seller has one
day, not nine. Any skill may raise a task; any skill may close one. The user can add a row in
Excel and the system will pick it up.

Tasks sit at `01-`, immediately after config, because it's the file a person actually opens daily.

### Linking back

Every task carries `related_type` + `related_id` (`opportunity` / `OPP-0031`) plus a denormalised
`account_name`. The denormalisation is on purpose: a spreadsheet full of `OPP-0031` is unreadable,
and the whole premise is that this file makes sense when opened by a human with no tooling.

### The three automation levels

| Level | What the system does | Fit for |
|---|---|---|
| `manual` | Raises the task and gets out of the way | Calls, meetings, judgement calls |
| `review` | Drafts the artifact, sets status `Awaiting Approval`, waits | Almost everything involving a customer |
| `auto` | Executes without asking, then reports what it did | Internal, reversible, low-stakes work |

**`review` is the default and should stay the default.** Drafting is where most of the value is —
the blank page is the expensive part, not the send button. When in doubt, draft and wait.

### Constraints on `auto`

Auto-sending on someone's behalf is the one capability here that can cause damage you can't take
back. A misjudged follow-up costs a relationship, and the system's read of "this needs a nudge"
will sometimes be wrong. So `auto` is fenced:

- **Never the default.** It is only ever set by the user explicitly, per rule, in `task-rules.csv`.
- **Never for first contact.** Cold outreach and any first email to a person is `review` at most,
  regardless of rule. A bad first impression can't be retracted.
- **Never for commercial substance.** Pricing, terms, commitments, dates you'd be held to,
  anything a customer could reasonably treat as a promise — `review`, always.
- **Capped.** `daily_cap` on the rule limits how many a rule may fire per day. If a rule wants to
  fire twenty times, something upstream is wrong; stop and tell the user instead.
- **Reported.** Everything `auto` did appears at the top of the next brief, not buried. The user
  should never learn about a sent email by hearing it from the recipient.
- **Reversible where possible.** Prefer scheduling a send with a delay over sending instantly, so
  there's a window to catch a mistake.
- **Killable.** If the user says stop, set `enabled` to `no` on the relevant rules immediately and
  confirm what's now dormant.

If a task's automation is `auto` but any of the above applies, downgrade it to `review` and say why
in `notes`. Silently downgrading is fine; silently upgrading never is.

### Lifecycle

```
Open ──> Drafted ──> Awaiting Approval ──> Done
  │                        │
  │                        └─> (edited, re-drafted) ──> Awaiting Approval
  ├─> Scheduled ──> Done            (auto, with a send delay)
  ├─> Snoozed  ──> Open             (snooze_until passes)
  ├─> Blocked  ──> Open             (blocked_reason cleared)
  └─> Cancelled
```

Set `completed_how` when closing so the record shows who actually did it: `user-approved`,
`system-auto`, `user-manual`, or `detected`.

### Detecting work the user did themselves

This is what keeps the list honest. People do things without telling the system, and a task list
that nags about work already finished gets abandoned within a week.

Before showing anyone their open tasks, sweep for evidence that they're already done. Each task
carries `verify_by` and `verify_target` describing what to look for:

| `verify_by` | Look for |
|---|---|
| `email-sent` | A sent message to `verify_target` after `created_date` |
| `email-reply` | A reply from `verify_target` — often better proof than a send |
| `calendar-event` | A past event matching `verify_target` that wasn't declined |
| `crm-activity` | A logged activity on the linked record |
| `crm-field` | The named field now holding a different value |
| `file-created` | A file existing at `verify_target` |
| `manual-only` | Nothing to detect; only the user can close it |

**Check the CRM as well as email and calendar.** Three sources carry evidence, and they see
different things:

- **Email** — what the user personally sent from their own mailbox.
- **Calendar** — meetings that happened, and whether they were declined.
- **CRM activity** — logged calls, auto-captured email, and field changes. Crucially this is the
  only source that shows **someone else's** work: a colleague who called the account, a manager who
  updated the next step, an SE who logged a POC outcome.

Under `team` scope the CRM is the primary source rather than a supplement, since a rep's mailbox
isn't visible and their work only shows up as activity records.

A field update is evidence too. If the task was "update the close date on Acme" and the close date
now differs, that's done — regardless of who did it. Where the CRM stamps an author (many orgs track
who last changed a next step), say who: "Dana updated the next step on Acme yesterday" is often more
useful than closing the task silently.

Activity tables are large and frequently auto-populated by email capture, so the profile may carry
query bounds and noise-filtering guidance. Honour both — an unbounded activity query can time out,
and unfiltered auto-captured email will bury the handful of records that mean anything.

When you find evidence, close the task with `completed_how = detected` and put the specific proof
in `completion_evidence` — "email to jane@acme.com sent 2026-08-04 09:12", not "found evidence".
The specificity is what lets the user overrule you when you're wrong.

Be conservative. A false close hides real work, which is worse than a task that lingers a day
longer. If the evidence is ambiguous — an email to the right domain but a different person, a
meeting that may have been about something else — leave it open and mention the near-match rather
than deciding. Never close a task because time passed.

### Raising tasks well

A task list is only trusted if every row earns its place. Before raising one, ask whether the user
would thank you for it.

- **Fill in `why`.** One line of justification. A task with no reason gets ignored, and one ignored
  task teaches people to skim the whole list.
- **Be specific in `title`.** "Send pricing follow-up to Jane Doe (Acme)" beats "Follow up on Acme."
  The title should be actionable without opening anything else.
- **Don't duplicate.** Check for an open task with the same `related_id` and `task_type` first. If
  one exists, raise its priority or update its due date instead of adding a second row.
- **Respect the caps** in `task-rules.csv`. A brief that generates thirty tasks has generated zero.
- **Prefer fewer, better tasks.** If you can only raise three, raise the three that matter.

### Tasks that also live somewhere else

`external_system` and `external_id` let a task carry a pointer to a copy in Todoist, Reminders,
Asana, or wherever the user actually looks. Blank means the task exists only here.

There is no bridge built yet — these columns exist so that adding one later is a small job rather
than a schema migration. If you do build one, the hard part isn't the plumbing, it's deciding
which side wins. Say so rather than papering over it: this folder has to be the source of truth
for anything the system drafts or verifies from email, because the external app can't see that
context. A mirrored copy is a convenience, not a second master.

### Rules are configuration, not code

`01-Tasks/task-rules.csv` holds the policy: what conditions raise what tasks, at what automation
level, with what caps. It's a CSV so the user can open it and change `automation` from `review` to
`manual`, or flip `enabled` to `no`, without asking anyone. Read it before raising tasks and honour
what it says, including when it says don't.

If the user asks for behaviour that isn't in the rules, add a rule rather than hard-coding the
behaviour into a one-off — that's what makes it inspectable and reversible later.

## 3c. Seeding is not refreshing

These are different operations and confusing them is the single most expensive mistake
available in this system. Both fill a registry with CRM data; only one of them is safe to
run twice.

| | Seed | Refresh |
|---|---|---|
| When | First load, once | Every time after |
| Against an existing registry | **Refuses** | Expected |
| Writes | Every column | Only `owner: crm` columns |
| Local edits since last sync | Destroyed | Preserved |
| IDs | Minted | Never renumbered |

```bash
crm_sync.py --plan    <project> --registry opportunities        # what to pull
crm_sync.py --seed    <project> --registry opportunities --json-file recs.json
crm_sync.py --refresh <project> --registry opportunities --json-file recs.json
crm_sync.py --verify  <project> --registry opportunities --json-file recs.json
crm_sync.py --ingest  <project> --registry leads --file <export.csv> --mode refresh
```

**Never write your own import.** If `crm_sync.py` can't do what's needed, extend it — a
one-off script in a session is exactly how a seeder gets re-run as a refresh months later
by someone who assumed it was idempotent. Any script that rebuilds a registry from a
snapshot is a seeder, must refuse to run against a registry that already has rows, and
must say so rather than helpfully proceeding.

**The CRM read belongs to the skill, the comparison belongs to the script.** The CRM is
reachable only through a connector the agent holds, so the flow is always: run `--plan` to
learn what to select, query through the connector, write the result to JSON, hand it to
`--refresh` or `--verify`. The scripts never talk to a CRM, which is what keeps them
CRM-agnostic and testable. `--plan` prints a ready-made query only where the CRM has a
query language the profile names; otherwise it names the fields and leaves the asking to
whatever the connector offers, because a query invented for an unknown API looks
authoritative and doesn't run.

### Bulk loading through a report export

Pulling records through a connector costs roughly a thousand tokens each — fine for 200
deals, absurd for 27,000 leads. For anything large, have the user export a report to
`<module>/import/` and run `--ingest`, which handles what exports generally get wrong:
cp1252 encoding rather than UTF-8, `M/D/YYYY` dates, booleans that arrive as `0`/`1` in one
column and `true`/`false` in the next, field labels instead of API names, title rows above
the header, and "Grand Totals" or confidentiality lines below the data. None of that is
particular to one vendor; it comes from the export machinery.

**The export must include the record ID column.** Without it nothing can be matched, and
rows will be skipped rather than guessed at. Ingest reports every column it could not map —
read that list, because an unmapped column is data silently not imported.

### Vendor quirks are named, not assumed

Nothing in this system is built for a particular CRM. But individual CRMs do have quirks
that silently corrupt an import, and pretending otherwise doesn't help anyone — so each is
declared against the CRM it belongs to in `csvguard.CRM_DIALECTS`, keyed on `crm` in
`field-map.json`, and applied to that CRM alone. An unrecognised CRM, or none at all, gets
generic behaviour throughout.

What a dialect declares: the record's identifier and last-modified field names, the query
language if it has one, whether custom fields carry a suffix or namespace that report
labels drop, and whether record IDs have more than one form.

That last one is currently Salesforce only. It has two forms of every ID — reports export
15 characters, the API returns 18 — which compared raw never match, so an import that
assumes one form loads every record twice. **Matching is on `crm_key()`, never on `crm_id`
directly.** `crm_key` changes nothing by default: an ID is an opaque string, and guessing
at its structure is how unrelated records get merged. Even for Salesforce it only collapses
18 to 15 when the last three characters verify as that CRM's checksum of the first fifteen.

Any of it can be overridden per org by putting the same keys at the top level of
`field-map.json` — which is how a CRM with no dialect entry, or one whose API has been
customised, gets handled without a code change.

## 4. IDs by type

| Prefix | Registry | Lives in |
|---|---|---|
| `REP` | team roster (team scope only) | `00-Config/team.csv` |
| `TASK` | tasks | `01-Tasks/tasks.csv` |
| `RULE` | task rules | `01-Tasks/task-rules.csv` |
| `CUST` | customers | `02-Context/Customers/customers.csv` |
| `SIG` | market signals | `03-Market/signals.csv` |
| `COMP` | competitors | `04-Competitors/competitors.csv` |
| `CMP` | campaigns | `05-Demand-Gen/campaigns.csv` |
| `LEAD` | leads | `06-Leads/leads.csv` |
| `OPP` | opportunities | `07-Opportunities/opportunities.csv` |
| `REN` | renewals | `08-Renewals/renewals.csv` |
| `ASSET` | content assets | `10-Content/asset-index.csv` |

Cross-references use the ID: a lead that converts gets `converted_opp_id = OPP-0031`. A
renewal points at `customer_id = CUST-0009`. This is what lets a brief walk from a calendar
event to a deal to the account's history without guessing.

## 5. Naming

- Folders: `Title Case With Spaces`, prefixed with a two-digit number for sort order.
- Registry CSVs: `lowercase-plural.csv`.
- Record notes: `<ID>-<slug>.md` — `OPP-0031-acme-platform.md`.
- Dated outputs: `YYYY-MM-DD-<slug>.md` — `2026-08-03-daily-brief.md`.

Numbered folder prefixes are there so the folder opens in a sensible order in Finder rather
than alphabetically. The numbers aren't meaningful beyond that.

## 6. Markdown records carry frontmatter

```markdown
---
id: OPP-0031
type: opportunity
account: Acme Corp
updated: 2026-08-03
---
```

Skills use this to find records without parsing prose. Keep it minimal — the registry holds
the structured data, frontmatter just makes the file findable.

## 7. CRM sync

This project is configured for two-way sync. The asymmetry is deliberate and load-bearing:

- **Pulls are automatic.** Reading from the CRM needs no permission.
- **Pushes are never automatic.** Before writing anything to the CRM, show a field-by-field
  diff — current CRM value, proposed new value — and get an explicit yes. Batch pushes get a
  summary table and one confirmation for the batch.
- **Conflicts go to the user.** If both the folder and the CRM changed since `last_updated`,
  don't pick a winner. Show both and ask.
- **Log everything** to `00-Config/sync-log.csv`, pulls included.

### Both sides, same action

> Any change to a synced record is applied to **both** the local registry and the CRM in the
> same action. Never one alone, never "push it later". Where a push is refused or blocked — a
> duplicate rule, a validation error, a departed contact — record the failure on the local row
> so the folder is never silently ahead of the CRM.

"Push it later" is how a folder ends up confidently reporting numbers the CRM disagrees with.
If the push can't happen now, set `sync_status` to `pending-push` and say so in the same
breath as reporting the local change — an unpushed edit is a half-finished action, not a
completed one.

### The four states, and keeping them true

Each synced row carries `crm_id`, `sync_status`, `crm_last_modified` and `last_synced`:

| `sync_status` | Meaning |
|---|---|
| `local-only` | Exists here, not in the CRM. Never pushed. |
| `synced` | Matched the CRM as at `last_synced`. |
| `pending-push` | Changed here since then; the CRM is currently wrong. |
| `conflict` | Both sides changed. Needs a human. |

These are only worth anything if they're maintained. **Set `pending-push` on every local
edit to a CRM-owned field, and clear it only on a confirmed push.** A column where every row
says `synced` forever answers no question at all.

`crm_last_modified` holds the CRM's own timestamp as at the last sync, and `last_synced`
when the row was last reconciled. Together they make drift computable rather than guessable:
if the CRM's current timestamp has moved past `crm_last_modified`, the change came from over
there; if `last_updated` is later than `last_synced`, it came from here.

A row with an empty `crm_id` has never been pushed. Don't create CRM records as a side effect
of some other task — creating records in a system of record is its own decision.

### Verify before you report

**Run a drift check at the top of every brief and every forecast**, before computing anything
from a synced registry:

```bash
csvguard.py --sync-query <project> --registry opportunities     # what to select
# ... query the CRM through the connector, write the result to snapshot.json ...
csvguard.py --verify-sync <project> --registry opportunities --crm-json snapshot.json
```

Three outcomes, and the distinction decides what to do:

| | What happened | Response |
|---|---|---|
| **DRIFT** | The CRM changed since the last sync — someone else edited it | `--refresh` to accept, or push if the local value is the right one |
| **AHEAD** | Changed here and never pushed | A push failed or was skipped; the CRM is currently wrong |
| **CONFLICT** | Both sides changed | Show both and ask. Never pick a winner |

Lead with what it found. A forecast that opens with "16 opportunities changed owner in the
CRM since your last sync" is doing its job; the same forecast reporting a quietly wrong
by-rep split is worse than no forecast, because it will be believed.

If a check can't run — no connector, no profile, the user in a hurry — say so in one line
and label the numbers as unverified. Silence reads as confirmation.

### Fields the profile says to ignore

`field-map.json` may carry an `ignore_fields` block. Those fields exist in the CRM and are
deliberately excluded from this system — not unmapped, not forgotten, excluded.

This usually happens where an org has accumulated several fields claiming the same meaning, and the
user has picked one. Honour that: don't import them, don't display them, and don't offer to
reconcile them against the field that was chosen. Re-importing a rejected field rebuilds exactly
the ambiguity the user resolved.

If someone asks about an ignored field, say the system tracks the chosen one only and offer to
query the CRM directly. That answers the question without quietly adding a second source of truth
to the folder.

## 8. Writing for the user

The person using this is selling for a living and reading your output between meetings.

- Lead with the answer. The three things that matter go at the top.
- Say what to do, not just what is true. "Acme has gone quiet for 12 days" is an observation;
  "Acme has gone quiet for 12 days — worth a check-in before Thursday's forecast call" is useful.
- Cite the file. When a claim comes from a record, name it so they can go look.
- Flag thin evidence. If a conclusion rests on one stale field, say so rather than laundering
  it into confident prose.
- Don't invent pipeline. If the data isn't there, say the data isn't there.

## 8a. Money and currency

Amounts are bare numbers; `currency` is a separate column, and orgs with multi-currency CRMs will
have mixed books. **Never sum amounts across currencies.** A €80K and a $120K deal do not make
"200K" of anything. Totals in forecasts, briefs, and goal attainment group by currency; if a book
is single-currency, this costs nothing. If someone wants a blended figure, that requires a
conversion rate and a date, which is a decision — ask, don't assume.

## 8b. Archiving — registries must not grow forever

Rows accumulate; a tasks file gains rows daily, and a registry with thousands of rows gets slow to
open and slower to style. Each schema carries an `archive` policy (closed states + age). Run:

```bash
python3 <project>/.sales-system/scripts/csvguard.py --archive <project> [--dry-run]
```

Rows move to `99-Archive/<registry>-<year>` in the same schema and styling — still openable, still
queryable. **Open items never archive regardless of age.** Quote lines follow their quote. A good
cadence: monthly for tasks, quarterly for the rest; the weekly brief may suggest it when a registry
is getting heavy. Derived stats (competitor win rates, partner totals) should be computed across
live + archive where history matters — say when a number excludes archived years.

## 8c. Shared drives and multiple users

The folder can live on OneDrive/SharePoint/Drive and be shared, with guardrails — this makes
sharing *safe*, not *simultaneous*. It's a small team taking turns cleanly, not Google Sheets.

- **Write leases.** Every registry write acquires `.sales-system/locks/<file>.lock`. A locked file
  produces "locked by dana@laptop-2, retry shortly" instead of silent last-writer-wins. Stale locks
  (10 min) are stolen automatically.
- **Excel-open detection.** A `~$` file next to a workbook means someone has it open in Excel;
  writes refuse rather than racing a live session.
- **Sync-conflict copies.** `--check-all` finds `-Copy` / `(1)` / "conflicted copy" forks of
  registries and demands a merge — nothing reads a fork, so edits in one are otherwise lost.
- **The activity cache is per-machine** (in local temp, keyed by project path), never synced, and
  cheap to rebuild via `activity_sync.py --rebuild`.
- **Quotes that were sent are immutable.** `quote.py --freeze-check <project>` recomputes every
  Sent/Accepted quote from its lines and flags mismatches. Changes go in a new version, never an
  edit.

## 8d. Fresh installs and template distribution

`make_template.py <project>` packages the generic layer (scripts, schemas, CONVENTIONS, VERSION —
no profile, no brand, no data) into `sales-system-template.zip`. Setting up a new project means
unpacking that zip into `<project>/.sales-system/` and running configure-project — **never**
regenerating the scripts from memory, which produces something subtly different every time. The
zip is safe to share outside the company.

### Upgrading a folder that already exists

Updating the plugin brings every script and skill forward everywhere at once. What it can't do
is reconcile a folder's **schemas**, because the user is allowed to edit those. That's the
`update-system` skill's job:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/skills/update-system/scripts/upgrade.py" --check <project>
python3 "$CLAUDE_PLUGIN_ROOT/skills/update-system/scripts/upgrade.py" --apply <project>
```

The upgrader lives in the skill rather than in this layer, so there is only ever one copy of
it and it always agrees with the skills it ships beside.

Each schema is classified before anything is written:

| | Meaning |
|---|---|
| `ADD` | Not installed yet |
| `SAME` | Already identical, or reconciled by an earlier upgrade with neither side moving since |
| `UPDATE` | Byte-identical to what was published at install, so replacing it loses nothing |
| `MERGE` | An edited schema. New columns arrive; the user's columns, extra enum values and ownership choices stay |
| `KEEP` | An edited script or document. Left alone, with the new version written alongside as `<name>.new` |

That distinction rests on `MANIFEST.json`, a hash per shipped file written at package time, plus
`manifests/<version>.json` for every past release — so a folder installed before manifests existed
still has a baseline and doesn't have to assume the worst about every file. The manifest records
both what the template published and what the folder actually holds, which is what makes a second
run a clean no-op rather than re-reporting the same merge forever.

Never touched: `crm-profile/`, `brand.json`, `backups/`, `cache/`, `locks/`, and every registry,
note and brief. What's about to be replaced is copied to
`backups/upgrade-<from>-to-<to>-<stamp>/` first, and `csvguard --check-all` runs afterwards so
new schema columns reach the existing registries.

**A file reported as `KEEP` means the folder is still running the user's version of it.** Say so.
Silently leaving someone on an old file while reporting a successful upgrade is the same class
of mistake as a silent revert.

Folders set up before scripts moved into the plugin still contain `.sales-system/scripts/`.
Nothing reads them. `--check` reports them and `--prune-scripts` retires them to `backups/` —
opt-in, because it's a deletion inside someone's folder. Leaving a stale `csvguard.py` next to
live registries is an invitation to run last month's guard against this month's data.

`csvguard --check-all` prints a one-line note whenever a folder's layer is older than the
plugin's. Every skill runs that before touching data, which is how the warning reaches all of
them without thirteen preambles having to remember to ask. It never blocks: a folder that's
behind still works.

## 9. When configuration is missing

If `00-Config/config.md` doesn't exist, the project hasn't been set up. Don't improvise a
folder structure — run the `configure-project` skill instead. Half-configured projects are
worse than unconfigured ones because they look finished.
