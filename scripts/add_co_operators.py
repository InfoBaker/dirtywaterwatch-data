"""Colorado operator rows for data/dischargers.json: one row per permittee, every Colorado permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_co_operators.py [--dry-run]

The shared rules are in scripts/mountain_operator_rows.py (inputs, names, legal forms, EPA-issued permits). Colorado:
  - 352 permits in EPA's plant table (data/outfalls-plants-us.json, file of 2026-11-01), 92 research rows (the major
    permits), the 96 major permits of the federal seed, 42 private candidates (8 of them outside the plant table).
    No combined sewer permit (EPA's CSO inventory of 2026-10-31 has none for Colorado).
  - Permit prefixes: CO0 individual CDPS permits; COG58/COG59 coverages under Colorado's general permits for domestic
    wastewater lagoons and small plants; COG587 EPA Region 8's lagoon general permit in Indian country (Ute Mountain
    Ute and Southern Ute lagoons); COX ground-water discharge permits and COE reclaimed-water permits by Colorado's
    numbering (their discharge goes to ground water or to reuse, not to a stream: said in the row's notes, and the
    outfall registry is left as EPA wrote it for the water batch to judge).
  - EPA-issued: EPA Region 8 issues every permit on tribal land and for every federal facility in Colorado
    (mountain_operator_rows.R8). Their channel is EPA's.
  - The channel (CHANNEL): C.R.S. 25-8-601(2) and the CDPS permits' standard conditions put the report on the operator,
    to the Water Quality Control Division (oral within 24 hours, written within five days); the Division publishes no
    list; no duty to tell the public was found. CDPHE's incident pages answered 403 to the build's client on
    2026-11-14. The City of Pueblo's row names the August 2026 Arkansas River spill that Colorado Parks and Wildlife's
    advisory reported (co-official-notices).
Idempotent: a rerun replaces the rows it wrote (state CO, source_areas ["co"]) where they stood.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mountain_operator_rows as M  # noqa: E402

CHECKED = "2026-11-14"
LAW = ("Colorado law puts the report on the operator and the recipient is the state: C.R.S. 25-8-601(2) requires anyone "
       "whose activity results in a spill or discharge that may pollute state waters to notify the Water Quality "
       "Control Division as soon as they know of it, and the Colorado Discharge Permit System permits' standard "
       "conditions require an oral report within 24 hours of noncompliance that may endanger health or the environment "
       "and a written report within five days. The Division publishes no list of the reports, and no duty to tell the "
       "public was found. A large spill reaches the public when an agency issues an advisory (Colorado Parks and "
       "Wildlife's water-contact advisory for the August 2026 Pueblo spill). The operator's own pages were not "
       "searched individually.")
EPA = ("A permit EPA Region 8 issues (tribal land or a federal facility in Colorado, where the state program does not "
       "apply): the permit's 24-hour and five-day noncompliance reports go to EPA (40 CFR 122.41(l)(6)), which publishes "
       "those filed electronically in its sewer overflow tables (" + M.ECHO + "); the extracts of 2026-11-14 hold no "
       "Colorado report. No public notice duty was found.")
PRIVATE = " The statute and the permit bind a private permittee as they bind a public one."
NAMES = {
    "CO0040053": "City of Grand Junction (Persigo plant, with Mesa County)",
    "CO0020435": "Tri-Lakes Wastewater Treatment Facility",
    "CO0021181": "U.S. Department of the Army, Fort Carson",
    "COE029000": "U.S. Department of the Army, Fort Carson",
    "CO0034398": "National Park Service",
    "CO0034975": "National Park Service",
    "COX622043": "National Park Service",
    "CO0021369": "Eagle River Water and Sanitation District",
    "CO0024431": "Eagle River Water and Sanitation District",
    "CO0037311": "Eagle River Water and Sanitation District",
    "CO0021580": "St. Vrain Sanitation District",
    "CO0041700": "St. Vrain Sanitation District",
    "CO0020508": "City of Evans",
    "CO0047287": "City of Evans",
    "CO0045420": "Upper Blue Sanitation District",
    "CO0021539": "Upper Blue Sanitation District",
    "COX634066": "Upper Blue Sanitation District",
    "CO0023132": "City of Monte Vista",
    "CO0036927": "City of Monte Vista",
    "CO0046868": "Town of Mead",
    "CO0046876": "Town of Mead",
    "COG650168": "Town of Mead",
    "COG650179": "Town of Wellington",
    "CO0041599": "Town of Crowley",
    "COG591126": "Town of Crowley",
    "CO0041653": "Town of Gilcrest",
    "COG588121": "Town of Gilcrest",
    "COE009000": "Fairways Metropolitan District",
    "CO0048411": "Fairways Metropolitan District",
    "COE022000": "Colorado Air and Space Port (Adams County)",
    "CO0047741": "Colorado Air and Space Port (Adams County)",
    "COX634041": "Catamount Metropolitan District",
    "COX634058": "Catamount Metropolitan District",
    "COG591193": "Will-O-Wisp Metropolitan District",
    "CO0041521": "Will-O-Wisp Metropolitan District",
    "CO0022853": "Southern Ute Indian Tribe",
    "COG587201": "Southern Ute Indian Tribe",
    "COG587101": "Ute Mountain Ute Tribe (Towaoc lagoons)",
    "COG587103": "Ute Mountain Ute Tribe (Towaoc lagoons)",
    "COG590067": "Colorado Department of Transportation",
    "COG590075": "Colorado Department of Transportation",
    "COG590076": "Colorado Department of Transportation",
    "COX631011": "Colorado Department of Transportation",
    "COX622004": "Colorado Department of Public Works (CDPW, as EPA records it)",
    "COX622007": "Colorado Parks and Wildlife (state parks)",
    "COX631074": "Colorado Parks and Wildlife (state parks)",
    "COG589008": "Colorado Parks and Wildlife (state parks)",
    "COX634078": "Colorado Parks and Wildlife (state parks)",
    "CO0046094": "Colorado Department of Corrections",
    "COX634065": "Colorado Department of Corrections",
    "COG588032": "Colorado Department of Corrections",
    "COG590148": "Routt County",
    "COG591184": "Routt County",
    "CO0047449": "Routt County",
    "COG588016": "Snyder Sanitation District",
    "COG590012": "Almont plant",
    "CO0046574": "Clear Creek plant",
    "CO0026409": "City and County of Broomfield",
    "COE013000": "City and County of Broomfield",
    "CO0029955": "Summit County",
    "CO0026638": "Metro Water Recovery",
    "CO0048959": "Metro Water Recovery",
    "CO0026735": "Colorado Springs Utilities",
    "CO0046850": "Colorado Springs Utilities",
    "COE008000": "Colorado Springs Utilities",
    "COE025000": "Colorado Springs Utilities",
    "CO0026646": "City of Pueblo",
    "COE012000": "Denver Water",
    "COE017000": "Elbert Creek Water Company, LLC",
}
FORMS = {
    "CO0040053": "city", "CO0020435": "special district", "COG590012": None, "CO0046574": None,
    "CO0026638": "special district",      # Metro Water Recovery: a metropolitan wastewater reclamation district
    "CO0026735": "city", "CO0046850": "city", "COE008000": "city", "COE025000": "city",   # a city enterprise
    "COE012000": "authority",             # the Denver Board of Water Commissioners
    "CO0032999": "authority",             # South Platte Renew: the Littleton/Englewood joint plant
    "COX622004": "state facility", "COG588016": "special district", "CO0047741": "county", "COE022000": "county",
    "COG591187": "county",                # Teller County Wastewater Utility
    "CO0047457": "county",                # Durango La Plata County Airport
    "COX632098": "member-owned utility",  # Louviers Mutual Service Co
    "COG588040": "investor-owned utility", "COE017000": "investor-owned utility",
    "CO0049019": "homeowners' association",   # Fox Acres Community Services Corp
    "CO0040835": "campground or resort",  # Clear Creek Skiing Corp (Loveland ski area)
    "CO0038598": "campground or resort",  # Sunlight Inc (ski area)
    "COG591147": "institution", "COX631005": "institution", "CO0048985": "institution",
    "CO0031062": "institution",           # Whiteman School
    "COE013000": "city",
    "CO0026409": "city",                  # a consolidated city and county (docs/legal-forms.md)
    "CO0047317": "institution",           # the University of Denver, a private university
    "CO0036129": "business or industrial",  # Tiny Town Company LLC (an amusement park), not a town
    "CO0030112": "institution",           # a church association's camp
    "COG590013": "special district",      # San Juan Village Metropolitan District
    "CO0047252": "investor-owned utility",  # Ellicott Utilities Company
}
ROW_IDS = {"CO0020435": "co-tri-lakes-wwtf", "COG590012": "co-almont-plant", "CO0046574": "co-clear-creek-plant"}
SHORT = {"co-co0026638": "Metro Water Recovery", "co-co0026735": "Colorado Springs Utilities"}
NOTES = {"CO0020435": ("The plant is owned jointly by the Monument Sanitation District, the Palmer Lake Sanitation District "
                      "and the Woodmoor Water and Sanitation District No. 1 (EPA's permit name: \"Monument SD&Palmer "
                      "Lake SD&Woodmoor WSD 1\"); legal_form is the districts'."),
         "COG590012": ("EPA's permit name is \"Almont Sewage Hereafter In Transit Plant\"; the body that holds the "
                       "coverage is not stated, so legal_form is left unset."),
         "CO0046574": "EPA names the facility only (\"Clear Creek WWTP\"); the body that holds it is not stated."}
for _p in ("COE001000", "COE002000", "COE003000", "COE004000", "COE005000", "COE007000", "COE008000", "COE009000",
           "COE010000", "COE011000", "COE012000", "COE013000", "COE015000", "COE016000", "COE017000", "COE018000",
           "COE022000", "COE025000", "COE027000", "COE029000", "COE032000"):
    NOTES[_p] = f"{_p} is a reclaimed-water permit by Colorado's numbering (COE): water reused, not a stream outfall."
TRIBAL_WORDS = re.compile(r"\bUte\b|Towaoc|Ignacio Peak", re.I)
KINDS = {"co-co0026646": "sso"}       # the August 2026 Arkansas River spill (co-official-notices)


def channel(row: dict) -> str:
    s = LAW
    if row.get("legal_form") not in M.PUBLIC_FORMS and row.get("legal_form"):
        s += PRIVATE
    if row["id"] == "co-co0026646":
        s += (" Its August 26-27, 2026 spill of about 4.2 million gallons of untreated sewage to the Arkansas River "
              "reached the public through Colorado Parks and Wildlife's water-contact advisory of August 30, 2026 "
              "(https://cpw.state.co.us/news/08302026/water-contact-advisory-john-martin-pueblo-sewage-spill-moves-"
              "downstream); the city's own news page (https://www.pueblo.us/m/newsflash/home/detail/5002) did not "
              "answer the build's client on 2026-11-14 (connection timed out).")
    for p in row["npdes_permits"]:
        if p.startswith("COX"):
            s += (f" {p} is a ground-water discharge permit by Colorado's numbering (COX): its discharge goes to ground "
                  "water, not to a stream.")
            break
    return s


def epa_channel(row: dict) -> str:
    return EPA


def main(argv: list[str]) -> int:
    new, counts = M.build_rows("CO", checked=CHECKED, channel=channel, epa_channel=epa_channel, names=NAMES,
                               forms={k: v for k, v in FORMS.items() if v}, tribal_words=TRIBAL_WORDS,
                               epa_issued_extra=set(), notes_by_permit=NOTES, kinds=KINDS, short_names=SHORT,
                               federal_is_epa=True, row_ids=ROW_IDS)
    for r in new:          # a FORMS value of None: the body is not known, keep legal_form unset
        if any(p in FORMS and FORMS[p] is None for p in r["npdes_permits"]):
            r.pop("legal_form", None)
    M.write("CO", new, "--dry-run" in argv)
    print(M.report("CO", new, counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
