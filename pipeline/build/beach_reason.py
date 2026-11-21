"""Beach closures and advisories whose source gives no water-quality reason: listed, not coloured.

data/rules.json `beach_reason` (decision 40, 2026-11-17): a beach closure or advisory keeps its colour as the
authority's own when its source states a water-quality reason (a bacteria result or exceedance, sewage, an algal
bloom, a spill). One whose source states none (a closure for the season, by the beach's operator, a map label such as
Utah's "Off Season") is kept on the record and listed on its water's page and in the report tables, and colours
neither the water nor the map (build/status.py event_intervals gives it no interval; the export carries
`no_stated_reason`). Rules only, no model.

Each beach source has one entry under `sources`, by the event's source_id:
  - kind "program": the source states the reason for every record it lists (its own words, in `basis`): every
    record keeps its colour;
  - kind "fields": the record's own fields (`fields`, paths into raw; "event.<field>" reads the record itself, "[]"
    walks a list) are read, and a match of `reason_pattern` there is the stated reason; no match: listed only;
    `records` names a record whose reason the source states elsewhere (its own words, cited);
  - kind "none": the source gives no reason for any record (listed only).
A record linked to another as its duplicate (status.find_duplicates, an ingester's duplicate_of) lends its stated
reason to the record shown (RIDOH's feed gives the reason for the closure its sheet lists).
A beach source with no entry keeps its colour (as before the rule) and is named in status.json problems, so a new
source is read and given an entry before the rule touches it.
"""
from __future__ import annotations

import re
from functools import lru_cache

TYPES_DEFAULT = ("beach_closure", "beach_advisory")


def config(rules: dict | None) -> dict | None:
    """rules.json beach_reason when it is switched on, else None."""
    cfg = (rules or {}).get("beach_reason") or {}
    return cfg if cfg.get("enabled") is True else None


@lru_cache(maxsize=8)
def _pattern(p: str) -> re.Pattern:
    return re.compile(p)


def _walk(v, parts: list[str]) -> list[str]:
    if not parts:
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [x for y in v for x in _walk(y, [])]
        return []
    head, rest = parts[0], parts[1:]
    if head.endswith("[]"):
        v = v.get(head[:-2]) if isinstance(v, dict) else None
        return [x for y in (v if isinstance(v, list) else []) for x in _walk(y, rest)]
    return _walk(v.get(head) if isinstance(v, dict) else None, rest)


def field_texts(ev: dict, path: str) -> list[str]:
    """The text values at one path of a record: raw.<path>, or the record's own field for "event.<field>"."""
    if path.startswith("event."):
        return _walk(ev, path[len("event."):].split("."))
    raw = ev.get("raw") if isinstance(ev.get("raw"), dict) else {}
    return _walk(raw, path.split("."))


def applies(ev: dict, cfg: dict | None) -> bool:
    return bool(cfg) and ev.get("event_type") in (cfg.get("event_types") or TYPES_DEFAULT)


def judge(ev: dict, rules: dict | None) -> dict | None:
    """None when the rule does not apply (switched off, not a beach closure or advisory). Else {"stated": bool,
    "how": "program" | "field" | "record" | "unlisted" | "none" | "no_field_match", "basis": ...}; for a field match
    also "field" and "words" (the source's words that state it)."""
    cfg = config(rules)
    if not applies(ev, cfg):
        return None
    sid = ev.get("source_id")
    ent = (cfg.get("sources") or {}).get(sid)
    if not isinstance(ent, dict):
        return {"stated": True, "how": "unlisted", "basis": None}
    kind = ent.get("kind")
    if kind == "program":
        return {"stated": True, "how": "program", "basis": ent.get("basis")}
    if kind == "fields":
        rec = (ent.get("records") or {}).get(str(ev.get("source_record_id")))
        if isinstance(rec, dict):
            return {"stated": True, "how": "record", "basis": rec.get("basis"), "source": rec.get("source")}
        pat = _pattern(cfg.get("reason_pattern") or r"(?!x)x")
        for path in ent.get("fields") or []:
            for text in field_texts(ev, path):
                text = " ".join(text.split())        # "E.  coli", a line break inside a reason
                if pat.search(text):
                    return {"stated": True, "how": "field", "field": path, "words": text[:200]}
        return {"stated": False, "how": "no_field_match", "read": ent.get("read"), "fields": list(ent.get("fields") or [])}
    if kind == "none":
        return {"stated": False, "how": "none", "read": ent.get("read")}
    return {"stated": True, "how": "unlisted", "basis": None}


def label(ev: dict, cfg: dict) -> str:
    """The listing's words: "Beach closed; the source gives no reason" (labels.<event_type>)."""
    labels = cfg.get("labels") or {}
    return labels.get(ev.get("event_type")) or labels.get("default") or "Listed; the source gives no reason"


def note(ev: dict, verdict: dict, rules: dict) -> dict:
    """The export's `no_stated_reason` for a record listed without a colour: the listing's words, what we read for the
    reason, and the rule (its rationale is rules.json beach_reason.rationale, in out/rules.json)."""
    cfg = config(rules) or {}
    return {"rule": "beach_reason", "label": label(ev, cfg), "read": verdict.get("read"), "source": "data/rules.json"}

