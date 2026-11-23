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
from ingest import lift_dates

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


# A lift is not a listing of the original advisory. Preserve its observed listing boundaries
# through generic history, which otherwise treats every emitted record as freshly listed.
_LISTING_KEYS = ('_unlisted_since', '_missing_from_source_since', '_last_seen_in_source', '_absences')


def _before(a, ap, b, bp, zone, *, same_day=False):
    """Compare timed evidence as aware instants; mixed/day evidence by the local calendar day."""
    if not a or not b:
        return False
    try:
        def parsed(value):
            t = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return t if t.tzinfo else t.replace(tzinfo=ZoneInfo(zone))
        x, y = parsed(a), parsed(b)
        if ap == 'day' or bp == 'day' or len(a) == 10 or len(b) == 10:
            x, y = x.astimezone(ZoneInfo(zone)).date(), y.astimezone(ZoneInfo(zone)).date()
            return x <= y if same_day else x < y
        return x < y
    except (ValueError, TypeError):
        return False


@F.hook
def or_hab_episodes(records: list[dict], ctx: F.Ctx) -> None:
    """Attribute a lift within one retained episode's issue, unlisting and successor boundaries.

    Every still-listed unmatched episode stays open. Historical listing evidence is never refreshed by a lift.
    A replay cannot move a previously attributed lift across a recorded return.
    """
    from copy import deepcopy

    snapshots = ctx.extra.setdefault('or_lift_listing_history', {})
    # Generic history rebuilds active rows; carry dated-lift observations through actual returns.
    previous = {p['event_id']: p for p in ctx.previous_records}
    for r in list(records):
        row = r['raw']['row']
        if F.clean(row.get('AdvisoryStatus')).lower() != 'advisory/precaution lifted':
            p = previous.get(r['event_id'], {})
            prior = p.get('raw', {})
            if prior.get('lift_observations'):
                r['raw']['lift_observations'] = deepcopy(prior['lift_observations'])
            if prior.get('returned_at'):
                r['raw']['returned_at'] = prior['returned_at']
            if p.get('status') == 'advisory_lifted':
                r['raw']['returned_at'] = ctx.fetched_at
            continue
        records.remove(r)
        end, ep = r.get('started_at'), r.get('time_precision')
        zone = r['raw'].get('time_zone') or 'America/Los_Angeles'
        matching = [p for p in ctx.previous_records
                    if row.get('OBJECTID') is not None
                    and (p.get('raw', {}).get('row') or {}).get('OBJECTID') == row['OBJECTID']]

        observations = []
        for p in matching:
            for o in p['raw'].get('lift_observations', []):
                lift_dates.remember(observations, o['date'], o['precision'], o['seen_at'])
        seen_at = lift_dates.remember(observations, end, ep, ctx.fetched_at)

        def latest_start(p):
            starts = [(p['started_at'], p.get('time_precision'))]
            if p['raw'].get('returned_at'):
                starts.append((p['raw']['returned_at'], 'poll'))
            starts += [(a['returned_at'], 'poll') for a in p['raw'].get('_absences', []) if a.get('returned_at')]
            return max(starts, key=lambda s: lift_dates.instant(s[0], zone))

        def follows_start(p):
            start, precision = latest_start(p)
            return lift_dates.follows(end, ep, start, precision, zone, seen_at)

        def eligible(p):
            raw = p.get('raw') or {}
            if (not F.clean(row.get('WaterbodyName')) or raw.get('row', {}).get('WaterbodyName') != row['WaterbodyName']
                    or (p.get('lat'), p.get('lon')) != (r.get('lat'), r.get('lon'))):
                return False
            if not follows_start(p):
                return False
            boundaries = [raw.get('_unlisted_since'), raw.get('_missing_from_source_since')]
            # Completed absences precede the latest return; only a current absence bounds its end.
            if any(b and not _before(end, ep, b, 'minute', zone) for b in boundaries):
                return False
            for other in matching:
                if other['event_id'] == p['event_id']:
                    continue
                if (lift_dates.instant(latest_start(other)[0], zone) > lift_dates.instant(latest_start(p)[0], zone)
                        and follows_start(other)):
                    return False
            return p.get('status') in {'advisory_active', 'advisory_lifted'}

        candidates = [p for p in matching if eligible(p)]
        chosen = candidates[0] if len(candidates) == 1 else None
        if chosen:
            p = chosen
            raw = deepcopy(p['raw'])
            raw.update(r['raw'])
            raw['lift_observations'] = deepcopy(observations)
            if p.get('ended_at') and p['ended_at'] != end:
                raw.setdefault('end_observations', []).append({
                    'ended_at': p['ended_at'], 'precision': p['raw'].get('ended_at_precision'),
                    'row': deepcopy(p['raw']['row']), 'replaced_at': ctx.fetched_at})
            r.update(event_id=p['event_id'], source_record_id=p['source_record_id'], started_at=p['started_at'],
                     time_precision=p['time_precision'], status='advisory_lifted', ended_at=end,
                     authority=p.get('authority'), raw=raw)
            raw.update(ended_at_precision=ep, end_basis="OHA's Issue_Date on its Advisory/Precaution Lifted row",
                       _started_basis=p['raw'].get('_started_basis'))
            for key in ('advisory_noun', '_interval_label'):
                if key in p['raw']:
                    raw[key] = p['raw'][key]
            snapshots[p['event_id']] = {k: deepcopy(p['raw'][k]) for k in _LISTING_KEYS if k in p['raw']}
            records.append(r)
        for p in matching:
            if chosen and p['event_id'] == chosen['event_id']:
                continue
            if (p.get('status') != 'advisory_active' or p['raw'].get('_unlisted_since')
                    or p['raw'].get('_missing_from_source_since')):
                snapshots[p['event_id']] = {k: deepcopy(p['raw'][k]) for k in _LISTING_KEYS if k in p['raw']}
            if any(x['event_id'] == p['event_id'] for x in records):
                continue
            held = deepcopy(p)
            held['raw']['lift_observations'] = deepcopy(observations)
            held['fetched_at'] = ctx.fetched_at
            evidence = {'row': deepcopy(row), 'seen_at': ctx.fetched_at,
                        'basis': 'This lift does not identify this advisory episode; we retain it as separate evidence.'}
            prior = held['raw'].get('lift_evidence')
            if prior and prior['row'] != row:
                held['raw'].setdefault('lift_evidence_history', []).append(prior)
            held['raw']['lift_evidence'] = evidence
            records.append(held)


@F.hook
def or_hab_lift_history(records: list[dict], ctx: F.Ctx) -> None:
    """An attributed lift may revise an end, but cannot erase or refresh an advisory's listing history."""
    snapshots = ctx.extra.get('or_lift_listing_history', {})
    for r in records:
        if r['event_id'] not in snapshots:
            continue
        for k in _LISTING_KEYS:
            r['raw'].pop(k, None)
        r['raw'].update(snapshots[r['event_id']])
