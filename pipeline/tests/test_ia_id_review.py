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
    Idaho joined POLL_END_HORIZON_SOURCES: byte for byte the same."""
    from build import status as S
    now = datetime(2026, 8, 10, tzinfo=UTC)
    ivs = [S.event_intervals(r, None, now, None, RULES) for r in _other_state_records()]
    got = hashlib.sha256(json.dumps(ivs, default=str, sort_keys=True).encode()).hexdigest()
    assert got == "d0f223a7f61641488bc06ade7dd1bf0fa2c229cb53e51f7faa06f31f8fc57d32"
