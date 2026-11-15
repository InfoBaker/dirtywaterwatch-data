# CSO rows without coordinates: MI, NE, TN (research notes)

Started 2026-11-15. Read-only web research; nothing in the registry is changed here. Coordinates are recorded exactly
as each source prints them; DMS values are converted to decimal and marked as converted. No point is derived from a
street name or intersection.

Note on the count: the brief says five rows; it lists four permits (six outfalls): MI0037621 001/002/003,
MI0051497 M23, NE0133680 205R, TN0020656 004.

## Rows

| # | Permit | Outfall(s) | Operator (EPA inventory) | Receiving water |
|---|---|---|---|---|
| 1 | MI0037621 | 001, 002, 003 | Oakland Co DPW - Farmington/Evergreen CSO (8 Mile Rd) | Rouge River |
| 2 | MI0051497 | M23 | City of Westland / Wayne Co Westland CSO (Parkway regulator) | Middle Rouge River |
| 3 | NE0133680 | 205R | Omaha CSO (RTB at 64th and Dupont) | Little Papillion Creek |
| 4 | TN0020656 | 004 | Clarksville Gas and Water | Cumberland River |

## Findings

(in progress)

### Checks common to all rows (read 2026-11-15)

- ECHO detailed facility report JSON, `https://echodata.epa.gov/echo/dfr_rest_services.get_dfr?output=JSON&p_id=<permit>`
  for TN0020656, NE0133680, MI0051497, MI0037621: facility-level points only (no permitted-feature coordinates).
  - MI0037621: ICIS facility latitude/longitude null; FRS 110042360539 null; ECHO map falls back to "Zip Code
    Centroid" (42.502486, -83.408936, 10,000 m): not an outfall point. ICIS status "Terminated; Compliance Tracking Off",
    expiry 03/31/1982.
  - MI0051497: ICIS facility point 42.333333, -82.333333 (the bogus Ontario point); FRS 110011117932 point
    42.324194, -83.401727 is "ADDRESS MATCHING-HOUSE NUMBER" / "ENTRANCE POINT OF A FACILITY OR STATION" for
    36601 Ford Road (the permit's facility address): an address geocode, not the outfall. Status "Terminated; Comp..."
    (truncated in the JSON), expiry 10/01/2001.
  - NE0133680 and TN0020656: facility points only.
- EPA's public CSO map (https://www.epa.gov/npdes/where-combined-sewer-overflow-outfalls-are-located), webmap
  4a0921592f81498baa4d4164452f44be, layer
  `https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/Combined_Sewer_Overflows/FeatureServer/0`
  (data last edited 2026-11-09 07:51 UTC), queried `npdes_id='<permit>'`, outFields=*:
  - TN0020656: 002 36.520917,-87.363694; 004 pf_lat 36, pf_lon -87 (geometry plotted at 36.0000002,-87.0000000,
    i.e. the same truncated value); 006 36.532861,-87.366111. Same as the CSV: 004 not usable.
  - NE0133680: 26 outfalls returned (103-121, 201-204, 207, 208, 210-212); **205R is not in the layer at all**
    (no geometry to plot).
  - MI0051497 and MI0037621: no features (terminated permits are not in the map layer).
