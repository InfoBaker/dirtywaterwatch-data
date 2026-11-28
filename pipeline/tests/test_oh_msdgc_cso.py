"""MSDGC public query and conservative snapshot-to-event contract."""
import copy
import json
from pathlib import Path

import pytest
import requests

from ingest import oh_msdgc_cso as m

FIX = Path(__file__).parent / 'fixtures' / 'oh_msdgc'
NOW = '2026-11-28T13:30:00Z'


def fixture(name):
    return json.loads((FIX / name).read_text())


def site(status='Currently Active', stamp=1795852819000):
    row = fixture('active-site.json')
    row.update({'Current State': status, 'timestamp': stamp})
    return row


def test_query_is_public_and_complete():
    q = m.query('CSOs', m.STATE_FIELDS)
    command = q['queries'][0]['Query']['Commands'][0]['SemanticQueryDataShapeCommand']
    assert command['Query']['From'][0]['Entity'] == 'CSOs'
    assert [x['Column']['Property'] for x in command['Query']['Select']] == m.STATE_FIELDS
    assert command['Binding']['DataReduction']['Primary']['Window']['Count'] == 5000
    assert q['modelId'] == 346


def test_real_compressed_rows_and_single_value():
    rows = m.decode(fixture('states.json'), m.STATE_FIELDS)
    assert rows[0]['facility_id'] == 10902003
    assert rows[1]['Active Status'] == 'Inactive'  # repeated dictionary index
    assert rows[2]['Current State'] is None       # null mask, not previous value
    assert rows[4]['Overflow Timer'] == 10.432446
    assert m.decode(fixture('refreshed.json'), ['Updated'])[0]['Updated'] == 1795854665000


def test_truncated_query_and_bad_schema_fail():
    doc = fixture('states.json')
    doc['results'][0]['result']['data']['dsr']['DS'][0]['RT'] = ['more']
    with pytest.raises(ValueError):
        m.decode(doc, m.STATE_FIELDS)
    with pytest.raises(ValueError):
        m.decode(fixture('states.json'), ['changed'])


def test_event_identity_transitions_and_no_invented_end():
    s = {}
    quiet = site('Recently Active', 1795849219000)
    m.poll(s, [quiet], NOW)
    assert not s['events']
    m.poll(s, [site()], NOW)
    key = next(iter(s['events']))
    active = site(stamp=1795856419000)
    m.poll(s, [active], '2026-11-28T14:30:00Z')
    assert list(s['events']) == [key]
    for status in ['Data Unavailable', 'Flooded', None]:
        m.poll(s, [site(status, 1795860019000)], '2026-11-28T15:30:00Z')
        assert s['events'][key].get('end') is None
    m.poll(s, [], '2026-11-28T16:30:00Z')
    ev = m.to_record(key, s['events'][key], [])
    assert ev['status'] == 'ongoing' and ev['ended_at'] is None
    stopped = site('Recently Active', 1795863619000)
    m.poll(s, [stopped], '2026-11-28T16:30:00Z')
    ev = m.to_record(key, s['events'][key], [])
    assert ev['status'] == 'ended'
    assert ev['ended_at'] == '2026-11-28T11:00:19-05:00'
    assert ev['time_precision'] == 'poll'
    assert ev['raw']['ended_at_precision'] == 'poll'
    assert ev['raw']['end_bounds'] == ['2026-11-28T09:00:19-05:00', ev['ended_at']]
    m.poll(s, [site(stamp=1795867219000)], '2026-11-28T17:30:00Z')
    assert len(s['events']) == 2


def test_recent_first_read_and_rtc_do_not_invent_events():
    s = {}
    rtc = site(); rtc['info']['asset_type'] = 'RTC'
    m.poll(s, [site('Recently Active'), rtc], NOW)
    assert not s['events']


def test_stale_stop_does_not_end_newer_active():
    s = {}; m.poll(s, [site()], NOW)
    m.poll(s, [site('Recently Active', 1795849219000)], NOW)
    assert next(iter(s['events'].values())).get('end') is None


def test_zone_precision_and_absent_volume_cause():
    assert m.source_time(1795852819000) == '2026-11-28T08:00:19-05:00'
    s = {}; m.poll(s, [site()], NOW)
    key = next(iter(s['events'])); e = m.to_record(key, s['events'][key], [])
    assert e['reported_at'] is None and e['published_at'] is None
    assert e['volume_gal'] is None and e['volume_text'] is None
    assert e['waterbody_text'] is None  # sewershed is not receiving water
    assert 'cause' not in e['raw']
    assert e['raw']['source_status'] == 'Currently Active'
    assert e['raw']['treatment_plant_permit'] == 'OH0025470'
    assert e['advice_window_hours'] == 72  # MSDGC's window after observed normal levels


def test_registry_exact_number_not_plant_outlet():
    rows = [{'npdes_permit': 'OH0105457', 'outfall': '223', 'outfall_kind': 'cso',
             'receiving_water_echo': 'Rapid Run', 'water_slug': 'rapid-run-oh',
             'lat': float(site()['info']['latitude']), 'lon': float(site()['info']['longitude']),
             'coords_from': 'permitted_feature'}]
    assert m.tie(site()['info'], rows)['outfall'] == '223'
    wrong = copy.deepcopy(rows); wrong[0]['npdes_permit'] = 'OH0025461'; wrong[0]['outfall_kind'] = 'plant'
    assert m.tie(site()['info'], wrong) is None
    wrong = copy.deepcopy(rows); wrong[0]['lon'] = -84.2
    assert m.tie(site()['info'], wrong) is None


def test_failure_keeps_records_and_state(tmp_path, monkeypatch):
    from common import write_events
    out = tmp_path / 'events.json'; state = out.with_suffix('.state.json')
    state.write_text('{"events": {}}')
    write_events(m.SOURCE_ID, [{'event_id': 'kept'}], path=out)
    def failed():
        raise requests.ConnectionError('unreachable')
    monkeypatch.setattr(m, 'fetch', failed)
    assert m.main(['--out', str(out)]) == 1
    assert json.loads(out.read_text())['records'] == [{'event_id': 'kept'}]
    assert not json.loads(out.read_text())['ok']
    assert state.read_text() == '{"events": {}}'


def test_duplicate_links_require_outfall_and_bounded_start():
    s = {}; m.poll(s, [site('Recently Active', 1795849219000)], NOW); m.poll(s, [site()], NOW)
    k = next(iter(s['events'])); e = m.to_record(k, s['events'][k], [])
    e.update(npdes_permit='OH0105457', outfall_id='223')
    other = {'event_id': 'echo-sewer-overflow:123', 'source_id': 'echo-sewer-overflow',
             'event_type': 'cso', 'npdes_permit': 'OH0105457', 'outfall_id': '223',
             'started_at': '2026-11-28T07:30:00-05:00', 'time_precision': 'minute'}
    m.link_records([e], [other])
    assert e['duplicate_of'] == other['event_id']
    assert e['raw']['_other_source_record'] == [other['event_id']]
    e['duplicate_of'] = None; e['raw'].pop('_other_source_record')
    other['time_precision'] = 'month'
    m.link_records([e], [other])
    assert e['duplicate_of'] is None and '_other_source_record' not in e['raw']


def test_eastern_summer_and_dst_ambiguity():
    from datetime import datetime
    def number(text):
        return (datetime.fromisoformat(text) - datetime(1970, 1, 1)).total_seconds() * 1000
    assert m.source_time(number('2026-07-01T08:01:23')).endswith('-04:00')
    for wall in ['2026-03-08T02:30:00', '2026-11-01T01:30:00']:
        with pytest.raises(ValueError):
            m.source_time(number(wall))


def test_malformed_row_does_not_silently_become_null():
    doc = fixture('states.json')
    doc['results'][0]['result']['data']['dsr']['DS'][0]['PH'][0]['DM0'][0]['C'] = []
    with pytest.raises(ValueError):
        m.decode(doc, m.STATE_FIELDS)


def test_same_observation_is_not_a_new_source_confirmation():
    s = {}; m.poll(s, [site()], NOW)
    before = copy.deepcopy(s)
    m.poll(s, [site()], '2026-11-28T17:30:00Z')
    assert s == before


def test_receiving_water_and_timer_are_preserved():
    s = {}; m.poll(s, [site()], NOW)
    k = next(iter(s['events']))
    reg = [{'npdes_permit': 'OH0105457', 'outfall': '223', 'outfall_kind': 'cso',
            'receiving_water_echo': 'Ohio River', 'water_slug': 'ohio-river-oh'}]
    e = m.to_record(k, s['events'][k], reg)
    assert e['waterbody_text'] == 'Ohio River'
    assert e['raw']['row']['Overflow Timer'] == 72
    assert e['raw']['source_words'] == m.WORDS['Currently Active']
    assert e['raw']['registry_record']['npdes_permit'] == 'OH0105457'
    assert e['raw']['treatment_plant_permit'] == 'OH0025470'
    assert e['ended_at'] is None


def test_missing_or_duplicate_inventory_rejected(monkeypatch):
    rows = [dict(site(), facility_id=str(i)) for i in range(205)]
    infos = [dict(r['info'], facility_id=r['facility_id']) for r in rows]
    monkeypatch.setattr(m, 'decode', lambda doc, fields: rows if fields == m.STATE_FIELDS else infos)
    assert len(m.rows_of({'states': {}, 'info': {}}, {})) == 205
    infos.pop()
    with pytest.raises(ValueError):
        m.rows_of({'states': {}, 'info': {}}, {})
    infos.append(infos[-1])
    with pytest.raises(ValueError):
        m.rows_of({'states': {}, 'info': {}}, {})


def test_atomic_failed_run_keeps_archive(tmp_path, monkeypatch):
    p = tmp_path / 'state.json'; p.write_text('{"events": {"old": {}}}')
    monkeypatch.setattr(m, 'rows_of', lambda *args: (_ for _ in ()).throw(ValueError('truncated')))
    with pytest.raises(ValueError):
        m.run({}, NOW, p, registry=[])
    assert json.loads(p.read_text()) == {'events': {'old': {}}}


def test_ambiguous_dated_match_does_not_dedupe_and_month_is_context():
    e = {'source_id': m.SOURCE_ID, 'npdes_permit': 'OH0105457', 'outfall_id': '223',
         'started_at': '2026-11-28T08:00:00-05:00',
         'raw': {'start_bounds': ['2026-11-28T07:00:00-05:00', '2026-11-28T08:00:00-05:00']}}
    other = {'event_id': 'feed:1', 'source_id': 'feed', 'npdes_permit': 'OH0105457', 'outfall_id': '223',
             'event_type': 'cso', 'started_at': '2026-11-28T07:30:00-05:00', 'time_precision': 'minute'}
    month = dict(other, event_id='oh-echo-dmr-cso:month', time_precision='month')
    m.link_records([e], [other, dict(other, event_id='feed:2'), month])
    assert not e.get('duplicate_of')
    assert e['raw']['monthly_context_records'] == [month['event_id']]
    e['raw']['start_bounds'][0] = None
    m.link_records([e], [other])
    assert not e.get('duplicate_of')


def test_fetch_uses_only_public_report_header_and_two_complete_queries(monkeypatch):
    calls = []
    class Session:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            class Response:
                def raise_for_status(self):
                    pass
                def json(self):
                    return {'public': True}
            return Response()
    monkeypatch.setattr(m.requests, 'Session', Session)
    assert m.fetch() == {'states': {'public': True}, 'info': {'public': True}}
    assert len(calls) == 2
    for url, kwargs in calls:
        assert url == m.API
        assert kwargs['headers']['X-PowerBI-ResourceKey'] == m.RESOURCE_KEY
        assert 'Authorization' not in kwargs['headers']
        assert '(+https://dirtywaterwatch.org/contact/)' in kwargs['headers']['User-Agent']
    assert calls[0][1]['json'] == m.query('CSOs', m.STATE_FIELDS)
    assert calls[1][1]['json'] == m.query('CSO_Info', m.INFO_FIELDS)
