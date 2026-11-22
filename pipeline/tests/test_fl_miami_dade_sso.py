"""Trimmed agency records: county identity, clocks, privacy and linked DEP notices."""
import copy
import json
from pathlib import Path

import pytest
import requests
from ingest import fl_miami_dade_sso as M

FIX = Path(__file__).parent / 'fixtures' / 'fl_miami_dade_sso.json'
AT = '2026-11-22T12:00:00Z'

def rows(): return json.loads(FIX.read_text())['county']
def records(): return M.build(rows(), AT, [])[0]
def local(): return next(r for r in records() if r['raw']['TRACKNUM'] == '597571')
def pnp():
    from ingest import fl_dep_pnp as P
    return P.build(json.loads(FIX.read_text())['pnp'], AT, [], permits={})[0]


def test_real_identity_times_volume_and_cause():
    r = local()
    assert r['source_record_id'] == '20261106100459783383'
    assert r['started_at'] == '2026-11-03T13:25:00-05:00'
    assert r['ended_at'] == '2026-11-03T14:40:00-05:00'
    assert r['time_precision'] == r['raw']['ended_at_precision'] == 'minute'
    assert r['volume_gal'] == 72917 and r['raw']['ESTGALRECOVER'] == 59840
    assert r['estimate_flag'] == 'estimated'
    assert r['raw']['DISCHARGECAUSE'] == 'CONTRACTOR' and r['raw']['DISCCAUSECAT'] == 'FM'
    assert r['published_at'] is None and r['reported_at'] is None
    assert r['source_updated_at'] == '2026-11-06T12:03:56-05:00' and r['fetched_at'] == AT
    assert 'INCIDENTID' in r['source_url'] and '*' not in r['source_url']


def test_objectid_changes_do_not_change_identity():
    a = rows()[0]
    assert M.to_record(a, AT)['event_id'] == M.to_record({**a, 'OBJECTID': 99999}, AT)['event_id']


def test_midnight_precision_and_incident_date_fallback():
    a = rows()[0]; a.update(STARTDATE=None, STOPDATE=a['INCDNTDATE'])
    r = M.to_record(a, AT)
    assert r['time_precision'] == r['raw']['ended_at_precision'] == 'day'
    assert r['raw']['_start_basis'] == 'INCDNTDATE' and r['ended_at'] == r['started_at']


def test_summer_clock_recovered_never_subtracted():
    a = next(a for a in rows() if a['TRACKNUM'] == '590628')
    assert M.to_record(a, AT)['started_at'] == '2026-07-09T10:30:00-04:00'
    a['ESTGALRECOVER'] = 100
    assert M.to_record(a, AT)['volume_gal'] == 30


def test_bad_end_and_unparseable_record_are_kept():
    a = rows()[0]; a['STOPDATE'] = a['STARTDATE'] - 60000
    r = M.to_record(a, AT)
    assert r['ended_at'] is None and r['status'] == 'unknown' and r['parse_error']
    a.update(STARTDATE=None, INCDNTDATE=None, STOPDATE=None)
    r = M.to_record(a, AT)
    assert r['started_at'] is None and r['event_type'] == 'unknown'


def test_water_as_named_and_existing_generic_name_guard():
    from build.status import Resolver, named_water_only, no_water_flag
    r = local()
    assert r['waterbody_text'] == 'CANAL' and r['water_slugs'] == []
    assert named_water_only(r)
    waters = {'pine-canal-fl': {'slug':'pine-canal-fl','name':'Pine Canal','state':'FL','kind':'canal',
                              'bbox':[-80.17,25.68,-80.15,25.69],'lat':25.686,'lon':-80.162}}
    assert Resolver(waters, []).resolve(r)['water_slugs'] == []
    assert r['raw']['reached_water'] is True
    n = next(r for r in records() if r['raw']['TRACKNUM'] == '590628')
    assert n['raw']['reached_water'] is False and no_water_flag(n)
    assert next(r for r in records() if r['raw']['UTILITYNAME'] == 'HIALEAH')['waterbody_text'] == 'GRATIGNY CANAL'


def test_privacy_before_raw_save():
    a = rows()[0]
    a.update(RPTNAME='[private reporter]', RPTPHONE='[private phone]', HNUM='[house number]',
             ADDRESS='[private address]', CREATEDBY='[private staff]', SURFWATNAME='12345 NW 199th ST',
             UTILITYNAME='[private person]')
    r = M.to_record(a, AT)
    assert not {'RPTNAME','RPTPHONE','HNUM','ADDRESS','CREATEDBY'} & r['raw'].keys()
    assert '12345' not in json.dumps(r) and '[private person]' not in json.dumps(r)
    assert r['lat'] == round(a['LAT'], 3)


class Response:
    def __init__(self, doc): self.doc = doc
    def raise_for_status(self): pass
    def json(self): return self.doc
class Session:
    def __init__(self, docs): self.docs = iter(docs); self.calls = []
    def get(self, url, params, **kw):
        self.calls.append((url,params)); return Response(next(self.docs))
def meta():
    return {'fields':[{'name':k,'domain':None} for k in M.SAFE_FIELDS],
            'dateFieldsTimeReference':{'timeZone':'UTC'}, 'editingInfo':{'lastEditDate':1}}
def page(items, more=False):
    return {'features':[{'attributes':a} for a in items], 'exceededTransferLimit':more}


def test_paging_safe_fields_and_saved_response():
    a,b = rows()[:2]; a['OBJECTID'],b['OBJECTID'] = 1,2; a['RPTNAME'] = '[private reporter]'
    s = Session([meta(),{'count':2},page([a],True),page([b]),{'count':2},meta()])
    got,raw,_ = M.query_layer(s)
    assert len(got)==2 and 'RPTNAME' not in raw.decode()
    qs = [p for _,p in s.calls if 'outFields' in p]
    assert all('*' not in p['outFields'] for p in qs) and 'OBJECTID > 1' in qs[1]['where']


@pytest.mark.parametrize('failure',['short','duplicate','changed_count','changed_edit','missing_field'])
def test_incomplete_unstable_read_fails(failure):
    a,b = rows()[:2]; a['OBJECTID'],b['OBJECTID'] = 1,2
    m=meta()
    if failure=='missing_field': m['fields']=[]
    docs=[m,{'count':2}]
    if failure=='duplicate': docs += [page([a],True),page([a])]
    else:
        docs += [page([a] if failure=='short' else [a,b]), {'count':3 if failure=='changed_count' else 2},
                 {**meta(),'editingInfo':{'lastEditDate':2}} if failure=='changed_edit' else meta()]
    with pytest.raises((RuntimeError,ValueError)): M.query_layer(Session(docs))


def test_identity_links_one_event_both_citations_and_idempotence():
    from export.detail import links_of
    c,p = records(),pnp(); stats=M.link_pnp(c,p)
    r=next(r for r in c if r['raw']['TRACKNUM']=='597571')
    assert stats['county_linked']==1 and r['duplicate_of']==p[0]['event_id']
    assert r['event_id'] in p[0]['raw']['_other_source_record']
    assert any(x['event_id']==p[0]['event_id'] for x in links_of(c+p)[r['event_id']]['linked_records'])
    before=copy.deepcopy((c,p)); M.link_pnp(c,p); assert (c,p)==before


def test_two_dep_numbers_for_one_overflow_count_once():
    c,p=records(),pnp(); old=copy.deepcopy(p[0]); old['event_id']+='-other'
    old['reported_at']='2026-11-04T10:00:00-05:00'; p.append(old)
    M.link_pnp(c,p)
    r=next(r for r in c if r['raw']['TRACKNUM']=='597571')
    assert sum(not x['duplicate_of'] for x in [r]+p)==1


def test_proximity_date_alone_conflicts_and_ambiguity_do_not_link():
    c,p=records(),pnp(); p[0]['raw']['INCIDENT_REPORT']='A sewage overflow was reported.'; p[0]['volume_gal']=None
    assert M.link_pnp(c,p)['county_linked']==0
    p=pnp(); p[0]['started_at']='2026-11-04T00:00:00-05:00'
    assert M.link_pnp(c,p)['county_linked']==0
    p=pnp(); extra=copy.deepcopy(local()); extra['event_id']+='-different'; c.append(extra)
    assert M.link_pnp(c,p)['county_linked']==0


def test_missing_records_retained_first_seen_unchanged():
    before=records(); new,stats=M.build(rows()[:1],'2026-11-23T12:00:00Z',before)
    assert len(new)==len(before) and stats['kept_from_earlier_runs']==len(before)-1
    assert all(r['raw']['_first_seen_at']==AT for r in new)


def test_source_down_retains_and_relinks_after_dep_refresh(tmp_path,monkeypatch):
    from common import write_events
    target=tmp_path/(M.SOURCE_ID+'.json'); dep=tmp_path/'fl-dep-pnp.json'
    monkeypatch.setattr(M,'EVENTS_DIR',tmp_path)
    write_events(M.SOURCE_ID,records(),path=target); write_events('fl-dep-pnp',pnp(),path=dep)
    before=json.loads(target.read_text())
    monkeypatch.setattr(M,'query_layer',lambda s: (_ for _ in ()).throw(requests.ConnectionError('unavailable')))
    monkeypatch.setattr(M,'write_events',lambda sid,rs,**kw: write_events(sid,rs,path=target,**kw))
    assert M.main([])==1
    after=json.loads(target.read_text())
    assert not after['ok'] and after['last_ok_at']==before['last_ok_at']
    assert len(after['records'])==len(before['records'])
    assert {r['fetched_at'] for r in after['records']}=={AT}
    assert any(r['duplicate_of'] for r in after['records'])


def test_direct_state_notice_id_and_unique_volume_point_match():
    c = local()
    c['raw'].update(UTILITYNAME='HIALEAH', TRACKNUM='2026-11184')
    c['discharger_name']='HIALEAH'; c['discharger_id']=None
    p = pnp()[0]; p['raw']['INCIDENT_REPORT']='A sewage overflow was reported.'
    p['discharger_name']='City of Hialeah'; p['discharger_id']=None
    assert M.link_pnp([c],[p])['county_linked']==1
    assert 'notice numbers' in c['raw']['_miami_link_basis']
    c['raw']['TRACKNUM']=None
    p['volume_gal']=c['volume_gal']; p['lat'],p['lon']=c['lat'],c['lon']
    assert M.link_pnp([c],[p])['county_linked']==1
    assert 'estimated discharged gallons' in c['raw']['_miami_link_basis']
    p['discharger_name']='City of North Miami Beach'
    assert M.link_pnp([c],[p])['county_linked']==0 and c['duplicate_of'] is None


def test_links_clear_if_counterpart_removed_without_changing_health(tmp_path,monkeypatch):
    from common import write_events
    target=tmp_path/(M.SOURCE_ID+'.json'); dep=tmp_path/'fl-dep-pnp.json'
    monkeypatch.setattr(M,'EVENTS_DIR',tmp_path)
    write_events(M.SOURCE_ID,records(),path=target); write_events('fl-dep-pnp',pnp(),path=dep)
    M.link_only()
    before=json.loads(dep.read_text())
    target.unlink(); M.link_only()
    after=json.loads(dep.read_text())
    assert after['ok']==before['ok'] and after['fetched_at']==before['fetched_at']
    assert not any(r['raw'].get('_miami_linked_ids') for r in after['records'])


def test_numeric_missing_and_negative_values_do_not_become_totals():
    a=rows()[0]
    for v in (None,'unknown',-1,float('inf')):
        assert M.to_record({**a,'QUANDSCHRG':v},AT)['volume_gal'] is None
    assert M.to_record({**a,'QUANDSCHRG':0},AT)['volume_gal']==0


def test_same_day_date_only_end_preserves_source_precision():
    a=rows()[0]; a['STOPDATE']=a['INCDNTDATE']
    r=M.to_record(a,AT)
    assert r['ended_at'] is not None and r['raw']['ended_at_precision']=='day'
    assert r['status']=='ended'


def test_feed_is_discovered_by_makefile():
    assert '__name__ == "__main__"' in Path(M.__file__).read_text()
    assert 'not a feed' not in Path(M.__file__).read_text()


def test_source_stated_secondary_effluent_is_retained_raw_but_excluded_from_sewage():
    a=rows()[0]; a['WATDISCTYPE']='SECONDARY EFFLUENT'
    previous=M.to_record({**a,'WATDISCTYPE':'RAW SEWAGE'},AT)
    out,stats=M.build([a],AT,[previous])
    assert out==[] and stats['excluded_by_material']=={'SECONDARY EFFLUENT':1}
    assert M.safe_attributes(a)['WATDISCTYPE']=='SECONDARY EFFLUENT'
    r=M.to_record({**a,'WATDISCTYPE':'RAW SEWAGE'},AT)
    assert r['material']=='RAW SEWAGE'
