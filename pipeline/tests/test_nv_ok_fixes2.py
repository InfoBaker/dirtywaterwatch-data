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
