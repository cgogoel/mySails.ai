---
name: "weekly-brief"
description: "Produce the weekly review focused on patterns rather than tasks — trends visible across the week, market signals worth acting on, demand gen campaigns or content worth considering, meaningful competitor news, and major changes at key accounts such as a new executive at a target organization. Compares against last week to show movement rather than a snapshot. Use when the user asks for their weekly brief, weekly review, week in review, what happened this week, what trends they should know about, what changed in the market or with competitors, what is new at their key accounts, or wants to plan the week ahead."
---

# Weekly Brief

The daily brief is execution: what to do today. The forecast is the reckoning: are we making the
number. This is the one that answers **what's changing around us, and what should we do differently
because of it.**

That's a genuinely different job, and the reason it earns a place. Nobody rereads their week, so a
weekly brief that stacks seven daily briefs is dead on arrival. The value is entirely in patterns
that are invisible at one-day range and irrelevant at quarterly range.

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`.
2. Read `.sales-system/CONVENTIONS.md`.
3. Read `00-Config/config.md` — `scope` and **`brief_content`**, which records what this user wants
   in weekly versus daily versus forecast. Honour it; the emphasis below is the default, not a rule.
   Some orgs want pipeline movement here and some want it only in the forecast.
4. Read `00-Config/enabled-modules.md` — only report on modules that are on.
5. Repair the registries:

```bash
python3 <project>/.sales-system/scripts/csvguard.py --check-all <project>
```

6. **Verify the synced registries against the CRM** — `opportunities`, plus `leads`, `renewals`
   and `partners` where those modules are on:

```bash
python3 <project>/.sales-system/scripts/csvguard.py --sync-query <project>
# run each query through the CRM connector, then for each registry:
python3 <project>/.sales-system/scripts/csvguard.py --verify-sync <project> \
    --registry <name> --crm-json snapshot.json
```

The weekly is the right place for the slower version of this. A daily check catches what moved
overnight; a weekly one catches the pattern — a batch of records reassigned in an admin change,
a run of local edits that never pushed. **Report drift as a trend, not a list**: "16 renewals
moved to a different owner on Tuesday, all previously Dean's" is the finding. Sixteen individual
lines is the raw material for it.

Anything still AHEAD after a week means a push has been failing silently. Say so.

Briefs go to `09-Briefs/Weekly/YYYY-MM-DD-weekly-brief.md`.

---

## Read last week's brief first

`09-Briefs/Weekly/` holds the sequence. Without it you can only describe a state, and a state is not
a week. "Three deals are single-threaded" is a fact; "the same three deals have been single-threaded
for a month" is a finding.

Where a registry carries its own history — close-date pushes, stage-change dates, signal dates,
engagement trend — use it rather than diffing two snapshots.

---

## What belongs here

### Trends

The core section. Look for things true across the week that no single day would surface:

- Deals moving in a consistent direction, especially several at once
- Engagement shifting across the book — more accounts cooling than heating is a leading indicator
  worth naming before it shows up in the forecast
- Lead flow changing in volume or quality
- A stage where deals consistently stall
- Losses clustering on one reason, competitor, segment, or source
- Response rates rising or falling

Two data points are not a trend. Where movement is within normal noise, say so — that's more useful
than a confident story and it protects the credibility of the weeks when something genuinely is
moving.

### Market signals worth acting on

From `03-Market/signals`, filtered hard. Not a news digest — market tracking already keeps one. Only
signals that change what someone should do, with the "so what" and the specific account or deal
affected.

Regulatory changes with deadlines, incidents in the customer base, funding at a prospect: each worth
a line and a suggested action.

### Changes at key accounts

**Explicitly worth its own section.** Organisational change at a tracked account is one of the
highest-value things a seller can know and one of the easiest to miss.

A new CIO at a target agency, a champion promoted or departed, a reorg, an acquisition, a security
incident, a public commitment to a programme you sell into. Check signals, CRM activity, and the
accounts in `07-Opportunities/`, `08-Renewals/`, and `02-Context/Customers/`.

Say what it means for the specific deal, not just that it happened. A new CIO resets priorities and
usually re-opens vendor decisions — that's an opportunity on a stalled deal and a risk on a
committed one, and which it is depends on where the deal stands.

### Competitor news

From `04-Competitors/`: new signals against tracked competitors, and — importantly — any battlecard
the news has overtaken. `signals_since_battlecard` being non-zero on a Primary competitor is a
finding: someone will walk into a call this week with a card that's out of date.

Flag competitive presence rising in deals. Don't report competitor funding as though it were a
threat by itself; say what it changes about how they'll behave.

### Demand gen and content worth considering

Campaigns that matured enough to judge, and — from `05-Demand-Gen/content-opportunities` — signals
where the company has standing to comment but hasn't yet. A perishable angle unused for a week is
about to expire, and this is the last useful moment to say so.

Also: drafts sitting in review for a week. That's a process problem worth naming.

### Renewals and pipeline

How much of this belongs here depends on `brief_content`. Where the forecast covers pipeline
position, keep this to what changed and what it implies, and don't duplicate the numbers.

Renewal exposure entering the window, and conversations now overdue, are worth a line here even when
the forecast covers them — they're time-sensitive and easy to defer.

---

## What does not belong here

Say this to yourself before writing: today's tasks, individual meeting prep, and a full pipeline
table all belong elsewhere. Pulling them in is the main way this brief becomes unread.

---

## Team scope

Under `scope: team` this becomes a manager's document. Lead with **distribution problems**, not
aggregates:

- A rep whose number depends on one or two deals
- A rep with no new pipeline this month
- A rep with no logged activity this week — check CRM activity, since their mailbox isn't visible
- Deals or renewals with no owner
- Someone losing to one competitor disproportionately, which is coaching rather than product

"The team is 68% to number" is a status. "Dana is at 40% with everything on one deal that's slipped
twice" is a conversation.

Be careful with tone. This is read by someone who manages the people named in it. State what's
observable and what it might mean, and leave room for the rep knowing something the CRM doesn't.

---

## Structure

Skip empty sections rather than printing "None."

**The week in three lines** — what changed, what it means, what next week should be about. Written
last, read first. Most people won't get further, so it has to stand alone.

**Trends** — with the evidence.

**Worth acting on** — market signals, account changes, competitor moves, expiring content angles.
Each with the affected deal and a suggested action.

**What moved** — brief. Deals, leads, renewals, campaigns.

**Next week** — three to five specific things, drawn from open tasks and the above, not invented.

Name accounts and people. Give numbers a shape. Say what you'd do.

---

## Tasks

Read `01-Tasks/task-rules.csv` and honour the caps. This is the second-biggest task-generating
moment after the daily, and the temptation is to convert every observation into one.

Prefer a handful that shape the week. Where a pattern needs a decision rather than an action — "we
keep losing on price in Enterprise" — say it and don't manufacture a task.

---

## Scheduling

Friday afternoon or Monday morning, and the choice matters: Friday captures the week while it's
fresh and gives the weekend to think; Monday lands when someone can act but competes with the inbox.
Ask rather than assuming. If there's a weekly pipeline meeting, land it a few hours before.

---

## Judgement

**Comprehensiveness** is the main failure. Every module has something to say, and letting each speak
produces a report nobody finishes.

**False narrative** is the subtler one. Weekly cadence invites storytelling, and a random week is
easy to explain as a trend. Resist it; a quiet week honestly reported as quiet is a good brief, and
saying so once buys credibility for the week something real happens.

