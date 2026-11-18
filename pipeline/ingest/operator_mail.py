"""Operators' e-mail notices -> data/build/events/<list's source>.json, one file per notice list (data/mail-lists.json).

Where the mail comes from
  The mail Worker `dirtywaterwatch-mail` (site repository, worker-mail/) receives every message sent to an address at
  dirtywaterwatch.org, archives it in R2 (bucket dirtywaterwatch-raw, email/<yyyy>/<mm>/<dd>/<id>.eml) and indexes it in
  D1 (database dirtywaterwatch, table inbound: id, received_at, to_addr, list_id, raw_key, ...). The list_id is the
  local part of the address the list was signed up with (springfield@ -> "springfield").

How it is read (design, 2026-11-17)
  The hourly refresh reads that index and archive itself, read-only, with the Cloudflare token the workflow already
  carries (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID): one D1 query for the index rows, one R2 object read per new
  message. Chosen over a read endpoint on a Worker (a new shared secret in this public repository's settings and a
  deploy) and over an export the mail Worker would write into the dirtywaterwatch-data bucket that the refresh restores
  (a second copy of raw mail, which holds staff names, phones and signatures, and a deploy): it adds no secret, no
  Worker code and no copy, and reads nothing the token cannot already read. The raw message is parsed in memory and
  never written to disk, logged or saved; the log prints counts per list only. Off the runner (a developer's machine
  with wrangler signed in) set MAIL_WRANGLER=1 (and MAIL_WRANGLER_CWD to a folder whose wrangler config names the
  database, such as the site repository's worker/) to read through wrangler instead.

What is kept between runs (data/build/inbound-mail.json, saved with the pipeline state, never published)
  Per message: its list, receipt time, R2 key, size, the sender's domain, whether Cloudflare's check verified the
  sender, the parser and its version, the result (notice, not_notice, account, needs_rule, failed, unverified,
  unknown_list, correspondence, fetch_failed), the reason, and the records it made. No subject, address, name or body.
  A message is read again only when its parser's VERSION or its list's settings change, or its fetch failed; a
  message that does not parse is kept and counted with its reason, never dropped and never guessed.

Trust
  Anyone can write to these addresses. A message makes records only when Cloudflare's own Authentication-Results (the
  first one, written by mx.cloudflare.net) shows DMARC passed for its From domain, or DKIM passed for one of the
  list's signing domains, and that From domain is one of the list's senders; otherwise it is "unverified", counted,
  never read further.

One event, not two
  A Massachusetts notice and MassDEP's portal record of the same overflow (same permit, same outfall number, starts
  within 3 hours) are one event: every e-mail record of that notice chain becomes duplicate_of the portal's shown
  record (the one no later portal record replaces), so the portal's record keeps the map and the e-mail's facts it
  lacks (the estimated volume, the cessation time) are attached to it by the status build (linked_notices).
  Manchester's e-mails repeat the city's page posts (ingest.nh_permittees): each becomes the duplicate of its post.
  This module runs after ma_massdep and nh_permittees (sorted order) and reads their events files of the same run.

A list that goes quiet (meta.quiet; the status build lists it as a stale reason)
  Lists that send only when something happens are checked against another source that sees the same operator: a
  portal notice (or Manchester page post) that started after the sign-up, published 6 hours or more ago, with nothing
  from the list since an hour before its start, means the list is not reaching us. A list of regular releases (CT
  DEEP's press list, weekly at least) is quiet after max_quiet_days without a message.

Usage (from pipeline/):  python -m ingest.operator_mail [--max-fetch N]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from common import BUILD_DIR, DATA_DIR, EVENTS_DIR, read_json, write_events, write_json
from ingest.mail import PARSERS
from ingest.mail.message import outfall_number, parse_iso, parse_mail, verified

LISTS_FILE = DATA_DIR / "mail-lists.json"
INDEX_FILE = BUILD_DIR / "inbound-mail.json"
D1_DATABASE = "dirtywaterwatch"
WRANGLER_REDACT = Path(__file__).resolve().parents[2] / "scripts" / "wrangler_redact.py"
D1_DATABASE_ID = "4231c50f-6207-4297-89d3-d4224b7cbb91"     # site repository worker-mail/wrangler.jsonc
RAW_BUCKET = "dirtywaterwatch-raw"
API = "https://api.cloudflare.com/client/v4"
ROWS_SQL = ("SELECT id, received_at, list_id, raw_key, size FROM inbound WHERE channel = 'email' "
            "ORDER BY received_at")
MAX_FETCH = 200                 # raw messages read per run (new, re-parsed, retried)
PORTAL_LINK_HOURS = 3           # ma_massdep's own rule for a notice and its verified report
CHAIN_HOURS = 72                # a Ceased notice closes the open notice of its outfall that started at most this long before
QUIET_GRACE_H = 6               # a cross-check notice counts once it was published this long ago
QUIET_LEAD_H = 1                # ... and the list said nothing from an hour before its start
RETRY = {"fetch_failed"}


# ---------------------------------------------------------------- reading the index and the archive

class ApiTransport:
    """Cloudflare's REST API with the workflow's token (D1 query, R2 object read)."""

    def __init__(self, token: str, account: str, sess: requests.Session | None = None):
        self.account = account
        self.sess = sess or requests.Session()
        self.sess.headers.update({"Authorization": f"Bearer {token}"})

    @staticmethod
    def _why(r: requests.Response) -> str:
        try:
            errs = r.json().get("errors") or []
            codes = ", ".join(f"{e.get('code')}: {str(e.get('message'))[:80]}" for e in errs[:2])
        except ValueError:
            codes = ""
        return f"HTTP {r.status_code}" + (f" ({codes})" if codes else "")

    def rows(self) -> list[dict]:
        r = self.sess.post(f"{API}/accounts/{self.account}/d1/database/{D1_DATABASE_ID}/query",
                           json={"sql": ROWS_SQL}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"D1 inbound index answered {self._why(r)}")
        res = (r.json().get("result") or [{}])[0]
        if not res.get("success", True):
            raise RuntimeError("D1 inbound query did not succeed")
        return res.get("results") or []

    def raw(self, key: str) -> bytes:
        if os.environ.get("R2_S3_ENDPOINT"):
            return self._raw_s3(key)
        r = self.sess.get(f"{API}/accounts/{self.account}/r2/buckets/{RAW_BUCKET}/objects/{quote(key, safe='/')}",
                          timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"R2 object answered {self._why(r)}")
        return r.content

    @staticmethod
    def _raw_s3(key: str) -> bytes:
        """The raw message through R2's S3 endpoint (scripts/r2-s3-keys.sh: the token is limited to the pipeline's
        buckets, which Cloudflare's REST API refuses for object reads). To stdout, never to a file; the error is
        reported by its kind only."""
        aws = os.environ.get("AWS_CLI") or shutil.which("aws") or "aws"
        cmd = [aws, "--endpoint-url", os.environ["R2_S3_ENDPOINT"], "--region",
               os.environ.get("AWS_DEFAULT_REGION") or "auto", "s3", "cp", f"s3://{RAW_BUCKET}/{key}", "-",
               "--only-show-errors"]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(f"R2 S3 read could not run ({type(e).__name__})") from None
        if p.returncode != 0 or not p.stdout:
            kind = "absent" if re.search(rb"An error occurred \(404\) when calling the HeadObject operation", p.stderr) \
                else f"exit {p.returncode}"
            raise RuntimeError(f"R2 S3 read failed ({kind})")
        return p.stdout


class WranglerTransport:
    """wrangler on a developer's machine (its own sign-in), for a hand run."""

    def __init__(self, cwd: str | None = None):
        self.cwd = cwd
        self.bin = os.environ.get("WRANGLER") or "wrangler"

    def _run(self, args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
        # through the filter that keeps the token's account name and e-mail addresses out of any log; the --json and
        # --pipe output a caller reads passes byte for byte when wrangler succeeds (scripts/wrangler_redact.py)
        return subprocess.run([sys.executable, "-I", str(WRANGLER_REDACT), *args], cwd=self.cwd, capture_output=True,
                              timeout=timeout, env={**os.environ, "WRANGLER_REAL": shutil.which(self.bin) or self.bin})

    def rows(self) -> list[dict]:
        p = self._run(["d1", "execute", D1_DATABASE, "--remote", "--json", "--command", ROWS_SQL])
        if p.returncode != 0:
            raise RuntimeError(f"wrangler d1 execute exited {p.returncode}")
        return (json.loads(p.stdout.decode()) or [{}])[0].get("results") or []

    def raw(self, key: str) -> bytes:
        # to stdout (--pipe): the raw message is never written to a file (Astra mail review 2026-11-17 P1-4)
        p = self._run(["r2", "object", "get", f"{RAW_BUCKET}/{key}", "--remote", "--pipe"])
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError(f"wrangler r2 object get exited {p.returncode}")
        return p.stdout


def transport_from_env():
    if os.environ.get("MAIL_WRANGLER"):
        return WranglerTransport(os.environ.get("MAIL_WRANGLER_CWD"))
    token, account = os.environ.get("CLOUDFLARE_API_TOKEN"), os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if token and account:
        return ApiTransport(token, account)
    return None


# ---------------------------------------------------------------- the lists and the index

def load_lists(path: Path = LISTS_FILE) -> dict:
    return (read_json(path, {}) or {}).get("lists") or {}


def rule_of(spec: dict | None) -> str:
    """What a message's reading depends on: the list's settings and its parser's version."""
    if not spec:
        return "unknown_list"
    parser = PARSERS.get(spec.get("parser") or "")
    body = json.dumps({k: v for k, v in spec.items() if k not in ("quiet", "since")}, sort_keys=True)
    return f"{spec.get('kind')}:{spec.get('parser')}:{getattr(parser, 'VERSION', 0)}:" \
           f"{hashlib.sha1(body.encode()).hexdigest()[:10]}"


def read_message(raw: bytes, row: dict, spec: dict | None, ctx: dict) -> dict:
    """One message -> its index entry (result, reason, records). Never raises for a message's content."""
    entry = {"list_id": row.get("list_id"), "received_at": row.get("received_at"), "raw_key": row.get("raw_key"),
             "size": row.get("size"), "rule": rule_of(spec)}
    try:
        mail = parse_mail(raw, str(row["id"]), str(row.get("received_at")), row.get("list_id"))
    except Exception as e:  # noqa: BLE001 - an unreadable message is kept and counted
        return {**entry, "result": "failed", "note": f"message could not be read: {type(e).__name__}", "records": []}
    entry["from_domain"] = mail.from_domain
    if spec is None:
        return {**entry, "result": "unknown_list", "note": "no list in data/mail-lists.json for this address",
                "records": []}
    if spec.get("kind") == "correspondence":
        return {**entry, "result": "correspondence", "note": "an address for letters, never parsed", "records": []}
    if spec.get("kind") == "context":
        return {**entry, "result": "not_notice", "note": "a context list (news), never a record", "records": []}
    if spec.get("kind") == "pending":
        # a list signed up to before its parser exists: kept and counted under its list, never a record
        acct = re.search(r"(?i)confirm|verif|welcome|thank(?:s| you) for|subscri", mail.subject or "")
        return {**entry, "result": "account" if acct else "needs_rule",
                "note": "a sign-up or confirmation message" if acct else "a list without a parser yet", "records": []}
    trust, how = verified(mail, spec)
    entry["trust"], entry["verified"] = trust, how
    if not trust:
        return {**entry, "result": "unverified", "note": how, "records": []}
    parser = PARSERS.get(spec.get("parser") or "")
    if parser is None:
        return {**entry, "result": "failed", "note": f"no parser named {spec.get('parser')!r}", "records": []}
    try:
        res = parser.parse(mail, spec, ctx)
    except Exception as e:  # noqa: BLE001 - a parser error is a failure of that message, kept with its reason
        # the exception's type only: its message can quote the notice (Astra mail review 2026-11-17 P1-2)
        return {**entry, "result": "failed", "note": f"parser error ({type(e).__name__})", "records": []}
    recs = res.records if res.kind == "notice" else []
    for r in recs:
        r["raw"]["_trust"] = trust
    return {**entry, "result": res.kind, "note": res.note, "records": recs}


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


RETRY_MAX = 12                  # fetch attempts before a message is left as fetch_failed for good (counted)


def update_index(index: dict, rows: list[dict], tr, lists: dict, ctx: dict, max_fetch: int = MAX_FETCH,
                 now: datetime | None = None) -> Counter:
    """Read the messages that need it, in this order: never read (newest first), read under an older rule, then
    fetch failures whose wait is over (1, 2, 4 ... 24 hours apart, RETRY_MAX tries). A row left for a later run is
    entered as "pending" at once, so it is counted (Astra mail review 2026-11-17 P1-5)."""
    now = now or datetime.now(UTC)
    msgs = index.setdefault("messages", {})
    stats = Counter()
    new, reread, retry = [], [], []
    for row in rows:
        mid = str(row.get("id") or "")
        if not mid or not row.get("raw_key"):
            stats["index_row_without_key"] += 1
            continue
        spec = lists.get(row.get("list_id") or "")
        old = msgs.get(mid)
        if old is None or old.get("result") == "pending":
            new.append(row)
        elif old.get("rule") != rule_of(spec):
            reread.append(row)
        elif old.get("result") == "fetch_failed" and (old.get("tries") or 0) < RETRY_MAX \
                and (parse_iso(old.get("next_try_at")) or now) <= now:
            retry.append(row)
    new.sort(key=lambda r: str(r.get("received_at") or ""), reverse=True)
    fetched = 0
    for row in new + reread + retry:
        mid = str(row["id"])
        spec = lists.get(row.get("list_id") or "")
        old = msgs.get(mid)
        base = {"list_id": row.get("list_id"), "received_at": row.get("received_at"), "raw_key": row.get("raw_key"),
                "size": row.get("size"), "rule": rule_of(spec)}
        if fetched >= max_fetch:
            if old is None:
                msgs[mid] = {**base, "result": "pending", "note": "not read yet (the run's reading limit)", "records": []}
            stats["left_for_next_run"] += 1
            continue
        fetched += 1
        try:
            raw = tr.raw(row["raw_key"])
        except Exception as e:  # noqa: BLE001 - kept, tried again later
            tries = ((old or {}).get("tries") or 0) + 1 if (old or {}).get("result") == "fetch_failed" else 1
            msgs[mid] = {**(old or {}), **base, "result": "fetch_failed", "note": str(e)[:200], "tries": tries,
                         "next_try_at": (now + timedelta(hours=min(2 ** (tries - 1), 24))).isoformat(),
                         "records": (old or {}).get("records") or []}
            stats["fetch_failed"] += 1
            continue
        msgs[mid] = read_message(raw, row, spec, ctx)
        stats["read"] += 1
    stats["fetched"] = fetched
    return stats


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


def build_list(lid: str, spec: dict, entries: list[dict], others: dict, now: datetime) -> tuple[list[dict], dict]:
    recs = list_records(entries)
    for r in recs:                  # links are made afresh each run
        r["duplicate_of"] = None
        r["parent_event_id"] = None
        for k in ("_chain", "_link_basis"):
            r["raw"].pop(k, None)
    stats = {}
    if spec.get("parser") == "manchester":
        PARSERS["manchester"].pair(recs)
        stats["linked_to_page"] = PARSERS["manchester"].link_page(recs, others.get("nh-permittees") or [])
    elif spec.get("outfall_prefix"):
        link_chains(recs)
        stats["linked_to_portal"] = link_portal(recs, others.get("ma-massdep") or [], spec.get("npdes_permit"))
    # a message proven only by a shared platform (raw._trust "platform") may add to another source's record of the same
    # discharge, never stand alone: a chain of such records not linked as a duplicate is held back, counted, unpublished
    held_chains = {r["raw"].get("_chain") or r["event_id"] for r in recs
                   if r["raw"].get("_trust") == "platform" and not r.get("duplicate_of")}
    held = [r for r in recs if (r["raw"].get("_chain") or r["event_id"]) in held_chains]
    recs = [r for r in recs if (r["raw"].get("_chain") or r["event_id"]) not in held_chains]
    stats["held_platform_only"] = len(held)
    res = Counter(e.get("result") for e in entries)
    received = [e.get("received_at") for e in entries if e.get("received_at")]
    meta = {
        "channel": "email", "list_id": lid, "address": spec.get("address"), "signed_up": spec.get("since"),
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


def run(tr, lists: dict, index_path: Path = INDEX_FILE, events_dir: Path = EVENTS_DIR, now: datetime | None = None,
        max_fetch: int = MAX_FETCH) -> int:
    now = now or datetime.now(UTC)
    notice_lists = {k: v for k, v in lists.items() if v.get("kind") == "notices" and v.get("source_id")}
    index = read_json(index_path, {}) or {}
    error = None
    if tr is None:
        error = "no Cloudflare credentials in the environment (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID)"
    else:
        try:
            rows = tr.rows()
        except Exception as e:  # noqa: BLE001
            error = f"the inbound mail index could not be read: {str(e)[:200]}"
    if error:
        for lid, spec in notice_lists.items():
            write_events(spec["source_id"], [], ok=False, error=error, path=events_dir / f"{spec['source_id']}.json")
        print(f"operator_mail: {error}; every list keeps its previous records", file=sys.stderr)
        return 1
    ctx = ma_context(notice_lists)
    stats = update_index(index, rows, tr, lists, ctx, max_fetch, now)
    index["read_at"] = now.isoformat()
    index["index_rows"] = len(rows)
    write_json(index_path, index)
    by_list = defaultdict(list)
    for mid, e in (index.get("messages") or {}).items():
        by_list[e.get("list_id")].append({**e, "_id": mid})
    others = {sid: read_events(sid, events_dir) for sid in ("ma-massdep", "nh-permittees")}
    for lid, spec in sorted(notice_lists.items()):
        recs, meta = build_list(lid, spec, by_list.get(lid, []), others, now)
        write_events(spec["source_id"], recs, ok=True, meta=meta, path=events_dir / f"{spec['source_id']}.json")
        q = " quiet" if meta.get("quiet") else ""
        print(f"  {lid}: {meta['messages']} messages, {meta['records']} records, "
              f"results {json.dumps(meta['results'], sort_keys=True)}{q}", file=sys.stderr)
    other = Counter(e.get("result") for lid, es in by_list.items() if lid not in notice_lists for e in es)
    print(f"operator_mail: {len(rows)} index rows; read {stats.get('read', 0)}, fetch failed "
          f"{stats.get('fetch_failed', 0)}, left for next run {stats.get('left_for_next_run', 0)}; other addresses "
          f"{json.dumps(dict(sorted(other.items())), sort_keys=True)}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--max-fetch", type=int, default=MAX_FETCH)
    a = ap.parse_args(argv)
    run(transport_from_env(), load_lists(), max_fetch=a.max_fetch)
    return 0    # a failed read is recorded as the lists' health; the refresh goes on


if __name__ == "__main__":
    sys.exit(main())
