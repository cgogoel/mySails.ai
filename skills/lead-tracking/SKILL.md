---
name: "lead-tracking"
description: "Manage the lead registry in the sales project folder — import leads from a CRM or a file, triage and prioritize them, update status, record what happened, convert qualified leads to opportunities, and raise follow-up tasks. Use whenever the user mentions leads, asks who to follow up with, wants to import or refresh leads from the CRM, wants to work or triage their lead list, asks which leads have gone quiet or are worth calling, wants to disqualify or nurture someone, wants to convert a lead into a deal, or asks to push lead changes back to the CRM. Also use when a brief or another sales skill needs the current state of the lead pipeline."
---

# Lead Tracking

Leads are the top of the funnel: the most rows, the least signal per row. The job here is not to
display a list — the CRM already does that badly. It's to make a long list short. Which handful of
people are worth attention today, and what to do about each one.

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`.
2. Read `$CLAUDE_PLUGIN_ROOT/.sales-system/CONVENTIONS.md`. It governs CSV handling, task raising, and CRM sync.
3. Read `00-Config/config.md` for `scope` (individual vs team) and `default_automation`.
4. If `00-Config/config.md` is missing, stop and run `configure-project` instead.
5. **Read `.sales-system/crm-profile/` if it exists** — see below. This is what makes the skill fit
   the user's actual CRM rather than a generic idea of one.
6. Repair the registry before reading it:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/csvguard.py" --repair <project>/06-Leads/leads.csv --project <project>
```

Leads live in `06-Leads/leads.csv`. Narrative goes in `06-Leads/Notes/LEAD-0042-jane-doe.md`.

---

## The CRM profile

This skill ships generic and knows nothing about any particular CRM. The user's environment is
described in `.sales-system/crm-profile/`:

| File | What it tells you |
|---|---|
| `profile.md` | Narrative: quirks, conventions, what a newcomer would trip over |
| `field-map.json` | Local column → CRM field, per object. Also `never_push`, `safe_to_push`, `shared_fields` |
| `picklists.json` | The org's real allowed values. `csvguard` already applies these |
| `contactability.json` | Which fields mean "don't contact," and what each blocks |

**Read the profile before writing a query or a push.** Field names, picklist values, and which
fields are owned by integrations all vary enormously between orgs, and guessing produces silent
failures — a push that hits a validation rule, or worse, one that succeeds and stomps a field some
integration owns.

If there's no profile, the CRM either isn't connected or hasn't been introspected. Work
folder-only and offer to run `configure-project` to generate one. Never invent field names.

Profiles go stale. If a CRM value isn't in the profile, that's usually the profile being out of
date rather than the record being wrong — say so and offer to refresh rather than treating a real
record as invalid.

---

## The two gates — check before anything reaches a person

These exist because the cost of getting them wrong is borne by the relationship, not the system.
Check both before drafting, sending, or even raising an outreach task.

### Gate 1: `contactable`

`contactable = no` means this person has told you, in some form, to stop. Don't draft to them,
don't raise outreach tasks, don't include them in a "who should I follow up with" list.

It's derived on import from the fields listed in `contactability.json`. Record which ones tripped
it in `contact_restrictions`, so the user sees *why* rather than having to trust a flag.

Two nuances that matter more than they look:

**Opt-outs are often channel-specific.** Many CRMs distinguish marketing opt-out from direct sales
opt-out, and treat them independently — someone who unsubscribed from a newsletter may be entirely
open to a 1-1 note. `contactability.json` records what each flag blocks. Report which channel is
closed rather than writing the person off.

**Some blockers are redirects, not dead ends.** A bounced address means find the new one. A
left-the-company flag means find someone else at that account. Raise *that* task instead of
silently dropping the lead — a departed champion at a good-fit account is a lead, not a loss.

### Gate 2: `in_sequence`

Most orgs run an automated cadence tool. A lead in an active sequence is already receiving
touches. Raising "follow up with Jane" on top of that produces two messages from two systems in
the same week, which reads as desperate and is the fastest route to an unsubscribe.

If `in_sequence = yes` and `sequence_next_step_date` is in the future, don't raise outreach tasks.
The sequence has it.

The exception is the whole point of the gate: **a lead who has replied to a sequence needs a human
immediately.** Someone answered a robot. Whatever that status is called in this org — the profile
will say — surface those first, always, with how long they've been waiting. A reply sitting three
days is an emergency, not a task.

---

## CRM sync

### Pulling

Filter by owner according to `scope`: individual → the user's CRM user ID (and any secondary-owner
field the profile names); team → the IDs in `00-Config/team.csv`.

Apply the profile's `default_filter` — usually excluding converted and deleted records. Pull every
gate field in the same query: a lead record without its contactability flags is unsafe to act on
and shouldn't be written to the registry at all.

Prefer incremental pulls on last-modified over refetching everything. Log the sync to
`00-Config/sync-log.csv`.

### Pushing

Per `CONVENTIONS.md`, never automatic. Build the diff, show it as a table — field, current CRM
value, proposed value, which local edit caused it — and get an explicit yes. One confirmation per
batch is fine; zero is not.

Push only what `field-map.json` lists under `safe_to_push`. Refuse anything in `never_push` even if
asked directly, and say why — the profile records the reason, usually that an integration owns the
field and a write would be reverted or would break a sync.

Respect `shared_fields`. Some CRMs have note fields that colleagues read and write. Append with a
date rather than overwriting someone else's text, and keep longer thinking in the local Markdown
note where it can't collide.

If a push fails on a validation rule, report the CRM's error text verbatim. It's ugly but specific,
and paraphrasing makes it useless to whoever has to fix the record.

---

## What to actually do

### Import

**Use `crm_sync.py`. Never write your own import** — see `CONVENTIONS.md` §3c for why.

```bash
S="$CLAUDE_PLUGIN_ROOT/.sales-system/scripts"
python3 $S/crm_sync.py --plan    <project> --registry leads          # what to select
python3 $S/crm_sync.py --seed    <project> --registry leads --json-file recs.json
python3 $S/crm_sync.py --refresh <project> --registry leads --json-file recs.json
```

Lead lists are where volume bites. Pulling 8,000 leads through a connector costs roughly a
thousand tokens each; have the user export a report instead, drop it in `06-Leads/import/`, and:

```bash
python3 $S/crm_sync.py --ingest <project> --registry leads --mode refresh
```

Ingest deals with what exports generally get wrong — cp1252 encoding, `M/D/YYYY` dates, booleans
that are `0`/`1` in one column and `true`/`false` in the next, field labels instead of API names,
and "Grand Totals" footers — plus whatever their specific CRM does to record IDs, which is
declared per CRM rather than assumed. **Read the list of unmapped columns it prints** — an
unmapped column is data silently not imported. Tell the user the export must include the record
ID column; without it rows are skipped rather than guessed at.

Derive `contactable` and `in_sequence` after every load — they're derived columns, so a refresh
deliberately leaves them alone.

Matching is on `crm_id` and is handled for you. Where a lead has no `crm_id` at all — a pasted
list, a conference scan — match by email, then name plus company, and when a match is probable but
not certain show both rows and ask rather than merging. Duplicates are the most common way these
registries rot.

Report the *shape* of what arrived, not just the count: how many are contactable, how many are in
sequence, how many have no email, how many are untouched in 30 days. That's the sentence that tells
someone whether the list is worth working.

Expect sparse data. Many CRMs require almost nothing on a lead record, so blanks are normal. A
missing email is a research task, not an error.

### Triage

The main event. When asked who to work, rank — don't print the registry. Roughly, in descending
order of what actually converts:

1. **Replied to a sequence** — a human answered. Nothing else comes close.
2. **Inbound with recent activity** — high-intent sources, activity inside a week.
3. **Working and going cold** — roughly 5 to 21 days quiet, not in sequence. Still recoverable.
4. **New and unrouted** — never touched, sitting more than a day or two.
5. **Everything else** — give the count, don't list them.

Cut ruthlessly at the top. Ten prioritized leads with a reason each beats two hundred rows. If the
ranking is thin because the data is thin — no activity dates, no sources — say that plainly rather
than dressing up a weak list as a strong one.

Under `team` scope, break out by owner and flag reps with unworked new leads or untouched replies.
That's what a manager can act on.

### Update

When the user says what happened, update the row, append to the note, adjust `next_step` and
`next_step_date`. Set `sync_status = pending-push` rather than pushing immediately, and mention at
the end that there are unpushed changes.

Disqualifying needs a reason from the org's list. If the user's reason doesn't fit one, ask — a
registry full of "Other" teaches nothing about why leads die.

Distinguish *not a good fit* from *not interested* every time. The first is a targeting problem
worth telling demand gen about; the second is timing or message. If you notice a run of poor-fit
disqualifications from one source, say so. That's a pattern nobody finds by reading rows.

### Convert

When a lead becomes real: create the opportunity row in `07-Opportunities/opportunities.csv`, carry
across account, source, campaign, product interest, and the contact as champion, set the lead's
status to qualified and fill `converted_opp_id`, and link the note.

Do the local conversion first and show it. CRM lead conversion typically creates an Account,
Contact, and Opportunity in one irreversible transaction — that deserves its own deliberate
confirmation, described in those terms, rather than being slipped into a batch of routine updates.

### Raise tasks

Read `01-Tasks/task-rules.csv` and honour it, caps included. Both gates apply — a task that can't
be acted on is worse than no task.

Good lead tasks name the person and the reason: "Reply to Jane Doe (Acme) — answered the sequence
3 days ago" beats "follow up on Acme." Fill `why`, set `verify_by = email-sent` with the address in
`verify_target` so completion can be detected without being told, and set `related_type = lead`
with the ID.

Check for an existing open task on the same lead first. Bump its priority rather than adding a row.

---

## Judgement

The failure mode of lead tracking is volume. It's easy to produce a hundred well-formatted rows and
a dozen tasks, and that output is worse than useless — it teaches the person to stop reading.

Prefer a short answer with reasoning over a long one with coverage. If the honest answer is "three
of these matter and the rest are noise," that's the answer. If the data is too stale to say
anything useful, say so and suggest a refresh rather than ranking noise.

