"""openboatlaunch's partner API (v1), the client the pipeline reads it with. Standard library only, so the workflows'
`python3 -I scripts/state_paths.py fetch-obl` can load it before the virtual environment exists.

Base https://openboatlaunch.org/api/v1/ (OBL_API_BASE overrides it: https, or http on this machine only, for the
tests). GET, JSON. The key is read from the environment variable OBL_API_KEY and sent as `Authorization: Bearer`;
it is never printed, logged, written to a file or put in a message: every message here is built from the path, the
HTTP status and the answer's own `error` word, and any text that could carry the key is scrubbed first (scrub()).
The user agent is DirtyWaterWatch-pipeline/1 (+https://dirtywaterwatch.org).

Endpoints used (the contract is openboatlaunch's docs/api/v1.md):
  meta                          snapshot, built, counts, licence, bulk URLs with size and sha256; ETag/304
  states/{ST}/waters            one state's records sorted by slug, 500 a page, next_cursor; geometry=0 leaves the
                                outlines out (the extract needs none)
  waters/{slug}                 one record; renamed or merged answers 301 with the old record's body and Location the
                                successor, deleted 410 with its body. Redirects are never followed: the 301 is the news.
  changes?since=&cursor=        the changes after a time, paged; `until` is the next since; 410 means do a full pull
  bulk/national.tar.gz(.sha256) meta.json and water/<slug>.json, one per record per state (non-active records too)

Request budget (docs/openboatlaunch-api-requirements.md §5, site repository): meta and changes hourly (a 304 most
hours), the national bulk at most once a day (scripts/state_paths.py fetch-obl), state pages only on a state build
(ingest.obl_waters --from-api). 429 and 5xx answers are retried up to three times, waiting Retry-After (at most 30 s).
The answers worth keeping are cached under data/raw/obl-api/ (scripts/state_paths.py RAW_CACHE): meta with its ETag
(the hourly 304 needs the body it confirms) and a state's pages with the snapshot they came from.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

BASE = "https://openboatlaunch.org/api/v1/"
USER_AGENT = "DirtyWaterWatch-pipeline/1 (+https://dirtywaterwatch.org)"
KEY_ENV = "OBL_API_KEY"
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.environ.get("OBL_API_CACHE_DIR") or ROOT / "data" / "raw" / "obl-api")   # the tests point it elsewhere
BODY_MAX = 64 * 1024 * 1024          # a JSON answer larger than this is refused (a state page with outlines is a few MB)
ERROR_BODY_MAX = 1 << 20
TRIES = 3


class ApiError(Exception):
    """The API could not be read; the message never carries the key or a header."""

    def __init__(self, msg: str, status: int | None = None):
        super().__init__(scrub(msg))
        self.status = status


@dataclass
class Answer:
    status: int
    body: bytes = b""
    etag: str | None = None
    last_modified: str | None = None
    location: str | None = None
    size: int = 0
    sha256: str | None = None
    extra: dict = field(default_factory=dict)

    def json(self):
        return json.loads(self.body.decode("utf-8")) if self.body else None


def key() -> str | None:
    k = (os.environ.get(KEY_ENV) or "").strip()
    return k or None


def scrub(text: str) -> str:
    """text with the key (if set) replaced, so no message can carry it."""
    k = key()
    text = str(text)
    return text.replace(k, "[key]") if k else text


def base() -> str:
    b = os.environ.get("OBL_API_BASE") or BASE
    b = b if b.endswith("/") else b + "/"
    u = urllib.parse.urlsplit(b)
    if not (u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost"))):
        raise ApiError("OBL_API_BASE must be an https URL")
    return b


def path_of(url: str) -> str:
    """A URL the API gave (bulk URLs in meta, a Location) as a path under the base; ApiError when it is elsewhere
    (the key is sent only to the base)."""
    b = base()
    full = urllib.parse.urljoin(b, url)
    if not full.startswith(b):
        raise ApiError("a URL outside the API base was given; not requested")
    return full[len(b):]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - the 301 is read, not followed
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _error_word(body: bytes) -> str:
    try:
        d = json.loads(body.decode("utf-8"))
        return str(d.get("error") or "")[:40] if isinstance(d, dict) else ""
    except Exception:  # noqa: BLE001 - an HTML error page from the CDN
        return ""


def get(path: str, params: dict | None = None, etag: str | None = None, timeout: float = 120,
        stream_to: Path | None = None, tries: int = TRIES, accept_json: bool = True) -> Answer:
    """GET base()+path. Returns the Answer for 200 and for 301, 304, 404 and 410 (their bodies kept); retries 429 and
    5xx and network failures; raises ApiError otherwise or after the tries. stream_to: the body is written there
    (sha256 and size computed on the way) instead of kept."""
    url = base() + path.lstrip("/")
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json" if accept_json else "*/*"}
    if key():
        headers["Authorization"] = f"Bearer {key()}"
    if etag:
        headers["If-None-Match"] = etag
    last = "no answer"
    for n in range(tries):
        req = urllib.request.Request(url, headers=headers, method="GET")
        wait = 5.0 * (n + 1)
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                a = Answer(r.status, etag=r.headers.get("ETag"), last_modified=r.headers.get("Last-Modified"))
                if stream_to is not None:
                    h, size = hashlib.sha256(), 0
                    with open(stream_to, "wb") as fh:
                        while chunk := r.read(1 << 20):
                            h.update(chunk)
                            fh.write(chunk)
                            size += len(chunk)
                    a.size, a.sha256 = size, h.hexdigest()
                else:
                    a.body = r.read(BODY_MAX + 1)
                    if len(a.body) > BODY_MAX:
                        raise ApiError(f"{path}: answer over {BODY_MAX >> 20} MB; refused")
                    a.size = len(a.body)
                return a
        except urllib.error.HTTPError as e:
            body = e.read(ERROR_BODY_MAX) if e.fp is not None else b""
            if e.code in (301, 302, 304, 404, 410):
                return Answer(e.code, body=body, etag=e.headers.get("ETag"),
                              last_modified=e.headers.get("Last-Modified"), location=e.headers.get("Location"))
            last = f"HTTP {e.code}" + (f" {w}" if (w := _error_word(body)) else "")
            if e.code != 429 and e.code < 500:
                raise ApiError(f"{path}: {last}", e.code) from None
            try:
                wait = min(float(e.headers.get("Retry-After") or wait), 30.0)
            except ValueError:
                pass
        except ApiError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last = type(e).__name__ + (f" ({type(e.reason).__name__})" if isinstance(e, urllib.error.URLError)
                                       and not isinstance(e.reason, str) else "")
        if stream_to is not None:
            Path(stream_to).unlink(missing_ok=True)
        if n < tries - 1:
            time.sleep(float(os.environ.get("OBL_API_RETRY_S") or wait))
    raise ApiError(f"{path}: {last} after {tries} tries")


def get_json(path: str, params: dict | None = None, **kw):
    a = get(path, params, **kw)
    if a.status != 200:
        raise ApiError(f"{path}: HTTP {a.status}" + (f" {w}" if (w := _error_word(a.body)) else ""), a.status)
    try:
        return a.json()
    except ValueError:
        raise ApiError(f"{path}: the answer is not JSON") from None


# ---------------------------------------------------------------- cached answers

def _cache_write(rel: str, obj) -> None:
    p = CACHE_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False))
    tmp.replace(p)


def _cache_read(rel: str):
    try:
        return json.loads((CACHE_DIR / rel).read_text())
    except (OSError, ValueError):
        return None


def meta(use_cache: bool = True) -> dict:
    """The API's meta, asked with the cached ETag (a 304 returns the cached body). Raises ApiError."""
    cached = _cache_read("meta.json") if use_cache else None
    etag = cached.get("etag") if isinstance(cached, dict) and isinstance(cached.get("meta"), dict) else None
    a = get("meta", etag=etag)
    if a.status == 304 and etag:
        m = cached["meta"]
        m["_not_modified"] = True
        return m
    if a.status != 200:
        raise ApiError(f"meta: HTTP {a.status}", a.status)
    try:
        m = a.json()
    except ValueError:
        raise ApiError("meta: the answer is not JSON") from None
    if not isinstance(m, dict) or not m.get("snapshot") or not m.get("built"):
        raise ApiError("meta: no snapshot or built in the answer")
    _cache_write("meta.json", {"etag": a.etag, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                               "meta": m})
    return m


def state_waters(state: str, snapshot: str | None = None, geometry: bool = False, limit: int = 500) -> tuple[list, str]:
    """(every record of a state in the API, sorted by slug, non-active ones included; the snapshot they came from).
    Pages are cached under data/raw/obl-api/states/<ST>.json with their snapshot: when snapshot (meta's) is the
    cached one, nothing is asked. Raises ApiError (a state the API does not have answers 404)."""
    st = state.upper()
    rel = f"states/{st}{'' if not geometry else '-geometry'}.json"
    cached = _cache_read(rel)
    if snapshot and isinstance(cached, dict) and cached.get("snapshot") == snapshot and isinstance(cached.get("waters"), list):
        return cached["waters"], snapshot
    out, cursor, snap = [], None, None
    for _ in range(1000):
        d = get_json(f"states/{st}/waters", {"limit": limit, "cursor": cursor, "geometry": None if geometry else 0})
        if not isinstance(d, dict) or not isinstance(d.get("waters"), list):
            raise ApiError(f"states/{st}/waters: no waters list in the answer")
        if snap and d.get("snapshot") != snap:
            raise ApiError(f"states/{st}/waters: the snapshot changed between pages; asked again next time")
        snap = d.get("snapshot")
        out += d["waters"]
        cursor = d.get("next_cursor")
        if not cursor:
            break
    else:
        raise ApiError(f"states/{st}/waters: more than 1,000 pages")
    _cache_write(rel, {"snapshot": snap, "waters": out})
    return out, snap


def water(slug: str) -> tuple[int, dict | None, str | None]:
    """(status, record, successor slug from Location) for waters/{slug}: 200 the record, 301 the old record with its
    successor, 410 the deleted record, 404 none. Raises ApiError otherwise."""
    a = get(f"waters/{urllib.parse.quote(slug)}")
    if a.status not in (200, 301, 410, 404):
        raise ApiError(f"waters/{slug}: HTTP {a.status}", a.status)
    try:
        rec = a.json() if a.status != 404 else None
    except ValueError:
        rec = None
    succ = None
    if a.location:
        succ = urllib.parse.unquote(a.location.rstrip("/").rsplit("/", 1)[-1])
    return a.status, rec if isinstance(rec, dict) else None, succ


def changes(since: str, etag: str | None = None) -> dict:
    """{"status": 200|304|410, "changes": [...], "until": ..., "etag": ...} for changes?since=, every page read."""
    out, cursor, until, first_etag = [], None, None, None
    for n in range(1000):
        a = get("changes", {"since": since, "cursor": cursor}, etag=etag if n == 0 else None)
        if n == 0:
            first_etag = a.etag
            if a.status in (304, 410):
                return {"status": a.status, "changes": [], "until": None, "etag": etag if a.status == 304 else None}
        if a.status != 200:
            raise ApiError(f"changes: HTTP {a.status}", a.status)
        d = a.json()
        if not isinstance(d, dict) or not isinstance(d.get("changes"), list):
            raise ApiError("changes: no changes list in the answer")
        out += d["changes"]
        until = d.get("until") or until
        cursor = d.get("next_cursor")
        if not cursor:
            break
    else:
        raise ApiError("changes: more than 1,000 pages")
    if not until:
        raise ApiError("changes: no until in the answer")
    return {"status": 200, "changes": out, "until": until, "etag": first_etag}
