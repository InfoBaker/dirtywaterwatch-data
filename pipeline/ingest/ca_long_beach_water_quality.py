"""Long Beach Health's dated water-quality conditions table -> hourly observation archive.

The dot's column is the status, not the cell's background color. The city's legend
explains ADVISORY as bacterial levels outside state standards, RAIN ADVISORY as rain,
and CLOSED only as a significant health risk: no sewage cause is inferred from CLOSED.
The table has no event start, lifting time, volume, coordinates or spill identifier.
Source text passes through; raw_fields classifies the fields we actually read.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, error_detail, error_text, now_iso, read_json, save_raw, write_events
from ingest import ca_local_beaches as C

SOURCE_ID = 'ca-long-beach-water-quality'
URL = 'https://www.longbeach.gov/health/inspections-and-reporting/inspections/recreational-water-samples/'
AUTHORITY = 'Long Beach Department of Health and Human Services'


def parse(body):
    updated = re.search(r'Website Updated:\s*(\d{1,2}/\d{1,2}/\d{4})', C.text(body))
    if not updated:
        raise ValueError('No conditions update date in Long Beach page')
    stamp = datetime.strptime(updated[1], '%m/%d/%Y').replace(tzinfo=ZoneInfo(C.TZ)).isoformat()
    definitions = {}
    for para in re.findall(r'(?is)<p\b[^>]*>(.*?)</p>', body):
        value = C.text(para)
        for status in ('ADVISORY', 'RAIN ADVISORY', 'CLOSED'):
            if re.match(re.escape(status) + r'\s*:', value):
                definitions[status] = value.split(':', 1)[1].strip()
    rows = []
    for table in re.findall(r'(?is)<table\b[^>]*>(.*?)</table>', body):
        trs = re.findall(r'(?is)<tr\b[^>]*>(.*?)</tr>', table)
        if not trs:
            continue
        header = [C.text(x) for x in re.findall(r'(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>', trs[0])]
        if header != ['', 'LOCATIONS', 'OPEN', 'ADVISORY', 'RAIN ADVISORY', 'CLOSED']:
            continue
        for tr in trs[1:]:
            cells = [C.text(x) for x in re.findall(r'(?is)<td\b[^>]*>(.*?)</td>', tr)]
            if len(cells) != 6 or not re.fullmatch(r'B-\d+', cells[0]):
                raise ValueError('Unexpected Long Beach station row')
            marked = [i for i, value in enumerate(cells[2:], 2) if value == '●']
            if len(marked) != 1 or any(v not in ('', '●') for v in cells[2:]):
                raise ValueError('Ambiguous Long Beach status marker')
            status = header[marked[0]]
            # The closure definition gives no specific water-quality cause (decision 40).
            cause = definitions.get(status) if status in ('ADVISORY', 'RAIN ADVISORY') else None
            rows.append({'station_id': cells[0], 'name': cells[1], 'status': status,
                         'cause': cause, 'status_definition': definitions.get(status), 'update_precision': 'day'})
    if not rows or len({r['station_id'] for r in rows}) != len(rows):
        raise ValueError('Missing or duplicate Long Beach stations')
    return rows, stamp


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--file'); ap.add_argument('--out')
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else EVENTS_DIR / f'{SOURCE_ID}.json'
    prev = read_json(out, {}) or {}
    fetched = now_iso()
    try:
        if args.file:
            body = Path(args.file).read_text()
        else:
            response = requests.get(URL, headers=HEADERS, timeout=(15, 45)); response.raise_for_status()
            body = response.content.decode('utf-8')
        rows, updated = parse(body)
        if len(rows) < (prev.get('meta', {}).get('stations', 0) * .8):
            raise ValueError('Incomplete Long Beach station table')
        if not args.file:
            save_raw(SOURCE_ID, json.dumps({'url': URL, 'updated': updated, 'rows': rows}), 'json')
        records = C.snapshot(SOURCE_ID, rows, updated, prev.get('records', []), fetched, URL, AUTHORITY)
    except Exception as exc:
        write_events(SOURCE_ID, [], ok=False, error=error_text(exc), path=out)
        print(f'{SOURCE_ID}: FAILED {error_detail(exc)}', file=sys.stderr)
        return 1
    write_events(SOURCE_ID, records, path=out, meta={'stations': len(rows), 'registry_ids': [SOURCE_ID],
                 'by_status': {s: sum(r['status'] == s for r in rows) for s in ('OPEN', 'ADVISORY', 'RAIN ADVISORY', 'CLOSED')},
                 'source_updated_at': updated, 'snapshot': True, 'timezone': C.TZ,
                 'time_note': 'The date is the published snapshot date. Advisory starts and lifting times are not supplied.'})
    print(f'{SOURCE_ID}: {len(rows)} stations, {len(records)} retained advisory records')
    return 0


if __name__ == '__main__':
    sys.exit(main())
