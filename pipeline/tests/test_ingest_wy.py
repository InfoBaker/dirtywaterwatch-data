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
    assert r["raw"]["_last_seen_in_source"] == "2026-08-11T21:00:00Z" and r["raw"]["time_zone"] == "America/Denver"
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
