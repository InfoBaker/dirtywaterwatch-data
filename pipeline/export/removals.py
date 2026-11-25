"""Private, explicit removal requests. No heuristics, name lists, or entry logging.

Text matches are literal substrings (case insensitive unless case_sensitive is true).
Field matches are dotted paths or bare keys. Record matches are literal source text
or identifiers. Scopes use source_id and/or event_id; unknown provenance is treated
conservatively so a derived quote cannot escape a request. Known other records stay.
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
from pathlib import Path

from common import DATA_DIR

DEFAULT_PATH = DATA_DIR / 'private' / 'removal-list.json'
REMOVED = '[removed on request]'
DROP = object()


def strings(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield str(key)
            yield from strings(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from strings(value)
    elif obj is not None:
        yield str(obj)


class RemovalList:
    def __init__(self, entries):
        if not isinstance(entries, list):
            raise ValueError('removal list must be an array')
        self.entries = []
        ids = set()
        for e in entries:
            if (not isinstance(e, dict) or not isinstance(e.get('id'), str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', e['id'])
                    or e['id'] in ids or not isinstance(e.get('added'), str)
                    or not e['added'] or e.get('kind') not in ('text', 'field', 'record')
                    or not isinstance(e.get('match'), str) or not e['match']
                    or not isinstance(e.get('scope', {}), dict)
                    or set(e.get('scope', {})) - {'source_id', 'event_id'}
                    or any(not isinstance(v, str) or not v for v in e.get('scope', {}).values())
                    or not isinstance(e.get('replacement', REMOVED), str)
                    or not isinstance(e.get('case_sensitive', False), bool)):
                raise ValueError('invalid removal entry (contents withheld)')
            ids.add(e['id'])
            self.entries.append(dict(e))
        self.patterns = {e['id']: re.compile(re.escape(e['match']), 0 if e.get('case_sensitive') else re.I)
                         for e in self.entries}
        self.sources = {}
        self.removed_ids = {e['match'] for e in self.entries if e['kind'] == 'record'
                            and ':' in e['match'] and self.scoped(e, {
                                'event_id': e['match'], 'source_id': e['match'].split(':', 1)[0]})}
        self.removed_by = {eid: {e['id'] for e in self.entries if e['kind'] == 'record' and e['match'] == eid}
                           for eid in self.removed_ids}
        self.field_texts = {e['id']: set() for e in self.entries if e['kind'] == 'field'}

    def remove_id(self, eid, entry_ids):
        self.removed_ids.add(eid)
        self.removed_by.setdefault(eid, set()).update(entry_ids)

    @classmethod
    def load(cls, path=DEFAULT_PATH):
        try:
            data = Path(path).read_text(encoding='utf-8')
        except FileNotFoundError:
            return cls([])
        try:
            return cls(json.loads(data))
        except (ValueError, TypeError):
            raise ValueError('invalid removal list (contents withheld)') from None

    def context(self, obj, inherited):
        ctx = dict(inherited)
        if isinstance(obj, dict):
            if obj.get('event_id'):
                ctx = {'event_id': str(obj['event_id'])}
                sid = obj.get('source_id') or self.sources.get(ctx['event_id'])
                if not sid and ':' in ctx['event_id']:
                    sid = ctx['event_id'].split(':', 1)[0]
                if sid:
                    ctx['source_id'] = sid
            elif obj.get('source_id'):
                ctx = {'source_id': str(obj['source_id'])}
        return ctx

    def scoped(self, e, ctx):
        return all(key not in ctx or ctx[key] == value for key, value in e.get('scope', {}).items())

    def field(self, e, path, key):
        target = e['match']
        equal = (lambda a, b: a == b) if e.get('case_sensitive') else (lambda a, b: a.casefold() == b.casefold())
        suffix = path[-len(target)-1:]
        return equal(target, key) or equal(target, path) or equal('.' + target, suffix)

    def register(self, obj):
        """Learn identities and removed field values before any derived payload is written."""
        if not self.entries:
            return
        def identities(value):
            if isinstance(value, dict):
                if value.get('event_id') and value.get('source_id'):
                    self.sources[str(value['event_id'])] = str(value['source_id'])
                for child in value.values():
                    identities(child)
            elif isinstance(value, list):
                for child in value:
                    identities(child)
        identities(obj)

        def visit(value, ctx, path=''):
            ctx = self.context(value, ctx)
            if isinstance(value, dict):
                for e in self.entries:
                    if e['kind'] == 'record' and self.scoped(e, ctx) and self.matches(e, value):
                        if value.get('event_id'):
                            self.remove_id(str(value['event_id']), [e['id']])
                for k, v in value.items():
                    p = f'{path}.{k}' if path else str(k)
                    for e in self.entries:
                        if e['kind'] == 'field' and self.scoped(e, ctx) and self.field(e, p, str(k)):
                            self.field_texts[e['id']].update(s for s in strings(v) if s)
                    visit(v, ctx, p)
            elif isinstance(value, list):
                for v in value:
                    visit(v, ctx, path)
        visit(obj, {})

    def matches(self, e, obj):
        rx = self.patterns[e['id']]
        # Event identifiers are complete identities, not prefixes of other IDs.
        match = rx.fullmatch if e['kind'] == 'record' and re.fullmatch(r'[^\s:]+:[^\s]+', e['match']) else rx.search
        return any(match(s) for s in strings(obj))

    def text(self, value, ctx, check=False):
        for e in self.entries:
            if not self.scoped(e, ctx):
                continue
            patterns = ([self.patterns[e['id']]] if e['kind'] == 'text' else
                        [re.compile(re.escape(s), 0 if e.get('case_sensitive') else re.I)
                         for s in sorted(self.field_texts.get(e['id'], ()), key=len, reverse=True)])
            for rx in patterns:
                if rx.search(value):
                    if check:
                        return e['id']
                    value = rx.sub(lambda m: e.get('replacement', REMOVED), value)
        return None if check else value

    def apply(self, obj):
        if not self.entries and not self.removed_ids:
            return obj
        result = self._walk(obj, {})
        return None if result is DROP else result

    def _walk(self, obj, ctx, path='', check=False, hits=None):
        ctx = self.context(obj, ctx)
        if isinstance(obj, dict):
            feature = obj.get('type') == 'Feature' and isinstance(obj.get('properties'), dict)
            if feature:
                ctx = self.context(obj['properties'], ctx)
            eid = str((obj['properties'] if feature else obj).get('event_id', ''))
            if eid in self.removed_ids:
                if check:
                    hits.update(self.removed_by.get(eid, ()))
                return DROP
            for e in self.entries:
                if e['kind'] == 'record' and self.scoped(e, ctx):
                    # Match at the record boundary, not an entire envelope of unrelated records.
                    own = {k: v for k, v in obj.items() if not isinstance(v, (dict, list))}
                    if self.matches(e, obj if eid or feature else own):
                        if check:
                            hits.add(e['id'])
                        if eid:
                            self.remove_id(eid, [e['id']])
                        return DROP
            out = {}
            for k, v in obj.items():
                if str(k) in self.removed_ids:
                    if check:
                        hits.update(self.removed_by.get(str(k), ()))
                    continue
                request = next((e for e in self.entries if e['kind'] == 'record' and self.scoped(e, ctx)
                                and self.matches(e, str(k))), None)
                if request:
                    if check:
                        hits.add(request['id'])
                    continue
                p = f'{path}.{k}' if path else str(k)
                request = next((e for e in self.entries if e['kind'] == 'field' and self.scoped(e, ctx)
                                and self.field(e, p, str(k))), None)
                hit = request['id'] if request else self.text(str(k), ctx, check=True)
                if hit:
                    if check:
                        hits.add(hit)
                        if eid:
                            self.remove_id(eid, [hit])
                        return DROP
                    if request:
                        continue
                new_key = self.text(str(k), ctx)
                child_hits = set() if check else None
                value = self._walk(v, ctx, p, check, child_hits)
                if check:
                    hits.update(child_hits)
                if check and child_hits and (eid or feature):
                    if eid:
                        self.remove_id(eid, child_hits)
                    return DROP
                if value is DROP:
                    # A remaining scalar match removes its containing record.
                    if check and not isinstance(v, (dict, list)):
                        if eid:
                            self.remove_id(eid, hits)
                        return DROP
                    continue
                out[new_key] = value
            for key in ('events', 'records', 'rows', 'waters', 'dischargers', 'outfalls', 'features'):
                if (isinstance(obj.get(key), (list, dict)) and key in out and 'count' in out
                        and obj.get('count') == len(obj[key])):
                    out['count'] = len(out[key])
                    break
            return out
        if isinstance(obj, list):
            # A history interval is one record; a list of event references is a collection.
            interval = 'intervals' in path.split('.') and len(obj) >= 5 and isinstance(obj[4], str)
            if interval:
                if obj[4] in self.removed_ids:
                    if check:
                        hits.update(self.removed_by.get(obj[4], ()))
                    return DROP
                ctx = self.context({'event_id': obj[4]}, ctx)
            out = []
            for v in obj:
                value = self._walk(v, ctx, path, check, hits)
                if value is DROP and interval:
                    return DROP
                if value is not DROP:
                    out.append(value)
            return out
        if isinstance(obj, (str, int, float)) and not isinstance(obj, bool):
            original = obj
            obj = str(obj)
            if obj in self.removed_ids:
                if check:
                    hits.update(self.removed_by.get(obj, ()))
                return DROP
            for e in self.entries:
                if e['kind'] == 'record' and self.scoped(e, ctx) and self.matches(e, obj):
                    if check:
                        hits.add(e['id'])
                    return DROP
            if check:
                hit = self.text(obj, ctx, check=True)
                if hit:
                    hits.add(hit)
                    return DROP
                return original
            out = self.text(obj, ctx)
            return original if out == obj else out
        return obj

    def _files(self, root):
        return sorted(p for p in Path(root).rglob('*') if p.is_file())

    def _file(self, path, check=False):
        """Decode JSON/GeoJSON and CSV; other payloads are conservatively a single record."""
        hits = set()
        data = path.read_bytes()
        try:
            text = data.decode('utf-8-sig')
        except UnicodeError:
            # Unknown binary payloads containing a requested literal cannot be published.
            hits = {e['id'] for e in self.entries if e['match'].encode().lower() in data.lower()}
            return (None if hits else data), hits
        try:
            if path.suffix.lower() in ('.json', '.geojson'):
                obj = json.loads(text)
                # Compact events index rows need their named columns for field and scope rules.
                compact = isinstance(obj, dict) and isinstance(obj.get('fields'), list) and isinstance(obj.get('rows'), list)
                if compact:
                    obj['rows'] = [dict(zip(obj['fields'], r)) for r in obj['rows']]
                out = self._walk(obj, {}, check=check, hits=hits)
                if out is DROP:
                    return None, hits
                if compact:
                    out['fields'] = [k for k in out['fields'] if not any(
                        e['kind'] == 'field' and not e.get('scope') and self.field(e, k, k)
                        for e in self.entries)]
                    out['rows'] = [[r.get(k) for k in out['fields']] for r in out['rows']]
                    out['count'] = len(out['rows'])
                result = json.dumps(out, ensure_ascii=False, separators=(',', ':')).encode()
            elif path.suffix.lower() == '.csv':
                reader = csv.DictReader(io.StringIO(text))
                rows = []
                for row in reader:
                    out = self._walk(row, {}, check=check, hits=hits)
                    if out is not DROP:
                        rows.append(out)
                buf = io.StringIO(newline='')
                fields = [k for k in reader.fieldnames or [] if not any(
                    e['kind'] == 'field' and not e.get('scope') and self.field(e, k, k)
                    for e in self.entries)]
                fields = [self.text(k, {}) for k in fields]
                writer = csv.DictWriter(buf, fieldnames=fields, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(rows)
                result = buf.getvalue().encode()
            else:
                decoded = html.unescape(text)
                hits.update(e['id'] for e in self.entries if e['kind'] == 'record' and self.matches(e, decoded))
                if check:
                    hit = self.text(decoded, {}, check=True)
                    if hit:
                        hits.add(hit)
                if hits:
                    return None, hits
                out = self._walk(text, {}, check=check, hits=hits)
                result = None if out is DROP else out.encode()
        except (ValueError, TypeError):
            raise ValueError('unreadable export payload during removal check') from None
        return result, hits

    def publish(self, root):
        if not self.entries and not self.removed_ids:
            return
        for path in self._files(root):
            result, _ = self._file(path)
            if result is None:
                self.empty_file(path)
            else:
                path.write_bytes(result)

    @staticmethod
    def empty_file(path):
        # Uploaders replace existing object keys. Keeping an empty payload ensures a
        # removed standalone record cannot survive remotely as an older object.
        path.write_bytes(b'null\n' if path.suffix.lower() in ('.json', '.geojson') else b'')

    def enforce(self, root):
        """Final check: remove any record still matching; warn with file and entry id only.

        The second pass removes references/copies of records rejected by the first,
        including copies in files visited earlier. No request contents are logged.
        """
        if not self.entries:
            return 0
        count = 0
        for path in self._files(root):
            result, hits = self._file(path, check=True)
            if hits:
                count += 1
                filename = path.relative_to(root).as_posix()
                for request in self.entries:
                    filename = self.patterns[request['id']].sub('[removed]', filename)
                    for value in self.field_texts.get(request['id'], ()):
                        filename = re.sub(re.escape(value), '[removed]', filename, flags=re.I)
                for entry_id in sorted(hits):
                    print(f'::warning::requested removal: {filename} entry {entry_id}')
                if result is None:
                    self.empty_file(path)
                else:
                    path.write_bytes(result)
        if count:
            self.publish(root)
        return count
