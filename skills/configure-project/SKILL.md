---
name: "configure-project"
description: "Set up, reconfigure, or repair the sales management project folder, as a guided session you can pause and come back to. Walks module by module — creating each registry, importing the user's own decks, templates, price lists and customer data, pulling real records from the CRM and confirming the field mapping against them — and keeps a completion tracker at 00-Config/setup-checklist.csv with an HTML progress dashboard. Also confirms email/calendar/CRM connections, introspects the CRM to build a per-org profile, captures company and personal goals, sets CSV or styled Excel, decides brief content and forecast cadence, and sets task automation posture. Use whenever the user wants to set up, configure, initialize, continue, resume or reset their sales project, asks how far through setup they are or what's left to do, says the folder is empty, asks where something goes, wants to enable another module, wants to import their existing content or collateral, wants to change goals or brief content or forecast cadence, wants to switch registries between CSV and Excel, wants to refresh the CRM field mapping, or when another sales skill finds config.md missing or the profile stale."
---

# Configure Project

The front door. Every other skill reads what this creates, and when setup is half-finished
downstream skills degrade quietly rather than failing loudly — which is why a folder that
looks finished and isn't is worse than an empty one.

The person running this sells for a living. They should finish with a folder they can open in
Finder, browse without a guide, and edit without fear.

**Setup is a resumable checklist, not an interview.** It takes longer than one sitting: it
involves finding documents, deciding things, and waiting on connectors somebody else has to
authorise. Treat every session as a slice of it.

---

## Always start here

### 1. Bootstrap the support layer if it's missing

The **project root** is the connected folder. On a fresh install it's empty.

**Only the schemas go into the folder.** Scripts and `CONVENTIONS.md` run from the plugin, so
they update when the plugin does and there is never a stale copy sitting next to live data.
What the folder holds is the part the user is allowed to edit — their schemas — plus their CRM
profile and brand.

Resolve the plugin root: use `$CLAUDE_PLUGIN_ROOT` when set, otherwise the directory two levels
above this `SKILL.md`. Then:

```bash
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:?resolve from this skill's own path if unset}"
mkdir -p "<project>/.sales-system"/{schemas,crm-profile,backups,cache}
cp "$PLUGIN_ROOT/.sales-system/schemas/"*.json "<project>/.sales-system/schemas/"
cp "$PLUGIN_ROOT/.sales-system/VERSION.json" "$PLUGIN_ROOT/.sales-system/MANIFEST.json" \
   "<project>/.sales-system/"
```

If a copy fails with a permission error — some connected folders reject `cp` because it
preserves the source's read-only mode — stream the files instead:

```bash
for f in "$PLUGIN_ROOT/.sales-system/schemas/"*.json; do
  cat "$f" > "<project>/.sales-system/schemas/$(basename "$f")"
done
```

Verify `schemas/` and `VERSION.json` are present. `MANIFEST.json` is what lets a later upgrade
tell a schema the user edited from one that hasn't been touched, so don't skip it. Say plainly
that the system layer was installed; don't expose paths unless asked.

**If `.sales-system/` already exists**, don't re-copy anything — go to 1a.

**Never overwrite an existing `.sales-system/`.** A user may have edited a schema, and clobbering
that silently loses their work. Upgrading is its own operation, in its own skill.

### 1a. Check whether the folder has fallen behind

The plugin and the folder's schemas version independently, so check at the start of every
session:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/skills/update-system/scripts/upgrade.py" --check <project>
```

If it reports changes, hand off to the **`update-system`** skill rather than reimplementing the
flow here — that skill owns it, including the plugin-level check and the marketplace auto-sync
explanation. Say what's waiting in plain terms first:

> Your folder is on the July build and the plugin ships August. That's the drift check against
> your CRM and the write guard, neither of which this folder has. Nothing of yours is
> overwritten — one schema you edited gets merged. Do it now, or carry on with setup?

**A folder that's behind is not broken**, so don't block on it. If they'd rather press on, note
it and carry on; just don't promise behaviour the installed layer doesn't have.

Then read `$CLAUDE_PLUGIN_ROOT/.sales-system/CONVENTIONS.md` — the rulebook the rest of this
assumes. It lives in the plugin, not the folder, because it has to agree with the skills that
follow it.

### 2. Find out where they already are

```bash
S="$CLAUDE_PLUGIN_ROOT/.sales-system/scripts"
python3 $S/setup_status.py --check <project>     # or --init on a first run
```

`--check` looks at the folder and marks steps complete from **evidence** — the file that exists,
the registry that has rows, the config key that's set. Never from memory of having done them. A
previous session that crashed mid-phase remembers nothing, and a user who did something by hand
last week never told anyone; both are recoverable by looking.

Then open with where they stand, not with a question:

> You're 60% through — 20 of 33 steps. Foundation and Goals are done; the CRM profile is built
> but the opportunity mapping hasn't been confirmed against real records yet.
>
> Next up is confirming that mapping — about five minutes. Or we can skip to something else.

**Never re-ask a question the checklist says is answered.** The `notes` column on each row exists
so a later session can read what was decided instead of asking again.

### 3. Work in slices, and save after every one

- **Ask in small batches.** Two or three questions, then do something visible with the answers.
- **Write the checklist after every completed step**, not at the end of the session. A session
  that ends unexpectedly should lose nothing.
- **Offer to stop.** Every three or four steps: "That's the pipeline connected — good place to
  pause, or keep going?" A folder they can grow into beats one abandoned at question fourteen.
- **Let them skip.** `Skipped` is a real status. So is `Blocked`, with a reason — use it rather
  than leaving something `Not started` forever while waiting on an admin.

```bash
python3 $S/setup_status.py --set <project> --key opportunities-mapping --status Done \
    --notes "Amount_Committed__c is the authoritative amount, not Amount"
python3 $S/setup_status.py --set <project> --key crm-connected \
    --blocked-reason "Waiting on Salesforce admin to approve the connected app"
```

Show progress when they ask, and at the end of every session:

```bash
python3 $S/setup_status.py --html <project>       # 00-Config/setup-progress.html
```

---

## Track 1 — Foundation

**Scope.** The most consequential answer, because it changes every CRM pull and every roll-up:

> Track just your own leads and deals, or your whole team's?

`individual` — pulls filter to their user ID, briefs speak in the first person.
`team` — also build `00-Config/team`, pulling the roster from the CRM role hierarchy rather than
making them type names, capturing each rep's CRM user ID. Confirm the list; hierarchies keep
people who've left.

Someone in an ops or management role often wants `team` even though they'd describe their own
quota when asked. Record as `scope:`.

**Storage format.** Registries are plain CSV or styled Excel workbooks.

| | `csv` | `xlsx` |
|---|---|---|
| Opening it | Raw text | A finished-looking table |
| Editing | Excel mangles dates and IDs; the guard repairs | Real typed cells, nothing to mangle |
| Data entry | Type and hope | Dropdowns of the org's real picklist values |
| grep / diff | Yes | No |

**Recommend `xlsx` when a CRM profile exists** — the dropdowns come from their real picklists, so
an invalid stage genuinely can't be typed. Recommend `csv` with no CRM, or if they'll grep the
folder. Write `storage_format:`. Plumbing stays CSV either way via `browsable: false`. Changing
later is safe and reversible: `--convert-all <project> --to xlsx`.

**Folder structure.** Always `README.md`, `00-Config/`, `01-Tasks/`, `02-Context/`,
`.sales-system/`. Everything else arrives with its module, in Track 4 — an empty `05-Demand-Gen/`
in a folder belonging to someone who doesn't run campaigns is clutter that makes the whole thing
look unfinished.

Tasks sit at `01-` because it's the file opened daily. The root `README.md` is the single most
important artifact for making the folder navigable — write it in their words, name their company,
say which format the data is in and that it's safe to edit.

---

## Track 2 — Connections

Probe rather than interview. Look for email, calendar, CRM, meeting transcripts, chat,
enrichment. Report in plain language, ask about gaps, and record everything in
`00-Config/connections.md` **including what was absent**, so later skills don't retry dead tools.

Flag if **email is missing** — without it tasks can't be drafted, sent, or verified as done, and
engagement scoring loses its strongest signal.

Write the CRM sync posture to config: pulls automatic, **pushes never automatic** (field-by-field
diff, explicit yes), conflicts always surfaced, everything logged to `00-Config/sync-log.csv`.
Ask which objects are in scope and about validation rules that make writes fail.

If a connector needs authorising by someone else, mark the step `Blocked` with the reason and
carry on with what doesn't depend on it. Setup should never stall waiting on an admin.

---

## Track 3 — The CRM profile

**This is what makes a generic template fit a specific company.** Everything shipped is identical
for every user; the org's specifics live in `.sales-system/crm-profile/`. Skip entirely if no CRM.

Fetch each in-scope object's schema and read it properly — real orgs replace standard picklists
wholesale, and half the custom fields are integration-owned. **Use a subagent to extract**, asking
for exact values not summaries: every picklist's values in order, custom fields with types, what's
required on create, and any admin-authored description or help text. That last is
disproportionately valuable — it's where integration ownership and business rules are documented.

Write four files:

| File | Holds |
|---|---|
| `picklists.json` | The org's real values. These also become the Excel dropdowns |
| `field-map.json` | `crm` (which CRM this is), column mapping, `required_on_create`, `safe_to_push`, `never_push` **with reasons**, `shared_fields`, `ignore_fields`, `gotchas` |
| `contactability.json` | What blocks contact, and on which channel — look for channel-specific opt-outs |
| `profile.md` | The narrative version |

`field-map.json` also carries an **`activity` block** — the objects behind contact roles, email and
meetings, with the shape set out in `CONVENTIONS.md` §7a. Introspect it here and confirm it,
because three things about it are wrong more often than not:

- **Which object actually holds the email.** Most orgs have two candidates and populate one. Check
  volumes on real records rather than trusting that a field exists.
- **Whether direction can be established at all.** `email_direction_semantics` is
  `boolean_incoming`, `subject_heuristic`, or `none`. The activity object most orgs populate often
  has no direction field, and `none` is a legitimate answer — record it rather than reaching for
  the heuristic. Everything downstream then reports `replied` blank and engagement `undetermined`,
  which is the honest output and needs saying out loud here so it isn't read later as a bug.
- **How few meetings are linked to opportunities.** Count them. An org with thousands of meeting
  records and eighteen linked to a deal needs the account-linked fallback, and that number is
  usually a surprise worth showing.

Record the org's own auto-reply subject patterns too. An out-of-office counted as a reply marks a
departed contact's still-running mailbox as an engaged human, and that error compounds quietly.

Fill in `lead_link` even though nothing reads it yet — the same evidence drives lead triage later,
and introspecting twice is how two versions of one block end up disagreeing.

**Set `crm` correctly — it's load-bearing.** It selects the dialect in
`csvguard.CRM_DIALECTS`: which field holds the record identifier, which holds the
last-modified stamp, whether there's a query language, whether custom fields carry a
suffix report labels drop, and whether record IDs have more than one form. Get it wrong or
leave it out and everything still works, but generically — drift detection falls back to
matching identifier and timestamp fields by name.

If their CRM has no entry there, don't add one blind: check whether the generic behaviour
actually works against real records first. If it doesn't, put the specific keys
(`id_field`, `modified_fields`, `query_language`, `id_form`) at the top level of
`field-map.json`, which overrides the dialect without a code change.

Confirm what you found, especially anything surprising. Say which objects you profiled and which
you didn't. The mapping gets *proved* against real records in Track 4, not here — reading a
schema tells you a field exists, not that it holds what its name suggests.

---

## Track 4 — Modules, one at a time

**This is the part that used to be a single checkbox list and shouldn't be.** Enabling a module
means creating its folder and registry, getting real data into it, and confirming the data is
right. Do all of that for one module before starting the next, so a session that ends early
leaves working modules rather than eleven half-built ones.

Suggest a starting set rather than leaving them to choose blind: **Lead Tracking, Opportunity
Tracking, Daily Brief, Forecast Update** for most people, adding Renewals if they have a customer
base and Partner Tracking if they sell through channel. Record the choice in
`00-Config/enabled-modules.md`, then:

```bash
python3 $S/setup_status.py --init <project>    # adds the steps for the modules chosen
```

| Module | What it gives you |
|---|---|
| Market Tracking | Signals from your own newsletters and sources that change what to do |
| Competitor Tracking | Battlecards from your real win/loss record, stale-flagged by news |
| Demand Gen | Campaign attribution, plus turning signals into content worth publishing |
| Lead Tracking | Working lead list with contactability and sequence gates |
| Opportunity Tracking | Pipeline with risk flags and engagement |
| Renewals Tracking | Contract calendar, conversation commitments, churn risk |
| Partner Tracking | Sell-through and sell-with partners, kept separate |
| Quote Generation | Quotes off a real price list, with floors and approval thresholds |
| Content Tailoring | Decks, one-pagers, comparisons and follow-ups for named deals |
| Daily Brief | Today's actions and meeting preparation |
| Weekly Brief | Trends, signals, competitor and account changes |
| Forecast Update | Pipeline against goals as an HTML dashboard |

Every module feeds the same task list.

### The four steps for each module

**a. Say what it does, in one or two lines**, and what it needs from them. Some modules need
nothing but a folder; Quote Generation needs a price list they may have to go and find.

**b. Create the folder and registry.** Omit the extension and the guard applies the project's
format:

```bash
python3 $S/csvguard.py --init <project>/07-Opportunities/opportunities \
    --schema opportunities --project <project>
mkdir -p <project>/07-Opportunities/import
```

Schema names: `team`, `goals`, `tasks`, `task_rules`, `customers`, `market_watchlist`,
`market_signals`, `competitors`, `campaigns`, `content_opportunities`, `leads`, `opportunities`,
`renewals`, `partners`, `deal_registrations`, `price_list`, `quotes`, `quote_lines`,
`content_assets`, `forecast_snapshots`, `sync_log`, `setup_checklist`, `opportunity_contacts`.

**c. Load real data.** Through `crm_sync.py` — never a hand-written import, for the reasons in
`CONVENTIONS.md` §3c:

```bash
python3 $S/crm_sync.py --plan <project> --registry opportunities   # prints what to select
# run that query through the CRM connector, write the result to snapshot.json
python3 $S/crm_sync.py --seed <project> --registry opportunities --json-file snapshot.json
```

For a large object — leads especially — don't pull through the connector at all. Ask them to
export a report to `06-Leads/import/` and:

```bash
python3 $S/crm_sync.py --ingest <project> --registry leads --mode seed
```

Tell them the export **must include the record ID column**, or nothing can be matched. Read the
list of unmapped columns it prints back to them: an unmapped column is data silently not
imported, and it's their field names, so they'll spot what matters.

**d. Confirm the mapping against real records — the step that earns its place.** Show three
actual rows and walk the columns that matter:

> Here are three of your opportunities as they landed:
>
> | | Amount | Stage | Close date | Owner |
> |---|---|---|---|---|
> | Northwind Platform | 240,000 | Negotiation | 2026-09-30 | you |
> | Contoso Expansion | 0 | Proposal | 2026-08-31 | Dana |
> | Fabrikam Renewal | 85,000 | Discovery | 2026-12-15 | you |
>
> Contoso shows 0 — your org has both `Amount` and `Amount_Committed__c` and I've mapped
> `Amount`. Which one do you forecast on?

Reading a CRM schema tells you a field exists. Only a person can tell you which of four
amount fields the business actually uses, whether "Qualification" comes before or after
"Discovery" in their process, or that a whole stage is legacy and nobody uses it. **A mapping
error found here costs a minute. Found in a forecast, it costs the forecast** — and it will be
believed, because everything about the output looks right.

Then reconcile once, so the folder starts life provably in agreement:

```bash
python3 $S/csvguard.py --verify-sync <project> --registry opportunities --crm-json snapshot.json
```

Record what was decided in the checklist's `notes` — "forecast on `Amount_Committed__c`; `Amount`
is the list price before discount" is exactly the sort of thing that would otherwise be
rediscovered painfully in three months.

### Module-specific notes

- **Leads** — expect sparse data and high volume. Derive `contactable` from
  `contactability.json` and say how many are contactable, in sequence, and have no email. That
  sentence tells them whether the list is worth working.
- **Opportunities** — recompute `risk_flags`, `close_plan_gaps`, `days_in_stage` after loading.
  Then create `opportunity-contacts` and build it, or the `single-threaded` flag has nothing to
  read and quietly reports every deal as fine:

  ```bash
  python3 $S/csvguard.py --init <project>/07-Opportunities/opportunity-contacts \
      --schema opportunity_contacts --project <project>
  python3 $S/contacts_sync.py --plan  <project>     # what to query, from the activity block
  python3 $S/contacts_sync.py --build <project> --input contacts.json
  ```

  Show them one deal's contacts afterwards, ideally one where `source` is `activity-only` — the
  gap between who the CRM lists and who is actually emailing is the thing that makes this land.
- **Renewals** — often not a CRM object at all. Ask how renewals are tracked before assuming; a
  contract end date on the closed-won opportunity is the common answer.
- **Partners** — territories, named accounts and margin are authored here, not imported. Budget
  time for it or mark it `In progress` and move on.
- **Quotes** — needs a real price list with floors. If they don't have one to hand, mark it
  `Blocked` with what's needed rather than inventing prices.
- **Briefs and forecast** — run each once at the end of the session. It's the fastest way to find
  out whether the data behind it is good enough yet, and it's the moment the whole thing starts
  looking worth having.

---

## Track 5 — Their own content

Everything generated for a customer reads from `02-Context/`. An empty context library produces
generic output, which is the fastest way for someone to conclude this doesn't work.

Two ways in, and offer both:

**Scan a folder they already have.** Ask whether their collateral lives somewhere — a Drive
folder, `~/Documents/Sales`, wherever the deck they last sent came from. Inventory it, propose a
filing, and get one confirmation before copying:

> I found 23 files. My reading:
>
> - **Corporate** (3) — company overview, the customer logo slide, the funding announcement
> - **Product** (6) — platform deck, two datasheets, the security whitepaper, two demo scripts
> - **Templates** (4) — intro email, follow-up, the MSA, an SOW
> - **Messaging** (2) — positioning doc, competitive matrix
> - **Not obviously useful** (8) — expense forms, an old org chart, four screenshots
>
> Copy the first four groups in?

Copy rather than move — never reorganise someone's own folders. Say plainly that copies are
copies and won't update when the originals do.

**A standing drop-box.** Create `02-Context/Inbox/` with a README saying what it's for. Anything
dropped there gets classified and filed on the next setup or content run. This is what makes the
library grow instead of being a one-time snapshot — most people won't have everything to hand
during setup, and asking them to go and find it stalls the session.

Sweep the inbox at the start of every resumed setup session and mention what turned up.

**The library:**

```
02-Context/Company/         Who you are, what you sell
          Messaging/        Positioning verbatim + messaging-summary.md
          Templates/        Emails and documents you already send
          Presentations/Corporate/   Who we are — executives want this
                        /Product/    What it does — evaluators want this
          Customers/        customers registry, from the CRM if connected
          Inbox/            Drop things here; they get filed
```

The Corporate/Product split matters: a deck mixing them lands badly with both audiences.

Copy any positioning doc **verbatim and** write a distilled `messaging-summary.md` — a 40-page
deck is too expensive to load on every request, and paraphrasing without keeping the original
loses the exact words someone chose.

For anything they don't have, create the folder with a README explaining what belongs there.
An empty folder with an explanation is an invitation; an empty folder is a gap.

---

## Track 6 — Goals

**A forecast against the wrong number is worse than no forecast.** Ask for both levels:

> What are you measuring against?
> - **Company goals** — the number the business carries this year and this quarter
> - **Personal or team goals** — your own quota, or your team's
>
> Either or both. I'll frame every forecast against them and check back each quarter.

Capture metric, period, target and dates into `00-Config/goals`. Set `last_confirmed` and
`confirm_cadence` (quarterly default) — goals move mid-year, and an unconfirmed goal quietly
makes every forecast wrong. When one changes later, mark the old row `Superseded` rather than
overwriting; a goal that moved is part of the story.

For renewals the goal is **100%** — every renewal not secured is leakage, not a deal lost. Track
it separately in the forecast rather than as a currency target.

---

## Track 7 — Tasks, automation and cadence

| Level | What happens | Good for |
|---|---|---|
| `manual` | Raises the task, you do it | Calls, meetings, judgement calls |
| `review` | Writes the draft, you approve | Almost everything customer-facing |
| `auto` | Acts, then reports | Internal, reversible, low-stakes |

Recommend **everything at `review`**: drafting is where most of the value is, and a week of
watching what the system *would* have sent is the cheapest way to learn whether you'd trust it
to send.

If they want `auto` on customer email immediately, say plainly that a misjudged follow-up is a
relationship cost that can't be undone — then if they still want it, apply the fences from
`CONVENTIONS.md`: never first contact, never pricing or commitments, `daily_cap` on every rule,
everything reported at the top of the next brief, delayed send where possible.

```bash
python3 $S/csvguard.py --init <project>/01-Tasks/tasks --schema tasks --project <project>
python3 $S/csvguard.py --init <project>/01-Tasks/task-rules --schema task_rules --project <project>
mkdir -p <project>/01-Tasks/Drafts <project>/.sales-system/cache
```

Populate starter rules matched to the modules enabled, wording triggers with the org's own
picklist values — a rule referencing a status the CRM doesn't have never fires.

**Briefs.** Three outputs with different jobs, and the split between them follows each org's
business rhythm — so ask rather than assuming.

| | Answers | Default cadence |
|---|---|---|
| **Daily brief** | What do I do today, and am I ready for my meetings | Weekday mornings |
| **Weekly brief** | What's changing around us, what should we do differently | Friday PM or Monday AM |
| **Forecast update** | Are we making the number, what would change the answer | Matches the forecast meeting |

> **Daily** — tasks due, follow-ups owed, today's meetings with attendee research and prep
> **Weekly** — trends, market signals, competitor news, changes at key accounts, content worth writing
> **Forecast** — pipeline against goals, renewal coverage, deals ranked by engagement
>
> Some people want pipeline movement in the weekly; others only in the forecast. Where would you
> put it?

Record as `brief_content:` — a short list per brief. Every brief skill reads it and honours it
over its own defaults.

**Ask when the forecast call is** and schedule the forecast to land a few hours before it. A
forecast produced after the meeting is a record, not a tool. Record `forecast_cadence:` and
`forecast_day:`. Offer quarterly and annual runs too — those are the ones people mean to do and
don't.

---

## Track 8 — Verify and hand off

```bash
python3 $S/csvguard.py --check-all <project>
python3 $S/setup_status.py --html <project>
```

Read the guard's warnings, not just its errors. Then show the tree, present the README, open the
progress dashboard, and name the two or three things to do next. Under `xlsx`, describe what
they'll see when they open a workbook — the dropdowns especially, since that's the feature people
don't discover on their own.

Offer to schedule the briefs and the forecast.

**If setup isn't finished, say so plainly and say what's missing.** "You're at 78% — everything
you need for the daily brief and the forecast is working. Renewals is enabled but empty, so leave
it out of anything you rely on until we load it." That's a usable folder with a known edge. A
folder presented as complete when it isn't produces confident output built on nothing.

---

## Reconfiguring later

Everything above works as an edit. Show the current setting, ask what to change, run only those
steps, never silently overwrite — show before and after.

Common asks and where they land:

| They say | Do |
|---|---|
| "How far through am I?" | `setup_status.py --check` then `--html` |
| "Update my sales system" | `upgrade.py --check` then `--apply`; the plugin manager updates the skills, this updates the folder |
| "Turn on renewals too" | Add to `enabled-modules.md`, `--init`, run Track 4 for that module only |
| "My quota changed" | Track 6; supersede the old goal row, don't overwrite it |
| "Move to Excel" | `csvguard.py --convert-all <project> --to xlsx` |
| "The stages are wrong" | Re-run Track 3 for that object, then re-confirm against real records |
| "Start over" | Confirm first. Keep their data and context; rebuild config and checklist |

`--init` is safe to re-run at any time: it adds steps for newly enabled modules and never resets
anything already done.

---

## Working with registries humans edit

Under **`xlsx`** most hazards disappear: real typed cells, dropdowns preventing invalid values,
styling reapplied on every write, and a person's own highlighting preserved because writes update
in place.

Under **`csv`** Excel is hostile — it rewrites dates, coerces IDs, adds currency symbols. The
system normalises on read rather than forbidding edits.

Either way `csvguard.py` repairs what it can, preserves user-added columns, backs up before
writing, and refuses any write that looks like an accident rather than an edit. **Never write a
registry file directly** — go through the guard, or validation, styling and that protection are
all lost.

Mention repairs in one line and move on. Never lecture about how to save a file.
