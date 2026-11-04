# Data licence

The compiled dataset in this repository and in its releases (the `out/` files: reports, water statuses, coverage
grades, outfalls, operators, sources, and the CSV files derived from them) is released under the
**Open Database License (ODbL) 1.0**: https://opendatacommons.org/licenses/odbl/1-0/

You are free to share, create from and adapt the database, as long as you:

- **attribute** it to DirtyWaterWatch (https://dirtywaterwatch.org, this repository) and to the sources named in
  each record (every record carries its source id, the source's own record id and times);
- **share alike**: a database adapted from it is offered under the ODbL too;
- **keep it open**: a redistributed copy is not locked behind technical measures.

Each source's own terms still apply to its records and are quoted in `data/sources/<id>.yaml` (`license`):

- Federal data (EPA ECHO and ICIS-NPDES, USGS NHD and NLDI, NOAA MRMS, NWS) is in the public domain
  (17 U.S.C. 105).
- State and local data carries the terms each agency states. Where a source discourages redistribution, its records
  are left out of the release.
- Water records from openboatlaunch and OpenStreetMap carry the ODbL already (OpenStreetMap contributors).

The pipeline code is released under the MIT licence (see `LICENSE`). The individual contents of the database
(a report's wording as published by its agency) are the agency's own public record.

Nothing in this dataset is a safety verdict: a report means a discharge was reported, and a water with no report
means only that nothing was reported.
