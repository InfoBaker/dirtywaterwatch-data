"""New Jersey ingesters: beach incident runs and snapshot state, the NJDEP outfall join, HAB site
episodes, ECHO outfall-months, the shared rainfall site's snapshot and water names (no network)."""
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from ingest import nj_beaches as B
from ingest import nj_cso_likely as L
from ingest import nj_echo_monthly as E
from ingest import nj_hab as H
from ingest import nj_outfalls as O
from ingest import nj_waters as W


def _row(st, start, end, act="CONTAM_ADV", source="UNKNOWN", ind="ENTERO"):
    return {"Program_Name": "Cooperative Coastal Monitoring Program", "Station_Name": st, "Beach_Name": "East Main",
            "Lat_DD": "40.1113420270", "Lon_DD": "-74.0323773678", "Municipality": "Manasquan Borough",
            "County_Name": "Monmouth County", "Incident_Start_Date": start, "Incident_End_Date": end,
            "Location_Type_Name": "Ocean", "Beach_Act_Type_Name": act, "Beach_Reason_Type_Name": "ELEV_BACT",
            "Beach_Source_Type_Name": source, "Beach_Indicator_Type_Name": ind, "Incident_Additional_Comments": ""}


def _state(runs=None):
    return {"active": {}, "lifted": {}, "history": runs or {}, "stations": {}}


def test_incident_rows_group_into_runs_and_cso_stays_a_beach_closure():
    rows = [_row("MC1036", "08/17/2026", "08/18/2026"), _row("MC1036", "08/18/2026", "08/19/2026"),
            _row("MC1036", "08/25/2026", "08/26/2026"),
            _row("MC1036", "08/22/2026", "08/23/2026", act="CLOSURE", source="CSO", ind="PREEMPT")]
    runs = B.incident_runs(rows)
    assert set(runs) == {"MC1036:beach_advisory:2026-08-17", "MC1036:beach_advisory:2026-08-25",
                         "MC1036:beach_closure:2026-08-22"}
    assert runs["MC1036:beach_advisory:2026-08-17"]["end"] == "2026-08-19"
    for k, r in runs.items():
        r["station_info"] = B.row_station(r["rows"][0])
    recs = {r["source_record_id"]: r for r in B.build_records(_state(runs), "2026-11-02")}
    cso = recs["MC1036:beach_closure:2026-08-22"]
    assert cso["event_type"] == "beach_closure" and cso["raw"]["cause"] == "CSO"
    assert cso["status"] == "advisory_lifted" and cso["ended_at"] == "2026-08-23" and cso["time_precision"] == "day"
    assert cso["authority"] == B.AUTHORITY and cso["advice_window_hours"] is None
    assert cso["discharger_id"] is None and cso["volume_gal"] is None
    assert recs["MC1036:beach_advisory:2026-08-17"]["raw"]["cause"] is None
    # an end after the download date is not an end
    assert {r["status"] for r in B.build_records(_state(runs), "2026-08-18")} >= {"advisory_active"}


def _stations(status_id, present=True):
    st = {"station": "MC1036", "beach": "East Main", "municipality": "Manasquan Borough", "category": "Ocean",
          "lat": 40.11, "lon": -74.03, "beach_status_id": status_id}
    return {"MC1036": st} if present else {}


def test_snapshot_advisory_lifts_on_second_poll_and_survives_missing_polls():
    state = _state()
    t0 = datetime(2026, 7, 6, 14, 0, tzinfo=UTC)
    B.apply_snapshot(state, _stations(2), t0)
    assert len(state["active"]) == 1
    B.apply_snapshot(state, _stations(2, present=False), t0 + timedelta(hours=1))
    a = next(iter(state["active"].values()))
    assert a["missing_polls"] == 1
    B.apply_snapshot(state, _stations(1), t0 + timedelta(hours=2))
    assert len(state["active"]) == 1 and next(iter(state["active"].values()))["pending_lift"]["observations"] == 1
    B.apply_snapshot(state, _stations(1), t0 + timedelta(hours=3))
    assert not state["active"] and len(state["lifted"]) == 1
    lifted = next(iter(state["lifted"].values()))
    assert lifted["ended_at"].startswith("2026-07-06T12:00")      # first poll that observed the lift (EDT)
    state["stations"]["MC1036"] = _stations(1)["MC1036"]
    rec = B.build_records(state, "2026-07-06")[0]
    assert rec["status"] == "advisory_lifted" and rec["time_precision"] == "hour"
    assert "first poll" in rec["raw"]["started_at_basis"]


def test_snapshot_start_comes_from_a_covering_incident_run():
    runs = B.incident_runs([_row("MC1036", "07/06/2026", "07/07/2026")])
    state = _state(runs)
    B.apply_snapshot(state, _stations(2), datetime(2026, 7, 7, 13, 0, tzinfo=UTC))
    state["stations"]["MC1036"] = _stations(2)["MC1036"]
    recs = B.build_records(state, "2026-07-07")
    assert len(recs) == 1 and recs[0]["started_at"] == "2026-07-06" and recs[0]["status"] == "advisory_active"


def test_incomplete_station_list_is_a_failed_fetch():
    js = {"payload": {"filters": {"counties": []}, "beachList": [
        {"station_name": "A", "is_active": True, "latitude": "40.1", "longitude": "-74.0"}]}}
    st, _, err = B.validate_snapshot(js, prev_count=1600)
    assert st is None and "incomplete" in err
    assert B.validate_snapshot({"payload": {}}, None)[2].startswith("malformed")


def test_lake_beach_named_after_another_lake_is_not_inferred_by_town():
    st = {"station": "SU1", "beach": "Lake Lenape", "municipality": "Andover Township", "category": "Lake",
          "lat": 41.0, "lon": -74.74}
    assert B.place(st)[1] in ("none", "name")
    assert B.place(st)[0] != ["lake-aeroflex-nj"]


def test_outfall_dsn_keys_and_join():
    assert O.dsn_keys("030A") == ["030A", "030"]
    assert O.dsn_keys("011A/013A") == ["011A", "011", "013A", "013"]
    echo = {("NJ0108880", "030"): {"outfall": "030", "water_slug": "passaic-river-nj", "water_name": "Passaic River",
                                   "match": "geometry+name"}}
    feats = [{"attributes": {"CSO_ID": "NJ0108880-030A", "NJPDES_NO": "NJ0108880", "DSN": "030A", "PERMITTEE": "Paterson City",
                             "OUTFALL_ALT": "19th Avenue", "RECV_WATER": "Passaic River", "CSO_STAT": "Active",
                             "LATITUDE": 40.907, "LONGITUDE": -74.133, "LAST_EDIT": 1656288000000}}]
    rows, stats = O.build_rows(feats, echo)
    r = rows[0]
    assert r["echo_outfall"] == "030" and r["water_slug"] == "passaic-river-nj" and r["water_match"] == "outfall_registry"
    assert r["last_edit"] == "2022-06-27" and stats["echo_joined"] == 1


def _visit(oid, day, tier, site="BOAT", trig_days=3, water="Spruce Run", lat=40.6575, lon=-74.9253):
    t = int(datetime(2026, 8, day, 14, 0, tzinfo=UTC).timestamp() * 1000)
    return {"objectid": oid, "globalid": f"{{G-{oid}}}", "sitevisitdate": t, "advistorytrigdt": t + trig_days * 86_400_000,
            "watbodnm": water, "siteid": site, "advisorytier": tier, "mungis": "Union Township", "_lat": lat, "_lon": lon}


def test_hab_site_episode_opens_on_a_tier_and_lifts_on_not_present():
    visits = [_visit(1, 3, "Watch"), _visit(2, 10, "Advisory", site="boat "), _visit(3, 17, "HAB Not Present", site="Boat"),
              _visit(4, 18, "Watch", site="DOCK", lat=40.70, lon=-74.90), _visit(5, 19, "", site="DOCK", lat=40.70, lon=-74.90)]
    sites = H.assign_sites(visits)
    assert len(sites) == 2
    stats = Counter()
    eps = [ep for sv in sites.values() for ep in H.episodes(sv, stats)]
    assert stats["visits_without_tier"] == 1
    recs = {r["source_record_id"]: r for r in (H.build_record(ep, 2026) for ep in eps)}
    lifted, active = recs["G-1"], recs["G-4"]
    assert lifted["status"] == "advisory_lifted" and lifted["raw"]["highest_tier"] == "Advisory"
    assert lifted["ended_at"].startswith("2026-08-20")          # the lift's posting date, 3 days after the sample
    assert active["status"] == "advisory_active" and active["event_type"] == "hab_advisory"
    assert lifted["water_slugs"] == ["spruce-run-reservoir-nj"]
    # an alert from an earlier season never resampled has no reported end
    assert H.build_record(eps[-1], 2027)["status"] == "unknown"
    assert H.tier_of("Banana")[1] == "unknown" and H.tier_of(" HAB Not Present ")[1] == "lift"


def test_echo_outfall_months_skip_nodi_and_zero_days():
    def dmr(pend, val, nodi=None):
        return {"MonitoringPeriodEndDate": pend, "DMRValueNmbr": val, "DMRUnitDesc": "d", "StatisticalBaseDesc": "MO TOTAL",
                "NODICode": "C" if nodi else None, "NODIDesc": nodi, "ValueReceivedDate": "15-OCT-26",
                "LimitSetScheduleId": "1"}
    res = {"NJ0156132": {"CWPName": "PERTH AMBOY", "PermFeatures": [{"PermFeatureNmbr": "008", "PermFeatureTypeDesc": "External Outfall",
           "Parameters": [{"ParameterCode": "81381", "ParameterDesc": "Duration of discharge", "MonitoringLocationDesc": "Effluent Gross",
                           "DischargeMonitoringReports": [dmr("30-SEP-26", "5"), dmr("31-AUG-26", "0"),
                                                          dmr("31-JUL-26", None, "No Discharge")]}]}]}}
    nj = {("NJ0156132", "008"): {"outfall_id": "NJ0156132-008A", "outfall_name": "Gordon & Front Street",
                                 "receiving_water": "Arthur Kill", "lat": 40.50, "lon": -74.26, "water_slug": None}}
    stats = defaultdict(Counter)
    cells, names = E.collect(res, nj, {}, stats, {"NJ0156132": {"id": "nj-perth-amboy", "kind": "cso"}})
    recs = E.build_records(cells, names, {"NJ0156132": {"id": "nj-perth-amboy", "name": "City of Perth Amboy"}}, nj, {}, stats)
    assert len(recs) == 1
    r = recs[0]
    assert r["event_id"] == "nj-echo-monthly:NJ0156132:008:2026-09" and r["time_precision"] == "month"
    assert (r["started_at"], r["ended_at"], r["reported_at"]) == ("2026-09-01", "2026-09-30", "2026-10-15")
    assert r["authority"] == E.AUTHORITY and r["volume_gal"] is None and "5 days" in r["volume_text"]
    assert stats["zero_day_months"]["NJ0156132"] == 1 and sum(stats["nodi_months"].values()) == 1


def test_cso_likely_rows_keep_labels_and_our_fetch_time():
    js = {"permittees": [{"permitteeId": 14, "name": "Borough of East Newark", "permitNumber": "NJ0117846",
                          "shortWindow": {"totalLabel": "0.30″", "totalInches": 0.3, "isExceeded": True},
                          "longWindow": {"totalLabel": "0.40″", "totalInches": 0.4, "isExceeded": False},
                          "latestObservationLabel": "Nov 2, 12:00 PM", "alertLevel": 2, "alertLevelLabel": "CSO event likely",
                          "recentHourlyTotals": [{"hourLabel": "2 AM", "totalInches": 0.1}]}]}
    rows = L.permittee_rows(js, "2026-11-02T18:00:00Z")
    r = rows[0]
    assert r["exceeded"] is True and r["alert_label"] == "CSO event likely" and r["fetched_at"] == "2026-11-02T18:00:00Z"
    assert r["short_window"] == {"hours": 1, "total_in": 0.3, "label": "0.30″", "exceeded": True}
    assert r["latest_observation_label"] == "Nov 2, 12:00 PM" and r["discharger_id"] == "nj-east-newark"


def test_nj_water_names():
    assert W.match_waters("Lake Hopatcong", None, (-74.62, 40.95))[0] == ["lake-hopatcong-nj"]
    assert W.match_waters("Spruce Run", None, (-74.92531, 40.65752))[0] == ["spruce-run-reservoir-nj"]
    assert W.match_waters("Spruce Run", None, None)[0] == []                 # bare name needs the point
    assert W.match_waters("Little Swartswood Lake", None, None)[0] == ["little-swartswood-lake-nj"]
    assert W.match_waters("Passaic River", None, (-70.0, 42.0))[0] == ["passaic-river-nj"]   # off-state point ignored
