"""scripts/gen_source_tally.py: a small fixture project in, docs/source-tally.md out; checks the twelve sections in their
fixed order, the counts in the summary table and in each section, the owner links, the water-record block, the scrubbing
of names and emails, the missing-register path, and that nothing under out/ is written."""
import importlib.util
import json
import re
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen_source_tally.py"
_spec = importlib.util.spec_from_file_location("gen_source_tally", SCRIPT)
T = importlib.util.module_from_spec(_spec)
sys.modules["gen_source_tally"] = T
_spec.loader.exec_module(T)

NOW = "2026-11-03T12:00:00Z"
ORDER = ["CT", "MA", "ME", "NH", "RI", "VT", "NJ", "NY", "PA", "DC", "MD", "VA"]


def w(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj))


def row(id, status, jur, role, access=("html",), url="https://example.org/x", name=None, reason="Reason one. Second.", **kw):
    return {"id": id, "name": name or id, "jurisdiction": jur, "operator": kw.pop("operator", "An Operator"), "role": role,
            "access": list(access), "url": url, "status": status, "status_reason": reason, "notes": "", "access_detail": "",
            "machine_readable": kw.pop("machine_readable", False), "history": kw.pop("history", None), "area": "x", **kw}


def ev(eid, state, slugs=(), text=None, **kw):
    return {"event_id": eid, "source_id": "s", "event_type": "cso", "state": state, "water_slugs": list(slugs),
            "waterbody_text": text, "category": "sewage", "fixture": False, **kw}


def water(slug, name, state, towns, **kw):
    return {"slug": slug, "name": name, "kind": "river", "state": state, "towns": towns, "bbox": [0, 0, 1, 1], **kw}


GEOM = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}


def make_project(root: Path, register=None, draft=None):
    w(root / "docs/source-checklist.json", [
        row("ma-signup", "candidate", "MA", "events", ["email"], "https://example.org/signup/ma-list",
            name="City of Alpha sewage alerts", operator="City of Alpha",
            reason="Official list. Contact: Jane Roe, Clerk, 555-123-4567. Write to jroe@alpha.example or ask Jane Roe."),
        row("ct-rejected", "rejected", "CT", "news"),
        row("nhdes-healthy-swimming-mapper-beaches", "candidate", "NH", "advisories", ["arcgis"], machine_readable=True),
        row("multi", "candidate", "CT,MA", "monitoring", ["api"], machine_readable=True, history="2020 on"),
        row("vt-blocked", "unreachable", "VT", "advisories", reason="Cloudflare blocks scripts (403)."),
        row("ma-used", "used", "MA", "events"),
        row("ma-collected", "candidate", "MA", "events"),
        row("us-science", "candidate", "US", "science"),
        row("ct-nourl", "watch", "CT", "monitoring", url=""),
        row("ct-law", "watch", "CT", "law"),
        row("ct-ecoli", "candidate", "CT", "monitoring", reason="Holds the receiving-water E. coli model results. More text.")])
    w(root / "data/sources/ma-feed-a.yaml", 'id: "ma-feed-a"\nname: "Feed A name"\nrole: "events"\nevent_types: ["cso", "sso"]\n'
                                            'states: ["MA"]\nenabled: true\nurl: "https://example.org/a"\n')
    w(root / "data/sources/ct-extra.yaml", 'id: "ct-extra"\nname: "CT extra registry row"\nrole: "monitoring"\n'
                                           'states: ["CT"]\nenabled: true\nurl: "https://example.org/e"\naccess: ["csv"]\n')
    feed = lambda sid, **k: {"source_id": sid, "ok": True, "last_ok_at": "2026-11-03T10:00:00Z", "count": 5, "stale": False,
                             "expected_cadence_hours": 6.0, "registry_ids": [], "fixture": False, **k}
    w(root / "out/sources.json", {"built": "2026-11-03T11:00:00Z", "registry": [], "feeds": [
        feed("ma-feed-a", registry_ids=["ma-feed-a", "ma-collected"]), feed("ma-beaches", expected_cadence_hours=24.0),
        feed("ct-feed-b", stale=True, expected_cadence_hours=24.0, count=0)]})
    w(root / "out/coverage.json", {"built": "2026-11-03T11:00:00Z", "states": {
        "MA": {"grade": "Dated reports", "sentence": "Massachusetts publishes dated overflow reports.",
               "feeds": [{"source_id": "ma-feed-a", "name": "Feed A", "precision": "minute", "precision_text": "to the minute",
                          "cadence_hours": 6.0, "records_12m": 1526}],
               "rain_caution": {"covered": False}},
        "CT": {"grade": "No public reports", "sentence": "Connecticut publishes nothing we can read.",
               "feeds": [{"source_id": "ct-feed-b", "name": "Feed B", "precision": None, "cadence_hours": 24.0, "records_12m": 0}],
               "rain_caution": {"covered": False}}}})
    w(root / "docs/owner-signups.md", "# Sign-ups\n\n| # | Who | What | Address |\n|---|---|---|---|\n"
                                      "| 1 | City of Alpha (Everbridge) | Join at https://example.org/signup/ma-list now | alpha@dirtywaterwatch.org |\n")
    w(root / "docs/subscriptions.md", "# Subscriptions\n\n| State | Who | URL | Status |\n|---|---|---|---|\n"
                                      "| MA | Elsewhere | https://example.org/elsewhere | captcha |\n")
    w(root / "docs/decisions.md", "# Owner decisions\n\n2.6 [nh-vt] The NHDES Healthy Swimming Mapper licence line ends "
                                  "\"Distribution is discouraged\".\n\n4.4 [me] A Freedom of Access request to Maine DEP.\n")
    w(root / "data/build/name-blocklist.json", {"names": ["Jane Roe"]})
    # waters
    w(root / "data/waters-ne.json", {"source": "openboatlaunch", "waters": [
        water("mill-river-ma", "Mill River", "MA", ["Alpha"]), water("mill-river-2-ma", "Mill River", "MA", ["Beta"]),
        water("long-pond-ma", "Long Pond", "MA", ["Alpha"]), water("long-pond-2-ma", "Long Pond", "MA", ["Alpha"]),
        water("ma-no-geom", "No Geom Brook", "MA", ["Alpha"]), water("ct-river-ct", "Ct River", "CT", ["Gamma"])]})
    w(root / "data/waters-nhd.json", {"source": "nhd", "waters": [
        water("x-creek-ct", "X Creek", "CT", ["Gamma"], source="nhd", geometry=GEOM),
        water("y-brook-ct", "Y Brook", "CT", ["Gamma"], source="osm", geometry=GEOM, fallback_for="nhd"),
        water("z-creek-ct", "Z Creek", "CT", ["Gamma"], source="nhd", geometry=GEOM, hand=True,
              note="the geometry is approximate; placed by name")]})
    w(root / "data/waters-extra.json", {"source": "osm", "waters": [water("q-river-vt", "Q River", "VT", ["Delta"], source="osm", geometry=GEOM)]})
    w(root / "out/waters.json", {"waters": [{"slug": "mill-river-ma", "state": "MA"}, {"slug": "ct-river-ct", "state": "CT"}]})
    obl = root.parent / (root.name + "-obl")
    for s in ("mill-river-ma", "mill-river-2-ma", "long-pond-ma", "long-pond-2-ma", "ct-river-ct"):
        w(obl / f"{s}.json", {"slug": s, "geometry": GEOM})
    out = lambda permit, oid, st, slug: {"npdes_permit": permit, "outfall": oid, "state": st, "permittee": f"{permit} STP", "water_slug": slug}
    w(root / "data/outfalls-ne.json", {"outfalls": [out("MA001", "1", "MA", "mill-river-ma"), out("MA001", "2", "MA", None),
                                                    out("MA002", "1", "MA", "nonexistent-ma"), out("CT001", "1", "CT", "ct-river-ct")]})
    w(root / "data/outfalls-mid-atlantic.json", {"outfalls": [out("VA001", "1", "VA", None)]})
    w(root / "out/events.json", {"events": [
        ev("m1", "MA", ["mill-river-ma"]), ev("m2", "MA", [], "Gulley Brook"), ev("m3", "MA", [], "gulley  brook"),
        ev("m4", "MA", [], ""), ev("m5", "MA", [], "Pavement", no_receiving_water=True),
        ev("m6", "MA", [], "Old", superseded="revised"), ev("m7", "MA", ["mill-river-ma"], duplicate_of="m1"),
        ev("m8", "MA", ["long-pond-ma"]), ev("c1", "CT", ["ct-river-ct"]), ev("c2", "CT", [], "Jane Roe's Pond")]})
    w(root / "data/build/status.json", {"unplaced_events": ["m2", "m3", "m4", "m6", "c2"], "no_receiving_water_events": ["m5"]})
    if register is not None:
        w(root / "data/notice-channels.json", register)
    if draft is not None:
        w(root / "data/notice-channels.draft.json", draft)
    return obl


REGISTER = {"channels": [
    {"state": "MA", "operator": "City of Alpha", "channel": "Everbridge CSO notices", "monitored": True, "last_state": "ok, checked 2026-11-03"},
    {"state": "MA", "operator": "Town of Beta", "channel": "email list", "monitored": False, "url": "https://example.org/beta",
     "reason": "sign-up needs the owner's phone number"},
    {"state": "CT", "operator": "MDC", "channel": "notices page", "monitored": True},
    {"state": "VT", "operator": "Burlington", "channel": "notices page", "monitored": False, "url": "https://example.org/bv",
     "reason": "bot wall: 403 to scripts"}]}


def run(tmp_path, register=None, draft=None):
    root = tmp_path / "proj"
    obl = make_project(root, register, draft)
    before = sorted((str(p.relative_to(root)), p.stat().st_mtime_ns) for p in (root / "out").rglob("*"))
    assert T.main(["--root", str(root), "--now", NOW, "--obl-dir", str(obl)]) == 0
    after = sorted((str(p.relative_to(root)), p.stat().st_mtime_ns) for p in (root / "out").rglob("*"))
    assert before == after, "the tally must not write under out/"
    return root, (root / "docs/source-tally.md").read_text()


def sections(md: str) -> dict[str, str]:
    parts = re.split(r"(?m)^## ", md)
    return {p.split("(")[1].split(")")[0]: p for p in parts if re.match(r"[A-Za-z ]+ \([A-Z]{2}\): ", p)}


def summary_rows(md: str) -> dict[str, list[str]]:
    out = {}
    for line in md.splitlines():
        m = re.match(r"\| ([A-Z]{2}) \|(.*)\|\s*$", line)
        if m:
            out[m.group(1)] = [c.strip() for c in m.group(2).split("|")]
    return out


def test_twelve_sections_in_fixed_order_with_all_blocks(tmp_path):
    _, md = run(tmp_path, REGISTER)
    heads = re.findall(r"(?m)^## [A-Za-z ]+ \(([A-Z]{2})\): ", md)
    assert heads == ORDER
    secs = sections(md)
    for st in ORDER:
        for h in ("### Collected now (", "### Monitored channels (", "### Not collected (", "### Opportunities (", "### Water records"):
            assert h in secs[st], (st, h)
    assert "## Summary" in md and md.index("## Summary") < md.index("## Connecticut (CT)")
    # one-line header: grade and sentence from coverage.json; a state with no coverage entry says so
    assert "## Massachusetts (MA): Dated reports\n\nMassachusetts publishes dated overflow reports." in md
    assert "## Connecticut (CT): No public reports" in md
    assert "no coverage grade" in secs["NH"] and "The register has no rows for this state yet" in secs["NH"]


def test_summary_table_counts(tmp_path):
    _, md = run(tmp_path, REGISTER)
    s = summary_rows(md)
    assert list(s) == ORDER
    # columns: grade, feeds on, channels monitored, not collected, opportunities, water records, outfalls w/o record, unplaced
    assert s["MA"][:5] == ["Dated reports", "2", "1", "3", "3"]
    assert s["CT"][:5] == ["No public reports", "1", "1", "6", "4"]
    assert s["NH"][:5] == ["-", "0", "-", "1", "1"]          # no register rows for NH yet: "-", not 0
    assert s["VT"][:5] == ["-", "0", "0", "2", "2"]
    assert s["ME"][1:5] == ["0", "-", "0", "0"]
    assert s["MA"][5:] == ["5", "2 of 3", "3 (50.0%)"]
    assert s["CT"][5:] == ["4", "0 of 1", "1 (50.0%)"]
    assert s["VA"][6] == "1 of 1"
    tot = [l for l in md.splitlines() if l.startswith("| **All**")][0]
    assert "**3**" in tot and "**12**" in tot and "**10**" in tot and "**3 of 5**" in tot and "**4 (50.0%)**" in tot


def test_collected_now_and_section_counts(tmp_path):
    _, md = run(tmp_path, REGISTER)
    ma, ct = sections(md)["MA"], sections(md)["CT"]
    assert "### Collected now (2)" in ma
    assert "| Feed A name | events: cso, sso | to the minute | every 6 h | 1,526 | 2026-11-03 10:00Z | no |" in ma
    assert "ma-beaches (no registry row)" in ma and "n/a (5 kept)" in ma           # assigned to MA by its id's prefix
    assert "| Feed B | sewage reports | - | daily | 0 |" in ct and "| stale |" in ct
    assert "### Not collected (3)" in ma and "### Opportunities (3)" in ma and "### Monitored channels (1)" in ma
    assert "- City of Alpha - Everbridge CSO notices; monitor: ok, checked 2026-11-03" in ma
    assert "### Not collected (6)" in ct and "### Opportunities (4)" in ct


def test_not_collected_rows_and_unlocks(tmp_path):
    _, md = run(tmp_path, REGISTER)
    secs = sections(md)
    ma, ct, nh, vt = secs["MA"], secs["CT"], secs["NH"], secs["VT"]
    # an owner sign-up links to the line of docs/owner-signups.md that holds the same URL
    assert "**City of Alpha sewage alerts** (candidate, events)" in ma
    assert "Unlock: owner sign-up - [owner-signups.md L5](owner-signups.md#L5)" in ma
    # a licence decision links to the line of docs/decisions.md
    assert "Unlock: licence decision - [decisions.md L3](decisions.md#L3)" in nh
    # a source spanning two states is listed in each; a collected one and a used one are not listed
    assert "**multi**" in ma and "**multi**" in ct
    assert "ma-used" not in md and "**ma-collected**" not in md
    assert "Unlock: engineering work" in ct
    assert "(rejected, news): Reason one. Unlock: none: rejected" in ct
    assert "**ct-nourl** (watch, monitoring): Reason one. Unlock: no URL" in ct
    assert "Unlock: reference only" in ct
    assert "Unlock: bot wall" in vt
    # "E. coli" is not a sentence end
    assert "Holds the receiving-water E. coli model results" in ct
    # the registry row with no feed and no checklist row is listed, status registered
    assert "**CT extra registry row** (registered, monitoring)" in ct
    # register rows with monitored false are Not collected, with what would unlock them
    assert "**Town of Beta / email list** (not monitored, events): sign-up needs the owner's phone number. Unlock: owner sign-up" in ma
    assert "**Burlington / notices page** (not monitored, events): bot wall: 403 to scripts. Unlock: bot wall" in vt
    # opportunities: reference-only and rejected rows are not ranked; dated public channels come first
    opp = ct.split("### Opportunities")[1].split("### Water records")[0]
    assert "ct-law" not in opp and "ct-rejected" not in opp and "ct-ecoli" in opp
    ma_opp = ma.split("### Opportunities")[1]
    assert ma_opp.index("City of Alpha sewage alerts") < ma_opp.index("multi")           # a dated channel before a feed with history
    assert "Ranked: dated public channels 2, feeds with history 1, context sources 0." in ma_opp


def test_water_records_block(tmp_path):
    _, md = run(tmp_path, REGISTER)
    ma, ct, vt = sections(md)["MA"], sections(md)["CT"], sections(md)["VT"]
    assert "- Records: 5 (1 on the site). By origin: openboatlaunch extract 5, NHD build 0, OpenStreetMap fallback 0, hand record 0, editorial 0." in ma
    assert "- Records: 4 (1 on the site). By origin: openboatlaunch extract 1, NHD build 1, OpenStreetMap fallback 1, hand record 1, editorial 0." in ct
    assert "OpenStreetMap fallback 1" in vt
    assert "Geometry: 0 flagged approximate, 1 with no geometry." in ma                # ma-no-geom has no openboatlaunch file
    assert "Geometry: 1 flagged approximate, 0 with no geometry." in ct                # the hand record's own note says so
    assert "Outfalls in the registry with no water record: 2 of 3 (66.7%). Most: MA001 (MA001 STP) 1, MA002 (MA002 STP) 1." in ma
    assert "Outfalls in the registry with no water record: 0 of 1 (0.0%)." in ct
    assert "Reports unplaced: 3 of 6 (50.0%). Largest names: Gulley Brook (2), (no water named) (1)." in ma
    assert "Reports classed no receiving water: 1 (16.7%)." in ma
    assert "2 names on 4 records; 1 resolvable by town" in ma and "1 not (Long Pond)" in ma
    assert "2 reports placed on them" in ma
    assert "Duplicate-name waters: none" in ct


def test_names_emails_and_phones_never_reach_the_file(tmp_path):
    _, md = run(tmp_path, REGISTER)
    assert "Jane Roe" not in md and "jroe@" not in md and "555-123-4567" not in md and "@" not in md
    assert "[name removed]" in sections(md)["CT"]            # the unplaced water text that was only a name


def test_without_a_register_the_section_says_so(tmp_path):
    _, md = run(tmp_path)
    s = summary_rows(md)
    assert s["MA"][2] == "-" and s["MA"][3] == "2" and s["VT"][3] == "1"
    assert "register not available" in sections(md)["MA"]
    assert "neither data/notice-channels.json nor data/notice-channels.draft.json exists" in md


def test_draft_register_is_read_when_the_register_is_absent(tmp_path):
    _, md = run(tmp_path, draft=REGISTER)
    assert summary_rows(md)["MA"][2] == "1"
    assert "data/notice-channels.draft.json (4 rows, 2 monitored)" in md


def test_register_in_the_real_schema_with_monitor_health(tmp_path):
    reg = {"schema_version": 1, "channels": [
        {"id": "ma-alpha-page", "state": "MA", "name": "City of Alpha", "channel_kind": "operator_page", "urls": ["https://alpha.example.org/cso"],
         "method": "html", "monitored": True, "unmonitored_reason": None, "publishes": "status", "authority": "Alpha CSO page"},
        {"id": "ma-beta-email", "state": "MA", "name": "Town of Beta", "channel_kind": "email_list", "urls": [], "monitored": False,
         "unmonitored_reason": "email_only", "signup_url": "https://example.org/signup/ma-list"},
        {"id": "ct-gamma", "state": "CT", "name": "Gamma Authority", "channel_kind": "operator_page", "urls": [], "monitored": False,
         "unmonitored_reason": "none_found", "note": "No page found for Gamma. Checked twice."},
        {"id": "ct-delta-feed", "state": "CT", "name": "Delta Sewer", "channel_kind": "feed", "urls": [], "monitored": False,
         "unmonitored_reason": "feed_ingested", "feed_source_id": "ct-feed-b"},
        {"id": "vt-eps", "state": "VT", "name": "Epsilon", "channel_kind": "operator_page", "urls": [], "monitored": False,
         "unmonitored_reason": "bot_wall"}]}
    root = tmp_path / "proj"
    make_project(root, register=reg)
    w(root / "data/build/notice-pages/health.json", {"states": {"MA": {"channels": [
        {"id": "ma-alpha-page", "wording": "Publishes a current status", "last_fetch": "2026-11-03T10:00:00Z"}]}}})
    assert T.main(["--root", str(root), "--now", NOW, "--obl-dir", str(root.parent / "proj-obl")]) == 0
    md = (root / "docs/source-tally.md").read_text()
    s, secs = summary_rows(md), sections(md)
    ma, ct, vt = secs["MA"], secs["CT"], secs["VT"]
    assert s["MA"][2] == "1" and s["CT"][2] == "0" and s["VT"][2] == "0"          # only monitored: true rows count
    assert "- City of Alpha - Alpha CSO page [alpha.example.org]; publishes status; monitor: Publishes a current status (fetched 2026-11-03)" in ma
    # an email-only channel is an owner sign-up, linked by its sign-up URL; none found is no URL, a bot wall is a bot wall
    assert "**Town of Beta / email list** (not monitored, events): an email list only. Unlock: owner sign-up - [owner-signups.md L5]" in ma
    assert "**Gamma Authority / operator page** (not monitored, events): No page found for Gamma. Unlock: no URL" in ct
    assert "Unlock: bot wall" in vt and "**Epsilon / operator page**" in vt
    # a channel a feed already reads is collected: not under Not collected, named under Monitored channels
    assert "Delta Sewer" not in ct.split("### Not collected")[1]
    assert "Read as feeds (register rows the monitor does not fetch, so not counted above): Delta Sewer (ct-feed-b)." in ct
    assert s["CT"][3] == "7" and s["MA"][3] == "3"


def test_register_shapes_and_missing_inputs_are_tolerated(tmp_path):
    root = tmp_path / "bare"
    (root / "docs").mkdir(parents=True)
    assert T.main(["--root", str(root), "--now", NOW, "--obl-dir", str(root / "nope")]) == 0
    md = (root / "docs/source-tally.md").read_text()
    assert [m for m in re.findall(r"(?m)^## [A-Za-z ]+ \(([A-Z]{2})\): ", md)] == ORDER
    assert "Missing inputs" in md and "out/coverage.json" in md
    # a register keyed by state, and a monitor dict
    root2 = tmp_path / "keyed"
    make_project(root2, register={"MA": [{"operator": "A", "channel": "c", "monitor": {"enabled": True, "last_state": "quiet"}}],
                                  "CT": [{"operator": "B", "channel": "d", "monitored": "no", "reason": "no URL known"}]})
    assert T.main(["--root", str(root2), "--now", NOW, "--obl-dir", str(root2 / "nope")]) == 0
    md2 = (root2 / "docs/source-tally.md").read_text()
    ma = sections(md2)["MA"]
    assert "### Monitored channels (1)" in ma and "monitor: quiet" in ma
    assert "B / d" in sections(md2)["CT"] and "geometry for its records is not checked" in md2


def test_output_is_deterministic_for_a_fixed_now(tmp_path):
    root, md = run(tmp_path, REGISTER)
    obl = root.parent / (root.name + "-obl")
    assert T.main(["--root", str(root), "--now", NOW, "--obl-dir", str(obl)]) == 0
    assert (root / "docs/source-tally.md").read_text() == md


def test_helpers():
    assert T.cadence_text(0.25) == "every 15 min" and T.cadence_text(1) == "hourly" and T.cadence_text(24) == "daily"
    assert T.cadence_text(168) == "weekly" and T.cadence_text(720) == "monthly" and T.cadence_text(9600) == "yearly"
    assert T.first_sentence("Holds the E. coli results. More.") == "Holds the E. coli results"
    assert T.states_in("NY (New York City)") == ["NY"] and T.states_in("CT,MA,ME,NH,RI,VT") == ["CT", "MA", "ME", "NH", "RI", "VT"]
    assert T.states_in("international") == [] and T.states_in("NH/VT") == ["NH", "VT"]
    y = T.parse_flat_yaml('# note\nid: "a-b"\nenabled: true\nstates: ["MA", "CT"]\ncadence: null\nn: 3\nname: plain text\n')
    assert y == {"id": "a-b", "enabled": True, "states": ["MA", "CT"], "cadence": None, "n": 3, "name": "plain text"}
    assert T.url_key("https://www.Example.org/a/b/?q=1") == "example.org/a/b" and T.url_key("https://example.org") is None


def test_combined_sewer_and_plant_outfalls_are_counted_apart_for_the_live_states_of_the_rules(tmp_path):
    root = tmp_path / "proj"
    obl = make_project(root, REGISTER)
    out = lambda permit, oid, st, slug, **k: {"npdes_permit": permit, "outfall": oid, "state": st,
                                              "permittee": f"{permit} STP", "water_slug": slug, **k}
    w(root / "data/outfalls-plants-us.json", {"outfalls": [out("MA009", "001", "MA", "mill-river-ma"),
                                                           out("MA009", "002", "MA", None), out("MA008", None, "MA", None)]})
    w(root / "data/build/outfalls-reported.json", {"outfalls": [
        out("MA007", "rep-1", "MA", None, outfall_kind="cso", record_status="provisional"),      # counted with the CSOs
        out("MA007", "rep-2", "MA", None, outfall_kind="reported", record_status="provisional"),  # not counted
        out("MA007", "rep-3", "MA", None, outfall_kind="cso", record_status="superseded")]})       # not counted
    w(root / "data/rules.json", {"version": "t", "live_states": ["MA", "CT", "OH"]})
    assert T.main(["--root", str(root), "--now", NOW, "--obl-dir", str(obl)]) == 0
    md = (root / "docs/source-tally.md").read_text()
    secs = sections(md)
    assert list(secs) == ["CT", "MA", "OH"]                       # the rules' list, in the tally's order; no VT
    assert "## Ohio (OH): " in md
    ma = secs["MA"]
    assert "Outfalls in the registry with no water record: 3 of 4 (75.0%)." in ma
    assert "MA007 (MA007 STP) 1" in ma and "MA009" not in ma.split("Treatment plant")[0]
    assert "- Treatment plant outfalls without a water record: 2 of 3 (66.7%)." in ma
    assert "Treatment plant" not in secs["CT"]
    T.set_live_states(tmp_path / "nowhere")                       # no rules file: the fixed twelve
    assert T.STATES == T.STATE_ORDER
