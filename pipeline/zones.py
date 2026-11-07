"""The clock a record's local times and calendar days are read in (SOL reviews of 2026-11-07: wave 1 P1-2 and P1-3,
wave 2 P1-1). A source that gives a bare date or a time without an offset means its own place's clock; reading it in
New York's put a Pacific, Central or Mountain day's end one to three hours early.

  STATE_ZONES  the zone of each state (its larger part for a state that straddles two: 49 CFR part 71).
  zone_for     the zone for a state and, where the state straddles two zones and the code knows the line, the point:
               Florida by its Eastern-Central boundary (florida_zone), South Dakota and Nebraska by the county files of
               data/reference used by the EPA overflow tables (ingest.echo_sewer_overflow_events.point_zone). Any other
               state gets STATE_ZONES; a state the table does not know gets None (the caller's default).

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


@functools.lru_cache(maxsize=4096)
def _county_zone(state: str, lat: float, lon: float) -> str | None:
    from ingest.echo_sewer_overflow_events import point_zone
    return point_zone(state, lat, lon)[0]


def zone_for(state: str | None, lat=None, lon=None) -> str | None:
    """The IANA zone for a record of this state at this point (module docstring); None for an unknown state."""
    st = (state or "").upper()
    if st == "FL":
        return florida_zone(lat, lon)
    if st in ("SD", "NE") and lat is not None and lon is not None:
        try:
            return _county_zone(st, float(lat), float(lon)) or STATE_ZONES[st]
        except (RuntimeError, ImportError, ValueError):
            return STATE_ZONES[st]          # the county file missing: the state's larger part
    return STATE_ZONES.get(st)
