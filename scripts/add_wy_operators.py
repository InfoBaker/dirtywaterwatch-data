"""Wyoming operator rows for data/dischargers.json: one row per permittee, every Wyoming permit in exactly one row.

Usage: pipeline/.venv/bin/python -I scripts/add_wy_operators.py [--dry-run]

The shared rules are in scripts/mountain_operator_rows.py. Wyoming:
  - 92 permits in EPA's plant table (data/outfalls-plants-us.json, file of 2026-11-01), 9 research rows, the 18 major
    permits of the federal seed, 15 private candidates and 4 public-by-name rows (some outside the plant table). No
    combined sewer permit.
  - Permit prefixes: WY0 individual WYPDES permits; WYG589 EPA Region 8's lagoon general permit in Indian country (the
    Wind River Reservation's lagoons); WYR a storm-water coverage (Laramie's plant site: not a sewage outfall, said in
    the row's notes).
  - EPA-issued: EPA Region 8 issues the permits on tribal land and lands of exclusive federal jurisdiction in Wyoming.
    Filed as EPA's: the WYG589 coverages (Fort Washakie, Great Plains, St. Stephens, Arapahoe, Mill Creek, Ethete,
    Beaver Creek). Yellowstone's Canyon Village plant (WY0023442) lies on land of exclusive federal jurisdiction, but its
    permit number is a state one: left with the state's channel and the question in its notes.
  - The channel: WDEQ's sanitary sewer overflow page (read 2026-11-14): owners and operators of municipal, state,
    federal, regional, industrial and private collection or treatment systems report an overflow verbally within 24
    hours of becoming aware of it and in writing within five days; WDEQ publishes no list, and its spills portal's
    search is behind a staff login.
Idempotent: a rerun replaces the rows it wrote (state WY, source_areas ["wy"]) where they stood.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mountain_operator_rows as M  # noqa: E402

CHECKED = "2026-11-14"
LAW = ("Wyoming puts the report on the system's owner or operator and the recipient is the state: the Department of "
       "Environmental Quality's sanitary sewer overflow instructions require owners and operators of municipal, state, "
       "federal, regional, industrial and private collection or treatment systems to report an overflow verbally within "
       "24 hours of becoming aware of it and in writing within five days. WDEQ publishes no list of the reports (its "
       "spills portal's searches are behind a staff login), and no duty to tell the public was found. The operator's "
       "own pages were not searched individually.")
EPA = ("A permit EPA Region 8 issues (the Wind River Reservation, where the state program does not apply): the permit's "
       "24-hour and five-day noncompliance reports go to EPA (40 CFR 122.41(l)(6)), which publishes those filed "
       "electronically in its sewer overflow tables (" + M.ECHO + "); the extracts of 2026-11-14 hold no Wyoming report, "
       "and list the Fort Washakie lagoon's collection system. No public notice duty was found.")
PRIVATE = " The instructions bind a private system as they bind a public one."
TRIBAL_WORDS = re.compile(r"Fort Washakie|Ethete|Arapaho|St\. Stephens|Wind River Reservation", re.I)
NAMES = {"WY0022381": "Cheyenne Board of Public Utilities", "WY0022934": "Cheyenne Board of Public Utilities",
         "WY0022209": "City of Laramie", "WYR001500": "City of Laramie",
         "WY0020010": "City of Sheridan", "WY0035661": "City of Sheridan",
         "WY0020028": "Town of Basin", "WY0020320": "Kemmerer-Diamondville Joint Powers Board",
         "WY0020931": "U.S. Forest Service, Bighorn National Forest (Burgess Junction)",
         "WY0023442": "National Park Service, Yellowstone National Park (Canyon Village)",
         "WY0043745": "Wyoming Department of Transportation (Powder River rest area)",
         "WY0032522": "Northeast Wyoming Regional Airport",
         "WY0034606": "Town of Burlington", "WY0096512": "Town of Burlington",
         "WY0036153": "TA Operating LLC (TravelCenters of America)",
         "WYG589101": "Wind River Reservation lagoons (EPA lagoon general permit)",
         "WYG589102": "Wind River Reservation lagoons (EPA lagoon general permit)",
         "WYG589103": "St. Stephens Indian Mission, Inc.",
         "WYG589104": "Wind River Reservation lagoons (EPA lagoon general permit)",
         "WYG589105": "Wind River Reservation lagoons (EPA lagoon general permit)",
         "WYG589106": "Wind River Reservation lagoons (EPA lagoon general permit)",
         "WYG589107": "Wind River Reservation lagoons (EPA lagoon general permit)",
         "WY0052451": "The Viking Resort LLC (Trailhead Lodge)", "WY0056006": "City of Douglas"}
FORMS = {"WY0022381": "authority", "WY0022934": "authority", "WY0020320": "authority", "WY0032522": "authority",
         "WY0020028": "town", "WY0020061": "town", "WY0020435": "town", "WY0020281": "town",
         "WY0021954": "mobile-home park", "WY0056308": "special district", "WYG589103": "institution",
         "WYG589101": "tribal", "WY0022071": "special district", "WY0025992": "special district",
         "WY0097036": "business or industrial"}
ROW_IDS = {"WYG589101": "wy-wind-river-reservation-lagoons"}
NOTES = {"WYR001500": "WYR001500 is a storm-water coverage at the plant site, not a sewage outfall.",
         "WY0035661": "WY0035661 is the city's raw water intake (EPA lists it with a sewage code); not a sewage plant.",
         "WY0023442": ("Yellowstone is land of exclusive federal jurisdiction, where EPA issues NPDES permits; this "
                       "permit's number is a state one, so the issuing authority was not settled."),
         "WYG589101": ("The coverages EPA lists under its lagoon general permit for Indian country on the Wind River "
                       "Reservation (Fort Washakie, Great Plains, Arapahoe industrial park, Mill Creek, Ethete, Beaver "
                       "Creek); EPA's records name the lagoons, not the tribal or community body that holds each."),
         "WY0056006": ("EPA records this permit's permittee as \"Douglas, Town of\" (Douglas is a city) and its facility "
                       "under a name that reads as a person's, which is not shown; filed with the city's row."),
         "WY0021954": "EPA records the facility as Country Meadows; the permittee is CV Laramie MHP, LLC."}
KINDS = {}


def channel(row: dict) -> str:
    s = LAW
    if row.get("legal_form") not in M.PUBLIC_FORMS and row.get("legal_form"):
        s += PRIVATE
    return s


def main(argv: list[str]) -> int:
    new, counts = M.build_rows("WY", checked=CHECKED, channel=channel, epa_channel=lambda r: EPA, names=NAMES,
                               forms=FORMS, tribal_words=TRIBAL_WORDS, epa_issued_extra=set(),
                               notes_by_permit=NOTES, kinds=KINDS, row_ids=ROW_IDS)
    M.write("WY", new, "--dry-run" in argv)
    print(M.report("WY", new, counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
