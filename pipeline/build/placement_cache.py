"""Content observations for selective placement reuse, stored inside the existing cache.

A query includes negative lookups: a newly added name, alias or spatial candidate must invalidate
an earlier miss. Interned dependency groups avoid repeating query text and water hashes per event.
Non-water inputs remain under the conservative global stamp in status.py.
"""
import hashlib
import json
from functools import wraps


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


def digest(value):
    return hashlib.blake2b(packed(value).encode(), digest_size=16).hexdigest()


class ObservedMap(dict):
    def __init__(self, values, owner, kind):
        super().__init__(values)
        self.owner, self.kind = owner, kind

    def observe(self, key):
        self.owner.observe((self.kind, key))

    def __getitem__(self, key):
        self.observe(key)
        # The original name indexes are defaultdict(list).
        if self.kind in ('names', 'stems', 'exact'):
            return dict.get(self, key, [])
        return dict.__getitem__(self, key)

    def get(self, key, default=None):
        self.observe(key)
        return dict.get(self, key, default)

    def __contains__(self, key):
        self.observe(key)
        return dict.__contains__(self, key)


class Dependencies:
    def __init__(self, resolver, water_hashes, saved=None, unchanged=False):
        self.resolver = resolver
        self.water_hashes = water_hashes
        self.frames = []
        self.queries, self.query_ids, self.values = [], {}, {}
        self.groups, self.group_ids = [], {}
        self.old = saved or {}
        self.unchanged = unchanged
        self.valid_groups = {}
        self.imported_groups = {}
        for kind in ('waters', 'slug_alias', 'names', 'stems', 'exact'):
            setattr(resolver, kind, ObservedMap(getattr(resolver, kind), self, kind))
        resolver.dependencies = self
        # These methods memoize nested water/index reads. Replay their observations on a memo hit,
        # including when the first caller was recent and therefore not persisted as a placement.
        for name in ('row_water', 'watershed_labels', 'distance_m'):
            self.wrap_memo(name)

    def wrap_memo(self, name):
        method = getattr(self.resolver, name)
        footprints = {}
        parameters = {"row_water": ("row",), "watershed_labels": ("text", "state"),
                      "distance_m": ("slug", "lat", "lon")}[name]

        @wraps(method)
        def call(*args, **kwargs):
            values = args + tuple(kwargs[p] for p in parameters[len(args):])
            # Exactly the underlying memo's identity: ignored row metadata and equal int/float
            # coordinates must replay the same observations, not capture an empty memo-hit trace.
            key = self.resolver.row_water_key(values[0]) if name == "row_water" else values
            if key in footprints:
                for frame in self.frames:
                    frame.update(footprints[key])
                return method(*args, **kwargs)
            frame = set()
            self.frames.append(frame)
            try:
                return method(*args, **kwargs)
            finally:
                self.frames.pop()
                footprints[key] = frame
        setattr(self.resolver, name, call)

    def value(self, query):
        from build import status as S
        kind, *args = query
        if kind == 'waters':
            return self.water_hashes.get(args[0])
        if kind in ('slug_alias', 'names', 'stems', 'exact'):
            key = tuple(args[0]) if isinstance(args[0], list) else args[0]
            return dict.get(getattr(self.resolver, kind), key)
        if kind == 'matching':
            state, text, stems = args
            names = self.resolver.names_by_state.get(state, [])
            if stems:
                names = names + self.resolver.stems_by_state.get(state, [])
            return [n for n in names if f' {n} ' in text]
        if kind == 'point':
            lat, lon, state = args
            return self.resolver.point_candidates(lat, lon, state)
        if kind == 'person':
            return S.person_shaped(args[0])
        raise ValueError('unknown placement dependency')

    def observe(self, query):
        if not self.frames:
            return
        key = packed(query)
        if key not in self.query_ids:
            idx = len(self.queries)
            self.query_ids[key] = idx
            value = digest(self.value(query))
            self.queries.append([query, value])
        idx = self.query_ids[key]
        for frame in self.frames:
            frame.add(idx)

    def group(self, ids):
        key = tuple(sorted(ids))
        if key not in self.group_ids:
            self.group_ids[key] = len(self.groups)
            self.groups.append(list(key))
        return self.group_ids[key]

    def resolve(self, ev):
        frame = set()
        self.frames.append(frame)
        try:
            pl = self.resolver.resolve(ev)
        finally:
            self.frames.pop()
        return pl, self.group(frame)

    def valid(self, group):
        if type(group) is not int or group < 0:
            return False
        if group in self.valid_groups:
            return self.valid_groups[group]
        try:
            ids = self.old['groups'][group]
            good = True
            for idx in ids:
                query, previous = self.old['queries'][idx]
                key = packed(query)
                if key not in self.values:
                    self.values[key] = previous if self.unchanged else digest(self.value(query))
                if self.values[key] != previous:
                    good = False
                    break
        except (KeyError, IndexError, TypeError, ValueError):
            good = False
        self.valid_groups[group] = good
        return good

    def import_group(self, group):
        if group not in self.imported_groups:
            ids = []
            for idx in self.old['groups'][group]:
                query, value = self.old['queries'][idx]
                key = packed(query)
                if key not in self.query_ids:
                    self.query_ids[key] = len(self.queries)
                    self.queries.append([query, value])
                ids.append(self.query_ids[key])
            self.imported_groups[group] = self.group(ids)
        return self.imported_groups[group]

    def saved(self):
        # Memoized work for recent/extent records can observe queries without persisting a placement.
        # Keep only queries referenced by an eligible record, pruning removed records on every write.
        used = sorted({i for group in self.groups for i in group})
        remap = {old: new for new, old in enumerate(used)}
        return {'queries': [self.queries[i] for i in used],
                'groups': [[remap[i] for i in group] for group in self.groups]}
