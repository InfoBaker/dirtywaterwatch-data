"""Writers preserve source text; the final requested-removal pass covers their output."""
import json
from export import build as X
from export.removals import RemovalList


def test_parallel_writer_preserves_source_then_requested_removals_apply(tmp_path):
    with X.compact_writes() as emit:
        for i in range(40):
            emit(tmp_path / f'{i}.json', {'event_id': f's:{i}', 'note': 'Jane Example'})
    assert json.loads((tmp_path / '1.json').read_text())['note'] == 'Jane Example'
    policy = RemovalList([{'id': 'req-1', 'added': '2026-11-25', 'kind': 'text', 'match': 'Jane Example'}])
    policy.publish(tmp_path)
    assert policy.enforce(tmp_path) == 0
    assert all(json.loads(p.read_text())['note'] == '[removed on request]' for p in tmp_path.iterdir())


def test_final_check_decodes_json_escapes(tmp_path):
    (tmp_path / 'event.json').write_text('{"event_id":"s:1","note":"Jane\\u0020Example"}')
    policy = RemovalList([{'id': 'req-1', 'added': '2026-11-25', 'kind': 'text', 'match': 'Jane Example'}])
    assert policy.enforce(tmp_path) == 1
    assert json.loads((tmp_path / 'event.json').read_text()) is None
