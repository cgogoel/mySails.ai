---
name: "market-tracking"
description: "Track market signals that change what to do about specific accounts and deals — funding, breaches, leadership changes, regulation, M&A, product launches, hiring. Maintains a watchlist of what to monitor and a dated signal log, mines the user's own newsletter subscriptions and named sources, links signals to tracked accounts and opportunities, and raises tasks when something is genuinely actionable. Use whenever the user asks what's happening in their market, wants to research or monitor industry trends, asks about news affecting an account or prospect, wants to set up or edit a market watchlist or add news sources, asks whether anything changed with a company they sell to, wants to know about regulatory or competitive shifts in their space, or asks for a market update. Also use when a brief needs recent market signals."
---

# Market Tracking

The point of watching a market is not to know things. It's to notice the handful of external events
that change what someone should do this week about a specific account.

That distinction is the whole skill. A market tracker that becomes a news digest gets skimmed for a
fortnight and then ignored, and the genuinely useful signal — the one that would have reopened a
stalled deal — gets lost in it.

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`.
2. Read `.sales-system/CONVENTIONS.md`.
3. Read `00-Config/config.md` for `scope` and `default_automation`, and `connections.md` to see
   whether email is available.
4. Read `02-Context/Company/` and `02-Context/Messaging/` — you can't judge whether an event matters
   without knowing what the company sells and to whom.
5. Repair the registries:

```bash
python3 <project>/.sales-system/scripts/csvguard.py --check-all <project>
```

Two files: `03-Market/watchlist.csv` (what to monitor and where to look) and `03-Market/signals.csv`
(what was found). Longer research goes in `03-Market/Research/YYYY-MM-DD-topic.md`.

---

## First run: establish the sources

**Don't start searching the open web.** The user already has sources they trust, and those beat
anything a general search will surface — a newsletter they read is pre-filtered by an editor who
knows the space, which is exactly the judgement a broad search lacks.

If `03-Market/watchlist.csv` is empty or has no source entries, do this before anything else.

### Ask what they read

Ask directly and specifically. Vague questions get vague answers:

> Before I start looking, what do you already read? Specifically:
> - Newsletters that land in your inbox
> - Sites or blogs you check regularly
> - Analyst or research sources you trust
> - Anyone worth following — people, not just publications
>
> I'd rather sweep the places you already rely on than guess at the open web.

Record each as a watchlist row with `kind = Newsletter` or `Feed`, the sender address or URL in
`sources`, and `discovered_how = user-named`.

### Mine the inbox for the ones they forgot

People under-report their own sources — the newsletter that arrives every Tuesday and gets read
every Tuesday rarely comes to mind when asked. If email is connected, scan for recurring senders
that look like publications: repeated sends from the same address on a regular cadence, unsubscribe
footers, digest-style subjects.

Present what you find as a list to confirm, not as a decision already made:

> I also found these arriving regularly — worth watching?
> - Mobile Security Weekly (news@example.com) — weekly, 40 issues
> - FedScoop Daily (daily@example.com) — daily
> - A vendor newsletter that looks like marketing rather than news

Mark confirmed ones `discovered_how = inbox-scan`. Don't add unconfirmed guesses; a watchlist the
user didn't agree to is one they won't trust or maintain.

Distinguish real publications from vendor marketing. Both arrive on a schedule; only one is worth
sweeping.

### Then derive the rest

For subject-matter watch terms — accounts, regulations, technologies — propose a starting set drawn
from what's already in the folder rather than asking cold. People find it far easier to edit a list
than to write one. Pull from named competitors, accounts in `07-Opportunities/` and `08-Renewals/`,
industries in `02-Context/Company/`, and the standards the messaging already leans on.

Propose ten or so with a `why` for each, and let them cut.

---

## The watchlist governs everything

Search against `03-Market/watchlist.csv`. If something isn't on it, either add it deliberately or
treat it as noise.

Each entry carries a `why` — **what you'd do differently if this moved.** That's the quality gate
for the watchlist itself. An entry whose `why` is "good to know" is a news habit wearing a sales
costume; sharpen it into a decision or turn it off.

| Kind | Weak | Strong |
|---|---|---|
| Regulation | "Compliance" | A named standard buyers cite in requirements |
| Account | "Our customers" | A named account whose renewal is exposed |
| Technology | "AI" | A shift that would change how a live evaluation is judged |
| Person | "Executives" | A champion who moved, worth following to the new company |

`Newsletter` and `Feed` entries work differently from the rest: they're *sources*, not subjects.
Rather than searching for them by name, sweep their contents for anything touching the other watch
terms.

Ten watched well beats fifty watched never.

---

## Sweeping newsletters

Newsletters are dense, and most of any issue is irrelevant to any given seller. Read them **against
the watchlist**, not for general interest.

For each recent issue, extract only items that name a watched company, prospect, customer, or theme,
or that would change an answer the company gives buyers. Everything else is skipped without comment.

Set `source_type = Newsletter` and record `newsletter_name`. That provenance matters when weighing a
signal later — an item an editor thought worth leading with carries different weight from a search
result.

Two cautions. Newsletters often report the same event days after it happened, so use the **event**
date in `date`, not the send date, and deduplicate hard against signals already logged from other
sources. And newsletters editorialise; separate what happened from what the writer thinks it means,
and set `confidence` on the underlying fact rather than on the framing.

---

## Every signal passes the "so what" test

`so_what` is a required field and `csvguard` rejects a row without it. One sentence on why a seller
should care. If you can't write it, it isn't a signal.

> **Headline:** Acme Corp discloses mobile app data-exposure incident
> **So what:** Their security team now has budget attention and a board deadline — the conversation
> that stalled in May is live again.

Against that, a funding announcement for a company nobody sells to has an honest `so_what` of
nothing. Don't log it. Leaving things out is what keeps the first one visible.

### Relevance and the account link

`relevance = High` means it changes what someone does **this week**. Reserve it; if a third of
signals are High, the field has stopped carrying information.

A signal tied to a tracked record via `related_id` is worth an order of magnitude more than a
general observation, because it produces a specific action for a specific person. After finding
anything, check it against `06-Leads/`, `07-Opportunities/`, `08-Renewals/`, and
`02-Context/Customers/`. Fuzzy-match on company name and domain — CRM account names and press
coverage rarely spell things identically.

Signals about prospects matter, but the bar is higher: a funding round at a company nobody has
spoken to is a prospecting hook, not an event.

### Say how sure you are

`Confirmed` for a primary source or company statement, `Reported` for credible secondary coverage,
`Rumour` for a single unverified account. Acting on a rumour as fact is how someone references a
layoff that didn't happen in an email to a buyer.

Always record `source_url` and `source_name`. A signal nobody can check is one nobody should act on.

---

## Signal types that actually move deals

**Breach or security incident** — at a prospect, creates budget and urgency faster than anything
else. Handle with care: someone having a bad week doesn't want a pitch shaped like an ambulance.
Usually the right move is a genuinely useful note, not an offer.

**Leadership change** — a new executive rewrites priorities within a quarter. A departing champion
is a risk on a live deal and an opportunity at their new company. Check both directions.

**Funding or earnings** — budget exists, or has just been cut. Reliable timing signal.

**Regulation** — strongest signal in regulated markets, because it creates deadlines that aren't
negotiable. Slow-moving and easy to be early on.

**M&A** — freezes procurement for months, then reopens everything. Usually bad for a deal in flight.

**Hiring** — a team being built in your area means a budget line exists. Layoffs mean the opposite.

**Product launch** — matters mainly when it's a competitor, or changes what a customer needs.

---

## What to actually do

### Sweep

Work the watchlist by `cadence`. Sweep newsletters and feeds first — they're pre-filtered — then
targeted search for watch terms that need it.

Update `last_checked` and `signals_found` so each entry's value becomes visible over time. An entry
that's produced nothing in six months should probably be retired, and having the number makes that
an easy conversation rather than a judgement call.

Deduplicate before writing. The same event gets covered repeatedly across sources, and a registry
holding one event five times is worse than useless.

### Report

Lead with what's actionable and tied to a real record. Then general market movement, briefly. Then
nothing.

Three lines per signal: what happened, why it matters here, what to do. If a sweep found nothing
worth acting on, say so — "nothing this week that changes anything" is legitimate and
trust-building, and manufacturing significance to justify the exercise is how this module dies.

### Raise tasks

Only for `High` relevance, preferably only where `related_id` points at something tracked. Read
`01-Tasks/task-rules.csv` and honour the caps. The lead gates apply to anything customer-facing:
check `contactable`, don't draft over an active sequence.

The task should carry the angle, not the fact: "Reach out to Acme security lead re: their incident —
reframe the Q-Scout conversation that stalled in May" is usable. "Follow up on Acme news" isn't.

Be careful with tone on sensitive events. Breaches, layoffs, and departures are bad days for real
people, and outreach that reads as opportunistic does lasting damage. Under `review` automation,
draft in a register the user would actually send. Never let this category run on `auto`.

### Scheduling

Weekly is usually right — daily produces noise, monthly misses windows. Match it to when the main
newsletters land, so a sweep runs against fresh material. Offer to feed the output into the weekly
brief rather than delivering it separately.

---

## Judgement

The failure mode is volume dressed as diligence. Twenty signals a week means nobody reads any, and
the two that mattered are indistinguishable from the eighteen that didn't.

Bias hard toward fewer, sharper entries. A month with three logged signals that each changed
something is a month this module earned its place. A month with sixty is a newsletter — and the user
already has those.

When nothing happened, say nothing happened.

