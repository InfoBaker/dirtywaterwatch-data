"""County beach actions: real public rows, trimmed; variants exercise failure paths."""
import copy
import json
from pathlib import Path

import pytest

from ingest import ca_sd_beaches as SD

FIX = Path(__file__).parent / 'fixtures' / 'ca_county_beaches'
AT = '2026-11-28T13:00:00Z'


def sd_fixture():
    return json.loads((FIX / 'sd_notifications.json').read_text())


def test_sd_source_times_station_identity_and_reported_spill():
    d = sd_fixture()
    records = SD.build(d['rows'], AT, d['updated_at'], [])
    by_station = {r['raw']['row']['Site']['StationID']: r for r in records}
    r = by_station['FM-010']
    assert r['started_at'] == '2026-11-20T08:30:00-08:00'
    assert r['time_precision'] == 'minute'
    assert r['source_updated_at'] == '2026-11-27T17:05:59-08:00'
    assert r['reported_at'] is None and r['published_at'] is None
    assert r['ended_at'] is None
    assert r['volume_gal'] == 160000 and r['estimate_flag'] == 'estimated'
    assert r['waterbody_text'] == 'San Diego River'
    assert 'sewage release' in r['raw']['cause']
    assert r['event_type'] == 'beach_closure'
    assert by_station['IB-010']['raw']['cause'] is None
    assert by_station['IB-010']['started_at'] == '2025-10-13T10:33:00-07:00'
    again = SD.build(list(reversed(d['rows'])), '2026-11-28T14:00:00Z', d['updated_at'], records)
    assert {r['event_id'] for r in records} == {r['event_id'] for r in again}
    assert all(r['raw']['_first_seen_at'] == AT for r in again)


def test_disappearance_and_source_lift_are_distinct():
    d = sd_fixture()
    records = SD.build(d['rows'], AT, d['updated_at'], [])
    kept = SD.build([], '2026-11-29T13:00:00Z', d['updated_at'], records)
    assert all(r['ended_at'] is None for r in kept)
    assert all(r['raw']['_missing_from_source_since'] for r in kept)
    assert all(r['fetched_at'] == AT for r in kept)
    lifted = copy.deepcopy(d['rows'][0])
    lifted['Event']['LiftedDateTime'] = '2026-11-28T23:11:00Z'
    r = SD.build([lifted], AT, d['updated_at'], [])[0]
    assert r['status'] == 'advisory_lifted' and r['ended_at'] == '2026-11-28T15:11:00-08:00'


def test_sd_paging_uses_outsystems_inputs_and_rejects_repeated_pages():
    calls = []
    class Client:
        def call(self, component, action, variables, inputs):
            calls.append(inputs)
            return {'List': {'List': [{'id': i} for i in range(inputs['StartIndex'], min(inputs['StartIndex'] + 2, 5))]}, 'Count': 5}
    assert len(SD.aggregate(Client(), 'block', 'action', {}, page_size=2)) == 5
    assert calls == [{'StartIndex': 0, 'MaxRecords': 2}, {'StartIndex': 2, 'MaxRecords': 2}, {'StartIndex': 4, 'MaxRecords': 2}]
    class Repeated:
        def call(self, *args):
            return {'List': {'List': [{'id': 1}, {'id': 2}]}, 'Count': -1}
    with pytest.raises(ValueError):
        SD.aggregate(Repeated(), 'block', 'action', {}, page_size=2)


def test_down_keeps_previous_records(tmp_path, monkeypatch):
    out = tmp_path / 'events.json'
    from common import write_events
    records = SD.build(sd_fixture()['rows'], AT, sd_fixture()['updated_at'], [])
    write_events(SD.SOURCE_ID, records, path=out)
    before = json.loads(out.read_text())
    monkeypatch.setattr(SD, 'fetch', lambda *a, **kw: (_ for _ in ()).throw(ConnectionError('down')))
    assert SD.main(['--out', str(out)]) == 1
    after = json.loads(out.read_text())
    assert after['records'] == before['records'] and after['last_ok_at'] == before['last_ok_at']
    assert after['ok'] is False


def test_oc_current_day_precision_and_no_inferred_lift():
    from ingest import ca_oc_beaches as OC
    rows = OC.parse_current((FIX / 'oc_current.html').read_text())
    assert len(rows) == 1
    r = OC.current_records(rows, AT)[0]
    assert r['started_at'] == '2026-11-25T00:00:00-08:00'
    assert r['time_precision'] == 'day'
    assert r['ended_at'] is None and r['volume_gal'] is None
    assert r['source_updated_at'] is None and r['reported_at'] is None
    assert 'Aliso Beach' in r['waterbody_text']
    assert 'bacteria' in r['raw']['cause']
    assert r['source_record_id'] == OC.current_records(rows, '2026-11-29T12:00:00Z')[0]['source_record_id']
    with pytest.raises(ValueError):
        OC.parse_current('<html>Temporarily unavailable</html>')


def test_oc_chart_phases_share_spill_identity_and_revised_volume():
    from ingest import ca_oc_beaches as OC
    r = OC.chart_records((FIX / 'oc_closures_2026.txt').read_text(), OC.chart_url(2026), AT, 2026)[0]
    assert r['source_record_id'] == 'closure-26-035'
    assert r['started_at'] == '2026-07-02T00:00:00-07:00'
    assert r['ended_at'] == '2026-07-04T00:00:00-07:00'
    assert r['volume_gal'] == 500 and r['estimate_flag'] == 'estimated'
    assert r['raw']['volume_to_water_gal'] == 500
    assert r['raw']['volume_recovered_gal'] == 0
    assert len(r['raw']['phases']) == 2
    assert '2,000' in r['volume_text']
    assert 'Mechanical Failure' in r['raw']['cause']
    assert r['event_type'] == 'beach_closure' and r['status'] == 'advisory_lifted'
    assert r['reported_at'] is None and r['published_at'] is None
    two = OC.chart_records((FIX / 'oc_closures_2025.txt').read_text(), OC.chart_url(2025), AT, 2025)
    assert len(two) == 4
    assert two[0]['volume_gal'] == 589500 and two[0]['raw']['volume_to_water_gal'] == 464700
    assert two[0]['ended_at'].startswith('2025-01-17')
    assert two[2]['ended_at'].startswith('2025-01-19')
    assert {r['raw']['spill_number'] for r in two} == {'25-003', '25-020'}
    assert [r['volume_gal'] for r in two] == [589500, None, None, 4000]
    assert len(two[0]['raw']['phases']) == 3


def test_oc_unknown_pdf_layout_is_an_error_not_an_empty_archive():
    from ingest import ca_oc_beaches as OC
    with pytest.raises(ValueError):
        OC.chart_records('OCEAN AND BAY WATER CLOSURES 2026 unreadable table', OC.chart_url(2026), AT, 2026)


def test_beachwatch_links_use_station_dates_types_and_preserve_conflicts():
    from ingest import ca_county_beach_link as L
    county = SD.build(sd_fixture()['rows'], AT, sd_fixture()['updated_at'], [])
    r = next(r for r in county if r['raw']['row']['Site']['StationID'] == 'IB-010')
    state = {**copy.deepcopy(r), 'source_id': L.BEACHWATCH, 'event_id': L.BEACHWATCH + ':123',
             'source_record_id': '123', 'started_at': r['started_at'][:10] + 'T00:00:00-07:00',
             'raw': {'advisory': {'County': 'San Diego', 'Station_Name': 'IB-010'}}}
    counts = L.link([state], county)
    assert counts['duplicates'] == 1 and state['duplicate_of'] == r['event_id']
    assert state['raw']['_duplicate_basis']
    state['ended_at'] = '2025-11-01T00:00:00-07:00'
    counts = L.link([state], county)
    assert counts['duplicates'] == 0 and state['duplicate_of'] is None
    assert state['raw']['related_record']['event_id'] == r['event_id']
    state['raw']['advisory']['Station_Name'] = 'IB-020'
    assert L.link([state], county)['duplicates'] == 0
    assert 'related_record' not in state['raw']


def test_reason_rules_and_detail_mapping(tmp_path):
    """Integration runs with the proposed shared patch in a temporary copy."""
    from build import beach_reason, status
    from export import detail
    rules = status.load_rules()
    if SD.SOURCE_ID not in rules['beach_reason']['sources']:
        pytest.skip('shared patch is intentionally unapplied in the working tree')
    rs = SD.build(sd_fixture()['rows'], AT, sd_fixture()['updated_at'], [])
    for r in rs:
        judged = beach_reason.judge(r, rules)
        assert judged['stated'] is (r['raw']['row']['Site']['StationID'] == 'FM-010')
        from datetime import datetime
        intervals = status.event_intervals(r, 'CA', datetime.fromisoformat(AT.replace('Z', '+00:00')), rules=rules)
        assert bool(intervals) is judged['stated']
    detail.enrich(rs)
    assert next(r for r in rs if r['volume_gal'])['detail']['cause']


def test_oc_open_chart_action_never_invents_end_and_unknown_agency_keeps_row():
    from ingest import ca_oc_beaches as OC
    original = (FIX / 'oc_closures_2026.txt').read_text()
    open_row = original[:original.index('1b 26-035')].replace('7/4/2026\n(reduced on)', '')
    record = OC.chart_records(open_row, OC.chart_url(2026), AT, 2026)[0]
    assert record['ended_at'] is None and record['status'] == 'advisory_active'
    unfamiliar = original.replace('PPO – Mechanical', 'County sanitation service – Mechanical')
    record = OC.chart_records(unfamiliar, OC.chart_url(2026), AT, 2026)[0]
    assert record['volume_gal'] == 500
    assert record['raw']['phases'][0]['source_text']
    assert record['waterbody_text'] is None


def test_oc_pdf_rows_cannot_silently_drop_an_unparsed_phase():
    from ingest import ca_oc_beaches as OC
    content = (FIX / 'oc_closures_2026.txt').read_text().replace('7/4/2026 7/5/2026', 'not-a-date 7/5/2026')
    with pytest.raises(ValueError):
        OC.chart_records(content, OC.chart_url(2026), AT, 2026)


def test_sd_fetch_checks_summary_counts_and_asks_all_action_types(monkeypatch):
    d = sd_fixture()
    calls = []
    class FakeClient:
        def __init__(self, session):
            pass
        def call(self, component, action, variables, inputs):
            calls.append((component, action, variables, inputs))
            if action == 'DataActionGetLastDateTime':
                return {'LastUpdate': d['updated_at']}
            if component == SD.HOME:
                return {'List': {'List': [{'Count': '0' if action.endswith('GetWarnings') else '2'}]}, 'Count': -1}
            kind = variables['EventTypeId']
            return {'List': {'List': [r for r in d['rows'] if r['EventType']['Id'] == kind]}, 'Count': -1}
    monkeypatch.setattr(SD, 'Client', FakeClient)
    assert len(SD.fetch()['rows']) == 4
    assert [c[2]['EventTypeId'] for c in calls if c[0] == SD.NOTICES] == [1, 2, 3]
    d['rows'].pop()
    with pytest.raises(ValueError):
        SD.fetch()


def test_oc_chart_failure_preserves_history_and_marks_partial_health(tmp_path, monkeypatch):
    from ingest import ca_oc_beaches as OC
    from common import write_events
    out = tmp_path / 'events.json'
    archive = OC.chart_records((FIX / 'oc_closures_2025.txt').read_text(), OC.chart_url(2025), AT, 2025)
    write_events(OC.SOURCE_ID, archive, path=out)
    before = json.loads(out.read_text())
    class Answer:
        text = (FIX / 'oc_current.html').read_text()
    def response(session, url):
        if url == OC.PAGE:
            return Answer()
        raise ConnectionError('unavailable')
    monkeypatch.setattr(OC, 'get', response)
    assert OC.main(['--out', str(out), '--state', str(tmp_path / 'state.json')]) == 1
    after = json.loads(out.read_text())
    assert after['ok'] is False and after['last_ok_at'] == before['last_ok_at']
    assert len(after['records']) == len(archive) + 1
    for r in archive:
        assert next(x for x in after['records'] if x['event_id'] == r['event_id']) == r


def test_beacon_existing_linker_accepts_county_action():
    from ingest import fed_beacon_beach_actions as B
    county = SD.build(sd_fixture()['rows'], AT, sd_fixture()['updated_at'], [])
    r = next(r for r in county if r['raw']['row']['Site']['StationID'] == 'IB-010')
    beacon = {**copy.deepcopy(r), 'source_id': B.SOURCE_ID, 'event_id': B.SOURCE_ID + ':test',
              'raw': {'jurisdiction': 'CA', 'beach_id': 'test', 'beach_name': r['outfall_name']}}
    registry = {'test': {'start_lat': r['lat'], 'start_lon': r['lon']}}
    assert B.link_copies([beacon], [r], registry)['by_point'] == 1
    assert beacon['duplicate_of'] == r['event_id']


def test_link_step_preserves_fetch_health_and_does_not_count_sewage_as_beach(tmp_path, monkeypatch):
    from ingest import ca_county_beach_link as L
    county = SD.build(sd_fixture()['rows'], AT, sd_fixture()['updated_at'], [])
    r = next(r for r in county if r['raw']['row']['Site']['StationID'] == 'IB-010')
    state = {**copy.deepcopy(r), 'source_id': L.BEACHWATCH, 'event_id': L.BEACHWATCH + ':123',
             'raw': {'advisory': {'County': 'San Diego', 'Station_Name': 'IB-010'}}}
    header = {'source_id': L.BEACHWATCH, 'ok': False, 'error': 'timeout', 'last_ok_at': AT,
              'fetched_at': '2026-11-29T00:00:00Z', 'records': [state], 'count': 1}
    path = tmp_path / f'{L.BEACHWATCH}.json'
    path.write_text(json.dumps(header))
    (tmp_path / f'{SD.SOURCE_ID}.json').write_text(json.dumps({'records': county}))
    monkeypatch.setattr(L, 'EVENTS_DIR', tmp_path)
    assert L.main() == 0
    after = json.loads(path.read_text())
    assert {k: after[k] for k in ('ok','error','last_ok_at','fetched_at','count')} == {k: header[k] for k in ('ok','error','last_ok_at','fetched_at','count')}
    assert after['records'][0]['duplicate_of'] == r['event_id']
    state['event_type'] = 'sso'
    assert L.link([state], county)['duplicates'] == 0


def test_county_links_reach_export_and_are_removed_when_match_disappears():
    from ingest import ca_county_beach_link as L
    from export.detail import links_of
    county = SD.build(sd_fixture()['rows'], AT, sd_fixture()['updated_at'], [])
    r = next(r for r in county if r['raw']['row']['Site']['StationID'] == 'IB-010')
    state = {**copy.deepcopy(r), 'source_id': L.BEACHWATCH, 'event_id': L.BEACHWATCH + ':123',
             'raw': {'advisory': {'County': 'San Diego', 'Station_Name': 'IB-010'}}}
    L.link([state], county)
    links = links_of([state, r])
    assert links[r['event_id']]['linked_records'][0]['event_id'] == state['event_id']
    L.link([state], [])
    assert '_other_source_record' not in state['raw']
    assert state['duplicate_of'] is None
