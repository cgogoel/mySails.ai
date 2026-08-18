---
name: "meeting-notes"
description: "Process a call transcript or meeting notes and turn it into the record the rest of the system runs on — action items raised as tasks, commitments tracked in both directions, key quotes kept verbatim, competitor mentions routed to battlecards, attendees threaded onto the deal, renewal risk captured, engagement credited, and a follow-up email drafted. Keeps the raw transcript beside the processed note so what the customer actually said stays findable. Use whenever the user pastes a transcript or call notes, says they just got off a call, asks to process or log a meeting, wants to pull a Zoom transcript, asks what a customer said about something, asks what was promised or agreed in a meeting, wants action items or a follow-up email from a call, or asks what happened last time they met an account. Also use when another skill needs the record of a past meeting."
---

# Meeting Notes

A meeting is the highest-value event a deal produces and the fastest one to evaporate. Two weeks
later, what remains is a vague sense it went well — the feature request that was actually a
renewal condition, the aside about a competitor, the promise someone made about a security
questionnaire are all gone. This skill turns the transcript into the durable version: one
searchable record per meeting, with everything actionable routed to the module that acts on it.

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`. Then resolve the
   scripts, and **stop if that fails**:

   ```bash
   S=$(python3 "<project>/.sales-system/find_scripts.py") || exit 1
   ```

   Every command below runs as `python3 "$S/<script>.py"`. Do not interpolate
   `$CLAUDE_PLUGIN_ROOT` directly — it is empty in some sandboxes and fails silently. **A
   non-zero exit here is a full stop.** A folder with no `find_scripts.py` predates this
   release — run `update-system`.
2. Read `$S/../CONVENTIONS.md`.
3. Read `00-Config/config.md` for `scope`, `default_automation`, `meeting_sources`, and
   `00-Config/connections.md` for which transcript source is actually connected.
4. Repair the registries:

```bash
python3 "$S/csvguard.py" --check-all <project>
```

**If `13-Meetings/` doesn't exist**, the module isn't enabled. Offer to enable it here — it's
one minute — rather than bouncing the user away mid-debrief:

```bash
mkdir -p <project>/13-Meetings/{Inbox,Raw,Notes}
python3 "$S/csvguard.py" --init <project>/13-Meetings/meetings --schema meetings --project <project>
python3 "$S/csvguard.py" --init <project>/13-Meetings/commitments --schema commitments --project <project>
```

Add it to `00-Config/enabled-modules.md` and re-run `setup_status.py --init` so the checklist
knows. If the schemas are missing entirely, the folder is behind — run `update-system` first.

---

## Three ways in, one pipeline

**Pasted.** The user pastes a transcript or their own rough notes and says (or you work out)
which meeting it was. The lowest-friction path and the one to optimise for — someone debriefing
two minutes after hanging up is giving you the material at its freshest.

**Dropped.** Files in `13-Meetings/Inbox/` — exports from Otter, Teams, Granola, Gong, a `.vtt`
from a recorder, a colleague's typed notes. Sweep the Inbox at the start of every run and say
what's waiting. Process each, then move the original to `Raw/` (use `mv`, which works on
connected folders where delete does not).

**Pulled.** If a meeting-transcript connector is available (Zoom, most commonly — check
`connections.md`, and record it in config as `meeting_sources:`), offer to list recent
recordings and fetch the transcript for the one the user names, or everything since the last
run. Never pull silently on a schedule — recordings can include meetings that were never meant
for a sales folder, so the user picks.

Whatever the source: **the raw is kept**, verbatim, in `13-Meetings/Raw/`, named
`YYYY-MM-DD-account-slug.<ext>`. The processed note is an interpretation; the raw is the
evidence behind it. The one exception is pasted material the user asks not to keep — respect
that, leave `raw_path` blank, and say the note is now the only record.

## Match it to a record, and don't guess

Work out what the meeting was about: match attendee email domains and account names against
`07-Opportunities/`, `08-Renewals/`, `02-Context/Customers/`, and `06-Leads/`. One clean match:
proceed, saying which. The same rule as everywhere else in this system applies when it isn't
clean:

- **Two open deals at the same account** — ask which. Attaching a meeting to the wrong deal
  corrupts engagement, contacts, and next steps in one move, and a guess reported as a fact is
  the one output this system must not produce.
- **No match at all** — ask. It may be a lead not yet imported, a deal that should exist and
  doesn't (offer to create it via opportunity-tracking), or genuinely internal.
- **Internal or non-deal meetings** — `related_type: none` is a real answer. What it is not is
  a dumping ground for meetings nobody matched.

An opportunity in a renewal cycle can match both the opportunity and the renewal row; prefer
the renewal when the conversation is about the contract, the opportunity when it's about new
scope, and say which you chose.

## The processed note

Write `13-Meetings/Notes/YYYY-MM-DD-account-slug.md`, frontmatter per CONVENTIONS §6 carrying
`meeting_id`, date, `related_type`/`related_id`, attendees. Sections, in order:

**Summary** — two or three sentences: what happened, what changed.

**Key moments** — the quotes that matter, **verbatim, with the speaker named**. Never tidy a
quote into what they probably meant; the exact words are the value, and "roughly said" must be
marked as such. Transcript speaker labels are unreliable — when attribution is uncertain, say
so rather than pinning words on the wrong person.

**Action items** — two lists, ours and theirs, each item with an owner and a date where one was
given. An action item has a doer and a deed; "we should think about pricing" is neither.

**Commitments** — the subset of action items someone actually promised, in the words they
promised it. These get registry rows (below).

**Challenges and risks** — what was said that threatens the deal: a feature gap named as
blocking, budget language, a stakeholder going cold, a competitor gaining ground. Quote or
closely paraphrase; don't editorialise.

**Positive signals** — advantages acknowledged, expansion interest, champion language ("I'll
take this to my VP" is a different fact from "sounds good"), timeline urgency on their side.

**Sentiment** — how the customer sounded, as one of Positive / Mixed / Neutral / Negative /
Unclear, **with the evidence beside it**. The rules that keep this honest:

- **Ground it in what was said**, not in tone imagined from a text transcript. "This is exactly
  what we've been looking for" supports Positive; a transcript where nobody said anything either
  way is Neutral, and one too garbled to read is Unclear. Any non-neutral reading requires a
  quote or close paraphrase in `sentiment_evidence` — the guard enforces it.
- **Sentiment is not outcome, and the divergence is the point.** A warm meeting where nothing
  moved is `Positive / Neutral` — the pleasant-meetings-no-deal pattern, worth naming when it
  repeats. A bruising negotiation that produced a signed next step is `Negative / Advanced`, and
  is a better meeting than the warm one. When the two diverge, say so in the summary.
- **One voice is not the room.** An enthusiastic champion and a silent economic buyer is `Mixed`,
  and *who* carried each side matters more than the aggregate — put it in the evidence.
- **Sentiment never feeds engagement scoring.** Engagement is behavioral — who gave up time, who
  replied. Sentiment is interpretive, and mixing the two would let a cheerful transcript inflate
  a score that deals get ranked by. It informs the human reading the note, not the arithmetic.

**Competitor mentions** — who came up, in what context, verbatim where it's quotable.

**Renewal signals** — for renewal-related meetings only: churn indicators (consolidation talk,
unused seats, budget review) and expansion signals, each tied to what was actually said.

**Next meeting** — what was agreed, when, and what each side owes before it.

The transcript will contain small talk, personal asides, and things said in confidence to a
person rather than to a file. The note extracts the business content; the raw keeps the rest.
Don't quote personal material into the note — it adds nothing and it reads badly in six months.

## Write the registries

One `meetings` row via the guard — never a direct file write. `summary`, `outcome` (a judgement,
recorded as one: a pleasant meeting where nothing moved is `Neutral`, however good it felt),
`sentiment` with its `sentiment_evidence` (the guard refuses a non-neutral sentiment without
evidence, and that refusal is the feature), `key_quote` (the single most consequential line, so
registry search alone can surface it), attendees with emails resolved from
`opportunity-contacts` wherever the transcript only gives a name, `new_faces`, counts, paths.

One `commitments` row per promise, both directions, `what` in the words it was made in. No due
date given is worth noticing — pin it down in the follow-up email. **`theirs` rows are the
underused half**: an unmet customer commitment is one of the earliest stall signals a deal gives
off, and the weekly brief now reads this registry looking for exactly that.

## Route the intelligence

Each of these goes to the module that owns it — this skill extracts, it doesn't duplicate.

**Tasks.** Raise one per action item of ours, `related_id` set, `task_type` and `verify_by`
chosen sensibly (an email commitment verifies by `email-sent`), at the automation level config
says. Write the task ids back to `tasks_raised` and link commitments via `task_id`. Don't raise
tasks for vague intentions — the task list's credibility is worth more than its completeness.

**Competitors.** A competitor mentioned in a live meeting is field intelligence battlecards are
built from. Hand it to competitor-tracking's flow: bump the encounter on the competitor row,
log the verbatim objection or comparison as a candidate landmine or win-theme, and flag a
first-time appearance on this deal. If the competitor isn't in the registry, say so and offer
to add them.

**Contacts.** Attendance is the strongest meeting evidence there is. After writing the meetings
row:

```bash
python3 "$S/contacts_sync.py" --fold <project>
```

That pushes attendance into `opportunity-contacts` — meeting columns only, `transcript` rung —
and every later full rebuild re-derives the same conclusion from the meetings registry, so the
evidence can't be reverted. New faces land as `activity-only` rows with email columns honestly
blank. Champion language spotted in the transcript belongs in the note and, when it's strong,
in the opportunity's `champion` field — with the user's confirmation, since anointing a
champion is a judgement about a person.

**Renewals.** For renewal meetings, offer updates to `health`, `churn_risk_reason`, and
`expansion_signal` on the renewal row — quoting the evidence, at `review`. If this was the
first renewal conversation, `first_renewal_touch_date` finally has its date.

**The opportunity.** Offer `next_step` / `next_step_date` from what was agreed in the meeting —
show current against proposed, since overwriting a next step someone typed deliberately is an
edit, not housekeeping. Local update at `review`; **CRM push follows §7: never automatic,
field-by-field diff, explicit yes.** Offer to log the meeting summary as a CRM activity the
same way, recording the id in `crm_activity_id`.

## Engagement: credit the meeting without counting it twice

Meetings are the highest-weighted event in engagement scoring, which makes double-counting them
the most expensive dedup mistake available. The rule:

- **The meeting was on the calendar** (a scheduled call — the normal case): the calendar or CRM
  copy is already in the activity cache via the briefs' ingest. Set
  `engagement_ingested: already-on-calendar` and ingest nothing. The transcript's engagement
  value here is the attendee evidence, which the fold already delivered.
- **Off-calendar** — an ad-hoc phone call, a hallway conversation someone typed up: this record
  is the only trace, and it's exactly the meeting that used to go uncounted. Ingest it:

  ```bash
  python3 "$S/activity_sync.py" --ingest <project> --input events.json
  # {"source": "transcript", "user_emails": ["you@co.com"],
  #  "events": [{"date": "2026-08-18", "kind": "meeting", "opp_id": "OPP-0031",
  #              "counterpart_email": "jane@acme.com", "detail": "ad-hoc pricing call"}]}
  ```

  Set `counterpart_email` to the primary external attendee's address resolved from
  `opportunity-contacts` — the dedup key includes it, so a resolvable email is what protects
  against a later calendar ingest of the same event. Then `engagement_ingested: ingested`.

When in doubt about which case applies, `already-on-calendar` is the safe wrong answer: it
under-credits one meeting, where the alternative inflates the strongest signal in the score.

## The follow-up email

Offer it while the meeting is fresh — it's the single most valuable artifact a debrief
produces, and the discipline of writing it is what pins down vague commitments. From the note:
thanks tied to something real from the conversation, what was agreed, what we owe and when,
what we asked of them (the polite restatement of their commitments — this is where a missing
due date gets pinned down), and the next step with its date. If a `my-writing-style` profile
exists, draft from it. Route through the task flow at the configured automation level — email
to a customer is customer-facing, so `review` unless config says otherwise.

## Search: "what did they say about..."

When the user asks what a customer said, wants the history before a meeting, or half-remembers
a quote: search `13-Meetings/Notes/` (and `Raw/` when the notes don't settle it) plus the
registry's `summary`/`key_quote` columns. Answer with the quote, who said it, the date, and
which meeting — and cite the note file so they can read the context. If the notes disagree with
the user's memory, say what the record shows; the record is why this module exists.

## Prep: what happened last time

When prepping a meeting (here, or feeding the daily brief), pull for the account: the last
note's summary, outcome and sentiment, **open commitments in both directions** — walking in
unaware of what you promised is the avoidable version of a bad meeting — plus unresolved risks,
and what was agreed as the agenda. Sequence beats snapshot: "last time they raised SSO as
blocking; here's what we said we'd do about it" is preparation, a stale account summary is not.
Where several meetings exist, the sentiment *trajectory* outranks any single reading — three
meetings sliding Positive → Mixed → Negative on a deal the stage field still calls Negotiation
is a finding, and the evidence column holds the quotes that make it concrete.

---

## Judgement

The pull is toward summarising everything and extracting nothing. A note that says "good
meeting, discussed pricing and next steps" has recorded no quote, no commitment, no risk — it
is the vague memory this module exists to replace, written down. Better three verbatim quotes
and two tracked commitments than five paragraphs of paraphrase.

The opposite failure is over-claiming: a sentiment asserted without a quote to stand on, a
"champion" appointed off one friendly remark, a risk manufactured from a stray comment. Extract
what was said. Where you interpret — and `sentiment` and `outcome` are both interpretation —
record the judgement as a judgement with its evidence beside it, and reach for `Unclear` and
`Neutral` when they're true. A sentiment column is only worth having while every non-neutral
value in it can point at something someone said.

Transcripts are imperfect: speakers mislabelled, jargon mangled, whole passages garbled. When
the material is bad, say so and extract less rather than guessing more. What this module writes
gets treated as the record of what the customer said — that trust is the asset, and one
invented quote spends it.
