#!/usr/bin/env python3
"""
run_integrity.py — make a skipped step impossible to miss.

From late September to late October 2026 one live folder's scheduled daily brief skipped
its activity ingest on nearly every run. Each brief said so — "ingest not run", "floor not
recomputed" — in a sentence in its run notes, and carried on. Nothing counted those
sentences, nothing compared them across days, and four weekday briefs never appeared at
all without anyone being told. The month ended with 23 of 39 deals past the 30-day floor
on a day the last recomputed number was 2.

The defect was not the skipped step. Steps get skipped: a connector times out, a run runs
long. The defect was that a skip cost the run nothing — the brief looked finished either
way. This script is the cost. It brackets the run:

  --begin    before anything else. Runs the registry check itself (so that step cannot be
             skipped), records the run, and checks the tripwires: a cache whose newest
             event is older than STALE_DAYS, weekday briefs missing since the last one, a
             previous run that never finished or failed. Prints TRIPWIRE lines.
  --skip     a required step that genuinely cannot run, with the reason. Recorded, and it
             still fails the run — loudly and honestly instead of silently.
  --finish   after the ingests, --lead-touch and floor_check, before the brief is shown.
             Checks the EVIDENCE each step leaves (watermarks and timestamps the scripts
             write), not the run's own account of what it did, builds the Preflight line,
             and with --brief writes that line as the brief's first line — so the line is
             the script's, and cannot be paraphrased into something kinder.

Exit codes: --begin 0 (never blocks; tripwires are reported, not enforced); --finish 0 when
every required step left evidence, 3 when any did not; 2 usage. Whenever --begin trips or
--finish fails, the LAST line printed is `NOTIFY: <text>` (under 200 characters): the run
must send that text as a push notification. That is the part of the contract a script
cannot do for itself.

Required steps default to: registries, gmail, calendar, crm (only when the profile names
a CRM), lead_touch, floor, drafts, market_sweep. Override with `preflight_required:` in
config.md, comma-separated. The news sweep is governed by its own key instead —
`news_sweep_required:` (default true) — so an override list written before the sweep was
a step does not silently drop it: from 2026-10-29 to 2026-11-16 one folder's brief carried
no news at all, because the sweep was the one section with no evidence check and a missing
section looked exactly like a quiet morning.

Usage:
  run_integrity.py --begin  <project> [--json]
  run_integrity.py --skip   <project> --step crm --reason "Salesforce connector not connected"
  run_integrity.py --skip   <project> --step market_sweep --reason "web search unavailable"
  run_integrity.py --finish <project> [--brief 09-Briefs/Daily/2026-10-29-daily-brief.md] [--json]
  run_integrity.py --status <project>          # tripwires only, no run recorded
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import activity_sync as A  # noqa: E402
import market_sweep as M  # noqa: E402

RUNS = "runs.json"
DEFAULT_REQUIRED = ("registries", "gmail", "calendar", "crm", "lead_touch", "floor", "drafts",
                    "market_sweep")
LABEL = {"registries": "registry check", "gmail": "mail ingest", "calendar": "calendar ingest",
         "crm": "CRM activity read", "lead_touch": "lead clocks", "floor": "30-day floor",
         "drafts": "follow-up drafts", "market_sweep": "news sweep"}
KNOWN_STEPS = set(LABEL)
# CRM activity on records the registry doesn't hold fails the run from this many events
# and this share of the read. Below it, the brief still names them; it just isn't a failure.
UNKNOWN_CRM_MIN, UNKNOWN_CRM_SHARE = 3, 0.2
DRAFTS_DIR = os.path.join("01-Tasks", "Drafts")


def now():
    return datetime.now(timezone.utc)


def iso(t):
    return t.isoformat(timespec="seconds")


def parse(ts):
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def runs_path(root):
    return os.path.join(A.cache_dir(root), RUNS)


def load_runs(root):
    return A.load_json(runs_path(root), {"runs": []})


def save_runs(root, data):
    data["runs"] = data["runs"][-60:]
    A.save_json(runs_path(root), data)


def has_crm(root):
    try:
        import csvguard as G
        return bool(str((G.load_field_map(root) or {}).get("crm", "")).strip())
    except Exception:
        return False


def required(root):
    raw = A.config_value(root, "preflight_required", "")
    steps = [s.strip() for s in raw.split(",") if s.strip()] if raw else list(DEFAULT_REQUIRED)
    if "crm" in steps and not raw and not has_crm(root):
        steps.remove("crm")
    steps = [s for s in steps if s != "market_sweep"]
    if M.required(root):
        steps.append("market_sweep")
    return steps


def brief_dir(root):
    return os.path.join(root, "09-Briefs", "Daily")


def brief_days(root):
    """Weekdays a brief is expected on, from `brief_days:` (e.g. `mon-fri`, `mon,wed,fri`)."""
    raw = (A.config_value(root, "brief_days", "mon-fri") or "mon-fri").lower()
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    if "-" in raw and "," not in raw:
        a, b = [x.strip()[:3] for x in raw.split("-", 1)]
        if a in names and b in names:
            ia, ib = names.index(a), names.index(b)
            return set(range(ia, ib + 1)) if ia <= ib else set(range(ia, 7)) | set(range(0, ib + 1))
    got = {names.index(x.strip()[:3]) for x in raw.split(",") if x.strip()[:3] in names}
    return got or set(range(5))


def missing_briefs(root, today, lookback=21):
    have = set()
    for p in glob.glob(os.path.join(brief_dir(root), "*-daily-brief*.md")):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", os.path.basename(p))
        if m:
            have.add(m.group(1))
    if not have:
        return []
    days, first = brief_days(root), min(have)
    out, d = [], today - timedelta(days=lookback)
    while d < today:
        s = d.isoformat()
        if s >= first and d.weekday() in days and s not in have:
            out.append(s)
        d += timedelta(days=1)
    return out


def reported_gaps(runs):
    """Missing-brief days an earlier, finished run already reported. Those were said once
    (and notified); repeating them on every run for three weeks turns a tripwire into
    wallpaper, which is how the next real gap gets missed. Older runs kept only the text."""
    seen = set()
    for r in runs:
        if not r.get("finished_at"):
            continue
        if "missing_days" in r:
            seen.update(r["missing_days"])
            continue
        for t in r.get("tripwires") or []:
            if t.startswith("no daily brief"):
                seen.update(re.findall(r"\d{4}-\d{2}-\d{2}", t))
    return seen


def tripwires(root, today, gaps_out=None):
    out = []
    st = status_json(root)
    if st.get("stale"):
        age = st.get("newest_event_age_days")
        out.append(f"activity cache stale: newest event {st.get('newest_event') or 'none'}"
                   + (f", {age} days old" if age is not None else ""))
    runs = load_runs(root)["runs"]
    all_gaps = missing_briefs(root, today)
    gaps = [g for g in all_gaps if g not in reported_gaps(runs)]
    if gaps_out is not None:
        gaps_out.extend(all_gaps)
    if gaps:
        out.append(f"no daily brief on {len(gaps)} expected day(s): {', '.join(gaps)}")
    try:
        od = M.overdue(root, today)
    except Exception as e:  # a broken sweep plan must not hide the other tripwires
        od = []
        out.append(f"news sweep overdue check failed: {e}")
    if od:
        out.append(f"news sweep: {len(od)} account(s) not searched in {M.OVERDUE_DAYS}+ days: "
                   + ", ".join(od[:6]) + (" …" if len(od) > 6 else ""))
    if runs:
        last = runs[-1]
        if not last.get("finished_at"):
            out.append(f"the previous run ({last.get('started_at', '?')[:16]}) never finished")
        elif last.get("ok") is False:
            out.append(f"the previous run ({last.get('started_at', '?')[:10]}) failed: "
                       + "; ".join(last.get("failures", [])[:2]))
    return out


def status_json(root):
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        A.status(root, as_json=True)
    try:
        return json.loads(buf.getvalue().strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def notify_text(prefix, items):
    s = f"{prefix}: " + "; ".join(items)
    return s if len(s) <= 195 else s[:192] + "…"


# ---------------------------------------------------------------------------- begin

def begin(root, as_json=False):
    t0, today = now(), date.today()
    guard = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csvguard.py")
    p = subprocess.run([sys.executable, guard, "--check-all", root],
                       capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip()
    meta = A.load_json(A.cache_paths(root)[1], {"sources": {}})
    prior = {s: m.get("last_sync") for s, m in (meta.get("sources") or {}).items()}
    gaps = []
    trips = tripwires(root, today, gaps)
    # Every NEEDS YOU line, not a tail: a brief that was handed the last three lines named
    # two of the four rows that needed a decision.
    needs = [l.strip() for l in out.splitlines() if l.strip().startswith("NEEDS YOU")]
    run = {"id": t0.strftime("%Y%m%dT%H%M%SZ"), "started_at": iso(t0),
           "registries": {"exit": p.returncode, "tail": out.splitlines()[-3:] if out else [],
                          "needs_you": len(needs), "needs_you_rows": needs},
           "prior_sync": prior, "tripwires": trips, "missing_days": gaps, "skips": {}}
    data = load_runs(root)
    data["runs"].append(run)
    save_runs(root, data)
    if as_json:
        print(json.dumps(run))
    else:
        print(f"run {run['id']} started. registry check: "
              + ("clean" if p.returncode == 0 else
                 f"{run['registries']['needs_you']} row(s) need a human decision"
                 if p.returncode == 1 else f"FAILED (exit {p.returncode})"))
        for line in needs:
            print(f"  {line}")
        if p.returncode not in (0, 1) and out:
            for line in out.splitlines()[-6:]:
                print(f"  {line}")
        for s in ("gmail", "calendar", "crm"):
            if prior.get(s):
                # Start ON the watermark day, not after it: the last read may have ended
                # partway through that day (a run at 09:00 has not seen the afternoon), and
                # dedup makes the overlap free.
                print(f"  {s}: last read through {prior[s]} — this run's window starts "
                      f"{prior[s]} (inclusive) or earlier")
            elif s in required(root):
                print(f"  {s}: never read — full 90-day window")
        for t in trips:
            print(f"TRIPWIRE: {t}")
    if trips:
        print("NOTIFY: " + notify_text("Sales brief tripwire", trips))
    return 0


def current_run(root):
    data = load_runs(root)
    if not data["runs"] or data["runs"][-1].get("finished_at"):
        return data, None
    return data, data["runs"][-1]


def skip(root, step, reason):
    data, run = current_run(root)
    if not run:
        print("error: no run in progress — call --begin first", file=sys.stderr)
        return 2
    if step not in KNOWN_STEPS:
        print(f"warning: {step!r} is not a step this script knows "
              f"({', '.join(sorted(KNOWN_STEPS))}); recorded anyway", file=sys.stderr)
    run["skips"][step] = reason
    save_runs(root, data)
    print(f"recorded: {LABEL.get(step, step)} skipped — {reason}. This run will be reported "
          "as FAILED in its Preflight line and notified; that is intended.")
    return 0


# --------------------------------------------------------------------------- finish

def _after(ts, t0):
    t = parse(ts)
    return bool(t and t0 and t >= t0)


def evaluate(root, run):
    t0 = parse(run["started_at"])
    meta = A.load_json(A.cache_paths(root)[1], {"sources": {}})
    src = meta.get("sources") or {}
    req = required(root)
    parts, fails = [], []

    # registries
    # csvguard: 0 clean or repaired, 1 rows that need a human (a data question for the
    # brief to raise, not a run that failed), anything else the check itself broke.
    rg = run.get("registries") or {}
    if rg.get("exit") == 0:
        parts.append("registries clean")
    elif rg.get("exit") == 1:
        parts.append(f"registries checked, {rg.get('needs_you', '?')} row(s) need you")
    else:
        parts.append(f"registry check exit {rg.get('exit')}")
        if "registries" in req:
            fails.append(f"registry check exit {rg.get('exit')}")

    def ingest_part(name, label):
        m = src.get(name) or {}
        crm_names = [s for s in src if name == "crm" and A.is_crm_source(s, root)]
        if name == "crm" and crm_names:
            m = max((src[s] for s in crm_names), key=lambda x: x.get("last_ingest_at", ""))
        if not _after(m.get("last_ingest_at"), t0):
            why = run["skips"].get(name)
            msg = f"{label} did not run" + (f" ({why})" if why else "")
            if name in req:
                fails.append(msg)
            parts.append(msg)
            return
        rd = m.get("read") or {}
        bit = label + ": "
        if name == "gmail":
            win = m.get("window") or {}
            bit += f"{rd.get('in', '?')} in / {rd.get('out', '?')} out"
            if win:
                bit += f" ({win.get('since')}..{win.get('until')})"
            prior = (run.get("prior_sync") or {}).get("gmail")
            if prior and win.get("since") and win["since"] > prior:
                fails.append(f"mail gap: last read through {prior} (possibly partway), this "
                             f"read starts {win['since']} — start on {prior}")
            if not m.get("window_declared"):
                fails.append("mail ingest declared no window — watermark unreliable")
            if rd.get("suspect_empty_days"):
                fails.append(f"mail suspect-empty days {','.join(rd['suspect_empty_days'])}")
            if rd.get("one_sided_days"):
                fails.append("sent but nothing received on "
                             f"{','.join(rd['one_sided_days'])} — re-run the received query")
            if rd.get("unqueried"):
                fails.append(f"mail not queried: {', '.join(rd['unqueried'][:4])}"
                             + (" …" if len(rd["unqueried"]) > 4 else ""))
            if rd.get("saturated"):
                fails.append(f"mail saturated {','.join(rd['saturated'])}")
            if rd.get("out") == 0 and rd.get("days", 0) >= 2:
                fails.append("zero outbound mail over a multi-day window")
            if rd.get("in") == 0 and rd.get("days", 0) >= 2:
                fails.append("zero inbound mail over a multi-day window (in:inbox instead of "
                             "-in:sent?)")
        else:
            bit += f"{m.get('last_payload_events', '?')} read"
        bit += f", +{m.get('last_added', 0)} deal / +{m.get('last_lead_added', 0)} lead"
        if name == "crm" and m.get("unknown_crm"):
            n_ev = m.get("unknown_crm_events", 0)
            n_rec = sum(len(v) for v in m["unknown_crm"].values())
            bit += f", {n_ev} on {n_rec} record(s) not in the registry"
            total = m.get("last_payload_events") or 0
            if n_ev >= UNKNOWN_CRM_MIN and total and n_ev / total >= UNKNOWN_CRM_SHARE:
                fails.append(f"{n_ev} of {total} CRM activities are on {n_rec} record(s) not "
                             "in the registry — import them and re-ingest")
        parts.append(bit)

    ingest_part("gmail", "mail")
    ingest_part("calendar", "calendar")
    if "crm" in req or src.get("crm"):
        ingest_part("crm", "CRM")

    if _after(meta.get("lead_touch_at"), t0):
        parts.append(f"lead clocks {meta.get('lead_touch_written', 0)} updated")
    else:
        msg = "lead clocks not refreshed" + (f" ({run['skips']['lead_touch']})"
                                            if "lead_touch" in run["skips"] else "")
        parts.append(msg)
        if "lead_touch" in req:
            fails.append(msg)

    fl = A.load_json(os.path.join(A.cache_dir(root), "floor-latest.json"), {})
    if _after(fl.get("generated_at"), t0):
        import floor_check as F
        parts.append(F.summary_line(fl))
    else:
        msg = "30-day floor not computed" + (f" ({run['skips']['floor']})"
                                             if "floor" in run["skips"] else "")
        parts.append(msg)
        if "floor" in req:
            fails.append(msg)

    # Drafts: the follow-up guarantee is "draft and stage every one raised". A brief that
    # lists 23 breaches and stages nothing has handed the work back; on 2026-10-29 a
    # verification run did exactly that and its Preflight said OK. The evidence is a file
    # in 01-Tasks/Drafts written during this run, not the brief's own account.
    owed = 0
    if _after(fl.get("generated_at"), t0):
        owed = sum(((fl.get(k) or {}).get("past_window") or 0) for k in ("deals", "leads"))
    staged = staged_drafts(root, t0)
    if owed:
        if staged:
            parts.append(f"drafts {staged} staged")
        else:
            why = run["skips"].get("drafts")
            msg = (f"no follow-up drafts staged for {owed} floor breach(es)"
                   + (f" ({why})" if why else ""))
            parts.append(msg)
            if "drafts" in req:
                fails.append(msg)

    # News sweep: the record market_sweep.py --record writes, after --begin. A brief whose
    # news section is missing must not read as a quiet morning.
    sw = M.latest(root)
    if sw and _after(sw.get("recorded_at"), t0):
        c = sw.get("counts") or {}
        nl = sw.get("newsletters") or {}
        bit = (f"news sweep: {nl.get('issues_read', 0)} newsletter(s), "
               + ", ".join(f"{(c.get(g) or {}).get('searched', 0)} {g}"
                           for g in ("competitors", "customers", "prospects", "themes")))
        parts.append(bit)
        gaps = sw.get("gaps") or {}
        if gaps and "market_sweep" in req:
            n = sum(len(v) for v in gaps.values())
            fails.append(f"news sweep left {n} planned item(s) unsearched ("
                         + ", ".join(f"{g} {len(v)}" for g, v in gaps.items()) + ")")
    else:
        why = run["skips"].get("market_sweep")
        msg = "news sweep did not run" + (f" ({why})" if why else "")
        parts.append(msg)
        if "market_sweep" in req:
            fails.append(msg)

    st = status_json(root)
    parts.append(f"cache newest {st.get('newest_event') or 'none'}")
    if st.get("stale"):
        fails.append(f"cache still stale after the run (newest {st.get('newest_event')})")
    for s, why in run["skips"].items():
        if s not in req and s not in KNOWN_STEPS:
            parts.append(f"{s} skipped ({why})")
    return parts, fails


def staged_drafts(root, t0):
    d = os.path.join(root, DRAFTS_DIR)
    if not (t0 and os.path.isdir(d)):
        return 0
    n = 0
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        if os.path.isfile(p) and not fn.startswith("."):
            if datetime.fromtimestamp(os.path.getmtime(p), timezone.utc) >= t0:
                n += 1
    return n


def write_line(brief, line):
    with open(brief, encoding="utf-8") as f:
        text = f.read()
    body_start = 0
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body_start = text.find("\n", end + 4) + 1 or len(text)
    head, body = text[:body_start], text[body_start:]
    body = re.sub(r"\A\s*\*\*Preflight[^\n]*\n+", "", body)
    new = head + line + "\n\n" + body.lstrip("\n")
    with open(brief, "w", encoding="utf-8") as f:   # truncate-and-write: no unlink needed
        f.write(new)


def finish(root, brief=None, as_json=False):
    data, run = current_run(root)
    if not run:
        print("error: no run in progress — --begin was never called, which is itself the "
              "failure this script exists to catch.", file=sys.stderr)
        print("NOTIFY: Sales brief ran without --begin: preflight never started, results "
              "unverified")
        return 3
    parts, fails = evaluate(root, run)
    ok = not fails
    line = (f"**Preflight: {'OK' if ok else 'FAILED — ' + '; '.join(fails)}.** "
            + " · ".join(parts) + ".")
    run.update({"finished_at": iso(now()), "ok": ok, "failures": fails, "line": line})
    if brief:
        bp = brief if os.path.isabs(brief) else os.path.join(root, brief)
        if os.path.exists(bp):
            write_line(bp, line)
            run["brief"] = os.path.relpath(bp, root)
        else:
            fails.append(f"brief file not found: {brief}")
            ok = run["ok"] = False
    save_runs(root, data)
    if as_json:
        print(json.dumps({"ok": ok, "failures": fails, "line": line}))
    else:
        print(line)
    if not ok:
        print("NOTIFY: " + notify_text("Sales brief preflight FAILED", fails))
        return 3
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--begin"); ap.add_argument("--finish"); ap.add_argument("--skip")
    ap.add_argument("--status")
    ap.add_argument("--step"); ap.add_argument("--reason", default="")
    ap.add_argument("--brief"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.begin:
        return begin(os.path.abspath(a.begin), a.json)
    if a.skip:
        if not (a.step and a.reason):
            print("--skip needs --step and --reason", file=sys.stderr)
            return 2
        return skip(os.path.abspath(a.skip), a.step, a.reason)
    if a.finish:
        return finish(os.path.abspath(a.finish), a.brief, a.json)
    if a.status:
        trips = tripwires(os.path.abspath(a.status), date.today())
        for t in trips:
            print(f"TRIPWIRE: {t}")
        if not trips:
            print("no tripwires")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
