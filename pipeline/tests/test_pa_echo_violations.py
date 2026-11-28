"""PA ECHO: source precision, range integrity, retention and links."""
import csv
import io
import json
import zipfile
from pathlib import Path
import pytest
import common
from ingest import pa_echo_violations as M
from ingest.echo_zip import RemoteZip
FIX = Path(__file__).parent / 'fixtures' / 'pa_echo_violations'

def rows(name='violations.csv'):
    return list(csv.DictReader((FIX / name).open()))

def records():
    selected, _ = M.select_rows(rows(), rows('sics.csv'))
    return M.normalize(selected, '2026-11-28T15:00:00Z', {}, {}, sic_rows=rows('sics.csv'))

def test_real_rows_selection_precision_and_absent_fields():
    recs = records()
    by = {r['source_record_id']: r for r in recs}
    r = by['3687608730']
    assert r['npdes_permit'] == 'PA0025984' and r['event_type'] == 'bypass'
    assert r['started_at'] == '2026-03-07T00:00:00-05:00'
    assert r['time_precision'] == 'day' and r['raw']['time_zone'] == 'America/New_York'
    assert r['raw']['source_end_date'] == '07/17/2026'
    assert r['ended_at'] is None  # regulatory closure is not proof of discharge end
    assert all(r[k] is None for k in ('published_at','reported_at','volume_gal','volume_text','waterbody_text','lat','lon'))
    assert r['water_slugs'] == [] and r['raw']['_placement'] == 'named_water_only'
    assert '3671083220' not in by  # industrial D0011 without sewerage SIC
    assert '3641054984' not in by  # reporting violation
    assert all(r['raw']['row']['NPDES_ID'].startswith('PA') for r in recs)
    summer = next(r for r in recs if r['raw']['row']['SINGLE_EVENT_VIOLATION_DATE'] == '06/26/2024')
    assert summer['started_at'].endswith('-04:00')

def test_identity_revisions_bad_dates_and_public_text():
    selected, _ = M.select_rows(rows(), rows('sics.csv'))
    old = {r['event_id']: r for r in records()}
    selected[0]['SINGLE_EVENT_END_DATE'] = '11/28/2026'
    selected[0]['SINGLE_EVENT_VIOLATION_COMMENT'] = 'Overflow reached Example Creek; pump stopped.'
    b = M.normalize(list(reversed(selected)), '2026-11-29T15:00:00Z', old, {}, sic_rows=rows('sics.csv'))
    assert set(old) == {r['event_id'] for r in b}
    r = next(r for r in b if r['source_record_id'] == selected[0]['NPDES_VIOLATION_ID'])
    assert r['raw']['row']['SINGLE_EVENT_VIOLATION_COMMENT'] == selected[0]['SINGLE_EVENT_VIOLATION_COMMENT']
    assert r['raw']['_first_seen_at'] == old[r['event_id']]['raw']['_first_seen_at']
    assert r['published_at'] is None
    selected[0]['SINGLE_EVENT_VIOLATION_DATE'] = 'invalid'
    r = M.normalize(selected[:1], '2026-11-29T15:00:00Z', old, {}, sic_rows=rows('sics.csv'))[0]
    assert r['started_at'] is None and r['parse_error'] and r['event_type'] == 'unknown'

def test_links_preserve_records_without_equating_ssos_and_csos():
    recs = records()
    local = dict(event_id=M.ALCOSAN_POWER_OUTAGE, source_id='pa-alcosan', npdes_permit='PA0025984',
                 event_type='bypass', started_at='2026-03-06T18:00:00-05:00', duplicate_of=None)
    M.link_records(recs, [local])
    r = next(r for r in recs if r['source_record_id'] == '3687608730')
    assert r['duplicate_of'] == local['event_id'] and r['raw']['_other_source_record'] == local['event_id']
    assert 'date' in r['raw']['_duplicate_basis']
    M.link_records(recs, [{**local, 'event_id': 'pa-alcosan:later', 'started_at': '2026-06-01T12:00:00-04:00'}])
    assert r['duplicate_of'] is None
    for source in ('pa-phila-csocast', 'pa-erie', 'pa-alcosan'):
        sso = next(r for r in recs if r['event_type'] == 'sso')
        candidate = {**local, 'event_id': source + ':test', 'source_id': source,
                     'npdes_permit': sso['npdes_permit'], 'event_type': 'cso', 'started_at': sso['started_at']}
        M.link_records(recs, [candidate])
        assert sso['duplicate_of'] != candidate['event_id']
        assert candidate['event_id'] in sso['raw']['possible_matches']
    M.link_records(recs, [])
    group = [r for r in recs if r['npdes_permit'] == 'PA0026671' and r['started_at'][:10] == '2024-06-26']
    assert len(group) == 2 and sum(not r['duplicate_of'] for r in group) == 1

class Response:
    def __init__(self, data=b'', status=206, headers=None):
        self.data, self.status_code, self.headers = data, status, headers or {}
    def raise_for_status(self):
        if self.status_code >= 400: raise ValueError('HTTP failure')
    def iter_content(self, chunk_size): yield self.data
    def close(self): pass

class Session:
    def __init__(self, payload, ignore=False, truncate=False):
        self.payload, self.calls, self.ignore, self.truncate = payload, [], ignore, truncate
    def get(self, url, headers, **kwargs):
        self.calls.append(headers)
        lo, hi = map(int, headers['Range'][6:].split('-'))
        data = self.payload[lo:hi+1]
        return Response(data[:-1] if self.truncate else data, 200 if self.ignore else 206,
                        {'Content-Range': f'bytes {lo}-{hi}/{len(self.payload)}'})

def test_range_zip_integrity():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('NPDES_SE_VIOLATIONS.csv', (FIX / 'violations.csv').read_bytes())
        z.writestr('NPDES_SICS.csv', (FIX / 'sics.csv').read_bytes())
    payload = stream.getvalue()
    s = Session(payload)
    with zipfile.ZipFile(RemoteZip(s, M.ZIP_URL, len(payload), 'v1', block_size=128)) as z:
        assert z.read('NPDES_SE_VIOLATIONS.csv') == (FIX / 'violations.csv').read_bytes()
    assert len(s.calls) > 2 and all(c['If-Match'] == 'v1' for c in s.calls)
    for bad in (Session(payload, ignore=True), Session(payload, truncate=True)):
        with pytest.raises(ValueError): RemoteZip(bad, M.ZIP_URL, len(payload), 'v1').read(10)

def test_failure_and_missing_rows_retain_history(tmp_path, monkeypatch):
    monkeypatch.setattr(M, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(M, 'registry', lambda: {})
    monkeypatch.setattr(common, 'EVENTS_DIR', tmp_path)
    selected, stats = M.select_rows(rows(), rows('sics.csv'))
    snap = {'rows': selected, 'sic_rows': rows('sics.csv'), 'stats': stats, 'last_modified': None, 'read_at': '2026-11-28T15:00:00Z'}
    monkeypatch.setattr(M, 'fetch_snapshot', lambda **kw: snap)
    assert M.main([]) == 0
    path = tmp_path / (M.SOURCE_ID + '.json')
    old = json.loads(path.read_text())
    def fail(**kw): raise ValueError('failed request token=secret')
    monkeypatch.setattr(M, 'fetch_snapshot', fail)
    assert M.main([]) == 1
    failed = json.loads(path.read_text())
    assert failed['records'] == old['records'] and failed['last_ok_at'] == old['last_ok_at'] and not failed['ok']
    assert 'secret' not in failed['error']
    monkeypatch.setattr(M, 'fetch_snapshot', lambda **kw: {**snap, 'rows': selected[:1]})
    assert M.main([]) == 0
    kept = json.loads(path.read_text())
    assert len(kept['records']) == len(old['records'])
    assert kept['meta']['kept_from_previous'] == len(selected)-1

def test_named_water_in_real_comment_is_kept_without_invented_cause_or_volume():
    r = next(r for r in records() if r['source_record_id'] == '3633971227')
    assert r['waterbody_text'] == 'Singer Run'
    assert r['raw']['overflow_point'] == 'manhole 575'
    assert r['volume_gal'] is None and 'cause' not in r['raw']
    assert r['water_slugs'] == []  # name is reported, no coordinates supplied


def test_selection_reads_all_rows_and_excludes_other_states():
    source = rows()
    outside = {**source[0], 'NPDES_ID': 'NJ0025984', 'NPDES_VIOLATION_ID': 'outside'}
    selected, stats = M.select_rows([outside] + source, rows('sics.csv'))
    assert all(r['NPDES_ID'].startswith('PA') for r in selected)
    assert stats['state_violation_rows'] == len(source)
    broken = {**selected[0], 'VIOLATION_DESC': 'changed'}
    with pytest.raises(ValueError, match='conflicting'):
        M.select_rows([selected[0], broken], rows('sics.csv'))
    with pytest.raises(ValueError, match='no sewerage'):
        M.select_rows(source, [])
    with pytest.raises(ValueError, match='identity'):
        M.select_rows([{**selected[0], 'NPDES_VIOLATION_ID': ''}], rows('sics.csv'))


def test_csv_missing_columns_and_truncation_fail_closed():
    for content in ('NPDES_ID\nPA0025984\n', 'NPDES_ID,SIC_CODE\nPA0025984\n'):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z: z.writestr('sics.csv', content)
        with zipfile.ZipFile(data) as z, pytest.raises(ValueError):
            list(M.csv_rows(z, 'sics.csv', {'NPDES_ID', 'SIC_CODE'}))

def test_fetch_snapshot_validates_cache_and_keeps_sic_join(tmp_path, monkeypatch):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(M.SE_MEMBER, (FIX / 'violations.csv').read_bytes())
        z.writestr(M.SIC_MEMBER, (FIX / 'sics.csv').read_bytes())
    class FetchSession(Session):
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def head(self, *args, **kwargs):
            return Response(status=200, headers={'Content-Length': str(len(self.payload)), 'ETag': 'v1'})
    session = FetchSession(payload.getvalue())
    monkeypatch.setattr(M.requests, 'Session', lambda: session)
    monkeypatch.setattr(M, 'CACHE_PATH', tmp_path / 'cache.json')
    monkeypatch.setattr(M, 'save_raw', lambda *args: None)
    snap = M.fetch_snapshot()
    assert snap['sic_rows']
    before = len(session.calls)
    again = M.fetch_snapshot()
    assert again == snap and len(session.calls) == before
    assert M.fetch_snapshot(from_raw=True) == snap

def test_real_utility_records_only_link_the_documented_alcosan_incident():
    recs = records()
    local = json.loads((FIX / 'utility_records.json').read_text())
    M.link_records(recs, local)
    external = [r for r in recs if r['duplicate_of'] and not r['duplicate_of'].startswith(M.SOURCE_ID)]
    assert [(r['source_record_id'], r['duplicate_of']) for r in external] == [('3687608730', M.ALCOSAN_POWER_OUTAGE)]
    # No source is overwritten and EPA's dates remain its own.
    assert external[0]['started_at'] == '2026-03-07T00:00:00-05:00'
    assert external[0]['ended_at'] is None


def test_no_water_name_does_not_inherit_the_plant_receiving_water():
    from build.status import Resolver
    r = next(r for r in records() if r['source_record_id'] == '3687608730')
    resolver = Resolver({'ohio-river-pa': {'slug': 'ohio-river-pa', 'name': 'Ohio River', 'state': 'PA'}},
                        [{'npdes_permit': 'PA0025984', 'outfall': '001', 'water_slug': 'ohio-river-pa'}],
                        discharger_waters={'PA0025984': ['ohio-river-pa']})
    assert resolver.resolve(r)['water_slugs'] == []


@pytest.mark.parametrize('stage', ['select', 'normalize'])
def test_real_industrial_bypasses_require_sewerage_evidence(stage):
    source = rows() + rows('industrial_bypasses.csv')
    sics = rows('sics.csv') + rows('industrial_sics.csv')
    if stage == 'select':
        selected, _ = M.select_rows(source, sics)
        ids = {r['NPDES_VIOLATION_ID'] for r in selected}
    else:
        # Old cached snapshots contain these rows, even after selection is fixed.
        normalized = M.normalize(source, '2026-11-28T15:00:00Z', {}, {}, sic_rows=sics)
        ids = {r['source_record_id'] for r in normalized}
    assert not ids & {'3637746096', '3690502307'}
    assert '3687608730' in ids  # real sewerage-permit bypass still included
    # Any SIC slot can establish sewerage, not just the primary industry.
    sics.append({'NPDES_ID': 'PA0004073', 'SIC_CODE': '4952', 'PRIMARY_INDICATOR_FLAG': 'N'})
    selected, _ = M.select_rows(source, sics)
    assert '3690502307' in {r['NPDES_VIOLATION_ID'] for r in selected}


@pytest.mark.parametrize('snapshot_has_industrial_rows', [True, False])
def test_replay_corrects_previously_published_industrial_bypasses(tmp_path, monkeypatch, snapshot_has_industrial_rows):
    source, sics = rows(), rows('sics.csv')
    industrial = rows('industrial_bypasses.csv')
    selected, stats = M.select_rows(source, sics)
    original = M.normalize(selected, '2026-11-28T15:00:00Z', {}, {}, sic_rows=sics)
    # Reproduce records written by the earlier reader, retaining its published IDs.
    legacy = [common.event(source_id=M.SOURCE_ID, source_record_id=r['NPDES_VIOLATION_ID'],
                           event_type='bypass', status='unknown', npdes_permit=r['NPDES_ID'],
                           started_at=M.day_iso(r['SINGLE_EVENT_VIOLATION_DATE']),
                           raw={'row': r, 'sic_rows': [s for s in rows('industrial_sics.csv')
                                                     if s['NPDES_ID'] == r['NPDES_ID']]}) for r in industrial]
    path = tmp_path / (M.SOURCE_ID + '.json')
    common.write_json(path, {'records': original + legacy})
    snapshot = {'rows': selected + industrial if snapshot_has_industrial_rows else selected[:1],
                'sic_rows': sics + rows('industrial_sics.csv') if snapshot_has_industrial_rows else sics,
                'stats': stats, 'read_at': '2026-11-28T15:00:00Z'}
    monkeypatch.setattr(M, 'CACHE_PATH', tmp_path / 'cache.json')
    common.write_json(M.CACHE_PATH, snapshot)
    monkeypatch.setattr(M, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(common, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(M, 'registry', lambda: {})
    assert M.main(['--from-raw']) == 0
    actual = json.loads(path.read_text())['records']
    assert {r['event_id'] for r in actual} == {r['event_id'] for r in original}
    old = {r['event_id']: r for r in original}
    for r in actual:
        for key in ('started_at', 'ended_at', 'reported_at', 'published_at'):
            assert r[key] == old[r['event_id']][key]
        assert r['raw']['_first_seen_at'] == old[r['event_id']]['raw']['_first_seen_at']


def test_partial_sic_refresh_retains_supported_historical_bypass(tmp_path, monkeypatch):
    source = [r for r in rows() if r['NPDES_ID'] == 'PA0025984']
    # Synthetic second SIC on the real permit reproduces an incomplete later table.
    sics = [r for r in rows('sics.csv') if r['NPDES_ID'] == 'PA0025984']
    other_sic = {'NPDES_ID': 'PA0025984', 'SIC_CODE': '4941',
                 'SIC_DESC': 'Water Supply', 'PRIMARY_INDICATOR_FLAG': 'N'}
    sics.append(other_sic)
    selected, stats = M.select_rows(source, sics)
    snapshot = {'rows': selected, 'sic_rows': sics, 'stats': stats,
                'read_at': '2026-11-28T15:00:00Z'}
    monkeypatch.setattr(M, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(common, 'EVENTS_DIR', tmp_path)
    monkeypatch.setattr(M, 'registry', lambda: {})
    monkeypatch.setattr(M, 'fetch_snapshot', lambda **kw: snapshot)
    assert M.main([]) == 0
    path = tmp_path / (M.SOURCE_ID + '.json')
    original = {r['event_id']: r for r in json.loads(path.read_text())['records']}
    expected_ids = {f'{M.SOURCE_ID}:3656108544', f'{M.SOURCE_ID}:3687608730'}
    assert set(original) == expected_ids

    snapshot = {**snapshot, 'rows': [r for r in selected if r['VIOLATION_CODE'] == 'A0020'],
                'sic_rows': [other_sic], 'read_at': '2026-11-29T15:00:00Z'}
    # Repeated refreshes must keep the archived positive evidence as well as the ID.
    for _ in range(2):
        assert M.main([]) == 0
        refreshed = json.loads(path.read_text())
        actual = {r['event_id']: r for r in refreshed['records']}
        assert set(actual) == expected_ids
        assert refreshed['meta']['selected_rows'] == 1
        assert refreshed['meta']['kept_from_previous'] == 1
        for eid, r in actual.items():
            for key in ('source_record_id', 'started_at', 'ended_at', 'reported_at', 'published_at'):
                assert r[key] == original[eid][key]
            assert r['raw']['_first_seen_at'] == original[eid]['raw']['_first_seen_at']
        bypass = actual[f'{M.SOURCE_ID}:3687608730']
        assert bypass['raw']['sic_rows'] == original[bypass['event_id']]['raw']['sic_rows']
        assert bypass['raw']['source_end_date'] == original[bypass['event_id']]['raw']['source_end_date']
        assert bypass['raw']['_missing_from_source_since']


def singer_variants(second_comment='Leak at manhole 575 into Example Creek'):
    # Only the first row is real; the second is a synthetic same-permit/day report.
    singer = next(r for r in rows() if r['NPDES_VIOLATION_ID'] == '3633971227')
    second = {**singer, 'NPDES_VIOLATION_ID': 'synthetic-second',
              'SINGLE_EVENT_VIOLATION_COMMENT': second_comment}
    return M.normalize([singer, second], '2026-11-28T15:00:00Z', {}, {})


@pytest.mark.parametrize('conflict', ['water', 'outfall', 'manhole'])
def test_distinct_locations_are_not_confirmed_duplicates(conflict):
    comment = ('Leak at manhole 576 into Singer Run' if conflict == 'manhole' else
               'Leak at manhole 575 into Singer Run' if conflict == 'outfall' else
               'Leak at manhole 575 into Example Creek')
    recs = singer_variants(comment)
    if conflict == 'outfall':
        recs[0]['outfall_id'], recs[1]['outfall_id'] = '001', '002'
    M.link_records(recs, [])
    assert all(r['duplicate_of'] is None for r in recs)
    assert all('count_basis' not in r['raw'] for r in recs)


@pytest.mark.parametrize('conflict', ['water', 'outfall', 'manhole'])
def test_utility_location_conflicts_remain_possible_only(conflict):
    r = singer_variants()[0]
    r['outfall_id'] = '001'
    candidate = common.event(source_id='pa-alcosan', source_record_id='synthetic-location',
                             npdes_permit=r['npdes_permit'], event_type='sso', started_at=r['started_at'],
                             time_precision='day', waterbody_text='Singer Run', outfall_id='001',
                             raw={'overflow_point': 'manhole 575'})
    if conflict == 'water':
        candidate['waterbody_text'] = 'Example Creek'
    elif conflict == 'outfall':
        candidate['outfall_id'] = '002'
    else:
        candidate['raw']['overflow_point'] = 'manhole 576'
    M.link_records([r], [candidate])
    assert r['duplicate_of'] is None
    assert r['raw']['possible_matches'] == [candidate['event_id']]


@pytest.mark.parametrize('bridge', ['epa', 'utility'])
def test_missing_location_cannot_bridge_conflicting_waters(bridge):
    from copy import deepcopy
    from itertools import permutations
    recs = singer_variants()
    unknown = common.event(source_id=M.SOURCE_ID if bridge == 'epa' else 'pa-alcosan',
                           source_record_id='synthetic-unknown-place', npdes_permit=recs[0]['npdes_permit'],
                           event_type='sso', started_at=recs[0]['started_at'], time_precision='day')
    local = [unknown] if bridge == 'utility' else []
    if bridge == 'epa':
        recs.append(unknown)
    for order in permutations(recs):
        group = deepcopy(list(order))
        M.link_records(group, local)
        assert all(r['duplicate_of'] is None for r in group)


def test_compatible_locations_keep_deterministic_links():
    recs = singer_variants('Leak at manhole 575 into Singer Run')
    ids = {r['event_id'] for r in recs}
    M.link_records(recs, [])
    assert recs[1]['duplicate_of'] == recs[0]['event_id']
    candidate = common.event(source_id='pa-alcosan', source_record_id='synthetic-compatible',
                             npdes_permit=recs[0]['npdes_permit'], event_type='sso',
                             started_at=recs[0]['started_at'], time_precision='day',
                             waterbody_text='Singer Run', raw={'overflow_point': 'manhole 575'})
    M.link_records(list(reversed(recs)), [candidate])
    assert all(r['duplicate_of'] == candidate['event_id'] for r in recs)
    assert {r['event_id'] for r in recs} == ids


def test_documented_alcosan_link_also_respects_location_conflicts():
    r = next(r for r in records() if r['source_record_id'] == '3687608730')
    # Synthetic location evidence must override even the incident-specific match.
    r['waterbody_text'] = 'Example Creek'
    candidate = common.event(source_id='pa-alcosan', source_record_id=M.ALCOSAN_POWER_OUTAGE.split(':', 1)[1],
                             npdes_permit=r['npdes_permit'], event_type='bypass',
                             started_at='2026-03-06T18:00:00-05:00', waterbody_text='Ohio River')
    M.link_records([r], [candidate])
    assert r['duplicate_of'] is None
