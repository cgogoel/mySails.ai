#!/usr/bin/env python3
"""
forecast_dashboard.py — render a forecast update as a self-contained HTML dashboard.

Layout follows the nesting the user asked for: the current period first, then the
quarter, then the year. Longer cadences drop the shorter sections — an annual forecast
that opens with last week's meeting count has buried its own point.

Anything that moved materially at quarter or year level gets promoted to a callout at
the top, because that's the thing someone would otherwise miss while reading a weekly.

Colours come from .sales-system/brand.json, same as the spreadsheets, so the whole
system looks like one thing.

Usage:
  forecast_dashboard.py --render <payload.json> --out <file.html>

The payload is assembled by the forecast-update skill; this file only lays it out.
Keeping the two apart means the skill can exercise judgement about what belongs in the
narrative while the rendering stays consistent run to run.
"""

import argparse
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TREND_STYLE = {
    "Heating": ("#E4F1E6", "#1E6B34", "▲"),
    "Warm":    ("#EAF3EC", "#2F7D4A", "▲"),
    "Steady":  ("#EEF1F4", "#4A5563", "—"),
    "Cooling": ("#FDF0D9", "#8A5A00", "▼"),
    "Cold":    ("#FBE3E1", "#A32C22", "▼"),
}


# Every figure on this dashboard is in one currency — the folder's base — because the
# skill hands over converted amounts, not raw ones. The symbol therefore has to follow the
# folder rather than be assumed: a $ in front of a European book's total is a wrong number
# wearing the right punctuation, and nobody reading it would know.
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "AUD": "A$",
           "CAD": "C$", "NZD": "NZ$", "CHF": "CHF ", "SEK": "kr", "NOK": "kr",
           "DKK": "kr", "INR": "₹", "BRL": "R$", "MXN": "MX$", "ZAR": "R",
           "SGD": "S$", "HKD": "HK$", "ILS": "₪", "PLN": "zł", "KRW": "₩"}
_SYMBOL = "$"
_BASE = ""


def set_currency(code):
    """Set the symbol every money() call uses. An unknown code falls back to the code
    itself — 'PHP 1.2M' is honest where a guessed symbol would not be."""
    global _SYMBOL, _BASE
    code = (code or "").strip().upper()
    _BASE = code
    _SYMBOL = SYMBOLS.get(code, (code + " ") if code else "$")


def money(v, cur=None):
    cur = _SYMBOL if cur is None else cur
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            s = f"{v/div:.1f}".rstrip("0").rstrip(".")
            return f"{cur}{s}{suf}"
    return f"{cur}{v:,.0f}"


def currency_band(p, pal):
    """States the currency every number below is in, and — when the book is mixed — what
    was converted to get there. A converted total that does not say it is converted is the
    same failure as a total that never converted at all: the reader cannot tell."""
    mix = p.get("currency_mix") or {}
    unconv = int(p.get("unconverted_records") or 0)
    if not _BASE and not mix and not unconv:
        return ""
    foreign = {k: v for k, v in mix.items() if k.upper() != _BASE and k != "(blank)"}
    bits = []
    if _BASE:
        bits.append(f"All figures in <b>{esc(_BASE)}</b>")
    if foreign:
        parts = ", ".join(f"{n} in {esc(c)}" for c, n in sorted(foreign.items()))
        asof = esc(p.get("rates_as_of", ""))
        bits.append("converted from " + parts
                    + (f" at rates dated {asof}" if asof else "")
                    + ". Closed records keep the rate they were frozen at")
    elif _BASE and mix:
        bits.append("single-currency book, nothing converted")
    warn = ""
    if unconv:
        warn = (f'<div style="margin-top:6px;color:#A32C22;font-weight:600">'
                f'{unconv} record(s) could not be converted and are missing from every '
                f'total below — run <code>fx.py --check</code>.</div>')
    return (f'<div style="background:#fff;border:1px solid #{pal["rule"]};border-radius:8px;'
            f'padding:9px 14px;margin-bottom:16px;font-size:11.5px;color:#5A626C;'
            f'line-height:1.5">{" · ".join(bits)}.{warn}</div>')


def pct(v):
    try:
        return f"{float(v):.0f}%"
    except (TypeError, ValueError):
        return "—"


def esc(s):
    return html.escape(str(s if s is not None else ""))


def bar(attained, target, pal, height=10):
    try:
        p = max(0.0, min(1.0, float(attained) / float(target))) if float(target) else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        p = 0.0
    return (f'<div style="background:#{pal["rule"]};border-radius:{height}px;height:{height}px;'
            f'overflow:hidden"><div style="width:{p*100:.1f}%;height:100%;'
            f'background:#{pal["accent"]};border-radius:{height}px"></div></div>')


def pace_note(g):
    """The sentence that turns a number into a judgement."""
    st = g.get("on_track", "")
    tone = {"Ahead": "good", "On track": "good", "Achieved": "good",
            "Behind": "warn", "At risk": "bad", "Missed": "bad"}.get(st, "neutral")
    return st, tone


def card(label, value, sub="", tone="neutral", pal=None):
    ink = {"good": "#1E6B34", "warn": "#8A5A00", "bad": "#A32C22"}.get(tone, "#1A1A1A")
    return f"""<div style="background:#fff;border:1px solid #{pal['rule']};border-radius:10px;
      padding:14px 16px;flex:1;min-width:150px">
      <div style="font-size:11px;letter-spacing:.05em;text-transform:uppercase;
        color:#7A828C;margin-bottom:6px">{esc(label)}</div>
      <div style="font-size:24px;font-weight:700;color:{ink};line-height:1.1">{esc(value)}</div>
      <div style="font-size:11.5px;color:#7A828C;margin-top:5px">{esc(sub)}</div></div>"""


def goal_block(g, pal):
    st, tone = pace_note(g)
    ink = {"good": "#1E6B34", "warn": "#8A5A00", "bad": "#A32C22"}.get(tone, "#4A5563")
    return f"""<div style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px">
        <div style="font-size:13px;font-weight:600">{esc(g.get('label',''))}
          <span style="color:#7A828C;font-weight:400">· {esc(g.get('level',''))}</span></div>
        <div style="font-size:12.5px"><b>{money(g.get('attained'))}</b>
          <span style="color:#7A828C">of {money(g.get('target'))}</span>
          <span style="color:{ink};font-weight:600;margin-left:8px">{esc(st)}</span></div>
      </div>
      {bar(g.get('attained'), g.get('target'), pal)}
      <div style="font-size:11.5px;color:#7A828C;margin-top:5px">{esc(g.get('note',''))}</div>
    </div>"""


def deal_rows(deals, pal):
    out = []
    for d in deals:
        bg, ink, arrow = TREND_STYLE.get(d.get("trend", "Steady"), TREND_STYLE["Steady"])
        out.append(f"""<tr style="border-bottom:1px solid #{pal['rule']}">
  <td style="padding:11px 12px;vertical-align:top;white-space:nowrap">
    <div style="font-weight:600;font-size:12.5px">{esc(d.get('account',''))}</div>
    <div style="color:#7A828C;font-size:11px">{esc(d.get('id',''))}</div></td>
  <td style="padding:11px 12px;vertical-align:top;white-space:nowrap">
    <span style="background:{bg};color:{ink};font-weight:700;font-size:11px;
      padding:3px 9px;border-radius:11px">{arrow} {esc(d.get('trend',''))}</span>
    <div style="color:#7A828C;font-size:10.5px;margin-top:4px">
      {esc(d.get('activity',''))}</div></td>
  <td style="padding:11px 12px;vertical-align:top;white-space:nowrap;font-size:12.5px">
    {esc(d.get('stage',''))}<div style="color:#7A828C;font-size:11px">
    {esc(d.get('close_date',''))}</div></td>
  <td style="padding:11px 12px;vertical-align:top;text-align:right;white-space:nowrap;
    font-weight:600;font-size:12.5px">{money(d.get('amount'))}</td>
  <td style="padding:11px 12px;vertical-align:top;font-size:12px;line-height:1.5;
    color:#2C3138">{esc(d.get('summary',''))}</td>
  <td style="padding:11px 12px;vertical-align:top;font-size:12px;line-height:1.5">
    <span style="color:#{pal['accent_ink']};font-weight:600">{esc(d.get('next_step',''))}</span>
    </td></tr>""")
    return "".join(out)


def track_group(t, pal, P):
    """One motion — new business or renewals — with its own goals and numbers.

    Kept visually separate because blending them hides both: a strong renewal quarter
    masks weak new business, and a weak renewal quarter looks like a pipeline problem
    when it is actually a retention problem. A renewal at 90% and a new deal at 90%
    are not comparable amounts of work."""
    inner = []
    if t.get("label"):
        inner.append('<div style="display:flex;align-items:baseline;gap:9px;margin-bottom:10px">'
                     '<span style="font-size:12px;font-weight:700;letter-spacing:.06em;'
                     'text-transform:uppercase;color:#%s">%s</span>'
                     '<span style="font-size:11.5px;color:#7A828C">%s</span></div>'
                     % (P.header_bg, esc(t["label"]), esc(t.get("subtitle", ""))))
    if t.get("goals"):
        inner.append('<div style="background:#fff;border:1px solid #%s;border-radius:10px;'
                     'padding:15px 17px;margin-bottom:10px">%s</div>'
                     % (pal["rule"], "".join(goal_block(g, pal) for g in t["goals"])))
    if t.get("renewal_tracker"):
        inner.append(renewal_tracker(t["renewal_tracker"], pal, P))
    if t.get("stats"):
        inner.append('<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">%s</div>'
                     % "".join(card(s.get("label"), s.get("value"), s.get("sub", ""),
                                    s.get("tone", "neutral"), pal) for s in t["stats"]))
    if t.get("narrative"):
        inner.append('<p style="font-size:12.5px;line-height:1.6;color:#2C3138;'
                     'margin:11px 2px 0">%s</p>' % esc(t["narrative"]))
    return '<div style="flex:1;min-width:340px">%s</div>' % "".join(inner)


def track_row(tracks, pal, P):
    return ('<div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start">%s</div>'
            % "".join(track_group(t, pal, P) for t in tracks))


def renewal_tracker(r, pal, P):
    """Renewals are measured against 100%, not against a currency target — every renewal
    not secured is leakage. The ghost marker shows where the bar sat at the last forecast,
    because 'we went from 20% to 50%' is the sentence someone actually wants."""
    due = float(r.get("value_due") or 0)
    sec = float(r.get("value_secured") or 0)
    prev = float(r.get("value_secured_prev") or 0)
    p_now = (sec / due) if due else 0.0
    p_prev = (prev / due) if due else 0.0
    at_risk = float(r.get("value_at_risk") or 0)
    p_risk = (at_risk / due) if due else 0.0

    moved = ""
    if abs(p_now - p_prev) > 0.005:
        moved = (f'<span style="color:#1E6B34;font-weight:600">'
                 f'&#9650; {(p_now-p_prev)*100:.0f} pts since last</span>')

    ghost = ""
    if p_prev > 0.005:
        ghost = (f'<div style="position:absolute;left:{min(p_prev,1)*100:.1f}%;top:-3px;'
                 f'bottom:-3px;width:2px;background:#{P.header_bg};opacity:.55"></div>')

    risk_seg = ""
    if p_risk > 0.005:
        risk_seg = (f'<div style="position:absolute;left:{min(p_now,1)*100:.1f}%;top:0;bottom:0;'
                    f'width:{min(p_risk,1-min(p_now,1))*100:.1f}%;background:#F3C9C4"></div>')

    rows = []
    for x in r.get("at_risk", []):
        rows.append(f"""<li style="margin-bottom:7px;line-height:1.5">
          <b>{esc(x.get('account',''))}</b> · {money(x.get('value'))} ·
          <span style="color:#A32C22">{esc(x.get('why',''))}</span>
          <span style="color:#7A828C"> — {esc(x.get('due',''))}</span></li>""")
    at_risk_html = (f'<div style="margin-top:14px"><div style="font-size:12px;font-weight:700;'
                    f'margin-bottom:7px">At risk</div><ul style="margin:0;padding-left:17px;'
                    f'font-size:12.5px">{"".join(rows)}</ul></div>') if rows else ""

    closed = []
    for x in r.get("closed_since", []):
        good = x.get("outcome", "").lower() in ("renewed", "expansion", "auto-renewed")
        ink = "#1E6B34" if good else "#A32C22"
        closed.append(f"""<li style="margin-bottom:6px;line-height:1.5">
          <b>{esc(x.get('account',''))}</b> · {money(x.get('value'))} ·
          <span style="color:{ink};font-weight:600">{esc(x.get('outcome',''))}</span>
          {(' — ' + esc(x.get('note',''))) if x.get('note') else ''}</li>""")
    closed_html = (f'<div style="margin-top:14px"><div style="font-size:12px;font-weight:700;'
                   f'margin-bottom:7px">Resolved since last forecast</div>'
                   f'<ul style="margin:0;padding-left:17px;font-size:12.5px">'
                   f'{"".join(closed)}</ul></div>') if closed else ""

    return f"""<div style="background:#fff;border:1px solid #{pal['rule']};border-radius:10px;
      padding:16px 18px">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">
        <div style="font-size:13px;font-weight:600">Renewal coverage
          <span style="color:#7A828C;font-weight:400">· goal is 100%</span></div>
        <div style="font-size:12.5px"><b>{money(sec)}</b>
          <span style="color:#7A828C">of {money(due)} due</span>
          <span style="font-weight:700;margin-left:8px">{p_now*100:.0f}%</span></div>
      </div>
      <div style="position:relative;background:#{pal['rule']};border-radius:10px;height:12px;
        overflow:hidden">
        <div style="width:{min(p_now,1)*100:.1f}%;height:100%;background:#1E6B34"></div>
        {risk_seg}{ghost}
      </div>
      <div style="font-size:11.5px;color:#7A828C;margin-top:6px">
        {moved or 'no movement since last forecast'}
        {(' · <span style="color:#A32C22">' + money(at_risk) + ' at risk</span>') if at_risk else ''}
        {(' · ' + esc(r.get('note',''))) if r.get('note') else ''}
      </div>
      {closed_html}{at_risk_html}</div>"""


def section(title, subtitle, inner, pal):
    return f"""<section style="margin-bottom:26px">
  <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:12px">
    <h2 style="font-size:15px;margin:0;color:#1A1A1A">{esc(title)}</h2>
    <span style="font-size:12px;color:#7A828C">{esc(subtitle)}</span></div>
  {inner}</section>"""


def render(p):
    import sheetstyle as S
    set_currency(p.get("base_currency"))
    brand = S.load_brand(p.get("project_root"))
    P = S.Palette(brand)
    pal = {"rule": P.rule, "accent": P.accent, "accent_ink": P.accent_ink,
           "header": P.header_bg, "band": P.band}

    alerts = "".join(
        f"""<div style="background:#fff;border-left:4px solid #{P.accent};
          border:1px solid #{P.rule};border-left:4px solid #{P.accent};
          border-radius:8px;padding:12px 15px;margin-bottom:10px">
          <div style="font-weight:700;font-size:13px;margin-bottom:3px">{esc(a.get('title',''))}</div>
          <div style="font-size:12.5px;color:#3A4048;line-height:1.55">{esc(a.get('detail',''))}</div>
        </div>""" for a in p.get("alerts", []))

    def card_block(title, items):
        return ('<div style="flex:1;min-width:330px">'
                '<div style="font-size:11px;font-weight:700;letter-spacing:.06em;'
                'text-transform:uppercase;color:#%s;margin-bottom:8px">%s</div>'
                '<div style="display:flex;gap:10px;flex-wrap:wrap">%s</div></div>'
                % (P.header_bg, esc(title),
                   "".join(card(c.get("label"), c.get("value"), c.get("sub", ""),
                                c.get("tone", "neutral"), pal) for c in items)))

    # Top-line numbers split by motion as well. A single "pipeline" figure mixing new
    # business with renewals is the number most likely to be quoted on a call and least
    # likely to mean anything.
    hc = p.get("headline_cards")
    if isinstance(hc, dict):
        groups = [(k, v) for k, v in hc.items() if v]
        if len(groups) == 1:
            # One motion tracked — drop the group heading, it labels nothing.
            cards = ('<div style="display:flex;gap:10px;flex-wrap:wrap">'
                     + "".join(card(c.get("label"), c.get("value"), c.get("sub", ""),
                                    c.get("tone", "neutral"), pal) for c in groups[0][1])
                     + "</div>")
        else:
            cards = ('<div style="display:flex;gap:20px;flex-wrap:wrap">'
                     + "".join(card_block(k, v) for k, v in groups) + "</div>")
    else:
        cards = "".join(card(c.get("label"), c.get("value"), c.get("sub", ""),
                             c.get("tone", "neutral"), pal) for c in (hc or []))

    body = []
    band = currency_band(p, pal)
    if band:
        body.append(band)
    if alerts:
        body.append(section("Needs your attention",
                            "material movement at quarter or year level", alerts, pal))
    if cards:
        body.append(f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:26px">{cards}</div>')

    for per in p.get("periods", []):
        inner = []
        if per.get("tracks"):
            inner.append(track_row(per["tracks"], pal, P))
        if per.get("goals"):
            inner.append('<div style="background:#fff;border:1px solid #%s;border-radius:10px;'
                         'padding:16px 18px">%s</div>'
                         % (pal["rule"], "".join(goal_block(g, pal) for g in per["goals"])))
        if per.get("renewals"):
            inner.append('<div style="margin-top:12px">%s</div>'
                         % renewal_tracker(per["renewals"], pal, P))
        if per.get("stats"):
            inner.append('<div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:12px">%s</div>'
                         % "".join(card(s.get("label"), s.get("value"), s.get("sub", ""),
                                        s.get("tone", "neutral"), pal) for s in per["stats"]))
        if per.get("narrative"):
            inner.append(f'''<p style="font-size:13px;line-height:1.65;color:#2C3138;
              margin:14px 2px 0">{esc(per["narrative"])}</p>''')
        body.append(section(per.get("title", ""), per.get("subtitle", ""),
                            "".join(inner), pal))

    if p.get("deals"):
        tbl = f"""<div style="background:#fff;border:1px solid #{pal['rule']};border-radius:10px;
          overflow:hidden"><div style="overflow-x:auto">
          <table style="border-collapse:collapse;width:100%;min-width:900px">
          <thead><tr style="background:#{pal['header']};color:#fff;font-size:11px;
            text-transform:uppercase;letter-spacing:.05em;text-align:left">
            <th style="padding:10px 12px">Account</th><th style="padding:10px 12px">Engagement</th>
            <th style="padding:10px 12px">Stage</th>
            <th style="padding:10px 12px;text-align:right">Amount</th>
            <th style="padding:10px 12px;width:34%">Where it stands</th>
            <th style="padding:10px 12px;width:22%">Next step</th></tr></thead>
          <tbody>{deal_rows(p['deals'], pal)}</tbody></table></div></div>"""
        body.append(section(p.get("deals_title", "New business — deal detail"),
                            "new business only — renewals are tracked above", tbl, pal))

    gen = esc(p.get("generated", ""))
    cur_note = (f" · amounts converted to {esc(_BASE)} from 00-Config/fx-rates"
                if _BASE else "")
    return f"""<!doctype html><meta charset="utf-8">
<title>{esc(p.get('title','Forecast update'))}</title>
<body style="margin:0;padding:26px;background:#F4F5F7;color:#1A1A1A;
 font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<div style="max-width:1240px;margin:0 auto">
  <div style="background:#{P.header_bg};color:#{P.header_fg};border-radius:12px;
    padding:20px 24px;margin-bottom:22px">
    <div style="font-size:11px;letter-spacing:.09em;text-transform:uppercase;opacity:.75">
      {esc(p.get('cadence',''))} forecast · {esc(p.get('scope',''))}</div>
    <h1 style="font-size:21px;margin:6px 0 0">{esc(p.get('title',''))}</h1>
    <div style="font-size:13px;opacity:.85;margin-top:7px;line-height:1.55">
      {esc(p.get('headline',''))}</div>
  </div>
  {''.join(body)}
  <div style="color:#98A0AA;font-size:11px;margin-top:22px">Generated {gen} ·
    engagement from CRM activity, email and calendar · figures from the project registries{cur_note}</div>
</div></body>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(a.render, encoding="utf-8") as f:
        payload = json.load(f)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(render(payload))
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
