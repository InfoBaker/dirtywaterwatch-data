"""Per-operator rows of data/notice-channels.json for duties the law puts on every operator (North Carolina, Georgia),
made from the law and data/dischargers.json, so the rows are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_register_rows.py [--only PART[,PART]] [--dry-run]

docs/collection-checklist.md §2: "A duty that falls on each operator gets a row per operator" (Maine's yearly
newspaper notice, Maryland's press notice); "Channels with no web form are rows too: urls [], unmonitored_reason
other, note 'No web form'". The parts:

  nc-annual   G.S. 143-215.1C(a) (fetched from ncleg.gov 2026-11-04 and quoted in LAW_NC_A): the owner or operator of
              a municipal or domestic collection or treatment works "having an average annual flow greater than
              200,000 gallons per day" gives its users or customers and the Department a yearly performance report.
              A row <operator id>-annual-report for every North Carolina operator the duty may fall on (nc_annual_scope):
                - an industrial system ("G.S. 143-215.1C(c)" in its notification_channel: works other than municipal
                  or domestic) is out of (a);
                - an operator whose every permit is a treatment plant with a design flow in EPA's plant rows
                  (data/outfalls-plants-us.json design_flow_mgd) of 0.2 MGD or less is out: the permitted flow bounds
                  the flow the plant is permitted to treat, so its average annual flow is not over 200,000 gallons a
                  day unless it runs over its permit (a design flow of 0 is taken as not entered, not as zero);
                - every other operator is in: a plant permit over 0.2 MGD (the note says the average annual flow the
                  law counts was not checked), or a collection system or a permit with no design flow (the note says
                  flow was not checked and the row is kept on the side of caution).
              The report goes to customers and the Department; no web posting is required, and operators' own
              postings were not searched one by one, so each row is unmonitored (barrier not_verified).

  nc-notice   G.S. 143-215.1C(b) (municipal or domestic works) and (c) (any other works): a press release to the
              news media within 24 hours for 1,000 gallons or more reaching surface waters, and a newspaper notice
              for 15,000 gallons or more. Rows <operator id>-press-release and <operator id>-newspaper-notice for every
              North Carolina operator in data/dischargers.json (public or private alike; (c) for an industrial
              system). Both go to the media or the newspaper only, so each is unmonitored, barrier print_only. They
              replace the statewide rows nc-operator-press-release and nc-operator-newspaper-notice (the Department
              publishes neither, so no agency channel is left to keep). An operator's own web page for its releases
              (Charlotte Water, Raleigh) stays its own row and is named in the note.

  ga-notice   Ga. Comp. R. & Regs. 391-3-6-.05(3), the owner of a POTW (every Georgia operator in data/dischargers.json:
              the registry's Georgia rows are POTW permits): (b) the legal-organ notice of a major spill, (e) the
              report to local television, radio and print media, (f) the report to the local health department and
              (g) the posted notice at the spill and the waterway's access points. Rows <operator id>-legal-organ-notice,
              -media-notice, -health-department and -spill-signs, replacing the statewide rows ga-legal-organ-notice,
              ga-media-notice, ga-local-health-departments and ga-spill-signs. ga-downstream-water-suppliers stays one
              row: (3)(d) is EPD's duty as well as the owner's, a direct notice to water suppliers, not to the public.

  voluntary   Voluntary channels the NC, GA and FL checklists found missing (basis_kind voluntary, legal_basis null,
              records false, the note saying why it is voluntary and how its address answered the project user agent
              on one GET, 2026-11-04): Swim Guide for North Carolina and Florida (a script app: app_only, as every
              other state's Swim Guide row), the Chattahoochee River BacteriALERT results page (USGS with Chattahoochee
              Riverkeeper), WWALS's Florida spill pages, and Sarasota County's spill layer (its description only: the
              rows carry street addresses and free-text notes, and DEP's PNP feed carries the same events).

Idempotent: a part's rows are rebuilt from the inputs and replace rows of the same id; the register stays sorted by
(state, id) and every row's barrier is what ingest.notification_pages.barrier_for says. `checked` is the date the law
and the inputs were read (CHECKED), not the run date, so a rerun changes nothing.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from ingest import notification_pages as NP  # noqa: E402

REGISTER = ROOT / "data" / "notice-channels.json"
DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CHECKED = "2026-11-04"
FLOW_THRESHOLD_MGD = 0.2              # 200,000 gallons a day

LAW_NC_A = ('G.S. 143-215.1C(a): "The owner or operator of any wastewater collection or treatment works, the operation '
            'of which is primarily to collect or treat municipal or domestic wastewater and for which a permit is issued '
            'under this Part and having an average annual flow greater than 200,000 gallons per day, shall provide to '
            'the users or customers of the collection system or treatment works and to the Department an annual report '
            'that summarizes the performance of the collection system or treatment works and the extent to which the '
            'collection system or treatment works has violated the permit or federal or State laws, regulations, or '
            'rules related to the protection of water quality. The report shall be prepared on either a calendar or '
            'fiscal year basis and shall be provided no later than 60 days after the end of the calendar or fiscal '
            'year."')
NC_SOURCE_A = "nc-law-gs-143-215-1c-a"
NC_SOURCE_B = "nc-law-gs-143-215-1c"
# G.S. 143-215.1C(b)(1)/(2) and (c)(1)/(2), quoted from the same text
_PRESS = ('"In the event of a discharge of 1,000 gallons or more of untreated {w} to the surface waters of the State, '
          'issue a press release to all print and electronic news media that provide general coverage in the county '
          'where the discharge occurred setting out the details of the discharge. The owner or operator shall issue '
          'the press release within 24 hours after the owner or operator has determined that the discharge has '
          'reached the surface waters of the State."')
_PAPER = ('"In the event of a discharge of 15,000 gallons or more of untreated {w} to the surface waters of the State, '
          'publish a notice of the discharge in a newspaper having general circulation in the county in which the '
          'discharge occurs and in each county downstream from the point of discharge that is significantly affected '
          'by the discharge." The notice is captioned "NOTICE OF DISCHARGE OF UNTREATED {cap}" and published within 10 '
          'days after the Secretary approves its form, content and newspapers')
LAW_NC_PRESS = {"b": "G.S. 143-215.1C(b)(1): " + _PRESS.format(w="wastewater"),
                "c": "G.S. 143-215.1C(c)(1): " + _PRESS.format(w="waste")}
LAW_NC_PAPER = {"b": "G.S. 143-215.1C(b)(2): " + _PAPER.format(w="wastewater", cap="SEWAGE"),
                "c": "G.S. 143-215.1C(c)(2): " + _PAPER.format(w="waste", cap="WASTE")}
NC_REPLACES = ("nc-operator-press-release", "nc-operator-newspaper-notice")

# Ga. Comp. R. & Regs. 391-3-6-.05(3), as research/ga/report.md §2.1 quotes the Cornell LII text
GA_RULE = "Ga. Comp. R. & Regs. 391-3-6-.05"
GA_SOURCES = ["ga-rule-391-3-6-05"]
GA_DUTIES = [
    # (suffix, channel_kind, noun, legal_basis, what the note says the duty is, the barrier sentence)
    ("health-department", "local_health_page", "Health department report",
     GA_RULE + '(3)(f): the owner "shall immediately report the incident to the local health department(s)"',
     "an immediate report of each spill to the local health department(s); the rule does not require the "
     "department to publish it",
     "No web channel found."),
    ("legal-organ-notice", "news_page", "Printed or broadcast notice",
     GA_RULE + '(3)(b); O.C.G.A. 12-5-30.1: notice of a major spill (over 10,000 gallons, or one causing a water-quality '
     'violation) in "the legal organ of the County where the incident occurred ... within seven days"',
     "a notice of each major spill in the county's legal organ (its newspaper of record) within seven days",
     "Printed only."),
    ("media-notice", "news_page", "Printed or broadcast notice",
     GA_RULE + '(3)(e): the owner "shall report the incident to the local media (television, radio and print media) '
     'within 24 hours of becoming aware of the incident", with date, location, cause, volume, receiving water and '
     'corrective action',
     "a report of each spill to local television, radio and print media within 24 hours",
     "The notice is broadcast or printed only; no public record of it is kept online."),
    ("spill-signs", "lights_signs_page", "Lights and signs",
     GA_RULE + '(3)(g): the owner "shall immediately post a notice as close as possible to where the spill or major '
     'spill occurred and where the spill or major spill entered State waters" and along the affected waterway "at '
     'bridge crossings, trails, boat ramps, recreational areas, and other points of public access", kept "a minimum '
     'of seven days after the spill or major spill has ceased"',
     "signs at the spill, where it entered State waters and at the waterway's public access points, kept at least "
     "seven days after it ceases",
     "No online record."),
]
GA_REPLACES = ("ga-legal-organ-notice", "ga-media-notice", "ga-local-health-departments", "ga-spill-signs")


def mgd(x: float) -> str:
    return f"{x:g} MGD"


def nc_industrial(op: dict) -> bool:
    """Works other than municipal or domestic: add_nc_operators.py writes the (c) duty into their channel."""
    return "G.S. 143-215.1C(c)" in str(op.get("notification_channel") or "")


def design_flows(plants: dict | list, state: str) -> dict[str, float]:
    """{permit: largest design flow in MGD} from EPA's plant rows of one state (rows without a flow, or with 0, which
    ICIS uses for a flow not entered, left out)."""
    rows = plants.get("outfalls", []) if isinstance(plants, dict) else plants
    out: dict[str, float] = {}
    for r in rows:
        f = r.get("design_flow_mgd")
        if r.get("state") == state and r.get("npdes_permit") and isinstance(f, (int, float)) and not isinstance(f, bool) \
                and f > 0:
            out[r["npdes_permit"]] = max(out.get(r["npdes_permit"], 0.0), float(f))
    return out


def permits_of(op: dict) -> list[str]:
    ps = list(op.get("npdes_permits") or [])
    if op.get("npdes_permit") and op["npdes_permit"] not in ps:
        ps.insert(0, op["npdes_permit"])
    return ps


def nc_annual_scope(op: dict, flows: dict[str, float]) -> tuple[bool, str]:
    """(in scope, the flow sentence of the note or the reason it is out)."""
    if nc_industrial(op):
        return False, "industrial system: (a) covers municipal or domestic works only"
    ps = permits_of(op)
    known = {p: flows[p] for p in ps if p in flows}
    over = {p: f for p, f in known.items() if f > FLOW_THRESHOLD_MGD}
    if over:
        p, f = max(over.items(), key=lambda kv: kv[1])
        return True, (f"EPA's permitted (design) flow for {p} is {mgd(f)}, over the threshold; the average annual flow "
                      f"the law counts was not checked.")
    if ps and len(known) == len(ps):
        return False, ("every permit is a plant with a design flow of 0.2 MGD or less ("
                       + ", ".join(f"{p} {mgd(f)}" for p, f in known.items()) + ")")
    unknown = [p for p in ps if p not in known]
    small = (" EPA's design flow for " + ", ".join(f"{p} is {mgd(f)}" for p, f in known.items())
             + ", under the threshold, but the other permits' flow is unknown.") if known else ""
    return True, (f"flow not checked: no design flow is on record for {', '.join(unknown) or 'its permits'}"
                  f" (a collection system or a plant missing from EPA's rows); listed on the side of caution.{small}")


def finish(r: dict) -> dict:
    """The row's barrier (and barrier_review) as the validator wants them."""
    bar, review = NP.barrier_for(r)
    r["barrier"] = bar
    if review:
        r["barrier_review"] = review
    else:
        r.pop("barrier_review", None)
    return r


def nc_annual_rows(dis: list[dict], plants) -> tuple[list[dict], list[tuple[str, str]]]:
    """The G.S. 143-215.1C(a) rows, and the operators left out with the reason."""
    flows = design_flows(plants, "NC")
    rows, out = [], []
    for op in dis:
        if op.get("state") != "NC":
            continue
        ok, why = nc_annual_scope(op, flows)
        if not ok:
            out.append((op["id"], why))
            continue
        rows.append(finish({
            "id": f"{op['id']}-annual-report", "state": "NC", "operator_id": op["id"], "agency": None,
            "name": op["name"], "permit": None, "channel_kind": "operator_page", "urls": [], "method": None,
            "legal_basis": LAW_NC_A, "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
            "publishes": "documents",
            "note": (f"No web form: {op['name']}: the yearly report on the system's performance and its permit "
                     "violations goes to the users or customers and a copy to the Department (DEQ), no later than 60 "
                     "days after the calendar or fiscal year; the law requires no web posting. It summarizes the year, "
                     "not single overflows. The duty applies to municipal or domestic works with an average annual "
                     f"flow over 200,000 gallons a day: {why} The operator's own posting was not searched "
                     "individually. (G.S. 143-215.1C(a), read on ncleg.gov 2026-11-04)"),
            "checked": CHECKED, "records": False, "noun": "Annual performance report", "sources": [NC_SOURCE_A]}))
    return rows, out


def own_pages(register: dict, op_id: str, section: str) -> list[str]:
    """Ids of the operator's existing web rows that cite the same subsection (its own page for the notices)."""
    return sorted(r["id"] for r in register.get("channels") or [] if r.get("operator_id") == op_id and r.get("urls")
                  and str(r.get("legal_basis") or "").startswith(section))


def nc_notice_rows(dis: list[dict], plants, register: dict | None = None) -> tuple[list[dict], list]:
    """The G.S. 143-215.1C(b)/(c) press-release and newspaper rows, two per North Carolina operator."""
    rows = []
    for op in dis:
        if op.get("state") != "NC":
            continue
        sub = "c" if nc_industrial(op) else "b"
        works = ("works other than municipal or domestic, so (c)" if sub == "c"
                 else "municipal or domestic works, public or private, so (b)")
        own = own_pages(register or {}, op["id"], f"G.S. 143-215.1C({sub})(1)")
        own_s = (f" Its own web page for releases is the row {', '.join(own)}." if own else "")
        rows.append(finish({
            "id": f"{op['id']}-press-release", "state": "NC", "operator_id": op["id"], "agency": None, "name": op["name"],
            "permit": None, "channel_kind": "news_page", "urls": [], "method": None, "legal_basis": LAW_NC_PRESS[sub],
            "basis_kind": "law", "monitored": False, "unmonitored_reason": "other", "publishes": "unknown",
            "note": (f"No web form: {op['name']} ({works}): a press release to all print and electronic news media "
                     "covering the county within 24 hours after it determines that 1,000 gallons or more reached "
                     "surface waters. It reaches the public printed only or on air, as the media carry it; the law "
                     "requires no web posting. Copies and the media list are kept a year and given to any person on request."
                     f"{own_s} (G.S. 143-215.1C, read on ncleg.gov 2026-11-04; research/nc/report.md §2.1)"),
            "checked": CHECKED, "records": False, "noun": "Printed or broadcast notice", "sources": [NC_SOURCE_B]}))
        rows.append(finish({
            "id": f"{op['id']}-newspaper-notice", "state": "NC", "operator_id": op["id"], "agency": None,
            "name": op["name"], "permit": None, "channel_kind": "news_page", "urls": [], "method": None,
            "legal_basis": LAW_NC_PAPER[sub], "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
            "publishes": "unknown",
            "note": (f"No web form: {op['name']} ({works}): a paid notice in newspapers of the county and of each "
                     "downstream county the Secretary finds significantly affected, for 15,000 gallons or more; proof "
                     "of publication is filed with DEQ within 30 days. Printed only; the law requires no web posting. "
                     "(G.S. 143-215.1C, read on ncleg.gov 2026-11-04; research/nc/report.md §2.1)"),
            "checked": CHECKED, "records": False, "noun": "Printed or broadcast notice", "sources": [NC_SOURCE_B]}))
    return rows, []


def ga_notice_rows(dis: list[dict], plants, register: dict | None = None) -> tuple[list[dict], list]:
    """The 391-3-6-.05(3) rows, four per Georgia operator."""
    rows = []
    for op in dis:
        if op.get("state") != "GA":
            continue
        for suffix, kind, noun, basis, duty, barrier_s in GA_DUTIES:
            srcs = GA_SOURCES + (["ga-law-ocgs-12-5-30-1"] if "12-5-30.1" in basis else [])
            rows.append(finish({
                "id": f"{op['id']}-{suffix}", "state": "GA", "operator_id": op["id"], "agency": None,
                "name": op["name"], "permit": None, "channel_kind": kind, "urls": [], "method": None,
                "legal_basis": basis, "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
                "publishes": "unknown",
                "note": (f"No web form: {op['name']}: {duty}. {barrier_s} The rule binds the owner of a publicly owned "
                         "treatment works. (research/ga/report.md §2.1)"),
                "checked": CHECKED, "records": False, "noun": noun, "sources": srcs}))
    return rows, []


SWIM_GUIDE = "https://www.theswimguide.org/"
VOLUNTARY = [
    {"id": "fl-sarasota-spill-layer", "state": "FL", "operator_id": None, "agency": "Sarasota County",
     "name": "Sarasota County", "permit": None, "channel_kind": "feed",
     "urls": ["https://ags3.scgov.net/server/rest/services/Hosted/AbnormalEventSpill/FeatureServer/0?f=json"],
     "method": "json", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices",
     "note": ("Sarasota County's AbnormalEventSpill layer: sanitary sewer overflows in the county reported to DEP by the "
              "North Port, Sarasota and Venice utilities, the Englewood district, Sarasota County Utilities and private "
              "systems (date, type, gallons, whether surface water was affected, a point). Voluntary: a county "
              "publication no law requires. The layer's description answered 200 to the project user agent on "
              "2026-11-04 (last edit 2026-08-17). Only the description is read (its last-edit time shows a change): "
              "the rows carry street addresses and free-text notes, and the PNP feed (fl-dep-pnp) carries the same "
              "reportable events. (research/fl/report.md, fl-sarasota-abnormal-event)"),
     "checked": CHECKED, "records": False, "every_hours": 24, "noun": "Voluntary spill layer",
     "sources": ["fl-sarasota-abnormal-event"]},
    {"id": "fl-swim-guide", "state": "FL", "operator_id": None, "agency": "Swim Drink Fish", "name": "Swim Drink Fish",
     "permit": None, "channel_kind": "swim_guide", "urls": [SWIM_GUIDE], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "app_only", "publishes": "results",
     "note": ("Swim Guide listings for Florida. Voluntary republisher of local beach results; affiliates not resolved. "
              "The site answered 200 to the project user agent on 2026-11-04 but shows its listings in a script app "
              "with no API: not read. The Department of Health's beach results are read as a feed (fl-doh-beaches)."),
     "checked": CHECKED, "records": False, "noun": "Swim Guide listing"},
    {"id": "fl-wwals-spill-posts", "state": "FL", "operator_id": None, "agency": "WWALS Watershed Coalition",
     "name": "WWALS Watershed Coalition", "permit": None, "channel_kind": "news_page",
     "urls": ["https://wwals.net/issues/vww/fl-spills/", "https://wwals.net/tag/notice-of-pollution/"],
     "method": "html", "legal_basis": None, "basis_kind": "voluntary", "monitored": True, "unmonitored_reason": None,
     "publishes": "notices",
     "note": ("WWALS Watershed Coalition (Suwannee Riverkeeper): its Florida spills page, which links to DEP's map of "
              "Public Notices of Pollution, and its posts tagged Notice of Pollution (one post, a High Springs sewage "
              "spill of 2023-03-30, on 2026-11-04). Voluntary: a watershed group's posts. Both answered 200 to the "
              "project user agent on 2026-11-04. Read for the channel's health; not used for records: the PNP feed "
              "(fl-dep-pnp) carries the notices. (research/fl/report.md, fl-wwals)"),
     "checked": CHECKED, "records": False, "every_hours": 24, "sources": ["fl-wwals"]},
    {"id": "ga-chattahoochee-bacterialert", "state": "GA", "operator_id": None,
     "agency": "U.S. Geological Survey and Chattahoochee Riverkeeper (BacteriALERT)",
     "name": "Chattahoochee River BacteriALERT", "permit": None, "channel_kind": "group_results",
     "urls": ["https://ga.water.usgs.gov/bacteria/"], "method": "html", "legal_basis": None, "basis_kind": "voluntary",
     "monitored": True, "unmonitored_reason": None, "publishes": "results",
     "note": ("Chattahoochee River BacteriALERT: weekly E. coli samples (reported within 24 hours) and turbidity-based "
              "E. coli estimates at three USGS stations in the Chattahoochee River National Recreation Area, a program "
              "with Chattahoochee Riverkeeper. Voluntary monitoring; results, not overflow notices. Answered 200 to "
              "the project user agent on 2026-11-04 (the page then said the estimate could not be calculated because "
              "of gage maintenance). Chattahoochee Riverkeeper's own BacteriALERT addresses answered 301 that day "
              "(to an image and to a blog post on the program's 20 years). The page offers a weekly e-mail of the "
              "sampled counts. "
              "(research/ga/report.md §2.5)"),
     "checked": CHECKED, "records": False, "every_hours": 24, "noun": "Results page"},
    {"id": "nc-swim-guide", "state": "NC", "operator_id": None, "agency": "Swim Drink Fish", "name": "Swim Drink Fish",
     "permit": None, "channel_kind": "swim_guide", "urls": [SWIM_GUIDE], "method": "html", "legal_basis": None,
     "basis_kind": "voluntary", "monitored": False, "unmonitored_reason": "app_only", "publishes": "results",
     "note": ("Swim Guide listings for North Carolina's beaches and the western river stations of DWR's recreational "
              "monitoring (nc-wnc-rec-monitoring). Voluntary republisher of local results; affiliates not resolved. "
              "The site answered 200 to the project user agent on 2026-11-04 but shows its listings in a script app "
              "with no API: not read. (research/nc/report.md §2.5)"),
     "checked": CHECKED, "records": False, "noun": "Swim Guide listing", "sources": ["nc-wwals-and-swim-guide"]},
]


def voluntary_rows(dis, plants, register=None) -> tuple[list[dict], list]:
    return [finish(dict(r)) for r in VOLUNTARY], []


PARTS = {"nc-annual": {"build": lambda dis, plants, reg: nc_annual_rows(dis, plants), "replaces": ()},
         "nc-notice": {"build": nc_notice_rows, "replaces": NC_REPLACES},
         "ga-notice": {"build": ga_notice_rows, "replaces": GA_REPLACES},
         "voluntary": {"build": voluntary_rows, "replaces": ()}}


def merge(doc: dict, new: list[dict], replaces=()) -> dict:
    """The register with `new` rows put in (same id replaced) and the `replaces` ids removed, sorted by (state, id)."""
    ids = {r["id"] for r in new} | set(replaces)
    chans = [r for r in doc["channels"] if r["id"] not in ids] + new
    chans.sort(key=lambda r: (str(r.get("state")), str(r.get("id"))))
    return {**doc, "channels": chans}


def run(parts: list[str], register: Path = REGISTER, dis_path: Path = DIS, plants_path: Path = PLANTS,
        dry_run: bool = False) -> dict:
    doc = json.loads(register.read_text())
    dis = json.loads(dis_path.read_text())
    plants = json.loads(plants_path.read_text()) if plants_path.exists() else {"outfalls": []}
    report: dict = {}
    for p in parts:
        rows, left_out = PARTS[p]["build"](dis, plants, doc)
        before = {r["id"] for r in doc["channels"]}
        doc = merge(doc, rows, PARTS[p]["replaces"])
        report[p] = {"rows": len(rows), "new": len({r["id"] for r in rows} - before),
                     "removed": sorted(set(PARTS[p]["replaces"]) & before), "left_out": left_out,
                     "barriers": dict(Counter(r["barrier"] or ("review" if r.get("barrier_review") else "none")
                                                for r in rows))}
    errs = NP.validate_register(doc, dis, ROOT)
    if errs:
        raise SystemExit("the register would not validate:\n" + "\n".join(errs[:20]))
    if not dry_run:
        register.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return report


def main(argv: list[str]) -> int:
    parts = list(PARTS)
    if "--only" in argv:
        parts = argv[argv.index("--only") + 1].split(",")
        bad = [p for p in parts if p not in PARTS]
        if bad:
            raise SystemExit(f"unknown parts {bad}; the parts are {list(PARTS)}")
    report = run(parts, dry_run="--dry-run" in argv)
    for p, r in report.items():
        print(f"{p}: {r['rows']} rows ({r['new']} new), barriers {r['barriers']}, removed {r['removed']}, "
              f"left out {len(r['left_out'])}")
        for oid, why in r["left_out"]:
            print(f"   left out {oid}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
