"""Every published payload is covered by explicit removals; no legacy list is read."""
import json
from pathlib import Path
import re

from export.removals import RemovalList

ROOT = Path(__file__).resolve().parents[2]
TEXT = 'Fictional public phrase'


def requests():
    return RemovalList([{'id': 'req-001', 'added': '2026-11-25', 'kind': 'text', 'match': TEXT}])


def test_every_published_file_is_checked_including_future_outputs(tmp_path):
    script = (ROOT / 'scripts/upload-current.sh').read_text()
    live = re.search(r'^for f in (.+); do$', script, re.M).group(1).split()
    files = set(live + ['events.json', 'waters/example.json', 'events/example.json',
                       'reaches/ma.geojson', 'csv/water/example.csv', 'future/nested/new-payload.txt'])
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('note\n' + TEXT + '\n' if p.suffix == '.csv' else json.dumps({'note': TEXT}))
    policy = requests()
    policy.publish(tmp_path)
    assert policy.enforce(tmp_path) == 0
    assert all(TEXT not in p.read_text() for p in tmp_path.rglob('*') if p.is_file())


def test_new_payload_with_remaining_match_is_removed_and_warns_ids_only(tmp_path, capsys):
    for name in ('sources.json', 'meta.json', 'future.txt'):
        (tmp_path / name).write_text(json.dumps({'note': TEXT}))
    assert requests().enforce(tmp_path) == 3
    output = capsys.readouterr().out
    assert 'req-001' in output and 'future.txt' in output and TEXT not in output
    assert all(p.read_text().strip() in ("", "null") for p in tmp_path.iterdir())
