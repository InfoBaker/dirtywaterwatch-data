"""data/notice-channels.json: the public-notice channel register (schema and validator in
ingest/notification_pages.py). The real file must validate; the validator must catch each kind of mistake."""
import copy

import pytest
import json
from pathlib import Path

from ingest import notification_pages as M

ROOT = Path(__file__).resolve().parents[2]
DOC = json.loads((ROOT / "data" / "notice-channels.json").read_text())
DIS = json.loads((ROOT / "data" / "dischargers.json").read_text())


def test_the_register_validates():
    errs = M.validate_register(DOC, DIS, ROOT)
    assert errs == [], "\n".join(errs)
    assert DOC["schema"]["enums"] == M.ENUMS and set(DOC["schema"]["fields"]) == set(M.REQUIRED)


def test_every_new_jersey_cso_permit_has_a_row():
    permits = {r["npdes_permit"] for r in DIS if str(r.get("id", "")).startswith("nj-")
               and r.get("kind") in ("cso", "cso_receiving_stp")}
    assert len(permits) == 25
    rows = [r for r in DOC["channels"] if r["state"] == "NJ"]
    assert permits <= {r["permit"] for r in rows}
    # each permit row cites the permit; the shared-site permits read one page, entry by entry
    for r in rows:
        if r["permit"]:
            assert r["basis_kind"] == "permit" and r["permit"] in r["legal_basis"]
    shared = [r for r in rows if r["channel_kind"] == "shared_site"]
    assert len(shared) == 15 and {u for r in shared for u in r["urls"]} == {"https://njcsonotifications.com/"}
    assert all(r["entry"]["start"] == r["permit"] and r["records"] is False for r in shared)
    none = {r["operator_id"] for r in rows if r.get("unmonitored_reason") == "none_found"}
    assert none == {"nj-camden-city", "nj-gloucester-city", "nj-jmeuc", "nj-bcua", "nj-mcua"}


def row(**kw):
    r = {"id": "nj-x-page", "state": "NJ", "operator_id": None, "agency": "Some Agency", "name": "Some Agency",
         "permit": None, "channel_kind": "operator_page", "urls": ["https://example.org/cso"], "method": "html",
         "legal_basis": "Permit NJ0000000, Part IV.F.8.b.iii", "basis_kind": "permit", "monitored": True,
         "unmonitored_reason": None, "publishes": "notices", "note": None, "checked": "2026-11-03", "barrier": None}
    r.update(kw)
    return r


def errs_of(*rows):
    return M.validate_register({"schema_version": 1, "channels": list(rows)}, DIS)


def test_validator_catches_mistakes():
    assert errs_of(row()) == []
    assert errs_of(row(basis_kind="voluntary", legal_basis=None)) == []          # voluntary needs no basis
    cases = {
        "unknown fields": row(colour="red"),
        "missing": {k: v for k, v in row().items() if k != "publishes"},
        "channel_kind": row(channel_kind="website"),
        "basis_kind": row(basis_kind="custom"),
        "needs a legal_basis": row(legal_basis=None),
        "unmonitored_reason": row(monitored=False),
        "needs a note": row(monitored=False, unmonitored_reason="none_found", urls=[], method=None),
        "needs urls": row(urls=[], method=None),
        "operator_id or agency": row(agency=None),
        "not in data/dischargers.json": row(operator_id="nj-nowhere"),
        "not one of nj-paterson's permits": row(operator_id="nj-paterson", agency=None, permit="NJ0000001"),
        "does not start with": row(id="ny-x-page"),
        "status_pattern does not compile": row(status_pattern="(open"),
        "seed URL": row(seeds={"https://example.org/other": [{"path": "x", "fetched_at": "2026-11-03T12:41:00Z",
                                                                "http_status": 200}]}),
        "checked is": row(checked="Nov 3"),
        "http(s) URLs": row(urls=["ftp://example.org/x"]),
    }
    for want, r in cases.items():
        e = errs_of(r)
        assert any(want in x for x in e), (want, e)
    # order and uniqueness
    a, b = row(id="nj-b"), row(id="nj-a")
    assert any("sorted" in x for x in errs_of(a, b))
    assert any("duplicate id" in x for x in errs_of(row(), copy.deepcopy(row())))


def test_new_jersey_rows_are_in_a_stable_order():
    nj = [r["id"] for r in DOC["channels"] if r["state"] == "NJ"]
    assert nj == sorted(nj)
    states = [r["state"] for r in DOC["channels"]]
    assert states == sorted(states)


def test_every_row_has_its_barrier_and_the_validator_holds_the_rules():
    """docs/plan.md §2.y "What stands in the way": each unmonitored row names its barrier, or why it is left for
    review (docs/reviews/2026-11-03-barriers.md); monitored and feed rows have none."""
    for r in DOC["channels"]:
        assert "barrier" in r, r["id"]
        assert (r["barrier"], r.get("barrier_review")) == M.barrier_for(r), r["id"]
        if r["monitored"] or r["unmonitored_reason"] == "feed_ingested":
            assert r["barrier"] is None and not r.get("barrier_review"), r["id"]
        else:
            assert (r["barrier"] in M.ENUMS["barrier"]) != bool(r.get("barrier_review")), r["id"]
    review_path = ROOT / "docs" / "reviews" / "2026-11-03-barriers.md"
    if review_path.exists():   # the review lives with the site repository, not the public data repository
        review = review_path.read_text()
        assert all(f"`{r['id']}`" in review for r in DOC["channels"] if r.get("barrier_review"))
    off = dict(monitored=False, urls=[], method=None, note="x")
    cases = {
        "is not one of": row(barrier="fax_only"),
        "barrier is null for a monitored": row(barrier="print_only"),
        "means barrier login_required": row(unmonitored_reason="login", barrier="no_web_page", **off),
        "has a barrier or a barrier_review": row(unmonitored_reason="other", **off),
        "barrier_review only on a row with no barrier": row(unmonitored_reason="other", barrier="print_only",
                                                            barrier_review="why", **off),
    }
    for want, r in cases.items():
        assert any(want in x for x in errs_of(r)), (want, errs_of(r))
    assert errs_of(row(unmonitored_reason="other", barrier="not_verified", **off)) == []
    assert errs_of(row(unmonitored_reason="other", barrier_review="unclear", **off)) == []


@pytest.mark.parametrize("note,kind,why,want", [
    ("No URL known (not searched): X: CSO public notification (NMC 8). Not searched individually: residents may ask.",
     "operator_page", "other", "not_verified"),
    ("No web form: Town: public notice of overflows (PSA or paid notice, posting). No web form.", "news_page", "other",
     "print_only"),
    ("No web form: Town: yearly newspaper notice. No web channel: Maine requires no notice, and the yearly notice is "
     "printed only.", "news_page", "other", "print_only"),
    ("No URL known (not searched): official notice: X WPCA. Channel varies by town and was not surveyed.",
     "local_health_page", "other", "varies_by_town"),
    ("No URL known (not searched): X: advisories. Advisories go out through NY-Alert; no own page found in the research.",
     "operator_page", "other", "no_web_page"),
    ("No web form: Warning signs at all CSO outfalls. No online record.", "lights_signs_page", "other", "signs_only"),
    ("mass.gov answers 403 to this machine", "state_alert_page", "other", "bot_wall"),
    ("X alerts by email", "email_list", "email_only", "no_web_page"),
    ("X: no notice page found", "operator_page", "none_found", "no_web_page"),
    ("Token-gated map", "operator_page", "login", "login_required"),
])
def test_barriers_follow_the_registers_reason_and_note(note, kind, why, want):
    r = row(monitored=False, urls=[], method=None, unmonitored_reason=why, channel_kind=kind, note=note)
    assert M.barrier_for(r) == (want, None)
    assert M.barrier_for(row()) == (None, None)
    assert M.barrier_for(row(monitored=False, unmonitored_reason="feed_ingested", feed_source_id="x")) == (None, None)
    bar, review = M.barrier_for(row(monitored=False, urls=[], method=None, unmonitored_reason="app_only"))
    assert bar is None and "Swim Guide" in review
