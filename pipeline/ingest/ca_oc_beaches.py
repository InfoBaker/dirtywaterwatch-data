"""Orange County ocean health: current notices hourly and annual closure charts daily.

The home page is a current list, not an archive. Annual PDFs supply closure dates,
spill numbers, changing closure extents, cause and source-estimated volumes. One
chart record per spill number retains all extent phases; the closing and final
reopening dates are beach-action dates, never discharge start/end dates. A chart
revision replaces the same identity. A missing current notice has no inferred end.
No coordinates, receipt or publication times are invented. The home page's posted
on date has Pacific day precision. Source text is retained in raw.

The Mac cannot reach ocbeachinfo.com (2026-11-28). Public page text and 2025/2026
chart text were verified through the web client; the parser deliberately fails on
an unrecognized layout instead of accepting an empty archive. Recheck native PDF
extraction on the runner. --backfill YEAR reads discovered charts from that year;
normal reads request this year and the previous year. Cached charts are checked
at most daily. --file replays saved home HTML and does not fetch charts.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from pypdf import PdfReader

from common import BUILD_DIR, EVENTS_DIR, HEADERS, error_detail, error_text, event, now_iso, read_json, write_events, write_json
from ingest.ca_county_beach_common import TZ, day, digest, retain, text

SOURCE_ID = 'ca-ocbeachinfo'
PAGE = 'https://ocbeachinfo.com/'
DOWNLOAD = PAGE + 'download/'
STATE_FILE = BUILD_DIR / 'ca-ocbeachinfo-state.json'
AUTHORITY = 'Orange County Health Care Agency, Ocean Water Protection Program'


def chart_url(year):
    return PAGE + f'wp-content/uploads/Closure-Chart-{year}-for-OCBeachInfo.pdf'


class PageParser(HTMLParser):
    """Semantic headings and links; no dependency on WordPress styling/classes."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self.href = None
        self.anchor = []
        self.heading = None
        self.heading_text = []

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r'h[1-6]', tag):
            self.heading = tag
            self.heading_text = []
        if tag == 'a':
            self.href = dict(attrs).get('href', '')
            self.anchor = []

    def handle_data(self, data):
        if self.heading:
            self.heading_text.append(data)
        elif self.href is not None:
            self.anchor.append(data)
        else:
            self.parts.append(('text', data))

    def handle_endtag(self, tag):
        if tag == self.heading:
            self.parts.append(('heading', ' '.join(self.heading_text)))
            self.heading = None
        if tag == 'a' and self.href is not None:
            label = ' '.join(self.anchor)
            self.links.append((self.href, label))
            self.parts.append(('link', (self.href, label)))
            self.href = None


def parse_current(html):
    parser = PageParser()
    parser.feed(html)
    sections = {}
    active = None
    for kind, content in parser.parts:
        if kind == 'heading':
            label = text(content).upper().strip(': ')
            active = label if label in ('CLOSURES', 'WARNINGS', 'ADVISORIES') else None
            if active:
                sections.setdefault(active, {'text': [], 'links': []})
        elif active:
            sections[active]['links' if kind == 'link' else 'text'].append(content)
    if set(sections) != {'CLOSURES', 'WARNINGS', 'ADVISORIES'}:
        raise ValueError('county beach notice sections are missing')
    rows = []
    for label, section in sections.items():
        prose = text(' '.join(section['text']))
        links = [(urljoin(PAGE, href), text(title)) for href, title in section['links'] if text(title)]
        links = [(url, title) for url, title in links if title.lower() not in ('more information', 'back to top of page')]
        no_notices = re.search(r'(?i)no ocean,? harbor,? or bay water ' + label.lower() + r' are currently in effect', prose)
        if not links and not no_notices:
            # A new unlinked notice or a changed structure needs review; never erase the last good list.
            raise ValueError('county beach notice section has no recognized notice or empty-state statement')
        for url, title in links:
            if no_notices:
                raise ValueError('county beach section contradicts its notice links')
            m = re.search(r'(?i)\(posted on (\d{1,2}/\d{1,2}/\d{4})\)', title)
            rows.append({'section': label, 'title': title, 'url': url, 'posted_on': m[1] if m else None,
                         'extent': title[:m.start()].strip() if m else title,
                         # These paragraphs state why the program issues warnings/advisories. A closure's
                         # generic immediate-health-hazard language is not a water-quality reason.
                         'program_reason': prose if label in ('WARNINGS', 'ADVISORIES') else None})
    return rows


def current_records(rows, at):
    records = []
    for row in rows:
        start = day(row['posted_on']) if row['posted_on'] else None
        key = 'current-' + digest(row['section'], row['extent'], start)
        cause = row['program_reason'] or None
        records.append(event(source_id=SOURCE_ID, source_record_id=key,
                             event_type='beach_closure' if row['section'] == 'CLOSURES' else 'beach_advisory',
                             status='advisory_active', outfall_name=row['extent'], waterbody_text=row['extent'],
                             started_at=start, time_precision='day' if start else None, fetched_at=at,
                             authority=AUTHORITY, advice_text=row['title'], source_url=PAGE,
                             raw={'row': row, 'cause': cause, 'state': 'CA', 'county': 'Orange',
                                  'time_zone': 'America/Los_Angeles', '_poll_confirmed': True,
                                  'collection': 'current', '_first_seen_at': at, '_last_seen_in_source': at,
                                  '_identity_basis': 'Our key combines the notice section, affected area and posted date.'},
                             parse_error=None if start else 'The notice gives no recognized posting date.'))
    return records


ROW = re.compile(r'(?m)(?:^|\n)\s*(\d+[a-z]?)\s+(\d{2}-\d{3,})\s+(\d{1,2}/\d{1,2}/\d{4})\s+'
                 r'(?:(\d{1,2}/\d{1,2}/\d{4})(?:\s*\(reduced\s+on\))?\s+)?(\d+)\s+([\d.]+)\s+')
# Agency/cause cell starts, as read in the 2024-2026 charts. Unknown agencies remain in the source
# body; no guess is used to populate a receiving water or cause field.
AGENCY = re.compile(r'(?im)^(PPO\s*[–-]|Moulton Niguel Water|Costa Mesa Sanitation|Los Angeles County\s*$|Orange County Parks|Same as above)')
VOLUME = re.compile(r'(?i)(?:Original reported volume\s*)?~?\s*[\d,]+\s+gallons?\s+(?:total spilled|spilled|sewage|recovered|released)')


def chart_records(content, url, at, year):
    title = re.search(r'OCEAN AND BAY WATER CLOSURES\s+(\d{4})', content, re.I)
    if not title or int(title[1]) != year:
        raise ValueError('closure chart year or heading mismatch')
    matches = list(ROW.finditer(content))
    all_spills = re.findall(r'\b\d{2}-\d{3,}\b', content)
    if not matches or [m[2] for m in matches] != all_spills:
        raise ValueError('closure chart rows could not all be parsed')
    groups = defaultdict(list)
    for index, m in enumerate(matches):
        if int(m[2][:2]) != year % 100:
            raise ValueError('closure chart contains a spill from another year')
        body = content[m.end():matches[index + 1].start() if index + 1 < len(matches) else len(content)]
        body = re.split(r'\n\s*\*\s*Amount Spilled', body)[0].strip()
        am = AGENCY.search(body)
        area, rest = (text(body[:am.start()]), body[am.start():]) if am else (None, body)
        vm = VOLUME.search(rest)
        if vm:
            agency, volumes = (text(rest[:vm.start()]) if am else None), text(rest[vm.start():])
        else:
            agency, volumes = (text(rest) if am else None), None
        groups[m[2]].append({'row_number': m[1], 'spill_number': m[2], 'date_closed': m[3], 'date_opened': m[4],
                             'days_closed': m[5], 'beach_mile_days': m[6], 'area': area, 'agency_reason': agency,
                             'amount_spilled': volumes, 'source_text': body,
                             'reduced_on': 'reduced' in m[0].lower()})
    records = []
    for number, phases in groups.items():
        phases.sort(key=lambda p: (day(p['date_closed']), p['row_number']))
        first, last = phases[0], phases[-1]
        start = day(first['date_closed'])
        end = day(last['date_opened']) if last['date_opened'] and not last['reduced_on'] else None
        if any(p['date_opened'] and day(p['date_opened']) < day(p['date_closed']) for p in phases):
            raise ValueError('closure chart reopening precedes closure')
        # Do not bridge separated closures that reused a spill number.
        if any(not a['date_opened'] or day(b['date_closed']) != day(a['date_opened']) for a, b in zip(phases, phases[1:])):
            raise ValueError('closure chart phases are not contiguous')
        volume_text = ' '.join(dict.fromkeys(p['amount_spilled'] for p in phases if p['amount_spilled']))
        amounts = {}
        # The final stated amount for each measure wins; never spilled minus recovered.
        for m in re.finditer(r'(?i)([\d,]+(?:\.\d+)?)\s+gallons?\s+(total spilled|spilled|sewage|recovered|released)', volume_text):
            field = {'total spilled': 'spilled', 'sewage': 'spilled'}.get(m[2].lower(), m[2].lower())
            amounts[field] = float(m[1].replace(',', ''))
        if not amounts:
            raise ValueError('closure chart has no recognized source volumes')
        cause = first['agency_reason']
        records.append(event(source_id=SOURCE_ID, source_record_id='closure-' + number,
                             event_type='beach_closure', status='advisory_lifted' if end else 'advisory_active',
                             outfall_name=first['area'], waterbody_text=first['area'],
                             started_at=start, ended_at=end, time_precision='day', fetched_at=at,
                             volume_gal=amounts.get('spilled'), volume_text=volume_text, estimate_flag='estimated',
                             authority=AUTHORITY, source_url=url,
                             advice_text='; '.join(dict.fromkeys(p['area'] for p in phases if p['area'])),
                             raw={'phases': phases, 'cause': cause, 'reason': 'Sewage spill',
                                  'spill_number': number, 'volume_to_water_gal': amounts.get('released'),
                                  'volume_recovered_gal': amounts.get('recovered'), 'collection': 'chart',
                                  'state': 'CA', 'county': 'Orange', 'time_zone': 'America/Los_Angeles',
                                  '_columns_unparsed': any(p['area'] is None for p in phases),
                                  '_time_basis': 'Beach closure and reopening dates from the county chart.',
                                  '_phase_basis': 'We group contiguous closure areas by the source spill number; each area keeps its own dates.'}))
    return records


def discover_charts(html):
    parser = PageParser()
    parser.feed(html)
    charts = {}
    for href, label in parser.links:
        url = urljoin(DOWNLOAD, href)
        if urlparse(url).hostname not in ('ocbeachinfo.com', 'www.ocbeachinfo.com'):
            continue
        m = re.search(r'(?i)Closure[-_ ]Chart[-_ ](\d{4})', url)
        if m and url.lower().endswith('.pdf'):
            charts[int(m[1])] = url
    if not charts:
        raise ValueError('county closure chart links are missing')
    return charts


def pdf_text(data):
    # Preserve cell line order. Strict row/column/count checks reject unsupported PDF layouts.
    return '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(data)).pages)


def get(session, url):
    response = session.get(url, timeout=(15, 60))
    response.raise_for_status()
    return response


def main(argv=None):
    from build.redact import redact_events
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--file', help='replay saved home HTML, no chart requests')
    ap.add_argument('--chart-file', action='append', default=[], help='YEAR=path to extracted chart text')
    ap.add_argument('--backfill', type=int)
    ap.add_argument('--out')
    ap.add_argument('--state')
    args = ap.parse_args(argv)
    out = Path(args.out) if args.out else EVENTS_DIR / f'{SOURCE_ID}.json'
    state_path = Path(args.state) if args.state else STATE_FILE
    previous = (read_json(out, {}) or {}).get('records', [])
    state = read_json(state_path, {}) or {}
    at = now_iso()
    session = requests.Session()
    session.headers.update(HEADERS)
    errors, new, charts_read = [], [], []
    try:
        html = Path(args.file).read_text() if args.file else get(session, PAGE).text
        new = current_records(parse_current(html), at)
    except Exception as exc:
        write_events(SOURCE_ID, [], ok=False, error=error_text(exc), path=out)
        print(f'{SOURCE_ID}: FAILED {error_detail(exc)}', file=sys.stderr)
        return 1
    if args.file:
        for value in args.chart_file:
            year, filename = value.split('=', 1)
            try:
                new.extend(chart_records(Path(filename).read_text(), chart_url(int(year)), at, int(year)))
                charts_read.append(int(year))
            except Exception as exc:
                errors.append(error_text(exc))
    else:
        last = datetime.fromisoformat(state['charts_checked_at'].replace('Z', '+00:00')) if state.get('charts_checked_at') else None
        if args.backfill is not None or last is None or datetime.now(timezone.utc) - last >= timedelta(days=1):
            try:
                charts = discover_charts(get(session, DOWNLOAD).text)
                year = datetime.now(TZ).year
                since = args.backfill if args.backfill is not None else year - 1
                selected = {y: url for y, url in charts.items() if since <= y <= year}
                if not selected or (year not in selected and year > max(charts)):
                    raise ValueError('county current-year closure chart is unavailable')
                for y, url in sorted(selected.items()):
                    try:
                        new.extend(chart_records(pdf_text(get(session, url).content), url, at, y))
                        charts_read.append(y)
                    except Exception as exc:
                        errors.append(error_text(exc))
                if not errors:
                    state['charts_checked_at'] = at
                    write_json(state_path, state)
            except Exception as exc:
                errors.append(error_text(exc))
    records = retain(new, previous, at, scope={'current'})
    records = redact_events(records)
    write_events(SOURCE_ID, records, ok=not errors, partial=bool(errors), error='; '.join(errors) or None, path=out,
                 meta={'registry_ids': [SOURCE_ID], 'page': PAGE, 'charts_read': charts_read,
                       'time_basis': 'County posting, closure and reopening dates, Pacific day precision.',
                       'caveat': 'Current notices are retained when they leave the list; disappearance gives no reopening date.'})
    print(f'{SOURCE_ID}: {len(new)} rows read; {len(records)} retained records; {len(errors)} chart errors')
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
