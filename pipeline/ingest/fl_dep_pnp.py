"""Florida DEP Public Notice of Pollution (PNP) sewage notices -> data/build/events/fl-dep-pnp.json

Source
  Florida Department of Environmental Protection, Public Notice of Pollution, the public ArcGIS
  feature service https://ags.dep.state.fl.us/arcgis/rest/services/External_Services/PNP/FeatureServer
  (no key; maxRecordCount 10,000; research row fl-dep-pnp-arcgis). Layer 0 "Public Notice of
  Pollution (Last 30 Days)" is read on every run; layer 1 "(All)" (about 16,600 notices since July
  2017) is read once with `--backfill`. The HTML list is
  https://prodenv.dep.state.fl.us/DepPNP/reports/viewIncidentDetails. No licence is stated; credit
  "Florida Department of Environmental Protection, Public Notice of Pollution".
  Law: Fla. Stat. 403.077: the owner or operator gives DEP the notice within 24 hours of discovering
  a release reportable to the State Watch Office; DEP posts it within 24 hours of receipt and mails
  it to county subscribers.

Privacy (the service is public but carries personal data)
  The layer has REPORTER_NAME, REPORTER_TITLE, REPORTER_EMAIL, REPORTER_PHONE, CONTACT_NAME,
  CONTACT_EMAIL and CONTACT_PHONE. They are never requested. The request names only these fields:
    INCIDENT_NUMBER, INCIDENT_NAME, INCIDENT_REPORT, DATE_TIME_OF_REPORT, RELEASE_START_DATE_TIME,
    RELEASE_ONGOING, RELEASE_END_DATE_TIME, FACILITY_NAME, FACILITY_ADDRESS_LINE_1,
    FACILITY_ADDRESS_LINE_2, FACILITY_CITY, FACILITY_STATE, FACILITY_ZIP5, AFFECTED_COUNTIES,
    MIGRATED_OFFSITE, MIGRATED_COUNTIES, LATITUDE, LONGITUDE, DATUM, MAP_SOURCE_SCALE, OBJECTID
  plus REPORTER_REALTIONSHIP (sic), the filer's relationship to the facility. That one is reduced at
  once to a code (operator, owner, citizen, other) and deleted from the attributes before anything is
  saved or built: its free-text "OTHER-..." values are never stored. FACILITY_DIRECTIONS (free text)
  is not requested.
  INCIDENT_REPORT is free text that often quotes forms with names, phones and e-mails (the
  "Agencies Notified" list names agency staff; county forms carry "Reported by", "Caller Name",
  "Employee ID", "Future Contact Person", "Form Completed by", "NAME / SIGNATURE" fields). scrub()
  removes every such labelled field up to the next non-personal label (or to the end), names after a
  job title ("Director: ...", "Chief of Staff ...") or before one, names before "with FDEP / DOH ...",
  "Mr./Ms. X", "I <name>", e-mail headers, and any common given name followed by a capitalised word
  that is not a place (drop_given_pairs: "Andrew Hooks received call" loses the name, "Dale Mabry
  Hwy" keeps it; a rare given name can still slip through, so build.redact runs after), then
  common.scrub_text (e-mails, phones, "Inspector X", "contact X at"); build.redact (private names
  in context, the blocklist) runs over the records last. Saved raw pages hold the scrubbed text
  only. INCIDENT_NAME and FACILITY_NAME go through scrub_name_field(): filers often type their own name
  (or a resident's) there, so a value that is only a person's name becomes "[name removed]" and names
  inside it go as in the text; a notice filed by a member of the public keeps no street address
  ("[address removed]": its facility is often the filer's or a neighbour's home). tests/test_fl_dep_pnp.py proves that a contact field and a name in those labels never reach
  a record or the saved raw page.
  The name review of 2026-11-04 (build/name_review.py over all 12,499 records) added the shapes it found: camel-case
  and particle surnames ("Mc...", "De..."), "Reporting Party:", "Contacted by:", "PERSON CONTACTED:", "Assigned To:"
  labels (a blank "____" field is empty), an initial and a surname next to a contact verb, any name before what only a
  person does ("received call", "called me", "were dispatched", "is aware", "began to"), "myself, <name>", a greeting,
  "is named <name>", "<name> (DEP)", "<agency> (<name>)", "<title> for the Village, <name>", a name before an e-mail or
  phone, a capitalised "PER <NAME> W.", "Ranger <surname>", and the State Watch Office's "DEM-<surname>"; a company,
  agency, role, place, water, storm or facility in those places is kept (_company_or_place). common.scrub_text removes a
  phone number typed without separators after a contact word and the house number of an address the text ties to a
  residence or a resident (the street stays); safe_attributes cuts that number from the incident name, facility name and
  address line too. A notice filed by a member of the public keeps no house number anywhere and its point is rounded
  to three decimals (about 100 m, raw._coords_note). Records kept from an earlier run are rebuilt from their raw
  attributes under the current rules (rebuilt()). A rare given name standing alone as the incident name, or a name that
  is also a company's, can still pass: the owner's blocklist (data/build/name-blocklist.json) covers those.
  The value of "Reporting Party:", "Person Contacted:", "Contacted by:" and "Assigned To:" ends at the next contact,
  date or time label when no safe label follows (NAME_VALUE_LABELS), so the account after it stays; a forwarded
  e-mail's addressees ("To: <surname>, <given> <address>") are removed; a Florida town of two words or more
  (data/waters-fl.json) before an action verb is the utility, not a person; a rounded complaint point carries its
  precision (raw._coord_precision_m: about 100 m, or the source's own when coarser).

Which notices become records (the feed mixes every kind of pollution)
  - Notices filed on DEP's wastewater template carry "Wastewater Type: <type> Cause: <cause> Spill
    Volume: <n> Volume Recovered: <n> Waterbodies Impacted: Y|N Clean-up Status: ... Clean-up
    Actions: ...". Untreated (and "Untreated mixed with rainwater") -> sso (cause Bypass -> bypass);
    Partially Treated -> plant_bypass; Unknown -> sso with raw._kind_note. Treated, Reuse
    (reclaimed water) and Biosolids are not sewage records: they are counted in meta.excluded and
    not written (the scope rule of 2026-11-04: untreated and partly treated discharges are sewage
    records, treated effluent, reclaimed water and biosolids are counted but not shown).
  - Notices without the template are read by words (classify()): raw or untreated sewage, a
    sanitary sewer, manhole, lift or pump station, force or gravity main, SSO, or domestic
    wastewater, and the filers' shorthand (LS #, FM, ARV, gravity line) -> sso (partially treated ->
    plant_bypass); a "storm sewer" is not a sewer; fuel, oil, leachate, cooling or industrial water
    released at a pump or lift station, with no word that sewage was released (sewage, overflow, raw,
    untreated ...), is other pollution; treated effluent, reclaimed or reuse water with no sewage word
    -> excluded; fuel, oil, chemicals, stormwater, mining and industrial process water -> excluded
    (other pollution). A template that says Treated (Reuse, Biosolids) while its description reports
    untreated (or partially treated) wastewater is read by the description. raw._pnp_kind says which
    rule took the notice.
  - The counts of what is left out are public and cumulative: data/build/fl-dep-pnp-state.json keeps
    each left-out notice's id and kind, and the events file's meta.left_out, listed_without_status
    and left_out_note (export/build.py PUBLIC_FEED_META) give the totals.
  - Citizen complaints (the scope rule of 2026-11-04): a sewage notice filed by a
    member of the public (relationship OTHER- with citizen, resident, homeowner or neighbour words)
    is a record of event_type unknown and status unknown, raw._pnp_kind "citizen_complaint": kept
    and listed, never coloured as a discharge (docs: unknown records colour only when ongoing),
    and never linked to an operator's notice as a revision (a revision supersedes its parent).

Record rules
  - OBJECTID is renumbered whenever DEP rebuilds the layer (newest first), so it is not an id.
    source_record_id = "<INCIDENT_NUMBER or none>-<report time, local, YYYYmmddTHHMMSS>"; a second
    notice with the same key in one layer gets "-b", "-c" (ordered by point and text). INCIDENT_NUMBER
    is the State Watch Office number as typed by the filer (often missing; sometimes a utility's own
    number).
  - Two or more notices with the same State Watch Office number (eight or nine digits beginning with
    the year) are one incident: the earliest report is the parent, each later one gets
    parent_event_id (a revision: Miami-Dade files Preliminary, Supplementary and Final versions). An
    exact copy (same number, report time and text) gets duplicate_of.
  - Times: DATE_TIME_OF_REPORT holds Florida wall-clock time stored as if it were UTC (reports
    cluster 08:00-17:00 "UTC" and a spill timed 6:15 am in the text was reported 08:25): each epoch
    value is read as UTC and the wall-clock time labelled America/New_York (DEP's clock in
    Tallahassee; the Panhandle west of the Apalachicola keeps Central time, so a filer there may have
    typed Central times into the text). reported_at = that time (DEP's receipt of the notice).
    RELEASE_START_DATE_TIME and RELEASE_END_DATE_TIME are dates (always 00:00): started_at and
    ended_at are local midnight of those dates, time_precision "day" (a day-precision end means the
    end of that day). Times written in the text are not parsed into the record.
  - A notice from an earlier run that the 30-day layer no longer lists gets raw._missing_from_layer_since
    only while its report time is inside the layer's window (older notices simply aged out). A layer
    that answers with no notices at all is an outage (ok false, the previous records kept).
  - Status: RELEASE_ONGOING Y -> ongoing (an end date given while ongoing stays in raw); else an end
    date -> ended; else ended with no ended_at (the notice says the release is not ongoing but
    gives no end; none is invented). An end before the start is dropped with a parse_error.
  - published_at is null: DEP posts within 24 hours of receipt but the layer has no posting time.
    source_updated_at is null (no edit time). raw._first_seen_at is our clock.
  - Volume: the template's Spill Volume (the form asks for gallons); else a labelled figure in the
    text ("Sewage Released in Gallons:", "Gallons released:", "Final Spill Volume:"); else the
    first "<n> gallons" not next to "recovered" (raw._volume_basis says which). Volume Recovered is
    kept in raw.
  - Water: the notice gives only "Waterbodies Impacted: Y/N" (raw.reached_water true/false; N means
    the report is kept but not placed on a water, unless its text names a water reached: below). A
    water named in the text after "into", "to", "impacted", "reached" ... ("Storm drain discharges
    into Pottsburg Creek") is waterbody_text
    (raw._water_names lists every one found); water_slugs stay empty until Florida's water records
    are built.
  - The text against the form (owner, 2026-11-04): a notice whose form says "Waterbodies Impacted: N" while its
    text says the sewage entered, may have entered, reached, impacted, discharged to or flowed into a named water
    ("overflowed and flowed into Example Creek", "may have entered Example Bayou", "the storm drain discharges into
    the Example River"), not negated in its part of the sentence ("did not flow into", "no discharge to", "none
    entered", "contained before reaching", "prevented from entering"), is placed on that water: raw.reached_water
    "text", waterbody_text that water, raw._reached_water_basis TEXT_REACHED_BASIS, raw._reached_water_words the
    words, raw._form_waterbodies_impacted "N". build/status.py colours such a record with the site's caution only
    (rule text_caution, never red). text_reached() is the rule.
  - Coordinates: LATITUDE/LONGITUDE (WGS84 decimal degrees, typed or mapped by the filer; DATUM and
    MAP_SOURCE_SCALE kept). A point outside Florida is dropped (raw._coords_rejected).
    coord_precision_m from the number of decimals given.
  - Operator: an NPDES number (FL0nnnnnn) in the facility name or text is npdes_permit; a state
    domestic wastewater permit (FLAnnnnnn) goes to raw._state_permit. discharger_id from
    data/dischargers.json by that permit, else by the operator names in OPERATORS below.

Cadence: hourly (notices appear within hours; median 1.5 days from release date to report).
Run from pipeline/:  python -m ingest.fl_dep_pnp [--backfill] [--file saved.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import string
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from build import redact
from common import (BUILD_DIR, DATA_DIR, EVENTS_DIR, HEADERS, OPERATOR_WORDS, ROOT, drop_house_numbers, event, now_iso,
                    parse_volume_gal, path_notes_to_meta, read_json, residence_numbers, save_raw, scrub_text,
                    strip_house_numbers, write_events, write_json)

SOURCE_ID = "fl-dep-pnp"
SERVICE = "https://ags.dep.state.fl.us/arcgis/rest/services/External_Services/PNP/FeatureServer"
LAYER_CURRENT = f"{SERVICE}/0"
LAYER_ALL = f"{SERVICE}/1"
PAGE_URL = "https://floridadep.gov/sec/sec/content/public-notice-pollution"
STATE_FILE = BUILD_DIR / "fl-dep-pnp-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Florida Department of Environmental Protection (Public Notice of Pollution)"
CREDIT = "Florida Department of Environmental Protection, Public Notice of Pollution (Fla. Stat. 403.077)"
SAFE_FIELDS = ("INCIDENT_NUMBER", "INCIDENT_NAME", "INCIDENT_REPORT", "DATE_TIME_OF_REPORT", "RELEASE_START_DATE_TIME",
               "RELEASE_ONGOING", "RELEASE_END_DATE_TIME", "FACILITY_NAME", "FACILITY_ADDRESS_LINE_1",
               "FACILITY_ADDRESS_LINE_2", "FACILITY_CITY", "FACILITY_STATE", "FACILITY_ZIP5", "AFFECTED_COUNTIES",
               "MIGRATED_OFFSITE", "MIGRATED_COUNTIES", "LATITUDE", "LONGITUDE", "DATUM", "MAP_SOURCE_SCALE", "OBJECTID")
RELATIONSHIP_FIELD = "REPORTER_REALTIONSHIP"      # requested for the citizen test only; never stored
FL_BOX = (-87.7, 24.3, -79.8, 31.1)             # lon min, lat min, lon max, lat max
TIME_BASIS = ("DATE_TIME_OF_REPORT holds Florida wall-clock time stored as if it were UTC: each epoch value is read as UTC "
              "and the wall-clock time labelled America/New_York. Release start and end are dates (00:00) and are read as "
              "local dates.")

# ---------------------------------------------------------------- privacy: the free text

# labels whose value is a person, a person's id or a contact detail
PERSON_LABEL = re.compile(
    r"(?i:\b(?:agencies\s+notified|other\s+agencies\s+notified|notified|reported\s+by(?:\s+wasd\s+employee\?)?|"
    r"caller(?:'s)?\s+name|caller|form\s+completed\s+by|completed\s+by|prepared\s+by|submitted\s+by|"
    r"future\s+contact\s+person(?:'s\s+phone\s+number)?|contact\s+person|contact\s+name|contact\s+information|"
    r"point\s+of\s+contact|on[- ]scene\s+contact|employee\s+id|employee\s+name|reporter(?:'s)?\s+name|reporter|"
    r"incident\s+reported\s+by|person\s+reporting|responsible\s+party(?:\s+name)?|suspected\s+responsible\s+party|"
    r"signature|signed|e-?mail(?:\s+address)?|phone(?:\s+number|\s*#)?|sewer\s+phone\s+number|cell|fax|"
    r"name\s+of\s+(?:reporter|caller|person)|reporting\s+party|person\s+contacted|contacted\s+by|assigned\s+to)\b)"
    r"|\b(?:NAME|Name)\b")
# labels that are safe to resume at (a field of the report, not a person)
SAFE_LABEL = re.compile(
    r"(?i:\b(?:incident\s+description|description|wastewater\s+type|cause|spill\s+volume|volume\s+recovered|"
    r"waterbod(?:y|ies)\s+(?:impacted|affected|name)|water\s+body\s+(?:affected|name)|body\s+of\s+water\s+name|"
    r"clean-?up\s+(?:status|actions|measures)|utility\s+name|permitted\s+utility(?:\s+(?:name|id))?|path\s+of\s+flow|"
    r"discharge\s+(?:caused\s+by|due\s+to)|caused\s+by\s+asset\s+type|sewage\s+released\s+in\s+gallons|"
    r"recovered\s+amount\s+in\s+gallons|gallons\s+(?:released|recovered)|time\s+release\s+started|"
    r"time\s+action\s+taken\s+at\s+site|location\s+of\s+discharge|additional\s+location\s+description|location|"
    r"incident\s+location|incident\s+address|address|county|district|city|state|zip(?:\s+code)?|latitude|longitude|"
    r"pipe\s+(?:size|material)|weather\s+conditions|method\s+of\s+(?:public\s+notification|disinfection)|"
    r"type\s+of\s+water\s+discharge|wastewater\s+characteristics|facility\s+(?:type|name)|initial\s+spill\s+volume|"
    r"final\s+spill\s+volume|date\s+of\s+release|time\s+discovered|incident\s+date/time|date/time\s+reported|"
    r"swo\s+incident\s+number|wasd\s+incident\s+#|version(?:\s+type)?|incident\s+version\s+created\s+on|job\s+order\s+#|"
    r"discharge\s+stopped\s+on|post\s+signs|feet\s+into\s+surface\s+water|status|update|worksheets?|"
    r"satellite\s+collection\s+systems|released\s+estimate\s+range|raw\s+sewage\s*/\s*treated\s+effluent|"
    r"injuries|this\s+situation\s+involves|release\s+occurred\s+from\s+a|dep\s+use\s+only|written\s+report\s+requested|"
    r"due\s+date|represents|affiliation|title|employee\s+title|relationship|installation\s+name|reported\s+to\s+swo\s+on|"
    r"severity|state\s+watch\s+office|date\s*/\s*time|date)\s*(?:[:?]|-\s|\u2013\s))")
JOB_TITLE = (r"(?:director|manager|supervisor|superintendent|coordinator|specialist|engineer|operator|chief\s+of\s+staff|"
             r"chief|foreman|technician|officer|administrator|dispatcher|mayor|commissioner|inspector|investigator|"
             r"analyst|planner|scientist|president|chairman|chair|deputy|representative|agent|consultant|ranger)")
# a given name and a surname; either may be camel-case or carry a particle ("McSample", "DeSample", "O'Sample"), and a
# middle initial or a middle name may stand between ("Pat E. Sample", "Lee Ann McSample")
_GNAME = r"(?:Ma?c|De|Di|Da|La|Le|O')?[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?"
_SNAME = r"(?:Ma?c|De|Di|Da|La|Le|O')?[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*"
_PNAME = rf"{_GNAME}(?:\s+[A-Z]\.?|\s+[A-Z][a-z]+(?=\s+(?:Ma?c|De|O')[A-Z]))?\s+{_SNAME}"
_PNAME_CAPS = r"[A-Z]{2,}(?:\s+[A-Z]\.?)?\s+[A-Z]{2,}(?:[-'][A-Z]+)?"
TITLE_THEN_NAME = re.compile(rf"(\b(?i:{JOB_TITLE})\b\s*[:,-]?\s+)(?:{_PNAME}|{_PNAME_CAPS})\b")
NOT_PERSON_WORDS = set("""staff crews crew department utilities utility county city town village district public works
water waste sewer wastewater field the our their state florida dep fdep doh fdoh health environmental protection division
office team services service operations maintenance collection collections plant facility station lift compliance
permitting engineering regulatory systems system senior lead assistant general project safety quality control program
laboratory lab treatment distribution reclamation sanitation sanitary pump pumping reuse stormwater storm utility's
on-call on call shift night day plant's wwtp wwtf wrf awt wrrf chief interim acting deputy fl dept environment
emergency management watch swo""".split())
NAME_WITH_AGENCY = re.compile(
    rf"\b({_PNAME})(\s+(?:with|from)\s+(?:the\s+)?(?:(?:[A-Z][\w.-]*|of)\s+){{0,3}}(?i:FDEP|DEP|FDOH|DOH|Department|Dept|"
    rf"Health|State\s+Watch|SWO|Utilities|Public\s+Works|Sheriff|Police|Fire)\b)")
SPACE = re.compile(r"[ \t\r\f\v]+")
LABEL_END = re.compile(r"\s*(?::|#|\?|-\s|\u2013\s)")
NAME_OF_THING = set("""utility facility company business contractor street water body storm location station plant system
site severe beach waterbody road project product chemical vessel boat vehicle carrier""".split())
HONORIFIC_NAME = re.compile(r"\b(?:Mr|Mrs|Ms|Miss)\.?\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)*(?:\s+[A-Z][a-z]+)?")
FIRST_PERSON_NAME = re.compile(rf"\b((?:I|[Mm]y\s+name\s+is|[Tt]his\s+is|[Mm]yself,?)\s+)({_PNAME})\b")
NAME_THEN_TITLE = re.compile(rf"\b({_PNAME})(?=,?\s+(?:[A-Z][A-Za-z/&]+\s+){{0,3}}(?i:{JOB_TITLE})\b)")


# A common given name followed by a capitalised word is taken as a person's name in this feed's free text (filers name
# staff, residents and contractors in passing: "At 6:51 PM <name> received call", "call <name> at"), unless the next
# word, or the word after the pair, makes it a place: a street, a park, a building, a company, a water.
PLACE_AFTER = set("""dr drive parkway pkwy hwy highway hall causeway turnpike tpke lift master plumbing construction lagoon
state park chapel island bridge blvd boulevard bay trail ln lane rd road st street ave avenue way ct court cir circle pl
place ter terrace loop run creek river lake pond canal beach shores estates village gardens heights apartments apts
elementary school middle high college university center centre plaza mall church hospital lift station pump ps ls wwtp
wwtf wrf awt plant facility utilities inc llc co company corp fl harbor harbour haven sound springs air force base
field""".split())
PLACE_PAIRS = {"wesley chapel", "mary esther", "holly hill", "marco island", "dana shores", "martin luther", "bob sikes",
               "dale mabry", "courtney campbell", "ronald reagan", "andrew jackson", "jose marti", "john young",
               "lake mary", "fort myers", "port charlotte", "palm bay", "st johns", "st lucie", "santa rosa"}
FL_PLACE_GIVEN = {"orlando", "stuart", "wesley", "lynn", "marco", "dana", "holly", "charlotte"}
# a person named after a cue ("spoke with X Y", "contact X Y", "Thank you X Y", "per X Y"): any capitalised pair that is
# not a place, an organisation or a storm
CUE_NAME = re.compile(r"(\b(?i:(?:contacted|notified|visited|e-?mailed|reported)\s+by|spoke\s+(?:with|to)|discussed(?:\s+individually)?\s+with|voice\s+message\s+from|"
                      r"(?:a\s+)?call\s+from|called\s+by|contacted|contact|call|thank\s+you|thanks|regards|sincerely|"
                      r"per|rep\.?|met\s+with|talked\s+(?:with|to))\s*,?\s+)"
                      r"((?:Ma?c|De|O')?[A-Z][a-z]+(?:\s+[A-Z]\.)?\s+(?:Ma?c|De|O')?[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?|"
                      r"[A-Z]\.\s?(?:Ma?c|De|O')?[A-Z][a-z]{2,})\b")
NOT_FIRST = set("""hurricane tropical state asset lift contractor center vac initial public field florida duke star simple
aqua subject incident bypass pumper risk underground seacoast sun northeast northwest southeast southwest north south
east west central the a an our their county city town village utility utilities emergency environmental code customer
service services dispatch central sewer water wastewater storm pump plant main""".split())
# a given name right after these words names a storm or a place, not a person
NAMED_AFTER = re.compile(r"\b(?:hurricane|tropical\s+storm|tropical\s+depression|TS|TD|lake|mt\.?|mount|port\s+st\.?|"
                         r"ponce\s+de|san|santa|saint|st\.?)\s+$", re.I)
GIVEN_PAIR = re.compile(r"(?=\b([A-Z][a-z]+|[A-Z]{2,})\s+((?:Ma?c|De|O')?[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?|"
                        r"[A-Z]{2,}(?:[-'][A-Z]+)?)\b(\s+\w+)?)")
BLANK_VALUE = re.compile(r"\s*[:#?-]?\s*_{3,}(?=\s*$|\s+\*?(?:SPILL|SOURCE|AREA|FACILITY|INCIDENT|LOCATION|CAUSE|ACTION|DATE|"
                         r"TIME|COUNTY|STATE|NOTIFICATION|AGENCIES|COMMENTS|REMARKS|DESCRIPTION|WASTEWATER|DISCHARGE|"
                         r"PERMIT|RESPONSIBLE|METHOD|WRITTEN|CORRECTIVE|EFFLUENT|OTHER)\b)")
# words of PERSON_LABEL that are labels only with a colon (or "#", "-") after them: "crews were notified", "contacted by
# phone", "the reporting party advised", "a contractor was assigned to" are ordinary text
# labels whose value is one person or one office ("Reporting Party: <name> <id> Contact Number: ..."): when no safe
# label follows, the value ends at the next contact-number, phone, e-mail, date or time label or at a line break within
# VALUE_REACH characters, so that the account after it (the volume, the water) is not cut with the name
NAME_VALUE_LABELS = {"reporting party", "person contacted", "contacted by", "assigned to"}
VALUE_REACH = 80
VALUE_STOP = re.compile(r"\n|\s(?=(?i:(?:contact|phone|cell|telephone|mobile|office|work)\s*(?:number|no\.?|#)|phone|cell|"
                        r"e-?mail|date\s*/\s*time|date|time)\s*[:#])")
LABEL_ONLY_WITH_COLON = {"notified", "caller", "cell", "signed", "reporter", "phone", "reporting party", "person contacted",
                         "contacted by", "assigned to"}
# a person named by what a person does: "<name> received a call", "<name> and <name> arrived", "<initial>. <surname>
# contacted ...", "<name> is aware" (any name, not only a common given name: a filer's colleague often has a rare one);
# a company, an agency, a place or a storm before the verb is kept (COMPANY_WORDS, NOT_PERSON_WORDS, PLACE_AFTER, NOT_FIRST)
_ACT_PERSON = (r"(?:received\s+(?:a\s+|the\s+)?(?:phone\s+)?call|called\s+(?:me|us)|(?:was|were|where)\s+dispatched|is\s+aware|was\s+aware|"
               r"began\s+to|begun\s+to|visited\s+the\s+site|went\s+out|drove\s+(?:out|to))")
_ACT = (rf"(?:{_ACT_PERSON}|arrived|responded|contacted|called|notified|informed|advised|stated|said|reported|spoke|met|"
        r"confirmed|explained|instructed|requested|emailed|e-mailed|texted)")
_INITIAL_SURNAME = r"[A-Z]\.\s?(?:Ma?c|De|O')?[A-Z][a-z]{2,}"
_ANY_NAME = rf"(?:{_PNAME}|{_INITIAL_SURNAME})"
_MORE_NAMES = rf"((?:\s*(?:,|and|&)\s+(?:{_ANY_NAME}|[A-Z][a-z]+\s+[A-Z]\b\.?))*)"
NAME_BEFORE_ACTION = re.compile(rf"(?<![\w.'-])({_PNAME}){_MORE_NAMES}(?=,?\s+{_ACT_PERSON}\b)")
INITIAL_BEFORE_ACTION = re.compile(rf"(?<![\w.'-])({_INITIAL_SURNAME}){_MORE_NAMES}"
                                   rf"(?=,?\s+(?:(?:then|also|later|immediately|subsequently|again)\s+)?{_ACT}\b)")
# the last word of a company's name ("Example Broadband", "Example Underground"), never a surname
COMPANY_SUFFIX = set("""inc llc co corp company construction contracting contractors contractor underground plumbing septic
systems group communications telecommunications broadband technologies technology solutions services pumping drilling
boring cable engineering energy enterprises industries partners associates management development builders realty
properties excavating paving utilities environmental enviro rooter aquatics electric electrical marine harbors""".split())
VENUE_WORDS = {"golf", "course", "club", "marina", "resort", "apartments", "condominium", "community", "subdivision"}
JOB_WORDS = set("""director manager supervisor superintendent superintendant coordinator specialist engineer operator chief
foreman technician tech officer administrator dispatcher mayor commissioner inspector investigator analyst planner
scientist president chairman chair deputy representative agent consultant ranger mechanic electrician laborer labor
worker workers crew personnel""".split())
COMPANY_WORDS = set("""inc llc co corp company marine electric electrical construction contracting contractors contractor underground
plumbing septic systems system group communications communication telecommunications broadband technologies technology
solutions services service pumping drilling boring cable engineering energy power gas barrel enterprises industries
partners associates management development developers builders homes realty properties excavating paving utilities
environmental enviro rooter drain drains vac hauling transport trucking towing landscaping lawn irrigation tree pest
pharmacy restaurant grill bar hotel motel resort club park camp church school academy university college hospital
center store market mall plaza dept department office division county city town village state federal national
american florida gulf atlantic coast coastal bay river lake beach island key keys south north east west central
team crew crews staff police sheriff fire rescue ems dot fdot fpl teco duke comcast att verizon spectrum aquatics harbors
harbor vac vacs truck trucks tanker tankers unit units jet support ops operations point desk room line dispatch personnel
employee employees notification summary report notice pollution inspection annual number information update incident
form spill sso overflow leak break release discharge event warning watch emergency response subject received size
categories sent attachment attachments cell phone office mobile tel fax email e-mail
fertilizer phosphate phosphates mining mine mines ranch nursery nurseries citrus groves plantation port yacht yachts
boatyard bayou slough prairie hammock preserve sanctuary refuge seafood brewing brewery packing chemical chemicals paper
lumber concrete asphalt aggregates materials recycling landfill disposal logistics railroad railway rail airlines airport
shipyard navy army pointe isles isle cove inlet lagoon estuary reservoir canal creek river sheriff's""".split())
# an initial and a surname after a contact verb ("then called S. Sample to respond")
CUE_INITIAL = re.compile(rf"(\b(?i:called|contacted|notified|informed|advised|told|asked|met\s+with|spoke\s+(?:with|to)|per|by)\s+)"
                         rf"({_INITIAL_SURNAME})\b")
# the same in a capitalised report ("PER JOHN W.", "CONTACTED JANE SAMPLE"): a cue, then a word and an initial or a common
# given name and a word
CUE_NAME_CAPS = re.compile(r"\b((?:PER|CONTACTED|SPOKE\s+(?:WITH|TO)|CALLED\s+BY|REPORTED\s+BY|NOTIFIED\s+BY|MET\s+WITH|CALL\s+FROM)\s+)"
                           r"([A-Z]{2,}(?:\s+[A-Z]\.?(?![\w])|\s+[A-Z]{2,}(?:[-'][A-Z]+)?))")
# a rank or a ranger's title before a surname alone ("Ranger Sample", "Deputy Sample", "Officer Sample")
RANK_SURNAME = re.compile(r"\b((?:Ranger|Deputy|Sergeant|Sgt\.?|Lieutenant|Lt\.?|Captain|Capt\.?|Officer|Trooper|Corporal|Cpl\.?|"
                          r"Detective|Det\.?|Firefighter)\s+)((?:Ma?c|De|O')?[A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b(?!\s+[A-Z][a-z])")
# the State Watch Office signs its forwarded reports "<date> / DEM-<surname>" (Division of Emergency Management)
AGENCY_DASH_SURNAME = re.compile(r"\b((?:F?DEM|SWO|SWP)-)(?:Ma?c|De|O')?[A-Z][a-z]+(?:-[A-Z][a-z]+)?\b")
GREETING_NAME = re.compile(r"\b((?:Hello|Hi|Dear|Good\s+(?:morning|afternoon|evening)),?\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?=\s*[,:!])")
# a name right before a contact label whose value is gone ("Lee Ann Sample E-mail: [removed]")
NAME_BEFORE_CONTACT = re.compile(rf"\b({_PNAME}|[A-Z][a-z]+\s+[A-Z][a-z]+\s+(?:Ma?c|De|O')?[A-Z][a-z]+)"
                                 r"(?=\s*,?\s*(?:(?:E-?mail|Phone|Cell|Tel|Office|Mobile)\b\s*(?:#|:)?\s*\[(?:removed|phone removed|email removed)\]|"
                                 r"(?:and\s+)?<?[\w.+-]+@[\w-]+\.|\[(?:phone|email) removed\]))")
# a person of an agency: "<name> (DEP)", "EPC of <County> (<name>)", "<title> for the Village, <name>"
_AGENCY_ABBR = r"(?:F?DEP|F?DOH|EPC|SWO|DERM|EPD|DEM|FWC|USACE|EPA)"
NAME_THEN_AGENCY = re.compile(rf"\b({_PNAME})(?=\s*\(\s*{_AGENCY_ABBR}\s*\))")
AGENCY_THEN_NAME = re.compile(rf"((?:\b{_AGENCY_ABBR}|\b(?i:county|department|dept|commission|district|utilities|program|office))\s*\(\s*)"
                              rf"({_PNAME})(?=\s*\))")
TITLE_ORG_NAME = re.compile(rf"(\b(?i:{JOB_TITLE})\s+(?i:for|of|with|at)\s+(?:the\s+)?(?:[A-Z][\w.&'-]*\s+){{0,3}}[A-Z][\w.&'-]*\s*,\s+)"
                            rf"({_PNAME}(?:\s+[A-Z][a-z]+)?)\b")
# a person given by a name cue, a lone given name included: "the owner is named <name>", "her name is <name>"
NAMED_CUE = re.compile(r"(\b(?i:(?:owner|resident|person|man|woman|lady|gentleman|caller|neighbou?r|tenant|customer|contact|he|she)"
                       r"\s+(?:is\s+|was\s+)?named|(?:his|her|their)\s+name\s+(?:is|was))\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")
# a forwarded e-mail's addressees ("To: Sample, Pat <pat@example.org>; Example, Lee S <...>"): the words right before an
# address in angle brackets are a person's name, in either order
EMAIL_ADDRESSEE = re.compile(r"(?<![\w\[])(?:[A-Z][A-Za-z'.-]*,?\s+){1,4}(?=<\s*(?:\[email removed\]|[\w.+-]+@))")
EMAIL_HEADER = re.compile(r"\bFrom:?\s+[^\n]{0,240}?\bSent:?\s+\w+day,?\s+\w+\s+\d{1,2},\s+\d{4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M")


def _given_names():
    from build.redact import FIRST_NAMES
    return FIRST_NAMES


_FL_TOWNS: set[str] | None = None


def _fl_towns() -> set[str]:
    """Florida's towns of two words or more ("cape coral", "fort lauderdale", "punta gorda"), from the towns of the state's
    water records (data/waters-fl.json): a city before "received a call" or "began to" is the utility, not a person."""
    global _FL_TOWNS
    if _FL_TOWNS is None:
        towns = set()
        waters = (read_json(DATA_DIR / "waters-fl.json", {}) or {}).get("waters") or []
        for w in waters.values() if isinstance(waters, dict) else waters:
            for t in (w.get("towns") or []) if isinstance(w, dict) else []:
                t = re.sub(r"\s+", " ", str(t).lower().replace(".", "")).strip()
                if " " in t:
                    towns.add(t)
                    towns.add(" ".join(t.split()[:2]))     # "royal palm beach" is also written "Royal Palm"
        _FL_TOWNS = towns
    return _FL_TOWNS


# a facility named after a person: the words right after the name ("<name> Regional WWTF", "<name> Water Reclamation
# Facility", "<name> Energy Center"); a name right after a station number is the station's ("Lift Station #814 <name>")
FACILITY_AFTER = re.compile(r"[\"'\u201d]?[ ]{1,2}(?i:(?:regional|reclamation|treatment|plant|facility|wwtp|wwtf|wrf|wrrf|awt|awtp|awwtf|wwrf|"
                            r"rf|generating|combined|advanced|memorial|elementary)\b|(?:water|waste|wastewater|energy|power)[ ]{1,2}"
                            r"(?:reclamation|treatment|plant|facility|center|station|wwtp|wwtf)\b)")
STATION_BEFORE = re.compile(r"(?i:\b(?:lift|pump(?:ing)?)\s+station|\bL\.?S\.?|\bP\.?S\.?)\s*(?:no\.?|#)?\s*[\w-]*\d[\w-]*\s*[-:]?\s*$")


def drop_given_pairs(s: str) -> str:
    first = _given_names()
    cuts, last_end = [], -1
    for m in GIVEN_PAIR.finditer(s):           # overlapping: "PM Andrew Sample" tries "PM Andrew" and "Andrew Sample"
        g, n = m.group(1), m.group(2)
        if m.start(1) < last_end:
            continue
        nxt = (m.group(3) or "").strip().lower().strip(".,")
        if g.lower() not in first or f"{g} {n}".lower() in PLACE_PAIRS or g.lower() in FL_PLACE_GIVEN:
            continue
        if re.search(r"\b(?:of|in|at|near)\s+$", s[max(0, m.start() - 6):m.start()], re.I) and nxt in ("", "and", "on", "in"):
            continue
        if NAMED_AFTER.search(s[max(0, m.start() - 16):m.start()]):
            continue                          # "Hurricane Ian ...", "TS Debby ...", "Lake Mary Jane": a storm or a place
        if n.lower() in PLACE_AFTER or n.lower() in NOT_PERSON_WORDS or nxt in PLACE_AFTER:
            continue
        if STATION_BEFORE.search(s[max(0, m.start() - 24):m.start()]):
            continue                          # "Lift Station #814 <name>": the station's name
        if FACILITY_AFTER.match(s, m.end(2)):
            continue                          # "<name> Water Reclamation Facility", "<name> Regional WWTF": a facility
        end = m.end(2)
        cuts.append((m.start(1), end))
        last_end = end
    for a, b in reversed(cuts):
        s = s[:a] + "[name removed]" + s[b:]
    return s


def _drop_cue_name(m: re.Match) -> str:
    w = m.group(2).split()
    nxt = re.match(r"\s+([A-Za-z]+)", m.string[m.end():])
    if w[0].lower() in NOT_FIRST or _not_person(m.group(2)) or w[-1].lower() in PLACE_AFTER or \
            w[-1].lower().strip(".") in NOT_FIRST or w[-1].lower().strip(".") in COMPANY_SUFFIX | JOB_WORDS or \
            (nxt and nxt.group(1).lower() in COMPANY_SUFFIX | PLACE_AFTER | VENUE_WORDS | AGENCY_NEXT) or \
            re.sub(r"'s$", "", w[-1].lower()) in AGENCY_TAIL or _is_fl_town(m.group(2)):
        return m.group(0)                     # "notified by <County> Sheriff's Office", "spoke with Cape Coral"
    return m.group(1) + "[name removed]"


def _not_person(name: str) -> bool:
    return any(w.lower().strip(".,") in NOT_PERSON_WORDS for w in name.split())


def _drop_name_with_agency(m: re.Match) -> str:
    words = m.group(1).lower().split()
    if any(w.strip(".") in NOT_PERSON_WORDS for w in words):
        return m.group(0)
    return "[name removed]" + m.group(2)


AGENCY_TAIL = {"sheriff", "sheriffs", "police", "fire", "rescue", "ems"}
AGENCY_NEXT = {"office", "department", "dept", "division", "district"}


def _is_fl_town(name: str) -> bool:
    return re.sub(r"\s+", " ", name.lower().replace(".", "")).strip() in _fl_towns()


def _place_after(m: re.Match) -> bool:
    nxt = re.match(r"\s+([A-Za-z]+)", m.string[m.end():])
    return bool(nxt and _place_or_company_word(nxt.group(1)))


def _place_or_company_word(word: str) -> bool:
    """The word after a name that makes the name a place's or a company's ("<name> Street", "<name> Telecommunications")."""
    w = word.lower().strip(".,'")
    return w in COMPANY_WORDS or w in PLACE_AFTER or w in redact.KILL or w in OPERATOR_WORDS


def _company_or_place(name: str, function_words: bool = True) -> bool:
    """A capitalised run that is a company, an agency, a role, a place, a water or a storm, not a person; with
    function_words, also one with an ordinary word in it ("Yes X No")."""
    words = [w.lower().strip(".,'") for w in re.split(r"[\s&,]+", name) if w]
    words = [w[:-2] if w.endswith("'s") else w for w in words]
    joined = " ".join(words)
    if any(f" {t} " in f" {joined} " for t in _fl_towns()):
        return True                                     # "Cape Coral", "Fort Lauderdale": a city
    return any(w in COMPANY_WORDS or w in NOT_PERSON_WORDS or w in PLACE_AFTER or w in redact.KILL or w in OPERATOR_WORDS
               or w in JOB_WORDS or (function_words and len(w) > 1 and w in redact.FUNCTION) for w in words) or \
        (words and words[0] in NOT_FIRST) or " ".join(words[:2]) in PLACE_PAIRS


def _drop_named_before_action(m: re.Match) -> str:
    """The names of NAME_BEFORE_ACTION, each unless it is a company, an agency, a place or a storm."""
    first, rest = m.group(1), m.group(2) or ""
    before = m.string[max(0, m.start() - 16):m.start()]
    if _company_or_place(first) or NAMED_AFTER.search(before) or re.search(r"\b(?i:city|town|county|village)\s+of\s+$", before):
        return m.group(0)
    rest = re.sub(rf"({_ANY_NAME}|[A-Z][a-z]+\s+[A-Z]\b\.?)", lambda x: x.group(0) if _company_or_place(x.group(0)) else "[name removed]", rest)
    return "[name removed]" + rest


def _drop_caps_cue(m: re.Match) -> str:
    words = m.group(2).split()
    w0 = words[0].lower()
    if _company_or_place(words[0]) or w0 in NOT_FIRST or len(words[0]) < 3:
        return m.group(0)
    if words[1].lower() in redact.FUNCTION:                     # "SPOKE WITH JAMIE FROM ...": the given name alone
        return m.group(1) + ("[name removed] " + words[1] if w0 in _given_names() else m.group(2))
    if _company_or_place(m.group(2)):
        return m.group(0)
    if re.fullmatch(r"[A-Z]\.?", words[1]) or w0 in _given_names():
        return m.group(1) + "[name removed]"
    return m.group(0)


def _drop_title_name(m: re.Match) -> str:
    name = m.group(0)[len(m.group(1)):]
    if any(w.lower().strip(".") in NOT_PERSON_WORDS for w in name.split()):
        return m.group(0)
    return m.group(1) + "[name removed]"


def scrub(text) -> str | None:
    """The notice text with personal fields removed (see the module docstring). Every labelled personal field
    loses its value up to the next safe label, or to the end of the text when none follows."""
    if text is None:
        return None
    s = str(text).replace("\u00bf", "'").replace("&#8209;", "-")
    out, pos = [], 0
    while True:
        m = PERSON_LABEL.search(s, pos)
        if not m:
            out.append(s[pos:])
            break
        if m.start() and s[m.start() - 1] == "[":
            out.append(s[pos:m.end()])     # "[email removed]", "[e-mail header removed]": a marker, not a label
            pos = m.end()
            continue
        blank = BLANK_VALUE.match(s, m.end())
        if blank:
            out.append(s[pos:blank.end()])     # "PERSON CONTACTED: ________": an empty form field
            pos = blank.end()
            continue
        # a bare "Name"/"NAME" only counts as a label when a colon (or a form's table header) follows
        after = s[m.end():m.end() + 4]
        bare = m.group(0).lower() == "name"
        before = s[max(0, m.start() - 20):m.start()].split()
        if bare and before and before[-1].strip(".,").lower() in NAME_OF_THING:
            out.append(s[pos:m.end()])     # "Utility Name:", "Facility Name:": a thing, not a person
            pos = m.end()
            continue
        if bare and not LABEL_END.match(after) and not re.search(r"\b(?:Name|NAME)\s+(?:Represents|Title|Phone)", s[m.start():m.start() + 40]):
            out.append(s[pos:m.end()])
            pos = m.end()
            continue
        if not bare and re.sub(r"\s+", " ", m.group(0).lower()) in LABEL_ONLY_WITH_COLON and not LABEL_END.match(after):
            out.append(s[pos:m.end()])   # an ordinary word ("crews were notified"), not a form label
            pos = m.end()
            continue
        out.append(s[pos:m.end()])
        nxt = SAFE_LABEL.search(s, m.end())
        if re.sub(r"\s+", " ", m.group(0).lower()) in NAME_VALUE_LABELS:
            stop = VALUE_STOP.search(s, m.end(), m.end() + VALUE_REACH)
            if stop and (nxt is None or stop.start() < nxt.start()):
                out.append(": [removed] ")
                pos = stop.end()
                continue
        # the value must not swallow a safe label that starts right after (empty value)
        if nxt:
            out.append(": [removed] " if not s[m.end():nxt.start()].strip(" :#?-") else ": [removed] ")
            pos = nxt.start()
        else:
            out.append(": [removed]")
            break
    s = "".join(out)
    s = re.sub(r"(:\s*)+: \[removed\]", ": [removed]", s)
    s = TITLE_THEN_NAME.sub(_drop_title_name, s)
    s = NAME_WITH_AGENCY.sub(_drop_name_with_agency, s)
    s = NAME_THEN_TITLE.sub(lambda m: m.group(0) if _not_person(m.group(1)) else "[name removed]", s)
    s = FIRST_PERSON_NAME.sub(lambda m: m.group(0) if _not_person(m.group(2)) else m.group(1) + "[name removed]", s)
    s = TITLE_ORG_NAME.sub(lambda m: m.group(0) if _company_or_place(m.group(2)) else m.group(1) + "[name removed]", s)
    s = NAME_BEFORE_CONTACT.sub(lambda m: m.group(0) if _company_or_place(m.group(1)) else "[name removed]", s)
    s = NAME_THEN_AGENCY.sub(lambda m: m.group(0) if _company_or_place(m.group(1)) else "[name removed]", s)
    s = AGENCY_THEN_NAME.sub(lambda m: m.group(0) if _company_or_place(m.group(2)) else m.group(1) + "[name removed]", s)
    s = NAMED_CUE.sub(lambda m: m.group(0) if _company_or_place(m.group(2)) else m.group(1) + "[name removed]", s)
    s = GREETING_NAME.sub(lambda m: m.group(0) if _company_or_place(m.group(2)) else m.group(1) + "[name removed]", s)
    s = CUE_NAME_CAPS.sub(_drop_caps_cue, s)
    s = HONORIFIC_NAME.sub("[name removed]", s)
    s = EMAIL_HEADER.sub("[e-mail header removed]", s)
    s = EMAIL_ADDRESSEE.sub("[name removed] ", s)
    s = drop_given_pairs(s)
    s = CUE_NAME.sub(_drop_cue_name, s)
    s = CUE_INITIAL.sub(lambda m: m.group(0) if _company_or_place(m.group(2)) or _place_after(m) else m.group(1) + "[name removed]", s)
    s = NAME_BEFORE_ACTION.sub(_drop_named_before_action, s)
    s = INITIAL_BEFORE_ACTION.sub(_drop_named_before_action, s)
    s = RANK_SURNAME.sub(lambda m: m.group(0) if _company_or_place(m.group(2)) else m.group(1) + "[name removed]", s)
    s = AGENCY_DASH_SURNAME.sub(r"\1[name removed]", s)
    s = scrub_text(s)
    s = SPACE.sub(" ", s).strip()
    return s or None


def relationship_code(v) -> str | None:
    """REPORTER_REALTIONSHIP -> operator | owner | citizen | other (the free text itself is never kept)."""
    t = str(v or "").strip()
    if not t:
        return None
    u = t.upper()
    if u.startswith("OPERATOR"):
        return "operator"
    if u.startswith("OWNER"):
        return "owner"
    if re.search(r"citizen|resident|home\s*owner|neighbo|concerned|member of (?:the )?public|tenant|renter|passer", t, re.I):
        return "citizen"
    return "other"


def scrub_name_field(v):
    """INCIDENT_NAME or FACILITY_NAME with personal data removed. Filers often type their own name, or a resident's,
    as the incident or facility name (a staff member's name as the incident name; a homeowner's name as the facility
    of a complaint): a value that is only a person's name (build.redact.person_shaped, read in any case) becomes
    "[name removed]"; names inside a longer value go as in the notice text (common given name + surname, Mr./Ms.),
    and e-mails and phone numbers as everywhere."""
    if not isinstance(v, str):
        return v
    s = SPACE.sub(" ", scrub_text(v)).strip()
    if not s:
        return s
    words = {w.lower() for w in re.split(r"[\s\-/.,()]+", s) if w}
    if not words & (NOT_PERSON_WORDS | PLACE_AFTER) and \
            (redact.person_shaped(s) or redact.person_shaped(string.capwords(s))):
        return "[name removed]"
    if s.islower() or s.isupper():          # "jordan sample", "JORDAN SAMPLE": read with capitals
        c = drop_given_pairs(HONORIFIC_NAME.sub("[name removed]", string.capwords(s)))
        if "[name removed]" in c:
            return c
    s = HONORIFIC_NAME.sub("[name removed]", s)
    return drop_given_pairs(s)


CITIZEN_COORD_DIGITS = 3      # about 100 m: a complaint's point is often the filer's home
CITIZEN_PRECISION_M = 100


def safe_attributes(a: dict) -> dict:
    """The attributes this module keeps: the safe fields only, the relationship as a code, the text scrubbed, the
    incident and facility names cleared of people's names, the house number of an address the text ties to a residence
    or a resident (common.residence_numbers) cut from the names and the address line too, and, for a notice filed by a
    member of the public, no street address, no house number anywhere and the point rounded to about 100 m: the facility
    of a complaint is often the filer's or a neighbour's home."""
    out = {k: a.get(k) for k in SAFE_FIELDS if k in a}
    # a saved page already holds the code (the relationship itself is never saved)
    out["_filer"] = relationship_code(a.get(RELATIONSHIP_FIELD)) if RELATIONSHIP_FIELD in a else a.get("_filer")
    homes = residence_numbers(out["INCIDENT_REPORT"]) if isinstance(out.get("INCIDENT_REPORT"), str) else []
    for k in ("INCIDENT_REPORT", "INCIDENT_NAME", "FACILITY_NAME"):
        if isinstance(out.get(k), str):
            out[k] = scrub(out[k]) if k == "INCIDENT_REPORT" else scrub_name_field(out[k])
            if out[k] and homes:
                out[k] = drop_house_numbers(out[k], homes)
    for k in ("FACILITY_ADDRESS_LINE_1", "FACILITY_ADDRESS_LINE_2"):
        if isinstance(out.get(k), str) and homes:
            out[k] = drop_house_numbers(out[k], homes)
    if out["_filer"] == "citizen":
        for k in ("FACILITY_ADDRESS_LINE_1", "FACILITY_ADDRESS_LINE_2"):
            if out.get(k):
                out[k] = "[address removed]"
        for k in ("INCIDENT_REPORT", "INCIDENT_NAME", "FACILITY_NAME"):
            if isinstance(out.get(k), str):
                out[k] = strip_house_numbers(out[k])
        lat0 = fnum(out.get("LATITUDE"))
        if lat0 is not None:
            # the precision of the rounded point: about 100 m, or the source's own when coarser; carried, because a
            # rounded value that ends in zero ("27.45") would read as 1 km (a rebuild reads the carried value)
            given = a.get("_coord_precision_m")
            out["_coord_precision_m"] = given if isinstance(given, int) else max(CITIZEN_PRECISION_M, precision_m(lat0))
        for k in ("LATITUDE", "LONGITUDE"):
            v = fnum(out.get(k))
            if v is not None:
                out[k] = round(v, CITIZEN_COORD_DIGITS)
    return out


# ---------------------------------------------------------------- classification

TEMPLATE_TYPE = re.compile(r"Wastewater\s+Type:\s*(.*?)\s+(?:Cause:|Spill\s+Volume:)", re.I | re.S)
TEMPLATE_FIELD = {
    "description": re.compile(r"Incident\s+Description:\s*(.*?)\s*(?=Wastewater\s+Type:|$)", re.I | re.S),
    "cause": re.compile(r"\bCause:\s*(.*?)\s*(?=Spill\s+Volume:|$)", re.I | re.S),
    "spill_volume": re.compile(r"Spill\s+Volume:\s*(.*?)\s*(?=Volume\s+Recovered:|$)", re.I | re.S),
    "volume_recovered": re.compile(r"Volume\s+Recovered:\s*(.*?)\s*(?=Waterbodies\s+Impacted:|$)", re.I | re.S),
    "waterbodies_impacted": re.compile(r"Waterbodies\s+Impacted:\s*([YN])\b", re.I),
    "cleanup_status": re.compile(r"Clean-?up\s+Status:\s*(.*?)\s*(?=Clean-?up\s+Actions:|$)", re.I | re.S),
    "cleanup_actions": re.compile(r"Clean-?up\s+Actions:\s*(.*?)\s*(?=(?:Other\s+)?Agencies\s+Notified:|$)", re.I | re.S),
}
STRONG_SEWAGE = re.compile(
    r"\b(raw\s+sewage|untreated|sanitary\s+sewer|sanitary\s+system|sewage|sewer|ssos?|manholes?|lift\s*-?\s*stations?|"
    r"liftstations?|pump\s+stations?|force\s*-?\s*mains?|forcemains?|f/m|gravity\s+(?:mains?|lines?|sewers?)|wet\s*-?\s*wells?|"
    r"grinder\s+pumps?|septic|clean-?outs?|domestic\s+wastewater|raw\s+wastewater|influent|headworks|"
    r"collection\s+system|i\s*&\s*i)\b", re.I)
WASTEWATER = re.compile(r"\b(waste\s*water|wwtp|wwtf|wrf|awt|wrrf|water\s+reclamation\s+facility)\b", re.I)
PARTIAL = re.compile(r"\bpartially[\s-]+treated\b", re.I)
TREATED = re.compile(r"\b(treated\s+effluent|chlorinated\s+effluent|effluent|reclaimed|reclaim\s+water|reuse|"
                     r"re-use|irrigation\s+quality|diluted\s+effluent)\b", re.I)
# shorthand filers use for sewer assets (case-sensitive: "LS #104", "FM was hit", "ARV failure")
SEWER_SHORTHAND = re.compile(r"(?-i:\bL\.?S\.?\s*-?\s*#\s*\d+|\bLS\s*-?\s*\d+\b|\bL/S\b|\bFM\b|\bARVs?\b)|"
                             r"\bair\s+re(?:lease|lief)\s+valves?\b|\bgravity\b", re.I)
# "storm sewer" is a stormwater pipe, not a sanitary sewer: fuel or paint in a storm sewer is not a sewage notice
STORM_SEWER = re.compile(r"\bstorm\s*-?\s*(?:water\s+)?sewers?(?:\s+(?:system|inlets?|lines?|pipes?))?\b", re.I)
# words that say the release itself was sewage (a sewer asset word alone does not: diesel at a lift station's generator)
SEWAGE_RELEASED = re.compile(r"\b(sewage|sewer\s+(?:spill|overflow|water|release)|waste\s*water|sanitary|raw|untreated|"
                             r"ssos?|overflow(?:s|ed|ing)?|influent|septic|black\s*water)\b", re.I)
# a description that reports untreated sewage although the form's Wastewater Type says Treated, Reuse or Biosolids
DESCRIBES_UNTREATED = re.compile(r"\b(?<!partially\s)untreated\b|\braw\s+(?:sewage|wastewater)\b|"
                                 r"\bsanitary\s+sewer\s+overflow|\bSSOs?\b|\bsewage\s+(?:spill|overflow|release)", re.I)
# what else is released at pumps, lift stations and plants (a generator's diesel, a cooling tower's water)
OTHER_RELEASE = re.compile(
    r"\b(diesel|gasoline|petroleum|fuel|hydraulic\s+(?:fluid|oil)|(?:motor|mineral|transformer|engine)\s+oil|"
    r"oil(?!\s+and\s+grease)\s+(?:sheen|spill|leak)|leachate|cooling\s+(?:water|tower)|industrial\s+(?:waste\s*)?water|"
    r"process\s+water|antifreeze|coolant|chlorine\s+(?:gas|leak|release|spill)|sulfuric|acid|ammonia\s+(?:leak|release))\b",
    re.I)                                   # not chlorine or potable water alone: crews disinfect and wash down with them
NOT_SEWAGE_STRONG = re.compile(
    r"\b(industrial\s+wastewater|process\s+water|cooling\s+water|phosphogypsum|gypstack|leachate|mining|"
    r"oil|fuel|diesel|gasoline|petroleum|hydraulic|transformer|chemical|ammonia|hypochlorite|acid|paint|"
    r"potable\s+water|drinking\s+water|antifreeze|coolant|pesticide|fertilizer)\b", re.I)


def template_fields(text: str) -> dict:
    out = {}
    for k, rx in TEMPLATE_FIELD.items():
        m = rx.search(text or "")
        if m:
            v = SPACE.sub(" ", m.group(1)).strip()
            out[k] = v or None
    return out


def classify(text: str | None, facility: str | None, filer: str | None) -> tuple[str, str, str]:
    """(kind, event_type, rule): kind is untreated, partially_treated, wastewater_unspecified, citizen_complaint
    (records) or treated, reuse, biosolids, other_pollution (not written)."""
    t = text or ""
    words = f"{facility or ''} {t}"
    m = TEMPLATE_TYPE.search(t)
    if m:
        wt = SPACE.sub(" ", m.group(1)).strip().lower()
        cause = (template_fields(t).get("cause") or "").lower()
        if wt.startswith("partially"):
            kind, et = "partially_treated", "plant_bypass"
        elif "untreated" in wt or wt.startswith("raw"):
            kind, et = "untreated", "bypass" if cause.startswith("bypass") else "sso"
        elif wt.startswith("treated"):
            kind, et = "treated", None
        elif wt.startswith("reuse") or "reclaim" in wt:
            kind, et = "reuse", None
        elif wt.startswith("biosolid"):
            kind, et = "biosolids", None
        else:
            kind, et = "wastewater_unspecified", "sso"
        rule = f"template: Wastewater Type {m.group(1).strip()!r}"
        desc = template_fields(t).get("description") or ""
        if et is None and PARTIAL.search(desc):
            kind, et = "partially_treated", "plant_bypass"
            rule += "; the description reports partially treated wastewater"
        elif et is None and DESCRIBES_UNTREATED.search(desc):
            # the filer picked Treated (or Reuse, Biosolids) but the description reports untreated sewage: the
            # cautious reading wins
            kind, et = "untreated", "bypass" if cause.startswith("bypass") else "sso"
            rule += "; the description reports untreated wastewater"
    else:
        t_sewer = STORM_SEWER.sub(" ", t)
        strong = (STRONG_SEWAGE.search(t_sewer) or SEWER_SHORTHAND.search(t_sewer) or
                  STRONG_SEWAGE.search(STORM_SEWER.sub(" ", facility or "")))
        if PARTIAL.search(t):
            kind, et, rule = "partially_treated", "plant_bypass", "text: partially treated"
        elif strong and OTHER_RELEASE.search(t) and not SEWAGE_RELEASED.search(t_sewer):
            kind, et, rule = "other_pollution", None, \
                f"text: {OTHER_RELEASE.search(t).group(0).lower()!r} released at a sewer asset, no sewage released"
        elif strong and not (TREATED.search(t) and not re.search(r"raw|untreated|sewage|sanitary|sso", t, re.I)
                             and not re.search(r"manhole|lift\s*station|gravity", t, re.I)):
            if re.search(r"industrial\s+wastewater|process\s+water", t, re.I) and not re.search(r"sewage|sanitary|raw", t, re.I):
                kind, et, rule = "other_pollution", None, "text: industrial wastewater"
            else:
                kind, et, rule = "untreated", "sso", f"text: {strong.group(0).lower()!r}"
        elif TREATED.search(t):
            kind, et, rule = ("treated" if re.search(r"effluent", t, re.I) else "reuse"), None, \
                f"text: {TREATED.search(t).group(0).lower()!r}"
        elif WASTEWATER.search(words) and not NOT_SEWAGE_STRONG.search(t):
            kind, et, rule = "wastewater_unspecified", "sso", f"text: {WASTEWATER.search(words).group(0).lower()!r}"
        else:
            kind, et, rule = "other_pollution", None, "text: no sewage words"
    if et and filer == "citizen":
        return "citizen_complaint", "unknown", rule + "; filed by a member of the public"
    return kind, et, rule


# ---------------------------------------------------------------- fields

def wall_clock(ms) -> datetime | None:
    """An epoch-ms value holding Florida wall-clock time stored as UTC -> aware America/New_York."""
    if ms in (None, ""):
        return None
    try:
        t = datetime.fromtimestamp(float(ms) / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return t.replace(tzinfo=None).replace(tzinfo=TZ)


def local_date(ms) -> datetime | None:
    t = wall_clock(ms)
    return t.replace(hour=0, minute=0, second=0, microsecond=0) if t else None


def iso(t: datetime | None) -> str | None:
    return t.isoformat() if t else None


def fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def precision_m(v) -> int | None:
    if v is None:
        return None
    s = repr(float(v))
    dec = len(s.split(".")[1].rstrip("0")) if "." in s else 0
    return {0: 100_000, 1: 10_000, 2: 1_000, 3: 100}.get(dec, 15)


SWO_NUMBER = re.compile(r"^20(?:1[7-9]|2\d|3\d)\d{4,5}$")


def incident_number(v) -> str | None:
    f = fnum(v)
    if f is None:
        return None
    return str(int(f)) if f == int(f) else str(f)


def record_key(a: dict) -> str:
    t = wall_clock(a.get("DATE_TIME_OF_REPORT"))
    return f"{incident_number(a.get('INCIDENT_NUMBER')) or 'none'}-{t.strftime('%Y%m%dT%H%M%S') if t else 'notime'}"


VOL_LABELS = re.compile(r"(?i)(?:sewage\s+released\s+in\s+gallons|gallons\s+released|final\s+spill\s+volume|"
                        r"initial\s+spill\s+volume)\s*:\s*([^:]{0,40}?)(?=\s+[A-Z][A-Za-z /#]+:|$)")
VOL_PHRASE = re.compile(r"(?i)(?:approximately|approx\.?|estimated|an?\s+estimated|about|roughly|total\s+of)?\s*"
                        r"(\d[\d,]*(?:\.\d+)?)\s*(?:-?\s*)(gallons?|gals?\b|mg\b|million\s+gallons)")


def volume(text: str, tf: dict) -> tuple[int | None, str | None, str, str | None]:
    """(gallons, volume_text, estimate_flag, basis)."""
    v = tf.get("spill_volume")
    if v:
        txt = v if re.search(r"[a-z]", v, re.I) else f"{v} gallons"
        gal, flag = parse_volume_gal(txt)
        return gal, txt, "estimated" if gal is not None else flag, "the notice form's Spill Volume (gallons)"
    m = VOL_LABELS.search(text or "")
    if m and re.search(r"\d", m.group(1)):
        txt = m.group(1).strip()
        txt = txt if re.search(r"[a-z]", txt, re.I) else f"{txt} gallons"
        gal, flag = parse_volume_gal(txt)
        return gal, txt, "estimated" if gal is not None else flag, "a labelled volume in the notice text"
    for m in VOL_PHRASE.finditer(text or ""):
        around = (text[max(0, m.start() - 30):m.start()] + " " + text[m.end():m.end() + 30]).lower()
        if "recover" in around or "washdown" in around or "per minute" in around or "gpm" in around:
            continue
        txt = SPACE.sub(" ", m.group(0)).strip()
        gal, flag = parse_volume_gal(txt)
        return gal, txt, "estimated" if gal is not None else flag, "the first volume in gallons in the notice text"
    return None, None, "unknown", None


WATER_KINDS = (r"Creek|River|Bay|Bayou|Canal|Lake|Lagoon|Waterway|Sound|Harbor|Harbour|Inlet|Branch|Slough|Run|"
               r"Springs?|Estuary|Gulf\s+of\s+(?:Mexico|America)|Atlantic\s+Ocean|Ocean|Basin|Marsh|Cove|Pass")
# a water's name as the notices write it ("Pottsburg Creek", "the St. Johns River", "C-51 Canal", "ICW")
NAME_PART = (rf"(?:(?:[A-Z][\w'.-]*|[A-Z]-?\d+|St\.?|of|the)\s+){{0,4}}(?:{WATER_KINDS})\b(?:\s+[A-Z]-?\d+[A-Z]?)?"
             rf"|(?:Lake|Canal)\s+[A-Z][\w'-]+|(?:Intracoastal(?:\s+Waterway)?|ICW)\b|C-\d+[A-Z]?\s+Canal|Canal\s+C-\d+[A-Z]?")
# the same for the text-against-the-flag rule (text_reached), which also reads "Lake <Name>" and "Canal <Name>" (tried
# first, else "Lake" alone, a kind, ends the match and the name is lost; not when the words after them end in a kind,
# "Lake Worth Lagoon", or make a place, "Lake County", "Lake Shore Dr") and the Intracoastal however it is spelt
# ("intercoastal waterway"). water_names keeps NAME_PART: changing it would move the water of records the rule does
# not touch.
REACH_NAME_PART = (rf"(?:Lake|Canal)\s+(?!(?:County|City|Town|Village|Park|Estates|Shores?|Heights|Point|Road|Rd|Street|"
                   rf"St|Avenue|Ave|Drive|Dr|Boulevard|Blvd)\b)[A-Z][\w'-]+"
                   rf"(?!\s+(?:[A-Z][\w'.-]*\s+){{0,3}}(?:{WATER_KINDS})\b)"
                   rf"|(?i:in(?:tra|ter)coastal(?:\s+waterway)?)\b|{NAME_PART}")
WATER_NAME = re.compile(
    rf"(?i:\b(?:into|to|reached|entered|entering|impacted|impacting|affected|affecting|toward|towards|in|of)\s+(?:the\s+)?)"
    rf"({NAME_PART})")
NOT_WATER_AFTER = re.compile(r"^\s*(?:Beach|Rd|Road|Dr|Drive|Blvd|Boulevard|Ave|Avenue|St|Street|Ln|Lane|Way|Ct|Court|Cir|Circle|Pkwy|"
                             r"Parkway|Hwy|Highway|Trl|Trail|Pl|Place|Ter|Terrace|Estates|Apartments|Subdivision|"
                             r"Elementary|School|Park|WRF|WWTP|WWTF|AWT|Plant|Utilities|Utility|Lift|Pump|HOA|Village|"
                             r"Golf|Club|Mall|Plaza|Center|Condos?|Community|Regional|Water\s+Reclamation)\b")
NOT_WATER_NAME = re.compile(r"(?i)^(?:the\s+)?(?:storm|retention|detention|drainage|a|an|nearby|adjacent|on-?site)\b|"
                            r"\b(?:retention|detention|stormwater|storm)\b")


def _water_name_at(m: re.Match, text: str, group=1) -> str | None:
    """The water name a WATER_NAME (or REACHED_SHAPE) match holds, or None when it is a place, a road or a kind."""
    name = SPACE.sub(" ", m.group(group)).strip(" .,;:")
    tail = text[m.end():m.end() + 25]
    if NOT_WATER_AFTER.match(tail) or NOT_WATER_NAME.search(name) or \
            re.match(r"(?i)(?:the\s+)?(?:city|town|village|county)\s+of\b", name):
        return None                           # "City of Crystal River": a place, not a water
    name = re.sub(r"^(?:the|of)\s+", "", name, flags=re.I)
    if len(name.split()) == 1 and re.fullmatch(rf"(?:{WATER_KINDS})", name, re.I):
        return None                           # "the bayou", "the harbor": a kind of water, not a name
    if not re.match(r"[A-Z]|ICW|(?i:in(?:tra|ter)coastal)", name):
        return None
    return name


def water_names(text: str) -> list[str]:
    out = []
    for m in WATER_NAME.finditer(text or ""):
        name = _water_name_at(m, text)
        if name and name not in out:
            out.append(name)
    return out


# ---------------------------------------------------------------- the text against the form's flag
# The owner's decision of 2026-11-04 (afternoon, item 2): a notice whose form says "Waterbodies Impacted: N" while its
# text says the sewage entered, may have entered, reached, discharged to or flowed into a named water is placed on that
# water under the site's caution, and the record says the form's flag said otherwise (err on the side of safety).
# raw.reached_water is then "text" (the form's value stays in raw._form_waterbodies_impacted) and
# raw._reached_water_basis says why; build/status.py reads "text" as a placement on the named water that colours only
# the site's caution, never red (no authority window applies to it).
TEXT_REACHED_BASIS = "the notice's text names the water; the form's flag said no water was reached"
# the shapes: "entered (into) X", "entering X", "may have entered X", "possibly reached X", "reached X", "impacted X",
# "discharged to/into X", "flowed to/into X" and any "into X" ("the storm drain discharges into X Creek"); a present
# "enter" or "reach" counts only after may, might or could ("may enter X Creek"), never alone ("to enter")
REACHED_SHAPE = re.compile(
    r"(?i:\b(?P<verb>(?:(?:may|might|could)\s+(?:have\s+)?(?:possibly\s+)?|possibly\s+|potentially\s+|likely\s+|"
    r"probably\s+)"
    r"(?:entered|enter|reached|reach|impacted|impact|gone\s+into|went\s+into|flowed\s+(?:in)?to|flow\s+(?:in)?to|"
    r"discharged\s+(?:in)?to|discharge\s+(?:in)?to)"
    r"|(?:entered|enters|entering|reached|reaches|reaching|impacted|impacting)(?:\s+into)?"
    r"|discharg(?:ed|es|ing)\s+(?:in)?to|flow(?:ed|s|ing)\s+(?:in)?to|into)"
    r"\s+(?:the\s+)?(?:nearby\s+|adjacent\s+|neighboring\s+|neighbouring\s+)?)"
    rf"(?P<name>{REACH_NAME_PART})")
# a statement that the sewage did not reach the water: a negation in the same part of the sentence before the verb
# ("did not flow into", "no discharge to", "none entered", "prevented it from entering", "contained before reaching");
# an unsure one ("not known if", "not sure whether") is no negation: "may have" is the reason for the rule
REACH_NEGATION = re.compile(
    r"(?i)\b(?:no|not|never|none|nothing|neither|nor|prevent\w*|averted|contained|stopped|kept|blocked|without)\b|n't\b")
NOT_A_NEGATION = re.compile(r"(?i)\bnot\s+(?:sure|known|certain|clear|determined|confirmed|yet\s+known)\b|"
                            r"\bno\s+(?:longer)\b|\bnot\s+only\b")
NEGATION_RIGHT_BEFORE = re.compile(r"(?i)\b(?:before|from|prior\s+to)\s+(?:it\s+|they\s+|any\s+)?(?:could\s+|can\s+)?$")
# where the part of a sentence that a negation governs begins: a full stop (not "St." or "Mt."), a semicolon, a line
# break, a comma, a colon (after a label of DEP's form), "and", "but", "however", "although", "while"
CLAUSE_START = re.compile(r"(?<![A-Z][a-z])(?<!\b[A-Z])\.\s|[;:\n,]|"
                          r"(?i:\b(?:and|but|however|although|though|while|then)\b)")


def _negated(text: str, start: int) -> bool:
    """Whether the verb at start is negated within its part of the sentence."""
    before = text[max(0, start - 200):start]
    cuts = list(CLAUSE_START.finditer(before))
    part = before[cuts[-1].end():] if cuts else before
    if NEGATION_RIGHT_BEFORE.search(part):
        return True
    part = NOT_A_NEGATION.sub(" ", part)
    return bool(REACH_NEGATION.search(part))


# after the name: a ditch or drain named after the water ("entered Example Lake drainage ditch") is not the water, and
# a discharge "via our treatment system" is a plant's own permitted outflow, not the spill
NOT_REACHED_AFTER = re.compile(r"(?i)^\s*(?:drainage|ditch(?:es)?|culverts?|swales?|storm\s*(?:drains?|water|sewers?))\b|"
                               r"^\s*(?:via|through)\s+(?:our|out|the|its|their)\s+(?:\w+\s+)?treatment\b")


def text_reached(text: str) -> tuple[str, str] | None:
    """(water name, the words that say so) when the notice's text says the sewage entered, may have entered, reached,
    discharged to or flowed into a named water, not negated; else None. The first such water is returned."""
    for m in REACHED_SHAPE.finditer(text or ""):
        name = _water_name_at(m, text, "name")
        if not name or _negated(text, m.start()) or NOT_REACHED_AFTER.match(text[m.end():m.end() + 40]):
            continue
        if re.fullmatch(r"(?i)in(?:tra|ter)coastal(?:\s+waterway)?", name):
            name = "Intracoastal Waterway"            # "intercoastal waterway", as filers often spell it
        return name, SPACE.sub(" ", m.group(0)).strip(" .,;:")
    return None


NPDES_RE = re.compile(r"\bFL\s?0\d{6}\b")
STATE_PERMIT_RE = re.compile(r"\bFLA\s?-?\s?\d{6}\b")
# operator ids (data/dischargers.json) by words in the facility name or text; checked in this order
OPERATORS = [
    ("fl-miami-dade-wasd", re.compile(r"miami[- ]dade\s+water|\bWASD\b|miami-dade\s+county\s+water", re.I)),
    ("fl-jea", re.compile(r"\bJEA\b|buckman\s+wrf|arlington\s+east\s+wrf|blacksford|district\s+ii\s+wrf|"
                          r"southwest\s+wrf.*jacksonville", re.I)),
    ("fl-fort-lauderdale", re.compile(r"city\s+of\s+fort\s+lauderdale|fort\s+lauderdale\s+(?:public\s+works|utilities)|"
                                      r"G\.?\s*T\.?\s*Lohmeyer", re.I)),
    ("fl-tampa", re.compile(r"city\s+of\s+tampa|tampa\s+wastewater|howard\s+f\.?\s+curren", re.I)),
    ("fl-st-petersburg", re.compile(r"st\.?\s+petersburg|southwest\s+water\s+reclamation\s+facility.*st|"
                                    r"(?:northeast|northwest|southwest)\s+wrf\s+.*petersburg", re.I)),
    ("fl-panama-city-millville", re.compile(r"millville|city\s+of\s+panama\s+city|st\.?\s+andrews\s+wwtf", re.I)),
    ("fl-defuniak-springs", re.compile(r"defuniak", re.I)),
    ("fl-fort-walton-beach", re.compile(r"fort\s+walton\s+beach", re.I)),
    ("fl-port-st-lucie", re.compile(r"port\s+st\.?\s+lucie|westport\s+ww|glades\s+wwtp", re.I)),
    ("fl-fort-pierce-ua", re.compile(r"fort\s+pierce\s+utilities|\bFPUA\b", re.I)),
    ("fl-orlando-iron-bridge", re.compile(r"iron\s+bridge|city\s+of\s+orlando", re.I)),
]


def load_permit_index(data_dir: Path = DATA_DIR) -> dict[str, tuple[str, str]]:
    """NPDES permit -> (operator id, name) for Florida rows of data/dischargers.json."""
    out = {}
    for d in read_json(data_dir / "dischargers.json", []) or []:
        if d.get("state") != "FL":
            continue
        for p in [d.get("npdes_permit")] + list(d.get("npdes_permits") or []):
            if p:
                out.setdefault(str(p).upper(), (d["id"], d.get("name")))
    return out


def operator_of(facility: str, text: str, permit: str | None, permits: dict) -> tuple[str | None, str]:
    if permit and permit in permits:
        return permits[permit][0], f"permit {permit}"
    for did, rx in OPERATORS:
        if rx.search(facility or ""):
            return did, "facility name"
    for did, rx in OPERATORS:
        if rx.search((text or "")[:400]):
            return did, "notice text"
    return None, "no operator matched"


def in_fl(lon, lat) -> bool:
    return FL_BOX[0] <= lon <= FL_BOX[2] and FL_BOX[1] <= lat <= FL_BOX[3]


# ---------------------------------------------------------------- records

def build_record(a: dict, key: str, fetched_at: str, prev: dict | None, permits: dict) -> dict | None:
    """One record, or None when the notice is not a sewage notice (counted by the caller)."""
    text = a.get("INCIDENT_REPORT") or ""
    facility = SPACE.sub(" ", str(a.get("FACILITY_NAME") or "")).strip() or None
    kind, et, rule = classify(text, facility, a.get("_filer"))
    if et is None:
        return None
    base = dict(source_id=SOURCE_ID, source_record_id=key, fetched_at=fetched_at,
                source_url=pnp_url(a))
    raw = {k: v for k, v in a.items() if k not in ("OBJECTID",)}
    raw["_layer_objectid"] = a.get("OBJECTID")        # renumbered when the layer is rebuilt: not an id
    try:
        return _record(a, base, raw, text, facility, kind, et, rule, prev, permits)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="unknown", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{type(e).__name__}: {e}")


def pnp_url(a: dict) -> str:
    """The layer query that returns this notice (safe fields only)."""
    n = incident_number(a.get("INCIDENT_NUMBER"))
    ms = fnum(a.get("DATE_TIME_OF_REPORT"))
    if n:
        where = f"INCIDENT_NUMBER%3D{n}"
    elif ms is not None:
        stamp = datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S").replace(" ", "%20")
        where = f"DATE_TIME_OF_REPORT%3Dtimestamp%20%27{stamp}%27"
    else:
        where = "1%3D0"
    return f"{LAYER_ALL}/query?where={where}&outFields={','.join(SAFE_FIELDS)}&returnGeometry=false&f=json"


def _record(a, base, raw, text, facility, kind, et, rule, prev, permits):
    problems = []
    tf = template_fields(text)
    raw["_pnp_kind"] = kind
    raw["_pnp_rule"] = rule
    if tf:
        raw["_template"] = tf
    raw["_time_basis"] = TIME_BASIS
    reported = wall_clock(a.get("DATE_TIME_OF_REPORT"))
    start, end = local_date(a.get("RELEASE_START_DATE_TIME")), local_date(a.get("RELEASE_END_DATE_TIME"))
    raw["_decoded_times"] = {"reported": iso(reported), "release_start_date": start.date().isoformat() if start else None,
                             "release_end_date": end.date().isoformat() if end else None}
    ongoing = str(a.get("RELEASE_ONGOING") or "").strip().upper()
    if et == "unknown":
        status, ended_at = "unknown", None
        if end:
            raw["_release_end_date"] = end.date().isoformat()
    elif ongoing == "Y":
        status, ended_at = "ongoing", None
        if end:
            raw["_end_while_ongoing"] = end.date().isoformat()
    elif end:
        status, ended_at = "ended", iso(end)
    else:
        status, ended_at = "ended", None
        raw["_end_note"] = "the notice says the release is not ongoing but gives no end date"
    if start and end and end < start:
        problems.append("release end date before the start date: ended_at left empty")
        ended_at = None
        if status == "ended":
            status = "unknown"

    lat, lon = fnum(a.get("LATITUDE")), fnum(a.get("LONGITUDE"))
    if lat is not None and lon is not None and not in_fl(lon, lat):
        raw["_coords_rejected"] = {"lat": lat, "lon": lon, "why": "not in Florida"}
        lat = lon = None
    elif lat is None or lon is None:
        lat = lon = None
    elif a.get("_filer") == "citizen":
        raw["_coords_note"] = (f"filed by a member of the public: the point is rounded to {CITIZEN_COORD_DIGITS} decimals "
                               "(about 100 m), since it is often the filer's home")

    wi = (tf.get("waterbodies_impacted") or "").upper()
    if not wi:
        m = re.search(r"(?i)\b(?:waterbod(?:y|ies)|water\s+bod(?:y|ies))\s+(?:impacted|affected)\s*[:?]\s*(yes|no|y|n)\b", text)
        wi = m.group(1)[0].upper() if m else ""
    if wi == "Y":
        raw["reached_water"] = True
    elif wi == "N":
        raw["reached_water"] = False
    names = water_names(tf.get("description") or text)
    water = names[0] if names else None
    said = text_reached(text) if wi == "N" else None
    if said:
        # the text wins over the form's N (owner, 2026-11-04): placed on the water the text names, site caution only
        water, words = said
        raw["_form_waterbodies_impacted"] = "N"
        raw["reached_water"] = "text"
        raw["_reached_water_basis"] = TEXT_REACHED_BASIS
        raw["_reached_water_words"] = words
        names = [water] + [n for n in names if n != water]
    if names:
        raw["_water_names"] = names
    raw["_water"] = {"why_none": (f"named in the notice text ({water!r}); no Florida water record yet" if water else
                                  "the notice names no receiving water (it gives only Waterbodies Impacted Y/N)")}

    gal, vtext, flag, vbasis = volume(text if not tf.get("description") else text, tf)
    if vbasis:
        raw["_volume_basis"] = vbasis

    hay = f"{facility or ''} {text}"
    pm = NPDES_RE.search(hay)
    permit = pm.group(0).replace(" ", "").upper() if pm else None
    sm = STATE_PERMIT_RE.search(hay)
    if sm:
        raw["_state_permit"] = re.sub(r"[\s-]", "", sm.group(0)).upper()
    did, dbasis = operator_of(facility or "", text, permit, permits)
    raw["_operator_match"] = dbasis

    p_raw = (prev or {}).get("raw") or {}
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or base["fetched_at"]

    material = {"untreated": "untreated wastewater", "partially_treated": "partially treated wastewater",
                "wastewater_unspecified": "wastewater (type not stated)",
                "citizen_complaint": "reported sewage (citizen report)"}.get(kind)
    if kind == "wastewater_unspecified":
        raw["_kind_note"] = "the notice does not say whether the wastewater was treated; it is shown as sewage"
    loc = SPACE.sub(" ", str(a.get("INCIDENT_NAME") or "")).strip() or None
    return event(
        **base, event_type=et, status=status,
        discharger_id=did, discharger_name=facility, npdes_permit=permit,
        outfall_id=None, outfall_name=loc,
        waterbody_text=water, water_slugs=[], water_match="none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        coord_precision_m=(a.get("_coord_precision_m") or precision_m(lat)) if lat is not None else None,
        started_at=iso(start), ended_at=ended_at, time_precision="day" if start else None,
        reported_at=iso(reported), published_at=None, source_updated_at=None,
        material=material, volume_gal=gal, volume_text=vtext, estimate_flag=flag if gal is not None or vtext else "unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


def keyed(features: list[dict]) -> list[tuple[str, dict]]:
    """(source_record_id, attributes) with "-b", "-c" for a key that repeats within one layer."""
    groups = defaultdict(list)
    for a in features:
        groups[record_key(a)].append(a)
    out = []
    for k, rows in groups.items():
        rows.sort(key=lambda a: (fnum(a.get("LATITUDE")) or 0, fnum(a.get("LONGITUDE")) or 0,
                                 hashlib.sha1(str(a.get("INCIDENT_REPORT") or "").encode()).hexdigest()))
        for i, a in enumerate(rows):
            out.append((k if i == 0 else f"{k}-{chr(ord('a') + i)}", a))
    return out


def link_revisions(records: list[dict]) -> dict:
    """parent_event_id for later notices of one State Watch Office number; duplicate_of for exact copies."""
    by_num = defaultdict(list)
    for r in records:
        if (r.get("raw") or {}).get("_pnp_kind") == "citizen_complaint":
            continue            # a complaint is never a revision of an operator's notice, nor revised by one
        n = (r.get("raw") or {}).get("INCIDENT_NUMBER")
        n = incident_number(n)
        if n and SWO_NUMBER.match(n):
            by_num[n].append(r)
    revised = dup = 0
    for n, rs in by_num.items():
        rs.sort(key=lambda r: (r.get("reported_at") or "", r["event_id"]))
        first = rs[0]
        first["parent_event_id"] = None
        seen = {(first.get("reported_at"), (first.get("raw") or {}).get("INCIDENT_REPORT")): first["event_id"]}
        for r in rs[1:]:
            k = (r.get("reported_at"), (r.get("raw") or {}).get("INCIDENT_REPORT"))
            if k in seen:
                r["duplicate_of"] = seen[k]
                r["parent_event_id"] = None
                dup += 1
                continue
            seen[k] = r["event_id"]
            r["parent_event_id"] = first["event_id"]
            revised += 1
    return {"revisions": revised, "exact_copies": dup}


def rebuilt(r: dict, permits: dict) -> dict:
    """A record kept from an earlier run, rebuilt from its own raw attributes under the current rules, so that a privacy
    rule added since reaches the notices the 30-day layer no longer lists (their text was scrubbed when first read). The
    record stays as it was when its raw holds no notice or the rebuild no longer reads it as the same sewage record."""
    raw = r.get("raw") or {}
    if not isinstance(raw.get("INCIDENT_REPORT"), str) and not isinstance(raw.get("INCIDENT_NAME"), str):
        return r
    a = {k: raw[k] for k in SAFE_FIELDS if k in raw and k != "OBJECTID"}
    a["OBJECTID"], a["_filer"] = raw.get("_layer_objectid"), raw.get("_filer")
    if raw.get("_coord_precision_m") is not None:
        a["_coord_precision_m"] = raw["_coord_precision_m"]
    try:
        new = build_record(safe_attributes(a), r["source_record_id"], r.get("fetched_at"), r, permits)
    except Exception:  # noqa: BLE001 - never drop a record
        return r
    if new is None or new.get("event_id") != r.get("event_id"):
        return r
    if raw.get("_missing_from_layer_since"):
        new["raw"]["_missing_from_layer_since"] = raw["_missing_from_layer_since"]
    return new


def build(features: list[dict], fetched_at: str, prev_records: list[dict], permits: dict | None = None,
          full_layer: bool = False) -> tuple[list[dict], dict]:
    permits = load_permit_index() if permits is None else permits
    prev = {r["event_id"]: r for r in prev_records}
    records, seen, excluded, left_out = [], set(), Counter(), {}
    kinds = Counter()
    for key, a in keyed([safe_attributes(f) for f in features]):
        eid = f"{SOURCE_ID}:{key}"
        rec = build_record(a, key, fetched_at, prev.get(eid), permits)
        seen.add(eid)
        if rec is None:
            kind = classify(a.get("INCIDENT_REPORT"), a.get("FACILITY_NAME"), a.get("_filer"))[0]
            excluded[kind] += 1
            left_out[key] = kind
            continue
        kinds[(rec.get("raw") or {}).get("_pnp_kind")] += 1
        records.append(rec)
    kept = 0
    window_from = _days_before(fetched_at, LAYER_CURRENT_DAYS)
    for eid, r in prev.items():
        if eid in seen:
            continue
        if eid.split(":", 1)[1] in left_out:
            continue            # read again and now classified as not a sewage notice
        # only a notice still inside the 30-day layer's window can be missing from it; older ones simply aged out
        r = rebuilt(r, permits)
        if not full_layer and window_from and (r.get("reported_at") or "") >= window_from:
            r.setdefault("raw", {})
            r["raw"]["_missing_from_layer_since"] = r["raw"].get("_missing_from_layer_since") or fetched_at
        records.append(r)
        kept += 1
    links = link_revisions(records)
    records.sort(key=lambda r: (r.get("reported_at") or "", r["event_id"]), reverse=True)
    stats = {"layer_rows": len(features), "records_from_layer": sum(kinds.values()), "kept_from_earlier_runs": kept,
             "by_kind": dict(kinds), "excluded": dict(excluded), **links,
             "by_event_type": dict(Counter(r["event_type"] for r in records)),
             "by_status": dict(Counter(r["status"] for r in records)),
             "reached_water": dict(Counter(str((r.get("raw") or {}).get("reached_water")) for r in records)),
             "with_water_name": sum(1 for r in records if r.get("waterbody_text")),
             "with_volume": sum(1 for r in records if r.get("volume_gal") is not None),
             "with_coordinates": sum(1 for r in records if r.get("lat") is not None),
             "with_operator": sum(1 for r in records if r.get("discharger_id")),
             "_left_out_ids": left_out}
    return records, stats


LAYER_CURRENT_DAYS = 31     # layer 0 holds the last 30 days of notices (one day's margin)
# the public names of the notices this feed reads but does not show as sewage reports (meta.left_out)
LEFT_OUT_LABEL = {"treated": "treated effluent", "reuse": "reclaimed water (reuse)", "biosolids": "biosolids",
                  "other_pollution": "other pollution (fuel, oil, chemicals, stormwater and the like)"}


def _days_before(iso_t: str, days: int) -> str | None:
    try:
        t = datetime.fromisoformat(str(iso_t).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t.astimezone(TZ) - timedelta(days=days)).isoformat()


def left_out_meta(left_out: dict, records: list[dict], backfilled_at: str | None) -> dict:
    """The public counts of what this feed reads and does not show (the scope rule of 2026-11-04: treated effluent, reuse and
    biosolids counted but not shown as sewage reports; complaints listed with no status). left_out: every notice
    ever read and left out, by its source_record_id, so the counts are cumulative and a re-read never doubles them."""
    by = Counter(LEFT_OUT_LABEL.get(k, k) for k in left_out.values())
    complaints = sum(1 for r in records if (r.get("raw") or {}).get("_pnp_kind") == "citizen_complaint")
    scope = ("every notice since July 2017" if backfilled_at else "the notices read so far (the last 30 days at first)")
    return {"left_out": dict(sorted(by.items())),
            "listed_without_status": {"filed by a member of the public": complaints},
            "left_out_note": (f"Counted over {scope}: notices about treated effluent, reclaimed water, biosolids and "
                              "other pollution are counted here but not shown as sewage reports; sewage notices filed "
                              "by members of the public are listed with no status.")}


# ---------------------------------------------------------------- fetch

def query_layer(sess: requests.Session, layer: str) -> list[dict]:
    """Every feature of the layer, the safe fields and the relationship only, paged by OBJECTID."""
    feats, offset = [], 0
    fields = ",".join(SAFE_FIELDS + (RELATIONSHIP_FIELD,))
    while True:
        params = {"where": "1=1", "outFields": fields, "returnGeometry": "false", "orderByFields": "OBJECTID",
                  "resultOffset": offset, "resultRecordCount": 5000, "f": "json"}
        r = sess.get(f"{layer}/query", params=params, timeout=(15, 180))
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        got = [f.get("attributes") or {} for f in d.get("features") or []]
        feats += got
        if not got or (not d.get("exceededTransferLimit") and len(got) < 5000) or offset > 100_000:
            break
        offset += len(got)
    return feats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved query response (ArcGIS JSON, or {pages: [...]}) instead of the layer")
    ap.add_argument("--backfill", action="store_true", help="read layer 1 (every notice since 2017) instead of layer 0")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    layer = LAYER_ALL if args.backfill else LAYER_CURRENT
    try:
        if args.file:
            d = json.loads(Path(args.file).read_text())
            pages = d.get("pages") or [d]
            features = [f.get("attributes", f) or {} for p in pages for f in p.get("features") or []]   # saved pages: plain rows
        else:
            sess = requests.Session()
            sess.headers.update(HEADERS)
            features = query_layer(sess, layer)
            if not features:
                raise RuntimeError("the layer returned no notices")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    # the saved page holds the safe fields and the scrubbed text only (the relationship is a code)
    safe = [safe_attributes(a) for a in features]
    state = read_json(STATE_FILE, {}) or {}
    raw_path = state.get("raw_path")
    if not args.file:
        sha = hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()
        if sha != state.get(f"sha256_{'all' if args.backfill else 'current'}"):
            body = json.dumps({"layer": layer, "fields": list(SAFE_FIELDS), "features": safe}, ensure_ascii=False)
            raw_path = str(save_raw(SOURCE_ID, body, "json").relative_to(ROOT))
            state[f"sha256_{'all' if args.backfill else 'current'}"] = sha
            state["raw_path"] = raw_path
        state["fetched_at"] = fetched_at
        if args.backfill:
            state["backfilled_at"] = fetched_at
        write_json(STATE_FILE, state)
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    records, stats = build(features, fetched_at, prev, full_layer=args.backfill)
    left = {**(state.get("left_out") or {}), **stats.pop("_left_out_ids")}
    ids = {r["source_record_id"] for r in records}
    left = {k: v for k, v in left.items() if k not in ids}
    if not args.file:
        state["left_out"] = left
        write_json(STATE_FILE, state)
    records = redact.redact_events(records)
    meta = {**stats, **left_out_meta(left, records, state.get("backfilled_at")), "layer": layer, "raw_path": raw_path, "time_basis": TIME_BASIS, "credit": CREDIT,
            "backfilled_at": state.get("backfilled_at"), "registry_ids": ["fl-dep-pnp-arcgis"],
            "requested_fields": list(SAFE_FIELDS)}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {stats['layer_rows']} notices read, {stats['records_from_layer']} sewage records "
          f"(excluded {stats['excluded']}), {stats['kept_from_earlier_runs']} kept from earlier runs; "
          f"types {stats['by_event_type']}; status {stats['by_status']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
