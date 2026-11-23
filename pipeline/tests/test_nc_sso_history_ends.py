"""The two real DWR records for incident 202500025; identity is not proximity or a date."""
import copy
import json
from pathlib import Path

import common
from ingest import nc_dwr_sso as N

FIX = Path(__file__).parent / 'fixtures' / 'nc_sso_history_end_join.json'
NOW = '2026-11-22T12:00:00Z'


def pair():
    d = json.loads(FIX.read_text())
    return d['history'], d['survey']


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
