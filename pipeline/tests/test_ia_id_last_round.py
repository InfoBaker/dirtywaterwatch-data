"""Iowa and Idaho: the verification pass of 2026-11-15 (Astra), last fix round. Every name, street, number and water
here is invented."""
import json

import pytest

from ingest import id_deq_cyanohab as H
from tests.test_ia_id_review import PTS, ROWS, T0, T1, T2, layer_doc, run_main

NAMES = [r[1] for r in ROWS]


# ------------------------------------------------------------------ Idaho: a partial layer read lifts nothing

def _truncated(names):
    doc = layer_doc(names)
    doc["exceededTransferLimit"] = True
    return doc


def _no_geometry(names):
    doc = layer_doc(names)
    for f in doc["features"]:
        if f["attributes"]["LocationDiscription"] != "Example Lake":
            f["geometry"] = None
    return doc


@pytest.mark.parametrize("bad_layer", [_truncated, _no_geometry])
def test_last_idaho_a_partial_layer_with_a_shortened_table_lifts_nothing(monkeypatch, tmp_path, bad_layer):
    code, out, recs = run_main(monkeypatch, tmp_path, ROWS, NAMES, T0)
    assert code == 0 and out.get("ok", True) is not False
    # a shortened table and a layer that is cut off (only the first water) or lost its points
    layer = bad_layer(["Example Lake"] if bad_layer is _truncated else NAMES)
    monkeypatch.setattr(H, "fetch_layer", lambda: layer)
    monkeypatch.setattr(H, "fetch_page", lambda: __import__("tests.test_ia_id_review", fromlist=["html"]).html(ROWS[:1]))
    out2 = {}

    def we(sid, recs, **kw):
        out2.update(recs=recs, **kw)
        return tmp_path / "events.json"
    monkeypatch.setattr(H, "write_events", we)
    assert H.main(["--at", T1]) == 0
    recs = {r["source_record_id"].split(":")[0]: r for r in out2["recs"]}
    assert not any(r["status"] in ("advisory_lifted", "ended") for r in out2["recs"]), \
        [(r["source_record_id"], r["status"]) for r in out2["recs"]]
    assert recs["sample-reservoir"]["status"] == "advisory_active" and out2["ok"] is False
    # the points of the last good read are kept: nothing moves, nothing is lost
    assert (recs["sample-reservoir"]["lat"], recs["sample-reservoir"]["lon"]) == (43.6, -116.2)


def test_last_idaho_parse_layer_keeps_a_water_without_a_point_and_flags_a_cut_off_answer():
    lay = H.parse_layer(_no_geometry(NAMES))
    assert "sample reservoir" in lay and lay["sample reservoir"]["lat"] is None
    assert H.layer_problem(_truncated(NAMES))
    assert H.layer_problem(layer_doc(NAMES)) is None


# ------------------------------------------------------------------ Idaho: no sample date -> no invented calendar start

@pytest.mark.parametrize("at", ["2026-07-15T06:30:00Z", "2026-07-15T05:30:00Z", "2026-07-14T23:59:00Z"])
@pytest.mark.parametrize("county", ["Kootenai", "Ada"])
def test_last_idaho_a_watch_without_a_collection_date_starts_at_the_read_marked_poll(monkeypatch, tmp_path, at, county):
    rows = [("Watch", "Specimen Pond", county, "", "", "Always use caution.")]
    _, _, recs = run_main(monkeypatch, tmp_path, rows, ["Specimen Pond"], at)
    w = recs["specimen-pond"]
    assert w["started_at"] == at and w["time_precision"] == "poll" and w["sampled_at"] is None
    assert "before" in w["raw"]["start_basis"]


def test_last_idaho_a_watch_with_a_collection_date_keeps_its_day():
    rows = [dict(zip(("level", "water", "county", "data_type", "collection_date", "info"), ROWS[2]))]
    w = H.records(H.update({}, rows, T0, None))[0]
    assert w["started_at"] == "2026-11-10" and w["time_precision"] == "day"


# ------------------------------------------------------------------ Idaho: DHW's names never reach a save unscrubbed

def test_last_idaho_dhw_names_and_their_keys_are_scrubbed_before_every_save(monkeypatch, tmp_path):
    bad = "Example Lake - Contact Example Person 208-555-0142"
    PTS[bad] = (47.5, -116.7, "Health Advisory")
    try:
        saves = []
        rows = [("Health Advisory", bad, "Kootenai", "Laboratory Results", "07/14/2026", "Toxins have exceeded.")]
        run_main(monkeypatch, tmp_path, rows, [bad], T0, saves)
        # carried state from before the fix: a raw key in points and in the snapshot
        st = json.loads((tmp_path / "state.json").read_text())
        st["points"]["example lake contact example person 208 555 0142"] = {"name": bad, "lat": 1, "lon": 1}
        st["last_snapshot"]["points"] = dict(st["points"])
        (tmp_path / "state.json").write_text(json.dumps(st))
        run_main(monkeypatch, tmp_path, rows, [bad], T1, saves)
    finally:
        PTS.pop(bad)
    assert len(saves) >= 4
    for s in saves:
        for b in ("Example Person", "example person", "555-0142", "555 0142"):
            assert b not in s, (b, s[:300])
