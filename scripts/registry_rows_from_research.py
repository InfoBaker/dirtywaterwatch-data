#!/usr/bin/env python3
"""Write data/sources/<id>.yaml for the data-bearing rows of research/<area>/sources.json.

    python3 scripts/registry_rows_from_research.py --compare nj pa     # regenerate in memory, diff against the files on disk
    python3 scripts/registry_rows_from_research.py md va dc            # write the files (existing files are left alone)

Rule (docs/plan.md section 4, as applied to every state so far): a row gets a yaml when its status is
used or candidate and its role is advisories, events, monitoring or outfalls. Everything else (law,
permits, news, science, prior art, social, hydrography, watch, rejected, unreachable) stays only in
docs/source-checklist.json. The yaml is the research row's fields in the existing layout: scalars as
JSON strings, lists as JSON lists, the research's notes as a wrapped comment block above `cadence`.
Judgment fields (kind, event_types) come from rules below; the feed yamls (ingester source ids) are
written by hand and name these rows in `registry_ids`.
"""
from __future__ import annotations

import json
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "data" / "sources"

DATA_ROLES = {"advisories", "events", "monitoring", "outfalls"}
KIND_ORDER = ["arcgis", "api", "rss", "csv", "html", "pdf", "email", "phone", "social", "map_only"]
EVENT_TYPES = ["cso", "sso", "bypass", "blended", "plant_bypass", "beach_advisory", "beach_closure", "hab_advisory",
               "shellfish_closure", "rain_advisory", "annual_total", "cso_likely"]
TYPE_MAP = {"dwo": ["cso"], "hab": ["hab_advisory"], "hab_watch": ["hab_advisory"], "hab_warning": ["hab_advisory"],
            "hab_danger": ["hab_advisory"], "unauthorized_discharge": ["sso"], "spill": ["sso"],
            "preemptive_closure": [], "advisory": [], "sample": [], "beach_sample": ["beach_monitoring"]}


# Rows whose url is an endpoint, file or API call get a human page as homepage (what /sources links to); every
# other row's homepage is its url. Hand-picked from the research rows and the feed yamls that name them.
HOMEPAGES = {
    "ca-swrcb-ciwqs-spills-flatfile": "https://www.waterboards.ca.gov/water_issues/programs/sso/docs/index.php",
    "ca-sfpuc-beach-map": "https://webapps.sfpuc.org/sapps/beachesandbay.html",
    "fl-dep-pnp-arcgis": "https://floridadep.gov/sec/sec/content/public-notice-pollution",
    "fl-dep-algal-bloom": "https://floridadep.gov/AlgalBloom",
    "nj-njdep-cso-outfalls-arcgis": "https://www.nj.gov/dep/gis/digidownload/metadata/html/Util_NJPDES_CSO.html",
    "pa-erie-cso-monitoring": "https://telog.erie.pa.us/CSO.Monitoring/",
    "pa-alcosan-news-advisories": "https://www.alcosan.org/news-and-events/featured-news",
    "md-mde-sewer-overflows-2023": "https://mde.maryland.gov/programs/water/Compliance/Pages/ReportedSewerOverflow.aspx",
    "md-mde-sewer-overflows-2005-2023": "https://opendata.maryland.gov/Energy-and-Environment/Reported-Sewer-Overflows/3rgd-zjxx",
    "va-deq-prep-api": "https://portal.deq.virginia.gov/v2/prep/search",
    "va-deq-prep-export-mapserver": "https://data.virginia.gov/dataset/prep-report-export-all",
    "va-alexrenew-cso-status-layer": "https://www.alexrenew.com/combined-sewer-overflow-status",
    "va-vdh-news-advisory-feed": "https://www.vdh.virginia.gov/news/",
    "va-echo-cso-inventory": "https://echo.epa.gov/tools/data-downloads/cso-inventory-download-summary",
    "dc-echo-sobe-dc0021199": "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary",
    "az-epa-sobe": "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary",
    "ak-epa-sobe": "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary",
    "nm-epa-sobe": "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary",
    "nm-nmed-hab-mapper": "https://www.env.nm.gov/surface-water-quality/hab/",
    "al-adem-sso-history": "https://gis.adem.alabama.gov/sso/index.html",
    "al-adem-sso-map-live": "https://gis.adem.alabama.gov/sso/index.html",
    "al-adem-beach-monitoring": "https://adem.alabama.gov/coastal/ademadph-coastal-alabama-beach-monitoring-program",
    "tx-tceq-sso-opendata": "https://www.tceq.texas.gov/compliance/investigation/ud-sso",
    "tx-glo-beach-watch": "https://www.texasbeachwatch.com/",
    "nc-dwr-sso-2026": "https://experience.arcgis.com/experience/4a50b5dc87844bab9930a5906522a779",
    "nc-dwr-sso-2022-2025": "https://www.deq.nc.gov/about/divisions/water-resources/water-quality-permitting/information-sewer-system-overflows",
    "nc-rwq-advisories": "https://www.deq.nc.gov/about/divisions/marine-fisheries/shellfish-sanitation-and-recreational-water-quality/recreational-water-quality",
    "nc-dwr-algal-bloom-reports": "https://www.deq.nc.gov/about/divisions/water-resources/water-sciences-section/algal-blooms",
    "nc-fish-kill-algal-bloom": "https://www.deq.nc.gov/about/divisions/water-resources/water-sciences-section/algal-blooms",
    "wa-ecology-sewage-spills": "https://ecology.wa.gov/water-shorelines/water-quality/wastewater/sewage-spills",
    "hi-doh-cwb-events-api": "https://eha-cloud.doh.hawaii.gov/cwb/",
    "wa-kc-cso-status-csv": "https://kingcounty.gov/en/dept/dnrp/waste-services/wastewater-treatment/sewer-system-services/cso-status",
    "nc-wnc-rec-monitoring": "https://www.deq.nc.gov/about/divisions/water-resources/locations/asheville-regional-office/western-nc-recreational-water-quality-monitoring-program",
    "sd-epa-sobe": "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary",
    "sd-danr-hab-2026-samples": "https://danr.sd.gov/Conservation/WatershedProtection/HAB.aspx",
    "ne-epa-sobe": "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary",
    "ne-dwee-beachwatch": "https://dwee.nebraska.gov/node/4996",
}


# Personal data in a research row never goes into the registry or the checklist (a named staff contact,
# a personal address inside an account name). Agency hotlines and role addresses stay.
SCRUB = [
    (re.compile(r"\s*Contact: [A-Z][a-z]+ [A-Z][a-z]+, [A-Za-z ]+, \d{3}-\d{3}-\d{4}\."), ""),
    (re.compile(r"\(owner [\w.+-]+@[\w.]+\)"), "(owner: a DCGIS account)"),
    # a plant named after a person: the plant's place and kind stay, the name goes
    (re.compile(r"[A-Z][a-z]+ [A-Z]\. [A-Z][A-Za-z'-]+(?: Jr\.| Sr\.)? (?=(?:\([A-Z][a-z]+\) )?WRF\b)"), ""),
]


def scrub_row(o):
    """A copy of the research row (any JSON value) with the SCRUB substitutions applied to every string."""
    if isinstance(o, str):
        for pat, rep in SCRUB:
            o = pat.sub(rep, o)
        return o
    if isinstance(o, list):
        return [scrub_row(v) for v in o]
    if isinstance(o, dict):
        return {k: scrub_row(v) for k, v in o.items()}
    return o


def wanted(r: dict) -> bool:
    return r.get("status") in ("used", "candidate") and r.get("role") in DATA_ROLES


def kind_of(access: list[str]) -> str:
    for k in KIND_ORDER:
        if k in (access or []):
            return k
    return "html"


def event_types_of(r: dict) -> list[str]:
    out: list[str] = []
    for t in r.get("event_types") or []:
        t = re.sub(r"\s*\(.*$", "", str(t)).strip()
        if t == "beach":
            ts = ["beach_monitoring"] if r.get("role") == "monitoring" else ["beach_advisory", "beach_closure"]
        elif t in TYPE_MAP:
            ts = TYPE_MAP[t]
        elif t in EVENT_TYPES:
            ts = [t]
        else:
            ts = []
        for x in ts:
            if x not in out:
                out.append(x)
    if not out and r.get("role") == "outfalls" and re.search(r"\bCSO|combined sewer", r.get("name") or "", re.I):
        out = ["cso"]
    return out


def js(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def wrap(label: str, text: str) -> list[str]:
    text = " ".join(str(text).split())
    return textwrap.wrap(f"{label}: {text}", width=100, initial_indent="# ", subsequent_indent="#   ",
                         break_long_words=False, break_on_hyphens=False)


def render(r: dict, area: str) -> str:
    r = scrub_row(r)
    notes = [f"Notes (research/{area}, status {r['status']}, verified {r.get('verified')}, checked {r.get('checked')})"]
    comment: list[str] = []
    if r.get("status_reason"):
        comment += wrap(notes[0], r["status_reason"])
    if r.get("access_detail"):
        comment += wrap("Access detail (research, quoted)", r["access_detail"])
    if r.get("fills_event_fields"):
        comment += wrap("Can fill", ", ".join(r["fills_event_fields"]))
    if r.get("cannot_fill"):
        comment += wrap("Cannot fill", "; ".join(r["cannot_fill"]))
    if r.get("waters_covered"):
        w = r["waters_covered"]
        if r.get("water_slugs"):
            w += f" (openboatlaunch slugs: {', '.join(r['water_slugs'])})"
        comment += wrap("Waters", w)
    if r.get("history"):
        comment += wrap("History", r["history"])
    if r.get("notes"):
        comment += wrap("Research notes", r["notes"])
    lines = [
        f"id: {js(r['id'])}",
        f"name: {js(r['name'])}",
        f"url: {js(r['url'])}",
        f"homepage: {js(HOMEPAGES.get(r['id'], r['url']))}",
        f"kind: {js(kind_of(r.get('access')))}",
        f"level: {js(r.get('operator_type'))}",
        *comment,
        f"cadence: {js(r.get('cadence'))}",
        f"license: {js(r.get('license') or 'none stated')}",
        f"attribution: {js(r.get('operator'))}",
        "enabled: true",
        f"role: {js(r.get('role'))}",
        f"event_types: {js(event_types_of(r))}",
        f"states: {js([area.upper() if r.get('jurisdiction') in (None, 'US') else r['jurisdiction']])}",
        f"access: {js(r.get('access') or [])}",
        f"access_detail: {js(r.get('access_detail') or None)}",
        f"machine_readable: {'true' if r.get('machine_readable') else 'false'}",
        f"legal_basis: {js(r.get('legal_basis'))}",
        f"checked: {js(r.get('checked'))}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    compare = argv[:1] == ["--compare"]
    areas = argv[1:] if compare else argv
    made = same = differ = 0
    for area in areas:
        for r in json.loads((ROOT / "research" / area / "sources.json").read_text()):
            if not wanted(r):
                continue
            path = SOURCES / f"{r['id']}.yaml"
            text = render(r, area)
            if compare:
                if not path.exists():
                    continue
                if path.read_text() == text:
                    same += 1
                else:
                    differ += 1
                    print("DIFFERS", path.name)
            elif path.exists():
                print("exists, left alone:", path.name)
            else:
                path.write_text(text)
                made += 1
    print(f"identical {same}, different {differ}" if compare else f"{made} files written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
