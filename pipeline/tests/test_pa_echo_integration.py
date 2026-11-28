"""Integration assertions; shared changes are supplied in the task's shared-files.patch."""
from build import status as S
from common import event
from export import detail as D
from ingest import pa_echo_violations as M
from test_pa_echo_violations import records


def test_status_does_not_promote_possible_matches_to_duplicates():
    sso = next(r for r in records() if r['event_type'] == 'sso')
    cso = event(source_id='pa-phila-csocast', source_record_id='same-day', event_type='cso',
                npdes_permit=sso['npdes_permit'], started_at=sso['started_at'], time_precision='poll')
    M.link_records([sso], [cso])
    assert cso['event_id'] in sso['raw']['possible_matches']
    assert S.find_duplicates([sso, cso]) == {}


def test_export_exposes_regulatory_end_without_turning_it_into_discharge_end():
    r = next(r for r in records() if r['source_record_id'] == '3687608730')
    d = D.detail_of(r)
    assert 'bypass' in d['report_kind']
    assert d['source_end_date'] == '07/17/2026'
    assert d['source_end_text'] == r['raw']['source_end_text']
    assert not d.get('cause') and not d.get('duration_text')
    r = next(r for r in records() if r['source_record_id'] == '3633971227')
    d = D.detail_of(r)
    assert d['description'] == 'Leak at manhole 575 into Singer Run'
    assert d['overflow_point'] == 'manhole 575'


def test_confirmed_cross_source_link_is_bidirectional_in_export():
    records_ = records()
    local = event(source_id='pa-alcosan', source_record_id=M.ALCOSAN_POWER_OUTAGE.split(':', 1)[1],
                  npdes_permit='PA0025984', event_type='bypass', started_at='2026-03-06T18:00:00-05:00')
    M.link_records(records_, [local])
    r = next(r for r in records_ if r['source_record_id'] == '3687608730')
    links = D.links_of(records_ + [local])
    assert links[local['event_id']]['linked_records'][0]['event_id'] == r['event_id']
    assert links[r['event_id']]['linked_records'][0]['event_id'] == local['event_id']


def test_different_named_waters_keep_independent_status_and_counts(tmp_path):
    import json
    from datetime import datetime
    from test_pa_echo_violations import singer_variants

    recs = singer_variants()
    M.link_records(recs, [])
    (tmp_path / (M.SOURCE_ID + '.json')).write_text(json.dumps({
        'source_id': M.SOURCE_ID, 'ok': True, 'records': recs,
        'last_ok_at': '2026-11-28T15:00:00Z'}))
    waters = {slug: {'slug': slug, 'name': name, 'state': 'PA', 'kind': 'stream'}
              for slug, name in [('singer-run-pa', 'Singer Run'), ('example-creek-pa', 'Example Creek')]}
    status, _ = S.build(events_dir=tmp_path, waters=waters, outfalls=[], registry={}, reaches={}, flows=({}, {}),
                        now=datetime.fromisoformat('2017-10-04T12:00:00-04:00'), write=False)
    assert status['duplicates'] == {}
    assert status['counts']['events_by_category'] == {'sewage': 2}
    for r, slug in zip(recs, waters):
        assert status['placements'][r['event_id']].get('duplicate_of') is None
        assert status['placements'][r['event_id']]['water_slugs'] == [slug]
        water = status['waters'][slug]
        assert water['events'] == [r['event_id']]
        assert water['status'] == 'yellow'
