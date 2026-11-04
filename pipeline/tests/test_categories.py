"""docs/plan.md §2.z: sewage, beach advisories and algal blooms as categories on every status effect, history hour,
map feature, list row and count; the headline is the strongest sewage status. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from export import build as X  # noqa: E402
from tests.test_status import TEST_RULES, ev, iso, tmp_events, world  # noqa: E402

H = timedelta(hours=1)
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


def adv(rid, et, start_h, **kw):
    return ev(rid, event_type=et, status="advisory_active", started_at=iso(NOW - start_h * H),
              water_slugs=kw.pop("water_slugs", ["other-pond-ma"]), **kw)


def test_every_type_has_a_category():
    assert [S.category_of(t) for t in ("cso", "sso", "bypass", "blended", "plant_bypass", "unknown", "annual_total")] \
        == ["sewage"] * 7
    assert [S.category_of(t) for t in ("beach_advisory", "beach_closure", "shellfish_closure", "rain_advisory")] \
        == ["beach"] * 4
    assert S.category_of("hab_advisory") == "bloom" and S.category_of(None) == "sewage"


def test_a_water_with_only_a_bloom_advisory_reads_algal_bloom_advisory_and_its_hours_are_b():
    bloom = adv("b", "hab_advisory", 30)
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([bloom])))
    w = st["waters"]["other-pond-ma"]
    assert w["status"] == "red" and w["status_by_category"] == {"sewage": "grey", "beach": "grey", "bloom": "red"}
    assert w["headline"] == {"category": "bloom", "status": "red", "label": "Algal bloom advisory"}
    assert w["reasons"][0]["category"] == "bloom"
    assert hist["waters"]["other-pond-ma"][-31:] == "B" * 31 and hist["waters"]["other-pond-ma"][-32] == "g"   # 30 h + this hour
    assert hist["intervals"]["other-pond-ma"][0][5] == "bloom"
    assert st["counts"]["waters_by_category"]["bloom"] == {"red": 1}
    assert st["counts"]["events_by_category"] == {"bloom": 1}


def test_sewage_comes_first_in_the_headline_the_card_and_the_hour_letters():
    beach = adv("beach", "beach_advisory", 40)
    bloom = adv("bloom", "hab_advisory", 40)
    sewage = ev("cso", water_slugs=["other-pond-ma"], status="ended", started_at=iso(NOW - 20 * H),
                ended_at=iso(NOW - 19 * H), advice_window_hours=0)            # no red window: yellow caution now
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([beach, bloom, sewage])))
    w = st["waters"]["other-pond-ma"]
    assert w["status"] == "red"                                         # the strictest colour on the water, as before
    assert w["status_by_category"] == {"sewage": "yellow", "beach": "red", "bloom": "red"}
    assert w["headline"] == {"category": "sewage", "status": "yellow", "label": None}
    assert [r["category"] for r in w["reasons"]] == ["sewage", "beach", "bloom"]
    assert w["reason_short"] == w["reasons"][0]["short"]
    strip = hist["waters"]["other-pond-ma"]
    assert strip[-41:-21] == "R" * 20                                   # beach red before bloom with no sewage status
    assert strip[-21] == "r" and strip[-20:] == "y" * 20                # sewage outranks both
    # the site's precedence r > y > u > R > Y > B > m > g: a beach caution (yellow) hour is Y above a bloom's B
    unconfirmed = ev("u", event_type="beach_advisory", status="unknown", started_at=iso(NOW - 10 * H),
                     water_slugs=["other-pond-ma"])
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([bloom, unconfirmed])))
    assert hist["waters"]["other-pond-ma"][-11:] == "Y" * 11 and hist["waters"]["other-pond-ma"][-12] == "B"
    assert st["waters"]["other-pond-ma"]["headline"]["category"] == "beach"
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([unconfirmed])))
    assert hist["waters"]["other-pond-ma"][-11:] == "Y" * 11 and hist["waters"]["other-pond-ma"][-12] == "g"
    assert st["waters"]["other-pond-ma"]["headline"]["label"] == "Beach advisory"


def test_effects_points_features_and_records_carry_the_category():
    point = adv("p", "beach_closure", 5, water_slugs=["test-bay-ma"], lat=42.05, lon=-70.95)
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([point])))
    ap = st["advisory_points"][0]
    assert ap["category"] == "beach" and hist["points"][ap["event_id"]][-6:] == "R" * 6
    effects, active = defaultdict(list), defaultdict(list)
    X.point_effects(st, effects, active)
    assert effects[ap["event_id"]][0]["category"] == "beach" and active[ap["event_id"]][0]["category"] == "beach"
    w = st["waters"]["test-bay-ma"]
    assert w["status_by_category"]["beach"] == "grey"                    # a point on a bay, not the bay's fill
    src = Path(X.__file__).read_text()
    for needle in ('"category": (w.get("headline") or {}).get("category") or "sewage"', '"status_by_category": w.get(',
                   'rec["category"] = status_mod.category_of(', '"events_by_category"', '"waters_by_category"',
                   '"properties": {"category": "sewage",', 'for frm, until, color, rule, eid, *rest in ivs'):
        assert needle in src, needle


def test_every_csv_row_carries_its_category(tmp_path, monkeypatch):
    import csv as std_csv
    from common import event
    from export import csv as C
    monkeypatch.setattr(S, "_STATES", {"MA"})
    rows = []
    for rid, et, st in (("1", "cso", "ended"), ("2", "beach_closure", "advisory_active"), ("3", "hab_advisory", "advisory_active")):
        e = event(source_id="ma-test", source_record_id=rid, event_type=et, status=st, started_at="2026-10-20T10:00:00-04:00",
                  npdes_permit="MA0101613", water_slugs=[])
        e["fixture"] = False
        rows.append(e)
    rows[1]["category"] = "beach"                       # the export's own field wins; else it is derived from the type
    C.write_csvs(rows, [], [], tmp_path / "csv", page_ids=set(), as_of="2026-11-03T12:00:00Z")
    with (tmp_path / "csv" / "all-reports-2026.csv").open(newline="", encoding="utf-8") as f:
        got = {r["record_id"]: r["category"] for r in std_csv.DictReader(f)}
    assert got == {"1": "sewage", "2": "beach", "3": "bloom"}
    assert C.COLUMNS.index("category") == C.COLUMNS.index("event_type") + 1


def test_a_bloom_advisory_heads_a_water_above_a_monthly_mark():
    from tests.test_monthly_mark import month_rec
    now = datetime(2026, 11, 3, 12, tzinfo=UTC)
    sep = month_rec("sep", "2026-09", water_slugs=["other-pond-ma"])
    bloom = ev("b", event_type="hab_advisory", status="advisory_active", started_at=iso(now - 30 * H),
               water_slugs=["other-pond-ma"])
    st, hist = S.build(now=now, write=False, **world(tmp_events([sep, bloom])))
    w = st["waters"]["other-pond-ma"]
    assert w["status_by_category"]["sewage"] == "monthly" and w["status_by_category"]["bloom"] == "red"
    assert w["headline"] == {"category": "bloom", "status": "red", "label": "Algal bloom advisory"}
    assert w["reasons"][0]["category"] == "bloom" and w["reason_short"] == w["reasons"][0]["short"]
    assert hist["waters"]["other-pond-ma"][-1] == "B"
    order = [S.precedence(c, s) for c, s in (("sewage", "red"), ("sewage", "yellow"), ("sewage", "unresolved"),
                                             ("beach", "red"), ("beach", "yellow"), ("bloom", "red"),
                                             ("sewage", "monthly"), ("sewage", "grey"))]
    assert order == sorted(order) and len(set(order)) == 8
