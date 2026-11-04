"""Merge a rebuild of data/outfalls-plants-us.json (build_plant_outfalls.py output) into the committed file without
touching the rows already there.

The committed rows carry fields written after the build: the water-record ties of scripts/match_outfalls.py and
ingest.outfall_waters (TIE_FIELDS). A rebuild has none of them, so the rebuilt file cannot simply replace the committed
one. This script checks, row by row on (permit, outfall), that the rebuild reproduces every committed row exactly
once the tie fields (and fetched_at, the time the source copy was fetched) are set aside, then writes:

  - every committed row unchanged, byte for byte;
  - every rebuilt row the committed file lacks, as the rebuild wrote it (with its own fetched_at);
  - the header keys source and fetched_at from the committed file (they describe the copy the committed rows came
    from), rule, count, counts, excluded_not_sewage and cso_features_not_in_inventory from the rebuild, and a
    `rebuilds` entry saying when, from which fetch, why and how many rows were added (and dropped).

It refuses (exit 1, nothing written) when a committed row differs from its rebuilt row in any other field, or is
missing from the rebuild: a rebuild that changes existing rows is a different change and needs its own review. A
field named with --accept may change (the committed row keeps its other fields and its key order, and takes the
rebuilt value): the fix that brought the rebuild may move a permit to another plant_basis, and says so in the
`rebuilds` entry (rows_changed). With --drop-excluded, a committed row whose permit the rebuild lists in
excluded_not_sewage (build_plant_outfalls.not_sewage: no sewage plant) is dropped instead of refused, and listed in the
`rebuilds` entry (rows_dropped, with the reason); any other missing row still refuses.

Usage: python -I merge_plant_outfalls.py <committed.json> <rebuilt.json> <out.json> --date YYYY-MM-DD
           --fetched-at <ISO time of the source copy the rebuild read> --why "<one sentence>" [--accept FIELD ...]
           [--drop-excluded]
"""
import argparse, json, sys

TIE_FIELDS = ('water_slug', 'water_name', 'water_kind', 'distance_m', 'match', 'water_match', 'water_matched_by',
              'no_water_reason', 'replaced_match')
IGNORED = set(TIE_FIELDS) | {'fetched_at'}
HEADER_FROM_COMMITTED = ('source', 'fetched_at')


def key(r):
    return (r['npdes_permit'], r.get('outfall'))


def bare(r):
    return {k: v for k, v in r.items() if k not in IGNORED}


def merge(committed, rebuilt, date, fetched_at, why, accept=(), drop_excluded=False):
    """(merged doc, problems, added rows). problems lists the committed rows the rebuild does not reproduce (fields
    in accept may change; with drop_excluded a row of a permit the rebuild lists in excluded_not_sewage is dropped)."""
    old = {key(r): r for r in committed['outfalls']}
    not_sewage = {x['npdes_permit']: x['reason'] for x in rebuilt.get('excluded_not_sewage') or []}
    dropped = {}
    new_keys = {key(r) for r in rebuilt['outfalls']}
    problems, rows, added = [], [], []
    changed = {}
    for r in rebuilt['outfalls']:
        o = old.get(key(r))
        if o is None:
            rows.append(r)
            added.append(r)
            continue
        if bare(o) != bare(r):
            diff = sorted(k for k in set(bare(o)) | set(bare(r)) if bare(o).get(k, '<absent>') != bare(r).get(k, '<absent>'))
            if set(diff) <= set(accept) and all(k in o and k in r for k in diff):
                o = dict(o)
                for k in diff:
                    o[k] = r[k]
                    changed.setdefault(k, []).append(f"{r['npdes_permit']} {r.get('outfall')}")
            else:
                problems.append({'npdes_permit': r['npdes_permit'], 'outfall': r.get('outfall'), 'fields': diff})
        rows.append(o)
    for k, o in old.items():
        if k not in new_keys:
            if drop_excluded and k[0] in not_sewage:
                dropped.setdefault(not_sewage[k[0]], []).append(f'{k[0]} {k[1]}')
            else:
                problems.append({'npdes_permit': k[0], 'outfall': k[1], 'fields': ['missing from the rebuild']})
    doc = {}
    for k in committed:
        if k in ('outfalls', 'cso_features_not_in_inventory'):
            continue
        doc[k] = committed[k] if k in HEADER_FROM_COMMITTED or k == 'rebuilds' else rebuilt.get(k, committed[k])
    doc['count'] = len(rows)
    doc['counts'] = rebuilt['counts']
    doc['excluded_not_sewage'] = list(rebuilt.get('excluded_not_sewage') or [])
    doc['rebuilds'] = doc.pop('rebuilds', None)
    by_state = {}
    for r in added:
        by_state[r['state']] = by_state.get(r['state'], 0) + 1
    doc['rebuilds'] = list(committed.get('rebuilds') or []) + [{
        'date': date, 'source_fetched_at': fetched_at, 'why': why, 'rows_added': len(added),
        'permits_added': len({r['npdes_permit'] for r in added}), 'rows_added_by_state': dict(sorted(by_state.items())),
        'rows_changed': {k: v for k, v in sorted(changed.items())},
        'rows_dropped': {k: v for k, v in sorted(dropped.items())},
        'rows_unchanged': len(rows) - len(added) - len({x for v in changed.values() for x in v})}]
    doc['cso_features_not_in_inventory'] = rebuilt['cso_features_not_in_inventory']
    doc['outfalls'] = rows
    return doc, problems, added


def write(path, doc):
    """The layout build_plant_outfalls.py and ingest.outfall_waters.write_plants use: header keys one per line, then
    one row per line."""
    with open(path, 'w') as fh:
        fh.write('{\n')
        for k, v in doc.items():
            if k in ('outfalls', 'cso_features_not_in_inventory'):
                continue
            fh.write(json.dumps(k) + ': ' + json.dumps(v, ensure_ascii=False) + ',\n')
        fh.write('"cso_features_not_in_inventory": [\n' + ',\n'.join(
            json.dumps(r, ensure_ascii=False) for r in doc['cso_features_not_in_inventory']) + '\n],\n')
        fh.write('"outfalls": [\n' + ',\n'.join(json.dumps(r, ensure_ascii=False) for r in doc['outfalls']) + '\n]\n}\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('committed')
    ap.add_argument('rebuilt')
    ap.add_argument('out')
    ap.add_argument('--date', required=True)
    ap.add_argument('--fetched-at', required=True)
    ap.add_argument('--why', required=True)
    ap.add_argument('--accept', action='append', default=[], metavar='FIELD',
                    help='a row field the rebuild may change on a committed row (repeatable)')
    ap.add_argument('--drop-excluded', action='store_true',
                    help="drop a committed row whose permit the rebuild lists in excluded_not_sewage")
    a = ap.parse_args(argv)
    doc, problems, added = merge(json.load(open(a.committed)), json.load(open(a.rebuilt)), a.date, a.fetched_at, a.why,
                                 a.accept, a.drop_excluded)
    if problems:
        print(f'{len(problems)} committed rows are not reproduced by the rebuild; nothing written', file=sys.stderr)
        for p in problems[:20]:
            print(' ', json.dumps(p), file=sys.stderr)
        return 1
    write(a.out, doc)
    print(json.dumps(doc['rebuilds'][-1], indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
