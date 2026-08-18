---
name: "content-tailoring"
description: "Build sales content tailored to a specific deal, meeting, or customer request — custom decks for an upcoming meeting, follow-up emails whether one-off or sequenced, one-pagers answering a feature question, and competitor comparisons. Assembles context from the opportunity or lead record, competitor battlecards, market signals, the corporate and product library, and messaging, then researches or asks for whatever is missing. Use whenever the user wants a deck, one-pager, comparison, leave-behind, proposal narrative, or follow-up email for a named account or meeting; says a customer asked for more detail on a feature or a comparison to another vendor; wants to prep materials for a meeting; or wants to tailor or repurpose existing collateral for a specific prospect."
---

# Content Tailoring

Every other module gathers; this one spends. It takes what the system knows about a deal — the
record, the competitor, the news, the messaging — and turns it into something you can send.

It sits last in the chain because a tailored asset is only as good as the context behind it. A deck
built from the deal's actual pain, the champion's actual title, and the competitor actually in the
room beats a generic deck enormously. A deck built from guesses is worse than the generic one,
because it's confidently wrong in front of a customer.

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
3. Read `00-Config/config.md` for `scope` and `default_automation`.
4. Repair the registries:

```bash
python3 "$S/csvguard.py" --check-all <project>
```

Source material is indexed in `10-Content/asset-index`; generated pieces go in
`10-Content/Generated/` and get indexed too.

---

## Step 1: Assemble context before writing anything

Resist the pull to start drafting. Ten minutes of gathering separates this from a template with a
name dropped in.

| Source | What you're looking for |
|---|---|
| `07-Opportunities/` + account notes | Stage, amount, champion, economic buyer, recorded pain, close-plan gaps, engagement trend |
| `06-Leads/` | Pre-opportunity work: source, product interest, what they responded to |
| `08-Renewals/` | Contract dates, health, expansion signals, churn risk |
| `04-Competitors/` battlecard | Win themes, landmines, **"do not say"**, and what changed recently |
| `03-Market/signals` | Anything about this account, their industry, or their regulator |
| `05-Demand-Gen/content-opportunities` | A published piece that already makes the argument |
| `02-Context/Messaging/` | The company's actual language, rather than a parallel vocabulary |
| `02-Context/Presentations/` | Corporate and Product source material |
| `10-Content/asset-index` | **Something that already answers this** |
| `13-Meetings/Notes/` + commitments | What the customer actually said last time — verbatim quotes, open commitments, the risk they named. An asset that answers the question they asked in the room beats one that answers the question we imagine |
| Email + calendar | What was actually asked, in their words |

**Check the index for an existing answer first.** The best outcome of a request is often "this
already exists, and it's approved." Regenerating something the library has wastes effort and
fragments the story customers hear. If a close match exists, offer it and ask whether tailoring is
really needed.

Read the battlecard's **"do not say"** section before writing a single competitive line. That
section exists because someone got burned.

## Step 2: Name the gaps, then ask

You will be missing things. Say what, rather than filling holes with plausible filler.

Ask about what only the user knows and what changes the piece materially:

- **Who's actually in the room**, and their role. Audience type drives register and depth far more
  than industry does — an executive deck and a technical evaluator deck share almost no slides.
- **What they actually asked for**, in their words. "Send me something on your API" and "send me
  something on your API — our team is worried about rate limits" produce different documents.
- **What was said on the last call** that isn't in the CRM.
- **Anything you'd assert about the product that you can't verify** from the context library.

That last one matters most. If a customer asks about a feature the library doesn't cover, **do not
invent behaviour.** Research it if there's a public source, ask the user if not, and if it still
can't be confirmed, record it in `unverified_claims` and leave it out. A confident sentence about a
capability that doesn't work as described gets discovered in a POC, and the cost is the deal.

Ask in one batch, not a trickle. If they can't answer, produce the piece with the gap explicitly
marked — `status = Needs Input`, `gaps_flagged` filled — rather than silently glossed.

## Step 3: Pick the form

| They asked for | Usually right | Watch out for |
|---|---|---|
| Meeting materials | Deck, 8–15 slides | Decks get built when a one-pager would land better |
| "More detail on feature X" | One-pager | Where the answer is "it depends," a call beats a document |
| "How do you compare to Y" | Comparison | See the honesty rules below |
| Post-meeting | Email, sometimes one attachment | Three attachments means none get opened |
| Multi-touch nurture | Email sequence | Only where there's a real reason for each touch |
| Proposal exec summary | One-pager or short deck | Don't restate the contract |

---

## Building each type

### Meeting decks

Start from the library, not from blank — `Corporate/` for executives and early stage, `Product/` for
evaluators and technical buyers — then cut hard and tailor the few slides that matter.

**A tailored deck is mostly subtraction.** Fifteen relevant slides beat forty with three good ones,
and the cutting is where the tailoring actually happens.

Add or rewrite: an opening slide naming their situation in their words; the pain slide from what's
recorded on the deal; proof points matched to their industry and size; competitive framing only if a
competitor is genuinely in the deal; a next-step slide matching the deal's actual next step.

Use the pptx skill and the template in `02-Context/Templates/`.

### One-pagers answering a specific question

The highest-conversion asset, because the customer asked for it. **Speed matters** — one two days
later beats a perfect one next week.

Answer the actual question in the first paragraph. Then supporting detail, then one next step.
Resist reintroducing the pitch; they've had the pitch, they asked a question.

If the honest answer includes a limitation, say it. A one-pager that admits a boundary and explains
the workaround builds more trust than one that dodges — and the limitation surfaces in evaluation
anyway.

### Competitor comparisons

The most dangerous thing this module produces, because it may well be forwarded to the competitor.

- **Only claims you can support** — battlecard win themes traced to real deals, not marketing lines.
- **Honour "do not say" absolutely.** No exceptions for a deal you want badly.
- **Name their genuine strengths.** A comparison where the competitor loses every row reads as
  marketing, not analysis, and discredits the rows that were true.
- **Date it and source it.** Check `signals_since_battlecard` — if news landed since the card was
  written, the comparison may already be wrong.
- **Compare on the buyer's criteria**, not the ones you happen to win.

Record `competitor_id` and `signals_used`, so a claim that turns out wrong can be traced to every
document repeating it.

### Follow-up emails, single or sequenced

Read the actual thread first. A follow-up ignoring what was said reads as automated, which is worse
than late.

Reference something specific from the conversation, deliver what you promised, one clear next step.
Short — the attachment does the explaining.

For **sequences**, each touch needs its own reason to exist: new information, a different angle, a
genuine deadline. A sequence of reminders is nagging with a schedule, and it trains people to stop
reading. Three good touches beat seven weak ones. Write them as one set so the arc is visible, and
space them against the deal's actual timeline.

Both lead gates apply: check `contactable`, and don't draft over an active sequence — a manual
follow-up on top of an automated cadence is two messages from two systems in one week.

If a `my-writing-style` profile exists, draft from it. These go out under a person's name.

---

## Step 4: Index what you made

Write the asset row: `built_from`, `competitor_id`, `signals_used`, `request_origin`,
`request_detail` in the customer's words, `unverified_claims`, `gaps_flagged`, `status`, and the
deal link.

Provenance is what makes the library improve rather than sprawl. Six months on, `built_from` finds
everything derived from a deck that turned out wrong, and `request_origin` shows which pieces came
from customer asks — those get used; proactive ones often don't.

Set `outcome_note` when you learn what happened. A comparison that won a technical evaluation is
worth promoting into the library as source material.

Raise a task at `review` automation so the draft waits for approval.

---

## Judgement

The failure mode is **volume dressed as personalisation** — a forty-slide deck with the prospect's
logo on slide one and nothing else changed. It takes longer to produce, lands worse than the generic
version, and teaches the customer your materials aren't worth reading.

The second is **confident invention**. Under pressure to produce something complete, it's tempting
to write the sentence about the feature you're unsure of. Don't. Flag it, ask, or leave it out.
Everything else in this system is recoverable; a false capability claim discovered in a POC usually
isn't.

When the honest answer is "this needs fifteen minutes with an SE before it goes out," say that. It's
better than a polished document nobody can stand behind.

