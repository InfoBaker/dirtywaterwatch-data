"""Decision 57: source text passes; only explicit requests remove public records."""
import json
import pytest
import common
from export import detail

TEXT = 'Inspector Jane Example at 123 Sample Road; jane@example.org; (212) 555-0123'


def test_public_record_helpers_preserve_source_text():
    for fn in (common.scrub_text, common.scrub_names, common.scrub_residence_numbers,
               common.strip_house_numbers, detail._clean):
        assert fn(TEXT) == TEXT
    assert common.drop_house_numbers(TEXT, [('123', 'Sample')]) == TEXT
    obj = {'contact': TEXT, 'nested': [{'reporter': TEXT}]}
    assert common.strip_personal(obj) == obj
    assert common.scrub_discharger({'discharger_name': 'Jane Example'}) == {'discharger_name': 'Jane Example'}


def test_default_redaction_never_reads_the_old_blocklist(monkeypatch):
    from build import redact
    monkeypatch.setattr(redact, 'blocklist', lambda *a: pytest.fail('legacy list read'))
    row = {'event_id': 'a:1', 'source_id': 'a', 'advice_text': TEXT, 'raw': {'contact': TEXT}}
    assert redact.redact_events([row]) == [row]


def entry(kind='text', match='Sample', scope=None, **kw):
    return {'id': 'request-001', 'added': '2026-11-25', 'kind': kind, 'match': match,
            'scope': scope or {}, **kw}


def policy(*entries):
    from export.removals import RemovalList
    return RemovalList(list(entries))


def test_absent_list(tmp_path):
    from export.removals import RemovalList
    p = RemovalList.load(tmp_path / 'absent.json')
    assert p.apply({'text': TEXT}) == {'text': TEXT}
    assert p.enforce(tmp_path) == 0


@pytest.mark.parametrize('scope', [{}, {'source_id': 'a'}, {'event_id': 'a:1'},
                                    {'source_id': 'a', 'event_id': 'a:1'}])
def test_text_request_scope_and_case(scope):
    p = policy(entry(scope=scope))
    row = {'source_id': 'a', 'event_id': 'a:1', 'raw': {'note': 'SAMPLE Road'}, 'advice_text': 'Sample Road'}
    out = p.apply(row)
    assert out['raw']['note'] == '[removed on request] Road'
    assert row['raw']['note'] == 'SAMPLE Road'
    if scope:
        other = {**row, 'source_id': 'b', 'event_id': 'b:1'}
        assert p.apply(other) == other


def test_field_request_and_copy_propagation():
    p = policy(entry('field', 'raw.contact', {'event_id': 'a:1'}))
    row = {'source_id': 'a', 'event_id': 'a:1', 'raw': {'contact': TEXT}, 'advice_text': TEXT}
    p.register([row])
    out = p.apply(row)
    assert 'contact' not in out['raw']
    assert TEXT not in json.dumps(out)
    assert TEXT not in json.dumps(p.apply({'event_id': 'a:1', 'detail': {'notes': TEXT}}))


def test_record_request_history_and_references():
    p = policy(entry('record', 'a:1', {'source_id': 'a'}))
    p.register([{'event_id': 'a:1', 'source_id': 'a', 'advice_text': TEXT}])
    assert p.apply({'events': [{'event_id': 'a:1'}, {'event_id': 'b:1'}]}) == {'events': [{'event_id': 'b:1'}]}
    assert p.apply({'intervals': {'water': [['start', 'end', 'red', 'rule', 'a:1']]}}) == {'intervals': {'water': []}}


def test_all_payloads_csv_and_postcheck_remove_remaining_record(tmp_path, capsys):
    p = policy(entry(scope={'event_id': 'a:1'}))
    p.register([{'event_id': 'a:1', 'source_id': 'a'}])
    (tmp_path / 'events.json').write_text(json.dumps({'events': [
        {'event_id': 'a:1', 'note': 'Sample'}, {'event_id': 'b:1', 'note': 'Sample'}]}))
    (tmp_path / 'download.csv').write_text('event_id,source_id,note\na:1,a,Sample\nb:1,b,Sample\n')
    p.publish(tmp_path)
    assert '[removed on request]' in (tmp_path / 'download.csv').read_text()
    (tmp_path / 'extra.json').write_text(json.dumps({'events': [{'event_id': 'a:1', 'note': 'Sample'}]}))
    assert p.enforce(tmp_path) > 0
    assert json.loads((tmp_path / 'extra.json').read_text())['events'] == []
    assert 'a:1' not in (tmp_path / 'download.csv').read_text()
    assert 'b:1' in (tmp_path / 'download.csv').read_text()
    log = capsys.readouterr().out
    assert 'extra.json' in log and 'request-001' in log and 'Sample' not in log


def test_secret_masking_still_runs():
    assert 'TEST_TOKEN_VALUE' not in common.redact_secrets('token=TEST_TOKEN_VALUE')


@pytest.mark.parametrize('module,name', [
    ('ct_deep', 'scrub'), ('ma_massdep', 'scrub'), ('mountain_scrub', 'scrub'),
    ('ia_id_privacy', 'scrub'), ('fl_dep_pnp', 'scrub'), ('fl_dep_pnp', 'scrub_name_field'),
    ('mi_egle_mienviro', 'party_name'), ('mi_egle_mienviro', 'free_text'),
    ('de_dnrec_derns', 'scrub'), ('sc_florence_sso', 'scrub_text'),
    ('md_mde_overflows', 'scrub_people'), ('mo_kc_water_news', 'safe_text'),
    ('oh_neorsd_cso', 'scrub_location'), ('tx_spill_notice_form', 'street_place'),
    ('va_deq_prep', 'scrub_free'), ('wv_dep_hab_advisories', 'scrub_advisory'),
    ('wy_deq_spills', 'scrub_free'), ('il_idph_beachguard', 'scrub_comment'),
    ('ca_swrcb_ciwqs_spills', 'location_name'), ('ca_swrcb_ciwqs_spills', 'entity_name'),
    ('wi_mmsd_storm_updates', 'scrub_names'), ('generic.fieldmap', 'scrub_strict_names'),
])
def test_source_helpers_keep_published_text(module, name):
    import importlib
    fn = getattr(importlib.import_module('ingest.' + module), name)
    obj = {'contact': TEXT} if module in ('ct_deep', 'ma_massdep') else TEXT
    assert fn(obj) == obj


def test_source_coordinates_are_kept_exactly():
    from ingest import ca_swrcb_ciwqs_spills as ca, ca_swrcb_ciwqs_sso_2006 as old
    from ingest import tx_houston_sso_monthly as tx
    a = {'lat': '34.123456', 'lon': '-118.123456', 'appearance_points': 'Lateral Clean Out (Private)'}
    assert ca.scrubbed_row(a)['lat'] == a['lat']
    assert old.scrubbed_row(a)['lat'] == a['lat']
    feature = {'attributes': {'EXCURSIONID': 1, 'ADDRESS': TEXT}, 'geometry': {'x': -95.123456, 'y': 29.123456}}
    assert tx.safe_history_feature(feature)['geometry'] == feature['geometry']


def test_invalid_list_fails_without_echoing_contents(tmp_path):
    from export.removals import RemovalList
    path = tmp_path / 'requests.json'
    path.write_text('[{"match": "PRIVATE_REQUEST_CONTENT"}]')
    with pytest.raises(ValueError) as err:
        RemovalList.load(path)
    assert 'PRIVATE_REQUEST_CONTENT' not in str(err.value)


def test_text_replacement_is_literal_and_case_sensitive_opt_in():
    p = policy(entry(match='a.b', replacement='\\1', case_sensitive=True))
    assert p.apply({'note': 'a.b A.B axb'}) == {'note': '\\1 A.B axb'}


def test_every_payload_and_history_only_rows(tmp_path):
    p = policy(entry(match='public phrase'))
    for name in ['waters.json', 'dischargers.json', 'outfalls.json', 'feed.xml', 'extra.txt']:
        path = tmp_path / name
        path.write_text(json.dumps({'note': 'PUBLIC PHRASE'}) if name.endswith('.json') else '<p>PUBLIC PHRASE</p>')
    p.publish(tmp_path)
    assert p.enforce(tmp_path) == 0
    assert all('public phrase' not in x.read_text().lower() for x in tmp_path.iterdir())


def test_cli_ids_only_and_private_fetch(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('removal_cli', Path(__file__).resolve().parents[2] / 'scripts/removal_list.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    remote = [entry(match='PRIVATE_REQUEST_CONTENT')]
    def transfer(action, path):
        if action == 'get':
            path.write_text(json.dumps(remote))
        else:
            remote[:] = json.loads(path.read_text())
        return True
    monkeypatch.setattr(cli, 'transfer', transfer)
    assert cli.main(['list']) == 0
    assert capsys.readouterr().out == 'request-001\n'
    assert cli.main(['remove', 'request-001']) == 0 and remote == []
    added = tmp_path / 'entry.json'
    added.write_text(json.dumps(entry(match='PRIVATE_REQUEST_CONTENT')))
    assert cli.main(['add', '--file', str(added)]) == 0
    assert capsys.readouterr().out == ''
    dest = tmp_path / 'private' / 'requests.json'
    cli.fetch(dest)
    assert dest.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(cli, 'transfer', lambda *a: False)
    cli.fetch(dest)
    assert json.loads(dest.read_text()) == []


def test_history_record_removal_without_current_source_record():
    p = policy(entry('record', 'archived:9', {'source_id': 'archived'}))
    assert p.apply({'intervals': {'water': [['start', 'end', 'red', 'rule', 'archived:9']]}}) == {'intervals': {'water': []}}
    assert p.apply({'event_id': 'other:1', 'note': 'Sample'})['note'] == 'Sample'


def test_postcheck_nested_hit_removes_event_not_just_raw(tmp_path, capsys):
    p = policy(entry())
    path = tmp_path / 'event.json'
    path.write_text(json.dumps({'event_id': 'a:1', 'raw': {'notes': 'Sample'}}))
    assert p.enforce(tmp_path) == 1
    assert path.read_text().strip() in ('', 'null')
    assert 'Sample' not in capsys.readouterr().out


def test_csv_requested_field_is_removed_from_header_too(tmp_path):
    p = policy(entry('field', 'contact'))
    path = tmp_path / 'rows.csv'
    path.write_text('event_id,contact,note\na:1,Sample,public\n')
    p.register([{'event_id': 'a:1', 'contact': 'Sample'}])
    p.publish(tmp_path)
    assert path.read_text().splitlines() == ['event_id,note', 'a:1,public']
    assert p.enforce(tmp_path) == 0


def test_record_request_removes_unstructured_payload(tmp_path):
    p = policy(entry('record', 'Sample'))
    path = tmp_path / 'feed.xml'
    path.write_text('<feed><entry>Sample</entry></feed>')
    p.publish(tmp_path)
    assert path.read_text().strip() in ('', 'null')


def test_scoped_field_case_sensitive_path():
    p = policy(entry('field', 'raw.Contact', case_sensitive=True))
    assert p.apply({'raw': {'contact': 'kept'}}) == {'raw': {'contact': 'kept'}}


def test_record_removal_keeps_unrelated_id_references():
    p = policy(entry('record', 'a:1'))
    assert p.apply({'events': ['a:1', 'b:1']}) == {'events': ['b:1']}


def test_montana_saved_advisory_keeps_full_source_narrative():
    from ingest import mt_deq_hab_map as mt
    row = {'advisory_issued': '11/1/2026 HAB warning: ' + TEXT,
           'advisory_lifted': 'lifted 11/12/2026 by ' + TEXT}
    got = mt.safe_rows({'features': [{'attributes': row, 'geometry': {'x': -111.123456, 'y': 46.123456}}]})
    assert got['features'][0]['attributes'] == row


def test_arkansas_published_beach_label_keeps_added_text():
    from ingest import ar_adh_swim_beaches as ar
    assert ar.read(['SB901 - Example Beach - ' + TEXT])['SB901'] == 'Example Beach - ' + TEXT


def test_miami_keeps_source_points_and_utility_name():
    from ingest import fl_miami_dade_sso as miami
    row = {'LAT': 25.123456, 'LON': -80.123456, 'UTILITYNAME': TEXT}
    got = miami.safe_attributes(row)
    assert got['LAT'] == row['LAT'] and got['LON'] == row['LON']
    assert got['UTILITYNAME'] == TEXT


def test_colorado_download_keeps_extra_source_columns():
    from ingest import co_cdphe_toxic_algae as co
    text = ','.join([*co.COLUMNS, 'Contact']) + '\n' + ','.join([''] * len(co.COLUMNS) + [TEXT]) + '\n'
    assert TEXT in co.scrubbed_csv(text)


def test_portland_notice_keeps_source_contact_lines():
    from ingest import or_bes_news as portland
    page = '<main><h1>Title</h1><p>Overflow began today.</p><p>Media Contact</p><p>' + TEXT + '</p></main>'
    assert TEXT in portland.page_lines(page)['lines']


@pytest.mark.parametrize('kind', ['field', 'record'])
@pytest.mark.parametrize('scope', [{}, {'source_id': 'a'}, {'event_id': 'a:1'},
                                    {'source_id': 'a', 'event_id': 'a:1'}])
def test_field_and_record_scope_matrix(kind, scope):
    p = policy(entry(kind, 'note' if kind == 'field' else 'Sample', scope))
    row = {'source_id': 'a', 'event_id': 'a:1', 'note': 'Sample'}
    out = p.apply(row)
    assert out is None if kind == 'record' else 'note' not in out
    if scope:
        other = {**row, 'source_id': 'b', 'event_id': 'b:1'}
        assert p.apply(other) == other


def test_numeric_and_scalar_record_copies_are_checked(tmp_path):
    p = policy(entry('text', '12345'))
    path = tmp_path / 'numeric.json'
    path.write_text('{"event_id":"a:1", "number":12345}')
    p.publish(tmp_path)
    assert '12345' not in path.read_text()
    p = policy(entry('record', 'Sample'))
    path.write_text('{"labels":["Sample","Other"]}')
    p.publish(tmp_path)
    assert json.loads(path.read_text()) == {'labels': ['Other']}


def test_compact_global_field_removal_drops_column(tmp_path):
    p = policy(entry('field', 'note'))
    path = tmp_path / 'index.json'
    path.write_text(json.dumps({'fields': ['event_id', 'note'], 'rows': [['a:1', 'Sample']]}))
    p.publish(tmp_path)
    assert json.loads(path.read_text()) == {'fields': ['event_id'], 'rows': [['a:1']], 'count': 1}


def test_final_check_sees_entity_encoded_feed_text(tmp_path, capsys):
    p = policy(entry(match='Sample & Other'))
    path = tmp_path / 'feed.xml'
    path.write_text('<feed>Sample &amp; Other</feed>')
    assert p.enforce(tmp_path) == 1
    assert path.read_text() == ''
    assert 'Sample' not in capsys.readouterr().out


def test_notice_parsers_keep_unselected_source_text():
    from pathlib import Path
    from ingest import oh_fremont_cso as fremont, oh_avon_lake_cso as avon
    fixtures = Path(__file__).parent / 'fixtures'
    for module, pattern in [(fremont, 'oh_fremont*texts.json'), (avon, 'oh_avon*texts.json')]:
        files = sorted(fixtures.glob(pattern))
        assert files
        text = next(v for v in json.loads(files[0].read_text()).values() if v)
        assert module.parse(text)['source_text'] == text


def test_removed_geojson_feature_keeps_no_orphan_geometry(tmp_path):
    path = tmp_path / 'map.geojson'
    feature = {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [-80, 30]},
               'properties': {'event_id': 'a:1', 'note': 'Sample'}}
    path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [feature]}))
    p = policy(entry('record', 'a:1'))
    p.publish(tmp_path)
    assert json.loads(path.read_text())['features'] == []
    path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [feature]}))
    p = policy(entry(scope={'event_id': 'a:1'}))
    assert p.enforce(tmp_path) == 1
    assert json.loads(path.read_text())['features'] == []


def test_history_interval_scope_and_postcheck_boundary(tmp_path):
    p = policy(entry(scope={'event_id': 'a:1'}))
    path = tmp_path / 'history.json'
    rows = [['start', 'end', 'red', 'Sample', eid] for eid in ('a:1', 'b:1')]
    path.write_text(json.dumps({'intervals': {'water': rows}}))
    p.publish(tmp_path)
    assert json.loads(path.read_text())['intervals']['water'][1] == rows[1]
    path.write_text(json.dumps({'intervals': {'water': rows}}))
    assert p.enforce(tmp_path) == 1
    assert json.loads(path.read_text())['intervals']['water'] == [rows[1]]


def test_postcheck_record_id_request_rejects_new_standalone_file(tmp_path, capsys):
    p = policy(entry('record', 'a:1'))
    path = tmp_path / 'late.json'
    path.write_text('{"event_id":"a:1","note":"public"}')
    assert p.enforce(tmp_path) == 1
    assert json.loads(path.read_text()) is None
    assert 'request-001' in capsys.readouterr().out


def test_postcheck_drops_every_record_for_repeated_nested_match(tmp_path):
    p = policy(entry())
    path = tmp_path / 'events.json'
    path.write_text(json.dumps({'events': [
        {'event_id': f'a:{i}', 'raw': {'notes': ['Sample']}} for i in (1, 2)]}))
    assert p.enforce(tmp_path) == 1
    assert json.loads(path.read_text()) == {'events': []}


def test_record_identifier_matches_whole_id_not_an_id_prefix():
    p = policy(entry('record', 'a:1'))
    row = {'event_id': 'a:10', 'note': 'public'}
    assert p.apply(row) == row
    assert p.apply({'event_id': 'A:1'}) is None


def test_record_match_in_a_dictionary_key_is_not_published(tmp_path):
    p = policy(entry('record', 'Sample'))
    path = tmp_path / 'records.json'
    path.write_text('{"Sample":{"note":"public"},"Other":{"note":"public"}}')
    p.publish(tmp_path)
    assert json.loads(path.read_text()) == {'Other': {'note': 'public'}}


def test_record_removal_updates_its_envelope_count():
    p = policy(entry('record', 'a:1'))
    assert p.apply({'count': 2, 'events': [{'event_id': 'a:1'}, {'event_id': 'a:2'}]}) == {
        'count': 1, 'events': [{'event_id': 'a:2'}]}


def test_postcheck_does_not_log_requested_text_in_filename(tmp_path, capsys):
    p = policy(entry())
    (tmp_path / 'Sample.json').write_text('{"event_id":"a:1","note":"Sample"}')
    p.enforce(tmp_path)
    log = capsys.readouterr().out
    assert 'Sample' not in log
    assert 'request-001' in log and '.json' in log
