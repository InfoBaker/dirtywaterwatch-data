"""Kentucky's operator rows, register rows, rules row, state text and missing-waters list: every Kentucky permit in one
row, Louisville MSD's and SD1's own channels, the combined sewer permittees named, no individual named, the law cited,
the page in the site's shape."""
import json
import re
from collections import Counter
from pathlib import Path

from ingest import dischargers_schema as DS

ROOT = Path(__file__).resolve().parents[2]


def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "KY"]


def register():
    return json.loads((ROOT / "data" / "notice-channels" / "ky.json").read_text())["channels"]


def test_every_kentucky_permit_is_in_exactly_one_row():
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "KY"}
    cso = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-us.json").read_text())["outfalls"]
           if str(r.get("npdes_permit")).startswith("KY")}
    cand = json.loads((ROOT / "research" / "ky" / "private-utilities-candidates.json").read_text())
    wanted = plants | cso | {c["npdes_permit"] for c in cand["candidates"]}
    assert all(every[p] == 1 for p in wanted), [p for p in wanted if every[p] != 1]
    assert wanted <= {p for r in ops() for p in r["npdes_permits"]}


def test_the_main_operators_hold_their_permits_and_the_research_ids():
    by = {r["id"]: r for r in ops()}
    msd, sd1 = by["ky-louisville-msd"], by["ky-sd1"]
    assert {"KY0022411", "KY0022420", "KY0098540", "KY0102784"} <= set(msd["npdes_permits"])
    assert msd["kind"] == "cso" and "louisvillemsd.org/overflowalert" in msd["notification_channel"]
    assert set(sd1["npdes_permits"]) == {"KY0021466", "KY0105031", "KY0107239"} and "0.25 inch" in sd1["notification_channel"]
    assert sd1["notification_signup_url"].startswith("https://sd1.org/218")
    assert set(by["ky-lfucg"]["npdes_permits"]) == {"KY0021491", "KY0021504"} and "ky-lexington-lfucg" in by["ky-lfucg"]["aliases"]
    research = [r["id"] for r in json.loads((ROOT / "research" / "ky" / "dischargers.json").read_text())]
    aliases = {a for r in ops() for a in r["aliases"]}
    assert set(research) <= aliases
    assert sum(1 for r in ops() if r["kind"] == "cso") == 13


def test_legal_forms_are_controlled_and_no_individual_is_named():
    rows = ops()
    assert all(r["legal_form"] in DS.LEGAL_FORMS or r["legal_form"] is None for r in rows)
    removed = next(r for r in rows if "KYP000089" in r["npdes_permits"])
    assert removed["legal_form"] == "facility (permittee not named)"
    from common import NAME_REMOVED, scrub_discharger
    assert all(scrub_discharger({"discharger_name": r["name"]})["discharger_name"] != NAME_REMOVED for r in rows)


def test_register_rows_per_operator_and_the_operators_own_channels():
    reg = {c["id"]: c for c in register()}
    for r in ops():
        row = reg[f"{r['id']}-division-notice"]
        assert row["basis_kind"] == "law" and "401 KAR 5:065" in row["legal_basis"] and row["barrier"] == "phone_only"
        assert row["permit"] in r["npdes_permits"]
    assert reg["ky-louisville-msd-overflow-advisory"]["feed_source_id"] == "ky-louisville-msd-overflow-advisory"
    assert reg["ky-dow-hab-viewer"]["feed_source_id"] == "ky-dow-hab-viewer"
    assert reg["ky-epa-echo-overflow-events"]["feed_source_id"] == "echo-sewer-overflow"
    assert reg["ky-sd1-wet-weather-notification"]["barrier"] == "no_web_page"
    assert reg["ky-sd1-cso-signs"]["barrier"] == "signs_only"
    assert reg["ky-orsanco-bacteria"]["barrier"] == "bot_wall"
    swim = reg["ky-dow-swimming-advisories"]
    assert swim["feed_source_id"] == "ky-dow-swimming-advisories" and swim["barrier"] is None   # review P1-1
    assert not re.search(r"\b\d{3}[-.]\d{3}[-.]\d{4}\b", json.dumps([c.get("note") for c in register()]))


def test_rules_row_and_sd1s_rain_rule():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    ky = rules["red"]["by_state"]["KY"]
    assert ky["hours"] is None and "401 KAR 5:065" in ky["source"] and "is not shown on this site" in ky["basis"]
    assert not re.search(r"\b(safe|clean)\b", ky["basis"], re.I)
    sd1 = rules["rain_likely"]["fallback"]["by_permit"]["KY0021466"]
    assert sd1["inches"] == 0.25 and sd1["tail_hours"] == 72 and sd1["months"] == [5, 6, 7, 8, 9, 10]
    assert "0.25 inches" in sd1["basis"] and "sd1.org" in sd1["source"]


def test_state_text_is_in_the_page_shape_and_says_what_the_site_does():
    t = (ROOT / "research" / "ky" / "state-text.md").read_text()
    assert t.startswith("---\nstate: KY\nname: Kentucky\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "is not shown on this site" in t and "not searched one by one" in t and "Central time" in t
    assert not re.search(r"\b\d{3}[-.]\d{3}[-.]\d{4}\b", t)


def test_missing_waters_list_leaves_out_what_the_national_list_holds():
    d = json.loads((ROOT / "research" / "ky" / "receiving-waters-missing.json").read_text())
    names = {r["name"] for r in d["rows"]}
    done = {r["name"] for r in d.get("resolved") or []}
    assert d["state"] == "KY" and "Banklick Creek" not in names and "Ohio River" not in names
    assert not {"Unnamed", "Unnamed Tributary Or Unknown", "Unnamed Tributary or Unknown"} & names
    # a name the batch's names pass resolved moves to "resolved" (final audit 2026-11-08 P1-2): either is right
    assert "Old Springfield Reservoir" in names and "Brashears Creek" in names | done
    assert not names & done
    by = {r["name"]: r for r in d["rows"]}
    # MSD's outfalls off the Ohio by EPA's reach index (final audit 2026-11-08 P2-1): on the list with their outfall
    # counts and reach codes until a names pass builds the record, then under "resolved" with its record (re-check)
    for name in ("Beargrass Creek", "South Fork Beargrass Creek", "Middle Fork Beargrass Creek", "Mill Creek"):
        assert name in names | done, name
        if name in by:
            assert by[name]["outfalls"] and by[name]["reach_ids"] and by[name]["gnis_ids"] and by[name]["counties"] == ["Jefferson"]
        else:
            assert next(r for r in d["resolved"] if r["name"] == name).get("slugs")
    if "South Fork Beargrass Creek" in by:
        assert by["South Fork Beargrass Creek"]["outfalls"] == 41 and by["Mill Creek"]["gnis_ids"] == ["498252"]


def test_operators_are_never_named_after_a_plant():
    """Review 2026-11-08 P2-5: 'City of Jerry L Riley', 'City of Russell County', 'City of Fort Knox' and others."""
    places = json.loads((ROOT / "data" / "reference" / "ky-census-places.json").read_text())["places"]
    rows = ops()
    for r in rows:
        m = re.match(r"^City of ([^(]+?)(?: \(|$)", r["name"])
        if r["legal_form"] == "city" and m:
            assert m.group(1) in places, r["name"]
    names = {r["name"] for r in rows}
    assert not {"City of Jerry L Riley", "City of Russell County", "City of Fort Knox", "City of Bardstown Town Creek",
                "City of Muddy Creek", "City of Bee Creek"} & names
    by = {r["id"]: r for r in rows}
    assert set(by["ky-city-of-bardstown"]["npdes_permits"]) == {"KY0021237", "KY0104027"}
    assert by["ky-fort-knox"]["legal_form"] == "federal facility"
    assert not any("Riley" in json.dumps(r) for r in rows)
    assert all("Morris Forman" not in r["notes"] for r in rows)


def test_each_cso_permittee_has_a_permit_row_that_says_the_clause_was_not_read():
    """Review 2026-11-08 P2-7."""
    reg = {c["id"]: c for c in register()}
    cso = [r for r in ops() if r["kind"] == "cso"]
    assert len(cso) == 13
    for r in cso:
        row = reg[f"{r['id']}-cso-permit-notice"]
        assert row["basis_kind"] == "permit" and "not read" in row["legal_basis"] and row["barrier"] == "not_verified"
    t = (ROOT / "research" / "ky" / "state-text.md").read_text()
    assert "under their consent decrees" not in t and "terms were not read" in t


def test_state_text_says_what_the_data_shows():
    """Review 2026-11-08 P2-8 and P1-1."""
    t = (ROOT / "research" / "ky" / "state-text.md").read_text()
    assert "a report that names no water and does not say one was reached" in t
    assert "289 open outfalls in the U.S. Environmental Protection Agency's national inventory (October 31, 2026" in t
    assert "standing swimming advisories are shown as the agencies' own" in t


def test_collection_system_permits_are_no_outfalls_and_no_row_names_a_person():
    """Final audit 2026-11-08 P2-4 and P3-8."""
    from common import load_outfall_registry
    rows = [o for o in load_outfall_registry(provisional=False) if o.get("state") == "KY"]
    kyp = [o for o in rows if str(o["npdes_permit"]).startswith("KYP")]
    assert kyp and all(o["outfall_kind"] == "other" for o in kyp) and len(kyp) == 56
    counted = [o for o in rows if o["outfall_kind"] != "other" and not str(o.get("outfall_status") or "").upper().startswith("CLS")]
    assert len(counted) == 617
    bard = next(o for o in rows if o["npdes_permit"] == "KY0104027")
    assert bard["outfall_kind"] == "plant" and "Riley" not in json.dumps(bard)
    reg = {c["permit"] for c in register() if c.get("permit")}
    assert {o["npdes_permit"] for o in kyp} <= reg | {p for r in ops() for p in r["npdes_permits"]}


def test_the_state_text_says_the_advisories_are_marked_where_they_are():
    t = (ROOT / "research" / "ky" / "state-text.md").read_text()
    assert "as a marker on each stretch or water the page names" in t and "rather than drawn" not in t


def test_msds_outfalls_take_their_own_reach_before_the_permit_level_label():
    """Final audit 2026-11-08 P2-1: once the NHD builder has made Beargrass Creek from the outfall's reach code, the
    reach decides for KY0022411, not EPA's one label 'OHIO RIVER'; any other permit keeps the name first."""
    from ingest import outfall_waters as OW

    class Stub:
        def clear_row(self):
            pass

        def by_reach(self, o, text):
            return ("beargrass-creek-ky", "reach") if o.get("reach_id") == "5140101000472" else (None, None)

        def usable(self, s, o, step):
            return True

        def by_name(self, o, text):
            return "ohio-river-ky", "name"

        def dist(self, s, lat, lon):
            return 50.0

        by_nhd_target = by_builder_permit = lambda self, o, text: (None, None)
    o = {"npdes_permit": "KY0022411", "outfall": "108", "receiving_water_echo": "OHIO RIVER", "reach_id": "5140101000472",
         "state": "KY", "lat": 38.24, "lon": -85.7}
    assert OW.Matcher.match(Stub(), o)["slug"] == "beargrass-creek-ky"
    assert OW.Matcher.match(Stub(), {**o, "npdes_permit": "KY0021466"})["slug"] == "ohio-river-ky"
    assert OW.Matcher.match(Stub(), {**o, "reach_id": "5140101000008"})["slug"] == "ohio-river-ky"


def test_msds_outfalls_take_the_reachs_own_name_near_their_point():
    """Re-check 2026-11-08: the builder's Beargrass Creek record carries no reach code, so all 121 outfalls stayed on the
    Ohio River; the reach's GNIS name, placed at the outfall's point and taken within 400 m, now decides. Hardin
    County's Mill Creek, 37 km off, is not Louisville's."""
    from ingest import outfall_waters as OW

    class Stub:
        def clear_row(self):
            pass

        def by_reach(self, o, text):
            return None, None

        def usable(self, s, o, step):
            return True

        def by_name(self, o, text):
            return {"South Fork Beargrass Creek": ("south-fork-beargrass-creek-ky", "name"),
                    "Mill Creek": ("mill-creek-ky", "name")}.get(text, ("ohio-river-ky", "name"))

        def dist(self, s, lat, lon):
            return {"south-fork-beargrass-creek-ky": 35.0, "mill-creek-ky": 37000.0}.get(s, 2300.0)

        by_nhd_target = by_builder_permit = lambda self, o, text: (None, None)
    o = {"npdes_permit": "KY0022411", "outfall": "108", "receiving_water_echo": "OHIO RIVER", "reach_id": "5140101000472",
         "state": "KY", "lat": 38.24, "lon": -85.7}
    hit = OW.Matcher.match(Stub(), o)
    assert hit["slug"] == "south-fork-beargrass-creek-ky" and hit["step"] == "reach name" and "503905" in hit["how"]
    assert OW.Matcher.match(Stub(), {**o, "reach_id": "5140101000484"})["slug"] == "ohio-river-ky"
    assert OW.Matcher.match(Stub(), {**o, "npdes_permit": "KY0021466"})["slug"] == "ohio-river-ky"
