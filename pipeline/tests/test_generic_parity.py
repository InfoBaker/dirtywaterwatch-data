"""Parity of the generic ingesters with the modules they could replace (docs/generic-ingesters.md): the
md-mde-overflows (Socrata) and md-baltimore-sso (ArcGIS) fetch blocks in data/sources/ against
ingest/md_mde_overflows.py and ingest/md_baltimore_sso.py on the same saved responses, record by record and
field by field; and the generic snapshot machine against the Philadelphia CSOcast machine on the same polls.

Fixtures (tests/fixtures/generic/): 26 features of the City's SSO_Points2 layer and 95 rows of MDE's table, both
fetched 2026-11-04 and chosen to cover repeated keys, rows MDE marks duplicate, City SSOs on both, the coordinate
repairs, every overflow type and the no-water texts; one free-text name replaced by a placeholder. No network."""
from __future__ import annotations

import json
from pathlib import Path

from build import redact
from ingest import md_baltimore_sso as B
from ingest import md_mde_overflows as M
from ingest import pa_phila_csocast as P
from ingest.generic import arcgis, runner, snapshot, socrata
from ingest.generic import fieldmap as F

FIX = Path(__file__).parent / "fixtures" / "generic"
FETCHED = "2026-11-04T12:00:00Z"
# raw differs by design (the generic raw is {"row": safe fields, notes}); fetched_at is the run's clock
NOT_COMPARED = {"raw", "fetched_at"}


def compare(module_recs, generic_recs) -> dict:
    a = {r["event_id"]: r for r in module_recs}
    b = {r["event_id"]: r for r in generic_recs}
    out = {"only_module": sorted(set(a) - set(b)), "only_generic": sorted(set(b) - set(a)), "fields": {}}
    for k in set(a) & set(b):
        for f in a[k]:
            if f in NOT_COMPARED:
                continue
            x, y = a[k][f], b[k].get(f)
            if f == "parse_error":            # the wording differs; whether there is one must not
                x, y = bool(x), bool(y)
            if x != y:
                out["fields"].setdefault(f, []).append((k, x, y))
    return out


def baltimore():
    content = (FIX / "md_baltimore_sso_layer.json").read_bytes()
    feats = [f["attributes"] for f in json.loads(content)["features"]]
    mod, _ = B.build(feats, FETCHED, [])
    mod = redact.redact_events(mod)
    _, block = runner.load_source("md-baltimore-sso")
    gen, stats = runner.build("md-baltimore-sso", block, arcgis.parse(block, content), FETCHED, [])
    return mod, gen, stats, block


def test_baltimore_arcgis_port_matches_the_module_field_by_field():
    mod, gen, stats, _ = baltimore()
    assert len(mod) == len(gen) == 26
    d = compare(mod, gen)
    assert d == {"only_module": [], "only_generic": [], "fields": {}}
    by = {r["event_id"]: r for r in gen}
    # the fixture covers what the module's rules decide
    assert {r["status"] for r in gen} >= {"ongoing", "ended"}
    assert any(r["raw"].get("_basis", {}).get("started_at", "").startswith("SSO_DATE") for r in gen)
    assert any(r["water_slugs"] for r in gen) and any(r["waterbody_text"] and not r["water_slugs"] for r in gen)
    assert all(r["time_precision"] == "minute" and r["started_at"].endswith(("-04:00", "-05:00")) for r in by.values())


def test_baltimore_port_keeps_only_the_safe_fields_in_raw():
    _, gen, _, block = baltimore()
    safe = set(block["safe_fields"])
    for r in gen:
        assert set(r["raw"]["row"]) <= safe
        assert "WAIVER_REASON" not in r["raw"]["row"] and "COMMENT_RELIEF_REQUEST_TYPE" not in r["raw"]["row"]


def test_mde_socrata_port_matches_the_module_field_by_field():
    text = (FIX / "md_mde_overflows_rows.csv").read_text(encoding="utf-8-sig")
    meta = json.loads((FIX / "md_mde_overflows_meta.json").read_text())
    dpw, _, _, _ = baltimore()
    permits, _ = M.load_dischargers()
    mod, _ = M.build(M.read_rows(text), meta, FETCHED, [], dpw, permits)
    _, block = runner.load_source("md-mde-overflows")
    gen, stats = runner.build("md-mde-overflows", block, socrata.parse(block, text.encode()), FETCHED, [], meta,
                              {"md_baltimore_records": dpw})
    assert len(mod) == len(gen) == 95
    d = compare(mod, gen)
    assert d == {"only_module": [], "only_generic": [], "fields": {}}
    # the fixture exercises the rules being compared
    dup = stats["duplicates"]
    assert dup["repeated_rows"] > 0 and dup["marked_by_mde"] > 0 and dup["baltimore_dpw"] > 0
    assert any("~2" in r["event_id"] for r in gen)
    assert {r["event_type"] for r in gen} >= {"cso", "sso", "bypass"}
    assert any("degrees and decimal minutes" in (r["raw"].get("_coords") or "") for r in gen)
    assert any(r["water_slugs"] for r in gen) and any(r["raw"].get("_water", {}).get("why_none") for r in gen)
    assert all(r["source_updated_at"] == gen[0]["source_updated_at"] is not None for r in gen)
    assert all(r["reported_at"] is None and r["published_at"] is None for r in gen)    # MDE publishes neither
    # a private name in the operators' free text reaches neither the module's records nor the generic ones
    for recs in (mod, gen):
        assert "Placeholder" not in json.dumps(recs)


# ---------------------------------------------------------------- snapshot: the CSOcast machine

CSOCAST_BLOCK = {
    "platform": "snapshot", "rows_from": "arcgis", "url": "https://example.invalid/FeatureServer/0",
    "time_zone": "America/New_York",
    "safe_fields": ["Name", "Status_Message", "LastPoll", "Latitude", "Longitude", "Waterbody", "Street"],
    "snapshot": {"unit": "Name", "state": "Status_Message",
                 "states": {"currently overflowing": "active", "^overflow in the past": "recent",
                            "^no overflow": "clear", "not currently available": "no_data"},
                 "poll_time": {"field": "LastPoll", "parse": "epoch_ms_wallclock"}},
    "record": {"event_type": {"const": "cso"}, "outfall_id": "Name", "outfall_name": "Street",
               "lat": {"field": "Latitude", "parse": "number"}, "lon": {"field": "Longitude", "parse": "number"}},
}
OVER, RECENT, CLEAR, NODATA = ("Currently overflowing.", "Overflow in the past 72 hours.",
                               "No overflow in the past 72 hours.", "Data is not currently available.")
T0 = 1793714400000          # 2026-11-03 14:00 wall clock


def polls():
    """Five hourly polls of three outfalls: an overflow that opens and closes, one first seen as recent, one that goes
    to no data while overflowing and comes back."""
    seq = [(OVER, CLEAR, OVER), (OVER, RECENT, NODATA), (RECENT, RECENT, OVER), (CLEAR, CLEAR, CLEAR), (OVER, CLEAR, CLEAR)]
    out = []
    for i, msgs in enumerate(seq):
        rows = [{"Name": n, "Status_Message": m, "LastPoll": T0 + i * 3_600_000, "Latitude": 39.95, "Longitude": -75.15,
                 "Street": "Example St"} for n, m in zip(("D_02", "S_12A", "C_FRA"), msgs)]
        out.append((f"2026-11-03T{17 + i:02d}:05:00Z", rows))
    return out


def test_snapshot_machine_matches_the_csocast_machine():
    ps, gs = {}, {}
    for now, rows in polls():
        P.poll(ps, rows, now)
        ctx = F.Ctx("pa-phila-csocast-generic", CSOCAST_BLOCK, F.ZoneInfo("America/New_York"), now)
        snapshot.build(rows, ctx, gs)
    pe = sorted(ps["events"].values(), key=lambda e: (e["outfall"], e.get("ended_at") or "", e.get("started_at") or ""))
    ge = sorted(gs["events"].values(), key=lambda e: (e["unit"], e.get("ended_at") or "", e.get("started_at") or ""))
    keys = ("started_at", "ended_at", "state", "started_after", "occurred_after", "ended_after", "no_data_since")
    assert [(e["outfall"], *(e.get(k) for k in keys)) for e in pe] == [(e["unit"], *(e.get(k) for k in keys)) for e in ge]
    assert len(ge) == 4            # D_02 twice, S_12A first seen as recent, C_FRA through no data


def test_snapshot_records_are_dated_to_the_poll():
    gs = {}
    recs = []
    for now, rows in polls():
        ctx = F.Ctx("x-snap", CSOCAST_BLOCK, F.ZoneInfo("America/New_York"), now)
        recs, stats = snapshot.build(rows, ctx, gs)
    assert {r["time_precision"] for r in recs} == {"poll"}
    assert all(r["event_type"] == "cso" and r["outfall_id"] in ("D_02", "S_12A", "C_FRA") for r in recs)
    recent = [r for r in recs if r["started_at"] is None]
    assert recent and all(r["status"] == "ended" and r["raw"]["occurred_after"] for r in recent)
    ongoing = [r for r in recs if r["status"] == "ongoing"]
    assert len(ongoing) == 1 and ongoing[0]["ended_at"] is None and ongoing[0]["outfall_id"] == "D_02"
    assert stats["units"]["D_02"]["open_event_id"] == ongoing[0]["event_id"]
