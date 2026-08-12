---
name: "renewals-tracking"
description: "Manage the renewal contract calendar in the sales project folder — track which customer contracts are expiring, flag contracts with no renewal opportunity, watch whether the renewal conversation has actually started, assess churn risk and expansion potential, and hand off to the pipeline. Use whenever the user mentions renewals, contracts expiring, churn or churn risk, at-risk customers, upsell or expansion within existing accounts, asks what's up for renewal this quarter, asks which customers need a QBR or a renewal conversation, wants to know renewal coverage or retention, or wants to create a renewal opportunity. Also use when a brief or forecast needs renewal exposure."
---

# Renewals Tracking

Renewals are the revenue you already earned and can still lose. They fail differently from new
business: not by losing a competitive evaluation, but by nobody noticing a date until it's too close
to do anything useful.

**This is not a second pipeline.** In most orgs a renewal *is* an opportunity — the profile says
which marker identifies one. Duplicating deal data here would create two numbers that disagree.

What this registry tracks is what opportunities don't: whether someone is actually working each
contract, and whether the customer has heard about it yet.

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`.
2. Read `.sales-system/CONVENTIONS.md`.
3. Read `00-Config/config.md` for `scope` and `default_automation`.
4. Read `.sales-system/crm-profile/field-map.json`, especially the `renewals` block and any
   `org_renewal_policy` it carries. **The org's renewal policy determines what counts as late here**,
   so read it before flagging anything.
5. Repair the registry:

```bash
python3 <project>/.sales-system/scripts/csvguard.py --repair <project>/08-Renewals/renewals.csv --project <project>
```

Contracts live in `08-Renewals/renewals.csv`. Account narrative belongs with the account, in
`07-Opportunities/Accounts/<Account Name>/` — it's the same customer and the history should read as
one story.

---

## Deadlines: read the policy, don't assume the default

Three org-specific facts change everything about how you read this registry. All three are in
`org_renewal_policy`.

### Does doing nothing renew it, or lose it?

`auto_renew` inverts the risk:

- **`no`** — doing nothing loses the contract. Silent lapse is the failure mode.
- **`yes`** — doing nothing renews it. The customer is locked in, which is fine commercially and
  occasionally a relationship problem.

The profile records the org's default where contracts are consistent. Getting this backwards
produces advice that is exactly wrong, so check rather than assuming.

### Is there a formal notice period?

Where one exists, `notice_deadline = contract_end_date - notice_period_days`, and past it the
outcome is decided by the contract rather than by anyone selling. Surface it ahead of the expiry
date.

**Where the org has no formal notice period, don't compute or mention one.** Inventing a deadline
that doesn't exist is worse than having none — it either creates false urgency or, once someone
notices it's fictional, discredits the real deadlines too. A blank `notice_period_days` means
unknown or not applicable. It never means zero.

### When should the renewal opportunity exist, and when should the customer have heard?

These are the two commitments that actually drive the work.

**`create_renewal_opp_at`** — some orgs create the renewal opportunity when the renewal window
opens; others create it the moment the original deal closes. If the policy is at-close, then a
closed-won contract without a renewal opportunity is a **policy gap from day one**, not a timing
question. Flag it regardless of how far out the contract end date is. A contract signed last month
with an eleven-month runway and no renewal opp is still a miss.

**`renewal_conversation_lead_days`** — how far ahead the customer should have heard from you.

```
conversation_target_date = contract_end_date - renewal_conversation_lead_days
```

This is the operative deadline in orgs without a notice period. Track it via
`first_renewal_touch_date`, and set that field **only from evidence** — a sent email or a held
meeting about this renewal. A task raised is not a conversation started, and an intention to reach
out is not outreach. The whole value of the field is that it distinguishes the two.

Detect it the way the task layer detects anything else: look for sent mail to the account after the
contract started that's plausibly about the renewal. When the evidence is ambiguous, leave the field
blank and say what you found rather than crediting a touch that may not have happened.

---

## Building the calendar

Source contracts from closed-won deals per the profile's `source_of_contracts` — typically won
opportunities with a future contract end date. Match existing rows on `original_opp_id` first, then
account plus end date.

Then link forward: find the renewal opportunity in `07-Opportunities/opportunities.csv` using the
marker the profile names. Set `renewal_opp_id`, denormalise its stage into `renewal_opp_stage`, and
record `renewal_opp_created_date`.

Where the policy is create-at-close, the gap between `contract_start_date` and
`renewal_opp_created_date` is itself a finding — a consistent lag means the policy exists on paper
and not in practice, which is worth saying once rather than flagging on every row.

Recompute derived fields on every read: `conversation_target_date`, `days_to_conversation_target`,
`days_to_expiry`, `risk_flags`. Stale derived values are worse than missing ones because they look
authoritative.

---

## Risk

Compute `risk_flags` fresh each time, ordered by how much they should worry someone:

**`no-renewal-opp`** — no renewal opportunity exists. Under a create-at-close policy this applies
from day one. These contracts are invisible to every pipeline report in the company, and that
invisibility *is* the risk.

**`conversation-overdue`** — past `conversation_target_date` with no `first_renewal_touch_date`. The
commitment has been missed. Say by how many days; "overdue" is abstract, "the customer should have
heard from you 47 days ago" is not.

**`conversation-due-soon`** — target date within 30 days, nothing sent yet.

**`notice-window-closing`** — only where a formal notice period exists.

**`champion-left`** — `champion_still_there = no`. The most common cause of surprise churn, and it
usually surfaces months ahead if anyone is looking.

**`no-qbr`** — no `last_qbr_date` in the last two quarters on a contract worth having. Not having
spoken to a customer all year is itself the risk.

**`quiet`** — no activity in 60+ days. A different standard from new business, where two weeks is
alarming; customers go quiet legitimately. A full quarter of silence before a renewal does not.

**`contraction-risk`** — proposed value below current value on an open renewal opportunity.

Rank by exposure, not date. A $200K contract 120 days out with no champion outranks an $8K contract
renewing next month with an engaged buyer, and a date-sorted list buries that.

---

## Handing off to the pipeline

Creating a renewal opportunity puts a number in the team's forecast. That's visible to management
and affects coverage reporting, so confirm it explicitly and show the values you're about to set —
even under a create-at-close policy where it's routine. Routine is not the same as automatic.

Follow the profile for which type marker and required fields to use. Carry across account, contract
dates, current value as the starting amount, owner, and champion. Then set `renewal_opp_id`,
`renewal_opp_created_date`, and `status`, and let the opportunity carry the commercial detail.

Before raising an expansion task, check whether another expansion motion is already open on the
account — the profile notes where that's flagged. Two people calling the same customer about growth
in one week is avoidable.

---

## Expansion

Renewals are the cheapest expansion opportunity in the business, and the timing is specific: a
renewing customer is already evaluating whether the thing is worth it.

Record concrete evidence in `expansion_signal`, not aspiration. "Added two teams, at app-count cap"
is a signal. "Seems happy" is not. Usage at a contractual limit, new business units adopting, an
adjacent need mentioned on a call, a champion promoted.

Be honest when a renewal isn't an expansion candidate. Pushing growth at an unhappy customer is how
flat renewals become churn.

---

## What to actually do

### Import and refresh

**Use `crm_sync.py`, never a hand-rolled import** (`CONVENTIONS.md` §3c):

```bash
S=<project>/.sales-system/scripts
python3 $S/crm_sync.py --plan    <project> --registry renewals
python3 $S/crm_sync.py --refresh <project> --registry renewals --json-file recs.json
```

Renewals are the registry a rebuild damages most quietly. Much of what's here is authored
locally — `churn_risk_reason`, `expansion_signal`, `conversation_target_date`, `next_action` —
so a refresh writes only the CRM-owned columns and leaves that work intact. A rebuild would
also renumber every `REN` id and orphan every task pointing at one, which is why bulk loading
goes through `--upsert` and never a rewrite.

Verify before reporting coverage:

```bash
python3 $S/csvguard.py --verify-sync <project> --registry renewals --crm-json snapshot.json
```

Renewal books get reassigned in bulk — a territory change, someone leaving — and sixteen
contracts silently changing owner is the kind of thing a coverage number absorbs without
complaint. Lead with it when it happens.

### Renewal review

Structure by urgency of *decision*, not by date:

1. **Commitments missed** — conversation overdue, or contracts with no renewal opportunity.
2. **Due soon** — conversation target inside 30 days.
3. **At risk** — flagged contracts with an opportunity already open.
4. **Expansion candidates** — with the evidence.
5. **Coverage** — value renewing this quarter and next, how much is in pipeline, how much isn't.

That last number is what a manager wants and rarely has: renewal revenue with nobody assigned.

Under `team` scope, break out by owner and flag distribution problems — a rep carrying a large
renewal book with no activity, contracts with no owner.

### Update and close

Update the row, recompute derived fields, set `sync_status = pending-push`.

On close, set `outcome` by comparing proposed to current value. If the CRM already computes
expansion-versus-contraction against the original deal, prefer reading its answer — the profile says
whether it does.

**Churn deserves a real post-mortem.** Capture what actually happened in `notes`, not just a
category. The causes usually predate the renewal by months — a champion left, a QBR never happened,
usage declined in Q2 and nobody looked. Write down the thing that was actually true.

Check the conversation history when a renewal is lost. If `first_renewal_touch_date` was blank or
late, that's a process finding, not a customer finding, and it generalises in a way individual
account post-mortems don't.

If churn clusters — one segment, one product, one cohort, one sales motion — say so.

### Raise tasks

Read `01-Tasks/task-rules.csv` and honour the caps.

The renewal-conversation task is the important one, and it's cleanly verifiable: set
`verify_by = email-sent` with the customer's address in `verify_target`, so the system closes it on
evidence rather than assertion and updates `first_renewal_touch_date` at the same time.

Put the date and the number in the title — that's what makes a task impossible to defer. "Start
Globex renewal conversation — target 2 Sep, $88K" beats "follow up with Globex."

Set `related_type = renewal` and the ID, and fill `why`.

---

## Judgement

Renewals reward looking further ahead than feels necessary. The useful conversation happens four
months out, when there's still time to repair a relationship. The conversation thirty days out is
damage control.

So bias toward surfacing things earlier than the date alone suggests, and always say why now rather
than later. "Globex renews in December" invites deferral. "Globex renews in December, you owe them a
conversation by 2 September, and the champion who bought it left in May" does not.

