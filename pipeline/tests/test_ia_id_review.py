"""Iowa and Idaho: the findings of the independent review of 2026-11-15 (Astra), each on invented data. Every name,
street, number and water here is invented."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingest import id_deq_cyanohab as H

ROOT = Path(__file__).resolve().parents[2]
RULES = json.loads((ROOT / "data" / "rules.json").read_text())
T0, T1, T2 = "2026-11-14T23:00:00Z", "2026-11-15T23:00:00Z", "2026-11-16T23:00:00Z"
UTC = timezone.utc

# ------------------------------------------------------------------ Idaho helpers

ROWS = [("Health Advisory", "Example Lake", "Kootenai", "Laboratory Results", "07/14/2026", "Toxins have exceeded."),
        ("Health Advisory", "Sample Reservoir", "Ada", "Laboratory Results", "07/20/2026", "Toxins have exceeded."),
        ("Watch", "Specimen Pond", "Canyon", "", "11/10/2026", "Always use caution."),
        ("Alert", "Fixture Pond", "Latah", "Visual", "11/01/2026", "Waterbody closed to recreational use.")]
PTS = {"Example Lake": (47.5, -116.7, "Health Advisory"), "Sample Reservoir": (43.6, -116.2, "Health Advisory"),
       "Specimen Pond": (43.5, -116.6, "Health Watch"), "Fixture Pond": (46.7, -117.0, "Health Alert")}


def html(rows):
    head = "".join(f"<th>{h}</th>" for h in H.HEADERS_EXPECTED)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<html><body><table><tr>{head}</tr>{body}</table><footer>DEQ</footer></body></html>"


def layer_doc(names):
    return {"features": [{"attributes": {"LocationDiscription": n, "RiskTier": PTS[n][2], "DisplayOnWebsite": "Yes"},
                          "geometry": {"x": PTS[n][1], "y": PTS[n][0]}} for n in names]}


def run_main(monkeypatch, tmp_path, rows, layer_names, at, saves=None):
    """H.main against invented pages, capturing every save (raw, state, records)."""
    saves = [] if saves is None else saves
    out = {}
    monkeypatch.setattr(H, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(H, "fetch_page", lambda: html(rows))
    if layer_names is None:
        def boom():
            raise H.requests.RequestException("layer down")
        monkeypatch.setattr(H, "fetch_layer", boom)
    else:
        monkeypatch.setattr(H, "fetch_layer", lambda: layer_doc(layer_names))
    monkeypatch.setattr(H, "save_raw", lambda sid, data, ext: saves.append(data.decode()))
    real = H.write_json
    monkeypatch.setattr(H, "write_json", lambda p, d, *a, **k: (saves.append(json.dumps(d)), real(p, d, *a, **k)))

    def we(sid, recs, **kw):
        out.clear()
        out.update(recs=recs, **kw)
        saves.append(json.dumps({"recs": recs, **kw}, default=str))
        return tmp_path / "events.json"
    monkeypatch.setattr(H, "write_events", we)
    code = H.main(["--at", at])
    return code, out, {r["source_record_id"].split(":")[0]: r for r in out["recs"]}


def iv_at(ev, when):
    from build import status as S
    now = datetime.fromisoformat(when)
    return [i for i in S.event_intervals(ev, "ID", now, None, RULES) if i["start"] <= now and (i["end"] is None or i["end"] > now)]


# ------------------------------------------------------------------ P1-1 an incomplete read lifts nothing

def test_p1_1_a_renamed_level_or_a_shortened_table_lifts_nothing_and_fails_health(monkeypatch, tmp_path):
    names = [r[1] for r in ROWS]
    code, out, recs = run_main(monkeypatch, tmp_path, ROWS, names, T0)
    assert code == 0 and out.get("ok", True) is not False
    # one row's level renamed: that water's advisory stays in effect; no lift, health false
    renamed = [("Health Advisory (updated)",) + r[1:] if r[1] == "Example Lake" else r for r in ROWS]
    code, out, recs = run_main(monkeypatch, tmp_path, renamed, names, T1)
    assert recs["example-lake"]["status"] == "advisory_active" and recs["example-lake"]["ended_at"] is None
    assert out["ok"] is False and not any(r["status"] == "advisory_lifted" for r in out["recs"])
    # a shortened table while DHW's map still shows the omitted waters: nothing ends
    code, out, recs = run_main(monkeypatch, tmp_path, ROWS[:1], names, T2)
    assert {k: recs[k]["status"] for k in ("sample-reservoir", "specimen-pond", "fixture-pond")} == {
        "sample-reservoir": "advisory_active", "specimen-pond": "unknown", "fixture-pond": "advisory_active"}
    assert out["ok"] is False and "no longer in DEQ's table" in out["error"]
    # the same shortened table with DHW's map down: still nothing ends
    t3 = "2026-11-17T23:00:00Z"
    code, out, recs = run_main(monkeypatch, tmp_path, ROWS[:1], None, t3)
    assert recs["sample-reservoir"]["status"] == "advisory_active" and out["ok"] is False
    # evidence: a complete read and DHW's map without the water -> it ends at that read, never earlier
    t4 = "2026-11-18T23:00:00Z"
    code, out, recs = run_main(monkeypatch, tmp_path, ROWS[:1], ["Example Lake"], t4)
    sr = recs["sample-reservoir"]
    assert sr["status"] == "advisory_lifted" and sr["ended_at"] == t4 and sr["raw"]["ended_at_precision"] == "poll"
    assert recs["example-lake"]["status"] == "advisory_active" and out.get("ok", True) is not False


def test_p1_1_a_water_listed_again_before_the_evidence_keeps_one_open_record():
    rows = [dict(zip(("level", "water", "county", "data_type", "collection_date", "info"), r)) for r in ROWS]
    lay = H.parse_layer(layer_doc([r[1] for r in ROWS]))
    st = H.update({}, rows, T0, lay)
    st = H.update(st, rows[1:], T1, lay)                 # missing, DHW still shows it: pending
    assert st["last_poll"]["pending"]
    st = H.update(st, rows, T2, lay)
    ex = [r for r in H.records(st) if r["source_record_id"].startswith("example-lake")]
    assert len(ex) == 1 and ex[0]["status"] == "advisory_active" and "first_unlisted_at" not in ex[0]["raw"]
    assert not st["last_poll"]["pending"]


# ------------------------------------------------------------------ P1-2 standing notices stay in effect between reads

def test_p1_2_a_listed_watch_is_never_grey_right_after_the_read(monkeypatch, tmp_path):
    names = [r[1] for r in ROWS]
    _, _, recs = run_main(monkeypatch, tmp_path, ROWS, names, "2026-11-20T23:00:00Z")    # sample 11/10: 72 h long past
    w = recs["specimen-pond"]
    assert w["status"] == "unknown" and w["raw"]["_open_notice_caution_hours"] == 72
    for later in ("2026-11-21T00:30:00+00:00", "2026-11-22T22:00:00+00:00"):          # before the next poll
        ivs = iv_at(w, later)
        assert ivs and ivs[0]["color"] == "yellow" and ivs[0]["rule"] == "sample_caution"


def test_p1_2_an_explicit_recreational_closure_is_the_authoritys_and_red_while_listed(monkeypatch, tmp_path):
    names = [r[1] for r in ROWS]
    _, _, recs = run_main(monkeypatch, tmp_path, ROWS, names, "2026-11-20T23:00:00Z")
    c = recs["fixture-pond"]
    assert c["event_type"] == "hab_advisory" and c["status"] == "advisory_active"
    assert c["raw"]["closure_words"] == "Waterbody closed to recreational use."
    assert "Closed to recreational use" in c["advice_text"] and "Health Alert" in c["raw"]["_closure_level"]
    assert "_agency_label_only" not in c["raw"]
    ivs = iv_at(c, "2026-11-21T06:00:00+00:00")
    assert ivs and ivs[0]["color"] == "red"


@pytest.mark.parametrize("info,closed", [
    ("Waterbody closed to recreational use.", True),
    ("The reservoir remains closed to recreational use until results allow.", True),
    ("Waterbody is not closed to recreational use.", False),
    ("The pond will be closed to recreational use if toxins are found.", False),
    ("The pond was closed to recreational use in August.", False),
    ("Always use caution.", False),
])
def test_p1_2_closure_wording_is_affirmative_only(info, closed):
    assert (H.closure_words(info) is not None) is closed
    assert (H.row_level({"level": "Alert", "info": info}) == "closure") is closed


# ------------------------------------------------------------------ P2-3 a later read never confirms an unread gap

@pytest.mark.parametrize("level,colour", [("Health Advisory", "red"), ("Watch", "yellow")])
def test_p2_3_a_reappearance_after_an_outage_leaves_the_gap_unconfirmed(level, colour):
    row = {"level": level, "water": "Example Lake", "county": "Kootenai", "data_type": "Laboratory Results",
           "collection_date": "06/01/2026", "info": "Avoid contact."}
    lay = H.parse_layer(layer_doc(["Example Lake"]))
    st = H.update({}, [row], "2026-06-02T12:00:00Z", lay)
    st = H.update(st, [row], "2026-08-01T12:00:00Z", lay)
    r = H.records(st)[0]
    assert len(r["raw"]["listed_periods"]) == 2
    assert not iv_at(r, "2026-07-01T12:00:00+00:00") or iv_at(r, "2026-07-01T12:00:00+00:00")[0]["color"] != colour
    assert iv_at(r, "2026-06-03T12:00:00+00:00")[0]["color"] == colour
    assert iv_at(r, "2026-08-02T12:00:00+00:00")[0]["color"] == colour


# ------------------------------------------------------------------ P2-5 part of a lake

def test_p2_5_an_advisory_for_part_of_a_lake_is_a_marker_never_the_whole_lake(monkeypatch, tmp_path):
    from build import status as S
    rows = [("Health Advisory", "Example Lake - North End", "Kootenai", "Laboratory Results", "11/01/2026", "Toxins."),
            ("Health Advisory", "Sample Reservoir", "Ada", "Laboratory Results", "11/01/2026", "Toxins.")]
    PTS["Example Lake - North End"] = (47.54, -116.66, "Health Advisory")
    try:
        _, out, recs = run_main(monkeypatch, tmp_path, rows, ["Example Lake - North End", "Sample Reservoir"],
                                "2026-11-01T23:00:00Z")
    finally:
        PTS.pop("Example Lake - North End")
    part = recs["example-lake-north-end"]
    assert part["raw"]["advisory_extent"] == "part_of_water" and part["waterbody_text"] == "Example Lake"
    assert recs["sample-reservoir"]["raw"].get("advisory_extent") is None
    d = tmp_path / "events"
    d.mkdir()
    (d / f"{H.SOURCE_ID}.json").write_text(json.dumps({"source_id": H.SOURCE_ID, "ok": True, "records": out["recs"],
                                                       "fetched_at": "2026-11-01T23:00:00Z",
                                                       "last_ok_at": "2026-11-01T23:00:00Z"}))

    def lake(slug, name, x, y):
        ring = [[x, y], [x + 0.1, y], [x + 0.1, y + 0.1], [x, y + 0.1], [x, y]]
        return slug, {"slug": slug, "name": name, "kind": "lake", "state": "ID", "area_km2": 5.0,
                      "bbox": [x, y, x + 0.1, y + 0.1], "geometry": {"type": "Polygon", "coordinates": [ring]}}
    waters = dict([lake("example-lake-id", "Example Lake", -116.72, 47.48),
                   lake("sample-reservoir-id", "Sample Reservoir", -116.25, 43.55)])
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    rules = json.loads(json.dumps(RULES))
    rules["live_states"] = sorted(set(rules["live_states"]) | {"ID"})
    rules["rain_likely"] = {**rules["rain_likely"], "enabled": False}
    st, _ = S.build(now=datetime(2026, 11, 2, 12, tzinfo=UTC), write=False, events_dir=d, waters=waters, outfalls=[],
                    registry={}, reaches={}, flows=({}, {}), rules=rules, placement_cache=False)
    assert st["waters"]["sample-reservoir-id"]["status"] == "red"            # control: the whole water's advisory
    ex = st["waters"].get("example-lake-id") or {}
    assert ex.get("status") in (None, "grey"), ex                           # the lake keeps no fill from one part
    pts = [m for m in st.get("advisory_points") or [] if "example-lake-north-end" in json.dumps(m)]
    assert pts, sorted(st)


# ------------------------------------------------------------------ P1-5 privacy on every Idaho save path

def test_p1_5_idaho_rows_are_scrubbed_before_raw_state_records_and_errors(monkeypatch, tmp_path):
    rows = [("Health Advisory", "Example Lake", "Kootenai", "Laboratory Results", "07/14/2026",
             "Contact Example Person at 208-555-0142 or at 123-A Example St."),
            ("Watch", "Specimen Pond", "Canyon", "", "11/10/2026", "Example Person reported the bloom.")]
    saves = []
    run_main(monkeypatch, tmp_path, rows, ["Example Lake", "Specimen Pond"], T0, saves)
    # carried state saved before the scrub existed is scrubbed again on the next run
    st = json.loads((tmp_path / "state.json").read_text())
    for ep in st["episodes"].values():
        ep["row"]["info"] = "Call Example Person at 208-555-0142."
    (tmp_path / "state.json").write_text(json.dumps(st))
    run_main(monkeypatch, tmp_path, rows, ["Example Lake", "Specimen Pond"], T1, saves)
    # a failed read whose error carries the page's header text
    monkeypatch.setattr(H, "fetch_page", lambda: "<table><tr><th>Example Person 208-555-0142</th></tr></table>")
    assert H.main(["--at", T2]) == 1
    assert len(saves) >= 5
    for s in saves:
        for bad in ("Example Person", "555-0142", "123-A"):
            assert bad not in s, (bad, s[:300])


# ------------------------------------------------------------------ shared module: other states unchanged

def _other_state_records():
    from common import event
    out = []
    for sid in ("de-dnrec-recreational-water", "sc-des-hab", "nv-state-parks-hab", "pr-drna-beach-notices",
                "ne-dwee-beachwatch", "ar-deq-hab-advisories", "hi-doh-cwb-events-api"):
        for st, label in (("advisory_active", False), ("advisory_lifted", False), ("unknown", True)):
            raw = {"_last_seen_in_source": "2026-08-01T12:00:00Z",
                   "listed_periods": [{"from": "2026-06-02T12:00:00Z", "to": "2026-06-05T12:00:00Z"},
                                      {"from": "2026-08-01T12:00:00Z", "to": "2026-08-01T12:00:00Z"}]}
            if label:
                raw.update(_agency_label_only="x", _caution_to_notice_end=True, _open_notice_caution_hours=72)
            out.append(event(source_id=sid, source_record_id=f"{sid}-{st}", event_type="hab_advisory", status=st,
                             started_at="2026-06-02T12:00:00Z", time_precision="poll", sampled_at="2026-06-01",
                             ended_at="2026-08-03T12:00:00Z" if st == "advisory_lifted" else None,
                             raw=dict(raw, ended_at_precision="poll") if st == "advisory_lifted" else raw,
                             lat=40.0, lon=-90.0, waterbody_text="Example Lake", authority="x", source_url="u"))
    return out


def test_shared_status_change_leaves_other_states_intervals_identical_to_state_ia_id():
    """The intervals of invented records of every other poll-period source, hashed at state/ia-id (6110a7f) before
    Idaho joined POLL_END_HORIZON_SOURCES: byte for byte the same. Pinned again on 2026-11-15 when the rules file's
    prose took the "we" voice: against the earlier hash (d0f223a7...) only four `rationale` strings differ, the
    sample caution's ("the site shows its own caution" is now "we show our own caution"); no time, status or rule."""
    from build import status as S
    now = datetime(2026, 8, 10, tzinfo=UTC)
    ivs = [S.event_intervals(r, None, now, None, RULES) for r in _other_state_records()]
    got = hashlib.sha256(json.dumps(ivs, default=str, sort_keys=True).encode()).hexdigest()
    assert got == "5ef92850eaf4ace0473c8db38de7952879ec56cb78df6ffea5e74a5a01b0483b"


# ------------------------------------------------------------------ Iowa: Waterloo

from ingest import ia_waterloo_sso as W  # noqa: E402

PARA_A = ("October 2, 2026 at 5:52 AM, WMSD began Sanitary Sewer bypass pumping at a Sanitary Sewer Overflow located at "
          "Example Ave and Sample St. The estimated volume of sewer discharged is 1,000 gallons; the duration of the "
          "event was 2 hours. Bypass pumping was the result of a wet weather event.")
PARA_B = PARA_A.replace("Example Ave and Sample St", "the Specimen Road lift station")
PARA_N = ("October 3, 2026 at 6:03 AM, WMSD was notified of a Sanitary Sewer Overflow located at Example Ave and "
          "Sample St. The estimated volume of sewer discharged is 5,000 gallons; the duration of the event was 4 hours "
          "and 2 minutes. The overflow was the result of a wet weather event.")


def test_p1_4_waterloo_notices_at_one_minute_on_separate_runs_keep_their_own_records():
    a, _ = W.build([PARA_A], T0, [])
    b, _ = W.build([PARA_B], T1, a)
    ids_b = {r["source_record_id"]: r for r in b}
    assert len(ids_b) == 2, sorted(ids_b)
    a_id = a[0]["source_record_id"]
    assert a_id in ids_b and ids_b[a_id]["raw"]["location"] == a[0]["raw"]["location"]   # A never overwritten
    both, _ = W.build([PARA_A, PARA_B], T2, b)
    assert {r["source_record_id"] for r in both} == set(ids_b)                       # same two ids, nothing new
    again, _ = W.build([PARA_B, PARA_A], T2, both)
    assert {r["source_record_id"] for r in again} == set(ids_b)
    # a record saved before with the bare minute keeps it when its minute and location match
    legacy = [dict(a[0], source_record_id="2026-10-02T0552", event_id="ia-waterloo-sso-notices:2026-10-02T0552")]
    kept, _ = W.build([PARA_A, PARA_B], T2, legacy)
    assert "2026-10-02T0552" in {r["source_record_id"] for r in kept} and len(kept) == 2


def test_p2_2_a_notification_time_is_the_reported_time_and_makes_no_start_or_end():
    recs, _ = W.build([PARA_N], T0, [])
    r = recs[0]
    assert r["started_at"] is None and r["reported_at"] == "2026-10-03T06:03:00-05:00"
    assert r["ended_at"] is None and r["status"] == "unknown"
    assert r["raw"]["duration_minutes_as_stated"] == 242 and "start is not stated" in r["raw"]["start_basis"]
    # an explicit stop after the notification is still the end
    stop = PARA_N.replace("the duration of the event was 4 hours and 2 minutes", "the duration is unknown") + \
        " The overflow was stopped at 9:30AM."
    r = W.build([stop], T0, [])[0][0]
    assert r["ended_at"] == "2026-10-03T09:30:00-05:00" and r["raw"]["end_basis"].startswith("the time the notice")
    # a stop time earlier than the notification, with no day: no end is made
    early = stop.replace("9:30AM", "5:30AM")
    r = W.build([early], T0, [])[0][0]
    assert r["ended_at"] is None and "day is not stated" in r["raw"]["end_note"]
    # a start the notice gives ("WMSD began") still ends at start plus duration
    r = W.build([PARA_A], T0, [])[0][0]
    assert r["started_at"] == "2026-10-02T05:52:00-05:00" and r["ended_at"] == "2026-10-02T07:52:00-05:00"


def test_p2_2_a_carried_notified_record_is_corrected_on_the_next_run():
    old = {"source_record_id": "2026-10-03T0603", "event_id": "ia-waterloo-sso-notices:2026-10-03T0603",
           "source_id": W.SOURCE_ID, "status": "ended", "started_at": "2026-10-03T06:03:00-05:00",
           "ended_at": "2026-10-03T10:05:00-05:00", "reported_at": None, "event_type": "sso",
           "raw": {"notice": PARA_N, "location": "Example Ave and Sample St", "ended_at_precision": "minute",
                   "end_basis": "the notice's start plus the duration it states",
                   "start_basis": "the time the City was notified of the overflow: it began at or before this time"}}
    r = W.build([], T0, [old])[0][0]
    assert r["started_at"] is None and r["reported_at"] == "2026-10-03T06:03:00-05:00"
    assert r["ended_at"] is None and r["status"] == "unknown" and r["raw"]["_placement"] == "own_place_only"


# ------------------------------------------------------------------ Iowa placement in a full status build

from ingest import ia_dnr_focomp as F  # noqa: E402
from ingest import ia_dnr_news as N  # noqa: E402

FAC = {"st_fac_id": "399999001", "name": "Example City Of Stp", "city": "Exampleton", "county": "Black Hawk"}


def _ia_status(tmp_path, records):
    from build import status as S
    d = tmp_path / "ev"
    d.mkdir()
    by_src = {}
    for r in records:
        by_src.setdefault(r["source_id"], []).append(r)
    for sid, rs in by_src.items():
        (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "ok": True, "records": rs,
                                                   "fetched_at": "2026-11-01T23:00:00Z",
                                                   "last_ok_at": "2026-11-01T23:00:00Z"}))

    def water(slug, name, kind, x, y):
        if kind == "river":
            g = {"type": "LineString", "coordinates": [[x, y], [x + 0.3, y + 0.01]]}
        else:
            g = {"type": "Polygon", "coordinates": [[[x, y], [x + 0.05, y], [x + 0.05, y + 0.05], [x, y + 0.05], [x, y]]]}
        return slug, {"slug": slug, "name": name, "kind": kind, "state": "IA", "area_km2": 2.0 if kind == "lake" else None,
                      "bbox": [x, y, x + 0.3, y + 0.05], "geometry": g}
    waters = dict([water("example-river-ia", "Example River", "river", -92.4, 42.5),
                   water("specimen-lake-ia", "Specimen Lake", "lake", -93.6, 41.6),
                   water("sample-creek-ia", "Sample Creek", "river", -96.4, 42.4),
                   water("fixture-river-ia", "Fixture River", "river", -96.5, 42.45)])
    # the plant's receiving water, resolved in the registry: Waterloo's permit and the FOCOMP permit discharge there
    outfalls = [{"npdes_permit": p, "outfall": "001", "water_slug": "example-river-ia", "water_match": "name",
                 "lat": 42.5, "lon": -92.3, "state": "IA", "receiving_water": "Example River"}
                for p in (W.PERMIT, "IA0099999")]
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    rules = json.loads(json.dumps(RULES))
    rules["live_states"] = sorted(set(rules["live_states"]) | {"IA"})
    rules["rain_likely"] = {**rules["rain_likely"], "enabled": False}
    st, _ = S.build(now=datetime(2026, 11, 2, 12, tzinfo=UTC), write=False, events_dir=d, waters=waters,
                    outfalls=outfalls, registry={}, reaches={}, flows=({}, {}), rules=rules, placement_cache=False,
                    discharger_waters={"ia-waterloo": ["example-river-ia"], "ia-exampleton": ["example-river-ia"]})
    return st


def test_p2_4_an_iowa_notice_with_no_water_and_no_point_never_takes_the_plants_water(tmp_path):
    para = PARA_A.replace("October 2, 2026", "November 1, 2026")
    wl = W.build([para], "2026-11-01T23:00:00Z", [])[0][0]
    rep = F.parse_report((Path(__file__).resolve().parent / "fixtures" / "ia" / "focomp-report-900002.html").read_text())
    nowhere = F.make_record({**rep, "receiving_stream": "", "lat": None, "lon": None, "incident_start": "11/01/2026",
                             "incident_start_time": "08:00", "incident_end": "", "incident_end_time": ""},
                            FAC, {"label": "x"}, ("IA0099999", "basis"), "2026-11-01T23:00:00Z",
                            ops={"IA0099999": ("ia-exampleton", "City of Exampleton")})
    on_lake = F.make_record({**rep, "report_id": "900099", "receiving_stream": "", "lat": 41.625, "lon": -93.575,
                             "incident_start": "11/01/2026", "incident_start_time": "08:00", "incident_end": "",
                             "incident_end_time": ""},
                            FAC, {"label": "x"}, ("IA0099999", "basis"), "2026-11-01T23:00:00Z",
                            ops={"IA0099999": ("ia-exampleton", "City of Exampleton")})
    assert nowhere["waterbody_text"] is None and nowhere["lat"] is None
    st = _ia_status(tmp_path, [wl, nowhere, on_lake])
    pl = st["placements"]
    for r in (wl, nowhere):
        p = pl[r["event_id"]]
        assert p["water_slugs"] == [] and "never on its permit" in p["unplaced_reason"], p
    assert pl[on_lake["event_id"]]["water_slugs"] == ["specimen-lake-ia"]              # a genuine point still places
    assert st["waters"]["example-river-ia"]["events"] == []


def test_p2_1_a_release_naming_two_waters_places_one_report_on_both(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "_OPERATORS", {})
    body = ("The Department of Natural Resources was notified on November 1 that wastewater from the Example lift "
            "station of the City of Exampleton discharged into Sample Creek, which flows to the Fixture River. An "
            "estimated 50,000 gallons was released. Downstream recreational users should avoid the area.")
    art = {"title": "Wastewater discharge reaches Fixture River", "date": "2026-11-01", "body": body}
    recs = N.records_for(art, "https://www.iowadnr.gov/news-release/2026-11-01/example", "2026-11-01T23:00:00Z")
    assert len(recs) == 1
    r = recs[0]
    assert r["waterbody_text"] == "Sample Creek" and r["raw"]["_also_named_waters"] == ["Fixture River"]
    st = _ia_status(tmp_path, recs)
    p = st["placements"][r["event_id"]]
    assert sorted(p["water_slugs"]) == ["fixture-river-ia", "sample-creek-ia"], p
    assert st["counts"]["events"] == 1                                                 # one report, counted once
    assert r["event_id"] in st["waters"]["fixture-river-ia"]["events"]
    assert r["event_id"] in st["waters"]["sample-creek-ia"]["events"]


def test_iowa_placement_values_are_written_only_by_iowa():
    """build/status.py own_place_only and _also_named_waters change only records carrying them; no other state's
    ingester or source writes them, so every other state's placements are unchanged."""
    hits = [p for d in ("pipeline/ingest", "data/sources") for p in (ROOT / d).rglob("*")
            if p.is_file() and p.suffix in (".py", ".yaml", ".json")
            and ("own_place_only" in p.read_text(errors="ignore") or "_also_named_waters" in p.read_text(errors="ignore"))]
    # Puerto Rico's go-live audit (2026-11-16 P1-2): EPA's overflow module writes own_place_only for PR records only
    # (OWN_PLACE_MODE_STATES, pinned to {"PR"} in tests/test_pr_audit_fixes.py)
    assert {p.name for p in hits} == {"ia_waterloo_sso.py", "ia_dnr_focomp.py", "ia_dnr_news.py",
                                      "echo_sewer_overflow_events.py"}, hits
    from ingest import echo_sewer_overflow_events as E
    assert E.OWN_PLACE_MODE_STATES == {"PR"}


# ------------------------------------------------------------------ P1-3 a partial FOCOMP detail read keeps good fields

FFIX = Path(__file__).resolve().parent / "fixtures" / "ia"


def _focomp_run(tmp_path, monkeypatch, pages, at, saves=None):
    """F.main on the invented facility page and these report pages {rid: html}; every save captured."""
    saves = [] if saves is None else saves
    fl = tmp_path / "facilities.json"
    fl.write_text(json.dumps({"facilities": [dict(FAC, county="Polk")]}))
    monkeypatch.setattr(F, "FACILITIES", fl)
    monkeypatch.setattr(F, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(F, "iowa_plants", lambda: [])
    monkeypatch.setattr(F, "_OPERATORS", {})
    monkeypatch.setattr(F, "PAUSE_S", 0)
    fac_page = (FFIX / "focomp-facility.html").read_text()

    def get(url):
        if "FacilityDetail" in url:
            return fac_page
        rid = url.split("incomingReportID=")[1]
        if rid not in pages:
            raise F.requests.RequestException("not in this test")
        return pages[rid]
    monkeypatch.setattr(F, "get", get)
    monkeypatch.setattr(F, "save_raw", lambda sid, data, ext: saves.append(data.decode()))
    real = F.write_json
    monkeypatch.setattr(F, "write_json", lambda p, d, *a, **k: (saves.append(json.dumps(d)), real(p, d, *a, **k)))
    out = {}

    def we(sid, recs, **kw):
        out.clear()
        out.update(recs=recs, **kw)
        saves.append(json.dumps({"recs": recs, **kw}, default=str))
        return tmp_path / "events.json"
    monkeypatch.setattr(F, "write_events", we)
    monkeypatch.setattr(F, "BACKFILL_FROM", "2000-01-01")
    rc = F.main(["--at", at, "--facility-budget", "1", "--report-budget", "10"])
    return rc, out, {r["source_record_id"]: r for r in out.get("recs") or []}


@pytest.mark.parametrize("damage", [
    lambda p: p.replace('name="IncidentStart"', 'name="IncidentStartDate"'),
    lambda p: p.replace('name="DateReceived"', 'name="ReceivedOn"').replace('name="IncidentEndTime"', 'name="EndT"'),
    lambda p: p.replace('name="IncidentStart" value="6/15/2026"', 'name="IncidentStart" value=""'),
    lambda p: p.replace('name="IncidentStart" value="6/15/2026"', 'name="IncidentStart" value="15 June"'),
])
def test_p1_3_a_partial_or_malformed_detail_read_never_replaces_good_dates(tmp_path, monkeypatch, damage):
    good = {rid: (FFIX / f"focomp-report-{rid}.html").read_text() for rid in ("900001", "900002", "900004")}
    good["100001"] = good["900004"].replace('value="900004"', 'value="100001"')       # the page's fifth report
    rc, out, recs = _focomp_run(tmp_path, monkeypatch, good, "2026-09-26T12:00:00Z")
    assert rc == 0 and recs["900002"]["started_at"] == "2026-06-15T14:10:00-05:00"
    st = json.loads((tmp_path / "state.json").read_text())
    for r in st["reports"].values():                 # make every report due a re-read
        r["closed"] = "Open"
    (tmp_path / "state.json").write_text(json.dumps(st))
    bad = dict(good, **{"900002": damage(good["900002"])})
    rc, out, recs = _focomp_run(tmp_path, monkeypatch, bad, "2026-09-28T12:00:00Z")
    assert rc == 0 and out["ok"] is False and any("900002" in e for e in out["meta"]["unread"])
    assert recs["900002"]["started_at"] == "2026-06-15T14:10:00-05:00"          # the good read kept
    assert recs["900001"]["raw"]["_read_at"] == "2026-09-28T12:00:00Z"           # the readable report updated
    st = json.loads((tmp_path / "state.json").read_text())
    assert st["reports"]["900002"]["retry"] is True
    assert F.reports_to_read(st, "2026-09-28T13:00:00Z", 1) == [(FAC["st_fac_id"], "900002")]   # first next run
    # a later good read clears it
    rc, out, recs = _focomp_run(tmp_path, monkeypatch, good, "2026-09-29T12:00:00Z")
    st = json.loads((tmp_path / "state.json").read_text())
    assert "retry" not in st["reports"]["900002"] and out.get("ok", True) is not False


# ------------------------------------------------------------------ P1-5 Iowa privacy before the first save

def test_p1_5_focomp_a_home_is_found_before_the_text_is_withheld_and_never_saved(tmp_path, monkeypatch):
    page = (FFIX / "focomp-report-900002.html").read_text()
    import re as _re
    page = _re.sub(r'(<textarea[^>]*name="ReportDetails"[^>]*>).*?(</textarea>)',
                   r"\1Overflow at the home of Example Person on Sample Ln.\2", page, flags=_re.S)
    page = _re.sub(r'name="Latitude"[^>]*value="[^"]*"', 'name="Latitude" value="41.51234"', page)
    page = _re.sub(r'name="Longitude"[^>]*value="[^"]*"', 'name="Longitude" value="-93.49876"', page)
    rep = F.parse_report(page)
    assert rep["private_home"] is True and rep["lat"] is None and rep["details"].startswith("[withheld")
    saves = []
    rc, out, recs = _focomp_run(tmp_path, monkeypatch, {"900002": page}, "2026-09-26T12:00:00Z", saves)
    r = recs["900002"]
    assert r["lat"] is None and r["raw"]["incident_address"] is None and "private home" in r["raw"]["privacy_cut"]
    for s in saves:
        for bad in ("Example Person", "41.512", "-93.498", "41.51234"):
            assert bad not in s, (bad, s[:200])
    # carried state saved before the fix: a withheld place description loses its point
    st = {"reports": {"1": {"fac": "399999001", "fields": {"location": "[withheld: the text may name a person]",
                                                          "lat": 41.5, "lon": -93.5, "address": "Sample Ln"}}}}
    f = F.scrub_state(st)["reports"]["1"]["fields"]
    assert f["lat"] is None and f["address"] is None and f["private_home"] is True


def test_p1_5_news_titles_are_scrubbed_on_every_save(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(N, "_OPERATORS", {})
    title = "Wastewater bypass reported by Example Person, call 515-555-0142"
    rss = (f"<rss><channel><item><title>{title}</title><link>https://www.iowadnr.gov/news-release/2026-11-01/x</link>"
           "<pubDate>Sun, 01 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>")
    page = ("<html><body><h1>" + title + "</h1>\n<p>Sunday, November 1, 2026</p>\n<p>News Release</p>\n"
            "<p>The City of Exampleton reported that its lift station discharged wastewater into Sample Creek.</p>"
            "</body></html>")
    saves = []
    monkeypatch.setattr(N, "get", lambda url: rss if url == N.RSS else page)
    monkeypatch.setattr(N, "save_raw", lambda sid, data, ext: saves.append(data.decode()))
    real = N.write_json
    monkeypatch.setattr(N, "write_json", lambda p, d, *a, **k: (saves.append(json.dumps(d)), real(p, d, *a, **k)))
    out = {}
    monkeypatch.setattr(N, "write_events", lambda sid, recs, **kw: (out.update(recs=recs, **kw),
                                                                     saves.append(json.dumps({"r": recs, **kw})))[0])
    assert N.main(["--at", T0]) == 0
    # carried state from before the fix is scrubbed again
    st = json.loads((tmp_path / "state.json").read_text())
    for a in st["articles"].values():
        a["title"] = title
        a["article"]["title"] = title
    (tmp_path / "state.json").write_text(json.dumps(st))
    assert N.main(["--at", T1]) == 0
    assert len(saves) >= 4
    for s in saves:
        for bad in ("Example Person", "555-0142"):
            assert bad not in s, (bad, s[:300])
