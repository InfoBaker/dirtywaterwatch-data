"""Regressions on trimmed agency rows read 2026-11-22; see fixtures/receiving_water_results."""
import json
from datetime import date
from pathlib import Path

from ingest import de_dnrec_recwater as D, fl_doh_beaches as F, id_deq_cyanohab as I, mt_deq_hab_map as M

FIX = Path(__file__).parent / 'fixtures'
AT = '2026-11-22T23:00:00Z'


def fixture(name):
    return json.loads((FIX / 'receiving_water_results' / name).read_text())


def test_delaware_description_survives_and_names_the_source_water():
    stations = D.safe_stations([f['attributes'] for f in fixture('de-stations.json')['features']])
    st = next(s for s in stations if s['UnitID'] == 363680)
    assert st['UnitDesc'] == 'This is an Unguarded area along Rehoboth Bay.'
    history = json.loads((FIX / 'de/recwater.json').read_text())['advisories']
    lewes = next(s for s in stations if s['UnitID'] == 25025)
    row = next(r for r in history if r['unitname'] == 'Lewes Beach (Savannah Beach)')
    rec = D.history_records([row], D.station_index(stations), date(2026, 11, 22), AT)[0][0]
    assert rec['waterbody_text'] == 'Delaware Bay'
    assert rec['raw']['unit_description'] == lewes['UnitDesc']
    assert rec['raw']['water_basis'] == "DNREC's station description (UnitDesc)"
    recs, state = D.poll_records([dict(st, CurrentAdvisory=0)], [], {}, AT, date(2026, 11, 22))
    assert recs[0]['waterbody_text'] == 'Rehoboth Bay'
    assert recs[0]['raw']['unit_description'] == st['UnitDesc']
    again, _ = D.poll_records([], [], state, '2026-11-23T23:00:00Z', date(2026, 11, 23))
    assert again[0]['waterbody_text'] == 'Rehoboth Bay' and again[0]['ended_at'] is None
    assert again[0]['raw']['unit_description_observed_at'] == AT


def test_florida_street_location_uses_only_a_county_qualified_registry_alias(monkeypatch):
    from test_fl_doh_beaches import POINT, PAGE
    waters = {'gulf-of-america-fl': {'name': 'Gulf Of America', 'state': 'FL',
                                   'aliases': ['8TH STREET, Bay County']}}
    monkeypatch.setattr(F, '_registry_waters', lambda: waters, raising=False)
    rec = F.build([POINT], {F.point_key(POINT): PAGE}, [], AT)[0][0]
    assert rec['waterbody_text'] == 'Gulf Of America'
    assert rec['outfall_name'] == rec['raw']['location'] == '8TH STREET'
    assert rec['raw']['water_basis'] == 'Our water registry matches the sampling location and county.'
    assert F.receiving_water(dict(POINT, County='Brevard')) is None
    monkeypatch.setattr(F, '_registry_waters', lambda: {})
    assert F.receiving_water(POINT) is None


def test_idaho_toxin_and_release_are_retained_separately_from_frozen_point():
    lay = I.parse_layer(fixture('id-layer.json'))
    rows = I.parse_table((FIX / 'id/cyanohab-table.html').read_text())
    state = I.update({}, rows, AT, lay)
    rec = next(r for r in I.records(state) if r['raw'].get('waterbody_as_listed') == 'Hordemann Pond')
    assert rec['raw']['dhw_toxin'] == 'Microcystins'
    assert rec['raw']['dhw_release_url'] == I.URL
    assert rec['raw']['dhw_detail_observed_at'] == AT
    assert rec['raw']['dhw_objectid'] == 115
    changed = fixture('id-layer.json')
    next(f['attributes'] for f in changed['features'] if f['attributes']['objectid'] == 115)['Toxin'] = None
    again = I.update(state, rows, '2026-11-23T23:00:00Z', I.parse_layer(changed))
    other = next(r for r in I.records(again) if r['event_id'] == rec['event_id'])
    assert other['raw'].get('dhw_toxin') is None
    assert (other['started_at'], other['ended_at'], other['status']) == (rec['started_at'], rec['ended_at'], rec['status'])


def test_montana_density_is_a_typed_source_result_on_every_save_path():
    doc = fixture('mt-density.json')
    records, _ = M.build(doc, AT)
    r = next(r for r in records if r['source_record_id'] == '867f568f-1c6d-487a-bfb1-eaeba070aed6')
    result = r['raw']['sample_results'][0]
    assert result['analyte'] == 'Cyanobacteria'
    assert result['text'] == 'Present: Dolichospermum'
    assert result['value'] is None and result['units'] is None
    assert result['sample_date'] == '2026-06-23'
    assert result['source_field'] == 'cyano_density' and result['source_url'] == M.LAYER
    assert M.sanitized(r)['raw']['sample_results'] == [result]
    rebuilt = M.build(M.safe_rows(doc), AT)[0]
    assert {r['event_id']: r['raw']['sample_results'] for r in rebuilt} == {
        r['event_id']: r['raw']['sample_results'] for r in records}
    ambiguous = next(r for r in records if r['source_record_id'] == '021d3031-5841-4d88-a0fc-b3c999df4539')
    assert ambiguous['raw']['sample_results'][0]['sample_date'] is None
    assert ambiguous['raw']['sample_results'][0]['sample_date_text'] == '7/8'


def test_idaho_failed_map_read_preserves_detail_time_and_closed_episode():
    rows = I.parse_table((FIX / 'id/cyanohab-table.html').read_text())
    state = I.update({}, rows, AT, I.parse_layer(fixture('id-layer.json')))
    first = next(r for r in I.records(state) if r['raw'].get('waterbody_as_listed') == 'Hordemann Pond')
    state = I.update(state, rows, '2026-11-23T23:00:00Z', None)
    r = next(r for r in I.records(state) if r['event_id'] == first['event_id'])
    assert r['raw']['dhw_detail_observed_at'] == AT
    assert r['raw']['dhw_toxin'] == first['raw']['dhw_toxin']
    closed = I.update(state, [r for r in rows if r['water'] != 'Hordemann Pond'], '2026-11-24T23:00:00Z', {})
    later = fixture('id-layer.json')
    next(f['attributes'] for f in later['features'] if f['attributes']['objectid'] == 115)['Toxin'] = 'Anatoxin a'
    state = I.update(closed, rows, '2026-11-25T23:00:00Z', I.parse_layer(later))
    old = next(r for r in I.records(state) if r['event_id'] == first['event_id'])
    assert old['raw']['dhw_toxin'] == 'Microcystins'
    assert old['ended_at'] == '2026-11-24T23:00:00Z'


def test_no_invented_water_or_density_and_no_unsafe_release():
    assert D.description_water('This is an Unguarded beach along a Pond.') is None
    assert D.description_water('') is None
    assert I.release_url('javascript:alert(1)') is None
    assert I.release_url('https://example.test/?token=withheld') is None
    assert I.release_url('https://example.test/#private') is None
    for text in ['NA', 'N/A', None]:
        assert M.density_results({'cyano_density': text}) == []
    result = M.density_results({'cyano_density': 'Present 07/08 until absent 08/05',
                                'sample_date': '7/8/2026; 8/5/2026'})[0]
    assert result['value'] is None and result['units'] is None and result['sample_date'] is None
    assert result['text'] == 'Present 07/08 until absent 08/05'
