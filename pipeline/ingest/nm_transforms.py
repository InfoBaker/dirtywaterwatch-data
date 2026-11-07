"""New Mexico hooks for fetch blocks (docs/generic-ingesters.md; not a feed).

nm_hab_record: NMED's HABs Mapper layer (data/sources/nm-nmed-hab-mapper.yaml). Each row is one monitoring station's
latest result: HAB_Status (MONITORED, WATCH, WARNING or DANGER), the toxin tested (CHARACTERISTIC_NAME) and its value
(ReportedValue_ug_L, text such as '<0.15'), the advisory's extent in Advisory_Details (free text, some with an HTML link
to a partner's press release) and the sample's time in Last_Monitored. The hook writes the advisory text in NMED's
words (the level, then the extent with the HTML taken out; the links kept in raw._links), the toxin result
(raw._toxin) and the basis of the times; it never sets a coordinate or a status.
"""
from __future__ import annotations

import re

from ingest.generic import fieldmap as F

LINK = re.compile(r"""<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
WINDOW_BASIS = ("NMED HABs Mapper: in effect while NMED's map shows the station at WATCH, WARNING or DANGER; NMED sets "
                "no fixed period")
STARTED_BASIS = ("started_at is the time of the station's latest sample under this status (Last_Monitored); the "
                 "advisory may have begun with an earlier sample, and it is announced after the sample's results")


def details(text) -> tuple[str, list[dict]]:
    """NMED's extent text without HTML ('See BLM press release.'), and its links."""
    t = F.clean(text)
    links = [{"url": u, "text": F.clean(TAG.sub(" ", x))} for u, x in LINK.findall(t)]
    t = F.clean(TAG.sub(" ", LINK.sub(lambda m: m.group(2), t)))
    return re.sub(r"\s+([.,;:])", r"\1", t), links


@F.hook
def nm_hab_record(row: dict, rec: dict, notes: dict, ctx: F.Ctx) -> None:
    level = F.clean(row.get("HAB_Status")).upper()
    ext, links = details(row.get("Advisory_Details"))
    if ext.lower() in ("none", "null", "n/a"):
        ext = ""
    rec["advice_text"] = (f"NMED harmful algal bloom {level} advisory" + (f": {ext}" if ext else ".")) if level else None
    rec["advice_window_basis"] = WINDOW_BASIS
    if links:
        notes["_links"] = links
    toxin, value = F.clean(row.get("CHARACTERISTIC_NAME")), F.clean(row.get("ReportedValue_ug_L"))
    if toxin or value:
        notes["_toxin"] = f"{toxin or 'toxin'} {value or '(no value)'} µg/L at the latest sample"
    notes["_started_basis"] = STARTED_BASIS
