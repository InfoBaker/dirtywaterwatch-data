"""Full City table: real, trimmed November 22 rows; no network or private addresses."""
import copy
import json
from pathlib import Path

import pytest

from ingest import md_baltimore_sso as B
from ingest import md_mde_overflows as M
from export.detail import links_of

FIX = json.loads((Path(__file__).parent / 'fixtures/generic/md_baltimore_full_sso.json').read_text())
ROWS = [f['attributes'] for f in FIX['features']]
NOW = '2026-11-22T15:00:00Z'


def test_full_detail_uses_domain_words_and_keeps_source_duration():
    row = next(r for r in ROWS if r['OBJECTID'] == 25987)
    r = B.to_record(row, NOW, None)
    assert r['raw']['_cause_flags']['CAUSE_RAIN'] == 'Yes'
    assert 'CAUSE_RAIN: "Yes"' in r['raw']['_cause_text']
    assert r['raw']['_duration_text'] == '395 (source duration; unit not stated)'
    assert r['raw']['_water_reach'] == 'Yes'
    assert r['started_at'] == '2026-10-11T11:15:00-04:00'
    assert r['ended_at'] == '2026-10-11T17:50:00-04:00'
    assert 'SSOID' in r['source_url'] and 'outFields=*' not in r['source_url']
    assert 'CAUSE_RAIN' in r['raw']['_field_sources']['cause']['fields']


def test_reissued_legacy_objectids_keep_their_event_ids_and_history():
    fixture = json.loads((Path(__file__).parent / 'fixtures/generic/md_baltimore_sso_layer.json').read_text())
    old = [f['attributes'] for f in fixture['features'] if f['attributes']['OBJECTID'] in {25942,25952,25964,25969,25970}]
    prev, _ = B.build(old, '2026-11-04T12:00:00Z', [])
    new = [r for r in ROWS if r['OBJECTID'] in {25987,26014,26012,26017,26022}]
    result, stats = B.build(new, NOW, prev)
    assert {r['event_id'] for r in result} == {r['event_id'] for r in prev}
    assert stats['kept_from_earlier_runs'] == 0
    assert all(r['raw']['_first_seen_at'] == '2026-11-04T12:00:00Z' for r in result)
    assert all(r['raw']['_identity_basis'] for r in result)
    again, _ = B.build(new, NOW, result)
    assert again == result


def test_duplicate_and_null_ssoids_do_not_collapse_rows():
    rows = [r for r in ROWS if r['SSOID'] == 9021]
    records, _ = B.build(rows, NOW, [])
    assert len(records) == 2 and len({r['event_id'] for r in records}) == 2


def test_no_end_is_derived_and_water_conflict_is_preserved():
    row = {**ROWS[0], 'END_DATETIME': None, 'DURATION': '30', 'REC_WATERS': 'JF', 'OVFL_REACH_WW': 0}
    r = B.to_record(row, NOW, None)
    assert r['ended_at'] is None and 'estimated_end' not in r['raw']
    assert r['waterbody_text'] == 'Jones Falls' and r['raw']['_water_reach'] == 'No'
    assert r['raw']['_water_reach_conflict']
    assert B.to_record({**row, 'CAUSE_RAIN': 9}, NOW, None)['raw']['_cause_flags']['CAUSE_RAIN'] == 'Unrecognized code: 9'


def test_full_precision_and_sentinel_dates():
    row = next(r for r in ROWS if r['OBJECTID'] == 26012)
    r = B.to_record(row, NOW, None)
    assert r['time_precision'] == 'second'
    assert r['started_at'].endswith('11:53:09-05:00')
    r = B.to_record({**row, 'SSO_DATE': -2209161600000}, NOW, None)
    assert r['started_at'] is None and r['parse_error']


class Response:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data


class Layer:
    def __init__(self, rows, repeat=False): self.rows, self.repeat, self.calls = rows, repeat, []
    def get(self, url, params, timeout):
        self.calls.append(params)
        if not url.endswith('/query'):
            return Response({**FIX, 'maxRecordCount': 2})
        if params.get('returnCountOnly'): return Response({'count': len(self.rows)})
        offset = 0 if self.repeat else params['resultOffset']
        return Response({'features': [{'attributes': r} for r in self.rows[offset:offset+2]]})


def test_paging_finishes_even_without_transfer_limit_flag_and_rejects_repeats():
    layer = Layer(ROWS[:5])
    rows, raw, _ = B.query_layer(layer)
    assert len(rows) == 5
    assert all('*' not in p.get('outFields', '') for p in layer.calls)
    with pytest.raises(RuntimeError, match='duplicate|repeated'):
        B.query_layer(Layer(ROWS[:5], repeat=True))


def test_existing_mde_match_adds_supporting_record_link():
    city = B.to_record(next(r for r in ROWS if r['OBJECTID'] == 25987), NOW, None)
    mde = {'event_id': 'md-mde-overflows:test', 'source_id': 'md-mde-overflows', 'started_at': city['started_at'],
           'discharger_id': city['discharger_id'], 'lat': city['lat'], 'lon': city['lon'], 'raw': {}, 'volume_gal': 10}
    assert M.match_baltimore([mde], {mde['event_id']: {'overflow_address': ''}}, [city]) == 1
    assert mde['raw']['_other_source_record'] == city['event_id']
    assert links_of([mde, city])[city['event_id']]['linked_records'][0]['event_id'] == mde['event_id']


def test_full_metadata_must_have_business_key():
    layer = Layer(ROWS[:1])
    original = layer.get
    def get(url, params, timeout):
        response = original(url, params, timeout)
        if not url.endswith('/query'):
            response.data = {**response.data, 'fields': [f for f in FIX['fields'] if f['name'] != 'SSOID']}
        return response
    layer.get = get
    with pytest.raises(RuntimeError, match='SSOID'):
        B.query_layer(layer)


def test_frozen_mde_history_links_to_full_city_table():
    from ingest.generic import transforms as T
    from ingest.generic.fieldmap import Ctx
    city = B.to_record(next(r for r in ROWS if r['OBJECTID'] == 25987), NOW, None)
    record = {'event_id': 'md-mde-sewer-overflows-2005-2023:test', 'source_id': 'md-mde-sewer-overflows-2005-2023',
              'event_type': 'sso', 'started_at': city['started_at'], 'time_precision': 'minute',
              'discharger_id': city['discharger_id'], 'lat': city['lat'], 'lon': city['lon'],
              'volume_gal': 10, 'raw': {'row': {'npdes': 'MDC021555', 'date_discovered': '10/11/2026',
                                            'time_discovered': '11:15:00'}}}
    # Synthetic dates exercise the history hook with a trimmed real City point.
    ctx = Ctx(source_id=record['source_id'], fetched_at=NOW, block={}, tz=B.TZ,
              extra={'md_mde_records': [], 'md_baltimore_records': [city]})
    T.md_mde_history_duplicates([record], ctx)
    assert record['duplicate_of'] == city['event_id']
    assert record['raw']['_other_source_record'] == city['event_id']
    assert '3rgd-zjxx' in record['source_url']


def test_unchanged_frozen_history_is_relinked_without_changing_fetch_clock(tmp_path):
    city = B.to_record(next(r for r in ROWS if r['OBJECTID'] == 25987), NOW, None)
    sid = 'md-mde-sewer-overflows-2005-2023'
    r = {'event_id': sid + ':test', 'source_id': sid, 'started_at': city['started_at'],
         'discharger_id': city['discharger_id'], 'lat': city['lat'], 'lon': city['lon'], 'volume_gal': 10,
         'raw': {'row': {}}, 'fetched_at': '2026-11-01T00:00:00Z'}
    doc = {'records': [r], 'fetched_at': r['fetched_at'], 'ok': True, 'meta': {'kept': True}}
    path = tmp_path / (sid + '.json')
    path.write_text(json.dumps(doc))
    M.relink_baltimore_files([city], tmp_path)
    out = json.loads(path.read_text())
    assert out['records'][0]['duplicate_of'] == city['event_id']
    assert out['fetched_at'] == out['records'][0]['fetched_at'] == doc['fetched_at']
    assert out['meta'] == doc['meta']


def test_already_retained_reissued_legacy_copy_is_not_counted_twice():
    fixture = json.loads((Path(__file__).parent / 'fixtures/generic/md_baltimore_sso_layer.json').read_text())
    old = next(f['attributes'] for f in fixture['features'] if f['attributes']['OBJECTID'] == 25942)
    new = next(r for r in ROWS if r['OBJECTID'] == 25987)
    # The old reader retained its old ID as well as the reissued ID on a later poll.
    prev, _ = B.build([old, {k: v for k, v in new.items() if k in B.LEGACY_SAFE_FIELDS}], NOW, [])
    result, _ = B.build([new], NOW, prev)
    assert len(result) == 2
    assert sum(not r.get('duplicate_of') for r in result) == 1
    copied = next(r for r in result if r['source_record_id'] == '25942')
    assert copied['duplicate_of'] == 'md-baltimore-sso:25987'


def test_midnight_fallback_keeps_date_precision_and_makes_no_start_equality_claim():
    row = {**ROWS[0], 'START_DATETIME': None, 'SSO_DATE': 1791676800000}
    r = B.to_record(row, NOW, None)
    assert r['time_precision'] == 'day'
    assert r['raw']['_started_at_precision'] == 'day'
    assert 'equal' not in r['raw']['_start_basis']


def test_changed_cause_domain_fails_instead_of_reusing_a_label():
    layer = Layer(ROWS[:1])
    original = layer.get
    def get(url, params, timeout):
        response = original(url, params, timeout)
        if not url.endswith('/query'):
            response.data = copy.deepcopy(response.data)
            field = next(f for f in response.data['fields'] if f['name'] == 'CAUSE_RAIN')
            field['domain']['codedValues'][0]['name'] = 'Changed label'
        return response
    layer.get = get
    with pytest.raises(RuntimeError, match='changed domain'):
        B.query_layer(layer)


def test_city_can_fill_a_previously_missing_business_key_without_changing_identity():
    row = ROWS[0]
    prev, _ = B.build([{**row, 'SSOID': None}], NOW, [])
    result, _ = B.build([{**row, 'SSOID': 123456}], NOW, prev)
    assert result[0]['event_id'] == prev[0]['event_id']
    assert result[0]['raw']['SSOID'] == 123456
