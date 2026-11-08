"""The live-only rule goes by a record's own state, never by a live water it names (2026-11-08, after 7023088): an
Alabama report whose ingester named a Georgia water stays out of the status build, the export and the charts while
Alabama is not in rules.json live_states, and comes back the moment it is. The charts keep to the same rule: no
discharger chart and no count for a record of a state not yet live. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from build import charts as C
from build import status as S
from export import build as X

NOW = datetime(2026, 11, 7, 23, tzinfo=UTC)


def _file(d: Path, sid: str, recs: list[dict]) -> None:
    (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "fetched_at": "2026-11-07T00:00:00Z", "ok": True,
                                                "last_ok_at": "2026-11-07T00:00:00Z", "count": len(recs),
                                                "records": recs}))


def _rec(sid: str, i: int, st: str, slug: str, day: int, disch: str) -> dict:
    return {"event_id": f"{sid}:{i}", "source_id": sid, "source_record_id": str(i), "event_type": "sso",
            "status": "ended", "raw": {"state": st}, "started_at": f"2026-10-{day:02d}T10:00:00Z",
            "ended_at": f"2026-10-{day:02d}T12:00:00Z", "water_slugs": [slug], "discharger_id": disch,
            "volume_gallons": 1000}


def _events(tmp_path: Path, with_al: bool = True) -> Path:
    d = tmp_path / "events"
    d.mkdir(parents=True, exist_ok=True)
    _file(d, "ga-epd-spills", [_rec("ga-epd-spills", i, "GA", "chattahoochee-river-ga", 3 + i, "ga-columbus")
                               for i in range(3)])
    if with_al:
        # Alabama's own report, which its ingester placed on the Georgia side of the river
        _file(d, "al-adem-sso-history", [_rec("al-adem-sso-history", 1, "AL", "chattahoochee-river-ga", 9,
                                              "al-phenix-city")])
    return d


def test_the_status_build_leaves_out_an_alabama_report_on_a_georgia_water_until_alabama_is_live(tmp_path):
    d = _events(tmp_path)
    al = {"event_id": "al-adem-sso-history:1", "source_id": "al-adem-sso-history", "raw": {"state": "AL"},
          "water_slugs": ["chattahoochee-river-ga"]}
    S._STATES = {"GA"}
    try:
        # event_state itself is unchanged: by its last fallback the report counts under the water's state
        assert S.event_state(al) == "GA"
        assert S.own_state(al) == "AL"
        _, events, _ = S.load_events(d, live={"GA"})
        assert sorted(e["event_id"] for e in events) == [f"ga-epd-spills:{i}" for i in range(3)]
        assert S.NOT_LIVE == [("al-adem-sso-history", "AL")]
        kept, n = X.live_jurisdiction_events([al], {"GA"})
        assert kept == [] and n == 1
        S._STATES = {"GA", "AL"}
        _, events, _ = S.load_events(d, live={"GA", "AL"})
        assert "al-adem-sso-history:1" in {e["event_id"] for e in events} and not S.NOT_LIVE
        kept, n = X.live_jurisdiction_events([al], {"GA", "AL"})
        assert len(kept) == 1 and n == 0
        # a record with nothing of its own to tell its state (a national feed's row) is kept, as before
        S._STATES = {"GA"}
        _file(d, "epa-national", [{"event_id": "epa-national:1", "source_id": "epa-national",
                                   "water_slugs": ["chattahoochee-river-ga"]}])
        _, events, _ = S.load_events(d, live={"GA"})
        assert "epa-national:1" in {e["event_id"] for e in events}
    finally:
        S._STATES = None


def _charts(tmp_path: Path, monkeypatch, live: list[str], with_al: bool = True) -> dict:
    """{(kind, key): chart document} from build.charts over a scratch world."""
    d = _events(tmp_path, with_al)
    build_dir = tmp_path / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    # the status build (--live-only) lists the Alabama report only once Alabama is live
    ids = [f"ga-epd-spills:{i}" for i in range(3)] + (["al-adem-sso-history:1"] if with_al and "AL" in live else [])
    (build_dir / "status.json").write_text(json.dumps(
        {"placements": {i: {"water_slugs": ["chattahoochee-river-ga"]} for i in ids},
         "waters": {"chattahoochee-river-ga": {"events": ids}}, "reaches": {}, "duplicates": {}}))
    (build_dir / "history.json").write_text("{}")
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "dischargers.json").write_text(json.dumps([
        {"id": "ga-columbus", "name": "Columbus Water Works", "state": "GA"},
        {"id": "al-phenix-city", "name": "Phenix City Utilities", "state": "AL"}]))
    rules = {**S.load_rules(), "live_states": live}
    waters = {"chattahoochee-river-ga": {"slug": "chattahoochee-river-ga", "name": "Chattahoochee River",
                                         "kind": "river", "state": "GA", "bbox": [-85.1, 32.0, -84.9, 32.5]}}
    monkeypatch.setattr(S, "_RULES", rules)
    monkeypatch.setattr(S, "_STATES", set(live))
    monkeypatch.setattr(C, "load_rules", lambda: rules)
    monkeypatch.setattr(C, "load_waters", lambda: waters)
    monkeypatch.setattr(C, "BUILD_DIR", build_dir)
    monkeypatch.setattr(C, "DATA_DIR", data_dir)
    real = S.load_events
    monkeypatch.setattr(C, "load_events", lambda include_fixtures=False, live=None: real(d, include_fixtures, live=live))
    data = C.Data(NOW)
    spans, per = C.source_spans(data)
    buckets, _, _ = C.gather(data)
    out = {}
    for (kind, key), bk in sorted(buckets.items()):
        doc = C.build_entity(bk, data, spans, per, C.entity_name(kind, key, bk, data))
        out[(kind, key)] = json.dumps(doc, sort_keys=True, default=str)
    return out


def test_the_charts_count_no_record_of_a_state_not_yet_live_and_give_it_no_discharger_chart(tmp_path, monkeypatch):
    with_al = _charts(tmp_path / "a", monkeypatch, ["GA"])
    without_al = _charts(tmp_path / "b", monkeypatch, ["GA"], with_al=False)
    # Alabama not live: its report changes no live chart (byte-identical to a world without it) and has no chart
    assert with_al == without_al
    assert ("discharger", "al-phenix-city") not in with_al and ("discharger", "ga-columbus") in with_al
    # the moment Alabama is live, its report is counted on the Georgia water and its operator has a chart
    live_al = _charts(tmp_path / "c", monkeypatch, ["GA", "AL"])
    assert ("discharger", "al-phenix-city") in live_al
    assert live_al[("water", "chattahoochee-river-ga")] != with_al[("water", "chattahoochee-river-ga")]
