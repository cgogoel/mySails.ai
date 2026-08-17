---
name: "opportunity-tracking"
description: "Manage the opportunity registry in the sales project folder — import deals from a CRM or file, review pipeline health, flag at-risk deals, update stage and close date, maintain close plans, record what happened on a deal, mark won or lost, and raise follow-up tasks. Use whenever the user mentions deals, opportunities, or pipeline, asks what's at risk or slipping, wants a pipeline review or deal-by-deal walk, asks which deals need attention this week, wants to update a stage, amount, or close date, wants to log a call outcome against a deal, wants to close a deal won or lost, or asks to push deal changes back to the CRM. Also use when a brief, forecast, or renewal skill needs current pipeline state."
---

# Opportunity Tracking

Opportunities are where the money is and where the self-deception lives. Every pipeline contains
deals that everyone knows aren't real but nobody has moved, and the value of this skill is mostly
in saying so — clearly, with evidence, without being tiresome about it.

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
3. Read `00-Config/config.md` for `scope`, `default_automation`, quota, and fiscal calendar.
4. If `00-Config/config.md` is missing, stop and run `configure-project` instead.
5. Read `.sales-system/crm-profile/` — `field-map.json`, `picklists.json`, `profile.md`. This skill
   ships generic and knows nothing about any particular CRM; the profile is what makes it fit.
6. Repair the registry before reading it:

```bash
python3 "$S/csvguard.py" --repair <project>/07-Opportunities/opportunities.csv --project <project>
```

Deals live in `07-Opportunities/opportunities.csv`. Per-deal narrative goes in
`07-Opportunities/Accounts/<Account Name>/OPP-0031-notes.md`, grouped by account because that's how
people actually look for it — you remember the customer, not the deal ID.

---

## Deal value

Deal value is where CRM archaeology hurts most. Orgs accumulate amount fields — ACV, ARR, TCV,
bookings, discounted totals — added at different times by different people, often with no
reconciliation between them. It's common to find two or three that each claim to be the real number.

`field-map.json` names the authoritative one in `amount_field`. **If it carries a caveat saying the
choice is unconfirmed, surface that the first time deal value matters in a session** rather than
quietly picking one. A forecast built on the wrong amount field is confidently wrong, which is worse
than uncertain.

If the profile also lists `ignore_fields`, those rival money fields have already been ruled out by
the user. Don't import them, don't display them, don't offer to reconcile them. Re-surfacing a
rejected field rebuilds exactly the ambiguity that got resolved. When asked about one, say the
system tracks the chosen field only and offer to query the CRM directly.

The profile may also record `forecast_category_api_mapping`. Some CRMs store a display label and an
API value that differ — filtering on the wrong one silently drops a whole category of deals from
results. Use the mapping; don't assume the label is the value.

---

## Pushes that trigger approval flows

This is the sharpest edge in the whole system and it's specific to opportunities.

Many orgs wire approval processes to opportunity changes: a discount past a threshold, an amount
dropping more than some percentage, a stage moving backwards. Pushing one of those changes doesn't
just update a record — it starts a workflow, notifies a manager, and creates something visible that
can't be quietly undone.

`field-map.json` lists these under `push_triggers_approval`. Before any push, check whether the
change matches one. If it does, say so explicitly and get a **separate** confirmation, distinct
from any batch approval:

> Moving Acme from Negotiate back to Validate will start the backward-stage-movement approval
> flow — your manager gets notified. Still want to push it?

This isn't excessive caution. A rep who wanted to fix a data-entry mistake and instead triggered a
management review will not use the system again.

Everything else from `CONVENTIONS.md` applies: pushes are never automatic, show a field-by-field
diff, honour `never_push` and explain refusals using the reason the profile records, and append
rather than overwrite anything listed in `shared_fields`.

Watch for `deprecated_do_not_write` in the profile. Orgs migrate qualification frameworks and leave
the old fields in place, sometimes with labels that no longer match their contents. Read them for
history on older deals; never write them.

---

## Risk: the actual job

Compute `risk_flags` on every read rather than trusting a stale column. These are the patterns that
predict a deal not closing, roughly in order of how much they should worry someone:

**Close date has moved.** `close_date_pushes` is the single best predictor in the registry. One push
is normal. Two is a pattern. Three or more means the date is fictional and the deal should be
re-baselined or moved out of the forecast. Say that plainly.

**Stalled.** No activity in 14+ days on an open deal, or `days_in_stage` well past the median for
that stage. Late-stage stalls are worse than early ones — a deal that sits in Negotiation is usually
losing, not marinating.

**Single-threaded.** One contact *replying* past the early stages. The most common way good deals
die is the champion leaving, and it's entirely preventable with enough notice. This one is computed
from `07-Opportunities/opportunity-contacts.csv`, not from the deal row — see **Threading** below,
including what to say when that file doesn't exist yet.

**No champion or no economic buyer** named at a stage where they should be. Populate
`close_plan_gaps` with what's missing — that derived field is the useful output, not the individual
close-plan columns, because "missing economic buyer and paper process" is a sentence someone can act
on and a row of blanks isn't.

**Close date inside the quarter with no next step**, or a next step whose date has passed.

**Amount changed materially** without a stage change — usually means scope moved and nobody
re-qualified.

**Close date in the past, still open.** Not a risk so much as a hygiene failure, but it corrupts
every forecast downstream, so flag it first and separately.

Distinguish *risk* from *hygiene*. A single-threaded deal is a real problem to solve. A close date
three weeks stale is a data problem to fix. Mixing them produces a list where the important items
don't stand out.

---

## Threading: who is on the deal, and which of them answer

A deal row can't hold a list of people, so the people live in
`07-Opportunities/opportunity-contacts.csv`, one row each. `contacts_attached` and
`contacts_engaged` on the deal are rollups of it — attached is everyone, engaged is everyone who
has actually replied. **The gap between those two numbers is the point.** Being on a contact-role
list tells you nothing about whether someone picks up the phone.

```bash
S=$(python3 "<project>/.sales-system/find_scripts.py") || exit 1
python3 $S/contacts_sync.py --plan   <project>                     # what to query
# run those queries through the CRM connector, write the result to contacts.json
python3 $S/contacts_sync.py --build  <project> --input contacts.json
python3 $S/contacts_sync.py --flags  <project>                     # the four flags, with evidence
```

`--plan` reads the `activity` block in `crm-profile/field-map.json`, which is what keeps this
CRM-agnostic. Never name a CRM object in a query you write by hand here.

### The four flags this unlocks

| | Fires when | What it means |
|---|---|---|
| `single-threaded` | Exactly one contact with `replied = yes`, past the early stages | One person is carrying the deal |
| `no-reply-ever` | Outbound logged, contacts present, no genuine reply | Distinct from stalled: stalled went quiet, this never started |
| `ghost-roles` | Contact roles exist, none of them appear in the activity | The CRM structure and the real relationship have come apart |
| `auto-reply-only` | Every inbound is machine-generated | Verify the people before spending more outreach on them |

These belong in `risk_flags`. **Keep them out of `close_plan_gaps`** — that's close-plan
completeness, and mixing relationship risk into it produces a list where nothing stands out.

### Three things to be careful about, all of them common

**Contact roles and the people talking to you are different sets.** A deal showing two contacts
can have a dozen in its activity, with the busiest of them on nobody's list. `source` records
which side each person came from. When you report threading, say which — "two on the contact-role
list, but the person actually working this is someone else" is the useful sentence, and it's the
`ghost-roles` case.

**`replied` is nullable and blank means undeterminable.** Plenty of orgs log activity with no
direction field at all. When `reply_evidence` is `none`, say the data can't support the
conclusion — do not report the deal as having no replies. That's manufacturing a risk flag out of
a logging gap, and it's the same failure as a flag that never fires.

**`meeting_evidence` says how strong the meeting claim is.** `opportunity-linked` is solid.
`invite-accepted` was reconstructed from calendar traffic captured as email, and most orgs link
almost no meetings to opportunities, so that weakest rung is where most of the answer comes from.
Mention the rung when a meeting is doing real work in your argument.

### When the file isn't there

New folders and any folder upgraded from an earlier version have no contacts registry. That is
normal and it must not look like good news.

> Nothing has been loaded into the contacts registry yet, so I can't tell you which of these deals
> are single-threaded. Want me to build it? It's one CRM pull.

Never report "no threading risk" from an empty or absent file. `--flags` says this itself when
there's no data; pass that distinction through rather than flattening it into a clean bill of
health.

---

## What to actually do

### Import and refresh

**Use `crm_sync.py`. Never write your own import.** Every hand-rolled importer is a seeder that
someone eventually re-runs as a refresh, rebuilding every row from a stale snapshot and reverting
whatever happened in between — closed-lost decisions, owner changes, close dates. It validates
clean afterwards, because it is clean.

```bash
S=$(python3 "<project>/.sales-system/find_scripts.py") || exit 1
python3 $S/crm_sync.py --plan    <project> --registry opportunities   # what to select
python3 $S/crm_sync.py --seed    <project> --registry opportunities --json-file recs.json
python3 $S/crm_sync.py --refresh <project> --registry opportunities --json-file recs.json
```

`--seed` is first load only and refuses to run against a registry that already has rows.
`--refresh` is a field-level merge: it writes only columns the schema marks `owner: crm`, so
`notes`, `health`, `risk_flags` and every derived column survive it, and it never renumbers an ID.

Pull per `scope` — the user's deals, or the team's from `00-Config/team.csv` — applying the
profile's `default_filter`, and skipping anything in `ignore_fields`. For a large book, have the
user export a report to `07-Opportunities/import/` and use `--ingest` rather than pulling several
hundred records through the connector one at a time.

Recompute `risk_flags`, `close_plan_gaps`, and `days_in_stage` after every refresh; they're
derived, so stale values are worse than absent ones. Where the contacts registry exists, run
`contacts_sync.py --rollup <project>` too, so `contacts_attached` and `contacts_engaged` match it.

**Check for drift before reporting anything**, especially before a pipeline review or forecast:

```bash
python3 $S/csvguard.py --verify-sync <project> --registry opportunities --crm-json snapshot.json
```

DRIFT means someone else changed the CRM — refresh to accept, or push if the local value is
right. AHEAD means a local change was never pushed and the CRM is currently wrong. CONFLICT
means both moved; show both and ask, per `CONVENTIONS.md` §7.

Report movement, not just totals. "Pipeline is $2.4M" is nearly useless on its own. "Pipeline is
$2.4M, up $180K — two new deals in, Globex slipped out of the quarter" is what someone wants.

### Pipeline review

The most-used operation. Don't print the registry — that's what the CRM is for. Structure it:

1. **What moved** since last look — new, advanced, slipped, closed.
2. **What's at risk** — by flag, worst first, with the specific evidence and a suggested action.
3. **What needs a decision** — deals where the honest answer is "this isn't real, move it out."
4. **Coverage** against quota and the remaining quarter, if config has the number.

Be willing to say a deal is dead. Sellers keep deals open past the point of belief because closing
them lost feels like failure, and a system that colludes in that is worse than no system. Say it
kindly and with evidence — "no activity in 31 days, close date pushed three times, single-threaded"
— and let them decide.

Under `team` scope, break out by owner and surface distribution problems: a rep whose whole number
sits in one deal, a rep with no new pipeline this month, deals with no owner. Aggregate health hides
exactly the things a manager needs.

### Update

Update the row, append to the account note, recompute derived fields, set
`sync_status = pending-push`, and mention unpushed changes at the end.

When a stage advances, check whether the close plan supports it. Advancing to a late stage with no
economic buyer named is worth one sentence of pushback — not a refusal, just a flag. The rep may
know something the CRM doesn't.

When a close date moves, increment `close_date_pushes` and record `previous_close_date`. Ask why
once, briefly, and record the answer in the note. That history is what makes the next slip legible.

### Close won or lost

**Won:** set stage, fill contract dates and term, and offer to create the customer row in
`02-Context/Customers/customers.csv` and a renewal row in `08-Renewals/renewals.csv` if that module
is on. A closed-won deal with no renewal tracked is future revenue nobody owns.

**Lost:** require a reason from the org's picklist and capture what actually happened in
`loss_notes`. Loss reasons are the highest-value data in the whole system and the most likely to be
filled in carelessly — "Price" is almost never the whole truth, and a note saying "we were 15% high
and the champion left in week three" is worth more than the picklist value.

If losses cluster — one competitor, one loss reason, one source, one segment — say so. That pattern
is invisible from inside individual deals and it's the thing worth escalating.

### Raise tasks

Read `01-Tasks/task-rules.csv` and honour the caps. Deal tasks should name the deal and the reason:
"Multi-thread Acme — single contact at Negotiate, $120K" beats "follow up on Acme."

Set `related_type = opportunity` and the ID, fill `why`, and pick a `verify_by` that matches the
work: `email-sent` for outreach, `calendar-event` for a meeting, `crm-field` for a data fix.

Prefer few. A pipeline review that raises fifteen tasks has raised none.

---

## Judgement

Pipeline conversations reward directness. The person already suspects which of their deals aren't
real; what they need is someone willing to say it with evidence, and to be equally clear about which
deals genuinely are worth the week's effort.

Avoid two failure modes. The first is cheerleading — reporting a healthy pipeline because the total
is large while three flags sit unmentioned. The second is indiscriminate pessimism, flagging
everything until the flags mean nothing. Both end with the person ignoring the output.

When the data can't support a conclusion, say so. "Six deals have no activity logged at all, so I
can't tell whether they're stalled or just not being tracked" is a genuinely useful sentence.

