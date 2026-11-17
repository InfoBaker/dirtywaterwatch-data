"""The record a Massachusetts operator's e-mail notice makes (not a feed): the shape of ingest.ma_massdep's records,
placed with its lookups (the MassDEP CSOs layer, the ECHO outfall registry, the portal waterbody crosswalk)."""
from __future__ import annotations

import re
from datetime import datetime

from common import event, parse_volume_gal, scrub_text

from .message import Mail, iso_utc

ADVICE_RE = re.compile(r"(?i)(Avoid (?:all )?contact with (?:these|the affected|affected) water ?bod(?:y|ies)[^.]*?"
                       r"(?:for|at least) (\d+) hours[^.]*\.)")
MATERIAL_RE = re.compile(r"(?i)The discharge (?:consists of|contains|may contain) ([^.]+)\.")


def place(ctx: dict, spec: dict, permit: str, num: int, suffix: str, water: str | None):
    """The outfall's point and water, trying the portal's spellings of the outfall (HOL018, HOL02, SPR015A) with the
    list's outfall_prefix; the town (the list's) narrows a name match."""
    from ingest import ma_massdep as M
    prefix = spec.get("outfall_prefix") or ""
    lay = echo = None
    for cand in (f"{prefix}{num:03d}{suffix}", f"{prefix}{num:03d}", f"{prefix}{num:02d}{suffix}",
                 f"{prefix}{num:02d}", f"{prefix}{num}{suffix}", f"{prefix}{num}"):
        lay = lay or M.layer_lookup(ctx.get("layer") or {}, cand)
        echo = echo or M.echo_lookup(ctx.get("echo") or {}, permit, cand, lay)
        if lay and echo:
            break
    texts = [("notice", water), ("outfall layer", (lay or {}).get("receiving_water"))]
    slugs, wmatch, wnote = M.resolve_water(texts, spec.get("town"), echo,
                                           ctx.get("crosswalk") or {}, ctx.get("waters") or {})
    return lay, echo, slugs, wmatch, wnote


def ma_record(mail: Mail, spec: dict, ctx: dict, n: int, *, permit: str, org: str | None, location: str,
              num: int, suffix: str, state: str, start: datetime | None, end: datetime | None,
              vol_text: str | None, water: str | None, block: str, event_type: str = "cso",
              extra_raw: dict | None = None) -> dict:
    """state: active | update | ceased. start and end are what the notice states (never the receipt time)."""
    volume_gal, _ = parse_volume_gal(vol_text) if vol_text else (None, "unknown")
    advice = ADVICE_RE.search(block)
    material = MATERIAL_RE.search(block)
    lay, echo, slugs, wmatch, wnote = place(ctx, spec, permit, num, suffix, water)
    raw = {
        "_channel": "email", "_list": mail.list_id, "_inbound_id": mail.inbound_id,
        "_received_at": mail.received_at, "_sent_at": mail.sent_at, "_notice_state": state,
        "_outfall_key": num, "_outfall_suffix": suffix, "location": scrub_text(location),
        "_tz_assumed": "America/New_York (the notice's local clock)",
        **(extra_raw or {}),
    }
    if wnote:
        raw["_water"] = wnote
    lat = lon = coord_source = None
    if lay and lay.get("lat") is not None:
        lat, lon, coord_source = round(lay["lat"], 6), round(lay["lon"], 6), "outfall_layer"
        raw["_coords"] = f"MassDEP CSOs layer DEP_OUTFL_ {lay['dep_id']} (locations are estimates)"
    elif echo and echo.get("lat") is not None:
        lat, lon, coord_source = echo["lat"], echo["lon"], "outfall_layer"
        raw["_coords"] = f"EPA ECHO CSO inventory {echo['npdes_permit']} outfall {echo['outfall']}"
    name = org or spec.get("operator_name") or None
    return event(
        source_id=spec["source_id"], source_record_id=f"{mail.inbound_id}:{n}",
        event_type=event_type, status="ongoing" if state in ("active", "update") else "ended",
        discharger_id=spec.get("operator"), discharger_name=name, npdes_permit=permit,
        outfall_id=location, outfall_name=(lay or {}).get("address"),
        waterbody_text=water, water_slugs=slugs, water_match=wmatch,
        lat=lat, lon=lon, coord_source=coord_source,
        started_at=iso_utc(start), ended_at=iso_utc(end), time_precision="minute",
        reported_at=None, published_at=mail.received_at,
        material=scrub_text(material.group(1)) if material else None,
        volume_gal=volume_gal, volume_text=vol_text, estimate_flag="estimated" if vol_text else "unknown",
        authority=f"{name or 'the operator'} (e-mail notice)",
        advice_text=scrub_text(advice.group(1)) if advice else None,
        advice_window_hours=int(advice.group(2)) if advice else None,
        advice_window_basis="the notice (314 CMR 16.04(10)(g))" if advice else None,
        source_url=spec.get("source_url"), raw=raw,
    )
