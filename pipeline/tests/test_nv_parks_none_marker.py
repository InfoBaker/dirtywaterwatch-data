"""Nevada State Parks HAB page: the explicit empty marker "None" and the real page as the pipeline runner read it at
2026-11-16T01:45Z (run 43788047052; tests/fixtures/nv_state_parks_hab_2026-11-16.html: the advisory accordion and the
passport block after it, unchanged; no person named). Watch lists Rye Patch and Wild Horse ("WIld Horse" on the page),
Warning lists Lahontan ("(updated November 2, 2026)", lower case), Danger reads "None"."""
import json
import re
from pathlib import Path

import pytest

from ingest import nv_state_parks_hab as P

FIX = Path(__file__).parent / "fixtures"
NOV26 = (FIX / "nv_state_parks_hab_2026-11-16.html").read_text()
AUG26 = (FIX / "nv_state_parks_hab_2026-08-13.html").read_text()
READ = "2026-11-16T01:45:00Z"
DANGER_NONE = "<p>None</p>"


def _danger(body: str) -> str:
    assert NOV26.count(DANGER_NONE) == 1
    return NOV26.replace(DANGER_NONE, body)


def test_the_real_page_reads_to_exactly_three_advisories():
    items, saved = P.parse(NOV26)
    assert [(i["level"], i["water"], i["heading"], i["updated"]) for i in items] == [
        ("Watch", "Rye Patch Reservoir", "Rye Patch State Recreation Area", "2026-10-05"),
        ("Watch", "Wild Horse Reservoir", "Wild Horse State Recreation Area", "2026-10-05"),
        ("Warning", "Lahontan Reservoir", "Lahontan State Recreation Area", "2026-11-02"),
    ]
    assert "downgraded to a Harmful Algal Bloom (HAB) WARNING Advisory" in items[2]["text"]
    assert not any(i.get("sentences_withheld") for i in items)
    assert json.loads(saved)["levels"]["Danger"] == []


def test_the_real_page_builds_records_that_start_at_the_read_never_at_the_update_date():
    recs, meta = P.build(NOV26, READ, [])
    assert meta["by_level"] == {"Watch": 2, "Warning": 1, "Danger": 0} and meta["opened"] == 3
    by = {r["waterbody_text"]: r for r in recs}
    assert set(by) == {"Rye Patch Reservoir", "Wild Horse Reservoir", "Lahontan Reservoir"}
    for name, level, updated in [("Rye Patch Reservoir", "Watch", "2026-10-05"),
                                 ("Wild Horse Reservoir", "Watch", "2026-10-05"),
                                 ("Lahontan Reservoir", "Warning", "2026-11-02")]:
        r = by[name]
        assert r["status"] == "advisory_active" and r["raw"]["level"] == level
        assert r["started_at"] == READ and r["time_precision"] == "poll"      # never the update date (lesson 8)
        assert r["source_updated_at"] == updated and r["raw"]["updated_date"] == updated
        assert r.get("ended_at") is None
        assert r["lat"] is not None and r["coord_source"] in ("gnis", "nhd")   # each a known water with its point
    # the page's "WIld Horse" is the known water: its county and GNIS point, not a name-only placement
    wh = by["Wild Horse Reservoir"]["raw"]
    assert wh["county"] == "Elko County" and "placement_note" not in wh


@pytest.mark.parametrize("marker", ["<p>None</p>", "<p>None.</p>", "<p>none at this time</p>", "<p>NONE AT THIS TIME.</p>",
                                    "<p>None at this time.</p>", "<p>&nbsp;None&nbsp;</p>"])
def test_the_explicit_marker_in_any_form_lists_no_water(marker):
    items, _ = P.parse(_danger(marker))
    assert len(items) == 3 and not [i for i in items if i["level"] == "Danger"]


@pytest.mark.parametrize("body", ["", "<p>&nbsp;</p>", "<p>Nothing to report</p>", "<p>None reported yet</p>",
                                  "<p>Nonetheless, check back</p>", "<p>None</p><p>Check back soon</p>",
                                  "<p>See the state dashboard</p>"])
def test_a_blank_or_unreadable_section_fails_the_read(body):
    with pytest.raises(ValueError, match="Danger"):
        P.parse(_danger(body))


def test_the_marker_beside_a_listed_water_fails_the_read():
    page = NOV26.replace("<p><strong>Lahontan State", "<p>None</p><p><strong>Lahontan State", 1)
    with pytest.raises(ValueError, match="Warning"):
        P.parse(page)


def test_the_danger_section_ends_before_the_passport_block():
    found = {m.group(1): P.text_of(m.group(2)) for m in P.SECTION.finditer(NOV26)}
    assert found["Danger"] == "None" and "Passport" not in found["Danger"]


def test_a_failed_read_after_the_real_page_lifts_and_greys_nothing(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(P, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    good, meta = P.build(NOV26, READ, [])
    common.write_events(P.SOURCE_ID, good, meta=meta, path=tmp_path / f"{P.SOURCE_ID}.json")
    for i, body in enumerate(["", "<p>Check back soon</p>"]):
        page = tmp_path / f"bad{i}.html"
        page.write_text(_danger(body))
        assert P.main(["--file", str(page)]) == 1
        doc = json.loads((tmp_path / f"{P.SOURCE_ID}.json").read_text())
        assert doc["ok"] is False and doc["count"] == 3
        assert all(r["status"] == "advisory_active" and not r.get("ended_at") for r in doc["records"])


def test_the_earlier_archive_pages_still_read_the_same():
    items, _ = P.parse(AUG26)
    assert len(items) == 4 and {i["level"] for i in items} == {"Watch"}
    # "None at this time." in Warning and Danger, as before
    assert re.search(r"None at this time\.", AUG26)
