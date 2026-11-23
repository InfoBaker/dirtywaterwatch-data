"""Oregon hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

or_hab_record: the Oregon Health Authority's cyanobacteria (harmful algae bloom) recreational use advisories layer
(data/sources/or-oha-hab-advisories.yaml). Each row is one water OHA has an advisory, a precaution, a result below its
recreational use value or a lifted advisory for, with the issue date, the toxin result and OHA's own words (Details).
The block reads "Advisory", "Precaution" and "Advisory/Precaution Lifted". A lift closes one retained episode
with the same point id and water name, keeping its original id and start; ambiguous matches keep their caution.
A lift without a retained start and "Below Human RUV" samples create no advisory. A precaution is labelled a precaution (authority and
raw.advisory_noun, OHA's own word), never an advisory; both are shown as blooms. A compound name is split for the water
batch (water_names; OHA's name kept as raw._water_as_given). The hook sets the record's clock from the row's county and
point (zones.oregon_zone: Malheur County north of township 35 South is Mountain time), the issue day in that clock, the
level as OHA names it (raw._hab_level), the toxin result, the second county, and OHA's advice text in OHA's words. It
never sets a coordinate or a colour.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import zones
from ingest.generic import fieldmap as F

WINDOW_BASIS = ("Oregon Health Authority: in effect while OHA's layer lists the water under an advisory or a precaution; "
                "OHA lifts it after its own sampling and sets no fixed period")
STARTED_BASIS = "started_at is OHA's issue date for the advisory or precaution now in effect (Issue_Date), a date only"


def water_names(name: str) -> list[str]:
    """OHA's water name as the water records' names (module docstring)."""
    n = re.sub(r"\s+-\s+.*$", "", name or "").strip()
    m = re.match(r"^(North|South|East|West|Middle)\s*&\s*mainstream\s+(.+)$", n, re.I)
    if m:
        return [f"{m.group(1).title()} {m.group(2)}", m.group(2)]
    return [n] if n else []


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
    # OHA keeps its two levels apart (review 2026-11-08 P2-2): a precaution (a bloom confirmed or toxins present below
    # its recreational values; pets at risk) is never labelled an advisory. Both are blooms; the label is OHA's word.
    word = "precaution" if level.lower() == "precaution" else "advisory"
    rec["authority"] = f"Oregon Health Authority (recreational use {word})"
    notes["advisory_noun"] = f"Cyanobacteria {word} (Oregon Health Authority)"
    if word == "precaution":
        notes["_interval_label"] = "Oregon Health Authority's recreational use precaution in effect (not an advisory)"
    # a compound name for the water batch: "Brownlee Reservoir - Powder Arm" is Brownlee Reservoir; "South &
    # mainstream Umpqua River" is the South Umpqua River and the Umpqua River (OHA's name kept in raw)
    name = F.clean(rec.get("waterbody_text"))
    waters = water_names(name)
    if waters and "; ".join(waters) != name:
        notes["_water_as_given"] = name
        rec["waterbody_text"] = "; ".join(waters)
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


@F.hook
def or_hab_episodes(records: list[dict], ctx: F.Ctx) -> None:
    """A lift's Issue_Date dates the lift, not a new advisory. Match one retained spell by source point and name.

    Ambiguous matches retain every caution and the lift evidence. A lift without a retained start creates no spell.
    """
    from copy import deepcopy

    for r in list(records):
        row = r['raw']['row']
        if F.clean(row.get('AdvisoryStatus')).lower() != 'advisory/precaution lifted':
            continue
        records.remove(r)
        end = r.get('started_at')
        matching = [p for p in ctx.previous_records
                      if all((p.get('raw', {}).get('row') or {}).get(k) == row.get(k)
                             for k in ('OBJECTID', 'WaterbodyName'))]
        candidates = [p for p in matching if p.get('started_at') and end and p['started_at'][:10] <= end[:10]
                      and (p.get('status') == 'advisory_active' or p.get('ended_at') == end)]
        if len(candidates) == 1:
            p = candidates[0]
            r.update(event_id=p['event_id'], source_record_id=p['source_record_id'], started_at=p['started_at'],
                     time_precision=p['time_precision'], status='advisory_lifted', ended_at=end,
                     authority=p.get('authority'))
            r['raw'].update(ended_at_precision='day' if len(end) == 10 or end[11:19] == '00:00:00' else 'minute',
                            end_basis="OHA's Issue_Date on its Advisory/Precaution Lifted row",
                            _started_basis=p.get('raw', {}).get('_started_basis'))
            for key in ('advisory_noun', '_interval_label'):
                if key in p['raw']:
                    r['raw'][key] = p['raw'][key]
            records.append(r)
        else:
            # Do not let generic missing-row handling shorten an uncertain spell at this poll.
            for p in matching:
                if p.get('status') != 'advisory_active':
                    continue
                held = deepcopy(p)
                held['fetched_at'] = ctx.fetched_at
                held['raw']['lift_evidence'] = {'row': row, 'seen_at': ctx.fetched_at,
                                               'basis': 'This lift does not identify one retained advisory episode; we keep the caution.'}
                held['raw'].pop('_unlisted_since', None)
                held['raw'].pop('_missing_from_source_since', None)
                records.append(held)
