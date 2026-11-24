"""Temporary-copy verification of the proposed writer hooks; invented names only."""
import json
from pathlib import Path

from export import build as X


def test_writer_checks_serialized_text_and_final_scan_does_not_reread(tmp_path, monkeypatch):
    out = tmp_path / 'out'
    (out / 'events').mkdir(parents=True)
    cache = tmp_path / 'cache.json'
    check = X.BlocklistWrites(out, ['Zorbel Quillfeather'], cache, workers=2)
    with X.compact_writes(blocklist_check=check) as emit:
        for i in range(520):
            emit(out / 'events' / f'{i:03}.json', {'raw': {'notes': 'Zorbel Quillfeather' if i % 29 == 0 else 'river'}})
    expected = X.blocklist_hits(out, ['Zorbel Quillfeather'], workers=1)
    original = Path.read_text

    def no_event_reads(path, *args, **kwargs):
        assert path.parent != out / 'events'
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', no_event_reads)
    stats = {}
    assert X.blocklist_hits(out, ['Zorbel Quillfeather'], cache, observed=check, stats=stats) == expected
    assert stats['files'] == stats['in_memory'] == 520


def test_overwrite_observation_follows_final_file_and_json_escapes(tmp_path):
    out = tmp_path / 'out'
    (out / 'events').mkdir(parents=True)
    check = X.BlocklistWrites(out, ['Zorbel Quillfeather'])
    with X.compact_writes(blocklist_check=check) as emit:
        emit(out / 'events/a.json', {'text': 'Zorbel Quillfeather'})
        emit(out / 'events/a.json', {'text': 'river'})
        emit(out / 'events/b.json', {'text': 'Zorbel\nQuillfeather'})
    assert X.blocklist_hits(out, ['Zorbel Quillfeather'], observed=check) == []
    for p in (out / 'events').glob('*.json'):
        assert p.read_text() == json.dumps(json.loads(p.read_text()), ensure_ascii=False, separators=(',', ':'))
