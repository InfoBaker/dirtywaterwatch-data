"""Operators' e-mail notices, the read: the site's mail index and raw messages -> per-list inbox files (2026-11-18).

Runs only in the private site repository's .github/workflows/mail-feed.yml (hourly, with the site's own Cloudflare
token), never in this repository's refresh, whose token reaches R2 objects in dirtywaterwatch-data only. The public
refresh's ingest/operator_mail.py takes the files this writes, places the records and links them (the one-event rules,
the platform hold, the quiet check). The site repository's docs/mail-feed.md has the layout, the token and the cost.

Where the mail comes from
  The mail Worker `dirtywaterwatch-mail` (site repository, worker-mail/) receives every message sent to an address at
  dirtywaterwatch.org, archives it in R2 (bucket dirtywaterwatch-raw, email/<yyyy>/<mm>/<dd>/<id>.eml) and indexes it in
  D1 (database dirtywaterwatch, table inbound: id, received_at, to_addr, list_id, raw_key, ...). The list_id is the
  local part of the address the list was signed up with (springfield@ -> "springfield"). This reads the index (one D1
  query: id, receipt time, list, key, size; never the subject or the addresses) and each new raw message (one R2 read),
  parses the message in memory and never writes it to disk, logs it or saves it; the log prints counts per list only.
  Off the runner (a developer's machine with wrangler signed in) MAIL_WRANGLER=1 (and MAIL_WRANGLER_CWD, a folder whose
  wrangler config names the database, such as the site repository's worker/) reads through wrangler instead.

What it writes (bucket dirtywaterwatch-data)
  inbox/mail/<list's source id>.json, one per notice list (data/mail-lists.json kind "notices"), every run:
    {"schema": 1, "list_id", "source_id", "written_at", "ok", "error", "stats",
     "entries": [{"id", "received_at", "result", "note", "trust", "records"}]}
    entries: every message the index holds for the list, with its result and note and the records its parser made,
    neither placed nor linked (the refresh does both). No subject, address, name or body: what a record keeps is what
    the parser took from labelled lines (ingest/mail/), as before. ok false (the index could not be read, or no
    credentials): error says why, entries is empty, and the refresh keeps each list's previous records.
  inbox/mail/state/inbound-mail.json, the read's own state (what data/build/inbound-mail.json held in the refresh
    before the split): per message its list, receipt time, R2 key, size, the sender's domain, whether Cloudflare's
    check verified the sender, the parser rule, the result, the note and the records. No subject, address, name or
    body. It is restored at the start of each run and saved at the end, so a run reads only new messages, messages
    whose parser's VERSION or list settings changed (this repository's main, which the job checks out), and fetch
    failures whose wait is over. An absent state (the first run) reads every message (--max-fetch per run, newest
    first); a state that is there but cannot be read stops the run before anything is written.

Trust, the per-message results and the retries are as before the split (rule_of, read_message, update_index). What is
saved or logged about a failure is a fixed category (inbox.category: an HTTP status with Cloudflare's numeric codes,
absent, denied, unreachable, timeout), never the words of Cloudflare or the AWS CLI, which can carry the account id or
an address (Astra review 2026-11-18 P1-3).

Credentials (review P1-2): the job's own token (the site's MAIL_FEED_CLOUDFLARE_TOKEN: D1 Read, R2 object Read on
dirtywaterwatch-raw, Write on dirtywaterwatch-data). With R2_S3_ENDPOINT set (scripts/r2-s3-keys.sh) every R2 call,
raw reads and the data bucket's state and inbox alike, goes through R2's S3 endpoint with the AWS CLI; D1 through the
REST API.

Usage (from pipeline/):
  python -m mailfeed.read --r2 [--max-fetch N]        the job: state from and files to the bucket (REST API, the
                                                       site's CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID)
  python -m mailfeed.read --out DIR [--max-fetch N]   a hand run: DIR/state/inbound-mail.json and DIR/inbox/mail/;
                                                       DWW_INBOX_DIR=DIR python -m ingest.operator_mail links them
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from common import read_json, write_json
from inbox import category, category_of
from ingest.mail import PARSERS
from ingest.mail.message import parse_iso, parse_mail, verified
from ingest.operator_mail import INBOX_PREFIX, INBOX_SCHEMA, load_lists

D1_DATABASE = "dirtywaterwatch"
D1_DATABASE_ID = "4231c50f-6207-4297-89d3-d4224b7cbb91"     # site repository worker-mail/wrangler.jsonc
RAW_BUCKET = "dirtywaterwatch-raw"
DATA_BUCKET = "dirtywaterwatch-data"
STATE_KEY = INBOX_PREFIX + "state/inbound-mail.json"
API = "https://api.cloudflare.com/client/v4"
ROWS_SQL = ("SELECT id, received_at, list_id, raw_key, size FROM inbound WHERE channel = 'email' "
            "ORDER BY received_at")
MAX_FETCH = 200                 # raw messages read per run (new, re-parsed, retried)
RETRY = {"fetch_failed"}
RETRY_MAX = 12                  # fetch attempts before a message is left as fetch_failed for good (counted)
# `aws s3 cp s3://... -` says this of an absent object; a bad key, a missing bucket or a refusal is a failure, never
# "absent" (the r2-s3 review's P1, data repository 8551eb0): a refused state read must not look like a first run
S3_ABSENT = re.compile(rb"An error occurred \(404\) when calling the HeadObject operation")
ROOT = Path(__file__).resolve().parents[2]
WRANGLER_REDACT = ROOT / "scripts" / "wrangler_redact.py"


def _redactor():
    spec = importlib.util.spec_from_file_location("wrangler_redact", WRANGLER_REDACT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.redact


_REDACT = _redactor()


def safe(text: str, account: str | None = None) -> str:
    """Text from Cloudflare or a transport, fit for a log or a public file: no account id, no address, no account name
    (scripts/wrangler_redact.py's filter)."""
    t = str(text)
    for v in {account, os.environ.get("CLOUDFLARE_ACCOUNT_ID")} - {None, ""}:
        t = t.replace(v, "[account]")
    return _REDACT(t)


# ---------------------------------------------------------------- reading the index and the archive

class ApiTransport:
    """Cloudflare's REST API with the job's token (D1 query, R2 object reads and writes)."""

    def __init__(self, token: str, account: str, sess: requests.Session | None = None):
        self.account = account
        self.sess = sess or requests.Session()
        self.sess.headers.update({"Authorization": f"Bearer {token}"})

    def _why(self, r: requests.Response) -> str:
        """The answer's HTTP status and Cloudflare's numeric error codes, never their messages."""
        try:
            errs = r.json().get("errors") or []
            codes = ", ".join(f"{int(e.get('code'))}:" for e in errs[:2] if str(e.get("code") or "").isdigit())
        except (ValueError, AttributeError):
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

    def _object_url(self, bucket: str, key: str) -> str:
        return f"{API}/accounts/{self.account}/r2/buckets/{bucket}/objects/{quote(key, safe='/')}"

    def raw(self, key: str) -> bytes:
        if os.environ.get("R2_S3_ENDPOINT"):
            return self._raw_s3(key)
        r = self.sess.get(self._object_url(RAW_BUCKET, key), timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"R2 object answered {self._why(r)}")
        return r.content

    @staticmethod
    def _aws(*args: str) -> list[str]:
        aws = os.environ.get("AWS_CLI") or shutil.which("aws") or "aws"
        return [aws, "--endpoint-url", os.environ["R2_S3_ENDPOINT"], "--region",
                os.environ.get("AWS_DEFAULT_REGION") or "auto", *args]

    @classmethod
    def _s3_get(cls, bucket: str, key: str) -> bytes | None:
        """An object through R2's S3 endpoint, to stdout (never a file); None when absent; an error by its category."""
        try:
            p = subprocess.run(cls._aws("s3", "cp", f"s3://{bucket}/{key}", "-", "--only-show-errors"),
                               capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(f"R2 S3 read could not run ({category_of(e)})") from None
        if p.returncode == 0:
            return p.stdout
        if S3_ABSENT.search(p.stderr):       # an absent object and nothing else (as scripts/wrangler_redact.py reads it)
            return None
        raise RuntimeError(f"R2 S3 read failed ({category(p.stderr.decode('utf-8', 'replace') + f' exit {p.returncode}')})")

    @classmethod
    def _raw_s3(cls, key: str) -> bytes:
        """The raw message through R2's S3 endpoint (scripts/r2-s3-keys.sh: a token limited to named buckets, which
        Cloudflare's REST API refuses for object reads)."""
        data = cls._s3_get(RAW_BUCKET, key)
        if not data:
            raise RuntimeError("R2 S3 read failed (absent)")
        return data

    def get_object(self, key: str) -> bytes | None:
        """An object of the data bucket; None when there is no such key."""
        if os.environ.get("R2_S3_ENDPOINT"):
            return self._s3_get(DATA_BUCKET, key)
        r = self.sess.get(self._object_url(DATA_BUCKET, key), timeout=60)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise RuntimeError(f"R2 {DATA_BUCKET}/{key} answered {self._why(r)}")
        return r.content

    def put_object(self, key: str, data: bytes) -> None:
        if os.environ.get("R2_S3_ENDPOINT"):
            # the inbox and the state only (no raw text): a temporary file for the AWS CLI's body, removed at once
            with tempfile.NamedTemporaryFile(dir=os.environ.get("RUNNER_TEMP"), suffix=".json") as fh:
                fh.write(data)
                fh.flush()
                try:
                    p = subprocess.run(self._aws("s3api", "put-object", "--bucket", DATA_BUCKET, "--key", key,
                                                 "--body", fh.name, "--content-type", "application/json; charset=utf-8"),
                                       capture_output=True, timeout=300)
                except (OSError, subprocess.TimeoutExpired) as e:
                    raise RuntimeError(f"R2 S3 write could not run ({category_of(e)})") from None
            if p.returncode != 0:
                raise RuntimeError(f"R2 S3 write failed ({category(p.stderr.decode('utf-8', 'replace') + f' exit {p.returncode}')})")
            return
        r = self.sess.put(self._object_url(DATA_BUCKET, key), data=data, timeout=120,
                          headers={"Content-Type": "application/json; charset=utf-8"})
        if r.status_code != 200:
            raise RuntimeError(f"R2 put {DATA_BUCKET}/{key} answered {self._why(r)}")


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


# ---------------------------------------------------------------- the index

def rule_of(spec: dict | None) -> str:
    """What a message's reading depends on: the list's settings and its parser's version."""
    if not spec:
        return "unknown_list"
    parser = PARSERS.get(spec.get("parser") or "")
    body = json.dumps({k: v for k, v in spec.items() if k not in ("quiet", "since")}, sort_keys=True)
    return f"{spec.get('kind')}:{spec.get('parser')}:{getattr(parser, 'VERSION', 0)}:" \
           f"{hashlib.sha1(body.encode()).hexdigest()[:10]}"


def read_message(raw: bytes, row: dict, spec: dict | None, ctx: dict | None = None) -> dict:
    """One message -> its index entry (result, reason, records). Never raises for a message's content. ctx None (the
    job): the Massachusetts records are not placed; the refresh places them (ingest/mail/ma_common.apply_place)."""
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
    if spec.get("kind") in ("pending", "copy"):
        # pending: a list signed up to before its parser exists. copy: a list whose notices repeat reports another
        # source already reads (spec.copy_of), monitored as a public-notice channel. Either way the message is kept and
        # counted under its list, never a record.
        acct = re.search(r"(?i)confirm|verif|welcome|thank(?:s| you) for|subscri", mail.subject or "")
        if acct:
            return {**entry, "result": "account", "note": "a sign-up or confirmation message", "records": []}
        if spec["kind"] == "copy":
            return {**entry, "result": "copy", "records": [],
                    "note": f"the same reports as {', '.join(spec.get('copy_of') or [])}, which the pipeline reads"}
        return {**entry, "result": "needs_rule", "note": "a list without a parser yet", "records": []}
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


def update_index(index: dict, rows: list[dict], tr, lists: dict, ctx: dict | None = None, max_fetch: int = MAX_FETCH,
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
            msgs[mid] = {**(old or {}), **base, "result": "fetch_failed", "note": f"fetch failed ({category_of(e)})",
                         "tries": tries,
                         "next_try_at": (now + timedelta(hours=min(2 ** (tries - 1), 24))).isoformat(),
                         "records": (old or {}).get("records") or []}
            stats["fetch_failed"] += 1
            continue
        msgs[mid] = read_message(raw, row, spec, ctx)
        stats["read"] += 1
    stats["fetched"] = fetched
    return stats


# ---------------------------------------------------------------- the inbox files

ENTRY_KEYS = ("received_at", "result", "note", "trust", "records")     # what the refresh needs of a message


def inbox_files(index: dict, lists: dict, now: datetime, error: str | None = None,
                stats: dict | None = None) -> dict[str, dict]:
    """{source_id: the list's inbox file}. error: the read failed, and every file says so with no entries."""
    notice_lists = {k: v for k, v in lists.items() if v.get("kind") == "notices" and v.get("source_id")}
    by_list = defaultdict(list)
    if not error:
        for mid, e in (index.get("messages") or {}).items():       # the state's order, which the refresh keeps
            by_list[e.get("list_id")].append({"id": mid, **{k: e.get(k) for k in ENTRY_KEYS}})
    at = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {spec["source_id"]: {"schema": INBOX_SCHEMA, "list_id": lid, "source_id": spec["source_id"],
                                "written_at": at, "ok": not error, "error": error, "stats": dict(stats or {}),
                                "entries": by_list.get(lid, [])}
            for lid, spec in sorted(notice_lists.items())}


def run(tr, lists: dict, state_path: Path, out_dir: Path, now: datetime | None = None,
        max_fetch: int = MAX_FETCH) -> int:
    """Read what is new into the state at state_path and write each list's file to out_dir/<source id>.json.
    0: read; 1: the index could not be read (the files say so)."""
    now = now or datetime.now(UTC)
    index = read_json(state_path, {}) or {}
    error, stats = None, Counter()
    if tr is None:
        error = "no Cloudflare credentials in the environment (CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID)"
    else:
        try:
            rows = tr.rows()
        except Exception as e:  # noqa: BLE001
            error = f"the inbound mail index could not be read ({category_of(e)})"
        else:
            if not rows:        # the index only grows: no rows is a wrong database or query, never "no mail"
                error = "the inbound mail index answered no rows"
    if not error:
        stats = update_index(index, rows, tr, lists, None, max_fetch, now)
        index["read_at"] = now.isoformat()
        index["index_rows"] = len(rows)
        write_json(state_path, index)
    files = inbox_files(index, lists, now, error, {"index_rows": len(rows) if not error else None, **stats})
    out_dir.mkdir(parents=True, exist_ok=True)
    for sid, doc in files.items():
        write_json(out_dir / f"{sid}.json", doc)
    if error:
        print(f"mail-feed: {error}; each list's file says so and the refresh keeps its previous records",
              file=sys.stderr)
        return 1
    for sid, doc in files.items():
        res = Counter(e.get("result") for e in doc["entries"])
        print(f"  {doc['list_id']}: {len(doc['entries'])} messages, "
              f"{sum(len(e.get('records') or []) for e in doc['entries'] if e.get('result') == 'notice')} notice records, "
              f"results {json.dumps(dict(sorted(res.items())), sort_keys=True)}", file=sys.stderr)
    by_list = {d["list_id"] for d in files.values()}
    other = Counter(e.get("result") for e in (index.get("messages") or {}).values() if e.get("list_id") not in by_list)
    print(f"mail-feed: {len(rows)} index rows; read {stats.get('read', 0)}, fetch failed "
          f"{stats.get('fetch_failed', 0)}, left for next run {stats.get('left_for_next_run', 0)}; other addresses "
          f"{json.dumps(dict(sorted(other.items())), sort_keys=True)}", file=sys.stderr)
    return 0


def run_r2(tr, lists: dict, max_fetch: int = MAX_FETCH, now: datetime | None = None, work: Path | None = None) -> int:
    """The job: the state from the bucket, the read, the files and the state back. A state that is there but cannot be
    read, or an upload that fails, is exit 1; nothing is written before the state is in hand."""
    if not isinstance(tr, ApiTransport):
        print("mail-feed: --r2 needs CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID", file=sys.stderr)
        return 1
    work = work or Path(tempfile.mkdtemp(prefix="mail-feed-", dir=os.environ.get("RUNNER_TEMP")))
    state_path, out_dir = work / "inbound-mail.json", work / "inbox"
    try:
        data = tr.get_object(STATE_KEY)
    except Exception as e:  # noqa: BLE001
        print(f"mail-feed: the saved state could not be read ({category_of(e)}); nothing written",
              file=sys.stderr)
        return 1
    if data is None:
        print("mail-feed: no saved state (a first run): every message is read, newest first, up to --max-fetch",
              file=sys.stderr)
    else:
        try:
            json.loads(data)
        except ValueError:
            print("mail-feed: the saved state is not JSON; nothing written", file=sys.stderr)
            return 1
        state_path.write_bytes(data)
    rc = run(tr, lists, state_path, out_dir, now, max_fetch)
    uploads = [(INBOX_PREFIX + f.name, f) for f in sorted(out_dir.glob("*.json"))]
    if rc == 0:             # each run builds every file from the whole state, so the next run makes good a failed upload
        uploads.append((STATE_KEY, state_path))
    done = failed = 0
    for key, f in uploads:
        try:
            tr.put_object(key, f.read_bytes())
            done += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"mail-feed: {key} not uploaded ({category_of(e)})", file=sys.stderr)
    print(f"mail-feed: uploaded {done} object(s) to {DATA_BUCKET}/{INBOX_PREFIX}" + (f"; {failed} failed" if failed else ""),
          file=sys.stderr)
    shutil.rmtree(work, ignore_errors=True)
    return 1 if rc or failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--r2", action="store_true", help="state from and files to the bucket (the job)")
    where.add_argument("--out", type=Path, help="a folder for the state and the files (a hand run)")
    ap.add_argument("--max-fetch", type=int, default=MAX_FETCH)
    a = ap.parse_args(argv)
    if a.max_fetch < 1:
        ap.error("--max-fetch must be 1 or more")
    if a.r2:
        return run_r2(transport_from_env(), load_lists(), a.max_fetch)
    return run(transport_from_env(), load_lists(), a.out / "state" / "inbound-mail.json",
               a.out / INBOX_PREFIX.rstrip("/"), max_fetch=a.max_fetch)


if __name__ == "__main__":
    sys.exit(main())
