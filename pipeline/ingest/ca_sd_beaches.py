"""San Diego County's public beach and bay app: hourly current actions.

Read the anonymous OutSystems screen calls used by MainFlow.Home. Versions are
obtained from the public module manifest and component scripts on every read;
no login, saved session, embedded API key or static CSRF token. Aggregate calls
page with StartIndex/MaxRecords and validate each action count against the home
screen. The source projects Event.Id and Site.Id as zero: identities are our
hash of station, action type and the source's issue timestamp, independent of
row order, mutable wording and fetch time. UTC API times are converted to Pacific.

The app's event-specific reason is often blank; station background descriptions
are not current-event evidence. Only explicit source issue/lift times become
started_at/ended_at. A missing row is retained, never implicitly reopened. The
current list is not a historical archive, even when a current action began in
1997. Public record text is kept; the private removal service is applied at write.
Run: python -m ingest.ca_sd_beaches [--file saved.json] [--out events.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

from common import EVENTS_DIR, HEADERS, error_detail, error_text, event, now_iso, read_json, write_events
from ingest.ca_county_beach_common import TZ, digest, retain, spill_volume, text, timestamp

SOURCE_ID = 'ca-sdcounty-beachinfo'
PAGE = 'https://cosdapps.sandiegocounty.gov/sdbeachinfo/'
HOME = 'HomeBlockNew'
NOTICES = 'BlockNotification'
TYPES = {1: 'beach_advisory', 2: 'beach_closure', 3: 'beach_advisory'}


class Client:
    def __init__(self, session):
        self.session = session
        self.scripts = {}
        r = session.get(PAGE, timeout=(15, 45))
        r.raise_for_status()
        csrf = None
        for cookie in session.cookies:
            m = re.search(r'crf=([^;]+)', cookie.value)
            if m:
                csrf = m[1]
                break
        if csrf is None:
            runtime = session.get(PAGE + 'scripts/OutSystems.js', timeout=(15, 45))
            runtime.raise_for_status()
            m = re.search(r'AnonymousCSRFToken="([^"]+)"', runtime.text)
            if not m:
                raise ValueError('public anonymous request mechanism changed')
            csrf = m[1]
        session.headers.update({'X-CSRFToken': csrf})
        r = session.get(PAGE + 'moduleservices/moduleinfo', timeout=(15, 45))
        r.raise_for_status()
        manifest = r.json()
        self.version = manifest['manifest']['versionToken']
        # Source-published entity values, verified against the public model's named constants.
        types = manifest['data']['modules']['dcd3862f-dafa-4a10-9c53-39c021e644fb']['staticEntities']['3443c6d9-74f6-4048-983a-bb5dc9c1037e']
        expected = {'278c7e12-184f-4251-9f5d-126a56439828': '1',
                    'd7313994-3af9-4e9d-98cc-adbcd1801a46': '2',
                    'f18236f4-166a-4cab-b8b2-500bcc472d23': '3'}
        if any(str(types.get(k)) != v for k, v in expected.items()):
            raise ValueError('source action type codes changed')

    def call(self, component, action, variables, inputs):
        if component not in self.scripts:
            r = self.session.get(PAGE + f'scripts/CoSD_Beach_Water_CW.MainFlow.{component}.mvc.js', timeout=(15, 45))
            r.raise_for_status()
            self.scripts[component] = r.text
        endpoint = f'screenservices/CoSD_Beach_Water_CW/MainFlow/{component}/{action}'
        m = re.search(r'"' + re.escape(endpoint) + r'",\s*"([^"]+)"', self.scripts[component])
        if not m:
            raise ValueError('public beach data call changed')
        payload = {'versionInfo': {'moduleVersion': self.version, 'apiVersion': m[1]},
                   'viewName': 'MainFlow.Home', 'screenData': {'variables': variables}, 'inputParameters': inputs}
        r = self.session.post(PAGE + endpoint, json=payload, timeout=(15, 60))
        r.raise_for_status()
        d = r.json()
        if d.get('exception') or (d.get('versionInfo') or {}).get('hasApiVersionChanged'):
            raise ValueError('public beach data call rejected or changed')
        if not isinstance(d.get('data'), dict):
            raise ValueError('public beach answer has no data')
        return d['data']


def aggregate(client, component, action, variables, page_size=200):
    rows, seen = [], set()
    for offset in range(0, 20000, page_size):
        d = client.call(component, action, variables, {'StartIndex': offset, 'MaxRecords': page_size})
        batch = d['List']['List']
        if not isinstance(batch, list):
            raise ValueError('public beach aggregate is not a list')
        fingerprint = json.dumps(batch, sort_keys=True)
        if batch and fingerprint in seen:
            raise ValueError('public beach aggregate repeated a page')
        seen.add(fingerprint)
        rows.extend(batch)
        count = int(d.get('Count', -1))
        if len(batch) < page_size or (count >= 0 and len(rows) >= count):
            if count >= 0 and len(rows) != count:
                raise ValueError('public beach aggregate count mismatch')
            return rows
    raise ValueError('public beach aggregate exceeded page limit')


def fetch(session=None):
    session = session or requests.Session()
    session.headers.update(HEADERS)
    client = Client(session)
    rows, counts = [], {}
    updated = client.call(HOME, 'DataActionGetLastDateTime', {}, {})['LastUpdate']
    for code, counter in [(1, 'GetAdvisoriesCount'), (2, 'GetClosures'), (3, 'GetWarnings')]:
        count_rows = aggregate(client, HOME, 'ScreenDataSet' + counter, {})
        expected = int(count_rows[0]['Count'])
        batch = aggregate(client, NOTICES, 'ScreenDataSetGetEventsList',
                          {'EventTypeId': code, '_eventTypeIdInDataFetchStatus': 1})
        if len(batch) != expected or any(int(r['EventType']['Id']) != code for r in batch):
            raise ValueError('public beach action count or type mismatch')
        rows.extend(batch)
        counts[str(code)] = len(batch)
    return {'rows': rows, 'updated_at': updated, 'counts': counts}


def build(rows, fetched_at, updated_at, previous):
    records = []
    for row in rows:
        site, source = row['Site'], row['Event']
        kind = int(row['EventType']['Id'])
        issue, lift = timestamp(source.get('IssueDateTime')), timestamp(source.get('LiftedDateTime'))
        station = site.get('StationID') or site.get('LocationName')
        key = digest(station, kind, issue)
        description = text(source.get('DescriptionIssue'))
        cause = text(source.get('Reason')) or description or None
        raw = {'row': row, 'cause': cause, 'state': 'CA', 'county': 'San Diego',
               'time_zone': 'America/Los_Angeles', 'collection': 'current',
               '_identity_basis': 'Our key combines the station, action type and source issue time.'}
        if issue and lift and lift < issue:
            raw['_end_not_used'] = 'The source lift time precedes the issue time.'
            lift = None
        volume, volume_text, qualifier = spill_volume(description)
        water = site.get('BeachName') or None
        # An explicit receiving-water clause takes precedence over the affected beach name.
        m = re.search(r'(?i)reached the (.+?)(?: near |[.;]|$)', description)
        if m:
            water = m[1].strip()
        lat, lon = float(site.get('Latitude') or 0), float(site.get('Longitude') or 0)
        if not (32.4 <= lat <= 33.6 and -118 <= lon <= -116):
            lat = lon = None
        dt = datetime.fromisoformat(issue) if issue else None
        record = event(source_id=SOURCE_ID, source_record_id=key,
                       event_type=TYPES.get(kind, 'unknown'),
                       status='advisory_lifted' if lift else 'advisory_active',
                       outfall_name=' - '.join(filter(None, [site.get('BeachName'), site.get('LocationName')])),
                       waterbody_text=water, lat=lat, lon=lon, coord_source='source' if lat is not None else None,
                       started_at=issue, ended_at=lift,
                       time_precision=('second' if dt.second or dt.microsecond else 'minute') if dt else None,
                       source_updated_at=timestamp(updated_at), fetched_at=fetched_at,
                       volume_gal=volume, volume_text=volume_text, estimate_flag=qualifier,
                       authority='San Diego County Department of Environmental Health and Quality',
                       advice_text=description or None, source_url=PAGE, raw=raw,
                       parse_error=None if station and issue and kind in TYPES else 'Source station, issue time or action type is missing.')
        records.append(record)
    return retain(records, previous, fetched_at)


def main(argv=None):
    from build.redact import redact_events
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--file')
    ap.add_argument('--out')
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else EVENTS_DIR / f'{SOURCE_ID}.json'
    previous = (read_json(out, {}) or {}).get('records', [])
    at = now_iso()
    try:
        data = json.loads(Path(args.file).read_text()) if args.file else fetch()
        records = build(data['rows'], at, data['updated_at'], previous)
        records = redact_events(records)
    except Exception as exc:
        write_events(SOURCE_ID, [], ok=False, error=error_text(exc), path=out)
        print(f'{SOURCE_ID}: FAILED {error_detail(exc)}', file=sys.stderr)
        return 1
    write_events(SOURCE_ID, records, path=out, meta={
        'registry_ids': [SOURCE_ID], 'page': PAGE, 'rows_read': len(data['rows']),
        'snapshot': True, 'time_basis': 'Source UTC issue and lift times, shown in America/Los_Angeles.',
        'caveat': 'Current actions only. A row leaving the list supplies no reopening date.'})
    print(f'{SOURCE_ID}: {len(data["rows"])} current actions; {len(records)} retained records')
    return 0


if __name__ == '__main__':
    sys.exit(main())
