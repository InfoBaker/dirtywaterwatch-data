"""Fields the sources publish and the pipeline kept only in raw, now in each record's `detail` (export/detail.py;
site docs/decisions.md items 31 and 46): CT DEEP's explanation of the cause and how the incident was resolved, New
Jersey's beach reasons, Hawaii's cause, MassDEP's additional information, Maine's comment, CIWQS's volume to surface
water and ADEM's live cause. Real records from the export built 2026-11-14, trimmed to the keys the readers use
(tests/fixtures/detail_fields/export-records.json). The source's words, scrubbed, never reworded.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import HOUSE_NUMBER_REMOVED  # noqa: E402
from export import csv as csv_export  # noqa: E402
from export import detail as D  # noqa: E402

FIX = json.loads((Path(__file__).resolve().parent / "fixtures" / "detail_fields" / "export-records.json").read_text())
REC = {r["event_id"]: r for r in FIX["records"]}
# sources written outside a module's own SOURCE_ID: {source id: the file that writes it}
WRITERS_ELSEWHERE = {
    "nc-dwr-sso-2022-2025": "pipeline/ingest/nc_dwr_sso.py",          # HIST_ID, the --backfill history layer
    "tx-tceq-sso-opendata": "pipeline/ingest/tx_transforms.py",       # the generic reader's tx_tceq_record transform
}


def d(eid: str) -> dict:
    return D.detail_of(REC[eid])


# ---------------------------------------------------------------- Connecticut DEEP

def test_ct_the_coded_cause_then_the_filers_explanation_and_how_it_was_resolved():
    got = d("ct-deep:10712")
    # the explanation's street address keeps its street and loses its number
    assert got["cause"] == ("Sewage Line Blockage - Grease; Backup came out of fresh air vent on sewer lateral on side of "
                            f"auto service station at {HOUSE_NUMBER_REMOVED} West Putnam Avenue")
    assert got["resolution"] == "Jetted the line to clear the partial blockage in the sewer main"
    assert "180" not in json.dumps(got)


def test_ct_an_explanation_that_says_nothing_is_left_out():
    assert d("ct-deep:9384")["cause"] == "Excessive Flows - Storm Event"          # "."
    assert d("ct-deep:9768")["cause"] == "Excessive Flows - Storm Event"          # "Same as above"
    assert d("ct-deep:9384")["resolution"] == "Rain event ended"
    assert d("ct-deep:10753")["cause"] == "Other; TEST TEST TEST TEST"            # the filer's words, as written
    assert "resolution" not in d("ct-deep:10753")                                 # null on the form
    assert "resolution" not in d("ct-deep:9941") and "cause" not in d("ct-deep:9941")   # a CSO form gives neither


def test_ct_a_header_row_read_as_a_record_gives_no_detail():
    # an annual workbook's repeated header row, read as a record: every value is its own column's name
    assert d("ct-deep-annual:xda4608dde58d") == {}


def test_ct_notes_from_the_annual_workbooks_and_the_archive_but_never_a_bare_number():
    assert d("ct-deep-annual:xe96cdc6fe830")["notes"] == "RAIN EVENT HAS ENDED"
    assert "notes" not in d("ct-deep-annual:x35a448f555a5")                      # "27102": a figure with no unit
    got = d("ct-deep-archive:bypass-35965153")
    assert got["notes"] == "Force Main Break" and got["cause"] == "Sewer Line Blockage - Other"


# ---------------------------------------------------------------- New Jersey beaches

def test_nj_the_reason_and_indicator_the_program_gives():
    assert d("nj-beaches:OC153101:beach_advisory:2026-08-12") == {
        "cause": "Monitoring that revealed elevated bacteria levels; Enterococci"}


def test_nj_a_placeholder_reason_gives_way_to_the_source_code_and_the_comment_keeps_its_words():
    got = d("nj-beaches:OC1048:beach_advisory:2026-08-17")
    assert got["cause"] == "WILDLIFE"            # "Other Please specify in the Description field" is not a reason
    # five rows "[Day #1] - ..." to "[Day #5] - ...": the words once, without the row counter
    assert got["notes"] == "Awaiting removal by NJ Fire Service coordination with Island Beach State Park facilities"
    assert d("nj-beaches:MC1096:beach_closure:2026-08-22") == {"cause": "Preemptive; CSO"}
    assert d("nj-beaches:SA171101:beach_closure:2025-07-03") == {"cause": "Harmful Algal Bloom as present.; ALGAE"}


def test_nj_template_comments_are_not_notes():
    # "First result that triggered an incident." and "[Day #1] - N/A" are in every incident's rows
    assert "notes" not in d("nj-beaches:OC153101:beach_advisory:2026-08-12")


# ---------------------------------------------------------------- Hawaii, MassDEP, Maine

def test_hi_the_cause_as_the_department_gives_it():
    assert d("hi-doh-cwb-events-api:1975") == {"cause": "Heavy rain"}
    assert d("hi-doh-cwb-events-api:1888") == {"cause": "Unknown"}        # the Department's word, shown as theirs


def test_ma_additional_information_is_the_notes():
    assert d("ma-massdep:d1fda2c6-fd79-476a-9bf6-423574e1720b")["notes"] == "Aquasite notification not sent out from ADS."
    assert d("ma-massdep:be6cecc3-03bd-424b-b7a7-276f724fe0cc")["notes"] == "estimates based on model"


def test_me_a_comment_that_states_a_reason_is_the_cause_and_any_other_is_a_note():
    assert d("me-healthy-beaches:123:beach_advisory:2025-07-15T17:00") == {
        "cause": "Recent enterococci bacteria results above Maine’s safety threshold (104 MPN/100ml)."}
    assert d("me-healthy-beaches:145:beach_advisory:2026-07-15T15:00") == {
        "notes": "Little Beach was placed under advisory in error, the correct advisory is being placed on Riverside Beach."}
    assert d("me-healthy-beaches:153:rain_advisory:2024-08-09T17:05") == {}


# ---------------------------------------------------------------- California CIWQS, Alabama ADEM

def test_ca_the_gallons_that_reached_surface_water():
    assert d("ca-swrcb-ciwqs-spills-flatfile:908028")["volume_to_water_gal"] == 290
    assert d("ca-swrcb-ciwqs-spills-flatfile:908897")["volume_to_water_gal"] == 0      # the operator's figure, as given
    assert "volume_to_water_gal" not in d("ca-swrcb-ciwqs-spills-flatfile:907277")       # not given: left out


def test_al_the_live_layers_cause_and_none_from_the_history_layer():
    assert d("al-adem-sso-history:SSO-00214428") == {"cause": "Equipment Failure"}
    assert d("al-adem-sso-history:SSO-00214490") == {}


# ---------------------------------------------------------------- the generic rules

def test_a_street_house_number_never_leaves_but_a_duration_or_a_station_number_stays():
    rec = {"source_id": "tx-tceq-sso-opendata", "raw": {"_cause": "Grease at the manhole in front of 4583 Buckley Rd."}}
    assert D.detail_of(rec)["cause"] == f"Grease at the manhole in front of {HOUSE_NUMBER_REMOVED} Buckley Rd."
    assert D.detail_of({"source_id": "ny-dec-sprtk", "raw": {"row": {"dischargeDuration": "2 Hours - Ongoing"}}}) == {
        "duration_text": "2 Hours - Ongoing"}
    assert D.detail_of({"source_id": "tx-tceq-sso-opendata", "raw": {"_cause": "Pump Station 3 failed"}})["cause"] == \
        "Pump Station 3 failed"


def test_new_fields_are_named_plainly_and_reach_the_csv_as_its_last_columns():
    from common import NAME_KEYS, PERSONAL_KEYS
    assert {"resolution", "notes"} <= set(D.FIELDS)
    assert not any(PERSONAL_KEYS.search(f) or NAME_KEYS.search(f) for f in D.FIELDS)
    assert csv_export.COLUMNS[-2:] == ["resolution", "notes"]
    assert set(csv_export.DETAIL_COLUMNS) | set(csv_export.LATER_DETAIL_COLUMNS) == set(D.FIELDS)   # every field has a column


# ---------------------------------------------------------------- Astra review 2026-11-21 (detail-fields-astra.md)

def _cause(text: str) -> str:
    return D.detail_of({"source_id": "tx-tceq-sso-opendata", "raw": {"_cause": text}})["cause"]


def test_review_2_a_range_a_fraction_and_an_address_with_no_street_word_lose_their_number():
    R = HOUSE_NUMBER_REMOVED
    assert _cause("Backup at 12-14 Main Street") == f"Backup at {R} Main Street"
    assert _cause("Backup at 12 1/2 Main Street") == f"Backup at {R} Main Street"
    assert _cause("Backup at 180 Broadway") == f"Backup at {R} Broadway"
    assert _cause("Overflow behind 22 Elmwood, into the creek") == f"Overflow behind {R} Elmwood, into the creek"


def test_review_3_a_count_or_a_duration_before_a_street_is_not_a_house_number():
    for s in ("2 hours on Main Street", "2 pumps run continuously", "12 manholes along Ocean Ave",
              "2 Hours on Main Street", "Bypass at 3 Pump Station on Elm St", "at 11 AM on Main Street",
              "1 hour on Elm Street"):
        assert _cause(s) == s, s


def test_review_1_a_compact_phone_number_is_removed():
    assert _cause("Please use (860)5550123 for updates") == "Please use [phone removed] for updates"


def test_review_4_every_mapped_source_has_a_writer_on_record():
    """Each SOURCES key is written by a module in ingest/ or by a writer named here with its path (a generic
    reader's config or a script); a source's yaml alone is not a writer."""
    import re
    root = Path(__file__).resolve().parent.parent
    ids = set()
    for p in (root / "ingest").glob("*.py"):
        ids |= set(re.findall(r"""(?:SOURCE_ID|source_id)\s*=\s*["']([a-z0-9-]+)["']""", p.read_text()))
    elsewhere = {sid: path for sid, path in WRITERS_ELSEWHERE.items()}
    for sid, path in elsewhere.items():
        assert sid in (root.parent / path).read_text(), (sid, path)
    assert sorted(s for s in D.SOURCES if s not in ids and s not in elsewhere) == []
