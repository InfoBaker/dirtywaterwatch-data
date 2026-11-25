import csv
import json
from pathlib import Path
from export import build as B, detail as D, csv as C
from ingest import mt_deq_hab_map as M, id_deq_cyanohab as I, de_dnrec_recwater as DE, fl_doh_beaches as F
from test_receiving_water_results import fixture, FIX, AT


def csv_row(rec, tmp_path):
    C.write_csvs([rec], [], [], tmp_path, page_ids=set())
    paths=list(tmp_path.glob('all-reports-*.csv'))
    assert len(paths)==1
    with paths[0].open() as f:return list(csv.DictReader(f))[0]


def test_montana_typed_result_survives_detail_compact_and_csv(tmp_path):
    rec=M.build(fixture('mt-density.json'), AT)[0][0]
    D.enrich([rec])
    result=rec['detail']['sample_results'][0]
    assert result['analyte']=='Cyanobacteria' and result['value'] is None and result['units'] is None
    assert result['source_record_id']==rec['source_record_id'] and result['observed_at']==AT
    assert B.slim_event(rec)['detail']['sample_results']==[result]
    assert json.loads(csv_row(rec,tmp_path)['sample_results_json'])==[result]


def test_idaho_toxin_and_release_survive_detail_compact_and_csv(tmp_path):
    rows=I.parse_table((FIX/'id/cyanohab-table.html').read_text())
    state=I.update({},rows,AT,I.parse_layer(fixture('id-layer.json')))
    rec=next(r for r in I.records(state) if r['raw'].get('waterbody_as_listed')=='Hordemann Pond')
    D.enrich([rec]); d=rec['detail']
    assert d['toxin']=='Microcystins' and d['release_url']==I.URL
    assert d['result_source_url']==I.LAYER and d['result_observed_at']==AT
    assert B.slim_event(rec)['detail']['toxin']=='Microcystins'
    row=csv_row(rec,tmp_path)
    assert row['toxin']==d['toxin'] and row['release_url']==I.URL


def test_florida_real_registry_alias_does_not_change_episode_dates(tmp_path):
    from test_fl_doh_beaches import POINT,PAGE
    rec=F.build([POINT],{F.point_key(POINT):PAGE},[],AT)[0][0]
    assert rec['waterbody_text']=='Gulf Of America'
    assert rec['outfall_name']=='8TH STREET'
    assert rec['ended_at']=='2026-10-30T00:00:00-05:00'
    assert csv_row(rec,tmp_path)['water']=='Gulf Of America'
    assert B.slim_event(rec)['waterbody_text']=='Gulf Of America'
