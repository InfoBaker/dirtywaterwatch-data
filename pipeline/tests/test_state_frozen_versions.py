"""Version keys come from the ingesters, never event timestamps or a whole-file hash."""
import json

import pytest
from test_state_history import SP
from test_state_frozen import source


def test_manifest_uses_actual_ingester_source_ids():
    from ingest import ca_swrcb_ciwqs_sso_2006 as ca, ny_sprtk_history as ny
    assert ca.SOURCE_ID in SP.FROZEN_FEEDS
    assert ny.SOURCE_ID in SP.FROZEN_FEEDS


@pytest.mark.parametrize('sid,state_file,changed', [
    ('ca-swrcb-ciwqs-sso-2006-order', 'ca-swrcb-ciwqs-sso-2006-state.json', 'last_modified'),
    ('ny-dec-sprtk-2013-2021', 'ny-sprtk-history-state.json', 'sha256'),
])
def test_history_state_versions_and_poll_checkpoints(tmp_path, sid, state_file, changed):
    b = source(tmp_path, sid)
    state = {'sha256': 'a' * 64, 'last_modified': '2026-11-20T00:00:00Z', 'read_at': 'read1'}
    (b / state_file).write_text(json.dumps(state))
    archive = tmp_path / 'frozen.tar.gz'; SP.pack_frozen(archive, tmp_path)
    baseline = tmp_path / 'baseline.json'; SP.frozen_baseline(baseline, tmp_path)
    state['read_at'] = 'read2'; (b / state_file).write_text(json.dumps(state))
    assert SP.pack_frozen(tmp_path / 'unused.gz', tmp_path, baseline) == 3
    hot = tmp_path / 'build.tar.gz'; SP.pack_build(hot, tmp_path, saved_frozen=archive)
    fresh = tmp_path / 'fresh'; SP.unpack_build(hot, fresh); SP.unpack_frozen(archive, fresh)
    assert json.loads((fresh / 'data/build' / state_file).read_text())['read_at'] == 'read2'
    state[changed] = 'b' * 64 if changed == 'sha256' else '2026-11-21T00:00:00Z'; (b / state_file).write_text(json.dumps(state))
    assert SP.pack_frozen(tmp_path / 'changed.gz', tmp_path, baseline) == 0


def test_frozen_unpack_retry_after_hot_upload_failed(tmp_path):
    # The legacy hot object has no split marker, but frozen upload already succeeded.
    b = source(tmp_path)
    archive = tmp_path / 'frozen.tar.gz'; SP.pack_frozen(archive, tmp_path)
    fresh = tmp_path / 'fresh'; source(fresh)
    SP.unpack_frozen(archive, fresh)
    baseline = tmp_path / 'baseline.json'; SP.frozen_baseline(baseline, fresh)
    assert SP.pack_frozen(tmp_path / 'unused.gz', fresh, baseline) == 3
    hot = tmp_path / 'build.tar.gz'; SP.pack_build(hot, fresh, saved_frozen=archive)
    assert SP.event_counts(hot) == {}


def test_corrupt_history_state_blocks_save(tmp_path):
    b = source(tmp_path, 'ca-swrcb-ciwqs-sso-2006-order')
    (b / 'ca-swrcb-ciwqs-sso-2006-state.json').write_text('{')
    with pytest.raises((SP.Unreadable, ValueError)):
        SP.pack_frozen(tmp_path / 'frozen.tar.gz', tmp_path)


@pytest.mark.parametrize('kind', ['events', 'state', 'parent'])
def test_frozen_inputs_refuse_links_before_reading(tmp_path, kind):
    b = source(tmp_path)
    sid = 'md-mde-sewer-overflows-2005-2023'
    if kind == 'events':
        path = b / 'events' / f'{sid}.json'; path.unlink(); path.symlink_to(tmp_path / 'not-an-input')
    elif kind == 'state':
        path = b / 'generic' / f'{sid}-fetch.json'; path.parent.mkdir(); path.symlink_to(tmp_path / 'not-an-input')
    else:
        (b / 'events').rename(b / 'original'); (b / 'events').symlink_to(b / 'original', target_is_directory=True)
    with pytest.raises(SP.Unreadable): SP.frozen_versions(tmp_path)


@pytest.mark.parametrize('version', [None, '', False, 0, -1, {}, [], 'not-a-version'])
def test_fix_unknown_marker_never_skips_changed_history(tmp_path, version):
    sid = 'md-mde-sewer-overflows-2005-2023'
    b = source(tmp_path, version=version)
    state = b / 'generic' / f'{sid}-fetch.json'; state.parent.mkdir()
    state.write_text(json.dumps({'sha256': 'a' * 64}))
    old = tmp_path / 'old.gz'; SP.pack_frozen(old, tmp_path)
    SP.unpack_frozen(old, tmp_path)
    baseline = tmp_path / 'baseline.json'; SP.frozen_baseline(baseline, tmp_path)
    source(tmp_path, n=11, version=version)
    state.write_text(json.dumps({'sha256': 'b' * 64}))
    new = tmp_path / 'new.gz'
    assert SP.pack_frozen(new, tmp_path, baseline) == 0
    assert SP.event_counts(new)[sid]['records'] == 11


def test_hot_checkpoint_refuses_linked_parent_before_hashing(tmp_path, monkeypatch):
    b = source(tmp_path)
    events = b / 'events'; events.rename(b / 'original')
    events.symlink_to(b / 'original', target_is_directory=True)
    read = type(events).read_bytes
    def no_linked_read(path):
        assert not any(p.is_symlink() for p in (path, *path.parents)), 'must refuse before reading'
        return read(path)
    monkeypatch.setattr(type(events), 'read_bytes', no_linked_read)
    with pytest.raises(SP.Unreadable):
        SP.pack_build(tmp_path / 'checkpoint.gz', tmp_path)


@pytest.mark.parametrize('sid,state_file', [
    ('ca-swrcb-ciwqs-sso-2006-order', 'ca-swrcb-ciwqs-sso-2006-state.json'),
    ('ny-dec-sprtk-2013-2021', 'ny-sprtk-history-state.json'),
])
@pytest.mark.parametrize('digest', [None, '', False, [], {}, 'not-a-digest'])
def test_unknown_history_digest_forces_save(tmp_path, sid, state_file, digest):
    b = source(tmp_path, sid)
    (b / state_file).write_text(json.dumps({'sha256': digest, 'last_modified': '2026-11-20T00:00:00Z'}))
    old = tmp_path / 'old.gz'; SP.pack_frozen(old, tmp_path)
    SP.unpack_frozen(old, tmp_path)
    baseline = tmp_path / 'baseline.json'; SP.frozen_baseline(baseline, tmp_path)
    source(tmp_path, sid, n=11)
    new = tmp_path / 'new.gz'
    assert SP.pack_frozen(new, tmp_path, baseline) == 0
    assert SP.event_counts(new)[sid]['records'] == 11


@pytest.mark.parametrize('marker', ['{', '{}', '{"members": null}'])
def test_invalid_hot_checkpoint_marker_cannot_overwrite_newer_history(tmp_path, marker):
    sid = 'md-mde-sewer-overflows-2005-2023'
    source(tmp_path)
    frozen = tmp_path / 'old.gz'; SP.pack_frozen(frozen, tmp_path)
    source(tmp_path, n=11)
    hot = tmp_path / 'hot.gz'; SP.pack_build(hot, tmp_path)
    fresh = tmp_path / 'retry'; SP.unpack_build(hot, fresh)
    (fresh / 'data/build' / SP.FROZEN_HOT).write_text(marker)
    with pytest.raises(SP.Unreadable):
        SP.unpack_frozen(frozen, fresh)
    assert SP.event_counts(fresh / 'data/build')[sid]['records'] == 11
