"""NC DWR sewer overflows: the Survey123 results layer DEQ's Tracking Map shows since November 2026
(survey123_1766d0b5d5294b05a27751560c1f1f97_results; ingest/nc_dwr_sso.py SURVEY_MAP). Fixtures trimmed from the real
answers of 2026-11-16: tests/fixtures/nc_dwr_sso_survey123.json holds 18 real rows, requested by named safe fields only
(street addresses replaced by a placeholder, weather and any free-text cause blanked); nc_dwr_sso_2026_held.json holds
three records of the 2026 layer as the public CSV published them (two of them, by the history layer's duplicate links,
carry the incident numbers 202600200 and 202600196; the third, a 50,000-gallon overflow of 2026-10-23 the new layer
does not hold, carries a number no row has). No network.
Run from pipeline/: python -m pytest tests/test_nc_dwr_sso_survey123.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import common
from ingest import nc_dwr_sso as S

FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-16T16:00:00Z"
PERMITS = {"WQCS00002": "nc-raleigh"}


def rows():
    return S._load_file(str(FIX / "nc_dwr_sso_survey123.json"))


def held():
    return json.loads((FIX / "nc_dwr_sso_2026_held.json").read_text())


def records(prev=None, hist=None):
    recs, stats = S.build(rows(), FETCHED, prev or [], PERMITS, hist)
    return {r["source_record_id"][:8]: r for r in recs}, stats


# (gid prefix, permit, facility, start, end, status, gallons, water, reached water, lat, lon), compared by hand with
# the layer's rows (epoch ms in UTC -> Eastern), newest first
NEWEST = [
    ("91eec952", "WQCS00113", "Louisburg Collection System", "2026-11-12T12:15:00-05:00", None, "ongoing", None, None,
     False, 36.095555, -78.296976),
    ("fb3a19ad", "WQCS00014", "Greenville Utilities Commission Collection System", "2026-11-10T17:46:00-05:00",
     "2026-11-10T20:25:00-05:00", "ended", 8316, "Greens Mill Run", True, 35.590638, -77.37876),
    ("824476f0", "WQCS00010", "High Point Collection System", "2026-11-09T15:34:00-05:00", "2026-11-09T16:20:00-05:00",
     "ended", 230, "Unnamed tributary to Oak Hollow Lake", True, 36.021672, -80.026043),
    ("97b4a4c8", "WQCS00031", "OWASA Collection System", "2026-11-09T10:25:00-05:00", "2026-11-09T10:27:00-05:00",
     "ended", 200, "Cedar Fork", True, 35.949236, -79.019512),
    ("80badd76", "WQCS00028", "Morganton Collection System", "2026-11-09T09:30:00-05:00", "2026-11-09T10:30:00-05:00",
     "ended", 200, "CATAWBA RIVER (including backwaters of Rhodhiss Lake below elevation 995)", True, 35.770554,
     -81.677781),
    ("c8e6bdbd", "WQCS00024", "Lumberton Collection System", "2026-11-09T09:00:00-05:00", "2026-11-09T10:00:00-05:00",
     "ended", 250, "Lake in Luther Britt Park", True, 34.627572, -79.029032),
    ("2901a9c7", "WQCS00009", "W&S Authority of Cabarrus Co Collection System", "2026-11-05T11:45:00-05:00",
     "2026-11-05T11:50:00-05:00", "ended", 1800, None, False, 35.377823, -80.431219),
    ("4a942fa2", "WQCS00066", "Anson County Collection System", "2026-11-05T11:30:00-05:00", None, "ongoing", None,
     None, False, 34.979226, -80.090978),
    ("c651b651", "WQCS00066", "Anson County Collection System", "2026-11-04T14:00:00-05:00", "2026-11-05T10:20:00-05:00",
     "ended", 51365, None, False, 34.976565, -80.073014),
    ("ed530ca2", "WQCS00042", "Lexington Collection System", "2026-11-04T09:40:00-05:00", "2026-11-04T09:55:00-05:00",
     "ended", 30, "Michael Branch", True, 35.825148, -80.274177),
    ("260aed7f", "WQCS00003", "Winston-Salem Collection System", "2026-11-04T08:50:00-05:00",
     "2026-11-04T10:50:00-05:00", "ended", 3300, "Monarcas Creek", True, 36.145224, -80.264313),
    ("6e2544f1", "WQCS00001", "Charlotte Water Collection System", "2026-11-01T12:37:00-05:00",
     "2026-11-01T14:28:00-05:00", "ended", 545, "Rocky River", True, 35.448417, -80.774037),
]


def test_the_twelve_newest_real_rows_parse_to_the_layers_values():
    recs, _ = records()
    for gid, permit, fac, start, end, status, gal, water, reached, lat, lon in NEWEST:
        r = recs[gid]
        got = (r["npdes_permit"], r["discharger_name"], r["started_at"], r["ended_at"], r["status"], r["volume_gal"],
               r["waterbody_text"], r["raw"]["reached_water"], r["lat"], r["lon"])
        assert got == (permit, fac, start, end, status, gal, water, reached, lat, lon), gid
        assert r["event_id"] == f"nc-dwr-sso-2026:{r['source_record_id']}" and r["time_precision"] == "minute"
        assert r["published_at"] is None and r["raw"]["_layer"] == S.SURVEY_LAYER and r["event_type"] == "sso"


def test_times_are_utc_epochs_in_eastern_time_and_the_published_raleigh_start_still_matches():
    recs, _ = records()
    r = recs["aac68069"]                                   # Raleigh, 1,143,800 gallons; Raleigh Water said 8:21 a.m.
    assert r["started_at"] == "2026-05-12T08:21:00-04:00" and r["ended_at"] == "2026-05-12T21:58:00-04:00"
    assert r["volume_gal"] == 1143800 and r["discharger_id"] == "nc-raleigh"
    assert r["waterbody_text"] == "Brier Creek" and r["raw"]["_stream_index"] == "27-33-4"
    assert "_gallons_to_water" not in r["raw"]             # volume_waterbody -1 is unfilled, never gallons
    assert r["reported_at"] is None                        # report_date is blank on the rows loaded before November
    assert r["raw"]["_decoded_times"]["CreationDate"].startswith("2026-11-01")   # the bulk load, kept apart
    n = recs["fb3a19ad"]
    assert n["reported_at"] == "2026-11-11T09:28:00-05:00" and n["fetched_at"] == FETCHED


def test_unfilled_volume_and_the_cautious_reading_of_reached_water():
    recs, _ = records()
    assert recs["91eec952"]["volume_gal"] is None and recs["91eec952"]["estimate_flag"] == "unknown"   # volume -1
    r = recs["0afc1203"]                     # "Not Impacted", but 200 gallons reached surface water: reached water
    assert r["raw"]["reached_water"] is True and r["raw"]["_gallons_to_water"] == 200
    assert "Not Impacted" in r["raw"]["_reached_water_basis"]
    r = recs["3430f47d"]                     # the end is before the start: not used; no end is invented
    assert r["ended_at"] is None and "an end before the start was not used" in r["parse_error"]
    assert r["status"] == "ended" and r["raw"]["_end_basis"]


def test_rows_before_2026_are_left_to_the_history_layer_unless_it_lacks_them():
    recs, stats = records()
    assert "c58469d9" not in recs and stats["left_to_history_layer"] == 1     # 2025-01-01, incident 202500025
    recs, stats = records(hist={"202500024"})
    assert recs["c58469d9"]["raw"]["_kept_basis"] and stats["before_2026_not_in_history"] == 1
    recs, stats = records(hist={"202500025"})
    assert "c58469d9" not in recs


def test_no_duplicate_and_no_loss_across_the_layer_switch():
    old = held()
    recs, stats = S.build(rows(), FETCHED, old, PERMITS, None)
    by = {r["event_id"]: r for r in recs}
    # the 2026 layer's copies of incidents 202600200 and 202600196 are duplicates of the new layer's records
    for o, new_gid in ((old[0], "1fe6ff92"), (old[1], "c8ff6787")):
        kept = by[o["event_id"]]
        new = next(r for r in recs if r["source_record_id"].startswith(new_gid))
        assert kept["duplicate_of"] == new["event_id"] and new["duplicate_of"] is None
        assert kept["started_at"] == new["started_at"]                 # the same start in both layers
        assert kept["raw"]["_missing_from_layer_since"] == FETCHED
    # a held report the new layer does not have stays as it was: ongoing, not ended, not a duplicate
    rock = by[old[2]["event_id"]]
    assert rock["status"] == "ongoing" and rock["ended_at"] is None and rock["duplicate_of"] is None
    assert stats["duplicates"] == 2 and stats["kept_from_earlier_runs"] == 3
    standing = [r for r in recs if not r.get("duplicate_of")]
    assert len({S.incident(r) for r in standing}) == len(standing)
    # a second run links the same way (recomputed, not stacked)
    again, _ = S.build(rows(), "2026-11-16T17:00:00Z", recs, PERMITS, None)
    assert sum(1 for r in again if r.get("duplicate_of")) == 2


def test_history_copies_point_at_the_new_layers_record_on_a_backfill():
    recs, _ = S.build(rows(), FETCHED, held(), PERMITS, None)
    hist = [{"OBJECTID": 1, "incident_number": "202600200", "start_date": 1771059600000, "permit_id": "WQCS00042"}]
    h, _ = S.build_history(hist, FETCHED, recs, PERMITS)
    new = next(r for r in recs if r["source_record_id"].startswith("1fe6ff92"))
    assert h[0]["duplicate_of"] == new["event_id"]


def test_only_safe_fields_are_requested_kept_and_linked():
    for f in ("owner", "submitter_name", "submitter", "submitter_id", "reporter", "reporter_id", "Creator", "Editor",
              "latest_comments", "resolution", "em_43"):
        assert f not in S.SURVEY_FIELDS
    recs, _ = records()
    for r in recs.values():
        assert set(k for k in r["raw"] if not k.startswith("_")) <= set(S.SURVEY_FIELDS) | {"reached_water"}
        assert "outFields=*" not in r["source_url"] and "submitter" not in r["source_url"]


def test_the_layer_is_read_by_its_description_and_named_fields_only(monkeypatch, tmp_path):
    feats = json.loads((FIX / "nc_dwr_sso_survey123.json").read_text())["pages"][0]["features"]
    layer_fields = S.SURVEY_FIELDS + ["owner", "submitter_name", "reporter", "latest_comments", "Creator"]
    asked = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    class Sess:
        headers = {}

        def get(self, url, params=None, timeout=None):
            asked.append((url, dict(params or {})))
            if url == S.ORG:
                return Resp({"services": []})
            if url == S.VIEWER_MAP:
                return Resp({"operationalLayers": [{"title": "Water Quality - Sanitary Sewer Overflows Since 2023",
                                                    "url": S.SURVEY_LAYER}]})
            if url == S.SURVEY_LAYER:
                return Resp({"name": "water_quality_sso_full_dataset", "fields": [{"name": f} for f in layer_fields],
                             "editingInfo": {"dataLastEditDate": 1794519922649}})
            if url == f"{S.SURVEY_LAYER}/query":
                want = params["outFields"].split(",")
                return Resp({"features": [{"attributes": {k: v for k, v in f["attributes"].items() if k in want}}
                                          for f in feats]})
            return Resp({"error": {"code": 400, "message": "Invalid URL"}})

    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(S, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(S, "ROOT", tmp_path)
    monkeypatch.setattr(S, "permit_index", lambda rows=None: {})
    monkeypatch.setattr(S.requests, "Session", lambda: Sess())
    assert S.main([]) == 0
    out = json.loads((tmp_path / "events" / "nc-dwr-sso-2026.json").read_text())
    assert out["ok"] and out["count"] == 17 and out["meta"]["layers"][S.SURVEY_LAYER]["schema"] == "survey123"
    assert out["meta"]["newest_start"] == "2026-11-12T12:15:00-05:00"
    queries = [p for u, p in asked if u.endswith("/query")]
    assert queries and all(p["outFields"] == ",".join(S.SURVEY_FIELDS) for p in queries)
    saved = "\n".join(p.read_text() for p in (tmp_path / "raw").rglob("*") if p.is_file())
    assert saved and "submitter" not in saved and "owner" not in saved


def test_a_missing_field_names_the_layer_the_missing_fields_and_the_lookalikes():
    schema, why = S.layer_schema(["objectid", "GlobalID", "bims_incident_no", "permit_and_name", "sso_start_date",
                                  "end_date"])
    assert schema is None
    assert "fields incident_number, permit_with_name, start_date absent" in why
    assert "sso_start_date" in why and "needs a field mapping" in why
    assert S.layer_schema(S.SURVEY_FIELDS)[0] == "survey123" and S.layer_schema(S.FIELDS)[0] == "2026"
    assert S.layer_schema([])[0] is None


def test_a_failed_read_keeps_every_held_record_as_it_was(monkeypatch, tmp_path):
    class Sess:
        headers = {}

        def get(self, url, params=None, timeout=None):
            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    if url == S.VIEWER_MAP:
                        return {"operationalLayers": [{"title": "Sanitary Sewer Overflows", "url": S.SURVEY_LAYER}]}
                    if url == S.SURVEY_LAYER:            # the schema changed again
                        return {"fields": [{"name": f} for f in ("objectid", "globalid", "sso_start", "permit")]}
                    return {"services": []}
            return R()

    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(S, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(S.requests, "Session", lambda: Sess())
    ev = tmp_path / "events" / "nc-dwr-sso-2026.json"
    ev.parent.mkdir(parents=True)
    old = held()
    ev.write_text(json.dumps({"source_id": S.SOURCE_ID, "ok": True, "meta": {"registry_ids": [S.SOURCE_ID]},
                              "count": len(old), "records": old}))
    assert S.main([]) == 1
    out = json.loads(ev.read_text())
    assert out["ok"] is False and out["records"] == old
    assert S.SURVEY_LAYER in out["error"] and "incident_number, permit_with_name, start_date absent" in out["error"]
    assert "sso_start" in out["error"] and "permit" in out["error"]
