"""The export's hook-up of the state assessments (export/build.py, the shared-file patch of the ATTAINS branch):
public_assessments (the cache kept to the tracked waters, checked whole, its free text through the records' redactor,
out/assessments.json), the water page's `assessment` (export/assessments.water_block), assessment_download
(out/csv/assessments.csv) and meta.json's counts, run on a status the status build made: with a valid cache, a malformed
one and none, and never changing a status, colour or reach. The module itself is tested in tests/test_attains.py. Run
from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import copy
import csv
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import redact as R  # noqa: E402
from build import status as S  # noqa: E402
from export import assessments as XA  # noqa: E402
from export import build as X  # noqa: E402
from tests.test_status import TEST_RULES, ev, iso, tmp_events, world  # noqa: E402

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
AT = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
MAIL = "pat" + "@" + "example.org"           # made up, for the privacy fixture
NAME = "Zebulon Quillfeather"                # a made-up name on the redactor's blocklist
TRACKED = [{"slug": "test-river-ma", "name": "Test River"}, {"slug": "other-pond-ma", "name": "Other Pond"}]


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


_BUILT: list[dict] = []


def status() -> dict:
    """A status from the status build (built once, a copy each time): Test River red from an ongoing overflow, with its
    reason; Other Pond with an overflow that ended weeks ago."""
    if not _BUILT:
        e = ev("r", status="ongoing", started_at=iso(NOW - timedelta(hours=2)))
        old = ev("p", water_slugs=["other-pond-ma"], status="ended", started_at=iso(NOW - timedelta(days=40)),
                 ended_at=iso(NOW - timedelta(days=39)))
        st, _ = S.build(now=NOW, write=False, **world(tmp_events([e, old])))
        assert st["waters"]["test-river-ma"]["status"] == "red" and "other-pond-ma" in st["waters"]
        _BUILT.append(st)
    return copy.deepcopy(_BUILT[0])


def redactor(tmp_path) -> R.Redactor:
    return R.Redactor(R.build_lexicon([], tmp_path, allow=[], block=[NAME]), set())


def unit(au="MA001", listed=True, sewage=False, **kw) -> dict:
    return {"org_id": "MA_DEP", "org_name": "Massachusetts", "state": "MA", "au_id": au, "au_name": "Test River",
            "cycle": 2024, "cycle_status": "EPA Final Action", "water_type": "RIVER", "size": 3.2, "size_units": "Miles",
            "location": f"Test River from the dam to the mouth; questions to {MAIL}, attention {NAME}",
            "recreation": {"support": "Not Supporting", "uses": ["Primary Contact Recreation"],
                           "monitoring_start": "2021-06-01", "monitoring_end": "2021-09-30",
                           "assessment_date": "2023-01-15"},
            "pathogens": [{"parameter": "ESCHERICHIA COLI (E. COLI)", "status": "Cause" if listed else "Meeting Criteria",
                           "ir_category": "5", "first_listed": 2010}],
            "sewage_sources": [{"name": "COMBINED SEWER OVERFLOWS", "kind": "cso", "confirmed": True,
                                "cause": "ESCHERICHIA COLI (E. COLI)", "cycle": 2024}] if sewage else [],
            "has_tmdl": False, "sources_cycle": 2024 if sewage else None,
            "report_url": f"https://mywaterway.epa.gov/waterbody-report/MA_DEP/{au}/2024",
            "latest_url": f"https://mywaterway.epa.gov/waterbody-report/MA_DEP/{au}",
            "from": "national files", "match": {"method": "geometry+name", "distance_m": 12, "geometry": "line"}, **kw}


def write_cache(tmp_path, waters, built=AT, **extra) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "attains-waters.json"
    p.write_text(json.dumps({"built": built, "source": {"name": "EPA ATTAINS", "files": [], "layers": {},
                                                        "fetched_at": built, "latest_cycles": {"assessments": {}}},
                             "waters": waters, **extra}))
    return p


def run_hook(tmp_path, cache_path, st=None):
    st = st or status()
    out = tmp_path / "out"
    a = X.public_assessments(st, redactor(tmp_path), out_dir=out, path=cache_path, now=AT)
    rows = X.assessment_download(out, a, TRACKED)
    return st, a, out, rows


def test_with_a_valid_cache_the_water_page_index_download_and_meta_carry_the_redacted_units(tmp_path):
    p = write_cache(tmp_path, {"test-river-ma": {"units": [unit(sewage=True), unit("MA002", listed=False)]},
                               "untracked-ma": {"units": [unit("MA009")]}},
                    audit={"test-river-ma": [{"au_id": "MA003", "au_name": f"Test River {MAIL}"}]})
    st, a, out, rows = run_hook(tmp_path, p)
    block = X.assess_mod.water_block(a, "test-river-ma")
    assert [u["au_id"] for u in block["units"]] == ["MA001", "MA002"] and block["source"]["name"] == "EPA ATTAINS"
    assert block["units"][0]["location"] == ("Test River from the dam to the mouth; questions to [email removed], "
                                             "attention [name removed]")
    assert X.assess_mod.water_block(a, "other-pond-ma") is None and "untracked-ma" not in a["waters"]   # no units
    index = json.loads((out / "assessments.json").read_text())
    assert set(index["waters"]) == {"test-river-ma"} and index["waters"]["test-river-ma"]["pathogen_listed"] == 1
    assert rows == 2
    text = (out / "csv" / "assessments.csv").read_text()
    published = json.dumps(block) + (out / "assessments.json").read_text() + text
    assert MAIL not in published and NAME not in published and "audit" not in published
    assert next(csv.DictReader(io.StringIO(text)))["location"].endswith("[email removed], attention [name removed]")
    assert XA.meta(a) == {"built": AT, "waters_with_units": 1, "waters_pathogen_listed": 1, "waters_sewage_named": 1,
                          "waters_capped": 0, "unavailable": None}


MALFORMED = {
    "a null unit": {"units": [None]},
    "units not a list": {"units": {"au_id": "MA001"}},
    "pathogens not a list": {"units": [unit(pathogens="Cause")]},
    "a null pathogen": {"units": [unit(pathogens=[None])]},
    "a pathogen year as text": {"units": [unit(pathogens=[{"status": "Cause", "first_listed": "2010"}])]},
    "match not an object": {"units": [unit(match=[])]},
    "a match distance as text": {"units": [unit(match={"method": "geometry+name", "distance_m": "12"})]},
    "recreation not an object": {"units": [unit(recreation="Not Supporting")]},
    "recreation uses not text": {"units": [unit(recreation={"support": "Not Supporting", "uses": [1]})]},
    "a sewage source not an object": {"units": [unit(sewage_sources=["CSO"])]},
    "a cycle as text": {"units": [unit(cycle="2024")]},
    "a size not finite": {"units": [unit(size=float("inf"))]},
    "a report address elsewhere": {"units": [unit(report_url="javascript:alert(1)")]},
    "no unit id": {"units": [unit(au_id="")]},
}


@pytest.mark.parametrize("bad", list(MALFORMED), ids=list(MALFORMED))
def test_a_malformed_cache_leaves_every_assessment_null_says_why_and_never_raises(tmp_path, capsys, bad):
    p = write_cache(tmp_path, {"test-river-ma": MALFORMED[bad], "other-pond-ma": {"units": [unit("MA005")]}})
    st, a, out, rows = run_hook(tmp_path, p)
    assert X.assess_mod.water_block(a, "test-river-ma") is None and X.assess_mod.water_block(a, "other-pond-ma") is None
    m = XA.meta(a)
    assert m["waters_with_units"] == 0 and m["unavailable"].startswith("the assessment file does not have the expected form")
    assert json.loads((out / "assessments.json").read_text())["waters"] == {}
    assert rows == 0 and not (out / "csv" / "assessments.csv").exists()
    assert "no state assessments on the water pages" in capsys.readouterr().out


@pytest.mark.parametrize("cache", ['{"waters": []}', '["not", "an", "object"]', '{"built": "' + AT + '", "waters": {},'
                                   ' "source": "EPA"}', "{not json", '{"built": "not a time", "waters": {}}'])
def test_a_cache_of_another_shape_or_unreadable_shows_nothing(tmp_path, cache):
    p = tmp_path / "attains-waters.json"
    p.write_text(cache)
    st, a, out, rows = run_hook(tmp_path, p)
    assert a["waters"] == {} and a["unavailable"] and rows == 0


def test_with_no_cache_the_export_runs_and_says_so(tmp_path, capsys):
    st, a, out, rows = run_hook(tmp_path, tmp_path / "none.json")
    assert X.assess_mod.water_block(a, "test-river-ma") is None and rows == 0
    assert XA.meta(a)["unavailable"] == "no assessment file for this export"
    assert json.loads((out / "assessments.json").read_text()) == {"built": None, "source": None, "waters": {}}
    assert "no state assessments on the water pages (no assessment file for this export)" in capsys.readouterr().out


def test_the_hook_changes_no_status_colour_or_reach(tmp_path):
    st = status()
    before = copy.deepcopy(st)
    p = write_cache(tmp_path, {"test-river-ma": {"units": [unit(sewage=True)]},
                               "other-pond-ma": {"units": [unit("MA005", listed=False)]}})
    _, a, out, rows = run_hook(tmp_path, p, st=st)
    assert st == before                                             # statuses, reasons, reaches, placements: as built
    assert st["waters"]["test-river-ma"]["status"] == "red"
    assert st["waters"]["other-pond-ma"]["status"] == before["waters"]["other-pond-ma"]["status"] != "red"
    block = X.assess_mod.water_block(a, "other-pond-ma")
    assert block["summary"]["pathogen_listed"] == 0
    keys = set(block) | {k for u in block["units"] for k in u}
    assert not keys & {"status", "colour", "color", "reach", "reasons", "until", "rule"}
    # with no cache, a malformed one or a valid one, the status is the same
    for cache in (tmp_path / "none.json", write_cache(tmp_path / "m", {"test-river-ma": {"units": [None]}}), p):
        st2 = status()
        X.public_assessments(st2, redactor(tmp_path), out_dir=tmp_path / "out2", path=cache, now=AT)
        assert st2 == before


def test_the_export_lists_the_assessment_files_and_scans_them():
    assert "assessments.json" in X.PUBLIC_PAYLOADS
    assert "assessments.json" in X.__doc__ and "`assessment` in waters/<slug>.json" in X.__doc__
    assert "assessments.csv" in X.__doc__
