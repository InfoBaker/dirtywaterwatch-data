"""Astra's review of feat/wi-dnr-feeds (2026-11-16): one test per finding, each asserting what a visitor would see (the
status intervals and markers), not only the record's flags. Fixtures: the runner's layer read (dnr_beach_layer.json,
run 43788371768) and the report page's table trimmed (dnr_beach_report_table.html, run 43788047052, 01:45Z)."""
import copy
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest import wi_dnr_beach_health as W

ROOT = Path(__file__).resolve().parents[2]
FIXD = Path(__file__).resolve().parent / "fixtures" / "wi"
RULES = json.loads((ROOT / "data" / "rules.json").read_text())
T0, T1, T2 = "2026-11-16T01:48:00Z", "2026-11-16T02:48:00Z", "2026-11-16T03:48:00Z"
GILE, KEGONSA = 474, 309


def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@pytest.fixture(autouse=True)
def small_floor(monkeypatch):
    monkeypatch.setattr(W, "MIN_BEACHES", 5)
    monkeypatch.setattr(W, "MIN_TABLE_ROWS", 5)


def layer():
    return json.loads((FIXD / "dnr_beach_layer.json").read_text())


def page():
    return (FIXD / "dnr_beach_report_table.html").read_text()


def feats(mutate=None, drop=()):
    d = layer()
    fs = d["layer"]["features"]
    for f in fs:
        if mutate and f["attributes"]["BEACH_SEQ_NO"] in mutate:
            f["attributes"].update(mutate[f["attributes"]["BEACH_SEQ_NO"]])
    fs[:] = [f for f in fs if f["attributes"]["BEACH_SEQ_NO"] not in drop]
    return W.safe_features(W.check_read(d["layer"], {"count": len(fs)}))


def recs_for(recs, seq):
    return [r for r in recs if r["raw"].get("beach_seq_no") == seq]


def ivs(rec, now):
    from build import status as S
    return S.event_intervals(rec, "WI", dt(now), None, RULES)


def colours_on(rec, now, at):
    t = dt(at)
    return {i["color"] for i in ivs(rec, now) if i["start"] <= t and (i["end"] is None or t < i["end"])}


class Resp:
    def __init__(self, js=None, text=""):
        self._js, self.text = js, text

    def raise_for_status(self):
        pass

    def json(self):
        if self._js is None:
            raise ValueError("not JSON")
        return self._js


def run_with(monkeypatch, tmp_path, js, cnt, at, html=None):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(W, "STATE_PATH", tmp_path / "state.json")
    saved = []
    monkeypatch.setattr(W, "save_raw", lambda name, body, ext: saved.append(body))

    def fake_get(url, **k):
        if "beachhealth" in url:
            if isinstance(html, Exception):
                raise html
            return Resp(text=page() if html is None else html)
        return Resp(cnt if "returnCountOnly" in url else js)
    monkeypatch.setattr(W.requests, "get", fake_get)
    rc = W.main(["--at", at])
    return rc, json.loads((tmp_path / "wi-dnr-beach-health.json").read_text()), saved


# ---------------------------------------------------------------- P1-1 every requested field's type

@pytest.mark.parametrize("field,value", [("SAMPLEDATE", {}), ("SAMPLEDATE", True), ("SAMPLEDATE", "2026-09-03"),
                                         ("OBJECTID", "12674"), ("OBJECTID", True), ("OBJECTID", None),
                                         ("OGW_BEACH_NAME_TEXT", 5), ("geometry", {"x": "west", "y": 42.9})])
def test_a_malformed_field_fails_the_read_and_the_held_closure_stays_red(monkeypatch, tmp_path, field, value):
    d = layer()
    rc, out, _ = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T0)
    held = out["records"]
    bad = copy.deepcopy(d)
    for f in bad["layer"]["features"]:
        if f["attributes"]["BEACH_SEQ_NO"] == KEGONSA:
            f["attributes"]["BEACH_ACTION"] = "End"            # would lift the closure if the read were accepted
            if field == "geometry":
                f["geometry"] = value
            else:
                f["attributes"][field] = value
    with pytest.raises(ValueError):
        W.check_read(bad["layer"], bad["count"])
    rc, out, saved = run_with(monkeypatch, tmp_path, bad["layer"], bad["count"], T1)
    assert rc == 1 and out["ok"] is False and out["records"] == held and saved == []   # nothing of the bad read saved
    k = recs_for(out["records"], KEGONSA)[0]
    assert k["status"] == "advisory_active" and colours_on(k, T1, T1) == {"red"}


# ---------------------------------------------------------------- P1-2 mixed and unknown reasons

def _points(recs, now):
    from build import status as S
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    (d / "wi-dnr-beach-health.json").write_text(json.dumps(
        {"source_id": "wi-dnr-beach-health", "ok": True, "last_ok_at": T0, "meta": {}, "records": copy.deepcopy(recs)}))
    st, _ = S.build(now=dt(now), write=False, events_dir=d, waters={}, outfalls=[], registry={}, reaches={},
                    flows=({}, {}), rules=RULES, placement_cache=None)
    return st


def test_a_reason_naming_bacteria_and_algae_keeps_both_signals_on_one_marker():
    recs, _, _ = W.records(feats({GILE: {"STATUS": "E. coli and Algae"}}), {}, T0)
    g = recs_for(recs, GILE)
    assert len(g) == 1
    assert g[0]["event_type"] == "beach_advisory" and g[0]["raw"]["_also_categories"] == ["bloom"]
    assert g[0]["raw"]["reason_categories"] == ["bacteria", "bloom"]
    st = _points(g, T0)
    pts = [p for p in st["advisory_points"] if p["event_id"] == g[0]["event_id"]]
    assert len(pts) == 1 and pts[0]["status"] == "red"
    assert pts[0]["category"] == "beach" and pts[0]["also_categories"] == ["bloom"]


def test_a_points_shape_is_unchanged_for_a_record_without_a_second_category():
    recs, _, _ = W.records(feats(), {}, T0)
    st = _points(recs, T0)
    assert st["advisory_points"] and all("also_categories" not in p for p in st["advisory_points"])


def test_an_unknown_reason_is_kept_as_unknown_with_the_departments_action():
    recs, _, _ = W.records(feats({GILE: {"STATUS": "Pollution event"}}), {}, T0)
    g = recs_for(recs, GILE)[0]
    assert g["event_type"] == "beach_advisory" and g["raw"]["reason_categories"] == ["unknown"]
    assert g["raw"]["reason"] == "Pollution event" and colours_on(g, T0, T0) == {"red"}
    recs, _, _ = W.records(feats({GILE: {"STATUS": None}}), {}, T0)
    assert recs_for(recs, GILE)[0]["raw"]["reason_categories"] == ["unknown"]


# ---------------------------------------------------------------- P1-3 a return with the old date

def test_a_beach_returning_with_a_date_before_the_last_observed_end_starts_at_its_return():
    end, back = "2026-11-17T15:00:00Z", "2026-11-20T15:00:00Z"
    _, st, _ = W.records(feats(), {}, T0)
    _, st, _ = W.records(feats({GILE: {"BEACH_ACTION": "End"}}), st, end)
    recs, st, _ = W.records(feats(), st, back)
    rows = recs_for(recs, GILE)
    old = [r for r in rows if r["status"] == "advisory_lifted"][0]
    new = [r for r in rows if r["status"] == "advisory_active"][0]
    assert new["started_at"] == back and new["time_precision"] == "poll"
    assert new["raw"]["issued_text"] == "17-SEP-26 -" and "returned" in new["raw"]["start_basis"]
    # the days between the observed end and the return are coloured by neither record
    for at in ("2026-11-18T12:00:00Z", "2026-11-19T12:00:00Z"):
        assert "red" not in colours_on(old, back, at) and "red" not in colours_on(new, back, at)
    assert colours_on(new, back, back) == {"red"}


# ---------------------------------------------------------------- P1-4 a recognised signal before a label

def test_an_unfamiliar_action_never_masks_the_map_closure():
    recs, _, _ = W.records(feats({GILE: {"BEACH_ACTION": "Posted", "STATUS": "E. coli", "MAP_STATUS": "Closed"}}), {},
                           T0)
    g = recs_for(recs, GILE)[0]
    assert g["event_type"] == "beach_closure" and g["status"] == "advisory_active"
    assert g["raw"]["unrecognised_action"] == "Posted" and colours_on(g, T0, T0) == {"red"}


def test_the_strongest_recognised_signal_wins():
    recs, _, _ = W.records(feats({GILE: {"BEACH_ACTION": "Advisory", "STATUS": "E. coli", "MAP_STATUS": "Closed"}}),
                           {}, T0)
    assert recs_for(recs, GILE)[0]["event_type"] == "beach_closure"


# ---------------------------------------------------------------- P1-5 an unknown label is our caution, always

def test_an_unknown_label_is_our_caution_while_listed_and_never_red_after_it_ends():
    first, later, end = "2026-11-16T15:00:00Z", "2026-11-19T15:00:00Z", "2026-11-20T15:00:00Z"
    m = {GILE: {"BEACH_ACTION": "Posted", "STATUS": "E. coli", "ISSUED": "16-NOV-26 - "}}
    recs, st, _ = W.records(feats(m), {}, first)
    g = recs_for(recs, GILE)[0]
    assert g["status"] == "unknown" and colours_on(g, first, first) == {"yellow"}
    recs, st, _ = W.records(feats(m), st, later)
    g = recs_for(recs, GILE)[0]
    assert colours_on(g, later, later) == {"yellow"}                   # still listed: still our caution
    recs, st, _ = W.records(feats({GILE: {"BEACH_ACTION": "End"}}), st, end)
    g = recs_for(recs, GILE)[0]
    assert g["ended_at"] == end
    assert all(i["color"] != "red" for i in ivs(g, end))
    assert all(i["color"] != "red" for i in ivs(g, "2026-12-30T00:00:00Z"))


# ---------------------------------------------------------------- P1-6 no recent data does not cancel an advisory

def test_the_texts_say_missing_sample_data_does_not_cancel_a_listed_advisory():
    t = (ROOT / "research" / "wi" / "state-text.md").read_text()
    y = (ROOT / "data" / "sources" / "wi-dnr-beach-health.yaml").read_text()
    for s in (t, y.replace("\n#   ", " ")):
        assert "does not cancel an advisory or closure the Department lists" in s
    assert "without recent data has no report here" not in t
    recs, _, _ = W.records(feats(), {}, T0)                              # both carry "No Data Available"
    assert {r["raw"]["map_status"] for r in recs} == {"No Data Available"} and len(recs) == 2


# ---------------------------------------------------------------- P2 scrub every retained text; P3 the ingest list

def test_every_retained_text_is_scrubbed_before_any_save_and_in_the_advice(monkeypatch, tmp_path):
    d = layer()
    for f in d["layer"]["features"]:
        if f["attributes"]["BEACH_SEQ_NO"] == GILE:
            f["attributes"]["STATUS"] = "Algae; contact Pat Example at pat@example.invalid or 608-555-0142"
            f["attributes"]["ISSUED"] = "17-SEP-26 - "
    rc, out, saved = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T0)
    assert rc == 0
    blob = json.dumps(out) + saved[0] + (tmp_path / "state.json").read_text()
    for s in ("Pat Example", "pat@example.invalid", "555-0142"):
        assert s not in blob
    g = recs_for(out["records"], GILE)[0]
    assert "Algae" in g["advice_text"] and g["event_type"] == "hab_advisory"


def test_the_module_is_in_the_ingest_list_the_makefile_computes():
    from tests.test_ingest_list_guard import make_ingest_modules
    assert "wi_dnr_beach_health" in make_ingest_modules()


# ---------------------------------------------------------------- 8. the report table's beaches with no point

def test_the_table_parses_and_finds_the_beaches_the_layer_has_no_point_for():
    rows = W.parse_table(page())
    assert len(rows) == 9 and rows[0] == {"name": "Pennoyer Park Beach", "status": "End",
                                          "reason": "Closed for season", "issued": "29-MAY-26 -", "town": "Kenosha"}
    names = {r["name"] for r in W.table_only(rows, feats())}
    assert {"Americinn Beach", "Big Pete Beach", "Cana Island", "Pioneer Park"} <= names
    assert "Gile Flowage Beach" not in names


def _table_with(name, status, reason, issued):
    h = page()
    return re.sub(r"(Big Pete Beach</font></span></td>\s*<td><span[^>]*><font size=\"2\">)End(</font></span></td>\s*"
                  r"<td><span[^>]*><font size=\"2\">)Closed for season(</font></span></td>\s*<td><span[^>]*><font "
                  r"size=\"2\">)[^<]*", rf"\g<1>{status}\g<2>{reason}\g<3>{issued}", h, count=1) \
        if name == "Big Pete Beach" else h


def test_an_advisory_at_a_beach_with_no_point_is_a_record_without_a_point(monkeypatch, tmp_path):
    d = layer()
    html = _table_with("Big Pete Beach", "Advisory", "E. coli", "10-NOV-26 - ")
    assert "Advisory" in html.split("Big Pete Beach")[1][:400]
    rc, out, saved = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T0, html=html)
    assert rc == 0 and out["ok"] is True
    t = [r for r in out["records"] if r["raw"].get("read_from") == "report_table"]
    assert len(t) == 1
    r = t[0]
    assert r["outfall_name"] == "Big Pete Beach" and r["lat"] is None and r["lon"] is None
    assert r["event_type"] == "beach_advisory" and r["started_at"] == "2026-11-10" and r["time_precision"] == "day"
    assert r["raw"]["state"] == "WI" and "not known" in r["raw"]["point_basis"]
    assert "nearest_town" in r["raw"]
    st = _points([r], T0)
    assert r["event_id"] in st["placements"] and not [p for p in st["advisory_points"] if p["event_id"] == r["event_id"]]
    assert colours_on(r, T0, T0) == {"red"}
    # a later complete table read without it ends it at that read
    rc, out, _ = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T1)
    t = [x for x in out["records"] if x["raw"].get("read_from") == "report_table"][0]
    assert t["status"] == "advisory_lifted" and t["ended_at"] == T1 and t["raw"]["ended_at_precision"] == "poll"


@pytest.mark.parametrize("bad", [RuntimeError("timeout"), "<html>Service unavailable</html>",
                                 "<table id=\"tblSearchResult\"><tr><td>Beach</td></tr></table>"])
def test_a_failed_table_read_keeps_its_held_record_fails_health_and_leaves_the_layer_alone(monkeypatch, tmp_path, bad):
    d = layer()
    html = _table_with("Big Pete Beach", "Advisory", "E. coli", "10-NOV-26 - ")
    rc, out, _ = run_with(monkeypatch, tmp_path, d["layer"], d["count"], T0, html=html)
    held = [r for r in out["records"] if r["raw"].get("read_from") == "report_table"]
    assert len(held) == 1
    # the layer now shows Gile Flowage ended; the table cannot be read
    d2 = copy.deepcopy(d)
    for f in d2["layer"]["features"]:
        if f["attributes"]["BEACH_SEQ_NO"] == GILE:
            f["attributes"]["BEACH_ACTION"] = "End"
    rc, out, _ = run_with(monkeypatch, tmp_path, d2["layer"], d2["count"], T1, html=bad)
    assert rc == 1 and out["ok"] is False and "table" in out["error"]
    t = [r for r in out["records"] if r["raw"].get("read_from") == "report_table"]
    assert [x["status"] for x in t] == ["advisory_active"] and t[0]["source_record_id"] == held[0]["source_record_id"]
    assert colours_on(t[0], T1, T1) == {"red"}
    g = recs_for(out["records"], GILE)[0]
    assert g["status"] == "advisory_lifted" and g["ended_at"] == T1     # the layer's read stands
    # the next good read ends the table record only if the table no longer lists it
    rc, out, _ = run_with(monkeypatch, tmp_path, d2["layer"], d2["count"], T2, html=html)
    assert rc == 0 and out["ok"] is True
    assert [x["status"] for x in out["records"] if x["raw"].get("read_from") == "report_table"] == ["advisory_active"]
