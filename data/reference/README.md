# Reference files the ingesters read

Hand-kept or hand-extracted inputs that are not source data and not rebuilt by a fetch:

- `ma-portal-waterbody-crosswalk.csv`: MassDEP portal water-body names mapped to water records (portal_waterBody, water_slug, confidence, note).
- `me-cso-<year>-status-report.txt`: the text extracted from Maine DEP's annual CSO status report, read by the Maine annual ingester.

The ingesters look here first, then in the research raw folder of the machine that built the file.
