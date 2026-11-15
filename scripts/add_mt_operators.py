"""Montana operator rows for data/dischargers.json: one row per permittee, every Montana permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_mt_operators.py [--dry-run]

The shared rules are in scripts/mountain_operator_rows.py. Montana:
  - 199 permits in EPA's plant table (data/outfalls-plants-us.json, file of 2026-11-01), 10 research rows, the 20
    major permits of the federal seed, 55 private candidates and 4 public-by-name rows (some outside the plant table).
    No combined sewer permit.
  - Permit prefixes: MT0 individual MPDES permits; MTG58 coverages under Montana's general permit for domestic lagoons;
    MTG589 EPA Region 8's lagoon general permit in Indian country; MTX Montana Ground Water Pollution Control System
    permits by DEQ's numbering (discharge to ground water, said in the row's notes; the outfall registry is left as EPA
    wrote it for the water batch to judge).
  - EPA-issued: EPA Region 8 issues the permits on tribal land and lands of exclusive federal jurisdiction in Montana
    (mountain_operator_rows.R8). Filed as EPA's: EPA's collection-system table (Polson, Ronan, Poplar), the MTG589
    coverages, EPA's tribal facility type, the tribes' and tribal utilities' names, and the reservation towns listed in
    EPA_EXTRA (Browning, Lodge Grass, Wolf Point, Poplar, Brockton, St. Ignatius, the Salish and Kootenai Housing
    Authority, the Bureau of Reclamation's Yellowtail Dam permits on the Crow Reservation).
  - The channel: MPDES permits' standard conditions (Lolo's MT0020168, Part II.I, read 2026-11-03): serious
    noncompliance reported to DEQ's Water Protection Bureau or Disaster and Emergency Services within 24 hours, in
    writing within five days, on DEQ's SSO form; DEQ publishes no list. deq.mt.gov did not resolve for the build's
    client on 2026-11-14, so the permit and form were not re-read.
Idempotent: a rerun replaces the rows it wrote (state MT, source_areas ["mt"]) where they stood.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mountain_operator_rows as M  # noqa: E402

CHECKED = "2026-11-14"
LAW = ("Montana puts the report on the operator and the recipient is the state: the Montana Pollutant Discharge "
       "Elimination System permits' standard conditions require noncompliance that may seriously endanger health or the "
       "environment, a bypass or an upset to be reported to the Department of Environmental Quality's Water Protection "
       "Bureau or to Disaster and Emergency Services within 24 hours, and in writing within five days on DEQ's sanitary "
       "sewer overflow form. DEQ publishes no list of the reports, and no duty to tell the public was found. The "
       "operator's own pages were not searched individually.")
EPA = ("A permit EPA Region 8 issues (tribal land or land of exclusive federal jurisdiction, where the state program does "
       "not apply): the permit's 24-hour and five-day noncompliance reports go to EPA (40 CFR 122.41(l)(6)), which "
       "publishes those filed electronically in its sewer overflow tables (" + M.ECHO + "); the extracts of 2026-11-14 "
       "hold no Montana report, and list the Polson, Ronan and Poplar collection systems. No public notice duty was "
       "found.")
PRIVATE = " The permit binds a private permittee as it binds a public one."
TRIBAL_WORDS = re.compile(r"Blackfeet|Chippewa Cree|Northern Cheyenne|Salish|Crow Agency|"
                          r"Assiniboine|Starr School|Busby|Muddy Cluster|Birney|Ashland Northern", re.I)
EPA_EXTRA = {"MT0031835", "MTG589006", "MT0021890", "MT0030571", "MT0030597", "MTG589502", "MTG589503", "MTG589301",
             "MT0029017", "MT0030554", "MT0022993", "MT0029106", "MTG589201", "MTG589204"}
NAMES = {"MT0000442": "City of Great Falls", "MT0021920": "City of Great Falls",
         "MT0000876": "City of Glendive", "MT0021628": "City of Glendive",
         "MT0020168": "Missoula County (Lolo Water and Sewer District plant)",
         "MT0021733": "Dawson County (West Glendive)", "MT0021750": "Stillwater County",
         "MT0022012": "Butte-Silver Bow (consolidated city and county)",
         "MT0030759": "City of Hardin", "MT0030767": "City of Hardin",
         "MT0022993": "U.S. Bureau of Reclamation, Yellowtail Dam", "MT0029106": "U.S. Bureau of Reclamation, Yellowtail Dam",
         "MTG589201": "U.S. Bureau of Reclamation, Yellowtail Dam",
         "MT0030601": "National Park Service, Glacier National Park", "MTX000171": "National Park Service, Glacier National Park",
         "MTG580004": "Montana State Hospital", "MTG581004": "Montana State Hospital",
         "MTX000138": "Montana Department of Transportation", "MTX000330": "Montana Department of Transportation",
         "MTX000231": "Anaconda-Deer Lodge County", "MTX000338": "Anaconda-Deer Lodge County",
         "MTG589003": "Blackfeet Tribe (water and utilities)", "MTG589101": "Blackfeet Tribe (water and utilities)",
         "MTG589105": "Blackfeet Tribe (water and utilities)", "MT0031835": "Blackfeet Tribe (water and utilities)",
         "MTG589020": "Blackfeet Tribe (water and utilities)",
         "MTG589005": "Chippewa Cree Tribe (utilities and water resources)",
         "MTG589008": "Chippewa Cree Tribe (utilities and water resources)",
         "MTG589701": "Chippewa Cree Tribe (utilities and water resources)",
         "MTG589702": "Chippewa Cree Tribe (utilities and water resources)",
         "MTG589703": "Chippewa Cree Tribe (utilities and water resources)",
         "MTG589704": "Chippewa Cree Tribe (utilities and water resources)",
         "MTG589705": "Chippewa Cree Tribe (utilities and water resources)",
         "MTG589706": "Chippewa Cree Tribe (utilities and water resources)",
         "MT0029360": "Northern Cheyenne Utilities Commission", "MTG589601": "Northern Cheyenne Utilities Commission",
         "MTG589602": "Northern Cheyenne Utilities Commission", "MTG589603": "Northern Cheyenne Utilities Commission",
         "MTG589604": "Northern Cheyenne Utilities Commission",
         "MTG589009": "Crow Tribe (Crow Agency lagoon)", "MTG589204": "Fort Smith wastewater lagoon",
         "MTG589502": "Town of Brockton", "MTG589503": "Town of Brockton",
         "MT0030554": "Woodcock Home Addition (Fort Peck Reservation housing)",
         "MT0020397": "Bigfork County Water and Sewer District", "MT0021474": "City of Ronan",
         "MT0030333": "City of Troy", "MTG581038": "City of Troy",
         "MTG589002": "Catholic Diocese of Great Falls", "MT0028118": "City of Livingston",
         "MT0021849": "City of Sidney", "MT0021431": "CCCS, Inc. (Montana Behavioral Health plant, Galen)",
         "MTX000178": "Integrated Water, Inc.", "MT0000221": "Lincoln County Port Authority"}
FORMS = {"MT0022012": "city", "MT0020168": "county", "MT0029360": "tribal", "MTG589204": None,
         "MT0029017": "tribal", "MT0030554": "tribal", "MTG589009": "tribal", "MTG589002": "institution",
         "MT0020460": "special district", "MT0031861": "business or industrial", "MT0023388": "state facility",
         "MTX000238": "special district", "MTX000167": "campground or resort", "MT0020516": "town",
         "MTX000190": "homeowners' association", "MTX000214": "homeowners' association",
         "MT0030571": "city", "MTG589006": "town", "MT0021890": "town", "MTX000157": "homeowners' association",
         "MTX000287": "homeowners' association", "MTX000174": "homeowners' association",
         "MTX000243": None}
ROW_IDS = {"MTG589204": "mt-fort-smith-lagoon"}
NOTES = {"MT0029017": "The Salish and Kootenai Housing Authority is the Confederated Salish and Kootenai Tribes' housing body.",
         "MTG589204": "EPA names the facility only; the body that holds the coverage is not stated.",
         "MTX000178": "EPA records the permittee as a company with a person's name before it; the person is not named here.",
         "MT0020397": "DEQ's MPDES index names the city of Bigfork and EPA the county water and sewer district: the legal "
                      "permittee was not checked (expansion research, 2026-11-09)."}
SHORT = {}


def channel(row: dict) -> str:
    s = LAW
    if row.get("legal_form") not in M.PUBLIC_FORMS and row.get("legal_form"):
        s += PRIVATE
    if any(p.startswith("MTX") for p in row["npdes_permits"]):
        s += (" Its MTX permit is a Montana Ground Water Pollution Control System permit by DEQ's numbering: its "
              "discharge goes to ground water, not to a stream.")
    return s


def main(argv: list[str]) -> int:
    new, counts = M.build_rows("MT", checked=CHECKED, channel=channel, epa_channel=lambda r: EPA, names=NAMES,
                               forms={k: v for k, v in FORMS.items() if v}, tribal_words=TRIBAL_WORDS,
                               epa_issued_extra=EPA_EXTRA, notes_by_permit=NOTES, short_names=SHORT, row_ids=ROW_IDS)
    for r in new:
        if any(p in FORMS and FORMS[p] is None for p in r["npdes_permits"]):
            r.pop("legal_form", None)
    M.write("MT", new, "--dry-run" in argv)
    print(M.report("MT", new, counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
