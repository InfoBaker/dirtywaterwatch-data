"""EPA BEACON 2.0 beach actions (ingest/fed_beacon_beach_actions.py) and the EPA beach registry
(scripts/build_epa_beach_registry.py). Fixtures: tests/fixtures/beacon/, rows trimmed from BEACON's own CSV exports of
2026-11-21 (Beach Actions and its detailed report for 2025 and 2026; Beach Attributes, Swim Season and Monitoring
Frequency, WQS Criteria and Possible Pollution Sources for 2025 and 2026), and three real state records of the
2026-11-14 export (NJDEP's two at 25th St Bay Front, Erie County's Beach 11). No network: the session is a fake."""
from __future__ import annotations

import copy
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from build import beach_reason as BR
from build import status as S
from ingest import fed_beacon_beach_actions as B

FIX = Path(__file__).resolve().parent / "fixtures" / "beacon"
ROOT = Path(__file__).resolve().parents[2]
READ = "2026-11-21T05:40:00Z"
NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)
RULES = S.load_rules()


def registry_module():
    spec = importlib.util.spec_from_file_location("build_epa_beach_registry", ROOT / "scripts" / "build_epa_beach_registry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def registry(tmp_path):
    R = registry_module()
    doc = R.build(R.read_reports([2025, 2026], FIX), READ)
    p = tmp_path / "beaches-epa.json"
    p.write_text(json.dumps(doc))
    return p


def events_dir(tmp_path, with_state=True):
    d = tmp_path / "events"
    d.mkdir(exist_ok=True)
    if with_state:
        for sid, f in json.loads((FIX / "state-records.json").read_text()).items():
            (d / f"{sid}.json").write_text(json.dumps(f))
    return d


def run_saved(tmp_path, registry, fetched_at=READ, argv=(), now=NOW, **kw):
    ev = events_dir(tmp_path, kw.pop("with_state", True))
    code = B.run(["--from-dir", str(FIX), "--fetched-at", fetched_at, *argv], now=now, events_dir=ev,
                 state_file=tmp_path / "state.json", registry_file=registry, **kw)
    doc = json.loads((ev / f"{B.SOURCE_ID}.json").read_text())
    return code, doc, {r["source_record_id"]: r for r in doc["records"]}


# ---------------------------------------------------------------- the session

class FakeResponse:
    def __init__(self, text="", ctype="text/html", url=""):
        self.text, self.content, self.url = text, text.encode(), url
        self.headers = {"Content-Type": ctype}

    def raise_for_status(self):
        return None


class FakeSession:
    """BEACON's report builder as the replay sees it: the page with its session id, the posts, the CSV exports."""

    def __init__(self, main=None, detail=None):
        self.calls = []
        self.main = main if main is not None else (FIX / "beach-actions_2025.csv").read_text()
        self.detail = detail if detail is not None else (FIX / "beach-actions-detail_2025.csv").read_text()

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, dict(params or {})))
        if url.endswith("/report-page-content"):
            return FakeResponse('<script>apex.env = {APP_SESSION: "70112233445566"};</script>')
        if (params or {}).get("request") == "CSV":
            return FakeResponse(self.detail if url.endswith("-detail") else self.main, "text/csv")
        return FakeResponse("<html>report</html>")

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(("POST", url, list(data or []), dict(headers or {})))
        return FakeResponse("{}", "application/json")


def test_the_session_replay_sets_the_national_region_and_the_year_then_exports_both_reports():
    sess, sleeps = FakeSession(), []
    main, detail = B.pull_year(sess, 2025, sleep=sleeps.append)
    assert main.startswith("Jurisdiction,Year,Beach ID") and detail.startswith("Jurisdiction,County,Year")
    kinds = [c[0] for c in sess.calls]
    assert kinds == ["GET", "POST", "POST", "POST", "POST", "GET", "GET", "GET", "GET"]     # nine requests a year
    assert sleeps == [1.0] * 8                                                          # a second between them
    posts = [dict((k, v) for k, v in c[2] if k != "p_arg_names" and k != "p_arg_values") for c in sess.calls
             if c[0] == "POST"]
    assert [p["p_request"] for p in posts] == ["APPLICATION_PROCESS=clearLocationLists",
                                               "APPLICATION_PROCESS=setAdditionalSearchVariables",
                                               "APPLICATION_PROCESS=buildFilters",
                                               "APPLICATION_PROCESS=setAdditionalSearchVariables"]
    assert all(p["p_instance"] == "70112233445566" and p["p_flow_id"] == "132" for p in posts)
    args = [list(zip([v for k, v in c[2] if k == "p_arg_names"], [v for k, v in c[2] if k == "p_arg_values"]))
            for c in sess.calls if c[0] == "POST"]
    assert ("UI_EPA_REGION", "11") in args[1] and ("F101_CALENDAR_YEAR", "2025") in args[3]
    assert sess.calls[1][1].endswith("wwv_flow.show?p_context=beacon2/report-page-content/70112233445566")
    gets = [(c[1].rsplit("/", 1)[-1], c[2]) for c in sess.calls[5:]]
    assert gets == [("beach-actions", {"clear": "Y", "session": "70112233445566"}),
                    ("beach-actions", {"session": "70112233445566", "request": "CSV"}),
                    ("beach-actions-detail", {"clear": "Y", "session": "70112233445566"}),
                    ("beach-actions-detail", {"session": "70112233445566", "request": "CSV"})]
    assert B.new_session().headers["User-Agent"].startswith("DirtyWaterWatch/")       # the pipeline's named client


def test_a_changed_report_is_a_failed_pull_that_keeps_the_records_and_names_only_the_class(tmp_path, registry):
    code, doc, _ = run_saved(tmp_path, registry)
    assert code == 0 and doc["ok"] and doc["count"] == 21
    bad = FakeSession(main="Jurisdiction,Year,Something Else\nAL,2025,x\n")
    ev = tmp_path / "events"
    code = B.run(["--force"], sess=bad, sleep=lambda s: None, now=NOW, events_dir=ev,
                 state_file=tmp_path / "state.json", registry_file=registry)
    after = json.loads((ev / f"{B.SOURCE_ID}.json").read_text())
    assert code == 1 and after["ok"] is False and after["count"] == 21      # the previous records kept
    assert after["error"] == "BEACON pull failed (2025: PullError)"           # a fixed reason and the class, no text


# ---------------------------------------------------------------- records

def test_dates_are_the_beachs_local_time_and_midnight_is_a_date_for_the_start_and_the_end_apart(tmp_path, registry):
    _, _, recs = run_saved(tmp_path, registry)
    al = recs["710924"]                         # 10-SEP-2025 12:00AM to 12-SEP-2025 12:00AM, Alabama
    assert (al["started_at"], al["ended_at"]) == ("2025-09-10T00:00:00-05:00", "2025-09-12T00:00:00-05:00")
    assert al["time_precision"] == "day" and al["raw"]["ended_at_precision"] == "day"
    assert al["raw"]["time_zone"] == "America/Chicago"
    pa = recs["728218"]                         # 15-JUL-2025 07:36AM to 02-SEP-2025 12:00AM, Erie County
    assert pa["started_at"] == "2025-07-15T07:36:00-04:00" and pa["time_precision"] == "minute"
    assert pa["ended_at"] == "2025-09-02T00:00:00-04:00" and pa["raw"]["ended_at_precision"] == "day"
    ny = recs["726528"]                         # 20-AUG-2025 05:25PM to 23-AUG-2025 12:00PM: noon is a time
    assert ny["ended_at"] == "2025-08-23T12:00:00-04:00" and ny["raw"]["ended_at_precision"] == "minute"
    assert B.when("31-DEC-2025 12:00AM", S.ZoneInfo("America/Los_Angeles")) == ("2025-12-31T00:00:00-08:00", "day")
    assert B.when("not a date", S.ZoneInfo("America/New_York")) == (None, None)
    for r in recs.values():                     # BEACON gives no publication time; our first read is kept apart
        assert r["published_at"] is None and r["reported_at"] is None and r["source_updated_at"] is None
        assert r["fetched_at"] == READ and r["raw"]["_first_seen_at"] == READ
        assert r["status"] == "advisory_lifted"
    assert al["event_type"] == "beach_advisory" and pa["event_type"] == "beach_closure"
    assert al["source_url"].endswith("beach-profile-details?beach_id=AL656449")
    assert al["authority"] == "Alabama Department of Environmental Management, as reported to U.S. EPA (BEACON 2.0)"


def test_a_record_keeps_the_codes_the_words_and_the_states_comment_and_its_point_from_the_registry(tmp_path, registry):
    _, _, recs = run_saved(tmp_path, registry)
    ny = recs["726528"]
    assert ny["raw"]["reasons"] == ["OTHER"] and ny["raw"]["indicators"] == ["PREEMPT"]
    assert ny["raw"]["possible_sources"] == ["STORM"] and ny["raw"]["reason_words"] == ["another reason"]
    assert ny["raw"]["reason_comments"] == ["Hurricane rip currents"]
    assert ny["raw"]["possible_source_comments"] == ["Hurricane Rip Currents"]
    assert ny["raw"]["station_ids"] == ["21NYBCH|NY989199-01"] and ny["raw"]["tier"] == "3"
    assert ny["raw"]["beach"]["owner"] == "Private"
    assert (ny["lat"], ny["lon"], ny["coord_source"]) == (41.280838, -71.943583, "source")
    assert ny["raw"]["point_basis"] == "the beach's start point in EPA's beach attributes (BEACON Beach Attributes, 2026)"
    assert ny["waterbody_text"] == "Atlantic Ocean" and ny["water_slugs"] == [] and ny["water_match"] == "none"
    # a row that lists several action ids (one window at several stations): one record, every id kept
    pa = recs["728218"]
    assert pa["raw"]["station_ids"] == ["21PABCH|31", "21PABCH|32", "21PABCH|33"]
    # two rows that list the same ids under two action types: two records, told apart by the type
    ca = [k for k in recs if k.startswith("721526")]
    assert sorted(ca) == ["721526-contamination-advisory", "721526-rain-advisory"]


def test_a_beach_with_no_registry_row_stays_a_record_unplaced_and_counted(tmp_path, registry):
    doc = json.loads(registry.read_text())
    doc["beaches"] = [b for b in doc["beaches"] if b["beach_id"] != "IL928218"]
    registry.write_text(json.dumps(doc))
    _, out, recs = run_saved(tmp_path, registry)
    il = recs["729819"]
    assert il["lat"] is None and il["coord_source"] is None and il["waterbody_text"] == "Lake Michigan"
    assert out["meta"]["no_point"] == {"rows": 1, "by_state": {"IL": 1}}
    assert out["meta"]["no_registry_row"]["by_state"] == {"IL": 1}


def test_the_territories_and_the_tribal_programs_are_counted_not_written(tmp_path, registry):
    _, doc, recs = run_saved(tmp_path, registry)
    assert {r["raw"]["jurisdiction"] for r in recs.values()} <= B.IN_SCOPE
    assert doc["meta"]["out_of_scope"] == {"rows": 3, "by_jurisdiction": {"BR": 1, "GU": 2}}
    assert doc["meta"]["by_state_year"]["LA"] == {"2026": {"actions": 1}}
    assert doc["meta"]["newest_action_by_state"]["LA"]["start"] == "2026-10-15T07:00:00-05:00"


# ---------------------------------------------------------------- copies of state records

def test_a_copy_is_linked_by_epa_beach_id_and_another_by_the_beach_point(tmp_path, registry):
    _, doc, recs = run_saved(tmp_path, registry)
    nj_c, nj_a = recs["723982"], recs["723981"]
    assert nj_c["duplicate_of"] == "nj-beaches:OC0142:beach_closure:2025-08-19"
    assert nj_a["duplicate_of"] == "nj-beaches:OC0142:beach_advisory:2025-08-18"
    assert nj_c["raw"]["copy_of"] == {"event_id": "nj-beaches:OC0142:beach_closure:2025-08-19",
                                      "source_id": "nj-beaches", "by": "epa_beach_id", "days_apart": 0}
    pa = recs["728218"]                 # Erie County's sheet keeps no EPA id field: its point, 100 m from Beach 11
    assert pa["duplicate_of"] == "pa-erie-beaches:PA102094-20250715"
    assert pa["raw"]["copy_of"]["by"] == "point" and pa["raw"]["copy_of"]["metres"] <= B.LINK_M
    assert "100 m from the beach's line" in pa["raw"]["_duplicate_basis"]
    assert doc["meta"]["links"]["linked"] == 3 and doc["meta"]["links"]["by_epa_beach_id"] == 2
    assert doc["meta"]["by_state_year"]["NJ"]["2025"] == {"actions": 2, "linked_by_epa_beach_id": 2}
    # each state record takes one copy; every other record stands on its own
    assert sum(1 for r in recs.values() if r["duplicate_of"]) == 3


def test_no_link_a_day_and_a_half_apart_nor_to_a_file_withheld_from_the_public_export(tmp_path, registry):
    ev = events_dir(tmp_path)
    nj = json.loads((ev / "nj-beaches.json").read_text())
    for r in nj["records"]:
        r["started_at"] = "2025-08-21" if r["event_type"] == "beach_closure" else r["started_at"]
    (ev / "nj-beaches.json").write_text(json.dumps(nj))
    pa = json.loads((ev / "pa-erie-beaches.json").read_text())
    pa["meta"]["distribution_discouraged"] = True
    (ev / "pa-erie-beaches.json").write_text(json.dumps(pa))
    B.run(["--from-dir", str(FIX), "--fetched-at", READ], now=NOW, events_dir=ev, state_file=tmp_path / "s.json",
          registry_file=registry)
    recs = {r["source_record_id"]: r for r in json.loads((ev / f"{B.SOURCE_ID}.json").read_text())["records"]}
    assert recs["723982"]["duplicate_of"] is None          # two days apart
    assert recs["723981"]["duplicate_of"] is not None      # the advisory still is the same day
    assert recs["728218"]["duplicate_of"] is None          # a withheld file is never the record shown


def test_a_point_link_is_not_made_when_the_two_name_different_waters(tmp_path, registry):
    ev = events_dir(tmp_path)
    pa = json.loads((ev / "pa-erie-beaches.json").read_text())
    pa["records"][0]["waterbody_text"] = "Presque Isle Bay"
    (ev / "pa-erie-beaches.json").write_text(json.dumps(pa))
    B.run(["--from-dir", str(FIX), "--fetched-at", READ], now=NOW, events_dir=ev, state_file=tmp_path / "s.json",
          registry_file=registry)
    recs = {r["source_record_id"]: r for r in json.loads((ev / f"{B.SOURCE_ID}.json").read_text())["records"]}
    assert recs["728218"]["duplicate_of"] is None


# ---------------------------------------------------------------- decision 40 and history only

def test_an_other_closure_for_hurricane_rip_currents_is_listed_only_and_a_bacteria_closure_keeps_its_window(
        tmp_path, registry):
    _, _, recs = run_saved(tmp_path, registry)
    ny, il = recs["726528"], recs["729819"]
    v = BR.judge(ny, RULES)
    assert v == {"stated": False, "how": "no_field_match", "fields": ["reason_comments"],
                 "read": "the reason code and the reason comment in the state's report to EPA's BEACON system"}
    assert BR.label(ny, BR.config(RULES)) == "Beach closed; the state's report to EPA gives no water-quality reason"
    assert S.event_intervals(ny, "NY", NOW, rules=RULES) == []
    assert BR.judge(il, RULES)["how"] == "program_value"
    ivs = S.event_intervals(il, "IL", NOW, rules=RULES)
    assert [(iv["color"], iv["rule"], S.iso(iv["start"]), S.iso(iv["end"])) for iv in ivs] == [
        ("red", "advisory_active", "2025-09-24T13:00:00Z", "2025-10-27T13:00:00Z")]
    assert ivs[0]["history_only"]["rule"] == "unresolved.history_only" and "cut_at_first_read" not in ivs[0]
    # each water-quality code is the state's stated reason; no code at all is listed only
    for code in ("ELEV_BACT", "RAINFALL", "MODEL", "SEWAGE", "POLICY"):
        assert BR.judge({**il, "raw": {**il["raw"], "reasons": [code]}}, RULES)["stated"] is True, code
    assert BR.judge({**il, "raw": {**il["raw"], "reasons": []}}, RULES)["stated"] is False
    # OTHER with a comment that states a water-quality reason keeps its colour
    other = {**ny, "raw": {**ny["raw"], "reason_comments": ["Elevated bacteria after the storm"]}}
    assert BR.judge(other, RULES)["stated"] is True


def _lake(slug, name, lat, lon, state, d=0.02):
    ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
    return {"slug": slug, "name": name, "kind": "lake", "state": state, "area_km2": 1.0,
            "bbox": [lon - d, lat - d, lon + d, lat + d], "geometry": {"type": "Polygon", "coordinates": [ring]}}


def _status(tmp_path, monkeypatch, recs, now, rules=None):
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "no-outlines-here")
    d = tmp_path / "status-events"
    d.mkdir(exist_ok=True)
    waters = {}
    for r in recs:
        slug = f"test-water-{r['raw']['jurisdiction'].lower()}"
        r["water_slugs"], r["water_match"] = [slug], "name"      # placement is not under test: the water is given
        waters[slug] = _lake(slug, "Test Water", r["lat"], r["lon"], r["raw"]["jurisdiction"])
    (d / f"{B.SOURCE_ID}.json").write_text(json.dumps({"source_id": B.SOURCE_ID, "ok": True, "last_ok_at": READ,
                                                       "meta": {}, "records": recs}))
    return S.build(now=now, write=False, events_dir=d, waters=waters, outfalls=[], registry={}, reaches={},
                   flows=({}, {}), rules=copy.deepcopy(rules or RULES), placement_cache=False)


def test_a_record_read_inside_its_window_never_colours_the_map_now_nor_starts_a_caution(tmp_path, registry, monkeypatch):
    # Louisiana's advisory at CYPT1 ran from Oct 15 to Oct 22, 2026; had we read BEACON on Oct 18, its end was ahead
    read = "2026-10-18T12:00:00Z"
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    _, _, recs = run_saved(tmp_path, registry, fetched_at=read, now=now)
    la = recs["736651"]
    assert la["status"] == "advisory_active" and la["ended_at"] == "2026-10-22T07:00:00-05:00"
    st, hist = _status(tmp_path, monkeypatch, [la], now)
    w = st["waters"]["test-water-la"]
    assert w["status"] == "grey" and not w.get("reasons")
    ivs = hist["intervals"]["test-water-la"]
    assert [(iv[0], iv[1], iv[2]) for iv in ivs] == [("2026-10-15T12:00:00Z", "2026-10-18T12:00:00Z", "red")]
    assert set(hist["waters"]["test-water-la"][-24:]) == {"g"}           # nothing in the last day
    assert {"r", "R"} & set(hist["waters"]["test-water-la"])             # the authority's past window, in the history
    # no end at all: the same
    noend = {**la, "ended_at": None, "raw": {**la["raw"], "end_text": None}}
    (tmp_path / "b").mkdir()
    st2, _ = _status(tmp_path / "b", monkeypatch, [noend], now)
    assert st2["waters"]["test-water-la"]["status"] == "grey"
    # without the rule the same record would be red now: the rule is what keeps it history
    rules = copy.deepcopy(RULES)
    rules["unresolved"].pop("history_only")
    (tmp_path / "c").mkdir()
    st3, _ = _status(tmp_path / "c", monkeypatch, [copy.deepcopy(la)], now, rules)
    assert st3["waters"]["test-water-la"]["status"] == "red"


def test_a_history_only_copy_never_lends_its_reason_to_the_state_record_shown(tmp_path, registry):
    _, _, recs = run_saved(tmp_path, registry)
    pa = recs["728218"]
    shown = {"event_id": "x-state:1", "source_id": "il-idph-beachguard", "event_type": "beach_closure",
             "raw": {"advisory_type": "Closure", "comment": None}}
    by_id = {pa["event_id"]: pa, shown["event_id"]: shown}
    out = S.annotate_beach_reasons([pa, shown], by_id, {pa["event_id"]: shown["event_id"]}, RULES)
    assert out["enabled"] and shown["_beach_reason"]["stated"] is False
    assert pa["_beach_reason"]["stated"] is True


# ---------------------------------------------------------------- cadence and backfill

def test_between_pulls_the_records_are_written_again_without_the_network(tmp_path, registry):
    run_saved(tmp_path, registry)
    ev = tmp_path / "events"
    state = json.loads((tmp_path / "state.json").read_text())
    state["pulled_at"] = "2026-11-21T05:40:00Z"
    (tmp_path / "state.json").write_text(json.dumps(state))

    class NoNetwork:
        def get(self, *a, **k):
            raise AssertionError("no request between pulls")
        post = get
    first = json.loads((ev / f"{B.SOURCE_ID}.json").read_text())
    code = B.run([], sess=NoNetwork(), now=datetime(2026, 11, 22, 1, tzinfo=UTC), events_dir=ev,
                 state_file=tmp_path / "state.json", registry_file=registry)
    again = json.loads((ev / f"{B.SOURCE_ID}.json").read_text())
    assert code == 0 and again["count"] == first["count"]
    assert (again["fetched_at"], again["last_ok_at"]) == (first["fetched_at"], first["last_ok_at"])   # the pull's time
    assert {r["event_id"]: r["fetched_at"] for r in again["records"]} == {r["event_id"]: r["fetched_at"]
                                                                         for r in first["records"]}
    sess = FakeSession()
    code = B.run([], sess=sess, sleep=lambda s: None, now=datetime(2026, 11, 22, 2, tzinfo=UTC), events_dir=ev,
                 state_file=tmp_path / "state.json", registry_file=registry)
    assert code == 0 and len([c for c in sess.calls if c[0] == "POST"]) == 8     # 20 hours on: two years pulled


def test_a_backfill_reads_the_older_years_names_those_it_could_not_and_keeps_the_rest(tmp_path, registry):
    class OneYear(FakeSession):
        def post(self, url, data=None, headers=None, timeout=None):
            year = dict((v, w) for v, w in zip([x for k, x in data if k == "p_arg_names"],
                                               [x for k, x in data if k == "p_arg_values"])).get("F101_CALENDAR_YEAR")
            if year == "2023":
                raise B.requests.ConnectionError("refused")
            return super().post(url, data, headers, timeout)
    ev = events_dir(tmp_path)
    code = B.run(["--backfill", "2023"], sess=OneYear(), sleep=lambda s: None, now=NOW, events_dir=ev,
                 state_file=tmp_path / "state.json", registry_file=registry)
    doc = json.loads((ev / f"{B.SOURCE_ID}.json").read_text())
    state = json.loads((tmp_path / "state.json").read_text())
    assert code == 0 and sorted(state["years"]) == ["2024"] and "pulled_at" not in state
    assert doc["meta"]["years_not_read"] == ["2023: ConnectionError"] and doc["ok"] is False


# ---------------------------------------------------------------- the registry

def test_the_registry_row_takes_each_group_from_its_own_report_and_year(registry):
    doc = json.loads(registry.read_text())
    rows = {b["beach_id"]: b for b in doc["beaches"]}
    nj = rows["NJ290142"]
    assert (nj["name"], nj["state"], nj["county"], nj["waterbody_name"]) == (
        "Barnegat Light Borough at 25th St Bay Front", "NJ", "OCEAN", "Atlantic Ocean")
    assert (nj["beach_act"], nj["tier"], nj["historical"], nj["access"], nj["owner"]) == ("Y", "1", "N", "Public", "Public")
    assert (nj["start_lat"], nj["start_lon"], nj["end_lat"], nj["end_lon"]) == (39.7449, -74.118008, 39.745665, -74.117665)
    assert nj["advisory_reporting_to_epa"] == "1 per-year" and nj["length_mi"] == 0.056
    assert nj["cited"]["attributes"] == {"report": "BEACON Beach Attributes", "year": 2026}
    assert nj["season"]["start"] and nj["cited"]["season"]["report"] == "BEACON Swim Season and Monitoring Frequency"
    assert nj["criteria"] and nj["cited"]["criteria"]["report"] == "BEACON WQS Criteria"
    assert "flags" in nj["possible_sources"] and nj["cited"]["possible_sources"]["report"] == \
        "BEACON Possible Pollution Sources"
    # Michigan's criterion as BEACON gives it, noted
    mi = rows["MI001504"]
    assert {"indicator": "ENTEROCOCCUS", "measure_type": "GM", "value": "300"}.items() <= mi["criteria"][0].items()
    assert any("Michigan" in n and "300" in n for n in doc["notes"])
    assert "GU732200" not in rows and doc["counts"]["out_of_scope"] == {"BR": 2, "GU": 1}
    assert {"attributes", "season", "criteria", "possible_sources"} == set(registry_module().REPORTS)


def test_a_policy_flag_keeps_its_value_and_its_note():
    R = registry_module()
    raw = {"Storm": '<span style="color:#24cb7f" title="Action may be by policy">Yes</span>', "CSO": "Activity Source"}
    out = R.sources(raw)
    assert out["flags"] == {"Storm": "Yes", "CSO": "Activity Source"}
    assert out["flag_notes"] == {"Storm": "Action may be by policy"}


def test_a_comment_is_scrubbed_before_it_is_saved():
    main = (FIX / "beach-actions_2026.csv").read_text()
    detail = (FIX / "beach-actions-detail_2026.csv").read_text().replace(
        "736651,Contamination Advisory,10-15-2026,10-22-2026,7,100,24,24,ELEV_BACT,,",
        "736651,Contamination Advisory,10-15-2026,10-22-2026,7,100,24,24,ELEV_BACT,"
        "Call 555-867-5309 or mail ranger@example.org,")
    assert "555-867-5309" in detail
    rows, _ = B.normalize(main, detail)
    com = rows["736651"]["reason_comments"][0]
    assert "555-867-5309" not in com and "example.org" not in com
