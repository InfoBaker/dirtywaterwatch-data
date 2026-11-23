"""The two real DWR records for incident 202500025; identity is not proximity or a date."""
import copy
import json
from datetime import datetime
from pathlib import Path

import common
import pytest
from build import status as S
from ingest import nc_dwr_sso as N

FIX = Path(__file__).parent / 'fixtures' / 'nc_sso_history_end_join.json'
NOW = '2026-11-22T12:00:00Z'


def pair():
    d = json.loads(FIX.read_text())
    return d['history'], d['survey']


def water_pair():
    """Synthetic water evidence added to the trimmed real identity/time pair."""
    h, a = pair()
    h['waterbody_text'] = 'Cross Creek'
    h['raw']['reached_water'] = True
    h['raw']['_gallons_to_water'] = 2800
    return h, {**a, 'waterbody_type': 'Named Waterbody', 'waterbody': 'Cross Creek',
               'volume_waterbody': 2800}


def water_status(tmp_path, records, at):
    for sid in (N.HIST_ID, N.SOURCE_ID):
        (tmp_path / f'{sid}.json').write_text(json.dumps({
            'source_id': sid, 'ok': True, 'fetched_at': NOW,
            'records': [r for r in records if r['source_id'] == sid]}))
    waters = {slug: {'slug': slug, 'name': name, 'kind': 'river', 'state': 'NC'}
              for slug, name in [('cross-creek-nc', 'Cross Creek'), ('other-creek-nc', 'Other Creek')]}
    point = next((r for r in records if r.get('waterbody_text') == 'Cross Creek'
                  and r.get('lat') is not None and r.get('lon') is not None), None)
    if point:
        waters['cross-creek-nc']['geometry'] = {'type': 'Point', 'coordinates': [point['lon'], point['lat']]}
    status, _ = S.build(now=datetime.fromisoformat(at), events_dir=tmp_path, write=False,
                        waters=waters, outfalls=[], registry={}, reaches={}, flows=({}, {}),
                        discharger_towns={}, discharger_waters={}, discharger_aliases_map={},
                        placement_cache=False, rain={}, rules={
                            'red': {'by_state': {}}, 'yellow': {'default_hours': 72},
                            'unresolved': {'unknown_status_yellow_days': 14, 'unresolved_yellow_days': 30}})
    return status


@pytest.mark.parametrize('change', [
    {'waterbody_type': 'Not Impacted', 'volume_waterbody': 0, 'waterbody': None},
    {'waterbody': None},
    {'waterbody': 'Other Creek'},
    {'waterbody_type': 'Not Impacted', 'volume_waterbody': 0},
])
def test_history_water_conflict_keeps_placement_and_caution(tmp_path, change):
    h, a = water_pair()
    rs, _ = N.build([(N.SURVEY_LAYER, {**a, **change})], NOW, [], {})
    N.join_history([h], rs)
    out = water_status(tmp_path, [h, *rs], '2025-01-02T12:00:00-05:00')
    assert out['placements'][h['event_id']]['water_slugs'] == ['cross-creek-nc']
    assert out['waters']['cross-creek-nc']['status'] == 'yellow'
    assert h['event_id'] in {r['event_id'] for r in out['waters']['cross-creek-nc']['reasons']}
    assert h['duplicate_of'] is None


def test_history_point_cannot_be_replaced_by_a_different_placement(tmp_path):
    h, a = water_pair()
    # Points are from the existing agency fixture; the conflicting assignment is a synthetic variant.
    rows = [a for _, a in N._load_file(str(FIX.with_name('nc_dwr_sso_survey123.json')))]
    cross = next(r for r in rows if r['incident_number'] == '202500025')
    elsewhere = rows[0]
    h.update(lat=cross['latitude'], lon=cross['longitude'])
    a.update(latitude=elsewhere['latitude'], longitude=elsewhere['longitude'])
    rs, _ = N.build([(N.SURVEY_LAYER, a)], NOW, [], {})
    assert N.join_history([h], rs) == 0
    out = water_status(tmp_path, [h, *rs], '2025-01-02T12:00:00-05:00')
    assert out['placements'][h['event_id']]['water_slugs'] == ['cross-creek-nc']
    assert out['placements'][rs[0]['event_id']]['water_slugs'] == []
    assert out['waters']['cross-creek-nc']['status'] == 'yellow'
    assert {r['event_id'] for r in out['waters']['cross-creek-nc']['reasons']} == {h['event_id']}


@pytest.mark.parametrize('layer', [N.SURVEY_LAYER, N.LAYER])
@pytest.mark.parametrize('change,at,colour', [
    ({'start_date': 1735862400000, 'end_date': 1735869600000}, '2025-01-01T20:30:00-05:00', 'red'),
    ({'end_date': 1735779600000}, '2025-01-01T20:30:00-05:00', 'red'),
    ({'start_date': 1735779600000}, '2025-01-01T19:30:00-05:00', 'red'),
    ({'permit_with_name': None}, '2025-01-01T20:30:00-05:00', 'red'),
    ({'permit_with_name': 'WQCS00001'}, '2025-01-01T20:30:00-05:00', 'red'),
    ({'incident_number': None}, '2025-01-01T20:30:00-05:00', 'red'),
    ({'waterbody_type': 'Not Impacted', 'volume_waterbody': 0, 'waterbody': None},
     '2025-01-02T12:00:00-05:00', 'yellow'),
    ({'waterbody': 'Other Creek'}, '2025-01-02T12:00:00-05:00', 'yellow'),
    ({}, '2025-01-01T20:30:00-05:00', 'red'),
])
def test_sequential_refresh_retains_ambiguous_or_conflicting_reports(tmp_path, layer, change, at, colour):
    h, a = water_pair()
    first, _ = N.build([(layer, a)], NOW, [], {})
    old_id = first[0]['event_id']
    updated = {**a, **change, 'globalid': '00000000-0000-4000-8000-000000000001'}
    rs, _ = N.build([(N.SURVEY_LAYER, updated)], '2026-11-22T13:00:00Z', first, {})
    N.join_history([h], rs)
    out = water_status(tmp_path, rs, at)
    assert out['placements'][old_id]['water_slugs'] == ['cross-creek-nc']
    assert out['waters']['cross-creek-nc']['status'] == colour
    old = next(r for r in rs if r['event_id'] == old_id)
    assert old['started_at'] == '2025-01-01T19:00:00-05:00'
    assert old['ended_at'] == '2025-01-01T21:00:00-05:00'
    if layer == N.SURVEY_LAYER or change:
        assert all(r['duplicate_of'] is None for r in rs)
        if change.get('incident_number', a['incident_number']):
            assert h['duplicate_of'] is None
        assert old_id in {r['event_id'] for r in out['waters']['cross-creek-nc']['reasons']}
    else:
        assert old['duplicate_of'] == f"{N.SOURCE_ID}:{updated['globalid']}"


@pytest.mark.parametrize('missing', ['retained', 'both'])
def test_sequential_refresh_requires_permits_on_retained_reports(tmp_path, missing):
    h, a = water_pair()
    first, _ = N.build([(N.LAYER, {**a, 'permit_with_name': None})], NOW, [], {})
    updated = {**a, 'globalid': '00000000-0000-4000-8000-000000000001'}
    if missing == 'both':
        updated['permit_with_name'] = None
    rs, _ = N.build([(N.SURVEY_LAYER, updated)], '2026-11-22T13:00:00Z', first, {})
    assert N.join_history([h], rs) == 0
    assert all(r['duplicate_of'] is None for r in rs)
    out = water_status(tmp_path, rs, '2025-01-01T20:30:00-05:00')
    assert out['waters']['cross-creek-nc']['status'] == 'red'
    for r in rs:
        assert out['placements'][r['event_id']]['water_slugs'] == ['cross-creek-nc']
    assert {r['event_id'] for r in rs} == {
        r['event_id'] for r in out['waters']['cross-creek-nc']['reasons']}


def test_refresh_removes_an_old_history_join_when_water_evidence_changes(tmp_path, monkeypatch):
    h, a = water_pair()
    monkeypatch.setattr(common, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(N, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(N, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(N, 'permit_index', lambda: {})
    hp = tmp_path / f'{N.HIST_ID}.json'
    original = {'source_id': N.HIST_ID, 'ok': True, 'fetched_at': h['fetched_at'],
                'meta': {'frozen': True}, 'records': [h]}
    hp.write_text(json.dumps(original))
    source = tmp_path / 'input.json'
    for change in ({}, {'waterbody_type': 'Not Impacted', 'volume_waterbody': 0, 'waterbody': None}):
        source.write_text(json.dumps({'layer': N.SURVEY_LAYER, 'features': [{'attributes': {**a, **change}}]}))
        assert N.main(['--file', str(source)]) == 0
        kept = json.loads(hp.read_text())
        history = kept['records'][0]
        assert bool(history['duplicate_of']) is (not change)
    current = json.loads((tmp_path / f'{N.SOURCE_ID}.json').read_text())['records']
    assert '_history_join' not in history['raw']
    assert '_history_join' not in current[0]['raw']
    assert {k: v for k, v in kept.items() if k != 'records'} == {
        k: v for k, v in original.items() if k != 'records'}
    for field in ('started_at', 'ended_at', 'fetched_at', 'source_url'):
        assert history[field] == h[field]
    out = water_status(tmp_path, [history, *current], '2025-01-02T12:00:00-05:00')
    assert out['placements'][history['event_id']]['water_slugs'] == ['cross-creek-nc']
    assert out['placements'][current[0]['event_id']]['water_slugs'] == []
    assert out['waters']['cross-creek-nc']['status'] == 'yellow'
    assert {r['event_id'] for r in out['waters']['cross-creek-nc']['reasons']} == {history['event_id']}


def test_retained_ambiguity_clears_previously_accepted_links(tmp_path):
    h, a = water_pair()
    old = {**a, 'globalid': '00000000-0000-4000-8000-000000000001'}
    first, _ = N.build([(N.LAYER, old)], NOW, [], {})
    second, _ = N.build([(N.SURVEY_LAYER, a)], '2026-11-22T13:00:00Z', first, {})
    assert sum(bool(r['duplicate_of']) for r in second) == 1
    assert N.join_history([h], second) == 1
    third, _ = N.build([(N.SURVEY_LAYER, {**a, 'globalid': '00000000-0000-4000-8000-000000000002'})],
                       '2026-11-22T14:00:00Z', second, {})
    assert N.join_history([h], third) == 0
    assert all(r['duplicate_of'] is None for r in [h, *third])
    assert all('_history_join' not in r['raw'] for r in [h, *third])
    out = water_status(tmp_path, [h, *third], '2025-01-06T12:00:00-05:00')
    assert out['placements'][h['event_id']]['water_slugs'] == ['cross-creek-nc']
    assert out['waters']['cross-creek-nc']['status'] == 'yellow'
    assert {r['event_id'] for r in out['waters']['cross-creek-nc']['reasons']} == {h['event_id']}


def test_matching_history_number_does_not_discard_the_source_end():
    h, a = pair()
    rs, _ = N.build([(N.SURVEY_LAYER, a)], NOW, [], {}, {N.incident(h)})
    assert len(rs) == 1
    r = rs[0]
    assert r['ended_at'] == '2025-01-01T21:00:00-05:00'
    assert r['started_at'] == '2025-01-01T19:00:00-05:00'
    assert r['raw']['end_date'] == a['end_date']
    assert r['source_url'].startswith(N.SURVEY_LAYER)


def test_join_keeps_each_sources_times_and_citation_and_repeats_cleanly():
    h, a = pair()
    original = copy.deepcopy(h)
    rs, _ = N.build([(N.SURVEY_LAYER, a)], NOW, [], {})
    assert N.join_history([h], rs) == 1
    assert h['duplicate_of'] == rs[0]['event_id']
    for k in ('started_at', 'ended_at', 'fetched_at', 'source_url'):
        assert h[k] == original[k]
    assert h['raw']['_history_join']['source_url'] == rs[0]['source_url']
    assert rs[0]['raw']['_history_join']['event_id'] == h['event_id']
    assert N.join_history([h], rs) == 1
    assert rs[0]['duplicate_of'] is None


def test_ambiguous_or_conflicting_evidence_never_suppresses_history():
    for change in ({'permit_with_name':'WQCS00001'}, {'incident_number':'202500024'},
                   {'ongoing':'Yes'}, {'end_date':None}, {'end_date':1735770000000},
                   {'end_date':1893456000000},
                   {'start_date':1735862400000, 'end_date':1735869600000}):
        h, a = pair()
        rs, _ = N.build([(N.SURVEY_LAYER, {**a, **change})], NOW, [], {})
        assert N.join_history([h], rs) == 0, change
        assert not h['duplicate_of']
    h, a = pair()
    rs, _ = N.build([(N.SURVEY_LAYER, a)], NOW, [], {})
    other = copy.deepcopy(h); other['event_id'] += '-another'
    assert N.join_history([h, other], rs) == 0
    h['ended_at'] = '2025-01-02T21:00:00-05:00'
    assert N.join_history([h], rs) == 0


def test_ordinary_refresh_joins_retained_history_without_claiming_a_history_fetch(tmp_path, monkeypatch):
    h, a = pair()
    monkeypatch.setattr(common, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(N, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(N, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(N, 'permit_index', lambda: {})
    hp = tmp_path / f'{N.HIST_ID}.json'
    old = {'source_id':N.HIST_ID,'ok':False,'fetched_at':h['fetched_at'],'last_ok_at':h['fetched_at'],
           'meta':{'frozen':True},'records':[h],'count':1}
    hp.write_text(json.dumps(old))
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'layer':N.SURVEY_LAYER,'features':[{'attributes':a}]}))
    for _ in range(2):
        assert N.main(['--file',str(source)]) == 0
        kept = json.loads(hp.read_text())
        assert kept['records'][0]['duplicate_of'].startswith(N.SOURCE_ID + ':')
        assert {k:v for k,v in kept.items() if k!='records'} == {k:v for k,v in old.items() if k!='records'}


def test_repeated_survey_incident_or_different_permit_is_not_arbitrarily_suppressed():
    h, a = pair()
    for permit in (a['permit_with_name'], 'WQCS00001 - '):
        other = {**a, 'globalid':'00000000-0000-4000-8000-000000000001', 'permit_with_name':permit}
        rs, _ = N.build([(N.SURVEY_LAYER,a),(N.SURVEY_LAYER,other)], NOW, [], {})
        assert all(r['duplicate_of'] is None for r in rs)
        if permit == a['permit_with_name']:
            assert N.join_history([h], rs) == 0


def test_first_backfill_persists_both_citations(tmp_path, monkeypatch):
    h, a = pair()
    monkeypatch.setattr(common, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(N, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(N, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(N, 'permit_index', lambda: {})
    source = tmp_path/'source.json'
    source.write_text(json.dumps({'layer':N.SURVEY_LAYER,'features':[{'attributes':a}]}))
    hist = tmp_path/'history.json'
    hist.write_text(json.dumps({'features':[{'attributes':h['raw']}]}))
    assert N.main(['--file',str(source),'--backfill-file',str(hist)]) == 0
    current = json.loads((tmp_path/f'{N.SOURCE_ID}.json').read_text())['records'][0]
    history = json.loads((tmp_path/f'{N.HIST_ID}.json').read_text())['records'][0]
    assert current['raw']['_history_join']['event_id'] == history['event_id']
    assert history['duplicate_of'] == current['event_id']
