"""Review regressions: saved Orange 26-035 phases and synthetic transition variants."""
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

from build import status as S
from common import write_events
from export.detail import links_of
from ingest import ca_county_beach_link as L
from ingest import ca_oc_beaches as OC
from ingest import ca_sd_beaches as SD

FIX = Path(__file__).parent / 'fixtures' / 'ca_county_beaches'
AT = '2026-07-06T12:00:00Z'


def dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def chart():
    return OC.chart_records((FIX / 'oc_closures_2026.txt').read_text(), OC.chart_url(2026), AT, 2026)


def status_build(tmp_path, monkeypatch, records, now):
    """The real status builder, isolated from production files and water placement."""
    evdir = tmp_path / 'events'
    evdir.mkdir(exist_ok=True)
    for sid in {r['source_id'] for r in records}:
        write_events(sid, [r for r in records if r['source_id'] == sid], path=evdir / f'{sid}.json')
    monkeypatch.setattr(S, 'OBL_WATER_DIR', tmp_path / 'no-outlines')
    return S.build(now=dt(now), write=False, events_dir=evdir, waters={}, outfalls=[], registry={}, reaches={},
                   flows=({}, {}), discharger_towns={}, discharger_waters={}, discharger_aliases_map={},
                   rain={}, rules=copy.deepcopy(S.load_rules()), placement_cache=False)


def test_oc_area_phases_keep_their_own_status_windows_and_original_id():
    records = chart()
    broad = next(r for r in records if '0.25' in r['outfall_name'])
    assert broad['event_id'] == 'ca-ocbeachinfo:closure-26-035'
    assert broad['ended_at'] == '2026-07-04T00:00:00-07:00'
    narrow = next(r for r in records if '370 feet' in r['outfall_name'])
    assert narrow['started_at'] == broad['ended_at']
    assert narrow['ended_at'] == '2026-07-05T00:00:00-07:00'
    assert {r['raw']['spill_number'] for r in records} == {'26-035'}
    assert all(r['reported_at'] is None and r['published_at'] is None for r in records)
    # Existing status rules include the entire local day for source dates of day precision.
    for r, end in [(broad, '2026-07-05T07:00:00Z'), (narrow, '2026-07-06T07:00:00Z')]:
        ivs = S.event_intervals(r, 'CA', dt(AT))
        assert len(ivs) == 1 and ivs[0]['end'] == dt(end)
    at = dt('2026-07-05T12:00:00Z')
    assert S.status_at(S.event_intervals(broad, 'CA', at), at)[0] == 'grey'
    assert S.status_at(S.event_intervals(narrow, 'CA', at), at)[0] == 'red'
    assert [r['event_id'] for r in chart()] == [r['event_id'] for r in records]


def test_sd_fallback_retains_later_lift_and_stops_colouring():
    data = json.loads((FIX / 'sd_notifications.json').read_text())
    row = next(r for r in data['rows'] if r['Site']['StationID'] == 'FM-010')
    # Explicit review reproduction, a variant of the saved reason-bearing row.
    row['Event']['IssueDateTime'] = '2026-11-01T08:50:00Z'
    row['Event']['LiftedDateTime'] = '2026-11-01T09:10:00Z'
    r = SD.build([row], '2026-11-01T10:00:00Z', data['updated_at'], [])[0]
    assert r['ended_at'] == '2026-11-01T01:10:00-08:00'
    assert r['started_at'] == '2026-11-01T01:50:00-07:00'
    assert r['status'] == 'advisory_lifted'
    ivs = S.event_intervals(r, 'CA', dt('2026-11-01T10:00:00Z'))
    assert len(ivs) == 1 and (ivs[0]['end'] - ivs[0]['start']).total_seconds() == 1200
    assert S.status_at(ivs, dt('2026-11-01T09:09:59Z'))[0] == 'red'
    assert S.status_at(ivs, dt('2026-11-01T09:10:00Z'))[0] == 'grey'


def current_for_chart():
    # Synthetic earlier current notice; area and issue date come from saved spill 26-035.
    p = chart()[0]['raw']['phases'][0]
    return OC.current_records([{'section': 'CLOSURES', 'extent': p['area'], 'posted_on': p['date_closed'],
                                'title': p['area'], 'url': OC.PAGE, 'program_reason': 'Sewage contamination'}],
                              '2026-07-03T12:00:00Z')[0]


def test_oc_completed_chart_reconciles_retained_current_notice(tmp_path, monkeypatch):
    original = current_for_chart()
    out = tmp_path / 'oc.json'
    write_events(OC.SOURCE_ID, [original], path=out)
    assert OC.main(['--out', str(out), '--state', str(tmp_path / 'state.json'),
                    '--file', str(FIX / 'oc_current.html'),
                    '--chart-file', '2026=' + str(FIX / 'oc_closures_2026.txt')]) == 0
    records = json.loads(out.read_text())['records']
    old = next(r for r in records if r['event_id'] == original['event_id'])
    target = next(r for r in records if r['event_id'] == 'ca-ocbeachinfo:closure-26-035')
    assert old['duplicate_of'] == target['event_id']
    assert old['source_url'] == OC.PAGE and target['source_url'] == OC.chart_url(2026)
    assert old['started_at'] == original['started_at'] and old['ended_at'] is None
    assert old['fetched_at'] == original['fetched_at']
    assert links_of(records)[target['event_id']]['linked_records']
    # Test-only point makes any obsolete window observable in the real marker build.
    old['lat'], old['lon'] = 33.53, -117.78
    st, _ = status_build(tmp_path, monkeypatch, records, AT)
    assert st['placements'][old['event_id']]['duplicate_of'] == target['event_id']
    assert not [p for p in st['advisory_points'] if p['event_id'] == old['event_id']]
    effective = [r for r in records if r['event_type'] == 'beach_closure' and not r.get('duplicate_of')]
    assert len(effective) == 2  # One spill action, two separately timed areas.
    assert all(S.status_at(S.event_intervals(r, 'CA', dt(AT)), dt(AT))[0] == 'grey' for r in effective)


def test_beachwatch_located_later_phase_survives_county_link(tmp_path, monkeypatch):
    county = chart()
    phase = county[0]['raw']['phases'][1]
    # Synthetic located Beach Watch copy of the real second phase.
    state = copy.deepcopy(county[0])
    state.update(source_id=L.BEACHWATCH, event_id=L.BEACHWATCH + ':test-phase', source_record_id='test-phase',
                 outfall_name=phase['area'], waterbody_text=phase['area'],
                 started_at=OC.day(phase['date_closed']), ended_at=OC.day(phase['date_opened']),
                 lat=33.53, lon=-117.78, coord_source='source',
                 raw={'advisory': {'County': 'Orange', 'DescriptionofArea': phase['area']},
                      'cause': 'Sewage Spill', 'state': 'CA', 'time_zone': 'America/Los_Angeles'})
    counts = L.link([state], county)
    assert not state.get('duplicate_of') and counts['duplicates'] == 0
    assert state['raw']['related_record']['event_id'] in {r['event_id'] for r in county}
    st, _ = status_build(tmp_path, monkeypatch, [*county, state], '2026-07-05T12:00:00Z')
    marker = next(p for p in st['advisory_points'] if p['event_id'] == state['event_id'])
    assert marker['status'] == 'red'


@pytest.mark.parametrize('change', ['area', 'date', 'type', 'end', 'undated', 'ambiguous'])
def test_current_chart_reconciliation_rejects_uncertain_matches(change):
    current, county = current_for_chart(), chart()
    if change == 'area':
        current['outfall_name'] += ' and adjacent beaches'
    elif change == 'date':
        current['started_at'] = '2026-07-03T00:00:00-07:00'
    elif change == 'type':
        current['event_type'] = 'beach_advisory'
    elif change == 'end':
        current['ended_at'] = '2026-07-08T00:00:00-07:00'
    elif change == 'undated':
        current['started_at'] = None
    else:
        other = copy.deepcopy(county[0])
        other['event_id'] += '-another-spill'
        county.append(other)
    before = copy.deepcopy(current)
    OC.reconcile_current([current, *county])
    assert current == before


def test_current_chart_links_recompute_without_mutating_dates_or_citations():
    current, county = current_for_chart(), chart()
    OC.reconcile_current([current, *county])
    once = copy.deepcopy(current)
    OC.reconcile_current([current, *county])
    assert current == once
    OC.reconcile_current([current])
    assert not current.get('duplicate_of') and '_other_source_record' not in current['raw']
    assert current['started_at'] == once['started_at'] and current['ended_at'] is None
    assert current['source_url'] == once['source_url']


def test_later_phase_links_only_to_its_own_area_when_placement_is_equivalent():
    county = chart()
    target = county[1]
    state = copy.deepcopy(target)
    state.update(source_id=L.BEACHWATCH, event_id=L.BEACHWATCH + ':test-equivalent',
                 raw={'advisory': {'County': 'Orange', 'DescriptionofArea': target['outfall_name']}})
    assert L.link([state], county)['duplicates'] == 1
    assert state['duplicate_of'] == target['event_id']
    state['water_slugs'] = ['test-water']
    assert L.link([state], county)['duplicates'] == 0
    assert not state['duplicate_of'] and state['raw']['related_record']


def test_old_aggregate_is_related_even_without_a_coordinate_difference():
    county = chart()
    state = copy.deepcopy(county[1])
    state.update(source_id=L.BEACHWATCH, event_id=L.BEACHWATCH + ':test-old-aggregate',
                 raw={'advisory': {'County': 'Orange', 'DescriptionofArea': state['outfall_name']}})
    aggregate = copy.deepcopy(county[0])
    aggregate['raw'].pop('phase')
    aggregate['ended_at'] = county[1]['ended_at']
    assert L.link([state], [aggregate])['duplicates'] == 0
    assert state['raw']['related_record']['event_id'] == aggregate['event_id']


def test_sd_fallback_rejects_a_truly_earlier_lift():
    data = json.loads((FIX / 'sd_notifications.json').read_text())
    row = data['rows'][0]
    row['Event']['IssueDateTime'] = '2026-11-01T09:10:00Z'
    row['Event']['LiftedDateTime'] = '2026-11-01T08:50:00Z'
    r = SD.build([row], AT, data['updated_at'], [])[0]
    assert r['ended_at'] is None and r['raw']['_end_not_used']
