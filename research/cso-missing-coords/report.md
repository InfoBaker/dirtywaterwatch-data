# Open combined sewer outfalls with no coordinates: sources and corrections

Research of 2026-11-15 (15:08Z to 18:55Z, with a pause for the usage limit; the research agent's notes for MI, NE and TN are in `notes-mi-ne-tn.md`). Nothing in `data/outfalls-*.json` or `data/waters-*.json` is changed by this
branch; `corrections.json` holds the cited points, and the last sections say how to apply them and what tests prove it.

## Summary

| State | Rows | Cited point found | No point (reason) |
|---|---|---|---|
| CT | 1 | 1 (CT DEEP's own CSO location layer) | 0 |
| MA | 3 | 0 | 3: not outfalls; EPA reporting numbers for collection-system co-permittees |
| MD | 16 | 0 | 16: no per-outfall source online; MDE's permit outfall tables needed |
| MI | 4 | 0 | 4: permits terminated decades ago; no source places them |
| NE | 1 | 0 | 1: described (64th and Dupont); the state fact sheet was unreachable |
| TN | 1 | 0 | 1: permit gives Commerce Street, river mile 125.9, no coordinates |
| **Total** | **26** | **1** | **25** |

Needs the owner: (1) a records request to MDE for three western Maryland permits' outfall tables (the only way found to
place 16 rows); (2) whether to reclassify the three Massachusetts co-permittee rows as kind "other" (they are not
outfalls, and Williamstown and Lunenburg have no combined sewers in their parent permits); (3) the Nebraska fact sheet for NE0133680 from NDEE (ecmp.nebraska.gov was unreachable here), and TDEC or Clarksville for outfall 004's coordinates; (4) the terminated-permit question in the follow-ups.

## The list (re-derived 2026-11-15 15:15Z on origin/main 721d13f)

`common.load_outfall_registry`, rows with `outfall_kind` cso, `outfall_status` not CLS, `rain_caution` not false, state
in `rainfall.radar_states()` (the 33 live jurisdictions), lat or lon null: 26 rows, the same 26 as the brief.

| Permit | Operator (EPA name) | File | Outfalls | Read today at |
|---|---|---|---|---|
| CT0100056 | Bridgeport Westside WPCA | new-england | 145 | the permit's 25 other outfall points |
| MAC010510 | Williamstown sewer collection system | new-england | 001 | nothing (no point, no plant row) |
| MAC010617 | Lunenburg sewer collection system | new-england | 001 | nothing |
| MAC010986 | Westminster DPW | new-england | 001 | nothing |
| MD0021598 | John J. DiFonzo Water Reclamation Facility, Cumberland | mid-atlantic | 002 003 005 007 008 010 011 012 015 017 019 | the plant (outfalls-plants-us.json 001, 39.6245, -78.754001) |
| MD0067407 | Allegany County combined sewer | mid-atlantic | 002 003 | its outfall 001 (Wright's Crossing pumping station) |
| MD0067547 | LaVale Sanitary Commission | mid-atlantic | 001 003 006 | its outfall 007 (EPA's point, the facility's) |
| MI0037621 | Oakland Co DPW Farmington/Evergreen CSO | us | 001 002 003 | nothing (no point, no plant row) |
| MI0051497 | City of Westland | us | M23 | nothing |
| NE0133680 | Omaha combined sewer overflows | us | 205R | Omaha's 24 other outfall points |
| TN0020656 | Clarksville Gas and Water | us | 004 | its outfalls 002 and 006 |

Note on the brief: MD0021598 is Cumberland's plant (EPA: "John J. DiFonzo Water Reclamation Facility", 400 East
Offutt Street, Cumberland; MDE: "Cumberland WWTP", state permit 06DP0567), not Hagerstown's.

The Michigan rows' `no_point_reason` says an overflow there "is read at the operator's plant", but neither permit has a
plant row, so `rainfall.cso_outfalls()` reads nothing for them today.

## Findings per row

### CT0100056 outfall 145 (Bridgeport West Side, Bridgeport Harbor): located, high confidence

- **Point: 41.166149273344594, -73.18194339093611** (the source's own LATITUDE and LONGITUDE fields, as given).
- Source: CT DEEP, "CSO or CSO Group Locations" (ArcGIS service `CSO_and_CSO_Groups`, layer 0, whose description
  reads "Locations of CSO outfalls for use in CSO event reporting"), record OBJECTID 13: FACILITY "Bridgeport West
  Side", CSO_NAME "BRIDGEPORT WEST 145 TIC", OUTFALL_LOCATION "Henry St & St of Atlantic St", RECEIVING_WATER
  "Bridgeport Harbor".
  `https://services1.arcgis.com/FjPcSmEFuDYlIdKC/arcgis/rest/services/CSO_and_CSO_Groups/FeatureServer/0/query?where=OBJECTID%3D13&outFields=*&f=json`,
  read 2026-11-15 15:20:53Z (evidence: `evidence/ct-deep-cso-groups-objectid-13.json`; the layer's geometry is CT State Plane
  feet, wkid 102656; reprojected by the server to 41.1661576, -73.1819446, within 1 m).
- This is the state's list of CSO outfalls for the reports the law requires (CGS 22a-424a); its other Bridgeport
  West Side records match EPA's numbered outfalls (33 HUNT, 38 SEAB, 80 CON, 101 CAP, 196 FAIM ...).
- Corroboration: CT DEEP's CSO reporting archive (`CSO_Reporting_Archive_deepgis`, layer `deepgis.WPLR.CSO_ARCHIVE`)
  has five operator reports for regulator "145 TIC" (2017-10-25, 2021-07-08, 2021-07-09, 2021-09-02); their map
  points lie at 41.16510 to 41.16590, -73.18037 to -73.18139, within about 150 m of the layer's point
  (`evidence/ct-deep-cso-archive-regulator-145.json`; three of the five carry DEEP's Hartford default 41.77177, -72.66488 in
  their LATITUDE/LONGITUDE fields while their geometry is in Bridgeport, so only the geometry is used here).
- EPA's point (41.04481, -73.540018; DMS longitude "- 73 32' 25"" in CT DEEP's copy of ICIS, `NPDES_Outfalls`, data
  pull 2026-01-14) lies in the Fivemile River basin 41.4 km away; the registry already set it aside (coords_problem).
- Caveat: the layer's street text names Atlantic Street where EPA's names Main Street. Number, name code, operator and
  water agree, so it is read as the same outfall. Confidence high.
- Check against the registry's water: the point lies inside the `bridgeport-harbor-ct` record (0 m by
  `ingest.outfall_waters.Matcher(offline=True).dist`, measured 2026-11-15 on origin/main 721d13f), the water EPA's text
  names; Pequonnock River and Cedar Creek are about 2.1 km away.

### MAC010510 001, MAC010617 001, MAC010986 001: not outfalls (no point exists)

- EPA's inventory gives each a single "outfall" 001 whose text is a reporting note, not a place: "COLLECTION SYSTEM
  REPORTS WITH CO-PERMITTEE HOOSAC" (Williamstown), "COLLECTION SYSTEM REPORTS WITH COPERMITTEE LEOMINSTER"
  (Lunenburg), "CO-PERMITTEE CSOs" (Westminster); status TCS, no coordinates, no receiving water
  (`research/federal/raw/cso_inventory/ALL_CSO_DOWNLOADS.csv`, fetched 2026-11-01).
- The permit numbers mirror the parent permits: MAC010510 / MA0100510 (Hoosac Water Quality District), MAC010617 /
  MA0100617 (Leominster), MAC010986 / MA0100986 (Fitchburg Easterly). Hoosac's and Leominster's permits have no
  combined sewer outfalls in the registry or EPA's inventory (only the plant outfall 001).
- Westminster: EPA Region 1's 2023 draft permit MA0100986 (Fitchburg Easterly), page 1, authorises "Combined Sewer
  Overflow (CSO) discharges at 9 locations" to the City of Fitchburg and names the Town of Westminster a co-permittee
  for Parts I.B (unauthorized discharges), I.C (operation and maintenance) and I.D (alternate power) only, with
  MAC010986 as its reporting number. The fact sheet (page 98) says Westminster "owns and operates a sanitary
  wastewater collection system" that discharges to the Fitchburg plant, and that Lunenburg is a co-permittee of
  Leominster's permit MA0100617 on the same terms.
  `https://www.epa.gov/system/files/documents/2023-12/draftma0100986permit2023.pdf`, read 2026-11-15 15:14Z. (The final
  permit, MassDEP's `fitchburg-fitchburg-easterly-wastewater-treatment-plant-and-9-csos-final-permit`, answered HTTP
  403 to a fetch; search excerpts of it keep the same co-permittee parts.) Fitchburg's nine CSOs are in the registry
  under MA0100986 with points.
- Recommendation: no point. Make each row `outfall_kind` "other" with a `kind_note` (the precedent is
  `scripts/ky_outfall_corrections.py`, Kentucky's KYP collection-system rows), so they leave the combined sewer outfall
  counts and this list; as CSO rows they suggest that Williamstown and Lunenburg have combined sewer outfalls, which
  their permits do not show. Owner's call, since it changes what the site counts.

### MD0021598 (Cumberland), 11 outfalls: not located

What was searched (all read 2026-11-15):
- EPA: the inventory has no PF_LAT/PF_LON for any of the 11 (receiving waters as text: Potomac River 002 003 005 007
  015 019, Wills Creek 008 010 011, Evitts Creek 017, "w" 012). ECHO's effluent service
  (`https://echodata.epa.gov/echo/eff_rest_services.get_summary_chart?output=JSON&p_id=MD0021598`) lists only feature 001;
  the detailed facility report service carries no feature coordinates.
- MDE "Permitted Wastewater Discharge Locations"
  (`https://mde.geodata.md.gov/mdedata/rest/services/WSA_WasteWater/Wastewater_Discharge_Locations/MapServer/0`) and MD
  iMAP "Point Source Discharges"
  (`https://mdgeodata.md.gov/imap/rest/services/Environment/MD_PointSourceDischarges/MapServer/1`): one point per
  permit, the plant (39.62519752, -78.75451538; state permit 06DP0567); the iMAP layer warns that many points "do not
  represent exact geographic locations of outfalls".
- MDE Reported Sewer Overflows (`https://opendata.maryland.gov/resource/stgj-u72u.json?npdes_no=MD0021598`, 198 rows):
  CSO reports name up to ten places (Mill Race, Elizabeth Street, Oldtown Road, Bedford Street, N. Mechanic Street,
  Franklin Street, Valley Street, Avirett Street, Walnut Place, WWTP), never an outfall number; a few rows carry a point
  for a single named street (Valley Street 39.6861, -78.7698; Franklin Street 39.6591, -78.7754; Avirett Street 39.6483,
  -78.7681; Oldtown Road 39.6438, -78.7645; Bedford Street 39.6525, -78.7641), others are swapped or missing a sign.
  Ten place names against eleven permitted outfalls, and no source that pairs a name with a number, so none is used.
- National Park Service, environmental assessment for the City of Cumberland Mill Race CSO project
  (`https://parkplanning.nps.gov/showFile.cfm?sfid=442206&projectID=86482`): names the Mill Race, Oldtown Road and
  Elizabeth Street outfalls, gives no numbers or coordinates.
- Web search for the permit, its fact sheet and a long-term control plan with an outfall table: nothing online.

### MD0067407 (Allegany County) 002 Braddock Estates, 003 Grahamtown: not located

- EPA's points (002: +38.791944, -76.719444; 003: +38.758333, -76.701389) are in Prince George's County; EPA's own
  automatic water names for them are "Western Branch Patuxent River" and "Swan Point Creek", 260 km from George's Creek.
  Not used (the registry already set them aside).
- MDE and iMAP layers: one point for the permit, at Wright's Crossing (39.48528, -79.04167; state permit 10DP3144,
  address "Wrights Cross./braddock/grahamtown"), the same as EPA's outfall 001.
- MDE overflow reports (58 rows): one CSO report names Braddock Estates, at 39.3820, -78.5557, the same digits as two
  "Wrights Crossing Pump Station" reports; the reporter used one point for two places, so it places neither. No report
  names Grahamtown.

### MD0067547 (LaVale) 001, 003, 006: not located

- EPA: no points for 001, 003, 006; 007 is at 39.64453, -78.8197, the facility's point in MDE's layers (39.644593,
  -78.8198017, address "Sanitary Commission Service Area", "4 Outfalls", state permit 10DP3164).
- MDE overflow reports (112 rows) name two places: "Old Mt. Savage Road" (also "Former LaVale Pump Station") and
  "12610 Labers Lane" ("Red Hill Outfall"). Their points are mostly degree-minute-second digits typed as decimals
  (39.4011, -78.4734 and 39.3824, -78.5121); a few rows give decimals, swapped into the wrong columns (39.67 / -78.7934;
  39.6397 / -78.8559), consistent with those readings. No source ties either place to outfall 001, 003 or 006, so none
  is used.

### Maryland: what would place these 16 rows

MDE's permits (06DP0567 / MD0021598, 10DP3144 / MD0067407, 10DP3164 / MD0067547) carry each outfall's location; none
is posted online. A request to MDE's Wastewater Permits Program (or a Maryland Public Information Act request) for
those three permits' outfall tables is the next step: an owner item. Until then the operators are read at the points
listed above.

### TN0020656 outfall 004 (Clarksville, Commerce Street): not located; place described, no coordinates

- The state permit names the place but gives no coordinates. TDEC DataViewer, permit TN0020656 ("Clarksville STP and
  Combined Sewer System", issued 2025-01-21, effective 2025-03-01): "limited untreated combined wastewater from Outfall
  004 (Commerce Street)"; receiving stream "Barkley Reservoir (Cumberland River) at miles 125.0, 125.4, 125.9 and 126.2".
  `https://dataviewers.tdec.tn.gov/dataviewers/f?p=2005:34051:::NO:34051:P34051_PERMIT_NUMBER:TN0020656`, read
  2026-11-15 18:43Z.
- The final permit (TDEC document, "Outgoing Final Permit", 21-JAN-2025, 129 pages; from the DataViewer's document list
  for TN0020656, file type Permit) says at page A-9 and in the rationale (page R-6, PDF page 71): "The Commerce Street
  Combined Sewer Overflow (Outfall 004) serves as a relief point for the combined sewer system", discharging "to
  Barkley Reservoir at the Cumberland River mile 125.9 during wet weather only". It gives no latitude or longitude for
  any outfall; its appended overflow table (TDEC event reports, with coordinates) has no Commerce Street row.
  Read 2026-11-15 18:45Z.
- EPA: the inventory and EPA's CSO map layer (`https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Combined_Sewer_Overflows/FeatureServer/0`,
  data edited 2026-11-09) give 004 as "+36", "-87": whole degrees, not a place (002 and 006 have full points).
- A river mile is a published locator, but turning mile 125.9 into a point needs a river-mile layer (US Army Corps of
  Engineers, Nashville District); no source places the outfall itself, so no point is proposed. The operator is read
  today at outfalls 002 (Gallows Hollow) and 006 (McClure Street), about 1 to 2 km away on the same river.

### NE0133680 outfall 205R (Omaha, Saddle Creek retention treatment basin): not located; place described

- EPA's inventory text: "City of Omaha Retention Treatment Basin located at 64th and Dupont."; no point. EPA's CSO map
  layer (above) returns 26 Omaha outfalls and not 205R (read 2026-11-15 by the research agent, notes-mi-ne-tn.md).
- Omaha's CSO annual report to the state (copy on the Nebraska Natural Resources Commission site,
  `https://nrc.nebraska.gov/sites/default/files/doc/wfs/WSF2025AR4116.pdf`, section V.B "64th and Dupont Retention
  Treatment Basin – Outfall 205R", PDF pages 46 to 47; read 2026-11-15 18:47Z): the Saddle Creek High Rate Treatment
  Basin was "operationally complete on December 20, 2023" and discharges treated effluent as CSO 205R; its overflow
  table (PDF page 120) lists "CSO 205 - 64th & Dupont St". No coordinates for 205 or 205R anywhere in the report.
- The NDEE permit (modified, comment period 2025-01-30 to 2025-03-01, `https://dwee.nebraska.gov/node/4730`) and its
  fact sheet are on NDEE's document system (`https://ecmp.nebraska.gov/publicaccess/...`), which did not answer from
  this machine (no connection) and could not be opened in the browser pane. The fact sheet may give the outfall's
  latitude and longitude: worth one fetch from another network.
- The designer's papers place the basin "adjacent to the Little Papillion Creek and S 64th Avenue" (Wade Trim,
  `https://wadetrim.com/wp-content/uploads/omaha-saddle-creek-rtb-weftec-23.pdf`): a description, not a point.

### MI0037621 001, 002, 003 (Oakland County, Evergreen-Farmington CSO) and MI0051497 M23 (Westland): not located; permits terminated

- Both permits are terminated in ICIS (ECHO detailed facility report service: "Terminated"; MI0037621 expired
  1982-03-31, MI0051497 2001-10-01) and neither is in EPA's CSO map layer, which holds active outfalls only. ECHO's points
  are a ZIP-code centroid (MI0037621) and an address geocode of 36601 Ford Road (MI0051497's FRS point), not outfalls;
  the inventory's own facility point for MI0051497 (42.333333, -82.333333) lies in Ontario (research agent's notes,
  read 2026-11-15).
- The Evergreen-Farmington system's current CSO basins have their own permits and points in the registry (Acacia Park
  MI0037427 103, Birmingham MI0025534 101, Bloomfield Village MI0048046 102); Westland's area is served by Wayne
  County's later community CSO permits. No source found ties MI0037621's 001 to 003 or MI0051497's M23 to a successor
  outfall or records them as eliminated (EGLE, the Oakland County Water Resources Commissioner and the Rouge River
  program were searched).
- These rows drive nothing today (no point and no plant row). Whether to keep them as open outfalls belongs with the
  terminated-permit follow-up below.


## How the registry already records a corrected point

1. **In place, with the source's point and EPA's kept** (`scripts/wa_gate_ties.py` `move()`): `lat`/`lon` become the
   source's, `coords_from` names the kind of source ("permit"), EPA's point is kept in `epa_lat`/`epa_lon`, and
   `coords_note` cites the document and section. The gate-tie scripts (`scripts/ne_gate_ties.py`,
   `scripts/ak_gate_ties.py`) carry their table in code and have a `--check` mode that changes nothing and exits 1
   when a row is not as the table says.
2. **A state file that outranks the national one** (`data/outfalls-pr.json` from `scripts/add_pr_cso_outfalls.py`,
   `data/outfalls-la.json`, `data/outfalls-ky.json`): a copy of EPA's row with the corrected fields, `supersedes`
   naming EPA's row and (PR) `epa_row` keeping EPA's values. `common.load_outfall_registry` keeps the row of the lower
   `outfall_file_rank`: a regional or state file (0) over `outfalls-us.json` (1) over a plants file (2).
3. **A point set aside** (`ingest.outfall_waters`, `scripts/ne_gate_ties.py` POINT_NOT_USED): `lat`/`lon` null, EPA's
   point in `echo_lat`/`echo_lon`, `coords_problem` saying why. A later `ingest.outfall_waters` run *restores*
   `echo_lat`/`echo_lon` into `lat`/`lon` on any row that still has `coords_problem` (outfall_waters.py, "a row this pass
   matched before: start again from ECHO's own values") and re-checks it.

## Proposed mechanism

Use (1), in place, for every row, through one script, `scripts/cso_coord_corrections.py [--check]`, that reads
`research/cso-missing-coords/corrections.json` (or a copy under `data/`), because:
- CT0100056 and the Maryland rows live in regional files (rank 0). A new state file would tie with them on rank, and
  the loader would then keep whichever file name sorts first: a correction that works by alphabetical accident.
- One row per outfall stays one row; no `supersedes` pair to keep in step when EPA's inventory is re-read.

Per corrected row the script writes: `lat`, `lon` (the source's values, source precision: registry outfalls are not
rounded); `coords_from` from the existing vocabulary ("state outfall layer" for CT DEEP's layer; "permit" for a permit
or fact sheet; "operator map layer" for an operator's map); `coords_note` naming the source, record and date read;
`coords_source` {url, record, read_at}; `epa_lat`/`epa_lon` from `echo_lat`/`echo_lon` when EPA had a point; and it
removes `coords_problem`, `echo_lat`/`echo_lon` and `no_point_reason`, so a later ties run cannot put EPA's point
back. It never touches a row whose permit, outfall or EPA text differs from the table (it reports it instead).

Then each corrected row's water is re-tied by its new point (distance, match, reach). `ingest.outfall_waters` with no
option re-ties every row of the two regional files (`FILES`: new-england and mid-atlantic, so the CT row), and
`--state XX` every row of that state in `outfalls-us.json` (the MI, NE and TN rows); both rewrite many rows, so run
them with `--dry-run` first and keep only the corrected rows' changes, or have the script call the per-row matcher
(`match_cso_row`) on the corrected rows alone. For the Massachusetts rows, if the owner agrees, the same script (or
`ky_outfall_corrections.py`'s pattern) sets `outfall_kind` "other" and `kind_note`.

Run it only after the water-batch chain has finished with `data/outfalls-*.json` and `data/waters-*.json`, on a
branch from the then current main, and with the coordinator's go-ahead.

## Test plan

New `pipeline/tests/test_cso_coord_corrections.py`:
1. Every entry in `corrections.json` has `npdes_permit`, `outfall`, `lat`, `lon`, `coords_from`, `source_url`, `read_at`;
   lat/lon are numbers inside the row's state (Census outline, as `provisional_outfalls` checks) and `coords_from` is in
   the registry's vocabulary.
2. After the script, each corrected row in `common.load_outfall_registry()` carries the table's point, no
   `coords_problem`, `echo_lat` or `no_point_reason`, and EPA's old point in `epa_lat`/`epa_lon` where there was one.
3. `rainfall.cso_outfalls()` includes each corrected (permit, outfall) with the new point and the registry source
   (REGISTRY_SOURCE of its file); the count of open CSO rows without a point in radar states drops from 26 by the
   number corrected (and by 3 more if the Massachusetts rows become kind "other"), and no row of the list is closed.
4. Idempotence: running the script twice changes nothing; `--check` exits 0 after a run and 1 on a fixture row
   altered by hand.
5. A ties run cannot undo it: run `ingest.outfall_waters` matching on a corrected row and assert `lat`/`lon` are
   unchanged and the row is tied to the expected water (CT 145: `bridgeport-harbor-ct`) with `distance_m` set.
6. Existing tests to update where a row changes: `pipeline/tests/test_ne_gates.py`
   `test_outfall_205r_keeps_epas_facility_point_aside_and_its_creek_by_the_text` asserts 205R has no point and Omaha
   has 24 points; if 205R is corrected it must assert the new point and 25.

Then the full suite (`cd pipeline && python -m pytest -q`, reading the count line, not the exit code through a pipe),
the map and rain checks of one refresh, and the site's outfall pages for the corrected permits.

## Follow-ups noticed (not part of this task)

- **Terminated permits still read as open outfalls.** The open-row test is per outfall status (not CLS), not per
  permit. In the radar states, 96 open CSO rows with points belong to permits EPA lists as terminated (TRM): Michigan
  52 rows on 18 permits (26 of them at whole-minute placeholder points such as 42.333333, -83.333333: the 1997-2001
  Wayne County community CSO permits MI0051501, MI0051543, MI0051551, MI0051560, MI0051802 ...), Pennsylvania 30 on 7,
  New York 13 on 3, California 1. Some of these outfalls continue under a successor permit (then the row is a
  duplicate), others were eliminated (then the caution is a false alarm at a placeholder point). Worth one pass that
  pairs each terminated permit with its successor or a closure record before deciding; the owner's err-on-safety rule
  argues for keeping a row until a source shows the outfall closed. Counted 2026-11-15 on origin/main 721d13f.
