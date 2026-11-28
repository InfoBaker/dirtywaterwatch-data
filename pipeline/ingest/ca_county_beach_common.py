"""California county beach utilities (not a feed). Source text is preserved."""
from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Los_Angeles')


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def text(value):
    parser = Text()
    parser.feed(str(value or ''))
    return ' '.join(' '.join(parser.parts).split())


def timestamp(value):
    """API offsets are authoritative; undated 1900 placeholders are not dates."""
    if not value or str(value).startswith('1900-01-01'):
        return None
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).isoformat()


def day(value):
    return datetime.strptime(value, '%m/%d/%Y').replace(tzinfo=TZ).isoformat()


def digest(*values):
    return hashlib.sha256('|'.join(str(v or '') for v in values).encode()).hexdigest()[:24]


def retain(records, previous, fetched_at, *, scope=None):
    """Disappearance is an observation, never a source reopening or a new end."""
    old = {r['event_id']: r for r in previous}
    result = {}
    for r in records:
        p = old.get(r['event_id']) or {}
        raw = r['raw']
        raw['_first_seen_at'] = (p.get('raw') or {}).get('_first_seen_at', fetched_at)
        raw['_last_seen_in_source'] = fetched_at
        result[r['event_id']] = r
    for eid, p in old.items():
        if eid not in result:
            r = copy.deepcopy(p)
            if scope is None or r['raw'].get('collection') in scope:
                r['raw'].setdefault('_missing_from_source_since', fetched_at)
            result[eid] = r
    return sorted(result.values(), key=lambda r: (r.get('started_at') or '', r['event_id']), reverse=True)


def spill_volume(description):
    """Only a source-stated sewage gallon total; no arithmetic or inferred volumes."""
    m = re.search(r'(?i)\b(approximately\s+|about\s+|estimated\s+)?([\d,]+(?:\.\d+)?)\s+gallons?\s+of\s+(?:raw\s+)?sewage', description)
    if not m:
        return None, None, 'unknown'
    return float(m[2].replace(',', '')), m[0], 'estimated' if m[1] else 'unknown'
