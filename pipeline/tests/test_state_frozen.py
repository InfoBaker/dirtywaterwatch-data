"""Split archives keep a complete events tree and refuse incomplete frozen history."""
import json
import shutil
import tarfile

import pytest
from test_state_history import SP, SAT, r2, puts
from test_state_workflows import checkout, seed, simulate, puts as workflow_puts, STANDINS, REFRESH_STANDIN

MD = 'md-mde-sewer-overflows-2005-2023'
CA = 'ca-swrcb-ciwqs-sso-2006-order'
NY = 'ny-dec-sprtk-2013-2021'


def source(root, sid=MD, n=10, version='v1'):
    b = root / 'data/build'
    p = b / 'events' / f'{sid}.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'records': [{'event_id': f'{sid}:{i}'} for i in range(n)],
                             'meta': {'table_version': version}}))
    return b


def test_split_migration_roundtrip_and_unchanged_versions(tmp_path):
    b = source(tmp_path)
    source(tmp_path, 'live')
    before = SP.event_counts(b)
    frozen, hot = tmp_path / 'frozen.tar.gz', tmp_path / 'build.tar.gz'
    assert SP.pack_frozen(frozen, tmp_path) == 0
    SP.pack_build(hot, tmp_path)
    assert SP.event_counts(b) == before  # packing never moves the files
    assert set(SP.event_counts(hot)) == {'live'}
    assert set(SP.event_counts(frozen)) == {MD}
    fresh = tmp_path / 'fresh'
    SP.unpack_build(hot, fresh)
    SP.unpack_frozen(frozen, fresh)
    assert SP.event_counts(fresh / 'data/build') == before
    SP.frozen_baseline(tmp_path / 'baseline.json', fresh)
    p = fresh / 'data/build/events' / f'{MD}.json'
    d = json.loads(p.read_text()); d['meta']['checked_at'] = 'later'; p.write_text(json.dumps(d))
    assert SP.pack_frozen(tmp_path / 'unused.gz', fresh, tmp_path / 'baseline.json') == 3
    d['meta']['table_version'] = 'v2'; p.write_text(json.dumps(d))
    assert SP.pack_frozen(tmp_path / 'changed.gz', fresh, tmp_path / 'baseline.json') == 0


@pytest.mark.parametrize('damage', ['missing', 'unreadable', 'drop'])
def test_frozen_drop_holds_both_and_blocks_save(tmp_path, r2, damage):
    b = source(tmp_path)
    source(tmp_path, 'live')
    frozen, hot = tmp_path / 'frozen.tar.gz', tmp_path / 'build.tar.gz'
    SP.pack_frozen(frozen, tmp_path); SP.pack_build(hot, tmp_path)
    counts = tmp_path / 'counts.json'; SP.write_counts(b, counts)
    p = b / 'events' / f'{MD}.json'
    if damage == 'missing': p.unlink()
    elif damage == 'unreadable': p.write_text('{')
    else: source(tmp_path, n=1)
    drops = SP.guard(counts, b, b / 'history-guard.json', hot, '5', SAT, frozen=frozen)
    assert drops[0]['source'] == MD
    assert 'state/held/frozen-2026-11-21-5.tar.gz' in puts(r2)
    assert not SP.save_check(counts, b, hot, frozen=frozen)
    counts.unlink()  # fallback must count both archives too
    assert not SP.save_check(counts, b, hot, frozen=frozen)


def test_frozen_manifest_rejects_missing_member_before_extract(tmp_path):
    source(tmp_path)
    frozen = tmp_path / 'frozen.tar.gz'; SP.pack_frozen(frozen, tmp_path)
    bad = tmp_path / 'bad.tar.gz'
    with tarfile.open(frozen) as src, tarfile.open(bad, 'w:gz') as dst:
        for m in src:
            if not m.name.endswith(f'{MD}.json'):
                dst.addfile(m, src.extractfile(m) if m.isfile() else None)
    fresh = tmp_path / 'fresh'
    with pytest.raises(SP.Unreadable): SP.unpack_frozen(bad, fresh)
    assert not (fresh / 'data/build').exists()


def test_frozen_monthly_retries_failed_upload(tmp_path, r2, monkeypatch):
    rec = tmp_path / 'frozen-generations.json'; src = tmp_path / 'frozen.tar.gz'; src.write_bytes(b'archive')
    assert SP.generations_plan(rec, '1', SAT, archive='frozen') == ['state/monthly/frozen-2026-11.tar.gz']
    monkeypatch.setenv('FAKE_R2_FAIL_PUT', 'state/monthly/frozen-2026-11.tar.gz')
    assert SP.generations_put(src, rec, '1', SAT, archive='frozen') == []
    monkeypatch.setenv('FAKE_R2_FAIL_PUT', '')
    assert SP.generations_plan(rec, '2', SAT, archive='frozen')
    assert SP.generations_put(src, rec, '2', SAT, archive='frozen')
    assert SP.generations_plan(rec, '3', SAT, archive='frozen') == []


def test_workflow_migrates_then_skips_frozen_upload(tmp_path):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2})
    assert not simulate('refresh.yml', a)['failed']
    assert 'put state/frozen.tar.gz' in workflow_puts(a)
    assert 'put state/monthly/frozen-2026-11.tar.gz' in workflow_puts(a)
    assert workflow_puts(a).index('put state/frozen.tar.gz') < workflow_puts(a).index('put state/build.tar.gz')
    b = checkout(tmp_path / 'b'); shutil.copytree(a / 'r2', b / 'r2', dirs_exist_ok=True); (b / 'r2/.puts').unlink()
    assert not simulate('refresh.yml', b)['failed']
    assert 'put state/frozen.tar.gz' not in workflow_puts(b)
    assert SP.event_counts(b / 'data/build')[MD]['records'] == 10


@pytest.mark.parametrize('failure', ['fetch', 'corrupt', 'absent'])
def test_workflow_failed_frozen_restore_never_saves(tmp_path, failure):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2})
    simulate('refresh.yml', a)
    b = checkout(tmp_path / 'b'); shutil.copytree(a / 'r2', b / 'r2', dirs_exist_ok=True); (b / 'r2/.puts').unlink()
    p = b / 'r2/state/frozen.tar.gz'
    env = {}
    if failure == 'fetch': env['FAKE_R2_FAIL_GET'] = 'state/frozen.tar.gz'
    elif failure == 'corrupt': p.write_bytes(b'bad')
    else: p.unlink(missing_ok=True)
    assert simulate('refresh.yml', b, env)['failed']
    assert workflow_puts(b) == []


def test_workflow_missing_frozen_events_after_refresh_no_save(tmp_path, monkeypatch):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2})
    simulate('refresh.yml', a)
    b = checkout(tmp_path / 'b'); shutil.copytree(a / 'r2', b / 'r2', dirs_exist_ok=True); (b / 'r2/.puts').unlink()
    monkeypatch.setitem(STANDINS, 'Refresh (', REFRESH_STANDIN + f'\nrm data/build/events/{MD}.json\n')
    assert simulate('refresh.yml', b)['failed']
    assert any('state/held/frozen-' in k for k in workflow_puts(b))
    assert 'put state/build.tar.gz' not in workflow_puts(b)
    assert 'put state/frozen.tar.gz' not in workflow_puts(b)


def test_failed_migration_upload_keeps_complete_legacy_build(tmp_path):
    a = checkout(tmp_path); seed(a, events={MD: 10, 'live': 2})
    old = (a / 'r2/state/build.tar.gz').read_bytes()
    assert simulate('refresh.yml', a, {'FAKE_R2_FAIL_PUT': 'state/frozen.tar.gz'})['failed']
    assert (a / 'r2/state/build.tar.gz').read_bytes() == old
    assert SP.event_counts(a / 'r2/state/build.tar.gz')[MD]['records'] == 10


def test_workflow_changes_frozen_only_on_source_version(tmp_path, monkeypatch):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2})
    simulate('refresh.yml', a)
    b = checkout(tmp_path / 'b'); shutil.copytree(a / 'r2', b / 'r2', dirs_exist_ok=True); (b / 'r2/.puts').unlink()
    change = f'''\npython3 - <<'PY'
import json
from pathlib import Path
p = Path('data/build/events/{MD}.json')
d = json.loads(p.read_text()); d['meta'] = {{'table_version': 'new-version'}}; p.write_text(json.dumps(d))
PY
'''
    monkeypatch.setitem(STANDINS, 'Refresh (', REFRESH_STANDIN + change)
    assert not simulate('refresh.yml', b)['failed']
    assert 'put state/frozen.tar.gz' in workflow_puts(b)


def test_month_rollover_copies_unchanged_frozen(tmp_path):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2})
    simulate('refresh.yml', a)
    b = checkout(tmp_path / 'b'); shutil.copytree(a / 'r2', b / 'r2', dirs_exist_ok=True); (b / 'r2/.puts').unlink()
    assert not simulate('refresh.yml', b, {'STATE_NOW': '2026-12-01T01:00:00Z', 'GITHUB_RUN_ID': '1235'})['failed']
    assert 'put state/frozen.tar.gz' not in workflow_puts(b)
    assert 'put state/monthly/frozen-2026-12.tar.gz' in workflow_puts(b)
    assert (b / 'r2/state/monthly/frozen-2026-12.tar.gz').read_bytes() == (a / 'r2/state/frozen.tar.gz').read_bytes()


@pytest.mark.parametrize('split', [False, True])
@pytest.mark.parametrize('damage', ['missing', 'unreadable'])
def test_frozen_companion_state_damage_is_held_and_blocks_save(tmp_path, r2, split, damage):
    b = source(tmp_path, CA)
    p = b / 'ca-swrcb-ciwqs-sso-2006-state.json'
    p.write_text('{"sha256": "v1", "last_modified": "date1"}')
    hot, frozen = tmp_path / 'build.tar.gz', None
    if split:
        frozen = tmp_path / 'frozen.tar.gz'; SP.pack_frozen(frozen, tmp_path)
    SP.pack_build(hot, tmp_path)
    counts = tmp_path / 'counts.json'; SP.write_counts(b, counts)
    if damage == 'missing': p.unlink()
    else: p.write_text('{')
    drops = SP.guard(counts, b, b / 'history-guard.json', hot, '5', SAT, frozen=frozen)
    assert drops and drops[0]['source'] == CA
    assert 'state/held/build-2026-11-21-5.tar.gz' in puts(r2)
    if split: assert 'state/held/frozen-2026-11-21-5.tar.gz' in puts(r2)
    assert not SP.save_check(counts, b, hot, frozen=frozen)
