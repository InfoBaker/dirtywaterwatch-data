"""The Census state outlines are found without the sibling project (ingest.waters_extra.states_zip): data/raw/census/
first, then openboatlaunch's copy, else downloaded once from the Census Bureau. No network: the download is faked.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import waters_extra as WX  # noqa: E402


def tiny_zip(path: Path, tag: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("tag.txt", tag)
    return path


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]


def outlines_zip(**extra) -> bytes:
    """A zip shaped like the Census file: the .shp and .dbf States reads (contents faked), plus extra members."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for m in WX.STATES_ZIP_MEMBERS:
            z.writestr(m, b"x")
        for k, v in extra.items():
            z.writestr(k, v)
    return buf.getvalue()


class FakeSession:
    def __init__(self, content: bytes):
        self.content, self.calls = content, []

    def get(self, url, **kw):
        self.calls.append(url)
        return FakeResponse(self.content)


def test_the_census_folder_comes_before_the_sibling_copy(tmp_path):
    census = tiny_zip(tmp_path / "raw" / "census" / WX.STATES_ZIP_NAME, "census")
    sibling = tiny_zip(tmp_path / "openboatlaunch" / WX.STATES_ZIP_NAME, "sibling")
    s = FakeSession(b"")
    assert WX.states_zip([census, sibling], session=s) == census
    assert s.calls == []


def test_the_sibling_copy_when_the_census_folder_has_none(tmp_path):
    sibling = tiny_zip(tmp_path / "openboatlaunch" / WX.STATES_ZIP_NAME, "sibling")
    s = FakeSession(b"")
    assert WX.states_zip([tmp_path / "raw" / "census" / WX.STATES_ZIP_NAME, sibling], session=s) == sibling
    assert s.calls == []


def test_downloaded_once_into_the_census_folder_when_neither_has_it(tmp_path):
    dest = tmp_path / "raw" / "census" / WX.STATES_ZIP_NAME
    s = FakeSession(outlines_zip(**{"tag.txt": "downloaded"}))
    got = WX.states_zip([dest, tmp_path / "nowhere.zip"], dest=dest, session=s)
    assert got == dest and zipfile.ZipFile(got).read("tag.txt") == b"downloaded"
    assert s.calls == [WX.STATES_ZIP_URL] and "census.gov" in WX.STATES_ZIP_URL
    assert WX.states_zip([dest], dest=dest, session=s) == dest and len(s.calls) == 1     # once


def test_a_download_that_is_not_a_zip_is_not_kept(tmp_path):
    dest = tmp_path / "raw" / "census" / WX.STATES_ZIP_NAME
    with pytest.raises(ValueError):
        WX.states_zip([dest], dest=dest, session=FakeSession(b"<html>error</html>"))
    assert not dest.exists()


def test_no_download_when_asked_not_to(tmp_path):
    with pytest.raises(FileNotFoundError):
        WX.states_zip([tmp_path / "a.zip"], download=False)


def test_a_zip_without_the_shapefile_is_not_kept(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.html", "a mirror's error page, zipped")
    dest = tmp_path / "raw" / "census" / WX.STATES_ZIP_NAME
    with pytest.raises(ValueError, match="lacks"):
        WX.states_zip([dest], dest=dest, session=FakeSession(buf.getvalue()))
    assert not dest.exists() and not list(dest.parent.glob("*.tmp"))


def test_an_oversized_answer_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(WX, "STATES_ZIP_MAX_BYTES", 1000)
    dest = tmp_path / "raw" / "census" / WX.STATES_ZIP_NAME
    with pytest.raises(ValueError, match="more than"):
        WX.states_zip([dest], dest=dest, session=FakeSession(outlines_zip(**{"big.bin": b"0" * 5000})))
    assert not dest.exists() and not list(dest.parent.glob("*.tmp"))
