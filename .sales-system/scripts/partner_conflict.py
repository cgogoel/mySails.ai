#!/usr/bin/env python3
"""
partner_conflict.py — check an incoming deal registration against existing claims.

Channel conflict is expensive and slow to unwind. Two partners working the same end
customer discover it late, usually when both quote, and someone loses margin or a
relationship. The check has to happen at registration time, before approval, and it has
to be consistent — a rule applied by memory gets applied differently by different people.

The hard part is identity. "Acme Corp", "ACME Corporation", "Acme, Inc." and
"Acme Corp." are one customer, and name matching alone misses that constantly. Domain is
the reliable key where it exists, so it's checked first and weighted highest.

Conflict is by TIER, not by partner. Two partners on one deal is normal channel
structure — a distributor and a reseller teaming on the same end customer is how
two-tier works, and a distributor who also resells occupies both tiers alone. Neither
is a conflict. What conflicts is two partners claiming the SAME tier.

  Same tier claimed     another partner already holds this tier on this customer
  Teaming — no conflict a different tier is taken; the deal is two-tier
  Role not permitted    the partner is not approved to act in the tier they claimed
  Direct opportunity    we are already selling to them ourselves
  Existing customer     they already buy from us
  Territory mismatch    outside the partner's countries/segments, or on their excluded list
  Expired claim         a lapsed registration — not blocking, but the prior partner
                        should hear about it before someone else is approved

Usage:
  partner_conflict.py --check <project> --partner "GuidePoint" --role Reseller \\
      --customer "Acme Corp" [--distributor "Carahsoft"] \\
      [--domain acme.com] [--country US] [--segment Enterprise]
  partner_conflict.py --list <project> [--partner "Optiv"]     # partner deal list
  partner_conflict.py --audit <project>                        # every open claim
"""

import argparse
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Suffixes that carry no identifying information. Stripping them is what turns
# "Acme Corporation" and "Acme, Inc." into the same key.
NOISE = r"\b(inc|inc\.|llc|ltd|limited|corp|corporation|co|company|plc|gmbh|sa|nv|bv|ag|" \
        r"holdings|group|international|technologies|technology|systems|solutions|services|" \
        r"software|the|and|of)\b"


def norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(NOISE, " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_domain(s):
    s = (s or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    s = s.split("/")[0].split("@")[-1]
    return s or ""


def name_match(a, b):
    """Conservative. Returns (match, how). Better to surface a near-miss for a human
    than to silently decide two similar names are the same company."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False, ""
    if na == nb:
        return True, "exact"
    if na in nb or nb in na:
        return True, "contained"
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb:
        overlap = len(ta & tb) / min(len(ta), len(tb))
        if overlap >= 0.75:
            return True, f"{overlap:.0%} token overlap"
    return False, ""


def load(root, rel):
    import csvguard as G
    p = G.resolve_path(os.path.join(root, rel), root)
    s, _ = G.schema_for_file(p, root)
    if not s or not os.path.exists(p):
        return []
    h, rows = G.read_table(p, s)
    return [dict(zip(h, r)) for r in rows]


def split_list(v):
    return [x.strip().lower() for x in (v or "").split(";") if x.strip()]


def check_territory(partner, country, segment, customer):
    """Territory problems are contractual rather than practical, so they're reported
    separately from customer collisions."""
    out = []
    countries = split_list(partner.get("countries"))
    if countries and country and country.strip().lower() not in countries:
        out.append(f"{country} is outside their territory ({partner.get('countries')})")
    segs = split_list(partner.get("segments_served"))
    if segs and segment and segment.strip().lower() not in segs:
        out.append(f"{segment} is outside their segments ({partner.get('segments_served')})")
    excluded = [norm_name(x) for x in split_list(partner.get("excluded_accounts"))]
    if excluded and norm_name(customer) in excluded:
        out.append(f"{customer} is on their excluded-accounts list")
    return out


def tiers_held(reg):
    """Which tiers an existing registration occupies, as {tier: (partner_id, name)}."""
    out = {}
    if (reg.get("distributor_id") or "").strip():
        out["Distributor"] = (reg["distributor_id"].strip(),
                              reg.get("distributor_name") or reg["distributor_id"])
    if (reg.get("reseller_id") or "").strip():
        out["Reseller"] = (reg["reseller_id"].strip(),
                           reg.get("reseller_name") or reg["reseller_id"])
    # Older rows recorded only a submitting partner with no tier. Treat that as a
    # Reseller claim — the common single-tier case — rather than as claiming nothing,
    # which would let a genuine collision through unnoticed.
    if not out and (reg.get("partner_id") or "").strip():
        out["Reseller"] = (reg["partner_id"].strip(),
                           reg.get("partner_name") or reg["partner_id"])
    return out


def role_permitted(partner, role):
    """Blank roles_supported means unconstrained — don't invent a restriction that the
    agreement doesn't state."""
    allowed = [x.strip().lower() for x in (partner.get("roles_supported") or "").split(";")
               if x.strip()]
    if not allowed:
        return True
    return (role or "").strip().lower() in allowed


def check(root, partner_name, customer, domain="", country="", segment="",
          role="Reseller", distributor=None, as_of=None):
    as_of = as_of or date.today()
    partners = load(root, "11-Partners/partners.csv")
    regs = load(root, "11-Partners/deal-registrations.csv")
    opps = load(root, "07-Opportunities/opportunities.csv")
    custs = load(root, "02-Context/Customers/customers.csv")

    me = None
    for p in partners:
        ok, _ = name_match(p.get("name"), partner_name)
        if ok:
            me = p
            break

    findings = []
    dom = norm_domain(domain)

    # --- is this partner even allowed to act in the tier they're claiming?
    if me and not role_permitted(me, role):
        findings.append(("Role not permitted", "block",
                         f"{me.get('name')} is approved for "
                         f"{me.get('roles_supported') or 'no roles on record'}, "
                         f"not {role}", ""))

    # --- existing claims on this customer, evaluated TIER BY TIER.
    # Two partners on one deal is normal channel structure. What collides is two
    # partners claiming the same tier.
    my_id = me.get("id") if me else None
    want = {role}
    if distributor:
        want.add("Distributor")

    for r in regs:
        if (r.get("status") or "") not in ("Approved", "Submitted", "Under Review"):
            continue
        hit, how = name_match(r.get("end_customer"), customer)
        dhit = dom and norm_domain(r.get("end_customer_domain")) == dom
        if not (hit or dhit):
            continue
        basis = "domain" if dhit else f"name ({how})"
        exp = (r.get("protection_expires") or "").strip()
        lapsed = bool(exp) and exp < as_of.isoformat()
        held = tiers_held(r)

        if lapsed:
            who = ", ".join(f"{n} as {t}" for t, (_, n) in held.items()) or "a partner"
            findings.append(("Expired claim", "warn",
                             f"{r['id']}: {who} held a claim on {r.get('end_customer')} that "
                             f"lapsed {exp}. Not blocking, but tell them before approving someone "
                             f"else — matched on {basis}", r["id"]))
            continue

        days = ""
        if exp:
            try:
                days = f", {(date.fromisoformat(exp) - as_of).days} days left"
            except ValueError:
                pass

        for tier in sorted(want):
            holder = held.get(tier)
            if not holder:
                continue
            hid, hname = holder
            if my_id and hid == my_id and tier == role:
                findings.append(("Already holds this tier", "info",
                                 f"{r['id']}: this partner already holds the {tier} tier on "
                                 f"{r.get('end_customer')} — matched on {basis}", r["id"]))
            elif tier == "Distributor" and distributor and hid != my_id:
                dist_ok, _ = name_match(hname, distributor)
                if dist_ok:
                    findings.append(("Teaming — no conflict", "info",
                                     f"{r['id']}: {hname} already holds the Distributor tier, "
                                     f"which is the distributor named on this submission — "
                                     f"consistent two-tier structure", r["id"]))
                else:
                    findings.append(("Same tier claimed", "block",
                                     f"{r['id']}: {hname} holds the Distributor tier on "
                                     f"{r.get('end_customer')} until {exp or 'unspecified'}"
                                     f"{days}, but this submission names {distributor} — "
                                     f"matched on {basis}", r["id"]))
            else:
                findings.append(("Same tier claimed", "block",
                                 f"{r['id']}: {hname} already holds the {tier} tier on "
                                 f"{r.get('end_customer')} until {exp or 'unspecified'}{days} — "
                                 f"matched on {basis}", r["id"]))

        # Tiers held by others that we are NOT claiming: that's teaming, and worth
        # saying so explicitly rather than staying silent.
        for tier, (hid, hname) in held.items():
            if tier in want:
                continue
            if my_id and hid == my_id:
                continue
            findings.append(("Teaming — no conflict", "info",
                             f"{r['id']}: {hname} holds the {tier} tier on "
                             f"{r.get('end_customer')}. Different tier from this "
                             f"{role} submission — two-tier deal, not a conflict. Confirm both "
                             f"partners know they are teaming.", r["id"]))

    # --- our own pipeline
    for o in opps:
        if (o.get("stage") or "").startswith("Closed"):
            continue
        hit, how = name_match(o.get("account_name"), customer)
        if not hit:
            continue
        other = (o.get("partner_id") or "").strip()
        if other and my_id and other != my_id:
            # An opportunity records one partner without a tier, so this can't be
            # resolved automatically — surface it for a human rather than guessing.
            findings.append(("Same tier claimed", "warn",
                             f"{o['id']}: open deal at {o.get('account_name')} is already "
                             f"attached to partner {other}. Confirm which tier they hold — if "
                             f"it is not {role}, this is teaming rather than a conflict.",
                             o["id"]))
        elif not other:
            findings.append(("Direct opportunity", "block",
                             f"{o['id']}: we have an open direct deal at {o.get('account_name')} "
                             f"({o.get('stage')}, {o.get('amount') or '?'}) — matched on name ({how})",
                             o["id"]))

    # --- already a customer
    for cst in custs:
        hit, how = name_match(cst.get("account_name"), customer)
        dhit = dom and norm_domain(cst.get("website")) == dom
        if hit or dhit:
            findings.append(("Existing customer", "warn",
                             f"{cst.get('id')}: {cst.get('account_name')} is already a customer "
                             f"(owner {cst.get('csm_or_owner') or 'unassigned'}) — a registration "
                             f"here is expansion, and usually belongs to whoever holds the account",
                             cst.get("id", "")))

    # --- territory
    if me:
        for t in check_territory(me, country, segment, customer):
            findings.append(("Territory mismatch", "warn", t, ""))
    else:
        findings.append(("Territory mismatch", "warn",
                         f"'{partner_name}' is not in the partner registry — add them before "
                         f"approving a registration", ""))

    order = {"block": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: order.get(f[1], 3))
    return findings, me


def report(findings, partner, customer):
    blocking = [f for f in findings if f[1] == "block"]
    print(f"Registration check — {partner} for {customer}\n")
    if not findings:
        print("  CLEAR — no conflicts found. Safe to approve.")
        return 0
    for ctype, sev, detail, ref in findings:
        tag = {"block": "BLOCK", "warn": "CHECK", "info": "note "}[sev]
        print(f"  [{tag}] {ctype}")
        print(f"          {detail}")
    print()
    if blocking:
        print(f"  DO NOT APPROVE — {len(blocking)} blocking conflict(s). Decline, or resolve with")
        print("  the other partner and record how in resolution_note.")
        return 1
    print("  No blocking conflict, but the items above need a human decision before approval.")
    return 0


def partner_deal_list(root, partner_filter=None):
    partners = {p["id"]: p for p in load(root, "11-Partners/partners.csv")}
    opps = load(root, "07-Opportunities/opportunities.csv")
    regs = load(root, "11-Partners/deal-registrations.csv")
    rows = []
    for o in opps:
        pid = (o.get("partner_id") or "").strip()
        if not pid:
            continue
        p = partners.get(pid, {})
        if partner_filter and not name_match(p.get("name", ""), partner_filter)[0]:
            continue
        rows.append({"kind": "Opportunity", "id": o["id"], "partner": p.get("name", pid),
                     "motion": o.get("partner_role") or p.get("motion", ""),
                     "account": o.get("account_name"), "stage": o.get("stage"),
                     "amount": o.get("amount"), "close": o.get("close_date")})
    linked = {(o.get("deal_registration_id") or "").strip()
              for o in opps if (o.get("deal_registration_id") or "").strip()}
    for r in regs:
        # converted if either side carries the link — the bidirectional reference is
        # frequently only populated on one, and double-counting is the failure mode
        if r.get("opportunity_id") or r["id"] in linked:
            continue
        if partner_filter and not name_match(r.get("partner_name", ""), partner_filter)[0]:
            continue
        rows.append({"kind": "Registration", "id": r["id"], "partner": r.get("partner_name"),
                     "motion": "Sell-through", "account": r.get("end_customer"),
                     "stage": r.get("status"), "amount": r.get("estimated_amount"),
                     "close": r.get("estimated_close_date")})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check"); ap.add_argument("--list"); ap.add_argument("--audit")
    ap.add_argument("--partner"); ap.add_argument("--customer")
    ap.add_argument("--domain", default=""); ap.add_argument("--country", default="")
    ap.add_argument("--segment", default=""); ap.add_argument("--as-of")
    ap.add_argument("--role", default="Reseller",
                    help="Tier this partner is claiming: Distributor, Reseller, Referral")
    ap.add_argument("--distributor", default="",
                    help="Distributor named on a two-tier submission")
    a = ap.parse_args()
    as_of = date.fromisoformat(a.as_of) if a.as_of else date.today()

    if a.check:
        if not (a.partner and a.customer):
            print("--check needs --partner and --customer", file=sys.stderr)
            return 2
        f, _ = check(os.path.abspath(a.check), a.partner, a.customer,
                     a.domain, a.country, a.segment, a.role,
                     a.distributor or None, as_of)
        return report(f, f"{a.partner} as {a.role}"
                      + (f" (dist: {a.distributor})" if a.distributor else ""),
                      a.customer)

    if a.list:
        rows = partner_deal_list(os.path.abspath(a.list), a.partner)
        if not rows:
            print("No partner-attributed deals or open registrations.")
            return 0
        print(f"{'type':13} {'id':13} {'partner':22} {'motion':13} {'account':22} "
              f"{'stage':16} {'amount':>10}")
        for r in sorted(rows, key=lambda x: (x["partner"] or "", x["kind"])):
            amt = r["amount"]
            try:
                amt = f"{float(amt):,.0f}"
            except (TypeError, ValueError):
                amt = amt or "—"
            print(f"{r['kind']:13} {r['id']:13} {(r['partner'] or '')[:22]:22} "
                  f"{(r['motion'] or '')[:13]:13} {(r['account'] or '')[:22]:22} "
                  f"{(r['stage'] or '')[:16]:16} {amt:>10}")
        return 0

    if a.audit:
        root = os.path.abspath(a.audit)
        regs = load(root, "11-Partners/deal-registrations.csv")
        live = [r for r in regs if (r.get("status") or "") == "Approved"]
        print(f"{'id':13} {'partner':22} {'end customer':26} {'expires':11} {'days':>5}")
        for r in sorted(live, key=lambda x: x.get("protection_expires") or ""):
            exp = (r.get("protection_expires") or "").strip()
            d = ""
            if exp:
                try:
                    d = str((date.fromisoformat(exp) - as_of).days)
                except ValueError:
                    pass
            flag = "  <- LAPSED" if d and int(d) < 0 else ("  <- expiring" if d and int(d) <= 14 else "")
            print(f"{r['id']:13} {(r.get('partner_name') or '')[:22]:22} "
                  f"{(r.get('end_customer') or '')[:26]:26} {exp or '—':11} {d or '—':>5}{flag}")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
