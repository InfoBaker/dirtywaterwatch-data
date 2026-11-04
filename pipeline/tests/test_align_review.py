"""scripts/align-discharger-ids.py: ids left on purpose (no operator in the text), the review file that keeps its
hand-settled sections across a rewrite, and the record of the 2026-11-03 pass over the ids with fewer than 10 events
(every id in that record is a registry row, a registry alias, or on the left-on-purpose list).
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import pytest
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import DATA_DIR, ROOT  # noqa: E402

_spec = importlib.util.spec_from_file_location("align_discharger_ids", ROOT / "scripts" / "align-discharger-ids.py")
A = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(A)

REVIEW = ROOT / "docs" / "reviews" / "2026-11-02-discharger-id-review.md"


def row(rid, name, state, permit=None, aliases=None):
    return {"id": rid, "name": name, "state": state, "kind": "sso", "npdes_permit": permit,
            "npdes_permits": [permit] if permit else [], "receiving_waters": [], "water_slugs": [], "outfall_count": None,
            "outfalls_source": None, "notification_channel": None, "notification_feed_machine_readable": None,
            "notification_signup_url": None, "towns": [], "notes": "", "verified": False, "checked": "2026-11-03",
            "aliases": [rid] if aliases is None else aliases, "source_areas": [state.lower()]}


def ev(eid, did, name=None, permit=None):
    return {"event_id": eid, "event_type": "sso", "discharger_id": did, "discharger_name": name, "npdes_permit": permit}


def test_an_id_on_the_left_on_purpose_list_is_neither_matched_nor_given_a_row():
    # a registry row of that very name would otherwise match it: the list wins
    reg = [row("ct-some-row", "Reporting Utility", "CT")]
    events = [ev("1", "ct-reporting-utility", "Reporting Utility"), ev("2", "ct-reporting-utility", "Reporting Utility"),
              ev("3", "ct-zzz-test-scotland", "ZZZ - TEST - SCOTLAND")]
    plan = A.align(events, reg, {}, "2026-11-03")
    assert [plan[k] for k in A.CATEGORIES] == [[], [], [], []]
    assert [(x["orphan"], x["events"], x["reason"]) for x in plan["left"]] == [
        ("ct-reporting-utility", 2, "placeholder"), ("ct-zzz-test-scotland", 1, "test")]


def test_the_left_on_purpose_ids_are_orphans_of_no_registry_row_and_have_one_word_reasons():
    rows = json.loads((DATA_DIR / "dischargers.json").read_text())
    known = A.known_ids(rows)
    assert A.LEFT_ON_PURPOSE and not set(A.LEFT_ON_PURPOSE) & known
    assert all(re.fullmatch(r"[a-z]+", r) for r in A.LEFT_ON_PURPOSE.values())
    assert all(re.match(r"[a-z]{2}-", i) for i in A.LEFT_ON_PURPOSE)


def test_review_text_lists_the_left_ids_with_their_reason_and_withholds_a_personal_name(monkeypatch):
    monkeypatch.setitem(A.LEFT_ON_PURPOSE, "ny-example-plant", "person")        # a stand-in id, not a real one
    plan = A.align([ev("1", "ny-example-plant", "SOME NAME WPCF"), ev("2", "vt-privately-owned", "Privately Owned")],
                   [], {}, "2026-11-03")
    text = A.review_text(plan, "2026-11-03")
    assert "- Left on purpose (no operator in the text): 2 ids, 2 events." in text
    assert "| `vt-privately-owned` | 1 | VT | Privately Owned | placeholder |" in text
    assert "| `ny-example-plant` | 1 | NY | withheld | person |" in text and "SOME NAME" not in text
    assert "## Unmatched" in text and "None." in text


def test_summary_has_a_left_line_only_when_ids_were_left_and_the_total_includes_it():
    plan = A.align([ev("1", "ct-zzz-test-scotland", "x"), ev("2", "ct-reporting-utility", "y"),
                    ev("3", "ct-west-haven", "WEST HAVEN")], [], {}, "2026-11-03")
    lines = A.summary(plan).splitlines()
    assert lines[5].split() == ["unmatched", "1", "1"] and lines[6].split() == ["left", "2", "2"]
    assert lines[-1].split() == ["total", "3", "3"]


def test_the_settled_sections_survive_a_rewrite_and_the_rewrite_changes_nothing_more():
    plan = A.align([ev("1", "ct-zzz-test-scotland", "x")], [], {}, "2026-11-03")
    settled = ("## Settled on 2026-11-03: a pass\n\nSome words.\n\n| id |\n|---|\n| `a` |\n\n"
               "## Settled on 2026-11-03: another pass\n\nMore words.")
    first = A.review_text(plan, "2026-11-03", settled)
    assert settled in first
    assert first.index("## Settled") < first.index("## Left on purpose") < first.index("## Ambiguous") < first.index("## Unmatched")
    assert A.settled_sections(first) == settled                       # read back exactly
    assert A.review_text(plan, "2026-11-03", A.settled_sections(first)) == first
    assert A.settled_sections("# no settled section here\n\n## Ambiguous\n\nNone.\n") == ""


def test_the_review_file_on_disk_has_its_settled_sections_and_every_id_in_them_is_placed():
    if not REVIEW.exists():
        pytest.skip("docs/reviews/ is not in this repository (the review lives with the site)")
    text = REVIEW.read_text()
    settled = A.settled_sections(text)
    assert settled.startswith("## Settled on 2026-11-03: ids with 10 or more events")
    assert "## Settled on 2026-11-03: ids with fewer than 10 events" in settled
    rows = json.loads((DATA_DIR / "dischargers.json").read_text())
    known = A.known_ids(rows)
    by_id = {r["id"]: r for r in rows}
    section = settled.split("## Settled on 2026-11-03: ids with fewer than 10 events", 1)[1]
    ids, aliased = [], {}
    for line in section.splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if line.startswith("| `") and re.fullmatch(r"[a-z]{2}-[a-z0-9-]+", cells[0]):
            ids.append(cells[0])
            if re.fullmatch(r"[a-z]{2}-[a-z0-9-]+", cells[1]):             # the two "Aliased to" tables
                aliased[cells[0]] = cells[1]
    assert len(ids) == len(set(ids)) >= 300                              # 336 ids, one line each
    assert [i for i in ids if i not in known] == [], "an id in the record has no row and no alias"
    assert [i for i in A.LEFT_ON_PURPOSE if i in ids] == []              # the left ones are in their own table
    for orphan, target in aliased.items():
        assert target in by_id and orphan in by_id[target]["aliases"], (orphan, target)


def test_rows_created_in_the_second_pass_have_the_shape_of_the_first_pass_rows():
    rows = json.loads((DATA_DIR / "dischargers.json").read_text())
    made = [r for r in rows if r.get("checked") == "2026-11-03" and r.get("verified") is False]
    assert len(made) >= 400                                              # 92 from the first pass, 320 from the second
    first = next(r for r in made if r["id"] == "ct-west-haven")
    for r in made:
        assert [k for k in r if k != "short_name"] == [k for k in first if k != "short_name"], r["id"]
        assert r["aliases"][0] == r["id"] and r["source_areas"] == [r["id"][:2]] and r["state"] == r["id"][:2].upper()
        assert r["notes"].startswith("Row made from the feed's own facility name") and r["notes"].endswith("Not verified.")
        assert r["towns"] == [] and r["receiving_waters"] == [] and r["water_slugs"] == []
        assert (r["npdes_permit"] is None) == (not r["npdes_permits"])
        if len(r["name"]) > 30:
            assert r.get("short_name") and len(r["short_name"]) <= len(r["name"]), r["id"]
        else:
            assert "short_name" not in r, r["id"]
    # no permit is the permit of two rows
    claims: dict[str, list[str]] = {}
    for r in rows:
        for p in r.get("npdes_permits") or []:
            claims.setdefault(p, []).append(r["id"])
    assert {p: v for p, v in claims.items() if len(v) > 1} == {}
