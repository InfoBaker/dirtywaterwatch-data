"""Normal export.build output, including per-water event provenance."""
import json

from build import rain_history, reaches, status as S
from common import event
from export import build as X, coverage, outfalls


def test_normal_export_keeps_calculated_end_basis_in_water_json(tmp_path, monkeypatch):
    slug = "third-beach-ri"
    e = event(
        source_id="ri-ridoh-beaches", source_record_id="third-beach:middletown:2025-08-26",
        event_type="beach_closure", status="advisory_lifted", water_slugs=[slug],
        started_at="2025-08-26T00:00:00-04:00", ended_at="2025-08-28T00:00:00-04:00",
        time_precision="day", raw={"ended_at_basis": "Closed On + Number of Days Closed (Re-Opened blank)",
                                   "Number of Days Closed": "2"})
    # Supply cached status and source inputs; enrichment and all export writers run normally.
    water = {"slug": slug, "name": "Third Beach", "kind": "bay", "state": "RI"}
    st = {"built": "2026-11-22T12:00:00Z", "now": "2026-11-22T12:00:00Z",
          "waters": {slug: {**water, "status": "grey", "since": None, "reason_short": "No current report",
                            "reasons": [], "events": [e["event_id"]], "stale": False,
                            "stale_sources": [], "covered_by": []}},
          "placements": {e["event_id"]: {"water_slugs": [slug], "state": "RI", "fixture": False}}}
    monkeypatch.setattr(X, "ensure_status", lambda *args: (st, {"waters": {}, "intervals": {}}))
    for name, value in {"OUT_DIR": tmp_path / "out", "BUILD_DIR": tmp_path / "build",
                        "DATA_DIR": tmp_path / "data", "BLOCKED_MARK": tmp_path / "blocked.json",
                        "HITS_MARK": tmp_path / "hits.json", "SCAN_CACHE": tmp_path / "scan.json"}.items():
        monkeypatch.setattr(X, name, value)
    monkeypatch.setattr(S, "_STATES", {"RI"})
    monkeypatch.setattr(S, "load_waters", lambda: {slug: water})
    monkeypatch.setattr(S, "load_registry_outfalls", lambda **kw: [])
    monkeypatch.setattr(S, "load_registry", lambda: {})
    monkeypatch.setattr(S, "load_events", lambda *args: ({}, [e], []))
    monkeypatch.setattr(S, "load_rules", lambda: {})
    monkeypatch.setattr(S, "water_geometry", lambda *args: None)
    monkeypatch.setattr(X, "load_dischargers", lambda: ([], ""))
    monkeypatch.setattr(X, "launches_for", lambda *args: [])
    monkeypatch.setattr(rain_history, "load_levels", lambda: None)
    monkeypatch.setattr(reaches, "load_reaches", lambda: {})
    monkeypatch.setattr(outfalls, "ma_layer_rows", lambda: [])
    monkeypatch.setattr(coverage, "load_notification_pages", lambda: None)
    monkeypatch.setattr(coverage, "load_register", lambda: None)

    meta = X.export()
    assert meta["counts"]["events"] == 1
    full = json.loads((X.OUT_DIR / "events" / X.event_file_name(e["event_id"])).read_text())
    slim = json.loads((X.OUT_DIR / "events.json").read_text())["events"][0]
    water_event = json.loads((X.OUT_DIR / "waters" / f"{slug}.json").read_text())["events"][0]
    assert full["ended_at_ours"]["basis"] == (
        "We added the number of days closed in the sheet, 2 days, to its closure date. "
        "The sheet gives no reopening date.")
    assert water_event["ended_at_ours"] == slim["ended_at_ours"]
    assert water_event["ended_at_ours"]["basis"] == full["ended_at_ours"]["basis"]
    assert water_event["ended_at_ours"]["basis_short"] == full["ended_at_ours"]["basis_short"]
    assert water_event["ended_at"] == e["ended_at"]
    assert water_event["ended_at_precision"] == "day"
