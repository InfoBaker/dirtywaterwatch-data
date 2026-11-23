"""Real agency shapes; transition variants explicitly change status/date fields only."""
import copy
import json
from pathlib import Path

import pytest
from ingest.generic import arcgis, runner
from ingest import mo_dnr_hab as M, wi_dnr_beach_health as W

FIX = Path(__file__).parent / 'fixtures'
AT = '2026-11-22T18:00:00Z'


def generic(sid, fixture):
    _, block = runner.load_source(sid)
    return block, arcgis.parse(block, fixture.read_bytes())


def test_oregon_lift_keeps_episode_identity_and_source_end():
    sid = 'or-oha-hab-advisories'
    block, rows = generic(sid, FIX / 'lifts' / f'{sid}.json')
    active = dict(rows[0], AdvisoryStatus='Precaution', Issue_Date=1787122800000)  # Aug. 19, as lift text states
    before, _ = runner.build(sid, block, [active], '2026-11-14T12:00:00Z', [])
    after, _ = runner.build(sid, block, rows, AT, before)
    assert len(after) == 1
    r = after[0]
    assert r['event_id'] == before[0]['event_id'] and r['started_at'] == before[0]['started_at']
    assert r['status'] == 'advisory_lifted' and r['ended_at'][:10] == '2026-11-19'
    assert r['raw']['ended_at_precision'] == 'day'
    assert r['raw']['row']['AdvisoryStatus'] == 'Advisory/Precaution Lifted'
    again, _ = runner.build(sid, block, rows, AT, after)
    assert len(again) == 1 and again[0]['event_id'] == r['event_id']
    assert runner.build(sid, block, rows, AT, [])[0] == []  # a lift alone cannot create an open spell


def test_oregon_ambiguous_or_older_lift_does_not_close_another_episode():
    sid = 'or-oha-hab-advisories'
    block, rows = generic(sid, FIX / 'lifts' / f'{sid}.json')
    active = dict(rows[0], AdvisoryStatus='Precaution', Issue_Date=1787122800000)
    before, _ = runner.build(sid, block, [active], AT, [])
    other = copy.deepcopy(before[0]); other['event_id'] += '-other'; other['source_record_id'] += '-other'
    after, _ = runner.build(sid, block, rows, AT, before+[other])
    assert len(after) == 2 and all(r['ended_at'] is None for r in after)
    assert all('_unlisted_since' not in r['raw'] for r in after)


def test_kentucky_real_text_lift_with_empty_habend_closes_exact_episode():
    sid = 'ky-dow-hab-viewer'
    block, rows = generic(sid, FIX / 'lifts' / f'{sid}.json')
    _, originals = generic(sid, FIX / 'ky_dow_hab.json')
    before, _ = runner.build(sid, block, originals, '2026-11-14T12:00:00Z', [])
    after, _ = runner.build(sid, block, rows, AT, before)
    assert len(after) == 1 and after[0]['event_id'] == before[0]['event_id']
    assert after[0]['ended_at'] == '2026-11-18' and after[0]['status'] == 'advisory_lifted'
    assert 'HABSTATDES' in after[0]['raw']['end_basis']
    assert runner.build(sid, block, rows, AT, [])[0] == []


def test_kentucky_inactive_habend_is_consumed_and_missing_end_keeps_caution():
    sid = 'ky-dow-hab-viewer'
    block, rows = generic(sid, FIX / 'ky_dow_hab.json')
    active = rows[-1]
    before, _ = runner.build(sid, block, [active], AT, [])
    inactive = dict(active, HABSTATUS='NoDetect', HABEND=1794960000000, HABSTATDES='No cyanotoxins detected.')
    after, _ = runner.build(sid, block, [inactive], AT, before)
    assert after[0]['status'] == 'advisory_lifted' and after[0]['ended_at'] == '2026-11-18'
    inactive['HABEND'] = None
    held, _ = runner.build(sid, block, [inactive], AT, before)
    assert held[0]['status'] == 'advisory_active' and held[0]['ended_at'] is None
    assert '_unlisted_since' not in held[0]['raw']


def test_missouri_source_dissipation_and_confirmation_method():
    doc = json.loads((FIX / 'lifts/mo.json').read_text())
    active = copy.deepcopy(doc)
    active['features'][0]['attributes'].update(BloomStat='advise', DissDat=None)
    before, _ = M.run(active, [], '2023-06-06T18:00:00Z')
    after, _ = M.run(doc, before, '2023-07-20T18:00:00Z')
    r = after[0]
    assert r['ended_at'] == '2023-07-14' and r['raw']['ended_at_precision'] == 'day'
    assert r['raw']['confirmation_method'] == 'visual'
    assert {'DissDat','IConfMet'} <= set(M.FIELDS.split(','))
    assert r['event_id'] == before[0]['event_id']
    again, _ = M.run(doc, after, AT)
    assert len(again) == 1 and again[0]['ended_at'] == r['ended_at']


def test_missouri_dissipation_while_still_shown_does_not_shorten_caution():
    doc = json.loads((FIX / 'lifts/mo.json').read_text())
    doc['features'][0]['attributes']['BloomStat'] = 'advise'
    rows, _ = M.run(doc, [], '2023-07-20T18:00:00Z')
    assert rows[0]['ended_at'] is None and rows[0]['status'] == 'advisory_active'
    assert rows[0]['raw']['dissolved_on'] == '2023-07-14'
    assert 'DissDat' in rows[0]['raw']['end_conflict']


def wi_features():
    return json.loads((FIX / 'wi/dnr_beach_layer.json').read_text())['layer']['features']


def test_wisconsin_source_end_matches_issued_start_and_conflict_stays_open():
    fs = wi_features()
    g = next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO'] == 474)
    g['ISSUED'] = '17-SEP-26 - 20-SEP-26'
    before, state, _ = W.records(fs, {}, AT)
    r = next(r for r in before if r['raw']['beach_seq_no'] == 474)
    assert r['ended_at'] is None and r['raw']['source_ended_at'] == '2026-09-20'
    assert 'Advisory' in r['advice_text'] and '20-SEP-26' in r['advice_text']
    g['BEACH_ACTION'] = 'End'
    after, _, _ = W.records(fs, state, AT)
    r = next(r for r in after if r['raw']['beach_seq_no'] == 474)
    assert r['ended_at'] == '2026-09-20' and r['raw']['ended_at_precision'] == 'day'
    assert r['event_id'] == next(r for r in before if r['raw']['beach_seq_no'] == 474)['event_id']


def test_wisconsin_ecoli_result_keeps_analyte_source_text_and_sample_date():
    fs = wi_features()
    g = next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO'] == 474)
    g['ECOLIVALUE'] = '>2400'  # field-shape variant; no unit claimed without source metadata
    rows, _, _ = W.records(W.safe_features(fs), {}, AT)
    r = next(r for r in rows if r['raw']['beach_seq_no'] == 474)
    result = r['raw']['sample_result']
    assert result['analyte'] == 'E. coli' and result['text'] == '>2400'
    assert result['sampled_at'] == r['raw']['last_sample_at'] and result['unit'] is None
    assert result['source_field'] == 'ECOLIVALUE'


def test_oregon_lift_older_than_retained_start_does_not_mark_new_episode_unlisted():
    sid = 'or-oha-hab-advisories'
    block, rows = generic(sid, FIX / 'lifts' / f'{sid}.json')
    active = dict(rows[0], AdvisoryStatus='Precaution', Issue_Date=1795248000000)  # Nov. 21
    before, _ = runner.build(sid, block, [active], AT, [])
    after, _ = runner.build(sid, block, rows, AT, before)
    assert len(after) == 1 and after[0]['ended_at'] is None
    assert '_unlisted_since' not in after[0]['raw']


def test_wisconsin_season_text_does_not_override_active_map_status_and_end():
    fs = wi_features()
    g = next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO'] == 474)
    g.update(BEACH_ACTION='End', STATUS='Closed for season', MAP_STATUS='Advisory', ISSUED='17-SEP-26 - 20-SEP-26')
    rows, _, _ = W.records(fs, {}, AT)
    r = next(r for r in rows if r['raw']['beach_seq_no'] == 474)
    assert r['status'] == 'advisory_active' and r['ended_at'] is None


@pytest.mark.parametrize('issued', ['18-SEP-26 - 20-SEP-26', '17-SEP-26 - 16-SEP-26', '17-SEP-26 - 20-DEC-26'])
def test_wisconsin_invalid_or_different_episode_end_is_not_used(issued):
    fs = wi_features()
    _, state, _ = W.records(fs, {}, AT)
    g = next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO'] == 474)
    g.update(BEACH_ACTION='End', ISSUED=issued)
    rows, _, _ = W.records(fs, state, AT)
    r = next(r for r in rows if r['raw']['beach_seq_no'] == 474)
    assert r['ended_at'] is None and r['status'] == 'advisory_active'
    assert r['raw']['unattributed_lift_evidence'][-1]['issued_text'] == issued


def test_missouri_late_dissipation_date_replaces_poll_end_of_same_episode():
    doc = json.loads((FIX / 'lifts/mo.json').read_text())
    active = copy.deepcopy(doc); active['features'][0]['attributes'].update(BloomStat='advise', DissDat=None)
    before, _ = M.run(active, [], '2023-06-06T18:00:00Z')
    without_date = copy.deepcopy(doc); without_date['features'][0]['attributes']['DissDat'] = None
    polled, _ = M.run(without_date, before, '2023-07-20T18:00:00Z')
    after, _ = M.run(doc, polled, AT)
    assert after[0]['ended_at'] == '2023-07-14'
    assert after[0]['raw']['end_observations'][-1]['ended_at'] == '2023-07-20T18:00:00Z'


def test_wisconsin_late_source_end_replaces_poll_end_with_same_issued_start():
    fs = wi_features()
    _, state, _ = W.records(fs, {}, AT)
    g = next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO'] == 474)
    g['BEACH_ACTION'] = 'End'
    _, state, _ = W.records(fs, state, AT)
    g['ISSUED'] = '17-SEP-26 - 20-SEP-26'
    rows, _, _ = W.records(fs, state, AT)
    r = next(r for r in rows if r['raw']['beach_seq_no'] == 474)
    assert r['ended_at'] == '2026-09-20'
    assert r['raw']['end_observations'][-1]['ended_at'] == AT


def test_wisconsin_reissue_after_source_day_end_is_a_separate_episode():
    fs = wi_features()
    _, state, _ = W.records(fs, {}, AT)
    g = next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO'] == 474)
    g.update(BEACH_ACTION='End', ISSUED='17-SEP-26 - 20-SEP-26')
    _, state, _ = W.records(fs, state, AT)
    g.update(BEACH_ACTION='Advisory', ISSUED='21-SEP-26 - ')
    rows, _, _ = W.records(fs, state, AT)
    rows = [r for r in rows if r['raw']['beach_seq_no'] == 474]
    assert len(rows) == 2
    assert {r['started_at'] for r in rows} == {'2026-09-17', '2026-09-21'}
    assert sum(r['status'] == 'advisory_active' for r in rows) == 1


def or_refreshes():
    from datetime import datetime
    sid = 'or-oha-hab-advisories'
    block, rows = generic(sid, FIX / 'lifts' / f'{sid}.json')
    held = []

    def refresh(issue, at, lifted=False):
        nonlocal held
        row = dict(rows[0], AdvisoryStatus='Advisory/Precaution Lifted' if lifted else 'Advisory',
                   Issue_Date=int(datetime.fromisoformat(issue).timestamp() * 1000)) if issue else None
        held, _ = runner.build(sid, block, [row] if row else [], at, held)
        return copy.deepcopy(held)
    return refresh


def test_review_ky_warning_with_end_remains_open_across_refreshes():
    sid = 'ky-dow-hab-viewer'
    block, rows = generic(sid, FIX / 'ky_dow_hab.json')
    active = rows[-1]
    before, _ = runner.build(sid, block, [active], '2026-11-14T12:00:00Z', [])
    conflict = dict(active, HABSTATUS='Warning', HABEND=1794960000000)
    for at in [AT, '2026-11-23T18:00:00Z']:
        before, _ = runner.build(sid, block, [conflict], at, before)
        r = before[0]
        assert r['status'] == 'advisory_active' and r['ended_at'] is None
        assert r['raw']['source_ended_at'] == '2026-11-18'
        assert 'Warning' in r['advice_text'] and 'HABEND' in r['advice_text'] and '2026-11-18' in r['advice_text']


def test_review_or_old_lift_with_retained_predecessor_keeps_new_episode_open():
    refresh = or_refreshes()
    old = refresh('2026-08-19T00:00:00-07:00', '2026-08-20T18:00:00Z')[0]
    refresh('2026-11-19T00:00:00-08:00', '2026-11-19T18:00:00Z', True)
    refresh('2026-11-21T00:00:00-08:00', '2026-11-21T18:00:00Z')
    for at in [AT, '2026-11-23T18:00:00Z']:
        rows = refresh('2026-11-19T00:00:00-08:00', at, True)
        new = next(r for r in rows if r['event_id'] != old['event_id'])
        assert new['ended_at'] is None and '_unlisted_since' not in new['raw']
        assert new['raw']['lift_evidence']['row']['AdvisoryStatus'] == 'Advisory/Precaution Lifted'


def test_review_or_earlier_time_on_same_day_is_not_a_lift():
    refresh = or_refreshes()
    refresh('2026-11-19T12:00:00-08:00', '2026-11-19T21:00:00Z')
    for at in [AT, '2026-11-23T18:00:00Z']:
        r = refresh('2026-11-19T09:00:00-08:00', at, True)[0]
        assert r['ended_at'] is None and r['status'] == 'advisory_active'
        assert '_unlisted_since' not in r['raw'] and r['raw']['lift_evidence']


def test_review_or_unlisted_history_is_not_resurrected_by_new_lift():
    refresh = or_refreshes()
    old = refresh('2026-08-19T00:00:00-07:00', '2026-08-20T18:00:00Z')[0]
    missing = refresh(None, '2026-10-01T18:00:00Z')[0]
    refresh('2026-11-01T00:00:00-07:00', '2026-11-02T18:00:00Z')
    for at in [AT, '2026-11-23T18:00:00Z']:
        rows = refresh('2026-11-19T00:00:00-08:00', at, True)
        historical = next(r for r in rows if r['event_id'] == old['event_id'])
        new = next(r for r in rows if r['event_id'] != old['event_id'])
        assert historical['raw']['_unlisted_since'] == missing['raw']['_unlisted_since']
        assert historical['raw']['_last_seen_in_source'] == old['raw']['_last_seen_in_source']
        assert new['ended_at'][:10] == '2026-11-19'


def test_review_or_corrected_lift_replaces_end_and_keeps_previous_row():
    refresh = or_refreshes()
    refresh('2026-08-19T00:00:00-07:00', '2026-08-20T18:00:00Z')
    old = refresh('2026-11-19T00:00:00-08:00', '2026-11-19T18:00:00Z', True)[0]
    revised = refresh('2026-11-20T00:00:00-08:00', AT, True)[0]
    assert revised['ended_at'][:10] == '2026-11-20'
    assert revised['event_id'] == old['event_id']
    history = revised['raw']['end_observations']
    assert history[-1]['ended_at'] == old['ended_at'] and history[-1]['row'] == old['raw']['row']
    assert refresh('2026-11-20T00:00:00-08:00', '2026-11-23T18:00:00Z', True)[0]['raw']['end_observations'] == history


def wi_sequence():
    fs = wi_features()
    a = next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO'] == 474)
    state = {}

    def refresh(at, **changes):
        nonlocal state
        a.update(changes)
        rows, state, _ = W.records(fs, state, at)
        return [r for r in rows if r['raw']['beach_seq_no'] == 474]
    return refresh


def test_review_wi_second_lift_with_reused_issue_date_never_rewrites_predecessor():
    refresh = wi_sequence()
    first = refresh('2026-09-18T18:00:00Z')[0]
    refresh('2026-09-21T18:00:00Z', BEACH_ACTION='End', ISSUED='17-SEP-26 - 20-SEP-26')
    refresh('2026-10-01T18:00:00Z', BEACH_ACTION='Advisory', ISSUED='17-SEP-26 - ')
    for at in ['2026-10-06T18:00:00Z', '2026-10-07T18:00:00Z']:
        rows = refresh(at, BEACH_ACTION='End', ISSUED='17-SEP-26 - 05-OCT-26')
        old = next(r for r in rows if r['event_id'] == first['event_id'])
        new = next(r for r in rows if r['event_id'] != first['event_id'])
        assert old['ended_at'] == '2026-09-20'
        assert new['started_at'] == '2026-10-01T18:00:00Z' and new['ended_at'] == '2026-10-05'


@pytest.mark.parametrize('changes', [dict(BEACH_ACTION='Closed'), dict(STATUS='E. coli')])
def test_review_wi_active_transition_never_consumes_contradictory_end(changes):
    refresh = wi_sequence()
    first = refresh('2026-09-18T18:00:00Z')[0]
    for at in ['2026-09-22T18:00:00Z', '2026-09-23T18:00:00Z']:
        rows = refresh(at, ISSUED='17-SEP-26 - 20-SEP-26', **changes)
        old = next(r for r in rows if r['event_id'] == first['event_id'])
        new = next(r for r in rows if r['event_id'] != first['event_id'])
        assert old['ended_at'] == '2026-09-22T18:00:00Z' and old['raw']['ended_at_precision'] == 'poll'
        assert new['ended_at'] is None and new['raw']['source_ended_at'] == '2026-09-20'
        assert old['raw']['unattributed_lift_evidence'][-1]['issued_text'] == '17-SEP-26 - 20-SEP-26'


def test_review_wi_replayed_old_end_does_not_close_returned_episode():
    refresh = wi_sequence()
    refresh('2026-09-18T18:00:00Z')
    refresh('2026-09-21T18:00:00Z', BEACH_ACTION='End', ISSUED='17-SEP-26 - 20-SEP-26')
    refresh('2026-10-01T18:00:00Z', BEACH_ACTION='Advisory', ISSUED='17-SEP-26 - ')
    for at in ['2026-10-02T18:00:00Z', '2026-10-03T18:00:00Z']:
        rows = refresh(at, BEACH_ACTION='End', ISSUED='17-SEP-26 - 20-SEP-26')
        new = next(r for r in rows if r['started_at'] == '2026-10-01T18:00:00Z')
        assert new['ended_at'] is None and new['raw']['unattributed_lift_evidence']


def test_review_or_revision_after_unlisting_keeps_unattributed_evidence():
    refresh = or_refreshes()
    refresh('2026-08-19T00:00:00-07:00', '2026-08-20T18:00:00Z')
    ended = refresh('2026-09-19T00:00:00-07:00', '2026-09-20T18:00:00Z', True)[0]
    missing = refresh(None, '2026-10-01T18:00:00Z')[0]
    revised = refresh('2026-11-20T00:00:00-08:00', AT, True)[0]
    assert revised['ended_at'] == ended['ended_at']
    assert revised['raw']['_unlisted_since'] == missing['raw']['_unlisted_since']
    assert revised['raw']['_last_seen_in_source'] == ended['raw']['_last_seen_in_source']
    assert revised['raw']['lift_evidence']['row']['Issue_Date'] != ended['raw']['row']['Issue_Date']


def test_review_wi_day_end_compares_with_local_return_day():
    refresh = wi_sequence()
    refresh('2026-09-18T18:00:00Z')
    refresh('2026-09-21T18:00:00Z', BEACH_ACTION='End', ISSUED='17-SEP-26 - 20-SEP-26')
    # 11 p.m. Oct. 1 in Wisconsin: the day-only Oct. 1 end can belong to this return.
    refresh('2026-10-02T04:00:00Z', BEACH_ACTION='Advisory', ISSUED='17-SEP-26 - ')
    rows = refresh('2026-10-03T18:00:00Z', BEACH_ACTION='End', ISSUED='17-SEP-26 - 01-OCT-26')
    new = next(r for r in rows if r['started_at'] == '2026-10-02T04:00:00Z')
    assert new['ended_at'] == '2026-10-01'


@pytest.mark.parametrize('change', [dict(_x=-122.0), dict(WaterbodyName='Another Lake')])
def test_review_or_lift_with_changed_identity_stays_unattributed(change):
    sid = 'or-oha-hab-advisories'
    block, rows = generic(sid, FIX / 'lifts' / f'{sid}.json')
    active = dict(rows[0], AdvisoryStatus='Advisory', Issue_Date=1787122800000)
    held, _ = runner.build(sid, block, [active], '2026-08-20T18:00:00Z', [])
    for at in [AT, '2026-11-23T18:00:00Z']:
        held, _ = runner.build(sid, block, [dict(rows[0], **change)], at, held)
        assert held[0]['ended_at'] is None and '_unlisted_since' not in held[0]['raw']
        assert held[0]['raw']['lift_evidence']['row'].items() >= change.items()


def test_review_wi_closed_season_text_cannot_consume_end_of_retained_advisory():
    refresh = wi_sequence()
    refresh('2026-09-18T18:00:00Z')
    for at in ['2026-09-22T18:00:00Z', '2026-09-23T18:00:00Z']:
        rows = refresh(at, BEACH_ACTION='Closed', STATUS='Closed for season', ISSUED='17-SEP-26 - 20-SEP-26')
        assert rows[0]['ended_at'] is None and rows[0]['raw']['unattributed_lift_evidence']


@pytest.mark.parametrize('start,end,expected', [
    ('2026-11-01T01:45:00-07:00', '2026-11-01T01:30:00-08:00', True),  # fall-back: later instant
    ('2026-11-01T01:30:00-08:00', '2026-11-01T01:45:00-07:00', False),
    ('2026-11-19T12:00:00-08:00', '2026-11-19T00:00:00-08:00', True),  # day-only lift
])
def test_review_or_timed_offsets_and_day_precision(start, end, expected):
    refresh = or_refreshes()
    refresh(start, '2026-11-20T18:00:00Z')
    for at in [AT, '2026-11-23T18:00:00Z']:
        r = refresh(end, at, True)[0]
        assert bool(r['ended_at']) == expected
        if not expected:
            assert '_unlisted_since' not in r['raw'] and r['raw']['lift_evidence']


def test_review_or_changed_lift_cannot_jump_across_return():
    refresh = or_refreshes()
    first = refresh('2026-08-19T00:00:00-07:00', '2026-08-20T18:00:00Z')[0]
    ended = refresh('2026-11-19T00:00:00-08:00', '2026-11-19T18:00:00Z', True)[0]
    refresh('2026-11-21T00:00:00-08:00', '2026-11-21T18:00:00Z')
    for at in ['2026-11-23T18:00:00Z', '2026-11-24T18:00:00Z']:
        rows = refresh('2026-11-22T00:00:00-08:00', at, True)
        old = next(r for r in rows if r['event_id'] == first['event_id'])
        new = next(r for r in rows if r['event_id'] != first['event_id'])
        assert old['ended_at'] == ended['ended_at']
        assert new['ended_at'] is None and '_unlisted_since' not in new['raw']
        assert new['raw']['lift_evidence']


def test_review_or_observed_absence_and_same_issue_return_is_not_crossed():
    refresh = or_refreshes()
    refresh('2026-08-19T00:00:00-07:00', '2026-08-20T18:00:00Z')
    refresh(None, '2026-10-01T18:00:00Z')
    back = refresh('2026-08-19T00:00:00-07:00', '2026-11-01T18:00:00Z')[0]
    for at in [AT, '2026-11-23T18:00:00Z']:
        r = refresh('2026-11-19T00:00:00-08:00', at, True)[0]
        assert r['ended_at'] is None and r['raw']['_absences'] == back['raw']['_absences']
        assert r['raw']['lift_evidence'] and '_unlisted_since' not in r['raw']
