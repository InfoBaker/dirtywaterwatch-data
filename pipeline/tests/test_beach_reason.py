"""A beach closure or advisory whose source gives no water-quality reason is listed, not coloured (data/rules.json
beach_reason, decision 40; build/beach_reason.py, build/status.py event_intervals, the export's no_stated_reason).
Fixtures: trimmed real pages and answers of 2026-11-21 (fixtures/beach_reason/: Illinois BeachGuard's feed and four
beach pages, DWQ's layer for two Utah sites), the five real SCDES "Swimming Advisory" sites of fixtures/sc, MDEQ's real
releases of fixtures/ms_mdeq_releases, and two real Anne Arundel County records of the 2026-11-14 export. No network."""
import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from build import beach_reason as BR
from build import status as S

FIX = Path(__file__).resolve().parent / "fixtures"
BRF = FIX / "beach_reason"
POLL = "2026-11-21T02:45:00Z"
NOW = datetime(2026, 11, 21, 3, tzinfo=UTC)
RULES = S.load_rules()


def illinois():
    """The four Illinois records as the ingester makes them from the real feed and pages of 2026-11-21."""
    from ingest import il_idph_beachguard as B
    details = {bid: B.parse_detail((BRF / f"il_{bid}.html").read_text()) for bid in ("467", "203", "84", "394")}
    recs, _ = B.run({}, (BRF / "il_rss.xml").read_bytes(), details, POLL)
    return {r["source_record_id"].split("-")[0]: r for r in recs}


def utah():
    from ingest.generic import runner as R
    _, block = R.load_source("ut-dwq-recreational-advisories")
    rows = R.platform("arcgis").parse(block, (BRF / "ut_recreational.json").read_bytes())
    recs, _ = R.build("ut-dwq-recreational-advisories", block, rows, POLL, (), None)
    return {r["raw"]["row"]["Advisory"]: r for r in recs}


def _lake(slug, name, lat, lon, d=0.01):
    ring = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]
    return {"slug": slug, "name": name, "kind": "lake", "state": "IL", "area_km2": 1.0,
            "bbox": [lon - d, lat - d, lon + d, lat + d], "geometry": {"type": "Polygon", "coordinates": [ring]}}


def _build(tmp_path, monkeypatch, recs, waters, rules=None):
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "no-outlines-here")
    ev_dir = tmp_path / "events"
    ev_dir.mkdir(exist_ok=True)
    by_src = {}
    for r in recs:
        by_src.setdefault(r["source_id"], []).append(r)
    for src, rs in by_src.items():
        (ev_dir / f"{src}.json").write_text(json.dumps(
            {"source_id": src, "ok": True, "last_ok_at": POLL, "meta": {}, "records": rs}))
    st, hist = S.build(now=NOW, write=False, events_dir=ev_dir, waters=waters, outfalls=[], registry={}, reaches={},
                       flows=({}, {}), rules=copy.deepcopy(rules or RULES), placement_cache=False)
    return st, hist


def _illinois_status(tmp_path, monkeypatch, rules=None):
    il = illinois()
    waters = {}
    for bid, slug, name in (("467", "deep-lake-il", "Deep Lake"), ("203", "clinton-lake-il", "Clinton Lake"),
                            ("84", "mccullom-lake-il", "McCullom Lake")):
        r = il[bid]
        r["water_slugs"], r["water_match"] = [slug], "name"     # placement is not under test: the water is given
        waters[slug] = _lake(slug, name, r["lat"], r["lon"])
    return il, _build(tmp_path, monkeypatch, list(il.values()), waters, rules)


def test_the_rule_is_on_with_its_rationale_and_every_beach_source_read():
    cfg = BR.config(RULES)
    assert cfg and cfg["event_types"] == ["beach_closure", "beach_advisory"]
    assert cfg["labels"]["beach_closure"] == "Beach closed; the source gives no reason"
    assert "a bacteria result or exceedance, sewage, an algal bloom or a spill" in cfg["rationale"]
    assert "Yes, list only" in cfg["_decided"]
    # every source that writes beach closures or advisories (the ingest modules' and generic blocks' ids) has an entry
    expected = {"al-adem-beach-monitoring", "ar-adh-swim-beach-status", "ca-beachwatch-advisories", "ca-sfpuc-beach-map",
                "de-dnrec-recreational-water", "fl-doh-beaches", "ga-dnr-beaches", "hi-doh-cwb-events-api",
                "id-deq-cyanohab-risk-table",
                "il-idph-beachguard", "ks-kdhe-stream-advisories", "ky-dow-swimming-advisories", "md-aa-health-closings",
                "me-healthy-beaches", "mi-egle-beachguard", "ms-mdeq-beach-monitoring", "ms-mdeq-water-contact-advisories", "nc-rwq-advisories",
                "ne-dwee-beachwatch", "nh-des-swimming", "nj-beaches", "notification-pages", "ny-parks-beaches",
                "oh-odh-beachguard", "ok-nps-chickasaw-bacteria", "or-oha-beach-monitoring", "pa-erie-beaches",
                "pr-drna-beach-notices", "ri-ridoh-beach-advisory-feed", "ri-ridoh-beaches", "sc-des-beach-monitoring",
                "sc-des-freshwater-swim-advisories", "tn-tdec-bacteriological-advisories", "tx-glo-beach-watch",
                "ut-dwq-recreational-advisories", "va-vdh-advisories", "vt-advisories", "wi-dnr-beach-health"}
    # EPA's BEACON archive (ingest/fed_beacon_beach_actions.py): its entry reaches data/rules.json with the coordinator's
    # shared-files patch (tests/test_fed_beacon.py checks the entry itself)
    expected |= {"fed-beacon-beach-actions"} & set(cfg["sources"])
    # Local California entries also arrive through the shared-files integration patch.
    expected |= {"ca-lacounty-beach", "ca-long-beach-water-quality"} & set(cfg["sources"])
    assert expected == set(cfg["sources"])
    for sid, ent in cfg["sources"].items():
        assert ent["kind"] in ("program", "fields", "none"), sid
        assert ent.get("basis") if ent["kind"] == "program" else ent.get("read"), sid
        assert ent["kind"] != "fields" or ent["fields"], sid


def test_illinois_records_from_the_real_feed_are_judged_by_their_type_and_comment():
    il = illinois()
    v = {bid: BR.judge(r, RULES) for bid, r in il.items()}
    # Deep Lake: "Closure", no comment (Lake County Health Department, Sep 1, 2026 8:00 AM)
    assert il["467"]["raw"]["advisory_type"] == "Closure" and il["467"]["raw"]["comment"] is None
    assert v["467"]["stated"] is False and v["467"]["how"] == "no_field_match"
    # the operator's closure "for the 2026 season", and a closure the list still shows from 2014
    assert il["84"]["raw"]["comment"] == "beach closed for the 2026 season per operator" and v["84"]["stated"] is False
    assert il["394"]["started_at"] == "2014-05-22" and v["394"]["stated"] is False
    # a contamination advisory states its reason in its type: it keeps its colour
    assert v["203"] == {"stated": True, "how": "field", "field": "advisory_type", "words": "Contamination Advisory"}


def test_deep_lake_is_listed_on_its_water_with_no_colour_and_mascoutin_stays_red(tmp_path, monkeypatch):
    il, (st, hist) = _illinois_status(tmp_path, monkeypatch)
    deep, masc, pet = il["467"]["event_id"], il["203"]["event_id"], il["84"]["event_id"]
    # listed: on its water's events, with the export's note
    assert deep in st["waters"]["deep-lake-il"]["events"]
    assert st["placements"][deep]["no_stated_reason"] == {
        "rule": "beach_reason", "label": "Beach closed; the source gives no reason",
        "read": "the advisory type and the comment on the beach's page in the Illinois BeachGuard System",
        "source": "data/rules.json"}
    # not coloured: grey water, no reason, no history hour, no marker
    assert st["waters"]["deep-lake-il"]["status"] == "grey"
    assert not [r for r in st["waters"]["deep-lake-il"].get("reasons") or [] if r.get("event_id") == deep]
    assert not hist["intervals"].get("deep-lake-il")
    assert set(hist["waters"].get("deep-lake-il", "g")) <= {"g"}
    assert not [p for p in st["advisory_points"] if p["event_id"] == deep]
    # the operator's seasonal closure likewise; the contamination advisory keeps the authority's red
    assert st["waters"]["mccullom-lake-il"]["status"] == "grey" and "no_stated_reason" in st["placements"][pet]
    assert st["waters"]["clinton-lake-il"]["status"] == "red" and "no_stated_reason" not in st["placements"][masc]
    assert st["counts"]["no_stated_reason"] == 3       # Timber Pointe (2014) names no water and is listed too
    assert st["beach_reason"]["listed_without_colour"] == {"il-idph-beachguard": 3}
    assert not [p for p in st["problems"] if p.startswith("beach_reason")]


def test_with_the_rule_switched_off_deep_lake_is_red_as_before(tmp_path, monkeypatch):
    rules = copy.deepcopy(RULES)
    rules["beach_reason"]["enabled"] = False
    il, (st, _) = _illinois_status(tmp_path, monkeypatch, rules)
    assert st["waters"]["deep-lake-il"]["status"] == "red"
    assert "no_stated_reason" not in st["placements"][il["467"]["event_id"]]


def test_a_beach_source_with_no_entry_keeps_its_colour_and_is_named(tmp_path, monkeypatch):
    rules = copy.deepcopy(RULES)
    del rules["beach_reason"]["sources"]["il-idph-beachguard"]
    il, (st, _) = _illinois_status(tmp_path, monkeypatch, rules)
    assert st["waters"]["deep-lake-il"]["status"] == "red"
    assert [p for p in st["problems"] if p.startswith("beach_reason: il-idph-beachguard has no entry")]


def test_utahs_off_season_label_is_listed_and_its_e_coli_health_watch_stays_red():
    ut = utah()
    off, hw = ut["Off Season"], ut["E coli HW"]
    assert off["event_type"] == hw["event_type"] == "beach_advisory"
    assert BR.judge(off, RULES)["stated"] is False
    assert S.event_intervals(off, "UT", NOW, rules=RULES) == []         # was the site's caution (code_caution)
    assert BR.label(off, BR.config(RULES)) == "Advisory listed; the source gives no reason"
    v = BR.judge(hw, RULES)
    assert v["stated"] is True and v["field"] == "row.Advisory" and v["words"] == "E coli HW"
    assert [iv["color"] for iv in S.event_intervals(hw, "UT", NOW, rules=RULES)][:1] == ["red"]


def test_the_pearl_river_keeps_red_on_mdeqs_2019_release_and_trahon_creek_on_its_own_text():
    from ingest import ms_mdeq_water_contact as W
    rel = FIX / "ms_mdeq_releases"
    pages = {"https://www.mdeq.ms.gov/water-contact-advisory-issued-for-section-of-trahon-creek/":
             (rel / "water-contact-advisory-issued-for-section-of-trahon-creek.html").read_text()}
    recs, _ = W.run((rel / "feed.xml").read_bytes(), pages, [], "2026-11-07T18:00:00Z")
    by = {r["source_record_id"]: r for r in recs}
    pearl = BR.judge(by["pearl-river-hanging-moss-creek-to-byram-swinging-bridge"], RULES)
    assert pearl["stated"] and pearl["how"] == "record"
    assert "due to ongoing sanitary sewer overflows around the City of Jackson" in pearl["basis"]
    trahon = BR.judge(by["trahon-creek-2026-09-02"], RULES)
    assert trahon["stated"] and trahon["how"] == "field" and "sewage bypass" in trahon["words"]


def test_an_update_that_gives_no_reason_takes_its_parents(tmp_path, monkeypatch):
    """Anne Arundel County: "the Department of Health has rescinded this advisory" under the closure for "a Large
    Sewage Spill": the update is the record the rules use, and it keeps the closure's reason."""
    recs = json.loads((BRF / "md_aa_records.json").read_text())["records"]
    closure, lift = recs
    assert BR.judge(lift, RULES)["stated"] is False and BR.judge(closure, RULES)["stated"] is True
    by_id = {r["event_id"]: copy.deepcopy(r) for r in recs}
    S.annotate_beach_reasons(list(by_id.values()), by_id, {}, RULES)
    v = by_id[lift["event_id"]]["_beach_reason"]
    assert v["stated"] is True and v["how"] == "parent" and v["parent"] == closure["event_id"]
    ivs = S.event_intervals(by_id[lift["event_id"]], "MD", datetime(2026, 6, 5, 12, tzinfo=UTC), rules=RULES)
    assert ivs and ivs[0]["color"] == "red"


def test_a_linked_record_lends_its_stated_reason_to_the_record_shown():
    shown = {"event_id": "x:sheet", "source_id": "ar-adh-swim-beach-status", "event_type": "beach_closure", "raw": {}}
    feed = {"event_id": "x:feed", "source_id": "ri-ridoh-beach-advisory-feed", "event_type": "beach_closure",
            "raw": {"reason": "high bacteria counts"}, "duplicate_of": "x:sheet"}
    by_id = {e["event_id"]: e for e in (shown, feed)}
    S.annotate_beach_reasons([shown, feed], by_id, {"x:feed": "x:sheet"}, RULES)
    assert shown["_beach_reason"]["how"] == "linked" and shown["_beach_reason"]["linked"] == "x:feed"


@pytest.mark.parametrize("text,stated", [
    ("Closure", False), ("Beach Closed by Operator", False), ("Beach closed for the season", False),
    ("Off Season", False), ("Debris Clean Up", False), ("End of Sampling Season", False), ("Other", False),
    ("Lifeguard staffing", False), ("Drain repair", False), ("Boil water notice lifted", False),
    ("Contamination Advisory", True), ("E coli HW", True), ("E. coli", True), ("Enterococci", True),
    ("Exceedance", True), ("Preemptive: rainfall", True), ("Algae", True), ("Combined Sewer Outflow", True),
    ("Chemical/Oil Spill", True), ("Recreational Water Quality Advisory", True), ("High bacteria levels", True)])
def test_the_reason_words(text, stated):
    ev = {"source_id": "il-idph-beachguard", "event_type": "beach_closure", "raw": {"advisory_type": text}}
    assert BR.judge(ev, RULES)["stated"] is stated


def test_other_types_and_a_switched_off_rule_are_not_judged():
    ev = {"source_id": "il-idph-beachguard", "event_type": "hab_advisory", "raw": {"advisory_type": "Closure"}}
    assert BR.judge(ev, RULES) is None
    rules = copy.deepcopy(RULES)
    rules["beach_reason"]["enabled"] = False
    assert BR.judge({**ev, "event_type": "beach_closure"}, rules) is None


def test_the_export_carries_the_note_on_the_record_and_in_the_csv(tmp_path, monkeypatch):
    from build import redact as R
    from export import build as X
    from export import csv as csv_export
    il, (st, _) = _illinois_status(tmp_path, monkeypatch)
    deep = il["467"]
    r = R.redactor_for([deep], tmp_path)
    rec = X.public_record(deep, st["placements"][deep["event_id"]], r)
    assert rec["no_stated_reason"]["label"] == "Beach closed; the source gives no reason"
    masc = il["203"]
    assert "no_stated_reason" not in X.public_record(masc, st["placements"][masc["event_id"]], r)
    monkeypatch.setattr(S, "_STATES", {"IL"})
    rows = []
    for e in (rec, X.public_record(masc, st["placements"][masc["event_id"]], r)):
        e["fixture"] = False
        rows.append(e)
    out = tmp_path / "csv"
    csv_export.write_csvs(rows, [], [], out, page_ids=set())
    import csv as _csv
    with (out / "all-reports-2026.csv").open(newline="", encoding="utf-8") as f:
        got = {x["record_id"]: x["listed_without_colour"] for x in _csv.DictReader(f)}
    assert got == {deep["source_record_id"]: "Beach closed; the source gives no reason", masc["source_record_id"]: ""}


def test_the_verdict_build_sets_is_not_part_of_the_record_placement_caches():
    rec = illinois()["467"]
    h = S.record_hash(rec)
    assert S.record_hash({**rec, "_beach_reason": {"stated": False, "how": "no_field_match"}}) == h


def test_a_new_york_live_layer_closure_reads_its_reason_from_the_layers_own_field_name():
    """NYS Parks' live layer writes Status_Reason (the yearly dataset status_reason): a closure for an exceedance keeps
    its colour from either. The layer is off season now; the row is in its field names with the dataset's values."""
    from ingest import ny_beaches_habs as N
    feat = {"attributes": {"StateParkBeach": "Wildwood SP", "Beach_status": "Closed", "Status_Reason": "Exceedance",
                           "Date_sampled": "08-Sep-26", "Latitude": 40.96, "Longitude": -72.80}}
    recs = N.live_beaches([feat], {}, datetime(2026, 9, 8, 15, tzinfo=UTC), "2026-09-08T15:00:00Z", {}, {})
    assert len(recs) == 1 and recs[0]["event_type"] == "beach_closure"
    v = BR.judge(recs[0], RULES)
    assert v["stated"] is True and v["field"] == "rows[].Status_Reason" and v["words"] == "Exceedance"


def test_a_maine_live_feed_closure_reads_its_public_comment():
    """Maine's live feed keeps the comment as public_comment (the status history page's rows as comment): a closure
    whose comment names a sewage spill keeps its colour; the raw shape is the ingester's (me_healthy_beaches.py)."""
    rec = {"source_id": "me-healthy-beaches", "event_type": "beach_closure",
           "raw": {"from": "mapdata_bma.geojson", "advisory_type": "Beach Closure", "advisory_status": "Active",
                   "public_comment": "Closed due to a sewage spill upstream."}}
    v = BR.judge(rec, RULES)
    assert v["stated"] is True and v["field"] == "public_comment"
    rec["raw"]["public_comment"] = ""
    assert BR.judge(rec, RULES)["stated"] is False


# ---- review 2026-11-21 (Astra, reviews/beach-astra.md): findings 1 to 4 and 6

def test_review_1_delawares_comment_is_read_from_the_records_advice():
    """ingest/de_dnrec_recwater.py keeps DNREC's advcomment as the record's advice_text."""
    rec = {"source_id": "de-dnrec-recreational-water", "event_type": "beach_closure", "advice_text": "Closed due to a sewage spill",
           "raw": {"advisory_type": "Recreational Water Closure", "advisory_reason": "Other", "advisory_description": None}}
    v = BR.judge(rec, RULES)
    assert v["stated"] is True and v["field"] == "event.advice_text"


def test_review_2_hawaiis_cause_is_read():
    """ingest/hi_doh_cwb_events.py keeps the Department's cause in raw.row.cause."""
    rec = {"source_id": "hi-doh-cwb-events-api", "event_type": "beach_advisory",
           "raw": {"row": {"type": "Beach Advisory", "title": "Advisory at Example Beach", "description": "The public is advised.",
                           "cause": "High enterococci levels"}}}
    v = BR.judge(rec, RULES)
    assert v["stated"] is True and v["field"] == "row.cause"


@pytest.mark.parametrize("text,stated", [
    ("High Escherichia coli levels", True), ("E.  coli", True), ("E.\ncoli result over the standard", True),
    ("Beach closed for spillway maintenance", False), ("Beach closed for the season at Rain Lake", False),
    ("Closed after an oil spill", True), ("Closed: heavy rain", True), ("Closed after rainfall", True)])
def test_review_3_and_6_the_reason_words(text, stated):
    ev = {"source_id": "il-idph-beachguard", "event_type": "beach_closure", "raw": {"advisory_type": "Closure", "comment": text}}
    assert BR.judge(ev, RULES)["stated"] is stated


def test_review_4_a_reason_passes_through_a_duplicate_and_then_a_revision():
    """Parent P states none; D, a duplicate of P, states a sewage spill; C revises P and says it remains in effect: C, the
    record the rules use, keeps the reason D gives for P."""
    def rec(eid, comment, **kw):
        return {"event_id": eid, "source_id": "il-idph-beachguard", "event_type": "beach_closure",
                "raw": {"advisory_type": "Closure", "comment": comment}, **kw}
    p = rec("x:P", None)
    d = rec("x:D", "Closure due to sewage spill", duplicate_of="x:P")
    c = rec("x:C", "Remains in effect", parent_event_id="x:P")
    by_id = {e["event_id"]: e for e in (p, d, c)}
    S.annotate_beach_reasons([p, d, c], by_id, {"x:D": "x:P"}, RULES)
    assert p["_beach_reason"]["stated"] is True and p["_beach_reason"]["how"] == "linked"
    assert c["_beach_reason"]["stated"] is True and c["_beach_reason"]["how"] == "parent"
    # and a cycle of links ends
    a, b = rec("x:A", None, parent_event_id="x:B"), rec("x:B", None, parent_event_id="x:A")
    by2 = {"x:A": a, "x:B": b}
    S.annotate_beach_reasons([a, b], by2, {}, RULES)
    assert a["_beach_reason"]["stated"] is False and b["_beach_reason"]["stated"] is False


def test_the_charts_count_an_update_with_its_parents_reason_as_the_status_build_does():
    """build/charts.py counts hours under an official advisory from the effective records (an update with its parent's
    start): an update that gives no reason of its own counts with its parent's, as on the water's status strip."""
    from build import charts as C
    recs = copy.deepcopy(json.loads((BRF / "md_aa_records.json").read_text())["records"])
    by_id = {r["event_id"]: r for r in recs}
    superseded, effective = S.resolve_revisions(recs, by_id)
    C.beach_verdicts(recs, by_id, {}, effective, RULES)
    lift = effective.get(recs[1]["event_id"], recs[1])
    assert lift["_beach_reason"]["how"] == "parent"
    assert C.red_intervals(lift, "MD", datetime(2026, 6, 5, 12, tzinfo=UTC), __import__("collections").Counter(), rules=RULES)


def test_delawares_map_label_of_a_current_advisory_is_its_water_quality_advisory():
    """DNREC's Recreational Water Program map (ingest/de_dnrec_recwater.py CODES): a station under "Monitoring – Current
    Advisory" is under the programme's water-quality advisory (its codes are monitoring states, among them "Resampling
    Enterococcus Spike"), so the map's record keeps its colour; a closure whose own reason is "End of Sampling Season" or
    "Other", with no comment, is listed."""
    m = {"source_id": "de-dnrec-recreational-water", "event_type": "beach_advisory",
         "raw": {"current_advisory_label": "Monitoring – Current Advisory"}}
    v = BR.judge(m, RULES)
    assert v["stated"] is True and v["how"] == "program_value" and "water-quality" in v["basis"]
    c = {"source_id": "de-dnrec-recreational-water", "event_type": "beach_closure", "advice_text": None,
         "raw": {"advisory_type": "Recreational Water Closure", "advisory_reason": "End of Sampling Season"}}
    assert BR.judge(c, RULES)["stated"] is False


def test_south_carolina_river_and_lake_swimming_advisories_keep_their_colour():
    # SCDES's "Water Advisories" service, layer "Swimming Advisory" (real fixture): the agency's advisory against
    # swimming at the site; no further reason is given, and the advisory itself concerns the water (coordinator,
    # 2026-11-21: erring on safety; the owner may list them instead)
    from ingest import sc_des_advisories as A
    ent = RULES["beach_reason"]["sources"]["sc-des-freshwater-swim-advisories"]
    assert ent["kind"] == "program" and "Swimming Advisory" in ent["basis"]
    d = json.loads((FIX / "sc" / "swimming_advisory.json").read_text())
    feats = A.safe_features(A.check_swim(d["layer"], d["count"]), "geometry", A.SWIM_FIELDS)
    recs, _, _ = A.swim_records(feats, {}, "2026-11-15T15:00:00Z")
    assert len(recs) == 5
    for r in recs:
        v = BR.judge(r, RULES)
        assert v["stated"] is True and v["how"] == "program" and v["basis"] == ent["basis"]
