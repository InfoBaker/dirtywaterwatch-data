"""Scan npdes_downloads.zip (ICIS-NPDES national dataset part 1): which active POTW permits are absent from the
discharge-points file, and do they have permitted-feature coordinates in NPDES_PERM_FEATURE_COORDS?
Usage: python -I supplement_scan.py <npdes_downloads.zip> <npdes_outfalls_layer.csv> <dischargers.json> <out.json>"""
import csv, io, json, sys, zipfile, collections

zpath, ol, disch, out = sys.argv[1:5]
C = collections.Counter
z = zipfile.ZipFile(zpath)
names = {n.split('/')[-1].upper(): n for n in z.namelist()}
print(sorted(names), file=sys.stderr)


def rd(name):
    return csv.DictReader(io.TextIOWrapper(z.open(names[name]), encoding='utf-8', errors='replace', newline=''))


layer = set()
for r in csv.DictReader(open(ol, newline='', encoding='utf-8', errors='replace')):
    layer.add(r['EXTERNAL_PERMIT_NMBR'].strip().upper())
tracked = {}
for d in json.load(open(disch)):
    for p in d.get('npdes_permits') or []:
        tracked.setdefault(p.strip().upper(), []).append(d['id'])

permits = {}
for r in rd('ICIS_PERMITS.CSV'):
    p = r['EXTERNAL_PERMIT_NMBR'].strip().upper()
    v = int(float(r.get('VERSION_NMBR') or 0))
    if p not in permits or v >= permits[p]['_v']:
        permits[p] = {**r, '_v': v}
comps = collections.defaultdict(set)
for r in rd('NPDES_PERM_COMPONENTS.CSV'):
    comps[r['EXTERNAL_PERMIT_NMBR'].strip().upper()].add(r['COMPONENT_TYPE_DESC'] or r['COMPONENT_TYPE_CODE'])
ACTIVE = {'EFF', 'ADC', 'EXP'}
cand = {}
stat = C()
for p, r in permits.items():
    potw = (r.get('FACILITY_TYPE_INDICATOR') or '').upper() == 'POTW' or 'POTW' in comps.get(p, ())
    active = r['PERMIT_STATUS_CODE'] in ACTIVE
    if potw and active:
        stat['active POTW permits in ICIS_PERMITS'] += 1
        if p not in layer:
            stat['... absent from discharge-points file'] += 1
            cand[p] = r
    if p in tracked and p not in layer:
        stat['tracked permits absent from layer, in ICIS_PERMITS'] += 1
        cand[p] = r
feats = collections.defaultdict(list)
for r in rd('NPDES_PERM_FEATURE_COORDS.CSV'):
    p = r['EXTERNAL_PERMIT_NMBR'].strip().upper()
    if p in cand:
        feats[p].append({'outfall': r['PERM_FEATURE_NMBR'], 'lat': r['LATITUDE_MEASURE'], 'lon': r['LONGITUDE_MEASURE']})
fac = {}
for r in rd('ICIS_FACILITIES.CSV'):
    p = r['NPDES_ID'].strip().upper()
    if p in cand:
        fac[p] = {k: r.get(k) for k in ('FACILITY_NAME', 'CITY', 'STATE_CODE', 'GEOCODE_LATITUDE', 'GEOCODE_LONGITUDE',
                                        'FACILITY_TYPE_CODE', 'FACILITY_UIN')}
stat['candidates with feature coordinates'] = sum(1 for p in cand if feats.get(p))
stat['candidate features with coordinates'] = sum(len(feats.get(p, [])) for p in cand)
by_state = C((fac.get(p) or {}).get('STATE_CODE') or p[:2] for p in cand)
by_state_feat = C((fac.get(p) or {}).get('STATE_CODE') or p[:2] for p in cand if feats.get(p))
res = {'stats': dict(stat), 'by_state': dict(by_state), 'by_state_with_features': dict(by_state_feat),
       'tracked_absent': {p: {'ids': tracked[p], 'status': permits[p]['PERMIT_STATUS_CODE'],
                              'features': feats.get(p, []), 'facility': fac.get(p)} for p in cand if p in tracked},
       'candidates': {p: {'permit': {k: cand[p].get(k) for k in ('PERMIT_STATUS_CODE', 'PERMIT_TYPE_CODE',
                                                                'FACILITY_TYPE_INDICATOR', 'PERMIT_NAME',
                                                                'STATE_WATER_BODY_NAME', 'TOTAL_DESIGN_FLOW_NMBR',
                                                                'MAJOR_MINOR_STATUS_FLAG', 'VERSION_NMBR')},
                          'components': sorted(comps.get(p, ())), 'features': feats.get(p, []),
                          'facility': fac.get(p)} for p in cand}}
json.dump(res, open(out, 'w'), indent=1)
print(json.dumps({k: res[k] for k in ('stats', 'by_state', 'by_state_with_features')}, indent=1))
print('tracked absent', {p: (v['status'], len(v['features'])) for p, v in res['tracked_absent'].items()})
