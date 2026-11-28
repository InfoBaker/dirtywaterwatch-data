"""Regressions for the four MSDGC review findings; transitions are simulated."""
import copy
import json
from datetime import datetime, timedelta

import pytest

from build import status as S
from common import event
from ingest import oh_msdgc_cso as M
from test_oh_msdgc_cso import NOW, fixture, site

H = timedelta(hours=1)


def records(state):
    return [M.to_record(k, v, []) for k, v in state['events'].items()]


def colour(e, at):
    return S.status_at(S.event_intervals(e, 'OH', at), at)


def test_authority_window_from_observed_normal_levels():
    state = {}
    M.poll(state, [site()], NOW)
    M.poll(state, [site('Recently Active', 1795856419000)], '2026-11-28T14:30:00Z')
    e, = records(state)
    end = datetime.fromisoformat(e['ended_at'])
    for hours in (0, 1, 71.999):
        c, intervals = colour(e, end + hours * H)
        assert c == 'red'
        iv, = intervals
        assert iv['rule'] == 'authority_window'
        assert iv['red_rule']['source'] == M.URL
        assert iv['red_rule']['clock'] == 'observed_return_to_normal'
    assert colour(e, end + 72 * H)[0] == 'grey'
    assert e['advice_window_hours'] == 72
    assert M.ADVICE in e['advice_window_basis']
    assert 'observed' in e['advice_window_basis']
    assert e['raw']['ended_at_precision'] == 'poll'
    assert e['reported_at'] is None and e['published_at'] is None


def load_pair(tmp_path, mapped, other):
    for e in (mapped, other):
        (tmp_path / (e['source_id'] + '.json')).write_text(json.dumps({
            'source_id': e['source_id'], 'ok': True, 'records': [e], 'fetched_at': mapped['fetched_at']}))
    _, loaded, problems = S.load_events(tmp_path)
    assert not problems
    duplicates = S.find_duplicates(loaded)
    duplicates.update({e['event_id']: e['duplicate_of'] for e in loaded if e.get('duplicate_of')})
    return loaded, duplicates


def test_linked_unknown_echo_keeps_active_then_expires(tmp_path):
    state = {}
    M.poll(state, [site('Recently Active', 1795849219000)], NOW)
    M.poll(state, [site()], NOW)
    e, = records(state)
    e.update(npdes_permit='OH0105457', outfall_id='223')
    other = event(source_id='echo-sewer-overflow', source_record_id='123', event_type='cso', status='unknown',
                  npdes_permit=e['npdes_permit'], outfall_id=e['outfall_id'],
                  started_at='2026-11-28T07:30:00-05:00', time_precision='minute', fetched_at=NOW)
    original_ids = {e['event_id'], other['event_id']}
    for stopped in (False, True):
        if stopped:
            M.poll(state, [site('Recently Active', 1795856419000)], '2026-11-28T14:30:00Z')
            e, = records(state)
            e.update(npdes_permit='OH0105457', outfall_id='223')
        M.link_records([e], [other])
        loaded, dup = load_pair(tmp_path, e, other)
        assert {x['event_id'] for x in loaded} == original_ids
        shown = [x for x in loaded if x['event_id'] not in dup]
        assert len(shown) == 1
        at = datetime.fromisoformat(e['ended_at'] or e['started_at']) + H
        assert colour(shown[0], at)[0] == 'red'
        # Exercise the full status build as well as its loader/interval rules.
        e.update(water_slugs=['ohio-river-oh'], waterbody_text='Ohio River')
        load_pair(tmp_path, e, other)
        water = {'slug': 'ohio-river-oh', 'name': 'Ohio River', 'kind': 'river', 'state': 'OH'}
        for instant, expected in [(at, 'red')] + ([(at + 96 * H, 'grey')] if stopped else []):
            built, _ = S.build(events_dir=tmp_path, now=instant, write=False,
                               waters={'ohio-river-oh': water}, outfalls=[], registry={}, reaches={},
                               flows=({}, {}), rain={}, discharger_towns={}, discharger_waters={},
                               discharger_aliases_map={}, placement_cache=False)
            assert built['waters']['ohio-river-oh']['status'] == expected
            assert built['counts']['duplicates'] == 1
        if stopped:
            assert colour(shown[0], at + 96 * H)[0] == 'grey'
            assert shown[0]['raw']['end_bounds'] == e['raw']['end_bounds']
            assert shown[0]['raw']['ended_at_precision'] == 'poll'
        assert other['ended_at'] is None and other['status'] == 'unknown'


def pair():
    return [r for r in fixture('snapshot.json') if r['info']['facility_name_edmr'] == 'CSO-403']


def changed(rows, statuses, step):
    out = copy.deepcopy(rows)
    for row, status in zip(out, statuses):
        row['Current State'] = status
        row['timestamp'] += step * 3600000
    return out


def test_paired_real_facility_ids_are_one_event_and_close_conservatively():
    rows = pair()
    assert {r['facility_id'] for r in rows} == {'11511001', '11511034'}
    state = {}
    M.poll(state, rows, NOW)
    M.poll(state, changed(rows, ['Currently Active'] * 2, 1), '2026-11-28T15:00:00Z')
    e, = records(state)
    original_id = e['event_id']
    assert len(e['raw']['facility_observations']) >= 2
    assert len(S.find_duplicates([e])) == 0
    for step, status in enumerate(('Data Unavailable', None, 'Flooded', 'Currently Active'), 2):
        M.poll(state, changed(rows, ['Recently Active', status], step), '2026-11-28T22:00:00Z')
        assert records(state)[0]['ended_at'] is None
    M.poll(state, changed(rows[:1], ['Recently Active'], 6), '2026-11-28T23:00:00Z')
    assert records(state)[0]['ended_at'] is None
    M.poll(state, changed(rows, ['Recently Active'] * 2, 1), '2026-11-28T23:00:00Z')
    assert records(state)[0]['ended_at'] is None
    normal = changed(rows, ['Recently Active'] * 2, 7)
    M.poll(state, normal, '2026-11-29T00:00:00Z')
    e, = records(state)
    assert e['event_id'] == original_id
    assert e['ended_at'] == max(M.source_time(r['timestamp']) for r in normal)
    assert {r['facility_id'] for r in e['raw']['stop_rows']} == {'11511001', '11511034'}
    M.poll(state, changed(rows[::-1], ['Currently Active'] * 2, 8), '2026-11-29T01:00:00Z')
    assert len(records(state)) == 2


def bundle(rows):
    # Real decoded rows encoded in complete Power BI envelopes for rows_of/run.
    def doc(fields, data):
        schema = [{'N': f'G{i}'} for i in range(len(fields))]
        return {'results': [{'result': {'data': {'descriptor': {'Select': [{'Name': 's.' + f} for f in fields]},
                'dsr': {'DS': [{'IC': True, 'PH': [{'DM0': [
                    {'S': schema, 'C': [r.get(f) for f in fields]} for r in data]}]}]}}}}]}
    return {'states': doc(M.STATE_FIELDS, rows), 'info': doc(M.INFO_FIELDS, [r['info'] for r in rows])}


def test_complete_inventory_decrease_keeps_history_and_new_activity(tmp_path):
    rows = fixture('snapshot.json')
    archive = tmp_path / 'state.json'
    before, _ = M.run(bundle(rows), NOW, archive, registry=[])
    missing = next(r for r in rows if r['Current State'] == 'Currently Active')
    old = next(e for e in before if e['raw']['row']['facility_id'] == missing['facility_id'])
    after_rows = [r for r in rows if r is not missing]
    activated = next(r for r in after_rows if r['info']['facility_name_edmr'] == 'CSO-403')
    activated['Current State'] = 'Currently Active'
    activated['timestamp'] += 3600000
    for read in ('2026-11-28T15:30:00Z', '2026-11-28T16:30:00Z'):
        after, meta = M.run(bundle(after_rows), read, archive, registry=[])
        assert meta['poll']['sites'] == 204
        assert old == next(e for e in after if e['event_id'] == old['event_id'])
        assert len(after) == len(before) + 1
    bad = bundle(after_rows)
    bad['info']['results'][0]['result']['data']['dsr']['DS'][0]['PH'][0]['DM0'].pop()
    saved = archive.read_bytes()
    with pytest.raises(ValueError):
        M.run(bad, NOW, archive, registry=[])
    assert archive.read_bytes() == saved


def test_saved_published_ids_survive_upgrade_and_repeated_poll():
    state = fixture('published-state.json')
    keys = set(state['events'])
    before = {e['event_id']: (e['started_at'], e['ended_at'], e['reported_at']) for e in records(state)}
    M.poll(state, fixture('snapshot.json'), '2026-11-28T17:00:00Z')
    M.poll(state, fixture('snapshot.json'), '2026-11-28T18:00:00Z')
    assert set(state['events']) == keys
    assert {e['event_id']: (e['started_at'], e['ended_at'], e['reported_at']) for e in records(state)} == before


def test_legacy_pair_keeps_both_ids_but_only_one_physical_event():
    # Simulate a saved pre-fix archive with each real sensor opened separately.
    rows = changed(pair(), ['Currently Active'] * 2, 1)
    state = {'events': {}, 'open': {}, 'sites': {}}
    for row in rows:
        single = {}
        M.poll(single, [row], NOW)
        for key in state:
            state[key].update(single[key])
    ids = {e['event_id'] for e in records(state)}
    M.poll(state, changed(pair(), ['Currently Active'] * 2, 2), '2026-11-28T16:00:00Z')
    es = records(state)
    assert {e['event_id'] for e in es} == ids
    shown, = [e for e in es if not e['duplicate_of']]
    dup, = [e for e in es if e['duplicate_of']]
    assert dup['duplicate_of'] == shown['event_id']
    M.poll(state, changed(pair(), ['Recently Active'] * 2, 3), '2026-11-28T17:00:00Z')
    es = records(state)
    assert all(e['ended_at'] for e in es)
    assert len({e['ended_at'] for e in es}) == 1
    assert {e['event_id'] for e in es} == ids


def test_single_clear_does_not_close_an_unavailable_alias_first_observed_together():
    rows = pair()
    state = {}
    M.poll(state, changed(rows, ['Currently Active', 'Data Unavailable'], 1), NOW)
    M.poll(state, changed(rows, ['Recently Active', 'Data Unavailable'], 2), NOW)
    assert records(state)[0]['ended_at'] is None


def test_complete_empty_inventory_and_partial_query_rejected():
    with pytest.raises(ValueError):
        M.rows_of(bundle([]), {})
    doc = bundle(fixture('snapshot.json'))
    doc['states']['results'][0]['result']['data']['dsr']['DS'][0]['IC'] = False
    with pytest.raises(ValueError):
        M.rows_of(doc, {})


@pytest.mark.parametrize('field,value', [('facility_name_edmr', 'CSO-404'), ('sewershed', 'Mill Creek')])
def test_distinct_source_outfalls_are_not_merged(field, value):
    rows = changed(pair(), ['Currently Active'] * 2, 1)
    rows[1]['info'][field] = value
    state = {}
    M.poll(state, rows, NOW)
    assert len(records(state)) == 2


def test_linked_report_with_stated_end_remains_canonical(tmp_path):
    state = {}
    M.poll(state, [site('Recently Active', 1795849219000)], NOW)
    M.poll(state, [site()], NOW)
    e, = records(state)
    e.update(npdes_permit='OH0105457', outfall_id='223')
    other = event(source_id='echo-sewer-overflow', source_record_id='ended', event_type='cso', status='ended',
                  npdes_permit=e['npdes_permit'], outfall_id=e['outfall_id'],
                  started_at='2026-11-28T07:30:00-05:00', ended_at='2026-11-28T08:10:00-05:00',
                  time_precision='minute', fetched_at=NOW)
    M.link_records([e], [other])
    loaded, dup = load_pair(tmp_path, e, other)
    assert dup == {e['event_id']: other['event_id']}
    kept, = [x for x in loaded if x['event_id'] not in dup]
    assert kept['started_at'] == other['started_at'] and kept['ended_at'] == other['ended_at']
