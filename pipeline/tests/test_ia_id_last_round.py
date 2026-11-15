"""Iowa and Idaho: the verification pass of 2026-11-15 (Astra), last fix round. Every name, street, number and water
here is invented."""
import json

import pytest

from ingest import id_deq_cyanohab as H
from tests.test_ia_id_review import PTS, ROWS, T0, T1, T2, layer_doc, run_main

NAMES = [r[1] for r in ROWS]


# ------------------------------------------------------------------ Idaho: a partial layer read lifts nothing

def _truncated(names):
    doc = layer_doc(names)
    doc["exceededTransferLimit"] = True
    return doc


def _no_geometry(names):
    doc = layer_doc(names)
    for f in doc["features"]:
        if f["attributes"]["LocationDiscription"] != "Example Lake":
            f["geometry"] = None
    return doc


@pytest.mark.parametrize("bad_layer", [_truncated, _no_geometry])
def test_last_idaho_a_partial_layer_with_a_shortened_table_lifts_nothing(monkeypatch, tmp_path, bad_layer):
    code, out, recs = run_main(monkeypatch, tmp_path, ROWS, NAMES, T0)
    assert code == 0 and out.get("ok", True) is not False
    # a shortened table and a layer that is cut off (only the first water) or lost its points
    layer = bad_layer(["Example Lake"] if bad_layer is _truncated else NAMES)
    monkeypatch.setattr(H, "fetch_layer", lambda: layer)
    monkeypatch.setattr(H, "fetch_page", lambda: __import__("tests.test_ia_id_review", fromlist=["html"]).html(ROWS[:1]))
    out2 = {}

    def we(sid, recs, **kw):
        out2.update(recs=recs, **kw)
        return tmp_path / "events.json"
    monkeypatch.setattr(H, "write_events", we)
    assert H.main(["--at", T1]) == 0
    recs = {r["source_record_id"].split(":")[0]: r for r in out2["recs"]}
    assert not any(r["status"] in ("advisory_lifted", "ended") for r in out2["recs"]), \
        [(r["source_record_id"], r["status"]) for r in out2["recs"]]
    assert recs["sample-reservoir"]["status"] == "advisory_active" and out2["ok"] is False
    # the points of the last good read are kept: nothing moves, nothing is lost
    assert (recs["sample-reservoir"]["lat"], recs["sample-reservoir"]["lon"]) == (43.6, -116.2)


def test_last_idaho_parse_layer_keeps_a_water_without_a_point_and_flags_a_cut_off_answer():
    lay = H.parse_layer(_no_geometry(NAMES))
    assert "sample reservoir" in lay and lay["sample reservoir"]["lat"] is None
    assert H.layer_problem(_truncated(NAMES))
    assert H.layer_problem(layer_doc(NAMES)) is None


# ------------------------------------------------------------------ Idaho: no sample date -> no invented calendar start

@pytest.mark.parametrize("at", ["2026-07-15T06:30:00Z", "2026-07-15T05:30:00Z", "2026-07-14T23:59:00Z"])
@pytest.mark.parametrize("county", ["Kootenai", "Ada"])
def test_last_idaho_a_watch_without_a_collection_date_starts_at_the_read_marked_poll(monkeypatch, tmp_path, at, county):
    rows = [("Watch", "Specimen Pond", county, "", "", "Always use caution.")]
    _, _, recs = run_main(monkeypatch, tmp_path, rows, ["Specimen Pond"], at)
    w = recs["specimen-pond"]
    assert w["started_at"] == at and w["time_precision"] == "poll" and w["sampled_at"] is None
    assert "before" in w["raw"]["start_basis"]


def test_last_idaho_a_watch_with_a_collection_date_keeps_its_day():
    rows = [dict(zip(("level", "water", "county", "data_type", "collection_date", "info"), ROWS[2]))]
    w = H.records(H.update({}, rows, T0, None))[0]
    assert w["started_at"] == "2026-11-10" and w["time_precision"] == "day"


# ------------------------------------------------------------------ Idaho: DHW's names never reach a save unscrubbed

def test_last_idaho_dhw_names_and_their_keys_are_scrubbed_before_every_save(monkeypatch, tmp_path):
    bad = "Example Lake - Contact Example Person 208-555-0142"
    PTS[bad] = (47.5, -116.7, "Health Advisory")
    try:
        saves = []
        rows = [("Health Advisory", bad, "Kootenai", "Laboratory Results", "07/14/2026", "Toxins have exceeded.")]
        run_main(monkeypatch, tmp_path, rows, [bad], T0, saves)
        # carried state from before the fix: a raw key in points and in the snapshot
        st = json.loads((tmp_path / "state.json").read_text())
        st["points"]["example lake contact example person 208 555 0142"] = {"name": bad, "lat": 1, "lon": 1}
        st["last_snapshot"]["points"] = dict(st["points"])
        (tmp_path / "state.json").write_text(json.dumps(st))
        run_main(monkeypatch, tmp_path, rows, [bad], T1, saves)
    finally:
        PTS.pop(bad)
    assert len(saves) >= 4
    for s in saves:
        for b in ("Example Person", "example person", "555-0142", "555 0142"):
            assert b not in s, (b, s[:300])


# ------------------------------------------------------------------ Iowa news: a revision that cannot be read keeps the saved record

from ingest import ia_dnr_news as N  # noqa: E402

NEWS_URL = "https://www.iowadnr.gov/news-release/2026-11-01/x"
NEWS_BODY = "<p>The City of Exampleton reported that its lift station discharged wastewater into Sample Creek.</p>"


def _news_run(tmp_path, monkeypatch, body, pub, at):
    monkeypatch.setattr(N, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(N, "_OPERATORS", {})
    title = "Wastewater bypass in Exampleton"
    rss = (f"<rss><channel><item><title>{title}</title><link>{NEWS_URL}</link>"
           f"<pubDate>{pub}</pubDate></item></channel></rss>")
    page = ("<html><body><h1>" + title + "</h1>\n<p>Sunday, November 1, 2026</p>\n<p>News Release</p>\n" + body
            + "</body></html>")
    monkeypatch.setattr(N, "get", lambda url: rss if url == N.RSS else page)
    monkeypatch.setattr(N, "save_raw", lambda sid, data, ext: None)
    out = {}
    monkeypatch.setattr(N, "write_events", lambda sid, recs, **kw: out.update(recs=recs, **kw) or tmp_path / "e.json")
    assert N.main(["--at", at]) == 0
    return out


@pytest.mark.parametrize("cut", ["", "<p>Image</p>", "<p>The Iowa Department of Natural Resources.</p>"])
def test_last_iowa_news_a_revision_that_lost_its_body_keeps_the_saved_report_and_retries(tmp_path, monkeypatch, cut):
    out = _news_run(tmp_path, monkeypatch, NEWS_BODY, "Sun, 01 Nov 2026 12:00:00 GMT", T0)
    assert len(out["recs"]) == 1 and out.get("ok", True) is not False
    out = _news_run(tmp_path, monkeypatch, cut, "Mon, 02 Nov 2026 12:00:00 GMT", T1)
    assert len(out["recs"]) == 1 and "Sample Creek" in json.dumps(out["recs"])
    assert out["ok"] is False and any(NEWS_URL in e for e in out["meta"]["errors"])
    # the full revision is read on the next run and replaces it
    out = _news_run(tmp_path, monkeypatch, NEWS_BODY.replace("Sample Creek", "Example River"),
                    "Mon, 02 Nov 2026 12:00:00 GMT", T2)
    assert len(out["recs"]) == 1 and "Example River" in json.dumps(out["recs"]) and out.get("ok", True) is not False


# ------------------------------------------------------------------ Iowa FOCOMP: a damaged clock never replaces a good one

from ingest import ia_dnr_focomp as F  # noqa: E402
from tests.test_ia_id_review import FFIX, _focomp_run  # noqa: E402

_GOOD_CLOCKS = {"IncidentStartTime": "03:25", "IncidentEndTime": "09:00", "ReceivedTime": "11:08"}


def _good_pages():
    good = {rid: (FFIX / f"focomp-report-{rid}.html").read_text() for rid in ("900001", "900002", "900004")}
    good["100001"] = good["900004"].replace('value="900004"', 'value="100001"')
    return good


@pytest.mark.parametrize("ctl", sorted(_GOOD_CLOCKS))
@pytest.mark.parametrize("bad", ["", "garbled", "25:00", "9"])
def test_last_iowa_focomp_a_damaged_clock_never_replaces_a_good_one(tmp_path, monkeypatch, ctl, bad):
    good = _good_pages()
    rc, out, recs = _focomp_run(tmp_path, monkeypatch, good, "2026-09-26T12:00:00Z")
    before = {k: recs["900001"][k] for k in ("started_at", "ended_at", "reported_at")}
    assert before["ended_at"] == "2026-09-26T09:00:00-05:00"
    st = json.loads((tmp_path / "state.json").read_text())
    for r in st["reports"].values():
        r["closed"] = "Open"
    (tmp_path / "state.json").write_text(json.dumps(st))
    damaged = good["900001"].replace(f'name="{ctl}" value="{_GOOD_CLOCKS[ctl]}"', f'name="{ctl}" value="{bad}"')
    assert damaged != good["900001"]
    rc, out, recs = _focomp_run(tmp_path, monkeypatch, dict(good, **{"900001": damaged}), "2026-09-28T12:00:00Z")
    assert {k: recs["900001"][k] for k in before} == before
    assert out["ok"] is False and any("900001" in e for e in out["meta"]["unread"])


def test_last_iowa_focomp_a_damaged_clock_on_a_first_read_invents_no_midnight():
    page = (FFIX / "focomp-report-900001.html").read_text().replace('name="IncidentEndTime" value="09:00"',
                                                                     'name="IncidentEndTime" value="garbled"')
    with pytest.raises(ValueError):
        F.check_against(F.parse_report(page), None)


def test_last_iowa_focomp_receiving_stream_is_scrubbed_before_every_save(tmp_path, monkeypatch):
    page = (FFIX / "focomp-report-900002.html").read_text().replace(
        'name="ReceivingStream" value=""', 'name="ReceivingStream" value="Ditch behind 123-A Example St, Contact Example Person"')
    saves = []
    _focomp_run(tmp_path, monkeypatch, {"900002": page}, "2026-09-26T12:00:00Z", saves)
    # carried state saved before the fix
    st = json.loads((tmp_path / "state.json").read_text())
    st["reports"]["900002"]["fields"]["receiving_stream"] = "Creek near 45-B Sample Ave, Contact Example Person"
    (tmp_path / "state.json").write_text(json.dumps(st))
    _focomp_run(tmp_path, monkeypatch, {}, "2026-09-27T12:00:00Z", saves)
    assert len(saves) >= 3
    for s in saves:
        for b in ("Example Person", "123-A", "45-B"):
            assert b not in s, (b, s[:300])
