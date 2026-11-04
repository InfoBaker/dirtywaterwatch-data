"""Stream NPDES_LIMITS.csv out of npdes_limits.zip and keep, per (permit, feature number), the limit set names,
whether any limit is current, and the parameter codes of interest. Output: JSON {permit|feature: {...}}.
Usage: python -I limits_pass.py <npdes_limits.zip> <permits.txt> <out.json> <today YYYY-MM-DD>"""
import csv, io, json, sys, zipfile, datetime

zpath, permits_path, out_path, today = sys.argv[1:5]
want = set(open(permits_path).read().split())
z = zipfile.ZipFile(zpath)
name = [n for n in z.namelist() if n.lower().endswith('.csv')][0]
print('reading', name, file=sys.stderr)
today_d = datetime.date.fromisoformat(today)


def nf(x):
    s = ''.join(str(x or '').split()).upper()
    return s.lstrip('0') or ('0' if s else '')


def parse_date(s):
    s = (s or '').strip()
    for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%d-%b-%y', '%m/%d/%Y %H:%M:%S'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


out = {}
n = 0
with z.open(name) as fh:
    rd = csv.DictReader(io.TextIOWrapper(fh, encoding='utf-8', errors='replace', newline=''))
    for r in rd:
        n += 1
        p = (r.get('EXTERNAL_PERMIT_NMBR') or '').strip().upper()
        if p not in want:
            continue
        k = p + '|' + nf(r.get('PERM_FEATURE_NMBR'))
        e = out.setdefault(k, {'names': [], 'types': [], 'current': False, 'params': [], 'end_max': None})
        nm = (r.get('LIMIT_SET_NAME') or '').strip()
        if nm and nm not in e['names'] and len(e['names']) < 6:
            e['names'].append(nm)
        t = (r.get('PERM_FEATURE_TYPE_CODE') or '').strip()
        if t and t not in e['types']:
            e['types'].append(t)
        pc = (r.get('PARAMETER_CODE') or '').strip()
        if pc in ('51484', '81381', '82220', '50050', '74076', '31616', '51040', '50047') and pc not in e['params']:
            e['params'].append(pc)
        end = parse_date(r.get('LIMIT_END_DATE'))
        if end and (e['end_max'] is None or end.isoformat() > e['end_max']):
            e['end_max'] = end.isoformat()
        if (r.get('LIMIT_SET_STATUS_FLAG') or '').strip().upper() == 'A' and (end is None or end >= today_d):
            e['current'] = True
        if n % 2000000 == 0:
            print(n, len(out), file=sys.stderr)
print('rows', n, 'kept features', len(out), file=sys.stderr)
print('columns', rd.fieldnames, file=sys.stderr)
json.dump(out, open(out_path, 'w'))
