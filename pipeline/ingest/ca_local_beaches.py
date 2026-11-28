"""Shared parsing and observation history for California's local beach pages (not a feed).

Unknown starts remain null. The dated publication of a status snapshot can anchor the
advisory display; observed_since and _unlisted_since are explicitly our observations.
Neither an Open flag nor disappearance supplies an agency reopening time.
"""
from __future__ import annotations

import copy
import hashlib
import html
import re

from common import event

TZ = 'America/Los_Angeles'


def text(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]*>', ' ', value or '')).split())


def slug(value):
    return re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')


def station_id(value):
    value = re.split(r'(?i)\s*(?:&|and)\s*nowcast', value)[0]
    value = re.sub(r'\s+', '', value).upper()
    return re.sub(r'^DPH-?0*(\d+)', r'DPH\1', value)


def snapshot(source, rows, updated, previous, fetched, url, authority):
    records = {r['event_id']: copy.deepcopy(r) for r in previous}
    active = {r['raw']['station_id']: r for r in records.values()
              if not r['raw'].get('_unlisted_since')}
    for row in rows:
        sid = row['station_id']
        old = active.get(sid)
        status = row['status']
        on = status not in ('OPEN', 'NO RECENT SAMPLES')
        if old and (not on or old['raw']['source_status'] != status):
            old['raw']['_unlisted_since'] = fetched
            old['raw']['observation_end_basis'] = 'Our first read that no longer showed this status; the source gives no lifting time.'
            old = None
        if not on:
            continue
        if old:
            old['source_updated_at'] = updated
            old['fetched_at'] = fetched
            old['raw'].update(row=row, cause=row.get('cause'), _last_seen_in_source=fetched)
            continue
        key = hashlib.sha256(f'{sid}|{status}|{fetched}'.encode()).hexdigest()[:16]
        kind = {'ADVISORY': 'beach_advisory', 'RAIN ADVISORY': 'rain_advisory', 'CLOSED': 'beach_closure'}.get(status, 'beach_advisory')
        rec = event(source_id=source, source_record_id=f'map-{sid}-{key}', event_type=kind,
                    status='advisory_active', outfall_name=row['name'], waterbody_text=row['name'],
                    lat=row.get('lat'), lon=row.get('lon'), coord_source='source' if row.get('lat') is not None else None,
                    started_at=None, ended_at=None, reported_at=None, published_at=updated,
                    source_updated_at=updated, time_precision=row.get('update_precision', 'day'), fetched_at=fetched,
                    authority=authority, source_url=url, advice_text=row.get('cause') or status,
                    raw={'state': 'CA', 'county': 'Los Angeles', 'time_zone': TZ, 'station_id': sid,
                         'row': row, 'cause': row.get('cause'), 'source_status': status,
                         'observed_since': fetched, '_first_seen_at': fetched, '_last_seen_in_source': fetched,
                         'publication_basis': 'The source dates this status snapshot; it gives no advisory start time.',
                         'observation_basis': 'Our first and last reads of this status are observation bounds.'})
        records[rec['event_id']] = rec
    return list(records.values())
