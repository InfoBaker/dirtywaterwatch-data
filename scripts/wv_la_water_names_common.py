"""Name keys and the national list's known names, for scripts/wv_report_water_names.py and
scripts/la_report_water_names.py (a helper, not a script to run). A name is compared with the national list's names,
keys, the names EPA's rows gave (names_seen) and the GNIS names its records were built from, case, punctuation and
common abbreviations aside; a qualified name ("Little Coal River", "West Fork River") is its own water, compared as
written."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOT_A_NAME = re.compile(r"^\s*(?:unnamed\b.*|unt\b.*|ut\b.*|unknown|none|n/?a|storm sewer|ditch|lateral|canal|creek|bayou)\s*$", re.I)
ABBR = [(r"\bfk\b", "fork"), (r"\bw\b", "west"), (r"\be\b", "east"), (r"\bn\b", "north"), (r"\bs\b", "south"),
        (r"\bcr\b", "creek"), (r"\bck\b", "creek"), (r"\br\b", "river"), (r"\bft\b", "fort"), (r"\bst\b", "saint"),
        (r"\bof the\b", " ")]


def key(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    for pat, rep in ABBR:
        s = re.sub(pat, rep, s)
    return " ".join(s.split())


def known_keys(state: str) -> set[str]:
    doc = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())
    st = doc["states"].get(state) or {}
    out = set()
    for w in st.get("waters") or []:
        for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])]:
            if n:
                out.add(key(n))
                out.add(key(first_named(n) or ""))
    return out


def first_named(text: str) -> str | None:
    """'Buffalo Creek/Monongahela River' -> 'Buffalo Creek'; 'UNT/Ohio River' -> None (an unnamed tributary is no
    name); the receiving water is the first part of DEP's chain."""
    parts = [" ".join(p.split()) for p in str(text or "").split("/")]
    if not parts or not parts[0] or NOT_A_NAME.match(parts[0]):
        return None
    return parts[0]
