"""Storage/dispatch proposal checks. Synthetic records only; never reads production state."""
import importlib.util, json, os, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]
SID='fed-beacon-beach-actions'

def module():
 path=Path(os.environ.get('BEACON_PATCH_ROOT',str(ROOT)))/'scripts/state_paths.py'
 spec=importlib.util.spec_from_file_location('state_paths_proposed',path)
 mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod);return mod

def seed(root):
 b=root/'data/build';(b/'events').mkdir(parents=True)
 (b/'events'/f'{SID}.json').write_text(json.dumps({'source_id':SID,'count':1,'records':[{'event_id':SID+':test-advisory'}],'meta':{}}))
 (b/f'{SID}-state.json').write_text(json.dumps({'years':{'2014':{'rows':{'test':{'jurisdiction':'OH'}}}},'first_seen':{'test':'2026-11-28T00:00:00Z'}}))
 return b

def test_frozen_beacon_roundtrip_and_unchanged_skip(tmp_path):
 s=module();assert SID in s.FROZEN_FEEDS
 b=seed(tmp_path);f=tmp_path/'frozen.gz';h=tmp_path/'hot.gz'
 assert s.pack_frozen(f,tmp_path)==0
 runtime=json.loads((b/s.FROZEN_RUNTIME).read_text());assert f'{SID}-state.json' not in runtime['states']
 assert s.reliable_versions(s.frozen_versions(tmp_path))
 s.pack_build(h,tmp_path,saved_frozen=f)
 assert SID not in s.event_counts(h)
 fresh=tmp_path/'restore';s.unpack_build(h,fresh);s.unpack_frozen(f,fresh)
 for rel in [f'events/{SID}.json',f'{SID}-state.json']:assert (fresh/'data/build'/rel).read_bytes()==(b/rel).read_bytes()
 baseline=tmp_path/'baseline.json';s.frozen_baseline(baseline,tmp_path)
 assert s.pack_frozen(tmp_path/'unchanged.gz',tmp_path,baseline)==3

@pytest.mark.parametrize('kind',['rows','link','clock'])
def test_changed_rows_links_or_fetch_clock_repack(tmp_path,kind):
 s=module();b=seed(tmp_path);s.pack_frozen(tmp_path/'first.gz',tmp_path)
 baseline=tmp_path/'baseline.json';s.frozen_baseline(baseline,tmp_path)
 p=b/(f'{SID}-state.json' if kind=='rows' else f'events/{SID}.json');d=json.loads(p.read_text())
 if kind=='rows':d['years']['2014']['rows']['second']={'jurisdiction':'MI'}
 elif kind=='link':d['records'][0]['duplicate_of']='state:example'
 else:d['fetched_at']='2026-12-01T00:00:00Z'
 p.write_text(json.dumps(d))
 assert s.pack_frozen(tmp_path/'changed.gz',tmp_path,baseline)==0


def test_missing_frozen_confirmation_keeps_hot_copy(tmp_path):
 s=module();b=seed(tmp_path);s.pack_build(tmp_path/'hot.gz',tmp_path)
 assert SID in s.event_counts(tmp_path/'hot.gz')


def test_bare_backfill_dispatch_defaults_to_2014(tmp_path,monkeypatch):
 from ingest import fed_beacon_beach_actions as original
 path=Path(os.environ.get('BEACON_PATCH_ROOT',str(ROOT)))/'pipeline/ingest/fed_beacon_beach_actions.py'
 spec=importlib.util.spec_from_file_location('beacon_proposed',path);b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
 years=[]
 def read(_directory,year):
  years.append(year);raise b.PullError('synthetic read failure')
 monkeypatch.setattr(b,'read_saved',read)
 assert b.run(['--backfill','--from-dir',str(tmp_path)],now=original.datetime(2026,11,28,tzinfo=original.UTC),events_dir=tmp_path/'events',state_file=tmp_path/'state.json')==1
 assert years==list(range(2014,2025))

@pytest.mark.parametrize('damage',['missing','empty'])
def test_beacon_requires_saved_rows_companion(tmp_path,damage):
 s=module();b=seed(tmp_path);p=b/f'{SID}-state.json'
 if damage=='missing':p.unlink()
 else:p.write_text('{}')
 with pytest.raises(s.Unreadable):s.pack_frozen(tmp_path/'bad.gz',tmp_path)

def test_empty_rolling_season_does_not_discard_nonempty_history(tmp_path):
 s=module();b=seed(tmp_path);p=b/f'{SID}-state.json';d=json.loads(p.read_text());d['years']['2027']={'rows':{}};p.write_text(json.dumps(d))
 assert s.pack_frozen(tmp_path/'valid.gz',tmp_path)==0

def beacon_module():
 path=Path(os.environ.get('BEACON_PATCH_ROOT',str(ROOT)))/'pipeline/ingest/fed_beacon_beach_actions.py'
 spec=importlib.util.spec_from_file_location('beacon_quality_proposed',path);b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b);return b

def test_permanent_closure_keeps_existing_key_and_closure_kind():
 b=beacon_module()
 row={'key':'test-permanent-closure','jurisdiction':'NC','year':'2014','beach_id':'synthetic','action_type':'Permanent Closure','start_text':'21-SEP-2014 05:00AM','end_text':'18-NOV-2014 09:46PM'}
 r=b.to_record(row,None,'2026-11-28T00:00:00Z',None)
 assert r['event_type']=='beach_closure'
 assert r['event_id']==SID+':test-permanent-closure'
 assert 'type_unmapped' not in r['raw']


def test_repeated_main_rows_keep_reported_hours_and_stable_keys():
 import csv,io
 b=beacon_module()
 row={k:'' for k in b.MAIN_COLUMNS};row.update({'Jurisdiction':'IN','Year':'2015','Beach ID':'synthetic','Action ID':'100','Action Type':'Contamination Advisory','ActionStart Date':'05-SEP-2015 12:00AM','ActionEnd Date':'06-SEP-2015 12:00AM'})
 def make(rows):
  out=io.StringIO();w=csv.DictWriter(out,fieldnames=[*b.MAIN_COLUMNS,'Time affected(in hours)']);w.writeheader();w.writerows(rows);return out.getvalue()
 rows=[{**row,'Time affected(in hours)':''},{**row,'Time affected(in hours)':'24'}]
 a,_=b.normalize(make(rows),'');z,_=b.normalize(make(rows[::-1]),'')
 assert a==z
 assert a['100-advisory~2']['time_affected_hours_text']=='24'
 rec=b.to_record(a['100-advisory~2'],None,'2026-11-28T00:00:00Z',None)
 assert rec['raw']['time_affected_hours_text']=='24'
