"""EPA's ICIS permit name without the contact person it often leads with: '<a person> - City of X', '<a person>,
City of X', '<a person>-Village of X' become 'City of X', 'Village of X'. The person who signs for a body is not the
permittee; the registry names the body (owner, 2026-11-04: no individual named in the registries).

Usage: pipeline/.venv/bin/python -I scripts/permit_names.py [--dry-run]
  Applies the rule once to the committed registry files (data/outfalls-plants-us.json; any other data/outfalls-*.json
  that carries permit_name), keeps every other field of a row, writes `permit_name_scrubbed: true` after permit_name
  on a changed row (never the removed text) and prints the number of rows changed per state (never a name). The
  plant build (research/federal/build_plant_outfalls.public_permit_name) applies the same rule, so a rebuild
  reproduces the committed rows.

Rule (deterministic: fixed word lists and the row itself, no reference file that a refresh could change)
  - The field is cut into parts at a dash with a space on either side (' - ', '- ', ' -'), at a dash joined to a
    body's word ('-City of', '-Village of'), at a comma or a semicolon, and a part in brackets is a part; ', Jr.' and
    the like stay with the name before them; 'c/o' or 'attn' and what follows is dropped.
  - A part is a person's name when it is one to three words of letters (a word of one letter is an initial; at least
    two words, or one word and an initial; at most four in all), none of them an organisation, operator, business,
    water, street, place-lead, state, calendar or function word (common.OPERATOR_WORDS, private_utilities ORG_WORDS,
    BUSINESS_WORDS, PLACE_LEADS, build.redact KILL, WATER_WORDS, STATES, FUNCTION, CALENDAR, HEADER_WORDS and the
    words below), the part is not the row's city, and the part does not recur in the rest of the field
    ('North Pole - City of North Pole').
  - A part that is a person's name is dropped only when what is left names a body (an organisation or operator word),
    and never when the rest is a bare 'City of' (EPA's inverted '<place>, City of'). Two one-word parts joined by a
    comma ('<surname>, <given> - City of X') are read together.
  - A field that is a person's name alone by that test and written in mixed case (EPA's contact entries) becomes
    null; one in capitals is left to the build's other rule (public_permit_name returns None for a common given name).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _d in (ROOT / "pipeline", ROOT / "scripts"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import private_utilities as pu  # noqa: E402
from build import redact  # noqa: E402
from common import OPERATOR_WORDS  # noqa: E402

# the brief's organisation words, and the words of bodies EPA's names carry that the shared lists lack
BODY_WORDS = set("""
city county district utility utilities authority inc llc corp plant wwtp borough village township department board
commission co company association school university park service services camp lodge mine cannery resort
council native tribe tribal tribes corporation regional municipality municipal public works health clinic
church base station fort refuge forest monument preserve hatchery fishery fisheries seafood seafoods processing
assembly government govt dept assoc nation community communities cooperative coop cooperative airport
dot pf dotpf state federal national army navy force guard usa us usaf usn usfs nps blm uscg club golf system
""".split())
TITLES = {"mr", "mrs", "ms", "mx", "dr", "hon", "mayor", "manager", "director", "superintendent", "operator",
          "attn", "attention", "contact"}
SUFFIX = r"(?:jr|sr|ii|iii|iv)\.?"
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’]*\.?|[A-Za-z](?:\.[A-Za-z])+\.?")
# where a field is cut into parts; a dash between letters with no space is a joined place name (Matanuska-Susitna)
# unless a body's word follows it ('-City of')
_BODY_AFTER_DASH = r"(?:city|village|town|borough|county|municipality|native|tribal|state|dept|department|school)\b"
SPLIT_RE = re.compile(rf"(\s+[-–—]+\s*|\s*[-–—]+\s+|\s*[-–—]+(?=(?i:{_BODY_AFTER_DASH}))|\s*[,;]\s*)")
# a corporate form after a comma belongs to the name before it ('Example Foods, Inc.')
CORP_TAIL = re.compile(r",\s*(inc|llc|l\.l\.c|ltd|lp|l\.p|llp|pc|p\.c|pllc|corp|co|company|corporation)\b\.?", re.I)
BARE_INVERTED = re.compile(r"^(?:the\s+)?(?:city|town|village|borough|county|township|municipality|parish|"
                           r"city\s+(?:and|&)\s+borough|unified\s+government|consolidated\s+city)(?:\s+of)?\.?$", re.I)
CARE_OF = re.compile(r"\s*,?\s*\b(?:c/o|attn:?|attention:?)\s+(.*)$", re.I)


def _stop(word: str) -> bool:
    w = word.lower().strip(".'’")
    return (w in OPERATOR_WORDS or w in pu.ORG_WORDS or w in pu.BUSINESS_WORDS or w in pu.PLACE_LEADS
            or w in pu.FUNCTION_WORDS or w in BODY_WORDS or w in redact.KILL or w in redact.WATER_WORDS
            or w in redact.STATES or w in redact.CALENDAR or w in redact.HEADER_WORDS
            or (w in redact.FUNCTION and w not in TITLES))


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def person_part(part: str, rest: str = "", city: str | None = None, facility: str | None = None) -> bool:
    """A part of the field that reads as a person's name (the module's rule)."""
    p = pu.clean(part.replace("\x00", " ")).strip(" ,.;-")
    if not p or re.search(r"\d|&|/", p):
        return False
    toks = p.split(" ")
    if not all(WORD_RE.fullmatch(t) for t in toks):
        return False
    toks = [t for t in toks if t.lower().strip(".") not in TITLES]
    words = [t for t in toks if len(t.replace(".", "")) > 1 and not re.fullmatch(SUFFIX, t, re.I)]
    initials = [t for t in toks if len(t.replace(".", "")) == 1]
    if not (1 <= len(words) <= 3 and len(toks) <= 4 and (len(words) >= 2 or initials)):
        return False
    if len(words) == 1 and len(words[0]) < 3:
        return False
    if any(_stop(w) for w in words):
        return False
    n = _norm(p)
    if city and n == _norm(city):
        return False
    if n and f" {n} " in f" {_norm(rest)} ":
        return False
    if facility and set(_norm(" ".join(words)).split()) & set(_norm(facility).split()):
        return False                                 # the facility's own name ('Example Hills - Example Hills WWTP')
    return True


def _names_a_body(rest: str) -> bool:
    """What is left names a body: an organisation or body word and a word of its own name ('City of X', 'North
    Example Borough'), not a bare 'City of', 'Golf Club' or 'Water & Sewerage System'."""
    words = re.findall(r"[A-Za-z][A-Za-z'’]*", rest)
    if BARE_INVERTED.match(rest.strip(" ,.-")):
        return False
    body = pu.has_org_word(rest) or any(w.lower() in BODY_WORDS for w in words)
    return body and any(len(w) > 1 and not _stop(w) for w in words)


def scrub_permit_name(v, city: str | None = None, facility: str | None = None) -> tuple[str | None, bool]:
    """(the field without a contact person's name, whether it changed). A blank stays as it was."""
    s = pu.clean(v)
    if not s:
        return v, False
    t = s
    m = CARE_OF.search(t)
    if m and (person_part(m.group(1)) or pu.person_like(m.group(1))):     # '<body> c/o <a person>'
        t = t[:m.start()].strip(" ,")
    cut = t
    # a comma that does not cut: '<a person>, Jr. - City of X', 'Example Foods, Inc.' (put back in the output)
    t = re.sub(rf",(\s*)({SUFFIX})(?=\s|$|[-,;])", "\x00\\1\\2", t, flags=re.I)
    t = CORP_TAIL.sub(lambda x: "\x00" + x.group(0)[1:], t)
    pieces = SPLIT_RE.split(t)
    parts, seps = pieces[0::2], pieces[1::2]
    drop: set[int] = set()

    def rest_of(skip: set[int]) -> str:
        return " ".join(x for i, x in enumerate(parts) if i not in skip and x.strip())

    if len(parts) > 1 and any(BARE_INVERTED.match(x.strip(" ,.-")) for x in parts[1:]):
        return cut, cut != s                         # EPA's inverted '<place>, City of': the place is the body's
    for i, part in enumerate(parts):
        if not part.strip():
            continue
        cand = [({i}, part)]
        if (i == 0 and len(parts) > 2 and "," in seps[0] and re.search(r"[-–—]", seps[1])
                and len(part.split()) == 1 and len(parts[1].split()) == 1):
            cand.insert(0, ({0, 1}, f"{parts[1]} {part}"))                   # '<surname>, <given> - City of X'
        for idx, text in cand:
            rest = rest_of(drop | idx)
            if not _names_a_body(rest):
                continue
            # a person leads EPA's field; after the body, only a name with a common given name is taken for one
            # (a part after the body is more often the plant's own name)
            if person_part(text, rest, city, facility) and (i == 0 or pu.person_like(text)):
                drop |= idx
                break
    if not drop:
        # the whole field a person's name, written in mixed case as EPA's contact entries are ('Pat Example' for a
        # city's lagoon); a name in capitals is more often a body's or a place's own and is left to public_permit_name
        if len(parts) == 1 and not cut.isupper() and person_part(cut, "", city, facility):
            return None, True
        return cut, cut != s
    kept = [i for i in range(len(parts)) if i not in drop and parts[i].strip()]
    out = parts[kept[0]]
    for j in kept[1:]:
        out += seps[j - 1] + parts[j]
    out = re.sub(r"\s+", " ", out.replace("\x00", ",")).strip(" ,;-–—")
    return (out or None), out != s


def scrub_rows(rows: list[dict]) -> Counter:
    """Scrub every row's permit_name in place; the marker goes right after permit_name. Counter of rows per state."""
    n: Counter = Counter()
    for k, r in enumerate(rows):
        if "permit_name" not in r or not r.get("permit_name"):
            continue
        new, changed = scrub_permit_name(r["permit_name"], r.get("city"), r.get("permittee"))
        if not changed:
            continue
        out = {}
        for key, val in r.items():
            if key == "permit_name_scrubbed":
                continue
            out[key] = new if key == "permit_name" else val
            if key == "permit_name":
                out["permit_name_scrubbed"] = True
        rows[k] = out
        n[r.get("state") or "??"] += 1
    return n


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    from ingest.outfall_waters import write_plants
    total: Counter = Counter()
    for path in sorted((ROOT / "data").glob("outfalls-*.json")):
        doc = json.loads(path.read_text())
        rows = doc["outfalls"] if isinstance(doc, dict) else doc
        if not any("permit_name" in r for r in rows):
            continue
        n = scrub_rows(rows)
        total += n
        print(f"{path.name}: {sum(n.values())} rows changed")
        if n and not a.dry_run:
            if path.name == "outfalls-plants-us.json":
                write_plants(path, doc)
            else:
                path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    for st, c in sorted(total.items()):
        print(f"  {st}: {c}")
    print(f"total: {sum(total.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
