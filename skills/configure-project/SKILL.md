---
name: "configure-project"
description: "Set up, reconfigure, or repair the sales management project folder. Interactive setup that confirms email/calendar/CRM connections, introspects the CRM to build a per-org profile, captures company and personal goals, sets whether registries are CSV or styled Excel, decides what goes in the daily versus weekly brief and on what cadence forecasts run, sets task automation posture, builds the folder structure, seeds the context library, and switches on the tracking modules wanted. Use whenever the user wants to set up, configure, initialize or reset their sales project, says the folder is empty, asks where something goes, wants to change their goals or brief content or forecast cadence, wants to switch registries between CSV and Excel, wants to refresh the CRM field mapping, or when another sales skill finds config.md missing or the profile stale."
---

# Configure Project

The front door to the sales management system. Every other skill reads what this creates, and when
setup is half-finished downstream skills degrade quietly rather than failing loudly.

The person running this sells for a living. They should finish with a folder they can open in
Finder, browse without a guide, and edit without fear.

## Orient first

The **project root** is the connected folder containing `.sales-system/`. Read
`<project>/.sales-system/CONVENTIONS.md` — the rulebook the rest of this assumes.

Then check `00-Config/config.md`:

- **Missing** → full setup, every phase.
- **Present** → reconfigure. Show current setup (company, scope, storage format, goals, brief
  content, automation, enabled modules, connections), ask what to change, run only those phases.
  Never silently overwrite — show before/after.

Ask in small batches. Show progress. Let them skip things. A folder they can grow into beats one
abandoned at question fourteen, so if they're flagging, offer to stop at a working minimum.

---

## Phase 1 — Connections

Probe rather than interview. Look for email, calendar, CRM, meeting transcripts, chat, enrichment.
Report in plain language, ask about gaps, and record everything in `00-Config/connections.md`
**including what was absent**, so later skills don't retry dead tools.

Flag if **email is missing** — without it tasks can't be drafted, sent, or verified as done, and
engagement scoring loses its strongest signal.

### CRM sync posture

Write to config: pulls automatic, **pushes never automatic** (field-by-field diff, explicit yes),
conflicts always surfaced, everything logged to `00-Config/sync-log.csv`. Ask which objects are in
scope and about validation rules that make writes fail.

## Phase 2 — Build the CRM profile

**What makes a generic template fit a specific company.** Everything shipped is identical for every
user; the org's specifics live in `.sales-system/crm-profile/`. Skip entirely if no CRM.

Fetch each in-scope object's schema and read it properly — real orgs replace standard picklists
wholesale, and half the custom fields are integration-owned. **Use a subagent to extract**, asking
for exact values not summaries: every picklist's values in order, custom fields with types, what's
required on create, and any admin-authored description or help text. That last is disproportionately
valuable — it's where integration ownership and business rules are documented.

Write four files: `picklists.json` (real values — these also become the Excel dropdowns),
`field-map.json` (column mapping, `required_on_create`, `safe_to_push`, `never_push` **with reasons**,
`shared_fields`, `ignore_fields`, `gotchas`), `contactability.json` (what blocks contact and on which
channel — look for channel-specific opt-outs), and `profile.md` (the narrative version).

Confirm what you found, especially anything surprising. Say which objects you profiled and which you
didn't.

## Phase 3 — Goals

**A forecast against the wrong number is worse than no forecast.** Ask for both levels:

> What are you measuring against?
> - **Company goals** — the number the business carries this year and this quarter
> - **Personal or team goals** — your own quota, or your team's
>
> Either or both. I'll frame every forecast against them and check back each quarter.

Capture metric, period, target, dates into `00-Config/goals`. Set `last_confirmed` and
`confirm_cadence` (quarterly default) — goals move mid-year, and an unconfirmed goal quietly makes
every forecast wrong. When one changes later, mark the old row `Superseded` rather than overwriting;
a goal that moved is part of the story.

For renewals, the goal is **100%** — every renewal not secured is leakage, not a deal lost. That's
tracked separately in the forecast rather than as a currency target.

## Phase 4 — Storage format

Registries can be plain CSV or styled Excel workbooks.

| | `csv` | `xlsx` |
|---|---|---|
| Opening it | Raw text | A finished-looking table |
| Editing | Excel mangles dates and IDs; the guard repairs | Real typed cells, nothing to mangle |
| Data entry | Type and hope | Dropdowns of the org's real picklist values |
| grep / diff | Yes | No |

**Recommend `xlsx` when a CRM profile exists** — the dropdowns come from their real picklists, so an
invalid stage genuinely can't be typed. Recommend `csv` with no CRM, or if they'll grep the folder.

Write `storage_format:`. Plumbing (sync log, indexes) stays CSV either way via `browsable: false`.
Changing later is safe: `--convert-all <project> --to xlsx`, originals kept.

## Phase 5 — Scope

The most consequential answer, because it changes every CRM pull and every roll-up:

> Track just your own leads and deals, or your whole team's?

**`individual`** — pulls filter to their user ID, briefs speak in first person.
**`team`** — also create `00-Config/team`, pulling the roster from the CRM role hierarchy rather
than making them type names, capturing each rep's CRM user ID. Confirm the list; hierarchies keep
people who've left. Under team scope, roll-ups break out by rep and briefs surface rep-level
anomalies.

Someone in an ops or management role often wants `team` even though they'd describe their own quota
when asked. Record as `scope:`.

## Phase 6 — Briefs and forecast cadence

**Three outputs with different jobs, and the split between them is driven by each org's business
rhythm — so ask rather than assuming.**

| | Answers | Default cadence |
|---|---|---|
| **Daily brief** | What do I do today, and am I ready for my meetings | Weekday mornings |
| **Weekly brief** | What's changing around us, what should we do differently | Friday PM or Monday AM |
| **Forecast update** | Are we making the number, what would change the answer | Matches the forecast meeting |

Present the default split and let them move things:

> **Daily** — tasks due, follow-ups owed, today's meetings with attendee research and prep
> **Weekly** — trends, market signals, competitor news, changes at key accounts, content worth writing
> **Forecast** — pipeline against goals, renewal coverage, deals ranked by engagement
>
> Some people want pipeline movement in the weekly; others only in the forecast. Where would you
> put it?

Record as `brief_content:` in config — a short list per brief. Every brief skill reads it and
honours it over its own defaults.

**Ask when the forecast call is** and schedule the forecast to land a few hours before it. A
forecast produced after the meeting is a record, not a tool. Record `forecast_cadence:` and
`forecast_day:`. Offer quarterly and annual runs too — those are the ones people mean to do and
don't.

## Phase 7 — Task automation posture

| Level | What happens | Good for |
|---|---|---|
| `manual` | Raises the task, you do it | Calls, meetings, judgement calls |
| `review` | Writes the draft, you approve | Almost everything customer-facing |
| `auto` | Acts, then reports | Internal, reversible, low-stakes |

Recommend **everything at `review`**: drafting is where most of the value is, and a week of watching
what the system *would* have sent is the cheapest way to learn whether you'd trust it to send.

If they want `auto` on customer email immediately, say plainly that a misjudged follow-up is a
relationship cost that can't be undone — then if they still want it, apply the fences from
`CONVENTIONS.md`: never first contact, never pricing or commitments, `daily_cap` on every rule,
everything reported at the top of the next brief, delayed send where possible.

Seed the registries (omit the extension and the guard applies the project's format):

```bash
python3 <project>/.sales-system/scripts/csvguard.py --init <project>/01-Tasks/tasks --schema tasks --project <project>
python3 <project>/.sales-system/scripts/csvguard.py --init <project>/01-Tasks/task-rules --schema task_rules --project <project>
mkdir -p <project>/01-Tasks/Drafts <project>/.sales-system/cache
```

Populate starter rules matched to enabled modules, wording triggers with the org's own picklist
values — a rule referencing a status the CRM doesn't have never fires.

## Phase 8 — Folder structure

Always:

```
README.md              00-Config/   (config, connections, goals, team, sync-log, enabled-modules)
01-Tasks/              02-Context/  .sales-system/
```

Then only the modules enabled in Phase 10:

```
03-Market/   04-Competitors/   05-Demand-Gen/   06-Leads/   07-Opportunities/
08-Renewals/ 09-Briefs/ (Daily, Weekly, Forecast)   10-Content/   11-Partners/   99-Archive/
```

Tasks sit at `01-` because it's opened daily. The root `README.md` is the most important artifact
for making the folder navigable — write it in their words, name their company, say which format the
data is in and that it's safe to edit.

## Phase 9 — Context library

`02-Context/Company/`, `Messaging/` (copy any positioning doc verbatim **and** write a distilled
`messaging-summary.md` — a 40-page deck is too expensive to load on every request), `Templates/`,
and `Presentations/` split **Corporate/** (who we are) and **Product/** (what it does), because
executives and technical evaluators want different material and a deck mixing them lands badly with
both.

`02-Context/Customers/customers` from the CRM if connected.

For anything they don't have, create the folder with a README explaining what belongs there.

## Phase 10 — Module selection

| Module | What it gives you |
|---|---|
| Market Tracking | Signals from your own newsletters and sources that change what to do |
| Competitor Tracking | Battlecards from your real win/loss record, stale-flagged by news |
| Demand Gen | Campaign attribution, plus turning signals into content worth publishing |
| Lead Tracking | Working lead list with contactability and sequence gates |
| Opportunity Tracking | Pipeline with risk flags and engagement |
| Renewals Tracking | Contract calendar, conversation commitments, churn risk |
| Partner Tracking | Sell-through and sell-with partners, kept separate |
| Daily Brief | Today's actions and meeting preparation |
| Weekly Brief | Trends, signals, competitor and account changes |
| Forecast Update | Pipeline against goals as an HTML dashboard |
| Content Tailoring | Decks, one-pagers, comparisons and follow-ups for named deals |

Every module feeds the same task list. Suggest a starting set rather than leaving them to choose
blind: **Lead Tracking, Opportunity Tracking, Daily Brief, Forecast Update** for most people, adding
Renewals if they have a customer base and Partner Tracking if they sell through channel.

Schema names: `team`, `goals`, `tasks`, `task_rules`, `customers`, `market_watchlist`,
`market_signals`, `competitors`, `campaigns`, `content_opportunities`, `leads`, `opportunities`,
`renewals`, `partners`, `content_assets`, `forecast_snapshots`, `sync_log`.

## Phase 11 — Verify and hand off

```bash
python3 <project>/.sales-system/scripts/csvguard.py --check-all <project>
```

Read its warnings, not just errors. Then show the tree, present the README, and name the two or
three things to do next. Under `xlsx`, describe what they'll see when they open a workbook — the
dropdowns especially, since that's the feature people don't discover alone.

Offer to schedule the briefs and forecast.

---

## Working with registries humans edit

Under **`xlsx`** most hazards disappear: real typed cells, dropdowns preventing invalid values,
styling reapplied on every write, and a person's own highlighting preserved because writes update
in place.

Under **`csv`** Excel is hostile — it rewrites dates, coerces IDs, adds currency symbols. The system
normalises on read rather than forbidding edits.

Either way `csvguard.py` repairs what it can, preserves user-added columns, backs up before writing,
and reports what it couldn't decide. **Never write a registry file directly** — go through the
guard, or validation and styling are lost.

Mention repairs in one line and move on. Never lecture about how to save a file.

