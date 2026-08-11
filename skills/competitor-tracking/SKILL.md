---
name: "competitor-tracking"
description: "Track named competitors and build battlecards grounded in your own win/loss record and recent market news. Maintains a competitor registry, computes win rates and trends from the opportunity pipeline rather than opinion, surfaces market signals about each competitor, flags battlecards made stale by specific events, and writes cards reps can actually use. Use whenever the user mentions a competitor by name, asks who they're up against, wants a battlecard or competitive positioning, asks how to beat or displace someone, asks what their win rate against a competitor is, asks what a competitor has been doing lately or whether they changed pricing or launched something, asks why deals are being lost to competition, or wants to add or research a competitor."
---

# Competitor Tracking

Most competitive intelligence is fiction: a deck written from the rival's website, listing
weaknesses nobody verified, that gets a rep ambushed the first time a buyer pushes back.

Two things make this module different. The win/loss numbers come from **your own closed deals**, and
the "what changed" comes from **dated market signals**. A battlecard saying "we win on X" is a claim.
One saying "we've won 11 of 17, the losses cluster on price in Enterprise, and they shipped a
capability last week that blunts our main win theme" is something a rep can act on.

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`.
2. Read `.sales-system/CONVENTIONS.md`.
3. Read `00-Config/config.md` for `scope`, and `.sales-system/crm-profile/field-map.json` —
   especially the `competitors` block.
4. Repair the registries:

```bash
python3 <project>/.sales-system/scripts/csvguard.py --check-all <project>
```

Competitors live in `04-Competitors/competitors`. Battlecards in
`04-Competitors/Battlecards/<name>.md`. Research in `04-Competitors/Research/`.

---

## Competitor news lives here, not just in the market log

Market tracking logs signals; this module is where competitor signals become useful. Every signal
about a tracked competitor carries `competitor_id` and a `competitive_impact`. On every run, pull
`03-Market/signals` where `competitor_id` matches and recompute:

| Column | What it tells you |
|---|---|
| `last_signal_date` | When they last did something worth noting |
| `signals_90d` | How active they've been. A quiet competitor and a busy one need different attention |
| `signals_since_battlecard` | Signals logged since `last_researched` |
| `latest_signal` | Headline and date, so the registry reads without opening the market log |
| `open_impacts` | Distinct `competitive_impact` values not yet reflected in the card |

**`signals_since_battlecard` is the staleness measure that matters.** A card isn't out of date
because time passed; it's out of date because specific things happened. Non-zero on a `Primary`
competitor means refresh before the next call against them, and say which events forced it.

`competitive_impact` says what actually changed about selling against them: positioning, pricing
pressure, a new capability, a weakness exposed, funding, leadership. `No impact` is valid and
common — most competitor news changes nothing, and recording that is what stops the flag becoming
noise.

**Watch for the impact that invalidates a win theme.** If a competitor ships something that
neutralises your main differentiator, the battlecard is now actively misleading — a rep leading with
that theme will be corrected in front of a buyer. Treat it as urgent rather than as an update.

If a signal about a competitor has no `competitor_id`, set it. That's how the link survives; an
untagged signal is invisible here no matter how relevant.

---

## Where competitive signal lives in deals

Read the profile's `sources_on_opportunity` before parsing. Typically:

**A free-text field.** Expect misspellings, several names per cell, prose. Match on `name` plus
`aliases`, case-insensitively. A competitor with no aliases recorded silently under-counts, so add
spellings as you find them in real records.

**A structured picklist** — where the trap is. Fields like "technology stack" routinely **mix
competitors with integrations**. Treating every value as a competitor invents a rivalry with Jira
and makes every number wrong. The profile lists which values are which; use it.

**A loss reason** with a competitive value — the strongest signal available, recorded deliberately
at the moment of losing.

**An account-level flag** that the customer already runs a competitor. Displacement, not greenfield.

If the CRM has a competitor child object and this org populates it, prefer it over parsing text.

---

## Derived columns are computed, never typed

All the deal counts, rates, trends, and the signal columns are recomputed each run. Anything typed
there is gone at the next refresh.

### Be honest about the sample

Sales teams don't have big competitive samples, and a percentage from four deals is noise wearing a
suit. Set `win_rate` only above a meaningful decided sample — five closed deals is a reasonable
floor — and show the sample size next to it. Below that, put raw counts in `sample_note` and leave
the rate blank. "2 of 3" is honest; "67%" is a fabrication with a decimal point.

Same for `trend`: comparing two quarters of three deals produces a direction that's pure noise.
`Too few deals` is a legitimate value.

A deal can name several competitors. Count it against each, and say totals will exceed the deal
count rather than letting someone add them up wrong.

---

## Battlecards

Read in the ninety seconds before a call, or during one. Structure for that.

```markdown
# <Competitor> battlecard
Updated <date> · Our record: <plain language, with sample size>

## What changed recently
Signals since this card was last written, newest first, with what each changes.
Omit the section entirely when nothing has changed — an empty heading is noise.

## In one line
## When you're against them, do this
## Questions that expose the gap
## What they're genuinely good at
## Where we lose to them, and why
## Do not say
## If the buyer says "<their strongest claim>"
```

Four sections carry most of the value:

**"What changed recently."** Straight from the signals. This is what makes the card feel current and
is the reason a rep opens it again rather than relying on memory.

**"What they're genuinely good at."** A card claiming a competitor has no strengths is worthless —
the buyer has already seen the demo. Naming a real strength is what makes everything else credible.

**"Where we lose to them, and why."** From actual loss reasons. Tells a rep when to qualify out,
which saves more time than any win theme.

**"Do not say."** Claims that are wrong, stale, or legally risky. A rep repeating an outdated claim
loses credibility permanently and can create real liability. When a signal shows a competitor has
closed a gap, **the old win theme moves into this section** — that migration is the single most
valuable thing this module does.

Write from `02-Context/Messaging/` so the language matches how the company actually sells.

---

## Researching a competitor

Research fills the qualitative columns; numbers come from the pipeline and signals.

Cover what they say about themselves in their own words, pricing where public, recent launches and
funding, hiring, and their positioning against you if they publish one.

Check `03-Market/signals` first — something may already be logged. Then add a market watchlist entry
so future changes get caught, linking via `watch_id`. A competitor with no watch entry will keep
surprising you.

Set `last_researched` when done; that's what resets `signals_since_battlecard`.

**Distinguish what they claim from what's verified.** A vendor's site is a source for their
positioning, not their capability. Where you're relying on their marketing, say so — that's exactly
what becomes a "do not say" entry later.

---

## What to actually do

### Refresh

Recompute deal-derived and signal-derived columns, update aliases from new spellings, and report
what changed: presence rising, a win rate moving once the sample got big enough to trust, new
signals against a `Primary` competitor, cards now stale.

New names in deal records that aren't in the registry are the most useful output of a refresh —
competitors you're meeting without knowing it.

### Report

Lead with what changed and what it implies. A ranked table of every competitor is reference
material, not analysis. Under `team` scope, look for reps losing to one competitor
disproportionately — usually a coaching gap, invisible in aggregate numbers.

### Prepare for a specific deal

The highest-value use. Read the opportunity, the account notes, the battlecard, and any signals
since it was written. Give three things: what usually works against them, what to watch on *this*
deal given its stage and history, and the questions to ask.

If a signal has invalidated a win theme, say so before anything else. Check whether the account
already runs the competitor — displacement is a different conversation.

### Raise tasks

Read `01-Tasks/task-rules.csv` and honour the caps. Useful tasks are specific: refresh a card the
signals have overtaken, investigate a cluster of losses, research a name that keeps appearing.

Set `related_type = competitor` and fill `why`.

---

## Judgement

Two failure modes, both common.

**Wishful battlecards.** Every competitor weak, we win on everything. Reps try it once, get
contradicted live, and never open the file again. Credibility here is spent in a single meeting.

**False precision.** Percentages from tiny samples, trends from noise, confident claims sourced from
a competitor's homepage. Attaching a number to a guess makes it worse, because it travels into
forecasts as though it were measured.

When the honest answer is "we've met them four times and I can't tell you much," say that. It's more
useful than a fabricated win rate, and it points at the real fix — record the competitor on deals
more consistently.

