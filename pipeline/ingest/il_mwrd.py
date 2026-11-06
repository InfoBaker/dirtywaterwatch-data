"""Metropolitan Water Reclamation District of Greater Chicago (MWRD): shared tables for the Illinois feeds and the
outfall registry (a helper, not a feed: ingest/il_mwrd_possible_cso.py, il_mwrd_lake_reversals.py and
scripts/add_il_mwrd_outfalls.py import it).

- CSO_POINTS: MWRD's public "CSO Points" layer (441 combined sewer outfalls in Cook County, 51 owners: the City of
  Chicago 214, MWRD 51, Evanston 16 ...; each with its owner, the town, MWRD's waterway reach, the TARP drop-shaft
  connection that keys MWRD's CSO Event Synopsis Report, a location such as "Pratt Ave (E)" and whether MWRD monitors
  it). Fields requested: the safe fields below; no field names a person.
- REACH_WATERS: MWRD's waterway reach labels ("NSC Lower (NSWRP)", "Cal Sag Ch") to the water's name as NHD gives it.
- DIVERSIONS: the three structures through which the Chicago Area Waterway System is let back into Lake Michigan in
  severe storms (the Wilmette gate, the Chicago River Controlling Works, O'Brien Lock and Dam), with the reversal
  table's column for each; GATE_IDS: each one's row in the outfall registry (permit and outfall id), which the
  reversal and possible-diversion records carry.
- OWNER_PERMITS: an owner on the layer to its combined sewer permit (EPA's CSO inventory, data/outfalls-us.json; Forest
  View's IL0020800 from EPA's discharge-point records, which type it private):
  the City of Chicago's IL0045012, MWRD's plant permits, the suburbs' general-permit coverages (ILM5800xx) and the
  communities with their own permits.
"""
from __future__ import annotations

import re

CSO_POINTS_URL = "https://services.arcgis.com/R2OqRHzOVTbwcOgY/arcgis/rest/services/CSO_Points/FeatureServer/0"
CSO_POINTS_FIELDS = ["OBJECTID", "OWNER", "OUTFALL_CITY", "WATERWAY_REACH", "TARP_CONNECTION", "LOCATION", "M_OR_U"]
CSO_HUB_URL = ("https://mwrd.org/community-action/you-can-help-prevent-flooding-and-protect-water-quality/"
               "combined-sewer-overflow-notification")
CREDIT = "Metropolitan Water Reclamation District of Greater Chicago"

REACH_WATERS = {
    "nbcr lower": "North Branch Chicago River", "nbcr upper": "North Branch Chicago River",
    "west fork nbcr upper": "West Fork North Branch Chicago River",
    "sb chicago r": "South Branch Chicago River", "sf sb chicago r": "South Fork South Branch Chicago River",
    "chicago r": "Chicago River",
    "desplaines upper": "Des Plaines River", "desplaines middle": "Des Plaines River",
    "desplaines lower": "Des Plaines River",
    "cssc upper": "Chicago Sanitary and Ship Canal", "cssc lower": "Chicago Sanitary and Ship Canal",
    "nsc upper": "North Shore Channel", "nsc lower": "North Shore Channel",
    "little cal r": "Little Calumet River", "cal r": "Calumet River", "grand cal r": "Grand Calumet River",
    "cal sag ch": "Calumet Sag Channel", "salt cr": "Salt Creek", "weller cr": "Weller Creek",
    "addison cr": "Addison Creek", "deer creek": "Deer Creek", "feehanville ditch": "Feehanville Ditch",
    "cal union drainage ditch": "Calumet Union Drainage Ditch", "collateral channel": "Collateral Channel",
    "i and m canal": "Illinois and Michigan Canal",
}
LAKE = "Lake Michigan"
# the reversal structures: (pattern on the layer's location or TARP key, the reversal table's column, display name)
DIVERSIONS = [
    (re.compile(r"(?i)\bwilmette\s+gate\b|^wilmette$"), "Wilmette", "Wilmette gate (North Shore Channel)"),
    (re.compile(r"(?i)chicago\s+river\s+controlling\s+works|\bcrcw\b"), "CRCW", "Chicago River Controlling Works"),
    (re.compile(r"(?i)o'?\s*brien\s+lock"), "O'Brien Lock", "O'Brien Lock and Dam (Calumet River)"),
]
# the structures' points (MWRD's CSO Points layer, 2026-11-04), for the reversal records
DIVERSION_POINTS = {"Wilmette": (42.075959, -87.684557), "CRCW": (41.888471, -87.608273),
                    "O'Brien Lock": (41.654744, -87.569396)}
DIVERSION_WATERWAYS = {"Wilmette": "North Shore Channel", "CRCW": "Chicago River", "O'Brien Lock": "Calumet River"}
# each structure's row in the outfall registry (data/outfalls-il.json, scripts/add_il_mwrd_outfalls.py gate_rows): the
# permit it is filed under and its outfall id, the layer's TARP key. EPA's CSO inventory lists none of the three, and no
# permit lists them as outfalls: a structure is filed under the MWRD water reclamation plant permit whose EPA row lies
# nearest it, the rule the script uses for MWRD's own outfalls (Wilmette: the Terrence J. O'Brien plant's outfall 101 at
# the Wilmette pumping station, 96 m; CRCW: the Stickney plant's outfall 142, 8.1 km; O'Brien Lock: the Calumet plant's
# outfall 152, 2.6 km). The reversal and possible-diversion records carry these, so each ties to its structure's row.
GATE_IDS = {"Wilmette": ("IL0028088", "Wilmette Gate"), "CRCW": ("IL0028053", "Chicago River Controlling Works"),
            "O'Brien Lock": ("IL0028061", "OBrien Lock and Dam")}
GATE_NOTE = ("a lake reversal structure, not a combined sewer outfall: in severe storms MWRD opens it and the Chicago "
             "Area Waterway System, which takes the area's combined sewer overflows, flows back into Lake Michigan. A "
             "reversal is a discharge of river water, with the combined sewage and stormwater in it, to the lake "
             "(MWRD's Reversals to Lake Michigan table)")
# MWRD's own outfalls: the permit of the plant whose service area holds them (the nearest of EPA's rows decides
# between these; scripts/add_il_mwrd_outfalls.py)
MWRD_PERMITS = ["IL0028053", "IL0028061", "IL0028088", "IL0047741", "IL0028070"]
OWNER_PERMITS = {
    "chicago": ["IL0045012"], "mwrd": MWRD_PERMITS,
    "evanston": ["ILM580002"], "melrose park": ["ILM580003"], "lyons": ["ILM580004"], "morton grove": ["ILM580005"],
    "arlington heights": ["ILM580006"], "riverdale": ["ILM580007"], "lagrange park": ["ILM580008"],
    "la grange park": ["ILM580008"], "lagrange": ["ILM580009"], "la grange": ["ILM580009"],
    "south holland": ["ILM580010"], "dixmoor": ["ILM580011"], "wilmette": ["ILM580012"],
    "schiller park": ["ILM580013"], "park ridge": ["ILM580014"], "riverside": ["ILM580015"],
    "calumet park": ["ILM580016"], "dolton": ["ILM580017"], "burnham": ["ILM580018"], "forest park": ["ILM580019"],
    "harvey": ["ILM580020"], "river grove": ["ILM580021"], "maywood": ["ILM580022"], "stickney": ["ILM580023"],
    "river forest": ["ILM580024"], "calumet city": ["ILM580025"], "des plaines": ["ILM580026"],
    "lansing": ["ILM580027"], "markham": ["ILM580028"], "franklin park": ["ILM580029"],
    "north riverside": ["ILM580030"], "blue island": ["ILM580031"], "brookfield": ["ILM580032"],
    "summit": ["ILM580033"], "lincolnwood": ["ILM580034"], "niles": ["ILM580035"], "skokie": ["ILM580036"],
    "posen": ["ILM580037"], "forest view": ["IL0020800"], "mt prospect": ["IL0052400"], "mount prospect": ["IL0052400"],
    "western springs": ["IL0045039"], "golf": ["IL0072389"], "phoenix": ["IL0072834"], "lemont": ["IL0039551"],
}


def _key(s: str | None) -> str:
    s = (s or "").lower().replace("&", " and ").replace(".", " ")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())


def reach_water(reach: str | None) -> str | None:
    """MWRD's reach label -> the water's name ('NSC Lower (NSWRP)' -> 'North Shore Channel'); None when unknown."""
    k = _key(re.sub(r"\([^)]*\)", " ", reach or ""))
    if k in REACH_WATERS:
        return REACH_WATERS[k]
    k2 = re.sub(r"\s+(north|south|upper|lower|middle)$", "", k)
    return REACH_WATERS.get(k2)


def diversion(*texts) -> tuple[str, str] | None:
    """(reversal table column, display name) when a location or TARP key names a reversal structure."""
    for t in texts:
        for pat, col, name in DIVERSIONS:
            if t and pat.search(str(t)):
                return col, name
    return None


def gate_ids(column: str | None) -> tuple[str | None, str | None]:
    """(permit, outfall id) of a reversal structure's registry row by the reversal table's column; (None, None)."""
    return GATE_IDS.get(column or "", (None, None))


def owners(owner: str | None) -> list[str]:
    """'Chicago / Calumet Park' -> ['chicago', 'calumet park']; 'Mt. Prospect' -> ['mt prospect']."""
    return [_key(p) for p in re.split(r"\s*/\s*", owner or "") if _key(p)]


def owner_permits(owner: str | None) -> list[str]:
    """The permits of the first owner the layer names that has one (a shared outfall goes to its first owner)."""
    for o in owners(owner):
        if o in OWNER_PERMITS:
            return OWNER_PERMITS[o]
    return []
