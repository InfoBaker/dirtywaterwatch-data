"""The record a Massachusetts operator's e-mail notice makes (not a feed): the shape of ingest.ma_massdep's records,
placed with its lookups (the MassDEP CSOs layer, the ECHO outfall registry, the portal waterbody crosswalk).

Placement is a step of its own (apply_place), since 2026-11-18: the private mail job reads and parses the mail with
ctx None (no placement; it has none of the lookups), and the public refresh places each record with ma_massdep's
lookups of that run (ingest.operator_mail.build_list). ma_record with a ctx places at once, as before; both give the
same record (tests/test_mail_feed_split.py)."""
from __future__ import annotations

import re
from datetime import datetime

from common import event, parse_volume_gal, strip_personal

from .message import PLACE_SHAPE, VOLUME_SHAPE, Mail, clean_text, iso_utc

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


def ma_record(mail: Mail, spec: dict, ctx: dict | None, n: int, *, permit: str, org: str | None, location: str,
              num: int, suffix: str, state: str, start: datetime | None, end: datetime | None,
              vol_text: str | None, water: str | None, block: str, event_type: str = "cso",
              extra_raw: dict | None = None) -> dict:
    """state: active | update | ceased. start and end are what the notice states (never the receipt time). ctx None:
    the record is not placed (apply_place does it later with the lookups). Every
    text taken from the notice passes clean_text; one that does not (a contact line under an empty label, an address,
    a phone) is set aside and only its field's name is noted (raw._fields_set_aside)."""
    aside = []

    def keep(name, v, **kw):
        out = clean_text(v, **kw)
        if v is not None and str(v).strip() and out is None:
            aside.append(name)
        return out
    vol_text = keep("volume", vol_text, shape=VOLUME_SHAPE, maxlen=40)
    water = keep("water", water, shape=PLACE_SHAPE, maxlen=80, water=True)
    volume_gal, _ = parse_volume_gal(vol_text) if vol_text else (None, "unknown")
    am, mm = ADVICE_RE.search(block), MATERIAL_RE.search(block)
    advice = keep("advice", am.group(1), maxlen=400) if am else None
    material = keep("material", mm.group(1), shape=r"[A-Za-z ,;'()/-]+", maxlen=120) if mm else None
    for k in ("volume_method", "affected_communities"):
        if k in (extra_raw or {}):
            extra_raw[k] = keep(k, extra_raw[k], maxlen=300, shape=None if k == "volume_method" else PLACE_SHAPE)
    raw = {
        "_channel": "email", "_list": mail.list_id, "_inbound_id": mail.inbound_id,
        "_received_at": mail.received_at, "_sent_at": mail.sent_at, "_notice_state": state,
        "_outfall_key": num, "_outfall_suffix": suffix, "location": location,
        "_tz_assumed": "America/New_York (the notice's local clock)",
        **(extra_raw or {}),
    }
    if aside:
        raw["_fields_set_aside"] = sorted(set(aside))
    name = org or spec.get("operator_name") or None
    rec = event(
        source_id=spec["source_id"], source_record_id=f"{mail.inbound_id}:{n}",
        event_type=event_type, status="ongoing" if state in ("active", "update") else "ended",
        discharger_id=spec.get("operator"), discharger_name=name, npdes_permit=permit,
        outfall_id=location, waterbody_text=water,
        started_at=iso_utc(start), ended_at=iso_utc(end), time_precision="minute",
        reported_at=None, published_at=mail.received_at,
        material=material,
        volume_gal=volume_gal, volume_text=vol_text, estimate_flag="estimated" if vol_text else "unknown",
        authority=f"{name or 'the operator'} (e-mail notice)",
        advice_text=advice,
        advice_window_hours=int(am.group(2)) if advice else None,
        advice_window_basis="the notice (314 CMR 16.04(10)(g))" if advice else None,
        source_url=spec.get("source_url"), raw=raw,
    )
    if ctx is not None:
        apply_place(rec, spec, ctx)
    return rec


PLACE_RAW = ("_water", "_fields_set_aside", "_coords")      # the raw notes placement writes, in ma_record's order


def apply_place(rec: dict, spec: dict, ctx: dict) -> dict:
    """Place a record ma_record made (with or without a ctx) with the lookups in ctx: the outfall's point and name, its
    water's slugs and how it was matched, raw._water and raw._coords. Everything placement sets is set again, so a
    record placed under other lookups comes out as ma_record would make it under these. The inputs are what the
    notice said and ma_record kept: the permit, the outfall number and suffix (raw._outfall_key, _outfall_suffix) and
    the water (waterbody_text). Changes rec in place and returns it."""
    raw = rec.get("raw") or {}
    lay, echo, slugs, wmatch, wnote = place(ctx, spec, rec.get("npdes_permit"), raw.get("_outfall_key"),
                                            raw.get("_outfall_suffix"), rec.get("waterbody_text"))
    lat = lon = coord_source = coords = None
    if lay and lay.get("lat") is not None:
        lat, lon, coord_source = round(lay["lat"], 6), round(lay["lon"], 6), "outfall_layer"
        coords = f"MassDEP CSOs layer DEP_OUTFL_ {lay['dep_id']} (locations are estimates)"
    elif echo and echo.get("lat") is not None:
        lat, lon, coord_source = echo["lat"], echo["lon"], "outfall_layer"
        coords = f"EPA ECHO CSO inventory {echo['npdes_permit']} outfall {echo['outfall']}"
    new = {k: v for k, v in raw.items() if k not in PLACE_RAW}
    for k, v in (("_water", wnote or None), ("_fields_set_aside", raw.get("_fields_set_aside")), ("_coords", coords)):
        if v:
            new[k] = v if k == "_fields_set_aside" else strip_personal(v)    # as common.event scrubs raw
    rec["raw"] = new
    rec.update(outfall_name=(lay or {}).get("address"), water_slugs=slugs, water_match=wmatch, lat=lat, lon=lon,
               coord_source=coord_source)
    return rec
