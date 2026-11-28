# Waters follow-up of 2026-11-28: what was applied, built and left

The batch that finishes the three outfall-water batches of 2026-11-28 (research/registry/outfall-water-fixes-2026-11-28-review.md,
research/registry/untraced-outfall-waters-2026-11-28.csv, research/mi/untraced-outfall-waters-2026-11-28.json). Report
counts are the worklists' counts of 2026-11-28. Rules kept: no water or point is guessed; every hand entry cites a
public address; "cannot tell" is a result; month-precision reports are untouched by this batch.

## 1. Second registry batch (the review's 15 "apply" rows and two crosswalk rows)

Applied through data/outfall-water-corrections.json:

| Permit and outfalls | Was | Now | Distance from the row's point | Live reports |
|---|---|---|---|---|
| ME0102075 005, 007, 012, 015, 016 | casco-bay-me | back-cove-me | 297 m (the permit's shared point) | 531 |
| ME0101435 006 | casco-bay-me | back-cove-me | 644 m (shared point): tie on the stated water, no stretch from the point | 28 |
| PA0021407 006 | monongahela-river-pa | camp-run-pa | 195 m | 0 |
| PA0025984 212, PA0217611 056 | ohio-river-pa | sawmill-run-pa | 231 m | 0 |
| PA0027111 004 | allegheny-river-pa | pucketa-creek-pa | 183 m | 0 |
| PA0027391 004 | allegheny-river-pa | bull-creek-pa | 131 m | 0 |
| NY0027057 020, 023, 034 | erie-canal-albion-ny | eighteenmile-creek-lockport-ny | 210, 184, 143 m | 0 |
| VT0101010 005 | connecticut-river-vt | white-river-vt | 249 m | 0 |

The Portland rows carry EPA's text 'Back Cove'. Maine DEP's outfall layer gives each of the six its own point and the
waterbody BACK COVE, 0 to 2 m from back-cove-me
(https://gis.maine.gov/mapservices/rest/services/dep/MainePollutantDischargeEliminationSystem/MapServer/2, queried by
NEPDES_FAC); the layer's address is on each entry.

data/reference/ma-portal-waterbody-crosswalk.csv: LITTLE MYSTIC CHANNEL (27 reports) now names boston-inner-harbor-ma
(medium), which carries the name as an alias and holds the channel; the Little Mystic Channel has no record of its own.
RESERVED CHANNEL (35 reports) names reserved-channel-ma (medium), the channel's own record, not the harbor around it
(review of 2026-11-28).

Left as the review says (every "do not apply" and "cannot tell" row). One finding for a later decision: the same Maine
DEP layer lists ME0101435 017 and 018 (EPA's text 'Portland Harbor, Back Cove, Ca') as BACK COVE at their own points,
and 024 as 'PORTLAND HARBOR, AT CASCO BAY'; 013 is CLOSED there. That layer could settle those rows (478 reports), which
the review marked "do not apply"; they were not touched. A record reserved-channel-ma (an OSM centre line, 63 to 181 m
from Boston's outfalls 076 to 080) exists, and the crosswalk row names it. The registry's ties of 076, 078, 079 and 080
to boston-inner-harbor-ma are left: they are main's point ties (0 to 7 m, inside the harbor's outline), not a correction
of this batch, and EPA states no Reserved Channel for those outfalls (076 and 078: the HUC label 'Charles River-Frontal
Boston Harbor'; 079 and 080: no text), so nothing ties them to the channel on a stated name.

## 2. Water records that did not exist

Built as hand records in ingest/waters_from_nhd.py (HAND, names_file research/<st>/receiving-waters-followup-2026-11-28.json,
built with `--names <file> --state XX --hand-only`). Only the new records and their target rows were spliced into
data/waters-nhd.json; the run's recuts of seven unrelated records against this machine's outlines (Brazos, Canadian,
Cumberland, Guadalupe, Red and Yellowstone River records) were left out.

| Record | Line | Name | Outfall tie | Reports |
|---|---|---|---|---|
| st-louis-creek-mi | NHD HR flowline 116536231 (reach 04020103000279, 3.4 km to the Trap Rock River), starting 3 m from EPA's point for MI0043982 001 | EPA's permit list (https://www.epa.gov/node/253663) and ECHO; St. Louis Falls on St. Louis Creek (https://www.waterfallsofthekeweenaw.com/st-louis-creek/st-louis-falls) lies 10 m from the flowline | correction, 2 m | 105 |
| spring-creek-oh | NHD HR flowline 123057428 (reach 04110002001790) | NEORSD's CSO alerts map (https://www.neorsd.org/cso-alerts-map-and-status-of-outfalls/), outfalls 059 and 257 | corrections, 0 and 3 m | 21 |
| wolf-creek-garfield-heights-oh | NHD HR reach 04110002000732 (2 flowlines) | NEORSD's map, outfall 249 | correction, 6 m | 8 |
| green-creek-oh | NHD HR flowline 128582007 | NEORSD's map, outfall 256 | correction, 15 m | 2 |
| shaw-brook-oh | NHD HR flowline 128582001 | NEORSD's map, outfall 232 | correction, 49 m | 4 |
| bloody-run-oh | NHD HR reach 05090203000609 (4 flowlines, to Mill Creek), the reach EPA itself indexes outfall 181 to | EPA's CSO inventory, OH0105457 181 (https://echo.epa.gov/detailed-facility-report?fid=110009661302) | correction, 35 m | 20 |
| longfellow-creek-wa | NHD HR reach 17110019019025 (9 flowlines), 86% within 60 m of Seattle Public Utilities' published 'Longfellow - Mainstem' line (Urban Watercourses layer, https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/services/Urban_Watercourses/FeatureServer/0) | Ecology's permit WA0031682 table 2 as SPU's CSO basin layer repeats it; EPA names outfall 169 'LONGFELLOW CREEK' | scripts/wa_gate_ties.py, outfalls 168 to 170 | 1 |

The NEORSD records rest on the operator's naming of the water at its own point and the NHD line that point sits on
(1 to 37 m); GNIS lists none of these names in Cuyahoga County, so the name is the operator's alone. NEORSD's copies of
the outfalls in data/outfalls-us.json (EPA's rows, at the plant's point, no text) take the same water, as 211 and 212
did. Seattle's 169 (the status file's point, 725 m from the creek) and EPA's 170 (a point in Kitsap County) are tied on
the operator's statement with the distance bound to the point (match permit_stated), so no stretch is modeled from
them; the other four copies lie 0 to 20 m from the creek.

St. Louis Creek and Longfellow Creek are kept although Michigan and Washington do not check a report's county: no
other water of either name is known in the state. GNIS lists no St. Louis Creek in Michigan, and the NHD
high-resolution flowlines (whose names are GNIS's) carry no name containing "Louis Creek" in a box around Michigan
(queried 2026-11-28); the NHD high-resolution flowlines' only Longfellow Creeks (GNIS 773659, 786544, 266945) lie in
regions 17010207, 10030101 and 18010206, none in Washington. Each record is the only one of its name in its state, and a
report with a point is still held to the placement guard's distance. The Ohio records are protected by the county
check: Ohio is a county state with a county field, so a name goes only to a record reaching the county of the report's
point or its own county field (tests/test_waters_followup.py: Spring Creek from Medina or Hamilton County and Bloody Run
from Licking or Cuyahoga County are not placed on the new records). An Ohio report with neither a point nor a county
would still take the record of the name.

Left, with what is missing:

- Big Beaver Creek (Warren, MI0024295 004), Holly Drain (Durand, MI0022063 001), Crystal Creek (North Branch,
  MI0053180 001) and Bradshaw Drain (Van Buren Township, MI0056677 001), one report each: left: a statewide name with no
  locality check. Each was built from its GNIS feature on the NHD high-resolution flowlines and then removed: Michigan
  is not a county state, and a report with no point naming the common name elsewhere (Crystal Creek in Oceana County,
  Big Beaver Creek in Chippewa County, Holly Drain in Eaton County, Bradshaw Drain in Sanilac County) would have taken
  the record. Building them needs a locality check for Michigan's no-point reports first.
- Dugway Brook (NEORSD 230, 231; 8 reports): no published line reaches the outfalls. The nearest NHD HR flowline
  (unnamed, reach 04110003001590) is 140 m away; OpenStreetMap names Dugway Brook only on open stretches 3.7 km
  upstream (ways 276663371 to 276663556, read through the maps.mail.ru Overpass mirror); GNIS has none in Ohio.
- Queen Ditch (NJ0108758 026; 24 reports): no line. The nearest NHD HR flowline is an unnamed artificial path 333 m away;
  GNIS has no Queen Ditch in Essex County.
- Little Snake Creek (NY0213934 002; 1 report): the record could be built (GNIS 955695 on the NHD HR), but the report
  names a tributary of it, and the point lies 4.2 km from the creek; tying the report to the creek would be a guess.
- Akron's Ohio Canal (047, 059, 060, 062, 080) and Camp Brook (055) (28 reports): NHD carries only unnamed artificial
  paths 62 to 382 m from the canal outfalls and an unnamed flowline 115 m from 055; GNIS's Ohio Canal (1080438) is the
  historic statewide canal with no line, and Camp Brook is not in GNIS; the one Summit County water layer read (a park
  district's, on ArcGIS Online) carries neither name, and OpenStreetMap's mirror timed out for Akron. The six rows now carry the permit's own coordinates (scripts/outfall_point_corrections.py
  PERMIT; Ohio EPA permit 3PF00000, Part II E.1, https://dam.assets.ohio.gov/image/upload/epa.ohio.gov/Portals/35/permits/doc/3PF00000.pdf)
  and stay untied. Their no_water_reason, rewritten by ingest.outfall_waters, still says the permit's waters "cannot be
  told apart"; the permit does name Ohio Canal or Camp Brook for each, which have no record.
- Call Drain (GM Flint, 3112a-1040; 1 report): GNIS 622463 gives only the drain's mouth point, 11 m from an unnamed NHD
  HR ditch; no published line says which flowlines are the drain.
- Douglas Creek (EPA's second water for MI0043982): GNIS's only Michigan Douglas Creek is in Crawford County; not built.

## 3. Michigan permits with no town on record

EGLE's MiEnviro CSO/SSO List (https://mienviro.michigan.gov/ncore/external/overflow/list, queried by permitNumber)
names the City of Manistee as responsible party for 3112a-0142 (Manistee CM, Manistee County) and Crystal Falls for
GW1810192 (Crystal Falls WWTP, Iron County). Each permit joins its city's row in data/dischargers.json (the owner-key
rule of scripts/add_mi_operators.py). 'Manistee Lake' from 3112a-0142 now resolves to manistee-lake-mi (25 reports).
'Paint River' from GW1810192 (55 reports) still does not resolve: paint-river-mi and paint-river-mastodon-mi both list
Crystal Falls (the duplicate pair the Michigan research describes), and paint-river-mastodon-mi's covers_part_of names
paint-river-iron-river-mi, not paint-river-mi, so the resolver's remainder rule does not set it aside. Settling it needs
the duplicate resolved in the water data, not a town.

## 4. Carried items

- Fall River MA0100382 010 (598 reports, none moved): MassDEP's CSO outfall layer
  (https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services/MassDEP_CSOs_2/FeatureServer/0) gives FAL010, City
  Pier, the receiving water TAUNTON RIVER at EPA's own point. Tied to taunton-river-ma on that statement (560 m, no
  stretch from the point), replacing Narragansett Bay.
- South Portland ME0100633 (no live reports): left. Maine DEP's layer gives 005 CALVERY POND, 006 BARBERRY CREEK (FORE
  RIVER) and 018 PORTLAND HARBOR, not EPA's 'Fore River'; 024 is FORE RIVER at DEP's point, but the two Fore River
  records (fore-river-me 176 m, fore-river-portland-me 182 m) are one water twice, so neither can be chosen.
- Maryland MD0021598 (11 rows) and MD0067547 (001, 003, 006): left. EPA's CSO layer and ICIS still list no points for
  these outfalls (rechecked; ICIS has only LaVale's 007); the permit's outfall table from MDE is what is missing
  (research/cso-missing-coords/mde-pia-request-draft.md).

## Reports placed

Expected to change placement: Portland's Back Cove outfalls 559 (from Casco Bay to Back Cove); Boston's two crosswalk
rows 62 (placed at collection instead of later by alias); St. Louis Creek 105; Cleveland 35 (Spring Creek 21, Wolf
Creek 8, Shaw Brook 4, Green Creek 2); Bloody Run 20; Manistee 25; Longfellow Creek 1; the four Michigan GNIS waters were removed (4 reports stay unplaced).
About 807 reports in all; Fall River's 010 moves none.
