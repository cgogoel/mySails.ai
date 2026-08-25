---
name: "forecast-update"
description: "Produce a forecast update as an HTML dashboard on whatever cadence the user runs — weekly, monthly, quarterly, or annual. Builds only the tracks the user actually runs: new business always, renewals and partners only when those modules are enabled, kept as separate lines under each company and personal goal since the work is not comparable. Shows progress since the last forecast of the same cadence, tracks renewal coverage toward 100% where relevant, and ranks new-business deals by engagement from Heating to Cooling with a summary and next step. Use whenever the user asks for a forecast, forecast update, forecast call prep, commit and upside, gap to quota, coverage, how they are pacing against their number, or which deals are heating up or going quiet."
---

# Forecast Update

A forecast answers one question: **are we going to make the number, and what would change the
answer.** Everything else serves that.

It differs from the briefs in cadence and altitude. The daily brief is today's actions; the weekly
is trends and signals. This is the periodic reckoning against goals, produced as an HTML dashboard
because it gets read on a forecast call and referred back to afterwards.

## Who reads this

**The forecast goes to the sales team.** None of them work in this folder, and most have never
seen it. That one fact settles most of what follows: what reaches the page, what language it
uses, and what stays behind.

Nothing project-internal appears on the rendered dashboard:

| Keep out | Use instead |
|---|---|
| `OPP-`, `REN-`, `FCST-` record IDs | The account name |
| Registry, folder, schema, `csvguard`, `crm_sync`, snapshot file names | Nothing — the reader does not need the plumbing |
| CRM sync drift, `sync_status`, `last_synced`, pending pushes | Nothing. Fix the data, or record it in the snapshot row |
| Data-quality findings about how the folder is maintained | The snapshot `notes` column |
| "since the last forecast this system produced" | "since Monday 17 August" |

**Keeping something off the dashboard is not losing it.** The snapshot row is the internal record:
it is where the next run reads from, and nobody outside sees it. Anything the next forecast needs
to know — an exclusion and why, a check that could not run, a figure nobody could total — goes in
`notes`. Anything *you* need to know goes to you in chat, where the rest of the team is not
standing.

Say dates as dates. "Since Monday 17 August" is a sentence anyone can check; "since the last
forecast" means something only to whoever ran it.

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
3. Read `00-Config/config.md` for `scope`, fiscal calendar, and forecast cadence.
4. **Read `00-Config/enabled-modules.md`.** This decides which tracks the forecast has — see below.
5. Read `.sales-system/crm-profile/field-map.json` — `amount_field` and any caveat on it, the
   forecast-category mapping, activity query bounds.
6. Repair the registries:

```bash
python3 "$S/csvguard.py" --check-all <project>
```

6a. **Bring the currency conversion up to date, before any total.** Every figure in this
   forecast is a sum, and a sum is only meaningful in one currency (CONVENTIONS §8a).

```bash
python3 "$S/fx.py" --convert <project>
```

   Open records reconvert at the current rate; closed ones keep the rate they were frozen at, so
   a settled quarter reads the same number every time. A non-zero exit means some records could
   not be converted — **they are missing from every total on the dashboard**, so carry the count
   into the payload as `unconverted_records` and name them in the narrative rather than
   presenting a total that quietly excludes them. If the rate table is stale or empty, pull it:
   query the CRM's currency table through the connector and hand it over as
   `{"base":"USD","convention":"units-of-currency-per-base","rates":{"EUR":0.91}}` to
   `fx.py --pull`. In Salesforce that is
   `SELECT IsoCode, ConversionRate, IsCorporate FROM CurrencyType WHERE IsActive = true` — and
   `ConversionRate` there is the **reciprocal** of the multiplier, which `--pull` inverts for you.
   Do not invert it yourself as well. A folder with no CRM uses `fx.py --fetch` instead, which
   takes rates from a public source.

   `--convert` also warns when the rate table is past its staleness window. **Do not build a
   forecast on a stale rate table without saying so in the narrative** — the totals will look
   exactly as authoritative as they would on fresh rates. If `fx.py --check` reports drift between
   the CRM's rates and the market, that belongs in the forecast too: pipeline that appears to have
   grown because the CRM's euro rate is a year out has not grown.

7. **Verify the pipeline still matches the CRM.** This comes before any arithmetic, because
   the failure it catches is invisible afterwards — a clean registry that quietly disagrees
   with the system of record produces a confident, wrong forecast.

```bash
python3 "$S/csvguard.py" --sync-query <project> --registry opportunities
# run that query through the CRM connector, write the result to snapshot.json
python3 "$S/csvguard.py" --verify-sync <project> \
    --registry opportunities --crm-json snapshot.json
```

Repeat for `renewals` where that module is on. **Report what it finds to the user, not on the
dashboard.** Sync state is plumbing: a rep reading the forecast can neither act on it nor judge
it, and it makes the page read as tool output.

- **DRIFT** — someone changed the CRM. Material drift changes the numbers, so it gets resolved
  before the page is built rather than annotated onto it; a by-rep split computed over stale
  owners is wrong in exactly the way nobody checks.
- **AHEAD** — changed here, never pushed. The CRM is currently wrong and the forecast call
  will be run from the CRM.
- **CONFLICT** — show both values and ask.

Resolve it with the user, then rebuild. `crm_sync.py --refresh` accepts the CRM's version, and
**only the records you hand it are touched** — rows absent from the payload are left exactly as
they are, so accepting eleven drifted records is a safe, narrow operation. Pass `--partial`
alongside `--dry-run` or `--verify` when the payload is a subset, or every row you left out is
reported as missing from the CRM and the one real finding drowns in it. Where `crm_last_modified`
is empty across the registry the direction of a change cannot be derived at all; one full refresh
stamps that baseline and it resolves itself from then on.

**In an unattended run, never refresh on your own judgement.** Accepting drift means accepting
someone else's edit over the team's. Build on the data as it stands, put the drift count and the
records affected in the snapshot `notes`, and tell the user what is waiting on a decision. If the
check could not run at all, say so to the user and record it in `notes` — and do not present the
numbers as verified. Silence reads as confirmation.

Snapshots live in `09-Briefs/Forecast/snapshots`; dashboards in `09-Briefs/Forecast/`.

---

## Step 1: Decide which tracks exist

**Build only the tracks the user actually runs.** Plenty of reps carry a new-business number and
nothing else; showing them an empty renewal section, or worse a renewal section built from nothing,
makes the forecast look broken and wastes the space.

| Track | Include when |
|---|---|
| **New business** | Always. This is the core. |
| **Renewals** | Renewals module enabled **and** `08-Renewals/` has contracts in the period |
| **Partners** | Partner module enabled **and** deals carry `partner_id` |
| **Expansion** | Only if the org treats it separately — ask once and record it |

If only new business applies, produce a **single-track forecast**: omit the track `label` and pass
one headline card group. The renderer drops the redundant headings, and the result reads as one
clean forecast rather than a two-column layout with a hole in it.

If renewals are enabled but there's nothing due in the period, say "no renewals this period" in one
line rather than rendering an empty tracker.

## Step 2: Never blend the tracks you do have

Where two or more tracks exist, keep them separate everywhere — headline numbers, goals, and the
deal table.

The work is not comparable. A renewal at 90% probability and a new deal at 90% require completely
different effort and carry different risk. Blending hides both directions at once: a strong renewal
quarter masks weak new business, and a weak renewal quarter reads as a pipeline problem when it's a
retention problem.

- **Headline numbers** — one labelled group per track. New business: commit, best case, closed, new
  pipeline. Renewals: secured, coverage, at risk, lost.
- **Goals** — each owner's goals split by the `track` field on `00-Config/goals`. A single blended
  revenue goal should be the exception; if one exists, still show the split beneath it.
- **Deal detail table** — **new business only**, always. Renewals live in their own tracker;
  partner deals appear in the new-business table with the partner named, not as a separate ranking.

Where two tracks move in opposite directions, **say so in the headline.** That's the single most
useful observation a split forecast produces and it's invisible in a blended one.

## Step 3: Confirm the goals

**A forecast against the wrong number is worse than no forecast.**

On first run, ask for both levels — company and personal or team — and **only for the tracks that
apply**. Don't ask a new-business-only rep about renewal retention; it signals the system isn't
paying attention.

Capture metric, track, period, target, dates into `00-Config/goals`. Set `last_confirmed` and
`confirm_cadence` (quarterly default), then check freshness on every run and ask once, briefly, if
stale.

When a target changes, don't overwrite: mark the old row `Superseded`, record `original_target`,
`revised_date`, `revision_reason`, and create the new one. A goal that moved mid-quarter is part of
the story.

With no goals at all, report absolute numbers and label them as such.

## Step 4: Work out the comparison period

Compare like with like — a weekly against the previous weekly. Read
`09-Briefs/Forecast/snapshots` filtered to the same `cadence`. If there's no prior snapshot of this
cadence, say it's the first rather than substituting another cadence.

### Cadence changes what counts as meaningful

| Cadence | Include | Leave out |
|---|---|---|
| **Weekly** | Meetings held, replies received, quotes sent, stage moves, per-deal engagement | Long-run trends |
| **Monthly** | The above aggregated, plus conversion and cohort movement | Individual email counts |
| **Quarterly** | Stage conversion, win rates, segment patterns, forecast accuracy vs commit | Meeting counts |
| **Annual** | Attainment, growth, retention, structural shifts in revenue mix | Anything operational |

A quarterly opening with "6 meetings held" has buried its own point. **Longer cadences report only
what's meaningful** — "steady, no structural change" is a legitimate quarterly forecast.

## Step 5: Build the picture

### New business

Use the profile's `amount_field`; if it carries an unconfirmed caveat, surface that once,
prominently. Commit, best case, weighted, closed in period, gap to goal, coverage. Honour the
forecast-category API mapping — filtering on a display label rather than the stored value silently
drops a category.

**Sum `converted_amount`, never `amount`.** `amount` is the deal in its own currency and is the
right number to quote back to the customer and the wrong number to add up. Every total, weighted
figure, gap and coverage ratio on this dashboard is built from the converted column. A deal whose
`converted_amount` is blank is not a zero — it is a deal nobody can total, and it belongs in the
narrative, not silently in the denominator. Goal attainment compares against `converted_target`
for the same reason.

Put the currency picture in the payload so the dashboard can state it: `base_currency`,
`currency_mix` as `{"USD": 12, "EUR": 3}` counted across the records in scope, `rates_as_of` from
the newest `effective_from` in `00-Config/fx-rates`, and `unconverted_records`. A converted total
that does not say it is converted is as unreadable as one that never converted.

Run the engagement scorer:

```bash
python3 "$S/engagement.py" --score <project> --window 14 --apply
```

It weights **inbound above outbound**: outbound volume measures effort, replies and meetings measure
interest. A deal with five chasing emails and no reply will not read as heating up. Use
`--explain <OPP-id>` when a ranking looks wrong — showing the working is what makes the column
trusted.

#### Whose fiscal year is this?

Before scoring engagement or questioning a close date, work out which fiscal calendar the
**customer** runs on. Ours is in `00-Config/config.md`; theirs usually is not, and the two are
routinely different — a US federal book runs to 30 September while the company's own year runs to
31 December, and both are in play in every forecast.

This matters because the scorer counts contact in a trailing window and cannot see a calendar.
"Waiting for the new fiscal year", "funds not available until FY27", "standby until the new FY" in
an account whose year turns over shortly is a **timing fact, not disengagement** — especially where
the technical work is already done. A deal whose evaluation closed with no open questions and whose
procurement opens in about thirty days is heating up, however quiet the inbox has been.

So where the record shows a completed evaluation plus a known procurement date, **the date beats
the activity window.** Say which fiscal year you are reading and what it implies — "federal FY27
money releases 1 October, about 30 days out" — and set the close date to match rather than pushing
the deal out of the period. Where the calendar is unclear, ask; do not assume it is ours.

### Renewals — only if the module is on

Measured against **100%**. Every renewal not secured is leakage, not a deal you didn't win.

**First, drop the renewals that were never renewals.** A renewal line exists because something was
won before and is now due again. Where there is no prior-term win behind it — no `original_opp_id`
pointing at a closed-won deal, and no other evidence the customer ever bought — it is not a
renewal. `08-Renewals` produces these on its own, because it is built from contract end dates on
opportunities that may never have closed.

Exclude them from the renewal track **entirely — from the denominator as well as the loss column.**
A contract that never existed was never due, so counting one as lost is wrong twice: it overstates
losses and it drags coverage down against a target that was never real. Then:

- Record the exclusion and the reason in the snapshot `notes`, or a later run will helpfully
  reinstate it.
- **Restate the prior period on the same basis before showing movement.** Comparing a corrected
  period against an uncorrected one manufactures a swing that never happened, which is worse than
  the error it fixes.

From `08-Renewals/`: value due in the period, secured, at risk, and where the number sat at the last
forecast so movement shows — from `converted_current_value` and `converted_proposed_value`, on the
same rule as new business.

Called out by name: **at risk**, from the renewals module's own flags with value and reason; and
**resolved since the last forecast**, with what it did to the tracker. "US Army renewed five weeks
early — coverage moved from 20% to 50%" is the sentence someone repeats on the call.

An early renewal is good news and should read that way. A renewal lost deserves more attention than
a new deal lost of the same size, because it was already earned.

### Partners — only if the module is on

Partner-attributed pipeline as its own cut, with **sell-through and sell-with separated** and
sell-through discounted more heavily than direct. Say plainly that you're discounting it and why.

## Step 6: Assemble and render

```bash
python3 "$S/forecast_dashboard.py" \
  --render <payload.json> --out 09-Briefs/Forecast/YYYY-MM-DD-<cadence>-forecast.html
```

`headline_cards` takes a dict keyed by track — pass one key for a single-track forecast. Each period
takes a `tracks` list; the renewal track carries `renewal_tracker`. Sections nest by horizon, and
shorter sections drop out at longer cadences.

**Card values: a number is money, a string is printed as written.** The renderer formats any
numeric `value` as full currency — `5627000` renders as `$5,627,000` — so counts and percentages
belong in the payload as strings: `"228"`, `"33%"`, `"12 deals"`. Do not pre-format currency
yourself and do not abbreviate anywhere: the dashboard prints full figures with separators
throughout, deliberately, because these numbers get read aloud and compared on a call and `$1.2M`
against `$1,165,674` is one number that reads as two. Deal entries may still carry `id`; it is not
rendered.

**Promote material quarter or annual movement to the alerts at the top**, naming which track moved.
Someone reading a weekly won't scroll to the annual section.

### The deal table — new business only

Ranked Heating → Cooling, identified by account name, with two written columns. Both are tightly
constrained, because this table is where a forecast most easily turns into an agent telling a sales
team what it thinks of their deals.

**"Where it stands"** — **countable facts only.** Stage, days in stage, close-date pushes and by how
much, days since the last recorded activity, the close date, and concrete dated events ("technical
evaluation closed 12 August", "quote sent 19 August"). Two or three sentences, every one of which
someone could check against the record. No judgement about whether the deal is real, no advice, no
adjectives grading the work.

**"Next step"** — the team's own `next_step` text, **verbatim**. Where the field is empty, print
`(none recorded)`. Never write a next step no human wrote: a large deal with no next step recorded
is itself the finding, and inventing one hides it.

Keep the *ranking* honest — a cold deal still ranks Cooling and the trend column still says so.
Let the numbers carry it.

Filter renewals out. If a renewal needs deal-level attention it belongs in the at-risk list with a
reason, not in an engagement ranking built for a different motion.

## Step 7: Record the snapshot

Write the row to `09-Briefs/Forecast/snapshots` — position by track, activity counts, renewal figures
where applicable, headline, `artifact_path`. This lets the next forecast say what changed and makes
forecast accuracy reviewable: what was committed in week one against what closed.

Offer that backward look at quarter end. Most teams never check whether their commits were right.

## Scheduling

Match the business rhythm and land it **before** the meeting it feeds. Offer quarterly and annual
runs too — those are the ones people mean to do and don't.

---

## Judgement

**Don't launder the number.** The pull is toward the version that sounds better — counting a deal as
commit because the quarter needs it, quoting created pipeline as revenue, letting renewals carry a
weak new-business quarter. A forecast's only value is being believed, and it's believed because it
was right when the news was bad.

**Separate what you know from what you think.** Closed-won is a fact. Commit is a judgement. Best
case is an upper bound, not a plan.

**Be specific about what would change the answer.** "We're short" is a status. "$188,000 short on
new business; Acme at $120,000 is the largest open deal in the period" is a forecast someone can
act on. Name the arithmetic, not the remedy — which deal to push is the team's call, and they make
it on the call.

**Report, don't grade.** The numbers and the ranking already carry the judgement. Prose telling the
team a deal is not credible, or handing them instructions, is the agent forming opinions about
other people's work, and it is the quickest way for a forecast to stop being read. Where you have a
real concern, bring it to the user in chat — not onto a page the whole team is reading.

When a period is genuinely uneventful, a short forecast saying so is the correct output.

