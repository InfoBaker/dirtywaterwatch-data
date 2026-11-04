"""Capital Region Water (Harrisburg, PA0027197) CSO status: a stub that fetches nothing.

CRW publishes per-outfall CSO status in public ArcGIS layers behind its Combined Sewer Overflow
Community Outreach App (https://capitalregionwater.com/resources/cso/): the Cityworks daily
inspection layer (58 outfalls) and the Sewer_Overflow_Alarms layer (10 real-time sites). The app's
licence says: "Unless otherwise stated, the data may not be redistributed, republished, or used for
commercial purposes without prior written permission from CRW." Until the owner has that written
permission, this module records the restriction in meta and writes no records. It makes no request.

When permission arrives: read the layers named in meta.layers (no key needed), keep the CRW
attribution ("Source: Capital Region Water - Combined Sewer Overflow Community Outreach App"), and
note that the app says it is not intended for emergency response or public notification.

Run from pipeline/: python -m ingest.pa_crw
"""
from __future__ import annotations

import sys

from common import write_events

SOURCE_ID = "pa-crw"
LICENCE = ("Unless otherwise stated, the data may not be redistributed, republished, or used for commercial "
           "purposes without prior written permission from CRW.")
META = {
    "stub": True,
    "fetches": "nothing",
    "reason": "licence bars republishing without CRW's prior written permission; the owner has not asked yet",
    "licence_text": LICENCE,
    "attribution_required": "Source: Capital Region Water - Combined Sewer Overflow Community Outreach App",
    "discharger": {"name": "Capital Region Water", "npdes_permit": "PA0027197", "outfalls": 58},
    "page": "https://capitalregionwater.com/resources/cso/",
    "layers": [
        "https://cityworks.capitalregionwater.com/cityworks_prod/gis/1/1517/rest/services/cw/FeatureServer/3",
        "https://cityworks.capitalregionwater.com/cityworks_prod/gis/1/1514/rest/services/cw/FeatureServer/3",
        "https://arcgis.capitalregionwater.com/server/rest/services/Hosted/Sewer_Overflow_Alarms/FeatureServer/0",
    ],
    "status": "awaiting permission",
}


def main() -> int:
    path = write_events(SOURCE_ID, [], ok=True, meta=META)
    print(f"pa-crw: stub, nothing fetched (licence: permission needed) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
