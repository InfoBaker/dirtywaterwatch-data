"""PA EPA ECHO ICIS-NPDES single-event violations, following RI DFR field conventions.

Hourly refresh checks the ZIP's validators; range-read only SE violations and SICs
when changed. No permit census limit. D0011 and generic bypass codes require a 4952
sewerage SIC; explicit SSO codes establish sewage. Dates are local calendar days, not times.
Violation closure dates stay in source_end_date, not discharge ended_at: the live
ALCOSAN record closes July 17 although its discharge ended March 6. No volume,
cause, receiving water, publication date or receipt date is invented. Public comments
are preserved. Code descriptions describe violations, not causes.

Each violation ID stays a record. Our permit/day grouping suppresses multiple codes
for one reported occurrence, with its basis and links. Local utility links require
compatible evidence; same-day CSO/SSO and poll matches remain possible only. Missing
historical rows and failed reads retain prior records. --from-raw replays the last
successful snapshot. PA only; the ZIP helper and row filter can serve other states.
"""
from __future__ import annotations
import csv
import io
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests
from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, ROOT, error_detail, event,
                    now_iso, read_json, save_raw, write_events, write_json)
from ingest.echo_zip import RemoteZip
from build.status import norm_oid, waters_differ

SOURCE_ID = 'pa-echo-violations'
ZIP_URL = 'https://echo.epa.gov/files/echodownloads/npdes_downloads.zip'
DICTIONARY_URL = 'https://echo.epa.gov/tools/data-downloads/icis-npdes-download-summary'
CACHE_PATH = BUILD_DIR / 'pa-echo-violations-cache.json'
TZ = ZoneInfo('America/New_York')
CODES = {'F024S': 'sso', 'A0020': 'sso', 'F036S': 'bypass', 'A0011': 'bypass'}
SE_MEMBER = 'NPDES_SE_VIOLATIONS.csv'
SIC_MEMBER = 'NPDES_SICS.csv'
LOCAL_SOURCES = ('pa-alcosan', 'pa-erie', 'pa-phila-csocast')
ALCOSAN_POWER_OUTAGE = ('pa-alcosan:news-2026-03-07-'
                       'advisory-issued-following-power-outage-and-river-discharge')
REQUIRED = {'NPDES_ID', 'NPDES_VIOLATION_ID', 'VIOLATION_TYPE_CODE', 'VIOLATION_CODE',
            'VIOLATION_DESC', 'SINGLE_EVENT_VIOLATION_DATE', 'SINGLE_EVENT_END_DATE',
            'SINGLE_EVENT_VIOLATION_COMMENT'}


def csv_rows(z, member, required):
    with z.open(member) as stream:
        reader = csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig', newline=''), strict=True)
        if not required <= set(reader.fieldnames or []):
            raise ValueError('EPA CSV is missing required columns')
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('EPA CSV has an incomplete row')
            yield row


def selected_row(row, sewerage):
    """Generic bypass and unpermitted-discharge codes alone do not establish sewage."""
    code = row.get('VIOLATION_CODE')
    return row.get('VIOLATION_TYPE_CODE') == 'S' and (
        code in ('F024S', 'A0020') or
        code in ('F036S', 'A0011', 'D0011') and row.get('NPDES_ID') in sewerage)


def select_rows(violations, sics, state='PA'):
    """Explicit SSOs; generic bypasses and D0011 require SIC 4952 (any SIC slot)."""
    sewerage = {r['NPDES_ID'] for r in sics if r['NPDES_ID'].startswith(state) and r['SIC_CODE'] == '4952'}
    selected, stats, seen = [], Counter(), {}
    if not sewerage:
        raise ValueError('EPA SIC file contains no sewerage permits for the state')
    for row in violations:
        if not row['NPDES_ID'].startswith(state):
            continue
        stats['state_violation_rows'] += 1
        if not selected_row(row, sewerage):
            continue
        vid = row['NPDES_VIOLATION_ID']
        if not vid or not row['NPDES_ID']:
            raise ValueError('EPA violation is missing its identity')
        if vid in seen:
            if row != seen[vid]:
                raise ValueError('EPA violation ID has conflicting rows')
            stats['identical_rows_skipped'] += 1
            continue
        seen[vid] = row
        selected.append(row)
    if not selected:
        raise ValueError('EPA file contains no selected state violations')
    stats['selected_rows'] = len(selected)
    stats['sewerage_permits'] = len(sewerage)
    return selected, dict(stats)


def fetch_snapshot(from_raw=False):
    cached = read_json(CACHE_PATH, {}) or {}
    if from_raw:
        if not cached.get('rows'):
            raise ValueError('no previous EPA snapshot')
        return cached
    with requests.Session() as session:
        session.headers.update(HEADERS)
        head = session.head(ZIP_URL, headers={'Accept-Encoding': 'identity'}, timeout=(20, 60), allow_redirects=True)
        head.raise_for_status()
        size = int(head.headers['Content-Length'])
        etag, modified = head.headers.get('ETag'), head.headers.get('Last-Modified')
        if size <= 0 or size > 2_000_000_000 or not (etag or modified):
            raise ValueError('EPA ZIP size or validators missing')
        identity = {'size': size, 'etag': etag, 'last_modified': modified}
        if cached.get('rows') and cached.get('sic_rows') and all(cached.get(k) == v for k, v in identity.items()):
            return cached
        remote = RemoteZip(session, ZIP_URL, size, etag, modified)
        with zipfile.ZipFile(remote) as z:
            for member in (SE_MEMBER, SIC_MEMBER):
                if z.getinfo(member).file_size > 500_000_000:
                    raise ValueError('EPA ZIP member exceeds read limit')
            sics = [r for r in csv_rows(z, SIC_MEMBER, {'NPDES_ID', 'SIC_CODE'}) if r['NPDES_ID'].startswith('PA')]
            selected, stats = select_rows(csv_rows(z, SE_MEMBER, REQUIRED), sics)
        permits = {r['NPDES_ID'] for r in selected}
        snapshot = {**identity, 'url': ZIP_URL, 'read_at': now_iso(), 'rows': selected,
                    'sic_rows': [r for r in sics if r['NPDES_ID'] in permits],
                    'stats': {**stats, 'downloaded_bytes': remote.downloaded}}
        # The selected source rows retain every source field, including comments.
        import json
        save_raw(SOURCE_ID, json.dumps(snapshot, ensure_ascii=False), 'json')
        write_json(CACHE_PATH, snapshot)
        return snapshot


def registry():
    result = {}
    for path in (ROOT / 'research' / 'pa' / 'dischargers.json', DATA_DIR / 'dischargers.json'):
        for row in read_json(path, []) or []:
            permit = row.get('npdes_permit')
            if permit and permit.startswith('PA'):
                result[permit] = row
    return result


def day_iso(value):
    return datetime.strptime(value, '%m/%d/%Y').replace(tzinfo=TZ).isoformat() if value else None


def normalize(rows, fetched, previous, operators, modified=None, sic_rows=()):
    updated = parsedate_to_datetime(modified).isoformat() if modified else None
    sics = defaultdict(list)
    for row in sic_rows:
        sics[row['NPDES_ID']].append(row)
    sewerage = {permit for permit, evidence in sics.items() if any(r['SIC_CODE'] == '4952' for r in evidence)}
    records = []
    for row in rows:
        # Apply current scope to old snapshots too, including unchanged HEADs and --from-raw.
        if not selected_row(row, sewerage):
            continue
        vid, permit = row['NPDES_VIOLATION_ID'], row['NPDES_ID']
        old = previous.get(f'{SOURCE_ID}:{vid}', {})
        problems = []
        try:
            start = day_iso(row['SINGLE_EVENT_VIOLATION_DATE'])
            if start is None:
                problems.append('EPA gives no violation start date')
        except ValueError:
            start = None
            problems.append('EPA violation start date could not be parsed')
        op = operators.get(permit, {})
        # One historical PA comment names a water. Read this explicit source sentence
        # rather than using the plant's treated-effluent receiving water for an SSO.
        water = re.fullmatch(r'Leak at (manhole \d+) into ([A-Za-z][A-Za-z .\'-]*?)\.?',
                             row.get('SINGLE_EVENT_VIOLATION_COMMENT', '').strip())
        raw = {
            'row': dict(row), 'time_zone': str(TZ), 'source_end_date': row['SINGLE_EVENT_END_DATE'] or None,
            'sic_rows': sics.get(permit, []),
            'source_end_text': 'End of the recorded violation; the discharge end is not confirmed.',
            'time_basis': 'Violation start date, to the day. We encode the local date at midnight; no clock time is reported.',
            'note': 'Reported to regulators and published in EPA ECHO; not a public advisory.',
            'water_basis': ('The receiving water is named in the violation comment.' if water else
                            'This violation names no receiving water or discharge location.'),
            'overflow_point': water.group(1) if water else None,
            '_placement': 'named_water_only',
            '_first_seen_at': (old.get('raw') or {}).get('_first_seen_at') or fetched,
            'archive_last_modified': modified,
            'source_updated_at_basis': 'Last-Modified of the EPA download archive, not a per-record update time.',
            'selection_basis': ('Sewerage SIC 4952 and discharge without a valid permit; overflow type is not stated.'
                                if row['VIOLATION_CODE'] == 'D0011' else
                                'Sewerage SIC 4952 and an EPA single-event bypass violation code.'
                                if row['VIOLATION_CODE'] in ('A0011', 'F036S') else
                                'EPA single-event sanitary sewer overflow violation code.'),
        }
        records.append(event(source_id=SOURCE_ID, source_record_id=vid,
            event_type=CODES.get(row['VIOLATION_CODE'], 'unknown') if start else 'unknown', status='unknown',
            npdes_permit=permit, discharger_id=op.get('id'), discharger_name=op.get('name'),
            waterbody_text=water.group(2) if water else None,
            started_at=start, ended_at=None, time_precision='day', fetched_at=fetched, source_updated_at=updated,
            authority='U.S. EPA ECHO (reported to regulators)',
            source_url=f'https://echo.epa.gov/detailed-facility-report?fid={permit}', raw=raw,
            parse_error='; '.join(problems) or None))
    return records


def local_day(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(TZ).date().isoformat()
    except ValueError:
        return None


def compatible_location(a, b):
    """Missing place evidence is compatible; contradictory stated places are not."""
    if waters_differ(a, b):
        return False
    for key in ('outfall_id', 'outfall_name'):
        if a.get(key) and b.get(key) and norm_oid(a[key]) != norm_oid(b[key]):
            return False
    ap, bp = (a.get('raw') or {}).get('overflow_point'), (b.get('raw') or {}).get('overflow_point')
    return not (ap and bp and norm_oid(ap) != norm_oid(bp))


def location_groups(records):
    """Compare every member, so an unspecified place cannot bridge conflicting ones."""
    groups = []
    # Locate the specific reports first; an ambiguous unlocated report remains separate.
    ordered = sorted(records, key=lambda r: (
        -sum(bool(v) for v in (r.get('waterbody_text'), r.get('outfall_id'), r.get('outfall_name'),
                              (r.get('raw') or {}).get('overflow_point'))), r['source_record_id']))
    for r in ordered:
        matches = [g for g in groups if all(compatible_location(r, other) for other in g)]
        if len(matches) == 1:
            matches[0].append(r)
        else:
            groups.append([r])
    return groups


def link_records(records, local):
    """Permit/day counting with compatible places; links never borrow a time or volume."""
    groups = defaultdict(list)
    local = [r for r in local if r.get('source_id') in LOCAL_SOURCES and not r.get('duplicate_of')]
    for r in records:
        r['duplicate_of'] = None
        for key in ('_other_source_record', '_duplicate_basis', 'possible_matches', 'count_basis'):
            r['raw'].pop(key, None)
        if r.get('started_at'):
            groups[r['npdes_permit'], local_day(r['started_at'])].append(r)
    plans = []
    for (permit, day), reports in groups.items():
        for group in location_groups(reports):
            plans.append((permit, day, group))
    matches = []
    for permit, day, group in plans:
        # Prefer the explicit overflow type over broad D0011; stable ID is the tie-breaker.
        group.sort(key=lambda r: (r['event_type'] == 'unknown', r['source_record_id']))
        primary = group[0]
        if len(group) > 1:
            primary['raw']['count_basis'] = (
                'We count violation codes for the same permit and start day with compatible reported locations '
                'as one occurrence.')
        candidates = [n for n in local if n.get('npdes_permit') == permit and local_day(n.get('started_at')) == day]
        confirmed = [n for n in candidates if n.get('event_type') == primary['event_type'] != 'unknown'
                     and n.get('time_precision') not in ('poll', 'bound')
                     and all(compatible_location(r, n) for r in group)]
        # Independently checked against ALCOSAN's named power-outage notice. ECHO uses
        # the notice's calendar date, one day after the operator's event date.
        if any(r['source_record_id'] == '3687608730' for r in group) and permit == 'PA0025984' and day == '2026-03-07':
            confirmed = [n for n in local if n['event_id'] == ALCOSAN_POWER_OUTAGE
                         and n.get('npdes_permit') == permit and n.get('event_type') == 'bypass'
                         and local_day(n.get('started_at')) == '2026-03-06'
                         and n.get('time_precision') not in ('poll', 'bound')
                         and all(compatible_location(r, n) for r in group)]
        matches.append((group, candidates, confirmed))
    # A utility report without a location cannot absorb distinct EPA location groups.
    uses = Counter(n['event_id'] for _, _, confirmed in matches for n in confirmed)
    for group, candidates, confirmed in matches:
        primary = group[0]
        target = confirmed[0] if len(confirmed) == 1 and uses[confirmed[0]['event_id']] == 1 else None
        if target:
            primary['duplicate_of'] = target['event_id']
            primary['raw']['_other_source_record'] = target['event_id']
            primary['raw']['_duplicate_basis'] = (
                'We link the ALCOSAN power-outage notice to this violation. The notice dates the discharge March 6, '
                '2026; EPA dates the violation March 7. Both source dates are retained.'
                if target['event_id'] == ALCOSAN_POWER_OUTAGE else
                'We match the same permit, local start date and overflow type with compatible reported locations '
                'to the utility report.')
        for r in group:
            if candidates and not target:
                r['raw']['possible_matches'] = sorted(n['event_id'] for n in candidates)
            if r is primary:
                continue
            r['duplicate_of'] = primary['duplicate_of'] or primary['event_id']
            r['raw']['_other_source_record'] = r['duplicate_of']
            r['raw']['_duplicate_basis'] = ('We count EPA violation codes for the same permit and start day with '
                                           'compatible reported locations as one occurrence.')


def main(argv=None):
    argv = argv or []
    previous = read_json(EVENTS_DIR / f'{SOURCE_ID}.json', {}) or {}
    old = {r['event_id']: r for r in previous.get('records', [])}
    try:
        snapshot = fetch_snapshot(from_raw='--from-raw' in argv)
        records = normalize(snapshot['rows'], snapshot['read_at'], old, registry(), snapshot.get('last_modified'),
                            snapshot.get('sic_rows', []))
        ids = {r['event_id'] for r in records}
        current_sics = defaultdict(list)
        for row in snapshot.get('sic_rows', []):
            current_sics[row['NPDES_ID']].append(row)
        kept = []
        for eid, r in old.items():
            if eid in ids:
                continue
            raw = r.get('raw') or {}
            evidence = current_sics.get(r['npdes_permit'], raw.get('sic_rows', []))
            sewerage = {s['NPDES_ID'] for s in evidence if s['SIC_CODE'] == '4952'}
            # Missing history stays only if it still meets the source's sewage scope.
            if selected_row(raw.get('row') or {}, sewerage):
                kept.append(r)
        for r in kept:
            r['raw'].setdefault('_missing_from_source_since', now_iso())
        records.extend(kept)
        local = [r for sid in LOCAL_SOURCES
                 for r in (read_json(EVENTS_DIR / f'{sid}.json', {}) or {}).get('records', [])]
        link_records(records, local)
        meta = {**snapshot['stats'], 'selected_rows': len(records) - len(kept),
                'url': ZIP_URL, 'member': SE_MEMBER, 'sic_member': SIC_MEMBER,
                'archive_last_modified': snapshot.get('last_modified'), 'snapshot_read_at': snapshot['read_at'],
                'kept_from_previous': len(kept), 'duplicates': sum(bool(r['duplicate_of']) for r in records),
                'by_year': dict(sorted(Counter(r['started_at'][:4] for r in records if r['started_at']).items())),
                'date_dictionary': DICTIONARY_URL}
        write_events(SOURCE_ID, sorted(records, key=lambda r: (r['started_at'] or '', r['event_id']), reverse=True), meta=meta)
    except Exception as exc:
        err = error_detail(exc)
        write_events(SOURCE_ID, [], ok=False, error=err)
        print(f'{SOURCE_ID}: FAILED {err}', file=sys.stderr)
        return 1
    print(f'{SOURCE_ID}: {len(records)} violation records, {meta["duplicates"]} linked copies, {len(kept)} retained')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
