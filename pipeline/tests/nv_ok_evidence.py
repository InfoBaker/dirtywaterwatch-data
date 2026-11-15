"""Shared checks for the Nevada and Oklahoma registry tests (Astra P2-9): an operator row's name must be the permittee
EPA records (its owner or facility field), and a row whose holder EPA does not name is permit-only."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# EPA's own abbreviations of a body's name, as its records spell them
ABBREV = {"ok city": "oklahoma city", "tmua": "tulsa metropolitan utility authority",
          "rmua": "regional metropolitan utility authority", "wtr util trst": "water utilities trust",
          "ok st dept of corrections": "oklahoma department of corrections"}
GENERIC = {"city", "of", "town", "the", "public", "works", "authority", "county", "municipal", "utilities", "utility",
           "trust", "district", "rural", "water", "sewer", "and", "no", "services", "improvement", "development", "inc",
           "llc", "department", "company", "association", "plant", "wastewater", "permit", "facility", "treatment",
           "reclamation", "sewage", "management", "gas", "solid", "waste", "master", "conservancy", "park", "parks",
           "mobile", "home", "corporation", "metropolitan", "regional", "tribe", "nation"}
BODY = re.compile(r"\b(city|town|county|pwa|pua|mua|msa|mia|ua|uda|auth\w*|district|rwd|rwsd|rw|inc|llc|corp\w*|"
                  r"company|co\b|tribe|nation|trust|association|department|dept|navy|army|state|u\.?s\.?)\b", re.I)


def plants() -> dict:
    out = {}
    for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]:
        out.setdefault(r["npdes_permit"], r)
    return out


def evidence(pr: dict) -> str:
    t = f"{pr.get('permit_name') or ''} {pr.get('permittee') or ''}".lower()
    for a, b in ABBREV.items():
        t = t.replace(a, b)
    return t


def unsupported(state: str) -> list:
    pl, bad = plants(), []
    for r in json.loads((ROOT / "data" / "dischargers.json").read_text()):
        if r.get("state") != state or not r.get("npdes_permits"):
            continue
        for p in r["npdes_permits"]:
            pr = pl.get(p)
            if pr is None:
                continue
            if r.get("permit_only"):
                if not (r["legal_form"] is None and r["name"].startswith(f"Permit {p} (")):
                    bad.append((r["id"], p, "permit-only row form"))
                continue
            toks = {t for t in re.findall(r"[a-z]+", r["name"].lower()) if t not in GENERIC and len(t) > 2}
            ev = evidence(pr)
            if not (any(t in ev for t in toks) if toks else r["name"].lower() in ev):
                bad.append((r["id"], p, pr.get("permit_name"), pr.get("permittee")))
    return bad
