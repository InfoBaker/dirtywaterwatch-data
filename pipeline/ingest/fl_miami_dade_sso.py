"""Miami-Dade RER/DERM sanitary sewer overflows, all county utilities.

Anonymous weekly ArcGIS publication; full history read with the shared cursor reader,
count and edit checks. INCIDENTID is the identity, never the reloadable OBJECTID.
Dates encode Eastern wall-clock time despite UTC metadata (confirmed against WASD
incident 597571 in DEP notice 202611184). Midnight is conservatively day precision;
INCDNTDATE is a date-only fallback. CREATEDDATE is entry, not publication or receipt.
QUANDSCHRG is estimated discharged gallons; ESTGALRECOVER stays separate in raw.
Secondary effluent stays in the sanitized snapshot but is excluded from sewage events.
Causes are source codes, unchanged: this layer supplies no coded-value domains.

Only selected fields are requested. Contacts, addresses and narrative comments are
excluded; water names are scrubbed and points rounded before any data is saved.
Placement uses existing named-water guards. Generic CANAL never supplies a water tie.

Run after fl_dep_pnp (the Makefile's alphabetical module order). Confirmed duplicates
use receiving-water evidence before recency to choose the counted record;
both statements remain separately cited. Linking also runs on a failed county read,
against retained evidence, because DEP may have rewritten its records this run.
No coordinates/dates-only match: an explicit tracking reference or a unique agreement
on date, municipal utility, positive volume and rounded source point is required.

Run from pipeline/: python -m ingest.fl_miami_dade_sso [--file safe-snapshot.json]
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

from common import (EVENTS_DIR, HEADERS, ROOT, error_detail, error_text, event, now_iso,
                    read_json, save_raw, strip_house_numbers, write_events, write_json)
from ingest.fl_dep_pnp import scrub, scrub_name_field
from ingest.generic import arcgis

SOURCE_ID = 'fl-miami-dade-sso'
ITEM_ID = '868a052504a449a4b0fa965b9e49e7c3'
LAYER = 'https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services/SewerOverflow_gdb/FeatureServer/0'
PAGE_URL = 'https://opendata.miamidade.gov/datasets/MDC::sewer-overflow/about'
AUTHORITY = 'Miami-Dade County Regulatory and Economic Resources, DERM'
TZ = ZoneInfo('America/New_York')
SAFE_FIELDS = ('OBJECTID','INCIDENTID','INCDNTDATE','STARTDATE','STOPDATE','QUANDSCHRG',
               'TRACKNUM','UTILITYNAME','DISCCAUSECAT','DISCHARGECAUSE','ESTGALRECOVER',
               'DISCSURFWAT','WATBODYTYPE','SURFWATNAME','WATDISCTYPE','MODIFIEDDATE','CREATEDDATE','LAT','LON')
DATE_FIELDS = ('INCDNTDATE','STARTDATE','STOPDATE','MODIFIEDDATE','CREATEDDATE')
UTILITIES = {'WASD','MIAMI BEACH','HIALEAH','NORTH MIAMI','CORAL GABLES','NORTH MIAMI BEACH',
             'OPA-LOCKA','BAY HARBOR ISLANDS','PRIVATE','NORTH BAY VILLAGE','MEDLEY','MDAD',
             'MIAMI SPRINGS','HIALEAH GARDENS','HOMESTEAD','SURFSIDE','BAL HARBOUR','FLORIDA CITY',
             'AIRPORT','BAL HARBOUR VILLAGE'}
TIME_BASIS = ('The date values encode Eastern wall-clock time despite UTC metadata. We read them in '
              'America/New_York. Midnight values have day precision because the source may omit the time.')
WASD_ID = re.compile(r'\bWASD\s+Incident\s*(?:#|Number|No\.?)\s*:?\s*(\d{5,8})\b', re.I)


def number(v):
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def safe_attributes(a):
    out = {k:a[k] for k in SAFE_FIELDS if k in a}
    for k in ('LAT','LON'):
        n = number(out.get(k))
        out[k] = n
    for k in ('DISCCAUSECAT','DISCHARGECAUSE','WATBODYTYPE','SURFWATNAME','WATDISCTYPE'):
        if isinstance(out.get(k),str):
            out[k] = strip_house_numbers(scrub_name_field(scrub(out[k])) or '') or None
    for k, pattern in (('INCIDENTID', r'\d{20}'), ('TRACKNUM',r'[A-Za-z0-9.\-/]{1,30}')):
        if out.get(k) is not None and not re.fullmatch(pattern,str(out[k])):
            out[k] = None
    return out


def get_json(sess, url, params):
    r = sess.get(url,params=params,timeout=(15,60)); r.raise_for_status()
    d = r.json()
    if not isinstance(d,dict) or 'error' in d:
        raise RuntimeError('ArcGIS query or metadata unavailable')
    return d


def query_layer(sess):
    meta = get_json(sess,LAYER,{'f':'json'})
    fields = {f.get('name'):f for f in meta.get('fields',[]) if isinstance(f,dict)}
    if not set(SAFE_FIELDS) <= fields.keys():
        raise RuntimeError('ArcGIS required fields missing')
    if any(fields[k].get('domain') for k in SAFE_FIELDS):
        raise RuntimeError('ArcGIS field domains changed; review decoding before ingestion')
    zone = (meta.get('dateFieldsTimeReference') or {}).get('timeZone')
    if zone not in ('UTC','Etc/UTC'):
        raise RuntimeError('ArcGIS time reference changed; review clock semantics')
    params = {'f':'json','where':'1=1','returnCountOnly':'true'}
    count = get_json(sess,LAYER+'/query',params).get('count')
    if not isinstance(count,int) or count <= 0:
        raise RuntimeError('ArcGIS empty or invalid count')
    fetched = arcgis.fetch({'url':LAYER,'safe_fields':list(SAFE_FIELDS),'page_size':1000,
                            'max_rows':100000},sess)
    rows = [safe_attributes(a) for a in arcgis.parse({},fetched.content)]
    ids = [a.get('INCIDENTID') for a in rows]
    if len(rows)!=count or None in ids or len(set(ids))!=len(ids):
        raise RuntimeError('ArcGIS incomplete read or nonunique incident identity')
    if get_json(sess,LAYER+'/query',params).get('count') != count:
        raise RuntimeError('ArcGIS count changed during read')
    after = get_json(sess,LAYER,{'f':'json'})
    if after.get('editingInfo') != meta.get('editingInfo'):
        raise RuntimeError('ArcGIS layer changed during read')
    safe_meta = {k:meta.get(k) for k in ('dateFieldsTimeReference','editingInfo')}
    body = json.dumps({'layer':LAYER,'fields_requested':list(SAFE_FIELDS),'metadata':safe_meta,
                       'features':[{'attributes':a} for a in rows]},ensure_ascii=False).encode()
    return rows, body, safe_meta


def wall_clock(ms):
    n = number(ms)
    if n is None: return None
    try:
        return datetime.fromtimestamp(n/1000,UTC).replace(tzinfo=None).replace(tzinfo=TZ)
    except (ValueError,OverflowError,OSError):
        return None


def precision(t):
    return ('day' if (t.hour,t.minute,t.second)==(0,0,0) else 'minute') if t else None


def to_record(a, fetched_at, prev=None):
    a = safe_attributes(a)
    key = a.get('INCIDENTID')
    if not key: raise ValueError('County record has no durable incident identity')
    raw = dict(a)
    raw.update(_time_basis=TIME_BASIS,time_zone=TZ.key,county='Miami-Dade',
               _placement='named_water_only',
               _first_seen_at=((prev or {}).get('raw') or {}).get('_first_seen_at') or fetched_at)
    raw['_decoded_times'] = {k:t.isoformat() for k in DATE_FIELDS if (t:=wall_clock(a.get(k)))}
    start = wall_clock(a.get('STARTDATE'))
    raw['_start_basis'] = 'STARTDATE' if start else 'INCDNTDATE'
    start = start or wall_clock(a.get('INCDNTDATE'))
    end = wall_clock(a.get('STOPDATE'))
    problems=[]
    if end and start and end < start and not (precision(end)=='day' and end.date()==start.date()):
        problems.append('STOPDATE precedes the start; we leave the end unknown.'); end=None
    raw['ended_at_precision'] = precision(end)
    if not start: problems.append('The source gives no usable start date.')
    flag = a.get('DISCSURFWAT')
    raw['reached_water'] = {'Y':True,'N':False}.get(flag)
    if flag=='N': raw['_no_water_reason']='The county reports no discharge into surface water.'
    lat,lon=number(a.get('LAT')),number(a.get('LON'))
    if lat is None or lon is None or not (24.3<=lat<=26.1 and -81.9<=lon<=-79.8):
        lat=lon=None
    vol=number(a.get('QUANDSCHRG'))
    if vol is not None and vol<0: vol=None
    utility=a.get('UTILITYNAME')
    params={'where':f"INCIDENTID = '{key}'",'outFields':','.join(SAFE_FIELDS),
            'returnGeometry':'false','f':'json'}
    return event(source_id=SOURCE_ID,source_record_id=key,source_url=LAYER+'/query?'+urlencode(params),
                 fetched_at=fetched_at,authority=AUTHORITY,event_type='sso' if start else 'unknown',
                 status='ended' if end else 'unknown',started_at=start.isoformat() if start else None,
                 ended_at=end.isoformat() if end else None,time_precision=precision(start),
                 reported_at=None,published_at=None,source_updated_at=raw['_decoded_times'].get('MODIFIEDDATE'),
                 discharger_id='fl-miami-dade-wasd' if utility=='WASD' else None,
                 discharger_name='Miami-Dade Water and Sewer Department' if utility=='WASD' else utility,
                 material=a.get('WATDISCTYPE'),volume_gal=vol,volume_text=f'{vol:,.0f} gallons (estimated)' if vol is not None else None,
                 estimate_flag='estimated' if vol is not None else 'unknown',
                 waterbody_text=a.get('SURFWATNAME'),water_slugs=[],water_match='none',
                 lat=lat,lon=lon,coord_source='source' if lat is not None else None,
                 coord_precision_m=100 if lat is not None else None,
                 raw=raw,parse_error=' '.join(problems) or None)


def build(rows, fetched_at, prev_records):
    prev={r['event_id']:r for r in prev_records}; out={}; seen=set(); excluded=Counter()
    for a in rows:
        key=a.get('INCIDENTID'); eid=f'{SOURCE_ID}:{key}'
        if eid in seen: raise ValueError('County snapshot repeats an incident identity')
        seen.add(eid)
        material=a.get('WATDISCTYPE')
        if material not in (None, '', 'RAW SEWAGE', 'OTHER', 'SECONDARY EFFLUENT'):
            raise ValueError('County discharge material changed; review classification')
        if material=='SECONDARY EFFLUENT':
            excluded[material]+=1
            continue
        out[eid]=to_record(a,fetched_at,prev.get(eid))
    kept=0
    for eid,r in prev.items():
        if eid not in seen:
            old=copy.deepcopy(r)
            old.setdefault('raw',{}).setdefault('_missing_from_layer_since',fetched_at)
            out[eid]=old; kept+=1
    records=sorted(out.values(),key=lambda r:(r.get('started_at') or '',r['event_id']),reverse=True)
    return records,{'layer_rows':len(rows),'kept_from_earlier_runs':kept,'excluded_by_material':dict(excluded),
                    'by_year':dict(sorted(Counter((r.get('started_at') or 'unknown')[:4] for r in records).items()))}


def _day(r):
    return (r.get('started_at') or '')[:10]


def _clear_links(records):
    for r in records:
        raw=r.setdefault('raw',{})
        owned=raw.pop('_miami_linked_ids',[])
        if owned:
            others=raw.get('_other_source_record') or []
            others=[others] if isinstance(others,str) else others
            remaining=[x for x in others if x not in owned]
            if remaining: raw['_other_source_record']=remaining
            else: raw.pop('_other_source_record',None)
        if '_miami_previous_duplicate_of' in raw:
            r['duplicate_of']=raw.pop('_miami_previous_duplicate_of')
        if '_miami_previous_parent_event_id' in raw:
            r['parent_event_id']=raw.pop('_miami_previous_parent_event_id')
        raw.pop('_miami_link_basis',None)
        raw.pop('_miami_water_contribution',None)


def _cite(a,b):
    raw=a.setdefault('raw',{}); links=raw.get('_other_source_record') or []
    links=[links] if isinstance(links,str) else links
    if b['event_id'] not in links:
        raw['_other_source_record']=sorted(links+[b['event_id']])
        raw.setdefault('_miami_linked_ids',[]).append(b['event_id'])


def _duplicate(r,target,basis):
    raw=r.setdefault('raw',{})
    raw['_miami_previous_duplicate_of']=r.get('duplicate_of')
    r['duplicate_of']=target['event_id']; raw['_miami_link_basis']=basis


def _utility_agrees(c,p):
    utility=(c.get('raw') or {}).get('UTILITYNAME')
    name=(p.get('discharger_name') or (p.get('raw') or {}).get('FACILITY_NAME') or '').upper()
    if utility=='WASD': return p.get('discharger_id')=='fl-miami-dade-wasd' or ('MIAMI-DADE' in name and ('SEWER' in name or 'W&S' in name))
    if utility in (None,'PRIVATE','MDAD','AIRPORT'): return False
    # Exact municipality, with only public utility labels removed; NORTH MIAMI != NORTH MIAMI BEACH.
    name=re.sub(r'\b(?:CITY OF|TOWN OF|VILLAGE OF|PUBLIC WORKS|WATER AND SEWER|UTILITY|UTILITIES|DEPARTMENT)\b','',name)
    return ' '.join(name.split())==utility


def _point_volume_agree(c,p):
    v=c.get('volume_gal')
    if not v or v!=p.get('volume_gal') or not _utility_agrees(c,p): return False
    coords=[number(r.get(k)) for r in (c,p) for k in ('lat','lon')]
    return None not in coords and all(round(coords[i],3)==round(coords[i+2],3) for i in (0,1))


def _release_bounds(r):
    """Comparison bounds only: never change source times or turn day precision into a stated time."""
    from build import status as S
    start, end = S.ev_time(r, 'started_at', 'FL'), S.ev_time(r, 'ended_at', 'FL')
    if end and S.end_precision(r) == 'day':
        end = S.end_of_local_day(end, TZ)
    # DEP's normalized times are dates. The WASD template may additionally state exact local times.
    text = (r.get('raw') or {}).get('INCIDENT_REPORT') or ''
    for field, label in (('start', r'Estimated\s+Time\s+Release\s+Started'),
                         ('end', r'Discharge\s+Stopped\s+On')):
        matches = re.findall(label + r'\s*:\s*(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[AP]M)\b', text, re.I)
        times = set()
        for value in matches:
            value = ' '.join(value.upper().split())
            fmt = '%m/%d/%Y %I:%M %p' if len(value.split()[0].split('/')[-1]) == 4 else '%m/%d/%y %I:%M %p'
            try:
                times.add(datetime.strptime(value, fmt).replace(tzinfo=TZ))
            except ValueError:
                return None
        if len(times) > 1: return None  # contradictory template values cannot support a fallback
        if times:
            t = times.pop()
            normalized = S.ev_time(r, 'started_at' if field == 'start' else 'ended_at', 'FL')
            if normalized and normalized.astimezone(TZ).date() != t.date(): return None
            if field == 'start': start = t
            else: end = t
    if start and end and end < start: return None
    return start, end


def _intervals_agree(a,b):
    aa, bb = _release_bounds(a), _release_bounds(b)
    if aa is None or bb is None: return False
    a0,a1 = aa; b0,b1 = bb
    return not ((a1 and b0 and a1 < b0) or (b1 and a0 and b1 < a0))


def _named_water_keys(text):
    """Source water names, including waterways and numbered canals; generic kinds are not names.

    The shared same-day duplicate heuristic deliberately limits names to six words and omits
    waterway. These already-linked source reports need to retain longer names as evidence too.
    """
    from build import status as S
    word = re.compile(S.WATER_WORD.pattern + r'|\bwaterways?\b', re.I)
    keys = set()
    for part in re.split(r'[;\n]', str(text or '')):
        if not part.strip() or S.no_water_text(part) or S.stated_no_water(part): continue
        toks = S.norm_name(part).split()
        first = next((i for i, t in enumerate(toks) if word.fullmatch(t)), None)
        if first is not None:
            cut = next((i for i in range(first + 1, len(toks)) if toks[i] in S.WHERE_WORDS), len(toks))
            toks = toks[:cut]
        named = [t for t in toks if t not in S.UNSPECIFIC_WATER_WORDS]
        if named and not all(word.fullmatch(t) for t in named):
            keys.add(''.join(named))
    return keys


def _water_evidence(r):
    # Same dry-record safeguards as al_jefferson_county_soa.link_adem.
    from build import status as S
    if S.no_water_flag(r) or S.reached_no_water(r) or S.no_receiving_water(r): return 0
    return 2 if _named_water_keys(r.get('waterbody_text')) else 1


def _waters_differ(a,b):
    if _water_evidence(a) != 2 or _water_evidence(b) != 2: return False
    ka, kb = _named_water_keys(a.get('waterbody_text')), _named_water_keys(b.get('waterbody_text'))
    return not any(x in y or y in x for x in ka for y in kb)


def link_pnp(county,pnp):
    """Link only unambiguous identity; never transfer one source's values into another's fields."""
    _clear_links(county+pnp)
    by_day=defaultdict(list)
    for c in county:
        if _day(c): by_day[_day(c)].append(c)
    pairs=defaultdict(list); bases={}; fallback=[]; candidates_by_county=Counter()
    for p in pnp:
        raw=p.get('raw') or {}
        if raw.get('_pnp_kind')=='citizen_complaint' or p.get('event_type') not in ('sso','bypass','plant_bypass','unknown'):
            continue
        if 'DADE' not in str(raw.get('AFFECTED_COUNTIES') or '').upper(): continue
        candidates=by_day.get(_day(p),[])
        refs=set(WASD_ID.findall(raw.get('INCIDENT_REPORT') or ''))
        matches=[c for c in candidates if (c.get('raw') or {}).get('UTILITYNAME')=='WASD'
                 and (c.get('raw') or {}).get('TRACKNUM') in refs]
        basis='We linked the county tracking number to the explicit WASD incident number in the DEP notice, on the same date.'
        weak=False
        if not matches and not refs:
            n=str(raw.get('INCIDENT_NUMBER') or '')
            matches=[c for c in candidates if n and re.sub(r'[-\s]','',str((c.get('raw') or {}).get('TRACKNUM') or ''))==n
                     and _utility_agrees(c,p)]
            basis='We linked the matching tracking and notice numbers, utility and start date.'
            if not matches:
                matches=[c for c in candidates if _point_volume_agree(c,p)]
                weak=True
                basis='We linked a unique match on start date, utility, estimated discharged gallons and the source point rounded to three decimals.'
        # Count all identity candidates before interval filtering, including ambiguous DEP notices.
        # A conflicting interval must not make another weak candidate look unique.
        candidates_by_county.update(c['event_id'] for c in matches)
        if len(matches)==1:
            c=matches[0]
            if weak: fallback.append((c,p,basis))
            else:
                pairs[c['event_id']].append(p); bases[(c['event_id'],p['event_id'])]=basis
    for c,p,basis in fallback:
        if candidates_by_county[c['event_id']]==1 and _intervals_agree(c,p):
            pairs[c['event_id']].append(p); bases[(c['event_id'],p['event_id'])]=basis
    by_id={c['event_id']:c for c in county}; n=dep_n=0
    for eid,ps in pairs.items():
        c=by_id[eid]
        group=[c]+ps
        primary=max(group,key=lambda r:(_water_evidence(r), r is not c,
                                        r.get('reported_at') or '',r['event_id']))
        # Identity links may group different SWO numbers; weaker evidence is always one-to-one.
        if primary.get('duplicate_of') in {p['event_id'] for p in ps}:
            primary['raw']['_miami_previous_duplicate_of']=primary['duplicate_of']; primary['duplicate_of']=None
        if primary.get('duplicate_of'): continue  # unrelated existing identity wins
        n+=1; dep_n+=len(ps)
        active_ids={r['event_id'] for r in group if r is primary or _waters_differ(r,primary)}
        for r in group:
            # A duplicate revision must not independently suppress the water-bearing representative.
            # Retain the original relation and restore it when these county links are recomputed.
            if r.get('parent_event_id') in active_ids:
                r['raw']['_miami_previous_parent_event_id']=r['parent_event_id']
                r['parent_event_id']=None
        for p in ps:
            _cite(c,p); _cite(p,c)
        for r in group:
            if r is primary: continue
            basis=bases[(eid, (primary if r is c else r)['event_id'])]
            _duplicate(r,primary,basis)
            # One counting identity, but each different named water keeps this source's own status.
            if r['event_id'] in active_ids:
                r['raw']['_miami_water_contribution']=primary['event_id']
    return {'county_linked':n,'dep_records_linked':dep_n}


def link_only():
    county_path=EVENTS_DIR/f'{SOURCE_ID}.json'; pnp_path=EVENTS_DIR/'fl-dep-pnp.json'
    cdoc=read_json(county_path,{}) or {}; pdoc=read_json(pnp_path,{}) or {}
    stats=link_pnp(cdoc.get('records',[]),pdoc.get('records',[]))
    for path,doc in ((county_path,cdoc),(pnp_path,pdoc)):
        if doc:
            doc.setdefault('meta',{})['miami_dade_links']=stats
            write_json(path,doc)  # linking changes neither fetch health nor evidence times
    return stats


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__.splitlines()[0]); ap.add_argument('--file')
    args=ap.parse_args(argv); at=now_iso()
    try:
        if args.file:
            d=json.loads(Path(args.file).read_text())
            rows=[safe_attributes(f.get('attributes') or {}) for f in d['features']]
            body=json.dumps({'features':[{'attributes':a} for a in rows]}).encode(); metadata={}
            if not rows: raise ValueError('Empty county snapshot')
        else:
            with requests.Session() as sess:
                sess.headers.update(HEADERS); rows,body,metadata=query_layer(sess)
        prev=(read_json(EVENTS_DIR/f'{SOURCE_ID}.json',{}) or {}).get('records',[])
        records,stats=build(rows,at,prev)
        path=save_raw(SOURCE_ID,body,'json')
        write_events(SOURCE_ID,records,meta={**stats,'raw_path':str(path.relative_to(ROOT)),
                     'layer_metadata':metadata,'requested_fields':list(SAFE_FIELDS),'registry_ids':[SOURCE_ID],
                     'credit':AUTHORITY,'time_basis':TIME_BASIS})
    except Exception as exc:
        write_events(SOURCE_ID,[],ok=False,error=error_text(exc)); link_only()
        print(f'{SOURCE_ID}: FAILED {error_detail(exc)}',file=sys.stderr); return 1
    links=link_only()
    print(f'{SOURCE_ID}: {len(records)} records; {links["county_linked"]} linked to DEP')
    return 0


if __name__ == "__main__":
    sys.exit(main())
