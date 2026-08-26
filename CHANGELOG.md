# Plugin changelog

Releases of the **skills** — the prose in `skills/`, versioned by `version` in
`.claude-plugin/plugin.json` and updated through the marketplace.

This is not the same file as `.sales-system/CHANGELOG.md`, and the distinction is load-bearing.
That one tracks the **support layer** — scripts, schemas, the things that live inside a project
folder — is keyed to dated template versions, and is what `upgrade.py` prints to someone moving a
folder forward. A release that changes only skill prose does not move a folder's version, so its
entry has no dated heading to live under there and would silently never print. It goes here
instead.

Newest first. Starts at 0.9.0; earlier releases are in the git history.

## 0.9.0 — 2026-08-26

Support layer unchanged at `2026-08-25`. No folder upgrade needed.

**The daily brief now clears work, not just describes it.** Three changes to `daily-brief`, all
pulling in the same direction: the brief should leave the user with fewer things to do than it
found them with.

- **Tasks are listed, not counted.** "You have seven tasks due" required opening a spreadsheet to
  find out what it meant, which is the thing the brief exists to prevent. Every task due today or
  overdue now gets its own line carrying the id, title, account, age, priority and `why`, overdue
  first and oldest first. Snoozed items stay out, blocked items get their own line with the reason,
  and a task three weeks overdue is now named as a decision nobody made rather than rolled forward
  again. Long lists are ranked and their length stated — never silently truncated.
- **A completion queue, gated on approval.** Where the system can actually finish a task — send a
  draft already sitting at `Awaiting Approval`, set a CRM field whose value is already known, log an
  activity — it now offers to, in one numbered block, stating exactly what would happen to whom.
  The user replies with numbers or `all`, and **silence is not approval**. A scheduled or unattended
  run builds the queue and executes none of it.

  The fences from `CONVENTIONS.md` §3b are checked per item against the record, not inferred from
  how the task was raised: no first contact, nothing commercial, nothing to an uncontactable person
  or someone in an active sequence, nothing a rule marks `manual` or that would breach its
  `daily_cap`, and nothing on a colleague's record under `team` scope without being asked. Excluded
  items are still shown, with the reason, so the difference is visible. `all` cannot reach a fenced
  item — that is what makes it safe to type.

  A missing `task-rules.csv` is not permission. With no rules, the queue holds only drafts already
  awaiting approval.
- **Ambiguous evidence has somewhere to go.** Step 1 used to close a task on strong evidence and
  leave everything else silently open — so a sent email to the right domain but the wrong person
  closed nothing and told nobody. Suggestive-but-inconclusive evidence now surfaces in the same
  queue as a *looks done, confirm?* item with the evidence and its date named.
- **An overnight sweep, deliberately small.** Newsletters that landed since the last brief, read
  against `03-Market/watchlist`, plus a bounded set of searches — accounts with a meeting today, the
  largest deals closing this quarter, renewals inside the conversation window, and watchlist rows
  set to `Daily`. Items survive only if they name something tracked, or match an enabled watchlist
  row with a `deal` or `both` lens and a concrete `so_what`. Everything kept is logged as a signal
  through `market-tracking`, dated on the **event** rather than the issue and deduplicated against
  what is already logged; this step consumes that module rather than keeping a second copy of it.

  Five lines is the aim and eight the ceiling, and printing nothing on a quiet morning is a result
  rather than a failure. Eight items a day for a week means the bar is too low, and the brief now
  says so and offers to tighten the watchlist instead of continuing.

  This is a deliberate exception to the rule that market content belongs in the weekly, and it is
  fenced on purpose: account-linked and actionable today. Aggregate trends and competitor
  positioning stay in `weekly-brief`. A market section that outgrows the meeting prep has turned
  the daily into the weekly printed seven times a week, and it will be skipped along with
  everything under it.
