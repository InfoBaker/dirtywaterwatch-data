import json, sys, urllib.parse, urllib.request, time
ids = open(sys.argv[1]).read().split()
out = {}
B = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/FRS_INTERESTS_NPDES/FeatureServer/0/query'
for i in range(0, len(ids), 150):
    chunk = ids[i:i + 150]
    where = 'PGM_SYS_ID IN (' + ','.join("'" + x + "'" for x in chunk) + ')'
    data = urllib.parse.urlencode({'where': where, 'outFields': 'REGISTRY_ID,PGM_SYS_ID', 'returnGeometry': 'false',
                                   'f': 'json', 'resultRecordCount': 2000}).encode()
    for attempt in range(3):
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(B, data=data), timeout=90))
            break
        except Exception as e:
            print('retry', e, file=sys.stderr); time.sleep(3)
    for f in d.get('features', []):
        a = f['attributes']
        out.setdefault(a['PGM_SYS_ID'], a['REGISTRY_ID'])
print(len(ids), 'found', len(out), file=sys.stderr)
json.dump(out, open(sys.argv[2], 'w'))
