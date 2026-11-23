import json
from pathlib import Path
from export import detail as D, build as B, csv as C
from ingest import wi_dnr_beach_health as W, mo_dnr_hab as M

ROOT=Path(__file__).resolve().parents[2]
AT='2026-11-22T18:00:00Z'


def test_wi_detail_and_slim_keep_result_context_and_contradictory_end():
    fs=json.loads((ROOT/'pipeline/tests/fixtures/wi/dnr_beach_layer.json').read_text())['layer']['features']
    a=next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO']==474)
    a.update(ECOLIVALUE='12',ISSUED='17-SEP-26 - 20-SEP-26')
    rows,_,_=W.records(fs,{},AT)
    r=next(r for r in rows if r['raw']['beach_seq_no']==474)
    d=D.detail_of(r)
    assert d['sample_analyte']=='E. coli' and d['sample_result_text']=='12'
    assert d['source_end_date']=='2026-09-20' and d['source_end_text']=='20-SEP-26'
    assert d['source_status']=='Advisory; No Data Available'
    assert 'sample_unit' not in d
    r.update(detail=d,file='x')
    assert B.slim_event(r)['detail']==d
    ctx=C._Context([],[],{},C.SiteLinks([r], [], [], set(), as_of=AT))
    cells,_=C.event_row(r,ctx); result=dict(zip(C.COLUMNS,cells))
    assert len(cells)==len(C.COLUMNS)
    assert result['sample_result_text']=='12' and result['source_end_date']=='2026-09-20'
    assert result['ended_at']=='' and result['end_reported']=='false'


def test_mo_confirmation_and_poll_end_is_not_source_reported():
    doc=json.loads((ROOT/'pipeline/tests/fixtures/lifts/mo.json').read_text())
    doc['features'][0]['attributes']['BloomStat']='advise'
    rows,_=M.run(doc,[],AT)
    r=rows[0];r['detail']=D.detail_of(r)
    assert r['detail']['confirmation_method']=='visual'
    assert r['detail']['source_end_date']=='2023-07-14'
    ended,_=M.run({'features':[]},rows,'2026-11-23T18:00:00Z')
    r=ended[0]
    ctx=C._Context([],[],{},C.SiteLinks([r], [], [], set(), as_of=AT))
    cells,_=C.event_row(r,ctx)
    assert dict(zip(C.COLUMNS,cells))['end_reported']=='false'


def test_wi_completed_and_corrected_lifts_export_one_attributed_observation():
    fs=json.loads((ROOT/'pipeline/tests/fixtures/wi/dnr_beach_layer.json').read_text())['layer']['features']
    a=next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO']==474)
    _,state,_=W.records(fs,{},'2026-09-18T18:00:00Z')
    # First retain a contradictory source date alongside an active advisory.
    a['ISSUED']='17-SEP-26 - 19-SEP-26'
    _,state,_=W.records(fs,state,'2026-09-20T18:00:00Z')
    for day,text,at in [('2026-09-20','20-SEP-26','2026-09-21T18:00:00Z'),
                        ('2026-09-21','21-SEP-26','2026-09-22T18:00:00Z')]:
        a.update(BEACH_ACTION='End',ISSUED=f'17-SEP-26 - {text}')
        rows,state,_=W.records(fs,state,at)
        r=next(r for r in rows if r['raw']['beach_seq_no']==474)
        d=D.detail_of(r)
        assert r['ended_at']==day
        assert r['raw']['source_end_observation']['seen_at']==at
        assert d['source_end_date']==day and d['source_end_text']==text
        assert d['source_status']=='End; No Data Available'
        assert r['raw']['issued_end_text']=='19-SEP-26'  # earlier contradiction stays separate
        r.update(detail=d,file='x')
        assert B.slim_event(r)['detail']==d
        ctx=C._Context([],[],{},C.SiteLinks([r], [], [], set(), as_of=at))
        cells,_=C.event_row(r,ctx); exported=dict(zip(C.COLUMNS,cells))
        assert exported['source_end_date']==day and exported['source_end_text']==text
        assert exported['source_status']=='End; No Data Available' and exported['end_reported']=='true'
    assert r['raw']['end_observations'][-1]['ended_at']=='2026-09-20'


def test_wi_direct_completed_lift_exports_end_observation():
    fs=json.loads((ROOT/'pipeline/tests/fixtures/wi/dnr_beach_layer.json').read_text())['layer']['features']
    a=next(f['attributes'] for f in fs if f['attributes']['BEACH_SEQ_NO']==474)
    _,state,_=W.records(fs,{},'2026-09-18T18:00:00Z')
    a.update(BEACH_ACTION='End',ISSUED='17-SEP-26 - 20-SEP-26')
    for at in ['2026-09-21T18:00:00Z','2026-09-22T18:00:00Z']:
        rows,state,_=W.records(fs,state,at)
        r=next(r for r in rows if r['raw']['beach_seq_no']==474)
        d=D.detail_of(r)
        assert d.get('source_end_date')=='2026-09-20'
        assert d['source_end_text']=='20-SEP-26' and d['source_status']=='End; No Data Available'
