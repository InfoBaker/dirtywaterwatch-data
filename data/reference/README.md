# Reference files the ingesters read

Hand-kept or hand-extracted inputs that are not source data and not rebuilt by a fetch:

- `ma-portal-waterbody-crosswalk.csv`: MassDEP portal water-body names mapped to water records (portal_waterBody, water_slug, confidence, note).
- `me-cso-<year>-status-report.txt`: the text extracted from Maine DEP's annual CSO status report, read by the Maine annual ingester.
- `cbep-portland-cso-2015-2019.csv`: the Casco Bay Estuary Partnership's merged file of Portland's combined sewer overflows by storm and outfall (2015 to 2019), as published at commit 99cadaab, read by `ingest/me_cbep_portland_cso.py` for 2015 to 2018 (SHA256 checked).
- `portland-cso-2019-filing.csv`: a numbers-only extract of the City of Portland's 2019 "CSO Activity and Volumes" workbook in the same archive (storm, dates as filed and as read, outfall, cell; no names), read by the same ingester for 2019; `python -m ingest.me_cbep_portland_cso --extract` rebuilds it from the pinned workbook.
- `ma-springfield-cso-archive-2019-2023.json`: the Springfield Water and Sewer Commission's monthly CSO reports (January 2019 to April 2023) and annual sheets (2019 to 2022) as transcribed from its CSO Data Archive PDFs, each month checked against its Total row, October 2021 (no report online) the 2021 annual sheet's own October line for all outfalls combined; read by `ingest/ma_springfield_archive.py`; `python -m ingest.ma_springfield_archive --extract RAW_DIR` rebuilds it from the PDFs.
- `ne-mountain-time-counties.json`: the Nebraska counties (and the western part of Cherry County) that keep Mountain time under 49 CFR 71.7(c), with Census TIGERweb outlines, read by the eRule module to give a Nebraska event the zone of its own point (written by `scripts/ne_mountain_time_counties.py`).
- `ne-incorporated-places.json`: Nebraska's incorporated places with their class (city or village) from the Census Bureau's TIGERweb, read by `scripts/add_ne_operators.py` for the legal form of a town's plant.

The ingesters look here first, then in the research raw folder of the machine that built the file.
