from datetime import datetime,UTC
import copy
import json
from pathlib import Path
from build import status as S
from export import detail as D
from ingest import fl_miami_dade_sso as M


def record():
    data=json.loads((Path(__file__).parent/'fixtures/fl_miami_dade_sso.json').read_text())
    a=next(a for a in data['county'] if a['TRACKNUM']=='597571')
    return M.to_record(a,'2026-11-22T12:00:00Z')


def test_shared_export_mapping():
    r=record(); d=D.detail_of(r)
    assert d['cause']=='FM; CONTRACTOR' and 'overflow_point' not in d
    assert d['volume_qualifier']=='estimated'
    assert d['notes']=='59840 gallons recovered (estimated)'
    assert r['volume_gal']==72917


def test_day_end_same_day_is_credible_without_inventing_time():
    r=record(); r['ended_at']='2026-11-03T00:00:00-05:00'; r['raw']['ended_at_precision']='day'
    assert S.end_not_credible(r) is None
    assert r['ended_at']=='2026-11-03T00:00:00-05:00'
    r['raw']['ended_at_precision']='minute'
    assert S.end_not_credible(r)
    r['raw']['ended_at_precision']='day'; r['ended_at']='2026-11-01T00:00:00-04:00'
    assert S.end_not_credible(r)


def test_previous_day_end_is_before_a_midnight_start():
    r=record(); r['started_at']='2026-11-03T00:00:00-05:00'
    r['ended_at']='2026-11-02T00:00:00-05:00'; r['raw']['ended_at_precision']='day'
    assert S.end_not_credible(r)


import pytest


@pytest.mark.parametrize('county_water, dep_water', [
    ('Biscayne Canal', 'Gratigny Canal'),
    ('Intracoastal Waterway', 'Mahi Waterway'),
])
def test_explicit_identity_counts_once_with_both_water_contributions(tmp_path, county_water, dep_water):
    from ingest import fl_dep_pnp as P
    from export.detail import links_of
    data = json.loads((Path(__file__).parent / 'fixtures/fl_miami_dade_sso.json').read_text())
    c, p = record(), P.build(data['pnp'], '2026-11-22T12:00:00Z', [], permits={})[0][0]
    c['waterbody_text'], p['waterbody_text'] = county_water, dep_water
    p['raw']['reached_water'] = True
    # Both records cite WASD incident 597571 on Nov. 3; neither supplies the other's times.
    original = [(r['started_at'], r['ended_at'], r['waterbody_text']) for r in [c, p]]
    assert M.link_pnp([c], [p])['county_linked'] == 1
    waters = {}
    for i, r in enumerate([c, p]):
        slug = f'test-water-{i}-fl'
        waters[slug] = {'slug': slug, 'name': r['waterbody_text'], 'state': 'FL', 'kind': 'canal',
                        'bbox': [-80.17, 25.68, -80.15, 25.69]}
        (tmp_path / (r['source_id'] + '.json')).write_text(json.dumps({
            'source_id': r['source_id'], 'ok': True, 'records': [r]}))
    def build_at(at):
        return S.build(now=datetime.fromisoformat(at), write=False, events_dir=tmp_path,
                       waters=waters, outfalls=[], registry={}, reaches={}, flows=({}, {}),
                       discharger_towns={}, discharger_waters={}, discharger_aliases_map={},
                       placement_cache=False)[0]
    st = build_at('2026-11-03T14:00:00-05:00')
    assert st['counts']['events_by_category']['sewage'] == 1
    assert st['counts']['duplicates'] == 1
    assert all(st['waters'][slug]['status'] == 'red' for slug in waters)
    assert st['placements'][c['event_id']]['duplicate_of'] == p['event_id']
    assert st['placements'][c['event_id']]['water_slugs'] == ['test-water-0-fl']
    assert st['placements'][p['event_id']]['water_slugs'] == ['test-water-1-fl']
    links = links_of([c, p])
    assert links[c['event_id']]['linked_records'][0]['event_id'] == p['event_id']
    assert links[p['event_id']]['linked_records'][0]['event_id'] == c['event_id']
    assert [(r['started_at'], r['ended_at'], r['waterbody_text']) for r in [c, p]] == original
    later = build_at('2026-11-03T21:00:00-05:00')
    assert later['waters']['test-water-0-fl']['status'] != 'red'
    assert later['waters']['test-water-1-fl']['status'] == 'red'


@pytest.mark.parametrize('change', ['missing_target', 'wrong_target', 'unrelated_source'])
def test_water_contribution_is_scoped_to_present_linked_miami_identity(change):
    c, p = record(), record()
    p['event_id'] = 'fl-dep-pnp:counterpart'
    p['source_id'] = 'fl-dep-pnp'
    c['duplicate_of'] = p['event_id']
    c['raw']['_miami_water_contribution'] = p['event_id']
    events = [c, p]
    if change == 'missing_target': events = [c]
    elif change == 'wrong_target': c['raw']['_miami_water_contribution'] = 'fl-dep-pnp:other'
    else: c['source_id'] = 'unrelated-source'
    assert not S.retained_water_contributions(events, {c['event_id']: p['event_id']})
