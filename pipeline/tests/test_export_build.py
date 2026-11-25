"""Normal export.build output, including per-water event provenance."""
import json
import common

from build import rain_history, reaches, status as S
from common import event
from export import build as X, coverage, outfalls


def test_normal_export_keeps_calculated_end_basis_in_water_json(tmp_path, monkeypatch, capsys):
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
                        "DATA_DIR": tmp_path / "data"}.items():
        monkeypatch.setattr(X, name, value)
    monkeypatch.setattr(common, "DATA_DIR", tmp_path / "data")
    # Isolate the private request list; no state list is read by this export.
    monkeypatch.setattr(X.RemovalList, "load", lambda: X.RemovalList([]))
    monkeypatch.setattr(S, "_STATES", {"RI"})
    monkeypatch.setattr(S, "load_waters", lambda: {slug: water})
    monkeypatch.setattr(S, "load_registry_outfalls", lambda **kw: [])
    monkeypatch.setattr(S, "load_registry", lambda: {})
    monkeypatch.setattr(S, "load_events", lambda *args: ({}, [e], []))
    monkeypatch.setattr(S, "load_rules", lambda: {})
    monkeypatch.setattr(S, "water_geometry", lambda *args: None)
    monkeypatch.setattr(X, "load_dischargers", lambda: ([], ""))
    monkeypatch.setattr(X, "launches_for", lambda *args: [])
    levels = {"method_version": "test", "permits": {}}
    monkeypatch.setattr(rain_history, "load_levels", lambda: levels)
    monkeypatch.setattr(reaches, "load_reaches", lambda: {})
    monkeypatch.setattr(outfalls, "ma_layer_rows", lambda: [])
    monkeypatch.setattr(coverage, "load_notification_pages", lambda: None)
    monkeypatch.setattr(coverage, "load_register", lambda: None)
    # Distinct phase durations, not cumulative elapsed time; the public clock is independent.
    ticks = iter(i * 2.5 for i in range(100))
    monkeypatch.setattr(X, "perf_counter", lambda: next(ticks), raising=False)

    meta = X.export()
    output = capsys.readouterr().out
    timing_lines = [line for line in output.splitlines() if line.startswith('timing:')]
    assert "blocklist" not in output
    assert timing_lines == [f'timing: export.{phase} 2 s' for phase in (
        'status', 'inputs', 'enrichment', 'per_event_files', 'events', 'assessments',
        'waters', 'advisory_points', 'reaches', 'history', 'dischargers', 'outfalls', 'feeds',
        'coverage', 'csv', 'metadata', 'requested_removals')]
    assert json.loads((X.OUT_DIR / "rain-levels.json").read_text()) == levels
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

    # A request for a history-only ID must overwrite its previously published event object too.
    old_id = 'ri-ridoh-beaches:old-record'
    requested = X.RemovalList([{'id': 'historic-request', 'added': '2026-11-25',
                                'kind': 'record', 'match': old_id}])
    monkeypatch.setattr(X.RemovalList, 'load', lambda: requested)
    X.export()
    assert not (X.OUT_DIR / 'events' / X.event_file_name(old_id)).exists()
    assert 'events/' + X.event_file_name(old_id) in json.loads(
        (X.DATA_DIR / 'private/publication-deletions.json').read_text())
    assert json.loads((X.OUT_DIR / 'events' / X.event_file_name(e['event_id'])).read_text())['event_id'] == e['event_id']
