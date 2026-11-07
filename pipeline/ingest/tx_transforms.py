"""Texas hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

tx_tceq_record: TCEQ's "Sanitary Sewer Overflows (SSO)" table on data.texas.gov (data/sources/tx-tceq-sso-opendata.yaml,
Socrata 8kc5-95uk): one row per incident reported to a TCEQ regional office since September 2010 (30 TAC 305.125(9),
319.301-319.303). The rows give dates only (start, end, received; every value is midnight), a volume, the cause, the
source of the spill, the TCEQ region, the county, the regulated entity (RN) and its permits, and often a receiving water;
no coordinates and no time of day. The table is refreshed in batches months apart.
  - Zone: dates only, so no clock time is converted; each record still says the zone its county keeps
    (raw.timezone and raw.timezone_note): Mountain time in El Paso and Hudspeth counties, Central time in the other 252
    (49 CFR 71.9 and 71.10: the boundary between the Central and Mountain zones in Texas follows the eastern lines of
    Hudspeth and El Paso counties).
  - Placement (owner default 2026-11-07, docs/state-builder-brief-wave3.md in the site repository): a row naming a water
    body goes to that water by its name (the status build's name matching, against the water records built from the
    national and the state's receiving-water lists); every other row is a report with no water, listed with its county
    (raw.county). raw._placement "named_water_only" tells build/provisional_outfalls.py never to geolocate the row from
    its text and never to stand the operator's plant point in for it. A model pass could later read a segment number or a
    misspelt name; a model never supplies a place or a colour.
  - Receiving-water text: TCEQ's wordings for no water given ("NOT PROVIDED", "NO WATER BODY PROVIDED", "NONE LISTED",
    "NOT SPECIFIED", "N/A" ...) and a bare number (a TCEQ segment number, "613") name no water: waterbody_text is null and
    the words stay in raw._water_text_as_given (and in raw.row). The river_segment column, when not 0, is TCEQ's
    classified segment, kept in raw._tceq_segment. A statement that the spill was contained or stayed on the ground
    stays as the text, which the status build reads as reaching no water.
  - Permits: list_of_permits holds TCEQ's own ids ("WASTEWATER-PERMIT-WQ0011406001"), stormwater authorisations and,
    for some entities, the federal id ("WASTEWATER-EPA ID-TX0125288"). npdes_permit is the row's own federal id, else the
    one federal id data/reference/tx-tceq-permits.json gives for its WQ permit or its regulated entity (rows of the table
    that list both, and EPA's Facility Registry links). raw.state_permits keeps the WQ ids, raw._permit_basis how the
    federal id was found. discharger_id is the data/dischargers.json row holding the entity (tceq_entities) or the
    permit.
  - event_type sso (the table is TCEQ's sewer overflow list), except a row whose material is not wastewater (rock, plain
    water): unknown, with the label in raw._source_type. status: ended with an end date, else unknown (TCEQ's OPEN,
    CLOSED and REFERRED are the incident file's, kept in raw.row.status_code). A volume in gallons is volume_gal; any
    other unit (pounds, cubic yards, barrels) stays text.
  - Privacy: only the safe fields are requested; customer_number, incident_action and incident_comment are not. The free
    text (source, receiving_water_body, incident_description) gets the strict scrub (free_text_scrub: strict): emails,
    phones, staff and residents' names, owners' names and every house number cut; the name redactor and the blocklist run
    over every record.

tx_beachwatch_record: Texas Beach Watch (data/sources/tx-glo-beach-watch.yaml), the Texas General Land Office's layer of
coastal monitoring stations, each with its latest enterococcus result and the program's level: Low, Medium or High.
  - High: the program's advisory level (enterococcus above 104 MPN/100 ml, "An advisory for this beach is
    recommended"; the local government posts it):
    beach_advisory, advisory_active, as of the sample date, while the layer shows it (history.confirm_while_listed).
  - Medium (35 to 104 MPN/100 ml): the program's elevated level, not an advisory: beach_advisory, status unknown, raw._agency_label_only, which
    the status build shows with this site's caution from the sample date, never as the authority's advisory.
  - Low rows are left out by the block's filter (a sample, no statement).
"""
from __future__ import annotations

import json
import re

from common import DATA_DIR, NAME_REMOVED, scrub_discharger
from ingest.generic import fieldmap as F

MOUNTAIN_COUNTIES = {"EL PASO", "HUDSPETH"}
ZONE_NOTE = "{zone} time ({county}; 49 CFR 71.9-71.10); dates only"
PLACEMENT = ("TCEQ's table gives no coordinates: a report is placed only on the water it names; a report naming none is "
             "listed with its county and is never placed at the plant or geolocated from its text")
# TCEQ's wordings for "no receiving water given" (and their typing slips); a bare number is a segment number, not a name
NOT_GIVEN = re.compile(
    r"^\s*(?:not\s*provide\w*|no\s+water\s*bod(?:y|ies)\s+(?:provided|listed|given|identified|noted|reported)|"
    r"none\s*(?:listed|lised|provided|given|identified|noted|reported|specified|stated)?(?:\s+in\s+report)?|"
    r"not\s+(?:specified|applicable|listed|given|identified|reported|stated|known)|n\s*/?\s*a|unknown|unk|"
    r"no\s+info\w*|blank|-+|0+)\W*$", re.I)
SEGMENT_ONLY = re.compile(r"^\s*(?:segment\s*(?:no\.?|number|#)?\s*)?\d{3,4}[a-z]{0,2}\s*\.?\s*$", re.I)
NOT_SEWAGE_MATERIAL = re.compile(r"^\s*(?:rock|water\s*\(h2o\)|water)\s*$", re.I)
EPA_ID = re.compile(r"WASTEWATER-EPA ID-(TX\d{7})")
WQ_ID = re.compile(r"WASTEWATER-PERMIT-(WQ\d{10})")
CROSSWALK = DATA_DIR / "reference" / "tx-tceq-permits.json"
# words that make an entity name a facility's in TCEQ's spelling, beyond common.OPERATOR_WORDS ("BOB DERRINGTON WWP" is
# Odessa's plant, not a person)
FACILITY_WORDS = re.compile(r"\b(?:WWP|WRP|WWS|WCID|FWSD|SUD|PUD|WSC|MUD|PLANT|SYSTEM|STATION|LIFT|COLLECTION|"
                            r"LAGOON|PONDS?|RV|PARK|MARINA)\b", re.I)


def county_name(raw: str) -> str | None:
    c = F.clean(raw)
    if not c:
        return None
    return " ".join(w if w.lower() in ("de", "la") and i else w.capitalize() for i, w in enumerate(c.lower().split())) \
        .replace("Mcl", "McL").replace("Mcc", "McC").replace("Mcm", "McM").replace("Dewitt", "DeWitt") + " County"


def zone_of(county: str | None) -> str:
    return "America/Denver" if F.clean(county).upper() in MOUNTAIN_COUNTIES else "America/Chicago"


def _lookups(ctx: F.Ctx) -> dict:
    """The permit crosswalk and the operator rows, read once per run."""
    if "tx" not in ctx.extra:
        x = json.loads(CROSSWALK.read_text()) if CROSSWALK.exists() else {}
        by_rn, by_permit, names = {}, {}, {}
        dis = DATA_DIR / "dischargers.json"
        for r in json.loads(dis.read_text()) if dis.exists() else []:
            if r.get("state") != "TX":
                continue
            names[r["id"]] = r.get("name")
            for rn in r.get("tceq_entities") or []:
                by_rn[rn] = r["id"]
            for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])]:
                if p:
                    by_permit.setdefault(p, r["id"])
        ctx.extra["tx"] = {"wq": x.get("wq_to_npdes") or {}, "rn": x.get("rn_to_npdes") or {}, "by_rn": by_rn,
                           "by_permit": by_permit, "names": names}
    return ctx.extra["tx"]


def federal_permit(row: dict, look: dict) -> tuple[str | None, str | None, list[str]]:
    """(npdes permit, how it was found, the WQ ids) for a row."""
    lst = F.clean(row.get("list_of_permits"))
    own = list(dict.fromkeys(EPA_ID.findall(lst)))
    wq = list(dict.fromkeys(WQ_ID.findall(lst)))
    if len(own) == 1:
        return own[0], "the row's own federal id (list_of_permits)", wq
    if len(own) > 1:
        return own[0], f"the first of the row's {len(own)} federal ids (list_of_permits)", wq
    via = {t for q in wq for t in look["wq"].get(q, [])}
    if len(via) == 1:
        return next(iter(via)), "the federal id of its WQ permit (TCEQ and EPA crosswalk)", wq
    rn = F.clean(row.get("regulated_entity_number")).upper()
    via_rn = set(look["rn"].get(rn, []))
    if len(via_rn) == 1 and not via:
        return next(iter(via_rn)), "the federal id of its regulated entity (TCEQ and EPA crosswalk)", wq
    if via or len(via_rn) > 1:
        return None, "several federal ids for its permits or entity: none chosen", wq
    return None, None, wq


@F.hook
def tx_tceq_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    county = county_name(row.get("county"))
    zone = zone_of(row.get("county"))
    if county:
        notes["county"] = county
    notes["state"] = "TX"
    notes["timezone"] = zone
    notes["timezone_note"] = ZONE_NOTE.format(zone="Mountain" if zone == "America/Denver" else "Central",
                                              county=county or "county not given")
    notes["_placement"] = "named_water_only"       # the rule: PLACEMENT (in the feed's meta, placement_rule)
    seg = F.clean(row.get("river_segment"))
    if seg and seg.strip("0"):
        notes["_tceq_segment"] = seg
    # the receiving water: TCEQ's "none given" wordings and bare segment numbers name no water
    text = F.clean(rec.get("waterbody_text"))
    if text and (NOT_GIVEN.match(text) or SEGMENT_ONLY.match(text)):
        notes["_water_text_as_given"] = text
        notes["_water_text_why"] = ("TCEQ's field gives a segment number, not a name" if SEGMENT_ONLY.match(text)
                                        else "TCEQ's field says no receiving water was given")
        rec["waterbody_text"] = None
    # the operator
    look = _lookups(ctx)
    permit, basis, wq = federal_permit(row, look)
    rec["npdes_permit"] = permit
    if basis:
        notes["_permit_basis"] = basis
    if wq:
        notes["state_permits"] = wq
    rn = F.clean(row.get("regulated_entity_number")).upper()
    did = look["by_rn"].get(rn) or (look["by_permit"].get(permit) if permit else None)
    rec["discharger_id"] = did
    if did:
        notes["_discharger_basis"] = ("its TCEQ regulated entity" if rn in look["by_rn"]
                                      else "the operator row holding its federal permit")
        if look["names"].get(did):
            rec["discharger_name"] = look["names"][did]     # the operator; the entity stays in raw.row
    # an entity name that is only a person's (a small private plant filed under its owner) leaves raw.row too, not
    # only discharger_name (common.scrub_discharger clears that one)
    ent = F.clean(row.get("regulated_entity_name"))
    if ent and not FACILITY_WORDS.search(ent) \
            and scrub_discharger({"discharger_name": ent})["discharger_name"] == NAME_REMOVED:
        notes["row"] = {**row, "regulated_entity_name": NAME_REMOVED}
        notes["_entity_name_removed"] = "the entity's name reads as a person's"
        if rec.get("discharger_name") == ent:
            rec["discharger_name"] = NAME_REMOVED
    # the kind of report
    mat = F.clean(row.get("material_type"))
    if mat and NOT_SEWAGE_MATERIAL.match(mat):
        rec["event_type"] = "unknown"
        notes["_source_type"] = mat
    # a volume in another unit than gallons stays text
    unit = F.clean(row.get("amount_unit")).upper()
    if rec.get("volume_gal") is not None and unit != "GALLONS":
        rec["volume_gal"] = None
        notes["_volume_unit"] = unit or "no unit given"


# ---------------------------------------------------------------- Texas Beach Watch

HIGH_RULE = ("Texas Beach Watch (texasbeachwatch.com, read 2026-11-07): enterococcus above 104 MPN/100 ml is the "
             "program's High level: \u201cAn advisory for this beach is recommended\u201d")
MEDIUM_RULE = ("Texas Beach Watch (texasbeachwatch.com, read 2026-11-07): enterococcus between 35 and 104 MPN/100 ml is the "
               "program's Medium level; the program recommends an advisory only at High")


@F.hook
def tx_beachwatch_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    level = F.clean(row.get("Advisory")).capitalize()
    meas = F.clean(row.get("Measurement"))
    county = F.clean(row.get("chrCountyName"))
    if county:
        notes["county"] = county
    notes["state"] = "TX"
    notes["_level"] = level
    if level == "High":
        rec["event_type"], rec["status"] = "beach_advisory", "advisory_active"
        rec["advice_text"] = (f"Texas Beach Watch level High (advisory recommended)"
                              + (f": enterococcus {meas} in the sample" if meas else ""))
        notes["_alert_basis"] = HIGH_RULE
    elif level == "Medium":
        rec["event_type"], rec["status"] = "beach_advisory", "unknown"
        rec["advice_text"] = (f"Texas Beach Watch's label: “Medium”"
                              + (f" (enterococcus {meas} in the sample)" if meas else "")
                              + "; the program recommends no advisory at this level")
        notes["_alert_basis"] = MEDIUM_RULE
        notes["_agency_label_only"] = True
        notes["_agency_label"] = "Medium"
    else:
        rec["event_type"], rec["status"] = "unknown", "unknown"
        notes["_sample_only"] = True
