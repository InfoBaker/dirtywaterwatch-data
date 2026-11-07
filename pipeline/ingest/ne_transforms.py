"""Nebraska hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

ne_beachwatch_record: DWEE's Beach Watch layer (data/sources/ne-dwee-beachwatch.yaml), one row per weekly sample at a
public beach, mid-May to mid-September. The block reads every row of the layer; each row carries two separate
statements of the agency, and a row is a record only when one of them is made (ne_beachwatch_sequence drops the
others after reading them for the next week's statement):
  - HealthAlert 'YES' ("This beach is under health alert"): the sample's microcystin was above DWEE's and the
    Department of Health and Human Services' 8 micrograms per litre, which puts the lake on health alert and closes its
    designated beach. event_type hab_advisory, status advisory_active: the authority's own alert, as of that week's
    sample, until the agency's next sample at the station (ne_beachwatch_sequence).
  - EColiRisk 'Elevated health risk for E. coli' (E. coli above 235 per 100 mL): the layer's label, but DWEE issues no
    advisory for E. coli. event_type beach_advisory (the beach category), status unknown, raw._agency_label_only and
    raw._agency_label (the agency's words): the status build gives it the site's caution for 72 hours from the sample
    (data/rules.json unresolved.sample_caution), never the authority's advisory rule (review 2026-11-07 P2-2).
  A row with both is the health alert (hab_advisory), with the E. coli label in raw._ecoli_risk. A row with neither is
  marked raw._sample_only and is not a record.

ne_beachwatch_sequence (post): the layer is weekly and an alert holds until the next sample says otherwise, so each
alert record ends at the date of its station's next sample (review 2026-11-07 P2-3): advisory_lifted when that sample is
not on alert (raw._lifted_by names it), ended when it is (raw._continued_by: the next week's record carries the alert
on). An alert with no later sample stays advisory_active (the status build's 14-day aging is the fallback). The end is
the next sample's date, not the Friday the agency posts it, which the layer does not give. The sample-only rows are then
removed from the run's records.
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
    notes["_station"] = F.clean(row.get("StationID")).upper()
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
        rec["advice_text"] = (f"DWEE's label: \u201c{ecoli}\u201d (E. coli {ec} per 100 mL in the week's sample); the "
                              "agency issues no advisory for E. coli")
        notes["_alert_basis"] = ECOLI_RULE
        notes["_agency_label_only"] = True
        notes["_agency_label"] = ecoli
    else:
        rec["event_type"], rec["status"] = "unknown", "unknown"
        notes["_sample_only"] = True


@F.hook
def ne_beachwatch_sequence(records: list[dict], ctx: F.Ctx) -> dict:
    """Each alert ends at its station's next sample; the sample-only rows leave the run (module docstring)."""
    by_station: dict[str, list[dict]] = {}
    for r in records:
        by_station.setdefault(r["raw"].get("_station") or "", []).append(r)
    n = {"alerts_lifted": 0, "alerts_continued": 0, "alerts_open": 0, "samples_dropped": 0}
    for rows in by_station.values():
        rows.sort(key=lambda r: r.get("started_at") or "")
        for i, r in enumerate(rows):
            if r["event_type"] != "hab_advisory":
                continue
            nxt = next((x for x in rows[i + 1:] if (x.get("started_at") or "") > (r.get("started_at") or "")), None)
            if nxt is None:
                n["alerts_open"] += 1
                continue
            r["ended_at"] = nxt["started_at"]
            if nxt["event_type"] == "hab_advisory":
                r["status"], r["raw"]["_continued_by"] = "ended", nxt["source_record_id"]
                n["alerts_continued"] += 1
            else:
                r["status"], r["raw"]["_lifted_by"] = "advisory_lifted", nxt["source_record_id"]
                n["alerts_lifted"] += 1
    keep = [r for r in records if not r["raw"].get("_sample_only")]
    n["samples_dropped"] = len(records) - len(keep)
    records[:] = keep
    return n
