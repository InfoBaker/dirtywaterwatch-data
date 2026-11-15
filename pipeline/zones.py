"""The clock a record's local times and calendar days are read in (SOL reviews of 2026-11-07: wave 1 P1-2 and P1-3,
wave 2 P1-1). A source that gives a bare date or a time without an offset means its own place's clock; reading it in
New York's put a Pacific, Central or Mountain day's end one to three hours early.

  STATE_ZONES  the zone of each state (its larger part for a state that straddles two: 49 CFR part 71).
  zone_for     the zone for a state and, where the state straddles two zones and the code knows the line, the point:
               Florida by its Eastern-Central boundary (florida_zone), South Dakota, Nebraska and Kentucky by the county
               files of data/reference used by the EPA overflow tables (ingest.echo_sewer_overflow_events.point_zone;
               Kentucky's forty-one Central-time counties, 49 CFR 71.5(c)), Oregon by Malheur County (oregon_zone),
               Tennessee by its county (a name, or the county a point lies in: tennessee_zone), North Dakota by its county
               (north_dakota_zone, 49 CFR 71.7(a)), Kansas by its county (49 CFR 71.7(d): kansas_zone), Indiana by its
               county (a name, or the county a point lies in: indiana_zone, the twelve Central-time counties of 49 CFR
               71.5(b)), Nevada by West Wendover's city limits (nevada_zone, 49 CFR 71.9(b)). Any other state gets
               STATE_ZONES; a state the table does not know gets None (the caller's default).

Not a feed (no __main__)."""
from __future__ import annotations

import functools
import re

EASTERN, CENTRAL, MOUNTAIN, PACIFIC = "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"

STATE_ZONES = {
    **{s: EASTERN for s in ("CT", "DE", "DC", "FL", "GA", "IN", "KY", "ME", "MD", "MA", "MI", "NH", "NJ", "NY", "NC",
                            "OH", "PA", "RI", "SC", "VT", "VA", "WV")},
    **{s: CENTRAL for s in ("AL", "AR", "IL", "IA", "KS", "LA", "MN", "MS", "MO", "NE", "ND", "OK", "SD", "TN", "TX",
                            "WI")},
    **{s: MOUNTAIN for s in ("CO", "ID", "MT", "NM", "UT", "WY")},
    "AZ": "America/Phoenix",              # no daylight saving time (the Navajo Nation's clock is the source's to give)
    **{s: PACIFIC for s in ("CA", "NV", "OR", "WA")},
    "AK": "America/Anchorage", "HI": "Pacific/Honolulu", "PR": "America/Puerto_Rico", "VI": "America/St_Thomas",
    "GU": "Pacific/Guam", "AS": "Pacific/Pago_Pago", "MP": "Pacific/Saipan",
}

# Florida's Eastern-Central boundary (49 CFR 71.5 and 71.6): the Apalachicola River from the Georgia line to the Gulf
# County line, then, in Gulf County, the Intracoastal Waterway west to the Bay County line; west of it Central, except
# the part of Gulf County south of the waterway (Port St. Joe, Cape San Blas: Eastern). Traced from the river's and the
# waterway's course to within about 2 km; a point that close to the line should carry its own raw.time_zone.
# (lat, the river's longitude), north to south
FL_RIVER = [(31.10, -84.86), (30.71, -84.86), (30.55, -84.95), (30.44, -85.01), (30.25, -85.08), (30.10, -85.12),
            (29.95, -85.05), (29.85, -85.03), (29.50, -85.03)]
# (lon, the waterway's latitude), west to east: the Gulf County pocket south of it keeps Eastern time
FL_WATERWAY = [(-85.39, 30.03), (-85.30, 29.96), (-85.22, 29.88), (-85.10, 29.86), (-85.03, 29.85)]
FL_GULF_COUNTY_WEST = -85.39


def _interp(pts: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear y at x over pts [(x, y)] (sorted either way); clamped to the ends."""
    pts = sorted(pts)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def florida_zone(lat, lon) -> str:
    """Florida's zone at a point: Central west of the Apalachicola River (FL_RIVER) except Gulf County south of the
    Intracoastal Waterway; Eastern elsewhere and when no point is given (the state's larger part)."""
    if lat is None or lon is None:
        return EASTERN
    lat, lon = float(lat), float(lon)
    if lon >= _interp(FL_RIVER, lat):
        return EASTERN
    if lon > FL_GULF_COUNTY_WEST and lat < _interp(FL_WATERWAY, lon):
        return EASTERN                      # Gulf County south of the waterway (Port St. Joe)
    return CENTRAL


# Oregon's Mountain-Pacific line (49 CFR 71.9(a), read in eCFR 2026-11-07): from the Idaho line "westerly along the north
# line of Malheur County to the northwest corner of Malheur County; thence southerly along the west line of Malheur
# County to the southwest corner of T. 35 S., R. 37 E.; thence east to the Idaho-Oregon boundary". Malheur County north
# of the south line of township 35 South is Mountain time; its part south of that line, and the rest of Oregon, Pacific.
# The township line lies 210 miles south of the Willamette base line (45.5197 N): about 42.48 N. Malheur's outline here
# is its Census outline (data/reference/or-counties.json) when the file is there, else a box: its west line about
# 118.23 W, its north line about 44.30 N (the Baker County line runs near 44.3 N to 44.5 N east of 118 W).
OR_MALHEUR_WEST, OR_MALHEUR_NORTH, OR_T35S_SOUTH = -118.23, 44.30, 42.48


@functools.lru_cache(maxsize=1)
def _malheur_outline():
    """Malheur County's Census outline (data/reference/or-counties.json, scripts/or_counties.py), or None (the box)."""
    try:
        import json
        from pathlib import Path

        from shapely.geometry import shape
        doc = json.loads((Path(__file__).resolve().parent.parent / "data" / "reference" / "or-counties.json").read_text())
        c = next(x for x in doc["counties"] if x["county"] == "Malheur County")
        return shape(c["geometry"])
    except (OSError, ValueError, KeyError, StopIteration, ImportError):
        return None


def _point(lon, lat):
    from shapely.geometry import Point
    return Point(lon, lat)


def oregon_zone(lat=None, lon=None, county: str | None = None) -> str:
    """Oregon's zone: Mountain in Malheur County north of township 35 South (49 CFR 71.9(a)), Pacific elsewhere. The
    county, when the source gives it, decides whether the record is in Malheur; else the point against Malheur's box.
    Malheur with no point is Mountain (the county's people and towns lie north of the line)."""
    c = (county or "").strip().lower().removesuffix(" county")
    if c and c != "malheur":
        return PACIFIC
    if lat is None or lon is None:
        return MOUNTAIN if c == "malheur" else PACIFIC
    lat, lon = float(lat), float(lon)
    if c == "malheur":
        in_malheur = True
    else:
        outline = _malheur_outline()
        in_malheur = (outline.covers(_point(lon, lat)) if outline is not None
                      else lon >= OR_MALHEUR_WEST and lat < OR_MALHEUR_NORTH)
    return MOUNTAIN if in_malheur and lat >= OR_T35S_SOUTH else PACIFIC


@functools.lru_cache(maxsize=4096)
def _county_zone(state: str, lat: float, lon: float) -> str | None:
    from ingest.echo_sewer_overflow_events import point_zone
    return point_zone(state, lat, lon)[0]


# Tennessee (49 CFR 71.5(d)): the Eastern-Central line follows county lines; these thirty East Tennessee counties keep
# Eastern time, the other sixty-five Central, none split (scripts/tn_eastern_time_counties.py checks them against the
# U.S. DOT time-zone layer and writes their outlines to data/reference/tn-eastern-time-counties.json)
TN_EASTERN_COUNTIES = frozenset({
    "ANDERSON", "BLOUNT", "BRADLEY", "CAMPBELL", "CARTER", "CLAIBORNE", "COCKE", "GRAINGER", "GREENE", "HAMBLEN",
    "HAMILTON", "HANCOCK", "HAWKINS", "JEFFERSON", "JOHNSON", "KNOX", "LOUDON", "MCMINN", "MEIGS", "MONROE", "MORGAN",
    "POLK", "RHEA", "ROANE", "SCOTT", "SEVIER", "SULLIVAN", "UNICOI", "UNION", "WASHINGTON"})


def tn_county_key(county) -> str:
    """'McMinn County' -> 'MCMINN'."""
    import re
    c = re.sub(r"\s+county\s*$", "", str(county or "").strip(), flags=re.I)
    return re.sub(r"^MC\s+", "MC", re.sub(r"\s+", " ", c).upper())      # "Mc Minn" is McMinn


@functools.lru_cache(maxsize=1)
def _tn_eastern_shapes():
    import json
    from pathlib import Path

    from shapely.geometry import shape
    from shapely.validation import make_valid
    p = Path(__file__).resolve().parents[1] / "data" / "reference" / "tn-eastern-time-counties.json"
    doc = json.loads(p.read_text())
    return [(c["county"], make_valid(shape(c["geometry"]))) for c in doc["counties"]]


def tn_point_county(lat, lon) -> str | None:
    """The Eastern-time county a point lies in ('Knox County'), or None (a Central county, or no point)."""
    if lat is None or lon is None:
        return None
    from shapely.geometry import Point
    pt = Point(float(lon), float(lat))
    for county, g in _tn_eastern_shapes():
        if g.covers(pt):
            return county
    return None


def tennessee_zone(county=None, lat=None, lon=None) -> str:
    """Tennessee's zone: Eastern in the thirty TN_EASTERN_COUNTIES (by the county's name when given, else by the
    county the point lies in), Central elsewhere and when neither is given (the state's larger part)."""
    if county and str(county).strip():
        return EASTERN if tn_county_key(county) in TN_EASTERN_COUNTIES else CENTRAL
    try:
        return EASTERN if tn_point_county(lat, lon) else CENTRAL
    except (OSError, ImportError, ValueError):
        return CENTRAL


# Kansas (49 CFR 71.7(d), read in eCFR 2026-11-14): the Central-Mountain line runs along the east lines of Sherman,
# Wallace, Greeley and Hamilton counties (with the north lines of Sherman, Logan's west part and Wichita between them),
# so those four counties keep Mountain time and the other 101 Central; no county is split. A record's county is its
# own county field when the source gives one, else the county whose Census outline (data/reference/ks-counties.json,
# scripts/ks_counties.py) holds its point; with neither it is Central (the state's larger part).
KS_MOUNTAIN_COUNTIES = frozenset({"SHERMAN", "WALLACE", "GREELEY", "HAMILTON"})


@functools.lru_cache(maxsize=1)
def _ks_county_shapes():
    import json
    from pathlib import Path

    from shapely.geometry import shape
    from shapely.validation import make_valid
    p = Path(__file__).resolve().parents[1] / "data" / "reference" / "ks-counties.json"
    doc = json.loads(p.read_text())
    return [(c["county"], make_valid(shape(c["geometry"]))) for c in doc["counties"]]


def ks_point_county(lat, lon) -> str | None:
    """The Kansas county a point lies in ('Sherman County'), or None (outside Kansas, or no point)."""
    if lat is None or lon is None:
        return None
    from shapely.geometry import Point
    pt = Point(float(lon), float(lat))
    for county, g in _ks_county_shapes():
        if g.covers(pt):
            return county
    return None


def kansas_zone(county=None, lat=None, lon=None) -> str:
    """Kansas's zone: Mountain in the four KS_MOUNTAIN_COUNTIES (by the county's name when given, else by the county the
    point lies in), Central elsewhere and when neither is given."""
    c = tn_county_key(county) if county and str(county).strip() else None
    if c is None:
        try:
            pc = ks_point_county(lat, lon)
        except (OSError, ImportError, ValueError):
            pc = None
        c = tn_county_key(pc) if pc else None
    return MOUNTAIN if c in KS_MOUNTAIN_COUNTIES else CENTRAL


# Indiana (49 CFR 71.5(b), read in eCFR 2026-11-14): the Eastern-Central line follows county lines, leaving six
# northwestern counties (Lake, Porter, LaPorte, Starke, Jasper, Newton) and six southwestern ones (Gibson, Posey,
# Vanderburgh, Warrick, Spencer, Perry) wholly in Central time and the other eighty Eastern; none split
# (scripts/in_central_time_counties.py checks them against the U.S. DOT time-zone layer and writes their outlines to
# data/reference/in-central-time-counties.json, which the point rule reads through _county_zone)
IN_CENTRAL_COUNTIES = frozenset({"GIBSON", "JASPER", "LAKE", "LAPORTE", "NEWTON", "PERRY", "PORTER", "POSEY", "SPENCER",
                                 "STARKE", "VANDERBURGH", "WARRICK"})


def in_county_key(county) -> str:
    """'La Porte County' -> 'LAPORTE', 'St. Joseph' -> 'STJOSEPH' (spaces, periods and the word County dropped)."""
    import re
    c = re.sub(r"\s+county\s*$", "", str(county or "").strip(), flags=re.I)
    return re.sub(r"[\s.']+", "", c).upper()


def indiana_zone(county=None, lat=None, lon=None) -> str:
    """Indiana's zone: Central in the twelve IN_CENTRAL_COUNTIES (by the county's name when given, else by the county
    the point lies in, data/reference/in-central-time-counties.json), Eastern elsewhere and when neither is given (the
    state's larger part)."""
    if county and str(county).strip():
        return CENTRAL if in_county_key(county) in IN_CENTRAL_COUNTIES else EASTERN
    if lat is None or lon is None:
        return EASTERN
    try:
        return _county_zone("IN", float(lat), float(lon)) or EASTERN
    except (RuntimeError, ImportError, ValueError, OSError):
        return EASTERN          # the county file missing: the state's larger part
# Nevada (49 CFR 71.9(b) and (d), read in eCFR 2026-11-14): the Mountain-Pacific line follows the Utah-Nevada boundary
# except around the City of West Wendover, whose northern, western and southern limits it follows: West Wendover keeps
# Mountain time, the rest of Nevada Pacific (towns that keep Mountain time by custom, such as Jackpot, are Pacific in
# law). The city's outline: data/reference/nv-west-wendover.json (scripts/nv_west_wendover.py, TIGERweb Incorporated
# Places); without the file, its box (114.113 W to the state line, 40.725 N to 40.756 N).
NV_WEST_WENDOVER_BOX = (-114.1135, 40.7250, -114.0400, 40.7560)


@functools.lru_cache(maxsize=1)
def _west_wendover_outline():
    try:
        import json
        from pathlib import Path

        from shapely.geometry import shape
        doc = json.loads((Path(__file__).resolve().parent.parent / "data" / "reference" / "nv-west-wendover.json").read_text())
        return shape(doc["place"]["geometry"])
    except (OSError, ValueError, KeyError, ImportError):
        return None


def nevada_zone(lat=None, lon=None, place: str | None = None) -> str:
    """Nevada's zone: Mountain inside West Wendover's city limits (by the place's name when the source gives one, else
    the point against the city's outline), Pacific elsewhere and when neither is given."""
    if place and str(place).strip():
        return MOUNTAIN if str(place).strip().lower().removesuffix(" city") == "west wendover" else PACIFIC
    if lat is None or lon is None:
        return PACIFIC
    lat, lon = float(lat), float(lon)
    outline = _west_wendover_outline()
    if outline is not None:
        # the city's east side is the state line: the strip between its rounded outline and the line is the city's
        w, s_, e, n = outline.bounds
        inside = outline.buffer(0.0005).covers(_point(lon, lat)) or (s_ <= lat <= n and e - 0.001 <= lon)
    else:
        w, s_, e, n = NV_WEST_WENDOVER_BOX
        inside = w <= lon <= e and s_ <= lat <= n
    return MOUNTAIN if inside else PACIFIC


def zone_for(state: str | None, lat=None, lon=None) -> str | None:
    """The IANA zone for a record of this state at this point (module docstring); None for an unknown state."""
    st = (state or "").upper()
    if st == "FL":
        return florida_zone(lat, lon)
    if st == "OR":
        return oregon_zone(lat, lon)
    if st == "TN" and lat is not None and lon is not None:
        return tennessee_zone(lat=lat, lon=lon)
    if st == "ND" and lat is not None and lon is not None:
        return north_dakota_zone(lat=lat, lon=lon)[0]
    if st == "KS" and lat is not None and lon is not None:
        return kansas_zone(lat=lat, lon=lon)
    if st == "IN":
        return indiana_zone(lat=lat, lon=lon)
    if st == "NV":
        return nevada_zone(lat, lon)
    if st in ("SD", "NE", "KY") and lat is not None and lon is not None:
        try:
            return _county_zone(st, float(lat), float(lon)) or STATE_ZONES[st]
        except (RuntimeError, ImportError, ValueError):
            return STATE_ZONES[st]          # the county file missing: the state's larger part
    return STATE_ZONES.get(st)


# North Dakota (49 CFR 71.7(a), read in eCFR 2026-11-14): the Central-Mountain line runs down the Montana line to the
# Missouri, along the Yellowstone and a township staircase (R. 102 W. and R. 101 W.) to the Little Missouri, along the
# Little Missouri and the Missouri to Mercer County's western land line, south along Mercer's west line, along Morton
# County's southwestern line to Sioux County, west along Sioux's north line to State Highway 31 and down Highway 31 to
# South Dakota. West and south of it is Mountain time: these eight counties whole, and the parts of McKenzie County
# (west of the staircase and south of the Little Missouri), Dunn County (south and east of the Little Missouri, which the
# line follows through the county to the Missouri: its part toward Lake Sakakawea is Central; verification pass 2
# 2026-11-15 P2-1) and Sioux County (west of Highway 31). A record in a split county is read on the side its point lies
# on; with no point, in Mountain time, the later day's end, as South Dakota's Stanley County is
# (sd_danr_hab_advisories), and marked as assumed: a caution never ends early.
ND_MOUNTAIN_COUNTIES = frozenset({"ADAMS", "BILLINGS", "BOWMAN", "GOLDEN VALLEY", "GRANT", "HETTINGER", "SLOPE",
                                  "STARK"})
ND_SPLIT_COUNTIES = frozenset({"DUNN", "MCKENZIE", "SIOUX"})
ND_ZONE_CITE = "49 CFR 71.7(a)"


@functools.lru_cache(maxsize=1)
def _nd_county_shapes():
    import json
    from pathlib import Path

    from shapely.geometry import shape
    from shapely.validation import make_valid
    p = Path(__file__).resolve().parents[1] / "data" / "reference" / "nd-counties.json"
    doc = json.loads(p.read_text())
    return [(c["county"], make_valid(shape(c["geometry"]))) for c in doc["counties"]]


def nd_point_county(lat, lon) -> str | None:
    """The North Dakota county a point lies in ('Stark County'), or None (no point, outside, or no outline file)."""
    if lat is None or lon is None:
        return None
    from shapely.geometry import Point
    pt = Point(float(lon), float(lat))
    for county, g in _nd_county_shapes():
        if g.covers(pt):
            return county
    return None


@functools.lru_cache(maxsize=1)
def _nd_split_parts():
    """{county key: the Mountain part's geometry} of Dunn, McKenzie and Sioux (data/reference/nd-split-county-zones.json:
    USDOT/BTS NTAD time zones cut to the county outlines)."""
    import json
    from pathlib import Path

    from shapely.geometry import shape
    from shapely.validation import make_valid
    p = Path(__file__).resolve().parents[1] / "data" / "reference" / "nd-split-county-zones.json"
    doc = json.loads(p.read_text())
    return {tn_county_key(c["county"]): make_valid(shape(c["mountain_part"])) for c in doc["counties"]}


def north_dakota_split_side(county, lat, lon) -> str | None:
    """MOUNTAIN or CENTRAL for a point in Dunn, McKenzie or Sioux County, from the cited line (NTAD), or None (no point,
    not a split county, no line file, or a point that does not lie in that county: its side there is not known)."""
    if lat is None or lon is None or tn_county_key(county or "") not in ND_SPLIT_COUNTIES:
        return None
    try:
        from shapely.geometry import Point
        part = _nd_split_parts().get(tn_county_key(county))
    except (OSError, ImportError, ValueError, KeyError):
        return None
    if part is None:
        return None
    try:
        inside = nd_point_county(lat, lon)
    except (OSError, ImportError, ValueError, KeyError):
        inside = None
    if inside is not None and tn_county_key(inside) != tn_county_key(county):
        return None
    return MOUNTAIN if part.covers(Point(float(lon), float(lat))) else CENTRAL


def north_dakota_zone_uncertain(county=None, lat=None, lon=None) -> bool:
    """True when the record's zone is assumed, not known: a Dunn, McKenzie or Sioux County record whose point cannot be
    placed on a side of the line (re-review 2026-11-14 P2-4)."""
    if not (county and str(county).strip()):
        try:
            county = nd_point_county(lat, lon)
        except (OSError, ImportError, ValueError, KeyError):
            county = None
    return tn_county_key(county or "") in ND_SPLIT_COUNTIES and north_dakota_split_side(county, lat, lon) is None


def north_dakota_zone(county=None, lat=None, lon=None) -> tuple[str, str]:
    """(zone, basis) for a North Dakota record: Mountain in ND_MOUNTAIN_COUNTIES; in the three split counties the side
    of the line the record's point lies on (data/reference/nd-split-county-zones.json, re-review 2026-11-14 P2-4), and
    with no point Mountain time, the later day's end, stated as assumed (north_dakota_zone_uncertain); Central
    elsewhere and when no county is known (the state's larger part). The county is the one the source gives, else the
    one the point lies in."""
    if not (county and str(county).strip()):
        try:
            county = nd_point_county(lat, lon)
        except (OSError, ImportError, ValueError, KeyError):
            county = None
        how = "the county the point lies in"
    else:
        how = "the county the source gives"
    if not county:
        return CENTRAL, f"no county known: Central time, the state's larger part ({ND_ZONE_CITE})"
    key = tn_county_key(county)
    name = re.sub(r"(?i)\s+county$", "", str(county).strip())
    if key in ND_MOUNTAIN_COUNTIES:
        return MOUNTAIN, f"{name} County keeps Mountain time ({ND_ZONE_CITE}; {how})"
    if key in ND_SPLIT_COUNTIES:
        side = north_dakota_split_side(county, lat, lon)
        if side:
            return side, (f"{name} County is split by the line ({ND_ZONE_CITE}); the record's point lies on its "
                          f"{'Mountain' if side == MOUNTAIN else 'Central'} side (USDOT/BTS NTAD time zones; {how})")
        return MOUNTAIN, (f"{name} County is split by the line ({ND_ZONE_CITE}) and the record gives no point: its zone "
                          f"is not known; this site assumes Mountain time, the later day's end, so a date read in it "
                          f"may be an hour later than the source's own clock ({how})")
    return CENTRAL, f"{name} County keeps Central time ({ND_ZONE_CITE}; {how})"
