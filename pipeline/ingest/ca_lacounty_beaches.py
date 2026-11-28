"""LA County beach map and paged ocean-water press releases, read hourly.

The map supplies station IDs, coordinates and a dated current status. Press releases
supply named affected areas, extent, reasons, reopening notices and occasional volumes.
Repeated lists are observations of continuous warnings, not new daily incidents.
No start is inferred from a publication date. Explicit lifting dates end beach actions;
sewage advisory ends are labelled closure ends, never discharge cessation times.
Current-year archive pages are traversed and checked against their published total.
Older cached releases and prior events survive year rollover and failed reads.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, EVENTS_DIR, HEADERS, error_detail, error_text, event, now_iso, read_json, save_raw, write_events, write_json
from ingest import ca_local_beaches as C

SOURCE_ID = 'ca-lacounty-beach'
PAGE = 'https://admin.publichealth.lacounty.gov/phcommon/public/eh/water_quality/beach_grades.cfm'
MAP = 'https://www.google.com/maps/d/kml?mid=1hrin1gMc6ok2dKu9d1i9szZKC6Y&forcekml=1'
LEGEND = 'https://admin.publichealth.lacounty.gov/phcommon/public/eh/water_quality/Capture.JPG'
INDEX = 'https://admin.publichealth.lacounty.gov/phcommon/public/media/mediapubOdisplay.cfm'
RELEASE = 'https://admin.publichealth.lacounty.gov/phcommon/public/media/mediapubhpdetail.cfm?prid='
AUTHORITY = 'Los Angeles County Department of Public Health'
NS = {'k': 'http://www.opengis.net/kml/2.2'}
PARSER_VERSION = 2
STATION_REFERENCES = {
    'DPH111': 'https://www.waterqualitydata.us/provider/STORET/CABEACH_WQX/CABEACH_WQX-DPH%20111/',
}

# Names shared by the public KML and county notices, verified November 28, 2026.
# Broad beach names with several stations remain areas: we do not select one point.
ALIASES = [
    ('dewatering well', 'DPH5'), ('treatment plant location at latigo', 'DPH5B'),
    ('strand street', 'DPH106'), ('malibu lagoon', 'SMB-MC2'), ('topanga canyon', 'SMB-1-18'),
    ('santa monica pier', 'SMB3-3'), ('pico-kenter', 'SMB-3-4'), ('windward', 'SMB-3-8'),
    ('culver', 'SMB-2-10'), ('westchester', 'SMB-2-11'), ('imperial highway', 'SMB-2-13'),
    ('40th street', 'SMB5-1'), ('manhattan beach pier', 'SMB5-3'), ('torrance beach', 'SMB6-6'),
    ('east malibu pier', 'DPH2B'), ('west malibu pier', 'DPH2'), ('solstice creek', 'SMB-1-10'),
    ('long point', 'SMB-7-3'), ('ballona creek', 'DPH122'), ('escondido creek', 'SMB-1-8'),
    ('castlerock', 'SMB-2-1'), ('castle rock', 'SMB-2-1'), ('pulga', 'SMB-2-4'),
    ('santa monica canyon', 'SMB-2-7'), ('topsail', 'DPH109'), ('marie canyon', 'SMB-1-12'),
    ('ramirez creek', 'DPH6'), ('redondo beach pier', 'SMB6-2'),
    # State Water Board station description at STATION_REFERENCES: "Hyperion Plant".
    ('hyperion plant', 'DPH111'),
]


def area_key(name):
    low = name.lower().replace('’', "'")
    if 'inner cabrillo' in low:
        return 'inner-cabrillo-beach'
    if ('mother' in low and ('marina' in low or 'del rey' in low)):
        return 'marina-mothers-beach'
    # Avalon pier-specific bacteria postings must not collapse into the whole closure.
    if low.strip() == 'avalon beach':
        return 'avalon-beach'
    for phrase, sid in ALIASES:
        if phrase in low:
            return sid
    return C.slug(low)


def parse_map(body):
    root = ET.fromstring(body)
    rows = []
    updated = None
    for folder in root.findall('.//k:Folder', NS):
        label = folder.findtext('k:name', default='', namespaces=NS)
        if folder.findall('k:Placemark', NS):
            label = re.sub(r'(\d+)(?:st|nd|rd|th)', r'\1', label)
            try:
                updated = datetime.strptime(label, '%A, %B %d, %Y %I:%M %p').replace(tzinfo=ZoneInfo(C.TZ)).isoformat()
            except ValueError:
                raise ValueError('Unrecognized LA map publication date') from None
        for pm in folder.findall('k:Placemark', NS):
            fields = {d.attrib['name']: d.findtext('k:value', namespaces=NS) for d in pm.findall('k:ExtendedData/k:Data', NS)}
            sid = C.station_id(fields.get('Station No.') or '')
            if not sid:
                raise ValueError('LA map station identifier missing')
            coords = pm.findtext('k:Point/k:coordinates', default='', namespaces=NS).strip().split(',')
            lon, lat = map(float, coords[:2])
            if not (-119.5 < lon < -117 and 32.5 < lat < 35):
                raise ValueError('LA map point outside source area')
            style = pm.findtext('k:styleUrl', default='', namespaces=NS)
            # Exact codes observed in the public file and checked against the linked legend.
            color = re.search(r'icon-503-([A-Fa-f0-9]{6})-', style)
            status = {'009D57': 'OPEN', '62AF44': 'OPEN', 'FFFFFF': 'NO RECENT SAMPLES',
                      'F4EB37': 'ADVISORY'}.get(color[1].upper() if color else '', 'UNRECOGNIZED MAP STATUS')
            cause = ('Ocean water bacteria level exceeds State Standards; also used for all beaches during an ocean water quality rain advisory.'
                     if status == 'ADVISORY' else None)
            name = pm.findtext('k:name', default='', namespaces=NS)
            key = 'marina-mothers-beach' if sid.startswith('MDRH-') else sid
            rows.append({'station_id': sid, 'name': name, 'area_key': key, 'status': status,
                         'lat': lat, 'lon': lon, 'style': style, 'fields': fields,
                         'cause': cause, 'legend_url': LEGEND, 'update_precision': 'minute'})
    if not rows or not updated or len({r['station_id'] for r in rows}) != len(rows):
        raise ValueError('Empty or duplicate LA map stations')
    return rows, updated


def parse_index(body):
    year = re.search(r'(\d{4}) Health Advisories', body)
    total = re.search(r'Total number of Records:\s*(\d+)', body)
    if not year or not total:
        raise ValueError('Missing LA archive year or total')
    rows = []
    for block in re.split(r'<div class="row"[^>]*>', body)[1:]:
        rid = re.search(r'<input[^>]*value="(\d+)"[^>]*name="prid"', block, re.I)
        title = re.search(r'<div class="col-8">(.*?)</div>', block, re.S)
        date = re.search(r'<div class="col-2">\s*([A-Za-z]+ \d{1,2})\s*</div>', block)
        if rid and title and date:
            rows.append({'id': rid[1], 'title': C.text(title[1]), 'date': f'{date[1]}, {year[1]}'})
    nxt = re.search(r'href\s*=\s*"([^"]+)"[^>]*>Next<', body, re.I)
    return rows, int(total[1]), urljoin(INDEX, html.unescape(nxt[1])) if nxt else None


def fetch_index(get):
    url, seen, result, total = INDEX, set(), {}, None
    while url:
        if url in seen or len(seen) >= 100 or urlparse(url).netloc != urlparse(INDEX).netloc:
            raise ValueError('Loop or unexpected link in LA archive pagination')
        seen.add(url)
        rows, count, nxt = parse_index(get(url))
        if total is not None and count != total:
            raise ValueError('LA archive count changed during paging')
        total = count
        if any(r['id'] in result for r in rows):
            raise ValueError('Repeated records in LA archive pagination')
        result.update({r['id']: r for r in rows})
        url = nxt
    if not result or len(result) != total:
        raise ValueError('LA archive pagination did not return its published total')
    return list(result.values())


def local_date(value):
    return datetime.strptime(value, '%B %d, %Y').replace(tzinfo=ZoneInfo(C.TZ)).isoformat()


def bullets(section):
    # Both actual <li> lists and middle-dot paragraphs occur in the archive.
    section = re.sub(r'(?i)<li\b[^>]*>', '\n• ', section)
    section = re.sub(r'(?i)<(?:/?p\b[^>]*|br\b[^>]*|/li)>', '\n', section)
    plain = html.unescape(re.sub(r'<[^>]+>', '', section))
    items = []
    if not re.search(r'[•·]', plain):
        # September 23's real release uses alternating place/extent paragraphs,
        # without list markers. Do not split its ambiguous concatenated lift text.
        lines = [' '.join(line.split()) for line in plain.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            if i and re.match(r'\d+ (?:yards|feet)|Entire swim area', line, re.I):
                items.append({'name': lines[i - 1], 'extent': line})
        return items
    for piece in re.split(r'[•·]', plain)[1:]:
        lines = [' '.join(line.split()) for line in piece.splitlines() if line.strip()]
        if not lines:
            continue
        name = lines[0].strip()
        extent = next((s for s in lines[1:] if re.match(r'\d+ (?:yards|feet)|Entire swim area', s, re.I)), None)
        items.append({'name': name, 'extent': extent})
    return items


def section(body, heading, end):
    m = re.search(heading, body, re.I)
    if not m:
        return ''
    return re.split(end, body[m.end():], maxsplit=1, flags=re.I)[0]


def parse_release(body, rid):
    if 'For Immediate Release:' not in body:
        raise ValueError('LA release body missing')
    content = body.split('For Immediate Release:', 1)[1].split('<hr', 1)[0]
    date = re.search(r'([A-Z][a-z]+ \d{1,2}, \d{4})', C.text(content))
    title = re.search(r'(?is)<h1[^>]*>(.*?)</h1>', content)
    if not date or not title:
        raise ValueError('LA release date or title missing')
    title = C.text(title[1]); published = local_date(date[1])
    # Keep the record body, including public narrative. No automatic text redaction.
    narrative = content.split('</h1>', 1)[1]
    plain = C.text(narrative)
    warnings = bullets(section(narrative, r'BEACH AREA WARNINGS:?', r'REASON FOR WARNING|BEACH AREAS NOW CLEARED|FOR MORE INFORMATION|Recorded information'))
    cleared = bullets(section(narrative, r'BEACH AREAS NOW CLEARED:?', r'FOR MORE INFORMATION|Recorded information'))
    closures = bullets(section(narrative, r'OCEAN WATER CLOSURE:', r'BEACH AREA WARNINGS|FOR MORE INFORMATION|Recorded information'))
    closure_lifted = 'closure lifted' in title.lower()
    if closure_lifted:
        closures = bullets(re.split(r'Recorded information', narrative, flags=re.I)[0])
    if not closures and 'closure' in title.lower() and not closure_lifted:
        # This release names its area in prose, with only the extent in the bullet.
        # Restrict the extraction to the actual source phrase, not a guessed geography.
        m = re.search(r'sewage discharge on\s+([A-Z][^.]+? Beach)\b', plain)
        if m:
            closures = [{'name': m[1], 'extent': next((x['name'] for x in bullets(narrative)), None)}]
    sewage = bool(re.search(r'\bsewage (?:discharge|spill|contamination)\b', plain, re.I))
    reason = re.search(r'[^.]*bacter(?:ial|ia) levels exceed[^.]*\.', plain, re.I)
    volume = re.search(r'((?:approximately\s+|about\s+)?([\d,]+(?:\.\d+)?)\s*(million\s+)?gallons) of sewage', plain, re.I)
    until = re.search(r'until (?:at least )?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*([A-Z][a-z]+ \d{1,2}, \d{4}),?\s*at\s*(\d{1,2}:\d{2}\s*[ap]m)', plain, re.I)
    announced = None
    if until:
        announced = datetime.strptime(f'{until[1]} {until[2].replace(" ", "")}', '%B %d, %Y %I:%M%p').replace(tzinfo=ZoneInfo(C.TZ)).isoformat()
    raw_links = re.findall(r'(?i)prid=(\d+)', narrative)
    return {'id': rid, 'title': title, 'published': published, 'text': plain, 'body_html': narrative,
            'warnings': warnings, 'cleared': cleared, 'closures': closures, 'closure_lifted': closure_lifted,
            'warning_list': bool(re.search(r'BEACH AREA WARNINGS', narrative, re.I)),
            'cause': reason[0].strip() if reason else None, 'sewage': sewage,
            'volume_text': volume[1] if volume else None,
            'volume_gal': float(volume[2].replace(',', '')) if volume and not volume[3] else None,
            'estimated': bool(volume and re.match(r'approximately|about', volume[1], re.I)),
            'rain': 'rain advisory' in title.lower(), 'announced_until': announced, 'links': raw_links}


def release_records(notices, previous, fetched):
    records, active = {}, {}
    prev = {r['event_id']: r for r in previous}
    for note in sorted(notices, key=lambda n: (n['published'], int(n['id']))):
        published = note['published']
        parts = [('warning', p, False) for p in note['warnings']]
        parts += [('warning', p, True) for p in note['cleared']]
        parts += [('closure', p, note['closure_lifted']) for p in note['closures']]
        if note['rain']:
            parts.append(('rain', {'name': 'Los Angeles County beaches', 'extent': None}, False))
        if not parts:
            rid = 'unparsed-' + note['id']
            r = event(source_id=SOURCE_ID, source_record_id=rid, event_type='unknown', status='unknown',
                      published_at=published, time_precision='day', fetched_at=fetched, authority=AUTHORITY,
                      source_url=RELEASE + note['id'], parse_error='The notice has no recognized beach action list.',
                      raw={'state': 'CA', 'notice': note, 'time_zone': C.TZ})
            records[r['event_id']] = r
        for kind, part, lifted in parts:
            key = (kind, area_key(part['name']))
            r = active.get(key)
            if kind == 'rain' and r:
                until = r['raw'].get('announced_until')
                if not until or published > until:
                    # A later rain notice after the announced window is a new
                    # action; the old action still has no observed lifting date.
                    active.pop(key)
                    r = None
            if r is None:
                rid = f'press-{note["id"]}-{kind}-{C.slug(key[1])}'
                etype = {'warning': 'beach_advisory', 'closure': 'sso' if note['sewage'] else 'beach_closure', 'rain': 'rain_advisory'}[kind]
                r = event(source_id=SOURCE_ID, source_record_id=rid, event_type=etype,
                          status='advisory_active', outfall_name=part['name'], waterbody_text=part['name'],
                          started_at=None, published_at=published, time_precision='day', fetched_at=fetched,
                          authority=AUTHORITY, source_url=RELEASE + note['id'],
                          raw={'state': 'CA', 'county': 'Los Angeles', 'time_zone': C.TZ, 'area_key': key[1],
                               'action_kind': kind, 'cause': None, 'notices': [], 'extent': part['extent'],
                               'grouping_basis': 'We group consecutive notices by the named area and action; this is our grouping, not a source incident identifier.',
                               '_first_seen_at': fetched, 'publication_basis': 'The first notice we hold for this action; the source does not give its start time.'})
                records[r['event_id']] = r
                active[key] = r
            raw = r['raw']
            raw['notices'].append({'id': note['id'], 'url': RELEASE + note['id'], 'published_at': published,
                                   'title': note['title'], 'text': note['text']})
            raw['extent'] = part['extent'] or raw.get('extent')
            if kind == 'warning':
                raw['cause'] = note['cause'] or raw.get('cause')
            elif kind == 'rain':
                raw['cause'] = 'Rainfall; potentially higher bacteria levels'
                raw['announced_until'] = note['announced_until']
                raw['announced_until_basis'] = 'The announced minimum advisory duration, which the county may extend; not a reported lifting.'
            elif note['sewage']:
                r['event_type'] = 'sso'
                raw['cause'] = 'Sewage discharge'
                raw['sewage_cause'] = True
                raw['advisory_noun'] = 'Sewage-related beach closure'
                raw['time_basis'] = 'The dates describe the beach closure, not the sewage discharge duration.'
                if note['volume_text']:
                    r.update(volume_gal=note['volume_gal'], volume_text=note['volume_text'],
                             estimate_flag='estimated' if note['estimated'] else 'unknown', material='sewage')
                    raw['volume_source_url'] = RELEASE + note['id']
            r['advice_text'] = raw['cause'] or note['title']
            r['source_updated_at'] = published
            if lifted:
                # Only the explicitly lifted beach action ends here. For sewage we retain the
                # closure end separately, avoiding a field that looks like a discharge end.
                if r['event_type'] == 'sso':
                    raw['closure_lifted_at'] = published
                    raw['_unlisted_since'] = published
                else:
                    r['ended_at'] = published
                r['status'] = 'advisory_lifted'
                raw['end_basis'] = 'The county explicitly reports the beach action lifted in this dated notice.'
                active.pop(key, None)
        # A complete warning list no longer showing an area bounds observation only.
        # Explicit lifting remains the only route into ended_at.
        if note['warning_list']:
            present = {area_key(p['name']) for p in note['warnings']}
            for key, r in list(active.items()):
                if key[0] == 'warning' and key[1] not in present:
                    r['raw']['_unlisted_since'] = published
                    r['raw']['unlisted_basis'] = 'Not listed in the later dated county warning list; no lifting time is inferred.'
                    active.pop(key)
    for eid, r in records.items():
        if eid in prev:
            r['raw']['_first_seen_at'] = prev[eid]['raw'].get('_first_seen_at', fetched)
    # An archive rollover or shortened index must never discard our earlier records.
    notice_ids = {n['id'] for n in notices}
    for eid, r in prev.items():
        first_notice = next(iter(r['raw'].get('notices', [])), {}).get('id')
        if eid not in records and r['raw'].get('action_kind') and first_notice not in notice_ids:
            records[eid] = copy.deepcopy(r)
    return list(records.values())


def rain_lifted(page):
    match = re.search(r'rain advisory has been lifted.*?on\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*([A-Z][a-z]+ \d{1,2}, \d{4}),?\s*at\s*(\d{1,2}:\d{2}\s*[ap]m)', C.text(page), re.I)
    if not match:
        return None
    return datetime.strptime(f'{match[1]} {match[2].replace(" ", "")}', '%B %d, %Y %I:%M%p').replace(tzinfo=ZoneInfo(C.TZ)).isoformat()


def combine(notices, stations, updated, previous, fetched, page=''):
    press = release_records(notices, previous, fetched)
    lifted = rain_lifted(page)
    if lifted:
        rains = [r for r in press if r['event_type'] == 'rain_advisory' and r['published_at'] <= lifted]
        if rains:
            last = max(rains, key=lambda r: r['published_at'])
            # The page's current lifting applies to the most recent rain episode,
            # never to all archived rain actions.
            last.update(ended_at=lifted, status='advisory_lifted')
            last['raw'].update(ended_at_precision='minute', end_source_url=PAGE,
                               end_basis='The county page explicitly states that the rain advisory has been lifted at this time.')
    lookup = {r['station_id']: r for r in stations}
    for r in press:
        raw = r['raw']; st = lookup.get(raw.get('area_key'))
        if st:
            r.update(lat=st['lat'], lon=st['lon'], coord_source='source')
            raw['map_station'] = st
            raw['coordinate_source_url'] = MAP
            raw['coordinate_basis'] = 'The notice and county map name the same location.'
            if raw.get('area_key') in STATION_REFERENCES:
                raw['station_reference_url'] = STATION_REFERENCES[raw['area_key']]
                raw['coordinate_basis'] = 'The State Water Board station description links the named location to this county map station.'
    maps = C.snapshot(SOURCE_ID, stations, updated,
                      [r for r in previous if r['raw'].get('station_id')], fetched, MAP, AUTHORITY)
    # Prefer the named notice for the same current action; keep the map as linked evidence.
    candidates = {}
    for r in press:
        if r['event_type'] == 'beach_advisory' and not r['raw'].get('_unlisted_since') and not r.get('ended_at'):
            candidates.setdefault(r['raw'].get('area_key'), []).append(r)
    for r in maps:
        r['duplicate_of'] = None
        area = r['raw']['row'].get('area_key')
        targets = candidates.get(area, [])
        if len(targets) == 1 and not r['raw'].get('_unlisted_since') and r['event_type'] == 'beach_advisory':
            target = targets[0]
            # A current map does not corroborate an old unmatched notice from months ago.
            age = datetime.fromisoformat(updated) - datetime.fromisoformat(target['source_updated_at'])
            if abs(age.total_seconds()) <= 7 * 86400:
                r['duplicate_of'] = target['event_id']
                r['raw']['_duplicate_basis'] = 'The county map and current notice name the same advisory location.'
                target['raw']['_last_seen_in_source'] = fetched
                target['raw']['map_updated_at'] = updated
    return press + maps


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--directory', help='replay saved la.kml, index-*.html and pr-*.html')
    ap.add_argument('--state'); ap.add_argument('--out')
    args = ap.parse_args(argv)
    state_path = Path(args.state) if args.state else BUILD_DIR / 'ca-lacounty-beaches-state.json'
    out = Path(args.out) if args.out else EVENTS_DIR / f'{SOURCE_ID}.json'
    if args.directory and not (args.out and args.state):
        ap.error('--directory requires --out and --state to isolate replay')
    prev = read_json(out, {}) or {}; state = read_json(state_path, {}) or {}
    fetched = now_iso(); cache = state.setdefault('releases', {})
    session = requests.Session(); session.headers.update(HEADERS)
    def get(url):
        if args.directory:
            from urllib.parse import parse_qs
            p = Path(args.directory)
            if url == MAP:
                return (p / 'la.kml').read_text()
            if url == PAGE:
                return (p / 'la.html').read_text()
            q = parse_qs(urlparse(url).query)
            if 'prid' in q:
                return (p / f'pr-{q["prid"][0]}.html').read_text()
            start = int(q.get('start', ['1'])[0])
            return (p / f'index-{start-1}.html').read_text()
        response = session.get(url, timeout=(15, 45)); response.raise_for_status()
        body = response.content.decode('utf-8')
        # Raw response persistence, one object per request without timestamp collisions.
        import hashlib
        save_raw(SOURCE_ID, body, hashlib.sha256(url.encode()).hexdigest()[:12] + '.html')
        return body
    try:
        stations, updated = parse_map(get(MAP))
        page = get(PAGE)
        if 'Beach Water Quality' not in page:
            raise ValueError('LA beach status page content missing')
        if len(stations) < prev.get('meta', {}).get('stations', 0) * .8:
            raise ValueError('Incomplete LA map station list')
        index = fetch_index(get)
        for item in index:
            cached = cache.get(item['id'])
            # Recheck recent releases daily for corrections; older source bodies remain cached.
            recent = (datetime.fromisoformat(fetched.replace('Z', '+00:00')) - datetime.fromisoformat(local_date(item['date']))).days < 30
            if cached and cached.get('parser_version') == PARSER_VERSION and (not recent or cached.get('checked', '')[:10] == fetched[:10]):
                continue
            body = cached['body'] if cached and cached.get('parser_version') != PARSER_VERSION and cached.get('body') else get(RELEASE + item['id'])
            parsed = parse_release(body, item['id'])
            cache[item['id']] = {'notice': parsed, 'checked': fetched, 'body': body, 'parser_version': PARSER_VERSION}
            write_json(state_path, state)  # retain successful work if a later page fails
        records = combine([x['notice'] for x in cache.values()], stations, updated, prev.get('records', []), fetched, page)
    except Exception as exc:
        write_events(SOURCE_ID, [], ok=False, error=error_text(exc), path=out)
        print(f'{SOURCE_ID}: FAILED {error_detail(exc)}', file=sys.stderr)
        return 1
    state.update(map_updated_at=updated, stations=len(stations)); write_json(state_path, state)
    meta = {'registry_ids': [SOURCE_ID], 'stations': len(stations), 'archive_releases': len(cache),
            'archive_by_year': dict(Counter(x['notice']['published'][:4] for x in cache.values())),
            'by_type': dict(Counter(r['event_type'] for r in records)), 'map_updated_at': updated,
            'by_publication_year': dict(Counter((r.get('published_at') or 'unknown')[:4] for r in records)),
            'time_note': 'Notice dates and map update dates are publication dates. Missing starts and lifting times remain unknown.'}
    write_events(SOURCE_ID, records, path=out, meta=meta)
    print(f'{SOURCE_ID}: {len(stations)} stations, {len(cache)} notices, {len(records)} retained records')
    return 0


if __name__ == '__main__':
    sys.exit(main())
