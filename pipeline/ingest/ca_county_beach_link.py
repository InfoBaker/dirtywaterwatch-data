"""Link county beach actions to Beach Watch after all feeds (not a feed).

A copy requires the same county, action type, exact station code (San Diego) or
exact affected-area text (Orange), and the same local issue and reopening days.
Orange chart phases retain their own days for comparison. Differing ends or
placement are related records, never hidden. No sewage discharge is deduplicated against a
beach action: a closure and the spill that caused it are different records.
EPA BEACON's existing post-feed linker runs afterward and can link to these
county sources through its existing state/point/name rules. We preserve each
feed's fetch health and timestamps while updating links, even during outages.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

from common import EVENTS_DIR, read_json, write_json
from ingest.ca_county_beach_common import TZ, day

BEACHWATCH = 'ca-beachwatch-advisories'
SD = 'ca-sdcounty-beachinfo'
OC = 'ca-ocbeachinfo'
COUNTIES = {SD: 'san diego', OC: 'orange'}
MARKER = 'ca_county_beach_link'


def norm(value):
    return re.sub(r'[^a-z0-9]+', '', str(value or '').lower())


def local_day(value):
    if not value:
        return None
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        t = t.replace(tzinfo=TZ)
    return t.astimezone(TZ).date().isoformat()


def preserves_placement(record, target):
    """Suppress only when the target retains the copy's explicit spatial evidence."""
    if record.get('lat') is not None or record.get('lon') is not None:
        if any(record.get(k) != target.get(k) for k in ('lat', 'lon')):
            return False
    if not set(record.get('water_slugs') or []) <= set(target.get('water_slugs') or []):
        return False
    if record.get('stretch') and record['stretch'] != target.get('stretch'):
        return False
    # Old retained aggregates may still be candidates until the chart is reread.
    # Their first area/window cannot stand in for a matching later phase.
    if target.get('source_id') == OC:
        return (norm(record.get('outfall_name')) == norm(target.get('outfall_name'))
                and local_day(record.get('started_at')) == local_day(target.get('started_at'))
                and local_day(record.get('ended_at')) == local_day(target.get('ended_at')))
    return True


def link(state_records, county_records):
    candidates = defaultdict(list)
    for r in county_records:
        sid = r.get('source_id')
        if sid not in COUNTIES or r.get('duplicate_of'):
            continue
        raw = r.get('raw') or {}
        if sid == SD:
            station = ((raw.get('row') or {}).get('Site') or {}).get('StationID')
            keys = [(norm(station), local_day(r.get('started_at')), local_day(r.get('ended_at')))] if station else []
        else:
            phases = [raw['phase']] if raw.get('phase') else raw.get('phases') or []
            keys = [(norm(p['area']), local_day(day(p['date_closed'])), local_day(day(p['date_opened'])) if p.get('date_opened') else None) for p in phases]
            if not phases and r.get('outfall_name'):
                keys = [(norm(r['outfall_name']), local_day(r.get('started_at')), local_day(r.get('ended_at')))]
        for identity, start, end in keys:
            if identity and start:
                candidates[(COUNTIES[sid], r['event_type'], identity, start)].append((r, end))
    counts = Counter()
    for r in state_records:
        raw = r.setdefault('raw', {})
        if raw.get('_county_linker') == MARKER:
            r['duplicate_of'] = None
            for key in ('_county_linker', '_duplicate_basis', 'related_record', 'copy_of', '_other_source_record'):
                raw.pop(key, None)
        if r.get('duplicate_of'):
            continue
        a = raw.get('advisory') or {}
        county = str(a.get('County') or '').lower()
        identities = [a.get('Station_Name')] if county == 'san diego' else [a.get('DescriptionofArea'), r.get('outfall_name')]
        found = {}
        for identity in identities:
            if identity:
                for other, end in candidates.get((county, r['event_type'], norm(identity), local_day(r.get('started_at'))), []):
                    found[other['event_id']] = (other, end)
        if len(found) != 1:
            if found:
                counts['ambiguous'] += 1
            continue
        other, end = next(iter(found.values()))
        raw['_county_linker'] = MARKER
        raw['_other_source_record'] = other['event_id']
        basis = 'The same county, action type, station code or affected area, and local issue date.'
        ends_agree = local_day(r.get('ended_at')) == end
        if ends_agree and preserves_placement(r, other):
            r['duplicate_of'] = other['event_id']
            raw['_duplicate_basis'] = basis + ' The reopening dates agree, or neither source gives one.'
            raw['copy_of'] = {'event_id': other['event_id'], 'source_id': other['source_id'], 'source_url': other['source_url']}
            counts['duplicates'] += 1
        else:
            raw['related_record'] = {'event_id': other['event_id'], 'source_id': other['source_id'],
                                     'source_url': other['source_url'],
                                     'basis': basis + (' The county record does not preserve the same placement and area window; both records remain listed.'
                                                       if ends_agree else ' The reopening dates differ; both records remain listed.')}
            counts['different_placement' if ends_agree else 'different_ends'] += 1
    return counts


def main():
    path = EVENTS_DIR / f'{BEACHWATCH}.json'
    state = read_json(path, {}) or {}
    if not state:
        return 0
    county = [r for sid in COUNTIES for r in (read_json(EVENTS_DIR / f'{sid}.json', {}) or {}).get('records', [])]
    counts = link(state.get('records', []), county)
    state.setdefault('meta', {})['county_links'] = dict(counts)
    write_json(path, state)
    print(f'{BEACHWATCH}: county beach links {dict(counts)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
