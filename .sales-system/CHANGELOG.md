# Support layer changelog

What changed in each release of the generic layer, newest first. `upgrade.py` prints the entries
between a folder's version and the one it's moving to, so someone upgrading finds out what they
gained — and, more importantly, what quietly means something different now.

The format is one `## YYYY-MM-DD` heading per template version, matching `VERSION.json`.

## 2026-09-05

Skills and `CONVENTIONS.md` only — no script or schema changed. Plugin `0.13.0`;
`requires_template` stays at **2026-09-04**. Three rules from the second live morning, all about
the brief deciding on its own that something did not need reading or doing — and one change to
how the approval queue is answered.

**The approval queue is answered through prompts, not by typing numbers.** The brief used to end
with a numbered block and "reply with the numbers you want run, or `all`". Where the host offers
a structured question prompt (the `AskUserQuestion` card in Cowork and Claude Code), the queue
now goes out as cards, one question per item, in rounds of four ordered by consequence: *Send as
drafted / Edit first / Skip today* for a draft, *Close it / Leave open* for a looks-done, *Apply
as proposed / Decline* with the value quoted for a next step, close date, amount, stage or
sentiment, and a single *Push all / Show the diff / Not now* for the CRM push. *Other* on any card
is where an edit arrives — a changed date, a dropped paragraph — and is applied to that item before
it runs. There is no "run all" first question; the one bulk option, offered only past eight
ready-to-run drafts, still runs item by item behind the fences. The numbered block stays in the
brief file as the record, and is the fallback where no prompt exists. Unattended runs ask nothing
and execute nothing, as before; the items are asked when the user next opens the session.

**Every skill asks the same way, and the written form is a setting.** The rule is now
`CONVENTIONS.md` §3b, *How the system asks*, and each skill's own asks are converted to it:
the approval-flow push and the won-deal customer and renewal rows in `opportunity-tracking`;
disqualify, hold, duplicate merge, the push and CRM conversion in `lead-tracking`; the champion,
renewal fields, next step, sentiment, push and activity log in `meeting-notes`; every clarified
term and discount in `quote-generation`; the registration decision in `partner-tracking`; the
renewal opportunity in `renewals-tracking`; the inbox-scan watchlist in `market-tracking`;
angle and type in `demand-gen`; the existing-asset offer in `content-tailoring`; goal
confirmation in `forecast-update`; and the update offer in `update-system`. A new
`approval_style:` key in `config.md` — `prompts` by default, `numbered` to have every skill ask
in prose and take the reply by number — is set in `configure-project` Track 7 and changed with one
line later; a missing key means `prompts`, and the numbered form is also the automatic fallback
on any surface without cards.

**The brief reads the whole inbox and the whole sent folder, every run.** The ingest step said
"ingest the window's email" and left the fetch to the run, and a run that searched mail per
account found only the traffic it already knew to look for — no sent follow-ups, no replies on
threads whose subject named nothing tracked. The fetch is now fixed: two queries, `in:inbox` and
`in:sent` since the last brief (seven-day cap; 90 days when the cache cannot be trusted), paged
to exhaustion, handed to the ingest as one set so direction can be derived for both sides.
Attribution stays the script's job. The brief reports what it read — in, out, attributed,
unmatched — and a run that read nothing, or read no sent mail across a working window, says so
as a failure rather than a quiet morning. Step 1's draft check, Step 1a's thread reads and Step
3's replies-owed list all run on this read and may not substitute a narrower search of their own.

**The next step is proposed for every touched record, one diff each.** In 0.11.0 the brief wrote
`next_step` automatically where a thread stated one plainly and otherwise left it alone, and a
record that had already been pushed to the CRM was treated as handled. So the deals with real
traffic — an outbound sent, a reply received — came through with yesterday's next step or none,
and the queue never mentioned them. Now every outbound the user sent and every customer reply
since the last brief produces a proposed `next_step` diff in the approval queue: current against
proposed, with the thread line behind it; stated where the thread states one, inferred and marked
so where it does not; one diff per record however many threads. Nothing exempts a record with
traffic — not an earlier CRM push, not a Tier 1 write, not a proposal approved yesterday, and not
the system's own view that the current value still looks right (that case prints as a one-line
"unchanged" so the record is visibly read). `next_step` leaves the auto tier for good.

**A staged draft is not unsent until sent mail says so.** A follow-up drafted by the brief and
then sent by the user from their mail client stayed at *Awaiting Approval*, was re-offered the
next morning, and its deal was still counted as untouched. Before the brief calls any staged draft
unsent — re-offers it, re-drafts for the same deal, or lets the follow-up clock run on it — it
searches the user's sent mail by the draft's recipient address from the task's created date and
reads the thread. A match closes the task with the recipient, subject and sent time as evidence,
counts as an outbound touch, and is reported under *Did automatically*. A search that could not
run leaves the item offered but marked *unverified*, never asserted unsent.

## 2026-09-04

Plugin `0.12.0`. `activity_sync.py` changed, so **`requires_template` moves to 2026-09-04**; run
`upgrade.py --apply`. Two defects from the first live morning with the follow-up rules, both of
the silent kind.

**The activity cache now lives in the folder.** It was kept in the machine's temp directory — a
shared-drive precaution — and in a sandbox whose temp directory is created per session and
discarded after it, every scheduled brief started from an empty cache, read every deal and lead
as never touched, and drafted nothing. It is now `.sales-system/cache/`, which persists; a cache
left in temp by an older version is migrated in on first use. Two users ingesting into one cache
is safe because ingest merges and dedups by event identity. `--status --json` reports
`needs_full_window`, the one bit the brief must act on.

**The follow-up floors ship enabled, and no follow-up rule may go silent.** *Follow-up guarantee*
and *Lead contact guarantee* were `enabled = no` with a four-step enable; that was the wrong
default, because a fresh folder's first week is exactly when the floor earns its keep and the
daily cap already makes it survivable. Both are on. Three rules now bind every no-activity rule:
a blank touch date on an empty or thin cache is not evidence — the brief forces a 90-day ingest
and `--lead-touch` before evaluating; a record with no recorded touch after that is **overdue by
definition** and enters the list marked *no recorded touch*, never held back as "unbaselined";
and matching more than a third of the book is a one-line warning on top of the list at the cap,
not a reason to withhold it. `followup_baseline:` / `followup_backlog_at_enable:` and their
`lead_` twins are stamped by the brief on first run if setup did not write them. Silence is the
one output a follow-up rule is not allowed to produce.

## 2026-09-03

Skills only — no script or schema changed. The version moves so this entry reaches anyone who
upgrades; `requires_template` stays at **2026-09-02**. Plugin `0.11.0`.

**The daily brief catches the records up with yesterday's email.** Step 1a reads every thread
since the last brief (capped at seven days, so a skipped day is not lost) on the user's open deals
and leads, and updates the record the way a rep would at the end of the day and usually does not.
Two tiers. Tier 1 is applied and reported: a dated append to the notes file, `next_step` /
`next_step_date` where the thread states one, a lead moved to the org's engaged status on a reply,
commitments and competitor mentions routed where they already go — all folder writes at
`pending-push`, listed under *Did automatically*, with the CRM push offered as one queue item and
never automatic. Tier 2 waits: a close date, an amount, a stage, or a Negative sentiment reading
(quote required, as with meetings) implied by a thread becomes an *edit before applying* item in
the approval queue showing current against proposed and the line that implied it; the user
approves, edits, or declines by number, and a declined proposal is noted so the same thread does
not raise it again. Governed by a new starter rule, *Update records from email* — the one rule
that ships `auto`, because its `auto` reaches only the folder. Tier 2 cannot be configured down.

## 2026-09-02

Plugin `0.10.0`. `activity_sync.py` gained lead attribution and `--lead-touch`, and the lead and
opportunity schemas changed, so **`requires_template` moves to 2026-09-02**: every folder is
behind until `upgrade.py --apply` runs. After upgrading, ingest a full history window once — the
existing cache holds no lead events, and until it does every lead reads as never touched.

**No-activity rules stop reading `last_activity_date`.** Every "deal gone quiet" test used to reach
for that column because the CRM owns it and it looks authoritative. It is not usable for the job:
it carries import and seeding stamps that are not events, it is blank on untouched rows, and it
stops moving the moment the CRM stops logging — which, in an org whose activity table is
auto-captured email noise that every query filters out, is most of the time. On one live book the
rule reported 71 of 75 open deals inactive on a day four of them had email threads running. The
failure is silent: the rule does not error, it fires on everything, and a rule that fires on
everything is one nobody can act on. Three changes, all in `opportunity-tracking` and `daily-brief`:

- The trigger is now **the last outbound touch from us** — the most recent of
  `opportunity-contacts.last_outbound_date`, an `email_out` or `meeting` event in the activity
  cache, and the CRM activity table only where the profile says it is populated.
- **A sanity check on the rule itself.** Matching more than about a third of the open book in one
  run is reported as "this signal looks broken", with the likely cause, instead of a list. A
  `daily_cap` truncated that list before; it never said why the list was long.
- **Partner-worked deals are checked before being called quiet** where `11-Partners/` exists. A
  deal moving through a distributor shows no direct customer touch, and this was the most common
  false positive in a channel-heavy book.

**The follow-up guarantee**, a second rule rather than a tighter first one. *Deal gone quiet* is
discretionary — ranked, capped, take the top N. *Follow-up guarantee* is a floor: no open deal the
user owns goes longer than the window (30 days is the suggested default) without an outbound touch,
and a breach is a system failure to report, not a judgement call. The brief drafts and stages every
follow-up the floor raises rather than naming it. It ships **disabled**, because on day one a fresh
folder has never touched anything and the rule would try to write to the whole book:
`configure-project` turns it on in four steps — ask the window and cap, stamp `followup_baseline:`
in `config.md` so untouched deals surface once as a data-quality finding rather than as breaches,
count the existing backlog and say it aloud (recorded as `followup_backlog_at_enable:` so the brief
reports "12 of 46 cleared"), then enable. The backlog is burned down at the cap, oldest and largest
first, recomputed every run and never stored. The §3b fences are restated in the rule: volume does
not relax them.

**`configure-project` now ships a starter-rules table** instead of asking each setup to improvise
one. Skills find rules by `rule_name`, never by id, since ids are whatever the guard assigned in
that folder — CONVENTIONS §3b says so.

**`on_hold = yes` is the pressure valve**, and it now exempts a deal from both rules explicitly. A
live award, a customer on leave, a pilot in flight are supposed to be silent; without the exemption
they breach every day and the whole mechanism gets ignored. `on_hold_reason` gains its own enum in
the generic schema — procurement in progress, fiscal year boundary, customer unavailable, POC or
pilot running, awaiting partner, legal or security review, other — because a folder without a CRM
picklist for it had free text, and once a rule branches on the flag the reason is data. The CRM
profile still overrides it; setup now checks whether an org's on-hold picklist is a clone of its
loss reasons and says so, rather than silently substituting values the CRM would reject on push.

**Leads get the same clock.** Nothing in the folder could say when *we* last wrote to a lead —
`last_activity_date` and `days_since_active` are CRM-calculated and carry the same defect as on
deals, and the activity cache was deal-only. Now `activity_sync.py` attributes an event that
matches no deal to a lead by the person's email address, into a sibling cache
(`activity-leads.json` — separate because `engagement.py` scores every key of the deal cache), and
`--lead-touch` writes `last_outbound_date` / `last_inbound_date` onto the lead registry. Two rules
read them, mirroring the deal pair: *Lead going cold* (14 days, the target, discretionary) and
*Lead contact guarantee* (30 days, a floor, shipped disabled, enabled by the same four steps with
`lead_followup_baseline:` / `lead_followup_backlog_at_enable:`). They share **one budget of 10
lead drafts a day, floor first**, on top of the deal drafts. The clock stops when a lead converts
or is disqualified — and *Disqualify on opt-out or refusal* now raises the disqualification itself
at `review`, quoting the opt-out flag or the reply, because "not now" and "not interested" are one
word apart. It pauses while a lead is in an active sequence, passed to a partner, or has a
`hold_until` in the future — the lead's valve, new on the schema with a `hold_reason` enum, which
the brief may propose from a reply but writes only when confirmed. First contact stays first
contact: drafted, handed over, never in the ready-to-run queue, whatever the backlog.

## 2026-08-26

Skills only — no script or schema changed. The version moves so this entry reaches anyone who
upgrades; `requires_template` stays at **2026-08-25**, so no existing folder is behind and nothing
has to be upgraded to keep working. Plugin `0.9.0`.

**The daily brief now clears work rather than describing it.** Four changes to `daily-brief`, all
pulling the same way: it should leave someone with fewer things to do than it found them with.

- **Tasks are listed, not counted.** "You have seven tasks due" meant opening a spreadsheet to find
  out what it referred to, which is the thing the brief exists to save. Every task due today or
  overdue now gets its own line — id, title, account, age, priority, `why` — overdue first and
  oldest first. Snoozed rows stay out, blocked rows get their own line carrying `blocked_reason`,
  and a task three weeks past its date is named as a decision nobody made rather than rolled
  forward again. Long lists are ranked with their length stated, never silently truncated.
- **A completion queue, gated on approval.** Where the system can actually finish a task — send a
  draft already sitting at `Awaiting Approval`, set a CRM field whose value is already known, log
  an activity — it now offers to, in one numbered block naming exactly what would happen and to
  whom. The user replies with numbers or `all`. **Silence is not approval**, and a scheduled or
  unattended run builds the queue and executes none of it.

  The §3b fences are checked per item against the record rather than inferred from how the task was
  raised: no first contact, nothing commercial, nobody whose `contactable` is no or who is mid
  sequence, nothing a rule marks `manual` or that would breach its `daily_cap`, and nothing on a
  colleague's record under `team` scope without being asked. Excluded items still appear in the
  task list with the reason, so the difference is visible, and `all` cannot reach them — which is
  what makes `all` safe to type. **A missing `task-rules.csv` is not permission**: with no rules the
  queue holds only drafts already awaiting approval.
- **Ambiguous completion evidence has somewhere to go.** Step 1 closed a task on strong evidence and
  left everything else silently open, so a sent email to the right domain but the wrong person
  closed nothing and told nobody. Suggestive-but-inconclusive evidence now surfaces in the same
  queue as a *looks done, confirm?* item with the evidence and its date named.
- **An overnight sweep, deliberately small.** Newsletters that landed since the last brief, read
  against `03-Market/watchlist`, plus a bounded set of searches: accounts with a meeting today, the
  largest deals closing this quarter, renewals inside the conversation window, and watch rows set to
  `cadence = Daily`. An item survives only if it names something tracked, or matches an enabled
  watch row with a `deal` or `both` lens and a concrete `so_what`. Everything kept is logged as a
  signal through `market-tracking` — dated on the **event** rather than the issue, and deduplicated
  against what is already there, since the same event arrives from three sources across four days.
  This step consumes that module rather than keeping a second copy of it.

  Five lines is the aim, eight the ceiling, and printing nothing on a quiet morning is a result
  rather than a failure. Eight items a day for a week means the bar is too low, and the brief now
  says so and offers to tighten the watchlist instead of carrying on.

  **This is a deliberate exception to market content belonging in the weekly**, and it is fenced on
  purpose: account-linked and actionable today. Aggregate trends and competitor positioning stay in
  `weekly-brief`. A market section that outgrows the meeting prep has turned the daily into the
  weekly printed seven times a week, and it will be skipped along with everything under it.

## 2026-08-25

**The forecast dashboard is read by the whole sales team, not by the person who runs this folder —
and it was written as though it weren't.** This release makes that the default: no record IDs, no
sync plumbing, no invented next steps, and money printed in full.

- **Money prints in full, everywhere.** `money()` no longer abbreviates: `$3,000,000` and
  `$240,570`, never `$3M` or `$240.6K`. These numbers get read aloud on a call and compared against
  figures people already hold, and `$1.2M` against `$1,165,674` is one number that reads as two.
- **Headline and stat cards were never formatted at all.** `card()` rendered its value raw, so a
  payload passing `5627000` printed `5627000` while the goal bars and renewal tracker beside it —
  which do call `money()` — printed theirs correctly. Every dashboard built before today had some
  figures formatted and some not. `card()` now formats numeric values as currency; **counts and
  percentages must be passed as strings** (`"228"`, `"33%"`), which is the same contract they
  already had in practice. If your skill or wrapper pre-formats card values or patches `money()`,
  delete that — it is now double work.
- **The deal table no longer prints opportunity IDs.** The account name identifies the deal. An
  `OPP-` number means nothing to a rep who does not work in this folder and makes the page read as
  tool output. Payloads may still carry `id`; it is simply not rendered.
- **"Next step" is now the team's own text, verbatim**, and `(none recorded)` where the field is
  empty. The forecast no longer writes next steps nobody wrote — a large deal with no next step
  recorded is itself the finding, and inventing one hid it. **"Where it stands" is countable facts
  only**: stage, days in stage, close-date pushes, days since last activity, dated events. The
  ranking still calls a cold deal Cooling; the prose no longer grades anyone's work.
- **Sync drift stays off the page.** Drift, `sync_status`, pending pushes and data-quality findings
  are reported to you in chat and recorded in the snapshot `notes` — not printed on an artifact the
  team reads. Removing something from the dashboard does not lose it: `notes` is what the next run
  reads from. Same rule for every artifact other people read — see CONVENTIONS §8, *Artifacts other
  people read*.
- **Renewals with no prior-term win are excluded from the renewal track entirely** — denominator as
  well as loss column. `08-Renewals` is built from contract end dates on opportunities, which
  happily produces a full-value renewal for a deal that never closed. A contract that never existed
  was never due, so counting one as lost overstates churn *and* drags coverage against a target
  that was never real. Exclusions go in `notes`, and the prior period is restated on the same basis
  before any movement is shown. `renewals-tracking` now applies the same test before creating a row.
- **Engagement scoring reads the customer's fiscal year, not ours.** "Waiting for the new FY" in a
  federal account approaching 30 September is a timing fact, not disengagement — and a scorer that
  counts contact in a trailing window cannot see a calendar. Where the record shows a completed
  evaluation plus a known procurement date, the date beats the activity window. This changes
  rankings: deals parked as Cooling on a fiscal-year note may now read Heating, which is what they
  were.

**Two defects that affected every skill, not just the forecast:**

- **A crashed write no longer locks a registry permanently.** `acquire_lock()` cleared a stale lock
  by deleting it, and some mounts — the Cowork device bridge among them — permit writing a file but
  not unlinking it, so the 10-minute staleness window never helped and the only way through was
  copying the registry out and back. The lease is now taken over by overwriting the lock in place
  where the delete is refused, and a clean release marks the file released rather than leaving a
  fresh-looking lock behind. A live lock still blocks, exactly as before.
- **`--partial` on `crm_sync.py` and `csvguard.py --verify-sync`.** `--refresh` only ever touched
  the records handed to it, but verifying a subset reported every row you left out as `MISSING —
  not in the CRM snapshot`, which buried the real findings and made accepting a handful of drifted
  records unsafe to do unattended. `--partial` says the snapshot is a subset: absent rows are
  counted as untouched, not missing. The `UNKNOWN` message now also names its own cure — an empty
  `crm_last_modified` baseline, which one full refresh stamps.

## 2026-08-19

**The content half of demand gen used to work out what your company could credibly talk about on
its own, from your website and your document titles. It doesn't any more — it asks you, once, at
setup.**

- **New file in your folder: `02-Context/Messaging/standing-profile.md`.** What your organisation
  can credibly speak about publicly, the evidence behind each claim and where that evidence lives,
  and — required, not optional — what's adjacent to you that you should stay out of. Written from
  your answers. `configure-project` has a new phase (Track 5a) that captures it, and that phase
  runs only when Demand Gen is enabled.
- **`demand-gen` now stops the content half if that file is missing**, and offers to capture it
  there and then. It will not infer standing in order to carry on. **Campaign measurement is
  untouched** — part one has no standing dependency and a folder that never runs content behaves
  exactly as before. If you have been running content sweeps without a standing profile, the
  assessment behind them was an inference nobody confirmed, and the angles it *declined* are the
  part worth re-reading.
- **Why this is a hard stop rather than a warning.** Surface signals under-represent what an
  organisation knows: research gets titled for its subject rather than its platform, and capability
  is not always marketed. In one real setup the inference concluded a company had no standing on a
  platform carrying roughly half its research, because the titles didn't name it — and wrote that
  conclusion into three files. A wrong exclusion suppresses a whole category of content permanently
  and silently, because nobody audits the pieces that were never suggested.
- **New column: `lens` on `03-Market/watchlist`** — `deal`, `content` or `both`. Deal signals and
  content topics are different questions with different tests, and they shared one registry with
  nothing but the `why` prose to tell them apart. **Your existing rows become `deal`, which is what
  they already meant** — every watchlist built before this column was deal-oriented, so there is
  nothing to fix by hand. Content rows also carry `evidence_ref`, naming the standing-profile claim
  behind them.
- **New column: `standing_ref` on `05-Demand-Gen/content-opportunities`** — which named claim a
  piece rests on. The guard requires it before a row can reach `Approved`, `Drafted`, `In Review`
  or `Published`, and deliberately does **not** require it on `New`, `Declined` or `Expired`: an
  untested idea has no answer yet and a passed-over one never will. A drafted piece with an empty
  `standing_ref` is the exact failure this release exists to prevent.
- **New file: `05-Demand-Gen/Content/README.md`**, carrying two rules that previously lived only in
  skill prose and were therefore re-derived every session: never comment publicly on a competitor's
  funding, win or bad news, and perishability is a deadline rather than a label.
- **Two new schema keys, usable in your own columns, documented in CONVENTIONS §3.**
  `"default": "x"` fills a blank cell and reports the fill — which is what lets a new *required*
  column arrive in an existing registry without turning every row into a `NEEDS YOU`.
  `"required_when": {"column": "status", "in": [...]}` makes a column required only at some point in
  a record's life. Both are checked on every `--check-all`. Declare a `default` only where a blank
  genuinely already meant that value; never on an amount, a date, or anything a person should decide.
- **`setup_status` scores three new steps when Demand Gen is on**, so a folder with no standing
  profile no longer reports 100%. It also now expects `content-opportunities` to exist alongside
  `campaigns` — the content half had nowhere to write and setup was calling that finished.
- **The weekly brief skips its content assessment rather than guessing** when no standing profile
  exists, and says so in one line. `market-tracking` sets `lens` on rows it adds, and won't invent
  content-lens rows against a profile that isn't there.

**Also in this release: meetings stop evaporating.** A new fifteenth skill, `meeting-notes`,
processes call transcripts and meeting notes into the record the rest of the system runs on.

- **New module: Meeting Notes, at `13-Meetings/`.** Three ways in — paste a transcript or your
  rough notes in conversation, drop exports (Otter, Teams, Gong, `.vtt`) into `13-Meetings/Inbox/`,
  or pull from a connected transcript source such as Zoom. The verbatim original is kept in `Raw/`,
  the processed note in `Notes/`, and both stay searchable — "what did they say about SSO" is now a
  question the folder can answer, with the quote, the speaker, and the date.
- **Two new registries.** `meetings` — one row per processed meeting: summary, outcome, key quote,
  attendees, risks, positives, next step. `commitments` — who promised what by when, **in both
  directions**. Yours become tasks and are verified like any task; an unmet customer commitment is
  one of the earliest stall signals a deal gives off, and the weekly brief now sweeps for exactly
  that.
- **Extraction routes to the module that owns it**: action items become tasks at your configured
  automation level; competitor mentions land on the battlecard as field intelligence; renewal-risk
  and expansion phrases are offered to the renewal row; the agreed next step is offered to the
  opportunity — and to the CRM under the usual rule: never automatic, field-by-field diff, explicit
  yes.
- **Attendance is now the strongest meeting evidence there is.** `meeting_evidence` on the contacts
  registry gains a `transcript` rung, above `opportunity-linked`. The contacts build folds the
  meetings registry in on every run, so transcript evidence survives rebuilds instead of being
  silently reverted — and `contacts_sync.py --fold` pushes it immediately, touching meeting columns
  only. Attendee rows discovered from a transcript arrive with email columns honestly blank rather
  than confidently wrong.
- **Sentiment, scored the way this system scores anything: with the receipts.** Each meeting
  carries `sentiment` (Positive / Mixed / Neutral / Negative / Unclear) beside `outcome`, and the
  guard requires `sentiment_evidence` — a quote or close paraphrase — for any non-neutral reading.
  The two columns answer different questions, and their divergence is the signal: Positive/Neutral
  is the pleasant-meetings-no-deal pattern, Negative/Advanced is a hard conversation that did its
  job. Sentiment deliberately does NOT feed engagement scoring, which stays behavioral — a cheerful
  transcript cannot inflate a number deals get ranked by.
- **Engagement finally counts the meetings the calendar never saw.** An off-calendar call whose
  only trace is the transcript is ingested into the activity cache; a scheduled meeting is marked
  `already-on-calendar` and NOT re-ingested, because meetings are the highest-weighted event in the
  score and double-counting them is the most expensive dedup mistake available.
- **The briefs read it.** Daily-brief meeting prep now leads with what happened last time and any
  unmet commitment of yours — walking in unaware of your own promise is the avoidable version of a
  bad meeting. Content tailoring reads recent meeting notes so an asset answers the question they
  asked in the room.
- **Upgrading is one `update-system` run**: two schemas arrive, `meeting_evidence` gains its rung,
  and nothing else in your folder is touched. The module stays off until you enable it, and every
  skill treats its absence as "not enabled", never as an error.

## 2026-08-18

**Money can be added up now. Before this release, on a mixed-currency book, it could not.**

- **New: a `currency` and a `converted_*` column on every registry that holds money** —
  opportunities, renewals, quotes and goals. The amount column stays in the record's own currency,
  which is the right number to quote at a customer and the wrong one to add up. `converted_amount`
  (and `converted_current_value`, `converted_proposed_value`, `converted_total`,
  `converted_target`) hold the same money in the folder's base currency, which is what every
  total, weighted forecast, coverage ratio and attainment figure is now built from. **If you have
  been reading forecasts from a folder with more than one currency in it, those totals were adding
  incompatible units.** Re-run them.
- **New file in your folder: `00-Config/fx-rates`.** Dated rates, one row per currency per rate
  change, seeded from your CRM's own currency table so your totals reconcile against your CRM's
  reports instead of quietly disagreeing with them. `rate_to_base` is a multiplier — amount ×
  rate_to_base = base — which is the **reciprocal** of what Salesforce stores in
  `CurrencyType.ConversionRate`. `fx.py --pull` does the inversion; the source's own number is kept
  verbatim in `source_rate` so you can check it against the CRM screen.
- **New setting: `base_currency:` in `00-Config/config.md`, and it has no default.** Until it is
  set, nothing converts and `fx.py` refuses rather than guessing. Setting a base currency decides
  what every number in every forecast means, so it is not a decision the system makes for you.
- **New script: `fx.py`** — `--pull`, `--convert`, `--check`, `--backfill-currency`, `--refreeze`,
  `--rates`. Run `--convert` after any import, amount change or stage change; the opportunity,
  renewal, forecast and setup skills now do.
- **Closed records freeze, and this is the part whose meaning is easy to miss.** Once a deal is
  Closed Won or Closed Lost — or a renewal resolves, a quote is sent, a goal's period ends — its
  converted figure is computed once and never recomputed, so a settled quarter reports the same
  number next month as it did on the day. A record that is merely late does **not** freeze: a deal
  whose close date has passed while it is still open is live pipeline and reconverts at today's
  rate. The freeze is on state, not on the calendar. `fx.py --refreeze --registry X --id ID` is the
  one deliberate way back through it.
- **A conversion that cannot be done is blank, never zero**, and is reported rather than absorbed.
  A record with no currency, or a currency with no rate on file, is missing from every total —
  `fx.py --check` names them, and the forecast dashboard now prints a red line saying how many were
  dropped. A zero here would have silently shrunk the forecast, which is the failure this whole
  feature exists to prevent, not one it should introduce.
- **Blank currencies are not assumed to be your base currency.** `fx.py --backfill-currency` fills
  them explicitly and tells you how many rows it touched. Turning missing information into an
  assertion is a decision, and it needs a command of its own.
- **The forecast dashboard no longer hardcodes `$`.** It takes the symbol from `base_currency` and
  states, above the numbers, which currency they are in and what was converted to get there. A
  `$` in front of a European book's total was a wrong number wearing the right punctuation.
- **`fx.py --convert` refuses to be quietly useless.** If none of a schema's declared closed states
  exist in your org's picklist — your stages are "Won"/"Lost" rather than "Closed Won"/"Closed
  Lost" — it says so instead of never freezing anything, which would look exactly like working
  correctly until a closed quarter rewrote itself. Edit `fx.freeze.values` in the schema; schemas
  live in your folder for this reason.
- **CONVENTIONS §8a rewritten.** It used to say never sum across currencies and stop there, which
  left every total in the system unbuildable on a mixed book. It now describes the conversion, the
  freeze, and the obligation to say a total is converted.
- **Rates can come from a public source instead of the CRM.** `fx.py --fetch` pulls from ECB
  reference rates (via Frankfurter), keyless, falling back to exchangerate-api's open endpoint for
  currencies the ECB does not publish. `--date 2026-03-31` fetches a historical rate, which is what
  backfilling a settled quarter needs given closed records freeze. It is the only command in this
  system that touches the network.
- **`rate_source:` in config.md decides which source converts — default `crm`, and this is the
  important sentence.** Rates from every source live in the same table side by side; the default
  stays the CRM so your folder's totals keep reconciling against your CRM's own reports. Set it to
  `market` for a folder with no CRM, or one whose currency table nobody maintains.
- **`fx.py --check` now reports rate drift between the sources on file**, past
  `rate_drift_threshold:` (default 2%). **This is the reason to hold a second opinion at all**: a
  CRM currency table nobody has touched in a year keeps converting, silently and confidently,
  several percent out, and nothing else in the system can tell. Drift is reported and never
  applied — which source is authoritative is a decision in config.md.
- **Stale rates are flagged on every conversion**, not only when asked, past
  `rate_staleness_days:` (default 30). A stale table converts exactly as confidently as a fresh one.
- Two providers quoting the same currency are **parallel opinions, not a history**: `effective_to`
  and `status` are computed within a source, so a market rate never marks the CRM's rate
  superseded, and a market fetch never reads a CRM row as "the previous rate".
- **New setup steps**: `base-currency` (required) and `fx-rates` (optional) in the Foundation
  section of the checklist.

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
