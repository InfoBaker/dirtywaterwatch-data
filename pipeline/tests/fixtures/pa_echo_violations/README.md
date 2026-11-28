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
