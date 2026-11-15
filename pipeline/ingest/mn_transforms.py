"""Minnesota hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

mn_wlssd_record (block mn-wlssd-overflows: Resource Renew / the Western Lake Superior Sanitary District's overflow
points layer behind wlssd.com/services/wastewater/overflows/):
  - Type from FacilityType: Treatmentplant -> plant_bypass (a release at the plant: "70 MGD" during a storm is the
    plant passing flow around treatment, the layer's other wording "Bypass" too); Manhole, ForceMain, PumpStation,
    Other and a blank type -> sso (a collection-system release). Never unknown (wave 4 rule 3).
  - Water: StateWaters "Yes" -> raw.reached_water true (WLSSD says the release reached waters of the state; the layer
    names none, so the report is placed from its own point); "No" -> raw.reached_water false with WLSSD's flag as the
    reason (kept, placed on no water); blank -> unknown (94 of the 117 rows on 2026-11-14), placed from its point.
  - Quantity: ReleaseAmount is free text ("25,000 gallons", "Less than 50 gallons", "70 MGD", "100 gpm", "UNK"): the
    field map's volume parser keeps a plain gallon figure; a rate (MGD, gpm) is a rate, never a volume, and stays text.
  - Clock: OverflowDate is an epoch. 84 of the 117 rows sit at exactly 00:00 UTC: a date entered without a time,
    read as that date (the block's midnight: date); the others are instants (UTC), shown in Central time. raw.time_zone
    America/Chicago; raw.county the county the point lies in (data/reference/mn-counties.json).
  - Operator: discharger_id mn-wlssd (Western Lake Superior Sanitary District, MN0049786) for every row: the layer is
    the District's own record of releases from its interceptors, pump stations and plant.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

from ingest.generic import fieldmap as F

ZONE = "America/Chicago"
COUNTIES = Path(__file__).resolve().parents[2] / "data" / "reference" / "mn-counties.json"
WLSSD_TYPES = {"treatmentplant": "plant_bypass", "manhole": "sso", "forcemain": "sso", "pumpstation": "sso",
               "other": "sso", "": "sso"}
WLSSD_ID, WLSSD_NAME, WLSSD_PERMIT = "mn-wlssd", "Western Lake Superior Sanitary District", "MN0049786"


@functools.lru_cache(maxsize=1)
def _counties():
    from shapely.geometry import shape
    from shapely.validation import make_valid
    doc = json.loads(COUNTIES.read_text())
    return [(c["county"], make_valid(shape(c["geometry"]))) for c in doc["counties"]]


def point_county(lat, lon) -> str | None:
    """The Minnesota county ('St. Louis County') a point lies in, or None."""
    if lat is None or lon is None:
        return None
    from shapely.geometry import Point
    p = Point(float(lon), float(lat))
    return next((c for c, g in _counties() if g.covers(p)), None)


@F.hook
def mn_wlssd_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    ft = F.clean(row.get("FacilityType"))
    rec["event_type"] = WLSSD_TYPES.get(ft.lower().replace(" ", ""), "sso")
    notes["_type_basis"] = f"WLSSD's FacilityType {ft or '(blank)'!r}"
    rec["outfall_name"] = {"Treatmentplant": "WLSSD treatment plant", "ForceMain": "force main",
                           "PumpStation": "pump station", "Manhole": "manhole"}.get(ft, ft.lower() or None)
    rec["discharger_id"], rec["discharger_name"], rec["npdes_permit"] = WLSSD_ID, WLSSD_NAME, WLSSD_PERMIT
    sw = F.clean(row.get("StateWaters")).lower()
    if sw == "yes":
        notes["reached_water"] = True
        notes["_reached_water_basis"] = "WLSSD's StateWaters field: Yes (the layer names no water)"
    elif sw == "no":
        notes["reached_water"] = False
        notes["_no_water_reason"] = "WLSSD's StateWaters field: No (the release did not reach waters of the state)"
    else:
        notes["reached_water"] = None
        notes["_reached_water_basis"] = "WLSSD's StateWaters field is blank: not stated"
    amt = F.clean(row.get("ReleaseAmount"))
    if amt and rec.get("volume_gal") is None:
        rec["volume_text"] = amt
    notes["state"] = "MN"
    notes["time_zone"] = ZONE
    county = point_county(rec.get("lat"), rec.get("lon"))
    if county:
        notes["county"] = county
