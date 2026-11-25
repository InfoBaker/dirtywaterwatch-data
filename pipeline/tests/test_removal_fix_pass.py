"""Review regressions: public inputs, historical identities and publication boundaries."""
import ast
import importlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
from datetime import UTC, datetime

import pytest
import common
from export.removals import RemovalList

ROOT = Path(__file__).resolve().parents[2]

def request(kind, match, **kw):
    return {'id': 'test-request', 'added': '2026-11-24', 'kind': kind, 'match': match, **kw}

def historical(module, names, namespace):
    """Read the actual pre-change functions; no copied expected hash or live history."""
    code = subprocess.check_output(['git', 'show', f'e70b9758:pipeline/{module}.py'], cwd=ROOT, text=True)
    tree = ast.parse(code)
    chosen = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    ns = dict(namespace)
    exec(compile(ast.Module(body=chosen, type_ignores=[]), '<historical functions>', 'exec'), ns)
    return ns

@pytest.mark.parametrize('location', ['123 SAMPLE ROAD NE', '@HAWAII AVE @TAYLOR ST NE', 'private location'])
def test_dc_reread_keeps_precommit_identity_and_old_removal(location):
    from ingest import dc_water_sso as D
    old = historical('ingest/dc_water_sso', ['safe_location', 'row_id'], vars(D))
    row = {'id': '2026-01-20T00:44:24.607', 'location': location, 'volume_as_given': '10'}
    oldrow = {**row, 'location': old['safe_location'](location)[0]}
    eid = D.SOURCE_ID + ':' + old['row_id'](oldrow)
    assert D.SOURCE_ID + ':' + D.row_id(row) == eid
    p = RemovalList([request('record', eid)])
    assert p.apply({'event_id': D.SOURCE_ID + ':' + D.row_id(row), 'source_id': D.SOURCE_ID}) is None

def test_waterloo_reread_home_keeps_precommit_identity():
    from ingest import ia_waterloo_sso as W, ia_id_privacy as I
    old = historical('ingest/ia_id_privacy', ['home_place'], vars(I))
    parsed = {'text': 'Overflow at a private home.', 'location': '123 Sample Road',
              'start': datetime(2026, 1, 20, 12, tzinfo=UTC)}
    assert old['home_place'](parsed['text'])
    previous = [{'source_record_id': '2026-01-20T1200~notice', 'raw': {'notice': parsed['text'], 'location': None}}]
    assert W.assign_ids([parsed], previous) == ['2026-01-20T1200~notice']

def test_dc_download_keeps_customer_identifier_and_description():
    from ingest import dc_water_sso as D
    rows, _ = D.parse('PremiseNo,Date Reported,SpillVolInGal,Location,Description\nCUSTOMER-7,2026-01-20 00:44:24.607,10,123 Sample Road,Published description\n')
    raw = D.to_records(rows, '2026-01-21T00:00:00Z')[0]['raw']
    assert raw['PremiseNo'] == 'CUSTOMER-7'
    assert raw['Description'] == 'Published description'

def test_ct_archive_requests_and_keeps_reporter_fields(monkeypatch):
    from ingest import ct_deep_archive as C
    calls = []
    def get(s, url, params):
        calls.append(params)
        return ({'fields': [{'name': k} for k in ['OBJECTID', 'USER_NAME', 'EMAIL', 'PHONE_NUMBER']], '_content': b'{}'}
                if len(calls) == 1 else {'features': [], '_content': b'{}'})
    monkeypatch.setattr(C, 'get', get)
    monkeypatch.setattr(C, 'save_raw', lambda *a: None)
    C.fetch_layer(None, 'cso')
    assert 'USER_NAME' in calls[1]['outFields']
    r = C.normalise('cso', {'attributes': {'OBJECTID': 1, 'USER_NAME': 'Jane Example'}}, '2026-11-24T00:00:00Z')
    assert r['raw']['USER_NAME'] == 'Jane Example'

def test_generic_preserves_unlisted_and_nested_source_fields():
    from ingest.generic import fieldmap as F
    row = {'id': 1, 'reporter': 'Jane Example', 'nested': {'contact': 'Public contact'}}
    assert F.safe_row(row, {'safe_fields': ['id']}) == (row, [])
    block = {'platform': 'json', 'safe_fields': ['id', 'reporter'], 'record': {'source_record_id': 'id'}}
    assert not any('private person' in x for x in F.validate(block))

def test_baltimore_narratives_requested_and_kept():
    from ingest import md_baltimore_sso as B
    assert {'WAIVER_REASON', 'COMMENT_RELIEF_REQUEST_TYPE'} <= set(B.SAFE_FIELDS)

def script(name):
    sys.path.insert(0, str(ROOT / 'scripts'))
    return importlib.import_module(name)

@pytest.mark.parametrize('module,fn,args,expected', [
    ('build_in_outfalls', 'scrub_name', ['123 Sample Road'], '123 Sample Road'),
    ('gen_receiving_waters', 'safe_permittee', ['Jane Example'], 'Jane Example'),
    ('gen_receiving_waters', 'safe_permittee', ['Jane Example - City of Sample'], 'Jane Example - City of Sample'),
    ('add_federal_operators', 'public_permit_name', ['Jane Example'], 'Jane Example'),
    ('registry_rows_from_research', 'scrub_row', ['Contact: Jane Example, Director, 212-555-0123.'], 'Contact: Jane Example, Director, 212-555-0123.'),
    ('registry_rows_from_research', 'scrub_row', ['Jane A. Example WRF'], 'Jane A. Example WRF'),
])
def test_registry_source_text(module, fn, args, expected):
    assert getattr(script(module), fn)(*args) == expected

def test_mountain_operator_name():
    assert script('mountain_operator_rows').name_for('XX0000001', [{'permit_name': 'Jane Example'}], {}, {})[0] == 'Jane Example'

def test_wv_operator_name():
    M = script('wv_la_operator_rules')
    assert M.owner('Jane Example', None, None, 'WV', 'WV0000001', [])[0] == 'Jane Example'

def test_provisional_outfall_name():
    from export.build import outfall_lists
    rows = [{'npdes_permit': 'XX0000001', 'outfall': '1', 'outfall_name': 'Source location', 'record_status': 'provisional'}]
    result = outfall_lists(rows)
    assert 'Source location' in json.dumps(result)

def test_marker_retired_and_gates_removed(tmp_path):
    from export import build as X
    workflow = (ROOT / '.github/workflows/refresh.yml').read_text()
    assert '[ -f data/build/export-blocked.json ]' not in workflow
    assert 'rm -f data/build/export-blocked.json' in workflow


def test_field_copies_registered_before_removal(tmp_path):
    p = RemovalList([request('field', 'name')])
    (tmp_path / 'a.json').write_text(json.dumps({'copied': 'Unique registry text'}))
    (tmp_path / 'z.json').write_text(json.dumps({'name': 'Unique registry text'}))
    p.publish(tmp_path)
    assert 'Unique registry text' not in (tmp_path / 'a.json').read_text()

def test_record_derived_summary_backstop(tmp_path):
    p = RemovalList([request('record', 'a:1')])
    p.register([{'event_id': 'a:1', 'source_id': 'a', 'advice_text': 'Withdrawn narrative'}])
    (tmp_path / 'water.json').write_text(json.dumps({'reason_short': 'Withdrawn narrative', 'event_count': 1, 'events': ['a:1']}))
    assert p.enforce(tmp_path) > 0
    assert 'Withdrawn narrative' not in (tmp_path / 'water.json').read_text()

def test_text_identifier_filename_references(tmp_path):
    from export.build import event_file_name
    p = RemovalList([request('text', 'Sample')])
    row = {'event_id': 'a:Sample', 'source_id': 'a', 'source_record_id': 'Sample'}
    p.register([row])
    clean = p.apply(row)
    assert clean['event_id'] != 'a:[removed on request]'
    assert clean['event_id'] == 'a:' + clean['source_record_id']
    name = event_file_name(row['event_id'])
    (tmp_path / name).write_text(json.dumps(row))
    (tmp_path / 'index.json').write_text(json.dumps({'file': name}))
    p.publish(tmp_path)
    p.enforce(tmp_path)
    assert not any('sample' in f.name.lower() for f in tmp_path.rglob('*'))
    index = json.loads((tmp_path / 'index.json').read_text())
    assert (tmp_path / index['file']).exists()

@pytest.mark.parametrize('kind,shared_status', [('record', None), ('record', 'red'),
    ('record', 'yellow'), ('field', None), ('text', None)])
def test_real_pipeline_and_dataset_archive(kind, shared_status, tmp_path, monkeypatch):
    from build import status as S, reaches, rain_history, charts as C
    from export import build as X, outfalls, coverage
    at = '2026-11-24T12:00:00+00:00'
    slug = 'test-bay-ri'
    data = tmp_path / 'data'
    build = data / 'build'
    inputs = build / 'events'
    inputs.mkdir(parents=True)
    water = {'slug': slug, 'name': 'Test Bay', 'state': 'RI', 'kind': 'bay'}
    target = common.event(source_id='ri-test', source_record_id='Sample', event_type='sso',
                          status='ongoing', started_at=at, fetched_at=at, water_slugs=[slug],
                          advice_text='Withdrawn narrative', raw={'note': 'Event field', 'state': 'RI'})
    other = common.event(source_id='ri-test', source_record_id='retained', event_type='sso',
                         status='ongoing', started_at=at, fetched_at=at, water_slugs=[slug], raw={'state': 'RI'})
    if shared_status:
        target['advice_text'] = 'Sewer overflow'
        target['water_slugs'] = ['withdrawn-bay-ri']
        if shared_status == 'yellow':
            other.update(status='ended', started_at='2026-11-21T12:00:00+00:00',
                         ended_at='2026-11-22T00:00:00+00:00')
    common.write_json(inputs / 'ri-test.json', {'source_id': 'ri-test', 'fetched_at': at, 'ok': True,
                                               'count': 2, 'records': [target, other]})
    registry = {'id': 'operator', 'state': 'RI', 'name': 'Unique field value',
                'raw': {'withdraw': 'Unique field value'}}
    common.write_json(data / 'dischargers.json', {'dischargers': [registry]})
    # Also exercise persisted history/enrichment inputs read through the normal JSON loader.
    common.write_json(build / 'enrichment.json', {'raw': {'withdraw': 'Unique field value'}, 'copy': 'Unique field value'})
    match = {'record': target['event_id'], 'field': 'raw.withdraw', 'text': 'Sample'}[kind]
    p = RemovalList([request(kind, match)])
    monkeypatch.setattr(RemovalList, 'load', lambda: p)
    monkeypatch.setattr(common, 'DATA_DIR', data)
    monkeypatch.setattr(common, 'BUILD_DIR', build)
    for module in (S, X, reaches):
        monkeypatch.setattr(module, 'DATA_DIR', data)
        monkeypatch.setattr(module, 'BUILD_DIR', build)
    monkeypatch.setattr(X, 'OUT_DIR', tmp_path / 'out')
    monkeypatch.setattr(X, 'EVENTS_DIR', inputs)
    monkeypatch.setattr(S, 'load_waters', lambda: {slug: water})
    monkeypatch.setattr(S, 'load_registry_outfalls', lambda **kw: [])
    monkeypatch.setattr(S, 'load_registry', lambda: {'ri-test': {'id': 'ri-test', 'states': ['RI']}})
    monkeypatch.setattr(S, 'load_rules', lambda: {'version': 'test', 'live_states': ['RI'], 'yellow': {'default_hours': 72}})
    monkeypatch.setattr(S, 'water_geometry', lambda *args: None)
    monkeypatch.setattr(X, 'launches_for', lambda *args: [])
    monkeypatch.setattr(rain_history, 'load_levels', lambda: None)
    monkeypatch.setattr(reaches, 'load_reaches', lambda: {})
    monkeypatch.setattr(outfalls, 'ma_layer_rows', lambda: [])
    monkeypatch.setattr(coverage, 'load_notification_pages', lambda: None)
    monkeypatch.setattr(coverage, 'load_register', lambda: None)
    monkeypatch.setattr(C, 'DATA_DIR', data)
    monkeypatch.setattr(C, 'BUILD_DIR', build)
    monkeypatch.setattr(C, 'CHARTS_DIR', X.OUT_DIR / 'charts')
    monkeypatch.setattr(C, 'load_waters', lambda: {slug: water})
    monkeypatch.setattr(C, 'load_rules', S.load_rules)
    monkeypatch.setattr(C, 'load_events', lambda **kw: S.load_events(inputs, **kw))
    captured = []
    def actual_status(*args):
        st, hist = S.build(now=datetime.fromisoformat(at), events_dir=inputs, write=False,
                           waters={slug: water}, outfalls=[], registry={}, rules=S.load_rules(), reaches={},
                           flows=({}, {}), discharger_towns={}, discharger_waters={}, discharger_aliases_map={},
                           rain={}, placement_cache=False)
        captured.append(st)
        common.write_json(build / 'status.json', st)
        common.write_json(build / 'history.json', hist)
        C.build(now=datetime.fromisoformat(at))
        return st, hist
    monkeypatch.setattr(X, 'ensure_status', actual_status)
    X.export()
    forbidden = {'record': target['event_id'].encode() if shared_status else b'Withdrawn narrative', 'field': b'Unique field value', 'text': b'Sample'}[kind]
    for f in X.OUT_DIR.rglob('*'):
        if f.is_file():
            assert forbidden.lower() not in f.read_bytes().lower(), f.relative_to(X.OUT_DIR)
            assert match.lower() not in f.relative_to(X.OUT_DIR).as_posix().lower()
    if kind == 'record':
        assert captured[0]['waters'][slug]['events'] == [other['event_id']]
        assert 'Withdrawn narrative' not in json.dumps(captured)
        if shared_status:
            summary = captured[0]['waters'][slug]
            assert summary['status'] == shared_status
            assert summary['reason_short'].startswith('Sewer overflow')
            assert p.apply(summary) == summary
            exported = json.loads((X.OUT_DIR / 'waters' / (slug + '.json')).read_text())
            assert exported['status'] == shared_status
            assert exported['reason_short'] == summary['reason_short']
        index = json.loads((X.OUT_DIR / 'events.json').read_text())
        assert len(index['events']) == 1
        assert not (X.OUT_DIR / 'events' / X.event_file_name(target['event_id'])).exists()
        charts = json.loads((X.OUT_DIR / 'charts/index.json').read_text())
        assert charts['state']['RI']['events'] == 1
    if kind == 'text':
        index = json.loads((X.OUT_DIR / 'events.json').read_text())
        for row in index['events']:
            assert (X.OUT_DIR / row['file']).exists()
    archive = tmp_path / 'dataset.zip'
    # Exactly the workflow's dataset membership: all output except the CSV folder.
    with zipfile.ZipFile(archive, 'w') as z:
        for f in X.OUT_DIR.rglob('*'):
            if f.is_file() and f.relative_to(X.OUT_DIR).parts[0] != 'csv':
                z.write(f, f.relative_to(X.OUT_DIR).as_posix())
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            assert match.lower() not in name.lower()
            assert forbidden.lower() not in z.read(name).lower()
        if kind == 'record':
            assert 'events/' + X.event_file_name(target['event_id']) not in z.namelist()

def test_source_declarations_and_expanded_generic_requests(monkeypatch):
    import yaml
    from ingest.generic import arcgis, socrata
    from export import build as X
    dc = yaml.safe_load((ROOT / 'data/sources/dc-water-sso.yaml').read_text())
    assert dc['raw_fields']['customer_identifier'] == ['PremiseNo']
    assert dc['raw_fields']['description'] == ['Description']
    assert 'raw_fields' in X.REGISTRY_KEYS
    for f in (ROOT / 'data/sources').glob('*.yaml'):
        doc = yaml.safe_load(f.read_text())
        assert isinstance(doc['raw_fields']['reporter_contact'], list), f.name
    calls = []
    def get(*a, **kw):
        calls.append(a[2])
        return {'features': []}
    monkeypatch.setattr(arcgis, 'get_json', get)
    arcgis.fetch({'url': 'https://example.org/layer', 'safe_fields': ['OBJECTID']}, None)
    assert calls[0]['outFields'] == '*'

def test_reaches_use_filtered_ingest_inputs(tmp_path, monkeypatch):
    from build import reaches as R
    p = RemovalList([request('record', 'ri-test:Sample')])
    monkeypatch.setattr(RemovalList, 'load', lambda: p)
    monkeypatch.setattr(common, 'DATA_DIR', tmp_path)
    folder = tmp_path / 'build' / 'events'
    folder.mkdir(parents=True)
    row = {'event_id': 'ri-test:Sample', 'source_id': 'ri-test', 'status': 'advisory_active',
           'raw': {'stretch': {'water': 'Test Bay'}}}
    common.write_json(folder / 'test.json', {'records': [row]})
    monkeypatch.setattr(R, 'stretch_candidate', lambda e: {'key': e['event_id']})
    assert R.stretch_points(events_dir=folder) == []

def test_delete_manifest_is_private_and_upload_failure_stops(tmp_path, monkeypatch):
    M = script('publication_deletions')
    manifest = tmp_path / 'private' / 'publication-deletions.json'
    p = RemovalList([request('record', 'a:Sample')])
    p.save_deletions(manifest)
    assert manifest.stat().st_mode & 0o777 == 0o600
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, b'', b'')
    monkeypatch.setattr(M.subprocess, 'run', run)
    assert M.delete(manifest) == 1
    assert manifest.exists()
    assert calls[0][-2:] == ['dirtywaterwatch-data/current/events/a~3ASample.json', '--remote']

def legacy_text_namespace():
    names = ['scrub_text', 'scrub_names', 'strip_house_numbers', 'scrub_residence_numbers', 'drop_house_numbers']
    return historical('common', names, vars(common))

@pytest.mark.parametrize('location', ['123-A Sample Road', '12Main Street', 'Highway 150', '123 Sample Road; contact Jane Example at noon'])
def test_alabama_and_knoxville_historical_street_identity(location):
    from ingest import al_jefferson_county_soa as A, al_adem_sso as D, tn_kub_sso_log as T
    oldclean = historical('ingest/al_adem_sso', ['clean_text', 'strip_al_house_numbers'], {**vars(D), **legacy_text_namespace()})
    old = historical('ingest/al_jefferson_county_soa', ['street_only', 'street_key'], {**vars(A), 'clean_text': oldclean['clean_text']})
    expected = old['street_key'](old['street_only'](location))
    assert A.street_key(location) == expected
    assert T.row_key({'date': '2026-01-20', 'time': '', 'location': location}).endswith(':' + expected)

def test_san_diego_location_hash_keeps_historical_contact_normalization():
    from ingest import ca_sd_tijuana_table as C
    old = historical('ingest/ca_sd_tijuana_table', ['record_ids'], {**vars(C), **legacy_text_namespace()})
    rows = [{'start': '01/20/2026', 'location': '123 Sample Road contact Jane Example at noon'}]
    assert C.record_ids(rows) == old['record_ids'](rows)

def test_nevada_water_keys_use_historical_field_identity():
    from ingest import nv_state_parks_hab as P, nv_ose_hab_list as N
    old = historical('ingest/nv_state_parks_hab', ['clean_field'], {**vars(P), **legacy_text_namespace()})
    water = 'Private home at 123 Sample Road'
    assert N.key_of({'water': water}) == P.slug(old['clean_field'](water))

def test_maryland_hash_tie_breaker_is_historical():
    from ingest import md_mde_overflows as M
    old = historical('ingest/md_mde_overflows', ['scrub_people', 'scrub_row', 'row_sha'], vars(M))
    row = {'overflow_address': '123 Sample Road', 'comments': 'Mr. Example contacted agency'}
    for f in M.FREE_TEXT_FIELDS:
        row[f] = 'Mr. Example contacted agency'
    assert M.row_sha(row) == old['row_sha'](old['scrub_row'](row, M._allowlist()))

def test_notification_hash_uses_historical_text():
    from ingest import notification_pages as N
    from datetime import date
    old = historical('ingest/notification_pages', ['notice_record'], vars(N))
    n = {'text': 'Inspector Jane Example reports an overflow', 'start': date(2026, 1, 20),
         'line': '', 'dates': [], 'date_from': 'source', 'type_basis': 'source', 'end': None,
         'event_type': 'sso', 'status': 'unknown', 'outfall': None}
    page = {'page_id': 'test', 'url': 'https://example.org', 'rows': [{'id': 'test', 'operator_id': 'test'}]}
    expected = old['notice_record']({**n, 'text': legacy_text_namespace()['scrub_text'](n['text'])}, page, '2026-01-20T12:00:00Z')
    assert N.notice_record(n, page, '2026-01-20T12:00:00Z')['event_id'] == expected['event_id']

@pytest.mark.parametrize('module,fn,args', [
    ('mi_egle_mienviro', 'safe_row', []), ('sc_des_overflows', 'safe_row', []),
    ('or_deq_oers_spills', 'safe_row', []), ('nc_dwr_sso', 'safe', [[]]),
])
def test_remaining_deferred_field_gates(module, fn, args):
    m = importlib.import_module('ingest.' + module)
    row = {'submissionId': '1', 'responsiblePartyName': 'Jane Example', 'submitter_name': 'Jane Example',
           'Situation': 'Full public narrative', 'latest_comments': 'Full public narrative'}
    assert getattr(m, fn)(row, *args) == row

def test_michigan_beach_comment_retained():
    from ingest import mi_egle_beaches as M
    assert 'AdvisoryComments' in M.ADV_KEPT

def test_record_provenance_retires_derived_registry_row():
    p = RemovalList([request('record', 'a:1')])
    derived = {'record_status': 'provisional', 'event_ids': ['a:1'], 'outfall_name': 'Withdrawn place', 'report_count': 1}
    p.register(derived)
    assert p.apply([derived]) == []

def test_scoped_identifier_does_not_change_other_source_id():
    p = RemovalList([request('text', 'Sample', scope={'event_id': 'a:Sample'})])
    a = {'event_id': 'a:Sample', 'source_id': 'a', 'source_record_id': 'Sample'}
    b = {'event_id': 'b:Sample', 'source_id': 'b', 'source_record_id': 'Sample'}
    p.register([a, b])
    assert p.apply(b) == b

def test_provisional_build_filters_injected_events(monkeypatch, tmp_path):
    from build import provisional_outfalls as P
    p = RemovalList([request('record', 'a:1')])
    monkeypatch.setattr(RemovalList, 'load', lambda: p)
    monkeypatch.setattr(common, 'DATA_DIR', tmp_path)
    visited = []
    monkeypatch.setattr(P, 'operator_of', lambda e, k: visited.append(e) or None)
    P.build_places([{'event_id': 'a:1', 'source_id': 'a'}], outlines={}, key={}, by_id={})
    assert visited == []

def test_generic_hash_and_template_id_preserve_historical_rows():
    from ingest.generic import fieldmap as F, runner
    ns = {**vars(F), **legacy_text_namespace()}
    old = historical('ingest/generic/fieldmap', ['safe_row', 'scrub', 'scrub_people', 'row_sha'], ns)
    block = {'platform': 'json', 'url': 'https://example.org', 'time_zone': 'UTC',
             'safe_fields': ['id', 'notes'], 'free_text': ['notes'], 'record': {'source_record_id': 'id'}}
    row = {'id': None, 'notes': 'Inspector Jane Example at Sample Road', 'reporter': 'Extra field'}
    oldrow = old['safe_row'](row, block)[0]
    old_id = 'test:row-' + old['row_sha'](oldrow)[:12]
    records, _ = runner.build('test', block, [row], '2026-11-24T00:00:00Z', [])
    assert records[0]['event_id'] == old_id
    assert records[0]['raw']['row']['notes'] == row['notes']
    assert RemovalList([request('record', old_id)]).apply(records) == []

def test_massdep_fallback_hash_uses_old_api_normalization(monkeypatch):
    from ingest import ma_massdep as M
    import hashlib
    old = historical('ingest/ma_massdep', ['scrub'], vars(M))
    row = {'description': 'Public value', 'reporterName': 'Jane Example'}
    expected = hashlib.sha1(json.dumps(old['scrub'](row), sort_keys=True).encode()).hexdigest()[:16]
    monkeypatch.setattr(M, 'build_event', lambda row, entry, ctx, base: base)
    assert M.normalise({'row': row}, {})['source_record_id'] == expected


def test_feed_declaration_combines_registered_readers():
    from export import build as X
    registry = {'ct-cso': {'raw_fields': {'reporter_contact': ['USER_NAME'], 'customer_identifier': []}},
                'ct-sso': {'raw_fields': {'reporter_contact': ['EMAIL'], 'customer_identifier': ['Account']}}}
    fields = X.feed_raw_fields('ct-archive', {'registry_ids': ['ct-cso', 'ct-sso']}, registry)
    assert fields['reporter_contact'] == ['EMAIL', 'USER_NAME']
    assert fields['customer_identifier'] == ['Account']


def test_reference_inputs_registered_before_any_copy_is_read(tmp_path, monkeypatch):
    from build.removal_inputs import publication_inputs
    data = tmp_path / 'data'
    (data / 'reference').mkdir(parents=True)
    common.write_json(data / 'reference' / 'late.json', {'withdraw': 'Distinct source quote'})
    monkeypatch.setattr(common, 'DATA_DIR', data)
    p = RemovalList([request('field', 'withdraw')])
    monkeypatch.setattr(RemovalList, 'load', lambda: p)
    @publication_inputs
    def build():
        return p.apply({'copy': 'Distinct source quote'})
    assert 'Distinct source quote' not in json.dumps(build())


def test_florida_duplicate_ids_reread_precommit_normalization():
    from ingest import fl_dep_pnp as F, identity_text
    old = historical('ingest/fl_dep_pnp', ['scrub', 'scrub_name_field', 'safe_attributes', 'keyed'],
                     {**vars(F), 'scrub_text': identity_text.scrub_text,
                      'drop_house_numbers': identity_text.drop_house_numbers,
                      'strip_house_numbers': identity_text.strip_house_numbers})
    rows = [dict(INCIDENT_NUMBER='2026-100', DATE_TIME_OF_REPORT=1760000000000,
                 INCIDENT_REPORT='Contact: Jane Example. Sewage spill.', LATITUDE=27.12349, LONGITUDE=-81.1,
                 REPORTER_REALTIONSHIP='Citizen'),
            dict(INCIDENT_NUMBER='2026-100', DATE_TIME_OF_REPORT=1760000000000,
                 INCIDENT_REPORT='Unknown sewage spill.', LATITUDE=27.12341, LONGITUDE=-81.1,
                 REPORTER_REALTIONSHIP='Citizen')]
    rows = [dict(rows[0], INCIDENT_REPORT=f'Contact: Jane Example. Sewage spill {i}.',
                 LATITUDE=27.12301 + i * 0.00001) for i in range(8)]
    oldrows = [old['safe_attributes'](r) for r in rows]
    # Compare row identity by the report text normalized exactly as the old saved history.
    expected = {r['INCIDENT_REPORT']: key for key, r in old['keyed'](oldrows)}
    actual = {old['safe_attributes'](r)['INCIDENT_REPORT']: key for key, r in F.keyed(rows)}
    assert actual == expected


def test_empty_policy_rebuilds_previously_filtered_status(monkeypatch):
    from export import build as X
    from build.removal_inputs import ACTIVE
    monkeypatch.setattr(X, 'read_json', lambda p: {'requested_removals_applied': True})
    monkeypatch.setattr(X, 'stale_reason', lambda *a: None)
    monkeypatch.setattr(X, 'status_inputs', lambda: [])
    monkeypatch.setattr(X.status_mod, 'build', lambda **kw: ('rebuilt', 'history'))
    token = ACTIVE.set(RemovalList([]))
    try:
        assert X.ensure_status(False) == ('rebuilt', 'history')
    finally:
        ACTIVE.reset(token)

@pytest.mark.parametrize('module,fn,args', [
    ('wa_ecology_spills', 'safe_row', ({'steps_taken_to_contain_or_clean': 'Published note'},)),
    ('nc_algal_blooms', 'keep', ({'details': 'Published note'}, [])),
])
def test_additional_narrative_inputs_kept(module, fn, args):
    assert 'Published note' in json.dumps(getattr(importlib.import_module('ingest.' + module), fn)(*args))


def test_louisville_identity_matches_precommit_snapshot():
    from ingest import ky_louisville_msd as K, mi_egle_mienviro as M
    from ingest import identity_text
    old_text = historical('ingest/mi_egle_mienviro', ['free_text'],
                          {**vars(M), 'scrub_text': identity_text.scrub_text,
                           'strip_house_numbers': identity_text.strip_house_numbers})['free_text']
    snap = {'title': 'MSD-02 Overflow', 'text': 'ASSET ADDRESS: 123 Sample Road\nRECEIVING STREAM: Sample Creek'}
    old_snap = {**snap, 'text': '\n'.join(old_text(s) for s in snap['text'].splitlines())}
    previous = historical('ingest/ky_louisville_msd', ['_ident'], vars(K))['_ident']('MSD-02', old_snap)
    assert K._ident('MSD-02', snap) == previous


def test_backstop_detects_encoded_filename_without_event_body(tmp_path):
    from export.build import event_file_name
    (tmp_path / event_file_name('a:Sample/Path')).write_text('null')
    p = RemovalList([request('text', 'Sample/Path')])
    p.enforce(tmp_path)
    assert all('Sample' not in path.name for path in tmp_path.iterdir())


def test_removed_record_does_not_leave_cached_feed_totals():
    p = RemovalList([request('record', 'a:1')])
    doc = {'source_id': 'a', 'count': 2, 'records': [{'event_id': 'a:1'}, {'event_id': 'a:2'}],
           'meta': {'registry_ids': ['source-a'], 'left_out': {'sso': 1}, 'listed_without_status': 2}}
    p.register(doc)
    out = p.apply(doc)
    assert out['count'] == 1
    assert out['meta'] == {'registry_ids': ['source-a']}


def test_newly_widened_readers_keep_source_coordinates():
    from ingest import nc_algal_blooms as B
    assert B.point({'x': -76.123456, 'y': 35.123456}) == (35.123456, -76.123456)
    module = script('build_in_outfalls')
    row = {'attributes': {'CSO_Number': '123 Sample Road', 'Photo_Credit': 'Jane Example'},
           'geometry': {'x': -86.123456, 'y': 40.123456}}
    assert module.sanitize({'features': [row]})['features'] == [row]


def test_publish_withdraws_cached_record_summary_and_its_count(tmp_path):
    p = RemovalList([request('record', 'a:1')])
    p.register([{'event_id': 'a:1', 'source_id': 'a', 'advice_text': 'Withdrawn narrative'}])
    (tmp_path / 'water.json').write_text(json.dumps({'reason_short': 'Withdrawn narrative', 'event_count': 1, 'events': ['a:1']}))
    p.publish(tmp_path)
    p.enforce(tmp_path)
    assert json.loads((tmp_path / 'water.json').read_text()) is None


def test_record_withdrawal_preserves_independent_record_with_same_words():
    p = RemovalList([request('record', 'a:1')])
    a = {'event_id': 'a:1', 'source_id': 'a', 'advice_text': 'Shared agency wording'}
    b = {**a, 'event_id': 'a:2'}
    p.register([a, b])
    assert p.apply(b) == b


def test_snapshot_unit_reread_keeps_historical_identity():
    from ingest.generic import snapshot, fieldmap as F
    from zoneinfo import ZoneInfo
    block = {'safe_fields': ['unit', 'state'], 'free_text': ['unit'],
             'snapshot': {'unit': 'unit', 'state': 'state', 'states': {'^active$': 'active'}},
             'record': {'event_type': {'const': 'cso'}}}
    row = {'unit': 'Inspector Jane Example', 'state': 'active'}
    old = historical('ingest/generic/fieldmap', ['safe_row', 'scrub', 'scrub_people'],
                     {**vars(F), **legacy_text_namespace()})['safe_row'](row, block)[0]
    ctx = F.Ctx('test', block, ZoneInfo('UTC'), '2026-11-24T00:00:00Z')
    state = {}
    first, _ = snapshot.build([old], ctx, state)
    second, _ = snapshot.build([row], ctx, state)
    assert [r['event_id'] for r in second] == [r['event_id'] for r in first]
    assert second[0]['raw']['row']['unit'] == row['unit']


def test_california_datastore_keeps_full_rows_and_requests_all_fields():
    from ingest import ca_datagov as C
    seen = []
    class Reply:
        def raise_for_status(self): pass
        def json(self): return {'result': {'records': [{'id': 1, 'Reporter': 'Published contact'}], 'total': 1}}
    class Session:
        def get(self, url, **kw): seen.append(kw['params']); return Reply()
    assert C.search(Session(), 'test', ['id'])[0]['Reporter'] == 'Published contact'
    assert 'fields' not in seen[0]
    assert C.sql(Session(), 'test', ['id'], '1=1')[0]['Reporter'] == 'Published contact'
    assert 'SELECT *' in seen[1]['sql']

@pytest.mark.parametrize('module,fn,args', [
    ('fl_dep_pnp', 'safe_attributes', ({'REPORTER_NAME': 'Published contact'},)),
    ('mo_dnr_hab', 'rounded', ({'features': [{'attributes': {'reporter': 'Published contact'}}]},)),
    ('sc_des_advisories', 'safe_features', ([{'attributes': {'Contact': 'Published contact'}}], 'geometry')),
])
def test_remaining_source_attribute_gates(module, fn, args):
    assert 'Published contact' in json.dumps(getattr(importlib.import_module('ingest.' + module), fn)(*args))

@pytest.mark.parametrize('module,fn,scrubber', [('sc_des_advisories','_norm','de_dnrec_derns'),
                                             ('id_deq_cyanohab','key','ia_id_privacy')])
def test_more_water_identity_rereads(module, fn, scrubber):
    current = importlib.import_module('ingest.' + module)
    oldmod = importlib.import_module('ingest.' + scrubber)
    oldscrub = historical('ingest/' + scrubber, ['scrub'], {**vars(oldmod), **legacy_text_namespace()})['scrub']
    oldkey = historical('ingest/' + module, [fn], vars(current))[fn]
    text = 'Inspector Jane Example at 123 Sample Road'
    assert getattr(current, fn)(text) == oldkey(oldscrub(text))


def test_charts_filter_records_before_counting(tmp_path, monkeypatch):
    from build import charts as C
    monkeypatch.setattr(common, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(RemovalList, 'load', lambda: RemovalList([request('record', 'a:1')]))
    monkeypatch.setattr(C, 'load_events', lambda **kw: ({}, [{'event_id': 'a:1', 'source_id': 'a'}], []))
    monkeypatch.setattr(C, 'load_waters', lambda: {})
    monkeypatch.setattr(C, 'load_rules', lambda: {})
    monkeypatch.setattr(C, 'read_json', lambda *a: {})
    assert C.Data(datetime(2026, 11, 24, tzinfo=UTC)).events == []


def test_dc_rereads_actual_precommit_records_without_carrying_a_duplicate():
    from ingest import dc_water_sso as D
    previous = historical('ingest/dc_water_sso', ['parse', 'safe_location', 'row_id', 'to_records'], vars(D))
    csv = 'PremiseNo,Date Reported,SpillVolInGal,Location,Description\nCUSTOMER-7,2026-01-20 00:44:24.607,10,123 Sample Road,Published description\n'
    old = previous['to_records'](previous['parse'](csv)[0], '2026-01-21T00:00:00Z')
    current = D.to_records(D.parse(csv)[0], '2026-11-24T00:00:00Z')
    assert current[0]['event_id'] == old[0]['event_id']
    assert D.carry_forward({'records': old}, current, '2026-11-24T00:00:00Z') == []
    policy = RemovalList([request('record', old[0]['event_id'])])
    policy.register(current)
    assert policy.apply(current) == []

@pytest.mark.parametrize('source,kind,keys', [
    ('dc-water-sso', 'customer_identifier', ['PremiseNo']),
    ('ct-deep-agol-cso-reporting-archive', 'reporter_contact', ['USER_NAME','EMAIL','PHONE_NUMBER','Creator','Editor']),
    ('fl-dep-pnp', 'reporter_contact', ['REPORTER_NAME','REPORTER_TITLE','REPORTER_EMAIL','REPORTER_PHONE','CONTACT_NAME','CONTACT_EMAIL','CONTACT_PHONE']),
    ('ca-swrcb-fhab', 'reporter_contact', ['Case_Lead','Response_Update_By','Reported_Management_Organizations']),
    ('sc-des-freshwater-swim-advisories', 'reporter_contact', ['Phone','Contact','Creator','Editor']),
    ('tx-tceq-sso-opendata', 'customer_identifier', ['customer_number']),
])
def test_expanded_source_declarations(source, kind, keys):
    import yaml
    doc = yaml.safe_load((ROOT / 'data/sources' / (source + '.yaml')).read_text())
    assert doc['raw_fields'][kind] == keys

@pytest.mark.parametrize('color,rule', [('red', 'ongoing'), ('yellow', 'caution')])
@pytest.mark.parametrize('match', ['a:1', 'Sewer overflow'])
def test_record_removal_preserves_other_waters_derived_status(tmp_path, color, rule, match):
    from build.status import short_reason
    removed = {'event_id': 'a:1', 'source_id': 'a', 'source_record_id': '1', 'advice_text': 'Sewer overflow'}
    surviving = {'event_id': 'a:2', 'source_id': 'a', 'event_type': 'sso'}
    reason = short_reason({'state': color, 'rule': rule, 'event_type': 'sso', 'yellow_rule': {'hours': 72}}, surviving)
    summary = {'status': color, 'reason_short': reason, 'events': ['a:2'], 'event_count': 1}
    p = RemovalList([request('record', match)])
    p.register([removed, surviving])
    assert p.removed_ids == {'a:1'}
    assert p.apply({'waters': {'other': summary}}) == {'waters': {'other': summary}}
    path = tmp_path / 'waters.json'
    path.write_text(json.dumps({'waters': {'other': summary}}))
    p.publish(tmp_path)
    assert p.enforce(tmp_path) == 0
    assert json.loads(path.read_text()) == {'waters': {'other': summary}}

@pytest.mark.parametrize('scope', [{'event_id': 'Sample:a'}, {'source_id': 'Sample'}])
def test_scoped_aliases_keep_shared_source_and_operator_identities(tmp_path, scope):
    from export.build import event_file_name
    a = {'event_id': 'Sample:a', 'source_id': 'Sample', 'source_record_id': 'a', 'discharger_id': 'Sample-operator'}
    b = {'event_id': 'Sample:b', 'source_id': 'Sample', 'source_record_id': 'b', 'discharger_id': 'Sample-operator'}
    c = {'event_id': 'other:c', 'source_id': 'other', 'source_record_id': 'c', 'discharger_id': 'Sample-operator'}
    p = RemovalList([request('text', 'Sample', scope=scope)])
    p.register([a, b, c])
    clean = p.apply([a, b, c])
    assert clean[2] == c
    if 'event_id' in scope:
        assert clean[1] == b
    for row in clean:
        assert row['event_id'] == row['source_id'] + ':' + row['source_record_id']
    index = []
    for row in (a, b, c):
        name = event_file_name(row['event_id'])
        (tmp_path / name).write_text(json.dumps(row))
        index.append({**row, 'file': name})
    (tmp_path / 'index.json').write_text(json.dumps(index))
    p.publish(tmp_path)
    p.enforce(tmp_path)
    published = json.loads((tmp_path / 'index.json').read_text())
    for row in published:
        assert (tmp_path / row['file']).exists()
        assert row['event_id'] == row['source_id'] + ':' + row['source_record_id']
    assert published[2] == {**c, 'file': event_file_name(c['event_id'])}
    if 'event_id' in scope:
        assert published[1] == {**b, 'file': event_file_name(b['event_id'])}


def test_registering_rebuilt_status_does_not_select_records_by_generated_words():
    from build.status import short_reason
    p = RemovalList([request('record', 'Sewer overflow')])
    removed = common.event(source_id='a', source_record_id='1', advice_text='Sewer overflow')
    surviving = common.event(source_id='a', source_record_id='2', event_type='sso')
    p.register([removed, surviving])
    assert p.removed_ids == {'a:1'}
    reason = {'event_id': 'a:2', 'source_id': 'a', 'status': 'red', 'rule': 'ongoing',
              'short': short_reason({'rule': 'ongoing', 'event_type': 'sso'}, surviving)}
    summary = {'status': 'red', 'reason_short': reason['short'], 'events': ['a:2'], 'reasons': [reason]}
    p.register({'waters': {'other': summary}})
    assert p.apply(summary) == summary
