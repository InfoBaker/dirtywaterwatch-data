# Springfield's CSO Data Archive: the monthly reports against the annual sheets and our event records

Permit MA0101613. Built 2026-11-28 from `data/reference/ma-springfield-cso-archive-2019-2023.json` (the transcript the feed `ma-springfield-archive` reads). Figures are the commission's as printed; nothing here changes a record. Earlier check of April 2023 outfall by outfall: `research/ma/springfield-archive-validation.md`.

## Each month's rows against its own Total row

Every month adds up (events and gallons exactly, hours within the rounding of the rows) except these, which the commission printed that way; the rows are kept as printed and the transcript lists each difference (`known_difference`):

| Month | Rows | Total row | Difference |
|---|---|---|---|
| 2019-03 | 6,481,489 gal | 6,481,490 | the Total row differs from the rows by 1 gallon in the commission's report (rounding) |
| 2019-04 | 61,149,569 gal | 61,149,568 | the Total row differs from the rows by 1 gallon in the commission's report (rounding) |
| 2019-05 | 22,027,007 gal | 22,027,008 | the Total row differs from the rows by 1 gallon in the commission's report (rounding) |
| 2019-09 | 41 events | 38.75 | the Total row prints 38.75 events, not a whole number; the rows give 41 (gallons and hours add up) |
| 2021-09 | 175,284,091 gal | 175,284,090 | the Total row differs from the rows by 1 gallon in the commission's report (rounding) |
| 2021-11 | 44,006,881 gal | 44,006,880 | the Total row differs from the rows by 1 gallon in the commission's report (rounding) |
| 2022-11 | 42,866,459 gal | 42,866,460 | the Total row differs from the rows by 1 gallon in the commission's report (rounding) |

No row was corrected by hand.

## Sum of the months against the annual sheet

| Year | Months (events / gal) | Annual sheet (events / gal) | Difference (gal) |
|---|---|---|---|
| 2019 | 460 / 346,780,127 | 452 / 345,910,042 | -870,085 |
| 2020 | 341 / 208,286,829 | 341 / 208,287,415 | 586 |
| 2021 | 426 / 726,240,778 (11 months; no October report) | 465 / 775,927,041 | 49,686,263 |
| 2022 | 375 / 382,262,401 | 374 / 382,262,401 | 0 |

The annual sheets are not a plain sum of the monthly reports: their month lines differ from the reports' Total rows in these months (sheet minus report):

| Month | Report Total row (gal) | Annual sheet's month line (gal) | Sheet minus report |
|---|---|---|---|
| 2019-03 | 6,481,490 | 6,675,404 | +193,914 |
| 2019-06 | 4,666,310 | 3,591,310 | -1,075,000 |
| 2019-07 | 32,005,097 | 32,016,097 | +11,000 |
| 2020-12 | 54,783,000 | 54,783,586 | +586 |
| 2021-05 | 76,018,484 | 87,572,484 | +11,554,000 |
| 2021-07 | 226,056,752 | 233,000,752 | +6,944,000 |
| 2021-08 | 100,825,410 | 100,974,410 | +149,000 |

Per outfall the 2019 sheet also differs from the sum of the months: in events at CSO 010, 014, 015A, 016, 018, 035 and 045, and in gallons at CSO 008, 010 and 048 (and by a gallon at a few others); the 2020 sheet in gallons at CSO 046. The annual sheets carry revisions the monthly reports do not; the feed publishes the monthly reports as printed.

## October 2021 (no report online)

The commission's archive page links no working file for October 2021. What the feed publishes for the month is one record with no outfall: the 31,039,264 gallons the 2021 annual sheet prints on its October line ("Discharge Summary By Month"), all outfalls combined, as the commission printed it. The sheet prints no October event count or hours, so the record gives none. The hourly run checks the transcript's October entry against that line, and the sheet's twelve month lines against its System Total (775,927,040 against 775,927,041: the reports' 1 gallon). The record is placed as any CSO report of the permit that names no outfall: on every water the permit's registry outfalls reach.

No per-outfall October figures are published. The arithmetic below is kept here only: it does not establish which outfalls discharged in October. Per outfall, the 2021 sheet less the other eleven months gives 49,686,263 gallons; the sheet's own October line is 31,039,264. The gap is the sheet's revisions of other months (its month line minus that month's report):

- 2021-05: 11,554,000 gallons, equal to the whole difference at CSO 024
- 2021-07: 6,944,000 gallons, equal to the whole difference at CSO 042
- 2021-08: 149,000 gallons, equal to no single outfall's difference

A revision that equals one outfall's difference need not belong to that outfall: the sheet gives each revision as a month total, not by outfall, so part of July's 6,944,000 gallons could sit at CSO 045 and the same amount of CSO 042's difference could be October's. The totals reconcile either way (less all three revisions the differences give 31,039,263 gallons, the sheet's October line to the gallon), but which outfalls discharged in October cannot be read from them. An earlier build published seven outfalls (CSO 010, 012, 013, 014, 016, 045 and 049) as discharging in October 2021 on this reasoning; those records were withdrawn after review on 2026-11-28.

| Outfall | Annual sheet less the other eleven months (events / gal) |
|---|---|
| CSO 010 | 4 / 3,696,000 |
| CSO 011 | 0 / -1 |
| CSO 012 | 4 / 24,617,000 |
| CSO 013 | 2 / 790,000 |
| CSO 014 | 2 / 745,000 |
| CSO 015A | 1 / 9,000 |
| CSO 016 | 1 / 822,000 |
| CSO 017 | 1 / 4,000 |
| CSO 018 | 2 / 10,264 |
| CSO 024 | 1 / 11,554,000 |
| CSO 025 | 2 / 33,000 |
| CSO 042 | 8 / 6,944,000 |
| CSO 045 | 4 / 155,000 |
| CSO 046 | 2 / 127,000 |
| CSO 048 | 1 / 4,000 |
| CSO 049 | 4 / 176,000 |

## The months that event-level records also cover

The map log as read 2026-11-28T01:42:02Z (`ma-springfield-aquasight`, 2,134 rows) and MassDEP's portal file of 2026-11-14T17:02:43Z (`ma-massdep`). Map rows are counted by the month their start falls in (Eastern time); portal gallons are the sum over the permit's CSO records with a volume (in this period a notice carries no volume and its verified report does). The reports count storm events (24 hours of dry weather on each side), so one event can hold several map rows. Counts only, not a match row by row.

| Month | Report events | Report gal | Map rows | Portal records with gallons | Portal gal |
|---|---|---|---|---|---|
| 2022-03 | 23 | 13,010,355 | 28 | n/a | n/a |
| 2022-04 | 45 | 68,079,000 | 92 | n/a | n/a |
| 2022-05 | 29 | 23,816,086 | 21 | n/a | n/a |
| 2022-06 | 40 | 18,892,363 | 63 | n/a | n/a |
| 2022-07 | 63 | 58,139,679 | 41 | 63 | 58,139,679 |
| 2022-08 | 26 | 7,504,000 | 13 | 26 | 7,504,000 |
| 2022-09 | 44 | 58,907,459 | 40 | 43 | 58,894,459 |
| 2022-10 | 22 | 22,007,000 | 24 | 23 | 22,020,000 |
| 2022-11 | 35 | 42,866,460 | 38 | 35 | 42,866,459 |
| 2022-12 | 19 | 22,832,000 | 32 | 19 | 22,832,000 |
| 2023-01 | 37 | 36,427,000 | 42 | 39 | 38,723,000 |
| 2023-02 | 9 | 1,228,000 | 9 | 9 | 1,228,000 |
| 2023-03 | 8 | 9,412,000 | 20 | 8 | 9,412,000 |
| 2023-04 | 44 | 34,301,401 | 77 | 44 | 34,301,400 |

The feed emits every month: a month-precision total stands beside the event records of the same outfall, is never counted as an event (build/charts.py is_total) and its monthly mark ranks below every red, yellow or unresolved status (build/status.py RANK; docs/plan.md section 2.x), as EPA's monthly DMR totals stand beside the portal's records of this permit since 2024.

