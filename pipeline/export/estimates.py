"""Figures we work out from a source's own record, labelled as ours with their basis (owner, 2026-11-21; site
docs/decisions.md items 47 and 48), and the rate a source states, kept as a value.

    rate_of(e)             -> dict | None   the rate the source states ("75 Gallons per Minute Estimated"), as a value:
                                            {text, unit, low, high, bound?, qualifier?}; the source's own figure
    volume_estimate_of(e)  -> dict | None   our computed volume: {gallons | low, high | low/high with bound, basis,
                                            formula, inputs}
    end_estimate_of(e)     -> dict | None   our estimated end: {at, precision, basis, inputs}
    estimates_of(e)        -> dict          the three above that apply (export/detail.py enrich writes them)

The rules, all of them:
  - Every input comes from the record itself: the rate and the duration it states, its own start and end. None is
    assumed, and a record whose source is not in SOURCES gets nothing.
  - A computed volume is rate x duration. It is written to `volume_estimate`, never to `volume_gal`, and a stated total
    wins: a record that gives a volume gets none, and export/detail.py drops it where a later record of the same event
    gives one (`later_volume`).
  - A range of rates gives a range of volumes; a "more than" or "at least" rate a lower bound; a "less than" rate an
    upper bound. A rate or a duration of zero gives no estimate (a computed zero would read as no discharge). Figures
    are whole gallons, a limit rounded outward (never a stronger claim than the arithmetic), and a figure under one
    gallon is "less than 1 gallon". The arithmetic keeps the duration's fractions; the words show them to a tenth.
  - A figure that says two things gives none: "60,000 gallons" typed under the form's "Gallons per Minute".
  - The duration: the time between the record's own start and end, both to the minute, where the record gives an end
    the source reported; else a duration the record states as a number ("4 Hours - Ongoing", "2 hours 30 min"); free
    text ("ongoing", "all day", "intermittent 2", "unknown") gives none. A duration over MAX_DAYS gives none (a typing
    error is likelier than a month-long overflow at one rate).
  - An estimated end only where the record gives no end: its start plus the duration it states (common.end_after, so a
    start known only to the day gives a day, never a clock time). The status rules do not read it: the map's windows,
    ageing and colours are unchanged.
  - Where a record's own ended_at is one the pipeline worked out (ny_sprtk_web: start + duration on an ENDED notice),
    `ended_at_ours` gives its basis, so the end is shown as ours; the end itself and the status are unchanged.
  - The basis is a sentence for the public: what we did, with the inputs, in the editors' guide's voice ("we", "our").

A source is added with a reader in SOURCES that says where its rate, duration and end come from.
"""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime, timedelta

from common import end_after

MAX_DAYS = 31

# ------------------------------------------------------------------------------------------------ the rate

# NY-Alert's quantity field (DEC's SPRTK workbook and its web page): the notifier's figure as typed, then the unit picked
# on the form ("Gallons per Minute" or "Gallons") and "Estimated" or "Actual"
NY_QTY = re.compile(r"^(?P<fig>.*?)\s*(?P<unit>Gallons per Minute|Gallons)\s+(?P<flag>Estimated|Actual)\s*$")
_N = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
_APPROX = r"(?:(?:approximately|approx\.?|apprx\.?|about|around|roughly|est\.?|estimated(?:\s+at)?|~)\s*)?"
_UNIT_WORDS = {
    "gallons per minute": ("gpm", r"gpm|g\.p\.m\.?|gallons?\s*(?:per|a|/)\s*min(?:ute)?|gal\s*/\s*min"),
    "gallons per hour": ("gph", r"gph|gallons?\s*(?:per|an|/)\s*h(?:ou)?r"),
    "million gallons per day": ("mgd", r"mgd|million\s+gallons?\s*(?:per|a|/)\s*day"),
    "gallons per day": ("gpd", r"gpd|gallons?\s*(?:per|a|/)\s*day|per\s+day"),
    "gallons": ("gal", r"gallons?|gal\.?"),
}
_UNIT_RE = "|".join(f"(?P<{k}>{rx})" for k, rx in _UNIT_WORDS.values())
_RATE_FIG = re.compile(
    rf"^{_APPROX}(?:(?P<lo>{_N})\s*(?:-|–|to)\s*(?P<hi>{_N})|(?P<one>{_N})\s*(?P<plus>\+)?"
    rf"|(?P<more>>|more than|over|greater than)\s*(?P<more_n>{_N})|(?P<least>at least|minimum(?: of)?)\s*(?P<least_n>{_N})"
    rf"|(?P<less><|less than|under)\s*(?P<less_n>{_N}))\s*(?:{_UNIT_RE})?\s*$", re.I)
PER_MINUTE = {"gpm": 1.0, "gph": 1 / 60, "gpd": 1 / 1440, "mgd": 1_000_000 / 1440}
UNIT_NAME = {"gpm": "gallons per minute", "gph": "gallons per hour", "gpd": "gallons per day",
             "mgd": "million gallons per day"}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _clean_num(v: float) -> int | float:
    return int(v) if v == int(v) else v


def parse_ny_rate(text) -> dict | None:
    """A NY-Alert quantity that is a rate -> {text, unit, low, high, bound?, qualifier}; None for a total, a figure
    with other words in it ("6 inch pump rated at 200 gpm"), or no figure ("unknown")."""
    if not isinstance(text, str) or not text.strip():
        return None
    s = " ".join(text.split())
    m = NY_QTY.match(s)
    if not m:
        return None
    fig, form_unit, flag = m.group("fig").strip(), m.group("unit"), m.group("flag").lower()
    f = _RATE_FIG.match(fig)
    if not f:
        return None
    unit = next((k for k in ("gpm", "gph", "mgd", "gpd") if f.group(k)), None)
    if unit is None:
        # "500 gallons" under "Gallons" is a total; "60,000 gallons" under "Gallons per Minute" says two things (a total
        # typed under the rate unit, or a rate with "gallons" for its unit): no value of ours from either (review 4)
        if form_unit != "Gallons per Minute" or f.group("gal"):
            return None
        unit = "gpm"                                     # a bare figure under the form's "Gallons per Minute"
    out: dict = {"text": s, "unit": UNIT_NAME[unit]}
    if f.group("lo"):
        lo, hi = _num(f.group("lo")), _num(f.group("hi"))
        if lo > hi:
            return None
        out.update(low=_clean_num(lo), high=_clean_num(hi))
    elif f.group("one"):
        v = _clean_num(_num(f.group("one")))
        if f.group("plus"):
            out.update(low=v, bound="at_least")
        else:
            out.update(low=v, high=v)
    elif f.group("more"):
        out.update(low=_clean_num(_num(f.group("more_n"))), bound="more_than")
    elif f.group("least"):
        out.update(low=_clean_num(_num(f.group("least_n"))), bound="at_least")
    else:
        out.update(high=_clean_num(_num(f.group("less_n"))), bound="less_than")
    out["qualifier"] = flag                              # the source's word: "estimated" or "actual"
    return out


# ------------------------------------------------------------------------------------------------ the duration

# NY-Alert's duration field: the notifier's figure as typed, the unit picked on the form, and "- Ongoing" or "- Ended"
# (the workbook; the web page's message gives the figure and the unit only)
NY_DUR = re.compile(r"^(?P<fig>.*?)\s*(?P<unit>Hours|Minutes)?(?:\s*-\s*(?P<state>Ongoing|Ended))?\s*$")
_H = r"(?:hours?|hrs?\.?|h)"
_M = r"(?:minutes?|mins?\.?|m)"
_D = r"(?:days?)"
_DUR_FIG = re.compile(
    rf"^{_APPROX}(?:(?P<hh>\d{{1,3}}):(?P<mm>[0-5]\d)"
    rf"|(?:(?P<d>{_N})\s*{_D})?\s*,?\s*(?:and\s+)?(?:(?P<h>{_N})\s*{_H})?\s*,?\s*(?:and\s+)?(?:(?P<m>{_N})\s*{_M})?"
    rf"|(?P<bare>{_N}))\s*$", re.I)


def parse_ny_duration(text) -> tuple[float | None, str | None]:
    """(minutes, state) of a NY-Alert duration: "4 Hours - Ongoing" -> (240, "ongoing"); "3 hours and 50 minutes Hours -
    Ended" -> (230, "ended"); "05:30 Hours - Ended" -> (330, "ended"); free text -> (None, state)."""
    if not isinstance(text, str) or not text.strip():
        return None, None
    s = " ".join(text.split())
    m = NY_DUR.match(s)
    if not m:
        return None, None
    state = (m.group("state") or "").lower() or None
    fig, unit = m.group("fig").strip(), m.group("unit")
    f = _DUR_FIG.match(fig) if fig else None
    if not f:
        return None, state
    if f.group("hh") is not None:
        mins = int(f.group("hh")) * 60 + int(f.group("mm"))
    elif f.group("bare") is not None:
        if not unit:
            return None, state                            # a number with no unit at all
        mins = _num(f.group("bare")) * (60 if unit == "Hours" else 1)
    elif any(f.group(k) for k in ("d", "h", "m")):
        mins = (_num(f.group("d") or "0") * 1440 + _num(f.group("h") or "0") * 60 + _num(f.group("m") or "0"))
    else:
        return None, state
    return float(mins), state


# ------------------------------------------------------------------------------------------------ the sources


def _row_value(raw: dict, *names: str):
    """The first of the workbook row's columns named (header compared without case or punctuation)."""
    row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
    want = {re.sub(r"[^a-z0-9]", "", n.lower()) for n in names}
    for k, v in row.items():
        if re.sub(r"[^a-z0-9]", "", str(k).lower()) in want and isinstance(v, str) and v.strip():
            return v
    return None


def _ny_workbook(e: dict, raw: dict) -> dict:
    # the workbook's own end: ny_sprtk sets ended_at only from a Close notice's or an "Ended" duration's end time
    return {"noun": "notice", "rate_text": _row_value(raw, "quantity", "quantityVolume", "Quantity/Volume"),
            "duration_text": _row_value(raw, "dischargeDuration", "duration"), "own_end": True}


def _ny_web(e: dict, raw: dict) -> dict:
    parsed = raw.get("parsed") if isinstance(raw.get("parsed"), dict) else {}
    # the web record's ended_at is start + its duration (ny_sprtk_web, raw._ended_at_basis "computed"): not an own end
    return {"noun": "notice", "rate_text": parsed.get("volume"), "duration_text": parsed.get("duration"),
            "own_end": False}


def _ny_web_computed_end(e: dict, raw: dict) -> bool:
    """Whether the web record's ended_at is ny_sprtk_web's start + duration (an ENDED notice gives no end time)."""
    return bool(e.get("ended_at")) and str(raw.get("_ended_at_basis") or "").startswith("computed")


def _duration_hours_input(e: dict, value, field: str) -> dict:
    """Preserve the source value and its citation; add hours only to a bare number in an hours field."""
    text = str(value).strip() if value is not None and not isinstance(value, bool) else ""
    if re.fullmatch(_N, text):
        text += " hours"
    return {"duration_text": text, "duration_field": field, "duration_value": value,
            "duration_field_unit": "hours", "source_record_id": e.get("source_record_id"), "source_url": e.get("source_url")}


def _ct_archive(e: dict, raw: dict) -> dict:
    # Both frozen layers' numeric durations are hours (checked against their start/stop intervals).
    field, stop = ("CSO_DURATION", "STOP_FLOW_DATETIME") if "CSO_DURATION" in raw else ("DURATION", "STOP_DATETIME")
    inp = _duration_hours_input(e, raw.get(field), field)
    inp["source_end_given"] = raw.get(stop) is not None
    return inp


def _wa_ecology(e: dict, raw: dict) -> dict:
    row = raw.get("row") if isinstance(raw.get("row"), dict) else {}
    inp = _duration_hours_input(e, row.get("final_event_duration_hours"), "row.final_event_duration_hours")
    inp["source_end_given"] = row.get("end_event_timedate") is not None
    # Active-flow duration need not span intermittent releases. Midnight starts may be day-only.
    if str(row.get("was_the_spill_continuous") or "").strip().lower() == "intermittent" or raw.get("_start_at_midnight"):
        inp["duration_text"] = None
    return inp


SOURCES = {
    "ct-deep-archive": {"inputs": _ct_archive, "duration": parse_ny_duration},
    "wa-ecology-sewage-spills": {"inputs": _wa_ecology, "duration": parse_ny_duration},
    "ny-dec-sprtk": {"inputs": _ny_workbook, "rate": parse_ny_rate, "duration": parse_ny_duration},
    "ny-dec-sprtk-web": {"inputs": _ny_web, "rate": parse_ny_rate, "duration": parse_ny_duration,
                         "computed_end": _ny_web_computed_end},
}


# ------------------------------------------------------------------------------------------------ words


def fmt_num(v: float) -> str:
    v = _clean_num(round(v, 6))
    return f"{v:,}" if isinstance(v, int) else f"{v:,.6f}".rstrip("0").rstrip(".")


def rate_words(rate: dict) -> str:
    one = rate.get("low") == rate.get("high") == 1 and not rate.get("bound")
    u = rate["unit"].replace("gallons per", "gallon per", 1) if one and rate["unit"].startswith("gallons") else rate["unit"]
    b = rate.get("bound")
    if b == "more_than":
        return f"more than {fmt_num(rate['low'])} {u}"
    if b == "at_least":
        return f"at least {fmt_num(rate['low'])} {u}"
    if b == "less_than":
        return f"less than {fmt_num(rate['high'])} {u}"
    if rate["low"] == rate["high"]:
        return f"{fmt_num(rate['low'])} {u}"
    return f"{fmt_num(rate['low'])} to {fmt_num(rate['high'])} {u}"


def duration_words(minutes: float) -> str:
    """"14 hours, 35 minutes"; a part of a minute kept to a tenth ("1.5 minutes", "2 hours, 0.9 minutes"), so the words
    give the figure the arithmetic used (review 5)."""
    tenths = int(round(minutes * 10))
    h, rem = divmod(tenths, 600)
    m = rem / 10
    mw = f"{_clean_num(m)} minute{'' if m == 1 else 's'}" if m else ""
    parts = ([f"{h:,} hour{'' if h == 1 else 's'}"] if h else []) + ([mw] if mw else [])
    return ", ".join(parts) or "0 minutes"


def _time(v) -> datetime | None:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        t = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


# ------------------------------------------------------------------------------------------------ the figures


def _spec(e: dict):
    spec = SOURCES.get(e.get("source_id") or "")
    raw = e.get("raw") if isinstance(e.get("raw"), dict) else {}
    if not spec or not raw:
        return None, None
    return spec, spec["inputs"](e, raw)


def rate_of(e: dict) -> dict | None:
    """The rate the record's source states, as a value (the source's own figure; never converted)."""
    spec, inp = _spec(e)
    if not spec or not inp.get("rate_text"):
        return None
    return spec["rate"](inp["rate_text"])


def _start_ok(e: dict) -> datetime | None:
    """The record's start, when it is a start the record gives (not an upper bound, not a start in the future as
    published)."""
    from build import status as status_mod        # here: build.status reads the rules at import
    st = _time(e.get("started_at"))
    if st is None or e.get("started_at_bound") or status_mod.start_bound(e):
        return None
    fetched = _time(e.get("fetched_at"))
    if fetched is not None and st > fetched + timedelta(hours=24):
        return None
    return st


# two durations of one record differ when they are more than both of these apart (a typing error in one of them)
DIFFER_MINUTES = 15
DIFFER_SHARE = 0.10


def _stated(spec: dict, inp: dict) -> dict | None:
    """{minutes, from, text} of the duration the record states as a number, or None."""
    text = inp.get("duration_text")
    mins, state = spec["duration"](text) if text else (None, None)
    if mins is None or not 0 < mins <= MAX_DAYS * 1440:
        return None
    how = {"ongoing": "expected", "ended": "reported"}.get(state or "", "given")
    return {"minutes": mins, "from": f"duration_{how}", "text": " ".join(str(text).split())}


def _span(e: dict, inp: dict) -> dict | None:
    """{minutes, from, started_at, ended_at} between the record's own start and an end the source reported, both to the
    minute, or None."""
    st, en = _start_ok(e), _time(e.get("ended_at"))
    if not (inp.get("own_end") and st is not None and en is not None and e.get("time_precision") == "minute"
            and e.get("ended_at_precision") in (None, "minute")):
        return None
    mins = (en.astimezone(UTC) - st.astimezone(UTC)).total_seconds() / 60
    if not 0 < mins <= MAX_DAYS * 1440:
        return None
    return {"minutes": mins, "from": "start_to_end", "started_at": e.get("started_at"), "ended_at": e.get("ended_at")}


def _duration(e: dict, spec: dict, inp: dict) -> dict | None:
    """The duration a computed volume uses: the time between the record's own start and end; where the record also
    reports a duration that differs from it (DIFFER_*), both, as {low, high, span, stated}; else the duration the
    record states. A duration the record only expects is not set against a reported end."""
    span, stated = _span(e, inp), _stated(spec, inp)
    if span and stated and stated["from"] == "duration_reported":
        a, b = span["minutes"], stated["minutes"]
        if abs(a - b) > DIFFER_MINUTES and abs(a - b) > DIFFER_SHARE * max(a, b):
            return {"low": min(a, b), "high": max(a, b), "from": "start_to_end_and_duration", "span": span, "stated": stated}
    return span or stated


SHORT = {"duration_expected": "expected", "duration_reported": "reported", "duration_given": "given"}
EXPECTS = {"duration_expected": "the expected duration the {noun} gives", "duration_reported": "the duration the {noun} reports",
           "duration_given": "the duration the {noun} gives"}
BY = {"duration_expected": "the expected duration it gives", "duration_reported": "the duration it reports",
      "duration_given": "the duration it gives"}


def volume_estimate_of(e: dict) -> dict | None:
    """Our computed volume (rate x duration, both from the record), or None. A record that states a volume gets none."""
    if e.get("volume_gal") is not None:
        return None
    spec, inp = _spec(e)
    if not spec:
        return None
    rate = spec["rate"](inp["rate_text"]) if inp.get("rate_text") else None
    if not rate:
        return None
    lo, hi, b = rate.get("low"), rate.get("high"), rate.get("bound")
    if (lo is not None and lo <= 0) or (hi is not None and hi <= 0):
        return None
    dur = _duration(e, spec, inp)
    if not dur:
        return None
    per_min = PER_MINUTE[next(k for k, v in UNIT_NAME.items() if v == rate["unit"])]
    d_lo, d_hi = (dur["low"], dur["high"]) if "low" in dur else (dur["minutes"], dur["minutes"])
    gal = lambda r, m: r * per_min * m   # noqa: E731
    # whole gallons, rounded outward where a figure is a limit, so the claim is never stronger than the arithmetic; a
    # figure under one gallon is "less than 1 gallon", never zero (review 2)
    out: dict = {}
    if b in ("more_than", "at_least"):
        x = math.floor(gal(lo, d_lo))
        if x < 1:
            return None
        out.update(low=x, bound=b)
    elif b == "less_than":
        out.update(high=math.ceil(gal(hi, d_hi)), bound=b)
    elif lo == hi and d_lo == d_hi:
        x = gal(lo, d_lo)
        if x >= 1:
            out["gallons"] = int(round(x))
        else:
            out.update(high=1, bound="less_than")
    else:
        x_lo, x_hi = gal(lo, d_lo), gal(hi, d_hi)
        if x_lo >= 1:
            out.update(low=math.floor(x_lo), high=math.ceil(x_hi))
        else:
            out.update(high=math.ceil(x_hi), bound="less_than")
    noun = inp.get("noun") or "report"
    rw = rate_words(rate)
    what = "the rate range" if (lo is not None and hi is not None and lo != hi and not b) else "the rate"
    if dur["from"] == "start_to_end_and_duration":
        sp, sd = dur["span"], dur["stated"]
        out["basis"] = (f"The {noun}'s start and end times are {duration_words(sp['minutes'])} apart, and the duration it "
                        f"reports is {duration_words(sd['minutes'])}. We multiplied {what} it gives, {rw}, by each.")
    elif dur["from"] == "start_to_end":
        out["basis"] = (f"We multiplied {what} the {noun} gives, {rw}, by the {duration_words(dur['minutes'])} between its "
                        "start and end times.")
    else:
        out["basis"] = f"We multiplied {what} the {noun} gives, {rw}, by {BY[dur['from']]}, {duration_words(dur['minutes'])}."
    # the same in short, for a report table's cell: the inputs, so the figure can be checked there too (review 9)
    if dur["from"] == "start_to_end_and_duration":
        out["basis_short"] = (f"{rw} × {duration_words(dur['stated']['minutes'])} reported, or × "
                              f"{duration_words(dur['span']['minutes'])} from start to end")
    elif dur["from"] == "start_to_end":
        out["basis_short"] = f"{rw} × {duration_words(dur['minutes'])} from start to end"
    else:
        out["basis_short"] = f"{rw} × {duration_words(dur['minutes'])} {SHORT[dur['from']]}"
    out["formula"] = "rate × duration"
    inputs: dict = {"rate": {k: rate[k] for k in ("text", "unit", "low", "high", "bound", "qualifier") if rate.get(k) is not None},
                    "duration_from": dur["from"]}
    if "low" in dur:
        inputs.update(duration_minutes_low=_clean_num(round(d_lo, 2)), duration_minutes_high=_clean_num(round(d_hi, 2)),
                      duration_text=dur["stated"]["text"], started_at=dur["span"]["started_at"], ended_at=dur["span"]["ended_at"])
    else:
        inputs["duration_minutes"] = _clean_num(round(dur["minutes"], 2))
        if dur.get("text"):
            inputs["duration_text"] = dur["text"]
        if dur["from"] == "start_to_end":
            inputs.update(started_at=dur["started_at"], ended_at=dur["ended_at"])
    out["inputs"] = inputs
    return out


def end_estimate_of(e: dict) -> dict | None:
    """Our estimated end (the record's start plus the duration it states), only where the record gives no end."""
    if e.get("ended_at"):
        return None
    spec, inp = _spec(e)
    if not spec or inp.get("source_end_given"):
        return None
    st = _start_ok(e)
    if st is None or e.get("time_precision") not in ("minute", "day"):
        return None
    dur = _stated(spec, inp)
    if not dur:
        return None
    end, _ = end_after(st, timedelta(minutes=dur["minutes"]), e.get("time_precision"))
    prec = "minute" if e.get("time_precision") == "minute" else "day"
    noun = inp.get("noun") or "report"
    what = EXPECTS[dur["from"]].format(noun=noun)
    dw = duration_words(dur["minutes"])
    if prec == "minute":
        basis = f"We added {what}, {dw}, to its start time."
        at = end.isoformat(timespec="seconds")
    else:
        basis = (f"We added {what}, {dw}, to the day it gives as the start. The {noun} gives no time of day, so this is "
                 "the last day the duration allows.")
        at = end.date().isoformat()
    out = {"at": at, "precision": prec, "basis": basis, "basis_short": f"start + {dw} {SHORT[dur['from']]}",
           "inputs": {"started_at": e.get("started_at"), "duration_minutes": _clean_num(round(dur["minutes"], 2)),
                      "duration_from": dur["from"], "duration_text": dur["text"]}}
    if inp.get("duration_field"):
        out["formula"] = "start + stated duration"
        out["inputs"].update({k: inp[k] for k in ("duration_field", "duration_value", "duration_field_unit",
                                                "source_record_id", "source_url")})
    return out


def ended_at_ours_of(e: dict) -> dict | None:
    """{basis} where the record's own ended_at is one the pipeline worked out (ny_sprtk_web: start + the duration an ENDED
    notice gives), so it is shown as our estimate, not as the source's end (review 3). The status build reads that end
    as before; only its label changes."""
    spec, inp = _spec(e)
    if not spec or not spec.get("computed_end") or not spec["computed_end"](e, e.get("raw") or {}):
        return None
    dur = _stated(spec, inp)
    if not dur:
        return {"basis": f"We worked out this end from the {inp.get('noun') or 'report'}'s start and the duration it gives.",
                "basis_short": "start + duration given"}
    return {"basis": f"We added {EXPECTS[dur['from']].format(noun=inp.get('noun') or 'report')}, "
                     f"{duration_words(dur['minutes'])}, to its start time.",
            "basis_short": f"start + {duration_words(dur['minutes'])} {SHORT[dur['from']]}"}


def estimates_of(e: dict) -> dict:
    out = {}
    for k, fn in (("volume_estimate", volume_estimate_of), ("end_estimate", end_estimate_of), ("ended_at_ours", ended_at_ours_of)):
        try:
            v = fn(e)
        except Exception:  # noqa: BLE001 - an odd value never stops the export; the figure is left out
            v = None
        if v:
            out[k] = v
    return out
