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
    assert out["error"].startswith("source unavailable: DWR's sewer overflow layer (Sanitary_Sewer_Overflows_since_Jan_2026)")
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
