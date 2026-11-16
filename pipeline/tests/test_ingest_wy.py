"""Wyoming: WDEQ's HCB bulletin feed, the operator rows, the register, the rules row, the state text and the
missing-waters list. The feed fixture is synthetic, in the GovDelivery RSS shape: its staff line is invented ("Example
Person", example.org, 555-0100), so a test proves a person named in a bulletin never reaches a record or the raw save.
Run from pipeline/: python -m pytest tests/test_ingest_wy.py -q
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import wy_deq_hcb_bulletins as W  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
T0 = "2026-11-15T12:00:00Z"
STAFF = ("<p>Questions can be directed to Example Person, Epidemiologist, at example.person@example.org or "
         "(307) 555-0100.</p>")
HEAD = ("<tr><td><p><strong>Waterbody Name</strong></p></td><td><p><strong>Observation or Sampling Location(s)    "
        "</strong></p></td><td><p><strong>Advisory Type  </strong></p></td><td><p><strong>Date Issued</strong></p></td></tr>")
A = ("Example Lake", "North Beach", "Bloom", "7/9/2026")
B = ("Example Reservoir", "Dam Ramp", "Toxin", "8/18/2026")
C = ("Unnamed Lake- Example Range (42.80812, -109.32745)", "Shore", "Bloom", "9/10/2026")


def table(rows, head=HEAD):
    body = "".join("<tr>" + "".join(f"<td><p>{escape(c)}</p></td>" for c in r) + "</tr>" for r in rows)
    return ("<p><strong>Current HCB Recreational Use Advisories*</strong></p><table><tbody>" + head + body +
            "</tbody></table>")


def item(bid, sent, title, body):
    return (f"<item><title>{escape(title)}</title><link>https://content.govdelivery.com/accounts/WYDEQ/bulletins/{bid}"
            f"</link><pubDate>{sent}</pubDate><description>{escape(body)}</description></item>")


def feed(*items):
    return "<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>" + "".join(items) + "</channel></rss>"


NEW = "New Harmful Cyanobacteria Bloom (HCB) Recreational Use Advisory"


def new(bid, sent, rows):
    return item(bid, sent, NEW, "<p>A BLOOM ADVISORY has been issued.</p>" + STAFF + table(rows))


def lift(bid, sent, water, rows, sentence=None):
    s = sentence or (f"The Wyoming Department of Health (WDH) has lifted the harmful cyanobacteria bloom (HCB) "
                     f"recreational use advisory for {water}.")
    return item(bid, sent, f"Harmful Cyanobacteria Bloom (HCB) Recreational Use Advisory Lifted for {water}",
                f"<p>{s}</p>" + STAFF + table(rows))


S1 = "Tue, 04 Aug 2026 16:00:00 -0500"     # 21:00Z
S2 = "Tue, 11 Aug 2026 16:00:00 -0500"
S3 = "Fri, 21 Aug 2026 18:00:00 -0500"
S4 = "Fri, 04 Sep 2026 15:00:00 -0500"


def by_key(recs):
    return {r["source_record_id"]: r for r in recs}


def kid(row):
    return W.read_table(table([row]))[0][0]["key"]


def build(*items, prev=None):
    return W.build(feed(*items), T0, prev or [])


# ------------------------------------------------------------------------------------------- records

def test_a_listed_row_starts_at_date_issued_and_is_confirmed_by_each_bulletin():
    recs, meta, _ = build(new("b1", S1, [A, B]), new("b2", S2, [A, B]))
    r = by_key(recs)[kid(A)]
    assert (r["started_at"], r["time_precision"], r["ended_at"], r["status"]) == ("2026-07-09", "day", None,
                                                                                  "advisory_active")
    # the latest table stands until a later bulletin drops it: confirmed at this read (Astra review 2026-11-15 P1)
    assert r["raw"]["_last_seen_in_source"] == T0 and r["raw"]["time_zone"] == "America/Denver"
    assert r["raw"]["_last_listed_in_bulletin"] == "2026-08-11T21:00:00Z"
    assert r["published_at"] == "2026-08-04T21:00:00Z" and r["event_type"] == "hab_advisory"
    assert r["raw"]["program_end_bound"]["date"] == "2026-12-31" and meta["current"] == 2


def test_a_row_dropped_by_a_later_table_ends_as_a_poll_and_ages_from_its_last_confirmation():
    recs, *_ = build(new("b1", S1, [A, B]), new("b2", S2, [B]))
    r = by_key(recs)[kid(A)]
    assert r["status"] == "advisory_active" and r["ended_at"] == "2026-08-11T21:00:00Z"
    assert r["raw"]["ended_at_precision"] == "poll" and r["raw"]["_ages_after_confirmation"] is True
    assert r["raw"]["_last_seen_in_source"] == "2026-08-04T21:00:00Z"


def test_an_absence_seen_months_later_does_not_colour_the_gap():
    from build import status as S
    late = "Wed, 28 Oct 2026 17:00:00 -0500"
    recs, *_ = build(new("b1", S1, [A, B]), new("b9", late, [B]))
    r = by_key(recs)[kid(A)]
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    reds = [iv for iv in S.event_intervals(r, "WY", now) if iv["color"] == "red"]
    assert reds and max(iv["end"] for iv in reds) <= datetime(2026, 8, 4, 21, tzinfo=timezone.utc) + timedelta(days=14)


def test_an_affirmative_lift_bulletin_lifts_and_a_conditional_one_does_not():
    recs, meta, _ = build(new("b1", S1, [A, B]), lift("b3", S3, "Example Lake", [B]))
    r = by_key(recs)[kid(A)]
    assert (r["status"], r["ended_at"], r["raw"]["ended_at_precision"]) == ("advisory_lifted", "2026-08-21T23:00:00Z",
                                                                           "bound")
    assert "has lifted" in r["raw"]["end_basis"] and by_key(recs)[kid(B)]["status"] == "advisory_active"
    for words in ("The advisory for Example Lake will be lifted when two samples are below the levels.",
                  "The WDH has not lifted the advisory for Example Lake.",
                  "If results allow, WDH has lifted the advisory for Example Lake."):
        recs, *_ = build(new("b1", S1, [A, B]), lift("b3", S3, "Example Lake", [B], sentence=words))
        r = by_key(recs)[kid(A)]
        assert r["status"] == "advisory_active" and r["raw"]["ended_at_precision"] == "poll", words


def test_a_lift_for_another_water_or_one_still_listed_ends_nothing():
    recs, *_ = build(new("b1", S1, [A, B]), lift("b3", S3, "Other Lake", [A, B]))
    assert all(r["status"] == "advisory_active" and r["ended_at"] is None for r in recs)
    recs, *_ = build(new("b1", S1, [A, B]), lift("b3", S3, "Example Lake", [A, B]))
    assert by_key(recs)[kid(A)]["ended_at"] is None


def test_a_reissue_is_a_new_record_and_a_relisting_is_a_new_period():
    a2 = A[:3] + ("9/1/2026",)
    recs, *_ = build(new("b1", S1, [A]), new("b2", S2, [B]), new("b4", S4, [a2, A]))
    k = by_key(recs)
    first, again, reissue = k[kid(A)], k[kid(A) + ":relisted-2026-09-04"], k[kid(a2)]
    assert (first["started_at"], first["ended_at"]) == ("2026-07-09", "2026-08-11T21:00:00Z")
    assert again["started_at"] == "2026-09-04T20:00:00Z" and again["time_precision"] == "poll" and not again["ended_at"]
    assert reissue["started_at"] == "2026-09-01" and reissue["waterbody_text"] == first["waterbody_text"]


def test_relisted_day_is_the_local_mountain_day():
    late_evening = "Thu, 01 Oct 2026 22:30:00 -0500"   # 03:30Z on Oct 2, 21:30 MDT on Oct 1
    recs, *_ = build(new("b1", S1, [A]), new("b2", S2, [B]), new("b5", late_evening, [A]))
    assert kid(A) + ":relisted-2026-10-01" in by_key(recs)
    assert W.local_day("2026-11-01T07:30:00Z") == "2026-11-01" and W.local_day("2026-11-01T05:30:00Z") == "2026-10-31"
    assert W.local_day("2026-03-08T08:30:00Z") == "2026-03-08" and W.local_day("2026-03-08T06:30:00Z") == "2026-03-07"


# ------------------------------------------------------------------------------------------- failed reads

@pytest.mark.parametrize("text", ["<html><body>Service unavailable</body></html>", "",
                                  "<?xml version='1.0'?><rss><channel></channel></rss>"])
def test_an_error_page_or_an_empty_feed_fails(text):
    with pytest.raises(Exception):
        W.build(text, T0, [])


def test_a_feed_with_no_readable_table_fails():
    bad_head = HEAD.replace("Date Issued", "Issued On")
    with pytest.raises(ValueError):
        build(item("b1", S1, NEW, table([A], head=bad_head)))
    with pytest.raises(ValueError):
        build(item("b1", S1, "Wyoming DEQ Encourages Safe Water Recreation", "<p>No table here.</p>"))


def test_an_unreadable_table_observes_nothing_and_is_listed():
    broken = table([A[:2] + ("Bloom",)])                       # a row with three cells
    recs, meta, _ = build(new("b1", S1, [A, B]), item("b2", S2, NEW, broken), new("b3", S3, [A, B]))
    assert [u["bulletin"] for u in meta["unread"]] == ["b2"]
    assert all(r["ended_at"] is None for r in recs)
    renamed = table([B], head=HEAD.replace("Advisory Type", "Kind"))
    recs, meta, _ = build(new("b1", S1, [A, B]), item("b2", S2, NEW, renamed))
    assert meta["unread"] and all(r["ended_at"] is None for r in recs)


def test_main_keeps_previous_records_on_a_failed_read(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(W, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    good = tmp_path / "good.rss"
    good.write_text(feed(new("b1", S1, [A, B])))
    assert W.main(["--file", str(good)]) == 0
    before = json.loads((tmp_path / f"{W.SOURCE_ID}.json").read_text())["records"]
    bad = tmp_path / "bad.rss"
    bad.write_text("<html>error</html>")
    assert W.main(["--file", str(bad)]) == 1
    after = json.loads((tmp_path / f"{W.SOURCE_ID}.json").read_text())
    assert after["ok"] is False and after["records"] == before


# ------------------------------------------------------------------------------------------- privacy, ids

def test_staff_never_saved_and_a_point_in_a_name_is_rounded():
    recs, _, saved = build(new("b1", S1, [A, C]))
    blob = json.dumps(recs) + json.dumps(saved)
    assert "Example Person" not in blob and "example.org" not in blob and "555-0100" not in blob
    c = [r for r in recs if r["lat"] is not None][0]
    assert (c["lat"], c["lon"]) == (42.808, -109.327) and "42.80812" not in blob
    assert c["waterbody_text"] == "Unnamed Lake- Example Range"


def test_ids_do_not_depend_on_order_or_on_which_bulletins_are_read_together():
    one, *_ = build(new("b1", S1, [A, B]), new("b2", S2, [B, A]))
    two, *_ = build(new("b2", S2, [A, B]), new("b1", S1, [B, A]))
    key = lambda rs: sorted((r["event_id"], r["started_at"], r["ended_at"]) for r in rs)  # noqa: E731
    assert key(one) == key(two)
    first, *_ = build(new("b1", S1, [A, B]))
    later, *_ = build(new("b2", S2, [A]), prev=first)            # the feed lost b1; the earlier read is kept
    k = by_key(later)
    assert k[kid(A)]["published_at"] == "2026-08-04T21:00:00Z" and k[kid(B)]["ended_at"] == "2026-08-11T21:00:00Z"
    again, *_ = build(new("b2", S2, [A]), prev=later)
    assert key(again) == key(later)


def test_a_qualified_name_keeps_its_part_as_a_place():
    rows, _ = W.read_table(table([("Example Reservoir: West Causeway", "Shore", "Bloom", "7/1/2026")]))
    assert (rows[0]["water"], rows[0]["place"]) == ("Example Reservoir", "West Causeway")


# ------------------------------------------------------------------------------------------- shared modules

def test_county_lines_for_the_new_states_leave_other_states_unchanged(monkeypatch):
    from build import status as S
    ev = {"event_id": "x", "source_id": "ut-example", "raw": {"state": "UT", "county": "Salt Lake"}, "lat": 40.76,
          "lon": -111.89}
    waters = {}
    before = S.county_slugs(["a", "b"], ev, waters, lambda *_: 0)
    for st in ("CO", "MT", "WY"):
        monkeypatch.delitem(S.COUNTY_STATES, st, raising=False)
        monkeypatch.setattr(S, "COUNTY_FIELD_STATES", S.COUNTY_FIELD_STATES - {st})
    assert S.county_slugs(["a", "b"], ev, waters, lambda *_: 0) == before


# ------------------------------------------------------------------------------------------- operators, register

def wy_rows():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
            if r.get("state") == "WY" and "wy" in (r.get("source_areas") or [])]


def test_every_wyoming_plant_permit_is_in_exactly_one_row():
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "WY"}
    held = [p for r in wy_rows() for p in r["npdes_permits"]]
    assert len(held) == len(set(held)) and plants <= set(held)


def test_names_are_not_persons():
    sys.path.insert(0, str(ROOT / "scripts"))
    import mountain_operator_rows as MR
    for r in wy_rows():
        assert not MR.personish(r["name"]) and "[name removed]" not in r["name"]


def test_register_rows_validate_and_cover_every_operator():
    from ingest import notification_pages as NP
    doc = NP.load_register(ROOT / "data" / "notice-channels")
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    assert not NP.validate_register(doc, dis, ROOT)
    wy = [r for r in doc["channels"] if r["state"] == "WY"]
    assert {r["id"] for r in wy_rows()} <= {r["operator_id"] for r in wy if r.get("operator_id")}
    assert {"wy-deq-hcb-bulletins", "wy-deq-sso-reports", "wy-deq-spills"} <= {r["id"] for r in wy}
    assert not any(r.get("barrier_review") for r in wy)


def test_rules_row_and_state_text():
    row = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["WY"]
    assert row["hours"] is None and "Sanitary Sewer Overflows" in row["source"]
    t = (ROOT / "research" / "wy" / "state-text.md").read_text()
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and not re.search(r"\b(safe|clean)\b", t) and ".json" not in t


def test_missing_waters_list():
    doc = json.loads((ROOT / "research" / "wy" / "receiving-waters-missing.json").read_text())
    assert doc["state"] == "WY" and (doc["rows"] or doc.get("resolved_names"))
    assert all(r["name"] == r["name"].strip() and not r["name"].isupper() for r in doc["rows"])


# ---------------------------------------------------------------- Astra review 2026-11-15 (fix/co-mt-wy-review)

def _status(tmp_path, recs, now, waters=None):
    """A full status build with Wyoming live over the given records (invented waters)."""
    from build import status as S
    d = tmp_path / "events"
    d.mkdir(exist_ok=True)
    (d / f"{W.SOURCE_ID}.json").write_text(json.dumps({"source_id": W.SOURCE_ID, "ok": True, "fetched_at": T0,
                                                       "last_ok_at": T0, "meta": {}, "count": len(recs),
                                                       "records": recs}))

    def lake(slug, name, x, y):
        ring = [[x, y], [x + 0.05, y], [x + 0.05, y + 0.05], [x, y + 0.05], [x, y]]
        return slug, {"slug": slug, "name": name, "kind": "lake", "state": "WY", "area_km2": 5.0,
                      "bbox": [x, y, x + 0.05, y + 0.05], "geometry": {"type": "Polygon", "coordinates": [ring]}}
    waters = waters or dict([lake("example-lake-wy", "Example Lake", -106.0, 42.0),
                             lake("example-reservoir-wy", "Example Reservoir", -107.0, 43.0)])
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    rules["live_states"] = sorted(set(rules["live_states"]) | {"WY"})
    rules["rain_likely"] = {**rules["rain_likely"], "enabled": False}
    st, _ = S.build(now=now, write=False, events_dir=d, waters=waters, outfalls=[], registry={}, reaches={},
                    flows=({}, {}), rules=rules, placement_cache=False)
    return st


def test_review_a_standing_list_stays_red_past_14_days(tmp_path):
    later = "2026-10-20T12:00:00Z"                 # 70 days after the last bulletin, the list unchanged
    recs, meta, _ = W.build(feed(new("b1", S1, [A, B]), new("b2", S2, [A, B])), later, [])
    r = by_key(recs)[kid(A)]
    assert r["status"] == "advisory_active" and r["ended_at"] is None and r["raw"]["_last_seen_in_source"] == later
    assert "standing_basis" in r["raw"]
    st = _status(tmp_path, recs, datetime(2026, 10, 20, 13, tzinfo=timezone.utc))
    assert st["waters"]["example-lake-wy"]["status"] == "red"


def test_review_the_programme_end_of_season_ends_a_standing_advisory():
    after = "2027-01-02T12:00:00Z"
    recs, meta, _ = W.build(feed(new("b1", S1, [A, B])), after, [])
    r = by_key(recs)[kid(A)]
    assert r["status"] == "advisory_lifted" and r["ended_at"] == "2027-01-01T07:00:00Z"
    assert r["raw"]["ended_at_precision"] == "bound" and r["raw"]["expired_at_programme_end"] is True
    assert r["raw"]["_last_seen_in_source"] == "2027-01-01T07:00:00Z" and meta["expired"] == 2


def test_review_a_dropped_row_still_ends_and_a_lift_still_lifts_with_the_standing_rule():
    recs, *_ = build(new("b1", S1, [A, B]), new("b2", S2, [B]))
    r = by_key(recs)[kid(A)]
    assert r["raw"]["ended_at_precision"] == "poll" and r["raw"]["_last_seen_in_source"] == "2026-08-04T21:00:00Z"


@pytest.mark.parametrize("rows", [[], [("", "", "", "")]])
def test_review_a_header_only_table_ends_nothing_and_is_unread(rows):
    recs, meta, _ = build(new("b1", S1, [A, B]), new("b2", S2, rows))
    assert all(r["ended_at"] is None for r in recs) and len(recs) == 2
    assert [u["bulletin"] for u in meta["unread"]] == ["b2"]


def test_review_a_corrected_bulletin_replaces_its_earlier_absence():
    # run 1: b2 was read with B missing (a mistake); run 2: the same bulletin corrected, listing A and B again
    first, *_ = build(new("b1", S1, [A, B]), new("b2", S2, [A]))
    assert by_key(first)[kid(B)]["raw"]["ended_at_precision"] == "poll"
    second, meta, _ = build(new("b1", S1, [A, B]), new("b2", S2, [A, B]), prev=first)
    keys = [r["source_record_id"] for r in second]
    assert keys.count(kid(B)) == 1 and not any("relisted" in k for k in keys)
    b = by_key(second)[kid(B)]
    assert b["ended_at"] is None and b["raw"]["_absent_in"] == [] and meta["relisted"] == 0
    # the same when the earlier run's absence was saved without its link (records from before this fix)
    for r in first:
        r["raw"].pop("_absent_links", None)
    again, *_ = build(new("b1", S1, [A, B]), new("b2", S2, [A, B]), prev=first)
    assert by_key(again)[kid(B)]["ended_at"] is None


def test_review_a_part_of_a_water_never_colours_the_whole_water(tmp_path):
    part = ("Example Reservoir: West Causeway", "West Causeway", "Toxin", "8/18/2026")
    recs, *_ = W.build(feed(new("b1", S1, [part, A])), "2026-08-20T12:00:00Z", [])
    r = [x for x in recs if x["raw"].get("place") == "West Causeway"][0]
    assert r["raw"]["advisory_extent"] == "part_of_water" and r["lat"] is None
    assert "not known" in r["raw"]["placement_note"]
    st = _status(tmp_path, recs, datetime(2026, 8, 20, 13, tzinfo=timezone.utc))
    assert (st["waters"].get("example-reservoir-wy") or {}).get("status", "grey") == "grey"
    assert st["waters"]["example-lake-wy"]["status"] == "red"         # control: a whole-water advisory colours


def test_review_a_cell_with_a_title_or_house_number_is_scrubbed():
    row_ = ("Example Lake", "Dock of Dr. Example Person, 12-B Sample Road", "Bloom", "7/9/2026")
    recs, _, saved = build(new("b1", S1, [row_]))
    blob = json.dumps(recs) + json.dumps(saved)
    assert "Example Person" not in blob and "12-B" not in blob


# ---------------------------------------------------------------- Astra verification 2026-11-15 (last round)

def test_verify_an_unreadable_reread_of_a_good_bulletin_keeps_every_record():
    first, *_ = build(new("b1", S1, [A]), new("b2", S2, [A, B]))
    assert kid(B) in by_key(first)
    second, meta, _ = build(new("b1", S1, [A]), new("b2", S2, []), prev=first)
    by = by_key(second)
    assert kid(B) in by and by[kid(B)]["ended_at"] is None
    assert by[kid(B)]["raw"]["_listed_in"] == by_key(first)[kid(B)]["raw"]["_listed_in"]
    assert by[kid(A)]["ended_at"] is None and [u["bulletin"] for u in meta["unread"]] == ["b2"]
    # the next good read of b2 replaces it as before
    third, *_ = build(new("b1", S1, [A]), new("b2", S2, [A, B]), prev=second)
    assert by_key(third)[kid(B)]["raw"]["_listed_in"] == by_key(first)[kid(B)]["raw"]["_listed_in"]


def test_verify_a_later_omission_keeps_the_confirmed_interval():
    from build import status as S
    s_aug = "Tue, 04 Aug 2026 16:00:00 -0500"
    first, *_ = W.build(feed(new("b1", s_aug, [A, B])), "2026-11-15T12:00:00Z", [])
    assert by_key(first)[kid(A)]["raw"]["_last_seen_in_source"] == "2026-11-15T12:00:00Z"
    s_nov = "Mon, 16 Nov 2026 10:00:00 -0700"
    second, *_ = W.build(feed(new("b1", s_aug, [A, B]), new("b2", s_nov, [B])), "2026-11-16T18:00:00Z", first)
    r = by_key(second)[kid(A)]
    assert r["raw"]["ended_at_precision"] == "poll" and r["ended_at"] == "2026-11-16T17:00:00Z"
    assert r["raw"]["_last_seen_in_source"] == "2026-11-15T12:00:00Z"
    reds = [iv for iv in S.event_intervals(r, "WY", datetime(2026, 11, 17, tzinfo=timezone.utc))
            if iv["color"] == "red"]
    assert reds and max(iv["end"] for iv in reds) >= datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


# ---------------------------------------------------------------- go-live audit 2026-11-16 (fixes 1 to 3)

NOW_AUDIT = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)
S_OCT = "Wed, 28 Oct 2026 17:22:52 -0500"


def _audit_build(rows):
    recs, *_ = W.build(feed(new("b-oct", S_OCT, rows)), "2026-11-16T03:00:00Z", [])
    return recs


def _wy_waters():
    """Wyoming's own water records (data/waters-*.json with data/water-aliases.json merged), as the status build
    reads them."""
    from build import status as S
    return {k: w for k, w in S.load_waters().items() if w.get("state") == "WY"}


def _big(slug, name, x, y, km2=80.0, kind="reservoir"):
    ring = [[x, y], [x + 0.1, y], [x + 0.1, y + 0.1], [x, y + 0.1], [x, y]]
    return slug, {"slug": slug, "name": name, "kind": kind, "state": "WY", "area_km2": km2,
                  "bbox": [x, y, x + 0.1, y + 0.1], "geometry": {"type": "Polygon", "coordinates": [ring]}}


def test_audit_a_bloom_advisory_colours_its_large_reservoir_a_toxin_or_part_advisory_does_not(tmp_path):
    from build import status as S
    waters = dict([_big("big-reservoir-wy", "Big Reservoir", -107.0, 43.0),
                   _big("toxin-reservoir-wy", "Toxin Reservoir", -106.0, 43.0),
                   _big("part-reservoir-wy", "Part Reservoir", -105.0, 43.0)])
    assert all(w["area_km2"] > S.SMALL_WATER_KM2 for w in waters.values())
    rows = [("Big Reservoir", "Tamarask Campground", "Bloom", "7/13/2026"),
            ("Big Reservoir", "Brannon Campground", "Toxin", "10/16/2026"),
            ("Toxin Reservoir", "Diabase Marina", "Toxin", "10/14/2026"),
            ("Part Reservoir: West Causeway", "West Causeway", "Bloom", "9/30/2026")]
    recs = _audit_build(rows)
    ext = {(r["waterbody_text"], r["raw"]["advisory_type"]): r["raw"].get("advisory_extent") for r in recs}
    assert ext[("Big Reservoir", "Bloom")] == "named_water"
    assert ext[("Big Reservoir", "Toxin")] is None and ext[("Toxin Reservoir", "Toxin")] is None
    assert ext[("Part Reservoir", "Bloom")] == "part_of_water"
    st = _status(tmp_path, recs, NOW_AUDIT, waters)
    assert st["waters"]["big-reservoir-wy"]["status"] == "red"
    assert st["waters"]["toxin-reservoir-wy"]["status"] == "grey"
    assert st["waters"]["part-reservoir-wy"]["status"] == "grey"


def test_audit_a_bloom_advisory_on_a_river_is_never_for_the_whole_water():
    recs = _audit_build([("Wind River", "Lower Campground", "Bloom", "10/14/2026"),
                         ("Example Creek", "Shore", "Bloom", "8/1/2026")])
    assert all(r["raw"].get("advisory_extent") is None for r in recs)


def _real(tmp_path, rows):
    recs = _audit_build(rows)
    st = _status(tmp_path, recs, NOW_AUDIT, _wy_waters())
    return recs, st


def test_audit_boysen_pathfinder_and_flaming_gorge_show_red_under_their_bloom_advisories(tmp_path):
    rows = [("Boysen Reservoir", "Tamarask Campground", "Bloom", "7/13/2026"),
            ("Boysen Reservoir", "Brannon Campground", "Toxin", "10/16/2026"),
            ("Pathfinder Reservoir", "Bishops Point", "Bloom", "7/16/2026"),
            ("Flaming Gorge Reservoir", "Firehole Ramp", "Bloom", "9/4/2026")]
    recs, st = _real(tmp_path, rows)
    for slug in ("boysen-reservoir-wy", "pathfinder-reservoir-wy", "flaming-gorge-reservoir-wy"):
        assert st["waters"][slug]["status"] == "red", slug
    tox = [r for r in recs if r["raw"]["advisory_type"] == "Toxin"][0]
    assert st["placements"][tox["event_id"]]["water_slugs"] == ["boysen-reservoir-wy"]


def test_audit_bighorn_and_granite_go_to_their_own_waters_never_the_nhd_namesakes(tmp_path):
    rows = [("Bighorn Reservoir", "Horseshoe Bend Beach", "Bloom", "7/9/2026"),
            ("Granite Reservoir: West Causeway", "West Causeway", "Bloom", "9/30/2026")]
    recs, st = _real(tmp_path, rows)
    by = {r["waterbody_text"]: r for r in recs}
    assert st["placements"][by["Bighorn Reservoir"]["event_id"]]["water_slugs"] == ["bighorn-lake-wy"]
    assert st["waters"]["bighorn-lake-wy"]["status"] == "red"
    assert st["waters"].get("bighorn-reservoir-wy", {}).get("status", "grey") == "grey"
    assert st["placements"][by["Granite Reservoir"]["event_id"]]["water_slugs"] == ["granite-springs-reservoir-wy"]
    assert st["waters"]["granite-springs-reservoir-wy"]["status"] == "grey"       # a part, with no point: listed
    assert by["Granite Reservoir"]["event_id"] not in (st["waters"].get("granite-reservoir-wy") or {}).get(
        "event_ids", [])


def test_audit_glendo_wheatland_one_and_the_wind_river_are_placed(tmp_path):
    rows = [("Glendo Reservoir", "Custer Cove Campground", "Bloom", "7/16/2026"),
            ("Wheatland Reservoir #1", "Southwest Ramp", "Bloom", "7/16/2026"),
            ("Wind River", "Below Dam", "Toxin", "9/4/2026")]
    recs, st = _real(tmp_path, rows)
    by = {r["waterbody_text"]: r for r in recs}
    glendo = ["glendo-reservoir-wy", "glendo-reservoir-glendo-wy", "southern-glendo-reservoir-wy"]
    assert sorted(st["placements"][by["Glendo Reservoir"]["event_id"]]["water_slugs"]) == sorted(glendo)
    assert all(st["waters"][s]["status"] == "red" for s in glendo)
    assert st["placements"][by["Wheatland Reservoir #1"]["event_id"]]["water_slugs"] == \
        ["wheatland-number-1-reservoir-wy"]
    assert st["waters"]["wheatland-number-1-reservoir-wy"]["status"] == "red"
    assert st["placements"][by["Wind River"]["event_id"]]["water_slugs"] == ["wind-river-wy"]
    assert st["waters"]["wind-river-wy"]["status"] == "grey"             # reaches, not whole rivers: listed


def test_audit_the_two_wrong_nhd_records_are_dropped_by_hand_rulings_and_their_rows_follow():
    sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest import waters_from_nhd as N
    ring = [[-107.21, 44.52], [-107.20, 44.52], [-107.20, 44.53], [-107.21, 44.52]]
    rows = [{"slug": "bighorn-reservoir-wy", "name": "Bighorn Reservoir", "state": "WY", "gnis_id": "1598179",
             "kind": "reservoir", "geometry": {"type": "Polygon", "coordinates": [ring]}},
            {"slug": "granite-reservoir-wy", "name": "Granite Reservoir", "state": "WY", "gnis_id": "01589039",
             "kind": "reservoir", "geometry": {"type": "Polygon", "coordinates": [ring]}},
            {"slug": "other-reservoir-wy", "name": "Other Reservoir", "state": "WY", "gnis_id": "1",
             "kind": "reservoir", "geometry": {"type": "Polygon", "coordinates": [ring]}}]
    targets = [{"state": "WY", "name": "Bighorn Reservoir", "slugs": ["bighorn-reservoir-wy"]},
               {"state": "WY", "name": "Granite Reservoir", "slugs": ["granite-reservoir-wy"]}]
    acts = N.recheck_remainders(rows, targets, {}, "2026-11-16")
    assert [r["slug"] for r in rows] == ["other-reservoir-wy"]
    assert {a["slug"]: (a["action"], a["to"]) for a in acts} == {
        "bighorn-reservoir-wy": ("dropped", "bighorn-lake-wy"),
        "granite-reservoir-wy": ("dropped", "granite-springs-reservoir-wy")}
    assert targets[0]["slugs"] == ["bighorn-lake-wy"] and targets[1]["slugs"] == ["granite-springs-reservoir-wy"]
    assert "lay on" not in " ".join(targets[0]["notes"])


def test_registry_the_two_wrong_nhd_records_are_gone_from_the_file_and_their_names_point_to_the_agencies_waters():
    """The tidy and the names recheck run on 2026-11-16 (registry fix, job 1): data/waters-nhd.json no longer holds
    NHD's Bighorn Reservoir (GNIS 1598179) or Granite Reservoir (GNIS 1589039), its report-name rows name Bighorn Lake
    and Granite Springs Reservoir, and the names file says the same."""
    doc = json.loads((ROOT / "data" / "waters-nhd.json").read_text())
    wy = [w for w in doc["waters"] if w.get("state") == "WY"]
    assert not [w["slug"] for w in wy if w["slug"] in ("bighorn-reservoir-wy", "granite-reservoir-wy")
                or str(w.get("gnis_id") or "").lstrip("0") in ("1598179", "1589039")]
    rows = {t["name"]: t["slugs"] for t in doc["targets"] if t.get("state") == "WY" and t.get("from") == "reports"}
    assert rows["Bighorn Reservoir"] == ["bighorn-lake-wy"]
    assert rows["Granite Reservoir"] == ["granite-springs-reservoir-wy"]
    names = json.loads((ROOT / "research" / "wy" / "receiving-waters-missing.json").read_text())
    held = {r["name"]: r["slugs"] for r in names["resolved"]}
    assert held["Bighorn Reservoir"] == ["bighorn-lake-wy"] and held["Granite Reservoir"] == ["granite-springs-reservoir-wy"]
    assert "bighorn-reservoir-wy" not in json.dumps(names) and "granite-reservoir-wy" not in json.dumps(names)
