---
name: "quote-generation"
description: "Generate a customer quote from the price list, clarifying every term and discount with the user before producing anything. Resolves volume tiers from quantity, refuses prices not on the price list or below floor, flags discounts needing approval, versions reissued quotes, and links the quote to its opportunity — offering to update the deal amount from the quote total. Also estimates opportunity value from quantities for a newly entered deal. Use only when the user explicitly asks to build, generate, draft, revise or reissue a quote, asks what something would cost for a given quantity, asks to price a deal, or asks to set up a price list or quote template. Do not produce quotes unasked."
---

# Quote Generation

This is the one module where a mistake reaches the customer as a number they'll hold you to. A
wrong forecast can be corrected next week. A quote sent below floor, or with a discount nobody
approved, is a commitment.

So this module works differently from the rest of the system: **it only runs when explicitly
asked**, and it asks before deciding rather than deciding and reporting. Never volunteer a quote
because a deal looks ready — offer, and wait.

## Before anything else

1. Find the project root — the connected folder containing `.sales-system/`.
2. Read `$CLAUDE_PLUGIN_ROOT/.sales-system/CONVENTIONS.md`.
3. Read `00-Config/config.md` for `scope`, currency, and any recorded quote defaults.
4. Repair the registries:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/csvguard.py" --check-all <project>
```

Quotes live in `12-Quotes/` — `price-list`, `quotes`, `quote-lines`, plus `Documents/` for
generated files and `quote-terms.md` for standard terms.

---

## Two things must exist first

### The price list

**Without it, stop.** A quote cannot be built from guesses, and the calculator will refuse.

If `12-Quotes/price-list` is empty, offer to build it — from a file they have, a pasted list, or
question by question. Per SKU you need: name, unit (device, app, user, site, flat), list price,
currency, default term, and billing frequency. Then the three fields that make the rest safe:

- **Volume tiers** — quantity thresholds and the price each earns
- **Floor price** — the absolute lowest permitted, whatever the discount
- **Max discount without approval** — the point where sign-off is required

Ask for those explicitly. They're the fields people skip and the ones that prevent every serious
error this module could make. If someone genuinely has no floor, record that as a deliberate choice
rather than leaving it blank.

### The quote template and standard terms

If there's no template in `02-Context/Templates/`, offer to generate one — but **clarify the terms
explicitly first**, one at a time, because these are contractual and a default nobody chose is a
default nobody will honour:

- **Validity period** — how long the quote stands. 30 days is common. An open-ended quote is a
  permanent discount.
- **Payment terms** — Net 30, Net 60, annual in advance, milestone
- **Contract term** and whether pricing assumes it
- **Currency** and who bears conversion
- **Tax treatment** — inclusive, exclusive, or exempt
- **What's excluded** — services, travel, support tier
- **Cancellation and auto-renewal**
- **Who signs**, and whether a PO is required

Write the answers to `12-Quotes/quote-terms.md` and use them as defaults from then on. Say plainly
that a generated template is a starting point and should see legal review before it goes to a
customer — that's true and it's the kind of caveat that matters more than it costs.

---

## Building a quote

### Step 1: Establish what's being quoted

Q&A, not assumption. Work through:

**Which opportunity.** A quote should almost always belong to a deal. If there isn't one, ask
whether to create it — an untethered quote is invisible to the forecast.

**What products, and how many of what.** The unit matters: 500 *devices* and 500 *apps* are
different products at different prices. Pull what you can from the deal record and confirm rather
than asking cold — if the opportunity already records the device count, say so and check it.

**Contract term.** Pricing usually assumes one. A twelve-month price quoted for thirty-six months is
a different deal and needs saying.

**Anything non-standard** — payment terms, start date, phasing.

### Step 2: Price it

```bash
python3 "$CLAUDE_PLUGIN_ROOT/.sales-system/scripts/quote.py" --build <project> \
  --lines lines.json --threshold <org blended-discount threshold>
```

The calculator resolves tiers from quantity — a rep can't choose tier 4 pricing on a tier 1
quantity — and refuses rather than warns on: a SKU not on the list, a quantity below minimum or off
the increment, a deprecated or expired price, a discount with no reason, and a net price below floor.

**Treat its problems as blocking.** "Below floor — do not issue" means do not issue. If the user
wants to anyway, that's a decision for someone with authority to make it, and it should be recorded
as an approval rather than quietly overridden.

### Step 3: Discounts, one at a time

Every discount is a deliberate answer to a question, never an assumption. For each one ask what it's
for and record it in `discount_reason`.

Good reasons are things you'd repeat at renewal: multi-year commitment, volume beyond a tier,
payment in advance, a reference agreement, a competitive displacement. "Customer asked" is not a
reason, it's a request — and a discount with no defensible reason is one you'll be asked to repeat
forever, because the customer will remember the price and not the circumstance.

Where the calculator flags approval, say so **before** building the document, with who needs to
approve and why. Set `needs_approval` and `approval_reason`, and leave the quote at
`Awaiting Approval` rather than `Draft`.

If the CRM profile records approval thresholds that fire on the opportunity — a discount over some
percentage triggering a workflow — mention that pushing the amount later will start it.

### Step 4: Generate the document

Use the template from `02-Context/Templates/` with the docx or pdf skill. Include quote number,
version, issue date, **valid-until date**, line items with quantities and unit prices, subtotal,
discount, total, the standard terms, and what's excluded.

Write to `12-Quotes/Documents/`, record `document_path`, and write the header and line rows.

**Versioning matters.** A revised quote is a **new version**, not an edit — increment `version`, set
`supersedes`, and mark the old one `Superseded`. You need to be able to say exactly what the
customer was sent and when, especially if terms are later disputed.

---

## Estimating an opportunity value

A common and useful case that isn't a full quote: a new deal where someone knows the shape but not
the number. "Acme has 500 devices" is enough to size it.

Price it with the tier logic and give the number with its basis:

> 500 devices at the tier-2 rate of $88 is **$44,000** annually. Note that's tier 2 — at list it
> would be $50,000, and at 2,000 devices it drops to $74.

That framing does two things. It shows the working, so the number can be challenged. And it names
the next tier, which is genuinely useful — the gap between 500 and 2,000 devices is a conversation
worth having.

Be explicit that this is an **estimate, not a quote**: no discount, no terms, nothing sent. Log it
in the opportunity note rather than the quote registry.

---

## Updating the opportunity

**Always ask; never do it silently.**

When a quote is generated for a deal, ask whether the opportunity amount should be updated to match:

> This quote totals $93,720. The opportunity is currently at $120,000. Update it to the quote total?

Ask because a quote and a deal amount legitimately differ. The deal may include a phase not yet
quoted; the quote may be one of several; the amount may deliberately reflect expected outcome rather
than opening ask. Overwriting a considered number with a quote total loses information.

When they say yes: update the local record, set `updated_opportunity`, and set
`sync_status = pending-push`. Per `CONVENTIONS.md` the CRM push is separate and needs its own
confirmation — and if the profile flags that an amount decrease past a threshold triggers an
approval flow, say so before pushing.

Record the quote against the deal either way, so the pipeline shows a quote was sent even when the
amount didn't move. That's a real stage signal.

---

## Afterwards

Set `sent_date` when it goes, and `outcome` when you know. Accepted, declined, expired, or
withdrawn — with a reason.

Quote outcomes are unusually good data and almost always wasted. Over time they answer questions
nothing else can: which discounts actually close deals, whether quotes are expiring un-chased,
whether one product is always discounted (which usually means it's mispriced rather than that
customers are tough).

Raise a task to follow up before `valid_until`. A quote expiring silently is a deal restarting from
zero.

---

## Judgement

**Never invent a price.** Not for a product not on the list, not for a bundle, not "roughly." If
someone asks for a price you don't have, say so and offer to add it to the price list. The
calculator enforces this and you should not route around it.

**Discounting is easy and permanent.** Every point given is given at every renewal, because the
customer remembers the price and not the reason. Where a discount is being used to solve a problem
discounting won't fix — a stalled deal, a weak champion — it's worth saying so once.

**Show the arithmetic.** A quote total nobody can reconstruct is a quote nobody can defend in a
negotiation. Unit price, tier, quantity, discount, extended — always visible.

When something is blocked, say what would unblock it. "Below floor" is a dead end; "10% takes it to
$79.20 which is above floor, or 25% needs Kelly's approval" is a decision someone can make.

