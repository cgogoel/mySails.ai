---
name: "daily-brief"
description: "Produce the morning brief focused on today's execution — tasks due, the emails and calls owed on specific leads and opportunities, and every meeting today with who is attending, what their role likely wants, background research on the account, relevant competitor and market context, and an offer to build tailored content for the meeting. Enforces the follow-up guarantee where it is enabled — no open deal the user owns goes past the window without an outbound touch — by drafting and staging every follow-up it raises, burning down any backlog at the cap. Reads every email thread since the last brief on the user's deals and leads and catches the records up — notes, a lead moved to engaged — proposes a next step for every deal or lead the user wrote to or heard from, one diff per record, and pauses for the user's edit on any close date, amount, stage or negative sentiment a thread implies. Never calls a staged draft unsent without first searching sent mail for the recipient. Lists every task due and overdue by name, closes the ones email, calendar and CRM activity show are already done, and offers to complete the ones the system can finish itself — waiting for approval before it acts. Also runs a light overnight sweep of the user's newsletter subscriptions and targeted searches for news at tracked accounts. Use when the user asks for their daily brief, morning brief, what's on their plate today, what they should focus on, what they missed, who they need to follow up with, what they missed overnight, what tasks are due or overdue, or asks to prep or start their day. Also use when setting the brief to run each morning."
---

# Daily Brief

The daily brief answers one question: **what do I need to do today, and am I ready for it.**

It is not a status report. Trends, aggregate market movement and competitor positioning belong in
the weekly; pipeline against quota belongs in the forecast. Everything here should be actionable
before this evening, and the test is whether someone could work the whole day from it.

The one piece of market content that does belong is the overnight sweep in Step 6 — news that names
an account someone here is actually working, tight enough to act on today. That is a different
thing from the weekly's market section, and most of Step 6 is rules for keeping it from becoming
one.

The bar: after reading, they know what to do first, and they walk into every meeting prepared.

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`. Then resolve the
   scripts, and **stop if that fails**:

   ```bash
   S=$(python3 "<project>/.sales-system/find_scripts.py") || exit 1
   ```

   Every command below runs as `python3 "$S/<script>.py"`. Do not interpolate
   `$CLAUDE_PLUGIN_ROOT` directly: it is empty in some sandboxes, and an empty variable does not
   fail loudly — the path collapses to `/`, python exits 2, and the skill carries on to produce
   normal-looking output that never ran the registry repair or the drift check it claims to have
   run. **A non-zero exit here is a full stop**: say so in plain terms and produce nothing. A
   brief or forecast built without registry repair and drift verification is a different artifact
   and must not be presented as the same one. A folder with no `find_scripts.py` predates this
   release — run `update-system`.
2. Read `$S/../CONVENTIONS.md`.
3. Read `00-Config/config.md` — `scope`, `default_automation`, and **`brief_content`**, which
   records what this user wants in daily versus weekly. Honour it; the split below is the default,
   not a rule. Also `followup_baseline` / `followup_backlog_at_enable` and their lead twins
   `lead_followup_baseline` / `lead_followup_backlog_at_enable`, which Step 3 needs where the
   *Follow-up guarantee* and *Lead contact guarantee* rules are enabled.
4. Read `00-Config/connections.md` so you don't retry tools that aren't there.
5. Read `.sales-system/crm-profile/field-map.json` for activity query bounds and noise filters.
6. Read `01-Tasks/task-rules.csv` — it decides what may be offered for completion in Step 5 and
   what may not. A missing rules file is not permission: with no rules, nothing is offered as
   `auto` and the queue holds only drafts already sitting at `Awaiting Approval`.
7. Read `03-Market/watchlist` for the Step 6 sweep — which newsletters are sources, and which
   terms are worth a search. No watchlist means no sweep, not a free-range news scan.
8. Repair the registries:

```bash
python3 "$S/csvguard.py" --check-all <project>
```

9. **Check whether anything moved in the CRM overnight** — for `opportunities` and `leads`:

```bash
python3 "$S/csvguard.py" --sync-query <project> --registry opportunities
# run that query through the CRM connector, write the result to snapshot.json
python3 "$S/csvguard.py" --verify-sync <project> \
    --registry opportunities --crm-json snapshot.json
```

Anything it reports goes at the top of the brief, with the automatic actions. Out-of-band
CRM changes are news: a deal reassigned, a stage moved by someone else, a close date pulled
in. They're also the changes least likely to reach the user any other way, which is the whole
argument for putting them in a brief rather than waiting for them to be noticed.

Keep it proportionate. Two drifted rows is a line; forty is the headline. If the check can't
run, don't stall the brief — note it in one line and carry on.

10. **Read the mail, all of it, then refresh the touch dates** the follow-up rules read. This
    runs on every brief, scheduled or not, and it is not a question for the user or a step to skip
    because the cache looks current. The read is **exhaustive over the window, both directions**:

    - **Inbox and sent, whole window.** Two queries against the connected mailbox — everything
      received and everything sent since the last brief (capped at seven days; 90 days when the
      cache cannot be trusted, below). Page through **every** result until the connector reports
      no more; a first page is not the window. Where the connector searches by query, that is
      `in:inbox after:<since>` and `in:sent after:<since>` (or the equivalent), not a search per
      account, per deal, or per contact — a targeted search finds only what you already knew to
      look for, and the first live mornings missed sent follow-ups and replies on threads whose
      subject named nothing tracked for exactly that reason. Include threads that look
      irrelevant; attribution is the ingest's job, not the fetch's.
    - **Every message becomes an event.** Hand the whole set to `--ingest` as one `gmail`-source
      file — date, from, to, subject, counterpart address, account hint where the domain gives
      one. Direction is derived by the script from the user's address, so sent and received must
      both be present or the outbound clocks stay blank. Then calendar and CRM activity per
      `CONVENTIONS.md` §7a, then the lead dates:

```bash
python3 "$S/activity_sync.py" --ingest <project> --input events.json
python3 "$S/activity_sync.py" --lead-touch <project>
```

    - **Say what was read.** One line: "read 212 inbox and 87 sent messages since Tue 2 Sep; 41
      attributed to 19 deals and 6 leads, 258 unmatched." A brief that read nothing must say it
      read nothing and why — connector missing, query refused — never imply the clocks were
      refreshed. Zero sent messages over a window in which the user was working is a signal the
      sent query failed, not that they sent nothing; say so.

    **Check `--status` first, and force a full window when the cache cannot be trusted.** Run
    `activity_sync.py --status <project> --json`; if `needs_full_window` is true, or most of the
    owned book has no events at all, ingest **90 days** from every connected
    source — mail, calendar, CRM activity — rather than the incremental window, then run
    `--lead-touch`. This is not optional and not a question for the user: an empty cache makes
    every deal and lead read as never touched, and a brief that responds by drafting nothing has
    failed silently in exactly the way the follow-up rules exist to prevent. Say in one line that
    the full ingest ran and how many events it found.

    The same read feeds three later steps, so it is done once here and reused: Step 1's
    sent-mail check on staged drafts (the per-address search there confirms against the mailbox;
    the sent set read here is what makes a miss visible), Step 1a's thread reads, and Step 3's
    replies-owed list. None of those may substitute their own narrower search for this read.

Briefs are written to `09-Briefs/Daily/YYYY-MM-DD-daily-brief.md`.

---

## Step 1: Close what's already done

Before showing anyone their list, sweep for evidence that items are finished. A brief that nags
about completed work gets ignored within a week, and then so does everything in it.

Check all three sources per `CONVENTIONS.md` — email for what they sent, calendar for what
happened, **CRM activity for what colleagues did**. That third one is the only source that shows
someone else's work: a call another rep logged, a next step a manager updated.

Bound every activity query per the profile, and filter auto-captured noise. Where the CRM records
who made a change, say so — "Dana updated the next step on Acme yesterday" is often the most useful
line in the brief.

**Every staged draft gets checked against sent mail before it is called unsent.** For each task
at `Awaiting Approval` with a `draft_path`, search the user's sent mail by the draft's recipient
address, from the task's `created_date` forward, and read the thread. People send from their mail
client without coming back to the queue, and a brief that then re-offers the draft — or, worse,
counts the deal as still untouched — has contradicted the one thing the user knows they did. A
sent message to that address on or after the draft date closes the task: `status = Done`,
`completed_how = user-sent`, `completion_evidence` carrying the recipient, subject and sent
time; it is an outbound touch for Step 3's clocks; and it earns a line under *Did automatically*
("you sent the Acme follow-up yourself on the 3rd — closed it"). No match means the draft is
still waiting and may be offered. A search that could not run — connector down, address missing
from the draft — is neither: say so beside the item, and offer it marked *unverified* rather than
asserting it is unsent.

Be conservative, and give ambiguity somewhere to go. Evidence strong enough to be sure closes the
task silently and earns one line in the summary. Evidence that is suggestive but not conclusive — a
sent email to the right domain but the wrong person, a meeting that happened under a different
title — does **not** close the task, and does not evaporate either: it goes to the approval queue in
Step 5 as a *looks done, confirm?* item with the evidence and its date named. A false close hides
real work; a task left silently open because the evidence was only 80% is how the list fills with
rows the user finished last week.

---

## Step 1a: What yesterday's email changed on the records

Step 10 of the setup ingested the email traffic since the last brief. Step 1 used it to close
tasks. This step uses it for what a rep would otherwise type in by hand at the end of the day and
usually does not: **the record catches up with the conversation.** Every open opportunity and
every lead the user owns that had email traffic in the window gets read — the thread, not just
the event — and updated, on two tiers that differ in exactly one way: whether the write waits — plus one
proposal that is made for every touched record, whether or not the thread says anything about it:
the next step.

The window is *since the last daily brief*, capped at seven days, not "yesterday": a brief that
was skipped on Tuesday must not lose Monday's traffic. Bound the mail query per the profile and
drop the auto-captured noise, auto-replies and bounces the same way Step 1 does.

**What to extract from each thread**, the way `meeting-notes` extracts from a transcript: the
current state in one or two sentences; a next step and its date where the thread states one;
commitments in either direction; any close date, amount, or stage the thread implies; competitor
mentions; and a sentiment reading, evidence-gated — `Negative` only with the line that supports
it, `Neutral` or `Unclear` when that is the truth. A thread that changes nothing produces nothing.

### Tier 1 — applied, then reported

Writes that catch the record up without deciding anything the person would want to decide:

- **Notes.** Append a dated entry to the deal's notes file (`07-Opportunities/Accounts/<Account>/
  OPP-nnnn-notes.md`) or the lead's, with the thread's subject and the one-line state. Append,
  never rewrite — the notes file is a log.
- **On a lead**: status to the org's *engaged* value when the person replied and the lead sits in
  *new* or *working*; `last_inbound_date` is already written by `--lead-touch`.
- **Commitments** into `13-Meetings/commitments` where that module is on, either direction, with
  the source set to the thread.
- **Competitor mentions** routed to `competitor-tracking` as it already expects them.

All of these are folder writes with `sync_status = pending-push`. **Nothing here reaches the CRM
on its own**: the brief offers "push *N* record updates to the CRM" as **one** numbered item in the
Step 5 queue, and §7 governs the push — field-by-field diff, explicit yes. Everything Tier 1 did is
listed under *Did automatically* at the top of the brief, per deal, one line each, so the user
never learns about a changed record by finding it.

`next_step` is not on this list. It used to be — applied where the thread stated one plainly —
and the first live morning showed why that is the wrong tier: a record that was written to or
replied to has a different next step than it had yesterday whether or not anyone wrote it down,
and the ones nobody wrote down are exactly the ones that go stale. It is proposed instead, every
time, below.

### The next step — proposed for every touched record, one diff each

**Every outbound the user sent and every customer reply since the last brief produces a proposed
`next_step` in the Step 5 queue, one diff per record.** Not "where the thread states one" — every
record with traffic. The step is what changed when the mail went out or came back, and it is the
field the forecast prints verbatim, so a stale one is a visible error and a blank one is worse.

Build the proposal from the thread the way a rep would after reading it: where the thread states
a step in words ("send the revised SOW by Friday"), propose that, with its date; where it does not,
propose the step that follows from what was said — a reply owed, a meeting to book, a document
promised — and say it is inferred, not quoted. The item shows the record's current `next_step` and
`next_step_date` against the proposed pair and the line from the thread that led to it. The user
approves as proposed, edits, or declines in the prompt; until then the record holds its current value.

Three things that do not exempt a record, because each one already caused a missed proposal:

- **It was pushed to the CRM earlier.** A push — yesterday's, this morning's, one from another
  skill — says the record was written, not that its next step still stands. A record that had
  traffic in the window gets a diff whether or not `sync_status` says `synced`.
- **A Tier 1 write or an earlier proposal already touched it.** A next step approved from
  Tuesday's thread does not survive Wednesday's reply. New traffic, new diff.
- **The current value looks fine.** If the proposal is the same as the current value, the diff
  says so in one line and asks nothing — but it still appears, so the user can see the record was
  read. What must never happen is the record being silently skipped on the system's own judgement
  that nothing changed.

One diff per record, not per thread: several threads on the same deal fold into one proposal
carrying the latest state. A declined proposal is noted in the notes file as "next step proposed
from email, declined" so the same traffic does not re-propose it; the next outbound or reply
re-opens it, since it is new evidence.

### Tier 2 — paused for the user's edit

Four things a thread can imply that the system must not apply on its own reading, because each
one moves the forecast or a relationship and each is easy to misread from prose:

| Signal | Why it waits |
|---|---|
| **Close date** | "We'll pick this up next quarter" is a slip, a pause, or a polite no, and only the person knows which |
| **Amount** | "We're thinking 150 seats now, not 250" changes the number the forecast runs on; the quote may not agree |
| **Stage** | The third forecast input. A backward move triggers an approval flow in some orgs |
| **Negative sentiment** | Evidence-gated: the quote is required. What to *do* about it is the rep's call |

Each becomes an **edit before applying** item in the Step 5 queue, showing the record's current
value against the proposed one, the line from the thread that implies it, and the thread date.
The user approves as proposed, edits the value, or declines — in the prompt. Until they do, the record
holds its current value and the item holds the proposal; a proposal never expires silently, it
re-appears tomorrow marked *still waiting*. A declined proposal is recorded in the notes file as
"proposed from email, declined", so the same thread does not propose it again.

Negative sentiment carries no field of its own on the deal row; the item offers what follows from
it — a `health` change, a risk flag, a task — with the quote, and the user picks.

### The rule that governs it

*Update records from email* in `task-rules`, `auto` for Tier 1, and it is the one place `auto` is
the shipped default, because Tier 1 writes only to the folder and every write is a dated append
or a field the thread states in words. It respects the ordinary fences: nothing under `team`
scope on a colleague's record unless asked (their traffic is reported, not written); nothing on a
record whose thread is with someone `contactable = no`. Flip it to `review` and every Tier 1
write joins the queue instead; flip it to `manual` and the step only reports. Tier 2 is not
configurable downward — it is `review` by construction.

The matching of a thread to a record is the ingest's attribution — deal by account, lead by the
person's address — and where a thread matches nothing it is not updated and not invented. Say
how many threads went unmatched; a large number is the account-name mismatch the ingest warns
about, and it is fixable.

---

## Step 2: Today's meetings, with real preparation

This is the heart of the brief and where most of the effort belongs. For each meeting today:

**Who's attending.** Pull from the invite, then enrich. For each external attendee: name, title, and
— this is the useful part — **what someone in that role is typically measured on**, so the user can
aim at it. A CISO is judged on risk reduction and audit outcomes; a DevOps lead on pipeline velocity
and not being the bottleneck; a procurement lead on terms and precedent. Say what they likely want
from this meeting, not just who they are.

Flag anyone new to the deal. A first-time attendee usually means either the deal is widening — good
— or the champion has brought a sceptic. Either way the user should know before walking in.

**Where the deal stands.** From `07-Opportunities/`: stage, amount, close date, last real contact,
close-plan gaps, engagement trend. Two or three sentences, not a data dump. If the deal has slipped
twice or is single-threaded, that belongs here.

**What happened last time.** If the Meeting Notes module is on, pull the account's most recent
note from `13-Meetings/` — the summary, the outcome, the sentiment with its evidence, and the
agreed agenda for this meeting — and
**open commitments in both directions** from the commitments registry. Lead with anything we
promised and haven't done: walking in unaware of your own unmet commitment is the avoidable version
of a bad meeting. A customer commitment now overdue is worth a line too — this meeting is the
natural moment to chase it without it reading as a chase. Sequence beats snapshot: "last time they
raised SSO as blocking; here's where that stands" is preparation.

**What's changed at their end.** Check `03-Market/signals` for anything about this account or its
industry, and check whether their org has shifted — a new CIO at a target account changes the whole
conversation. Recent funding, a breach, a regulatory deadline: all worth thirty seconds of the
user's attention beforehand.

**Competitive context.** If the deal names a competitor, pull the battlecard's key moves and —
importantly — anything in `signals_since_battlecard`. Walking in with a win theme that a competitor
neutralised last week is worse than walking in with none.

**Research the gaps.** Where the folder is thin, look it up: recent company news, the attendee's
background, what the account has published. Don't invent; if you can't find it, say the meeting is
under-researched and what you'd want to know.

**Offer tailored content.** When a meeting would benefit from something specific — a deck for this
audience, a one-pager answering the question they asked last time, a comparison against the
competitor in the deal — say so concretely and offer to build it via content tailoring. Name the
asset and why, rather than asking a generic "want materials?". Flag it early enough in the brief
that there's time to make it.

---

## Step 3: Follow-ups owed

Specific people, specific reasons. This section is a worklist, not a category.

**Replies owed.** Emails from leads or customers waiting on a response, oldest first. Age is the
whole point — "3 days" makes it real in a way "pending" doesn't.

**Leads who replied to a sequence.** Someone answered an automated cadence and is waiting on a
human. Highest-value state in the lead registry; surface it above everything else in this section.

**Deals gone quiet.** From `07-Opportunities/`, where the last **outbound touch from us** is past
the window in the *Deal gone quiet* rule (14 days in the starter rules) or the next step date has
passed. Say what to send, not just that contact is due. The touch is measured the way
`opportunity-tracking` measures it — from `opportunity-contacts.last_outbound_date`, the activity
cache, and a CRM activity table that is actually populated — never from `last_activity_date`,
which carries import stamps and goes stale the moment the CRM stops logging. Two rules from
`opportunity-tracking` apply before naming a deal: **a record with no recorded touch is overdue,
not excluded** — if the cache is empty or thin, run the full-window ingest first (Step 10), then
treat what is still blank as untouched beyond the window and put it in the list marked *no
recorded touch*; and if the rule matches more than a third of the book even after the ingest,
say in one line that the signal may be broken, then list at the cap anyway. Where `11-Partners/`
exists, look for traffic with the partner's domain before calling a partner-worked deal quiet.
`on_hold = yes` exempts a deal. This rule is discretionary — rank by value and stage, take the
top `daily_cap`, and say how many more there were.

**The follow-up guarantee.** Where `task-rules` holds an enabled *Follow-up guarantee* rule — *no
open opportunity the user owns goes without an outbound touch for longer than the window* — the
brief evaluates it separately from the discretionary list above, because a breach here is a system
failure rather than a ranking decision. It runs on the same outbound-touch signal, the same
forced-ingest-then-list rule, the same partner check and the same `on_hold` exemption. **It ships
enabled**, and it never waits for configuration: a missing key is stamped, not a reason to skip.
What differs:

- **No recorded touch means overdue.** A deal with no outbound touch in the cache after the
  full-window ingest is past the window by definition and enters the burn-down like any other
  breach, marked *no recorded touch* so the user can see which are genuinely cold and which may
  be data. Nothing is held back as "unbaselined": the cap is what keeps the first week sane, and
  a record that was never written to is exactly what the floor exists to catch.
- **Backlog, recomputed every run.** Where the book already breaches the floor, run a burn-down at
  the cap, not a flood: oldest and largest first, at `daily_cap` and never above it, and report
  progress as a fraction of the original — "12 of 46 cleared" — so the end is visible. The
  original is `followup_backlog_at_enable:` in `00-Config/config.md`, with `followup_baseline:`
  beside it as the date; **if either is missing, the brief writes both on this run** from the
  count it just made and says so in one line. Never store the running count; it drifts the moment
  a deal closes, goes on hold, or is answered outside the system.
- **Draft and stage every one raised.** Under `review`, each follow-up the floor raises gets a
  draft in `01-Tasks/Drafts/`, `draft_path` set, `status = Awaiting Approval`, and a line in the
  Step 5 queue. A brief that says "five deals need a follow-up" has moved the work to the person;
  a brief that stages five drafts has done the expensive part — the blank page — and left the
  cheap part, the send, where it belongs.

The fences do not move under volume. A floor creates pressure to relax them, and the pressure is
strongest exactly when the backlog is largest. The answer is the same each time: first contact is
drafted and handed over, never staged as ready to run; a deal with no contactable person is
reported as a gap in its own line, not skipped — silence caused by having nobody to write to is a
data problem and must read as one; nothing commercial is staged; and other reps' relationships
under `team` scope are named, not written to. Clearing a backlog by flooding produces a book that
has been mailed, not worked.

**Leads going cold, and the lead contact guarantee.** The same two-rule shape, on `06-Leads/`,
reading `last_outbound_date` — the clock `lead-tracking` describes, never `last_activity_date`.
*Lead going cold* (14 days, discretionary) and *Lead contact guarantee* (30 days, a floor, shipped
enabled, stamping `lead_followup_baseline:` and `lead_followup_backlog_at_enable:` in `config.md`
on its first run exactly as the deal floor stamps its own pair) share **one budget of 10 lead
drafts a day, floor first** — separate from the deal budget. Skip a lead whose clock is paused:
in an active sequence, passed to a partner, or `hold_until` in the future. **A lead with a blank
`last_outbound_date` is overdue, not excluded** — but blank across the whole book means the touch
dates have never been written, so Step 10's forced full-window ingest and `--lead-touch` must have
run this morning before the list is built; after that, what is still blank is genuinely
untouched and goes in the list marked *no recorded touch*. If more than a third of the owned lead
book still matches, say the signal may be off in one line and list at the cap regardless. Nearly
every lead follow-up is first contact: draft it, set `Awaiting Approval`, and keep it out of the
ready-to-run queue.

Two things the lead sweep offers in Step 5 rather than doing: **disqualify** where an opt-out flag
flipped `contactable` to no or a reply reads as *not interested* — quote the reply, name the
reason it would set — and **hold** where a reply implies a wait ("circle back after Q1", an
out-of-office with a return date) — quote the line, propose `hold_until` and `hold_reason`. Both
are the user's call in the prompt; inference never writes on its own.

**Renewal conversations due or overdue.** From `08-Renewals/`, using the org's conversation lead
time. Name the number of days.

Both lead gates apply throughout: check `contactable`, and never suggest outreach to someone in an
active sequence — that produces two messages from two systems in one week.

Under `review` automation, **draft the emails rather than only naming them.** Write to
`01-Tasks/Drafts/`, set `draft_path` and `status = Awaiting Approval`, and say in one line how many
are waiting. A morning's drafts reviewable in one folder is most of the value of the whole system.

Before drafting for a deal or lead, and before counting an existing draft as still waiting, apply
Step 1's sent-mail check: search sent mail by the recipient's address and read the thread. A
draft the user already sent from their mail client is a touch, not a gap — it resets the clock,
closes the task, and must not be re-drafted or re-offered. The activity ingest usually catches the
same send, but the check is per draft and per address, and it runs whether or not the cache did.

---

## Step 4: Tasks due and overdue — listed, not counted

From `01-Tasks/tasks`, honouring `01-Tasks/task-rules.csv`. **Every task due today or overdue gets
its own line.** "You have seven tasks due" is not a task list, it is a number — and the user now has
to open a spreadsheet to find out what it means, which is the one thing this brief exists to save
them.

Overdue first, oldest first, then today's. One line each, every field on it taken from the row:

> **TASK-00042** · Send pricing follow-up to Jane Doe (Acme Corp) — **4 days overdue** · High
> *They asked for tiered pricing on the 18th and haven't been answered.*

Carry the id, the title, the account, the age, the priority and the `why`. Not the whole row. The
`why` is the field that makes someone act, and it is also the one most often left blank by whatever
raised the task — a blank one is worth noticing out loud rather than printing an empty line under.

Three things stay out of this list, each deliberately:

- **Snoozed**, where `snooze_until` is still in the future. That is what snoozing is for, and
  re-showing it teaches people that snooze does nothing.
- **Blocked** — out of the main list and into one line of its own carrying `blocked_reason`. A
  blocked task nobody revisits never happens; naming the blocker is the only thing that moves it.
- **Awaiting Approval** — those are Step 5's. Printing them twice makes the day look longer than it
  is.

And two things to say rather than let the list imply:

- **Long lists.** Past about fifteen items, ranking them is the useful act. Say how many there are,
  show the ones that matter, offer the rest — but never quietly truncate. A list that silently stops
  at ten teaches the user the brief is lossy, and after that they open the spreadsheet anyway.
- **Deep overdue.** A task three weeks past its date is not late, it is a decision nobody has made.
  Say so and offer the two honest options: a real new date, or cancel it. Rolling it forward one more
  day is how a task list turns into wallpaper.

Note anything Step 1 auto-closed in one line — "closed 2 tasks I could see you'd already done."

Anything the system did automatically since the last brief goes at the **top of the brief**, not
here. Per `CONVENTIONS.md`, the user should never learn about a sent email from the recipient.

---

## Step 5: Offer to complete what can be completed

Some of what is on that list, the system can simply do. The distance between a brief that reports
work and one that removes it is this section — and **nothing in it happens without the user saying
yes.**

### What qualifies

Two kinds of candidate, presented as one queue because the user's decision has the same shape for
both: yes or no, item by item.

| Kind | Looks like | What a yes means |
|---|---|---|
| **Ready to run** | A drafted email at `draft_path` sitting at `Awaiting Approval`; a `CRM Update` task where the field and the new value are both already known; logging an activity; filing a note | The system performs the action, then closes the task |
| **Looks done** | Step 1 found evidence that was suggestive but not conclusive | The system closes the task and records the evidence. It performs nothing |
| **Edit before applying** | Step 1a proposed a next step for a touched record, or read a close date, amount, stage or negative sentiment in a thread | The system writes the value the user confirmed or edited, locally, `pending-push` |
| **Push to CRM** | Tier 1 writes waiting as `pending-push` | One item for the batch; §7's field-by-field diff runs before anything is sent |

A draft enters the queue only after Step 1's sent-mail check by recipient address came back
empty. A draft found sent is closed and reported, never offered; one the check could not verify is
offered with *unverified* beside it and the reason.

Something is **ready to run** only when the action is fully determined — recipient, text, field and
value all either exist already or follow from the record without a judgement call. If producing the
action means deciding what to say, it is not a completion candidate. It is a drafting job, and it
belongs in Step 3, where it gets drafted and waits.

### What never enters the queue

These stay in the ordinary task list and stay the user's to do. The fences are `CONVENTIONS.md` §3b
and they are not re-decided per run:

- **First contact.** Any first email to a person, and all cold outreach. A bad first impression
  cannot be retracted.
- **Commercial substance.** Pricing, terms, discounts, commitments, dates a customer could hold
  someone to. The user's send, whatever the rule says.
- **A contact who should not be contacted** — `contactable` is no, or they are in an active
  sequence. Two messages from two systems in one week is exactly what that check exists to stop.
- **Anything a rule marks `manual`**, or whose rule is `enabled = no`, or that would breach the
  rule's `daily_cap`. A rule wanting to fire twenty times means something upstream is wrong — say
  that, rather than presenting twenty approvals.
- **Someone else's record** under `team` scope, unless the user asks for it. Then name whose it is
  in the offer and again in `notes`.

Where something is excluded, say so in a clause where it appears in the task list — "first email to
this person, so yours to send" — rather than dropping it without explanation. A user who cannot tell
why one task got an offer and another didn't stops trusting both.

Downgrading is silent and fine; upgrading never is. A task marked `auto` that meets any fence above
becomes `review`, with the reason in `notes`.

### How to ask

Two forms, and the difference is the surface the user is on. The written brief carries a
numbered block so the file is a complete record of what was offered; the decision itself is
taken **through prompts**, not by typing numbers back.

**In the file.** One numbered block after the task list, near the end where a decision belongs.
Each entry says in concrete terms what will happen — not "send the follow-up" but who it goes to,
what the subject line is, and where the draft can be read before deciding:

> **Ready when you are**
>
> 1. **TASK-00042** — send the pricing follow-up to jane@acme.com, subject "Tiered pricing, as
>    promised". Draft: `01-Tasks/Drafts/TASK-00042-followup-acme.md`
> 2. **TASK-00051** — set Next Step on Northwind to "Security review, 9 Sept" in the CRM (it is
>    currently blank)
> 3. **OPP-0031 Acme** — next step: current *"Send pricing"* (28 Aug) → proposed *"Book the
>    security review Priya asked for"* by 11 Sept, from her reply of the 3rd
> 4. **TASK-00038** — looks done: you emailed rob@northwind.com on the 24th, two days after this was
>    raised
>
> Not offered: **TASK-00047** (first email to a new contact) and **TASK-00055** (discount approval) —
> both yours to send.

A draft already described under follow-ups appears here as a number and a one-line action, not a
second retelling. The queue is the decision; the sections above are the context for it. Say a
thing once and the brief stays the length of the day.

**In the session.** When the user is present and the host offers a structured question prompt
(in Cowork and Claude Code that is the `AskUserQuestion` tool — a card with selectable options
and a free-text *Other*), the brief asks through it, immediately after the brief is written, and
performs nothing until the answers come back. Nobody should have to read a list, hold the numbers
in their head, and type "1, 3 and 4" — that is a form pretending to be a conversation. The
prompt is the form.

How the prompts are built:

- **One question per item, a short header naming the record.** Every question carries the same
  concrete sentence as the file entry — recipient, subject, current → proposed — because the card
  is what the user reads, not the file. The first option is the recommended action and is
  marked so.
- **Options by kind.** *Ready to run*: **Send as drafted** / **Edit first** / **Skip today**.
  *Looks done*: **Close it** / **Leave open**. *Edit before applying* (a next step, close date,
  amount, stage or sentiment): **Apply as proposed** / **Decline** — with the proposed value quoted
  in the option text so approving it is a read, not a recall; an edited value comes in through
  *Other*. *Push to CRM*: one question, **Push all N** / **Show me the diff first** / **Not now**.
  Every question also has *Other* by construction — that is where "send it, but drop the second
  paragraph" and "make the next step 15 Sept, not the 11th" arrive, and any text there is a
  customisation of that item, applied before the action runs and echoed back in the result line.
- **Batches of four, ordered by consequence.** The tool takes four questions per call; the queue
  goes out in rounds of four — ready-to-run first, then looks-done, then edit-before-applying,
  then the push — and each round says where it is: "4 of 11; 7 more after this." Never more than
  four rounds without pausing to run what has been approved so far, so a long queue does not
  become a wall of unanswered cards.
- **No "run all" as a first question.** A single yes covering a dozen sends is the number-typing
  problem in a different coat, and the fences are enforced per item. Where the queue holds more
  than eight ready-to-run drafts, the first question may ask **Go through them one by one** /
  **Send every draft as written** — and the second option, if chosen, still runs only the items
  that passed the fences, still lists each one in the result, and is never offered to a queue
  containing anything under `team` scope or anything the draft check left *unverified*.
- **Edit first opens the draft in the conversation** — the subject and body, not the path — and
  takes the change as free text; the revised draft is written back to `draft_path`, and the
  send is asked again as its own question. An edit never runs on the same answer that requested
  it.

Where there is **no structured prompt** — a plain chat surface, a headless run, a host without the
tool — fall back to the numbered block and take the reply by number, read literally: "1 and 3" is
two items, not the first three, and an ambiguous reply is asked about rather than resolved
generously.

Handling the answers, in either form:

- **Only an answered item moves.** A dismissed card, an unanswered round, a reply about something
  else — every item not explicitly chosen stays where it was, `Awaiting Approval`, and appears
  again tomorrow marked *still waiting*.
- **A scheduled or unattended run asks nothing and executes nothing.** Build the queue, write the
  numbered block into the brief, leave the tasks at `Awaiting Approval`, say how many are waiting
  and that they will be asked when the user next opens the session. Approving on someone's behalf
  because they were not there to answer is the precise failure this whole model exists to prevent.
  A run that cannot tell whether someone is present treats itself as unattended.
- **Skip is a decision, decline is a record.** *Skip today* leaves the item to re-appear tomorrow;
  *Decline* on an edit-before-applying item writes "proposed from email, declined" to the notes
  file so the same evidence does not propose it again.

### After running

One line per item on what actually happened, then write it down. On success: `status = Done`,
`completed_date`, `completed_how = user-approved`, and `completion_evidence` carrying real proof —
"email to jane@acme.com sent 2026-08-26 09:12", not "completed via brief".

On failure — connector down, CRM refused the write, draft gone — name the item and the reason and
**leave the task open**. Closing a task on an attempt is worse than never having offered, because it
converts a job that still needs doing into a row claiming it is done.

Approved but not yet executed is `Awaiting Approval`, not `Done`. Where a send can be scheduled with
a short delay instead of fired instantly, prefer that: a few minutes is a cheap window in which to
catch a mistake.

---

## Step 6: The overnight sweep — what you may have missed

A light pass, run last and kept short: newsletters that landed since the previous brief, plus a
small number of targeted searches. The Market Tracking module owns the watchlist, the signal
registry, and the rules for both — **this step is a consumer of that module, not a second copy of
it.** Everything kept here is logged there as a signal, through the guard, with
`source_type = Newsletter` (and `newsletter_name`) or `Web Search`.

If there is no watchlist, do not invent one. Say the sweep has no sources configured, point at
`market-tracking`, and do the one thing still worth doing without it: a search on each account with a
meeting today.

### Newsletters

Sweep the enabled `03-Market/watchlist` rows whose `kind` is `Newsletter` or `Feed`, matching on the
sender address or URL in `sources`, across messages that arrived since the last brief. Read them
**against the watchlist**, not for general interest.

Two mechanics from `market-tracking` matter more here than anywhere else, because a daily cadence
collides with a weekly publication schedule:

- **Date the event, not the issue.** Newsletters report things days after they happen, and a signal
  dated on the send date sorts wrongly forever after.
- **Deduplicate hard.** The same funding round arrives from three sources across four days. If it is
  already in `03-Market/signals` it is not news and it gets no line — including when this is the
  first time you personally saw it.

### Searches

Bounded, and chosen rather than swept. Search:

- each account with a meeting today — though what turns up belongs in that meeting's prep in Step 2,
  not down here;
- the few deals where a change would actually move something: the largest live opportunities closing
  this quarter, and renewals inside the conversation window;
- watchlist rows with `cadence = Daily`.

That is a budget, not a starting point. If the list of things worth searching is longer than the
budget, say which you picked and leave the rest to the weekly.

### The bar

An item survives if it does one of two things:

1. **Names something tracked** — an account, prospect, opportunity, renewal, customer or competitor.
   Fuzzy-match on name and domain; CRM account names and press coverage rarely spell things the same
   way.
2. **Matches an enabled watchlist row** whose `lens` is `deal` or `both`, *and* carries a concrete
   `so_what` naming what changes.

A watched theme with nothing to do about it is dropped without comment. `lens = content` rows are not
the daily's business — standing and thought leadership belong to `demand-gen` and the weekly.

Each surviving line reads: what happened, what it changes, for whom. Three sentences at most, and the
middle one is the only one earning its space.

> **Acme discloses a mobile data-exposure incident** (reported, *Risk Weekly*, event 24 Aug) — their
> security team now has board attention and a deadline. The evaluation that stalled in May is live
> again, and Priya is the way back in. → OPP-0031

### Size, and the honest empty case

Aim at five lines. Eight is the ceiling. **Print nothing at all on a quiet morning** — "nothing
overnight worth your attention" is a real result, and it is what makes the section believable on the
day it does have something.

If it produces eight items a day for a week, the bar is too low or the watchlist too broad. Say so
and offer to tighten it. Quietly carrying on is how a decision aid becomes a digest.

Raise a task off a signal only where `relevance = High` and there is a specific person to contact,
and count it against the day's caps like any other. Two signals becoming two tasks is this step
working. Ten is it competing with the rest of the brief.

---

## Writing it

Structure, skipping empty sections rather than printing "None":

**Did automatically** — only if something did. Always first. Includes every Tier 1 record update
from Step 1a, one line per deal or lead: what changed, from which thread; and every staged draft
Step 1 found already sent and closed.

**Today** — meetings in order, each with the preparation from Step 2. Long is acceptable here;
this is what the brief is for.

**Before your first meeting** — the two or three things where waiting costs something.

**Follow-ups owed** — ranked by age and value, with drafts noted.

**Tasks** — every item due or overdue, by name, oldest first, plus what was auto-closed. Blocked
items on a line of their own.

**Ready when you are** — the numbered approval queue, as the record; the asking happens through
prompts in the session. Omitted entirely when there is nothing to approve.

**Worth knowing** — the overnight sweep. Five lines at most, and omitted when the morning is quiet.

Under `team` scope, keep the focus on the user's own day but flag where a colleague's account needs
them — an unowned meeting, a rep out today with a deal needing cover.

### Voice

Write like a good chief of staff. Name people and accounts. Give numbers a shape: "3 days,"
"$120K," "pushed twice." Say the action, not just the fact. No preamble, no restating the date.

Don't manufacture urgency. "Quiet morning — one meeting, nothing overdue" is a legitimate brief and
builds more trust than three invented priorities.

---

## Scheduling

Offer to run it on weekday mornings, early enough to act on. A brief that has to be remembered
about is a brief nobody reads.

The sweep in Step 6 narrows the window: late enough that the morning's newsletters have landed,
early enough to still change the day. For most people that is a specific half hour rather than a
guess — ask rather than assume. A scheduled run builds the approval queue and executes none of it;
when the user next opens the session and asks for the queue — or asks for the brief again — the
items still at `Awaiting Approval` are put to them as prompts, not re-derived.

---

## Judgement

Three failure modes.

**Breadth.** Pulling in trends and pipeline analysis because they are available. That is the
weekly's job and the forecast's, and including them here means the meeting prep — the part only
this brief does — gets skimmed. Step 6 is the deliberate exception and it is fenced for exactly
this reason: account-linked, actionable today, five lines. The moment it starts carrying industry
trends or competitor positioning it has become the weekly printed daily, and it will be skipped
along with everything under it.

**Shallow prep.** Listing a meeting with the account name and calling it preparation. If the brief
doesn't tell the user something they didn't already know about who they're meeting and what those
people want, it hasn't earned its place in their morning.

**Approval creep.** Offering to complete something the system should not touch. The value of the
queue is that a user can answer each card in a second without re-reading the record, and that
holds only while every item in it deserves a yes. One fenced item slipping through once costs more trust than a hundred
correct offers earn — which is why the fences in Step 5 are checked against the record each time
rather than inferred from how the task was raised.

Where you couldn't research something properly, say so and name what would help. "Two attendees I
couldn't find anything on — worth asking your champion who they are" is more useful than silence.

