"""Real agency rows trimmed; street numbers removed and source points rounded to 100 m."""
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from ingest import tx_houston_sso_monthly as H
from tests.test_ingest_tx_houston_sso import recs, tceq_rec

FEATURES = json.loads((Path(__file__).parent / 'fixtures/tx_houston_history.json').read_text())
AT = '2026-11-22T20:00:00Z'


def history(features=FEATURES):
    return {'features': copy.deepcopy(features), 'read_at': AT, 'last_edit': 1795013740967}


def test_exact_identity_enriches_without_replacing_monthly_fields_or_tceq_link():
    r = recs('2026-09')['68784']
    old = copy.deepcopy(r)
    out = H.enrich_history([r], history(), {'67077': {}})
    r = next(r for r in out if r['source_record_id'] == '68784')
    assert r['event_id'] == old['event_id']
    assert (r['lat'], r['lon'], r['coord_precision_m']) == (29.737, -95.395, 100)
    for k in ['started_at','ended_at','volume_gal','published_at','source_url']:
        assert r[k] == old[k]
    assert r['raw']['history']['attributes']['EXCURSIONID'] == 68784
    assert r['raw']['history']['fetched_at'] == AT
    tq = [tceq_rec('1', '2026-09-10', ['WQ0010495003'], 567,
                   'Manhole at [house number removed] Graustark St', water='Brays Bayou')]
    assert H.link_tceq([r], tq)['linked'] == 1
    assert tq[0]['duplicate_of'] == old['event_id']
    assert r['waterbody_text'] == 'Brays Bayou'
    assert H.link_tceq([r], tq)['linked'] == 1
    assert not any(r['source_record_id']=='67077' for r in out)


def test_new_rows_share_source_and_decode_separate_epoch_clocks_in_central_time():
    out = {r['source_record_id']:r for r in H.enrich_history([],history(),{})}
    assert out['57707']['started_at']=='2024-01-29T08:25:00-06:00'
    assert out['68784']['started_at']=='2026-09-10T09:33:00-05:00'
    assert out['68784']['ended_at']=='2026-09-10T12:15:00-05:00'
    assert out['68784']['volume_gal']==567  # source's figure, not 4 * 162 = 648
    assert out['68966']['ended_at']=='2026-10-01T10:55:00-05:00'
    assert out['68977']['volume_gal'] is None
    assert out['1075']['ended_at'] is None
    assert out['1075']['discharger_id'] is None
    assert out['1075']['raw']['system']=='Private System'
    assert all(r['source_id']==H.SOURCE_ID and r['published_at'] is None for r in out.values())


def test_date_only_missing_end_and_dst_ambiguity_never_invent_instants():
    f=copy.deepcopy(FEATURES[-1])
    a=f['attributes']
    a.update(EXCURSIONID=99999,STARTDATE=1790744400000,STARTTIME=None,
             ENDDATE=1790830800000,ENDTIME=None,TOTALVOLLOST=None,GPM=3,DURATION=20)
    r=H.enrich_history([],history([f]),{})[0]
    assert r['started_at']=='2026-09-30' and r['time_precision']=='day'
    assert r['ended_at']=='2026-10-01' and r['raw']['ended_at_precision']=='day'
    assert r['volume_gal'] is None
    a.update(ENDDATE=None,ENDTIME=None)
    assert H.enrich_history([],history([f]),{})[0]['ended_at'] is None
    a.update(STARTDATE=int(datetime(2026,11,1,5,tzinfo=UTC).timestamp()*1000),
             STARTTIME=int(datetime(1899,12,30,7,30,tzinfo=UTC).timestamp()*1000))
    r=H.enrich_history([],history([f]),{})[0]
    assert r['started_at']=='2026-11-01' and r['time_precision']=='day'


class Response:
    def __init__(self,d):self.d=d
    def json(self):return self.d
    def raise_for_status(self):pass


def getter(pages, count=3):
    calls=[]
    def get(url):
        q=parse_qs(urlsplit(url).query);calls.append(q)
        if '/query?' not in url:
            return Response({'fields':[{'name':k} for k in H.HISTORY_FIELDS], 'maxRecordCount':2,
                             'advancedQueryCapabilities':{'supportsPagination':True},
                             'editingInfo':{'lastEditDate':123}})
        if q.get('returnCountOnly')==['true']:return Response({'count':count})
        return Response(pages[int(q['resultOffset'][0])//2])
    return get,calls


def test_complete_paging_safe_geometry_and_cache():
    fs=copy.deepcopy(FEATURES[:3])
    for i,f in enumerate(fs):f['attributes']['OBJECTID']=i+1
    fs[0]['attributes']['ACTION']='unrequested private text'
    fs[0]['geometry']={'x':-95.394789,'y':29.736999}
    get,calls=getter([{'features':fs[:2],'exceededTransferLimit':True},{'features':fs[2:]}])
    h=H.read_history({},AT,get)
    assert len(h['features'])==3
    assert 'ACTION' not in h['features'][0]['attributes']
    assert h['features'][0]['geometry']=={'x':-95.395,'y':29.737}
    assert [q['resultOffset'][0] for q in calls if 'resultOffset' in q]==['0','2']
    assert all(q['outSR']==['4326'] and '*' not in q['outFields'][0] for q in calls if 'outFields' in q)
    calls.clear()
    assert H.read_history(h,AT,get)['features']==h['features']
    assert len(calls)==2


@pytest.mark.parametrize('pages,count',[
    ([{'features':FEATURES[:2],'exceededTransferLimit':True},{'features':FEATURES[:2]}],4),
    ([{'features':FEATURES[:2],'exceededTransferLimit':True},{'features':[]}],3),
    ([{'error':{'message':'private response'}}],3),
])
def test_incomplete_or_repeated_pages_fail_without_replacing_cache(pages,count):
    get,_=getter(pages,count)
    held = history()
    original = copy.deepcopy(held)
    with pytest.raises(H.ReadError):
        H.read_history(held, AT, get)
    assert held == original


@pytest.mark.parametrize('lost_state', [False, True])
def test_history_refresh_failure_keeps_enrichment_and_links_with_lost_state(tmp_path, lost_state):
    from tests.test_ingest_tx_houston_sso import _fake_pages
    out, st, tq = tmp_path/'ev.json', tmp_path/'st.json', tmp_path/'tq.json'
    notice = {'67077': {'noted_in': '2026-04', 'note': 'Entry voided by the City'}}
    out.write_text(json.dumps({'records': [], 'meta': {'voided': notice}}))
    tq.write_text(json.dumps({'records': [tceq_rec('1', '2026-09-10', ['WQ0010495003'], 567,
        'Manhole at [house number removed] Graustark St', water='Brays Bayou')]}))
    get, _ = combined_get()
    assert H.run(AT, st, out, get=get, tceq_path=tq, pages_of=_fake_pages) == 0
    before = {r['source_record_id']: r for r in json.loads(out.read_text())['records']}
    expected = {'1075', '57707', '68128', '68143', '68719', '68720', '68726',
                '68784', '68835', '68838', '68937', '68966', '68977'}
    assert set(before) == expected
    held = json.loads(st.read_text())['history']
    if lost_state:
        st.unlink()
    get, calls = combined_get(bad_second_page=True)
    # Force a later-page read rather than the unchanged cache path.
    if not lost_state:
        state = json.loads(st.read_text()); state['history']['last_edit'] = 0
        st.write_text(json.dumps(state))
        held = copy.deepcopy(state['history'])
    assert H.run('2026-11-23T20:00:00Z', st, out, get=get, tceq_path=tq, pages_of=_fake_pages) == 1
    assert [q['resultOffset'][0] for q in calls if 'resultOffset' in q] == ['0', '2']
    doc = json.loads(out.read_text())
    after = {r['source_record_id']: r for r in doc['records']}
    assert set(after) == expected
    assert doc['meta']['voided'] == notice
    for sid in expected:
        assert after[sid]['raw'].get('history') == before[sid]['raw'].get('history')
    if not lost_state:
        assert json.loads(st.read_text())['history'] == held
    assert after['68784']['raw']['_other_source_record'] == 'tx-tceq-sso-opendata:1'
    assert after['68784']['waterbody_text'] == 'Brays Bayou'
    assert json.loads(tq.read_text())['records'][0]['duplicate_of'] == after['68784']['event_id']
    assert doc['ok'] is False and doc['meta']['history']['error']


def test_disappeared_history_row_keeps_original_evidence_date():
    fs=copy.deepcopy(FEATURES[:2])
    old={'features':[dict(fs[0],fetched_at='2026-11-01T00:00:00Z',layer_updated_at='2026-10-31T00:00:00Z')]}
    get,_=getter([{'features':[fs[1]]}],1)
    h=H.read_history(old,AT,get)
    oldrow=next(r for r in H.enrich_history([],h,{}) if r['source_record_id']=='1075')
    assert oldrow['raw']['history']['fetched_at']=='2026-11-01T00:00:00Z'
    assert oldrow['raw']['history']['layer_updated_at']=='2026-10-31T00:00:00Z'
    assert oldrow['raw']['history']['missing_since']==AT


def test_conflicting_source_values_are_retained_without_overwriting_monthly_report():
    r=recs('2026-09')['68784']
    old=copy.deepcopy(r)
    f=copy.deepcopy(next(f for f in FEATURES if f['attributes']['EXCURSIONID']==68784))
    f['attributes'].update(TOTALVOLLOST=648, ENDTIME=-2209092300000)
    merged=H.enrich_history([r],history([f]),{})[0]
    assert merged['volume_gal']==old['volume_gal']==567
    assert merged['ended_at']==old['ended_at']
    assert merged['raw']['history']['attributes']['TOTALVOLLOST']==648


def test_missing_monthly_end_cannot_be_filled_before_its_reported_start():
    r=recs('2026-09')['68784']
    r['ended_at']=None
    r['status']='unknown'
    f=copy.deepcopy(next(f for f in FEATURES if f['attributes']['EXCURSIONID']==68784))
    f['attributes']['STARTDATE']-=86400000
    f['attributes']['ENDDATE']-=86400000
    merged=H.enrich_history([r],history([f]),{})[0]
    assert merged['ended_at'] is None
    assert merged['status']=='unknown'


def test_containment_is_distinct_from_proximity_and_never_names_a_water():
    f=copy.deepcopy(FEATURES[0])
    for flow,flag in [("Cont'd On Site - Not 5 ft",False),('Within 5 ft of B/SW/DD',None),
                      ("Storm Sewer - Not Cont'd",None)]:
        f['attributes']['FLOWLOCATION']=flow
        r=H.enrich_history([],history([f]),{})[0]
        assert r['raw'].get('reached_water') is flag
        assert r['waterbody_text'] is None


def combined_get(features=FEATURES, fail_pdfs=False, bad_second_page=False):
    from tests.test_ingest_tx_houston_sso import _get
    fs = copy.deepcopy(features)
    for i, f in enumerate(fs):
        f['attributes']['OBJECTID'] = i + 1
    pages = [{'features': fs[i:i+2]} for i in range(0, len(fs), 2)]
    if bad_second_page:
        pages[1] = {'error': {'message': 'unavailable'}}
    layer, calls = getter(pages, len(fs))
    pdf = _get([], fail=('2026-07', '2026-08', '2026-09') if fail_pdfs else ())
    def get(url, headers=None):
        return layer(url) if url.startswith(H.HISTORY_LAYER) else pdf(url, headers)
    return get, calls


def test_lost_state_successful_refresh_recovers_void_notices(tmp_path):
    from tests.test_ingest_tx_houston_sso import _fake_pages
    out, st = tmp_path/'ev.json', tmp_path/'st.json'
    notice = {'67077': {'noted_in': '2026-04', 'note': 'Entry voided by the City'}}
    out.write_text(json.dumps({'records': [], 'meta': {'voided': notice}}))
    get, _ = combined_get()
    assert H.run(AT, st, out, get=get, tceq_path=None, pages_of=_fake_pages) == 0
    doc = json.loads(out.read_text())
    assert '67077' not in {r['source_record_id'] for r in doc['records']}
    assert doc['meta']['voided'] == notice
    assert json.loads(st.read_text())['voided'] == notice
    out.unlink()
    H.run(AT, st, out, get=get, tceq_path=None, pages_of=_fake_pages)
    assert '67077' not in {r['source_record_id'] for r in json.loads(out.read_text())['records']}


def test_successful_history_is_published_when_all_monthly_pdfs_fail(tmp_path):
    out, st = tmp_path/'ev.json', tmp_path/'st.json'
    get, _ = combined_get(fail_pdfs=True)
    assert H.run(AT, st, out, get=get, tceq_path=None) == 1
    doc = json.loads(out.read_text())
    assert {r['source_record_id'] for r in doc['records']} == {H.history_id(f['attributes']) for f in FEATURES}
    assert doc['ok'] is False and doc['meta']['pending']


def test_retained_monthly_history_fields_follow_corrections_and_withdrawals():
    r = recs('2026-09')['68784']
    r.update(volume_gal=None, volume_text='Volume unknown', estimate_flag='unknown', ended_at=None, status='unknown')
    r['raw'].update(volume_as_written=0, volume_note='Monthly zero note', cause=None, end_note='Monthly end note')
    f = copy.deepcopy(next(f for f in FEATURES if H.history_id(f['attributes']) == '68784'))
    first = H.enrich_history([r], history([f]), {})[0]
    assert first['volume_gal'] == 567
    f['attributes'].update(TOTALVOLLOST=648, CAUSE='Debris', ENDTIME=-2209092300000)
    corrected = H.enrich_history([copy.deepcopy(first)], history([f]), {})[0]
    assert corrected['volume_gal'] == 648
    assert corrected['raw']['cause'] == 'Debris'
    assert corrected['ended_at'] == H.history_when(f['attributes'], 'END')[0]
    assert corrected['raw']['monthly_volume_note'] == 'Monthly zero note'
    assert corrected['raw']['monthly_volume_as_written'] == 0
    f['attributes'].update(TOTALVOLLOST=None, CAUSE=None, ENDDATE=None, ENDTIME=None)
    f['geometry'] = None
    withdrawn = H.enrich_history([corrected], history([f]), {})[0]
    assert withdrawn['volume_gal'] is None and withdrawn['ended_at'] is None
    assert withdrawn['status'] == 'unknown' and withdrawn['lat'] is None
    assert withdrawn['raw']['cause'] is None
    assert withdrawn['raw']['volume_note'] == 'Monthly zero note'
    assert withdrawn['raw']['end_note'] == 'Monthly end note'


def test_exact_tceq_reference_survives_scrubbing_and_links_without_operator():
    import yaml
    from ingest.generic import fieldmap as F
    block = yaml.safe_load((Path(__file__).parents[2]/'data/sources/tx-tceq-sso-opendata.yaml').read_text())['fetch']
    row, _ = F.safe_row({'incident_description': 'Houston SSO ID# 65766', 'incident_number': '451100'}, block)
    assert row['_houston_sso_ids'] == ['65766']
    f = copy.deepcopy(FEATURES[1]); f['attributes']['EXCURSIONID'] = 65766
    r = H.history_record(f, history([f]))
    t = tceq_rec('451100', r['started_at'][:10], [], r['volume_gal'], '')
    from ingest.generic import runner as R
    row.update(start_date=r['started_at'][:10], county='HARRIS', material_type='Sewage')
    built, _ = R.build(H.TCEQ_SOURCE, block, [row], AT, (), None)
    assert built[0]['raw']['houston_sso_ids'] == ['65766']
    t['raw']['houston_sso_ids'] = built[0]['raw']['houston_sso_ids']
    assert H.link_tceq([r], [t])['linked'] == 1
    assert t['duplicate_of'] == r['event_id'] and r['raw']['_other_source_record'] == t['event_id']
    assert r['discharger_id'] is None and r['discharger_name'] is None
    assert 'same City system' not in r['raw']['tceq_match']['basis']
    assert 'SSO history row' in t['raw']['_duplicate_basis']
    assert H.link_tceq([r], [t])['linked'] == 1


@pytest.mark.parametrize('conflict', ['day', 'volume', 'street', 'water', 'containment', 'other_id', 'ambiguous', 'permit', 'unreadable_street'])
def test_exact_tceq_reference_retains_conflict_checks(conflict):
    r = H.history_record(next(f for f in FEATURES if H.history_id(f['attributes']) == '68784'), history())
    t = tceq_rec('451100', r['started_at'][:10], [], r['volume_gal'], '')
    t['raw']['houston_sso_ids'] = ['68784']
    if conflict == 'day': t['started_at'] = '2020-01-01'
    if conflict == 'volume': t['volume_gal'] = 999999
    if conflict == 'street': t['outfall_name'] = '[house number removed] Alpine St'
    if conflict == 'water': r['waterbody_text'], t['waterbody_text'] = 'San Jacinto River', 'Brazos River'
    if conflict == 'containment': r['raw']['reached_water'], t['waterbody_text'] = False, 'Brays Bayou'
    if conflict == 'permit': r['raw']['tpdes_permit'] = 'WQ0014418001'
    if conflict == 'unreadable_street': t['outfall_name'] = '[house number removed] ;'
    if conflict == 'other_id': t['raw']['houston_sso_ids'] = ['65766']
    if conflict == 'ambiguous': t['raw']['houston_sso_ids'] = ['68784', '65766']
    assert H.link_tceq([r], [t])['linked'] == 0
    assert t['duplicate_of'] is None


def test_history_payload_keeps_citations_without_repeated_queries_or_time_prose():
    out = H.enrich_history([recs('2026-09')['68784']], history(), {})
    for r in out:
        raw = r['raw']; h = raw['history']
        assert 'time_basis' not in h
        if not raw.get('report_month'):
            assert 'timezone_note' not in raw
        assert not {'BASIN', 'WWTP', 'NOTOBSERVED', 'GPM'} & h['attributes'].keys()
        assert len(r['source_url']) < 220
        if raw.get('report_month'):
            assert h['url'] == H.HISTORY_LAYER
        else:
            assert 'url' not in h
        assert h['attributes']['EXCURSIONID'] == int(r['source_record_id'])


def test_tceq_unchanged_cache_must_refresh_when_reference_parser_changes(tmp_path, monkeypatch):
    from ingest.generic import runner as R, socrata
    _, block = R.load_source(H.TCEQ_SOURCE)
    block = {**block, 'meta': {**block.get('meta', {}), 'parser_version': 2}}
    out = tmp_path/'tceq.json'
    out.write_text(json.dumps({'ok': True, 'records': [tceq_rec('451100', '2025-12-23', [], 1, '')],
                              'meta': {'table_version': 'unchanged'}}))
    monkeypatch.setattr(socrata, 'current_version', lambda *args: 'unchanged')
    assert R.keep_unchanged(H.TCEQ_SOURCE, block, out, AT) is None


def test_explicit_reference_survives_safe_snapshot_reprocessing():
    from ingest.generic import fieldmap as F, runner as R
    _, block = R.load_source(H.TCEQ_SOURCE)
    row = {'incident_number': '451100', 'incident_description': 'SSO ID#65766',
           'start_date': '2025-12-23', 'county': 'HARRIS', 'material_type': 'Sewage'}
    safe, _ = F.safe_row(row, block)
    records, _ = R.build(H.TCEQ_SOURCE, block, [safe], AT, (), None)
    assert records[0]['raw']['houston_sso_ids'] == ['65766']


def test_cached_history_drops_unused_fields_without_changing_evidence_times():
    held = history()
    held.update(last_edit=123, current_count=len(FEATURES), parser_version=H.HISTORY_VERSION)
    for f in held['features']:
        f.update(fetched_at=AT, layer_updated_at='2026-11-18T00:00:00Z')
        f['attributes'].update(BASIN='unused', WWTP='unused', NOTOBSERVED='unused', GPM=4)
    get, calls = getter([], len(FEATURES))
    refreshed = H.read_history(held, '2026-11-23T00:00:00Z', get)
    assert len(calls) == 2
    for f in refreshed['features']:
        assert not {'BASIN', 'WWTP', 'NOTOBSERVED', 'GPM'} & f['attributes'].keys()
        assert f['fetched_at'] == AT and f['layer_updated_at'] == '2026-11-18T00:00:00Z'


def test_reproduction_query_template_accepts_record_id(tmp_path):
    from tests.test_ingest_tx_houston_sso import _fake_pages
    get, _ = combined_get()
    out = tmp_path/'events.json'
    H.run(AT, tmp_path/'state.json', out, get=get, tceq_path=None, pages_of=_fake_pages)
    template = json.loads(out.read_text())['meta']['history']['query_template']
    assert parse_qs(urlsplit(template.format(source_record_id='68784')).query)['where'] == ['EXCURSIONID=68784']
