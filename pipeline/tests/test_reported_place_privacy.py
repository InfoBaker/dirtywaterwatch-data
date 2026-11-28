"""Our geocodes are approximate listings; a plant never fills a missing spill point."""
import json
from types import SimpleNamespace

from build import provisional_outfalls as P, report_geolocate as RG
from common import load_outfall_registry
from export import build as E, outfalls as O


def place(**kw):
    return dict(id='rep-test', outfall='rep-test', source_id='reported-outfalls',
                npdes_permit='CT0100013', discharger_id='ct-test', state='CT',
                lat=41.312345, lon=-73.123456, coord_source='geocode',
                record_status='provisional', outfall_kind='reported', reached_water='yes',
                report_count=1, sources={'test': 1}, event_ids=['test:1'],
                reports_water_slugs=['test-river'], water_slugs=['test-river'],
                geolocation={'kind': 'address', 'step': 'a', 'confidence': 'medium',
                             'precision_m': 50, 'method': 'US Census geocoder, address-range match'}, **kw)


def test_address_geocode_is_rounded_but_never_a_parcel_dot():
    row = P.public_row(place())
    assert (row['lat'], row['lon']) == (41.312, -73.123)
    assert row['on_map'] is False
    assert row['place_method'] == 'address'
    assert row['place_precision_m'] >= 100
    assert row['place_basis'].startswith('Our approximate location')
    assert 'Census' in row['place_basis']
    assert O.outfall_rows([row], {'CT'}) == []
    by_water, by_permit, _ = E.outfall_lists([row])
    listing = by_permit['CT0100013'][0]
    assert listing['lat'] is None and listing['lon'] is None
    assert listing['place_basis'] == row['place_basis']
    assert by_water['test-river'] == [listing]


def test_operator_point_is_unchanged_even_when_agency_geocoded_it():
    for source in ('source', 'geocode'):
        p = place()
        p.pop('geolocation')
        p['coord_source'] = source
        row = P.public_row(p)
        assert (row['lat'], row['lon']) == (p['lat'], p['lon'])
        assert row['on_map'] is True
        assert 'place_basis' not in row


def test_cached_plant_stand_in_loses_point_and_only_keeps_report_water(tmp_path):
    p = place(stand_in=True)
    p['geolocation']['kind'] = 'frs_stand_in'
    p['water_slugs'] = ['plant-water']
    p['water_slug'] = 'plant-water'
    (tmp_path / 'build').mkdir()
    (tmp_path / 'build/outfalls-reported.json').write_text(json.dumps({'outfalls': [p]}))
    rows = load_outfall_registry(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row['lat'] is None and row['lon'] is None and row['on_map'] is False
    assert row['water_slugs'] == ['test-river'] and row['water_slug'] == 'test-river'
    assert 'plant' in row['place_basis'] and 'Our' in row['place_basis']
    assert O.outfall_rows(rows, {'CT'}) == []
    assert set(E.outfall_lists(rows)[0]) == {'test-river'}


def test_no_location_never_requests_a_plant_point(monkeypatch):
    monkeypatch.setattr(P, 'registry_rows', lambda: [])
    monkeypatch.setattr(P, 'state_outlines', lambda: {})
    class Geo:
        def __init__(self, *args, **kwargs): pass
        def census_batch(self, *args): pass
        def echo_facility(self, *args):
            raise AssertionError('A missing spill location must not request a plant point')
        def save(self): pass
    monkeypatch.setattr(RG, 'Geo', Geo)
    ev = {'event_id': 'test:1', '_op': 'ct-test', '_state': 'CT', 'event_type': 'sso',
          'npdes_permit': 'CT0100013', 'raw': {}, 'waterbody_text': None}
    rows, stats = RG.geolocate([ev], SimpleNamespace(offline=True, geo_budget_s=1), by_id={})
    assert rows == [] and stats['reports_placed'] == 0
    assert stats['by_outcome']['no usable location; listed without a point'] == 1


def test_rounded_place_keeps_its_id_on_the_next_refresh():
    p = place()
    p.update(id='fresh-id', lat=41.31249, lon=-73.12349)
    old = P.public_row(p)
    old['id'] = old['outfall'] = 'rep-stable'
    P.carry_over([p], {'ct-test': [old]}, '2026-11-24T00:00:00Z')
    assert p['id'] == 'rep-stable'


def test_no_point_with_a_named_water_stays_water_only(monkeypatch):
    monkeypatch.setattr(P, 'registry_rows', lambda: [])
    class Geo:
        def __init__(self, *args, **kwargs): pass
        def census_batch(self, *args): pass
        def echo_facility(self, *args): raise AssertionError('No plant substitution')
        def save(self): pass
    monkeypatch.setattr(RG, 'Geo', Geo)
    ev = {'event_id': 'test:water', '_op': 'ct-test', '_state': 'CT', 'event_type': 'sso',
          'npdes_permit': 'CT0100013', 'raw': {}, 'waterbody_text': 'Test River',
          'water_slugs': ['test-river']}
    rows, stats = RG.geolocate([ev], SimpleNamespace(offline=True, geo_budget_s=1), by_id={})
    assert not rows and ev['water_slugs'] == ['test-river']
    assert stats['water_only_operators'] == [{'operator': 'ct-test', 'state': 'CT', 'reports': 1}]


def test_cached_trace_alone_is_not_a_named_water_listing():
    p = place()
    p['reports_water_slugs'] = []
    p['water_slug'] = 'trace-only-water'
    row = P.public_row(p)
    assert row['water_slugs'] == [] and row['water_slug'] is None
    assert row['place_tier'] == 4 and row['on_map'] is False


def test_our_basis_does_not_call_an_existing_link_a_source_name():
    p = place()
    p['reports_water_text'] = []
    row = P.public_row(p)
    assert 'named in the reports' not in row['place_basis']


def test_build_summary_counts_only_drawable_markers():
    from collections import Counter
    p = place(confidence='medium')
    summary = P.summarize([p], Counter(), [], {}, {}, [])
    assert summary['places'] == 1 and summary['on_map'] == 0
