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
    state = {'sha256': 'digest1', 'last_modified': 'date1', 'read_at': 'read1'}
    (b / state_file).write_text(json.dumps(state))
    archive = tmp_path / 'frozen.tar.gz'; SP.pack_frozen(archive, tmp_path)
    baseline = tmp_path / 'baseline.json'; SP.frozen_baseline(baseline, tmp_path)
    state['read_at'] = 'read2'; (b / state_file).write_text(json.dumps(state))
    assert SP.pack_frozen(tmp_path / 'unused.gz', tmp_path, baseline) == 3
    hot = tmp_path / 'build.tar.gz'; SP.pack_build(hot, tmp_path)
    fresh = tmp_path / 'fresh'; SP.unpack_build(hot, fresh); SP.unpack_frozen(archive, fresh)
    assert json.loads((fresh / 'data/build' / state_file).read_text())['read_at'] == 'read2'
    state[changed] = 'version2'; (b / state_file).write_text(json.dumps(state))
    assert SP.pack_frozen(tmp_path / 'changed.gz', tmp_path, baseline) == 0


def test_frozen_unpack_retry_after_hot_upload_failed(tmp_path):
    # The legacy hot object has no split marker, but frozen upload already succeeded.
    b = source(tmp_path)
    archive = tmp_path / 'frozen.tar.gz'; SP.pack_frozen(archive, tmp_path)
    fresh = tmp_path / 'fresh'; source(fresh)
    SP.unpack_frozen(archive, fresh)
    baseline = tmp_path / 'baseline.json'; SP.frozen_baseline(baseline, fresh)
    assert SP.pack_frozen(tmp_path / 'unused.gz', fresh, baseline) == 3
    hot = tmp_path / 'build.tar.gz'; SP.pack_build(hot, fresh)
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
