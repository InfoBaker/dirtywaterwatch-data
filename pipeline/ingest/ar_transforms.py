"""Arkansas hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

ar_deq_record: the Division of Environmental Quality's Reported Noncompliance Incident Data
(data/sources/ar-deq-overflow-incidents.yaml; fetched by ingest/ar_deq_overflow_incidents.py, an HTML form search):
every sanitary sewer overflow, bypass, upset and unpermitted discharge a permittee reports on DEQ's 24-hour online
forms. Columns read: permit, facility, location, the days the overflow started and stopped, the day DEQ received the
report, volume (gallons), impact, type, environmental damage, and the detail row's Web Confirmation Number, cause,
action taken and type of overflow. The filer's comments are never read. Dates only; no coordinates; no receiving-water
field; no county.
  - Law: DEQ's incident page, quoting the NPDES permits' Part II: notice "within 24 hours of becoming aware of the
    circumstances" and, in most cases, a five-day written report, for "Any Sanitary Sewer Overflow (SSO), no matter how
    small", any unanticipated bypass, any upset and "Any Unpermitted Discharge ... regardless of whether it reaches
    waters of the state". No duty to tell the public.
  - Zone: Arkansas is wholly Central time (49 CFR part 71, the Central zone); each date is midnight in America/Chicago (raw.time_zone).
  - Kind (DEQ's Type): "SSO" -> sso; "Bypass" and "Upset" -> plant_bypass; "Unpermitted Discharge" -> sso (a release
    from a collection or treatment system other than through a permitted outfall); a blank type -> sso (filed on the
    sewer overflow forms). DEQ's label stays in raw._source_type. The search also lists industrial permits: a report
    that is not an SSO, from a permit that is not one of EPA's Arkansas sewage plants (data/outfalls-plants-us.json),
    whose facility name reads as industrial (INDUSTRY) is not a sewage report: removed by ar_deq_not_sewage and
    counted in meta.duplicates.not_sewage (2026-11-14: 26 rows of paper and packaging mills, a gravel mine, a brick
    plant and other plants).
  - Times: started_at is Date Overflow Started, ended_at Date Overflow Stopped (both day precision; the stop is the
    filer's own: raw.ended_at_precision day), reported_at Date Reported (the day DEQ received the form, day
    precision). A report with no stop day has no end (status unknown, "end not confirmed"); the source is in
    data/rules.json unresolved.day_start_caution, so it carries the site's caution for 72 hours from the start of its
    day. published_at and source_updated_at stay null: the page's "Data current as of" day is the whole search's, not
    a record's (meta.data_current_as_of).
  - Reached water (DEQ's Impact): "SSO Reached Receiving Water (river,stream)" -> the filer says it reached water;
    "SSO Reached Public Land Only (ground)", "SSO Affected Private Property (ground)" and "Basement Backup" ->
    raw.reached_water false with DEQ's words as raw._no_water_reason (kept, listed, placed on no water); "SSO Occurred
    at Treatment Plant" and a blank impact leave the question open (err on safety). Any other impact text is the
    filer's own words, read as the water named.
  - Placement (rules only; raw._placement named_water_only): the search gives no coordinates and no receiving-water
    field, so a report is never placed at its permit's plant or outfalls and never geolocated from its location text.
    A report whose impact does not rule water out and whose location text names a water ("... into Gulpha Creek")
    carries that name as waterbody_text (WATER_NAME; "Unknown Creek", a ditch, a storm drain and a "tributary of X"
    name no water and are kept in raw._water_text_unused); the status build places it by name, county-aware.
  - County: the search gives none. raw.county is the county of the permit's treatment plant (EPA ICIS-NPDES point in
    data/outfalls-plants-us.json against data/reference/ar-counties.json), raw.county_basis saying so: it is used only
    to choose among same-named waters and to list the report. A permit with no plant point has no county, and its
    report's water name is kept in raw._water_text_unused rather than tied by name across the state.
  - Operator: npdes_permit is the permit when it is a federal id (AR plus seven characters: AR0, ARG, ARR); DEQ's state
    ids (ARU) stay in raw.state_permit. discharger_id is the data/dischargers.json row holding the permit.
  - Key: the Web Confirmation Number (a GUID per report, lower case). DEQ lists a few reports twice (the same number on
    two rows that differ only in a blank or zero volume): the copy is kept as id~2, duplicate_of the first.
  - Privacy: the comments are never read; location, cause, action taken and type of overflow pass the strict
    free-text scrub before anything is saved (house numbers, unit numbers, phones, e-mails, people's names). A
    report whose impact is private property or a basement backup keeps no location text at all
    (ingest/ar_deq_overflow_incidents.py privacy_cut, before the save): it is often a home.

ar_hab_record: DEQ's harmful algal bloom advisories (data/sources/ar-deq-hab-advisories.yaml): see ar_hab_* below.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from common import DATA_DIR
from ingest.generic import fieldmap as F

TZ_NAME = "America/Chicago"
TZ = ZoneInfo(TZ_NAME)
ZONE_NOTE = "Central time (Arkansas is wholly in the Central zone, 49 CFR part 71, the Central zone); dates only"
FEDERAL = re.compile(r"^AR[0-9GR][0-9A-Z]\d{5}$")
KINDS = [
    (re.compile(r"\bSSO\b", re.I), "sso"),
    (re.compile(r"\bunpermitted\b", re.I), "sso"),
    (re.compile(r"\b(bypass|upset)\b", re.I), "plant_bypass"),
]
REACHED = re.compile(r"reached\s+receiving\s+water", re.I)
LAND_ONLY = re.compile(r"reached\s+public\s+land\s+only|affected\s+private\s+property|basement\s+backup", re.I)
DEQ_IMPACTS = re.compile(r"^(SSO\s+Reached\s+Receiving\s+Water|SSO\s+Reached\s+Public\s+Land\s+Only|SSO\s+Affected\s+"
                         r"Private\s+Property|SSO\s+Occurred\s+at\s+Treatment\s+Plant|Basement\s+Backup)\b", re.I)
PRIVATE_IMPACT = re.compile(r"affected\s+private\s+property|basement\s+backup", re.I)
INDUSTRY = re.compile(r"\b(packaging|kraft|paper|weyerhaeuser|brick|mine|gravel|arms|armtec|steel|foods|pilgrim|"
                      r"tyson|lumber|chemical|refin\w*|plastics?)\b", re.I)
WATER_WORD = r"(?:Creek|River|Bayou|Lake|Branch|Slough|Reservoir|Fork|Run)"
CAP = r"(?:Mc[A-Z][a-z]+|St\.|[A-Z][a-z']+|De|La)"         # no full stop: a sentence ends the name
# no length cap: a long name is read whole and refused if too long to be one (MAX_NAME_WORDS), never cut short
WATER_NAME = re.compile(rf"\b((?:{CAP}[ \t]+)+{WATER_WORD}\b|Lake(?:[ \t]+{CAP})+\b)")
MAX_NAME_WORDS = 6
CAPS_RUN = re.compile(r"\b[A-Z][A-Z'.]+(?:[ \t]+[A-Z][A-Z'.]+)+\b")
WATER_WORD_RX = re.compile(rf"\b{WATER_WORD}\b", re.I)
STREET_AFTER = re.compile(r"^\s*(street|st|road|rd|drive|dr|lane|ln|avenue|ave|blvd|circle|cir|court|ct|parkway|pkwy|"
                          r"loop|cove|cv|terrace|way|place|pl|trail|trl|estates|subdivision|park|apartments|"
                          r"manhole|lift|pump)\b", re.I)
# words a filer writes before the name that are not part of it ("Storm Drain Arkansas River", "Into Hamestring Creek")
LEAD = {"into", "storm", "drain", "paved", "area", "yard", "culvert", "stream", "near", "then", "and", "the", "to",
        "a", "nearby", "ditch", "flowed", "entered", "street", "road", "lift", "station", "manhole", "from", "in",
        "at", "of", "on", "by", "reached", "went", "under", "bridge", "behind", "beside", "along", "across", "where",
        "which", "it", "overflow", "overflowed", "sewer", "line", "main", "s", "n", "e", "w", "dr", "rd", "ave",
        "hwy", "highway", "circle", "lane", "ln", "pump", "pumped", "spilled", "flowing", "flows", "towards",
        "toward", "unnamed", "an", "small", "nearest", "possible", "possibly"}
NO_NAME = re.compile(r"^(unknown|unkown|unnamed|un-named|no name)\b", re.I)
TRIB_BEFORE = re.compile(r"\btrib(?:utary|\.)?\s+(?:of|to)\s+(?:the\s+)?$", re.I)
STREETY = re.compile(r"\b(street|st|road|rd|drive|dr|lane|ln|avenue|ave|blvd|circle|cir|court|ct|parkway|pkwy|"
                     r"loop|cove|cv|terrace|way|place|pl|trail|trl)\.?\s*$", re.I)


# a chain of qualifiers written before a name ("upper little Sample Creek", "west fork of the"): all of it stays
QUALIFIER_BEFORE = re.compile(r"(?:\b(?:little|middle|upper|lower|big|east|west|north|south)(?:\s+(?:fork|branch|prong))?"
                              r"(?:\s+of(?:\s+the)?)?\s+)+$", re.I)
# words a sentence goes on with after a lake's name ("Lake Hamilton Due to rain"): not part of it
TRAIL_STOP = {"due", "used", "approximately", "approx", "was", "were", "from", "after", "near", "and", "the", "at",
              "on", "in", "to", "area", "about", "around", "with", "by"}


def _title(text: str) -> str:
    """An all-capitals text read as a name ("INTO TOWN CREEK" -> "Into Town Creek")."""
    t = text.title()
    t = re.sub(r"\bMc(\w)", lambda m: "Mc" + m.group(1).upper(), t)
    return re.sub(r"(?<=\w)'S\b", "'s", t)


def water_names(text: str) -> tuple[list[str], list[str]]:
    """(the waters a location text names, the water-like words it uses that name none). A text written in capitals is
    read as a title-cased one; a qualifier written in lower case before a name ("little Sample Creek") stays with it,
    since a qualified name is another water; a name is never cut to a shorter one."""
    text = text or ""
    if text and not re.search(r"[a-z]", text):
        text = _title(text)
    # a run of capitals inside mixed text ("overflow into TOWN CREEK") is read as a name when it holds a water word
    text = CAPS_RUN.sub(lambda m: _title(m.group(0)) if WATER_WORD_RX.search(m.group(0)) else m.group(0), text)
    names, unused = [], []
    for m in WATER_NAME.finditer(text):
        words = m.group(1).split()
        while words and (words[0].lower().strip(".,") in LEAD or words[0] == "St"):
            words.pop(0)
        if words and words[0].lower() == "lake":
            while len(words) > 2 and words[-1].lower().strip(".,") in TRAIL_STOP:
                words.pop()
        cand = " ".join(words).strip(" .,;")
        if len(words) > MAX_NAME_WORDS:
            unused.append(cand)                  # too long to be one name: refused, never shortened
            continue
        if STREET_AFTER.match(text[m.end():]) or (words and STREET_AFTER.match(words[-1])):
            unused.append(cand)                  # "Lake Lane", "Mill Creek Estates": a street or a place
            continue
        if len(words) < 2 and not cand.lower().startswith("lake "):
            if cand:
                unused.append(cand)
            continue
        if NO_NAME.match(cand) or STREETY.search(" ".join(words[:-1])):
            unused.append(cand)
            continue
        before = text[:m.start()] + " ".join(m.group(1).split()[:len(m.group(1).split()) - len(words)])
        if TRIB_BEFORE.search(before):
            unused.append(f"a tributary of {cand}")
            continue
        q = QUALIFIER_BEFORE.search(before.rstrip() + " ")
        if q:
            cand = re.sub(r"\bOf\b", "of", re.sub(r"\bThe\b", "the", _title(q.group(0).strip()))) + " " + cand
        names.append(cand)
    return list(dict.fromkeys(names)), list(dict.fromkeys(unused))


def kind_of(label: str) -> str:
    for rx, kind in KINDS:
        if rx.search(label or ""):
            return kind
    return "sso"            # a blank or new type: a report on the sewer overflow forms, never an uncoloured one


def _lookups(ctx: F.Ctx) -> dict:
    if "ar" not in ctx.extra:
        by_permit, names = {}, {}
        dis = DATA_DIR / "dischargers.json"
        for r in json.loads(dis.read_text()) if dis.exists() else []:
            if r.get("state") != "AR":
                continue
            names[r["id"]] = r.get("name")
            for p in [r.get("npdes_permit"), *(r.get("npdes_permits") or [])]:
                if p:
                    by_permit.setdefault(str(p).upper(), r["id"])
        plants: dict[str, tuple[float, float]] = {}
        pf = DATA_DIR / "outfalls-plants-us.json"
        doc = json.loads(pf.read_text()) if pf.exists() else {}
        for r in (doc.get("outfalls") if isinstance(doc, dict) else doc) or []:
            if r.get("state") == "AR" and r.get("npdes_permit"):
                p = str(r["npdes_permit"]).upper()
                if r.get("lat") is not None and r.get("lon") is not None and p not in plants:
                    plants[p] = (float(r["lat"]), float(r["lon"]))
                plants.setdefault(p, None)
        ctx.extra["ar"] = {"by_permit": by_permit, "names": names, "plants": plants, "counties": None,
                           "county_of": {}}
    return ctx.extra["ar"]


def plant_county(look: dict, permit: str) -> str | None:
    """The county holding the permit's plant point (data/reference/ar-counties.json), or None."""
    if permit in look["county_of"]:
        return look["county_of"][permit]
    pt = look["plants"].get(permit)
    out = None
    if pt:
        if look["counties"] is None:
            from shapely.geometry import shape
            path = DATA_DIR / "reference" / "ar-counties.json"
            doc = json.loads(path.read_text()) if path.exists() else {}
            look["counties"] = [(c["county"], shape(c["geometry"])) for c in doc.get("counties") or []]
        from shapely.geometry import Point
        p = Point(pt[1], pt[0])
        out = next((n for n, g in look["counties"] if g.covers(p)), None)
    look["county_of"][permit] = out
    return out


def _local_midnights(rec: dict) -> None:
    for k in ("started_at", "ended_at", "reported_at"):
        v = rec.get(k)
        if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            rec[k] = datetime(int(v[:4]), int(v[5:7]), int(v[8:10]), tzinfo=TZ).isoformat()


def clean_list(v: str) -> str | None:
    """DEQ's checkbox lists end each item with ';': "Grease; Debris;" -> "Grease; Debris"."""
    t = F.clean(v).strip(" ;")
    return re.sub(r"\s*;\s*", "; ", t) or None


@F.hook
def ar_deq_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    notes["state"] = "AR"
    notes["time_zone"] = TZ_NAME
    notes["timezone_note"] = ZONE_NOTE
    _local_midnights(rec)
    label = clean_list(row.get("incident_type")) or ""
    rec["event_type"] = kind_of(label)
    notes["_source_type"] = label or None
    if not label:
        notes["_type_basis"] = "DEQ's type is blank: read as a sewer overflow report (the 24-hour overflow forms)"
    rec["status"] = "ended" if rec.get("ended_at") else "unknown"
    if rec.get("ended_at"):
        notes["ended_at_precision"] = "day"
    for f in ("cause", "action_taken", "overflow_type", "environmental_damage"):
        v = clean_list(row.get(f))
        if v:
            notes[f"_{f}"] = v
    if re.search(r"\bpublic\s+notification\b", row.get("action_taken") or "", re.I):
        notes["_public_notification_ticked"] = True     # the filer's tick; no notice text or date is published
    # the operator
    permit = re.sub(r"\s+", "", F.clean(row.get("permit_no"))).upper()
    rec["npdes_permit"] = permit if FEDERAL.match(permit) else None
    if permit and not FEDERAL.match(permit):
        notes["state_permit"] = permit
    look = _lookups(ctx)
    did = look["by_permit"].get(permit) if permit else None
    rec["discharger_id"] = did
    if did:
        notes["_discharger_basis"] = "the operator row holding its permit"
        if look["names"].get(did):
            rec["discharger_name"] = look["names"][did]
    notes["_sewage_plant_permit"] = permit in look["plants"]
    county = plant_county(look, permit) if permit else None
    if county:
        notes["county"] = county
        notes["county_basis"] = ("the county of the permit's treatment plant (EPA ICIS-NPDES point); DEQ's report gives "
                                 "no county")
    # water: DEQ's impact first, then the water the location names
    notes["_placement"] = "named_water_only"
    impact = F.clean(row.get("impact"))
    notes["_impact"] = impact or None
    loc = F.clean(row.get("location"))
    names, unused = water_names(loc) if loc else ([], [])
    if impact and not DEQ_IMPACTS.match(impact):
        # the filer typed its own words in the impact box ("Village Creek"): the water it names
        # (only the water names it gives are used; the text itself passed the strict scrub before any save)
        n2, u2 = water_names(impact)
        names = list(dict.fromkeys(n2 + names))
        unused += u2
    if LAND_ONLY.search(impact or ""):
        notes["reached_water"] = False
        notes["_no_water_reason"] = f"DEQ's impact for this report: “{impact}”"
        if names:
            notes["_water_text_unused"] = names + unused
        names, unused = [], []
    elif REACHED.search(impact or ""):
        notes["reached_water"] = True
    if names and not county:
        notes["_water_text_unused"] = names + unused
        notes["_water_text_why"] = ("the report names a water but its permit has no plant point to give a county, so "
                                    "the name is not tied across the state")
        names, unused = [], []
    elif unused:
        notes["_water_text_unused"] = unused
    rec["waterbody_text"] = "; ".join(names) or None
    if names:
        notes["_water_basis"] = "the water the report's location text names (DEQ's search has no receiving-water field)"


@F.hook
def ar_deq_not_sewage(records: list[dict], ctx: F.Ctx) -> dict:
    """Drop the reports of industrial permits that are not sewage (module docstring); count them."""
    keep, n = [], 0
    for r in records:
        raw = r.get("raw") or {}
        row = raw.get("row") or {}
        label = raw.get("_source_type") or ""
        if (not re.search(r"\bSSO\b", label, re.I) and label and not raw.get("_sewage_plant_permit")
                and INDUSTRY.search(F.clean(row.get("facility_name")))):
            n += 1
            continue
        keep.append(r)
    records[:] = keep
    return {"not_sewage": n}


# ---------------------------------------------------------------- DEQ harmful algal bloom advisories

HAB_PAGE = "https://adeq.state.ar.us/water/planning/hab/"
HAB_ADVICE = ("DEQ lists this water among the “recreational use health advisories issued and lifted throughout the "
              "season for monitored and sampled water bodies” (Harmful Algal Blooms page)")
HAB_STAR = ("DEQ's archive marks this row: “Advisory posted by partner agency or HAB confirmed, but no advisory "
            "issued”")
NOT_GIVEN = re.compile(r"^\s*(n/?a|none|-+)\s*$", re.I)
COORDS = re.compile(r"\(\s*coordinates\s+(-?\d{1,2}\.\d+)\s*,\s*(-?\d{2,3}\.\d+)\s*\)", re.I)
# the water's point in the USGS Geographic Names Information System for that name in the advisory's county (The National
# Map geonames, layer 7 Other Hydrographic Features, read 2026-11-14): (name, county) -> (GNIS feature id, lat, lon).
# Waters with no GNIS feature of that name in that county (Lake Hamilton, Lake Conway, Brewer Lake in Conway County,
# Harris Brake Lake, Lake Nimrod, Lake Fayetteville, Lake Wilson in Washington County, Huston Lake, Mom's Lake, the
# park ponds) have no point here and are placed by name and county only.
GNIS_POINTS = {
    ("bear creek lake", "Lee"): (74641, 34.711, -90.695),
    ("bois d'arc lake", "Hempstead"): (75657, 33.555, -93.703),
    ("gillham lake", "Howard"): (81042, 34.172, -94.322),       # GNIS files the reservoir under Sevier County
    ("horsehead lake", "Johnson"): (80009, 35.560, -93.625),
    ("horseshoe lake", "Crittenden"): (74912, 34.925, -90.340),
    ("lake atalanta", "Benton"): (76207, 36.338, -94.098),
    ("lake bennett", "Faulkner"): (79378, 35.286, -92.286),
    ("lake catherine", "Garland"): (80152, 34.427, -92.887),    # GNIS: Hot Spring County, the lake's other county
    ("lake charles", "Lawrence"): (79903, 36.073, -91.149),
    ("lake desoto", "Garland"): (80351, 34.678, -93.018),
    ("lake elmdale", "Washington"): (75705, 36.195, -94.213),
    ("lake hogue", "Poinsett"): (81237, 35.583, -90.963),
    ("lake june", "Lafayette"): (80580, 33.355, -93.492),
    ("lake omaha", "Fulton"): (79677, 36.307, -91.597),
    ("lake overcup", "Conway"): (79868, 35.203, -92.721),
    ("lake poinsett", "Poinsett"): (80073, 35.531, -90.676),
    ("lake sophia", "Garland"): (2787042, 34.634, -92.850),     # GNIS: Saline County, the lake's other county
    ("spring lake", "Yell"): (80411, 35.154, -93.427),
    ("victory lake", "Clay"): (75201, 36.413, -90.565),
}


DESCRIBED = re.compile(r"^(stream|creek|pond|lake|cove|inlet|spring)\b\s+(by|near|at|behind|east|west|north|south|"
                       r"below|above|off)\b", re.I)


def round_text_coords(text):
    """DEQ's coordinates written in a waterbody name, rounded to 0.001 degree before anything is saved."""
    if not isinstance(text, str):
        return text
    return COORDS.sub(lambda m: f"(coordinates {round(float(m.group(1)), 3)}, {round(float(m.group(2)), 3)})", text)


def hab_water(text: str) -> tuple[str, str | None]:
    """(the water's name, the qualifier DEQ adds): "Lake Catherine - Spencer Bay *" -> ("Lake Catherine", "Spencer
    Bay"); "Huston Lake on Big Huston Creek" -> ("Huston Lake", "on Big Huston Creek"); the star and a coordinate
    note are not part of the name."""
    t = COORDS.sub("", text or "").replace("’", "'").rstrip(" *").strip()
    m = re.match(r"^(.*?)\s+(?:-\s+(.+)|((?:on|near|by)\s+.+))$", t)
    if m and not t.lower().startswith("stream"):
        return m.group(1).strip(), (m.group(2) or m.group(3)).strip()
    return t, None


def hab_counties(text: str) -> list[str]:
    """"Garland and Saline Counties", "Garland County and Saline County" -> ["Garland", "Saline"]."""
    t = re.sub(r"\bcount(?:y|ies)\b", "", F.clean(text), flags=re.I)
    out = [c.strip() for c in re.split(r"\s*(?:,|\band\b|&)\s*", t) if c.strip()]
    out = [c.title() for c in out]                                         # "LaFayette" -> "Lafayette"
    return ["Hot Spring" if c == "Hot Springs" else c for c in out]         # the county is Hot Spring


@F.hook
def ar_hab_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    notes["state"] = "AR"
    notes["time_zone"] = TZ_NAME
    notes["timezone_note"] = "Central time (Arkansas is wholly in the Central zone, 49 CFR part 71, the Central zone); dates only"
    _local_midnights(rec)
    raw_name = F.clean(row.get("waterbody"))
    star = raw_name.endswith("*")
    name, qualifier = hab_water(raw_name)
    rec["event_type"] = "hab_advisory"
    described = bool(DESCRIBED.match(name or ""))
    if described:
        # "Stream by Waterfall Trail East of Lake Alma": a place described, not a water's name; the lake it mentions
        # is not the affected water. Placed only by DEQ's own point when the row gives one.
        rec["waterbody_text"] = None
        notes["_water_description"] = name
    else:
        rec["waterbody_text"] = name or None
    if qualifier:
        # "Lake Catherine - Spencer Bay": DEQ's advisory is for part of the lake, never the whole lake's colour
        notes["_water_qualifier"] = qualifier
    counties = hab_counties(row.get("county"))
    if counties:
        notes["county"] = f"{counties[0]} County"
        if len(counties) > 1:
            notes["counties"] = [f"{c} County" for c in counties]
    area = F.clean(row.get("area"))
    if area:
        notes["_nearest_area"] = area
    if not described:
        notes["_placement"] = "named_water_only"
    lifted = F.clean(row.get("lifted"))
    if star:
        # not DEQ's own advisory: the site's caution from the posting day (data/rules.json unresolved.sample_caution)
        rec["status"] = "unknown"
        rec["ended_at"] = None
        notes["_agency_label_only"] = True
        notes["_agency_label"] = HAB_STAR
        rec["advice_text"] = HAB_STAR
        if lifted and not NOT_GIVEN.match(lifted):
            notes["_lifted_as_given"] = lifted
    else:
        rec["advice_text"] = HAB_ADVICE
        if rec.get("ended_at"):
            rec["status"] = "advisory_lifted"
            notes["ended_at_precision"] = "day"
            notes["end_basis"] = "DEQ's Date Lifted"
        elif lifted and NOT_GIVEN.match(lifted):
            # DEQ shows it as no longer in effect (its current table lists only rows with no lift date) but gives no
            # lift date: no end is invented, and the status build draws no window without one
            rec["status"] = "advisory_lifted"
            notes["_lift_date_not_given"] = f"DEQ's Date Lifted reads “{lifted}”"
        else:
            rec["status"] = "advisory_active"
            notes["start_basis"] = "DEQ's Date Posted"
    # the point: DEQ's own coordinates where the row gives them, else the GNIS feature of that name in its county
    m = COORDS.search(raw_name)
    if m:
        rec["lat"], rec["lon"] = round(float(m.group(1)), 3), round(float(m.group(2)), 3)
        rec["coord_source"], rec["coord_precision_m"] = "source", 150
        notes["_point_basis"] = "the coordinates DEQ gives in the advisory's waterbody name, rounded to 0.001 degree"
    elif not qualifier and not described:
        # the parent lake's GNIS point is never used for a bay, an arm or a described place: that would draw the
        # marker at the wrong place (review 2026-11-14 P1-3); such a row has a point only where DEQ gives one
        pt = next((GNIS_POINTS[(name.lower(), c)] for c in counties if (name.lower(), c) in GNIS_POINTS), None)
        if pt:
            rec["lat"], rec["lon"] = pt[1], pt[2]
            rec["coord_source"], rec["coord_precision_m"] = "gnis", 1000
            notes["_point_basis"] = (f"the USGS GNIS feature {pt[0]} of this name in this county (The National Map "
                                     "geonames, read 2026-11-14): the water, not where the bloom was sampled")
    if not described and not qualifier:
        notes["advisory_extent"] = "named_water"      # DEQ names the lake itself as the advisory's water
    else:
        # part of a water, or a place described near one: the status build draws its marker only and never colours
        # the water it is placed on, whatever the water's size (build/status.py part_of_water)
        notes["advisory_extent"] = "part_of_water"
