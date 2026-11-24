"""Kentucky hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

ky_hab_record: the Division of Water's HAB Viewer layer (data/sources/ky-dow-hab-viewer.yaml). Each row is one
observation point's current status: HABSTATUS (Warning, Below, NoDetect; inactive rows supply lift evidence only),
HABNAME (the water), HABSTATDES (the Division's text: the advisory issued and the toxin results with their sample
dates) and HABSTART and HABEND (dates). The hook writes the advisory text in the Division's words, the record's clock
(raw.time_zone from the point: zones.zone_for, Eastern or the forty-one Central-time counties of 49 CFR 71.5(c)), and
advisory_lifted only when an inactive row gives an end or an explicit dated lift in HABSTATDES. It
writes a day-precision date as the bare date (the day it is in the point's own zone); it never sets a coordinate.
"""
from __future__ import annotations

import re

import zones
from ingest.generic import fieldmap as F

LAKE_NAME = re.compile(r"\b(?:lake|reservoir|pond)\b", re.I)
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
    if LAKE_NAME.search(str(row.get("HABNAME") or "")):
        # a bloom on a named lake or reservoir is placed on that water only, never on a stream near the point (final
        # audit 2026-11-08 P2-3: Old Springfield Reservoir sat on Road Run); with no record it keeps its own marker
        notes["_placement"] = "named_water_only"
    tz = zones.zone_for("KY", rec.get("lat"), rec.get("lon"))
    if tz:
        notes["time_zone"] = tz
    end = notes.get("_end_while_ongoing")       # the generic map holds an end back from an active status
    if end and rec.get("status") == "advisory_active":
        notes["source_ended_at"] = str(end)[:10]
        notes["end_conflict"] = "HABEND gives an end while HABSTATUS still lists an active advisory; we keep the caution."
        rec["advice_text"] += f" HABEND: {str(end)[:10]}; HABSTATUS: {level}."
    for k in ("started_at", "ended_at"):       # a date is a date: its day ends in the point's own zone (raw.time_zone)
        if rec.get(k) and rec.get("time_precision") == "day" and "T" in str(rec[k]):
            rec[k] = str(rec[k])[:10]


@F.hook
def ky_hab_episodes(records: list[dict], ctx: F.Ctx) -> None:
    """Inactive samples never create advisories; their explicit lift can close the exact retained point/start."""
    from datetime import datetime

    previous = {p['event_id']: p for p in ctx.previous_records}
    inactive = {'below', 'nodetect', 'no detect', 'none', 'not detected', 'monitored', ''}
    for r in list(records):
        row, raw = r['raw']['row'], r['raw']
        is_inactive = F.clean(row.get('HABSTATUS')).lower() in inactive
        p = previous.get(r['event_id'])
        if is_inactive and not p:
            records.remove(r)
            continue
        end = r.get('ended_at')
        basis = "The Division's HABEND date"
        if not end and is_inactive:
            # The agency currently dates the lift in its sentence while HABEND is empty.
            m = re.search(r'\bRecreational Public Health Advisory lifted (\d{1,2}/\d{1,2}/\d{4})\b',
                          F.clean(row.get('HABSTATDES')), re.I)
            if m:
                try:
                    end = datetime.strptime(m[1], '%m/%d/%Y').date().isoformat()
                except ValueError:
                    end = None
                basis = "The Division's explicit advisory lift date in HABSTATDES"
        if is_inactive and end and r.get('started_at') and r['started_at'][:10] <= str(end)[:10] <= ctx.fetched_at[:10]:
            r.update(status='advisory_lifted', ended_at=str(end)[:10])
            raw.update(ended_at_precision='day', end_basis=basis)
        elif is_inactive and p:
            r.update(status=p['status'], ended_at=p.get('ended_at'))
            raw['end_conflict'] = "The Division lists an inactive sample status without an advisory lift date; we keep the caution."
