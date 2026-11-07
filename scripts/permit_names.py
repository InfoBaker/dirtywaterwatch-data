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
SPLIT_RE = re.compile(rf"(\s+[-–—]+\s*|\s*[-–—]+\s+|\s*[-–—]+(?=(?i:{_BODY_AFTER_DASH}))|\s*[,;]\s*"
                      r"|\s*[(\[]\s*|\s*[)\]]\s*)")
_OPEN, _CLOSE = "([", ")]"
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
            # a part in brackets is an aside ('City of X (<a person>)'): the shape alone marks the contact
            bracketed = i > 0 and any(c in seps[i - 1] for c in _OPEN)
            if person_part(text, rest, city, facility) and (i == 0 or bracketed or pu.person_like(text)):
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
    for j in range(kept[0] + 1, len(parts)):
        sep = seps[j - 1]
        if any(c in sep for c in _OPEN + _CLOSE):
            out += f" {sep.strip()} "               # a bracket stays until _balance pairs it or drops it
        elif j in kept:
            out += sep
        if j in kept:
            out += parts[j]
    out = re.sub(r"\s+", " ", _balance(out).replace("\x00", ",")).strip(" ,;-–—")
    return (out or None), out != s


def _balance(s: str) -> str:
    """Brackets left without a partner (or empty) once a bracketed part or the part before one is dropped."""
    keep = [True] * len(s)
    stack: list[int] = []
    for i, c in enumerate(s):
        if c in _OPEN:
            stack.append(i)
        elif c in _CLOSE:
            if stack and s[stack[-1]] == _OPEN[_CLOSE.index(c)]:
                j = stack.pop()
                if not s[j + 1:i].strip(" ,;-–—"):
                    keep[j] = keep[i] = False
            else:
                keep[i] = False
    for j in stack:
        keep[j] = False
    out = "".join(c for c, k in zip(s, keep) if k)
    return re.sub(r"\s+([)\]])", r"\1", re.sub(r"([(\[])\s+", r"\1", out))


# ---------------------------------------------------------------- a permit held in a person's own name (2026-11-07)
# The Texas review (P1-2) found permits whose EPA name is the holder's own: '<code> <surname>, <forename>',
# 'HOA <a person> AND <a person>', a three-part personal name, '<bodies>, AND <a person>', '<a person> d/b/a <trade
# name>' and '<a person> Family Limited Partnership'. The field then becomes the facility's name (or the trade name
# after d/b/a), else 'Holder of permit <id>'; the plant file marks the row permit_name_scrubbed as before.
DBA = re.compile(r"\s*-?\s*\b(?:d\s*/\s*b\s*/\s*a|dba|doing\s+business\s+as)\b\s*-?\s*", re.I)
FAMILY = re.compile(r"\bfamily\s+(?:limited\s+)?(?:partnership|trust|lp|ltd|llc)\b", re.I)
HOLDER_LEAD = re.compile(r"^(?:the|hoa|poa)\s+", re.I)
CORP_PART = re.compile(r"(?:inc|l\.?l\.?c|l\.?p|ltd|llp|co|corp|pc|pllc)\.?", re.I)
# EPA's abbreviations of a body's words that the shared lists lack (a word with no vowel, TWP or CNTY, is one too)
ABBREVIATIONS = set("""
auth muni sani sew svc svcs prk dept div dist corr sch bur opr const fac maint bldg ctr env envir util utils wtr ww
cnty cisd isd sd ud psd pud hoa poa assn assoc boparc reservation rancheria pueblo mhc mhp odnr
""".split())
# bodies named for their founders, read as bodies (a firm, not the person)
FIRM_NAMES = {"hatch mott macdonald", "martin marietta materials"}
HOLDER = "Holder of permit {}"


def _given(word: str) -> bool:
    from build import redact
    return word.lower() in (redact.FIRST_NAMES | pu.GIVEN_EXTRA)


def _words(s: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", (s or "").lower()) if len(w) > 1}


def _personal_part(part: str, context: set[str]) -> bool:
    """A part of the holder's name that is a person's: private_utilities.person_like with no body's word, or two or
    three words of letters none of which is a body's, an organisation's, a place-lead's or an abbreviation's word
    (a word with no vowel is an abbreviation) and none of which the facility's name or the city shares."""
    p = HOLDER_LEAD.sub("", pu.clean(part).strip(" .,;-"))
    if not p or pu.has_org_word(p) or _norm(p) in FIRM_NAMES:
        return False
    if _words(p) & context:
        return False
    if pu.person_like(p):
        return True
    ws = p.split()
    return (2 <= len(ws) <= 3 and all(re.fullmatch(r"[A-Za-z]{2,}", w) for w in ws)
            and not any(_stop(w) or w.lower() in ABBREVIATIONS or not re.search(r"[aeiouy]", w, re.I) for w in ws))


def person_holder(v, facility: str | None = None, city: str | None = None) -> bool:
    """Whether EPA's permit name is (or holds) a private person's own name, by the shapes above."""
    s = pu.clean(v)
    if not s:
        return False
    if FAMILY.search(s) and any(_given(w) for w in re.findall(r"[A-Za-z]+", s)):
        return True
    context = _words(facility) | _words(city)
    raw = [x for x in re.split(r"\s*[,;]\s*(?:and\s+|&\s*)?", s, flags=re.I) if x.strip(" .")]
    if any(BARE_INVERTED.match(x.strip(" ,.-")) for x in raw[1:]):
        return False                                  # EPA's inverted '<place>, City of'
    # 'and' or '&' joins two people ('HOA <a person> AND <a person>') only where no word around it is a body's, an
    # abbreviation's or a function word ('Department of Conservation and Natural Resources', 'Sand and Gravel LLC')
    split: list[str] = []
    for x in raw:
        bare = HOLDER_LEAD.sub("", x.strip())
        if re.search(r"\s(?:and|&)\s", bare, re.I) and not pu.has_org_word(bare) and not any(
                _stop(w) or w.lower() in ABBREVIATIONS for w in re.findall(r"[A-Za-z]+", bare) if w.lower() != "and"):
            sides = [y for y in re.split(r"\s+(?:and|&)\s+", bare, flags=re.I) if y.strip()]
            split += sides if all(len(y.split()) >= 2 for y in sides) else [x]     # a person: two words at least
        else:
            split.append(x)
    raw = split
    parts: list[str] = []
    for x in raw:                         # a corporate form belongs to the part before it ('<x> Materials, Inc.')
        if parts and CORP_PART.fullmatch(x.strip(" .")):
            parts[-1] += ", " + x
        else:
            parts.append(x)
    if len(parts) == 1 and (pu.has_org_word(s) or not _words(s) - context):
        return False
    for i, x in enumerate(parts):
        # '<code> <surname>, <forename>': a lone given name after a part with no body's word
        if (i and len(x.split()) == 1 and _given(x.strip(" ."))
                and not pu.has_org_word(parts[i - 1]) and not any(_stop(w) for w in parts[i - 1].split())):
            return True
        if _personal_part(x, context):
            return True
    return False


def holder_name(v, permit: str | None, city: str | None = None, facility: str | None = None) -> tuple[str | None, bool]:
    """(the permit name with a holder's own name replaced, whether it changed): the trade name after d/b/a when the
    owner before it is a person; else the facility's name when it is a body's; else 'Holder of permit <id>'."""
    s = pu.clean(v)
    if not s:
        return v, False
    halves = DBA.split(s, maxsplit=1)
    if len(halves) == 2 and halves[1].strip(" ,-"):
        owner, trade = halves[0].strip(" ,-"), halves[1].strip(" ,-")
        if person_holder(owner, facility, city) or person_part(owner) or pu.person_like(owner):
            return trade, True
        return s, False
    if not person_holder(s, facility, city):
        return s, False
    fac = pu.clean(facility)
    if fac and not person_holder(fac) and pu.public_name(fac) not in (None, pu.NAME_REMOVED):
        return fac, True
    return HOLDER.format(permit or "unknown"), True


def scrub_candidates(doc: dict) -> Counter:
    """research/<st>/private-utilities-candidates.json: a permittee_as_recorded that is a holder's own name becomes
    the file's '[name removed]' (its convention: the permit is kept; the operator builders read that value), or the
    trade name after d/b/a. Counter of rows per state."""
    n: Counter = Counter()
    for key in ("candidates", "public_by_name"):
        for c in doc.get(key) or []:
            v = c.get("permittee_as_recorded")
            if not v or v == pu.NAME_REMOVED:
                continue
            new, changed = holder_name(v, c.get("npdes_permit"), c.get("city"), c.get("facility"))
            if changed:
                trade = len(DBA.split(pu.clean(v), maxsplit=1)) == 2      # the trade name after d/b/a is the body's
                c["permittee_as_recorded"] = new if trade else pu.NAME_REMOVED
                n[c.get("state") or "??"] += 1
    return n


def scrub_rows(rows: list[dict]) -> Counter:
    """Scrub every row's permit_name in place; the marker goes right after permit_name. Counter of rows per state."""
    n: Counter = Counter()
    for k, r in enumerate(rows):
        if "permit_name" not in r or not r.get("permit_name"):
            continue
        held, by_holder = holder_name(r["permit_name"], r.get("npdes_permit"), r.get("city"), r.get("permittee"))
        new, changed = scrub_permit_name(held, r.get("city"), r.get("permittee"))
        changed = changed or by_holder
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
    for path in sorted((ROOT / "research").glob("*/private-utilities-candidates.json")):
        doc = json.loads(path.read_text())
        n = scrub_candidates(doc)
        total += n
        if n:
            print(f"{path.relative_to(ROOT)}: {sum(n.values())} rows changed")
            if not a.dry_run:
                path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    for st, c in sorted(total.items()):
        print(f"  {st}: {c}")
    print(f"total: {sum(total.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
