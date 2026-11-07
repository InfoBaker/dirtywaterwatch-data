"""EPA ECHO Sewer Overflow and Bypass Event dataset (eRule Phase 2), New England, New York, Washington DC, Georgia,
Washington State, Illinois, Arizona (with the Navajo Nation's reports located in Arizona), South Dakota,
Mississippi, Nebraska, Alaska and New Mexico (with the Navajo Nation's reports located in New Mexico).

Source
  https://echo.epa.gov/files/echodownloads/current_sewer_overflow_and_collection_systems_tables.zip
  (registry: fed-echo-sewer-overflow-bypass-events). ZIP of CSVs, no key, ~1.1 MB: the parent
  table sewer_overflow_bypass_report_events plus child tables (types, receiving_waters, impacts,
  causes, corrective_actions, treatment_codes) and collection_system_permits. Current version of
  each report only (the all-versions ZIP holds the revision history). These are the permittee's
  24-hour / 5-day noncompliance reports to the regulator (40 CFR 122.41(l)(6)-(7), (m)(3); part 127),
  not public notices. Coverage in New England is partial: NH (EPA-issued permits) and RI report
  here, MA barely (MWRA and one other), CT, VT and ME not at all (ME and VT have until 2028); NY
  had no rows in the 2026-10-30 file. Routine permitted wet-weather CSOs are mostly not here.

  2026-11-05: the current-version ZIP of that day (Last-Modified 2026-11-05 12:13 UTC, 302 KB) held only
  sewer_overflow_bypass_columns_metadata.csv and sewer_overflow_public_erd.pdf, none of its eight tables. EPA did not
  move the table: on 2026-11-06 the summary page (https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary)
  still says "This Zipped collection of CSV files represents the Sewer Overflow and Bypass data ... It's comprised of 7
  of the 8 data files ... These data represents the latest version of each 'Report'", the data downloads index still
  links the same ZIP ("Sewer Overflow and Bypass Event Dataset (ZIP) (~516 KB)"), the metadata CSV inside it still
  lists the same eight tables, the echodownloads directory has no other current-version file, and ECHO's web services
  have no sewer overflow endpoint. The all-versions ZIP
  (https://echo.epa.gov/files/echodownloads/all_sewer_overflow_and_collection_systems_tables.zip, summary
  .../sewer-overflow-all-versions-summary, 2026-11-04 extract) still holds every table, so when the current-version
  ZIP fails or holds no events table this module reads the current version of each report from it
  (current_from_all_versions): the all-versions metadata CSV (sewer_overflow_bypass_columns_metadata_all.csv) splits
  the events table into sewer_overflow_bypass_report (report fields: received, start and end dates, data group,
  submission type) and sewer_overflow_bypass_event (event fields), each row flagged current_report_form_flag Y or N.
  The Y event rows joined to their Y report rows by permit, form set and form id reproduce the events table under
  the same column names (the 2026-11-04 extract: 5,688 current events, one per event key, every one with its report;
  5,669 in the 2026-11-03 current-version file). The current table's program_report_npdes_data_group_desc is not in
  the all-versions tables and is left out; its event_transaction_type is the event row's transaction_type. The run
  is ok, with meta.via, meta.url and meta.note saying which file was read; published_at and source_updated_at are
  the all-versions file's own.

Which events are kept (one record per event that reached a water)
  The dataset has no 'reached a water' flag, so the rule is built from its fields, in order:
    1. DROP building backups: structure type BAS 'Basement Backup', impact SBB 'Sewage Backup in
       Building', or an 'Other' structure text naming a basement, bathtub, toilet or home.
    2. DROP when the receiving-water field says there was none ('none', 'n/a', 'No water body',
       'No discharge was sent to the river' ...).
    3. KEEP when a receiving water is named (an unnamed brook or wetland counts as a water).
    4. KEEP when an impact is to a water: AHI aquatic habitat, ALI aquatic life, SBC shellfish bed,
       BEC beach, DWC drinking water; or the 'Other' impact/description text names a river, brook,
       stream, pond, harbor, bay, cove, waterway or storm drain.
    5. KEEP bypass events (the diverted flow leaves the plant through its permitted outfall) and
       CSO events at a CSO outfall or regulator (structure 'CSO Outfall', or 'Other' text naming a
       CSO, regulator or outfall).
    6. DROP the rest: SSOs, and CSO-type overflows from manholes or broken pipes, with no receiving
       water and only land or no-observable impacts.
  Dropped events go to data/build/echo-sewer-overflow-dropped.json with the reason, for review (and with the start,
  end and receipt date as given, which ingest/ga_epd_spills.py reads to give a Georgia dry-land spill its end).

Mapping
  event_type from the types table: CSO -> cso, SSO -> sso, BYP -> bypass (first by sequence; a
  report with several types keeps them in raw.types). Start/end are given without a timezone:
  they are recorded as given, naive ('2025-09-09T20:30:00', time_precision minute, raw.timezone_note),
  presumably local time. Extreme-event reports (G9B) have no per-event times: the report period
  is used (time_precision day). status: ended when an end is given, else unknown (never ongoing:
  the report is filed after the fact). reported_at = program_report_received_date (date only).
  published_at = the extract date (ZIP entry date of the events table); source_updated_at = the
  ZIP's HTTP Last-Modified. Volume in gallons; estimate_flag measured for automated/manual
  measurement, estimated for best professional judgement/modeling. Coordinates are the event's own.
  water_slugs: CSO events via data/outfalls-new-england.json (permit + permitted feature), else the
  receiving-water name against data/waters-new-england.csv in the permit's state (bbox tiebreak).
  source_record_id = permit:form_set_id:event_id_ext (stable across report versions).

Failures
  The current-version ZIP failing or holding no events table falls back to the all-versions ZIP (above). Both
  failing (the research copy then stands in only on a first run with no previous records), or an extract missing
  any expected table, writes ok=False with the error; the previous records stay and the dropped-events file is not
  rewritten.

Washington DC (permit DC0021199, DC Water; research/dc/report.md section 2.3)
  EPA writes DC's permit, so DC Water files its SSO/CSO noncompliance reports here: 140 current rows
  (2023-03 to 2026-09) with coordinates, times and gallons; Maryland and Virginia have none yet.
  - Receiving water is free text ('soapstone', 'Hickory Run', 'Watts Branch Creek', 'Rock Creek ' with
    a trailing space, 'ROCK CREEK', 'Anacostia river'). DC_WATER_ALIASES (from research/dc/waters-dc.json)
    normalises each name to the NHD name of the DC water record, so waterbody_text reads 'Hickey Run'
    for 'Hickory Run'. The text as reported stays in raw.receiving_waters; raw.receiving_water_aliases
    says what was changed. A name that is not in the table is kept as typed.
  - Rows whose point lies outside the District (the Potomac Interceptor collapse of 2026-01-19, in
    Montgomery County, Maryland, reported under DC0021199) get raw.state 'MD' and raw.state_basis
    (a point in Virginia would get MD too and stay unplaced); npdes_permit and discharger stay DC Water's (docs/decisions.md,
    Washington DC item 3: reported in Maryland, operator unchanged). The point is tested against the
    DC GIS boundary (ingest/dc_waters.py), which takes in the Potomac to the Virginia shore. status.py's
    event_state reads a two-letter raw.state before the permit prefix (review 2026-11-03 P1-2), so these rows
    are placed, guarded and counted in Maryland.
  - Revisions are NOT read: this module uses the current-version ZIP only, so a report is seen in its
    latest version (the Interceptor row: no volume on 20 January, 217 gal on 3 February, 242,000,000 gal
    on 16 April; the three 3 February rows 291.70 to 291,667 gal). The all-versions ZIP (revision_history
    in research/dc/events.json) is not downloaded or parsed here; a build that reads it would link the
    versions by parent_event_id.
  - The CSO-typed rows with a feature number (structure 'CSO Outfall') look the outfall up in
    data/outfalls-new-england.json only, which has no DC rows, so they are placed by name or point; DC's outfalls
    are in data/outfalls-mid-atlantic.json (scripts/match_outfalls.py).

Georgia (permits GA...; research/ga/report.md section 2.2; the state is not live until data/rules.json says so)
  Georgia permittees file their 24-hour and 5-day spill reports in EPD's GEOS, and these reach this dataset: 1,232
  current GA rows from 90 permits in the 2026-11-03 extract (887 kept, from 83 permits), with start and end times and receiving waters but no
  volume (the volume field is empty on every GA row). Two Georgia habits are handled here:
  - The receiving-water field often says the spill did not reach a water ('DID NOT ENTER STATE WATERS', 'did not
    reach waters', misspelt variants): NO_WATER_TEXT reads these as "receiving water stated as none" (dropped, like
    'none'). No row of another state used these words in that extract. STATE_NO_WATER["GA"] adds Georgia's other
    wordings for no water ('Dry land', 'N/A dry land', 'Not Appicable', 'Bulding Basement', 'DID NOT DISCHARGE TO
    STATE WATERS'), read for GA permits only. Storm drains, MS4 systems and catch basins stay waters, as everywhere.
  - The point is mostly the permit's own (the plant or the utility's office), not the spill's: in that extract 757 of
    887 kept GA events share a point with four or more other events of the same permit. For the states in
    REPEATED_POINT_STATES a point that REPEATED_POINT_MIN or more kept events of one permit share is not used for
    those events (lat/lon null; raw.reported_point keeps it and raw.point_note says why), unless the event is a
    bypass (a plant bypass happens at the plant). The live states are not in the set.
  The state's own list (ingest/ga_epd_spills.py, run after this module) is the public record where both describe a
  spill: it takes the end from the EPA record and marks that record duplicate_of its own, in this module's file.

Washington State (permits WA...; research/wa/report.md section 2.3; not live until data/rules.json says so)
  Two permittees report here (2026-11-03 extract: 36 current rows): American Water Military Services at Joint Base
  Lewis-McChord (WA0021954, an EPA-issued federal-facility permit, which Ecology's own spill list need not carry) and
  the City of Puyallup (WA0037168). Their SSO reports name no receiving water and give the event's own point (no
  point shared by many reports), so the general rules apply unchanged: an SSO with no receiving water and only land
  impacts is dropped, a bypass that names Puget Sound is kept. Ecology's list (ingest/wa_ecology_spills.py) is the
  state's public record for the permits it carries.

Illinois (permits IL...; research/il/report.md section 2.2; not live until data/rules.json says so)
  Illinois permittees file their overflow and bypass reports through EPA's NeT-SewerOverflow, so this dataset is the
  statewide record (2026-11-03 extract: 1,687 current IL rows from 267 permits since 2024-10-01; 772 kept, 915 dropped,
  most of them SSOs into basements or onto land). It does not hold Chicago's, MWRD's or the suburban general-permit
  CSO reports, which reach the public only through MWRD (ingest/il_mwrd_possible_cso.py, il_mwrd_lake_reversals.py).
  Three Illinois habits are handled here, for IL permits only, so the live states' records are unchanged:
  - Time zone (docs/decisions.md, National expansion item 6: the permit's state zone, labelled): the file's times carry
    no zone and Illinois keeps Central time, which the status build would otherwise read as Eastern. STATE_TZ gives
    the zone; a time is written with its offset (a fall-back hour that happens twice is read as the first) and
    raw.timezone_note says so. A date-only time (an extreme-event report's period) stays a date.
  - Receiving-water texts that name none: 'LAWN', 'We do not expect any overflows', 'None, opposite side of ... Levee',
    and a plant's own lagoon ('City of ... Lagoon', a bypass from the plant to its lagoon) are read as no water
    (STATE_NO_WATER["IL"]).
  - Free text: the description, the 'Other' structure, cause, action and impact texts carry street addresses of
    breaks and manholes ('Force main break at <number> <street> Ct.', 'behind <number> <street> Rd.'). For the states
    in FREE_TEXT_STATES every such field goes through the same scrub as Michigan's list (mi_egle_mienviro.free_text:
    emails, phones, staff names, an owner's or resident's name, every house number). The point stays: it is the
    event's own (no Illinois point is shared by many reports of one permit except at a CSO outfall or a plant).

Arizona (permits AZ..., and the Navajo Nation's NN... where the event's point is in Arizona; research/az/report.md
section 2.2; not live until data/rules.json says so)
  Arizona's AZPDES permittees file their 24-hour and five-day overflow and bypass reports in ADEQ's myDEQ, and they
  reach this dataset (2026-11-04 extract: 288 current AZ rows from 42 permits, 264 SSO and 24 bypass, starts from
  2019-09 to 2026-10-28; received a median 3 days after the start, 90th percentile 10). Pima County (Tucson) files no
  rows, and collection systems with only an Aquifer Protection Permit report to ADEQ under A.A.C. R18-9-C305(F) but
  are not in this table. The rules below are keyed on AZ (and the NN prefix), so the other states' records are
  unchanged:
  - Navajo Nation permits (NN...): EPA Region 9 issues them for the Navajo Nation, which spans Arizona, New Mexico and
    Utah, so the prefix names no state. The state is the one the event's own point lies in (navajo_point_state: west of
    the Arizona-New Mexico line at 109.045 W and south of the Arizona-Utah line at 37 N is Arizona; the Four Corners
    boundaries), written in raw.state with raw.state_basis as for DC's rows in Maryland; a point outside STATES (New
    Mexico, Utah) or no point is skipped as before. 2026-11-04 extract: 56 NN reports, 50 in Arizona (Window Rock,
    Kayenta, Tuba City, Twin Arrows, Chinle), 6 in New Mexico (Shiprock 3, Window Rock's 3; near the line the Census
    outlines decide: navajo_point_place, module docstring New Mexico). Clock (PERMIT_TZ): the
    Navajo Nation keeps daylight saving time, unlike the rest of Arizona, so NN times are read as America/Denver (the
    tz database's backward link Navajo -> America/Denver); the Hopi reservation inside it keeps Arizona time, and its
    permits (AZ...) stay America/Phoenix. An owner question: the decision gives the permit's state's zone.
  - Time zone (docs/decisions.md, National expansion item 6): STATE_TZ gives America/Phoenix (no daylight time, so
    every Arizona time is written -07:00).
  - Receiving water as an ADEQ waterbody identifier: most named receiving waters are WBIDs ('AZ15060202-421'), not
    names. AZ_WBID (data/reference/az-adeq-wbids.json, from ADEQ's stream and lake WBID layers;
    scripts/az_adeq_wbids.py) turns each into ADEQ's name ('Unnamed Trib to Munds Creek'), so waterbody_text carries
    the name; raw.receiving_waters keeps what was filed, raw.receiving_water_aliases what was changed and
    raw.receiving_water_wbids ADEQ's segment (origin, terminus, flow regime). A code ADEQ's layer lacks is kept as
    typed. 'UNK_PERNL' (a receiving-water entry with no name) counts as a water but gives no name (AZ_WATER_ALIASES).
    A Navajo Nation entry that goes on after the name ('Black Creek wash however it was bypassed into lagoon') is cut
    to the name; one that names only the plant's lagoon ('by passed into emergency lagoon.') is no water
    (STATE_NO_WATER["AZ"]).
  - Washes and canals: most Arizona overflows reach streets, retention basins and dry washes, and the report says so
    only in the impact text ('flowed to an unnamed wash', 'Discharged to the Corgett Wash', 'flowed into RID canal').
    az_water_text reads a named wash, arroyo or canal ('Queen Creek Wash', 'RID canal'), one the overflow went to,
    into or through with a determiner ('to an unnamed wash', 'into a Concrete lined canal') and 'went to wash' ending a
    clause, as a water: a report naming a wash names a water (the owner's rule of 2026-11-03 keeps a report that
    reached no water off the water). The verb ('Wash with potable water', 'to wash down the street', 'Crew Will Wash
    Down Area'), places named for washing ('Car Wash', 'Vactor Truck Wash') and a wash the overflow did not reach
    ('over 1/2 mile from the closest dry wash') are not read as one.
  - Texts that name a water only to deny it ('The SSO did not impact any waterway', 'did not reach any body of
    water', 'did not enter the canal') and the plant's own ponds ('effluent storage pond', 'retention pond', 'recharge
    basin') are taken out of the text before the water words are read (STATE_NOT_WATER_TEXT["AZ"]); a water-feature
    or other pond still counts in an overflow's report.
  - Bypasses held at the plant: a bypass whose text sends the flow to a pond or lagoon (a bypass's pond is the
    plant's: AZ_BYPASS_POND) or says it was contained on the plant's property or site, and names no other water, is
    dropped with the reason "bypass held at the plant (its own pond, lagoon or grounds)" (Cottonwood's lined effluent
    ponds, 9 reports; Grand Canyon South Rim's emergency effluent lagoon, 1).
  - The plant's point: many permits give one point for most of their reports (Grand Canyon's South Rim plant 30 of
    32, Yuma 15 of 17). For the prefixes in REPEATED_POINT_ALL_REPORTS (AZ, NN) a point that three or more of a
    permit's reports give (kept or dropped) is taken as the permit's location when it lies within
    REPEATED_POINT_PLANT_M (1,000 m) of a point EPA's plant list gives the permit; a shared point farther away, or of a
    permit with no plant point, is kept with raw.point_note. The descriptions are not compared: an Arizona
    description ('Manhole ID : 112945') carries the report's own form id, not an asset number. Bypasses keep the point.
  - Free text: descriptions give street addresses ('SSO at <number> N <street> Blvd') and 'Other' texts mention
    private residences: the AZ rows (FREE_TEXT_STATES) get the Illinois scrub (house numbers removed).

South Dakota (permits SD...; research/sd/report.md section 2.2; not live until data/rules.json says so)
  South Dakota has no public-notice law for sewage; its permittees file their 5-day written overflow and bypass reports
  through EPA's NeT-SewerOverflow, so this dataset is the state's only dated, event-level record (2026-11-04 extract:
  208 current SD rows from 56 permits, starts April 2023 to 2026-11-02; SSO 167, BYP 40, CSO 1; every row with a
  point, 186 with a volume; received a median 5 days after the start, 10% the same day, 10% 57 days or more). 57 are
  kept, from 30 permits; 151 dropped: 97 SSOs naming no water and no water impact, 34 building backups, 20 naming no
  water in words. Lead's CSO permit (SD0027481) files its Gold Run Creek overflows as SSOs at a manhole; they are kept
  by the water they name. Four South Dakota habits are handled here, for SD permits only, so every other state's records
  are unchanged (checked on that extract: 1,809 kept and 1,741 dropped records of the other states identical):
  - Time zone. The state straddles Central and Mountain time, so one zone would mislabel a third of the reports
    (Central for the whole state: 71 of 208 rows, 14 of 57 kept; Mountain: 137 rows, 43 kept). The rule uses public
    records only: the event's own point against the outlines of the counties the Mountain zone covers. The boundary is
    49 CFR 71.7(b) (down the Missouri River from North Dakota to Pierre, then along the north line of Jones County and
    the west lines of Jones, Mellette and Todd counties); it leaves fifteen counties wholly in the Mountain zone (Bennett,
    Butte, Corson, Custer, Dewey, Fall River, Haakon, Harding, Jackson, Lawrence, Meade, Oglala Lakota, Pennington,
    Perkins, Ziebach) and splits Stanley County, whose corner around Fort Pierre keeps Central time. The outlines are
    the Census Bureau's TIGERweb counties (data/reference/sd-mountain-time-counties.json, written by
    scripts/sd_mountain_time_counties.py, which cites both). A point in one of the fifteen is read as America/Denver.
    Stanley County is cut in two by the U.S. DOT time-zone layer's Central polygon (NTAD Time Zones, committed in the
    same file; review 2026-11-07 P2-2): a point in its Fort Pierre corner is Central, a point in the rest of it (84% of
    the county) Mountain. Any other point is America/Chicago (STATE_TZ), and raw.timezone_note names the county, or the
    part of Stanley County, that decided it. On that extract: 71 rows Mountain (Rapid City, Spearfish, Hot Springs,
    Lead, Sturgis, Custer, Keystone, and one Oahe Dam row in western Stanley County), 137 Central. The DOT layer as a
    whole agrees on 207 rows; the other is the second Oahe Dam row (SD0026794), in Hughes County on the river channel
    that is the boundary, read here as Central. Both Oahe Dam rows are dropped. Fort Pierre's four rows are Central.
  - Receiving-water texts that name none (STATE_NO_WATER["SD"]): 'Does not apply- Do not discharge to any waters',
    'NA, <why>' (unless the why says the water was discharged: then STATE_NO_NAME reads it as no name given, so
    the bypass is kept by the bypass rule), the flow sent to the city's sewer system or plant ('Sanitation system of
    City of ...', '... Wastewater Facility', '... WWTP', '... sewer system/POTW'), a lagoon cell ('Cell # 3', 'Cell 4 at the Lagoons'), 'Excavated
    hole. No waterbody.', 'water is discharged out into a field', and 'Ditch by Lake ... Water never entered lake'.
    'Spearfish Creek / Rubble Site Cell' and 'Unnamed' stay waters.
  - The description's water words: a lagoon system's "emergency pond" is a holding cell of the plant, not a water
    (STATE_NOT_A_WATER_TEXT["SD"]); a detention pond, a creek or a storm drain still counts.
  - Free text: descriptions carry house addresses of backups and breaks ('entered basement of <number> <street>',
    'SSO - <number> <street> SE'), so SD is in FREE_TEXT_STATES (the Illinois scrub). The points are the events' own
    (no kept point is shared by more than four reports of one permit), so SD is not in REPEATED_POINT_STATES.

Planned bypasses (every state; review 2026-11-07 P2-3)
  An anticipated bypass notice (reporting requirement 'Anticipated bypass notice', code 4, or a report carrying the
  anticipated-bypass text) gives the operator's planned start and end; a planned end can lie months ahead (Rapid City's
  UV-building bypass to Rapid Creek, 2026-11-02 to 2027-04-30; Aberdeen's plant rebuild to Moccasin Creek, 2026-03-23
  to 2028-06-01). While that end is still ahead of the run, the record is ongoing with the planned end as ended_at,
  raw.end_is_planned true and raw.planned_end_note saying so; the status build keeps such an end (it is not a typing
  error) and colours the discharge to it. Once the end has passed the record is ended, as any other. An end far ahead
  on any other report is still treated as a typing error by the status build (unresolved.implausible_end).
  On the 2026-11-04 extract four records carry a planned end ahead: the two South Dakota ones above and two Navajo
  Nation bypasses in Arizona (NN0020265 to Nazlini Wash and NN0020281 to Laguna Creek, both to 2027-01-01 as filed).

Mississippi (permits MS...; research/ms/report.md section 2.2; not live until data/rules.json says so)
  MDEQ requires the 5-day written report of every SSO and bypass through EPA's NeT-SewerOverflow from 2025-12-21, so
  this dataset is the statewide record (2026-11-04 all-versions extract: 358 current MS rows from 47 permits, all with
  coordinates; SSO 314, BYP 43, CSO 1; report received a median 4 days after the start). MDEQ publishes no list of
  its own. Three Mississippi habits are handled here, for MS permits only, so the other states' records are unchanged:
  - Time zone: Mississippi is wholly in Central time; STATE_TZ gives America/Chicago, as for Illinois.
  - Free text: descriptions name the manhole's or break's street address ('<number> <street> DR - <manhole no.>'),
    so MS is in FREE_TEXT_STATES and every free-text field gets the Illinois scrub.
  - The City of Jackson's reports (MS0024295, MS0044059, run by JXN Water) give a creek's name without 'Creek'
    ('EUBANKS', 'HANGING MOSS ', 'TOWN'), and Meridian's (MS0020117) misspell its creeks three times ('OAKTIBEE
    CREEK', 'OKATIBBEE CREED', 'SAWASHEE CREEK'). STATE_WATER_ALIASES reads such a name, for that permit only, as
    the NHD flowline of the name (USGS NHD large-scale flowlines, GNIS id and the lines' bbox in the table, checked
    2026-11-07), and only when the report's point lies within ALIAS_REACH_KM (3.5 km) of that bbox: in the
    2026-11-04 extract 50 of 51 such reports lie within 3.5 km of the line itself (the farthest a Trahon Creek report
    at 3,466 m); one EUBANKS report 15.4 km from Eubanks Creek is kept as typed. Names with no such flowline
    ('BELHAVEN', 'CANEY', 'EASTOVER', 'THREE MILE'; JCUA's 'Forth Bayou Creek') are kept as typed.
    raw.receiving_waters keeps the text as reported and raw.receiving_water_aliases says what was read.
  - Two text rules (STATE_NOT_SEWAGE, STREET_WATER): a description saying the matter was not sewage ("customer
    thought there was sewer in the pond. It was algae ...") drops the report; a water word that is part of a street
    name ('FOREST LAKE CIR') is not read as a water.
  Points are the event's own (a manhole that overflows in each storm repeats its point; the Vicksburg plant's
  bypasses all give the plant's point), so MS is not in REPEATED_POINT_STATES. The generic 'no water' wordings cover
  the Mississippi rows ('None'); a roadside or drainage ditch named as the receiving water is kept as a water.

Nebraska (permits NE...; research/ne/report.md section 2.2; not live until data/rules.json says so)
  Nebraska has no public-notice law for sewage; its permittees file their overflow and bypass reports through EPA's
  NeT-SewerOverflow (DWEE's NeTSSO guide, publication 25-032), so this dataset is the state's only dated, event-level
  record (2026-11-04 all-versions extract: 162 current NE rows from 21 permits, starts 2022-04 to 2026-10-06; CSO 89, SSO 64,
  BYP 9; every row with a point, 158 with a volume; received a median 22.5 days after the start, 10% within a day, 10%
  83 days or more). 51 are kept, from 13 permits; 111 dropped: 83 building backups, 28 SSOs and manhole CSOs naming no
  water and no water impact. Omaha files under three permits (Papillion Creek WRRF NE0112810 with 71 rows, Missouri
  River WRRF NE0036358, the CSO permit NE0133680); the Papillion Creek rows are all typed CSO but none is at a CSO
  outfall (manholes, pump stations, broken pipes, basements), so they are kept only by the water they name. Four
  Nebraska habits are handled here, for NE permits only, so every other state's records are unchanged (checked on that extract: 1,809 kept and 1,741 dropped records of
  the other states identical):
  - Time zone. The state straddles Central and Mountain time. The rule uses public records only and is South Dakota's
    mechanism: the event's own point against the outlines of the area the Mountain zone covers (POINT_ZONE_FILES). The
    boundary is 49 CFR 71.7(c) (south from the South Dakota line along range and section lines through Cherry County,
    then the north and west lines of Thomas and McPherson counties, the north line of Keith County, the west line of
    Lincoln County and the west lines of Hayes and Hitchcock counties to Kansas); it leaves eighteen counties wholly in
    the Mountain zone (Arthur, Banner, Box Butte, Chase, Cheyenne, Dawes, Deuel, Dundy, Garden, Grant, Hooker, Keith,
    Kimball, Morrill, Perkins, Scotts Bluff, Sheridan, Sioux) and splits Cherry County, whose western part keeps
    Mountain time. The outlines are the Census Bureau's TIGERweb counties, Cherry County's two parts cut by the U.S.
    DOT time-zone layer (NTAD Time Zones) and filed as South Dakota files Stanley County (split_counties with
    mountain_part and central_part; data/reference/ne-mountain-time-counties.json, written by
    scripts/ne_mountain_time_counties.py, which cites all three). A point in one of the eighteen counties or in Cherry
    County's western part is read as America/Denver; any other point as America/Chicago (STATE_TZ), and
    raw.timezone_note names the county that decided it, quoting the file's note for a split county. On that extract every one of the 162 points lies in the Central part (Omaha, Lincoln, Grand
    Island, Seward, Falls City, Nebraska City and the other reporting towns are all east of the line); a single Central
    zone would mislabel none of them today, a single Mountain zone all 162. The point rule is kept so a report from the
    panhandle (Scottsbluff, Sidney, Ogallala, Alliance, Chadron) is read in its own zone when one is filed.
  - Free text: descriptions carry house addresses of backups ('Sewer Back-up into home located at <number> <street>'),
    so NE is in FREE_TEXT_STATES (the Illinois scrub). The receiving-water texts name no "none" wordings the generic rule
    misses (no STATE_NO_WATER entry). The points are the events' own (no point is shared by
    more than four reports of one permit), so NE is not in REPEATED_POINT_STATES.
  - CSO by structure (CSO_BY_STRUCTURE_STATES; review 2026-11-07 P2-1). EPA's system table registers both Omaha
    collection systems as combined, yet the Papillion Creek and Missouri River plants file manhole, pipe and pump-station
    overflows in the separated western sewers (Boxelder Creek, the Elkhorn River, points west of every one of Omaha's 25
    CSO outfalls) as CSOs. A CSO-typed NE report stays a CSO only at a CSO outfall or regulator, with a permitted
    feature, or when its description names the permit's outfall ("at CSO 204", read into outfall_id with
    raw.outfall_basis); any other is written sso, with raw.type_as_filed "CSO" and raw.type_note. On the 2026-11-04
    extract 28 kept reports change (27 Papillion Creek, 1 Missouri River); the 4 kept CSOs are Omaha's CSO permit's
    (outfalls 110, 119, 204 twice). A retyped report is never placed on every water of Omaha's operator row (that
    inference is for CSOs): it is placed by the water it names, its point, or not at all.
  - 'Unknown' as the receiving water (UNKNOWN_WATER_STATES): two Papillion Creek reports into a storm inlet. They are
    kept (the report says a water was reached), but waterbody_text is null, so 'Unknown' is never printed as a water;
    the text stays in raw.receiving_waters and raw.receiving_water_note says why.

Alaska (permits AK...; research/ak/report.md; not live until data/rules.json says so)
  Alaska's APDES permittees that file electronically report here, and this dataset is the only dated, machine-readable
  overflow record for the state (the 2026-11-04 all-versions extract: 46 current AK rows from 3 permits, 2023-06-05 to
  2026-10-26: Anchorage AK0022551 43, Ketchikan AK0021440 2 anticipated pump-station bypasses, Denali National Park
  AK0053775 1; 44 SSO and 2 bypass; 22 'Basement Backup'; receipt a median 1 day after the start, the anticipated
  bypasses filed before they began). Juneau's CSO permit (AK0023213) files nothing here. Two Alaska rules, keyed on
  AK permits only, so the other states' records are unchanged:
  - Time zone (docs/decisions.md, National expansion item 6): America/Anchorage, labelled in raw.timezone_note.
    49 CFR 71.12 puts "that part of the Aleutian Islands that is west of 169 degrees 30 minutes west longitude" in the
    Hawaii-Aleutian zone and 71.11 the rest of Alaska in the Alaska zone, so an event whose own point lies in the
    Aleutian chain west of that line is read as America/Adak, and the note says so. The chain is taken as two boxes
    (AK_ALEUTIAN_WEST): longitude -180 to -169.5 with latitude 51 to 54.5 N (the Islands of Four Mountains to the
    Andreanof Islands), and longitude 172 to 180 E with latitude 51 to 53.5 N (the Rat and Near Islands, Attu and
    Shemya). Alaska land west of the line but off the chain stays Alaska time: the Pribilof Islands (St. Paul and St.
    George, 56.5 to 57.3 N) and St. Lawrence Island (63 to 63.8 N). A positive longitude outside the Near Islands box
    (a sign slip such as 149.9 for -149.9) stays Alaska time. No AK event in the extract lies in the boxes (the
    westernmost is Denali, -148.9); one AK sewage permit in EPA's plant table does (Shemya Island, AKG573005, 52.72 N
    174.09 E) and has not filed; St. Paul (AKG527721, 57.12 N -170.26) is Alaska time. An event without a point keeps
    America/Anchorage.
  - Receiving-water text: a report naming the water and where it went ('Fish Creek which flowed to Travels to Cook
    Inlet') is read as both waters ('Fish Creek', 'Cook Inlet'); the text as typed stays in raw.receiving_waters and
    raw.receiving_water_aliases says what was read (STATE_WATER_SPLIT).
  - The generic text rule applies unchanged: 'Sewer Overflow out of manhole at Riley Creek Mercantile' (Denali; land
    impact, no receiving water; the point about 540 m from Riley Creek) is kept as "text names a water (creek)",
    erring on the side of showing it.
  Alaska's descriptions carry no addresses or personal names ('SSO', 'FOG and Rags', 'Ruptured 30" Sewer Force
  main'), and no point is shared by many reports (Ketchikan's two bypasses give the pump station's), so AK is in
  neither FREE_TEXT_STATES nor REPEATED_POINT_STATES.

New Mexico (permits NM..., and the Navajo Nation's NN... where the event's point is in New Mexico; research/nm/report.md
section 2.2; not live until data/rules.json says so)
  EPA Region 6 issues New Mexico's permits, so their 24-hour and five-day noncompliance reports go to EPA, and those filed
  electronically reach this dataset. Few do (2026-11-04 extract): 2 reports under New Mexico permits, both the Town of
  Taos's (NM0024066, 2026-02 and 2026-10), although EPA's collection-system table lists 55 New Mexico permits
  (Albuquerque, Santa Fe and Las Cruces among them); and 6 Navajo Nation reports whose point lies in New Mexico (3 under
  the Shiprock plant's NN0020621, 2024-06 to 2025-11, and three under Window Rock's NN0021555, 2026-08; 8 in all).
  New Mexico's own notice rule (20.6.2.1203 NMAC: an oral report to NMED within 24 hours)
  leaves no public record. The rules below are keyed on NM (and the NM and NN prefixes), so the other states' records
  are unchanged:
  - Navajo Nation permits (NN...): placed by the event's own point as for Arizona (navajo_point_place: east of 109.045 W
    and south of 37 N is New Mexico, except within NAVAJO_BAND of that meridian, where the Census state outlines decide,
    since the Arizona-New Mexico line runs up to 430 m west of it; review 2026-11-07 P2-1), with raw.state and
    raw.state_basis. 2026-11-04 extract: 8 located in New Mexico (Shiprock 3, Window Rock's permit 3: two lift-station
    reports at Navajo, New Mexico, 48 m east of the line, and a line break east of Fort Defiance). The Nation's
    clock (PERMIT_TZ, America/Denver) is New Mexico's zone too, so its reports and the state's read alike.
  - Time zone (docs/decisions.md, National expansion item 6): STATE_TZ gives America/Denver (Mountain time with
    daylight saving time). Known problem: one Taos report (2026-02-19) gives 18:10 to 18:30 while its description says
    "from 1:10pm to 1:30pm", five hours apart; times are read as filed (that report is dropped: no water).
  - A longitude filed without its minus sign (SIGN_REPAIR_PREFIXES: NM, NN): one Shiprock report gives 108.666488 E. A
    positive longitude whose negative lies, with the latitude, in the Four Corners states' box (SIGN_REPAIR_BOX) is
    read as west, raw.reported_longitude keeping what was filed and raw.coord_note saying so, before the state is read
    from it; any other positive longitude is kept as filed.
  - Receiving-water entries that name only the plant's own lagoon ('by passed into emergency lagoon.') are no water
    (STATE_NO_WATER["NM"] is Arizona's pattern for the same Navajo Nation habit). A bypass whose receiving-water field
    names the San Juan River is kept on that river although its description says the flow went to the back-up lagoon:
    the permittee named the river (the safe side); raw.kept_note says so (LAGOON_NOTE_STATES).
  - Free text: descriptions give street intersections ('on <street> and <street> Intersection'): the NM rows
    (FREE_TEXT_STATES) get the Illinois scrub. Points are the event's own; the Shiprock plant's two bypasses give the
    plant's point, which bypasses keep.
  - A Navajo Nation report dropped for New Mexico or Arizona carries "state" in the dropped file, so the state scripts
    count it under the state it was placed in.

Lag and cadence
  'The data are refreshed daily' (extract ~07:10 ET); event-to-receipt lag in NE: median 2-3 days,
  90th percentile 6-7 days (NH, MA), 38 days (RI), so weeks of lag overall. Poll daily.

Run from pipeline/:  python -m ingest.echo_sewer_overflow_events [--file saved.zip]   (either ZIP)
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

import common
from common import (BUILD_DIR, DATA_DIR, HEADERS, ROOT, event, now_iso, read_json, save_raw,
                    write_events, write_json)

SOURCE_ID = "echo-sewer-overflow"
URL = "https://echo.epa.gov/files/echodownloads/current_sewer_overflow_and_collection_systems_tables.zip"
# the all-versions ZIP: every submitted version of each report, read for its current rows when URL fails
ALL_URL = "https://echo.epa.gov/files/echodownloads/all_sewer_overflow_and_collection_systems_tables.zip"
FALLBACK_DIR = ROOT / "research" / "federal" / "raw" / "sobe_current"
STATES = {"CT", "MA", "ME", "NH", "RI", "VT", "NY", "DC", "GA", "WA", "IL", "AZ", "SD", "MS", "NE", "AK", "NM"}
# states whose times are written with their zone's offset (module docstring, Illinois); the others stay naive
STATE_TZ = {"IL": "America/Chicago", "AZ": "America/Phoenix", "SD": "America/Chicago", "MS": "America/Chicago",
            "NE": "America/Chicago", "AK": "America/Anchorage", "NM": "America/Denver"}
# states that straddle two zones: STATE_TZ is the zone outside the listed counties, and an event whose own point lies in
# one of the counties of the reference file is read in that file's zone (module docstring, South Dakota and Nebraska)
POINT_ZONE_FILES = {"SD": "sd-mountain-time-counties.json", "NE": "ne-mountain-time-counties.json"}
# a state's part in another zone, by the event's own point: [(lon_min, lon_max, lat_min, lat_max)], zone. The Aleutian
# Islands west of 169 deg 30 min W are Hawaii-Aleutian time (49 CFR 71.12; the rest of Alaska 71.11); module docstring
AK_ALEUTIAN_WEST = [(-180.0, -169.5, 51.0, 54.5), (172.0, 180.0, 51.0, 53.5)]
STATE_TZ_WEST = {"AK": (AK_ALEUTIAN_WEST, "America/Adak")}
# states whose free-text fields get the full scrub (owners' names, house numbers; module docstring, Illinois)
FREE_TEXT_STATES = {"IL", "AZ", "SD", "MS", "NE", "NM"}
FREE_TEXT_FIELDS = ("sewer_overflow_bypass_description_text", "sewer_overflow_structure_type_code_other_text",
                    "anticipated_bypass_text", "anticipated_bypass_expect_limit_violation_text")
# a permit's shorthand receiving-water names -> the NHD name, keyed (permit, _alias_key(text)); module docstring,
# Mississippi (and Alaska's Birch Lake, a Census record's alias). Each NHD flowline of the name runs within about 3 km
# of the reports' points (GNIS id after the name).
STATE_WATER_ALIASES = {"MS": {
    # (permit, _alias_key(text)): (NHD name, GNIS id, the NHD flowlines' bbox [lon0, lat0, lon1, lat1])
    ("MS0024295", "eubanks"): ("Eubanks Creek", "00669816", (-90.2099, 32.3221, -90.1528, 32.3590)),
    ("MS0024295", "hanging moss"): ("Hanging Moss Creek", "00670883", (-90.2371, 32.3604, -90.1039, 32.4146)),
    ("MS0024295", "town"): ("Town Creek", "00678831", (-90.2395, 32.2835, -90.1783, 32.3595)),
    ("MS0024295", "purple"): ("Purple Creek", "00676424", (-90.1506, 32.3663, -90.1044, 32.4174)),
    ("MS0024295", "lynch"): ("Lynch Creek", "00672967", (-90.2806, 32.2725, -90.1872, 32.3394)),
    ("MS0024295", "white oak"): ("White Oak Creek", "00679605", (-90.2005, 32.3641, -90.1270, 32.4497)),
    ("MS0024295", "hardy"): ("Hardy Creek", "00670914", (-90.2530, 32.2508, -90.2049, 32.2860)),
    ("MS0044059", "trahon"): ("Trahon Creek", "00678852", (-90.2825, 32.1780, -90.2399, 32.2570)),
    # Meridian's misspellings of its own creeks (its other reports spell them right)
    ("MS0020117", "oaktibee creek"): ("Okatibbee Creek", "00691590", (-88.8433, 32.1826, -88.7475, 32.6101)),
    ("MS0020117", "okatibbee creed"): ("Okatibbee Creek", "00691590", (-88.8433, 32.1826, -88.7475, 32.6101)),
    ("MS0020117", "sawashee creek"): ("Sowashee Creek", "00678030", (-88.7515, 32.3039, -88.6085, 32.4747)),
}, "AK": {
    # Anchorage's Birch Lake (Alaska final audit 2026-11-07): the state's only other record of the name is the lake near
    # Delta Junction, 505 km away. The name is read as the Anchorage lake's record alias; the bbox is the Census
    # TIGER/Line polygon 'Birch Lk' (OID 11050902166) the hand record is built from (no GNIS id: Census, not NHD)
    ("AK0022551", "birch lake"): ("Birch Lake (Anchorage)", None, (-149.9387, 61.1444, -149.9352, 61.1458)),
}}
# a shorthand is read as the NHD name only when the report's point lies within this distance of the named lines' bbox
ALIAS_REACH_KM = 3.5
# states whose reports mostly carry the permit's point rather than the event's (module docstring, Georgia)
REPEATED_POINT_STATES = {"GA", "AZ", "NN"}
REPEATED_POINT_MIN = 5
# Arizona and the Navajo Nation (module docstring, by permit prefix): a point counts as the plant's when three or more
# of the permit's reports, kept or dropped, give it and it lies within REPEATED_POINT_PLANT_M of a point EPA's plant
# list gives the permit (data/outfalls-plants-us.json); a shared point farther away is kept, with a note
REPEATED_POINT_ALL_REPORTS = {"AZ", "NN"}
REPEATED_POINT_MIN_BY_STATE = {"AZ": 3, "NN": 3}
REPEATED_POINT_PLANT_M = 1000
PLANTS_FILE = DATA_DIR / "outfalls-plants-us.json"
# permits whose prefix is not a state (module docstring, Navajo Nation): the state the report counts under is read from
# the event's own point; the reports placed outside STATES are skipped as before
POINT_PLACED_PREFIXES = {"NN"}
# permit prefixes with a clock of their own (module docstring, Navajo Nation): before STATE_TZ
PERMIT_TZ = {"NN": "America/Denver"}
# permit prefixes whose positive longitude is read as west when its negative lies in SIGN_REPAIR_BOX (module docstring,
# New Mexico): [lon_min, lat_min, lon_max, lat_max] around Arizona, New Mexico, Utah and Colorado
SIGN_REPAIR_PREFIXES = {"NM", "NN"}
SIGN_REPAIR_BOX = (-114.9, 31.3, -102.0, 42.0)
# states whose kept reports that name a receiving water but describe the flow going to the plant's lagoon carry a note
# saying why they are shown (module docstring, New Mexico; review 2026-11-07 P2-3)
LAGOON_NOTE_STATES = {"NM"}
LAGOON_TEXT = re.compile(r"\blagoons?\b", re.I)
AUTHORITY = "EPA ECHO Sewer Overflow and Bypass Event report (reported to regulators)"
SUMMARY_URL = "https://echo.epa.gov/tools/data-downloads/sewer-overflow-download-summary"

TYPE_MAP = {"CSO": "cso", "SSO": "sso", "BYP": "bypass"}
MATERIAL = {"cso": "combined sewage and stormwater", "sso": "untreated sewage",
            "bypass": "wastewater diverted around part of the treatment process"}
MEASURED = {"Automated Remote Monitoring", "Manual Direct Measurement"}
ESTIMATED = {"Best Professional Judgement", "Modeling"}
WATER_IMPACTS = {"AHI", "ALI", "SBC", "BEC", "DWC"}
BUILDING_TEXT = re.compile(r"basement|bathtub|bathroom|toilet|\bhome\b|\bhouse\b|residential", re.I)
NO_WATER_TEXT = re.compile(r"^\s*(none|n/?a|no water ?body|no discharge.*|no direct discharge.*|not applicable|"
                           r"did\s*n\S*\s+(?:enter|reach)\b.*)\s*\.?\s*$", re.I)
# Georgia reports' own ways of saying no water was reached (dry land, misspelt "not applicable", a basement), read
# only for GA permits so the live states' rows are untouched
STATE_NO_WATER = {"GA": re.compile(r"^\s*((?:n/?a\s+)?dry\s*land(?:\s+spill)?|n[o0][a-z]?t?\s+ap+l?i?c\w*|non\s+applicable|"
                                   r"bu\w*ding\s+basement|did\s*n\S*\s+discharge\b.*)\s*\.?\s*$", re.I),
                  # Illinois: a lawn, an expectation of none, "None, <where>", the plant's own lagoon
                  "IL": re.compile(r"^\s*(lawn|grass|yard|we do not expect\b.*|none\s*[,;:-].*|"
                                   r"(?:[\w.' -]+\s)?lagoons?)\s*\.?\s*$", re.I),
                  # Arizona and the Navajo Nation: the flow bypassed into the plant's own (emergency) lagoon
                  "AZ": re.compile(r"^\s*(?:by\s*-?\s*passed|bypassed|diverted)\s+(?:in)?to\s+(?:the\s+|an?\s+|our\s+)?"
                                   r"(?:emergency\s+)?lagoons?\s*\.?\s*$", re.I),
                  # South Dakota: "does not apply", "NA, <why>", the flow sent to the sewer system or a plant, a lagoon
                  # cell, an excavation, a field, and a report that says the water was never reached
                  "SD": re.compile(r"^\s*(does not apply\b.*|n/?a\s*[,;:-](?!.*\bdischarged?\b).*|.*\bsewer system\b.*|"
                                   r"sanitation system\b.*|.*\bwastewater (?:treatment )?(?:facility|plant)|.*\bwwtp|"
                                   r"(?:[\w.' -]+\s)?cell\s*#?\s*\d+\b.*|excavated hole\b.*|.*\bno ?water ?body\b.*|"
                                   r"water (?:is|was) discharged (?:out )?(?:into|onto) a field|.*\bnever (?:entered|reached)\b.*)"
                                   r"\s*\.?\s*$", re.I)}
# New Mexico (the Navajo Nation's reports placed there): Arizona's wording for the plant's own lagoon
STATE_NO_WATER["NM"] = STATE_NO_WATER["AZ"]
# receiving-water texts that name no water but do not deny one either: read as no name given, so the other rules
# decide (South Dakota: "NA, all water was filtered before discharged." on a bypass that was discharged; review
# 2026-11-07 P2-4)
STATE_NO_NAME = {"SD": re.compile(r"^\s*n/?a\s*[,;:-].*\bdischarged?\b", re.I)}


def named(waters: list[str], state: str | None) -> list[str]:
    """The receiving-water texts minus those of STATE_NO_NAME (no name given, no denial)."""
    pat = STATE_NO_NAME.get(state or "")
    return [w for w in waters if not (pat and pat.match(w))]


# words that name a structure of the sewer system, not a water, taken out of the text before WATER_WORDS is read, for
# the listed states only (South Dakota's lagoon systems pump to an "emergency pond", a holding cell of the plant)
STATE_NOT_A_WATER_TEXT = {"SD": re.compile(r"\bemergency ponds?\b", re.I)}


def alias_reaches(bbox, lat, lon) -> bool:
    """The report's point lies within ALIAS_REACH_KM of the bbox of the NHD lines an alias names."""
    if lat is None or lon is None:
        return False
    import math
    dlat = ALIAS_REACH_KM / 110.54
    dlon = ALIAS_REACH_KM / (111.32 * math.cos(math.radians(lat)))
    return bbox[0] - dlon <= lon <= bbox[2] + dlon and bbox[1] - dlat <= lat <= bbox[3] + dlat


# Mississippi (module docstring): a description saying the matter was not sewage, and a water word that is a street's
# name ('FOREST LAKE CIR'), read for MS permits only
STATE_NOT_SEWAGE = {"MS": re.compile(r"\bthought there was sew\w*\b.*\bit was\b", re.I)}
STREET_WATER = {"MS": re.compile(r"\b(?:river|brook|stream|creek|pond|lake|harbou?r|bay|cove)\s+(?:cir|circle|dr|drive|st|"
                                 r"street|rd|road|ln|lane|ave|avenue|blvd|ct|court|pl|place|ter|terrace|way|pkwy|trl|"
                                 r"trail|cv)\b\.?", re.I)}


# states whose CSO-typed reports are read by the structure they come from (module docstring, Nebraska): a report typed
# CSO stays a CSO only at a CSO outfall or regulator, or when it names the permit's outfall ("at CSO 204"); a manhole,
# pipe or pump-station overflow is a sanitary sewer overflow, with the type as filed in raw.type_as_filed
CSO_BY_STRUCTURE_STATES = {"NE"}
CSO_OUTFALL_IN_TEXT = re.compile(r"\bCSO\s*(?:outfall\s*)?#?\s*(\d{3}[A-Z]?)\b", re.I)
# states whose receiving-water text 'Unknown' is a placeholder: never printed as a water name
UNKNOWN_WATER_STATES = {"NE"}
UNKNOWN_WATER = re.compile(r"^\s*unknown\s*\.?\s*$", re.I)


def cso_by_structure(ev: dict, outfall: str | None) -> tuple[str, str | None, dict]:
    """(event_type, outfall, raw notes) for a CSO-typed report of a CSO_BY_STRUCTURE_STATES permit."""
    struct = ev.get("sewer_overflow_structure_type_code") or ""
    other = ev.get("sewer_overflow_structure_type_code_other_text") or ""
    notes = {}
    if not outfall:
        m = CSO_OUTFALL_IN_TEXT.search(ev.get("sewer_overflow_bypass_description_text") or "")
        if m:
            outfall = m.group(1).upper().zfill(3)
            notes["outfall_basis"] = f"outfall {outfall} read from the description ({m.group(0)!r})"
    if outfall or struct == "CSO" or (struct == "OTH" and OUTFALL_TEXT.search(other)):
        return "cso", outfall, notes
    notes["type_as_filed"] = "CSO"
    notes["type_note"] = (f"filed as a combined sewer overflow, but at a {(ev.get('sewer_overflow_structure_type_desc') or 'structure not given').lower()}"
                          ", not at a combined sewer outfall or regulator: shown as a sewer overflow")
    return "sso", outfall, notes


# a receiving-water text naming the water and where it went: both are read (module docstring, Alaska)
STATE_WATER_SPLIT = {"AK": re.compile(r"^(.+?)\s+which\s+flow\w*\s+(?:(?:to|into)\s+)?(?:travel\w*\s+)?"
                                      r"(?:(?:to|into)\s+)?(.+?)\s*\.?\s*$", re.I)}


def no_water(w: str, state: str | None = None) -> bool:
    """The receiving-water text says there was none (NO_WATER_TEXT, and the state's own wordings)."""
    pat = STATE_NO_WATER.get(state or "")
    return bool(NO_WATER_TEXT.match(w) or (pat and pat.match(w)))
WATER_WORDS = re.compile(r"\b(river|brook|stream|creek|pond|lake|harbou?r|bay|cove|waterway|body of water|"
                         r"storm ?drain|catch basin|wetland|swamp|ocean)\b", re.I)
OUTFALL_TEXT = re.compile(r"\bcso\b|regulator|outfall", re.I)
TZ_NOTE = "ECHO gives event times without a timezone; recorded as given (presumably local time)"
# Arizona (module docstring): a wash, arroyo or canal named ('Queen Creek Wash', 'RID canal') or one the overflow went
# to, into or through; read only for AZ permits
AZ_NAMED_WASH = re.compile(r"\b((?:[A-Z][\w'-]*\s+){1,3})(Wash|Washes|Arroyo|Canal)\b")
AZ_CAPS_CANAL = re.compile(r"\b[A-Z]{2,}\s+(?i:canal)\b")
# a wash the overflow went to, into or through: a determiner or a dry/unnamed before it, or "to wash" ending the clause
AZ_TO_WASH = re.compile(
    r"(?i:\b(?:to|into|in|through|entered|enter|entering|reached|reach|reaching)\s+"
    r"(?:(?:an?|the|this|that|these|unnamed|dry|nearby|adjacent|natural|desert|concrete|lined|open)\s+)"
    r"(?:[\w'-]+\s+){0,2}?(?:washe?s?|arroyos?|canals?)\b|"
    r"\b(?:went|flowed|ran|drained|go|goes|flows|discharged)\s+(?:in)?to\s+washe?s?(?=\s*(?:[.,;]|$)))")
# words before "Wash" that make it a place or a verb, not a water ('Car Wash', 'Crew Will Wash Down')
AZ_WASH_STOP = {"car", "truck", "power", "pressure", "crew", "crews", "will", "vactor", "hand", "wheel", "auto", "bus",
                "eye", "then", "and", "to", "please", "must", "should", "would", "can", "could", "shall", "did", "do",
                "was", "were", "staff", "we", "they", "then", "also", "jet", "high", "street", "area"}


def az_water_text(texts: str) -> str | None:
    """Arizona (module docstring): a named wash, arroyo or canal ('Queen Creek Wash', 'RID canal'), or one the
    overflow went to, into or through ('to an unnamed wash', 'Flow went to wash.'); None for the verb ('to wash down
    the street', 'Crew Will Wash Down Area') and places named for washing ('Car Wash', 'Vactor Truck Wash')."""
    for m in AZ_NAMED_WASH.finditer(texts):
        words = m.group(1).split()
        if not {w.lower().strip(".,;:'") for w in words} & AZ_WASH_STOP:
            return m.group(0)
    m = AZ_CAPS_CANAL.search(texts)
    if m:
        return m.group(0)
    for m in AZ_TO_WASH.finditer(texts):
        words = m.group(0).split()
        before = words[-2].lower().strip(".,;:'") if len(words) > 1 else ""
        if before == "to" or before not in AZ_WASH_STOP:   # 'went to wash'; not 'the Car Wash'
            return m.group(0)
    return None


STATE_WATER_TEXT = {"AZ": az_water_text}
# Arizona: a water named only to deny it, and the plant's own ponds and basins, taken out before the water words
STATE_NOT_WATER_TEXT = {"AZ": re.compile(
    r"(?i:\b(?:did\s*n[o']?t|does\s*n[o']?t|do\s*n[o']?t|never|no\s+impact\s+to)\s+(?:[\w-]+\s+){0,3}?"
    r"(?:any\s+|a\s+|the\s+)?(?:waterways?|bod(?:y|ies)\s+of\s+water|water\s*bod(?:y|ies)|surface\s+waters?|"
    r"waters?\s+of\s+the\s+(?:state|u\.?s\.?)|creeks?|rivers?|streams?|washe?s?|lakes?|canals?|arroyos?|ditch(?:es)?|"
    r"channels?)\b|"
    r"\b(?:effluent|storage|holding|retention|detention|evaporation|recharge|percolation|sludge|aeration|"
    r"emergency\s+effluent)\s+(?:storage\s+|holding\s+)?(?:ponds?|basins?|lagoons?)\b)")}
# Arizona bypasses: the flow held at the plant (its own pond or lagoon, or its grounds); and the pond words a bypass's
# text uses for that pond
AZ_PLANT_HELD = re.compile(r"(?i:\b(?:ponds?|lagoons?)\b|contained\s+(?:on|within|at)\s+(?:the\s+)?(?:plant|site|"
                           r"facility|wwtp|property)|on\s+plant\s+property|on-?site\b|stayed\s+on\s*site)")
AZ_BYPASS_POND = re.compile(r"(?i:\b(?:ponds?|lagoons?)\b)")
# Arizona receiving-water entries that are not names: counted as a water, no name given
AZ_WATER_ALIASES = {"UNK_PERNL": None}
AZ_WBID_RE = re.compile(r"^\s*(AZ\d{8}[A-Z]?-\d+[A-Z]?)\s*$")
AZ_WBID_FILE = DATA_DIR / "reference" / "az-adeq-wbids.json"
_AZ_WBID: dict | None = None


def az_wbids() -> dict:
    """ADEQ's WBIDs -> {name, kind, origin, terminus, flow_regime} (data/reference/az-adeq-wbids.json)."""
    global _AZ_WBID
    if _AZ_WBID is None:
        _AZ_WBID = (read_json(AZ_WBID_FILE, {}) or {}).get("wbids", {})
    return _AZ_WBID


def normalise_az_water(w: str) -> str | None:
    """An Arizona receiving-water entry as a name: a WBID as ADEQ names it, 'UNK_PERNL' as no name (None), any other
    text as typed (trimmed)."""
    t = (w or "").strip()
    if t in AZ_WATER_ALIASES:
        return AZ_WATER_ALIASES[t]
    m = AZ_WBID_RE.match(t)
    if m and (az_wbids().get(m.group(1)) or {}).get("name"):
        return az_wbids()[m.group(1)]["name"]
    # 'Black Creek wash however it was bypassed into lagoon', 'BLACK CREEK WASH, BYPASSED DIVERTED TO LAGOON': the name
    cut = re.sub(r"(?i)\s*(?:,|\bhowever\b|\bbypass(?:ed)?\b|\bby\s*-?\s*passed\b|\bdiverted\b).*$", "", t).strip(" .")
    return cut or t

NAVAJO_BASIS = ("a Navajo Nation permit (NN...), which spans Arizona, New Mexico and Utah: the state is the one the "
                "event's own point lies in, west of the Arizona-New Mexico line (109.045 W) and south of the Arizona-Utah "
                "line (37 N) being Arizona (the Four Corners boundaries)")
# the Arizona-New Mexico line is not the meridian: in the Census outlines it runs from 109.0452 W at the Four Corners
# to 109.0498 W at 31.5 N (review 2026-11-07 P2-1), so a point within NAVAJO_BAND of the meridian is placed by the Census
# Bureau's 1:500,000 state outlines (waters_extra.states_zip(), read by waters_from_nhd.read_state_outlines)
NAVAJO_BAND = (-109.056, -109.040)
NAVAJO_OUTLINE_BASIS = ("a Navajo Nation permit (NN...), which spans Arizona, New Mexico and Utah: the state is the one "
                        "the event's own point lies in; near the Arizona-New Mexico line, whose course runs up to 430 m "
                        "west of the 109.045 W meridian, the point is placed by the Census Bureau's 1:500,000 state "
                        "outlines (cb_2023_us_state_500k)")
NAVAJO_FALLBACK_BASIS = NAVAJO_BASIS + ("; the Census state outlines could not be read, so a point within 1.5 km of the "
                                        "meridian was placed by the meridian")
_NAVAJO_OUTLINES: dict | None = None


def repair_sign(ev: dict) -> tuple[dict, str | None]:
    """For SIGN_REPAIR_PREFIXES (module docstring, New Mexico): a positive longitude whose negative lies, with the
    latitude, in SIGN_REPAIR_BOX is read as west. (a copy of the row, the note), or (the row, None) unchanged."""
    try:
        la, lo = float(ev.get("latitude_measure")), float(ev.get("longitude_measure"))
    except (TypeError, ValueError):
        return ev, None
    x0, y0, x1, y1 = SIGN_REPAIR_BOX
    if lo <= 0 or not (x0 <= -lo <= x1 and y0 <= la <= y1):
        return ev, None
    out = dict(ev)
    out["longitude_measure"] = "-" + str(ev["longitude_measure"]).strip().lstrip("+")   # '+108.6' too
    return out, (f"longitude filed as {str(ev['longitude_measure']).strip()} (east of Greenwich), read as west: the "
                 "minus sign was missing, and only so does the point lie in the Four Corners states")


def navajo_outlines() -> dict:
    """{state: shapely geometry} for AZ, NM, UT and CO from the Census state outlines; {} when they cannot be read."""
    global _NAVAJO_OUTLINES
    if _NAVAJO_OUTLINES is None:
        try:
            from ingest import waters_extra as WX, waters_from_nhd as WFN
            # downloaded once when absent, except under the tests (a saved copy or the meridian rule there)
            zp = WX.states_zip(download="pytest" not in sys.modules)
            _NAVAJO_OUTLINES = WFN.read_state_outlines({"AZ", "NM", "UT", "CO"}, zip_path=zp)
        except Exception:   # noqa: BLE001 (no file and no network: the meridian rule, said in the basis)
            _NAVAJO_OUTLINES = {}
    return _NAVAJO_OUTLINES


def navajo_point_place(lat, lon) -> tuple[str | None, str | None]:
    """(the state a Navajo Nation report's point lies in, AZ, NM, UT or CO, and the basis); (None, None) without a
    point. Away from the Arizona-New Mexico line the Four Corners meridian and parallel decide; within NAVAJO_BAND of the
    meridian the Census state outlines do (the nearest outline when the point is in none)."""
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None
    if la == 0 and lo == 0:
        return None, None
    by_meridian = ("NM" if la < 37 else "CO") if lo >= -109.045 else ("AZ" if la < 37 else "UT")
    if not (NAVAJO_BAND[0] <= lo < NAVAJO_BAND[1]):
        return by_meridian, NAVAJO_BASIS
    shapes = navajo_outlines()
    if not shapes:
        return by_meridian, NAVAJO_FALLBACK_BASIS
    from shapely.geometry import Point
    pt = Point(lo, la)
    inside = [st for st, g in sorted(shapes.items()) if g.covers(pt)]
    st = inside[0] if inside else min(sorted(shapes), key=lambda k: shapes[k].distance(pt))
    return st, NAVAJO_OUTLINE_BASIS


def navajo_point_state(lat, lon) -> str | None:
    """The state a Navajo Nation report's point lies in (navajo_point_place); None without a point."""
    return navajo_point_place(lat, lon)[0]


TABLES = {
    "events": "sewer_overflow_bypass_report_events.csv",
    "types": "sewer_overflow_bypass_types.csv",
    "waters": "sewer_overflow_bypass_receiving_waters.csv",
    "impacts": "sewer_overflow_bypass_impacts.csv",
    "causes": "sewer_overflow_bypass_causes.csv",
    "actions": "sewer_overflow_bypass_corrective_actions.csv",
    "treatment": "sewer_overflow_treatment_codes.csv",
    "systems": "collection_system_permits.csv",
}
# the all-versions ZIP's tables (sewer_overflow_bypass_columns_metadata_all.csv): the events table is split into
# the report (one row per report version) and the event (one row per event per version)
ALL_TABLES = {
    "report": "sewer_overflow_bypass_report.csv",
    "event": "sewer_overflow_bypass_event.csv",
    "types": "sewer_overflow_bypass_type.csv",
    "waters": "sewer_overflow_bypass_receiving_water.csv",
    "impacts": "sewer_overflow_bypass_impact.csv",
    "causes": "sewer_overflow_bypass_cause.csv",
    "actions": "sewer_overflow_bypass_corrective_action.csv",
    "treatment": "sewer_overflow_treatment_code.csv",
    "systems": "collection_system_permit.csv",
}
# the version-tracking columns of the all-versions tables, which the current tables do not have
VERSION_COLUMNS = {"current_report_form_flag", "current_report_flag", "replaced_date", "replacing_payload_id",
                   "replacing_transaction_type", "transaction_id"}
# columns of the current events table that come from the all-versions report table (same names in both metadata
# CSVs); the event row's own transaction_type is the current table's event_transaction_type
REPORT_COLUMNS = ("program_report_received_date", "program_report_start_date", "program_report_end_date",
                  "electronic_submission_type_code", "electr_submission_type_desc",
                  "program_report_npdes_data_group_number_code", "payload_id", "transaction_type")
# columns of the current events table that come from the collection-system table
SYSTEM_COLUMNS = ("collection_system_owner_type_code", "collection_system_owner_type_desc", "collection_system_population")
# columns the build reads, checked by name before the all-versions tables are used
ALL_REQUIRED = {
    "event": ("permit_identifier", "program_report_form_set_id", "program_report_form_id", "sewer_overflow_bypass_event_key",
              "sewer_overflow_bypass_event_id_ext", "current_report_form_flag", "sewer_overflow_bypass_start_datetime",
              "sewer_overflow_bypass_end_datetime", "latitude_measure", "longitude_measure",
              "sewer_overflow_bypass_discharge_volume_gallons", "discharge_quantification_method_desc",
              "sewer_overflow_structure_type_code", "sewer_overflow_structure_type_desc",
              "sewer_overflow_structure_type_code_other_text", "sewer_overflow_bypass_description_text",
              "permitted_feature_identifier", "collection_system_identifier", "transaction_type"),
    "report": ("permit_identifier", "program_report_form_set_id", "program_report_form_id", "current_report_form_flag",
               *REPORT_COLUMNS),
    "types": ("sewer_overflow_bypass_event_key", "sewer_overflow_bypass_type_code", "sewer_overflow_bypass_type_desc",
              "sewer_overflow_bypass_type_code_sequence"),
    "waters": ("sewer_overflow_bypass_event_key", "name_receiving_water"),
    "impacts": ("sewer_overflow_bypass_event_key", "sewer_overflow_bypass_impact_code", "sewer_overflow_bypass_impact_desc",
                "sewer_overflow_bypass_impact_other_text"),
    "causes": ("sewer_overflow_bypass_event_key", "sewer_overflow_bypass_cause_code", "sewer_overflow_bypass_cause_desc",
               "sewer_overflow_bypass_cause_other_text"),
    "actions": ("sewer_overflow_bypass_event_key", "sewer_overflow_bypass_corrective_action_code",
                "sewer_overflow_bypass_corrective_action_desc", "sewer_overflow_bypass_corrective_action_other_text"),
    "systems": ("permit_identifier", "collection_system_identifier", "current_report_flag",
                "collection_system_name", "percent_collection_system_css", *SYSTEM_COLUMNS),
}
# tables that hold thousands of rows nationally: one that arrives empty is a failed read, never "no events" (an empty
# events table would otherwise empty every record of the feed; an empty report table would blank every report date)
ALL_NONEMPTY = ("event", "report", "types", "waters", "impacts", "systems")


# --------------------------------------------------------------------------- DC names and state

def _alias_key(text: str) -> str:
    """Lower case, '&' as 'and', punctuation dropped, spaces collapsed: 'Rock Creek ' == 'ROCK CREEK'."""
    t = (text or "").lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


# Free-text receiving waters in DC Water's reports and in ECHO's inventory -> the NHD name of the DC
# water record (research/dc/waters-dc.json, name and source_aliases). Keys are _alias_key() forms.
# 'Soapstone Valley stream' has no NHD name (it is the research record's name; no record is built yet).
# The Piney Branch address is the research file's alias for a row that gave an address as its water.
DC_WATER_ALIASES = {
    "potomac river": "Potomac River", "potomac river east side": "Potomac River",
    "anacostia river": "Anacostia River", "anacostia river east side": "Anacostia River",
    "anacostia river west side": "Anacostia River", "lower anacostia river": "Anacostia River",
    "anacostia": "Anacostia River",
    "rock creek": "Rock Creek", "rock creek east side": "Rock Creek", "rock creek west side": "Rock Creek",
    "piney branch": "Piney Branch", "park rd piney branch pky nw": "Piney Branch",
    "broad branch": "Broad Branch",
    "soapstone": "Soapstone Valley stream", "soapstone stream": "Soapstone Valley stream",
    "soapstone valley stream": "Soapstone Valley stream",
    "washington channel": "Washington Channel", "washington ship channel": "Washington Channel",
    "oxon run": "Oxon Run",
    "watts branch": "Watts Branch", "watts branch creek": "Watts Branch",
    "hickey run": "Hickey Run", "hickory run": "Hickey Run",
    "pope branch": "Pope Branch",
    "pinehurst branch": "Pinehurst Branch", "fenwick branch": "Fenwick Branch", "piney run": "Piney Run",
    "barnaby run": "Barnaby Run", "maddox branch": "Maddox Branch",
    "chesapeake and ohio canal": "Chesapeake and Ohio Canal", "c and o canal": "Chesapeake and Ohio Canal",
    "beaverdam creek": "Beaverdam Creek",
    "tidal basin": "Tidal Basin", "kingman lake": "Kingman Lake",
}


def normalise_dc_water(name: str) -> str:
    """The NHD name for a DC receiving-water text; the text itself, stripped, when it is not in the table."""
    return DC_WATER_ALIASES.get(_alias_key(name), (name or "").strip())


OUT_OF_DISTRICT_BASIS = ("point outside the District: DC Water's Potomac Interceptor runs through Maryland and "
                         "its overflows are reported in Maryland, operator unchanged (owner-decision default, Washington DC item 3)")


def dc_row_state(lat, lon) -> tuple[str | None, str | None]:
    """('MD', basis) for a DC0021199 row whose point lies outside the District (the Potomac Interceptor
    collapse of 2026-01-19 is in Montgomery County); (None, None) inside the District or with no point.
    The decision names Maryland. A point in Virginia (the Interceptor also runs through Loudoun and
    Fairfax) would get MD too and then fail the placement guard (no Maryland water near it), so it stays
    unplaced rather than landing on a wrong water. The District outline is the DC GIS boundary
    (ingest/dc_waters.py), which takes in the Potomac to the Virginia shore."""
    if lat is None or lon is None:
        return None, None
    from ingest.dc_waters import in_district
    return (None, None) if in_district(lat, lon) else ("MD", OUT_OF_DISTRICT_BASIS)


# --------------------------------------------------------------------------- fetch

def _zip_tables(zf: zipfile.ZipFile, wanted: dict[str, str]) -> dict[str, list[dict]]:
    names = {Path(n).name: n for n in zf.namelist()}
    return {k: list(csv.DictReader(io.TextIOWrapper(zf.open(names[v]), encoding="utf-8-sig")))
            for k, v in wanted.items() if v in names}


def _entry_date(zf: zipfile.ZipFile, name: str) -> str:
    names = {Path(n).name: n for n in zf.namelist()}
    return datetime(*zf.getinfo(names[name]).date_time).date().isoformat()


def is_all_versions(zf: zipfile.ZipFile) -> bool:
    return ALL_TABLES["event"] in {Path(n).name for n in zf.namelist()}


def current_from_all_versions(raw: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """The current-version tables (TABLES' keys and column names) from the all-versions tables (module docstring,
    2026-11-06): the event rows flagged current_report_form_flag Y, each joined to its report row by permit, form set
    and form id; child rows by the event key of a current event (EPA gives each version its own key); the collection
    systems flagged current_report_flag Y. Every column is mapped by its name in the two metadata CSVs; a column the
    build needs that is missing raises RuntimeError (a renamed table is a failed read, never a blank field)."""
    missing = [ALL_TABLES[k] for k in ("event", "report") if k not in raw]
    if missing:
        raise RuntimeError("all-versions ZIP has no " + ", ".join(missing))
    empty = [ALL_TABLES[k] for k in ALL_NONEMPTY if k in raw and not raw[k]]
    if empty:
        raise RuntimeError("all-versions ZIP has no rows in " + ", ".join(empty))
    for k, cols in ALL_REQUIRED.items():
        rows = raw.get(k) or []
        absent = [c for c in cols if rows and c not in rows[0]]
        if absent:
            raise RuntimeError(f"all-versions {ALL_TABLES[k]} lacks column(s) {', '.join(absent)}")

    def strip(r: dict, also=()) -> dict:
        return {c: v for c, v in r.items() if c not in VERSION_COLUMNS and c not in also}

    def key3(r: dict) -> tuple:
        return r["permit_identifier"], r["program_report_form_set_id"], r["program_report_form_id"]

    reports = {key3(r): r for r in raw["report"] if r.get("current_report_form_flag") == "Y"}
    systems = [strip(r) for r in raw.get("systems") or [] if r.get("current_report_flag") == "Y"]
    sysidx = {(r["permit_identifier"], r.get("collection_system_identifier") or ""): r for r in systems}
    events = []
    for r in raw["event"]:
        if r.get("current_report_form_flag") != "Y":
            continue
        row = strip(r, ("transaction_type",))
        row["event_transaction_type"] = r.get("transaction_type", "")
        rep = reports.get(key3(r)) or {}
        for c in REPORT_COLUMNS:
            row[c] = rep.get(c, "")
        sysrow = sysidx.get((r["permit_identifier"], r.get("collection_system_identifier") or ""), {})
        for c in SYSTEM_COLUMNS:
            row[c] = sysrow.get(c, "")
        events.append(row)
    keys = {r["sewer_overflow_bypass_event_key"] for r in events}
    out = {"events": events, "systems": systems}
    for k in ("types", "waters", "impacts", "causes", "actions", "treatment"):
        if k in raw:
            out[k] = [strip(r, ("payload_id", "transaction_type")) for r in raw[k]
                      if r.get("sewer_overflow_bypass_event_key") in keys]
    return out


def _get(url: str) -> tuple[zipfile.ZipFile, bytes, str | None]:
    r = requests.get(url, headers=HEADERS, timeout=180)
    r.raise_for_status()
    lm = r.headers.get("Last-Modified")
    return (zipfile.ZipFile(io.BytesIO(r.content)), r.content,
            parsedate_to_datetime(lm).isoformat().replace("+00:00", "Z") if lm else None)


def _save(content: bytes, last_modified: str | None) -> str | None:
    prev = (read_json(BUILD_DIR / "events" / f"{SOURCE_ID}.json", {}) or {}).get("meta", {})
    if prev.get("last_modified") and prev.get("last_modified") == last_modified:
        return None   # same extract as last run: no second copy
    return str(save_raw(SOURCE_ID, content, "zip").relative_to(ROOT))


def fetch_current() -> tuple[dict[str, list[dict]], dict]:
    zf, content, lm = _get(URL)
    names = {Path(n).name for n in zf.namelist()}
    if TABLES["events"] not in names:
        raise KeyError(f"current-version ZIP has no {TABLES['events']} (it holds {', '.join(sorted(names)) or 'nothing'})")
    tables = _zip_tables(zf, TABLES)
    if not tables["events"]:   # a header with no rows would empty every record of the feed: read the other ZIP
        raise KeyError(f"current-version ZIP's {TABLES['events']} has no rows")
    return tables, {"url": URL, "via": "live", "last_modified": lm, "raw_saved": _save(content, lm),
                    "extract_date": _entry_date(zf, TABLES["events"])}


def fetch_all_versions(why: str) -> tuple[dict[str, list[dict]], dict]:
    zf, content, lm = _get(ALL_URL)
    tables = current_from_all_versions(_zip_tables(zf, ALL_TABLES))
    return tables, {"url": ALL_URL, "via": "live, all-versions ZIP (current version of each report)", "last_modified": lm,
                    "raw_saved": _save(content, lm), "extract_date": _entry_date(zf, ALL_TABLES["event"]),
                    "note": f"The current-version ZIP could not be read ({why}); the current version of each report "
                            f"was taken from the all-versions ZIP ({ALL_URL}): rows flagged current_report_form_flag Y."}


def fetch() -> tuple[dict[str, list[dict]], dict]:
    """Tables from the live current-version ZIP; when it fails or holds no events table, the current rows of the live
    all-versions ZIP; when that fails too, the research copy (module docstring, Failures)."""
    try:
        return fetch_current()
    except (requests.RequestException, zipfile.BadZipFile, KeyError) as e:
        why = f"{type(e).__name__}: {e.args[0] if isinstance(e, KeyError) and e.args else e}"
        print(f"warn: ECHO current-version ZIP failed ({why}); trying the all-versions ZIP", file=sys.stderr)
    try:
        return fetch_all_versions(why)
    except (requests.RequestException, zipfile.BadZipFile, KeyError, RuntimeError) as e2:
        why = f"{why}; all-versions ZIP: {type(e2).__name__}: {e2}"
    print(f"warn: ECHO downloads failed ({why}); using {FALLBACK_DIR}", file=sys.stderr)
    info: dict = {"url": URL, "via": "research copy", "last_modified": None, "raw_saved": None,
                  "error": f"ECHO download: {why}"}
    zpath = FALLBACK_DIR / "current_sewer_overflow_and_collection_systems_tables.zip"
    if zpath.exists():
        zf = zipfile.ZipFile(zpath)
        info["extract_date"] = _entry_date(zf, TABLES["events"])
    tables = {}
    for k, v in TABLES.items():
        p = FALLBACK_DIR / v
        if p.exists():
            with open(p, encoding="utf-8-sig", newline="") as f:
                tables[k] = list(csv.DictReader(f))
    if "events" not in tables:
        raise RuntimeError(f"ECHO download failed and no research copy: {why}")
    return tables, info


# --------------------------------------------------------------------------- lookups

def by_event(rows: list[dict] | None) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows or []:
        out[r["sewer_overflow_bypass_event_key"]].append(r)
    return out


def discharger_index() -> dict[str, dict]:
    idx = {}
    for f in sorted((ROOT / "research").glob("*/dischargers.json")):
        rows = read_json(f, []) or []
        for r in rows if isinstance(rows, list) else rows.get("dischargers", []):
            if r.get("npdes_permit"):
                idx.setdefault(r["npdes_permit"], r)
    return idx


class Waters:
    """Receiving-water name -> openboatlaunch slug, in the permit's state; registry for outfalls."""

    def __init__(self):
        self.by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
        bbox = {}
        for st in ("ct", "ma", "me", "nh", "ri", "vt"):
            for w in (read_json(DATA_DIR / f"waters-{st}.json", {}) or {}).get("waters", []):
                bbox[w["slug"]] = w.get("bbox")
        with open(DATA_DIR / "waters-new-england.csv", newline="") as f:
            for r in csv.DictReader(f):
                r["bbox"] = bbox.get(r["slug"])
                self.by_name[(r["state"], self.key(r["name"]))].append(r)
        self.keys: dict[str, list[str]] = defaultdict(list)
        for st, k in self.by_name:
            self.keys[st].append(k)
        reg = read_json(DATA_DIR / "outfalls-new-england.json", {}) or {}
        self.outfalls = {(o["npdes_permit"], str(o["outfall"]).zfill(3)): o for o in reg.get("outfalls", [])}

    @staticmethod
    def key(name: str) -> str:
        s = (name or "").lower().replace("&", " and ")
        s = re.sub(r"\bwbid\b|\bestuar(y|ies)\s*:", " ", s)
        s = re.sub(r"\s+via\s+.*$", "", s)
        return re.sub(r"[^a-z0-9]", "", s)

    def by_text(self, text: str, state: str, lat, lon) -> list[str]:
        slugs = []
        parts = re.split(r",|;|\band\b|/", text or "")
        for part in [text or ""] + parts:
            hits = self.by_name.get((state, self.key(part)), [])
            if not hits and len(self.key(part)) >= 8:   # spelling slips: 'Conncecticut River'
                close = difflib.get_close_matches(self.key(part), self.keys.get(state, []), n=2, cutoff=0.92)
                if len(close) == 1:
                    hits = self.by_name[(state, close[0])]
            if hits and lat is not None:   # a same-named water elsewhere in the state is not this one
                pad = .02 if len(hits) > 1 else .05
                hits = [h for h in hits if h["bbox"] and h["bbox"][0] - pad <= lon <= h["bbox"][2] + pad
                        and h["bbox"][1] - pad <= lat <= h["bbox"][3] + pad]
            if len(hits) == 1 and hits[0]["slug"] not in slugs:
                slugs.append(hits[0]["slug"])
            if slugs and part == (text or ""):
                break   # the whole text matched one water
        return slugs


# --------------------------------------------------------------------------- rule

def reached_water(ev: dict, types: list[str], waters: list[str], impacts: list[dict],
                  state: str | None = None) -> tuple[bool, str]:
    struct = ev.get("sewer_overflow_structure_type_code") or ""
    other = ev.get("sewer_overflow_structure_type_code_other_text") or ""
    codes = {i["sewer_overflow_bypass_impact_code"] for i in impacts}
    waters = named(waters, state)
    real_waters = [w for w in waters if w.strip() and not no_water(w, state)]
    if struct == "BAS" or "SBB" in codes or (struct == "OTH" and BUILDING_TEXT.search(other)):
        if not real_waters:
            return False, "building backup"
    if waters and not real_waters:
        return False, "receiving water stated as none"
    if real_waters:
        return True, "receiving water named"
    if codes & WATER_IMPACTS:
        return True, "impact to a water (" + ",".join(sorted(codes & WATER_IMPACTS)) + ")"
    texts = " ".join([i.get("sewer_overflow_bypass_impact_other_text") or "" for i in impacts]
                     + [ev.get("sewer_overflow_bypass_description_text") or ""])
    if state in STATE_NOT_SEWAGE and STATE_NOT_SEWAGE[state].search(texts):
        return False, "the report says the matter was not sewage"
    if state in STREET_WATER:
        texts = STREET_WATER[state].sub(" ", texts)
    if state in STATE_NOT_A_WATER_TEXT:
        texts = STATE_NOT_A_WATER_TEXT[state].sub(" ", texts)
    held = bool(state == "AZ" and "BYP" in types and AZ_PLANT_HELD.search(texts))
    if state in STATE_NOT_WATER_TEXT:   # a water named only to deny it, the plant's own ponds (module docstring, Arizona)
        texts = STATE_NOT_WATER_TEXT[state].sub(" ", texts)
    if state == "AZ" and "BYP" in types:   # a bypass's pond or lagoon is the plant's (module docstring, Arizona)
        texts = AZ_BYPASS_POND.sub(" ", texts)
    m = WATER_WORDS.search(texts)
    if m:
        return True, f"text names a water ({m.group(0).lower()})"
    found = STATE_WATER_TEXT[state](texts) if state in STATE_WATER_TEXT else None
    if found:
        return True, f"text names a water ({' '.join(found.split()).lower()})"
    if held:
        return False, "bypass held at the plant (its own pond, lagoon or grounds)"
    if "BYP" in types:
        return True, "bypass (leaves the plant through its permitted outfall)"
    if "CSO" in types and (struct == "CSO" or (struct == "OTH" and OUTFALL_TEXT.search(other))):
        return True, "CSO at a CSO outfall or regulator"
    return False, "no evidence the discharge reached a water"


# --------------------------------------------------------------------------- records

def naive(ts: str | None) -> str | None:
    ts = (ts or "").strip()
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).isoformat()
    except ValueError:
        return None


def event_tz(state: str, lat=None, lon=None) -> str | None:
    """The zone an event's naive times are read in: the state's (STATE_TZ), or STATE_TZ_WEST's when the event's own
    point lies in that part of the state (the Aleutian Islands west of 169 deg 30 min W, 49 CFR 71.12); None for a
    state that stays naive."""
    west = STATE_TZ_WEST.get(state)
    if west and lat is not None and lon is not None and any(
            x0 <= lon <= x1 and y0 <= lat <= y1 for x0, x1, y0, y1 in west[0]):
        return west[1]
    return STATE_TZ.get(state)


def split_water(w: str, state: str) -> list[str]:
    """A receiving-water text as the waters it names (STATE_WATER_SPLIT; a text it does not fit is one water)."""
    pat = STATE_WATER_SPLIT.get(state)
    m = pat.match(w) if pat else None
    return [m.group(1).strip(), m.group(2).strip()] if m else [w]


def zoned(ts: str | None, state: str, tz: str | None = None) -> str | None:
    """A naive time of a STATE_TZ state with its zone's offset ('2026-07-04T19:26:00-05:00'); a date or a time of
    another state as it is. A fall-back hour that happens twice is read as the first (fold 0). tz, when given, is the
    event's own zone (point_zone) in place of the state's."""
    tz = tz or STATE_TZ.get(state)
    if not ts or not tz or "T" not in ts:
        return ts
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is not None:
        return ts
    from zoneinfo import ZoneInfo
    return dt.replace(tzinfo=ZoneInfo(tz)).isoformat()


def tz_note(state: str, permit: str = "", tz: str | None = None, basis: str | None = None) -> str:
    if permit[:2] in PERMIT_TZ:
        return (f"ECHO gives event times without a timezone; read as {PERMIT_TZ[permit[:2]]}, the Navajo Nation's clock "
                "(it keeps daylight saving time, unlike the rest of Arizona; tz database link Navajo -> America/Denver)")
    if basis:   # a state of POINT_ZONE_FILES: the zone of the event's own point
        return (f"ECHO gives event times without a timezone; read as {tz}, {basis} (a fall-back hour that happens "
                "twice is read as the first)")
    tz = STATE_TZ.get(state)
    return (f"ECHO gives event times without a timezone; read as {tz}, the permit's state's zone (a fall-back hour "
            "that happens twice is read as the first)") if tz else TZ_NOTE


_ZONE_SHAPES: dict[str, dict] = {}


def zone_shapes(state: str) -> dict:
    """The reference file of POINT_ZONE_FILES[state], its outlines as shapely shapes (read once)."""
    if state not in _ZONE_SHAPES:
        from shapely.geometry import shape
        doc = read_json(DATA_DIR / "reference" / POINT_ZONE_FILES[state], None)
        if not doc or not doc.get("counties"):
            raise RuntimeError(f"time-zone counties for {state} missing: data/reference/{POINT_ZONE_FILES[state]}")
        _ZONE_SHAPES[state] = {
            "doc": doc,
            "zone": [(c["county"], shape(c["geometry"])) for c in doc["counties"]],
            "split": [(c["county"], c.get("central_label") or "Central part", shape(c["geometry"]),
                       shape(c["central_part"]) if c.get("central_part") else None,
                       shape(c["mountain_part"]) if c.get("mountain_part") else None)
                      for c in doc.get("split_counties", [])]}
    return _ZONE_SHAPES[state]


def point_zone(state: str, lat, lon) -> tuple[str | None, str | None]:
    """(zone, basis) for an event of a POINT_ZONE_FILES state: the reference file's zone when the event's own point
    lies in one of its counties (or the Mountain part of a split county), else the state's STATE_TZ zone; (None, None)
    for any other state. The basis says which county decided it, or that no point was given; for a split county it
    names the part by the file's central_label ("Fort Pierre corner"; "Central part" when the file gives none)."""
    if state in STATE_TZ_WEST:   # Alaska: the Aleutian Islands west of 169 deg 30 min W (module docstring, Alaska)
        tz = event_tz(state, lat, lon)
        return tz, ("the zone of the event's own point (the Aleutian Islands west of 169 deg 30 min W, 49 CFR 71.12)"
                    if tz != STATE_TZ.get(state) else None)
    if state not in POINT_ZONE_FILES:
        return None, None
    z = zone_shapes(state)
    doc, cite = z["doc"], z["doc"]["law"]["cite"]
    if lat is None or lon is None:
        return STATE_TZ[state], f"no point given: the zone of the state's eastern counties ({cite})"
    from shapely.geometry import Point
    pt = Point(lon, lat)
    for county, g in z["zone"]:
        if g.covers(pt):
            return doc["zone"], f"the zone of {county}, where the event's point lies ({cite})"
    for county, note, g, central, mountain in z["split"]:
        if not g.covers(pt):
            continue
        if mountain is not None and mountain.covers(pt):
            return doc["zone"], (f"the zone of the part of {county} west of the boundary, where the event's point lies; "
                                 f"the county is split ({cite}; parts from the U.S. DOT time-zone layer)")
        if central is not None and central.covers(pt):
            return STATE_TZ[state], (f"the zone of the {note} of {county}, where the event's point lies; "
                                     f"the county is split ({cite}; parts from the U.S. DOT time-zone layer)")
        return STATE_TZ[state], (f"{county} is split by the boundary ({cite}) and the point lies on neither part of it "
                                 "in the U.S. DOT time-zone layer: read as Central")
    n = len(z["zone"])
    words = {15: "fifteen", 18: "eighteen"}.get(n, str(n))
    split = " and ".join(c for c, *_ in z["split"])
    return STATE_TZ[state], (f"the event's point lies outside the {words} Mountain-time counties"
                             + (f" and {split}" if split else "") + f" ({cite})")


PLANNED_LABEL = "reporting requirement 'Anticipated bypass notice', or the anticipated-bypass text filled"


def planned_notice(ev: dict) -> bool:
    """The report is an anticipated (planned) bypass notice: its reporting requirement says so (code 4, 'Anticipated
    bypass notice') or it carries the anticipated-bypass text. Keyed on the report type, never on the state."""
    return (str(ev.get("sewer_overflow_bypass_reporting_requirement_code") or "").strip() == "4"
            or (ev.get("sewer_overflow_reporting_requirement_desc") or "").strip().lower() == "anticipated bypass notice"
            or bool((ev.get("anticipated_bypass_text") or "").strip()))


def end_ahead(end: str, now: str) -> bool:
    """The end lies after now (a date-only end counts to the end of its day; a naive time is compared as written)."""
    try:
        e = datetime.fromisoformat(end)
        n = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return False
    if "T" not in end:
        e = e.replace(hour=23, minute=59, second=59)
    if e.tzinfo is None:
        n = n.replace(tzinfo=None)
    return e > n


def scrub_free_text(d: dict, keys) -> dict:
    """The free-text values of d under keys through the Michigan list's scrub (owners' names, house numbers, emails,
    phones, staff names); d changed in place and returned."""
    from ingest.mi_egle_mienviro import free_text
    for k in keys:
        if isinstance(d.get(k), str) and d[k].strip():
            d[k] = free_text(address_typos(d[k]))
    return d


def address_typos(v: str) -> str:
    """House numbers the scrub would not see as numbers: a letter o typed for a zero ('near 45o1 24th St') and a range
    of numbers ('611-615 Brookside backup', read as its first number)."""
    v = re.sub(r"(?<=\d)[oO]+(?=\d|\b)", lambda m: "0" * len(m.group(0)), v)
    return re.sub(r"(?<![\d/.-])(\d{3,6})-\d{1,6}(?=\s+[A-Za-z])", r"\1", v)


def build(tables: dict, info: dict) -> tuple[list[dict], list[dict], Counter]:
    types, rws, imps = by_event(tables.get("types")), by_event(tables.get("waters")), by_event(tables.get("impacts"))
    causes, acts, treat = by_event(tables.get("causes")), by_event(tables.get("actions")), by_event(tables.get("treatment"))
    systems = {(s["permit_identifier"], s["collection_system_identifier"]): s for s in tables.get("systems", [])}
    disc = discharger_index()
    W = Waters()
    kept, dropped, why = [], [], Counter()
    run_now = info.get("now") or now_iso()
    all_points = report_points(tables["events"])
    plant_pts = plant_points({p for p, _, _ in all_points})
    for ev in tables["events"]:
        permit = ev["permit_identifier"]
        state = permit[:2]
        sign_note = None
        if permit[:2] in SIGN_REPAIR_PREFIXES:   # a longitude without its minus sign (module docstring, New Mexico)
            ev, sign_note = repair_sign(ev)
        point_state = None
        if state in POINT_PLACED_PREFIXES:   # Navajo Nation permits: the state from the event's point
            state, point_basis = navajo_point_place(ev.get("latitude_measure"), ev.get("longitude_measure"))
            point_state = state
        if state not in STATES:
            continue
        k = ev["sewer_overflow_bypass_event_key"]
        t_rows = sorted(types.get(k, []), key=lambda r: int(r.get("sewer_overflow_bypass_type_code_sequence") or 0))
        t_codes = [r["sewer_overflow_bypass_type_code"] for r in t_rows]
        w_names = [r["name_receiving_water"] for r in rws.get(k, [])]
        i_rows = imps.get(k, [])
        ok, reason = reached_water(ev, t_codes, w_names, i_rows, state)
        why[(state, "kept" if ok else "dropped", reason)] += 1
        srid = f"{permit}:{ev['program_report_form_set_id']}:{ev['sewer_overflow_bypass_event_id_ext'] or '0'}"
        if state in FREE_TEXT_STATES:
            ev = scrub_free_text(dict(ev), FREE_TEXT_FIELDS)
            for rows_ in (i_rows, causes.get(k, []), acts.get(k, [])):
                for x in rows_:
                    scrub_free_text(x, [c for c in x if c.endswith("_other_text")])
        if not ok:
            dropped.append({"source_record_id": srid, "permit": permit, "reason": reason,
                            "type": t_codes, "structure": ev.get("sewer_overflow_structure_type_desc"),
                            "impacts": [i["sewer_overflow_bypass_impact_desc"] for i in i_rows],
                            "receiving_water": w_names, "start": ev.get("sewer_overflow_bypass_start_datetime"),
                            "end": ev.get("sewer_overflow_bypass_end_datetime") or None,
                            "received": ev.get("program_report_received_date") or None,
                            "description": ev.get("sewer_overflow_bypass_description_text")})
            if point_state:   # a Navajo Nation report: the state it was placed in (module docstring, New Mexico)
                dropped[-1]["state"] = point_state
            continue

        etype = TYPE_MAP.get(t_codes[0], "unknown") if t_codes else "unknown"
        perr = None if t_codes else "no type row for this event"
        start, end = naive(ev["sewer_overflow_bypass_start_datetime"]), naive(ev["sewer_overflow_bypass_end_datetime"])
        precision = "minute"
        extreme = ev.get("program_report_npdes_data_group_number_code") == "G9B"
        if extreme and not start:
            start, end, precision = (ev.get("program_report_start_date") or None), (ev.get("program_report_end_date") or None), "day"
        if not start:
            perr = (perr + "; " if perr else "") + "no start time"
            precision = None
        vol = ev.get("sewer_overflow_bypass_discharge_volume_gallons")
        try:
            vol_gal = int(round(float(vol))) if vol not in (None, "") else None
        except ValueError:
            vol_gal = None
        qm = ev.get("discharge_quantification_method_desc") or ""
        flag = "measured" if qm in MEASURED else "estimated" if qm in ESTIMATED else "unknown"
        try:
            lat, lon = float(ev["latitude_measure"]), float(ev["longitude_measure"])
            if lat == 0 and lon == 0:
                lat = lon = None
        except (TypeError, ValueError):
            lat = lon = None
        outfall = (ev.get("permitted_feature_identifier") or "").strip() or None
        ne_notes = {}
        if state in CSO_BY_STRUCTURE_STATES and etype == "cso":
            etype, outfall, ne_notes = cso_by_structure(ev, outfall)
        slugs, how, coord_src = [], "none", "source" if lat is not None else None
        reg = W.outfalls.get((permit, outfall.zfill(3))) if outfall and etype == "cso" else None
        if reg and reg.get("water_slug"):
            slugs, how = [reg["water_slug"]], "outfall_registry"
        real_w = [w.strip() for w in named(w_names, state) if w.strip() and not no_water(w, state)]
        if state in UNKNOWN_WATER_STATES and any(UNKNOWN_WATER.match(w) for w in real_w):
            ne_notes["receiving_water_note"] = ("the report gives the receiving water as 'Unknown': kept (the report "
                                                "says it reached one), no water named")
            real_w = [w for w in real_w if not UNKNOWN_WATER.match(w)]
        w_aliases = {}
        az_wbid = {}
        if state == "AZ":   # ADEQ's WBIDs -> ADEQ's names; what was filed stays in raw.receiving_waters
            w_aliases = {w: normalise_az_water(w) for w in w_names if w.strip() and not no_water(w, state)
                         and normalise_az_water(w) != w}
            real_w = list(dict.fromkeys(n for n in (normalise_az_water(w) for w in real_w) if n))
            az_wbid = {m_.group(1): az_wbids()[m_.group(1)] for m_ in (AZ_WBID_RE.match(w) for w in w_names)
                       if m_ and m_.group(1) in az_wbids()}
        if state == "DC":   # free text -> the NHD name; what was typed stays in raw.receiving_waters
            w_aliases = {w: normalise_dc_water(w) for w in w_names if w.strip() and not NO_WATER_TEXT.match(w)
                         and normalise_dc_water(w) != w}
            real_w = list(dict.fromkeys(normalise_dc_water(w) for w in real_w))
        elif state in STATE_WATER_ALIASES:   # a permit's shorthand name -> the NHD name (module docstring, Mississippi)
            def _alias(w: str, tab=STATE_WATER_ALIASES[state]) -> str:
                hit = tab.get((permit, _alias_key(w)))
                return hit[0] if hit and alias_reaches(hit[2], lat, lon) else w.strip()
            w_aliases = {w: _alias(w) for w in w_names if w.strip() and not no_water(w, state) and _alias(w) != w.strip()}
            real_w = list(dict.fromkeys(_alias(w) for w in real_w))
        if state in STATE_WATER_SPLIT:   # 'X which flowed to Y' -> X; Y (what was typed stays in raw.receiving_waters)
            w_aliases = {**w_aliases, **{w: "; ".join(split_water(w.strip(), state)) for w in w_names
                         if w.strip() and not no_water(w, state) and len(split_water(w.strip(), state)) > 1}}
            real_w = list(dict.fromkeys(x for w in real_w for x in split_water(w, state)))
        dc_state, dc_basis = dc_row_state(lat, lon) if state == "DC" else (None, None)
        if not slugs and real_w:
            for w in real_w:
                for s in W.by_text(w, state, lat, lon):
                    if s not in slugs:
                        slugs.append(s)
            how = "name" if slugs else "none"
        if lat is None and reg and reg.get("lat") is not None:
            lat, lon, coord_src = reg["lat"], reg["lon"], "outfall_layer"
        ev_tz, tz_basis = point_zone(state, lat, lon)
        ev_tz = PERMIT_TZ.get(permit[:2]) or ev_tz   # the Navajo Nation's clock (module docstring, Arizona)
        start, end = zoned(start, state, ev_tz), zoned(end, state, ev_tz)
        sysrow = systems.get((permit, ev.get("collection_system_identifier") or ""), {})
        d = disc.get(permit, {})
        dname = d.get("name") or (reg or {}).get("permittee") or sysrow.get("collection_system_name") or None
        raw = {k2: v for k2, v in ev.items() if v not in ("", None)}
        raw.update({
            "types": [r["sewer_overflow_bypass_type_desc"] for r in t_rows],
            "receiving_waters": w_names,
            "impacts": [{"code": i["sewer_overflow_bypass_impact_code"], "desc": i["sewer_overflow_bypass_impact_desc"],
                         "other": i.get("sewer_overflow_bypass_impact_other_text") or None} for i in i_rows],
            "causes": [{"code": c["sewer_overflow_bypass_cause_code"], "desc": c["sewer_overflow_bypass_cause_desc"],
                        "other": c.get("sewer_overflow_bypass_cause_other_text") or None} for c in causes.get(k, [])],
            "corrective_actions": [{"code": a["sewer_overflow_bypass_corrective_action_code"],
                                    "desc": a["sewer_overflow_bypass_corrective_action_desc"],
                                    "other": a.get("sewer_overflow_bypass_corrective_action_other_text") or None}
                                   for a in acts.get(k, [])],
            "treatment": [{"code": t.get("sewer_overflow_treatment_code") or None,
                           "desc": t.get("sewer_overflow_treatment_desc") or None,
                           "bypassed_equipment": t.get("bypass_treatment_plant_equipment_desc") or None}
                          for t in treat.get(k, [])],
            "collection_system_name": sysrow.get("collection_system_name"),
            "percent_collection_system_css": sysrow.get("percent_collection_system_css"),
            "reached_water_rule": reason, "timezone_note": tz_note(state, permit, ev_tz, tz_basis), "report_version": ev.get("program_report_form_id"),
        })
        raw.update(ne_notes)
        if w_aliases:
            raw["receiving_water_aliases"] = w_aliases
        if az_wbid:
            raw["receiving_water_wbids"] = az_wbid
            raw["receiving_water_wbid_source"] = ("ADEQ waterbody identifiers (WBID layers on ArcGIS Online, "
                                                  "data/reference/az-adeq-wbids.json)")
        if point_state:   # a Navajo Nation permit: the state from the point
            raw["state"], raw["state_basis"] = point_state, point_basis
        if state in LAGOON_NOTE_STATES and real_w and LAGOON_TEXT.search(ev.get("sewer_overflow_bypass_description_text") or ""):
            raw["kept_note"] = ("the description says the flow went to the plant's lagoon; shown on "
                                + "; ".join(real_w) + " because the report names it as the receiving water")
        if sign_note:   # module docstring, New Mexico
            raw["reported_longitude"], raw["coord_note"] = str(ev["longitude_measure"])[1:], sign_note
        if dc_state:   # placement state differs from the permit's; the operator stays DC Water
            raw["state"], raw["state_basis"] = dc_state, dc_basis
        if extreme:
            raw["extreme_event_note"] = "G9B extreme-event report: spills too numerous to list; times are the report period"
        status = "ended" if end else "unknown"
        if end and planned_notice(ev) and end_ahead(end, run_now):
            status = "ongoing"     # the operator's planned end, still ahead (module docstring, Planned bypasses)
            raw["end_is_planned"] = True
            raw["planned_end_note"] = (f"the operator's planned end of an anticipated bypass ({PLANNED_LABEL}); the "
                                       "bypass runs to it unless a later report changes it")
        kept.append(event(
            source_id=SOURCE_ID, source_record_id=srid, event_type=etype,
            status=status,
            discharger_id=d.get("id"), discharger_name=dname, npdes_permit=permit,
            outfall_id=outfall if etype in ("cso", "bypass") else None,
            outfall_name=(reg or {}).get("outfall_name") or None,   # the description text stays in raw
            waterbody_text="; ".join(real_w) or None, water_slugs=slugs, water_match=how,
            lat=lat, lon=lon, coord_source=coord_src,
            started_at=start, ended_at=end, time_precision=precision,
            reported_at=ev.get("program_report_received_date") or None,
            published_at=info.get("extract_date"), source_updated_at=info.get("last_modified"),
            material=MATERIAL.get(etype), volume_gal=vol_gal,
            volume_text=(f"{vol_gal:,} gallons" + (f" ({qm})" if qm else "")) if vol_gal is not None else None,
            estimate_flag=flag, authority=AUTHORITY,
            source_url=f"https://echo.epa.gov/detailed-facility-report?fid={permit}&sys=ICP",
            raw=raw, parse_error=perr,
        ))
    repeated_points(kept, all_points, plant_pts)
    kept.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    return kept, dropped, why


def report_points(events: list[dict]) -> Counter:
    """For REPEATED_POINT_ALL_REPORTS (by permit prefix): (permit, lat, lon) -> the number of the permit's reports, kept
    or dropped, that give the point. (The descriptions are not compared: an Arizona description such as 'Manhole ID :
    112945' carries the report's own form id, not an asset's, so every description differs.)"""
    out: Counter = Counter()
    for ev in events:
        p = ev.get("permit_identifier") or ""
        if p[:2] not in REPEATED_POINT_ALL_REPORTS:
            continue
        try:
            lat, lon = float(ev["latitude_measure"]), float(ev["longitude_measure"])
        except (TypeError, ValueError, KeyError):
            continue
        out[(p, lat, lon)] += 1
    return out


def plant_points(permits: set[str]) -> dict[str, list[tuple[float, float]]]:
    """permit -> the points EPA's plant list gives it (data/outfalls-plants-us.json), for the permits asked."""
    if not permits or not PLANTS_FILE.exists():
        return {}
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in (read_json(PLANTS_FILE, {}) or {}).get("outfalls", []):
        p = str(r.get("npdes_permit") or "").upper()
        if p in permits and r.get("lat") is not None and r.get("lon") is not None:
            out[p].append((float(r["lat"]), float(r["lon"])))
    return out


def metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    from math import asin, cos, radians, sin, sqrt
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * asin(sqrt(h))


def repeated_points(kept: list[dict], all_points: Counter | None = None,
                    plants: dict[str, list[tuple[float, float]]] | None = None) -> int:
    """For REPEATED_POINT_STATES: a point REPEATED_POINT_MIN or more kept events of one permit share is the permit's
    location, not the spill's; it is moved to raw.reported_point (bypasses keep it). For REPEATED_POINT_ALL_REPORTS the
    count is all_points' (every report of the permit) against the prefix's own minimum, and the point must also lie
    within REPEATED_POINT_PLANT_M of a point of the permit in EPA's plant list (plants); a shared point farther away,
    or of a permit the plant list has no point for, stays, with raw.point_note. Returns the events changed."""
    shared = Counter((r["npdes_permit"], r["lat"], r["lon"]) for r in kept
                     if r["lat"] is not None and r["npdes_permit"][:2] in REPEATED_POINT_STATES
                     and r["npdes_permit"][:2] not in REPEATED_POINT_ALL_REPORTS)
    shared.update({k: n for k, n in (all_points or {}).items()})
    n = 0
    for r in kept:
        k = (r["npdes_permit"], r["lat"], r["lon"])
        prefix = r["npdes_permit"][:2]
        least = REPEATED_POINT_MIN_BY_STATE.get(prefix, REPEATED_POINT_MIN)
        if r["lat"] is None or shared.get(k, 0) < least or r["event_type"] == "bypass":
            continue
        if prefix in REPEATED_POINT_ALL_REPORTS:
            near = min((metres((r["lat"], r["lon"]), q) for q in (plants or {}).get(r["npdes_permit"], [])),
                       default=None)
            if near is None or near > REPEATED_POINT_PLANT_M:
                r["raw"]["point_note"] = (f"the same point is given for {shared[k]} reports of this permit; "
                                          + ("EPA's plant list gives no point for the permit"
                                             if near is None else f"it lies {near / 1000:.1f} km from the plant's point")
                                          + ", so it is kept as the report gives it")
                continue
            r["raw"]["reported_point"] = [r["lat"], r["lon"]]
            r["raw"]["point_note"] = (f"the same point is given for {shared[k]} reports of this permit and lies "
                                      f"{near:.0f} m from the plant's point in EPA's plant list: taken as the permit's "
                                      "location, not the spill's")
            r["lat"] = r["lon"] = r["coord_source"] = None
            n += 1
            continue
        r["raw"]["reported_point"] = [r["lat"], r["lon"]]
        r["raw"]["point_note"] = (f"the same point is given for {shared[k]} reports of this permit: taken as the "
                                  "permit's location, not the spill's")
        r["lat"] = r["lon"] = r["coord_source"] = None
        n += 1
    return n


def write_failed(records: list[dict], error: str, meta: dict) -> Path:
    """ok=False with the error. The previous records stay (common.write_events); only on a first run
    with nothing to keep are the research-copy records written, still marked ok=False."""
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = read_json(path, {}) or {}
    if prev.get("records") or not records:
        return write_events(SOURCE_ID, [], ok=False, error=error, meta=meta)
    write_json(path, {"source_id": SOURCE_ID, "fetched_at": now_iso(), "ok": False, "error": error,
                      "last_ok_at": prev.get("last_ok_at"), "meta": meta, "count": len(records), "records": records})
    return path


def read_zip(path: Path) -> tuple[dict[str, list[dict]], dict]:
    """Tables from a saved copy of either ZIP (--file: tests and replays; nothing fetched or saved). An all-versions
    ZIP is read for the current version of each report (current_from_all_versions)."""
    zf = zipfile.ZipFile(path)
    if is_all_versions(zf):
        return current_from_all_versions(_zip_tables(zf, ALL_TABLES)), {
            "url": ALL_URL, "via": f"file {Path(path).name} (all-versions ZIP, current version of each report)",
            "last_modified": None, "raw_saved": None, "extract_date": _entry_date(zf, ALL_TABLES["event"])}
    names = {Path(n).name for n in zf.namelist()}
    if TABLES["events"] not in names:
        raise RuntimeError(f"{path}: no {TABLES['events']} in the ZIP")
    info = {"url": URL, "via": f"file {Path(path).name}", "last_modified": None, "raw_saved": None,
            "extract_date": _entry_date(zf, TABLES["events"])}
    return _zip_tables(zf, TABLES), info


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = Path(argv[argv.index("--file") + 1]) if "--file" in argv else None
    try:
        tables, info = read_zip(path) if path else fetch()
    except RuntimeError as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    errors = [info["error"]] if info.get("error") else []
    missing = [TABLES[k] for k in TABLES if k not in tables]
    if missing:
        errors.append("tables missing from the extract: " + ", ".join(missing))
    kept, dropped, why = build(tables, info)
    meta = {"registry_ids": ["fed-echo-sewer-overflow-bypass-events"], "states": sorted(STATES),
            "extract_date": info.get("extract_date"), "last_modified": info.get("last_modified"),
            "via": info.get("via"), "url": info.get("url"), "raw_saved": info.get("raw_saved"),
            **({"note": info["note"]} if info.get("note") else {}),
            "kept": len(kept), "dropped": len(dropped),
            "by_rule": [{"state": s, "outcome": o, "reason": r, "count": n} for (s, o, r), n in sorted(why.items())],
            "cadence": "daily (ECHO refresh ~07:10 ET); event-to-receipt lag days to weeks", "errors": errors}
    if errors:
        path = write_failed(kept, "; ".join(errors), meta)
        print(f"{SOURCE_ID}: run not ok ({'; '.join(errors)}) -> {path}", file=sys.stderr)
        return 1
    write_json(BUILD_DIR / "echo-sewer-overflow-dropped.json",
               {"source_id": SOURCE_ID, "fetched_at": now_iso(), "rule": "see ingest/echo_sewer_overflow_events.py docstring",
                "count": len(dropped), "dropped": dropped})
    path = write_events(SOURCE_ID, kept, meta=meta)
    print(f"{SOURCE_ID}: {len(kept)} kept, {len(dropped)} dropped ({info.get('via')}, extract {info.get('extract_date')}) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
