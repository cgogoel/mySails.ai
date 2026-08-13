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

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`.
2. Read `$CLAUDE_PLUGIN_ROOT/.sales-system/CONVENTIONS.md`.
3. Read `00-Config/config.md` for `scope`, fiscal calendar, and forecast cadence.
4. **Read `00-Config/enabled-modules.md`.** This decides which tracks the forecast has — see below.
5. Read `.sales-system/crm-profile/field-map.json` — `amount_field` and any caveat on it, the
   forecast-category mapping, activity query bounds.
6. Repair the registries:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/csvguard.py" --check-all <project>
```

7. **Verify the pipeline still matches the CRM.** This comes before any arithmetic, because
   the failure it catches is invisible afterwards — a clean registry that quietly disagrees
   with the system of record produces a confident, wrong forecast.

```bash
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/csvguard.py" --sync-query <project> --registry opportunities
# run that query through the CRM connector, write the result to snapshot.json
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/csvguard.py" --verify-sync <project> \
    --registry opportunities --crm-json snapshot.json
```

Repeat for `renewals` where that module is on. Then **open the forecast with what it found**,
above the numbers:

- **DRIFT** — someone changed the CRM. "16 opportunities changed owner since your last sync"
  is the first thing on the page, not a footnote; a by-rep split computed over stale owners
  is wrong in exactly the way nobody checks.
- **AHEAD** — changed here, never pushed. The CRM is currently wrong and the forecast call
  will be run from the CRM.
- **CONFLICT** — show both values and ask.

If drift is material, offer `crm_sync.py --refresh` and rebuild before continuing. If the
check couldn't run at all, say so in one line and label the numbers unverified — silence
reads as confirmation.

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

Run the engagement scorer:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/engagement.py" --score <project> --window 14 --apply
```

It weights **inbound above outbound**: outbound volume measures effort, replies and meetings measure
interest. A deal with five chasing emails and no reply will not read as heating up. Use
`--explain <OPP-id>` when a ranking looks wrong — showing the working is what makes the column
trusted.

### Renewals — only if the module is on

Measured against **100%**. Every renewal not secured is leakage, not a deal you didn't win.

From `08-Renewals/`: value due in the period, secured, at risk, and where the number sat at the last
forecast so movement shows.

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
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/forecast_dashboard.py" \
  --render <payload.json> --out 09-Briefs/Forecast/YYYY-MM-DD-<cadence>-forecast.html
```

`headline_cards` takes a dict keyed by track — pass one key for a single-track forecast. Each period
takes a `tracks` list; the renewal track carries `renewal_tracker`. Sections nest by horizon, and
shorter sections drop out at longer cadences.

**Promote material quarter or annual movement to the alerts at the top**, naming which track moved.
Someone reading a weekly won't scroll to the annual section.

### The deal table — new business only

Ranked Heating → Cooling, with two written columns:

**"Where it stands"** — two or three sentences of what actually happened: what moved, the last real
contact, what's missing from the close plan. From the record and activity, not restated from the
stage name.

**"Next step"** — one specific action. "Get the procurement contact named before Friday" beats
"follow up." Where the honest next step is to stop, say that.

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
case is a hope with a number attached.

**Be specific about what would change the answer.** "We're $188K short" is a status. "$188K short on
new business; Acme at $120K is the only deal that closes it and needs a procurement contact this
week" is a forecast someone can act on.

When a period is genuinely uneventful, a short forecast saying so is the correct output.

