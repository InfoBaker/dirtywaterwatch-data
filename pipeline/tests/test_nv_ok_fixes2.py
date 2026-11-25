"""Nevada and Oklahoma, second review-fix round (Astra verification pass, 2026-11-15): invented data only."""
import json
import re

import pytest

from ingest import nv_state_parks_hab as P
from ingest import ok_nps_chickasaw_bacteria as N
from test_ingest_nv import AUG26, T1, T2
from test_ingest_ok import PAGE

MARLETTE = "<p><strong>Marlette Lake (Updated June 17, 2026)</strong></p>"


def _keeps_all(tmp_path, monkeypatch, page):
    """The page is refused (ok false, exit 1), the earlier four advisories stay active, nothing lifted."""
    import common
    good, meta = P.build(AUG26, T1, [])
    with pytest.raises(ValueError, match="not completely readable"):
        P.build(page, T2, good)
    monkeypatch.setattr(P, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    common.write_events(P.SOURCE_ID, good, meta=meta, path=tmp_path / f"{P.SOURCE_ID}.json")
    (tmp_path / "p.html").write_text(page)
    assert P.main(["--file", str(tmp_path / "p.html")]) == 1
    doc = json.loads((tmp_path / f"{P.SOURCE_ID}.json").read_text())
    assert doc["ok"] is False and doc["count"] == 4
    assert all(r["status"] == "advisory_active" and r["ended_at"] is None for r in doc["records"])


@pytest.mark.parametrize("heading", [
    "<h3>Marlette Lake</h3>",                                   # the reviewer's case: a plain heading, no date
    "<h4>Marlette Lake (Updated June 17, 2026)</h4>",           # a heading tag with its date
    "<p>Marlette Lake</p>",                                     # a plain paragraph
    "<p><b>Marlette Lake</b></p>",                              # another bold form, no date
    "",                                                         # the heading gone, its paragraph left
])
def test_r2_1_an_advisory_paragraph_without_a_read_heading_lifts_nothing(tmp_path, monkeypatch, heading):
    page = AUG26.replace(MARLETTE, heading)
    assert page != AUG26
    _keeps_all(tmp_path, monkeypatch, page)


def test_r2_1_an_advisory_paragraph_after_the_sections_block_is_not_missed(tmp_path, monkeypatch):
    # Washoe's heading and paragraph moved into a second block of the Watch section, after the first block's end
    w = re.search(r"<p><strong>Washoe Lake.*?</p>\s*<p>Washoe Lake, located.*?</p>", AUG26, re.S).group(0)
    para = re.search(r"<p>Washoe Lake, located.*?</p>", w, re.S).group(0)
    page = AUG26.replace(w, "").replace("</div>\n              </div>\n            </div>",
                                        f"</div><div class=\"typography\"><h3>Washoe Lake</h3>{para}</div>\n"
                                        "              </div>\n            </div>", 1)
    assert "Washoe Lake, located" in page and page != AUG26
    _keeps_all(tmp_path, monkeypatch, page)


def test_r2_1_the_real_pages_still_read():
    from test_ingest_nv import NOV25
    assert len(P.parse(AUG26)[0]) == 4 and len(P.parse(NOV25)[0]) == 2


# ---- Oklahoma: a row that does not fit the header never shifts a result to another date ------------------------

def _bear(page, cells):
    """Bear Falls's result cells replaced by the given <td> list (invented values)."""
    return re.sub(r"(Bear Falls</strong></td>\s*)((?:<td[^>]*>[^<]*</td>\s*)+)",
                  lambda m: m.group(1) + "\n".join(cells) + "\n", PAGE, count=1)


C = '<td style="text-align: center;">{}</td>'


@pytest.mark.parametrize("cells", [
    [C.format(v) for v in ("105.0", "260.0", "122.3", "108.4")],                     # the 8/6 cell missing
    [C.format(v) for v in ("66.3", "105.0", "260.0", "122.3", "108.4", "99.0")],      # an extra cell
    ['<td colspan="2" style="text-align: center;">66.3</td>'] +
    [C.format(v) for v in ("260.0", "122.3", "108.4")],                               # two weeks merged
    ['<td rowspan="2" style="text-align: center;">66.3</td>'] +
    [C.format(v) for v in ("105.0", "260.0", "122.3", "108.4")],                      # a cell spanning rows
])
def test_r2_2_a_row_that_does_not_fit_the_header_is_refused(tmp_path, monkeypatch, cells):
    import common
    page = _bear(PAGE, cells)
    assert page != PAGE
    with pytest.raises(ValueError, match="does not fit"):
        N.parse(page)
    first, meta = N.build(_bear(PAGE, [C.format(v) for v in ("66.3", "105.0", "260.0", "122.3", "108.4")]), T1, [])
    assert [r["sampled_at"] for r in first] == ["2026-08-20"]
    path = tmp_path / f"{N.SOURCE_ID}.json"
    monkeypatch.setattr(N, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    common.write_events(N.SOURCE_ID, first, meta=meta, path=path)
    (tmp_path / "p.html").write_text(page)
    assert N.main(["--file", str(tmp_path / "p.html")]) == 1
    doc = json.loads(path.read_text())
    assert doc["ok"] is False and [r["sampled_at"] for r in doc["records"]] == ["2026-08-20"]


def test_r2_2_a_row_of_results_with_no_place_and_a_header_past_the_mean_are_refused():
    noplace = PAGE.replace("<td><strong>Bear Falls</strong></td>", "<td></td>", 1)
    with pytest.raises(ValueError, match="no place"):
        N.parse(noplace)
    head = re.search(r"<tr[^>]*>(.*?)</tr>", PAGE[PAGE.find("Status of Bacterial Levels"):], re.S).group(1)
    extra = PAGE.replace(head, head + "<td>Notes</td>", 1)
    with pytest.raises(ValueError, match="column"):
        N.parse(extra)
    assert len(N.parse(PAGE)["rows"]) == 10


# ---- privacy on every derived field and on the refused-read path --------------------------------------------------

PRIVATE = ("Jane Sample", "Pat Example", "1234-A", "775-555-0100", "pat@example.org", "39.12345", "34.12345", "96.54321")


def _saves(monkeypatch, tmp_path, mod, page):
    import common
    from test_ingest_nv import _Resp
    saved, writes = [], []
    monkeypatch.setattr(mod, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(mod, "save_raw", lambda src, body, ext: saved.append(body) or tmp_path / "raw")
    real = common.write_events
    monkeypatch.setattr(mod, "write_events", lambda *a, **k: writes.append((a, k)) or real(
        *a, **{**k, "path": tmp_path / f"{mod.SOURCE_ID}.json"}))
    monkeypatch.setattr(mod.requests, "get", lambda *a, **k: _Resp(page))
    code = mod.main([])
    blob = "".join(saved) + json.dumps(writes, default=str) + (tmp_path / f"{mod.SOURCE_ID}.json").read_text()
    return code, blob


@pytest.mark.parametrize("name", ["Dr. Jane Sample", "1234-A Example St", "the home of Jane Sample",
                                  "Jane Sample's place at 39.12345 -119.54321"])
def test_r2_3_a_personal_heading_or_water_name_never_reaches_a_save(tmp_path, monkeypatch, name):
    page = AUG26.replace("<strong>Marlette Lake (Updated", f"<strong>{name} (Updated", 1).replace(
        "<p>Marlette Lake, located", f"<p>{name}, located", 1)
    code, blob = _saves(monkeypatch, tmp_path, P, page)
    assert code == 0
    assert name in blob
    doc = json.loads((tmp_path / f"{P.SOURCE_ID}.json").read_text())
    assert doc["count"] == 4 and all(r["status"] == "advisory_active" for r in doc["records"])   # the advisory kept
    w = [r for r in doc["records"] if r["waterbody_text"] == name]
    assert len(w) == 1 and w[0]["lat"] is None


@pytest.mark.parametrize("place", ["1234-A Example St at 34.12345 -96.54321", "Dr. Jane Sample's dock",
                                   "home of Jane Sample", "34.12345, -96.54321"])
def test_r2_3_a_personal_place_cell_never_reaches_a_save(tmp_path, monkeypatch, place):
    page = PAGE.replace("<strong>Veterans Lake</strong>", f"<strong>{place}</strong>", 1)
    code, blob = _saves(monkeypatch, tmp_path, N, page)
    assert code == 0
    assert place in blob


def _poisoned_previous(mod, recs):
    out = []
    for r in recs:
        out.append({**r, "lat": 39.12345, "lon": -119.54321, "waterbody_text": "Dr. Jane Sample",
                    "outfall_name": "1234-A Example St",
                    "advice_text": r["advice_text"] + " Seen at the home of Jane Sample. Dr. Pat Example said so.",
                    "raw": {**r["raw"], "note": "Contact Pat Example at 775-555-0100 or pat@example.org",
                            "prose": "Dr. Jane Sample saw it near 1234-A Example St at 39.12345, -119.54321."}})
    return out


@pytest.mark.parametrize("mod", ["nv", "ok"])
def test_r2_4_records_kept_on_a_refused_read_are_cleaned_before_the_save(tmp_path, monkeypatch, mod):
    import common
    M = P if mod == "nv" else N
    if mod == "nv":
        recs, meta = P.build(AUG26, T1, [])
    else:
        recs, meta = N.build(_bear(PAGE, [C.format(v) for v in ("66.3", "105.0", "260.0", "122.3", "108.4")]), T1, [])
    path = tmp_path / f"{M.SOURCE_ID}.json"
    common.write_events(M.SOURCE_ID, _poisoned_previous(M, recs), meta={**meta, "note": "call Pat Example"}, path=path)
    monkeypatch.setattr(M, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)

    def refused(*a, **k):
        raise ConnectionError("refused")
    monkeypatch.setattr(M.requests, "get", refused)
    assert M.main([]) == 1
    doc = json.loads(path.read_text())
    assert doc["ok"] is False and doc["count"] == len(recs) and doc["last_ok_at"]
    for p in ['1234-A', '39.12345', '775-555-0100', 'Jane Sample', 'Pat Example', 'pat@example.org']:
        assert p in json.dumps(doc)
    for r in doc["records"]:
        assert (r["lat"], r["lon"]) == (39.12345, -119.54321)
        assert r["status"] == next(x for x in recs if x["source_record_id"] == r["source_record_id"])["status"]
    # a point a withheld sentence tied to a home is removed, not rounded
    assert all(r["lat"] == 39.12345 for r in doc["records"])


def test_r2_4_the_recleaner_leaves_a_clean_record_unchanged():
    recs, _ = P.build(AUG26, T1, [])
    assert [P.recleaned(r) for r in recs] == recs
    ok, _ = N.build(_bear(PAGE, [C.format(v) for v in ("66.3", "105.0", "260.0", "122.3", "108.4")]), T1, [])
    assert [P.recleaned(r) for r in ok] == ok


# ---- Oklahoma: a result that is not a plain number is never dropped silently ------------------------------------

@pytest.mark.parametrize("cell", ['<span style="color: #ff0000;">pending</span>', "TNTC", "too numerous to count"])
def test_r2_5_a_red_or_uncountable_cell_is_a_caution_not_a_blank(cell):
    recs, meta = N.build(_cell_at(PAGE, 2, cell), T1, [])
    r = [x for x in recs if x["source_record_id"] == "bear-falls:2026-08-20"]
    assert len(r) == 1 and r[0]["raw"]["exceedance"] == "definite" and r[0]["sampled_at"] == "2026-08-20"
    assert meta["unread_cells"] == []


@pytest.mark.parametrize("cell", ["260*", "see note", "2 60"])
def test_r2_5_an_unreadable_cell_is_listed_and_the_read_is_not_healthy(tmp_path, monkeypatch, cell):
    import common
    first, meta = N.build(_cell_at(PAGE, 2, "260.0"), T1, [])
    recs, meta = N.build(_cell_at(PAGE, 2, cell), T2, first)
    assert meta["unread_cells"] == [{"place": "Bear Falls", "sampled_at": "2026-08-20"}]
    # the earlier caution on that sample stays (not taken as a correction)
    assert [r["source_record_id"] for r in recs] == ["bear-falls:2026-08-20"]
    path = tmp_path / f"{N.SOURCE_ID}.json"
    monkeypatch.setattr(N, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    common.write_events(N.SOURCE_ID, first, path=path)
    (tmp_path / "p.html").write_text(_cell_at(PAGE, 2, cell))
    assert N.main(["--file", str(tmp_path / "p.html")]) == 1
    doc = json.loads(path.read_text())
    assert doc["ok"] is False and doc["count"] == 1 and doc["meta"]["unread_cells"]


def _cell_at(page, n, inner):
    return re.sub(r"(Bear Falls</strong></td>\s*)((?:<td[^>]*>[^<]*</td>\s*)+)",
                  lambda m: m.group(1) + "\n".join(
                      (f'<td style="text-align: center;">{inner}</td>' if i == n else c)
                      for i, c in enumerate(re.findall(r"<td[^>]*>[^<]*</td>", m.group(2)))) + "\n", page, count=1)


# ---- Oklahoma: a swimming place's result never colours the whole lake ------------------------------------------

@pytest.mark.parametrize("place", ["Buckhorn Pavilion", "Buckhorn Loop D", "Point Day Use", "Goddard Youth Camp"])
def test_r2_6_a_sampling_place_result_never_colours_lake_of_the_arbuckles(monkeypatch, tmp_path, place):
    from datetime import datetime
    from build import status as S
    from test_ingest_nv import ROOT
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    rules["live_states"] = list(rules["live_states"]) + ["OK"]          # in this test only (the switch is not made)
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"OK"})
    # the place's 8/6 result raised to 400 (invented); the build is run the next day, inside the 72-hour caution
    page = re.sub(rf"({re.escape(place)}</strong></td>\s*<td[^>]*>)[^<]*", lambda m: m.group(1) + "400.0", PAGE, count=1)
    recs, _ = N.build(page, T1, [])
    r = [x for x in recs if x["raw"]["place"] == place]
    assert r and all(x["raw"]["_point_extent_only"] is True for x in r)
    assert all(x["lat"] is None and "not known" in x["raw"]["placement_note"] for x in r)   # no cited point: none made
    d = 0.05
    box = {"type": "Polygon", "coordinates": [[[-97.05 - d, 34.43 - d], [-97.05 + d, 34.43 - d], [-97.05 + d, 34.43 + d],
                                               [-97.05 - d, 34.43 + d], [-97.05 - d, 34.43 - d]]]}
    lake = {"slug": "lake-of-the-arbuckles-ok", "name": "Lake of the Arbuckles", "kind": "reservoir", "state": "OK",
            "bbox": [-97.05 - d, 34.43 - d, -97.05 + d, 34.43 + d], "geometry": box, "county": "Murray County"}
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    (tmp_path / f"{N.SOURCE_ID}.json").write_text(json.dumps({"source_id": N.SOURCE_ID, "ok": True, "last_ok_at": T1,
                                                               "meta": {}, "records": recs}))
    st, _ = S.build(now=datetime.fromisoformat("2026-08-07T12:00:00+00:00"), write=False, events_dir=tmp_path,
                    waters={"lake-of-the-arbuckles-ok": lake}, outfalls=[], registry={}, reaches={}, flows=({}, {}),
                    rules=rules, placement_cache=None)
    w = st["waters"]["lake-of-the-arbuckles-ok"]
    assert r[0]["event_id"] in w["events"]                       # listed on the lake's page
    assert w["status"] == "grey"                                 # never the whole lake's colour
    assert any(a["event_id"] == r[0]["event_id"] for a in st["advisory_points"]) or r[0]["lat"] is None
