"""The reaches per state (docs/national-approach.md §7 item 1): out/reaches/<st>.geojson and out/reaches/index.json
beside the unchanged national out/reaches.geojson and out/reach-paths.geojson (export/build.py), and their upload
(scripts/upload-current.sh: the index's explicit, checked and bounded list, the index last)."""
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from build import reaches as R
from export import build as X

ROOT = Path(__file__).resolve().parents[2]

# a Pennsylvania outfall whose modeled reach runs into New York (Chemung River, then the Susquehanna at the line),
# and a Pennsylvania reach that stays home
CROSS, HOME = "PA0026000-001", "PA0027000-002"


def _rec(key, permit, slug, coords):
    return {"key": key, "permit": permit, "outfall": key[-3:], "water_slug": slug, "state": "PA", "river": "R",
            "cut_reason": "cap_km", "length_km": 12.0,
            "segments": [{"comid": 1, "km_start": 0.0, "km_end": 6.0, "coords": coords[:2]},
                         {"comid": 2, "km_start": 6.0, "km_end": 12.0, "coords": coords[1:]}]}


CACHED = {CROSS: _rec(CROSS, "PA0026000", "chemung-river-pa", [[-76.8, 41.98], [-76.7, 41.999], [-76.6, 42.01]]),
          HOME: _rec(HOME, "PA0027000", "pine-creek-pa", [[-77.3, 41.4], [-77.2, 41.35], [-77.1, 41.3]])}
BAND = {"hours_typical": 3.0, "hours_fast": 2.0, "hours_leading_edge": 2.7, "reached_fast": True,
        "reached_typical": True}
ST = {"waters": {"chemung-river-pa": {"state": "PA", "reaches": [CROSS]},
                 "susquehanna-river-ny": {"state": "NY", "reaches": [CROSS]},
                 "pine-creek-pa": {"state": "PA", "reaches": [HOME]}},
      "reaches": {CROSS: {"water_slug": "chemung-river-pa", "status": "red", "active": True},
                  HOME: {"water_slug": "pine-creek-pa", "status": "grey"}},
      "reach_events_active": [{"event_id": "pa-test:1", "reach": CROSS, "status": "red", "rule": "ongoing",
                               "short": "CSO ongoing", "hours_since_start": 4.0, "segments": [BAND, BAND]}]}
BY_EVENT = {"pa-test:1": {"started_at": "2026-11-04T10:00:00Z"}}
LIVE = {"PA", "NY", "MA"}


@pytest.fixture
def feats(monkeypatch):
    monkeypatch.setattr(R, "cap_km", lambda rules=None: 40.0)
    return X.reach_features(ST, BY_EVENT, CACHED)


def test_a_reach_crossing_a_state_line_is_in_both_state_files_with_its_states(feats):
    reach_feats, path_feats = feats
    by_state, homeless = X.reaches_by_state(reach_feats, path_feats, ST, CACHED, LIVE)
    assert homeless == [] and sorted(by_state) == ["MA", "NY", "PA"]
    pa = by_state["PA"]
    assert [(f["properties"]["feature"], f["properties"]["reach"]) for f in pa] == [
        ("path", CROSS), ("path", HOME), ("segment", CROSS), ("segment", CROSS), ("stop", CROSS)]
    ny = by_state["NY"]
    assert [(f["properties"]["feature"], f["properties"]["reach"]) for f in ny] == [
        ("path", CROSS), ("segment", CROSS), ("segment", CROSS), ("stop", CROSS)]
    for f in ny:            # the outfall's state first, then the downstream water's
        assert f["properties"]["states"] == ["PA", "NY"]
    assert [f["properties"]["states"] for f in pa if f["properties"]["reach"] == HOME] == [["PA"]]
    assert by_state["MA"] == []          # a live state no reach touches still gets its (empty) file


def test_the_national_features_are_not_changed_by_the_split(feats):
    reach_feats, path_feats = feats
    before = copy.deepcopy((reach_feats, path_feats))
    X.reaches_by_state(reach_feats, path_feats, ST, CACHED, LIVE)
    assert (reach_feats, path_feats) == before
    assert all("states" not in f["properties"] for f in reach_feats + path_feats)
    assert all("feature" not in f["properties"] for f in path_feats)


def test_a_state_comes_from_the_permit_or_a_live_slug_suffix_when_the_record_does_not_say():
    state_of = X.water_state_of({"waters": {"a-river-pa": {"state": "PA"}}}, {"PA", "NY"})
    assert X.reach_states({"permit": "PA0001"}, ["a-river-pa", "b-creek-ny", "c-lake-oh", None], state_of) == ["PA", "NY"]
    assert X.reach_states({"state": "ny", "permit": "PA0001"}, [], state_of) == ["NY"]
    assert X.reach_states({"permit": "0012345"}, ["a-river-pa"], state_of) == ["PA"]


def test_a_reach_in_no_live_state_is_counted_not_dropped_silently(feats):
    reach_feats, path_feats = feats
    by_state, homeless = X.reaches_by_state(reach_feats, path_feats, ST, CACHED, {"MA"})
    assert by_state == {"MA": []} and homeless == [CROSS, HOME]


def test_state_files_and_index_are_written_and_a_stale_state_file_removed(feats, tmp_path):
    reach_feats, path_feats = feats
    out = tmp_path / "out"
    X.write_compact(out / "reaches" / "vt.geojson", {"type": "FeatureCollection", "features": []})   # an old state
    by_state, homeless = X.reaches_by_state(reach_feats, path_feats, ST, CACHED, LIVE)
    idx = X.write_reach_state_files(by_state, out, built="2026-11-04T12:00:00Z", without_state=homeless)
    assert sorted(p.name for p in (out / "reaches").iterdir()) == ["index.json", "ma.geojson", "ny.geojson", "pa.geojson"]
    assert json.loads((out / "reaches" / "index.json").read_text()) == idx
    rows = {e["state"]: e for e in idx["files"]}
    assert rows["NY"] == {"state": "NY", "file": "reaches/ny.geojson", "features": 4, "paths": 1, "segments": 2,
                          "stops": 1, "bytes": (out / "reaches" / "ny.geojson").stat().st_size,
                          "built": "2026-11-04T12:00:00Z"}
    assert rows["PA"]["features"] == 5 and rows["MA"]["features"] == 0 and idx["without_state"] == 0
    fc = json.loads((out / "reaches" / "ny.geojson").read_text())
    assert fc["type"] == "FeatureCollection" and fc["state"] == "NY" and len(fc["features"]) == 4
    with pytest.raises(ValueError):
        X.write_reach_state_files({"../x": []}, out)


def test_the_blocklist_check_reads_the_state_files(tmp_path):
    out = tmp_path / "out"
    X.write_compact(out / "reaches" / "pa.geojson", {"features": [{"properties": {"label": "at the home of Pat Doe"}}]})
    assert X.blocklist_hits(out, ["Pat Doe"]) == ["reaches/pa.geojson"]


def test_the_export_writes_the_state_files_beside_the_unchanged_national_ones():
    import inspect
    src = inspect.getsource(X.export)
    assert 'write_compact(OUT_DIR / "reaches.geojson", {"type": "FeatureCollection", "features": reach_feats})' in src
    assert 'write_compact(OUT_DIR / "reach-paths.geojson", {"type": "FeatureCollection", "features": path_feats})' in src
    assert src.index('OUT_DIR / "reach-paths.geojson"') < src.index("write_reach_state_files(") \
        < src.index("enforce_blocklist(OUT_DIR)")


# ---------------------------------------------------------------- scripts/upload-current.sh

NATIONAL = ["outfalls.json", "meta.json", "waters.json", "active.json", "rules.json", "overlays.geojson", "reaches.geojson",
            "advisory-points.geojson", "launches.geojson", "history.json", "events-index.json", "sources.json",
            "dischargers.json"]       # the thirteen files the Worker and the site read, in the script's order


def _project(tmp_path, index, states=("pa", "ny"), fail=(), flaky=(), missing=()):
    """Run scripts/upload-current.sh under sh (dash on the runners) in a scratch project with a stub wrangler that logs
    every put (fail: keys that never put; flaky: keys that fail once, then put). Returns (the process, the keys put)."""
    root = tmp_path / "proj"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "upload-current.sh", root / "scripts" / "upload-current.sh")
    (root / "scripts" / "export-outfalls.py").write_text("")
    (root / "out" / "reaches").mkdir(parents=True)
    for f in NATIONAL:
        if f not in missing:
            (root / "out" / f).write_text("{}")
    for s in states:
        (root / "out" / "reaches" / f"{s}.geojson").write_text("{}")
    if index is not None:
        (root / "out" / "reaches" / "index.json").write_text(index if isinstance(index, str) else json.dumps(index))
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "put.log"
    fails = " ".join(f"dirtywaterwatch-data/current/{f}" for f in fail)
    flakes = " ".join(f"dirtywaterwatch-data/current/{f}" for f in flaky)
    mark = tmp_path / "flaked"
    (bin_ / "wrangler").write_text(f'#!/bin/sh\nfor k in {fails or "none"}; do [ "$4" = "$k" ] && exit 1; done\n'
                                   f'for k in {flakes or "none"}; do [ "$4" = "$k" ] && [ ! -e "{mark}" ] && '
                                   f'{{ : > "{mark}"; exit 1; }}; done\n'
                                   f'echo "$4 $6" >> "{log}"\n')
    (bin_ / "sleep").write_text(f'#!/bin/sh\necho "slept $1" >> "{log}"\n')
    for b in ("wrangler", "sleep"):
        os.chmod(bin_ / b, 0o755)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}
    r = subprocess.run(["sh", str(root / "scripts" / "upload-current.sh")], env=env, capture_output=True, text=True,
                       timeout=60)
    lines = log.read_text().splitlines() if log.exists() else []
    puts = [ln.split()[0].removeprefix("dirtywaterwatch-data/current/") for ln in lines if not ln.startswith("slept ")]
    r.sleeps = [int(ln.split()[1]) for ln in lines if ln.startswith("slept ")]
    return r, puts


def _index(*files):
    return {"files": [{"state": f[8:10].upper(), "file": f} for f in files]}


def test_upload_puts_the_national_files_as_before_then_the_listed_state_files_then_the_index_last(tmp_path):
    r, puts = _project(tmp_path, _index("reaches/pa.geojson", "reaches/ny.geojson"))
    assert r.returncode == 0, r.stderr
    assert puts == NATIONAL + ["reaches/pa.geojson", "reaches/ny.geojson", "reaches/index.json"]
    assert [ln for ln in r.stdout.splitlines() if not ln.startswith("uploaded current/")] == []


def test_upload_without_an_index_puts_the_national_files_only_and_passes(tmp_path):
    r, puts = _project(tmp_path, None, states=())
    assert r.returncode == 0 and puts == NATIONAL


@pytest.mark.parametrize("index", [
    _index("reaches/pa.geojson", "../secrets.json"),
    _index("reaches/pa.geojson", "reaches/pa.geojson"),
    _index("reaches/pa.geojson", "reaches/PA.geojson"),
    _index(*[f"reaches/{chr(97 + i // 26)}{chr(97 + i % 26)}.geojson" for i in range(65)]),
    {"files": [{"file": "reaches/pa.geojson reaches/ny.geojson"}]},
    {"files": "reaches/pa.geojson"},
    "{not json",
])
def test_upload_refuses_an_index_outside_the_bounds_puts_no_state_file_and_fails(tmp_path, index):
    r, puts = _project(tmp_path, index)
    assert puts == NATIONAL and "the index did not pass the check" in r.stdout
    assert r.returncode == 1 and "not uploaded: reaches/index.json" in r.stdout


def test_upload_keeps_the_old_index_when_a_state_file_fails_or_is_missing_and_exits_1(tmp_path):
    r, puts = _project(tmp_path, _index("reaches/pa.geojson", "reaches/ny.geojson"), fail=("reaches/pa.geojson",))
    assert puts == NATIONAL + ["reaches/ny.geojson"]
    assert "not uploaded: reaches/pa.geojson" in r.stdout and "index.json left as it was" in r.stdout
    assert r.returncode == 1 and r.stdout.rstrip().endswith("upload-current: not uploaded: reaches/pa.geojson")
    r, puts = _project(tmp_path / "b", _index("reaches/pa.geojson", "reaches/ny.geojson"), states=("pa",))
    assert "reaches/index.json" not in puts and "not in out/: reaches/ny.geojson" in r.stdout and r.returncode == 1


def test_upload_exits_1_after_a_failed_or_missing_national_file_but_still_puts_the_rest(tmp_path):
    # scripts/refresh-data.sh reads the exit code: 1 means the live files in R2 were not all replaced
    r, puts = _project(tmp_path, _index("reaches/pa.geojson"), states=("pa",), fail=("waters.json",))
    assert puts == [f for f in NATIONAL if f != "waters.json"] + ["reaches/pa.geojson", "reaches/index.json"]
    assert r.returncode == 1 and "upload failed: current/waters.json" in r.stdout
    assert r.stdout.rstrip().endswith("upload-current: not uploaded: waters.json")
    assert r.sleeps == [2, 4, 8]                        # the three retries' backoff
    r, puts = _project(tmp_path / "b", _index("reaches/pa.geojson"), states=("pa",), missing=("history.json",))
    assert puts == [f for f in NATIONAL if f != "history.json"] + ["reaches/pa.geojson", "reaches/index.json"]
    assert r.returncode == 1 and "not in out/: history.json" in r.stdout


def test_upload_retries_a_transient_failure_under_a_posix_shell(tmp_path):
    # the old backoff, $((2 ** n)), is not POSIX: dash (sh on the runners) stopped the whole upload at the first retry
    r, puts = _project(tmp_path, _index("reaches/pa.geojson"), states=("pa",), flaky=("meta.json",))
    assert r.returncode == 0 and "arithmetic" not in r.stderr and r.sleeps == [2]
    assert puts == NATIONAL + ["reaches/pa.geojson", "reaches/index.json"]
