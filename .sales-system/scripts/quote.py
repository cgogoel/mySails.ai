#!/usr/bin/env python3
"""
quote.py — resolve prices, apply discounts, and check a quote against the guard rails.

Quoting is the one place in this system where a mistake has a direct commercial cost. A
wrong forecast can be corrected next week; a quote sent below floor, or with a discount
nobody approved, is a number the customer now believes.

So the arithmetic lives here rather than being redone in prose each time, and the checks
are refusals rather than warnings:

- A price must come from the price list. There is no path to inventing one.
- The volume tier is resolved from quantity, not chosen. A rep can't accidentally quote
  tier 4 pricing on a tier 1 quantity.
- A line below its floor price is an error, not a note.
- Anything past the no-approval discount threshold is flagged before the quote is built,
  not discovered after it's sent.

Usage:
  quote.py --price <project> --sku Q-SCOUT-DEV --qty 500 [--discount 10]
  quote.py --build <project> --lines lines.json [--out totals.json]
  quote.py --check <project> --quote QUOTE-0003

lines.json: [{"sku":"Q-SCOUT-DEV","quantity":500,"discount_pct":10,
              "discount_reason":"3-year commitment"}]
"""

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_price_list(root):
    import csvguard as G
    p = G.resolve_path(os.path.join(root, "12-Quotes/price-list.csv"), root)
    s, _ = G.schema_for_file(p, root)
    if not s or not os.path.exists(p):
        return {}
    header, rows = G.read_table(p, s)
    i = {n: k for k, n in enumerate(header)}
    out = {}
    for r in rows:
        sku = (r[i["sku"]] or "").strip()
        if not sku:
            continue
        out[sku.upper()] = {k: (r[i[k]] if k in i else "") for k in header}
    return out


def num(v, default=None):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def resolve_tier(item, qty):
    """Return (unit_price, tier_number). Tiers are earned by quantity, never chosen."""
    price = num(item.get("list_price"))
    tier = 1
    for n in (2, 3, 4):
        mn = num(item.get(f"tier{n}_min_qty"))
        pr = num(item.get(f"tier{n}_price"))
        if mn is not None and pr is not None and qty >= mn:
            price, tier = pr, n
    return price, tier


def price_line(item, qty, discount_pct=0.0):
    """Compute a single line and everything wrong with it."""
    problems = []
    unit, tier = resolve_tier(item, qty)
    if unit is None:
        problems.append(f"{item.get('sku')}: no list price on the price list")
        return None, problems

    minq = num(item.get("min_quantity"))
    if minq and qty < minq:
        problems.append(f"{item.get('sku')}: minimum quantity is {minq:.0f}, asked for {qty:.0f}")
    inc = num(item.get("increment"))
    if inc and inc > 0 and abs((qty / inc) - round(qty / inc)) > 1e-9:
        problems.append(f"{item.get('sku')}: must be bought in multiples of {inc:.0f}")
    if (item.get("status") or "").strip().lower() == "deprecated":
        problems.append(f"{item.get('sku')}: is deprecated — confirm before quoting it")

    eff_to = (item.get("effective_to") or "").strip()
    if eff_to and eff_to < date.today().isoformat():
        problems.append(f"{item.get('sku')}: price expired {eff_to}")

    d = max(0.0, float(discount_pct or 0))
    net = unit * (1 - d / 100.0)
    floor = num(item.get("floor_price"))
    below_floor = floor is not None and net < floor - 1e-9
    if below_floor:
        problems.append(
            f"{item.get('sku')}: {d:.0f}% discount puts the unit price at {net:,.2f}, "
            f"below the floor of {floor:,.2f}")

    max_d = num(item.get("max_discount_no_approval"))
    needs_approval = max_d is not None and d > max_d + 1e-9

    return {
        "sku": item.get("sku"), "name": item.get("name"),
        "unit": item.get("unit"), "quantity": qty,
        "list_unit_price": round(unit, 2), "tier_applied": tier,
        "discount_pct": d, "net_unit_price": round(net, 2),
        "extended": round(net * qty, 2),
        "extended_list": round(unit * qty, 2),
        "below_floor": "yes" if below_floor else "no",
        "needs_approval": needs_approval,
        "max_discount_no_approval": max_d,
        "term_months": num(item.get("term_months")),
        "currency": item.get("currency") or "",
    }, problems


def build(root, lines, org_discount_threshold=None):
    pl = load_price_list(root)
    if not pl:
        return None, ["No price list found at 12-Quotes/price-list. A quote cannot be "
                      "built without one — run configure-project or import your pricing."]
    priced, problems = [], []
    for L in lines:
        sku = (L.get("sku") or "").strip().upper()
        item = pl.get(sku)
        if not item:
            problems.append(f"{sku or '(blank)'}: not on the price list. "
                            f"Add it, or pick from: {', '.join(sorted(pl)[:8])}"
                            + (" ..." if len(pl) > 8 else ""))
            continue
        qty = num(L.get("quantity"), 0) or 0
        if qty <= 0:
            problems.append(f"{sku}: quantity must be greater than zero")
            continue
        d = num(L.get("discount_pct"), 0) or 0
        if d > 0 and not (L.get("discount_reason") or "").strip():
            problems.append(f"{sku}: {d:.0f}% discount has no reason recorded")
        row, probs = price_line(item, qty, d)
        problems.extend(probs)
        if row:
            row["discount_reason"] = L.get("discount_reason", "")
            priced.append(row)

    subtotal_list = round(sum(r["extended_list"] for r in priced), 2)
    subtotal = round(sum(r["extended"] for r in priced), 2)
    disc_amt = round(subtotal_list - subtotal, 2)
    disc_pct = round(100 * disc_amt / subtotal_list, 2) if subtotal_list else 0.0

    needs = [r["sku"] for r in priced if r["needs_approval"]]
    reasons = []
    if needs:
        reasons.append("line discount over threshold: " + ", ".join(needs))
    if org_discount_threshold is not None and disc_pct > org_discount_threshold:
        reasons.append(f"blended discount {disc_pct:.1f}% exceeds the "
                       f"{org_discount_threshold:.0f}% approval threshold")

    terms = {r["term_months"] for r in priced if r["term_months"]}
    annualised = None
    if len(terms) == 1:
        t = terms.pop()
        if t:
            annualised = round(subtotal * (12.0 / t), 2)

    return {
        "lines": priced,
        "subtotal_list": subtotal_list,
        "discount_amount": disc_amt,
        "discount_pct": disc_pct,
        "subtotal": subtotal,
        "total": subtotal,
        "annualised_value": annualised,
        "needs_approval": bool(reasons),
        "approval_reason": "; ".join(reasons),
        "below_floor_lines": [r["sku"] for r in priced if r["below_floor"] == "yes"],
        "mixed_terms": len(terms) > 1,
    }, problems


def show(res, problems):
    if problems:
        print("PROBLEMS — resolve these before issuing:")
        for p in problems:
            print(f"  · {p}")
        print()
    if not res:
        return 1
    print(f"{'sku':16} {'qty':>7} {'tier':>4} {'list':>10} {'disc':>6} "
          f"{'net':>10} {'extended':>12}")
    for r in res["lines"]:
        print(f"{r['sku'][:16]:16} {r['quantity']:>7,.0f} {r['tier_applied']:>4} "
              f"{r['list_unit_price']:>10,.2f} {r['discount_pct']:>5.0f}% "
              f"{r['net_unit_price']:>10,.2f} {r['extended']:>12,.2f}")
    print(f"\n{'list total':>28} {res['subtotal_list']:>14,.2f}")
    print(f"{'discount':>28} {-res['discount_amount']:>14,.2f}  ({res['discount_pct']:.1f}%)")
    print(f"{'TOTAL':>28} {res['total']:>14,.2f}")
    if res["annualised_value"]:
        print(f"{'annualised':>28} {res['annualised_value']:>14,.2f}")
    if res["mixed_terms"]:
        print("\nnote: lines have different contract terms — annualised value not computed")
    if res["below_floor_lines"]:
        print(f"\nBELOW FLOOR: {', '.join(res['below_floor_lines'])} — do not issue")
    if res["needs_approval"]:
        print(f"\nNEEDS APPROVAL: {res['approval_reason']}")
    return 1 if (problems or res["below_floor_lines"]) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--price"); ap.add_argument("--build"); ap.add_argument("--check")
    ap.add_argument("--sku"); ap.add_argument("--qty", type=float)
    ap.add_argument("--discount", type=float, default=0)
    ap.add_argument("--reason", default="")
    ap.add_argument("--lines"); ap.add_argument("--out")
    ap.add_argument("--threshold", type=float)
    ap.add_argument("--next-number", dest="next_number",
                    help="Project root: allocate the next quote number")
    ap.add_argument("--freeze-check", dest="freeze_check",
                    help="Project root: verify sent/accepted quotes still match their lines")
    a = ap.parse_args()

    if a.next_number:
        import csvguard as G
        root = os.path.abspath(a.next_number)
        p = G.resolve_path(os.path.join(root, "12-Quotes/quotes.csv"), root)
        s, _ = G.schema_for_file(p, root)
        year = date.today().year
        n = 0
        if s and os.path.exists(p):
            h, rows = G.read_table(p, s)
            i = {c: k for k, c in enumerate(h)}
            import re as _re
            for r in rows:
                m = _re.fullmatch(rf"Q-{year}-(\d+)", (r[i["quote_number"]] or "").strip())
                if m:
                    n = max(n, int(m.group(1)))
        print(f"Q-{year}-{n + 1:04d}")
        return 0

    if a.freeze_check:
        # A quote the customer has seen must stay reconstructable. Recompute every
        # sent/accepted quote from its lines; a mismatch means someone edited a row
        # that was supposed to be immutable.
        import csvguard as G
        root = os.path.abspath(a.freeze_check)
        qp = G.resolve_path(os.path.join(root, "12-Quotes/quotes.csv"), root)
        lp = G.resolve_path(os.path.join(root, "12-Quotes/quote-lines.csv"), root)
        qs, _ = G.schema_for_file(qp, root); ls, _ = G.schema_for_file(lp, root)
        if not (qs and ls and os.path.exists(qp) and os.path.exists(lp)):
            print("no quotes to check"); return 0
        qh, qr = G.read_table(qp, qs); qi = {c: k for k, c in enumerate(qh)}
        lh, lr = G.read_table(lp, ls); li = {c: k for k, c in enumerate(lh)}
        bad = 0
        for q in qr:
            if q[qi["status"]] not in ("Sent", "Accepted", "Under Negotiation"):
                continue
            lines = [x for x in lr if x[li["quote_id"]] == q[qi["id"]]]
            recomputed = sum(num(x[li["extended"]], 0) or 0 for x in lines)
            stored = num(q[qi["total"]], 0) or 0
            if abs(recomputed - stored) > 0.51:
                bad += 1
                print(f"  TAMPERED? {q[qi['quote_number']]} ({q[qi['status']]}): stored "
                      f"total {stored:,.2f} but lines sum to {recomputed:,.2f}. A sent "
                      f"quote must not change — restore from backup or issue a new version.")
        print("all sent quotes intact" if not bad else f"{bad} quote(s) inconsistent")
        return 1 if bad else 0

    if a.price:
        root = os.path.abspath(a.price)
        lines = [{"sku": a.sku, "quantity": a.qty,
                  "discount_pct": a.discount, "discount_reason": a.reason or "n/a"}]
        res, probs = build(root, lines, a.threshold)
        return show(res, probs)

    if a.build:
        root = os.path.abspath(a.build)
        with open(a.lines, encoding="utf-8") as f:
            lines = json.load(f)
        res, probs = build(root, lines, a.threshold)
        rc = show(res, probs)
        if a.out and res:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump({"result": res, "problems": probs}, f, indent=2)
            print(f"\nwrote {a.out}")
        return rc

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
