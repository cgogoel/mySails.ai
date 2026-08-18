# Support layer changelog

What changed in each release of the generic layer, newest first. `upgrade.py` prints the entries
between a folder's version and the one it's moving to, so someone upgrading finds out what they
gained — and, more importantly, what quietly means something different now.

The format is one `## YYYY-MM-DD` heading per template version, matching `VERSION.json`.

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
