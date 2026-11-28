# Outfall registry: water records audit (2026-11-28)

Inputs: the registry files `data/outfalls-*.json` on data main (37,743 rows), the waters data (`data/waters-*.json`, 26,883
records), the live event index built 2026-11-28T03:42Z (397,759 reports, no fixtures), the pipeline state saved
2026-11-28 (the reach index `data/build/reach-outfalls.json` built 10:42Z, the ingesters' events files, and the placement
notes in `data/build/status.json` built 10:48Z). Counts of reports come from the event index; the reasons come from the
placement notes, which are seven hours newer. Nothing in the registry, crosswalk or alias files was changed: the fixes are
proposed as rows in `outfall-water-audit-2026-11-28-proposed.csv`, and every unplaced outfall is listed in
`outfall-water-audit-2026-11-28-unplaced.csv`.

## Headline

- **Part A, the 4,186 rows matched by geometry alone.** 3,112 are plausibly right (class i), 197 point to a water when the
  stated water has its own record nearby (class ii), 877 cannot be settled from the data (class iii). **No live report at
  these outfalls is without a water** (0 of 10,115). The MA and NY resolvers set aside 1,011 reports at collection (985
  MassDEP, 26 NY DEC); every one is placed later by `build/status.py`, by its own water name. The harm is elsewhere:
  **1,460 live reports at class ii outfalls carry the registry's water, which is probably the wrong one** (1,101 in rows
  marked for review, 359 in rows marked high). The worst case is Portland, Maine: about 1,200 Casco Bay Estuary Partnership
  reports sit on Casco Bay when the permit says Back Cove.
- **2,861 of the 4,186 "geometry" rows are mislabelled, not mismatched.** They have no usable stated water name (no
  ECHO text, or a text such as "NA" or "Unnamed Stream"). The match rests on the outfall's own EPA NHDPlus reach, the NHD
  builder or the permit research. `ingest/outfall_waters.py` (around line 1118) labels any match within 400 m whose
  name it cannot compare to a text as `geometry`.
- **Part B, the 8,564 rows with no water record.** 8,536 are in live states (the other 28 are in GU, VI, MP and AS).
  6,949 are plant outfalls (6,948 open), 1,503 CSO outfalls (1,032 open) and 112 "other". 491 duplicate a row from a more
  specific file, which wins (129 of those have a water there). Live reports at these outfalls: **6,937, of which 1,021 have
  no water** (all at 123 CSO outfalls). A trace on file does not help: 839 of the 1,021 are at outfalls with a traced reach
  (see "Why a trace does not place a report").
- **The 4,590 live reports with a permit and outfall but no water** break down as: 2,110 with a water name that matches
  two or more records (MI only), 1,426 with an outfall the registry lacks, 876 with a registry outfall that has no water, and
  178 where the guard rejected a name match as too far away or the reason is blank. **The Michigan block (3,592) is
  almost entirely a name problem, not a registry gap:** MiEnviro reports have no point and do name a water, but "St. Clair
  River", "Rouge River" and "Manistee Lake" each match two Michigan records, and the discharger's towns do not decide
  between them.

## Part A: the 4,186 rows matched by geometry alone

### Method

For each row the stated water is the receiving-water override, else ECHO's text (`receiving_water_echo`), else MO DNR's
water body. Plant rows also carry the NHDPlus reach name (`reach_gnis_name`) as a second witness. Texts are normalised:
abbreviations expanded (R, RVR, CR, CRK, BR, FK, TRIB, UT, ST to Saint), camel case split, accents dropped. They are
split on "-", "/", "&", ",", "and", "to" and "via", and "unnamed tributary to" is stripped. Two names agree if they share
a distinctive word (kind and direction words do not count), are the same letters without spaces, or are within a 0.85
similarity ratio (to catch typos such as "Ocmuglee" and "Chmaplain"). "Little", "Big" and "Great" must match on both
sides. The stated water's own records (exact name, alias in `data/water-aliases.json`, or a name that agrees) were measured
against EPA's point with their real outlines. Those outlines come from the inline geometry or the openboatlaunch water
files, which were read only, and the record's box was used where neither exists. A record in the row's own state, or
with the exact name, wins a tie (300 m handicap otherwise).

### Classes

| Class | Rows | Open | Live reports | Reports carrying the registry water | Set aside at collection |
|---|---:|---:|---:|---:|---:|
| i0 no usable stated name; match from the EPA reach, NHD builder or permit research | 2,861 | 2,549 | 993 | 891 | 0 |
| i-name stated and matched names agree (variant, typo, one of several waters named) | 239 | 221 | 161 | 161 | 0 |
| i-imp matched water is an impoundment on the stated river (Lake Massasoit type) | 5 | 4 | 383 | 39 | 224 |
| i-emb stated water has no record and reads as a channel, cove or harbor of the matched water within 300 m | 7 | 7 | 31 | 31 | 0 |
| **i total** | **3,112** | | 1,568 | | |
| ii-high stated water's record is no farther from the point than the matched one (+50 m) | 114 | 96 | 916 | 359 | 557 |
| ii-review stated water's record is within 1 km but farther than the matched one | 83 | 70 | 1,708 | 1,101 | 0 |
| **ii total** | **197** | | 2,624 | 1,460 | |
| iii-none no stated name and no reach name | 561 | 449 | 4,682 | 1,928 | 217 |
| iii-far stated water's nearest record is more than 1 km away | 257 | 221 | 1,039 | 1,016 | 1 |
| iii-norec stated water has no record | 38 | 34 | 202 | 202 | 12 |
| iii-gw permit names groundwater, a wetland or land | 21 | 21 | 0 | 0 | 0 |
| **iii total** | **877** | | 6,923 | | |

None of the 10,115 live reports at these outfalls has an empty water list.

iii-far is mostly CSOs on a tributary near its mouth whose permit-wide text names the main stem. Examples: Louisville
outfalls on Beargrass Creek ("Ohio River"), Star City and Fairmont on Deckers Creek and the West Fork ("Monongahela
River"), Elkhart on the Elkhart River ("St Joseph River"). The matched tributary is probably right, and the modeled
reach carries the main stem. ii-review holds the opposite case: a main stem within 1 km of a point whose nearest water is
a tributary. Check before applying.

By state (the top rows; the full set comes from the CSV's state column and the class table above):

| State | i | ii | iii | Total |
|---|---:|---:|---:|---:|
| OH | 1,492 | 1 | 113 | 1,606 |
| WA | 214 | 0 | 185 | 399 |
| MI | 265 | 0 | 2 | 267 |
| WI | 259 | 0 | 8 | 267 |
| NY | 26 | 27 | 163 | 216 |
| IN | 70 | 16 | 107 | 193 |
| LA | 136 | 0 | 3 | 139 |
| PA | 8 | 66 | 46 | 120 |
| SC | 94 | 0 | 2 | 96 |
| WV | 26 | 13 | 40 | 79 |
| MA | 6 | 7 | 48 | 61 |
| KY | 7 | 2 | 49 | 58 |
| ME | 3 | 27 | 14 | 44 |
| RI | 0 | 12 | 7 | 19 |
| CT | 3 | 8 | 0 | 11 |
| other 35 states and PR | 503 | 18 | 90 | 611 |

### Which code sets a geometry-only match aside

- `ingest/ma_massdep.py` `resolve_water` (used by `ma-massdep` and, through `ingest/mail/ma_common.py`, by the Holyoke,
  Somerville and Springfield mail feeds). The crosswalk decides first, and a crosswalk row that says "no slug" stops the
  name step. After that, a registry row matched by geometry alone counts only if a word of the report's text appears in
  its water name.
- `ingest/ny_sprtk.py` `place` (used by `ny-dec-sprtk`, `ny-dec-sprtk-web` and the 2013-2021 history). This applies the
  same word test.
- `ingest/ma_springfield_aquasight.py` passes no registry row at all (`echo=None`), so the registry never counts there.
- Everything else accepts the match: `build/status.py` `Resolver.row_water`, `va_alexrenew_cso`, and the ECHO DMR and
  operator feeds, which take the registry water as is.

At collection, 985 MassDEP and 26 NY DEC reports were set aside. Every one was placed later by status's own name
step, on the stated water. The MassDEP losses come mainly from **stale crosswalk rows**. Records now exist for MOUNT
HOPE BAY, BEAVER BROOK (Lowell), BOSTON INNER HARBOR, FORT POINT CHANNEL, CHELSEA RIVER and LITTLE RIVER (Haverhill),
yet those rows still say "no slug". `ma-massdep` still writes these 985 records with no water.

### Proposed fixes (CSV, not applied)

`outfall-water-audit-2026-11-28-proposed.csv` has 213 rows. Each has its mechanism, file, key, current and proposed
value, confidence, the live reports at the outfall, the reports that carry the current water, the reports set aside at
collection, and a one-line basis.

- 8 `ma_crosswalk_row` rows: the stale rows above, plus LITTLE MYSTIC CHANNEL and RESERVED CHANNEL mapped to Boston Inner
  Harbor (medium). The two town-specific rows (BEAVER BROOK@LOWELL, LITTLE RIVER@HAVERHILL) need the NAME@TOWN lookup of
  commit 00a8cd07 (branch fix/springfield-mill-river, not on main yet).
- 202 `registry_correction` rows (119 high, 83 review): class ii and i-imp rows only. Each gives the new `water_slug`,
  `water_name`, `distance_m`, `match`, and a `receiving_water_override` with its basis. The fields have to be written
  directly: `ingest/outfall_waters.py` keeps any `geometry` match that `scripts/match_outfalls.py` made without re-reading
  the text, so an override alone changes nothing on a re-run.
- No rows for class i (nothing to fix) or class iii (no basis in the data).

Top fixes by live reports (Part A):

| Reports | Fix | Confidence |
|---:|---|---|
| 598 | MA0100382:010 Fall River: Narragansett Bay to Taunton River (stated "Taunton River", 435 m) | review |
| 415 | crosswalk MOUNT HOPE BAY to mount-hope-bay-ma (FAL002, 003, 006: 415 set aside at collection) | high |
| 320 | MA0100382:002 Narragansett Bay to Mount Hope Bay (0 m) | high |
| 368 | MA0101613:025 and 048 Springfield: Lake Massasoit to mill-river-springfield-ma | high |
| 1,212 | Portland ME (ME0101435, ME0102075; 13 outfalls with reports): Casco Bay to Back Cove, Fore River or Portland Harbor, as the permit states | 3 high, 10 review |
| 117 | crosswalk BEAVER BROOK@LOWELL, and MA0100633:007 Merrimack River to beaver-brook-lowell-ma | high |
| 100 | crosswalk BOSTON INNER HARBOR to boston-inner-harbor-ma | high |
| 78 | PA0026301:008 Erie: Lake Erie to Mill Creek (stated) | high |

A side effect on reaches: 29 class ii rows are matched to a bay, lake or reservoir (`not_river`), so they are not traced.
Correcting them to the stated river (for example Taunton River, Mill River) makes them candidates for tracing.

## Part B: the 8,564 rows with no water record

| | Rows |
|---|---:|
| Live state / not live (GU 12, VI 11, MP 3, AS 2) | 8,536 / 28 |
| Plant outfalls: open / closed | 6,948 / 1 |
| CSO outfalls: open / closed | 1,032 / 471 |
| Other: open / closed | 110 / 2 |
| With a point / without | 8,138 / 426 |
| Duplicate of a row in a more specific file (that row decides) | 491 (129 of them have a water there) |

States with the most: IN 981, PA 953, TX 744, IL 523, IA 471, MO 470, NY 366, OH 300, WV 281, MN 278, ND 254, VA 251.

**Reach index** (the 8,073 rows that decide; built 10:42Z, every one of the 52 jurisdictions live):

| Reach status | Rows | Live reports | No water |
|---|---:|---:|---:|
| plant_deferred (plants are traced only with `--plants`) | 6,444 | 158 | 0 |
| traced | 586 | 1,756 | 839 |
| closed | 385 | 23 | 0 |
| no_location (no point and no EPA reach id; 62 are GLWA's notification-plan outfalls) | 66 | 4,391 | 0 |
| tidal_at_outfall | 62 | 418 | 182 |
| lake_at_outfall | 8 | 191 | 0 |
| no_trace (failed: "no NHDPlus catchment at the outfall's point", "no shore within 5 km") | 8 | 0 | 0 |
| not in the index | 514 | 0 | 0 |

The 514 rows not in the index are 391 live plant rows, 94 "other" rows from the KY, WV, LA and SC files, 28 rows in
territories that are not live, and 1 CSO row. Why the 391 live plant rows are missing is not determined: they are not on
the plants file's `excluded_not_sewage` list, and 252 of them have a point.

### Why a trace does not place a report

In `build/status.py` (around lines 5636 and 5689) a reach colours only the river waters the report is already placed on:
`modeled = [(r, c) for r, c in carry if r.get("segments") and c]`. A report with no water carries nothing, so its
outfall's trace adds nothing. Separately, a report of month or coarser precision never uses a reach (`coarse`). Every
ECHO DMR feed is monthly. So for these 1,021 reports the fix is a water record on the outfall (or a placeable name),
not more tracing. Running `--plants` traces would attach none of the 158 plant-outfall reports, which already have
water.

### The 4,590 reports with a permit and outfall but no water

| Reason (status.json placement note) | Reports |
|---|---:|
| the name matches 2 or more records, no point, and the discharger's towns do not decide (all MI) | 2,110 |
| the outfall is not in the registry (MI 1,348, RI NBC 56, NY 22) | 1,426 |
| the registry outfall has no water (OH 439, IN 166, MI 105, IL 100, KS 28, NJ 24, ECHO overflow feed 13) | 876 |
| the guard rejected a name match as too far, or the town is not among the record's towns (IL, IN, OH) | 144 |
| no reason recorded (MI 29, NY 5) | 34 |

**Michigan, `mi-egle-mienviro-cso-sso-list` (3,592):** No MiEnviro report has a point. All of them name a water
(`receivingWater`). The permits are in the registry, but many outfall numbers are not: Dearborn MI0025542 lacks 005,
007, 008, 010, 011, 012, 015 and 020, Port Huron MI0023833 lacks 003 and 012-024, and Manistee MI0020362 has only its
plant outfall. The deciding failures are names, though:

- "St. Clair River" (Port Huron, 1,357 reports): matches saint-clair-river-mi and saint-clair-river-algonac-mi. The first
  record's towns (Corunna, Marine City, Port Lambton) do not include Port Huron.
- "Rouge River" (Dearborn, 359): matches river-rouge-mi (towns: Melvindale) and river-rouge-detroit-mi.
- "Manistee Lake" (295): matches two lakes. The Manistee discharger row has no towns.
- "Rouge River, Lower Branch" (Dearborn, 1,051): matches no record by name. The record is "Lower River Rouge"
  (lower-river-rouge-mi), whose towns lack Dearborn.
- "O`Brien Drain (tributary to Rouge River)" (GLWA outfall 082, 246): no record, and 082 is not in the registry.
- North Houghton MI0043982 001 "St. Louis Creek" (105): no NHD record found. The trace exists but ends in a lake.

Reach: a trace exists for some of these outfalls, but with no water and no point a report draws nothing from it.

### Recommendations, ranked by reports attached for the work

1. **Choose among same-named records by the permit's own registry waters** (code, `status.Resolver.by_name`). When a
   name is ambiguous and the permit's registry outfalls lie on exactly one of the candidates, take that one. This would
   settle 2,021 of the 2,110 ambiguous reports (Port Huron 1,357, Dearborn 359, Manistee 295, Marysville 5, and 5 more).
   Data-only alternative for Manistee: give `mi-manistee-wwtp-mi0020362` the town Manistee in `data/dischargers.json`
   (295, proposed CSV).
2. **Alias "Rouge River, Lower Branch" to lower-river-rouge-mi** (`data/water-aliases.json`; 1,051). Check that the
   no-point guard accepts it while the record's towns lack Dearborn, or add Dearborn to them.
3. **Fix the MassDEP crosswalk's stale "no slug" rows** (8 rows, proposed CSV). This places 985 reports at collection
   that today wait for status.
4. **Correct the class ii registry rows** (202 rows, proposed CSV). This moves 1,460 reports off a probably wrong water,
   1,200 of them in Portland, Maine. Apply the 119 high rows first.
5. **Give Akron OH0023833's 24 CSO outfalls a water** (201 reports, the largest "registry outfall has no water" group).
   They have no ECHO text, and the Cuyahoga River record lies 199 m from the points, outside the 150 m point step. Work
   from the permit's outfall list, then Euclid OH0031062 (121 reports: HUC-12 labels "City of Euclid-Frontal Lake Erie"
   and "Doan Brook-Frontal Lake Erie", not water names).
6. **Add GLWA outfall 082 (Oakwood Pump Station) to the registry** with the Rouge River as its water (246; proposed CSV,
   a point is still needed).
7. **Settle the guard's "name match too far" rows in IL and IN** (144 reports at about 15 outfalls: Oglesby on the
   Vermilion, Gary and East Chicago on the Grand Calumet, East St. Louis on the Mississippi). Each point lies 2 to 25 km
   from the named record: either the point is wrong or the record is too short. One review per outfall.
8. **Add the NBC outfalls the reports name** (RI0100072 "OF 107" and others, 56) and Sawyer Creek NY0026280 (12).
9. **Plant traces (`--plants`)**: nothing to gain for report placement now, since 0 plant-outfall reports lack water.
   Run them for the rain caution and the outfall pages, not for this.

## Assumptions and limits

- **Outfall ids.** An event's outfall was matched to the registry by `common.outfall_number` (upper case, spaces and
  leading zeros dropped). Failing that, a leading 1-4 letter prefix with an optional "-", "_" or "#" was stripped
  (MassDEP's SPR024, FAL002, HAV021F; NBC's OF107; CSO-12), and then a single trailing letter on a number (MI 049A to
  049). The trailing-letter rule may join a sub-outfall to its parent. It joined 20,946 reports (mostly MassDEP prefixes
  and Detroit's lettered basins).
- **Registry rows.** Where one permit and outfall appears in several files, the row that decides follows
  `common.load_outfall_registry`'s order (regional files over `outfalls-us.json` over the plants file; an open row over
  a closed one within a file). Reports are counted only under that row: 361 Part A rows and 491 Part B rows are
  duplicates and carry no report counts of their own.
- **Live reports** means every non-fixture row of the event index. The index's `water_slugs` are after reach placement.
- **Collection-time set-asides** were counted from the events files' `echo_candidate` notes ("geometry only").
- **Distances** were measured to the record's outline in a local metric projection, or to its box where no outline was
  available. The 1 km "nearby" threshold and the +50 m "high" margin are judgement calls.
- **Impoundments.** "Impoundment on the stated river" (i-imp) needs the matched lake, pond or reservoir to be under 10
  km across and within about 200 m of the stated river's line. Lake Champlain at Plattsburgh is therefore class ii, not
  i.
- **Not read or not determined.** No web sources were used. No per-outfall reach files were read beyond five samples.
  Why 391 live plant rows are missing from the reach index is not determined. The reasons for reports come from
  status.json built at 10:48Z; the counts come from the index built at 03:42Z, and 13 of the index's 4,590 empty reports
  are at outfalls whose registry row has a water (placed in the later build).
