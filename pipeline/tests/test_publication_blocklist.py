"""Publication coverage follows the archive and live uploader, with invented names only."""
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path

from export import build as X

ROOT = Path(__file__).resolve().parents[2]
NAME = "Zorbel Quillfeather"


def test_every_published_file_is_checked_including_future_outputs(tmp_path):
    # Derive the live manifest from the uploader, not the scanner's allowlist.
    script = (ROOT / "scripts/upload-current.sh").read_text()
    live = re.search(r"^for f in (.+); do$", script, re.M).group(1).split()
    # The site receives the entire out/ archive (CSV downloads included). Exercise
    # new root/nested outputs and extensions so a new publisher needs no scan-list edit.
    files = live + ["events.json", "waters/example.json", "events/example.json",
                    "reaches/ma.geojson", "reaches/index.json", "conditions.json",
                    "rain-levels-sso.json", "csv/water/example.csv", "future.json",
                    "future/nested/new-payload.txt"]
    out = tmp_path / "out"
    for rel in files:
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"attribution": NAME}))
    workflow = (ROOT / ".github/workflows/refresh.yml").read_text()
    archive_command = next(line.strip() for line in workflow.splitlines()
                           if line.strip().startswith("tar ") and "out.tar.gz" in line)
    subprocess.run(archive_command.split(), cwd=tmp_path, check=True, capture_output=True,
                   env={**os.environ, "COPYFILE_DISABLE": "1"})  # no macOS resource forks on the Linux publisher
    with tarfile.open(tmp_path / "out.tar.gz") as archive:
        published = {str(Path(member.name).relative_to("out"))
                     for member in archive if member.isfile()}
    assert set(live) <= published
    stats = {}
    assert set(X.blocklist_hits(out, [NAME], stats=stats)) == published
    assert stats["files"] == len(published)


def test_newly_covered_files_warn_with_filenames_and_keep_upload_enabled(tmp_path, monkeypatch, capsys):
    for attr in ("BLOCKED_MARK", "HITS_MARK"):
        monkeypatch.setattr(X, attr, tmp_path / f"{attr}.json")
    out = tmp_path / "out"
    out.mkdir()
    for rel in ("sources.json", "events-index.json", "meta.json"):
        (out / rel).write_text(json.dumps({"attribution": NAME}))
    X.BLOCKED_MARK.write_text("{}")
    assert X.enforce_blocklist(out, [NAME]) == 3
    output = capsys.readouterr().out
    assert "::warning::" in output and "uploaded anyway" in output and NAME not in output
    assert not X.BLOCKED_MARK.exists()
    assert set(json.loads(X.HITS_MARK.read_text())["files"]) == {"sources.json", "events-index.json", "meta.json"}
