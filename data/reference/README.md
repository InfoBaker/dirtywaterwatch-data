# Reference files the ingesters read

Hand-kept or hand-extracted inputs that are not source data and not rebuilt by a fetch:

- `ma-portal-waterbody-crosswalk.csv`: MassDEP portal water-body names mapped to water records (portal_waterBody, water_slug, confidence, note).
- `me-cso-<year>-status-report.txt`: the text extracted from Maine DEP's annual CSO status report, read by the Maine annual ingester.
- `ne-mountain-time-counties.json`: the Nebraska counties (and the western part of Cherry County) that keep Mountain time under 49 CFR 71.7(c), with Census TIGERweb outlines, read by the eRule module to give a Nebraska event the zone of its own point (written by `scripts/ne_mountain_time_counties.py`).
- `ne-incorporated-places.json`: Nebraska's incorporated places with their class (city or village) from the Census Bureau's TIGERweb, read by `scripts/add_ne_operators.py` for the legal form of a town's plant.

The ingesters look here first, then in the research raw folder of the machine that built the file.
