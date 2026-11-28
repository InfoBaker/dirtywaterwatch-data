"""MSDGC public Power BI CSO Activity Map, captured by the hourly refresh.

The publish-to-web resource key identifies the public report (no sign-in). Two
complete 5000-row queries join by facility_id. Malformed/limited answers fail
closed; complete matching inventories may grow or shrink without losing history.
Raw responses are retained without default redaction.

Only CSO assets seen Currently Active open suspected-overflow records. Starts
and stops are observation bounds, not exact discharge times (precision poll).
Newer Recently Active observations from every known facility ID of an outfall
say water levels returned to normal and close its open event. Unavailable, flooded,
missing and stale sites never end it. The 72-hour timer is retained, never subtracted to invent an end. Recent-only first
reads and RTC/HRT assets remain snapshot evidence, not newly dated CSO events.

Numeric source dates carry local wall time, interpreted in America/New_York;
seconds retained, interpretation labelled. Ambiguous/nonexistent DST hours fail
rather than silently choose an offset. Query response time, fetch time, source
update and observation bounds remain separate; no receipt/publication invented.

Registry: exact CSO number in MSD permits, checked within 250 m where both have
outfall points. Numbered CSOs use OH0105457 in the current registry. Treatment
permits OH0025461/OH0025453/OH0025470 link separately via the published sewershed;
a sewershed is not a receiving water. Only the matched registry supplies water.

Archive: data/build/oh-msdgc-cso-state.json. Keep across refreshes. --out isolates
state beside that output; --file replays {states, info} and requires --out.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, EVENTS_DIR, HEADERS, error_detail, error_text, event,
                    load_outfall_registry, now_iso, outfall_number, read_json,
                    save_raw, write_events, write_json)

SOURCE_ID = 'oh-msdgc-cso-activity-map'
URL = 'https://msdgc.org/programs/cso-notification-program/'
API = 'https://wabi-us-north-central-k-primary-api.analysis.windows.net/public/reports/querydata?synchronous=true'
RESOURCE_KEY = '180b341d-826b-4829-9bc2-0bf9cc0054c7'  # public report id, not a credential
STATE_PATH = BUILD_DIR / 'oh-msdgc-cso-state.json'
AUTHORITY = 'Metropolitan Sewer District of Greater Cincinnati'
TZ_NAME = 'America/New_York'
TZ = ZoneInfo(TZ_NAME)
STATE_FIELDS = ['facility_id', 'Current State', 'timestamp', 'Site Status', 'Overflow Timer', 'Active Status', 'State']
INFO_FIELDS = ['facility_id', 'asset_type', 'facility_name', 'facility_name_edmr', 'watershed',
               'sewershed', 'latitude', 'longitude', 'event_trigger', 'include_in_cso_dashboard', 'raingauge_name']
PERMITS = {'OH0105457', 'OH0025461', 'OH0025453', 'OH0025470'}
PLANTS = {'Mill Creek': 'OH0025461', 'Little Miami': 'OH0025453', 'Muddy Creek': 'OH0025470'}
PERMIT_URL = ('https://muraprod.msdgc.org/sites/default/assets/downloads/doing_business/'
              'capital_project_resource_library/Permits/PTI_Information_for_MSD_Treatment_Facilities.pdf')
WORDS = {
    'Currently Active': 'Remote monitoring indicates a CSO may be occurring at this location.',
    'Recently Active': ('Remote monitoring indicates a CSO may have occurred within the previous 72 hours, '
                        'but water levels have returned to a normal elevation.'),
    'Flooded': 'The local creek or river level is elevated and may be entering the combined sewer system at this location',
    'Data Unavailable': ('The CSO outfall was in an active or flooded state within the last 72 hours, '
                         'but data is no longer accessible, so the status is unknown.'),
}
ADVICE = ('The public should avoid contact with impacted streams or rivers for at least 72 hours after a rainfall '
          'or after water levels have returned to normal.')


def query(table: str, fields: list[str]) -> dict:
    selects = [{'Column': {'Expression': {'SourceRef': {'Source': 's'}}, 'Property': f}, 'Name': f's.{f}'}
               for f in fields]
    return {'version': '1.0.0', 'queries': [{'Query': {'Commands': [{'SemanticQueryDataShapeCommand': {
        'Query': {'Version': 2, 'From': [{'Name': 's', 'Entity': table, 'Type': 0}], 'Select': selects},
        'Binding': {'Primary': {'Groupings': [{'Projections': list(range(len(fields)))}]},
                    'DataReduction': {'DataVolume': 4, 'Primary': {'Window': {'Count': 5000}}}, 'Version': 1}}}]},
        'QueryId': '', 'ApplicationContext': {'DatasetId': 'c9931b94-bc0b-49b5-833c-b5979d3dda8d',
                                             'Sources': [{'ReportId': '', 'VisualId': ''}]}}],
        'cancelQueries': [], 'modelId': 346}


def fetch() -> dict:
    bundle = {}
    with requests.Session() as sess:
        for key, table, fields in [('states', 'CSOs', STATE_FIELDS), ('info', 'CSO_Info', INFO_FIELDS)]:
            r = sess.post(API, json=query(table, fields), timeout=(20, 90),
                          headers={**HEADERS, 'X-PowerBI-ResourceKey': RESOURCE_KEY})
            r.raise_for_status()
            bundle[key] = r.json()
    return bundle


def decode(doc: dict, fields: list[str]) -> list[dict]:
    """Decode complete flat responses, including dictionary/repetition/null encoding."""
    try:
        results = doc['results']
        if len(results) != 1:
            raise ValueError('unexpected query result count')
        data = results[0]['result']['data']
        names = [x['Name'].split('.', 1)[-1] for x in data['descriptor']['Select']]
        if names != fields or len(data['dsr']['DS']) != 1:
            raise ValueError('query schema changed')
        ds = data['dsr']['DS'][0]
        if ds.get('IC') is not True or ds.get('RT') or len(ds['PH']) != 1:
            raise ValueError('incomplete query response')
        dictionaries, schema, previous, rows = ds.get('ValueDicts', {}), None, None, []
        for row in ds['PH'][0]['DM0']:
            schema = row.get('S', schema)
            if not schema or len(schema) != len(fields):
                raise ValueError('missing query row schema')
            cells = iter(row.get('C', []))
            values = []
            for i, col in enumerate(schema):
                if row.get('R', 0) & (1 << i):
                    if previous is None:
                        raise ValueError('repetition without a previous row')
                    v = previous[i]
                elif row.get('Ø', 0) & (1 << i):
                    v = None
                elif col['N'] in row:
                    v = row[col['N']]
                else:
                    v = next(cells)
                values.append(v)
            if next(cells, None) is not None:
                raise ValueError('extra query cells')
            decoded = []
            for v, col in zip(values, schema):
                dn = col.get('DN')
                decoded.append(dictionaries[dn][v] if dn and isinstance(v, int) else v)
            rows.append(dict(zip(fields, decoded)))
            previous = values
        if len(rows) >= 5000:
            raise ValueError('query reached the requested row limit')
        return rows
    except (KeyError, IndexError, TypeError, StopIteration) as exc:
        raise ValueError('unreadable public query response') from exc


def source_time(value) -> str:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('missing or invalid source timestamp')
    naive = datetime(1970, 1, 1) + timedelta(milliseconds=value)
    dt = naive.replace(tzinfo=TZ)
    if dt.utcoffset() != naive.replace(tzinfo=TZ, fold=1).utcoffset():
        raise ValueError('ambiguous or nonexistent Eastern source hour')
    return dt.isoformat()


def rows_of(bundle: dict, previous: dict) -> list[dict]:
    states, infos = decode(bundle['states'], STATE_FIELDS), decode(bundle['info'], INFO_FIELDS)
    indexed = {str(r['facility_id']): r for r in infos}
    ids = [str(r['facility_id']) for r in states]
    if (len(ids) != len(set(ids)) or len(indexed) != len(infos) or set(ids) != set(indexed)
            or not ids):
        raise ValueError('missing, duplicated or truncated site inventory')
    rows = []
    for r in states:
        if r['Current State'] not in {*WORDS, None}:
            raise ValueError('unknown source state')
        source_time(r['timestamp'])
        info = indexed[str(r['facility_id'])]
        if info['asset_type'] not in {'CSO', 'RTC', 'HRT'}:
            raise ValueError('unknown asset type')
        rows.append({**r, 'facility_id': str(r['facility_id']), 'info': info})
    return rows


def physical_site(row: dict) -> tuple:
    """The source's reporting outfall and sewershed, never a proximity guess.

    CSO_Info assigns both 11511001 and 11511034 to CSO-403 / Muddy Creek
    (saved 2026-11-28). The same relationship appears for CSOs 402–406.
    Unknown reporting names or sewersheds keep their facility identity.
    """
    info = row['info']
    name = info.get('facility_name_edmr') or ''
    shed = info.get('sewershed')
    if re.fullmatch(r'CSO-\d{3}', name) and shed in PLANTS:
        return name, shed
    return ('facility', str(row['facility_id']))


def poll(state: dict, rows: list[dict], now: str) -> dict:
    evs, opened, sites = (state.setdefault(k, {}) for k in ('events', 'open', 'sites'))
    counts = {'opened': 0, 'ended': 0, 'continued': 0}
    incoming = {str(r['facility_id']): r for r in rows if r['info']['asset_type'] == 'CSO'}
    known = {unit: s['row'] for unit, s in sites.items()}
    known.update(incoming)
    groups = {}
    for unit, row in known.items():
        groups.setdefault(physical_site(row), []).append(unit)
    for units in groups.values():
        fresh = {u: incoming[u] for u in units if u in incoming
                 and (u not in sites or incoming[u]['timestamp'] > sites[u]['row']['timestamp'])}
        if not fresh:
            continue
        latest = {u: fresh[u] if u in fresh else sites[u]['row'] for u in units}
        keys = {opened[u] for u in units if u in opened}
        cur = min(keys, key=lambda k: (evs[k]['start'], k)) if keys else None
        # Upgrade old per-facility archives without deleting or renaming published records.
        for key in keys - {cur}:
            evs[key]['duplicate_of'] = cur
            evs[cur]['last_active_at'] = max(evs[cur]['last_active_at'], evs[key]['last_active_at'])
        active = [r for r in fresh.values() if r['Current State'] == 'Currently Active']
        if active and cur is None:
            first = min(active, key=lambda r: (r['timestamp'], str(r['facility_id'])))
            at = source_time(first['timestamp'])
            cur = f'{first["facility_id"]}:{at}'
            prior = [sites.get(u) for u in units]
            lower = (min(s['at'] for s in prior) if all(
                s and s['row']['Current State'] == 'Recently Active' for s in prior) else None)
            evs[cur] = {'start': at, 'first_seen_at': now, 'start_row': copy.deepcopy(first),
                        'start_bounds': [lower, at], 'last_active_at': at}
            counts['opened'] += 1
        elif active:
            counts['continued'] += 1
        if cur:
            ev = evs[cur]
            for u in units:
                opened[u] = cur
            if active:
                ev['last_active_at'] = max(ev['last_active_at'], *(source_time(r['timestamp']) for r in active))
            evidence = ev.setdefault('facility_observations', [])
            seen = {(r['facility_id'], r['timestamp']) for r in evidence}
            # Also retain the start rows of any old aliases merged into this event.
            for r in [evs[k]['start_row'] for k in keys] + list(latest.values()):
                if (r['facility_id'], r['timestamp']) not in seen:
                    evidence.append(copy.deepcopy(r))
                    seen.add((r['facility_id'], r['timestamp']))
            # Every known sensor must explicitly show normal levels after the last active
            # observation and still be present. Absence/unavailability never supplies a stop.
            normal = all(u in incoming and latest[u]['Current State'] == 'Recently Active'
                         and source_time(latest[u]['timestamp']) > ev['last_active_at'] for u in units)
            row = max(latest.values(), key=lambda r: (r['timestamp'], str(r['facility_id'])))
            at = source_time(row['timestamp'])
            if normal:
                ev.update(end=at, end_bounds=[ev['last_active_at'], at], stop_row=copy.deepcopy(row),
                          stop_rows=copy.deepcopy(list(latest.values())))
                for u in units:
                    del opened[u]
                counts['ended'] += 1
            ev.update(row=copy.deepcopy(row), source_updated_at=at, last_seen_at=now)
            # Existing alias pages remain reachable and get the same observed bounds.
            for key in [k for k, v in evs.items() if v.get('duplicate_of') == cur]:
                for field in ('end', 'end_bounds', 'stop_row', 'stop_rows', 'row', 'source_updated_at',
                              'last_seen_at', 'last_active_at', 'facility_observations'):
                    if field in ev:
                        evs[key][field] = copy.deepcopy(ev[field])
        for unit, row in fresh.items():
            sites[unit] = {'at': source_time(row['timestamp']), 'seen_at': now, 'row': copy.deepcopy(row)}
    return counts


def tie(info: dict, registry: list[dict]) -> dict | None:
    match = re.fullmatch(r'CSO-(\d{3})', info.get('facility_name_edmr') or '')
    if not match:
        return None
    candidates = [r for r in registry if r.get('npdes_permit') in PERMITS
                  and r.get('outfall_kind') == 'cso'
                  and not str(r.get('outfall_status') or '').startswith('CLS')
                  and outfall_number(r.get('outfall')) == outfall_number(match[1])]
    if len(candidates) != 1:
        return None
    row = candidates[0]
    if row.get('coords_from') == 'permitted_feature' and row.get('lat') is not None and info.get('latitude'):
        lat, lon = float(info['latitude']), float(info['longitude'])
        distance = 6371000 * math.hypot(math.radians(lat - row['lat']),
                                      math.radians(lon - row['lon']) * math.cos(math.radians(lat)))
        if distance > 250:
            return None
    return row


def to_record(key: str, ev: dict, registry: list[dict]) -> dict:
    row, info = ev['row'], ev['row']['info']
    outfall = tie(info, registry)
    water = (outfall.get('receiving_water_echo') or outfall.get('water_name')) if outfall else None
    lat = float(info['latitude']) if info.get('latitude') else None
    lon = float(info['longitude']) if info.get('longitude') else None
    if lat is None or lon is None or not (38 < lat < 41 and -86 < lon < -83):
        lat = lon = None
    raw = {'state': 'OH', 'row': row, 'start_row': ev['start_row'], 'source_status': row['Current State'],
           'source_words': WORDS.get(row['Current State']), 'confirmation_method': 'suspected overflow; remote monitoring',
           'time_zone': TZ_NAME, 'time_note': 'We interpret the source’s numeric wall-clock dates in Eastern time.',
           'start_basis': 'We first observed an active state at this source update; the overflow may have begun earlier.',
           'start_bounds': ev['start_bounds'], 'start_precision': 'poll',
           'facility_observations': ev.get('facility_observations', [ev['start_row'], row]),
           'identity_basis': ('We group facility IDs with the same reporting CSO name and sewershed '
                              'in MSDGC’s CSO_Info table.'), 'identity_source': URL,
           '_first_seen_at': ev['first_seen_at'], '_last_seen_in_source': ev['last_seen_at'],
           'treatment_plant_permit': PLANTS.get(info.get('sewershed')), 'treatment_plant_permit_source': PERMIT_URL,
           'timer_note': 'The source’s Overflow Timer is retained as given; we do not use it as an event start or end.',
           'registry_record': ({'npdes_permit': outfall['npdes_permit'], 'outfall': outfall['outfall'],
                                'source_url': outfall.get('echo_url'), 'receiving_water': water} if outfall else None),
           'water_basis': 'Receiving water from the matched outfall registry.' if water else None}
    if ev.get('end'):
        raw.update(ended_at_precision='poll', end_bounds=ev['end_bounds'], stop_row=ev['stop_row'],
                   stop_rows=ev.get('stop_rows', [ev['stop_row']]),
                   end_basis='The source showed water levels had returned to normal by this update; the exact stop is not given.')
    else:
        raw['end_note'] = 'No stop has been observed; the event remains ongoing.'
    return event(source_id=SOURCE_ID, source_record_id=key, event_type='cso',
                 duplicate_of=f'{SOURCE_ID}:{ev["duplicate_of"]}' if ev.get('duplicate_of') else None,
                 status='ended' if ev.get('end') else 'ongoing', discharger_name=AUTHORITY,
                 npdes_permit=outfall['npdes_permit'] if outfall else None,
                 outfall_id=outfall['outfall'] if outfall else None,
                 outfall_name=info.get('facility_name_edmr'), waterbody_text=water,
                 water_slugs=[outfall['water_slug']] if outfall and outfall.get('water_slug') else [],
                 water_match='outfall_registry' if outfall else 'none',
                 lat=lat, lon=lon, coord_source='source' if lat is not None else None,
                 started_at=ev['start'], ended_at=ev.get('end'), time_precision='poll',
                 source_updated_at=ev['source_updated_at'], fetched_at=ev['last_seen_at'],
                 authority=AUTHORITY, material='combined sewage and stormwater', advice_text=ADVICE,
                 advice_window_hours=72,
                 advice_window_basis=(f'{AUTHORITY}: “{ADVICE}” We count the 72 hours from the observed '
                                      'return to normal water levels; the exact discharge stop is not given.'),
                 source_url=URL, raw=raw)


def link_records(records: list[dict], others: list[dict]) -> None:
    """Uniquely identified dated CSOs within a witnessed activation interval only.

    Monthly reports are context, never equivalent events or later event volumes.
    A first active read without a lower bound cannot identify another source's start.
    """
    for e in records:
        if e.get('duplicate_of'):
            continue
        lower, upper = e['raw']['start_bounds']
        matches, monthly = [], []
        for other in others:
            if (not e.get('npdes_permit') or not e.get('outfall_id') or other.get('duplicate_of')
                    or other.get('source_id') == SOURCE_ID or other.get('event_type') != 'cso'
                    or other.get('npdes_permit') != e['npdes_permit']
                    or outfall_number(other.get('outfall_id')) != outfall_number(e['outfall_id'])):
                continue
            start = other.get('started_at')
            if other.get('time_precision') == 'month':
                if start and start[:7] == e['started_at'][:7]:
                    monthly.append(other['event_id'])
                continue
            if lower and start and other.get('time_precision') in {'minute', 'second'}:
                try:
                    if datetime.fromisoformat(lower) < datetime.fromisoformat(start) <= datetime.fromisoformat(upper):
                        matches.append(other['event_id'])
                except ValueError:
                    continue
        if len(matches) == 1:
            e['duplicate_of'] = matches[0]
            e['raw']['_other_source_record'] = matches
            e['raw']['duplicate_basis'] = 'Same permitted outfall and a unique reported start within our observed activation interval.'
        if monthly:
            e['raw']['monthly_context_records'] = sorted(monthly)


def run(bundle: dict, now: str, state_path: Path, registry=None, others=None) -> tuple[list[dict], dict]:
    state = read_json(state_path, {}) or {}
    rows = rows_of(bundle, state)
    counts = poll(state, rows, now)
    state['last_poll'] = {'at': now, 'sites': len(rows), 'states': dict(Counter(r['Current State'] or 'Unknown' for r in rows)),
                          'assets': dict(Counter(r['info']['asset_type'] for r in rows)), **counts}
    state['snapshot'] = rows
    registry = load_outfall_registry() if registry is None else registry
    records = [to_record(k, ev, registry) for k, ev in state['events'].items()]
    link_records(records, others or [])
    records.sort(key=lambda e: (e['started_at'], e['event_id']))
    write_json(state_path, state)
    return records, {'registry_ids': [SOURCE_ID], 'url': URL, 'query_url': API, 'poll': state['last_poll'],
                     'query_response_times': {k: bundle[k]['results'][0]['result']['data'].get('timestamp')
                                              for k in ('states', 'info')},
                     'history_note': 'History starts with our first active observations. The map provides no event archive.'}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--file'); ap.add_argument('--out')
    a = ap.parse_args(argv)
    if a.file and not a.out:
        ap.error('--file requires --out')
    out = Path(a.out) if a.out else None
    state_path = out.with_suffix('.state.json') if out else STATE_PATH
    try:
        bundle = json.loads(Path(a.file).read_text()) if a.file else fetch()
        others = []
        if not a.file:
            for path in sorted(EVENTS_DIR.glob('*.json')):
                if path.stem != SOURCE_ID:
                    others.extend(r for r in (read_json(path, {}) or {}).get('records', [])
                                  if r.get('npdes_permit') in PERMITS and r.get('event_type') == 'cso')
            save_raw(SOURCE_ID, json.dumps(bundle), 'json')
        records, meta = run(bundle, now_iso(), state_path, others=others)
        write_events(SOURCE_ID, records, path=out, meta=meta)
    except (requests.RequestException, ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
        write_events(SOURCE_ID, [], path=out, ok=False, error=error_text(exc))
        print(f'{SOURCE_ID}: FAILED {error_detail(exc)}', file=sys.stderr)
        return 1
    print(f'{SOURCE_ID}: {len(records)} events; {meta["poll"]["sites"]} sites')
    return 0


if __name__ == '__main__':
    sys.exit(main())
