"""Per-operator rows of data/notice-channels.json for duties the law puts on every operator (North Carolina, Georgia),
made from the law and data/dischargers.json, so the rows are reproducible.

Usage: pipeline/.venv/bin/python -I scripts/add_register_rows.py [--only PART[,PART]] [--dry-run]

docs/collection-checklist.md §2: "A duty that falls on each operator gets a row per operator" (Maine's yearly
newspaper notice, Maryland's press notice); "Channels with no web form are rows too: urls [], unmonitored_reason
other, note 'No web form'". The parts:

  nc-annual   G.S. 143-215.1C(a) (fetched from ncleg.gov 2026-11-04 and quoted in LAW_NC_A): the owner or operator of
              a municipal or domestic collection or treatment works "having an average annual flow greater than
              200,000 gallons per day" gives its users or customers and the Department a yearly performance report.
              A row <operator id>-annual-report for every North Carolina operator the duty may fall on (nc_annual_scope):
                - an industrial system ("G.S. 143-215.1C(c)" in its notification_channel: works other than municipal
                  or domestic) is out of (a);
                - an operator whose every permit is a treatment plant with a design flow in EPA's plant rows
                  (data/outfalls-plants-us.json design_flow_mgd) of 0.2 MGD or less is out: the permitted flow bounds
                  the flow the plant is permitted to treat, so its average annual flow is not over 200,000 gallons a
                  day unless it runs over its permit (a design flow of 0 is taken as not entered, not as zero);
                - every other operator is in: a plant permit over 0.2 MGD (the note says the average annual flow the
                  law counts was not checked), or a collection system or a permit with no design flow (the note says
                  flow was not checked and the row is kept on the side of caution).
              The report goes to customers and the Department; no web posting is required, and operators' own
              postings were not searched one by one, so each row is unmonitored (barrier not_verified).

Idempotent: a part's rows are rebuilt from the inputs and replace rows of the same id; the register stays sorted by
(state, id) and every row's barrier is what ingest.notification_pages.barrier_for says. `checked` is the date the law
and the inputs were read (CHECKED), not the run date, so a rerun changes nothing.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from ingest import notification_pages as NP  # noqa: E402

REGISTER = ROOT / "data" / "notice-channels.json"
DIS = ROOT / "data" / "dischargers.json"
PLANTS = ROOT / "data" / "outfalls-plants-us.json"
CHECKED = "2026-11-04"
FLOW_THRESHOLD_MGD = 0.2              # 200,000 gallons a day

LAW_NC_A = ('G.S. 143-215.1C(a): "The owner or operator of any wastewater collection or treatment works, the operation '
            'of which is primarily to collect or treat municipal or domestic wastewater and for which a permit is issued '
            'under this Part and having an average annual flow greater than 200,000 gallons per day, shall provide to '
            'the users or customers of the collection system or treatment works and to the Department an annual report '
            'that summarizes the performance of the collection system or treatment works and the extent to which the '
            'collection system or treatment works has violated the permit or federal or State laws, regulations, or '
            'rules related to the protection of water quality. The report shall be prepared on either a calendar or '
            'fiscal year basis and shall be provided no later than 60 days after the end of the calendar or fiscal '
            'year."')
NC_SOURCE_A = "nc-law-gs-143-215-1c-a"


def mgd(x: float) -> str:
    return f"{x:g} MGD"


def nc_industrial(op: dict) -> bool:
    """Works other than municipal or domestic: add_nc_operators.py writes the (c) duty into their channel."""
    return "G.S. 143-215.1C(c)" in str(op.get("notification_channel") or "")


def design_flows(plants: dict | list, state: str) -> dict[str, float]:
    """{permit: largest design flow in MGD} from EPA's plant rows of one state (rows without a flow, or with 0, which
    ICIS uses for a flow not entered, left out)."""
    rows = plants.get("outfalls", []) if isinstance(plants, dict) else plants
    out: dict[str, float] = {}
    for r in rows:
        f = r.get("design_flow_mgd")
        if r.get("state") == state and r.get("npdes_permit") and isinstance(f, (int, float)) and not isinstance(f, bool) \
                and f > 0:
            out[r["npdes_permit"]] = max(out.get(r["npdes_permit"], 0.0), float(f))
    return out


def permits_of(op: dict) -> list[str]:
    ps = list(op.get("npdes_permits") or [])
    if op.get("npdes_permit") and op["npdes_permit"] not in ps:
        ps.insert(0, op["npdes_permit"])
    return ps


def nc_annual_scope(op: dict, flows: dict[str, float]) -> tuple[bool, str]:
    """(in scope, the flow sentence of the note or the reason it is out)."""
    if nc_industrial(op):
        return False, "industrial system: (a) covers municipal or domestic works only"
    ps = permits_of(op)
    known = {p: flows[p] for p in ps if p in flows}
    over = {p: f for p, f in known.items() if f > FLOW_THRESHOLD_MGD}
    if over:
        p, f = max(over.items(), key=lambda kv: kv[1])
        return True, (f"EPA's permitted (design) flow for {p} is {mgd(f)}, over the threshold; the average annual flow "
                      f"the law counts was not checked.")
    if ps and len(known) == len(ps):
        return False, ("every permit is a plant with a design flow of 0.2 MGD or less ("
                       + ", ".join(f"{p} {mgd(f)}" for p, f in known.items()) + ")")
    unknown = [p for p in ps if p not in known]
    small = (" EPA's design flow for " + ", ".join(f"{p} is {mgd(f)}" for p, f in known.items())
             + ", under the threshold, but the other permits' flow is unknown.") if known else ""
    return True, (f"flow not checked: no design flow is on record for {', '.join(unknown) or 'its permits'}"
                  f" (a collection system or a plant missing from EPA's rows); listed on the side of caution.{small}")


def finish(r: dict) -> dict:
    """The row's barrier (and barrier_review) as the validator wants them."""
    bar, review = NP.barrier_for(r)
    r["barrier"] = bar
    if review:
        r["barrier_review"] = review
    else:
        r.pop("barrier_review", None)
    return r


def nc_annual_rows(dis: list[dict], plants) -> tuple[list[dict], list[tuple[str, str]]]:
    """The G.S. 143-215.1C(a) rows, and the operators left out with the reason."""
    flows = design_flows(plants, "NC")
    rows, out = [], []
    for op in dis:
        if op.get("state") != "NC":
            continue
        ok, why = nc_annual_scope(op, flows)
        if not ok:
            out.append((op["id"], why))
            continue
        rows.append(finish({
            "id": f"{op['id']}-annual-report", "state": "NC", "operator_id": op["id"], "agency": None,
            "name": op["name"], "permit": None, "channel_kind": "operator_page", "urls": [], "method": None,
            "legal_basis": LAW_NC_A, "basis_kind": "law", "monitored": False, "unmonitored_reason": "other",
            "publishes": "documents",
            "note": (f"No web form: {op['name']}: the yearly report on the system's performance and its permit "
                     "violations goes to the users or customers and a copy to the Department (DEQ), no later than 60 "
                     "days after the calendar or fiscal year; the law requires no web posting. It summarizes the year, "
                     "not single overflows. The duty applies to municipal or domestic works with an average annual "
                     f"flow over 200,000 gallons a day: {why} The operator's own posting was not searched "
                     "individually. (G.S. 143-215.1C(a), read on ncleg.gov 2026-11-04)"),
            "checked": CHECKED, "records": False, "noun": "Annual performance report", "sources": [NC_SOURCE_A]}))
    return rows, out


PARTS = {"nc-annual": {"build": lambda dis, plants: nc_annual_rows(dis, plants), "replaces": ()}}


def merge(doc: dict, new: list[dict], replaces=()) -> dict:
    """The register with `new` rows put in (same id replaced) and the `replaces` ids removed, sorted by (state, id)."""
    ids = {r["id"] for r in new} | set(replaces)
    chans = [r for r in doc["channels"] if r["id"] not in ids] + new
    chans.sort(key=lambda r: (str(r.get("state")), str(r.get("id"))))
    return {**doc, "channels": chans}


def run(parts: list[str], register: Path = REGISTER, dis_path: Path = DIS, plants_path: Path = PLANTS,
        dry_run: bool = False) -> dict:
    doc = json.loads(register.read_text())
    dis = json.loads(dis_path.read_text())
    plants = json.loads(plants_path.read_text()) if plants_path.exists() else {"outfalls": []}
    report: dict = {}
    for p in parts:
        rows, left_out = PARTS[p]["build"](dis, plants)
        before = {r["id"] for r in doc["channels"]}
        doc = merge(doc, rows, PARTS[p]["replaces"])
        report[p] = {"rows": len(rows), "new": len({r["id"] for r in rows} - before),
                     "removed": sorted(set(PARTS[p]["replaces"]) & before), "left_out": left_out,
                     "barriers": dict(Counter(r["barrier"] or "review" for r in rows))}
    errs = NP.validate_register(doc, dis, ROOT)
    if errs:
        raise SystemExit("the register would not validate:\n" + "\n".join(errs[:20]))
    if not dry_run:
        register.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return report


def main(argv: list[str]) -> int:
    parts = list(PARTS)
    if "--only" in argv:
        parts = argv[argv.index("--only") + 1].split(",")
        bad = [p for p in parts if p not in PARTS]
        if bad:
            raise SystemExit(f"unknown parts {bad}; the parts are {list(PARTS)}")
    report = run(parts, dry_run="--dry-run" in argv)
    for p, r in report.items():
        print(f"{p}: {r['rows']} rows ({r['new']} new), barriers {r['barriers']}, removed {r['removed']}, "
              f"left out {len(r['left_out'])}")
        for oid, why in r["left_out"]:
            print(f"   left out {oid}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
