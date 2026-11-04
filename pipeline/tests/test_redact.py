"""Names of private individuals in quoted source text: build/redact.py removes the ones the text marks
as a person (honorific, role, name cue, phone, address, contact) and the blocklist, everywhere in the
export, and leaves agency, company, street and water names; build/name_review.py lists every
candidate for the owner. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import name_review as NR  # noqa: E402
from build import redact as R  # noqa: E402
from export import build as X  # noqa: E402

N = R.REDACTED


@pytest.fixture
def data_dir(tmp_path):
    """Reference files for the lexicon: one water, one discharger, the allowlist and blocklist."""
    (tmp_path / "waters-ne.csv").write_text("slug,name,kind,state,towns,launch_count,wikidata\n"
                                            "fort-point-channel-ma,Fort Point Channel,channel,MA,Boston,1,\n"
                                            "charles-river-ma,Charles River,river,MA,Boston; Cambridge; Sharon,3,\n")
    (tmp_path / "dischargers.json").write_text(json.dumps([{"name": "Town of Orange WPCA", "towns": ["Orange"],
                                                            "receiving_waters": ["Wepawaug River"]}]))
    (tmp_path / "waters-extra.json").write_text(json.dumps({"waters": [{"name": "Burr Creek", "towns": ["Bridgeport"]}]}))
    (tmp_path / "outfalls-ne.json").write_text(json.dumps({"outfalls": [{"npdes_permit": "CT0100366",
                                                                         "permittee": "GREATER NEW HAVEN WPCA",
                                                                         "outfall_name": "Huntington Road and Vernon Street"}]}))
    (tmp_path / "name-allowlist.json").write_text(json.dumps({"names": ["Mr. Rooter", "Sweet Peas"]}))
    (tmp_path / "name-blocklist.json").write_text(json.dumps({"names": ["Pat Morrissey"]}))
    return tmp_path


def ev(i, text, **f):
    return {"event_id": f"ct-deep-annual:{i}", "source_id": "ct-deep-annual", "raw": {"How incident was resolved": text}, **f}


# ordinary wording the lexicon learns from the records themselves (lower-case use)
FILLER = [ev(900 + i, t) for i, t in enumerate([
    "crew jetted the main and restored flow; the pump station was cleaned regarding the backup",
    "pump station alarm; crew cleaned the main regarding the blockage at the station",
    "staff cleaned the station and jetted the main; regarding the alarm, the pump was reset",
    "the rest of the grit was shoveled up and the mold was cleaned at the park",
    "mold and grease in the main; the pump was jetted and the mold removed",
    "pipe repaired; the pipe crew left; pipe flushed",
])]


def redact(texts, data_dir, **f):
    recs = [ev(i, t, **f) for i, t in enumerate(texts)] + FILLER
    out = R.redact_events(recs, data_dir)
    return [o["raw"]["How incident was resolved"] for o in out[:len(texts)]]


# ---------------------------------------------------------------- removed

def test_the_connecticut_resident_is_removed(data_dir):
    t = ("Building owner contacted to repair pump station.  Robert Sacks was his name.  He manually pumped the "
         "station down, and reported to us that the stations automatic operation had been restored by 3:00PM.")
    assert redact([t], data_dir) == [t.replace("Robert Sacks", N)]


@pytest.mark.parametrize("text, expected", [
    ("Spoke with Mr. Sacks about the lateral", f"Spoke with {N} about the lateral"),                    # honorific
    ("Mrs Jane Doe reported sewage in the yard", f"{N} reported sewage in the yard"),
    ("Called in by resident (Joe Romenelli)", f"Called in by resident ({N})"),                         # role
    ("Customer, Eric Kotarba, called with sewage in the basement.", f"Customer, {N}, called with sewage in the basement."),
    ("Received a call from Ed Dubois, owner of house 45 Robbins Ave", f"Received a call from {N}, owner of house 45 Robbins Ave"),
    ("Cathy, homeowner of 69 Dover Rd, called", f"{N}, homeowner of 69 Dover Rd, called"),             # given name + role
    ("Recieved call from Nancy Brown at 274 Morningside Drive West", f"Recieved call from {N} at 274 Morningside Drive West"),
    ("Tim Lee 238 Scott street (landlord)", f"{N} 238 Scott street (landlord)"),                       # address
    ("call from Simomne Corriveau at 96 Mercier Avenue", f"call from {N} at 96 Mercier Avenue"),       # caller + address
    ("any questions please call Dan Gregory at [phone removed] thanks", f"any questions please call {N} at [phone removed] thanks"),
    ("left message with Iliana Raffa at [phone removed]", f"left message with {N} at [phone removed]"),  # phone
    ("Complaint from Jose Acosta", f"Complaint from {N}"),                                             # contact
    ("Treatment plant operator Joe Barrios arrived at the plant", f"Treatment plant operator {N} arrived at the plant"),
    ("Notified by Robert Britain of the Town of Orange CT", f"Notified by {N} of the Town of Orange CT"),
    ("per conversation with Nicole G. - Hurricane Dike Station", f"per conversation with {N} - Hurricane Dike Station"),
    ("SPOKE WITH ROBERT SACKS REGARDING SEWER BACKUP", f"SPOKE WITH {N} REGARDING SEWER BACKUP"),        # upper case
])
def test_names_marked_as_a_person_are_removed(data_dir, text, expected):
    assert redact([text], data_dir) == [expected]


def test_a_marked_name_is_removed_everywhere_but_not_in_a_place_name(data_dir):
    out = redact(["Robert Sacks was his name.", "Robert Sacks repaired the pump.", "ROBERT SACKS ON SITE",
                  "Outfall at Robert Sacks Park"], data_dir)
    assert out == [f"{N} was his name.", f"{N} repaired the pump.", f"{N} ON SITE", "Outfall at Robert Sacks Park"]


def test_free_text_fields_are_covered_too(data_dir):
    recs = [ev(1, "ok", outfall_name="Lateral, resident John Smith, 12 Elm St", advice_text="Call Mr. Brown at [phone removed]",
               volume_text="45 gallons per homeowner Mary Jones", parse_error="note from caller (Ann Lee)", lat=41.2)]
    out = R.redact_events(recs, data_dir)[0]
    assert out["outfall_name"] == f"Lateral, resident {N}, 12 Elm St"
    assert out["advice_text"] == f"Call {N} at [phone removed]"
    assert out["volume_text"] == f"45 gallons per homeowner {N}"
    assert out["parse_error"] == f"note from caller ({N})"
    assert out["lat"] == 41.2
    assert recs[0]["outfall_name"] == "Lateral, resident John Smith, 12 Elm St"      # the input is not changed


# ---------------------------------------------------------------- kept

@pytest.mark.parametrize("text", [
    "Bypass at Fort Point Channel near Boston Post Rd and Main Street",
    "CSO 16 CONCORD AVE FRED MOLD PARK",
    "605 Baldwin Street, Francis Xavier plaza apartments utilizing dye testing",
    "Sewer Main, 38 Patrick Flood Road Farmington CT",
    "Manhole, Nathan Hale road",
    "Martin Luther King Jr Blvd manhole overflowed",
    "When the contractors Green Mountain Pipe turned on their pump a seal was missed",
    "Bunker Hill residents reported odors",
    "45 Oak Dr. Smith said",
    "Town of Orange WPCA notified; overflow reached the Charles River and Burr Creek",
    "Huntington Road and Vernon Street regulator; Greater New Haven WPCA crew responded",
    "Excessive Flows - Storm Event",
    "Department received call from American Rooter about the lateral",
    "Call came in for a backup located in front of Apex Pharmacy located at 2380 Dixwell Ave, Hamden",
    "The rest of the Grit was shoveled up by the crew.",
    "Case was assigned to Inspector [name removed] on 07/17/2025.",
    "https://portal.ct.gov/Robert Sacks/report.pdf",
])
def test_places_companies_and_wording_stay(data_dir, text):
    assert redact([text], data_dir) == [text]


def test_allowlist_and_blocklist(data_dir):
    out = redact(["Upon inspection the Mr. Rooter was called to clear the blockage.",
                  "Reported by business owner (Sweet Peas - 212 Sound Beach Avenue)",
                  "(Pat Morrissey)", "PAT MORRISSEY approved the bypass"], data_dir)
    assert out == ["Upon inspection the Mr. Rooter was called to clear the blockage.",
                   "Reported by business owner (Sweet Peas - 212 Sound Beach Avenue)", f"({N})", f"{N} approved the bypass"]


def test_blocklist_wins_over_allowlist(tmp_path, data_dir):
    (data_dir / "name-allowlist.json").write_text(json.dumps({"names": ["Pat Morrissey"]}))
    assert redact(["signed (Pat Morrissey)"], data_dir) == [f"signed ({N})"]


def test_given_names_that_are_towns_do_not_count(data_dir):
    lex = R.build_lexicon([], data_dir, allow=[], block=[])
    assert "sharon" not in lex.first_names and "nancy" in lex.first_names


def test_unmarked_candidates_are_found_but_kept(data_dir):
    lex = R.build_lexicon(FILLER, data_dir, allow=[], block=[])
    hits = R.find_names("The rest of the Grit was shoveled up by Ryan Festa. Chris Conners (DEEP Parks) was there.", lex)
    by = {h.phrase: h for h in hits}
    assert by["Ryan Festa"].auto and "contact" in by["Ryan Festa"].contexts
    assert not by["Chris Conners"].auto                       # a name with nothing marking it: review only


# ---------------------------------------------------------------- review and export

def test_name_review_lists_candidates_with_verdicts(data_dir):
    rows = [("ct-deep-annual", ev(1, "Robert Sacks was his name.")), ("ct-deep", ev(2, "Robert Sacks on site")),
            ("ct-deep", ev(3, "Chris Conners (DEEP Parks) was investigating")),
            ("ct-deep", ev(4, "Upon inspection the Mr. Rooter was called")), ("ct-deep", ev(5, "(Pat Morrissey)"))]
    rep = NR.review(rows + [("ct-deep", f) for f in FILLER], data_dir)
    c = {o["candidate"]: o for o in rep["candidates"]}
    assert c["Robert Sacks"]["count"] == 2 and c["Robert Sacks"]["auto_redact"] and c["Robert Sacks"]["verdict"] is None
    assert c["Robert Sacks"]["sources"] == {"ct-deep-annual": 1, "ct-deep": 1}
    assert c["Robert Sacks"]["example_event_ids"] == ["ct-deep-annual:1", "ct-deep-annual:2"]
    assert c["Robert Sacks"]["contexts"] == {"name_cue": 1}
    assert not c["Chris Conners"]["auto_redact"] and c["Chris Conners"]["verdict"] is None
    assert c["Mr. Rooter"]["verdict"] == "allow" and not c["Mr. Rooter"]["auto_redact"]
    assert c["Pat Morrissey"]["verdict"] == "block" and c["Pat Morrissey"]["auto_redact"]
    assert rep["by_source"]["ct-deep"]["redactions"] == 2
    md = NR.markdown(rep)
    assert "## By source" in md and "| ct-deep-annual |" in md and "Chris Conners" in md


def test_export_removes_names_before_writing_records():
    src = inspect.getsource(X.export)
    assert "redact_events(" in src
    assert src.index("redact_events(") < src.index("write_compact(OUT_DIR / rec[\"file\"]")


def test_a_marked_name_is_removed_in_lower_case_text_and_before_a_job_title(data_dir):
    out = redact(["any questions please call Dan Gregory at [phone removed] thanks",
                  "any questions please call dan gregory at [phone removed] thanks",
                  "jet truck got stuck\nDan Gregory Plant Superintendent", "Dan Gregory Park overflow"], data_dir)
    assert out == [f"any questions please call {N} at [phone removed] thanks",
                   f"any questions please call {N} at [phone removed] thanks",
                   f"jet truck got stuck\n{N} Plant Superintendent", "Dan Gregory Park overflow"]


def test_nhd_water_names_and_towns_are_reference_names(tmp_path, data_dir):
    """data/waters-nhd.json (ingest/waters_from_nhd.py) feeds the lexicon like waters-extra.json."""
    (data_dir / "waters-nhd.json").write_text(json.dumps({"waters": [
        {"name": "Harry Wright Lake", "aliases": ["Plum Bottom Creek"], "towns": ["Manchester"]}]}))
    names, towns = R.reference_names(str(data_dir))
    assert {"Harry Wright Lake", "Plum Bottom Creek", "Burr Creek"} <= set(names) and "manchester" in towns


# ---------------------------------------------------------------- Virginia, Maryland and DC notices (2026-11-03 review)
# The names below are made up (no one's); "Dan" is a common given name, "Zorbel Quillfeather" is not a name at all.

@pytest.mark.parametrize("text, expected", [
    # form fields and referrals
    ("PERSON REPORTING: Dan Quillfeather TYPE OF PROBLEM: Manhole", f"PERSON REPORTING: {N} TYPE OF PROBLEM: Manhole"),
    ("Contact at Scene: Dan Quillfeather; Telephone No.: [phone removed]", f"Contact at Scene: {N}; Telephone No.: [phone removed]"),
    ("Referred to Dan Quillfeather with the local office", f"Referred to {N} with the local office"),
    ("Land belonging to Dan Quillfeather", f"Land belonging to {N}"),
    ("Caller requests a callback from RHMO Dan Quillfeather in reference to this", f"Caller requests a callback from RHMO {N} in reference to this"),
    ("A call was placed to the complaintant, Dan Quillfeather, who stated there was no odor", f"A call was placed to the complaintant, {N}, who stated there was no odor"),
    ("Owned by his niece Dan Quillfeather who lives down the road", f"Owned by his niece {N} who lives down the road"),
    # a job title joined to the name, or a person's title before it: no common given name needed
    ("Zorbel Quillfeather, Chief Operator at the plant, provided notice", f"{N}, Chief Operator at the plant, provided notice"),
    ("Zorbel Quillfeather (Director of Public Works) called back", f"{N} (Director of Public Works) called back"),
    ("Zorbel Quillfeather, Administrative Assistant at the plant, was contacted", f"{N}, Administrative Assistant at the plant, was contacted"),
    ("Mayor Zorbel Quillfeather signed the notice", f"Mayor {N} signed the notice"),
    ("Dispatcher Zorbel Quillfeather reported a septic overflow", f"Dispatcher {N} reported a septic overflow"),
    # a dated notice names its sender first
    ("On June 5, 2026, Zorbel Quillfeather with the town of Wise provided email notification", f"On June 5, 2026, {N} with the town of Wise provided email notification"),
    ("On 6/5/2026 at 10:15 AM, Zorbel Quillfeather reported an overflow", f"On 6/5/2026 at 10:15 AM, {N} reported an overflow"),
    ("Dan Quillfeather, with the Lee County PSA, provided email notification", f"{N}, with the Lee County PSA, provided email notification"),
    # a lone given name that acts like a person, and the later mentions of a removed name
    ("Dan arrived on scene at 5:20 pm and informed the owners", f"{N} arrived on scene at 5:20 pm and informed the owners"),
    ("Dan with the Lee County Authority advised that the pump failed", f"{N} with the Lee County Authority advised that the pump failed"),
    ("Per Dan Quillfeather the pump failed; Dan went home and Quillfeather stayed", f"Per {N} the pump failed; {N} went home and {N} stayed"),
])
def test_notice_templates_name_their_people(data_dir, text, expected):
    assert redact([text], data_dir) == [expected]


@pytest.mark.parametrize("text", [
    "Staff engaged our oncall contractor, Blorvex Civil, and our oncall consultant, Hazen for assistance",
    "Valley St., Oldtown Road, Quillfeather Stret, N. Mechanic Street, Franklin Street",
    "Blockage from an isolation plug lost by Blorvex Bros - owner [name removed]",
    "Per Dan Quillfeather the pump failed on Dan Street and near Prince Dan Road".replace("Per Dan Quillfeather", "Per [name removed]"),
    "Dan Street and Dan Road manholes overflowed",
    "On June 5, 2026, the plant reported an overflow",
])
def test_the_new_templates_leave_companies_streets_and_wording(data_dir, text):
    assert redact([text], data_dir) == [text]


def test_a_follow_up_mention_stops_at_a_place_name(data_dir):
    out = redact(["Per Dan Quillfeather the pump failed on Dan Street; Dan went home"], data_dir)
    assert out == [f"Per {N} the pump failed on Dan Street; {N} went home"]


def test_top_level_text_loses_emails_and_phone_numbers_and_a_quoted_header_name(data_dir):
    recs = [ev(1, "ok", waterbody_text="05/27/2025 email from Quillfeather, Dan <dan@example.org> said the spill stayed on the ground",
               outfall_name="Lift station; call (555) 010-0199 for the key", volume_text="300-1000 gallons",
               advice_text="Report backups to the Public Works Dept. at (555) 010-0199 or help@example.org", material="sewage")]
    out = R.redact_events(recs, data_dir)[0]
    assert out["waterbody_text"] == f"05/27/2025 email from {N} <[email removed]> said the spill stayed on the ground"
    assert out["outfall_name"] == "Lift station; call [phone removed] for the key"
    assert out["volume_text"] == "300-1000 gallons"                              # a range, not a phone number
    assert out["advice_text"] == "Report backups to the Public Works Dept. at (555) 010-0199 or [email removed]"   # an agency's number stays
    assert out["material"] == "sewage"


def test_blocklist_is_read_from_data_build_and_from_data(data_dir):
    (data_dir / "build").mkdir()
    (data_dir / "build" / "name-blocklist.json").write_text(json.dumps({"names": ["Zorbel Quillfeather", "Quibblesnort"]}))
    assert set(R.blocklist(data_dir)) == {"Pat Morrissey", "Zorbel Quillfeather", "Quibblesnort"}
    out = redact(["overflow only when the water is on according to Quibblesnort", "(Zorbel Quillfeather) and (Pat Morrissey)"], data_dir)
    assert out == [f"overflow only when the water is on according to {N}", f"({N}) and ({N})"]
    assert R.build_lexicon([], data_dir).block == R.blocklist(data_dir)
