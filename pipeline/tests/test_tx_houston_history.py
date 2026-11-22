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
    with pytest.raises(H.ReadError):H.read_history({},AT,get)


def test_history_refresh_failure_keeps_enrichment_and_links_with_lost_state(tmp_path):
    from tests.test_ingest_tx_houston_sso import _get, _fake_pages
    out, st = tmp_path/'ev.json', tmp_path/'st.json'
    fs=copy.deepcopy(FEATURES)
    get_layer,_=getter([{'features':fs[:2],'exceededTransferLimit':True},
                        {'features':fs[2:4],'exceededTransferLimit':True}, {'features':fs[4:]}],len(fs))
    pdf_get=_get([])
    def get(url,headers=None):
        return get_layer(url) if url.startswith(H.HISTORY_LAYER) else pdf_get(url,headers)
    assert H.run(AT,st,out,get=get,tceq_path=None,pages_of=_fake_pages)==0
    before={r['source_record_id']:r for r in json.loads(out.read_text())['records']}
    assert before['68784']['lat']==29.737
    st.unlink()
    assert H.run(AT,st,out,get=_get([]),tceq_path=None,pages_of=_fake_pages)==1
    doc=json.loads(out.read_text())
    after={r['source_record_id']:r for r in doc['records']}
    assert set(before)<=set(after)
    assert after['68784']['lat']==29.737
    assert after['68784']['raw']['history']==before['68784']['raw']['history']
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
