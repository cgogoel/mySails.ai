---
name: "daily-brief"
description: "Produce the morning brief focused on today's execution — tasks due, the emails and calls owed on specific leads and opportunities, and every meeting today with who is attending, what their role likely wants, background research on the account, relevant competitor and market context, and an offer to build tailored content for the meeting. Closes tasks already done by checking email, calendar and CRM activity. Use when the user asks for their daily brief, morning brief, what's on their plate today, what they should focus on, what they missed, who they need to follow up with, or asks to prep or start their day. Also use when setting the brief to run each morning."
---

# Daily Brief

The daily brief answers one question: **what do I need to do today, and am I ready for it.**

It is not a status report. Trends, market movement, and competitor news belong in the weekly;
pipeline against quota belongs in the forecast. Everything here should be actionable before this
evening, and the test is whether someone could work the whole day from it.

The bar: after reading, they know what to do first, and they walk into every meeting prepared.

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`.
2. Read `$CLAUDE_PLUGIN_ROOT/.sales-system/CONVENTIONS.md`.
3. Read `00-Config/config.md` — `scope`, `default_automation`, and **`brief_content`**, which
   records what this user wants in daily versus weekly. Honour it; the split below is the default,
   not a rule.
4. Read `00-Config/connections.md` so you don't retry tools that aren't there.
5. Read `.sales-system/crm-profile/field-map.json` for activity query bounds and noise filters.
6. Repair the registries:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/csvguard.py" --check-all <project>
```

7. **Check whether anything moved in the CRM overnight** — for `opportunities` and `leads`:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/csvguard.py" --sync-query <project> --registry opportunities
# run that query through the CRM connector, write the result to snapshot.json
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/csvguard.py" --verify-sync <project> \
    --registry opportunities --crm-json snapshot.json
```

Anything it reports goes at the top of the brief, with the automatic actions. Out-of-band
CRM changes are news: a deal reassigned, a stage moved by someone else, a close date pulled
in. They're also the changes least likely to reach the user any other way, which is the whole
argument for putting them in a brief rather than waiting for them to be noticed.

Keep it proportionate. Two drifted rows is a line; forty is the headline. If the check can't
run, don't stall the brief — note it in one line and carry on.

Briefs are written to `09-Briefs/Daily/YYYY-MM-DD-daily-brief.md`.

---

## Step 1: Close what's already done

Before showing anyone their list, sweep for evidence that items are finished. A brief that nags
about completed work gets ignored within a week, and then so does everything in it.

Check all three sources per `CONVENTIONS.md` — email for what they sent, calendar for what
happened, **CRM activity for what colleagues did**. That third one is the only source that shows
someone else's work: a call another rep logged, a next step a manager updated.

Bound every activity query per the profile, and filter auto-captured noise. Where the CRM records
who made a change, say so — "Dana updated the next step on Acme yesterday" is often the most useful
line in the brief.

Be conservative. A false close hides real work; ambiguous evidence leaves the task open with the
near-match mentioned.

---

## Step 2: Today's meetings, with real preparation

This is the heart of the brief and where most of the effort belongs. For each meeting today:

**Who's attending.** Pull from the invite, then enrich. For each external attendee: name, title, and
— this is the useful part — **what someone in that role is typically measured on**, so the user can
aim at it. A CISO is judged on risk reduction and audit outcomes; a DevOps lead on pipeline velocity
and not being the bottleneck; a procurement lead on terms and precedent. Say what they likely want
from this meeting, not just who they are.

Flag anyone new to the deal. A first-time attendee usually means either the deal is widening — good
— or the champion has brought a sceptic. Either way the user should know before walking in.

**Where the deal stands.** From `07-Opportunities/`: stage, amount, close date, last real contact,
close-plan gaps, engagement trend. Two or three sentences, not a data dump. If the deal has slipped
twice or is single-threaded, that belongs here.

**What's changed at their end.** Check `03-Market/signals` for anything about this account or its
industry, and check whether their org has shifted — a new CIO at a target account changes the whole
conversation. Recent funding, a breach, a regulatory deadline: all worth thirty seconds of the
user's attention beforehand.

**Competitive context.** If the deal names a competitor, pull the battlecard's key moves and —
importantly — anything in `signals_since_battlecard`. Walking in with a win theme that a competitor
neutralised last week is worse than walking in with none.

**Research the gaps.** Where the folder is thin, look it up: recent company news, the attendee's
background, what the account has published. Don't invent; if you can't find it, say the meeting is
under-researched and what you'd want to know.

**Offer tailored content.** When a meeting would benefit from something specific — a deck for this
audience, a one-pager answering the question they asked last time, a comparison against the
competitor in the deal — say so concretely and offer to build it via content tailoring. Name the
asset and why, rather than asking a generic "want materials?". Flag it early enough in the brief
that there's time to make it.

---

## Step 3: Follow-ups owed

Specific people, specific reasons. This section is a worklist, not a category.

**Replies owed.** Emails from leads or customers waiting on a response, oldest first. Age is the
whole point — "3 days" makes it real in a way "pending" doesn't.

**Leads who replied to a sequence.** Someone answered an automated cadence and is waiting on a
human. Highest-value state in the lead registry; surface it above everything else in this section.

**Deals gone quiet.** From `07-Opportunities/`, where engagement has cooled and the next step date
has passed. Say what to send, not just that contact is due.

**Renewal conversations due or overdue.** From `08-Renewals/`, using the org's conversation lead
time. Name the number of days.

Both lead gates apply throughout: check `contactable`, and never suggest outreach to someone in an
active sequence — that produces two messages from two systems in one week.

Under `review` automation, **draft the emails rather than only naming them.** Write to
`01-Tasks/Drafts/`, set `draft_path` and `status = Awaiting Approval`, and say in one line how many
are waiting. A morning's drafts reviewable in one folder is most of the value of the whole system.

---

## Step 4: Tasks due

From `01-Tasks/tasks`: due today and overdue, honouring the rules file. Note anything auto-closed in
one line — "closed 2 tasks I could see you'd already done."

Anything the system did automatically since the last brief goes at the **top of the brief**, not
here. Per `CONVENTIONS.md`, the user should never learn about a sent email from the recipient.

---

## Writing it

Structure, skipping empty sections rather than printing "None":

**Did automatically** — only if something did. Always first.

**Today** — meetings in order, each with the preparation from Step 2. Long is acceptable here;
this is what the brief is for.

**Before your first meeting** — the two or three things where waiting costs something.

**Follow-ups owed** — ranked by age and value, with drafts noted.

**Tasks** — due and overdue, plus what was auto-closed.

Under `team` scope, keep the focus on the user's own day but flag where a colleague's account needs
them — an unowned meeting, a rep out today with a deal needing cover.

### Voice

Write like a good chief of staff. Name people and accounts. Give numbers a shape: "3 days,"
"$120K," "pushed twice." Say the action, not just the fact. No preamble, no restating the date.

Don't manufacture urgency. "Quiet morning — one meeting, nothing overdue" is a legitimate brief and
builds more trust than three invented priorities.

---

## Scheduling

Offer to run it on weekday mornings, early enough to act on. A brief that requires remembering to
ask for it is a brief nobody reads.

---

## Judgement

Two failure modes.

**Breadth.** Pulling in trends, market news, and pipeline analysis because they're available. That's
the weekly's and the forecast's job, and including them here means the meeting prep — the part only
this brief does — gets skimmed.

**Shallow prep.** Listing a meeting with the account name and calling it preparation. If the brief
doesn't tell the user something they didn't already know about who they're meeting and what those
people want, it hasn't earned its place in their morning.

Where you couldn't research something properly, say so and name what would help. "Two attendees I
couldn't find anything on — worth asking your champion who they are" is more useful than silence.

