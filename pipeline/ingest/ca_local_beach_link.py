"""Reconcile local California beach actions after the hourly feeds (not a feed).

Exact station IDs (or an exact named area for whole-beach closures), compatible action
kinds and the state action's dated interval must contain all local confirmations.
A local reopening must agree to the day. One area can correspond to multiple statewide
station rows; those links are retained and one canonical target suppresses the local
copy. Mere date/proximity similarity to a sewage spill is never a duplicate.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
from pathlib import Path

from common import EVENTS_DIR, read_json, write_json
from ingest.ca_lacounty_beaches import SOURCE_ID as LA, area_key
from ingest.ca_long_beach_water_quality import SOURCE_ID as LB
from ingest.ca_local_beaches import station_id

BEACHWATCH = 'ca-beachwatch-advisories'
CIWQS = 'ca-swrcb-ciwqs-spills-flatfile'


def day(value):
    return str(value or '')[:10]


def action(record):
    return {'beach_advisory': 'warning', 'beach_closure': 'closure', 'sso': 'closure',
            'rain_advisory': 'rain'}.get(record.get('event_type'))


def reconcile(records, state_records, spills):
    result = copy.deepcopy(records)
    for rec in result:
        raw = rec['raw']
        if raw.pop('_local_external_duplicate', False):
            rec['duplicate_of'] = None
            raw.pop('_duplicate_basis', None)
        raw.pop('related_records', None)
        raw.pop('same_action_records', None)
        # Map/notice links inside the LA feed are established before this pass.
        if rec.get('duplicate_of'):
            continue
        area = raw.get('area_key') or raw.get('row', {}).get('area_key') or raw.get('station_id')
        first = day(rec.get('published_at'))
        last = day(rec.get('source_updated_at')) or first
        if not area or not first:
            continue
        matches = []
        for other in state_records:
            if other.get('duplicate_of') or action(other) != action(rec):
                continue
            row = other.get('raw', {}).get('advisory', {})
            sid = station_id(str(row.get('Station_Name') or ''))
            same = sid == area
            if action(rec) == 'closure':
                same = same or area_key(str(row.get('Beach_Name') or '')) == area
            if not same:
                continue
            start, end = day(other.get('started_at')), day(other.get('ended_at'))
            confirmed = day(other.get('raw', {}).get('_table_current_to'))
            if not start or start > first or (end or confirmed or '') < last:
                continue
            local_end = day(rec.get('ended_at') or raw.get('closure_lifted_at'))
            if local_end and local_end != end:
                continue
            matches.append(other)
        if matches:
            # Do not choose among two separate statewide episodes for one station.
            by_station = {}
            for r in matches:
                sid = station_id(str(r['raw']['advisory'].get('Station_Name') or ''))
                by_station.setdefault(sid, []).append(r)
            if all(len(rs) == 1 for rs in by_station.values()):
                matches.sort(key=lambda r: r['event_id'])
                rec['duplicate_of'] = matches[0]['event_id']
                raw['_local_external_duplicate'] = True
                raw['_duplicate_basis'] = 'The same station or named closure area and action; the statewide dated action contains the local notices, with any lifting date agreeing.'
                raw['same_action_records'] = [{'event_id': r['event_id'], 'source_url': r['source_url']} for r in matches]
        # These notices supply no native spill ID. Volume/day/water matches are
        # labelled related evidence only, not an automatic sewage-incident duplicate.
        if rec['event_type'] == 'sso':
            related = []
            for spill in spills:
                if day(spill.get('started_at')) != first or not rec.get('volume_gal'):
                    continue
                if spill.get('volume_gal') != rec['volume_gal']:
                    continue
                water = str(spill.get('waterbody_text') or '')
                if not water or area_key(water) != area:
                    continue
                related.append({'event_id': spill['event_id'], 'source_url': spill['source_url'],
                                'basis': 'Same named water, reported volume and date; the notice has no shared spill identifier, so incident identity remains unconfirmed.'})
            if related:
                raw['related_records'] = related
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0]); ap.add_argument('--events-dir', type=Path, default=EVENTS_DIR)
    args = ap.parse_args(argv)
    state = read_json(args.events_dir / f'{BEACHWATCH}.json', {}) or {}
    spills = read_json(args.events_dir / f'{CIWQS}.json', {}) or {}
    for source in (LA, LB):
        path = args.events_dir / f'{source}.json'; doc = read_json(path, {}) or {}
        if not doc:
            continue
        doc['records'] = reconcile(doc.get('records', []), state.get('records', []), spills.get('records', []))
        # Preserve feed health and fetch times; this pass makes no network observation.
        write_json(path, doc)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
