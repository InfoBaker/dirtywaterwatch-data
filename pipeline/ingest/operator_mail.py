"""Operators' e-mail notices -> data/build/events/<list's source>.json, one file per notice list (data/mail-lists.json).

Where the records come from (since 2026-11-18)
  This repository's token reaches R2 objects in dirtywaterwatch-data only, so the refresh no longer reads the mail. The
  private site repository's mail-feed job (its .github/workflows/mail-feed.yml, hourly, with the site's own token)
  runs this repository's pipeline/mailfeed/read.py: it reads the site's mail index and the archived messages, checks
  each sender, parses each notice in memory and writes, per notice list, the parsed records and each message's result
  to the bucket dirtywaterwatch-data, inbox/mail/<list's source id>.json (pipeline/inbox.py; the layout is in
  mailfeed/read.py and in the site repository's docs/mail-feed.md). No raw message, subject, address or body reaches
  this repository, its bucket or its log.
  This step, in the hourly refresh, reads each list's file through R2's S3 endpoint, places the Massachusetts records
  with ma_massdep's lookups of this run (ingest/mail/ma_common.apply_place), applies the one-event rules below, holds
  back what only a platform proves, checks for a quiet list, and writes the events file as before the split; for the
  same mail it writes the same records (tests/test_mail_feed_split.py).

An inbox that cannot be used (meta.inbox says which)
  No file, a file that cannot be read, one not in the expected form (any entry or record malformed, or another list's
  file: Astra review 2026-11-18 P2-4), one written more than INBOX_MAX_AGE_H hours ago, one whose read failed in the
  private job, or one holding messages not read yet or whose fetch failed (review P1-1): the list keeps its previous
  records and its health is false with the reason (common.write_events ok=False). A list is never emptied for want of a
  file or by a partial read. The reason saved is this module's sentence or a fixed category, never the file's words
  (review P1-3).

One event, not two
  A Massachusetts notice and MassDEP's portal record of the same overflow (same permit, same outfall number, starts
  within 3 hours) are one event: every e-mail record of that notice chain becomes duplicate_of the portal's shown
  record (the one no later portal record replaces), so the portal's record keeps the map and the e-mail's facts it
  lacks (the estimated volume, the cessation time) are attached to it by the status build (linked_notices).
  Manchester's e-mails repeat the city's page posts (ingest.nh_permittees): each becomes the duplicate of its post.
  This module runs after ma_massdep and nh_permittees (sorted order) and reads their events files of the same run.
  A message proven only by a shared sending platform (raw._trust "platform", Holyoke's Everbridge) may add to another
  source's record of the same discharge and never stands alone: its chain is held back unless linked as a duplicate;
  except on a list whose platform entry sets stands_alone (with at least one mark of the operator), where it does.

A list that goes quiet (meta.quiet; the status build lists it as a stale reason)
  Lists that send only when something happens are checked against another source that sees the same operator: a
  portal notice (or Manchester page post) that started after the sign-up, published 6 hours or more ago, with nothing
  from the list since an hour before its start, means the list is not reaching us. A list of regular releases (CT
  DEEP's press list, weekly at least) is quiet after max_quiet_days without a message.

Usage (from pipeline/):  python -m ingest.operator_mail      (DWW_INBOX_DIR=<folder> reads local copies of inbox/)
"""
from __future__ import annotations

import copy
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import inbox
from common import DATA_DIR, EVENTS_DIR, read_json, write_events
from ingest.mail import PARSERS
from ingest.mail.ma_common import apply_place
from ingest.mail.message import outfall_number, parse_iso

LISTS_FILE = DATA_DIR / "mail-lists.json"
INBOX_PREFIX = "inbox/mail/"
INBOX_SCHEMA = 1
INBOX_MAX_AGE_H = 3             # an older file keeps the list's previous records (the job runs hourly)
PORTAL_LINK_HOURS = 3           # ma_massdep's own rule for a notice and its verified report
CHAIN_HOURS = 72                # a Ceased notice closes the open notice of its outfall that started at most this long before
QUIET_GRACE_H = 6               # a cross-check notice counts once it was published this long ago
QUIET_LEAD_H = 1                # ... and the list said nothing from an hour before its start


def load_lists(path: Path = LISTS_FILE) -> dict:
    return (read_json(path, {}) or {}).get("lists") or {}


def ma_context(lists: dict) -> dict:
    """ingest.ma_massdep's lookups for the Massachusetts lists: the CSOs layer as its last run cached it (never
    fetched here), the ECHO registry, the waterbody crosswalk and the water names. A missing input leaves that
    lookup empty: the status build still places a record by its water's name."""
    if not any(s.get("outfall_prefix") for s in lists.values()):
        return {}
    from ingest import ma_massdep as M
    ctx = {}
    for key, fn in (("echo", M.load_echo), ("crosswalk", M.load_crosswalk), ("waters", M.load_waters)):
        try:
            ctx[key] = fn()
        except Exception as e:  # noqa: BLE001
            print(f"operator_mail: {key} lookup not loaded ({type(e).__name__})", file=sys.stderr)
    ctx["layer"] = (read_json(M.LAYER_CACHE, {}) or {}).get("outfalls") or {}
    return ctx


# ---------------------------------------------------------------- linking

def _t(r: dict, *keys) -> datetime | None:
    for k in keys:
        v = parse_iso(r.get(k))
        if v:
            return v
    return None


RESEND_MINUTES = 10             # two notices of one outfall this close in their stated time are one notice sent twice


def _activity(r: dict) -> datetime | None:
    """The latest moment a record shows the overflow still going: its stated start or, for an update, its receipt."""
    ts = [t for t in (_t(r, "started_at"), parse_iso((r.get("raw") or {}).get("_received_at"))) if t]
    return max(ts) if ts else None


def link_chains(records: list[dict]) -> None:
    """Within one list: the notices of one outfall's overflow form a chain (Active, its 8-hour updates and re-sends,
    then Ceased and any re-send of the Ceased), each the child of the one before, so the newest is the record shown.
    A Ceased notice takes the chain's start from the earlier notice (the operator's own start). A Ceased notice closes
    the open chain when its end is no earlier than the chain's start and within CHAIN_HOURS of the chain's latest
    notice; a second Ceased notice with the same end (RESEND_MINUTES) joins the closed chain. raw._chain names the
    chain's first record. (Astra mail review 2026-11-17 P1-9.)"""
    groups = defaultdict(list)
    for r in records:
        groups[(r.get("npdes_permit"), (r.get("raw") or {}).get("_outfall_key"))].append(r)
    for (_, key), rs in groups.items():
        if key is None:
            for r in rs:
                r["raw"]["_chain"] = r["event_id"]
            continue
        rs.sort(key=lambda r: (_t(r, "started_at", "ended_at") or datetime.max.replace(tzinfo=UTC),
                               r["raw"].get("_received_at") or "", r["event_id"]))
        head = None                  # the newest record of the open chain
        closed = None                # the newest record of the chain a Ceased notice closed last
        for r in rs:
            st = r["raw"].get("_notice_state")
            s, e = _t(r, "started_at"), _t(r, "ended_at")
            open_ = head is not None and head["status"] == "ongoing"
            hs = _t(head, "started_at") if head else None
            act = _activity(head) if head else None

            def join(parent, why):
                r["parent_event_id"] = parent["event_id"]
                r["raw"]["_chain"] = parent["raw"]["_chain"]
                r["raw"]["_link_basis"] = why
                if not r.get("started_at") and parent.get("started_at"):
                    r["started_at"] = parent["started_at"]
                    r["raw"]["_started_at_basis"] = f"the start of the earlier notice {parent['event_id']}"
            if st in ("active", "update") and s is not None:
                if open_ and hs and abs((s - hs).total_seconds()) <= RESEND_MINUTES * 60:
                    join(head, "the same outfall and start as the earlier notice (an update or a re-send)")
                else:
                    r["raw"]["_chain"] = r["event_id"]
                head = r
            elif st == "ceased" and e is not None and open_ and hs and hs <= e \
                    and act and e <= act + timedelta(hours=CHAIN_HOURS):
                join(head, "a Ceased notice for the outfall's open notice")
                head, closed = r, r
            elif st == "ceased" and e is not None and closed is not None and _t(closed, "ended_at") \
                    and abs((e - _t(closed, "ended_at")).total_seconds()) <= RESEND_MINUTES * 60:
                join(closed, "the same cessation as the earlier Ceased notice (a re-send)")
                closed = r
                if head is not None and head["raw"].get("_chain") == r["raw"]["_chain"]:
                    head = r
            else:
                r["raw"]["_chain"] = r["event_id"]
                head = r if st != "ceased" else None
                if st == "ceased":
                    closed = r


def portal_families(portal: list[dict], permit: str) -> list[dict]:
    """MassDEP's records of one permit grouped by overflow: a notice, its Ceased updates and its Verified Data Report
    (linked by parent_event_id in ingest.ma_massdep), each family with its outfall number, its start (the root's own,
    else inherited through the chain, as build.status.resolve_revisions does) and the record it shows (the member no
    later member replaces; the newest published if several)."""
    by_id = {p["event_id"]: p for p in portal if p.get("npdes_permit") == permit}
    replaced = set()
    for p in by_id.values():
        par = p.get("parent_event_id")
        if par in by_id and par != p["event_id"] and (p.get("started_at") or p.get("status", "unknown") != "unknown"):
            replaced.add(par)

    def root(eid, depth=0):
        par = by_id[eid].get("parent_event_id")
        return root(par, depth + 1) if par in by_id and par != eid and depth < 50 else eid
    fams = defaultdict(list)
    for eid in by_id:
        fams[root(eid)].append(by_id[eid])
    out = []
    for rid, members in fams.items():
        start = next((_t(m, "started_at") for m in [by_id[rid]] + members if m.get("started_at")), None)
        num, _ = outfall_number(by_id[rid].get("outfall_id"))
        if start is None or num is None or any(m.get("duplicate_of") for m in members):
            continue
        shown = [m for m in members if m["event_id"] not in replaced] or members
        target = max(shown, key=lambda m: ((_t(m, "published_at") or datetime.min.replace(tzinfo=UTC)), m["event_id"]))
        out.append({"root": rid, "start": start, "num": num, "target": target})
    return out


def link_portal(records: list[dict], portal: list[dict], permit: str | None) -> int:
    """Each e-mail chain to MassDEP's record of the same overflow, one to one: same permit and outfall number,
    starts within PORTAL_LINK_HOURS; the closest pairs are taken first and a portal overflow is given to one chain only,
    so a second overflow of the same outfall is never folded into the first (Astra mail review 2026-11-17 P1-7, P1-8).
    Every record of a linked chain becomes duplicate_of the family's shown record."""
    if not permit:
        return 0
    fams = portal_families(portal, permit)
    chains = defaultdict(list)
    for r in records:
        chains[r["raw"].get("_chain") or r["event_id"]].append(r)
    pairs = []
    for cid, rs in chains.items():
        root = next((r for r in rs if r["event_id"] == cid), rs[0])
        s = _t(root, "started_at") or next((_t(r, "started_at") for r in rs if r.get("started_at")), None)
        key = root["raw"].get("_outfall_key")
        if s is None or key is None:
            continue
        for f in fams:
            if f["num"] == key:
                gap = abs((f["start"] - s).total_seconds())
                if gap <= PORTAL_LINK_HOURS * 3600:
                    pairs.append((gap, cid, f["root"], f))
    pairs.sort(key=lambda x: (x[0], x[1], x[2]))
    used_c, used_f, n = set(), set(), 0
    for gap, cid, frid, f in pairs:
        if cid in used_c or frid in used_f:
            continue
        used_c.add(cid)
        used_f.add(frid)
        best = f["target"]
        for r in chains[cid]:
            r["duplicate_of"] = best["event_id"]
            r["raw"]["_link_basis"] = "; ".join(x for x in (r["raw"].get("_link_basis"), (
                f"the same overflow as the MassDEP portal record {best.get('source_record_id')}: same permit and "
                f"outfall number, starts {round(gap / 60)} min apart")) if x)
            n += 1
    return n


# ---------------------------------------------------------------- quiet lists

def quiet_check(spec: dict, entries: list[dict], others: dict, now: datetime) -> dict | None:
    q = spec.get("quiet") or {}
    since = parse_iso(spec.get("since"))
    heard = [parse_iso(e.get("received_at")) for e in entries        # only a message the check proved came from
             if e.get("trust") in ("operator", "platform")]             # the list (Astra mail review 2026-11-17 P2-13)
    heard = [t for t in heard if t]
    last = max(heard) if heard else None
    cc = q.get("cross_check")
    if cc and since:
        recs = others.get(cc.get("source_id")) or []
        missed = []
        for r in recs:
            if r.get("duplicate_of"):
                continue
            if cc.get("npdes_permit") and r.get("npdes_permit") != cc["npdes_permit"]:
                continue
            if cc.get("record_prefix") and not str(r.get("source_record_id") or "").startswith(cc["record_prefix"]):
                continue
            if cc.get("raw_kind") and (r.get("raw") or {}).get("kind") != cc["raw_kind"]:
                continue
            s, pub = _t(r, "started_at", "reported_at"), _t(r, "published_at", "reported_at")
            if s is None or pub is None or s < since or pub > now - timedelta(hours=QUIET_GRACE_H):
                continue
            if last is None or last < s - timedelta(hours=QUIET_LEAD_H):
                missed.append(s)
        if missed:
            return {"reason": (f"no message from this list since {last.strftime('%Y-%m-%d %H:%MZ') if last else 'the sign-up'}"
                               f", though {cc['source_id']} has {len(missed)} notice{'s' if len(missed) != 1 else ''} "
                               f"from the operator that started after the sign-up (latest {max(missed).astimezone(UTC):%Y-%m-%d %H:%MZ})"),
                    "missed": len(missed), "last_message_at": last.isoformat() if last else None}
    days = q.get("max_quiet_days")
    if days and since:
        ref = last or since
        if now - ref > timedelta(days=float(days)):
            return {"reason": f"no message from this list in {(now - ref).days} days (expected at least every {days})",
                    "last_message_at": last.isoformat() if last else None}
    return None


# ---------------------------------------------------------------- per list

def list_records(entries: list[dict]) -> list[dict]:
    out = []
    for e in sorted(entries, key=lambda e: (e.get("received_at") or "")):
        if e.get("result") == "notice" or (e.get("result") == "fetch_failed" and e.get("records")):
            out += copy.deepcopy(e.get("records") or [])
    return out


def build_list(lid: str, spec: dict, entries: list[dict], others: dict, now: datetime,
               ctx: dict | None = None) -> tuple[list[dict], dict]:
    """One list's records and meta from its entries (each message's result and records, with its inbound id as _id).
    ctx: ma_massdep's lookups, which place each Massachusetts record (a list with an outfall_prefix) afresh."""
    recs = list_records(entries)
    for r in recs:                  # links are made afresh each run
        r["duplicate_of"] = None
        r["parent_event_id"] = None
        for k in ("_chain", "_link_basis"):
            r["raw"].pop(k, None)
    if spec.get("outfall_prefix") and ctx is not None:
        for r in recs:              # placed with this run's lookups (the private read does not place)
            if (r.get("raw") or {}).get("_outfall_key") is not None:
                apply_place(r, spec, ctx)
    stats = {}
    if spec.get("parser") == "manchester":
        PARSERS["manchester"].pair(recs)
        stats["linked_to_page"] = PARSERS["manchester"].link_page(recs, others.get("nh-permittees") or [])
    elif spec.get("outfall_prefix"):
        link_chains(recs)
        stats["linked_to_portal"] = link_portal(recs, others.get("ma-massdep") or [], spec.get("npdes_permit"))
    # a message proven only by a shared platform (raw._trust "platform") may add to another source's record of the same
    # discharge, never stand alone: a chain of such records not linked as a duplicate is held back, counted, unpublished
    # A list whose platform binding names the operator's own marks (spec.platform.stands_alone, owner 2026-11-27:
    # Holyoke's Everbridge notices carry its permit and its own Everbridge account; the portal lags days) lets such
    # a record stand alone: a forged notice could only make the map more cautious. Linking to the portal is unchanged.
    alone = bool(((spec.get("platform") or {}).get("stands_alone"))
                 and ((spec.get("platform") or {}).get("body_marks") or (spec.get("platform") or {}).get("header_marks")))
    if alone:
        # ... but a platform-only notice never closes an open one (Astra 2026-11-27 P1): a Ceased notice that joined
        # an earlier notice's chain is held, with any re-send of it, so the earlier notice stays the record shown and
        # stays ongoing until the portal's record of the same overflow (duplicate_of) or an operator-proven notice
        # ends it. A forged notice can then only add red, never clear it. A Ceased notice that closes nothing stands.
        by_id = {r["event_id"]: r for r in recs}
        closing = {r["event_id"] for r in recs
                   if r["raw"].get("_trust") == "platform" and not r.get("duplicate_of")
                   and r["raw"].get("_notice_state") == "ceased" and r.get("parent_event_id") in by_id}
        grew = True
        while grew:                              # re-sends of a held Ceased notice are its children
            more = {r["event_id"] for r in recs if r.get("parent_event_id") in closing and r["event_id"] not in closing
                    and r["raw"].get("_trust") == "platform" and not r.get("duplicate_of")}
            grew, closing = bool(more), closing | more
        held = [r for r in recs if r["event_id"] in closing]
        recs = [r for r in recs if r["event_id"] not in closing]
    else:
        held_chains = {r["raw"].get("_chain") or r["event_id"] for r in recs
                       if r["raw"].get("_trust") == "platform" and not r.get("duplicate_of")}
        held = [r for r in recs if (r["raw"].get("_chain") or r["event_id"]) in held_chains]
        recs = [r for r in recs if (r["raw"].get("_chain") or r["event_id"]) not in held_chains]
    stats["held_platform_only"] = len(held)
    res = Counter(e.get("result") for e in entries)
    received = [e.get("received_at") for e in entries if e.get("received_at")]
    meta = {
        "channel": "email", "list_id": lid, "signed_up": spec.get("since"),      # the sign-up address is not published
        "messages": len(entries), "results": dict(sorted(res.items())), "records": len(recs), **stats,
        "last_message_at": max(received) if received else None,
        "failures": [{"inbound_id": mid, "received_at": e.get("received_at"), "result": e.get("result"),
                      "note": e.get("note")} for mid, e in sorted(((e["_id"], e) for e in entries),
                                                                  key=lambda x: x[1].get("received_at") or "")
                     if e.get("result") in ("failed", "needs_rule", "fetch_failed", "unverified")][-50:],
        "covers_permits": [spec["npdes_permit"]] if spec.get("npdes_permit") else [],
        "statewide": False,
    }
    meta["quiet"] = quiet_check(spec, entries, others, now)
    return recs, meta




def read_events(source_id: str, events_dir: Path = EVENTS_DIR) -> list[dict]:
    return (read_json(events_dir / f"{source_id}.json", {}) or {}).get("records") or []


SAFE_ERROR = re.compile(r"[A-Za-z0-9 ,.()_:'-]{1,200}")
UNSAFE = re.compile(r"[0-9a-f]{32}|@|://|cloudflarestorage", re.I)


def safe_error(text) -> str:
    """The private read's error as saved: its own sentences and categories pass; anything else is withheld."""
    t = str(text or "")
    return t if SAFE_ERROR.fullmatch(t) and not UNSAFE.search(t) else "the mail feed's read failed"


def _entries_ok(entries, source_id: str) -> bool:
    """Every entry a dict with an id, a receipt time, a result, a note and a trust that are strings (or None where
    they may be), and records that are a list of record dicts of this list's source, each with an event id and raw."""
    if not isinstance(entries, list):
        return False
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not e["id"] \
                or not isinstance(e.get("result"), str):
            return False
        if any(e.get(k) is not None and not isinstance(e.get(k), str) for k in ("received_at", "note", "trust")):
            return False
        recs = e.get("records")
        if not isinstance(recs, list):
            return False
        for r in recs:
            if not isinstance(r, dict) or not isinstance(r.get("event_id"), str) \
                    or r.get("source_id") != source_id or not isinstance(r.get("raw"), dict):
                return False
    return True


def read_inbox(source_id: str, now: datetime, reader=None, list_id: str | None = None
               ) -> tuple[dict | None, str | None, dict]:
    """(the list's inbox file, None, about) when it can be used; (None, why, about) when it cannot: absent, unreadable,
    not in the expected form, older than INBOX_MAX_AGE_H, a failed read in the private job, or messages not read yet
    or whose fetch failed. about goes to meta.inbox."""
    doc, why = (reader or inbox.get_json)(f"{INBOX_PREFIX}{source_id}.json")
    about = {"key": f"{INBOX_PREFIX}{source_id}.json"}
    if doc is None:
        return None, ("no file from the mail feed" if why == inbox.ABSENT else
                      f"the mail feed's file was {safe_error(why)}"), about
    written = parse_iso(doc.get("written_at")) if isinstance(doc.get("written_at"), str) else None
    about["written_at"] = doc.get("written_at") if written else None
    stats = doc.get("stats")
    about["stats"] = {k: v for k, v in stats.items() if isinstance(k, str) and isinstance(v, int)} \
        if isinstance(stats, dict) else {}
    form = "the mail feed's file is not in the expected form"
    if doc.get("schema") != INBOX_SCHEMA or doc.get("source_id") != source_id \
            or (list_id is not None and doc.get("list_id") != list_id) or not isinstance(doc.get("ok"), bool) \
            or not _entries_ok(doc.get("entries"), source_id):
        return None, form, about
    if written is None:
        return None, "the mail feed's file has no time", about
    age_h = (now - written).total_seconds() / 3600
    about["age_hours"] = round(age_h, 2)
    if age_h > INBOX_MAX_AGE_H:
        return None, (f"the mail feed's file was written {written.astimezone(UTC):%Y-%m-%d %H:%MZ}, more than "
                      f"{INBOX_MAX_AGE_H} hours ago"), about
    if not doc["ok"]:
        return None, safe_error(doc.get("error")), about
    left = Counter(e["result"] for e in doc["entries"] if e["result"] in ("pending", "fetch_failed"))
    if left:
        about["not_read"] = dict(sorted(left.items()))
        parts = [f"{n} message{'s' if n != 1 else ''} {w}" for n, w in (
            (left.get("pending", 0), "not read yet (the reader's limit per run)"),
            (left.get("fetch_failed", 0), "could not be fetched (tried again later)")) if n]
        return None, "; ".join(parts) + "; the list keeps its previous records until they are read", about
    return doc, None, about


def run(lists: dict, events_dir: Path = EVENTS_DIR, now: datetime | None = None, reader=None) -> int:
    """Each notice list's file from the inbox -> its events file. 0 when every list was written from a usable file.
    A list whose file cannot be used, or whose linking fails, keeps its previous records; the other lists go on."""
    now = now or datetime.now(UTC)
    notice_lists = {k: v for k, v in lists.items() if v.get("kind") == "notices" and v.get("source_id")}
    others = {sid: read_events(sid, events_dir) for sid in ("ma-massdep", "nh-permittees")}
    ctx = ma_context(notice_lists)
    kept = 0
    for lid, spec in sorted(notice_lists.items()):
        sid = spec["source_id"]
        path = events_dir / f"{sid}.json"
        doc, why, about = read_inbox(sid, now, reader, lid)
        if not why:
            try:
                entries = [{**{k: v for k, v in e.items() if k != "id"}, "_id": e["id"],
                            "note": e.get("note") if not UNSAFE.search(str(e.get("note") or "")) else "[withheld]"}
                           for e in doc["entries"]]
                recs, meta = build_list(lid, spec, entries, others, now, ctx)
            except Exception as e:  # noqa: BLE001 - one list's failure never stops the others
                why = f"the mail feed's file could not be linked ({type(e).__name__})"
        if why:
            write_events(sid, [], ok=False, error=why, meta={"inbox": about}, path=path)
            print(f"  {lid}: {why}; the list keeps its previous records", file=sys.stderr)
            kept += 1
            continue
        meta["inbox"] = about
        write_events(sid, recs, ok=True, meta=meta, path=path)
        q = " quiet" if meta.get("quiet") else ""
        print(f"  {lid}: {meta['messages']} messages, {meta['records']} records, "
              f"results {json.dumps(meta['results'], sort_keys=True)}{q}", file=sys.stderr)
    print(f"operator_mail: {len(notice_lists)} lists from {inbox.BUCKET}/{INBOX_PREFIX}; "
          f"{kept} kept their previous records", file=sys.stderr)
    return 1 if kept else 0


def main(argv=None) -> int:
    run(load_lists())
    return 0    # a list that could not be read is recorded as its health; the refresh goes on


if __name__ == "__main__":
    sys.exit(main())
