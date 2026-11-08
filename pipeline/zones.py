"""The clock a record's local times and calendar days are read in (SOL reviews of 2026-11-07: wave 1 P1-2 and P1-3,
wave 2 P1-1). A source that gives a bare date or a time without an offset means its own place's clock; reading it in
New York's put a Pacific, Central or Mountain day's end one to three hours early.

  STATE_ZONES  the zone of each state (its larger part for a state that straddles two: 49 CFR part 71).
  zone_for     the zone for a state and, where the state straddles two zones and the code knows the line, the point:
               Florida by its Eastern-Central boundary (florida_zone), South Dakota, Nebraska and Kentucky by the county
               files of data/reference used by the EPA overflow tables (ingest.echo_sewer_overflow_events.point_zone;
               Kentucky's forty-one Central-time counties, 49 CFR 71.5(c)), Oregon by Malheur County (oregon_zone),
               Tennessee by its county (a name, or the county a point lies in: tennessee_zone). Any other state gets
               STATE_ZONES; a state the table does not know gets None (the caller's default).

Not a feed (no __main__)."""
from __future__ import annotations

import functools

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


def zone_for(state: str | None, lat=None, lon=None) -> str | None:
    """The IANA zone for a record of this state at this point (module docstring); None for an unknown state."""
    st = (state or "").upper()
    if st == "FL":
        return florida_zone(lat, lon)
    if st == "OR":
        return oregon_zone(lat, lon)
    if st == "TN" and lat is not None and lon is not None:
        return tennessee_zone(lat=lat, lon=lon)
    if st in ("SD", "NE", "KY") and lat is not None and lon is not None:
        try:
            return _county_zone(st, float(lat), float(lon)) or STATE_ZONES[st]
        except (RuntimeError, ImportError, ValueError):
            return STATE_ZONES[st]          # the county file missing: the state's larger part
    return STATE_ZONES.get(st)
