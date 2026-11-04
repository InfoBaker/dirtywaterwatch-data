"""Build data/outfalls-plants-us.json: one row per permitted external outfall of every active POTW / public sewer
permit in EPA ICIS-NPDES (ECHO "ICIS-NPDES Discharge Points", npdes_outfalls_layer.zip), CSO features removed
(EPA's National CSO Inventory covers those), plus one facility-point row for a permit with no outfall coordinates.

Usage (pipeline venv for shapely/numpy):
  python -I build_plant_outfalls.py <npdes_outfalls_layer.csv> <ALL_CSO_DOWNLOADS.csv> <NPDES_CATCHMENTS.csv>
      <NPDES_ATTAINS_AU_SUMMARIES.csv> <limits.json|-> <dischargers.json> <cb_2023_us_state_500k.zip>
      <fetched_at> <out.json> <report.json>
"""
import csv, json, re, struct, sys, zipfile, collections
import numpy as np
from shapely.geometry import Point, Polygon, LinearRing
from shapely.ops import unary_union
from shapely.prepared import prep

(OL, CSO, CATCH, AUSUM, LIMITS, DISCH, STATES_ZIP, FETCHED_AT, OUT, REPORT) = sys.argv[1:11]
FRS_EXTRA = json.load(open(sys.argv[11])) if len(sys.argv) > 11 else {}   # NPDES id -> FRS registry id
# supplement: active POTW permits that ICIS_PERMITS has and the discharge-points file omits (supplement_scan.py output
# over npdes_downloads.zip), with their NPDES_PERM_FEATURE_COORDS points; feature types from a limits pass over them
SUPP = json.load(open(sys.argv[12]))['candidates'] if len(sys.argv) > 12 else {}
SUPP_LIMITS = json.load(open(sys.argv[13])) if len(sys.argv) > 13 else {}
SUPP_SOURCE_ID = 'fed-echo-icis-npdes-national-dataset'
SUPP_FETCHED_AT = sys.argv[14] if len(sys.argv) > 14 else FETCHED_AT
C = collections.Counter
ACTIVE = {'EFF', 'ADC', 'EXP'}
PUBLIC = {'MWD', 'CTG', 'CNG', 'STF', 'FDF', 'DIS', 'TRB', 'SDT', 'GOC', 'MXO'}
STORMWATER = {'Construction Stormwater', 'Industrial Stormwater', 'Urban Stormwater (Small MS4)',
              'Urban Stormwater (Medium/Large MS4)'}
INDIVIDUAL = {'NPD', 'SIN'}
CSO_NAME = re.compile(r'\bCSO\b|COMBINED\s+SEW|\bCOMB\.?\s*SEW', re.I)
WET_NAME = re.compile(r'\bCSO\b|COMBINED\s+SEW|\bCOMB\.?\s*SEW|EXCESS\s+FLOW|BYPASS|\bEHLO\b|OVERFLOW|HIGH\s+LEVEL', re.I)
SOURCE_ID = 'fed-echo-npdes-discharge-points'


def nf(x):
    s = ''.join(str(x if x is not None else '').split()).upper()
    return s.lstrip('0') or ('0' if s else '')


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def rows(path):
    return csv.DictReader(open(path, newline='', encoding='utf-8', errors='replace'))


# ------------------------------------------------------------------ inputs
tracked = collections.defaultdict(list)          # permit -> discharger ids
for d in json.load(open(DISCH)):
    ps = d.get('npdes_permits') or ([d['npdes_permit']] if d.get('npdes_permit') else [])
    for p in ps:
        if p:
            tracked[p.strip().upper()].append(d['id'])

inv = {}                                          # (permit, feature) -> PF_CHARACTER
inv_permits = C()
for r in rows(CSO):
    p = r['NPDES_ID'].strip().upper()
    inv[(p, nf(r['PERM_FEATURE_NMBR']))] = r['PF_CHARACTER']
    inv_permits[p] += 1

limits = json.load(open(LIMITS)) if LIMITS != '-' else {}

# ------------------------------------------------------------------ the discharge points file, grouped by permit
perm = {}
dups = 0
for r in rows(OL):
    p = r['EXTERNAL_PERMIT_NMBR'].strip().upper()
    e = perm.get(p)
    if e is None:
        comps = [c.strip() for c in (r['PERMIT_COMPONENTS'] or '').split(',') if c.strip()]
        sic = {c.strip() for c in (r['SIC_CODES'] or '').split(',')}
        naics = {c.strip() for c in (r['NAICS_CODES'] or '').split(',')}
        e = perm[p] = dict(r=r, comps=comps, sewer_code=('4952' in sic or '221320' in naics), exo={}, other_pf=[],
                           fac=None)
    if r['LATLONG_TYPE'] == 'Facility':
        e['fac'] = e['fac'] or r
    elif r['SUB_TYPE_DESC'] == 'External Outfall':
        k = nf(r['PERM_FEATURE_NMBR'])
        if k in e['exo']:
            dups += 1
        else:
            e['exo'][k] = r
    else:
        e['other_pf'].append(r)


def basis(p, e):
    r = e['r']
    comps = set(e['comps'])
    if r['PERMIT_STATUS_CODE'] not in ACTIVE:
        return None
    if 'POTW' in comps and r['PERMIT_TYPE_CODE'] in INDIVIDUAL | {'GPC'}:
        return 'potw_component'
    if (e['sewer_code'] and r['FACILITY_TYPE_CODE'] in PUBLIC and r['PERMIT_TYPE_CODE'] in INDIVIDUAL | {'GPC'}
            and not (comps and comps <= STORMWATER)):
        return 'sewerage_code_public_owner'
    if (e['sewer_code'] and r['FACILITY_TYPE_CODE'] in ('', 'UNK') and r['PERMIT_TYPE_CODE'] in INDIVIDUAL
            and not (comps and comps <= STORMWATER)):
        return 'sewerage_code_owner_unknown'
    if p in tracked:
        return 'tracked_operator'
    return None


universe = {}
excluded = C()
for p, e in perm.items():
    b = basis(p, e)
    if b:
        universe[p] = b
    else:
        r = e['r']
        comps = set(e['comps'])
        if 'POTW' in comps or e['sewer_code']:
            if r['PERMIT_STATUS_CODE'] not in ACTIVE:
                excluded['sewer-type permit not active (' + (r['PERMIT_STATUS_CODE'] or 'blank') + ')'] += 1
            elif comps and comps <= STORMWATER and 'POTW' not in comps:
                excluded['stormwater-only permit at a sewer facility'] += 1
            elif e['sewer_code'] and r['FACILITY_TYPE_CODE'] not in PUBLIC:
                excluded['sewerage SIC/NAICS but private or unknown owner, ' +
                         ('individual permit' if r['PERMIT_TYPE_CODE'] in INDIVIDUAL else 'general/other permit')] += 1
            else:
                excluded['other (' + r['PERMIT_TYPE_CODE'] + ')'] += 1

# ------------------------------------------------------------------ reach index and registry ids for those permits
catch = {}
for r in rows(CATCH):
    p = r['NPDES_ID'].strip().upper()
    if p in universe or p in SUPP:
        sid = r['SUB_ID'].strip().upper()
        catch[(p, 'BESTPICK' if sid == 'BESTPICK' else nf(sid))] = r
registry = {}
for r in rows(AUSUM):
    p = r['NPDES_ID'].strip().upper()
    if p in universe and r['REGISTRY_ID'] and p not in registry:
        registry[p] = r['REGISTRY_ID'].strip()

# ------------------------------------------------------------------ state outlines (as pipeline/ingest/waters_from_nhd)


def read_state_outlines(zpath):
    z = zipfile.ZipFile(zpath)
    stem = 'cb_2023_us_state_500k'
    shp, dbf = z.read(f'{stem}.shp'), z.read(f'{stem}.dbf')
    nrec = struct.unpack('<I', dbf[4:8])[0]
    hlen, rlen = struct.unpack('<HH', dbf[8:12])
    fields, pos = [], 32
    while dbf[pos] != 0x0D:
        fields.append((dbf[pos:pos + 11].split(b'\0')[0].decode(), dbf[pos + 16]))
        pos += 32
    codes = []
    for i in range(nrec):
        off, vals = hlen + i * rlen + 1, {}
        for name, flen in fields:
            vals[name] = dbf[off:off + flen].decode('latin-1').strip()
            off += flen
        codes.append(vals.get('STUSPS'))
    out, pos, i = {}, 100, 0
    while pos + 8 <= len(shp):
        _, clen = struct.unpack('>ii', shp[pos:pos + 8])
        content = shp[pos + 8:pos + 8 + clen * 2]
        pos += 8 + clen * 2
        code = codes[i]
        i += 1
        if struct.unpack('<i', content[:4])[0] != 5:
            continue
        nparts, npts = struct.unpack('<ii', content[36:44])
        parts = list(struct.unpack(f'<{nparts}i', content[44:44 + 4 * nparts])) + [npts]
        pts = np.frombuffer(content[44 + 4 * nparts:44 + 4 * nparts + 16 * npts], dtype='<f8').reshape(-1, 2)
        outers, holes = [], []
        for a, b in zip(parts, parts[1:]):
            ring = pts[a:b]
            if len(ring) < 4:
                continue
            (holes if LinearRing(ring).is_ccw else outers).append(Polygon(ring))
        g = unary_union(outers)
        if holes:
            g = g.difference(unary_union(holes))
        out[code] = g.buffer(0)
    return out


STATES = read_state_outlines(STATES_ZIP)
STATES_BUF = {k: prep(v.buffer(0.02)) for k, v in STATES.items()}   # about 2 km
MARINE = re.compile(r'OCEAN|\bSEA\b|GULF|\bBAY\b|SOUND|STRAIT|CHANNEL|HARBOU?R|ESTUARY|INLET|LAGOON|\bLAKE\b', re.I)
OFFSHORE = {}


def km_outside(state, lat, lon):
    import math
    d = STATES[state].distance(Point(lon, lat))          # degrees; rough km below
    return d * 111.0 * max(0.3, math.cos(math.radians(lat)))


def coords_problem(state, lat, lon, water=None, key=None):
    g = STATES_BUF.get(state)
    if g is None or lat is None or lon is None:
        return None
    if g.contains(Point(lon, lat)):
        return None
    other = [k for k, v in STATES_BUF.items() if k != state and v.contains(Point(lon, lat))]
    if not other:
        km = km_outside(state, lat, lon)
        # the Census outlines stop at the shoreline: an ocean, bay, sound or Great Lakes outfall lies offshore
        if km <= 5 or (km <= 60 and water and MARINE.search(water)):
            OFFSHORE[key] = round(km, 1)
            return None
    hint = ''
    if other:
        hint = '; it falls inside ' + ', '.join(sorted(other))
    if g.contains(Point(-lon, lat)):
        hint += '; with the longitude sign flipped it would fall inside the state'
    elif any(g.contains(Point(sx * lat, sy * lon)) for sx in (1, -1) for sy in (1, -1)):
        hint += '; with latitude and longitude swapped it would fall inside the state'
    elif lat == 0 or lon == 0:
        hint += '; a zero coordinate'
    return f"EPA's point ({lat}, {lon}) lies more than about 2 km outside {state}" + hint


# ------------------------------------------------------------------ rows
out_rows, cso_suspects, report = [], [], {}
tracked_gain = {}
cnt = C()


def echo_url(p):
    if p in registry:
        return f'https://echo.epa.gov/detailed-facility-report?fid={registry[p]}'
    if p in FRS_EXTRA:
        return f'https://echo.epa.gov/detailed-facility-report?fid={FRS_EXTRA[p]}'
    return f'https://echo.epa.gov/trends/loading-tool/reports/effluent-charts#{p}'


def base_row(p, r, b):
    return {
        'npdes_permit': p,
        'permittee': (r['FACILITY_NAME'] or '').strip() or None,
        'permit_name': (r['PERMIT_NAME'] or '').strip() or None,
        'state': r['STATE_CODE'],
        'city': (r['CITY'] or '').strip() or None,
    }


for p, b in sorted(universe.items()):
    e = perm[p]
    r0 = e['r']
    exo_open = {}
    for k, r in e['exo'].items():
        if (p, k) in inv:
            cnt['exo in CSO inventory (left to the CSO registry)'] += 1
            continue
        lim = limits.get(f'{p}|{k}') or {}
        names = lim.get('names') or []
        cso_named = 'CSO' in e['comps'] and any(CSO_NAME.search(n) for n in names)
        if cso_named and all(WET_NAME.search(n) for n in names):
            cso_suspects.append({'npdes_permit': p, 'permittee': r['FACILITY_NAME'], 'state': r['STATE_CODE'],
                                 'outfall': r['PERM_FEATURE_NMBR'], 'lat': num(r['LATITUDE83']),
                                 'lon': num(r['LONGITUDE83']), 'receiving_water_echo': r['STATE_WATER_BODY_NAME'] or None,
                                 'limit_set_names': names,
                                 'why': 'CSO permit component; ICIS limit set named as a combined sewer overflow; '
                                        'not in the National CSO Inventory'})
            cnt['exo held back as CSO not in inventory'] += 1
            continue
        exo_open[k] = (r, lim, cso_named)
    rows_p = []
    if exo_open:
        for k, (r, lim, cso_named) in exo_open.items():
            lat, lon = num(r['LATITUDE83']), num(r['LONGITUDE83'])
            c = catch.get((p, k)) or {}
            row = base_row(p, r, b)
            row.update({
                'outfall': r['PERM_FEATURE_NMBR'],
                'outfall_name': None,
                'outfall_status': None,
                'feature_type': 'EXO',
                'receiving_water_echo': (r['STATE_WATER_BODY_NAME'] or '').strip() or None,
                'reach_id': c.get('REACHCODE') or None,
                'reach_gnis_name': c.get('GNIS_NAME') or None,
                'nhdplus_id': c.get('NHDPLUSID') or None,
                'lat': lat, 'lon': lon,
                'coords_from': 'permitted_feature' if lat is not None and lon is not None else None,
            })
            row['has_limits'] = bool(lim)
            if lim.get('names'):
                row['limit_set_names'] = lim['names'][:4]
            if cso_named:
                row['cso_limit_sets'] = True      # a plant outfall that also carries combined-sewer limit sets
                cnt['plant rows that also carry CSO-named limit sets'] += 1
            rows_p.append(row)
    elif not e['exo']:
        # no external outfall coordinates at all: the facility's point, else EPA's best-pick point for the permit
        fr = e['fac']
        c = catch.get((p, 'BESTPICK')) or {}
        if fr is not None:
            lat, lon, how = num(fr['LATITUDE83']), num(fr['LONGITUDE83']), 'facility row of the discharge-points file'
        elif c:
            lat, lon, how = num(c['LATITUDE83']), num(c['LONGITUDE83']), "ECHO catchment index 'BESTPICK' point"
        else:
            lat = lon = None
            how = None
        row = base_row(p, fr or r0, b)
        row.update({
            'outfall': None, 'outfall_name': None, 'outfall_status': None, 'feature_type': None,
            'receiving_water_echo': ((fr or r0)['STATE_WATER_BODY_NAME'] or '').strip() or None,
            'reach_id': c.get('REACHCODE') or None, 'reach_gnis_name': c.get('GNIS_NAME') or None,
            'nhdplus_id': c.get('NHDPLUSID') or None,
            'lat': lat, 'lon': lon, 'coords_from': 'facility' if lat is not None and lon is not None else None,
            'coords_note': ('the facility\'s point (' + how + '): ICIS has no outfall coordinates for this permit, '
                            'so this is a point for the treatment plant or the permittee\'s address, not the '
                            'outfall\'s own point') if how else 'no point in EPA\'s files',
            'other_features': sorted({x['SUB_TYPE_DESC'] for x in e['other_pf']}) or None,
        })
        rows_p.append(row)
        cnt['permits with facility point only'] += 1
    else:
        cnt['permits whose external outfalls are all CSO (inventory or held back)'] += 1
    # shared points
    pts = C((r['lat'], r['lon']) for r in rows_p if r['lat'] is not None)
    for row in rows_p:
        ex = row
        ex.update({
            'in_icis': 'YES',
            'permit_status': r0['PERMIT_STATUS_CODE'],
            'permit_type': r0['PERMIT_TYPE_CODE'],
            'permit_components': e['comps'],
            'plant_basis': b,
            'facility_type': r0['FACILITY_TYPE_DESC'] or None,
            'major_minor': r0['MAJOR_MINOR_FLAG'] or None,
            'design_flow_mgd': num(r0['TOTAL_DESIGN_FLOW_NMBR']),
            'echo_url': echo_url(p),
            'outfall_kind': 'plant',
            'country': 'US',
            'source': SOURCE_ID,
            'fetched_at': FETCHED_AT,
        })
        if p in tracked:
            ex['discharger_ids'] = sorted(set(tracked[p]))
        if row['lat'] is not None:
            n = pts[(row['lat'], row['lon'])]
            if n > 1:
                row['point_shared_by'] = n
                if row['coords_from'] == 'permitted_feature':
                    row['coords_note'] = f'{n} of this permit\'s outfalls share this one point in ICIS'
            key = (p, row['outfall'])
            prob = coords_problem(row['state'], row['lat'], row['lon'], row.get('receiving_water_echo'), key)
            if key in OFFSHORE and OFFSHORE[key] > 0.5:
                row['coords_note'] = ((row.get('coords_note') + '; ') if row.get('coords_note') else '') + (
                    f"offshore: EPA's point is about {OFFSHORE[key]} km outside the state's land outline (Census "
                    "cartographic boundary, clipped at the shoreline), in open water; normal for an ocean, bay, "
                    "sound or lake outfall")
                cnt['rows offshore (kept)'] += 1
            if prob:
                row['coords_problem'] = prob
                row['echo_lat'], row['echo_lon'], row['echo_coords_from'] = row['lat'], row['lon'], row['coords_from']
                row['lat'] = row['lon'] = None
                row['coords_from'] = None
                cnt['rows with coords_problem'] += 1
        out_rows.append(row)

# ------------------------------------------------------------------ supplement from the national dataset part 1
SUPP_ACTIVE_TYPES = {'NPD', 'SIN', 'GPC'}
for p, c in sorted(SUPP.items()):
    pm, fac = c['permit'], c.get('facility') or {}
    if p in perm or pm['PERMIT_STATUS_CODE'] not in ACTIVE or pm['PERMIT_TYPE_CODE'] not in SUPP_ACTIVE_TYPES:
        cnt['supplement permits skipped (in file, inactive or not NPD/SIN/GPC)'] += 1
        continue
    b = 'potw_component' if 'POTW' in c['components'] else ('potw_indicator' if (pm.get('FACILITY_TYPE_INDICATOR') or '').upper() == 'POTW' else 'tracked_operator')
    state = fac.get('STATE_CODE') or p[:2]
    rows_p, kept_feats = [], 0
    feats_xy = [f for f in c['features'] if num(f['lat']) is not None and num(f['lon']) is not None]
    for f in feats_xy:
        k = nf(f['outfall'])
        if (p, k) in inv:
            cnt['supplement features in CSO inventory'] += 1
            continue
        lim = SUPP_LIMITS.get(f'{p}|{k}') or {}
        types = lim.get('types') or []
        names = lim.get('names') or []
        if types and 'EXO' not in types:
            cnt['supplement features of another type (' + '/'.join(types) + ')'] += 1
            continue
        if not types and re.match(r'^(INF|IN\d|SUM|MON|UP|DN|BS|SL|LA|RW)', k):
            cnt['supplement untyped features skipped by number (influent, sum, monitoring ...)'] += 1
            continue
        if 'CSO' in c['components'] and names and any(CSO_NAME.search(n) for n in names) and all(WET_NAME.search(n) for n in names):
            cso_suspects.append({'npdes_permit': p, 'permittee': fac.get('FACILITY_NAME'), 'state': state,
                                 'outfall': f['outfall'], 'lat': num(f['lat']), 'lon': num(f['lon']),
                                 'receiving_water_echo': pm.get('STATE_WATER_BODY_NAME') or None, 'limit_set_names': names,
                                 'why': 'CSO permit component; ICIS limit set named as a combined sewer overflow; not in the National CSO Inventory'})
            continue
        lat, lon = num(f['lat']), num(f['lon'])
        cc = catch.get((p, k)) or {}
        row = {'npdes_permit': p, 'permittee': (fac.get('FACILITY_NAME') or '').strip() or None,
               'permit_name': (pm.get('PERMIT_NAME') or '').strip() or None, 'state': state,
               'city': (fac.get('CITY') or '').strip() or None, 'outfall': f['outfall'], 'outfall_name': None,
               'outfall_status': None, 'feature_type': 'EXO' if 'EXO' in types else None,
               'receiving_water_echo': (pm.get('STATE_WATER_BODY_NAME') or '').strip() or None,
               'reach_id': cc.get('REACHCODE') or None, 'reach_gnis_name': cc.get('GNIS_NAME') or None,
               'nhdplus_id': cc.get('NHDPLUSID') or None, 'lat': lat, 'lon': lon,
               'coords_from': 'permitted_feature' if lat is not None and lon is not None else None,
               'has_limits': bool(lim)}
        if names:
            row['limit_set_names'] = names[:4]
        if not types:
            row['feature_type_note'] = 'ICIS gives no type for this feature (no limit set); it may not be an external outfall'
        rows_p.append(row)
        kept_feats += 1
    if not rows_p and not feats_xy:
        lat, lon = num(fac.get('GEOCODE_LATITUDE')), num(fac.get('GEOCODE_LONGITUDE'))
        cc = catch.get((p, 'BESTPICK')) or {}
        if lat is None and cc:
            lat, lon = num(cc.get('LATITUDE83')), num(cc.get('LONGITUDE83'))
        rows_p.append({'npdes_permit': p, 'permittee': (fac.get('FACILITY_NAME') or '').strip() or None,
                       'permit_name': (pm.get('PERMIT_NAME') or '').strip() or None, 'state': state,
                       'city': (fac.get('CITY') or '').strip() or None, 'outfall': None, 'outfall_name': None,
                       'outfall_status': None, 'feature_type': None,
                       'receiving_water_echo': (pm.get('STATE_WATER_BODY_NAME') or '').strip() or None,
                       'reach_id': cc.get('REACHCODE') or None, 'reach_gnis_name': cc.get('GNIS_NAME') or None,
                       'nhdplus_id': cc.get('NHDPLUSID') or None, 'lat': lat, 'lon': lon,
                       'coords_from': 'facility' if lat is not None and lon is not None else None,
                       'coords_note': "the facility's point (ICIS_FACILITIES geocode): ICIS has no outfall coordinates "
                                      "for this permit, so this is a point for the treatment plant or the permittee's "
                                      "address, not the outfall's own point"})
        cnt['supplement permits with facility point only'] += 1
    if not rows_p:
        cnt['supplement permits with no row (features all CSO or other types)'] += 1
        continue
    universe[p] = b
    pts = C((r['lat'], r['lon']) for r in rows_p if r['lat'] is not None)
    for row in rows_p:
        row.update({'in_icis': 'YES', 'permit_status': pm['PERMIT_STATUS_CODE'], 'permit_type': pm['PERMIT_TYPE_CODE'],
                    'permit_components': c['components'], 'plant_basis': b,
                    'facility_type': (pm.get('FACILITY_TYPE_INDICATOR') or None),
                    'major_minor': {'M': 'Major', 'N': 'Minor'}.get(pm.get('MAJOR_MINOR_STATUS_FLAG') or '', None),
                    'design_flow_mgd': num(pm.get('TOTAL_DESIGN_FLOW_NMBR')),
                    'echo_url': (f"https://echo.epa.gov/detailed-facility-report?fid={fac['FACILITY_UIN']}"
                                 if fac.get('FACILITY_UIN') else echo_url(p)),
                    'outfall_kind': 'plant', 'country': 'US', 'source': SUPP_SOURCE_ID, 'fetched_at': SUPP_FETCHED_AT,
                    'supplement_note': 'active POTW permit in ICIS_PERMITS that the ECHO discharge-points file omits'})
        if p in tracked:
            row['discharger_ids'] = sorted(set(tracked[p]))
        if row['lat'] is not None:
            n = pts[(row['lat'], row['lon'])]
            if n > 1:
                row['point_shared_by'] = n
                if row['coords_from'] == 'permitted_feature':
                    row['coords_note'] = f"{n} of this permit's outfalls share this one point in ICIS"
            key = (p, row['outfall'])
            prob = coords_problem(row['state'], row['lat'], row['lon'], row.get('receiving_water_echo'), key)
            if key in OFFSHORE and OFFSHORE[key] > 0.5:
                row['coords_note'] = ((row.get('coords_note') + '; ') if row.get('coords_note') else '') + (
                    f"offshore: EPA's point is about {OFFSHORE[key]} km outside the state's land outline (Census "
                    "cartographic boundary, clipped at the shoreline), in open water; normal for an ocean, bay, "
                    "sound or lake outfall")
            if prob:
                row['coords_problem'] = prob
                row['echo_lat'], row['echo_lon'], row['echo_coords_from'] = row['lat'], row['lon'], row['coords_from']
                row['lat'] = row['lon'] = None
                row['coords_from'] = None
                cnt['rows with coords_problem'] += 1
        out_rows.append(row)
        cnt['supplement rows'] += 1
    cnt['supplement permits with rows'] += 1

# ------------------------------------------------------------------ CSO features ICIS has that the inventory lacks:
# also permits with a CSO component and no inventory row at all
cso_comp_no_inv = C()
for p, e in perm.items():
    if 'CSO' in e['comps'] and e['r']['PERMIT_STATUS_CODE'] in ACTIVE and p not in inv_permits:
        cso_comp_no_inv[e['r']['STATE_CODE']] += 1

# ------------------------------------------------------------------ write
by_state = C(r['state'] for r in out_rows)
doc = {
    'source': ('EPA ECHO ICIS-NPDES Discharge Points (npdes_outfalls_layer.zip -> NPDES_OUTFALLS_LAYER.csv, file dated '
               '2026-11-01, fetched ' + FETCHED_AT + '); reach codes from ECHO NPDES Catchment Indexing '
               '(npdes_attains_downloads.zip -> NPDES_CATCHMENTS.csv, dated 2026-10-31); CSO features removed by '
               'joining EPA\'s National CSO Inventory (ALL_CSO_downloads.zip, dated 2026-10-31); limit set names from '
               'the ICIS-NPDES national permit limit dataset (npdes_limits.zip); plus rows with source '
               'fed-echo-icis-npdes-national-dataset for active POTW permits that ICIS_PERMITS (npdes_downloads.zip, '
               'dated 2026-11-01, fetched ' + SUPP_FETCHED_AT + ') holds and the discharge-points file omits, their '
               'points from NPDES_PERM_FEATURE_COORDS and the facility geocode in ICIS_FACILITIES. Raw copies: '
               'data/raw/icis-npdes/2026-11-03/ (README.md there). Report: research/federal/plant-outfalls.md.'),
    'rule': ('Permits: status EFF/ADC/EXP and (permit component POTW, or SIC 4952 / NAICS 221320 with a public owner '
             'type and not a stormwater-only permit), individual (NPD/SIN) or general (GPC); plus every permit of an '
             'operator in data/dischargers.json that is active in ICIS; plus active POTW permits (component POTW or facility '
             'type indicator POTW) that only the national dataset lists. Rows: one per permitted feature of type '
             '"External Outfall" with its own coordinates (coords_from permitted_feature), except features in the '
             'National CSO Inventory (any PF_CHARACTER: CSO, TCS, CLS) and features held back as likely CSOs '
             '(cso_features_not_in_inventory); a permit with no external outfall coordinates gets one row at the '
             'facility\'s point (coords_from facility, outfall null). No water matching yet. outfall_status is null: '
             'this file carries no ICIS characteristic or open/closed status for plant features; has_limits says '
             'whether the ICIS permit limit dataset holds any limit set for the feature (a hint that it is a monitored '
             'discharge point, not a status) and limit_set_names gives up to four of their names.'),
    'fetched_at': FETCHED_AT,
    'count': len(out_rows),
    'counts': {
        'by_state': dict(sorted(by_state.items())),
        'coords_from': dict(C(str(r['coords_from']) for r in out_rows)),
        'plant_basis_permits': dict(C(universe.values())),
        'permits': len(universe),
        'permits_with_rows': len({r['npdes_permit'] for r in out_rows}),
        'build': dict(cnt),
        'excluded_sewer_type_permits': dict(excluded),
        'duplicate_feature_rows_in_source': dups,
    },
    'outfalls': out_rows,
    'cso_features_not_in_inventory': cso_suspects,
}
out_rows.sort(key=lambda r: (r['state'] or '', r['npdes_permit'], str(r.get('outfall') or '')))
cso_suspects.sort(key=lambda r: (r['state'] or '', r['npdes_permit'], str(r.get('outfall') or '')))
with open(OUT, 'w') as fh:
    fh.write('{\n')
    for k, v in doc.items():
        if k in ('outfalls', 'cso_features_not_in_inventory'):
            continue
        fh.write(json.dumps(k) + ': ' + json.dumps(v, ensure_ascii=False) + ',\n')
    fh.write('"cso_features_not_in_inventory": [\n' + ',\n'.join(json.dumps(r, ensure_ascii=False) for r in cso_suspects)
             + '\n],\n')
    fh.write('"outfalls": [\n' + ',\n'.join(json.dumps(r, ensure_ascii=False) for r in out_rows) + '\n]\n}\n')
report = {
    'cso_suspects_by_state': dict(C(r['state'] for r in cso_suspects)),
    'cso_component_permits_without_inventory_rows_by_state': dict(cso_comp_no_inv),
    'universe': len(universe),
}
json.dump(report, open(REPORT, 'w'), indent=1)
print(json.dumps(doc['counts'], indent=1))
print(json.dumps(report, indent=1))
