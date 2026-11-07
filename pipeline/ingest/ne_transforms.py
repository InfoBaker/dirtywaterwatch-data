"""Nebraska hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

ne_beachwatch_record: DWEE's Beach Watch layer (data/sources/ne-dwee-beachwatch.yaml), one row per weekly sample at a
public beach, mid-May to mid-September. Each row carries two separate statements of the agency, and a row is a record
only when one of them is made (the block's where clause asks only for those rows):
  - HealthAlert 'YES' ("This beach is under health alert"): the sample's microcystin was above DWEE's and the
    Department of Health and Human Services' 8 micrograms per litre, which puts the lake on health alert and closes its
    designated beach. event_type hab_advisory, status advisory_active: the authority's own alert, as of that week's
    sample (the next week's row is the next statement; the layer gives no lift time, so no end is written).
  - EColiRisk 'Elevated health risk for E. coli' (E. coli above 235 per 100 mL): the layer's label, but DWEE issues no
    advisory for E. coli. event_type beach_advisory, status unknown: the site's caution, never the authority's red.
  A row with both is the health alert (hab_advisory), with the E. coli label in raw._ecoli_risk. A row with neither
  (read from a saved copy of the whole layer) keeps event_type unknown and a parse_error saying so.
The sample date (ActivityStartDate) is stored as an epoch at midnight Central time (05:00 UTC in summer), a date with
no time of day; the reader's midnight: date knows only UTC midnight, so the hook writes a Central-midnight value as the
date, precision day (raw._date_basis). A value at any other time stays the time it is.
"""
from __future__ import annotations

import re

from ingest.generic import fieldmap as F

ALERT_RULE = ("DWEE and DHHS: a microcystin result above 8 micrograms per litre puts the lake on health alert and "
              "closes its designated beach")
ECOLI_RULE = "DWEE: E. coli above 235 per 100 mL is an elevated health risk; no advisory is issued for E. coli"


@F.hook
def ne_beachwatch_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    st = rec.get("started_at") or ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00[+-]0[56]:00", st):
        rec["started_at"], rec["time_precision"] = st[:10], "day"
        notes["_date_basis"] = "ActivityStartDate is stored as midnight Central time: read as the sample date"
    alert = F.clean(row.get("HealthAlert")).upper() == "YES"
    ecoli = F.clean(row.get("EColiRisk"))
    micro, ec = F.clean(row.get("Microcystin")), F.clean(row.get("EColi"))
    if ecoli:
        notes["_ecoli_risk"] = ecoli
    if alert:
        rec["event_type"], rec["status"] = "hab_advisory", "advisory_active"
        rec["advice_text"] = (F.clean(row.get("HealthDescription")) or "This beach is under health alert") + \
            (f" (microcystin {micro} micrograms per litre in the week's sample)" if micro else "")
        notes["_alert_basis"] = ALERT_RULE
    elif ecoli:
        rec["event_type"], rec["status"] = "beach_advisory", "unknown"
        rec["advice_text"] = f"{ecoli} (E. coli {ec} per 100 mL in the week's sample); no advisory issued"
        notes["_alert_basis"] = ECOLI_RULE
    else:
        rec["event_type"], rec["status"] = "unknown", "unknown"
        notes.setdefault("_problems", []).append("the row is neither a health alert nor an elevated E. coli result")
