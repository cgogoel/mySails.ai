---
name: "partner-tracking"
description: "Track channel and technology partners, their deals, and their deal registrations. Handles sell-through and sell-with separately, and models two-tier channel properly — a distributor and reseller teaming on one deal is normal structure, not a conflict, and a partner may occupy both tiers alone. Runs a tier-aware conflict check on every registration, matching end customers by domain and normalised name against other partners' live claims, direct opportunities, existing customers, permitted roles, and territory boundaries. Also lists partner deals and audits protection windows. Use whenever the user mentions partners, channel, resellers, distributors, deal registration, channel conflict, partner territories, two-tier or teaming, partner pipeline or margin, co-selling, or asks which partners are performing or have gone quiet."
---

# Partner Tracking

Two motions live here and they behave nothing alike:

**Sell-through.** A reseller, distributor, or MSP transacts. They own the paper, often the customer
relationship, and take margin. Your revenue is net of that margin and your visibility into the end
customer is partial.

**Sell-with.** A technology partner's product completes the solution. You transact, there's no
margin, and the partner brings access, credibility, or a technical requirement being satisfied.

**Summing these into one "partner revenue" number makes partner reporting useless.** `motion` on
the partner record keeps them apart, and it's the field to check before answering almost any
question here.

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
3. Read `00-Config/config.md` for `scope`, and `.sales-system/crm-profile/field-map.json`.
4. Repair the registries:

```bash
python3 "$S/csvguard.py" --check-all <project>
```

`11-Partners/` holds `partners`, `deal-registrations`, and per-partner folders.

---

## Deals have tiers, and conflict is by tier

This is the model everything else depends on, and getting it wrong in either direction is costly.

A sell-through deal has up to two **tiers**: a **Distributor** and a **Reseller**. Each tier holds
at most one partner. Three shapes are all legitimate:

| Shape | Example | Is it a conflict? |
|---|---|---|
| **Two-tier** | Carahsoft distributes, GuidePoint resells | **No** — this is how two-tier channel works |
| **Single-tier, both roles** | Carahsoft distributes *and* resells | **No** — one partner, two tiers |
| **Single-tier, one role** | Optiv resells, no distributor | **No** |
| **Same tier, two partners** | GuidePoint and Optiv both want Reseller | **Yes** — this is the conflict |

**Two partners on one deal is normal. Two partners in the same tier is not.** Treating any second
partner as a conflict blocks legitimate teaming and makes the channel team stop using the check;
treating tier collisions as fine produces the dispute you were trying to prevent.

Partners carry `roles_supported` — a semicolon list of the tiers they're approved to occupy.
`partner_type` says what they primarily are; `roles_supported` says what they're permitted to do.
A distributor who also resells has both. Blank means unconstrained; don't invent a restriction the
agreement doesn't state.

---

## The conflict check

**Run it on every registration, before approving anything.**

```bash
python3 "$S/partner_conflict.py" --check <project> \
  --partner "GuidePoint Security" --role Reseller \
  --customer "Dept of Homeland Security" --domain dhs.gov \
  --distributor "Carahsoft" --country US --segment Government
```

`--role` is the tier being claimed. `--distributor` names the distributor on a two-tier submission
— supplying it lets the checker confirm the tiers are consistent rather than colliding.

Set `conflict_checked = yes` with the result in `conflict_type` and `conflict_detail`. That field
exists so an unchecked approval is visible afterwards.

### Why the checker rather than reading the registry

Identity is the hard part. "Acme Corp", "ACME Corporation" and "Acme, Inc." are one customer, and
eyeballing a list misses that reliably. The checker strips legal suffixes and corporate noise words,
and matches on **domain first** — a submission for "Acme, Inc." at `www.acme.com` correctly collides
with a claim on "Acme Corporation" at `acme.com`. It's deliberately conservative, surfacing
near-misses for a human rather than silently deciding two similar names are the same company.

### What it returns

| Finding | Severity | Meaning |
|---|---|---|
| **Same tier claimed** | BLOCK | Another partner already holds this tier on this customer |
| **Role not permitted** | BLOCK | The partner isn't approved to act in the tier they claimed |
| **Direct opportunity** | BLOCK | We're already selling to them ourselves |
| **Teaming — no conflict** | note | A *different* tier is held by someone else. Legitimate two-tier |
| **Already holds this tier** | note | This partner already has it — a duplicate submission, not a conflict |
| **Existing customer** | CHECK | They already buy from us; this is expansion and usually belongs to the account owner |
| **Territory mismatch** | CHECK | Outside their countries or segments, or on their excluded list |
| **Expired claim** | CHECK | A lapsed registration |

**Treat BLOCK as blocking.** Decline, or resolve with the partners involved and record how in
`resolution_note` — that note stops the same dispute being re-litigated in six months.

**Teaming notes still deserve a human moment.** Two partners on a deal who each think they're alone
is the same problem as channel conflict, arriving later. Set `teaming_confirmed` only when both
partners actually know, and say so in the approval.

**Expired claims deserve a courtesy call.** The customer is technically open again, but a partner
who worked a deal for three months and let protection lapse will not react well to a competitor
being registered the next day.

### Territory

Partners carry `countries`, `segments_served`, `named_accounts`, `excluded_accounts`, and
`exclusive_territory`. Territory findings are contractual rather than practical — an **exclusive**
overlap is a breach of agreement, not an awkward conversation, and should be escalated rather than
settled between reps.

`named_accounts` overrides territory in both directions: an account assigned to one partner
shouldn't be registered by another even if the geography fits.

### The protection clock

Record `protection_days` **from the agreement at time of approval**, not looked up later — terms
change, and a claim is governed by what was agreed when it was made.

```bash
python3 "$S/partner_conflict.py" --audit <project>
```

Claims expiring within two weeks warrant a nudge; lapsed ones should be resolved rather than left
ambiguous.

---

## Listing partner deals

```bash
python3 "$S/partner_conflict.py" --list <project> [--partner "Optiv"]
```

Opportunities carrying a `partner_id` alongside registrations not yet converted, with motion,
account, stage and amount.

**It deduplicates across both sides of the link** — a registration counts as converted if either it
carries an `opportunity_id` or an opportunity carries its `deal_registration_id`. That reference is
frequently populated on only one side, and double-counting inflates partner pipeline exactly where
accuracy matters.

Note that opportunities record one partner without a tier. On a two-tier deal, attribution to the
distributor versus the reseller has to come from the registration — say so rather than implying the
opportunity's single partner field tells the whole story.

---

## Derived performance

Recomputed from opportunities carrying `partner_id`. Never hand-edit.

**Gross versus net.** Sell-through revenue is gross; net of margin can differ by a third. Always say
which you're quoting. On two-tier deals margin may be split across both tiers — if the agreement
does that, the single `margin_pct` on each partner won't tell you the whole answer, and it's worth
saying so rather than presenting a confident net figure.

**Sample honesty.** No win rate below a meaningful decided sample.

**`months_since_last_deal` is the leading indicator.** A partner with an agreement, a logo on a
slide, and no deal in six months is dormant regardless of how the relationship feels. This is the
number that turns "we have forty partners" into "we have six."

---

## Health

**`no-deals-90d`** — clearest signal of drift.
**`enablement-lapsed`** — a sell-through partner whose people can't demo doesn't sell.
**`agreement-expiring`** — within 90 days; channel agreements renew slower than customer contracts.
**`single-rep-dependency`** — every deal from one person is a relationship, not a partnership.
**`no-qbr`** — none in two quarters on a tier that warrants one.
**Registered but never closed** — speculative registration to block competitors, or being outsold
once live. Worth distinguishing.

Sell-with health looks different: joint customers, whether the integration survived either side's
releases, whether their field team knows you exist.

---

## Partner forecast

Forecast the motions separately and say so.

**Sell-through** carries risks direct doesn't: partner-forecast deals are less reliable — the
partner's rep is optimistic *and* you're seeing it second-hand. Registration isn't qualification.
Protection windows expire. Margin makes gross and net diverge. On two-tier deals the distributor's
forecast and the reseller's may differ, and the reseller is usually closer to the customer.

Discount partner-sourced commit more heavily than direct, and say you're doing it and why.

**Sell-with** deals are your own with a partner involved. Forecast normally, but track attach rate —
that's the number that says whether the alliance is real.

---

## What to actually do

**Import** — through `crm_sync.py` only, never a hand-rolled script (`CONVENTIONS.md` §3c):

```bash
S=$(python3 "<project>/.sales-system/find_scripts.py") || exit 1
python3 $S/crm_sync.py --refresh <project> --registry partners --json-file recs.json
python3 $S/crm_sync.py --refresh <project> --registry deal_registrations --json-file recs.json
```

Almost everything that makes this registry useful is authored here — territories, named and
excluded accounts, margin, protection days, enablement status. Those are `local` columns and a
refresh never touches them. The performance columns are `derived` and get recomputed below.

**Refresh** — recompute, report what changed. New partner names in deal records that aren't in the
registry are the most useful output.

**Review** — by decision: producing, drifting (with the reason), dormant (re-engage or retire),
coverage gaps. Resist ranking purely by revenue; a small partner in a region you can't otherwise
reach may be worth more than a large one duplicating direct coverage.

**Route a deal** — check existing relationships, registrations, enablement, and what margin does to
the economics. Say what the partner adds — access, delivery, a contract vehicle, a technical
requirement. If the honest answer is "nothing except margin," say that.

**Raise tasks** — honour `01-Tasks/task-rules.csv` caps. Specific ones: re-engage a quiet partner,
renew a lapsing agreement, chase a registration losing protection, resolve a flagged conflict,
confirm teaming on a two-tier deal where `teaming_confirmed` is blank.

---

## Judgement

Partner programmes accumulate partners. Signing one produces a press release; retiring one produces
nothing, so the roster grows and the active-to-nominal ratio quietly falls. "Forty partners, six
with a deal this year, two with more than one" is more useful than a total, and it's the version
that leads to a decision.

On conflict: the temptation is to approve and sort it out later, because declining is an unpleasant
conversation with a partner who has done work. Later is worse — the conversation at registration is
about a rule; the conversation after both partners have quoted is about money.

And be careful not to over-block. A checker that flags every second partner as a conflict trains
people to ignore it, and then it catches nothing.

