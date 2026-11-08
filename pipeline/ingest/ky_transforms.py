"""Kentucky hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

ky_hab_record: the Division of Water's HAB Viewer layer (data/sources/ky-dow-hab-viewer.yaml). Each row is one
observation point's current status: HABSTATUS (Warning, Below, NoDetect; the block keeps the advisory levels only),
HABNAME (the water), HABSTATDES (the Division's text: the advisory issued and the toxin results with their sample
dates) and HABSTART and HABEND (dates). The hook writes the advisory text in the Division's words, the record's clock
(raw.time_zone from the point: zones.zone_for, Eastern or the forty-one Central-time counties of 49 CFR 71.5(c)), and
advisory_lifted when the Division gives an end, and writes a day-precision date as the bare date (the day it is in
the point's own zone); it never sets a coordinate.
"""
from __future__ import annotations

import zones
from ingest.generic import fieldmap as F

WINDOW_BASIS = ("Kentucky Division of Water HAB Viewer: in effect while the Division's map shows the point under an "
                "advisory status; the Division sets no fixed period")
STARTED_BASIS = ("started_at is the point's HABSTART date as the Division gives it (the start of the status shown); "
                 "the advisory is announced after the sample's results")


@F.hook
def ky_hab_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    level = F.clean(row.get("HABSTATUS"))
    text = F.clean(row.get("HABSTATDES"))
    rec["advice_text"] = (f"Kentucky Division of Water, harmful algal bloom status {level}"
                          + (f": {text}" if text else ".")) if level else None
    rec["advice_window_basis"] = WINDOW_BASIS
    notes["_started_basis"] = STARTED_BASIS
    tz = zones.zone_for("KY", rec.get("lat"), rec.get("lon"))
    if tz:
        notes["time_zone"] = tz
    end = notes.get("_end_while_ongoing")       # the generic map holds an end back from an active status
    if end and rec.get("status") == "advisory_active" and str(end)[:10] <= str(ctx.fetched_at)[:10]:
        rec["ended_at"] = end                   # the Division's own end (HABEND): the advisory was lifted
        rec["status"] = "advisory_lifted"
    for k in ("started_at", "ended_at"):       # a date is a date: its day ends in the point's own zone (raw.time_zone)
        if rec.get(k) and rec.get("time_precision") == "day" and "T" in str(rec[k]):
            rec[k] = str(rec[k])[:10]
