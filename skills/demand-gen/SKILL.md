---
name: "demand-gen"
description: "Two jobs: measure demand generation campaigns against what they actually produced, and turn market signals into thought-leadership content. Computes leads, opportunities, pipeline and cost per opportunity by joining campaign sources back to the lead and deal registries. Also sweeps recent market signals for moments the company has legitimate standing to comment on, proposes angles, and drafts social posts, blogs, webinar briefs, or signal-led outreach emails. Use whenever the user mentions campaigns, demand gen, channels, lead sources, attribution, cost per lead, or event and webinar ROI; asks which campaigns are working or where their best leads come from; wants to plan a campaign; or asks about content, thought leadership, a LinkedIn or social post, a blog, a webinar topic, what they should be writing about, or whether recent news is worth commenting on."
---

# Demand Gen

Two jobs that feed each other: measuring what campaigns produced, and creating the content that
gives you something to run campaigns with.

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
3. Read `00-Config/config.md` for `scope`, fiscal calendar, `default_automation`, and any social
   channel preference, plus `.sales-system/crm-profile/field-map.json` (the `campaigns` block holds
   the join keys and attribution models).
4. Repair the registries:

```bash
python3 "$S/csvguard.py" --check-all <project>
```

Campaigns in `05-Demand-Gen/campaigns`, content ideas in `05-Demand-Gen/content-opportunities`,
drafts in `05-Demand-Gen/Content/`.

---

# Part one — campaign measurement

Campaign reporting is where sales data most often becomes fiction. Channels report their own
performance, cost per lead gets quoted without cost per opportunity, and campaigns are declared
successful weeks before any deal could have closed.

Every funnel number here is computed by joining campaign source values back to `06-Leads/` and
`07-Opportunities/`. Nothing is reported by the channel; nothing is typed by hand.

## The join key is the whole thing

`source_value` is what a campaign writes into the source field on a lead or deal. **Without it,
attribution silently returns zero** — not an error, just a campaign that appears to have produced
nothing, which is worse because it looks like a finding. Set it when creating a campaign, and check
it before concluding a campaign failed.

**When one source value covers several campaigns** — common, since source picklists often name
vendors rather than programmes — use the source-detail field the profile names to split them, and
say in `sample_note` that the split is approximate. If it can't be split, report those campaigns
together rather than inventing a division.

**Name the attribution model every time.** First-touch and last-touch disagree most on long cycles,
which is exactly where someone is about to make a budget decision. If the CRM tracks campaign
influence, amounts may be credited to several campaigns — say so before someone sums the column and
gets more pipeline than exists.

## Four derived columns that prevent wrong conclusions

**`leads_contactable`** — a purchased list that's 40% unmailable cost far more per usable lead than
the headline suggests.

**`leads_worked`** — how many got past `New`. **The crucial one.** A campaign with 200 leads and 9
worked has a follow-up problem, not a channel problem, and the two call for opposite responses.
Conflating them usually kills a channel that was fine. Always report both when they diverge, and say
which problem you think it is.

**`still_open`** — judging a campaign while most of its pipeline is unresolved is guessing.

**`maturity`** — whether enough of the cohort has resolved to conclude anything. A campaign that
closed three weeks ago in a six-month-cycle business is `Too early`, and no arithmetic changes that.

Suppress rates the sample can't support. "3 opportunities from 22 leads" is honest; "13.6%" invites
a forecast built on nothing. Never compare rates across campaigns when either sample is thin — that
comparison gets repeated in a QBR long after the caveat is lost.

## Cost tells you more than volume

`cost_per_lead` is the most quoted and least useful. `cost_per_opp` is closer to truth. A trade show
with an ugly cost per lead can easily beat cheap content because the leads convert and the deals are
larger — report the pair together, or a good channel gets cut.

`pipeline_roi` is **pipeline, not revenue**. Treating created pipeline as return is how budgets get
defended with numbers that never became money.

## Reviewing

Structure by decision: what's working and what they have in common; what isn't, with the diagnosis
(bad channel, bad targeting, or no follow-up); what's too early to judge and when it can be assessed;
what to do.

Always state how many leads had **no source at all** — they're excluded from every campaign, and if
that number is large the whole picture is weaker than it looks. Report it; never quietly drop them.

Under `team` scope, check whether follow-up quality varies by rep. If one rep's campaign leads
convert at twice the rate, that's coaching, not channel.

---

# Part two — turning signals into content

Market tracking finds things happening. This turns the few that matter into something the company
can say — and the point is being **early and relevant**, not prolific.

## The sweep

Read `03-Market/signals` where `content_reviewed = no`. Report what's arrived since the last sweep,
which is usually what the daily brief wants.

Triage each against `02-Context/Company/` and `02-Context/Messaging/`. Three outcomes:

**Worth commenting on** — the event touches something the company genuinely knows about.

**Useful but not postable** — competitor funding, rival product news. This informs positioning and
belongs in competitor tracking. **Publicly commenting on a competitor's funding round is a bad
look**, and reads as rattled rather than authoritative.

**Skip** — no standing. Set `content_reviewed = yes` with a `declined_reason` so the same item
doesn't resurface every sweep.

### Standing is the test that matters

`relevance_why` is required, and it's the quality gate for the whole module. It answers: *why does
this company specifically have the right to say something here?*

Good standing looks like: the event is in a domain the company has real evidence about, or it
matches a pattern seen across customers, or the company has data nobody else has.

If the honest answer is "we sell adjacent software," **there's no piece here.** Commentary without
standing reads as news-hijacking, and buyers recognise it instantly. Saying nothing is a legitimate
outcome and protects the credibility of the times you do speak.

### Perishability sets the deadline

Set `perishability` honestly. A breach comment written a fortnight late is worse than silence —
it announces you weren't paying attention. `Hours` and `Days` items either move now or get declined;
don't let them sit in `New` until they expire, and mark them `Expired` when they do rather than
pretending they're still live.

`Evergreen` angles — a regulation with a compliance deadline, a durable trend — are where blogs and
webinars belong, because they survive a production cycle.

## Angles, then type, then draft

Work in that order and confirm at each step. Drafting before the angle is agreed wastes the
expensive part.

**1. Propose two or three genuinely distinct angles.** Not one idea reworded — different arguments,
each with a different reader in mind. Say who each would land with. Note where an angle is
contrarian, since that's higher risk and higher reward and the user should choose knowingly.

**2. Ask for the content type**, with a recommendation and a reason:

| Type | Fits when | Note |
|---|---|---|
| Social post | Perishable, one clear point | Fastest; use the user's configured channel |
| Blog | Evergreen, needs evidence or length | Slowest to publish — check it's still fresh on arrival |
| Webinar brief | The topic warrants a conversation, or a partner angle exists | An outline and abstract, not a script |
| Outreach email | The signal matters to a *specific* account more than the market | See below |
| Newsletter item | Worth saying but not worth a standalone piece | |

**3. Draft on confirmation.** Write to `05-Demand-Gen/Content/`, set `draft_path` and `status`, and
link back to the signal via `content_opp_id`.

## Signal-led outreach — the highest-value case

When a signal matches a specific account's profile or use case, the best use often isn't a public
post at all. It's a note to one person who now has a reason to care.

Check every signal against `06-Leads/`, `07-Opportunities/`, and `08-Renewals/` — match on industry,
size, product interest, and the pain already recorded on the deal. A supply-chain incident at a
retailer is a live reason to re-open a stalled retail deal about exactly that risk.

When drafting these:

- **Lead with the thing that happened, not with the product.** The article is the reason for the
  email; the product is at most the second paragraph.
- **Be useful before being interested.** Something they'd value even if they never reply.
- **Never imply they're exposed** unless you know it. "Thought of you because of X" is fine.
  "This could be happening to you" is fear-selling and it damages the relationship.
- **Match the register.** If the signal is someone's bad week, a note that reads as opportunism does
  lasting harm. Never run this category on `auto`.

Both lead gates apply: check `contactable`, and don't draft over an active sequence.

Set `related_id` and raise the task at `review` automation so the draft waits for approval.

## Writing the drafts

Read `02-Context/Messaging/messaging-summary.md` first so the language matches how the company
actually sells, rather than inventing a parallel vocabulary. If a `my-writing-style` profile exists,
draft from it — this is content going out under a person's name.

Some things that separate a draft worth sending from filler:

- **Say something.** A post that summarises the news and adds "interesting times" is worse than
  nothing. The value is the claim only this company could make.
- **Bring evidence.** Proprietary data, a pattern across customers, a specific example.
- **Earn the length.** A social post is one idea. A blog with one idea should have been a post.
- **Attribute honestly.** Link the source. If the signal is `Reported` rather than `Confirmed`, hedge
  in the copy — publishing a rumour as fact is a correction you can't fully undo.
- **No manufactured urgency.** "Every organisation must act now" is the register of a vendor nobody
  believes.

For webinar briefs: a title, the argument, three to five sections, who should attend, and what they
leave with. Not a script.

## After publishing

Record `published_url` and `published_date`, and create the campaign row if the piece is being
promoted — that's how part one measures whether the content produced anything. Add it to
`10-Content/asset-index` so content tailoring can reuse it in deals.

A published piece that isn't indexed gets written twice and used never.

---

## Judgement

The pull in part one is toward flattering arithmetic; everyone wants the campaign to have worked and
the numbers are soft enough to cooperate. Don't launder a weak campaign with a favourable attribution
model, and don't condemn a channel whose leads nobody called.

The pull in part two is toward volume. Posting on everything trains the audience to ignore you, and
the piece that mattered gets lost in the ones that didn't. **Three pieces a quarter that only this
company could have written beats thirty of anyone's.**

In both halves, "not enough to say anything yet" is a real answer. Give it when it's true, and the
numbers and posts that follow carry more weight.

