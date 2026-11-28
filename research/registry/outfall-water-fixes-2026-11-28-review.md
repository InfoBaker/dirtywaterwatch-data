# Outfall registry water fixes: the review and medium rows (2026-11-28)

The 87 rows of `outfall-water-audit-2026-11-28-proposed.csv` marked `review` (85) or `medium` (2), judged from the data in this repository alone (no web): the registry rows, the water records and their outlines (the openboatlaunch outlines read, not changed), the crosswalk and the research notes. Distances are from the row's point to the record's outline by `build.status` `Resolver.distance_m`; they differ by a few to some tens of metres from the audit's own measure. Verdicts: **apply** (the data support the change), **do not apply** (the data contradict it), **cannot tell** (two records fit, or neither the point nor the text decides). Nothing here was applied, except the Rouge alias (below), applied on the brief's own instruction after the check it asked for.

Rows with live reports are listed first; reports are the audit's counts from the event index of 2026-11-28.

## Verdicts in brief

- **Portland, Maine (ME0102075, ME0101435; 1,037 reports at the review rows).** Apply Back Cove to the six outfalls whose own text is 'Back Cove' (ME0102075 005, 007, 012, 015, 016; ME0101435 006: 559 reports). Do not apply to the four ME0101435 outfalls whose text is 'Portland Harbor, Back Cove, Ca' (013, 017, 018, 024: 478 reports): the text names three waters, and Casco Bay's outline holds both Back Cove and Portland Harbor, so the current tie is broad, not wrong. In both permits EPA's point is one shared point for the open CSOs, so the point decides nothing; the high rows applied in Portland (ME0102075 008 to 011, ME0101435 014 and 019: 175 reports) are closed outfalls with points of their own on Back Cove. South Portland's Fore River rows (ME0100633) cannot be told: two Fore River records.
- **Fall River MA0100382 outfall 010 (598 reports).** Cannot tell between the Taunton River (the permit's text; its record lies 560 m from the point) and Mount Hope Bay (7 m); the current Narragansett Bay tie is the weakest. No report carries the registry water now, so the row's change moves none.
- **Tributary near the main stem** (IN0025674, WV0023124, WV0023353, IN0023604, IN0023183, IN0032956, WV0023230, NY0026689, PA0026107, DC0021199 048 and 049): do not apply; the point is on the tributary the registry has now, and the permit-wide text names the main stem.
- **Stated water within 250 m** (PA0021407 006 Camp Run, PA0025984 212 and PA0217611 056 Sawmill Run, PA0027111 004 Pucketa Creek, PA0027391 004 Bull Creek, NY0027057 020, 023 and 034 Eighteenmile Creek, VT0101010 005 White River): apply; none has live reports.
- **Crosswalk medium rows**: apply (the record already carries both names as aliases). **Alias**: applied. **GLWA 082**: do not apply.

## Portland, Maine, and Fall River outfall 010

### MA0100382 (MA; 1 row; 598 live reports)

- **010** narragansett-bay-ma to taunton-river-ma (598 reports, 0 carry the current water): **cannot tell**. The permit names the Taunton River, but its record (a centre line) lies 560 m from EPA's point, beyond the 400 m tie distance, while Mount Hope Bay's outline is 7 m away; City Pier is where the river meets the bay and the data do not place that boundary. The current Narragansett Bay tie (359 m) is the least supported of the three. None of the 598 reports carries the registry water (MassDEP's crosswalk maps the portal's 'TAUNTON RIVER' to taunton-river-ma), so the row's change moves no report. Settle the row from the permit's outfall map: Taunton River by name, or Mount Hope Bay by the point.

### ME0102075 (ME; 5 rows; 531 live reports)

- **016** casco-bay-me to back-cove-me (131 reports, 131 carry the current water): **apply**. EPA gives this permit's open CSOs one shared point (16 outfalls at 43.673944, -70.254389), so distance says nothing about the outfall. The per-outfall text is the evidence: EPA's text for this outfall is 'Back Cove', and research/me/dischargers.json (me-pwd, from DEP's 2025 status report) counts 5 Portland Water District outfalls to Back Cove, the number of open 'Back Cove' rows here. back-cove-me lies 98.7% inside casco-bay-me's outline, so the change narrows the water rather than moving it.
- **005** casco-bay-me to back-cove-me (125 reports, 125 carry the current water): **apply**. EPA gives this permit's open CSOs one shared point (16 outfalls at 43.673944, -70.254389), so distance says nothing about the outfall. The per-outfall text is the evidence: EPA's text for this outfall is 'Back Cove', and research/me/dischargers.json (me-pwd, from DEP's 2025 status report) counts 5 Portland Water District outfalls to Back Cove, the number of open 'Back Cove' rows here. back-cove-me lies 98.7% inside casco-bay-me's outline, so the change narrows the water rather than moving it.
- **012** casco-bay-me to back-cove-me (125 reports, 125 carry the current water): **apply**. EPA gives this permit's open CSOs one shared point (16 outfalls at 43.673944, -70.254389), so distance says nothing about the outfall. The per-outfall text is the evidence: EPA's text for this outfall is 'Back Cove', and research/me/dischargers.json (me-pwd, from DEP's 2025 status report) counts 5 Portland Water District outfalls to Back Cove, the number of open 'Back Cove' rows here. back-cove-me lies 98.7% inside casco-bay-me's outline, so the change narrows the water rather than moving it.
- **015** casco-bay-me to back-cove-me (113 reports, 113 carry the current water): **apply**. EPA gives this permit's open CSOs one shared point (16 outfalls at 43.673944, -70.254389), so distance says nothing about the outfall. The per-outfall text is the evidence: EPA's text for this outfall is 'Back Cove', and research/me/dischargers.json (me-pwd, from DEP's 2025 status report) counts 5 Portland Water District outfalls to Back Cove, the number of open 'Back Cove' rows here. back-cove-me lies 98.7% inside casco-bay-me's outline, so the change narrows the water rather than moving it.
- **007** casco-bay-me to back-cove-me (37 reports, 37 carry the current water): **apply**. EPA gives this permit's open CSOs one shared point (16 outfalls at 43.673944, -70.254389), so distance says nothing about the outfall. The per-outfall text is the evidence: EPA's text for this outfall is 'Back Cove', and research/me/dischargers.json (me-pwd, from DEP's 2025 status report) counts 5 Portland Water District outfalls to Back Cove, the number of open 'Back Cove' rows here. back-cove-me lies 98.7% inside casco-bay-me's outline, so the change narrows the water rather than moving it.

### ME0101435 (ME; 5 rows; 506 live reports)

- **017** casco-bay-me to back-cove-me (159 reports, 159 carry the current water): **do not apply**. EPA's text is 'Portland Harbor, Back Cove, Ca' (cut at 30 characters: Portland Harbor, Back Cove, Casco Bay); it names three waters and the point is the permit's shared point (8 outfalls), so neither the text nor the point picks Back Cove; casco-bay-me's outline holds both Back Cove and Portland Harbor, so the current tie is not wrong, only broad. Settle from the City's or the CBEP's per-outfall list.
- **018** casco-bay-me to back-cove-me (152 reports, 152 carry the current water): **do not apply**. EPA's text is 'Portland Harbor, Back Cove, Ca' (cut at 30 characters: Portland Harbor, Back Cove, Casco Bay); it names three waters and the point is the permit's shared point (8 outfalls), so neither the text nor the point picks Back Cove; casco-bay-me's outline holds both Back Cove and Portland Harbor, so the current tie is not wrong, only broad. Settle from the City's or the CBEP's per-outfall list.
- **013** casco-bay-me to back-cove-me (140 reports, 140 carry the current water): **do not apply**. EPA's text is 'Portland Harbor, Back Cove, Ca' (cut at 30 characters: Portland Harbor, Back Cove, Casco Bay); it names three waters and the point is the permit's shared point (8 outfalls), so neither the text nor the point picks Back Cove; casco-bay-me's outline holds both Back Cove and Portland Harbor, so the current tie is not wrong, only broad. Settle from the City's or the CBEP's per-outfall list.
- **006** casco-bay-me to back-cove-me (28 reports, 28 carry the current water): **apply**. EPA gives this permit's open CSOs one shared point (8 outfalls at 43.673111, -70.251389), so distance says nothing about the outfall. The per-outfall text is the evidence: EPA's text for this outfall is 'Back Cove', and research/me/dischargers.json (me-portland-city, from DEP's 2025 status report) counts 3 City outfalls to Back Cove; its 'Back Cove ... no own slug; mapped to casco-bay-me' predates the record. back-cove-me lies 98.7% inside casco-bay-me's outline, so the change narrows the water rather than moving it.
- **024** casco-bay-me to back-cove-me (27 reports, 27 carry the current water): **do not apply**. EPA's text is 'Portland Harbor, Back Cove, Ca' (cut at 30 characters: Portland Harbor, Back Cove, Casco Bay); it names three waters and the point is the permit's shared point (8 outfalls), so neither the text nor the point picks Back Cove; casco-bay-me's outline holds both Back Cove and Portland Harbor, so the current tie is not wrong, only broad. Settle from the City's or the CBEP's per-outfall list.

## Other rows with live reports

### MI0025542 (MI; 1 row; 1,051 live reports)

- **lower-river-rouge-mi** (alias, 1051 reports): **applied** (on the brief's instruction; marked review in the audit). 'Rouge River, Lower Branch' is now an alias of lower-river-rouge-mi, whose existing alias is 'Lower Rouge River', which Dearborn's own discharger row lists. The status resolver keeps it with no point: the name is that record's alone in Michigan, and the no-point guard checks only the state, so the record's towns (Dearborn Heights, Wayne) need not include Dearborn. Test: `tests/test_registry_water_fixes.py`.

### MI0022802 (MI; 1 row; 246 live reports)

- **MI0022802:082** (registry_addition, 246 reports): **do not apply** (and cannot tell the water). The reports name 'O`Brien Drain (tributary to Rouge River)', which has no record; 'Rouge River' is two Michigan records (river-rouge-mi, river-rouge-detroit-mi) and the row would have no point to choose between them. When a source gives the point, `scripts/outfall_point_corrections.py`'s ADD table is the existing way to add an authority-listed outfall.

### MA0101192 (MA; 2 rows; 62 live reports)

- **LITTLE MYSTIC CHANNEL** (ma_crosswalk_row, 27 reports): **apply**. boston-inner-harbor-ma already carries 'Little Mystic Channel' as an alias and the registry ties BOS019 to it; the crosswalk's 'no slug' row is what stops MassDEP's 27 reports at collection (status places them later by the alias).
- **RESERVED CHANNEL** (ma_crosswalk_row, 35 reports): **apply**. boston-inner-harbor-ma already carries 'Reserved Channel' as an alias and the registry ties BOS076, 078, 079 and 080 to it; as Little Mystic Channel.

### NH0100234 (NH; 1 row; 38 live reports)

- **013** piscataqua-river-nh to portsmouth-harbor-nh (38 reports, 38 carry the current water): **do not apply**. The point lies 99 m from the Piscataqua River and 829 m from Portsmouth Harbor; outfall 012 of the same permit has the opposite (text 'Piscataqua River', point 18 m from Portsmouth Harbor), which suggests the two points or texts are swapped; check both against the permit.

### NJ0108723 (NJ; 1 row; 26 live reports)

- **020** little-basin-nj to hudson-river-nj (26 reports, 26 carry the current water): **do not apply**. Two Hudson River records lie 887 m from the point (hudson-river-nj and hudson-river-jersey-city-nj), Little Basin 181 m; the point does not reach the river and two records fit.

### MA0100625 (MA; 1 row; 9 live reports)

- **005** massachusetts-bay-ma to gloucester-harbor-ma (9 reports, 0 carry the current water): **cannot tell**. The text names Gloucester Inner Harbor and the Gloucester Harbor record lies 840 m from the point, while Massachusetts Bay is 122 m; the point does not reach the harbor record.

## Rows with no live reports

### CT0100056 (CT; 4 rows; 0 live reports)

- **047** bridgeport-harbor-ct to pequonnock-river-ct (0 reports, 0 carry the current water): **cannot tell**. The stated water's record lies 846 m from the point and bridgeport-harbor-ct 161 m; the point does not reach the stated water.
- **048** bridgeport-harbor-ct to pequonnock-river-ct (0 reports, 0 carry the current water): **cannot tell**. The stated water's record lies 846 m from the point and bridgeport-harbor-ct 161 m; the point does not reach the stated water.
- **049** bridgeport-harbor-ct to pequonnock-river-ct (0 reports, 0 carry the current water): **cannot tell**. The stated water's record lies 614 m from the point and bridgeport-harbor-ct 415 m; the point does not reach the stated water.
- **207** bridgeport-harbor-ct to pequonnock-river-ct (0 reports, 0 carry the current water): **cannot tell**. The stated water's record lies 733 m from the point and bridgeport-harbor-ct 304 m; the point does not reach the stated water.

### DC0021199 (DC; 2 rows; 0 live reports)

- **048** piney-branch-dc to rock-creek-dc (0 reports, 0 carry the current water): **do not apply**. The point lies 48 m from Piney Branch, a tributary of Rock Creek, and 919 m from Rock Creek; 'Rock Creek East Side' names the side of the creek's drainage, and the matched tributary is probably right.
- **049** piney-branch-dc to rock-creek-dc (0 reports, 0 carry the current water): **do not apply**. As 048: Piney Branch 87 m, Rock Creek 1,032 m.

### IN0023183 (IN; 2 rows; 0 live reports)

- **049** fall-creek-in to white-river-in (0 reports, 0 carry the current water): **do not apply**. The point lies 0 m from fall-creek-in, a tributary, and 1,112 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **210** fall-creek-in to white-river-in (0 reports, 0 carry the current water): **do not apply**. The point lies 42 m from fall-creek-in, a tributary, and 1,196 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.

### IN0023604 (IN; 4 rows; 0 live reports)

- **006** eel-river-in to wabash-river-in (0 reports, 0 carry the current water): **do not apply**. The point lies 50 m from eel-river-in, a tributary, and 812 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **007** eel-river-in to wabash-river-in (0 reports, 0 carry the current water): **do not apply**. The point lies 60 m from eel-river-in, a tributary, and 845 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **008** eel-river-in to wabash-river-in (0 reports, 0 carry the current water): **do not apply**. The point lies 58 m from eel-river-in, a tributary, and 882 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **013** eel-river-in to wabash-river-in (0 reports, 0 carry the current water): **do not apply**. The point lies 66 m from eel-river-in, a tributary, and 963 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.

### IN0025674 (IN; 7 rows; 0 live reports)

- **006** elkhart-river-in to st-joseph-river-bristol-in (0 reports, 0 carry the current water): **do not apply**. The point lies 17 m from elkhart-river-in, a tributary, and 494 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **007** elkhart-river-in to st-joseph-river-bristol-in (0 reports, 0 carry the current water): **do not apply**. The point lies 36 m from elkhart-river-in, a tributary, and 475 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **008** elkhart-river-in to st-joseph-river-bristol-in (0 reports, 0 carry the current water): **do not apply**. The point lies 22 m from elkhart-river-in, a tributary, and 810 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **009** elkhart-river-in to st-joseph-river-bristol-in (0 reports, 0 carry the current water): **do not apply**. The point lies 34 m from elkhart-river-in, a tributary, and 540 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **010** elkhart-river-in to st-joseph-river-bristol-in (0 reports, 0 carry the current water): **do not apply**. The point lies 16 m from elkhart-river-in, a tributary, and 748 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **011** elkhart-river-in to st-joseph-river-bristol-in (0 reports, 0 carry the current water): **do not apply**. The point lies 24 m from elkhart-river-in, a tributary, and 801 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **016** elkhart-river-in to st-joseph-river-bristol-in (0 reports, 0 carry the current water): **do not apply**. The point lies 25 m from elkhart-river-in, a tributary, and 525 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.

### IN0032956 (IN; 3 rows; 0 live reports)

- **009** pigeon-creek-evansville-in to ohio-river-in (0 reports, 0 carry the current water): **do not apply**. The point lies 247 m from pigeon-creek-evansville-in, a tributary, and 488 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **015** pigeon-creek-evansville-in to ohio-river-in (0 reports, 0 carry the current water): **do not apply**. The point lies 255 m from pigeon-creek-evansville-in, a tributary, and 487 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **020** pigeon-creek-evansville-in to ohio-river-in (0 reports, 0 carry the current water): **do not apply**. The point lies 386 m from pigeon-creek-evansville-in, a tributary, and 664 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.

### KS0038563 (KS; 1 row; 0 live reports)

- **C65** kansas-river-ks to jersey-creek-ks (0 reports, 0 carry the current water): **do not apply**. The point lies 25 m from the Kansas River and 700 m from Jersey Creek; the point and text disagree.

### KY0025291 (KY; 1 row; 0 live reports)

- **003** levisa-fork-ky to pikeville-pond-ky (0 reports, 0 carry the current water): **cannot tell**. Pikeville Pond lies 596 m from the point, the Levisa Fork 431 m and Pikeville Cut-Through 463 m; none is beside the point.

### ME0100439 (ME; 1 row; 0 live reports)

- **002** piscataquis-river-me to sebec-river-me (0 reports, 0 carry the current water): **do not apply**. The Sebec River record lies 1,051 m from the point, the Piscataquis River 317 m.

### ME0100633 (ME; 4 rows; 0 live reports)

- **005** casco-bay-me to fore-river-portland-me (0 reports, 0 carry the current water): **cannot tell**. Two records carry the name Fore River (fore-river-portland-me 674 m, fore-river-me 675 m, both centre lines) and the point is the permit's shared point (4 outfalls at 43.637806, -70.257), so the data do not pick one; no live reports.
- **006** casco-bay-me to fore-river-portland-me (0 reports, 0 carry the current water): **cannot tell**. Two records carry the name Fore River (fore-river-portland-me 674 m, fore-river-me 675 m, both centre lines) and the point is the permit's shared point (4 outfalls at 43.637806, -70.257), so the data do not pick one; no live reports.
- **018** casco-bay-me to fore-river-portland-me (0 reports, 0 carry the current water): **cannot tell**. Two records carry the name Fore River (fore-river-portland-me 674 m, fore-river-me 675 m, both centre lines) and the point is the permit's shared point (4 outfalls at 43.637806, -70.257), so the data do not pick one; no live reports.
- **024** casco-bay-me to fore-river-portland-me (0 reports, 0 carry the current water): **cannot tell**. Two records carry the name Fore River (fore-river-portland-me 674 m, fore-river-me 675 m, both centre lines) and the point is the permit's shared point (4 outfalls at 43.637806, -70.257), so the data do not pick one; no live reports.

### NH0100234 (NH; 1 row; 0 live reports)

- **012** portsmouth-harbor-nh to piscataqua-river-nh (0 reports, 0 carry the current water): **do not apply**. The point lies 18 m from Portsmouth Harbor and 685 m from the Piscataqua River; see 013.

### NJ0108758 (NJ; 1 row; 0 live reports)

- **020** little-basin-nj to hudson-river-nj (0 reports, 0 carry the current water): **do not apply**. As NJ0108723:020: two Hudson River records at 894 m, Little Basin 167 m.

### NY0026689 (NY; 2 rows; 0 live reports)

- **003** saw-mill-river-ny to hudson-river-ny (0 reports, 0 carry the current water): **do not apply**. The point lies 127 m from saw-mill-river-ny, a tributary, and 615 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **025** saw-mill-river-ny to hudson-river-ny (0 reports, 0 carry the current water): **do not apply**. The point lies 186 m from saw-mill-river-ny, a tributary, and 991 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.

### NY0027057 (NY; 4 rows; 0 live reports)

- **019** erie-canal-albion-ny to eighteenmile-creek-lockport-ny (0 reports, 0 carry the current water): **cannot tell**. Eighteenmile Creek's record lies 329 m from the point and the Erie Canal record (erie-canal-albion-ny) 67 m; the point is much nearer the canal.
- **020** erie-canal-albion-ny to eighteenmile-creek-lockport-ny (0 reports, 0 carry the current water): **apply**. 'Eighteenmile Creek' has one record, 210 m from the point (erie-canal-albion-ny 54 m); the outfall is plausibly on the stated water, and no other record of its name is near.
- **023** erie-canal-albion-ny to eighteenmile-creek-lockport-ny (0 reports, 0 carry the current water): **apply**. 'Eighteenmile Creek' has one record, 184 m from the point (erie-canal-albion-ny 46 m); the outfall is plausibly on the stated water, and no other record of its name is near.
- **034** erie-canal-albion-ny to eighteenmile-creek-lockport-ny (0 reports, 0 carry the current water): **apply**. 'Eighteenmile Creek' has one record, 143 m from the point (erie-canal-albion-ny 38 m); the outfall is plausibly on the stated water, and no other record of its name is near.

### NY0028410 (NY; 2 rows; 0 live reports)

- **014** lake-erie-ny to buffalo-river-ny (0 reports, 0 carry the current water): **do not apply**. The text is 'Buffalo Harbor'; the proposed record is the Buffalo River (605 m), another water that shares only the word Buffalo; the point lies in Lake Erie's outline.
- **015** lake-erie-ny to buffalo-river-ny (0 reports, 0 carry the current water): **do not apply**. As 014: 'Buffalo Harbor' is not the Buffalo River (535 m); the point lies in Lake Erie's outline.

### NY0183695 (NY; 1 row; 0 live reports)

- **002** champlain-canal-ny to hudson-river-ny (0 reports, 0 carry the current water): **cannot tell**. The stated water's record lies 599 m from the point and champlain-canal-ny 326 m; the point does not reach the stated water.

### OH0026565 (OH; 1 row; 0 live reports)

- **005** cross-creek-oh to ohio-river-oh (0 reports, 0 carry the current water): **do not apply**. The Ohio River record lies 1,013 m from the point, Cross Creek 420 m; the permit-wide text names the main stem.

### PA0021407 (PA; 1 row; 0 live reports)

- **006** monongahela-river-pa to camp-run-pa (0 reports, 0 carry the current water): **apply**. 'Camp Run' has one record, 195 m from the point (monongahela-river-pa 110 m); the outfall is plausibly on the stated water, and no other record of its name is near.

### PA0025984 (PA; 1 row; 0 live reports)

- **212** ohio-river-pa to sawmill-run-pa (0 reports, 0 carry the current water): **apply**. 'Sawmill Run' has one record, 231 m from the point (ohio-river-pa 134 m); the outfall is plausibly on the stated water, and no other record of its name is near.

### PA0026107 (PA; 1 row; 0 live reports)

- **044** lackawanna-river-pa to susquehanna-river-pa (0 reports, 0 carry the current water): **do not apply**. The point lies 364 m from lackawanna-river-pa, a tributary, and 1,048 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.

### PA0027090 (PA; 1 row; 0 live reports)

- **007** lackawanna-river-pa to pancoast-creek-pa (0 reports, 0 carry the current water): **cannot tell**. The stated water's record lies 674 m from the point and lackawanna-river-pa 297 m; the point does not reach the stated water.

### PA0027111 (PA; 3 rows; 0 live reports)

- **004** allegheny-river-pa to pucketa-creek-pa (0 reports, 0 carry the current water): **apply**. 'Pucketa Creek' has one record, 183 m from the point (allegheny-river-pa 39 m); the outfall is plausibly on the stated water, and no other record of its name is near.
- **005** allegheny-river-pa to pucketa-creek-pa (0 reports, 0 carry the current water): **do not apply**. The stated water's record lies 766 m from the point, allegheny-river-pa 202 m; the point and the text disagree.
- **006** allegheny-river-pa to pucketa-creek-pa (0 reports, 0 carry the current water): **do not apply**. The stated water's record lies 959 m from the point, allegheny-river-pa 227 m; the point and the text disagree.

### PA0027197 (PA; 3 rows; 0 live reports)

- **002** susquehanna-river-pa to paxton-creek-pa (0 reports, 0 carry the current water): **do not apply**. The stated water's record lies 538 m from the point, susquehanna-river-pa 245 m; the point and the text disagree.
- **023** susquehanna-river-pa to conodoguinet-creek-pa (0 reports, 0 carry the current water): **do not apply**. The text 'Conodoguinet Creek' and the point disagree: the point lies 75 m from the Susquehanna and 1,007 m from Conodoguinet Creek (ingest.outfall_waters notes Harrisburg's 'Conodoguinet Creek' outfalls on Paxton Creek).
- **063** susquehanna-river-pa to paxton-creek-pa (0 reports, 0 carry the current water): **do not apply**. The stated water's record lies 627 m from the point, susquehanna-river-pa 386 m; the point and the text disagree.

### PA0027391 (PA; 1 row; 0 live reports)

- **004** allegheny-river-pa to bull-creek-pa (0 reports, 0 carry the current water): **apply**. 'Bull Creek' has one record, 131 m from the point (allegheny-river-pa 16 m); the outfall is plausibly on the stated water, and no other record of its name is near.

### PA0217611 (PA; 1 row; 0 live reports)

- **056** ohio-river-pa to sawmill-run-pa (0 reports, 0 carry the current water): **apply**. 'Sawmill Run' has one record, 231 m from the point (ohio-river-pa 134 m); the outfall is plausibly on the stated water, and no other record of its name is near.

### RI0100315 (RI; 1 row; 0 live reports)

- **019A** narragansett-bay-ri to providence-river-ri (0 reports, 0 carry the current water): **cannot tell**. The Providence River record lies 574 m from the point, Narragansett Bay 22 m; the river is the bay's head and the data do not place the boundary.

### RISS00032 (RI; 1 row; 0 live reports)

- **019A** narragansett-bay-ri to providence-river-ri (0 reports, 0 carry the current water): **cannot tell**. The same outfall as RI0100315:019A (Providence River 574 m, Narragansett Bay 22 m).

### VT0101010 (VT; 1 row; 0 live reports)

- **005** connecticut-river-vt to white-river-vt (0 reports, 0 carry the current water): **apply**. 'WHITE RIVER' has one record, 249 m from the point (connecticut-river-vt 165 m); the outfall is plausibly on the stated water, and no other record of its name is near.

### WV0023124 (WV; 8 rows; 0 live reports)

- **C003** deckers-creek-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 37 m from deckers-creek-wv, a tributary, and 581 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **C004** deckers-creek-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 24 m from deckers-creek-wv, a tributary, and 709 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **C005** deckers-creek-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 6 m from deckers-creek-wv, a tributary, and 737 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **C006** deckers-creek-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 9 m from deckers-creek-wv, a tributary, and 884 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **C038** deckers-creek-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 43 m from deckers-creek-wv, a tributary, and 702 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **XXX2** deckers-creek-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 0 m from deckers-creek-wv, a tributary, and 591 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **XXX6** deckers-creek-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 95 m from deckers-creek-wv, a tributary, and 625 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **XXX9** deckers-creek-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 6 m from deckers-creek-wv, a tributary, and 737 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.

### WV0023230 (WV; 1 row; 0 live reports)

- **C065** big-wheeling-creek-wv to ohio-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 37 m from big-wheeling-creek-wv, a tributary, and 590 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.

### WV0023353 (WV; 4 rows; 0 live reports)

- **C006** west-fork-river-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 4 m from west-fork-river-wv, a tributary, and 762 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **C008** west-fork-river-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 6 m from west-fork-river-wv, a tributary, and 657 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **C010** west-fork-river-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 122 m from west-fork-river-wv, a tributary, and 485 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.
- **C050** west-fork-river-wv to monongahela-river-wv (0 reports, 0 carry the current water): **do not apply**. The point lies 50 m from west-fork-river-wv, a tributary, and 957 m from the main stem the permit-wide text names; the matched tributary is probably the outfall's water.

## Ohio: Akron and Euclid (not in the proposed CSV; data only, nothing applied)

### OH0023833 Akron (41 registry rows in data/outfalls-us.json; 36 without a water, 26 of them open CSOs)

**Not applied.** 35 of the 36 rows without a water have no receiving-water text in EPA's inventory and carry the
facility's point (coords_from 'facility', point_shared_by 35, at 41.157121, -81.569837: the treatment plant, not an
outfall); the 36th (082, closed) names the Ohio Canal Enclosure, which has no record. The Cuyahoga River record's 199 m is measured from that plant point, so it says nothing about where any CSO
discharges. The permit's own listed receiving waters (data/dischargers.json, research/oh/dischargers.json) are the
Little Cuyahoga River, the Ohio Canal Enclosure and 'SS to Little Cuyahoga River', not the Cuyahoga main stem, and the
Akron rows that do have a text name the Little Cuyahoga (073, 074) or the Ohio Canal Enclosure (082). A record exists for
the Little Cuyahoga River (little-cuyahoga-river-oh, towns Akron, Mogadore, Springfield), but nothing in the repository
says which of the 36 outfalls are on it and which on the Ohio Canal Enclosure (no record) or the Cuyahoga. Tying them to
the Cuyahoga would be a guess, and probably the wrong water. What would settle it: the per-outfall receiving waters from
Ohio EPA's permit or the City's CSO notification layer (the discharger row's ArcGIS service), with each outfall's point.

### OH0031062 Euclid (20 rows; report only)

16 rows have no water. Their texts are USGS HUC-12 labels ('City of Euclid-Frontal Lake Erie' on 9 rows, 'Doan Brook-
Frontal Lake Erie' on 022; receiving_water_source 'auto') or none (5 rows, 4 of them at the facility's point,
41.611828, -81.527876, 299 m from Lake Erie). The labels name watersheds, not waters, and the points lie more than 150 m
from every record, so no water can be read from the data. Rows 007 and 013 are on unnamed-stream-near-euclid-oh and 014
on euclid-creek-oh. Records exist for Euclid Creek, Doan Brook and Lake Erie; the per-outfall waters need the permit's
outfall list.
