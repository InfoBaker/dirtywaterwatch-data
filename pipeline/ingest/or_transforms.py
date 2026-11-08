"""Oregon hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

or_hab_record: the Oregon Health Authority's cyanobacteria (harmful algae bloom) recreational use advisories layer
(data/sources/or-oha-hab-advisories.yaml). Each row is one water OHA has an advisory, a precaution, a result below its
recreational use value or a lifted advisory for, with the issue date, the toxin result and OHA's own words (Details).
The block keeps only "Advisory" and "Precaution" (OHA issues both); "Below Human RUV" and "Advisory/Precaution Lifted"
are no current advisory, never a record (grey: no report). The hook sets the record's clock from the row's county and
point (zones.oregon_zone: Malheur County north of township 35 South is Mountain time), the issue day in that clock, the
level as OHA names it (raw._hab_level), the toxin result, the second county, and OHA's advice text in OHA's words. It
never sets a coordinate or a colour.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import zones
from ingest.generic import fieldmap as F

WINDOW_BASIS = ("Oregon Health Authority: in effect while OHA's layer lists the water under an advisory or a precaution; "
                "OHA lifts it after its own sampling and sets no fixed period")
STARTED_BASIS = "started_at is OHA's issue date for the advisory or precaution now in effect (Issue_Date), a date only"


@F.hook
def or_hab_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    county = F.clean(row.get("County_1"))
    zone = zones.oregon_zone(rec.get("lat"), rec.get("lon"), county or None)
    notes["state"], notes["time_zone"] = "OR", zone
    if county:
        notes["county"] = county
    c2 = F.clean(row.get("County_2"))
    if c2:
        notes["county_2"] = c2
    # Issue_Date is a calendar day stored as Pacific midnight (an epoch at 07:00 or 08:00 UTC, which the field map's
    # midnight rule, UTC midnight, does not see): a Pacific midnight is that day, precision day, in the record's own
    # clock; any other time (two rows on 2026-11-07) is kept as a time
    v = rec.get("started_at")
    if isinstance(v, str) and len(v) >= 19 and v[11:19] == "00:00:00":
        rec["started_at"] = datetime(int(v[:4]), int(v[5:7]), int(v[8:10]), tzinfo=ZoneInfo(zone)).isoformat()
        rec["time_precision"] = "day"
    level = F.clean(row.get("AdvisoryStatus"))
    notes["_hab_level"] = level
    details = F.clean(row.get("Details"))
    rec["advice_text"] = (f"Oregon Health Authority recreational use {level.lower() or 'advisory'}"
                          + (f": {details}" if details else "."))
    rec["advice_window_basis"] = WINDOW_BASIS
    toxin, lvl = F.clean(row.get("Toxin")), F.clean(row.get("ToxinLevel"))
    if toxin or lvl:
        notes["_toxin"] = f"{toxin or 'toxin'}: {lvl or 'no value given'}"
    if F.clean(row.get("Above_PetRUV")):
        notes["_above_pet_ruv"] = F.clean(row.get("Above_PetRUV"))
    link = F.clean(row.get("AdvisoryLink"))
    if link:
        notes["_advisory_link"] = link
    notes["_started_basis"] = STARTED_BASIS
