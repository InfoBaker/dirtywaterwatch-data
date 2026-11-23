"""Progressive water builds must not evict unrelated historical placements."""
import copy
import json
from datetime import timedelta

import pytest

from build import status as S
from tests.test_placement_cache import recs, world
from tests.test_placement_steps import NOW, WATERS


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('variants', [
    [{'water_matched_by': 'checked'}, {'water_matched_by': 'verified'}],
    [{'water_matched_by': 'checked', 'water_slug': None, 'no_water_reason': reason}
     for reason in ('unmapped', 'no outline')],
    [{'water_matched_by': 'ingest.outfall_waters', 'water_match': step}
     for step in ('geometry: checked', 'name: checked')],
    [{'match': 'geometry'}, {'match': 'name_only'}],
    [{'distance_m': 1}, {'distance_m': 1.0}],
], ids=['matched-by', 'no-water-reason', 'water-match', 'match', 'distance'])
def test_registry_memo_keeps_each_rows_placement_note(variants, reverse):
    waters = {'example-ma': dict(name='Example Creek', state='MA', kind='stream')}
    row = dict(npdes_permit='MA0000001', outfall='C01', state='MA',
               water_slug='example-ma', receiving_water='Example Creek')
    rows = [{**row, **v} for v in variants]
    if reverse:
        rows.reverse()
    expected = [S.Resolver(waters, [], {}, {}, {}).row_water(r) for r in rows]
    assert expected[0] != expected[1]
    resolver = S.Resolver(waters, rows, {}, {}, {})
    assert [resolver.row_water(r) for r in rows] == expected


@pytest.mark.parametrize('reverse_initial', [False, True], ids=['a-first', 'b-first'])
@pytest.mark.parametrize('reverse_refresh', [False, True], ids=['keep-order', 'reverse-order'])
def test_distinct_registry_rows_keep_own_placement_after_water_addition(
        tmp_path, monkeypatch, capsys, reverse_initial, reverse_refresh):
    """Caller-supplied rows may share permit/outfall IDs but require different water lookups."""
    from tests.test_placement_steps import ev
    monkeypatch.setattr(S, 'now_iso', lambda: NOW.isoformat())
    monkeypatch.setattr(S, '_GEOM_CACHE', {})
    monkeypatch.setattr(S, '_STATES', None)
    monkeypatch.setattr(S, 'OBL_WATER_DIR', tmp_path / 'outlines')
    monkeypatch.setattr(S, 'BUILD_DIR', tmp_path / 'output')
    row = dict(npdes_permit='MA0000001', outfall='C01', state='MA', receiving_water='Example Creek')
    outfalls = [dict(row, outfall_name='MWR001: First', water_matched_by='checked', no_water_reason='unmapped'),
               dict(row, outfall_name='MWR002: Second')]
    common = dict(npdes_permit='MA0000001', waterbody_text='Unmapped', raw={'state': 'MA'},
                  started_at=(NOW - timedelta(days=400)).isoformat(),
                  ended_at=(NOW - timedelta(days=399)).isoformat())
    records = [ev('a', **common, outfall_id='MWR001', water_slugs=['future-ma'], water_match='geometry'),
               ev('b', **common, outfall_id='MWR002')]
    if reverse_initial:
        records.reverse()
    kw = world(tmp_path, records, {'example-ma': dict(name='Example Creek', state='MA', kind='stream')})
    kw.update(outfalls=outfalls, write=True, rain={}, discharger_aliases_map={})
    S.build(**kw)
    capsys.readouterr()
    kw['waters']['future-ma'] = dict(name='New Reach', state='MA', kind='stream')
    if reverse_refresh:
        path = kw['events_dir'] / 'ma-test.json'
        doc = json.loads(path.read_text())
        doc['records'].reverse()
        path.write_text(json.dumps(doc))
    warm, _ = S.build(**kw)
    assert 'placement reused for 1 of 2' in capsys.readouterr().out
    warm_bytes = {p.name: p.read_bytes() for p in S.BUILD_DIR.glob('*.json')}
    cold, _ = S.build(**{**kw, 'placement_cache': False})
    assert set(warm_bytes) == {'status.json', 'history.json'}
    assert warm_bytes == {p.name: p.read_bytes() for p in S.BUILD_DIR.glob('*.json')}
    assert warm['placements'] == cold['placements']
    assert warm['placements']['ma-test:a']['water_slugs'] == ['future-ma']
    assert warm['placements']['ma-test:b']['water_slugs'] == ['example-ma']


@pytest.mark.parametrize('change,hits', [('unchanged', 3), ('other_state', 3), ('same_state', 3),
                                        ('alias', 1), ('outline', 2), ('remove', 2), ('order', 3), ('alias_order', 3)])
def test_selective_refresh_matches_cold_bytes(tmp_path, monkeypatch, capsys, change, hits):
    monkeypatch.setattr(S, 'now_iso', lambda: NOW.isoformat())
    monkeypatch.setattr(S, '_GEOM_CACHE', {})
    monkeypatch.setattr(S, '_STATES', None)
    monkeypatch.setattr(S, 'OBL_WATER_DIR', tmp_path / 'outlines')
    monkeypatch.setattr(S, 'BUILD_DIR', tmp_path / 'output')
    kw = world(tmp_path, recs()[:-1], copy.deepcopy(WATERS))
    kw.update(write=True, rain={}, discharger_aliases_map={})
    kw['rules']['live_states'] = ['MA', 'CT']
    if change == 'alias_order':
        kw['waters']['short-brook-ma']['aliases'] = ['Example Brook', 'Example Stream']
    S.build(**kw)
    capsys.readouterr()
    if change in ('other_state', 'same_state'):
        kw['waters']['distant-lake'] = dict(name='Distant Lake', state='CT' if change == 'other_state' else 'MA',
                                           kind='lake', bbox=[-73, 41, -72.9, 41.1])
    elif change == 'alias':
        kw['waters']['short-brook-ma']['aliases'] = ['Nowhere Creek']
    elif change == 'outline':
        kw['waters']['test-river-ma']['geometry'] = {'type': 'LineString', 'coordinates': [[-71, 41], [-70.9, 41]]}
    elif change == 'remove':
        del kw['waters']['test-river-ma']
    elif change == 'alias_order':
        kw['waters']['short-brook-ma']['aliases'].reverse()
    elif change == 'order':
        kw['waters'] = dict(reversed(list(kw['waters'].items())))
    S._GEOM_CACHE.clear()
    S.build(**kw)
    assert f'placement reused for {hits} of 3' in capsys.readouterr().out
    warm = {p.name: p.read_bytes() for p in S.BUILD_DIR.glob('*.json')}
    S._GEOM_CACHE.clear()
    S.build(**{**kw, 'placement_cache': False})
    assert warm == {p.name: p.read_bytes() for p in S.BUILD_DIR.glob('*.json')}


@pytest.mark.parametrize('kind', ['point', 'registry_memo', 'label_memo', 'slug_alias', 'reference'])
def test_negative_queries_and_memoized_reads_invalidate(tmp_path, monkeypatch, kind):
    """Two identical records exercise internal memos; a third name in another state stays reusable."""
    from build import redact as R
    from tests.test_placement_steps import ev, w
    from datetime import timedelta
    monkeypatch.setattr(S, '_GEOM_CACHE', {})
    monkeypatch.setattr(S, '_STATES', {'MA', 'CT'})
    monkeypatch.setattr(S, 'OBL_WATER_DIR', tmp_path / 'outlines')
    kw = dict(waterbody_text='Unmapped', lat=41.5, lon=-72.5, raw={'state': 'MA'})
    outfalls = []
    waters = copy.deepcopy(WATERS)
    if kind == 'registry_memo':
        kw = dict(npdes_permit='MA0000001', outfall_id='001', raw={'state': 'MA'})
        outfalls = [dict(npdes_permit='MA0000001', outfall='001', state='MA',
                        receiving_water='Future Creek', lat=41.5, lon=-72.5)]
    elif kind == 'label_memo':
        kw = dict(waterbody_text='Test River Basin', raw={'state': 'MA'})
    elif kind == 'slug_alias':
        kw = dict(water_slugs=['retired-ma'], raw={'state': 'MA'})
    elif kind == 'reference':
        # A place-style synthetic token; the predicate is controlled without storing a person's name.
        kw = dict(waterbody_text='Example Place', raw={'state': 'MA'})
        monkeypatch.setattr(S, 'person_shaped', lambda text: text == 'Example Place')
    records = [ev(str(i), **kw, started_at=(NOW - timedelta(days=400)).isoformat()) for i in range(2)]
    records.append(ev('outside', waterbody_text='Other River', raw={'state': 'CT'},
                      started_at=(NOW - timedelta(days=400)).isoformat()))
    def cache(resolver, saved=None):
        from build.placement_cache import Dependencies
        hashes = {}
        S.placement_stamp(resolver.waters, outfalls, {}, {}, {}, {'MA', 'CT'}, water_hashes=hashes)
        return Dependencies(resolver, hashes, saved)
    first = cache(S.Resolver(waters, outfalls, {}, {}, {}))
    held = [first.resolve(r) for r in records]
    if kind in ('point', 'registry_memo'):
        slug, water = w('future-creek-ma', 'Future Creek', 'stream',
                        {'type': 'LineString', 'coordinates': [[-72.51, 41.5], [-72.49, 41.5]]})
        waters[slug] = water
    elif kind == 'label_memo':
        waters['short-brook-ma']['aliases'] = ['Test River Basin']
    elif kind == 'slug_alias':
        waters['short-brook-ma']['slug_aliases'] = ['retired-ma']
    else:
        monkeypatch.setattr(S, 'person_shaped', lambda text: False)
    S._GEOM_CACHE.clear()
    second = cache(S.Resolver(waters, outfalls, {}, {}, {}), first.saved())
    assert [second.valid(group) for _, group in held] == [False, False, True]
    for record, (old, group) in zip(records, held):
        result = old if second.valid(group) else second.resolve(record)[0]
        assert result == S.Resolver(waters, outfalls, {}, {}, {}).resolve(record)


def test_real_nhd_writer_progress_and_obl_snapshot_restore(tmp_path, monkeypatch):
    """Real writers, loaders and reference vocabulary; no network or production event data."""
    import json
    import tarfile
    from pathlib import Path
    from shapely.geometry import shape
    from build import redact as R
    from ingest import waters_from_nhd as N, obl_waters as O
    data = tmp_path / 'data'
    data.mkdir()
    outlines = tmp_path / 'outlines'
    outlines.mkdir()
    monkeypatch.setattr(S, 'DATA_DIR', data)
    monkeypatch.setattr(S, 'OBL_WATER_DIR', outlines)
    monkeypatch.setattr(R, 'DATA_DIR', data)
    monkeypatch.setattr(N, 'OUT', data / 'waters-nhd.json')
    monkeypatch.setattr(N, 'now_iso', lambda: NOW.isoformat())
    fixture = Path(__file__).parent / 'fixtures' / 'obl-snapshot' / 'water'
    snapshots = []
    references = []
    for run in range(3):
        # Restore the same payload in opposite tar member order; metadata alone is immaterial.
        with tarfile.open(tmp_path / 'outlines.tar', 'w') as tf:
            for p in sorted(fixture.glob('*.json'), reverse=bool(run)):
                tf.add(p, arcname=p.name)
        with tarfile.open(tmp_path / 'outlines.tar') as tf:
            tf.extractall(outlines, filter='data')
        O.extract('NC', outlines, data / 'waters-nc.json', snapshot=f'2026-11-{21 + run}')
        rows = list(WATERS.values())[:1 + bool(run)]
        N.write_output([{**r, '_geom': shape(r['geometry'])} for r in rows], [], [], [], partial=True, final=True)
        R.reference_names.cache_clear()
        R._reference_norm.cache_clear()
        S._GEOM_CACHE.clear()
        waters = S.load_waters()
        parts = {}
        S.placement_stamp(waters, [], {}, {}, {}, {'MA', 'NC'}, parts=parts)
        snapshots.append(parts)
        references.append(R._reference_norm(str(data)))
    assert snapshots[0]['waters'] != snapshots[1]['waters']
    assert snapshots[0]['outlines'] != snapshots[1]['outlines']
    assert references[0] != references[1]  # The old stamp hashed this entire vocabulary.
    assert snapshots[1] == snapshots[2]  # An identical rerun changes only writer metadata.
    R.reference_names.cache_clear()
    R._reference_norm.cache_clear()


def test_spatial_candidates_keep_inclusive_edges_state_and_canonical_order():
    waters = {
        'z': {'state': 'MA', 'bbox': [-72, 41, -71, 42]},
        'a': {'state': 'MA', 'bbox': [-72, 41, -71, 42]},
        'b': {'state': 'CT', 'bbox': [-72, 41, -71, 42]},
        'missing': {'state': 'MA'},
    }
    resolver = S.Resolver(waters, [], {}, {}, {})
    for lat, lon in [(41, -72), (40.99, -72.01), (42.01, -70.99), (42.010001, -70.99), (0, 0)]:
        for state in ('MA', 'CT', None):
            expected = [s for s, w in sorted(waters.items()) if w.get('bbox')
                        and (state is None or w['state'] == state)
                        and w['bbox'][0] - .01 <= lon <= w['bbox'][2] + .01
                        and w['bbox'][1] - .01 <= lat <= w['bbox'][3] + .01]
            assert resolver.point_candidates(lat, lon, state) == expected


def test_reference_stamp_only_keeps_predicate_inputs(tmp_path, monkeypatch):
    from build import redact as R
    monkeypatch.setattr(S, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(S, 'OBL_WATER_DIR', tmp_path)
    names, towns = {'test river'}, {'example town'}
    monkeypatch.setattr(R, '_reference_norm', lambda _: (frozenset(names), frozenset(towns)))
    def stamp():
        return S.placement_stamp({}, [], {}, {}, {}, {'MA'})
    baseline = stamp()
    names.add('new creek')
    towns.add('another town')
    assert stamp() == baseline
    # Frances Slocum is a public Pennsylvania lake, whose shortened name the vocabulary retains.
    names.add('frances slocum')
    assert stamp() != baseline
    baseline = stamp()
    towns.add('austin')
    assert stamp() != baseline


def test_successive_catalog_edits_match_uncached_resolver(tmp_path, monkeypatch):
    """Exercise negative indexes, multi-name text, point fallbacks and shared memos over several edits."""
    import random
    from build.placement_cache import Dependencies
    from tests.test_placement_steps import ev, w
    rng = random.Random(15)
    monkeypatch.setattr(S, '_STATES', {'MA', 'CT'})
    monkeypatch.setattr(S, 'OBL_WATER_DIR', tmp_path)
    waters = {}
    for i in range(12):
        slug, row = w(f'catalog-{i}', f'Example Creek {i // 2}', 'stream',
                      {'type': 'LineString', 'coordinates': [[-72 + i*.02, 42], [-72 + i*.02, 42.01]]},
                      state='MA' if i % 2 else 'CT')
        waters[slug] = row
    records = [ev(str(i), waterbody_text=f'Example Creek {rng.randrange(8)}',
                  raw={'state': rng.choice(['MA', 'CT'])}, lat=42.005, lon=-72+rng.randrange(15)*.02)
               for i in range(80)]
    records += [ev(f'slug-{i}', water_slugs=[f'catalog-{i}'], raw={'state': 'MA'}) for i in range(15)]
    saved, held = None, None
    for step in range(6):
        if step == 1:
            waters['catalog-1']['aliases'] = ['Example Creek 7']
        elif step == 2:
            waters['catalog-3']['geometry']['coordinates'] = [[-71.9, 42], [-71.9, 42.01]]
        elif step == 3:
            waters['catalog-5']['bbox'] = [-72, 42, -71.5, 42.1]
        elif step == 4:
            del waters['catalog-7']
        elif step == 5:
            waters['catalog-9']['slug_aliases'] = ['catalog-13']
        S._GEOM_CACHE.clear()
        resolver = S.Resolver(waters, [], {}, {}, {})
        hashes = {}
        S.placement_stamp(waters, [], {}, {}, {}, {'MA', 'CT'}, water_hashes=hashes)
        deps = Dependencies(resolver, hashes, saved)
        current = []
        for i, record in enumerate(records):
            if held and deps.valid(held[i][1]):
                current.append((held[i][0], deps.import_group(held[i][1])))
            else:
                current.append(deps.resolve(record))
        S._GEOM_CACHE.clear()
        cold = S.Resolver(waters, [], {}, {}, {})
        assert [p for p, _ in current] == [cold.resolve(record) for record in records]
        held, saved = current, deps.saved()


def test_registry_memo_observations_survive_metadata_variants(tmp_path, monkeypatch):
    from build.placement_cache import Dependencies
    from tests.test_placement_steps import ev
    monkeypatch.setattr(S, '_STATES', {'MA'})
    monkeypatch.setattr(S, '_GEOM_CACHE', {})
    monkeypatch.setattr(S, 'OBL_WATER_DIR', tmp_path)
    row = dict(npdes_permit='MA0000001', outfall='001', state='MA', receiving_water='Future Creek')
    waters = copy.deepcopy(WATERS)
    hashes = {}
    S.placement_stamp(waters, [row], {}, {}, {}, {'MA'}, water_hashes=hashes)
    first = Dependencies(S.Resolver(waters, [row], {}, {}, {}), hashes)
    records = [ev(str(i), npdes_permit='MA0000001', outfall_id='001') for i in range(2)]
    held = [first.resolve(records[0])]
    row['fetched_at'] = '2026-11-23T04:00:00Z'  # Same resolver memo key, different harmless metadata.
    held.append(first.resolve(records[1]))
    waters['future-ma'] = dict(name='Future Creek', state='MA', kind='stream', towns=[])
    hashes = {}
    S.placement_stamp(waters, [row], {}, {}, {}, {'MA'}, water_hashes=hashes)
    second = Dependencies(S.Resolver(waters, [row], {}, {}, {}), hashes, first.saved())
    assert [second.valid(group) for _, group in held] == [False, False]


def test_canonical_order_also_controls_equal_distance_ties(monkeypatch):
    from tests.test_placement_steps import ev, w
    monkeypatch.setattr(S, '_STATES', {'MA'})
    monkeypatch.setattr(S, '_GEOM_CACHE', {})
    geometry = {'type': 'LineString', 'coordinates': [[-72, 42], [-72, 42.01]]}
    waters = dict([w('b-ma', 'Example Creek', 'stream', geometry),
                   w('a-ma', 'Example Creek', 'stream', geometry)])
    record = ev('tie', waterbody_text='Example Creek', raw={'state': 'MA'}, lat=42.005, lon=-72)
    first = S.Resolver(waters, [], {}, {}, {}).resolve(record)
    second = S.Resolver(dict(reversed(list(waters.items()))), [], {}, {}, {}).resolve(record)
    assert first == second
    assert first['water_slugs'] == ['a-ma']
