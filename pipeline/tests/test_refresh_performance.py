"""Byte-for-byte writer comparisons and work-count regressions. Synthetic, offline inputs only."""
import copy
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import box

from build import charts as C
from build import provisional_outfalls as P
from build import status as S
from common import write_json

NOW = '2026-11-22T18:26:00Z'


def records():
    out = []
    for i in range(100):
        start = datetime(2026, 3, 7, 12, tzinfo=UTC) + timedelta(days=i * 2)
        out.append({'event_id': f'ct-synthetic:{i}', 'source_id': 'ct-synthetic',
            'source_record_id': str(i), 'event_type': 'cso', 'status': 'ended',
            'started_at': start.isoformat(), 'ended_at': (start + timedelta(hours=3)).isoformat(),
            'time_precision': 'minute', 'fetched_at': NOW, 'raw': {'state': 'CT'},
            'discharger_id': 'ct-synthetic', 'npdes_permit': 'CT0000001',
            'lat': 41.3, 'lon': -73., 'water_slugs': ['sample-ct'],
            'outfall_name': 'Pump station', 'outfall_id': '001', 'waterbody_text': 'Sample River',
            'volume_gal': 120})
    return out


def reference_places():
    ns = dict(vars(P))
    src = (Path(__file__).parent / 'fixtures/refresh_performance/provisional_reference.txt').read_text()
    exec(compile(src, 'provisional_reference', 'exec'), ns)
    return ns


@pytest.mark.parametrize('state', [['CT'], {'code': 'CT'}, 7])
def test_malformed_registry_state_preserves_coordinate_rejection(state):
    ev = dict(records()[0], event_id='synthetic:zero', source_id='synthetic',
              discharger_id='synthetic', npdes_permit=None, raw={}, water_slugs=[], lat=0, lon=0)
    kwargs = dict(outlines={}, key={}, by_id={'synthetic': {'state': state}})
    expected = reference_places()['build_places']([ev], **kwargs)
    assert expected[1] == Counter({'point at (0, 0)': 1})
    assert P.build_places([ev], **kwargs) == expected


def test_place_checks_scale_with_distinct_points_and_names(monkeypatch):
    counts = Counter()
    for name in ('coord_problem', 'safe_place_name', 'person_like'):
        orig = getattr(P, name)
        def counted(*args, _name=name, _orig=orig, **kwargs):
            counts[_name] += 1
            return _orig(*args, **kwargs)
        monkeypatch.setattr(P, name, counted)
    P.build_places(records(), outlines={'CT': box(-74, 41, -72, 42)}, key={}, by_id={})
    assert counts['coord_problem'] == 1
    assert counts['safe_place_name'] == 1
    assert counts['person_like'] <= 2


def provisional_world(monkeypatch, tmp_path):
    evs = records()
    evs += [dict(evs[0], event_id='ct-synthetic:unknown', lat=None, lon=None)]
    # Identical geolocation text, but eligibility and privacy remain per record.
    for i, raw in enumerate([{'reached_water': True}, {'reached_water': False},
                             {'reached_water': False}, {'BYPASS_PRIV_PUB': 'Yes'},
                             {'reached_water': True}, {'reached_water': True}]):
        evs.append(dict(evs[0], event_id=f'ct-synthetic:geo-{i}', lat=None, lon=None,
                        outfall_name='Pump Station, Sample Road',
                        waterbody_text='Sample Canal' if i >= 4 else 'Sample River',
                        raw={'state': 'CT', **raw}))
    # Distinct strings may scrub/truncate to the same public text; counts and tie order must survive.
    for i, e in enumerate(evs[:10]):
        e['outfall_name'] = ['Pump  station', 'Pump station', None, ['malformed'], 'Main station'][i % 5]
        e['waterbody_text'] = 'Sample River ' + 'x' * (120 + i)
    evs[1]['raw'] = {'state': 'CT', 'reached_water': False}
    evs[2]['duplicate_of'] = evs[0]['event_id']
    evs[3]['raw'] = {'state': 'CT', 'BYPASS_PRIV_PUB': 'Yes'}
    evs[4]['lat'], evs[4]['lon'] = 0, 0
    evs[5]['lat'] = 'invalid'
    evs[6]['lat'] = []
    evs[7]['lat'], evs[7]['lon'] = 41.3008, -73.
    waters = {'sample-ct': {'name': 'Sample River', 'state': 'CT', 'kind': 'river'}}
    monkeypatch.setattr(P, 'now_iso', lambda: NOW)
    monkeypatch.setattr(P, 'time', SimpleNamespace(monotonic=lambda: 1000.))
    monkeypatch.setattr(P, 'load_report_events', lambda: copy.deepcopy(evs))
    monkeypatch.setattr(P, 'operator_index', lambda: ({}, {}))
    monkeypatch.setattr(P, 'state_outlines', lambda: {'CT': box(-74, 41, -72, 42)})
    monkeypatch.setattr(P, 'registry_rows', lambda: [{'npdes_permit': 'CT0000001', 'outfall': '002',
                                                   'lat': 41.31, 'lon': -73.}])
    monkeypatch.setattr(P, 'state_layer_rows', lambda: [])
    monkeypatch.setattr(P, 'previous_rows', lambda: {'ct-synthetic': [
        {'id': 'old-place', 'lat': 41.3, 'lon': -73., 'first_seen': '2025-01-01T00:00:00Z'}]})
    monkeypatch.setattr(P, 'load_cache', lambda: {'hydro': {}, 'flowline': {}, 'waterbody': {}, 'dm': {}})
    matcher = P.WaterMatcher
    monkeypatch.setattr(P, 'WaterMatcher', lambda: matcher(waters))
    return SimpleNamespace(offline=True, no_water=False, geolocate=False, llm=False, budget_s=45,
                           max_requests=150, workers=1, first='position', refine=False, verbose=False)


@pytest.mark.parametrize('stage_flags', [False, True])
def test_provisional_complete_file_matches_original(monkeypatch, tmp_path, stage_flags):
    original = reference_places()
    args = provisional_world(monkeypatch, tmp_path)
    geo_groups, geo_rows = [], []
    if stage_flags:
        from build import report_geolocate as RG, llm_judge as LJ
        monkeypatch.setattr(RG, 'time', SimpleNamespace(monotonic=lambda: 1000.))
        monkeypatch.setattr(RG, 'GEO_CACHE', tmp_path / 'absent-geo-cache.json')
        monkeypatch.setattr(RG, 'resolve', lambda *a, **kw: {
            'status': 'placed', 'lat': 41.32, 'lon': -73., 'step': 'b',
            'confidence': 'medium', 'detail': 'Synthetic offline lookup', 'precision_m': 50})
        changed_place_row = P.place_row
        def track_changed_place_row(op, oprow, permits, group):
            row = changed_place_row(op, oprow, permits, group)
            if any(e.get('coord_source') == 'geocode' for _, _, e in group):
                geo_groups.append([e for _, _, e in group])
                geo_rows.append(row)
            return row
        monkeypatch.setattr(P, 'place_row', track_changed_place_row)
        monkeypatch.setattr(LJ, 'env_value', lambda name: None)
        judge = LJ.Judge
        monkeypatch.setattr(LJ, 'Judge', lambda **kw: judge(**kw, cache_path=tmp_path / 'absent-model.json',
                                                          log_path=tmp_path / 'unused-log.jsonl'))
        args.geolocate = args.llm = True
        args.geo_budget_s, args.llm_cap_usd, args.llm_budget_s = 30, .25, 60
    monkeypatch.setattr(P, 'OUT', tmp_path / 'new.json')
    P.run(args)
    if stage_flags:
        assert geo_groups
        geocoded = {e['event_id']: e for group in geo_groups for e in group}
        assert all(f'ct-synthetic:geo-{i}' in geocoded for i in (0, 1, 2, 4, 5))
        assert 'ct-synthetic:geo-3' not in geocoded
        assert {bool(S.reached_no_water(geocoded[f'ct-synthetic:geo-{i}'])) for i in range(3)} == {False, True}
        # Counting the repeated dry-land text would incorrectly put River first.
        assert geo_rows[0]['reports_water_text'] == ['Sample Canal', 'Sample River']
    changed_geo_calls = len(geo_groups)
    monkeypatch.setattr(P, 'build_places', original['build_places'])
    monkeypatch.setattr(P, 'place_row', original['place_row'])
    monkeypatch.setattr(P, 'OUT', tmp_path / 'old.json')
    P.run(args)
    assert len(geo_groups) == changed_geo_calls, 'reference geolocation must use original place_row'
    assert (tmp_path / 'new.json').read_bytes() == (tmp_path / 'old.json').read_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['new.json', 'old.json']


def chart_world(monkeypatch, tmp_path):
    evs = records()
    # Different state windows, water contexts, long/unknown ends, day precision, totals and advisories.
    for i, e in enumerate(evs):
        if i % 10 == 0:
            e['ended_at'] = (datetime.fromisoformat(e['started_at']) + timedelta(days=40)).isoformat()
        if i % 10 == 1:
            e['ended_at'], e['status'] = None, 'ongoing'
        if i % 10 == 2:
            e['ended_at'], e['status'] = None, 'unknown'
        if i % 10 == 3:
            e['time_precision'] = 'day'
        if i % 10 == 4:
            e['event_type'], e['status'] = 'hab_advisory', 'advisory_active'
        if i % 10 == 5:
            e['time_precision'] = 'month'
        if i % 10 == 6:
            e['raw']['_citizen_report'] = True
    waters = {'sample-ct': {'name': 'Sample River', 'state': 'CT', 'kind': 'river'},
              'sample-ny': {'name': 'Sample River', 'state': 'NY', 'kind': 'lake', 'area_km2': 2}}
    write_json(tmp_path / 'dischargers.json', [{'id': 'ct-synthetic', 'name': 'Synthetic utility'}])
    write_json(tmp_path / 'status.json', {
        'waters': {slug: {'events': [e['event_id'] for e in evs]} for slug in waters},
        'placements': {e['event_id']: {'water_slugs': ['sample-ct']} for e in evs}})
    write_json(tmp_path / 'history.json', {})
    monkeypatch.setattr(C, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(C, 'BUILD_DIR', tmp_path)
    monkeypatch.setattr(C, 'load_waters', lambda: waters)
    monkeypatch.setattr(C, 'load_events', lambda **kw: ({'ct-synthetic': {'fetched_at': NOW}}, copy.deepcopy(evs), []))
    monkeypatch.setattr(C, 'now_iso', lambda: NOW)
    return datetime.fromisoformat(NOW)


def output_bytes(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob('*.json')}


@pytest.mark.parametrize('refresh', [False, True])
def test_chart_complete_files_match_original_uncached_intervals(monkeypatch, tmp_path, refresh):
    now = chart_world(monkeypatch, tmp_path)
    monkeypatch.setattr(C, 'CHARTS_DIR', tmp_path / 'new')
    if refresh:
        monkeypatch.setattr(C, 'MAX_CACHED_INTERVALS', 3)
        C.build(now=now)
        now += timedelta(days=9)
        rules = copy.deepcopy(S.load_rules())
        rules['red']['by_state']['CT']['hours'] = 12
        monkeypatch.setattr(C, 'load_rules', lambda: rules)
        load = C.load_events
        def revised(**kw):
            files, evs, problems = load(**kw)
            evs[0]['ended_at'] = evs[0]['started_at']
            return files, evs, problems
        monkeypatch.setattr(C, 'load_events', revised)
    C.build(now=now)
    # The original red_intervals path, including its per-entity long-event counter.
    monkeypatch.setattr(C, '_cached_red_intervals',
        lambda ev, state, now, capped, water, rules, cache:
            C.red_intervals(ev, state, now, capped, water=water, rules=rules))
    monkeypatch.setattr(C, 'CHARTS_DIR', tmp_path / 'old')
    C.build(now=now)
    assert output_bytes(tmp_path / 'new') == output_bytes(tmp_path / 'old')


def test_chart_reuses_identical_contexts_only(monkeypatch, tmp_path):
    now = chart_world(monkeypatch, tmp_path)
    original = C.red_intervals
    calls = Counter()
    def count(ev, state, *args, water=None, **kw):
        calls[(ev['event_id'], state, (water or {}).get('slug'))] += 1
        return original(ev, state, *args, water=water, **kw)
    monkeypatch.setattr(C, 'red_intervals', count)
    C.build(now=now, write=False)
    assert calls[('ct-synthetic:0', 'CT', None)] == 1
    assert calls[('ct-synthetic:0', 'NY', None)] == 0
    assert calls[('ct-synthetic:0', 'CT', 'sample-ct')] >= 1


def test_interval_cache_keeps_state_and_event_identity_and_counts():
    ev = records()[0]
    ev['ended_at'] = '2026-05-01T12:00:00Z'
    now = datetime.fromisoformat(NOW)
    rules = S.load_rules()
    cache = {}
    for state, water, event in [('CT', None, ev), ('NY', None, ev), ('CT', None, ev),
                                ('CT', {'kind': 'lake', 'slug': 'sample'}, ev),
                                ('CT', None, dict(ev, ended_at=None, status='unknown'))]:
        want_count, got_count = Counter(), Counter()
        want = C.red_intervals(event, state, now, want_count, water=water, rules=rules)
        got = C._cached_red_intervals(event, state, now, got_count, water, rules, cache)
        assert got == want and got_count == want_count
    assert len(cache) == 3


def test_interval_cache_bounds_retained_results(monkeypatch):
    monkeypatch.setattr(C, 'MAX_CACHED_INTERVALS', 3, raising=False)
    events = records()[:10]
    events[0]['ended_at'] = '2026-05-01T12:00:00Z'
    events[5]['ended_at'] = '2026-05-01T12:00:00Z'
    cache = {}
    now, rules = datetime.fromisoformat(NOW), S.load_rules()
    # Saturate, then repeat: capped counts and intervals must also survive misses.
    for ev in events + events:
        want_count, got_count = Counter(), Counter()
        want = C.red_intervals(ev, 'CT', now, want_count, rules=rules)
        got = C._cached_red_intervals(ev, 'CT', now, got_count, None, rules, cache)
        assert got == want and dict(got_count) == dict(want_count)
        assert len(cache) <= 3


def test_interval_cache_retains_scalar_cap_increment():
    ev = records()[0]
    ev['ended_at'] = '2026-05-01T12:00:00Z'
    cache = {}
    C._cached_red_intervals(ev, 'CT', datetime.fromisoformat(NOW), Counter(), None, S.load_rules(), cache)
    _, increment = cache[(id(ev), 'CT')]
    assert type(increment) is int and increment == 1


def test_point_cache_does_not_survive_outline_changes():
    evs = records()
    yes, _, _ = P.build_places(evs, outlines={'CT': box(-74, 41, -72, 42)}, key={}, by_id={})
    no, drops, unlocated = P.build_places(evs, outlines={'CT': box(-72, 41, -71, 42)}, key={}, by_id={})
    assert yes and not no and len(unlocated) == len(evs)
    assert drops["point outside the report's state"] == len(evs)
