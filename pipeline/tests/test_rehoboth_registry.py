"""Real DNREC stations placed on the proposed NHD receiving-water record."""
from datetime import date

import pytest
from shapely.geometry import shape

from build import status as S
from ingest import de_dnrec_recwater as D
from test_receiving_water_results import fixture, AT


@pytest.fixture(scope="module")
def resolver():
    return S.Resolver({k: w for k, w in S.load_waters().items()
                       if S.water_state(k, w) == 'DE'}, [])


@pytest.mark.parametrize('unit_id', [363680, 363701])
def test_rehoboth_stations_resolve_to_rehoboth_bay(resolver, unit_id):
    stations = D.safe_stations([f['attributes'] for f in fixture('de-stations.json')['features']])
    station = next(s for s in stations if s['UnitID'] == unit_id)
    records, state = D.poll_records([dict(station, CurrentAdvisory=0)], [], {}, AT, date(2026, 11, 22))
    retained, _ = D.poll_records([], [], state, '2026-11-23T23:00:00Z', date(2026, 11, 23))
    for record in records + retained:
        placed = resolver.resolve(record)
        assert placed['water_slugs'] == ['rehoboth-bay-de']
        assert 'indian-river-bay-de' not in placed['water_slugs']
        assert placed['water_match'] == 'name'


def test_rehoboth_has_its_own_cited_nhd_outline(resolver):
    water = resolver.waters['rehoboth-bay-de']
    assert water['source'] == 'nhd'
    assert water['gnis_id'] == '214534'
    assert water['kind'] == 'bay'
    assert water['nhd_fcodes'] == [31200]
    assert '167496750' in water['note']
    assert 'https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/9' in water['note']
    outline = shape(water['geometry'])
    assert outline.geom_type in ('Polygon', 'MultiPolygon')
    assert outline.is_valid and not outline.is_empty
    assert not S.colours_whole_water(water)
    assert 'Rehoboth Bay' not in resolver.waters['indian-river-bay-de'].get('aliases', [])
