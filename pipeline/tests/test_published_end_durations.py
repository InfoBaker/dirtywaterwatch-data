"""Live CT/WA records and existing NEORSD fixtures; altered edge cases are stated explicitly."""
import copy
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from build import status as S
from export import build as B, csv as C, detail as D, estimates as E

FIX = Path(__file__).parent / 'fixtures' / 'published_end_durations.json'


def records(source):
    return [r for r in json.loads(FIX.read_text())['records'] if r['source_id'] == source]


@pytest.mark.parametrize('index,field', [(0,'DURATION'),(2,'CSO_DURATION')])
def test_ct_duration_is_source_detail_and_a_published_end_wins(index, field):
    r = records('ct-deep-archive')[index]
    before = copy.deepcopy(r)
    D.enrich([r])
    assert r['detail']['duration_text'] == f"{r['raw'][field]} hours"
    assert 'end_estimate' not in r
    assert r['ended_at'] == before['ended_at'] and r['raw'] == before['raw']


@pytest.mark.parametrize('index,field,stop', [(0,'DURATION','STOP_DATETIME'),(2,'CSO_DURATION','STOP_FLOW_DATETIME')])
def test_ct_missing_end_variant_gets_only_our_estimate(index, field, stop):
    # The real records give ends. Remove both copies to test a later publication without an end.
    r = records('ct-deep-archive')[index]
    r['ended_at'] = r['raw'][stop] = None
    r['status'] = 'unknown'
    estimate = E.end_estimate_of(r)
    expected = datetime.fromisoformat(r['started_at']) + timedelta(hours=r['raw'][field])
    assert estimate['at'] == expected.isoformat(timespec='seconds')
    assert estimate['formula'] == 'start + stated duration'
    assert estimate['inputs']['duration_field'] == field
    assert estimate['inputs']['source_url'] == r['source_url']
    assert estimate['inputs']['duration_field_unit'] == 'hours'
    assert estimate['basis'].startswith('We added')
    assert r['ended_at'] is None and r['status'] == 'unknown'


def test_real_ct_missing_ends_have_zero_duration_and_get_no_estimate():
    for r in records('ct-deep-archive'):
        if not r['ended_at']:
            assert E.end_estimate_of(r) is None


def test_wa_real_missing_end_gets_our_estimate_without_changing_the_caution():
    r = records('wa-ecology-sewage-spills')[0]
    before = copy.deepcopy(r)
    D.enrich([r])
    assert r['detail']['duration_text'] == '1.5 hours'
    assert r['end_estimate']['at'] == '2026-07-30T22:45:00-07:00'
    assert r['end_estimate']['inputs']['duration_field'] == 'row.final_event_duration_hours'
    assert r['end_estimate']['inputs']['duration_value'] == '1.5 hours'
    assert r['ended_at'] is None and r['status'] == before['status']
    at = datetime.fromisoformat(r['started_at']) + timedelta(days=1)
    assert S._event_intervals(r, 'WA', at, None, S.load_rules()) == S._event_intervals(before, 'WA', at, None, S.load_rules())


@pytest.mark.parametrize('value', ['Unknown/Not Reported','ongoing','Intermittent 2 hours','2-4 hours','0','-1','NaN','744.1'])
def test_wa_unusable_duration_does_not_invent_an_end(value):
    r = records('wa-ecology-sewage-spills')[0]
    r['raw']['row']['final_event_duration_hours'] = value
    assert E.end_estimate_of(r) is None


@pytest.mark.parametrize('value', ['1.5', 'about 1.5 hours', 'est. 1.5 hours'])
def test_wa_numeric_hours_and_qualified_words_keep_the_source_input(value):
    r = records('wa-ecology-sewage-spills')[0]
    r['raw']['row']['final_event_duration_hours'] = value
    estimate = E.end_estimate_of(r)
    assert estimate['at'] == '2026-07-30T22:45:00-07:00'
    assert estimate['inputs']['duration_value'] == value


def test_stated_or_rejected_end_and_intermittent_flow_are_not_replaced():
    r = records('wa-ecology-sewage-spills')[0]
    for changes in ({'end_event_timedate':1}, {'was_the_spill_continuous':'Intermittent'}):
        variant = copy.deepcopy(r); variant['raw']['row'].update(changes)
        assert E.end_estimate_of(variant) is None
    r['raw']['_start_at_midnight'] = 'the source may give only a day'
    assert E.end_estimate_of(r) is None
    for r in records('ct-deep-archive'):
        if r['ended_at']:
            r['ended_at'] = None  # rejected end still supplied in raw: not a missing source end
            assert E.end_estimate_of(r) is None


def test_neorsd_duration_is_exported_but_never_supplies_an_end():
    for r in records('oh-neorsd-cso-notification-map'):
        D.enrich([r])
        assert r['detail']['duration_text'] == f"{r['raw']['duration_h']} hours"
        assert 'end_estimate' not in r
        r['ended_at'] = None  # a missing-end variant still cannot use the shorter duration
        assert E.end_estimate_of(r) is None


def test_full_compact_and_csv_keep_duration_and_estimate_apart(tmp_path, monkeypatch):
    monkeypatch.setattr(S, '_STATES', {'CT','WA','OH'})
    rows = records('ct-deep-archive') + records('wa-ecology-sewage-spills') + records('oh-neorsd-cso-notification-map')
    for r in rows:
        r.update(state={'ct-deep-archive':'CT','wa-ecology-sewage-spills':'WA','oh-neorsd-cso-notification-map':'OH'}[r['source_id']], fixture=False, water_slugs=[])
    D.enrich(rows)
    C.write_csvs(rows, [], [], tmp_path, page_ids=set())
    got = {}
    for state in ('ct','wa','oh'):
        with (tmp_path/'state'/f'{state}.csv').open() as f:
            got.update({r['event_id']:r for r in csv.DictReader(f)})
    for r in rows:
        row = got[r['event_id']]
        slim = B.slim_event(r)
        assert row['duration_text'] == r.get('detail',{}).get('duration_text','')
        assert slim.get('detail',{}).get('duration_text') == r.get('detail',{}).get('duration_text')
        assert row['end_reported'] == ('true' if r['ended_at'] else 'false')
        if r['event_id'].endswith('36d2083f-5455-45cb-8d63-87148e218ea9'):
            assert row['end_estimate_at'] == slim['end_estimate']['at'] == r['end_estimate']['at']
            assert row['end_estimate_basis'].startswith('We added')
            assert row['ended_at'] == '' and 'inputs' not in slim['end_estimate']


@pytest.mark.parametrize('source,path', [('ct-deep-archive','DURATION'),
                                       ('oh-neorsd-cso-notification-map','duration_h'),
                                       ('wa-ecology-sewage-spills','final_event_duration_hours')])
def test_units_we_append_use_the_singular_but_source_words_stay_as_written(source, path):
    r = records(source)[0]
    raw = r['raw'].get('row',r['raw'])
    raw[path] = 1
    assert D.detail_of(r)['duration_text'] == '1 hour'
    raw[path] = '1 hours'  # source wording is not ours to edit
    assert D.detail_of(r)['duration_text'] == '1 hours'
