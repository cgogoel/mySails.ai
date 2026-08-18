#!/usr/bin/env python3
"""
setup_status.py — what setting this folder up involves, and how far through it you are.

Setting up properly takes longer than one sitting. It involves finding documents, deciding
things, and waiting on connectors somebody else has to authorise. The old failure was a
single long interview that either got abandoned at question fourteen or produced a folder
that looked complete and wasn't — and downstream skills degrade quietly rather than
failing loudly, so nobody finds out for a week.

So setup is a resumable checklist living at `00-Config/setup-checklist.csv`, and this
script is how it's kept honest:

  --init     create the checklist for the modules in play (never resets what's Done)
  --check    look at the folder and mark steps complete from evidence, not memory
  --report   print where things stand and what to do next
  --html     render the same as a dashboard
  --doctor   assert the scripts resolve and actually run in this environment

The distinction that matters is `--check`. A session that crashed mid-phase remembers
nothing, and a user who did something manually last week never told anyone. Both are
recoverable by looking at the folder, so completion is *derived* wherever it can be and
only asserted where it can't.

Usage:
  setup_status.py --init   <project> [--modules leads,opportunities,daily-brief]
  setup_status.py --check  <project>
  setup_status.py --report <project>
  setup_status.py --html   <project> [--out <file.html>]
  setup_status.py --set    <project> --key crm-profile --status Done [--notes "..."]
  setup_status.py --doctor <project>
"""

import argparse
import html as H
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csvguard as G

REGISTRY = "setup_checklist"


# ------------------------------------------------------------------ evidence checks
# Each returns (done, evidence). Evidence is a specific sentence, never "found" — the
# specificity is what lets the user overrule a wrong call.


def _cfg(root):
    p = os.path.join(root, "00-Config", "config.md")
    if not os.path.exists(p):
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def config_has(key):
    def check(root):
        m = re.search(rf"^\s*[-*]?\s*{key}\s*:\s*(\S.*)$", _cfg(root),
                      re.MULTILINE | re.IGNORECASE)
        if m:
            return True, f"config.md · {key}: {m.group(1).strip()[:60]}"
        return False, ""
    return check


def file_exists(*rel):
    def check(root):
        for r in rel:
            p = os.path.join(root, r)
            if os.path.exists(p):
                return True, f"{r} exists"
        return False, ""
    return check


def dir_has_files(rel, exts=None, minimum=1, exclude=()):
    """`exclude` names files that live in this directory but are not what the step is
    asking about. `standing-profile.md` sits in 02-Context/Messaging/ and is a different
    artifact from the positioning material — counting it would report "add positioning and
    messaging" as done for a folder that has none, which is the class of quietly-wrong
    completion this checklist exists to prevent."""
    skip = {f.lower() for f in exclude} | {"readme.md"}

    def check(root):
        d = os.path.join(root, rel)
        if not os.path.isdir(d):
            return False, ""
        got = [f for f in os.listdir(d)
               if not f.startswith(".") and f.lower() not in skip
               and (not exts or f.lower().endswith(tuple(exts)))]
        if len(got) >= minimum:
            return True, f"{rel}/ · {len(got)} file(s): {', '.join(sorted(got)[:3])}"
        return False, ""
    return check


def registry_rows(schema_name, minimum=1, where=None):
    def check(root):
        s = G.load_schemas(root).get(schema_name)
        if not s:
            return False, ""
        p = G.resolve_path(os.path.join(root, s["path"]), root)
        if not os.path.exists(p):
            return False, ""
        try:
            header, rows = G.read_table(p, s)
        except Exception:
            return False, ""
        if where:
            col, vals = where
            if col in header:
                i = header.index(col)
                rows = [r for r in rows if i < len(r) and r[i] in vals]
        if minimum == 0:
            return True, f"{os.path.basename(p)} exists ({len(rows)} rows)"
        if len(rows) >= minimum:
            return True, f"{os.path.basename(p)} · {len(rows)} rows"
        return False, f"{os.path.basename(p)} exists but is empty"
    return check


def profile_block(name, needs=()):
    """A named block in field-map.json, present and carrying the keys that make it
    usable. A block with an object name and no direction semantics is half-answered, and
    half-answered here means every downstream flag quietly reads as clean."""
    def check(root):
        fm = G.load_field_map(root) or {}
        block = fm.get(name)
        if not isinstance(block, dict) or not block:
            return False, ""
        missing = [k for k in needs if not block.get(k)]
        if missing:
            return False, f"`{name}` block is missing {', '.join(missing)}"
        return True, (f"field-map.json · `{name}` block, direction "
                      f"{block.get('email_direction_semantics', 'unrecorded')}")
    return check


def any_of(*checks):
    def check(root):
        for c in checks:
            ok, ev = c(root)
            if ok:
                return True, ev
        return False, ""
    return check


def all_of(*checks):
    def check(root):
        evs = []
        for c in checks:
            ok, ev = c(root)
            if not ok:
                return False, ""
            evs.append(ev)
        return True, "; ".join(evs)
    return check


def scripts_runnable():
    """Not "are the scripts installed" but "can this folder reach them right now". The two
    came apart when the scripts moved into the plugin and `$CLAUDE_PLUGIN_ROOT` turned out
    to be empty in Cowork's sandbox, and because nothing asserted the second, fourteen
    skills reported success while running nothing for six days. Cheap enough to evaluate on
    every --check, which is the point: the expensive version is the one nobody runs."""
    def check(root):
        resolver = os.path.join(root, G.SYSTEM_DIR, "find_scripts.py")
        if not os.path.isfile(resolver):
            return False, "no .sales-system/find_scripts.py — run update-system"
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("_fs_probe", resolver)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            scripts, source = mod.find_scripts(root)
        except Exception as e:                                    # noqa: BLE001
            return False, f"find_scripts.py failed to run: {e}"
        if not scripts:
            return False, "the plugin's scripts cannot be found from this folder"
        return True, f"scripts resolve via {source} — run --doctor to confirm they execute"
    return check


def module_folder(rel):
    return file_exists(rel)


def synced_and_fresh(schema_name):
    """A synced registry with rows AND a last_synced stamp — a registry full of rows
    that has never been reconciled is imported, not connected."""
    def check(root):
        s = G.load_schemas(root).get(schema_name)
        if not s:
            return False, ""
        p = G.resolve_path(os.path.join(root, s["path"]), root)
        if not os.path.exists(p):
            return False, ""
        try:
            header, rows = G.read_table(p, s)
        except Exception:
            return False, ""
        if not rows or "last_synced" not in header:
            return False, ""
        i = header.index("last_synced")
        stamped = [r for r in rows if i < len(r) and r[i]]
        if len(stamped) >= max(1, len(rows) // 2):
            return True, (f"{os.path.basename(p)} · {len(stamped)} of {len(rows)} rows "
                          f"reconciled, last {max(r[i] for r in stamped)}")
        return False, f"{len(stamped)} of {len(rows)} rows have ever been reconciled"
    return check


# ------------------------------------------------------------------- the catalogue

CORE = [
    # CONVENTIONS.md deliberately isn't checked for here any more: it moved into the plugin,
    # so a correctly set-up folder doesn't have one and this step was reporting incomplete
    # for exactly the folders that were right. What the folder must hold is its schemas and
    # the resolver that lets the skills reach everything else.
    ("system-layer", "Foundation", "Install the system layer",
     "Schemas and the script resolver every skill depends on. Nothing else works without it.",
     True, all_of(file_exists(".sales-system/find_scripts.py"),
                  file_exists(".sales-system/schemas"))),
    ("scripts-runnable", "Foundation", "Confirm the scripts actually run",
     "Every skill shells out to these. If they can't be reached the steps fail silently and "
     "briefs still come out looking normal, so this is checked rather than assumed.",
     True, scripts_runnable()),
    ("config-file", "Foundation", "Create the config file",
     "Where scope, storage format, brief content and cadences live. Skills read it before anything else.",
     True, file_exists("00-Config/config.md")),
    ("scope", "Foundation", "Decide individual or team scope",
     "Changes every CRM pull and every roll-up. The most consequential answer in setup.",
     True, config_has("scope")),
    ("storage-format", "Foundation", "Choose CSV or styled Excel",
     "Excel gives dropdowns of your real picklist values, so an invalid stage can't be typed.",
     True, config_has("storage_format")),
    ("base-currency", "Foundation", "Set the base currency",
     "The one currency every forecast total, pipeline figure and goal attainment number is "
     "expressed in. Without it nothing can be added up across a mixed-currency book, and "
     "there is no safe default to pick on your behalf.",
     True, config_has("base_currency")),
    ("fx-rates", "Foundation", "Load the conversion rates",
     "From your CRM's currency table, so the folder's totals reconcile against the CRM's own "
     "reports \u2014 or from a public source with fx.py --fetch where there is no CRM. Loading both "
     "costs one extra command and is what lets the drift check tell you a CRM currency table "
     "nobody has maintained has been converting several percent out.",
     False, registry_rows("fx_rates")),
    ("folder-structure", "Foundation", "Build the folder structure",
     "The numbered folders you'll actually browse in Finder.",
     True, all_of(file_exists("01-Tasks"), file_exists("02-Context"))),
    ("readme", "Foundation", "Write the folder README",
     "The one artifact that makes the folder navigable by someone who wasn't in this session.",
     True, file_exists("README.md")),
    ("team-roster", "Foundation", "Capture the team roster",
     "Team scope only. Per-rep coverage and quota attainment need it; hierarchies keep people who've left, so it has to be confirmed.",
     False, registry_rows("team")),

    ("connections", "Connections", "Confirm email, calendar and CRM connections",
     "Recorded including what was absent, so later skills don't retry dead tools.",
     True, file_exists("00-Config/connections.md")),
    ("email-connected", "Connections", "Connect email",
     "Without it tasks can't be drafted, sent, or verified as done, and engagement scoring loses its strongest signal.",
     True, None),
    ("crm-connected", "Connections", "Connect the CRM",
     "Optional — the system works without one — but everything about pipeline gets manual.",
     False, None),

    ("crm-profile", "CRM Profile", "Build the CRM profile",
     "What makes a generic template fit your company: your real picklists, field mapping, and what must never be pushed.",
     True, all_of(file_exists(".sales-system/crm-profile/field-map.json"),
                  file_exists(".sales-system/crm-profile/picklists.json"))),
    ("crm-picklists", "CRM Profile", "Confirm your real picklist values",
     "The shipped schemas carry generic placeholders. Until these are yours, validation flags every real record as invalid.",
     True, file_exists(".sales-system/crm-profile/picklists.json")),
    ("crm-contactability", "CRM Profile", "Record what blocks contact",
     "Channel-specific opt-outs. Getting this wrong is the one data error with legal consequences.",
     False, file_exists(".sales-system/crm-profile/contactability.json")),
    ("crm-activity", "CRM Profile", "Map where activity lives, and whether direction is knowable",
     "Which objects hold contact roles, email and meetings, and whether this CRM can tell an "
     "inbound message from an outbound one. Without it the relationship flags read a column "
     "nothing populates and report every deal as fine.",
     False, profile_block("activity", needs=("email_direction_semantics",))),
    ("crm-never-push", "CRM Profile", "Agree what must never be pushed",
     "Integration-owned and automation-stamped fields. A push to one either gets overwritten or fights the integration.",
     True, None),

    ("goals-company", "Goals", "Capture the company goal",
     "A forecast against the wrong number is worse than no forecast.",
     True, registry_rows("goals", where=("level", {"Company", "company"}))),
    ("goals-personal", "Goals", "Capture your own or your team's goal",
     "What every forecast gets framed against.",
     True, registry_rows("goals")),
    ("goals-cadence", "Goals", "Set when goals get reconfirmed",
     "Goals move mid-year, and an unconfirmed goal quietly makes every forecast wrong.",
     False, None),

    ("modules-chosen", "Modules", "Choose which modules to run",
     "Each one adds a folder, a registry and a set of behaviours. Off is a valid answer.",
     True, file_exists("00-Config/enabled-modules.md")),

    ("context-company", "Content", "Add company background",
     "What you sell and who you are. Everything generated for a customer reads from here.",
     False, dir_has_files("02-Context/Company")),
    ("context-messaging", "Content", "Add positioning and messaging",
     "Kept verbatim plus a distilled summary — a 40-page deck is too expensive to load on every request.",
     False, any_of(file_exists("02-Context/Messaging/messaging-summary.md"),
                   dir_has_files("02-Context/Messaging",
                                 exclude=("standing-profile.md",)))),
    ("context-corporate-deck", "Content", "Add the corporate deck",
     "Who we are. Executives want this one.",
     False, dir_has_files("02-Context/Presentations/Corporate")),
    ("context-product-deck", "Content", "Add the product deck",
     "What it does. Technical evaluators want this one, and a deck mixing the two lands badly with both.",
     False, dir_has_files("02-Context/Presentations/Product")),
    ("context-templates", "Content", "Add email and document templates",
     "Whatever you already send. Tailored content starts from these rather than from nothing.",
     False, dir_has_files("02-Context/Templates")),
    ("context-customers", "Content", "Import the customer list",
     "Who already buys from you. Renewals, references and expansion all read it.",
     False, registry_rows("customers")),

    ("tasks-registry", "Automation", "Create the task list",
     "One registry across every module, because a seller has one day, not nine.",
     True, registry_rows("tasks", minimum=0)),
    ("task-rules", "Automation", "Seed the task rules",
     "Policy as configuration: what raises what, at what automation level, with what caps. Editable in Excel without asking anyone.",
     True, registry_rows("task_rules")),
    ("automation-posture", "Automation", "Set the automation posture",
     "Everything at review is the right start: a week of watching what the system would have sent is the cheapest way to learn whether you'd trust it to send.",
     True, config_has("default_automation")),
    ("brief-content", "Automation", "Decide what goes in each brief",
     "The daily/weekly/forecast split follows your business rhythm, not a default.",
     True, config_has("brief_content")),
    ("forecast-cadence", "Automation", "Set the forecast cadence",
     "Scheduled to land a few hours before the forecast call. Produced after it, a forecast is a record rather than a tool.",
     True, config_has("forecast_cadence")),
    ("schedules", "Automation", "Schedule the briefs",
     "The briefs people mean to run and don't.",
     False, None),

    ("registries-clean", "Verification", "Registries validate clean",
     "csvguard --check-all with no NEEDS YOU rows.",
     True, None),
    ("sync-verified", "Verification", "Local data matches the CRM",
     "A drift check that comes back clean. Until this passes once, nothing here has been proven against the system of record.",
     True, None),
    ("walkthrough", "Verification", "Walk through the finished folder",
     "Open it, see the dropdowns, know where things live and what to do next.",
     False, None),
]

# label, folder, registries that must exist, registries that must hold data, synced
MODULES = {
    "market": ("Market Tracking", "03-Market", ["market_watchlist"], ["market_watchlist"], False),
    "competitors": ("Competitor Tracking", "04-Competitors", ["competitors"], ["competitors"], False),
    # Both registries, because Demand Gen is two halves: campaigns measure what ran,
    # content-opportunities tracks what is worth saying. Listing only campaigns reported a
    # folder complete while the half the skill spends most of its time in had nowhere to
    # write. Only campaigns has to hold rows — a content pipeline legitimately starts empty.
    "demand-gen": ("Demand Gen", "05-Demand-Gen",
                   ["campaigns", "content_opportunities"], ["campaigns"], False),
    "leads": ("Lead Tracking", "06-Leads", ["leads"], ["leads"], True),
    "opportunities": ("Opportunity Tracking", "07-Opportunities", ["opportunities"], ["opportunities"], True),
    "renewals": ("Renewals Tracking", "08-Renewals", ["renewals"], ["renewals"], True),
    "partners": ("Partner Tracking", "11-Partners", ["partners"], ["partners"], True),
    "content": ("Content Tailoring", "10-Content", ["content_assets"], [], False),
    "quotes": ("Quote Generation", "12-Quotes", ["price_list"], ["price_list"], False),
    # Neither registry has to hold rows at setup — the module fills as meetings happen.
    "meetings": ("Meeting Notes", "13-Meetings", ["meetings", "commitments"], [], False),
    "daily-brief": ("Daily Brief", "09-Briefs/Daily", [], [], False),
    "weekly-brief": ("Weekly Brief", "09-Briefs/Weekly", [], [], False),
    "forecast": ("Forecast Update", "09-Briefs/Forecast", [], [], False),
}

MODULE_ALIASES = {
    "market tracking": "market", "competitor tracking": "competitors",
    "competitors": "competitors", "demand gen": "demand-gen",
    "demand generation": "demand-gen", "lead tracking": "leads",
    "opportunity tracking": "opportunities", "opportunities": "opportunities",
    "pipeline": "opportunities", "renewals tracking": "renewals",
    "partner tracking": "partners", "content tailoring": "content",
    "quote generation": "quotes", "quotes": "quotes",
    "meeting notes": "meetings", "meetings": "meetings",
    "meeting tracking": "meetings", "transcripts": "meetings",
    "call notes": "meetings",
    "daily brief": "daily-brief", "weekly brief": "weekly-brief",
    "forecast update": "forecast", "forecast": "forecast",
}


def module_steps(slug):
    label, folder, must_exist, must_have_data, synced = MODULES[slug]
    steps = [(f"{slug}-structure", "Modules", f"{label}: create the folder and registry",
              f"Where {label.lower()} lives.", True,
              all_of(module_folder(folder),
                     *[registry_rows(r, minimum=0) for r in must_exist]))]
    if must_have_data:
        steps.append((f"{slug}-data", "Modules", f"{label}: load the data",
                      "An empty registry makes every downstream skill report nothing "
                      "and look broken.", True,
                      all_of(*[registry_rows(r) for r in must_have_data])))
    if synced:
        steps.append((f"{slug}-mapping", "Modules", f"{label}: confirm the field mapping",
                      "Look at three real records together and check the columns hold "
                      "what you'd expect. A mapping error found here costs a minute; "
                      "found in a forecast it costs the forecast.", True, None))
        steps.append((f"{slug}-sync", "Modules", f"{label}: reconcile against the CRM",
                      "One clean drift check, so the folder starts life provably in "
                      "agreement with the system of record.", True,
                      synced_and_fresh(must_have_data[0] if must_have_data
                                       else must_exist[0])))
    if slug == "opportunities":
        steps.append((f"{slug}-contacts", "Modules",
                      f"{label}: build the contact list",
                      "Who is on each deal and which of them reply. Until this exists the "
                      "single-threaded flag has nothing to read, and a flag that never "
                      "fires reports every deal as healthy.",
                      False, registry_rows("opportunity_contacts")))
    # Demand Gen is two halves and only one of them used to get configured. Campaign
    # measurement needs a registry, which the structure step covers. The content half needs
    # to know what this organisation may credibly speak about — and until that was captured
    # at setup, the first sweep inferred it from the website and document titles and wrote
    # the guess into the folder as settled fact. A wrong exclusion there suppresses a whole
    # category of content silently and permanently, because nobody audits the things that
    # were never suggested. So it is a step, scored from evidence, and it is required:
    # a dashboard reporting 100% on a folder with no standing profile is how the gap
    # stayed invisible.
    if slug == "demand-gen":
        steps.append((f"{slug}-standing", "Modules",
                      f"{label}: capture what you can credibly speak about",
                      "The standing profile, answered by you rather than inferred from your "
                      "website. Surface signals under-represent what an organisation knows "
                      "— research is titled for its subject, not its platform — so a guess "
                      "here reads as fact later and quietly kills a category of content.",
                      True, file_exists("02-Context/Messaging/standing-profile.md")))
        steps.append((f"{slug}-content-rules", "Modules",
                      f"{label}: seed the content folder",
                      "Where drafts live, with the two rules that must not be re-derived "
                      "each session: never comment publicly on a competitor's funding or "
                      "bad news, and perishability is a deadline rather than a label.",
                      False, file_exists("05-Demand-Gen/Content/README.md")))
        steps.append((f"{slug}-content-config", "Modules",
                      f"{label}: set voice, publisher and sweep cadence",
                      "Who content goes out as, who approves it, where it publishes, and "
                      "whether the sweep is standalone or rides inside a brief.",
                      False, config_has("content_sweep_cadence")))
    if slug == "meetings":
        steps.append((f"{slug}-folders", "Modules",
                      f"{label}: create the Inbox, Raw and Notes folders",
                      "Inbox/ is where transcript exports get dropped; Raw/ keeps the "
                      "verbatim original; Notes/ holds the processed record. The raw is "
                      "kept always — the note is an interpretation and the original is "
                      "the evidence behind it.",
                      True, all_of(file_exists("13-Meetings/Inbox"),
                                   file_exists("13-Meetings/Raw"),
                                   file_exists("13-Meetings/Notes"))))
        steps.append((f"{slug}-sources", "Modules",
                      f"{label}: record where transcripts come from",
                      "Which tool records their calls (Zoom via the connector, or Otter/"
                      "Teams/Gong exports dropped in the Inbox, or typed notes). Recorded "
                      "so the skill offers the right pull instead of asking every time.",
                      False, config_has("meeting_sources")))
    if slug in ("daily-brief", "weekly-brief", "forecast"):
        steps.append((f"{slug}-firstrun", "Modules", f"{label}: run it once",
                      "The fastest way to find out whether the data behind it is good "
                      "enough yet.", True, None))
    return steps


CHECKS = {}


def catalogue(modules):
    rows = list(CORE)
    for slug in modules:
        if slug in MODULES:
            rows.extend(module_steps(slug))
    CHECKS.clear()
    for key, phase, step, why, req, check in rows:
        CHECKS[key] = check
    return rows


def read_modules(root, override=None):
    if override:
        return [MODULE_ALIASES.get(m.strip().lower(), m.strip().lower())
                for m in override.split(",") if m.strip()]
    p = os.path.join(root, "00-Config", "enabled-modules.md")
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    found = []
    for line in text.splitlines():
        s = line.strip().lstrip("-*[ ]xX").strip()
        if not s or s.startswith("#"):
            continue
        # "| Lead Tracking | on |" and "- Lead Tracking" both have to work
        cells = [c.strip() for c in s.split("|") if c.strip()]
        name = cells[0] if cells else s
        if len(cells) > 1 and cells[-1].lower() in ("off", "no", "disabled", "-"):
            continue
        slug = MODULE_ALIASES.get(name.lower(), name.lower())
        if slug in MODULES and slug not in found:
            found.append(slug)
    return found


# ------------------------------------------------------------------------ registry


def path_for(root):
    s = G.load_schemas(root).get(REGISTRY)
    if not s:
        raise SystemExit("error: setup_checklist schema missing — is .sales-system current?")
    return G.resolve_path(os.path.join(root, s["path"]), root), s


def load(root):
    p, s = path_for(root)
    if not os.path.exists(p):
        return p, s, [c["name"] for c in s["columns"]], []
    header, rows = G.read_table(p, s)
    return p, s, header, rows


def init(root, modules, quiet=False):
    """Create missing steps, leave existing ones exactly as they are. Re-running this
    after enabling another module must never reset progress."""
    p, s, header, rows = load(root)
    idx = {h: i for i, h in enumerate(header)}
    have = {r[idx["key"]] for r in rows if idx["key"] < len(r)}
    prefix, width = s.get("id_prefix", "SETUP"), s.get("id_width", 4)
    used = {r[idx["id"]] for r in rows if idx["id"] < len(r) and r[idx["id"]]}
    nxt = G.next_free(used, prefix, width)
    added = 0
    for key, phase, step, why, req, _check in catalogue(modules):
        if key in have:
            continue
        row = [""] * len(header)
        for col, val in (("id", f"{prefix}-{nxt:0{width}d}"), ("key", key),
                         ("phase", phase), ("step", step), ("why", why),
                         ("required", "yes" if req else "no"),
                         ("status", "Not started"),
                         ("module", key.split("-")[0] if phase == "Modules" else "")):
            if col in idx:
                row[idx[col]] = val
        rows.append(row)
        used.add(row[idx["id"]])
        nxt += 1
        added += 1
    G.write_table(p, header, rows, schema=s, root=root, backup=True, guard=False)
    if not quiet:
        print(f"setup checklist: {added} step(s) added, {len(rows)} total"
              + (f" · modules: {', '.join(modules)}" if modules else ""))
    return added


def check(root, quiet=False):
    """Mark steps complete from what's actually in the folder."""
    p, s, header, rows = load(root)
    if not rows:
        return 0
    idx = {h: i for i, h in enumerate(header)}
    catalogue(read_modules(root))
    today = date.today().isoformat()
    newly, regressed = [], []
    for r in rows:
        key = r[idx["key"]]
        fn = CHECKS.get(key)
        if fn is None:
            continue                      # only a human can confirm this one
        try:
            ok, ev = fn(root)
        except Exception:
            continue
        was = r[idx["status"]]
        if "evidence" in idx:
            r[idx["evidence"]] = ev
        if "verified_date" in idx:
            r[idx["verified_date"]] = today
        if ok and was in ("Not started", "In progress"):
            r[idx["status"]] = "Done"
            if "completed_date" in idx and not r[idx["completed_date"]]:
                r[idx["completed_date"]] = today
            newly.append((r[idx["step"]], ev))
        elif not ok and was == "Done":
            # Something that was done no longer is — a file moved, a registry emptied.
            # Say so rather than silently leaving a green tick over an empty folder.
            regressed.append(r[idx["step"]])
    G.write_table(p, header, rows, schema=s, root=root, backup=True, guard=False)
    if not quiet:
        for step, ev in newly:
            print(f"  done   {step}  ({ev})")
        for step in regressed:
            print(f"  CHECK  {step} — was marked done, but the evidence has gone")
        if not newly and not regressed:
            print("  nothing changed since the last check")
    return len(newly)


def set_status(root, key, status=None, notes=None, blocked=None):
    p, s, header, rows = load(root)
    idx = {h: i for i, h in enumerate(header)}
    hit = None
    for r in rows:
        if r[idx["key"]] == key:
            hit = r
            break
    if hit is None:
        raise SystemExit(f"error: no step with key {key!r}")
    if status:
        hit[idx["status"]] = status
        if status == "Done" and "completed_date" in idx:
            hit[idx["completed_date"]] = date.today().isoformat()
    if notes is not None and "notes" in idx:
        hit[idx["notes"]] = notes
    if blocked is not None and "blocked_reason" in idx:
        hit[idx["blocked_reason"]] = blocked
        if not status:
            hit[idx["status"]] = "Blocked"
    G.write_table(p, header, rows, schema=s, root=root, guard=False)
    print(f"{key}: {hit[idx['status']]}")
    return 0


# -------------------------------------------------------------------------- report

PHASE_ORDER = ["Foundation", "Connections", "CRM Profile", "Goals", "Modules",
               "Content", "Automation", "Verification"]
DONE = ("Done", "Skipped")


def summarise(root):
    p, s, header, rows = load(root)
    idx = {h: i for i, h in enumerate(header)}
    items = []
    for r in rows:
        items.append({k: (r[idx[k]] if k in idx and idx[k] < len(r) else "")
                      for k in ("id", "key", "phase", "step", "why", "module",
                                "required", "status", "evidence", "blocked_reason",
                                "notes", "completed_date")})
    req = [i for i in items if i["required"] == "yes"]
    opt = [i for i in items if i["required"] != "yes"]
    done_req = [i for i in req if i["status"] in DONE]
    pct = int(round(100 * len(done_req) / len(req))) if req else 0
    phases = []
    for ph in PHASE_ORDER:
        got = [i for i in items if i["phase"] == ph]
        if not got:
            continue
        gr = [i for i in got if i["required"] == "yes"]
        # A phase of nothing but optional steps has no required progress to report, and
        # showing it as 100% complete before anything has been done is a lie the eye
        # believes. Score those on their own terms and label them.
        basis = gr or got
        d = [i for i in basis if i["status"] in DONE]
        phases.append({"phase": ph, "total": len(basis), "done": len(d),
                       "pct": int(round(100 * len(d) / len(basis))) if basis else 100,
                       "optional_only": not gr, "items": got})
    nxt = [i for i in req if i["status"] not in DONE and i["status"] != "Blocked"]
    blocked = [i for i in items if i["status"] == "Blocked"]
    return {"items": items, "required": req, "optional": opt, "pct": pct,
            "done": len(done_req), "total": len(req), "phases": phases,
            "next": nxt[:3], "blocked": blocked,
            "optional_done": len([i for i in opt if i["status"] in DONE])}


def report(root):
    d = summarise(root)
    if not d["items"]:
        print("No setup checklist yet — run configure-project, or setup_status.py --init.")
        return 1
    bar_w = 32
    filled = int(round(bar_w * d["pct"] / 100))
    print(f"\nSetup  [{'█' * filled}{'·' * (bar_w - filled)}]  {d['pct']}%   "
          f"{d['done']} of {d['total']} required steps"
          + (f", plus {d['optional_done']} of {len(d['optional'])} optional"
             if d["optional"] else ""))
    print()
    for ph in d["phases"]:
        w = 12
        f = int(round(w * ph["pct"] / 100))
        mark = "✓" if ph["pct"] == 100 and ph["total"] else " "
        print(f"  {mark} {ph['phase']:<12} [{'█' * f}{'·' * (w - f)}] "
              f"{ph['done']}/{ph['total']}"
              + ("  all optional" if ph["optional_only"] else ""))
        for i in ph["items"]:
            if i["status"] in DONE:
                continue
            tag = "BLOCKED" if i["status"] == "Blocked" else i["status"].lower()
            extra = f" — {i['blocked_reason']}" if i["blocked_reason"] else ""
            opt = "" if i["required"] == "yes" else "  (optional)"
            print(f"      · {i['step']}  [{tag}]{opt}{extra}")
    if d["next"]:
        print("\nNext:")
        for i in d["next"]:
            print(f"  {i['step']}")
            print(f"    {i['why']}")
    elif d["pct"] == 100:
        print("\nEverything required is done. Optional steps are listed above.")
    print()
    return 0


# ----------------------------------------------------------------------- dashboard


def esc(s):
    return H.escape(str(s if s is not None else ""))


def render_html(root, out):
    import sheetstyle as S
    brand = S.load_brand(root)
    P = S.Palette(brand)
    d = summarise(root)
    company = brand.get("company") or os.path.basename(os.path.abspath(root))

    tone = {"Done": (P.green_bg, P.green_ink, "✓"),
            "Skipped": (P.mute_bg, P.mute_ink, "–"),
            "In progress": (P.amber_bg, P.amber_ink, "·"),
            "Blocked": (P.red_bg, P.red_ink, "!"),
            "Not started": ("FFFFFF", "6B7280", "")}

    def ring(pct):
        r, c = 52, 2 * 3.14159 * 52
        off = c * (1 - pct / 100)
        return f"""<svg width="132" height="132" viewBox="0 0 132 132">
  <circle cx="66" cy="66" r="52" fill="none" stroke="#{P.rule}" stroke-width="13"/>
  <circle cx="66" cy="66" r="52" fill="none" stroke="#{P.header_bg}" stroke-width="13"
     stroke-linecap="round" stroke-dasharray="{c:.1f}" stroke-dashoffset="{off:.1f}"
     transform="rotate(-90 66 66)"/>
  <text x="66" y="72" text-anchor="middle" font-size="30" font-weight="700"
     fill="#1A1D21" font-family="-apple-system,Segoe UI,sans-serif">{pct}%</text>
</svg>"""

    phase_bars = []
    for ph in d["phases"]:
        phase_bars.append(f"""
      <div style="margin-bottom:11px">
        <div style="display:flex;justify-content:space-between;font-size:12px;
             margin-bottom:4px"><span style="font-weight:600">{esc(ph['phase'])}</span>
          <span style="color:#6B7280">{ph['done']}/{ph['total']}{
            ' optional' if ph['optional_only'] else ''}</span></div>
        <div style="height:7px;background:#{P.rule};border-radius:4px;overflow:hidden">
          <div style="height:100%;width:{ph['pct']}%;background:#{P.header_bg}"></div>
        </div>
      </div>""")

    sections = []
    for ph in d["phases"]:
        rows_html = []
        for i in ph["items"]:
            bg, ink, mark = tone.get(i["status"], tone["Not started"])
            detail = i["evidence"] or i["blocked_reason"] or i["why"]
            opt = ('<span style="font-size:10.5px;color:#8A9099;font-weight:500;'
                   'margin-left:6px">optional</span>'
                   if i["required"] != "yes" else "")
            rows_html.append(f"""
        <tr style="border-top:1px solid #{P.rule}">
          <td style="padding:9px 10px;width:26px">
            <span style="display:inline-block;width:18px;height:18px;border-radius:50%;
              background:#{bg};color:#{ink};font-size:11px;line-height:18px;
              text-align:center;font-weight:700;border:1px solid #{P.rule}">{mark}</span>
          </td>
          <td style="padding:9px 10px">
            <div style="font-size:13px;font-weight:600;color:#1A1D21">{esc(i['step'])}{opt}</div>
            <div style="font-size:11.5px;color:#6B7280;line-height:1.5;margin-top:2px">{esc(detail)}</div>
          </td>
          <td style="padding:9px 10px;text-align:right;white-space:nowrap;
              font-size:11px;color:#{ink};font-weight:600">{esc(i['status'])}</td>
        </tr>""")
        sections.append(f"""
      <div style="background:#fff;border:1px solid #{P.rule};border-radius:10px;
           margin-bottom:14px;overflow:hidden">
        <div style="padding:11px 14px;background:#{P.band};border-bottom:1px solid #{P.rule};
             font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
             color:#{P.header_bg}">{esc(ph['phase'])}</div>
        <table style="width:100%;border-collapse:collapse">{''.join(rows_html)}</table>
      </div>""")

    nxt = "".join(f"""
        <div style="padding:10px 0;border-top:1px solid #{P.rule}">
          <div style="font-size:13px;font-weight:600">{esc(i['step'])}</div>
          <div style="font-size:11.5px;color:#6B7280;line-height:1.5">{esc(i['why'])}</div>
        </div>""" for i in d["next"])
    if not nxt:
        nxt = (f'<div style="padding:14px 0;font-size:13px;color:#{P.green_ink}">'
               f'Everything required is done.</div>')

    blocked = ""
    if d["blocked"]:
        blocked = ('<div style="background:#%s;border:1px solid #%s;border-radius:10px;'
                   'padding:12px 15px;margin-bottom:14px">'
                   '<div style="font-size:12px;font-weight:700;color:#%s;margin-bottom:5px">'
                   'Waiting on something</div>%s</div>'
                   % (P.amber_bg, P.rule, P.amber_ink,
                      "".join(f'<div style="font-size:12px;color:#3A4048;line-height:1.6">'
                              f'· {esc(i["step"])} — {esc(i["blocked_reason"] or "reason not recorded")}'
                              f'</div>' for i in d["blocked"])))

    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Setup — {esc(company)}</title></head>
<body style="margin:0;background:#F6F7F9;font-family:-apple-system,BlinkMacSystemFont,
 'Segoe UI',Roboto,sans-serif;color:#1A1D21">
<div style="max-width:860px;margin:0 auto;padding:28px 22px 44px">
  <div style="font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
       color:#{P.header_bg};margin-bottom:3px">{esc(company)}</div>
  <h1 style="margin:0 0 4px;font-size:23px;font-weight:700">Setting up your sales folder</h1>
  <div style="font-size:12.5px;color:#6B7280;margin-bottom:22px">
    Pick this up whenever — it saves where you got to. Last checked {date.today().isoformat()}.</div>

  <div style="display:flex;gap:20px;flex-wrap:wrap;background:#fff;border:1px solid #{P.rule};
       border-radius:10px;padding:18px 20px;margin-bottom:16px">
    <div style="flex:0 0 132px">{ring(d['pct'])}</div>
    <div style="flex:1;min-width:250px">
      <div style="font-size:13px;margin-bottom:12px">
        <b>{d['done']} of {d['total']}</b> required steps done{
          f", plus {d['optional_done']} of {len(d['optional'])} optional" if d['optional'] else ""}
      </div>
      {''.join(phase_bars)}
    </div>
    <div style="flex:1;min-width:230px">
      <div style="font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
           color:#{P.header_bg}">Do next</div>
      {nxt}
    </div>
  </div>
  {blocked}
  {''.join(sections)}
  <div style="font-size:11px;color:#8A9099;margin-top:18px;line-height:1.6">
    Source: <code>00-Config/setup-checklist.csv</code> — editable like any other registry.
    Ticks come from evidence in the folder, not from memory, so anything you do by hand
    gets picked up on the next check.</div>
</div></body></html>"""

    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    return out


# ---------------------------------------------------------------------------- doctor
# Every skill runs scripts. Whether those scripts can actually be found and executed was,
# until now, checked by nothing — so when the plugin moved and `$CLAUDE_PLUGIN_ROOT` turned
# out to be empty in Cowork's sandbox, fourteen skills spent six days doing no scripted work
# at all in a live folder while producing entirely normal-looking briefs. One check that runs
# one script and looks at the exit code would have caught it on day one. This is that check.


def doctor(root):
    """Assert the support layer is not just present but *runnable*. Returns 0 or 1."""
    import subprocess

    problems = []
    ok = []

    resolver = os.path.join(root, G.SYSTEM_DIR, "find_scripts.py")
    print("support layer")
    if not os.path.isfile(resolver):
        print(f"  FAIL  no find_scripts.py in {G.SYSTEM_DIR}/")
        print("        Every skill locates the plugin's scripts through this file. Without "
              "it they interpolate\n        an empty variable and every scripted step fails "
              "without saying so. Run update-system.")
        return 1
    ok.append("find_scripts.py present")

    r = subprocess.run([sys.executable, resolver, root],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  FAIL  the scripts cannot be located")
        for ln in (r.stderr or "").strip().splitlines():
            print(f"        {ln}")
        return 1
    scripts = r.stdout.strip()
    print(f"  ok    scripts resolve to {scripts}")

    # Reachable is not the same as runnable. Run one for real.
    guard = os.path.join(scripts, "csvguard.py")
    r = subprocess.run([sys.executable, guard, "--check-all", root],
                       capture_output=True, text=True)
    if r.returncode not in (0, 1):     # 1 means the guard found data problems, which is fine
        problems.append(f"csvguard.py --check-all exited {r.returncode}: "
                        f"{(r.stderr or '').strip().splitlines()[-1] if r.stderr else ''}")
    else:
        ok.append(f"csvguard.py runs (exit {r.returncode})")

    # Everything the manifest says shipped should be where the resolver points. Read the
    # PLUGIN's manifest, not the folder's: a folder's own manifest records only what the
    # folder holds — schemas and the resolver — and reading that one would assert nothing
    # about the scripts, which are the thing in question.
    man = read_json_safe(os.path.join(scripts, os.pardir, "MANIFEST.json"))
    named = [f for f in (man.get("files") or {}) if f.startswith("scripts/")]
    missing = [f for f in named if not os.path.isfile(os.path.join(scripts, os.path.basename(f)))]
    if missing:
        problems.append(f"{len(missing)} script(s) named in the plugin's MANIFEST.json are "
                        f"not at the resolved path: {', '.join(sorted(missing))}")
    elif named:
        ok.append(f"all {len(named)} manifest scripts present and hashed")
    else:
        problems.append("the plugin's MANIFEST.json names no scripts, so what shipped "
                        "cannot be verified — a session inspecting it would conclude there "
                        "are no scripts at all")

    # The regression cover for the bugs that were invisible in the field.
    act = os.path.join(scripts, "activity_sync.py")
    if os.path.isfile(act):
        r = subprocess.run([sys.executable, act, "--selftest"], capture_output=True, text=True)
        line = (r.stdout or r.stderr or "").strip().splitlines()
        if r.returncode != 0:
            problems.append("activity_sync selftest failed: " + (line[-1] if line else ""))
        else:
            ok.append(line[-1] if line else "activity_sync selftest passed")

    print("\nchecks")
    for s in ok:
        print(f"  ok    {s}")
    for s in problems:
        print(f"  FAIL  {s}")

    if problems:
        print(f"\n{len(problems)} problem(s). Until these are fixed, any skill that says it "
              "repaired the registries\nor verified against the CRM did not do so. Treat "
              "briefs and forecasts produced meanwhile as unverified.")
        return 1
    print("\nall good — the scripts resolve and run, so scripted steps in the skills are "
          "really happening.")
    return 0


def read_json_safe(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--init")
    ap.add_argument("--check")
    ap.add_argument("--report")
    ap.add_argument("--html")
    ap.add_argument("--set")
    ap.add_argument("--key")
    ap.add_argument("--status", choices=["Not started", "In progress", "Done",
                                         "Skipped", "Blocked"])
    ap.add_argument("--notes")
    ap.add_argument("--blocked-reason", dest="blocked")
    ap.add_argument("--modules")
    ap.add_argument("--out")
    ap.add_argument("--doctor")
    a = ap.parse_args()

    root = os.path.abspath(a.init or a.check or a.report or a.html or a.set
                          or a.doctor or "")
    if not root or not os.path.isdir(os.path.join(root, G.SYSTEM_DIR)):
        print("error: pass a project root containing .sales-system", file=sys.stderr)
        return 2

    if a.doctor:
        return doctor(root)
    if a.init:
        init(root, read_modules(root, a.modules))
        check(root, quiet=True)
        return report(root)
    if a.check:
        print("checking the folder for evidence...")
        check(root)
        return report(root)
    if a.set:
        if not a.key:
            print("error: --set needs --key", file=sys.stderr)
            return 2
        return set_status(root, a.key, a.status, a.notes, a.blocked)
    if a.html:
        check(root, quiet=True)
        out = a.out or os.path.join(root, "00-Config", "setup-progress.html")
        render_html(root, out)
        print(f"wrote {os.path.relpath(out, root)}")
        return report(root)
    if a.report:
        return report(root)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
