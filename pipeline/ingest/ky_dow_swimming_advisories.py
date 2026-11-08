"""Kentucky's standing swimming advisories (the Division of Water with the Division of Public Health Protection and
Safety) -> data/build/events/ky-dow-swimming-advisories.json.

Source
  https://eec.ky.gov/Environmental-Protection/Water/Monitor/Pages/Swimming-Advisories.aspx (registry
  ky-dow-swimming-advisories; research/ky/report.md section 2.5). The page says the agencies "agree that swimming
  advisories that have been in place for several years in different areas of the state because of high levels of E.
  coli bacteria should remain in effect until further notice", that "People should avoid recreational contact with
  waters in the areas specified because of the bacteria, which occur in human and animal waste and indicate the
  presence of untreated or inadequately treated sewage", and lists the areas under "Swimming advisories remain in
  effect for the following:" (Upper Cumberland River, Kentucky River, Licking River), before its general advice on
  "Residential and Agricultural Areas". Prose with no dates and no table. The page gives no date of its own (no
  modified date was found on 2026-11-07), so no start date is invented.

Records (a standing list read as a snapshot; review 2026-11-08 P1-1)
  - One record per named stretch or water the list gives (STRETCHES: the rule that finds each in the list's text, the
    water the record is placed on, the stretch in the page's words). event_type beach_advisory (the agencies' E. coli
    advisory for recreational contact; the category is an owner question), status advisory_active, the agencies'
    own words in advice_text, raw.listed_text the page's sentence.
  - started_at is the first poll that found it on the page (time_precision poll); raw.start_basis says the
    advisories have stood "for several years" with no date given. reported_at, published_at and source_updated_at
    stay null (the page gives none); raw._last_seen_in_source is the latest poll that listed it, so the status build
    keeps it red while the page lists it.
  - A stretch no longer found in a list the module could read is lifted at that poll (advisory_lifted, ended_at the
    poll, raw.ended_at_precision "poll"). A page whose list cannot be found (the heading or the "Residential" section
    missing) is ok=False: the records are kept and nothing is lifted.
  - A sentence of the list no rule recognises is kept as an "unknown" record with parse_error, so a new advisory is
    seen and never dropped.
  - Placement by rules only: waterbody_text is the named water (the national list's spelling where it holds it), no
    point and no geocoding; on a river or stream the status build shows a marker, never a whole-water colour. The
    stretch's ends are in raw.stretch_text; drawing the stretch needs a public point for each end (not yet).
  Privacy: the page's contact block (a staff member) lies outside the list and is never read or saved; only the list's
  text is saved to data/raw/, and only when it changes.

Run from pipeline/: python -m ingest.ky_dow_swimming_advisories [--file saved.html] [--at 2026-11-07T12:00:00Z]
Cadence: daily is enough (the list changes rarely); it runs with the refresh.
"""
from __future__ import annotations

import hashlib
import html as htmllib
import json
import re
import sys
from pathlib import Path

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "ky-dow-swimming-advisories"
URL = "https://eec.ky.gov/Environmental-Protection/Water/Monitor/Pages/Swimming-Advisories.aspx"
STATE_PATH = BUILD_DIR / "ky-dow-swimming-advisories-state.json"
AUTHORITY = ("Kentucky Division of Water and Division of Public Health Protection and Safety (standing swimming "
             "advisories)")
START = re.compile(r"Swimming advisories remain in effect for the following", re.I)
END = re.compile(r"Residential and Agricultural Areas", re.I)
ADVICE = ("Kentucky Division of Water and Division of Public Health Protection and Safety: “People should avoid "
          "recreational contact with waters in the areas specified because of the bacteria, which occur in human and "
          "animal waste and indicate the presence of untreated or inadequately treated sewage.” The advisories "
          "“have been in place for several years” and “should remain in effect until further notice.”")
START_BASIS = ("the first read of the agencies' page that listed it: the page gives no date, and says the advisories "
               "have been in place \"for several years\"; the advisory began long before this date")
WINDOW_BASIS = "in effect \"until further notice\" (the agencies' page): shown while the page lists it"
# (key, the rule that finds it in the list's text, the water placed on, the stretch in the page's words, area)
STRETCHES = [
    ("cumberland-four-mile-bridge-to-pineville", r"Cumberland River from Four Mile Bridge[^.]*?to Pineville",
     "Cumberland River", "from Four Mile Bridge (Highway 2014) to Pineville at the Highway 66 Bridge",
     "Upper Cumberland River"),
    ("cumberland-wallins-creek-bridge-to-harlan", r"from Wallins Creek Bridge[^.]*?to Harlan", "Cumberland River",
     "from Wallins Creek Bridge (Highway 219) to Harlan", "Upper Cumberland River"),
    ("martins-fork-harlan-to-cawood", r"Martins Fork Cumberland River from Harlan to the Cawood Water Plant",
     "Martins Fork Cumberland River", "from Harlan to the Cawood Water Plant", "Upper Cumberland River"),
    ("catron-creek", r"All of Catron Creek", "Catron Creek", "all of it", "Upper Cumberland River"),
    ("clover-fork", r"all of Clover Fork", "Clover Fork of the Cumberland River", "all of it",
     "Upper Cumberland River"),
    ("straight-creek", r"all of Straight Creek", "Straight Creek", "all of it", "Upper Cumberland River"),
    ("poor-fork-harlan-to-looney-creek", r"Poor Fork from Harlan to Looney Creek",
     "Poor Fork of the Cumberland River", "from Harlan to Looney Creek", "Upper Cumberland River"),
    ("looney-creek-mouth-to-lynch", r"Looney Creek from the mouth to Lynch Water Plant Bridge", "Looney Creek",
     "from the mouth to the Lynch Water Plant Bridge", "Upper Cumberland River"),
    ("north-fork-kentucky-above-chavies", r"North Fork of the Kentucky River upstream of Chavies",
     "North Fork of Kentucky River", "upstream of Chavies", "Kentucky River"),
    ("licking-banklick-to-ohio", r"Banklick Creek to the confluence with the Ohio River", "Licking River",
     "from Banklick Creek to the confluence with the Ohio River", "Licking River"),
    ("banklick-creek", r"includes all of Banklick Creek", "Banklick Creek", "all of it", "Licking River"),
    ("three-mile-creek", r"includes all of Banklick Creek and Three Mile Creek", "Three Mile Creek", "all of it",
     "Licking River"),
]
# sentences of the list that are commentary, not an advisory
COMMENTARY = re.compile(r"^(?:Although|Inadequate|Efforts|Work by|The swimming advisory includes)\b", re.I)
AREA_HEADINGS = {"Upper Cumberland River", "Kentucky River", "Licking River"}


def list_text(page: str) -> str:
    """The list's text between its heading and the 'Residential and Agricultural Areas' section; ValueError when
    either is missing (the page is not read as a withdrawal)."""
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", page or "", flags=re.S | re.I)
    s = re.sub(r"<(?:br|p|li|h\d|tr|div|ul)\b[^>]*>", "\n", s, flags=re.I)
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s)).replace("​", " ").replace("\xa0", " ")
    s = "\n".join(ln for ln in (re.sub(r"[ \t]+", " ", x).strip() for x in s.split("\n")) if ln)
    a, b = START.search(s), END.search(s)
    if not a or not b or b.start() < a.end():
        raise ValueError("the list of standing advisories was not found on the page")
    return s[a.end():b.start()].lstrip(": \n")


def sentences(text: str) -> list[str]:
    out = []
    for ln in text.split("\n"):
        if ln.strip() in AREA_HEADINGS:
            continue
        out += [x.strip() for x in re.split(r"(?<=\.)\s+", ln) if x.strip()]
    return out


def read(text: str) -> tuple[dict[str, str], list[str]]:
    """({key: the sentence that lists it}, sentences no rule recognises)."""
    found, used = {}, set()
    sents = sentences(text)
    for key, pat, *_ in STRETCHES:
        for s in sents:
            if re.search(pat, s, re.I):
                found[key] = s
                used.add(s)
                break
    unknown = [s for s in sents if s not in used and not COMMENTARY.match(s)]
    return found, unknown


def update(state: dict, text: str, at: str) -> dict:
    found, unknown = read(text)
    items = state.setdefault("items", {})
    current = dict(found)
    for s in unknown:
        current["unknown-" + hashlib.sha1(s.encode()).hexdigest()[:10]] = s
    for k, it in items.items():
        if it.get("left_at") is None and k not in current:
            it["left_at"] = at
    for k, s in current.items():
        it = items.get(k)
        if it is None or it.get("left_at"):
            it = items[k] = {"first_seen": at}
        it.update(last_seen=at, text=s)
    state["last_poll"] = {"at": at, "listed": sorted(current)}
    return state


def records(state: dict) -> list[dict]:
    by = {k: (w, st, area) for k, _, w, st, area in STRETCHES}
    out = []
    for k, it in sorted(state.get("items", {}).items()):
        left = it.get("left_at")
        raw = {"listed_text": it.get("text"), "first_seen_at": it["first_seen"],
               "_last_seen_in_source": it.get("last_seen"), "start_basis": START_BASIS, "time_zone": "America/New_York",
               "advisory_noun": "Swimming advisory"}
        if left:
            raw.update(left_page_at=left, ended_at_precision="poll",
                       end_basis="the first read of the page that no longer listed it")
        if k in by:
            water, stretch, area = by[k]
            raw.update(stretch_text=stretch, area=area)
            out.append(event(source_id=SOURCE_ID, source_record_id=k, event_type="beach_advisory",
                             status="advisory_lifted" if left else "advisory_active", waterbody_text=water,
                             water_slugs=[], water_match="none", started_at=it["first_seen"], ended_at=left,
                             time_precision="poll", reported_at=None, published_at=None, source_updated_at=None,
                             authority=AUTHORITY, advice_text=ADVICE, advice_window_hours=None,
                             advice_window_basis=WINDOW_BASIS, source_url=URL, raw=raw))
        else:
            out.append(event(source_id=SOURCE_ID, source_record_id=k, event_type="unknown",
                             status="advisory_lifted" if left else "advisory_active", started_at=it["first_seen"],
                             ended_at=left, time_precision="poll", authority=AUTHORITY, advice_text=ADVICE,
                             source_url=URL, raw=raw,
                             parse_error=f"a listed sentence no rule recognises: {it.get('text')!r}"))
    return out


def fetch() -> str:
    r = requests.get(URL, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.text


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    at = argv[argv.index("--at") + 1] if "--at" in argv else now_iso()
    try:
        page = Path(argv[argv.index("--file") + 1]).read_text() if "--file" in argv else fetch()
        text = list_text(page)
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    state = read_json(STATE_PATH, {}) or {}
    if "--file" not in argv and state.get("last_text") != text:
        save_raw(SOURCE_ID, json.dumps({"fetched_at": at, "list_text": text}, indent=1).encode(), "json")
    state["last_text"] = text
    state = update(state, text, at)
    write_json(STATE_PATH, state)
    recs = records(state)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "last_poll": state.get("last_poll"),
            "cadence": "with the refresh; the list changes rarely and gives no dates"}
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {sum(1 for r in recs if r['status'] == 'advisory_active')} listed; {len(recs)} records -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
