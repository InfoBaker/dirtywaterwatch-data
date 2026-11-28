"""Live LA/Long Beach markup, plus explicit mutations for lifecycle/error cases."""
from pathlib import Path
import copy
import json

import pytest

from ingest import ca_lacounty_beaches as LA
from ingest import ca_long_beach_water_quality as LB
from ingest import ca_local_beaches as C

FIX = Path(__file__).parent / 'fixtures' / 'ca_local_beaches'
POLL = '2026-11-28T15:00:00Z'


def notice(key):
    return LA.parse_release((FIX / f'pr-{key}.html').read_text(), str(key))


def test_archive_paginates_every_page_and_checks_total():
    calls = []
    def get(url):
        from urllib.parse import parse_qs, urlparse
        start = int(parse_qs(urlparse(url).query).get('start', ['1'])[0])
        calls.append(start)
        return (FIX / f'index-{start-1}.html').read_text()
    rows = LA.fetch_index(get)
    assert len(rows) == 176 and len({r['id'] for r in rows}) == 176
    assert calls == [1, 26, 51, 76, 101, 126, 151, 176]
    with pytest.raises(ValueError):
        LA.fetch_index(lambda _: (FIX / 'index-0.html').read_text())


def test_map_station_ids_points_source_update_and_no_sample_status():
    rows, updated = LA.parse_map((FIX / 'la.kml').read_text())
    assert len(rows) == 4 and updated == '2026-11-25T15:30:00-08:00'
    st = {r['station_id']: r for r in rows}
    assert st['DPH106']['lat'] == 34.0024369
    assert st['DPH106']['status'] == 'ADVISORY'
    assert st['SMB-1-13']['status'] == 'NO RECENT SAMPLES'


def test_long_beach_column_positions_and_date_precision():
    rows, updated = LB.parse((FIX / 'lb.html').read_text())
    assert len(rows) == 15 and updated == '2026-11-25T00:00:00-08:00'
    assert all(r['status'] == 'OPEN' for r in rows)
    assert rows[0]['station_id'] == 'B-5'
    body = (FIX / 'lb.html').read_text().replace('<strong><strong>●</strong></strong></td>\n<td align="center" style="background-color: #9bc2e6;">&nbsp;', '&nbsp;</td>\n<td align="center" style="background-color: #9bc2e6;">●', 1)
    mutated, _ = LB.parse(body)
    assert mutated[0]['status'] == 'ADVISORY' and 'Bacterial' in mutated[0]['cause']
    assert C.snapshot(LB.SOURCE_ID, rows, updated, [], POLL, LB.URL, LB.AUTHORITY) == []


def test_snapshots_stable_with_observation_times_and_no_invented_end():
    rows, updated = LB.parse((FIX / 'lb.html').read_text())
    rows[0].update(status='CLOSED', cause=None)
    a = C.snapshot(LB.SOURCE_ID, rows, updated, [], POLL, LB.URL, LB.AUTHORITY)
    b = C.snapshot(LB.SOURCE_ID, rows, updated, a, '2026-11-29T15:00:00Z', LB.URL, LB.AUTHORITY)
    assert len(b) == 1 and a[0]['event_id'] == b[0]['event_id']
    assert b[0]['started_at'] is None and b[0]['reported_at'] is None
    assert b[0]['raw']['observed_since'] == POLL
    assert b[0]['source_updated_at'] == updated
    rows[0]['status'] = 'OPEN'
    c = C.snapshot(LB.SOURCE_ID, rows, updated, b, '2026-11-30T15:00:00Z', LB.URL, LB.AUTHORITY)
    assert c[0]['ended_at'] is None and c[0]['raw']['_unlisted_since']


def test_notices_keep_sewage_volume_cause_extent_and_merge_repeated_closure():
    notices = [notice(k) for k in ('5285', '5286', '5287')]
    records = LA.release_records(notices, [], POLL)
    sewage = [r for r in records if r['event_type'] == 'sso']
    assert len(sewage) == 1
    r = sewage[0]
    assert r['volume_gal'] == 300 and r['estimate_flag'] == 'estimated'
    assert 'approximately 300 gallons' in r['volume_text']
    assert r['waterbody_text'] == 'Avalon Beach'
    assert r['started_at'] is None and r['published_at'] == '2026-03-25T00:00:00-07:00'
    assert r['ended_at'] is None and r['time_precision'] == 'day'
    assert r['raw']['sewage_cause'] and len(r['raw']['notices']) == 3
    assert '50 yards' in r['raw']['extent']
    assert any(r['event_type'] == 'beach_advisory' for r in records)


def test_explicit_lifting_is_closure_end_not_discharge_end():
    records = LA.release_records([notice(k) for k in ('5222', '5223', '5224')], [], POLL)
    closures = [r for r in records if r['event_type'] == 'beach_closure']
    assert len(closures) == 1
    assert closures[0]['ended_at'] == '2026-01-13T00:00:00-08:00'
    assert closures[0]['status'] == 'advisory_lifted'
    assert closures[0]['raw']['cause'] is None  # a closure label is not proof of sewage


def test_rain_deadline_is_not_an_observed_lifting():
    recs = LA.release_records([notice('5496')], [], POLL)
    assert len(recs) == 1 and recs[0]['event_type'] == 'rain_advisory'
    assert recs[0]['ended_at'] is None
    assert recs[0]['raw']['announced_until'] == '2026-11-23T12:00:00-08:00'


def test_long_beach_outage_retains_history(tmp_path, monkeypatch):
    out = tmp_path / 'events.json'
    old = {'event_id': 'kept', 'raw': {}, 'started_at': None}
    out.write_text(json.dumps({'records': [old], 'ok': True}))
    bad = tmp_path / 'bad.html'; bad.write_text('<html>unavailable</html>')
    assert LB.main(['--file', str(bad), '--out', str(out)]) == 1
    saved = json.loads(out.read_text())
    assert not saved['ok'] and saved['records'] == [old]


def test_separated_rain_notices_do_not_make_one_yearlong_advisory():
    first = notice('5496')
    earlier = copy.deepcopy(first)
    earlier.update(id='5000', published='2026-01-01T00:00:00-08:00', announced_until='2026-01-04T12:00:00-08:00')
    recs = LA.release_records([earlier, first], [], POLL)
    assert len(recs) == 2
    assert all(r['ended_at'] is None for r in recs)


def test_map_absence_is_not_a_lift_and_late_old_notice_is_not_reconfirmed():
    rows, updated = LA.parse_map((FIX / 'la.kml').read_text())
    recs = LA.combine([notice('5501')], rows, updated, [], POLL)
    maps = [r for r in recs if r['raw'].get('station_id')]
    assert maps and all(r['duplicate_of'] for r in maps)
    old = notice('5501'); old['published'] = '2026-01-01T00:00:00-08:00'
    recs = LA.combine([old], rows, updated, [], POLL)
    assert all(not r['duplicate_of'] for r in recs if r['raw'].get('station_id'))


def test_unbulleted_notice_keeps_seven_warnings():
    n = notice('5456')
    assert len(n['warnings']) == 7


def test_state_copy_links_require_station_and_containing_dates():
    from ingest.ca_local_beach_link import reconcile
    from ingest.ca_beachwatch import build_record
    data = json.loads((FIX / 'beachwatch.json').read_text())
    others = [build_record(row, POLL, '2026-03-06') for row in data]
    local = LA.release_records([notice(k) for k in ('5222', '5223', '5224')], [], POLL)
    closed = next(r for r in local if r['event_type'] == 'beach_closure')
    linked = reconcile([closed], others, [])[0]
    assert linked['duplicate_of'] == 'ca-beachwatch-advisories:67160'
    assert len(linked['raw']['same_action_records']) == 2
    assert linked['ended_at'] == closed['ended_at']
    changed = copy.deepcopy(closed); changed['ended_at'] = '2026-01-14T00:00:00-08:00'
    assert not reconcile([changed], others, [])[0]['duplicate_of']
    assert not reconcile([linked], [], [])[0]['duplicate_of']  # target removed


def test_linker_does_not_hide_a_different_water_or_guess_a_sewage_incident():
    from ingest.ca_local_beach_link import reconcile
    local = next(r for r in LA.release_records([notice('5285')], [], POLL) if r['event_type'] == 'sso')
    spill = dict(event_id='ca-swrcb-ciwqs-spills-flatfile:1', started_at='2026-03-25T10:00:00-07:00',
                 volume_gal=300, waterbody_text='Avalon Beach', source_url='https://www.waterboards.ca.gov/')
    r = reconcile([local], [], [spill])[0]
    assert not r['duplicate_of'] and r['raw']['related_records'][0]['event_id'] == spill['event_id']
    spill['waterbody_text'] = 'Other Beach'
    assert 'related_records' not in reconcile([local], [], [spill])[0]['raw']


def test_only_explicit_page_lifting_sets_rain_end_at_source_minute():
    page = ('Beach Water Quality: The Ocean Water Quality Rain Advisory has been lifted for all Los Angeles County '
            'beaches on Monday, November 23, 2026, at 12:00pm.')
    recs = LA.combine([notice('5496')], [], '2026-11-25T15:30:00-08:00', [], POLL, page)
    assert recs[0]['ended_at'] == '2026-11-23T12:00:00-08:00'
    assert recs[0]['raw']['ended_at_precision'] == 'minute'
    assert recs[0]['raw']['end_source_url'] == LA.PAGE
    assert LA.rain_lifted('A rain advisory may be lifted tomorrow') is None


def test_sanitized_network_error_and_la_retention(tmp_path, monkeypatch):
    import requests
    out = tmp_path / 'events.json'; state = tmp_path / 'state.json'
    old = {'event_id': 'kept', 'raw': {}}
    out.write_text(json.dumps({'records': [old], 'ok': True}))
    def fail(*args, **kwargs):
        raise requests.ConnectionError('Connection refused https://example.org/?token=PRIVATEVALUE')
    monkeypatch.setattr(requests.Session, 'get', fail)
    assert LA.main(['--out', str(out), '--state', str(state)]) == 1
    saved = json.loads(out.read_text())
    assert saved['records'] == [old] and not saved['ok']
    assert 'PRIVATEVALUE' not in saved['error']


def test_reason_rule_distinguishes_bacteria_and_unexplained_closure():
    from build import status, beach_reason
    from datetime import datetime, timezone
    rules = copy.deepcopy(status.load_rules())
    for source in (LA.SOURCE_ID, LB.SOURCE_ID):
        rules['beach_reason']['sources'][source] = {'kind': 'fields', 'fields': ['cause']}
    rows, updated = LB.parse((FIX / 'lb.html').read_text())
    rows[0].update(status='CLOSED', cause=None)
    r = C.snapshot(LB.SOURCE_ID, rows, updated, [], POLL, LB.URL, LB.AUTHORITY)[0]
    assert beach_reason.judge(r, rules)['stated'] is False
    assert status.event_intervals(r, 'CA', datetime(2026, 11, 28, tzinfo=timezone.utc), None, rules) == []
    rows[0].update(status='ADVISORY', cause='Bacterial levels are outside of State Standards.')
    r = C.snapshot(LB.SOURCE_ID, rows, updated, [], POLL, LB.URL, LB.AUTHORITY)[0]
    assert beach_reason.judge(r, rules)['stated'] is True
    assert any(i['color'] == 'red' for i in status.event_intervals(r, 'CA', datetime(2026, 11, 28, tzinfo=timezone.utc), None, rules))


def test_source_categories_and_raw_field_declarations():
    import yaml
    from build.status import category_of
    assert category_of('sso') == 'sewage'
    assert category_of('beach_advisory') == category_of('beach_closure') == 'beach'
    for source in (LA.SOURCE_ID, LB.SOURCE_ID):
        cfg = yaml.safe_load((FIX.parents[3] / 'data' / 'sources' / f'{source}.yaml').read_text())
        assert cfg['enabled'] and set(cfg['raw_fields']) == {'reporter_contact', 'customer_identifier', 'description'}
        assert cfg['raw_fields']['reporter_contact'] == cfg['raw_fields']['customer_identifier'] == []


def test_hyperion_alias_uses_the_state_station_metadata():
    assert LA.area_key('Hyperion Plant outfall at Dockweiler State Beach') == 'DPH111'
    assert 'CABEACH_WQX-DPH%20111' in LA.STATION_REFERENCES['DPH111']


def test_rebuild_does_not_retain_obsolete_group_when_same_notice_is_reparsed():
    original = LA.release_records([notice('5501')], [], POLL)
    changed = copy.deepcopy(original[0])
    changed['event_id'] = LA.SOURCE_ID + ':obsolete-group'
    changed['source_record_id'] = 'obsolete-group'
    rebuilt = LA.release_records([notice('5501')], original + [changed], POLL)
    assert len(rebuilt) == len(original)
    # Earlier years really absent from a shortened archive remain retained.
    historical = copy.deepcopy(changed)
    historical['raw']['notices'][0]['id'] = '1'
    assert any(r['event_id'] == historical['event_id'] for r in LA.release_records([notice('5501')], [historical], POLL))
