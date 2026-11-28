# PA ECHO real-record fixtures

`violations.csv` keeps nine real rows and source column names from EPA's
`https://echo.epa.gov/files/echodownloads/npdes_downloads.zip`, member
`NPDES_SE_VIOLATIONS.csv`. The selected rows were checked against a fresh range
read on Nov. 28, 2026; archive Last-Modified: Nov. 23, 2026, 04:07:27 GMT.
Two excluded rows (industrial D0011 and paperwork) come from the researchers'
same-day PA extract of that archive. `sics.csv` contains only the needed permits'
SIC rows from `NPDES_SICS.csv`. No contact or customer fields exist in these tables.
The manhole number in the Singer Run comment identifies infrastructure.

The examples cover ALCOSAN's March 7 violation, overlapping SSO/D0011 codes for
Philadelphia on June 26, 2024, winter and summer dates, missing closure dates,
old codes, and a named water in a public comment. Every closure date is a
regulatory date, not a confirmed physical discharge end.

`utility_records.json` trims three records from the researchers' Nov. 28, 2026
live read of `https://dirtywaterwatch.org/csv/state/pa.csv`. Permit IDs are joined
from the existing discharger registry, not columns claimed to be in that CSV.
The original record URLs are retained. The ALCOSAN notice was checked again at
its public agency URL on Nov. 28 and explicitly dates its two-hour outage
March 6, despite March 7 in the URL and ECHO. PWD and Erie examples establish
that unrelated current utility records do not become duplicates.

Tests change copies in memory for bad dates, malformed rows and other-state
queries; those changed inputs are synthetic test cases, not source claims.

`industrial_bypasses.csv` and `industrial_sics.csv` contain two real violations
and their SIC rows copied from the saved Nov. 28, 2026, 13:55:03 UTC snapshot of
the same EPA archive (same Last-Modified above). Violation 3637746096 is A0011 at
water-supply permit PA0000272 (SIC 4941); 3690502307 is F036S at steel-mill
permit PA0004073 (SIC 3312). Neither establishes sewage. ALCOSAN's bypass in
`violations.csv` is the sewerage-SIC positive control. Tests add a secondary 4952
SIC in memory solely to check that any SIC slot may supply sewerage evidence.

The location-conflict tests change copies of the real Singer Run row in memory
to name Example Creek or another manhole, or supply different outfall IDs. Those
variants and utility candidates marked `synthetic-` are invented test cases,
not additional EPA or utility records. The tests preserve the real row's date.
