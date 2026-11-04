"""Parity of the generic ingesters with the modules they could replace (docs/generic-ingesters.md): the
md-mde-overflows (Socrata) and md-baltimore-sso (ArcGIS) fetch blocks in data/sources/ against
ingest/md_mde_overflows.py and ingest/md_baltimore_sso.py on the same saved responses, record by record and
field by field, over several runs (corrected rows, edited addresses, rows that leave and come back), with the
module's per-record notes present in the generic raw; and the generic snapshot machine against the Philadelphia
CSOcast machine on the same polls.

Fixtures (tests/fixtures/generic/): 26 features of the City's SSO_Points2 layer and 95 rows of MDE's table, both
fetched 2026-11-04 and chosen to cover repeated keys, rows MDE marks duplicate, City SSOs on both, the coordinate
repairs, every overflow type and the no-water texts; one free-text name replaced by a placeholder. No network.
When full saved responses are present in data/raw/ (not in git), the whole tables are compared too."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from build import redact
from common import ROOT
from ingest import md_baltimore_sso as B
from ingest import md_mde_overflows as M
from ingest import pa_phila_csocast as P
from ingest.generic import arcgis, runner, snapshot, socrata
from ingest.generic import fieldmap as F

FIX = Path(__file__).parent / "fixtures" / "generic"
FETCHED = "2026-11-04T12:00:00Z"
LATER = ("2026-11-04T13:00:00Z", "2026-11-04T14:00:00Z")
# raw is compared by its note keys (the generic raw keeps the source's fields under raw.row); fetched_at is the
# run's clock
NOT_COMPARED = {"raw", "fetched_at"}
# the module's raw note -> the generic raw note that carries the same citation
RAW_KEY_MAP = {"_ended_at_basis": "_basis", "_start_basis": "_basis", "_end_while_in_progress": "_end_while_ongoing"}


def compare(module_recs, generic_recs, source_fields=()) -> dict:
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
        # every note the module writes on a record is on the generic record too (the source's own fields are in
        # the generic raw.row by design)
        notes = {RAW_KEY_MAP.get(n, n) for n in a[k]["raw"] if n not in source_fields and n != "row"}
        missing = notes - set(b[k]["raw"])
        if missing:
            out["fields"].setdefault("raw notes", []).append((k, sorted(missing)))
    return out


def layer_fields(content: bytes) -> set:
    return {f["name"] for f in json.loads(content).get("fields") or []}


def baltimore_runs(contents: list[bytes], times=(FETCHED, *LATER)):
    mod, gen = [], []
    _, block = runner.load_source("md-baltimore-sso")
    stats = None
    for content, t in zip(contents, times):
        feats = [f["attributes"] for f in json.loads(content)["features"]]
        mod, _ = B.build(feats, t, mod)
        mod = redact.redact_events(mod)
        gen, stats = runner.build("md-baltimore-sso", block, arcgis.parse(block, content), t, gen)
    return mod, gen, stats, block


def baltimore():
    return baltimore_runs([(FIX / "md_baltimore_sso_layer.json").read_bytes()])


def test_baltimore_arcgis_port_matches_the_module_field_by_field():
    content = (FIX / "md_baltimore_sso_layer.json").read_bytes()
    mod, gen, stats, _ = baltimore()
    assert len(mod) == len(gen) == 26
    d = compare(mod, gen, layer_fields(content))
    assert d == {"only_module": [], "only_generic": [], "fields": {}}
    by = {r["event_id"]: r for r in gen}
    # the fixture covers what the module's rules decide
    assert {r["status"] for r in gen} >= {"ongoing", "ended"}
    assert any(r["raw"].get("_basis", {}).get("started_at", "").startswith("SSO_DATE") for r in gen)
    assert any(r["water_slugs"] for r in gen) and any(r["waterbody_text"] and not r["water_slugs"] for r in gen)
    assert all(r["time_precision"] == "minute" and r["started_at"].endswith(("-04:00", "-05:00")) for r in by.values())
    # the per-record citations: the time rule and the decoded codes, as the module writes them
    m = {r["event_id"]: r for r in mod}
    for k, r in by.items():
        assert r["raw"]["_time_basis"].startswith("The source stores local wall-clock time as if it were UTC")
        assert r["raw"]["_decoded_times"] == m[k]["raw"]["_decoded_times"]
        assert r["raw"]["_status_name"] == m[k]["raw"]["_status_name"]
        assert r["raw"]["_responsibility"] == m[k]["raw"]["_responsibility"]
        if "_watershed_name" in m[k]["raw"]:
            assert r["raw"]["_watershed_name"] == m[k]["raw"]["_watershed_name"]


def test_baltimore_port_keeps_the_module_history_over_runs():
    content = (FIX / "md_baltimore_sso_layer.json").read_bytes()
    doc = json.loads(content)
    prog = next(f for f in doc["features"] if f["attributes"]["STATUS"] == "PROG")
    later = json.loads(content)
    for f in later["features"]:
        if f["attributes"]["OBJECTID"] == prog["attributes"]["OBJECTID"]:
            f["attributes"].update({"STATUS": "5DAY", "EST_VOLUME": 1234.0})
    gone = json.loads(content)
    gone["features"] = [f for f in gone["features"] if f["attributes"]["OBJECTID"] != prog["attributes"]["OBJECTID"]]
    runs = [content, json.dumps(later).encode(), json.dumps(gone).encode()]
    mod, gen, _, _ = baltimore_runs(runs)
    assert compare(mod, gen, layer_fields(content)) == {"only_module": [], "only_generic": [], "fields": {}}
    eid = f"md-baltimore-sso:{prog['attributes']['OBJECTID']}"
    m, g = {r["event_id"]: r for r in mod}[eid], {r["event_id"]: r for r in gen}[eid]
    for key in ("_status_seen", "_volume_seen", "_missing_from_layer_since", "_first_seen_at"):
        assert g["raw"][key] == m["raw"][key], key


def test_baltimore_port_matches_the_module_when_an_overflow_starts_or_ends_at_midnight():
    """END_DATETIME and START_DATETIME hold wall-clock times: one at exactly 00:00 is a time, as the module reads
    it, and not a date whose end is moved a day later."""
    import datetime as D
    content = (FIX / "md_baltimore_sso_layer.json").read_bytes()
    doc = json.loads(content)
    timed = [f["attributes"] for f in doc["features"] if f["attributes"].get("END_DATETIME")
             and f["attributes"].get("START_DATETIME")]
    a, b = timed[0], timed[1]
    end = D.datetime.fromtimestamp(a["END_DATETIME"] / 1000, D.UTC)
    a["END_DATETIME"] = int((D.datetime(end.year, end.month, end.day, tzinfo=D.UTC) + D.timedelta(days=1)).timestamp() * 1000)
    start = D.datetime.fromtimestamp(b["START_DATETIME"] / 1000, D.UTC)
    b["START_DATETIME"] = int(D.datetime(start.year, start.month, start.day, tzinfo=D.UTC).timestamp() * 1000)
    mod, gen, _, _ = baltimore_runs([json.dumps(doc).encode()])
    assert compare(mod, gen, layer_fields(content)) == {"only_module": [], "only_generic": [], "fields": {}}


def test_baltimore_port_keeps_only_the_safe_fields_in_raw():
    _, gen, _, block = baltimore()
    safe = set(block["safe_fields"])
    for r in gen:
        assert set(r["raw"]["row"]) <= safe
        assert "WAIVER_REASON" not in r["raw"]["row"] and "COMMENT_RELIEF_REQUEST_TYPE" not in r["raw"]["row"]


def mde_runs(texts: list[str], times=(FETCHED, *LATER)):
    meta = json.loads((FIX / "md_mde_overflows_meta.json").read_text())
    dpw, _, _, _ = baltimore()
    permits, _ = M.load_dischargers()
    _, block = runner.load_source("md-mde-overflows")
    mod, gen, stats = [], [], None
    for text, t in zip(texts, times):
        mod, _ = M.build(M.read_rows(text), meta, t, mod, dpw, permits)
        gen, stats = runner.build("md-mde-overflows", block, socrata.parse(block, text.encode()), t, gen, meta,
                                  {"md_baltimore_records": dpw})
    return mod, gen, stats


MDE_TEXT = (FIX / "md_mde_overflows_rows.csv").read_text(encoding="utf-8-sig")


def test_mde_socrata_port_matches_the_module_field_by_field():
    mod, gen, stats = mde_runs([MDE_TEXT])
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


def edited(text: str, edits: dict, drop: set = frozenset()) -> str:
    """The CSV with {row index: {column: value}} applied and the rows in drop left out."""
    rows = list(csv.reader(io.StringIO(text)))
    hdr = rows[0]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(hdr)
    for i, r in enumerate(rows[1:]):
        if i in drop:
            continue
        for col, v in (edits.get(i) or {}).items():
            r[hdr.index(col)] = v
        w.writerow(r)
    return out.getvalue()


def unique_rows():
    rows = M.read_rows(MDE_TEXT)
    keys = [M.base_key(r) for r in rows]
    ok = [i for i, r in enumerate(rows) if keys.count(keys[i]) == 1 and r["start_time"] and r["duration_hour"]
          and "duplicate" not in (r["overflow_address"] + r["receiving_water"] + r["overflow_cause"]).lower()]
    return rows, ok


def test_mde_port_matches_the_module_when_rows_are_corrected_dropped_and_return():
    rows, ok = unique_rows()
    a, b, c = ok[0], ok[5], ok[10]
    t = rows[a]["start_time"]
    corrected = t[:3] + ("10" if t[3:5] != "10" else "20") + t[5:]
    run2 = edited(MDE_TEXT, {a: {"START_TIME": corrected}, b: {"OVERFLOW_ADDRESS": rows[b]["overflow_address"] + " Rear"}},
                  drop={c})
    run3 = edited(MDE_TEXT, {a: {"START_TIME": corrected}, b: {"OVERFLOW_ADDRESS": rows[b]["overflow_address"] + " Rear"}})
    mod, gen, stats = mde_runs([MDE_TEXT, run2, run3])
    d = compare(mod, gen)
    assert d == {"only_module": [], "only_generic": [], "fields": {}}
    by_g = {r["event_id"]: r for r in gen}
    old_a = f"md-mde-overflows:{M.base_key(rows[a])}"
    old_b = f"md-mde-overflows:{M.base_key(rows[b])}"
    # the corrected start and the edited address: the old records point at their corrected rows, as in the module
    assert by_g[old_a]["duplicate_of"] and by_g[old_a]["raw"]["_missing_from_source_since"] == LATER[0]
    assert by_g[old_b]["duplicate_of"] and not stats["history"].get("superseded_by_corrected_row")   # both in run 2
    # the dropped row came back: present again, with its absence on record
    back = by_g[f"md-mde-overflows:{M.base_key(rows[c])}"]
    assert "_missing_from_source_since" not in back["raw"]
    assert back["raw"]["_absences"] == [{"missing_since": LATER[0], "returned_at": LATER[1]}]


def test_mde_port_records_no_false_revision_for_a_redacted_name():
    """The previous run's raw was written redacted; an unchanged row must not read as revised (review P2-2)."""
    rows, ok = unique_rows()
    i = ok[3]
    text = edited(MDE_TEXT, {i: {"OVERFLOW_CAUSE": "Homeowner Placeholder Examplename called it in."}})
    _, gen, stats = mde_runs([text, text, text])
    assert stats["history"].get("revised", 0) == 0
    assert not any(r["raw"].get("_revisions") for r in gen)


SAVED = {"md-baltimore-sso": sorted((ROOT / "data" / "raw" / "md-baltimore-sso").glob("*.json")),
         "md-mde-overflows": sorted((ROOT / "data" / "raw" / "md-mde-overflows").glob("*[0-9]Z.csv"))}


@pytest.mark.skipif(not (SAVED["md-baltimore-sso"] and SAVED["md-mde-overflows"]),
                    reason="no full saved responses in data/raw/ (a pre-switch check, run where they exist)")
def test_whole_saved_tables_match_the_modules():
    bcontent = SAVED["md-baltimore-sso"][-1].read_bytes()
    bpages = json.loads(bcontent)
    feats = [f["attributes"] for p in bpages.get("pages", [bpages]) for f in p.get("features") or []]
    bmod = redact.redact_events(B.build(feats, FETCHED, [])[0])
    _, bblock = runner.load_source("md-baltimore-sso")
    bgen, _ = runner.build("md-baltimore-sso", bblock, arcgis.parse(bblock, bcontent), FETCHED, [])
    assert compare(bmod, bgen, set(feats[0]) if feats else ())["fields"] == {}
    mtext = SAVED["md-mde-overflows"][-1].read_text(encoding="utf-8-sig")
    meta_p = SAVED["md-mde-overflows"][-1].with_suffix(".meta.json")
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    mmod, _ = M.build(M.read_rows(mtext), meta, FETCHED, [], bmod, M.load_dischargers()[0])
    _, mblock = runner.load_source("md-mde-overflows")
    mgen, _ = runner.build("md-mde-overflows", mblock, socrata.parse(mblock, mtext.encode()), FETCHED, [], meta,
                           {"md_baltimore_records": bmod})
    d = compare(mmod, mgen)
    assert d["only_module"] == [] and d["only_generic"] == [] and d["fields"] == {}


# ---------------------------------------------------------------- snapshot: the CSOcast machine

CSOCAST_BLOCK = {
    "platform": "snapshot", "rows_from": "arcgis", "url": "https://example.invalid/FeatureServer/0",
    "time_zone": "America/New_York",
    "safe_fields": ["Name", "Status_Message", "LastPoll", "Latitude", "Longitude", "Waterbody", "Street"],
    "reviewed_fields": {"Name": "the outfall's code (D_02, S_12A), not a person"},
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
    keys = ("started_at", "ended_at", "state", "started_after", "occurred_after", "ended_after")
    assert [(e["outfall"], *(e.get(k) for k in keys)) for e in pe] == [(e["unit"], *(e.get(k) for k in keys)) for e in ge]
    assert len(ge) == 4            # D_02 twice, S_12A first seen as recent, C_FRA through no data
    # one deliberate difference: an event that resumes after "no data" no longer says "no data since" (review P3-4);
    # the spell is kept in its resumed list
    fra = next(e for e in ge if e["unit"] == "C_FRA")
    assert "no_data_since" not in fra and fra["resumed"][0]["no_data_since"] == "2026-11-03T15:00:00-05:00"


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
