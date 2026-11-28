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


def source(root, sid=MD, n=10, version=1677163934):
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
    SP.pack_build(hot, tmp_path, saved_frozen=frozen)
    assert SP.event_counts(b) == before  # packing never moves the files
    assert set(SP.event_counts(hot)) == {'live'}
    assert set(SP.event_counts(frozen)) == {MD}
    fresh = tmp_path / 'fresh'
    SP.unpack_build(hot, fresh)
    SP.unpack_frozen(frozen, fresh)
    assert SP.event_counts(fresh / 'data/build') == before
    SP.frozen_baseline(tmp_path / 'baseline.json', fresh)
    assert SP.pack_frozen(tmp_path / 'unused.gz', fresh, tmp_path / 'baseline.json') == 3
    p = fresh / 'data/build/events' / f'{MD}.json'
    d = json.loads(p.read_text()); d['meta']['checked_at'] = 'later'; p.write_text(json.dumps(d))
    # Even an operational clock changes the exact bytes that must survive in one primary archive.
    assert SP.pack_frozen(tmp_path / 'clock-changed.gz', fresh, tmp_path / 'baseline.json') == 0
    d['meta']['table_version'] = 1677163935; p.write_text(json.dumps(d))
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
    assert SP.generations_plan(rec, '1', SAT, archive='frozen') == ['state/daily/frozen-Sat.tar.gz', 'state/monthly/frozen-2026-11.tar.gz']
    monkeypatch.setenv('FAKE_R2_FAIL_PUT', 'state/monthly/frozen-2026-11.tar.gz')
    assert SP.generations_put(src, rec, '1', SAT, archive='frozen') == ['state/daily/frozen-Sat.tar.gz']
    monkeypatch.setenv('FAKE_R2_FAIL_PUT', '')
    assert SP.generations_plan(rec, '2', SAT, archive='frozen')
    assert SP.generations_put(src, rec, '2', SAT, archive='frozen')
    assert SP.generations_plan(rec, '3', SAT, archive='frozen') == []


def test_workflow_migrates_then_skips_frozen_upload(tmp_path):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2}, versions={MD: '1677163934'})
    assert not simulate('refresh.yml', a)['failed']
    assert 'put state/frozen.tar.gz' in workflow_puts(a)
    assert 'put state/monthly/frozen-2026-11.tar.gz' in workflow_puts(a)
    assert workflow_puts(a).index('put state/build.tar.gz') < workflow_puts(a).index('put state/frozen.tar.gz')
    b = checkout(tmp_path / 'b'); shutil.copytree(a / 'r2', b / 'r2', dirs_exist_ok=True); (b / 'r2/.puts').unlink()
    assert not simulate('refresh.yml', b)['failed']
    assert 'put state/frozen.tar.gz' not in workflow_puts(b)
    assert SP.event_counts(b / 'data/build')[MD]['records'] == 10


@pytest.mark.parametrize('failure', ['fetch', 'corrupt', 'absent'])
def test_workflow_failed_frozen_restore_never_saves(tmp_path, failure):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2}, versions={MD: '1677163934'})
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
    assert 'put state/build.tar.gz' in workflow_puts(b)
    assert 'put state/frozen.tar.gz' not in workflow_puts(b)


def test_failed_migration_upload_keeps_complete_legacy_build(tmp_path):
    a = checkout(tmp_path); seed(a, events={MD: 10, 'live': 2})
    assert simulate('refresh.yml', a, {'FAKE_R2_FAIL_PUT': 'state/frozen.tar.gz'})['failed']
    assert 'put state/build.tar.gz' in workflow_puts(a)
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
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2}, versions={MD: '1677163934'})
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


# Fix-pass regressions: each starts with saved state, then changes or interrupts a later run.
def next_run(tmp_path, previous, name='next'):
    run = checkout(tmp_path / name)
    shutil.copytree(previous / 'r2', run / 'r2', dirs_exist_ok=True)
    (run / 'r2/.puts').unlink(missing_ok=True)
    return run


def test_fix_frozen_drop_saves_new_hot_history_then_fails(tmp_path, monkeypatch):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2})
    assert not simulate('refresh.yml', a)['failed']
    b = next_run(tmp_path, a)
    old = (b / 'r2/state/frozen.tar.gz').read_bytes()
    monkeypatch.setitem(STANDINS, 'Refresh (', REFRESH_STANDIN + f'''\npython3 - <<'PY'
import json
from pathlib import Path
p = Path('data/build/events/live.json')
d = json.loads(p.read_text()); d['records'].append({{'event_id': 'live:later'}}); p.write_text(json.dumps(d))
Path('data/build/events/{MD}.json').unlink()
PY
''')
    assert simulate('refresh.yml', b)['failed']
    assert 'put state/build.tar.gz' in workflow_puts(b)
    assert 'put state/frozen.tar.gz' not in workflow_puts(b)
    assert (b / 'r2/state/frozen.tar.gz').read_bytes() == old
    assert SP.event_counts(b / 'r2/state/build.tar.gz')['live']['records'] == 3
    c = next_run(tmp_path, b, 'third')
    monkeypatch.setitem(STANDINS, 'Refresh (', REFRESH_STANDIN)
    assert not simulate('refresh.yml', c)['failed']
    assert SP.event_counts(c / 'data/build')[MD]['records'] == 10
    assert SP.event_counts(c / 'data/build')['live']['records'] == 3


@pytest.mark.parametrize('operation', ['frozen-plan', 'counts'])
def test_fix_optional_failure_still_saves_both_primaries(tmp_path, operation):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2})
    assert not simulate('refresh.yml', a)['failed']
    b = next_run(tmp_path, a)
    script = b / 'scripts/state_paths.py'
    text = script.read_text()
    trigger = "a.cmd == 'counts'" if operation == 'counts' else "a.cmd == 'generations' and a.action == 'plan' and a.archive == 'frozen'"
    text = text.replace('a = ap.parse_args(argv)', 'a = ap.parse_args(argv)\n    if ' + trigger + ':\n        return 1')
    assert text != script.read_text()
    script.write_text(text)
    # Unknown marker forces a frozen save; neither optional operation may prevent it.
    r = simulate('refresh.yml', b)
    assert not r['failed'], r['log']
    assert 'put state/build.tar.gz' in workflow_puts(b)
    assert 'put state/frozen.tar.gz' in workflow_puts(b)


def test_fix_frozen_daily_ring_rollover_and_retry(tmp_path, r2, monkeypatch):
    from datetime import timedelta
    rec = tmp_path / 'frozen-generations.json'
    src = tmp_path / 'frozen.tar.gz'; src.write_bytes(b'complete frozen archive')
    monkeypatch.setenv('FAKE_R2_FAIL_PUT', 'state/daily/frozen-Sat.tar.gz')
    assert 'state/daily/frozen-Sat.tar.gz' in SP.generations_plan(rec, '1', SAT, archive='frozen')
    SP.generations_put(src, rec, '1', SAT, archive='frozen')
    monkeypatch.setenv('FAKE_R2_FAIL_PUT', '')
    assert SP.generations_plan(rec, '2', SAT, archive='frozen') == ['state/daily/frozen-Sat.tar.gz']
    SP.generations_put(src, rec, '2', SAT, archive='frozen')
    assert SP.generations_plan(rec, '3', SAT, archive='frozen') == []
    for day in range(1, 9):
        now = SAT + timedelta(days=day)
        assert len(SP.generations_plan(rec, str(day + 3), now, archive='frozen')) == 1
        SP.generations_put(src, rec, str(day + 3), now, archive='frozen')
    assert len(list((r2 / 'state/daily').glob('frozen-*.tar.gz'))) == 7


def test_fix_promotion_uses_saved_membership_and_requires_upload_confirmation(tmp_path, monkeypatch):
    feeds = dict(SP.FROZEN_FEEDS)
    monkeypatch.setattr(SP, 'FROZEN_FEEDS', {k: v for k, v in feeds.items() if k != MD})
    source(tmp_path, MD, version=1677163934)
    b = source(tmp_path, NY)
    (b / 'ny-sprtk-history-state.json').write_text(json.dumps({'sha256': 'a' * 64}))
    old = tmp_path / 'old.gz'; SP.pack_frozen(old, tmp_path)
    # Restore the actual saved frozen manifest alongside Maryland's still-hot history.
    SP.unpack_frozen(old, tmp_path)
    monkeypatch.setattr(SP, 'FROZEN_FEEDS', feeds)
    baseline = tmp_path / 'baseline.json'; SP.frozen_baseline(baseline, tmp_path)
    new = tmp_path / 'new.gz'
    assert SP.pack_frozen(new, tmp_path, baseline) == 0
    hot = tmp_path / 'hot.gz'
    SP.pack_build(hot, tmp_path)  # packing alone is not confirmation of a successful upload
    assert MD in SP.event_counts(hot)
    SP.pack_build(hot, tmp_path, saved_frozen=old)
    assert MD in SP.event_counts(hot)
    SP.pack_build(hot, tmp_path, saved_frozen=new)
    assert MD not in SP.event_counts(hot)
    assert SP.event_counts(new)[MD]['records'] == 10


@pytest.mark.parametrize('workflow', ['refresh.yml', 'state-build.yml'])
def test_fix_demotion_accepts_old_schema_and_copies_before_retiring(tmp_path, workflow):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, NY: 10, 'live': 2})
    assert not simulate('refresh.yml', a)['failed']
    b = next_run(tmp_path, a)
    script = b / 'scripts/state_paths.py'
    script.write_text(script.read_text().replace('FROZEN_MANIFEST =', f'FROZEN_FEEDS.pop({MD!r})\nFROZEN_MANIFEST =', 1))
    # Stop at the replacement frozen upload. The hot checkpoint must already hold Maryland.
    r = simulate(workflow, b, {'FAKE_R2_FAIL_PUT': 'state/frozen.tar.gz'})
    if workflow == 'state-build.yml':
        assert not r['failed'], r['log']
        assert SP.event_counts(b / 'data/build')[MD]['records'] == 10
        return
    assert r['failed']
    assert 'put state/build.tar.gz' in workflow_puts(b)
    assert SP.event_counts(b / 'r2/state/build.tar.gz')[MD]['records'] == 10
    c = next_run(tmp_path, b, 'retry'); shutil.copy(script, c / 'scripts/state_paths.py')
    assert not simulate(workflow, c)['failed']
    assert SP.event_counts(c / 'r2/state/build.tar.gz')[MD]['records'] == 10
    assert MD not in SP.event_counts(c / 'r2/state/frozen.tar.gz')


def test_fix_interrupted_checkpoint_counts_fallback_uses_new_hot_history(tmp_path):
    b = source(tmp_path, n=10)
    frozen = tmp_path / 'frozen.gz'; SP.pack_frozen(frozen, tmp_path)
    source(tmp_path, n=20, version=1677163935)
    hot = tmp_path / 'hot.gz'; SP.pack_build(hot, tmp_path)
    fresh = tmp_path / 'retry'
    SP.unpack_build(hot, fresh); SP.unpack_frozen(frozen, fresh)
    assert SP.event_counts(fresh / 'data/build')[MD]['records'] == 20
    # The optional counts write failed. The fallback must follow the same checkpoint precedence.
    baseline = SP.restored_baseline(tmp_path / 'missing-counts.json', hot, frozen)
    assert baseline[MD]['records'] == 20


def test_fix_promoted_companion_drop_checks_hot_and_frozen_archives(tmp_path, monkeypatch):
    feeds = dict(SP.FROZEN_FEEDS)
    monkeypatch.setattr(SP, 'FROZEN_FEEDS', {NY: feeds[NY]})
    b = source(tmp_path, NY)
    (b / 'ny-sprtk-history-state.json').write_text(json.dumps({'sha256': 'a' * 64}))
    frozen = tmp_path / 'frozen.gz'; SP.pack_frozen(frozen, tmp_path)
    source(tmp_path, MD)
    state = b / feeds[MD][0]; state.parent.mkdir()
    state.write_text(json.dumps({'sha256': 'b' * 64}))
    hot = tmp_path / 'hot.gz'; SP.pack_build(hot, tmp_path, saved_frozen=frozen)
    fresh = tmp_path / 'retry'; SP.unpack_build(hot, fresh); SP.unpack_frozen(frozen, fresh)
    monkeypatch.setattr(SP, 'FROZEN_FEEDS', feeds)
    counts = tmp_path / 'counts.json'; SP.write_counts(fresh / 'data/build', counts)
    (fresh / 'data/build' / feeds[MD][0]).unlink()
    assert not SP.save_check(counts, fresh / 'data/build', hot, frozen)


@pytest.mark.parametrize('failed_build_put', [1, 2])
def test_copy_first_demotion_interruption_at_each_hot_upload(tmp_path, monkeypatch, failed_build_put):
    from test_state_workflows import WRANGLER
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, NY: 10, 'live': 2})
    assert not simulate('refresh.yml', a)['failed']
    b = next_run(tmp_path, a)
    old_frozen = (b / 'r2/state/frozen.tar.gz').read_bytes()
    script = b / 'scripts/state_paths.py'
    script.write_text(script.read_text().replace('FROZEN_MANIFEST =', f'FROZEN_FEEDS.pop({MD!r})\nFROZEN_MANIFEST =', 1))
    monkeypatch.setitem(STANDINS, 'Refresh (', REFRESH_STANDIN + f'''\npython3 - <<'PY'
import json
from pathlib import Path
p = Path('data/build/events/{MD}.json')
d = json.loads(p.read_text()); d['records'].append({{'event_id': '{MD}:later'}}); p.write_text(json.dumps(d))
PY
''')
    wrangler = WRANGLER.replace('  put)\n', f'''  put)
    if [ "$key" = state/build.tar.gz ]; then
      count=0; [ ! -f "$FAKE_R2/.build-count" ] || read count < "$FAKE_R2/.build-count"
      count=$((count + 1)); echo "$count" > "$FAKE_R2/.build-count"
      [ "$count" != {failed_build_put} ] || exit 1
    fi
''')
    assert simulate('refresh.yml', b, tools={'wrangler': wrangler})['failed']
    if failed_build_put == 1:
        assert (b / 'r2/state/frozen.tar.gz').read_bytes() == old_frozen
    else:
        assert MD not in SP.event_counts(b / 'r2/state/frozen.tar.gz')
        assert SP.event_counts(b / 'r2/state/build.tar.gz')[MD]['records'] == 11
    c = next_run(tmp_path, b, 'retry'); shutil.copy(script, c / 'scripts/state_paths.py')
    monkeypatch.setitem(STANDINS, 'Refresh (', REFRESH_STANDIN)
    assert not simulate('refresh.yml', c)['failed']
    assert SP.event_counts(c / 'r2/state/build.tar.gz')[MD]['records'] == (10 if failed_build_put == 1 else 11)


@pytest.mark.parametrize('split', [False, True])
@pytest.mark.parametrize('damage', ['drop', 'unreadable', 'companion'])
def test_frozen_recovery_keeps_original_and_damaged_bytes(tmp_path, split, damage):
    b = source(tmp_path)
    state = b / SP.FROZEN_FEEDS[MD][0]; state.parent.mkdir()
    state.write_text('{"sha256": "original"}')
    hot, frozen = tmp_path / 'hot.gz', tmp_path / 'frozen.gz'
    SP.pack_build(hot, tmp_path)
    if split:
        SP.pack_frozen(frozen, tmp_path)
        SP.pack_build(hot, tmp_path, saved_frozen=frozen)
    counts = tmp_path / 'counts.json'; SP.write_counts(b, counts)
    event = b / 'events' / f'{MD}.json'
    if damage == 'drop':
        source(tmp_path, n=1, version=1677163935)
        damaged = event
    elif damage == 'unreadable':
        event.write_text('{'); damaged = event
    else:
        state.write_text('{'); damaged = state
    damaged_bytes = damaged.read_bytes()
    assert SP.save_status(counts, b, hot, frozen) == 3
    checkpoint = tmp_path / 'checkpoint.gz'; SP.pack_build(checkpoint, tmp_path)
    assert SP.event_counts(checkpoint)[MD]['records'] == 10
    with tarfile.open(checkpoint) as tf:
        assert any(tf.extractfile(m).read() == damaged_bytes for m in tf
                   if m.isfile() and '/history-recovery/' in m.name)


def test_interrupted_demotion_then_repromotion_keeps_saved_history(tmp_path, monkeypatch):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2}, versions={MD: 1677163934})
    assert not simulate('refresh.yml', a)['failed']
    b = next_run(tmp_path, a)
    script = b / 'scripts/state_paths.py'
    script.write_text(script.read_text().replace('FROZEN_MANIFEST =', f'FROZEN_FEEDS.pop({MD!r})\nFROZEN_MANIFEST =', 1))
    monkeypatch.setitem(STANDINS, 'Refresh (', REFRESH_STANDIN + f'''\npython3 - <<'PY'
import json
from pathlib import Path
p = Path('data/build/events/{MD}.json')
d = json.loads(p.read_text()); d['records'].append({{'event_id': '{MD}:later'}}); p.write_text(json.dumps(d))
PY
''')
    assert simulate('refresh.yml', b, {'FAKE_R2_FAIL_PUT': 'state/frozen.tar.gz'})['failed']
    assert SP.event_counts(b / 'r2/state/build.tar.gz')[MD]['records'] == 11
    assert SP.event_counts(b / 'r2/state/frozen.tar.gz')[MD]['records'] == 10
    c = next_run(tmp_path, b, 'repromoted')  # original configuration promotes Maryland again
    monkeypatch.setitem(STANDINS, 'Refresh (', REFRESH_STANDIN)
    assert not simulate('refresh.yml', c)['failed']
    assert SP.event_counts(c / 'data/build')[MD]['records'] == 11
    assert 'put state/frozen.tar.gz' in workflow_puts(c)
    assert SP.event_counts(c / 'r2/state/frozen.tar.gz')[MD]['records'] == 11


@pytest.mark.parametrize('marker', [None, '{"members": {}}', 'partial'])
def test_incomplete_hot_map_restore_counts_and_recovery_keep_hot(tmp_path, marker):
    b = source(tmp_path, version=1)
    source(tmp_path, NY)
    state = b / SP.FROZEN_FEEDS[MD][0]; state.parent.mkdir()
    state.write_text('{"read_at": "old"}')
    frozen = tmp_path / 'frozen.gz'; SP.pack_frozen(frozen, tmp_path)
    source(tmp_path, n=11, version=2)
    state.write_text('{"read_at": "new"}')
    hot = tmp_path / 'hot.gz'; SP.pack_build(hot, tmp_path)
    # Simulate legacy/incomplete metadata in the successfully saved hot object itself.
    if marker == 'partial':
        checkpoint = json.loads((b / SP.FROZEN_HOT).read_text())
        checkpoint['members'].pop(f'events/{MD}.json')
        checkpoint['members'].pop(SP.FROZEN_FEEDS[MD][0])
        marker = json.dumps(checkpoint)
    if marker is None:
        (b / SP.FROZEN_HOT).unlink()
    else:
        (b / SP.FROZEN_HOT).write_text(marker)
    with tarfile.open(hot, 'w:gz') as tf:
        tf.add(b, arcname=SP.BUILD_DIR)
    fresh = tmp_path / 'retry'; SP.unpack_build(hot, fresh)
    restored = fresh / SP.BUILD_DIR
    expected = (restored / f'events/{MD}.json').read_bytes()
    SP.unpack_frozen(frozen, fresh)
    assert (restored / f'events/{MD}.json').read_bytes() == expected
    assert (restored / SP.FROZEN_FEEDS[MD][0]).read_bytes() == state.read_bytes()
    counts = tmp_path / 'missing-counts.json'
    assert SP.restored_baseline(counts, hot, frozen)[MD]['records'] == 11
    baseline = tmp_path / 'baseline.json'; SP.frozen_baseline(baseline, fresh)
    replacement = tmp_path / 'replacement.gz'
    assert SP.pack_frozen(replacement, fresh, baseline) == 0
    saved = tmp_path / 'saved.gz'; SP.pack_build(saved, fresh, saved_frozen=replacement)
    retry = tmp_path / 'next'; SP.unpack_build(saved, retry); SP.unpack_frozen(replacement, retry)
    assert (retry / SP.BUILD_DIR / f'events/{MD}.json').read_bytes() == expected
    (restored / f'events/{MD}.json').unlink()
    assert SP.save_status(counts, restored, hot, frozen) == 3
    assert (restored / f'events/{MD}.json').read_bytes() == expected
    assert (restored / SP.FROZEN_FEEDS[MD][0]).read_bytes() == state.read_bytes()


@pytest.mark.parametrize('changed', ['records', 'whitespace', 'companion', 'clock'])
def test_exclusion_requires_exact_saved_bytes_and_mismatch_forces_replacement(tmp_path, changed):
    b = source(tmp_path)
    state = b / SP.FROZEN_FEEDS[MD][0]; state.parent.mkdir()
    state.write_text('{"read_at": "old"}')
    frozen = tmp_path / 'old.gz'; SP.pack_frozen(frozen, tmp_path)
    baseline = tmp_path / 'baseline.json'; SP.frozen_baseline(baseline, tmp_path)
    event = b / f'events/{MD}.json'
    target = state if changed == 'companion' else event
    if changed == 'records': source(tmp_path, n=11)
    elif changed == 'companion': state.write_text('{"read_at": "new"}')
    elif changed == 'clock':
        doc = json.loads(event.read_text()); doc['meta']['checked_at'] = 'later'; event.write_text(json.dumps(doc))
    else: event.write_bytes(event.read_bytes() + b'\n')
    hot = tmp_path / 'hot.gz'; SP.pack_build(hot, tmp_path, saved_frozen=frozen)
    with tarfile.open(hot) as tf:
        assert tf.extractfile(f'{SP.BUILD_DIR}/{target.relative_to(b)}').read() == target.read_bytes()
    replacement = tmp_path / 'new.gz'
    assert SP.pack_frozen(replacement, tmp_path, baseline) == 0
    SP.pack_build(hot, tmp_path, saved_frozen=replacement)
    with tarfile.open(hot) as tf:
        assert f'{SP.BUILD_DIR}/{target.relative_to(b)}' not in tf.getnames()


def test_frozen_drop_uses_restored_archive_for_identical_hot_exclusions(tmp_path, monkeypatch):
    a = checkout(tmp_path / 'a'); seed(a, events={MD: 10, 'live': 2}, versions={MD: 1677163934})
    assert not simulate('refresh.yml', a)['failed']
    b = next_run(tmp_path, a)
    monkeypatch.setitem(STANDINS, 'Refresh (', REFRESH_STANDIN + f'\nrm data/build/events/{MD}.json\n')
    assert simulate('refresh.yml', b)['failed']
    assert MD not in SP.event_counts(b / 'r2/state/build.tar.gz')
    assert SP.event_counts(b / 'r2/state/frozen.tar.gz')[MD]['records'] == 10


@pytest.mark.parametrize('random_seed', range(12))
def test_random_membership_upload_and_restore_sequences_preserve_saved_records(tmp_path, monkeypatch, random_seed):
    """A seeded state-machine property: every committed record survives every later successful save.

    Only append records; membership changes and failed uploads must never remove committed history.
    Check record identities across both primary objects, not just counts or the restored directory.
    """
    import io
    import random
    rng = random.Random(random_seed)
    feeds = dict(SP.FROZEN_FEEDS)
    hot, frozen = tmp_path / 'saved-hot.gz', tmp_path / 'saved-frozen.gz'
    ever_saved = set()

    def records(archive):
        if not archive.exists(): return set()
        with tarfile.open(archive) as tf:
            return {r['event_id'] for m in tf if m.isfile() and m.name.startswith(f'{SP.BUILD_DIR}/events/')
                    for r in json.load(tf.extractfile(m))['records']}

    def upload(candidate, archive):
        if archive == hot:
            # Legacy or incomplete checkpoint maps are metadata, never overwrite authority.
            map_kind = rng.choice(['intact', 'missing', 'empty', 'partial'])
            rewritten = candidate.with_suffix('.map.gz')
            with tarfile.open(candidate) as src, tarfile.open(rewritten, 'w:gz') as dst:
                for member in src:
                    payload = src.extractfile(member) if member.isfile() else None
                    if member.name == f'{SP.BUILD_DIR}/{SP.FROZEN_HOT}' and map_kind != 'intact':
                        if map_kind == 'missing': continue
                        mapping = json.load(payload)['members']
                        mapping = dict(list(mapping.items())[::2]) if map_kind == 'partial' else {}
                        content = json.dumps({'members': mapping}).encode()
                        member.size = len(content); payload = io.BytesIO(content)
                    dst.addfile(member, payload)
            candidate = rewritten
        shutil.copyfile(candidate, archive)
        present = records(hot) | records(frozen)
        assert ever_saved <= present, (random_seed, step, failure, ever_saved - present)
        ever_saved.update(present)

    for step in range(30):
        run = tmp_path / f'run-{step}'
        monkeypatch.setattr(SP, 'FROZEN_FEEDS', {sid: states for sid, states in feeds.items() if rng.choice([True, False])})
        if hot.exists(): SP.unpack_build(hot, run)
        if frozen.exists(): SP.unpack_frozen(frozen, run)
        build = run / SP.BUILD_DIR
        restored_ids = {r['event_id'] for p in (build / 'events').glob('*.json')
                        for r in json.loads(p.read_text())['records']}
        assert ever_saved <= restored_ids
        baseline = run / 'baseline.json'; SP.frozen_baseline(baseline, run)
        for sid, states in feeds.items():
            path = build / f'events/{sid}.json'
            if not path.exists(): source(run, sid, n=0)
            doc = json.loads(path.read_text())
            if rng.randrange(3) == 0 or step == 0:
                doc['records'].append({'event_id': f'{sid}:{step}'})
            if rng.randrange(4) == 0: doc['meta']['table_version'] += 1
            path.write_text(json.dumps(doc))
            state = build / states[0]; state.parent.mkdir(parents=True, exist_ok=True)
            if sid == 'fed-beacon-beach-actions':
                # BEACON requires its saved rows, not the version markers used by the other feeds.
                companion = {'years': {'2014': {'rows': {r['event_id']: r for r in doc['records']}}}}
            else:
                companion = {'sha256': 'a' * 64, 'last_modified': '2026-11-20T00:00:00Z'}
            state.write_text(json.dumps(companion))
        # Periodic guaranteed successes ensure the property covers saves after interruptions.
        failure = rng.choice(['checkpoint', 'frozen', 'final-hot', None]) if step % 4 else None
        candidate = run / 'frozen.gz'
        rc = SP.pack_frozen(candidate, run, baseline)
        if rc == 0:
            checkpoint = run / 'checkpoint.gz'; SP.pack_build(checkpoint, run)
            if failure == 'checkpoint': continue
            upload(checkpoint, hot)
            if failure == 'frozen': continue
            upload(candidate, frozen)
        final = run / 'hot.gz'; SP.pack_build(final, run, saved_frozen=frozen if frozen.exists() else None)
        if failure != 'final-hot': upload(final, hot)
