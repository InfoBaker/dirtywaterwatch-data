"""NC DWR sewer overflows: the this-year layer stopped being public on 2026-11-05 (ArcGIS 400 CONT_0001 "Item does
not exist or is inaccessible"). The ingester says so plainly, keeps the records it has, follows a layer the
Tracking Map's web map is pointed at, and never reads a layer whose fields it does not know (ingest/nc_dwr_sso.py
docstring, 2026-11-05). Fake ArcGIS answers, no network."""
from __future__ import annotations

import json
from pathlib import Path

import common
from ingest import nc_dwr_sso as S

FIX = Path(__file__).resolve().parent / "fixtures"
GONE = {"error": {"code": 400, "message": "Item does not exist or is inaccessible.", "messageCode": "CONT_0001",
                  "details": ["Item does not exist or is inaccessible."]}}
NEW = f"{S.ORG}/SSOs_and_Bypasses_2026/FeatureServer/0"


class Resp:
    def __init__(self, body):
        self.body, self.status_code = body, 200

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class Sess:
    """Answers by URL: the service list, the viewer web map, a layer's query and its metadata."""

    def __init__(self, routes):
        self.routes, self.headers, self.asked = routes, {}, []

    def get(self, url, params=None, timeout=None):
        self.asked.append(url)
        for key, body in self.routes.items():
            if url == key or url == f"{key}/query":
                return Resp(body(params) if callable(body) else body)
        return Resp({"error": {"code": 400, "message": "Invalid URL"}})


def _setup(monkeypatch, tmp_path, routes):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(S, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "permit_index", lambda rows=None: {})
    sess = Sess(routes)
    monkeypatch.setattr(S.requests, "Session", lambda: sess)
    return sess


def _services(*names):
    return {"services": [{"name": n, "type": "FeatureServer"} for n in names]}


def _viewer(url):
    return {"operationalLayers": [{"title": "North Carolina Waterbodies", "layers": [
        {"title": "Major Streams", "url": f"{S.ORG}/MajorHydro/FeatureServer/0"}]},
        {"title": "Sanitary Sewer Overflows since Jan 2026", "url": url}]}


def test_a_layer_that_is_no_longer_public_is_reported_plainly_and_the_records_stay(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {
        S.ORG: _services("Sanitary_Sewer_Overflows_September_2022_through_December_2025", "Report_an_SSO_Public_View"),
        S.VIEWER_MAP: _viewer(S.LAYER), S.LAYER: GONE})
    ev = tmp_path / "events" / "nc-dwr-sso-2026.json"
    ev.parent.mkdir(parents=True)
    ev.write_text(json.dumps({"source_id": S.SOURCE_ID, "ok": True, "last_ok_at": "2026-11-04T20:00:00Z",
                              "meta": {"registry_ids": [S.SOURCE_ID]}, "count": 1, "records": [{"event_id": "x"}]}))
    assert S.main([]) == 1
    out = json.loads(ev.read_text())
    assert out["ok"] is False and out["count"] == 1                     # the records already read are kept
    assert out["error"].startswith("source unavailable: the NC Division of Water Resources sewer overflow layer "
                                   "(Sanitary_Sewer_Overflows_since_Jan_2026) is not publicly available")
    assert "Item does not exist or is inaccessible" in out["error"]
    assert out["meta"]["unavailable"] is True and out["meta"]["registry_ids"] == [S.SOURCE_ID]
    since = out["meta"]["unavailable_since"]
    assert S.main([]) == 1                                              # the first-seen time is kept across runs
    assert json.loads(ev.read_text())["meta"]["unavailable_since"] == since


def test_a_layer_the_viewer_map_is_pointed_at_is_read(monkeypatch, tmp_path):
    rows = json.loads((FIX / "nc_dwr_sso_2026.json").read_text())
    page = rows["pages"][0] if "pages" in rows else rows
    sess = _setup(monkeypatch, tmp_path, {S.ORG: _services(), S.VIEWER_MAP: _viewer(NEW), NEW: page})
    assert S.main([]) == 0
    out = json.loads((tmp_path / "events" / "nc-dwr-sso-2026.json").read_text())
    assert out["ok"] and out["count"] == len(page["features"]) and out["meta"]["unavailable"] is False
    assert NEW in out["meta"]["layers"] and f"{NEW}/query" in sess.asked


def test_a_republished_layer_with_other_field_names_is_not_guessed(monkeypatch, tmp_path):
    other = {"features": [{"attributes": {"OBJECTID": 1, "IncidentNo": "X1", "StartDate": 1767225600000}}]}
    _setup(monkeypatch, tmp_path, {S.ORG: _services(), S.VIEWER_MAP: _viewer(NEW), NEW: other})
    assert S.main([]) == 1
    out = json.loads((tmp_path / "events" / "nc-dwr-sso-2026.json").read_text())
    assert out["ok"] is False and "needs a field mapping" in out["error"] and out["meta"]["unavailable"] is False


# ---------------------------------------------------------------- review 2026-11-06 (docs/reviews/2026-11-06-stale-sources-review.md)

def _previous(tmp_path):
    ev = tmp_path / "events" / "nc-dwr-sso-2026.json"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(json.dumps({"source_id": S.SOURCE_ID, "ok": True, "last_ok_at": "2026-11-04T20:00:00Z",
                              "meta": {"registry_ids": [S.SOURCE_ID]}, "count": 1, "records": [{"event_id": "x"}]}))
    return ev


def _two_layer_viewer(second_title, second_url):
    return {"operationalLayers": [{"title": "Sanitary Sewer Overflows since Jan 2026", "url": S.LAYER},
                                  {"title": second_title, "url": second_url}]}


def test_an_empty_layer_with_unknown_fields_does_not_hide_the_outage(monkeypatch, tmp_path):
    # the viewer's map also shows an empty overflow layer: no rows, no field list, so nothing shows it is this layer
    _setup(monkeypatch, tmp_path, {S.ORG: _services(), S.VIEWER_MAP: _two_layer_viewer("SSO reports", NEW),
                                   S.LAYER: GONE, NEW: {"features": []}})
    ev = _previous(tmp_path)
    assert S.main([]) == 1
    out = json.loads(ev.read_text())
    assert out["ok"] is False and out["count"] == 1 and out["meta"]["unavailable"] is True
    assert out["error"].startswith("source unavailable:") and "1 other sewer overflow layer" in out["error"]
    assert "needs a field mapping" in out["meta"]["layers"][NEW]["error"]


def test_an_empty_layer_whose_field_list_matches_is_read(monkeypatch, tmp_path):
    # a new year's layer on 1 January: no rows yet, but its query answers with this layer's fields
    empty = {"fields": [{"name": f} for f in S.KEY_FIELDS], "features": []}
    _setup(monkeypatch, tmp_path, {S.ORG: _services(), S.VIEWER_MAP: _viewer(NEW), NEW: empty})
    assert S.main([]) == 0
    assert NEW in json.loads((tmp_path / "events" / "nc-dwr-sso-2026.json").read_text())["meta"]["layers"]


def test_a_layer_of_another_organisation_on_the_viewer_map_is_never_read(monkeypatch, tmp_path):
    rows = json.loads((FIX / "nc_dwr_sso_2026.json").read_text())
    page = rows["pages"][0] if "pages" in rows else rows
    other = "https://services9.arcgis.com/SomeOtherOrg/arcgis/rest/services/County_SSOs/FeatureServer/0"
    sess = _setup(monkeypatch, tmp_path, {S.ORG: _services(), S.VIEWER_MAP: _two_layer_viewer("County SSOs", other),
                                          S.LAYER: GONE, other: page})
    ev = _previous(tmp_path)
    assert S.main([]) == 1
    out = json.loads(ev.read_text())
    assert not any(u.startswith(other) for u in sess.asked)             # same field names, but never asked
    assert out["ok"] is False and out["meta"]["unavailable"] is True and out["count"] == 1
    assert "organisation" in out["meta"]["layers"][other]["error"]


def test_the_history_layer_is_left_out_however_the_viewer_map_writes_its_url():
    hist_service = S.HIST_LAYER.rsplit("/", 1)[0] + "/"
    sess = Sess({S.VIEWER_MAP: {"operationalLayers": [
        {"title": "Sanitary Sewer Overflows September 2022 through December 2025", "url": hist_service},
        {"title": "Sanitary Sewer Overflows since Jan 2026", "url": S.LAYER}]}})
    assert S.viewer_layers(sess) == [S.LAYER]
