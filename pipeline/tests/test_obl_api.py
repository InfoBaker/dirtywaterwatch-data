"""openboatlaunch's partner API: the client (pipeline/obl_api.py), the national pull (scripts/state_paths.py fetch-obl,
pack-obl, obl-not-saved), the reader of the new record shape and the API extract (ingest/obl_waters.py), the hourly
changes check (ingest/obl_changes.py), the export's launches and the placement stamp. A local server answers from
real API records of 2026-11-07 (pipeline/tests/fixtures/obl-api: six Rhode Island records, meta trimmed to RI; the
launches carry no personal fields). The key is a test value: no output may carry it ("obl_dww").
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PIPE = Path(__file__).resolve().parent.parent
ROOT = PIPE.parent
sys.path.insert(0, str(PIPE))

import obl_api  # noqa: E402
from ingest import obl_changes, obl_waters  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "obl-api"
KEY = "obl_dww_test_0123456789abcdef"            # a test value shaped like the real key's prefix
_spec = importlib.util.spec_from_file_location("state_paths", ROOT / "scripts" / "state_paths.py")
SP = importlib.util.module_from_spec(_spec)
sys.modules["state_paths"] = SP
_spec.loader.exec_module(SP)


def rec(slug):
    return json.loads((FIX / "water" / f"{slug}.json").read_text())


def national_tgz(records=None, meta=None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        def add(name, obj):
            b = json.dumps(obj).encode()
            ti = tarfile.TarInfo(name)
            ti.size = len(b)
            tf.addfile(ti, io.BytesIO(b))
        add("meta.json", meta or json.loads((FIX / "meta.json").read_text()))
        for d in records or [json.loads(p.read_text()) for p in sorted((FIX / "water").glob("*.json"))]:
            add(f"water/{d['slug']}.json", d)
    return buf.getvalue()


class Api:
    """What the local server answers; tests change it."""

    def __init__(self):
        self.meta = json.loads((FIX / "meta.json").read_text())
        self.tgz = national_tgz()
        self.sha_file = None
        self.records = {p.stem: json.loads(p.read_text()) for p in (FIX / "water").glob("*.json")}
        self.deleted = {}
        self.changes = []
        self.history_from = "2026-11-07T02:52:45+00:00"
        self.down = False
        self.page = 2
        self.seen = []           # (path, authorization ok, user agent)


class Handler(BaseHTTPRequestHandler):
    api: Api = None

    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        a = self.api
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        path = u.path.removeprefix("/api/v1/")
        a.seen.append((path, self.headers.get("Authorization") == f"Bearer {KEY}", self.headers.get("User-Agent")))
        if a.down:
            return self.send(503, b'{"error":"unavailable"}', headers={"Retry-After": "0"})
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self.send(401, b'{"error":"unauthorized"}')
        j = lambda o, **h: self.send(200, json.dumps(o).encode(), headers=h)
        etag = f'"{a.meta["snapshot"]}"'
        if path == "meta":
            if self.headers.get("If-None-Match") == etag:
                return self.send(304, headers={"ETag": etag})
            sha = hashlib.sha256(a.tgz).hexdigest()
            return j({**a.meta, "bulk": {"national": {"url": f"http://{self.headers['Host']}/api/v1/bulk/national.tar.gz",
                                                      "size": len(a.tgz), "sha256": sha}}}, ETag=etag)
        if path == "bulk/national.tar.gz":
            return self.send(200, a.tgz, "application/gzip")
        if path == "bulk/national.tar.gz.sha256":
            return self.send(200, (a.sha_file or hashlib.sha256(a.tgz).hexdigest()).encode() + b"  national.tar.gz\n",
                             "text/plain")
        if path == "states/RI/waters":
            rows = sorted((r for r in a.records.values() if r["state"] == "RI"), key=lambda r: r["slug"])
            rows = [{k: v for k, v in r.items() if k != "geometry"} for r in rows]
            cur = q.get("cursor")
            start = next((i for i, r in enumerate(rows) if r["slug"] == cur), 0) if cur else 0
            page = rows[start:start + a.page]
            nxt = rows[start + a.page]["slug"] if start + a.page < len(rows) else None
            return j({"state": "RI", "snapshot": a.meta["snapshot"], "count": len(rows), "limit": a.page,
                      "next_cursor": nxt, "waters": page})
        if path.startswith("waters/"):
            slug = path.split("/", 1)[1]
            if slug in a.deleted:
                return self.send(410, json.dumps(a.deleted[slug]).encode())
            r = a.records.get(slug)
            if r is None:
                return self.send(404, b'{"error":"not_found"}')
            if r["status"] in ("renamed", "merged"):
                return self.send(301, json.dumps(r).encode(), headers={"Location": f"/api/v1/waters/{r['successor_slug']}"})
            return j(r)
        if path == "changes":
            since = q.get("since", "")
            if since < a.history_from:
                return self.send(410, b'{"error":"gone","detail":"do a full pull"}')
            tag = f'"c{len(a.changes)}"'
            if self.headers.get("If-None-Match") == tag:
                return self.send(304, headers={"ETag": tag})
            return j({"since": since, "until": "2026-11-07T05:00:00+00:00", "changes": a.changes, "next_cursor": None},
                     ETag=tag)
        return self.send(404, b'{"error":"not_found"}')


@pytest.fixture
def api(monkeypatch, tmp_path):
    a = Api()
    Handler.api = a
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("OBL_API_BASE", f"http://127.0.0.1:{srv.server_address[1]}/api/v1/")
    monkeypatch.setenv("OBL_API_KEY", KEY)
    monkeypatch.setenv("OBL_API_RETRY_S", "0")
    monkeypatch.setattr(obl_api, "CACHE_DIR", tmp_path / "raw-obl-api")
    monkeypatch.setenv("OBL_API_CACHE_DIR", str(tmp_path / "raw-obl-api"))
    a.base = os.environ["OBL_API_BASE"]
    yield a
    srv.shutdown()


def no_key(*texts):
    for t in texts:
        assert "obl_dww" not in (t or ""), "the key reached the output"


# ---------------------------------------------------------------- the client

def test_client_sends_key_and_agent_and_reads_a_304_from_its_cache(api):
    m = obl_api.meta()
    assert m["snapshot"] == "20261107T025245Z" and "_not_modified" not in m
    m2 = obl_api.meta()
    assert m2["_not_modified"] and m2["snapshot"] == m["snapshot"]
    assert all(ok and ua == obl_api.USER_AGENT for _, ok, ua in api.seen)


def test_redirects_are_read_not_followed_and_gone_is_a_record(api):
    api.deleted["gone-pond-ri"] = {"slug": "gone-pond-ri", "state": "RI", "status": "deleted", "name": "Gone Pond"}
    assert obl_api.water("blue-bill-cove-ri")[0::2] == (301, "sakonnet-river-ri")
    code, r, _ = obl_api.water("gone-pond-ri")
    assert code == 410 and r["status"] == "deleted"
    assert obl_api.water("no-such-ri")[0] == 404


def test_an_error_never_carries_the_key(api):
    api.down = True
    with pytest.raises(obl_api.ApiError) as ex:
        obl_api.meta()
    assert "503" in str(ex.value)
    no_key(str(ex.value))
    assert obl_api.scrub(f"x {KEY} y") == "x [key] y"


def test_a_url_outside_the_base_is_never_asked(api):
    with pytest.raises(obl_api.ApiError):
        obl_api.path_of("https://example.org/bulk/national.tar.gz")


# ---------------------------------------------------------------- the record shape

def test_new_shape_active_only_aliases_unpublished_launches_and_new_fields(tmp_path):
    out = obl_waters.extract("RI", FIX / "water", tmp_path / "w.json")
    ws = {w["slug"]: w for w in out["waters"]}
    assert sorted(ws) == ["100-acre-cove-ri", "coddington-cove-ri", "sakonnet-river-ri"]    # merged ones are aliases
    assert out["_read"] == {"merged": 3, "records": 3}
    assert ws["sakonnet-river-ri"]["slug_aliases"] == ["blue-bill-cove-ri", "sachuest-bay-ri", "sapowet-cove-ri"]
    cod = ws["coddington-cove-ri"]
    assert cod["launches"] == [] and cod["launches_unpublished"] == ["stillwater-basin-ri"]
    acre = ws["100-acre-cove-ri"]
    assert acre["launches"] == ["walker-farm-ri"]
    for k in obl_waters.API_FIELDS:
        assert k in acre
    assert acre["status"] == "active" and acre["geometry_tolerance_m"] == 17 and len(acre["geometry_hash"]) == 64
    assert out["source"] == "openboatlaunch out/water snapshot 2026-11-07"


def test_long_and_short_launch_keys_read_the_same():
    long_ = rec("100-acre-cove-ri")["launches"][0]
    short = {"s": long_["slug"], "n": long_["name"], "k": long_["kind"], "st": "RI", "t": long_["town"],
             "x": long_["lon"], "y": long_["lat"], "f": None, "a": None}
    a, b = obl_waters.launch(long_), obl_waters.launch(short)
    assert {k: a[k] for k in ("slug", "name", "kind", "state", "town", "lon", "lat", "fee", "access", "visibility")} == \
           {k: b[k] for k in ("slug", "name", "kind", "state", "town", "lon", "lat", "fee", "access", "visibility")}


def test_a_hand_field_on_file_is_kept_and_a_partial_answer_refused(tmp_path):
    p = tmp_path / "waters-ri.json"
    p.write_text(json.dumps({"state": "RI", "waters": [{"slug": "100-acre-cove-ri", "aliases": ["Hundred Acre Cove"]}]}))
    obl_waters.extract("RI", FIX / "water", p)
    w = {x["slug"]: x for x in json.loads(p.read_text())["waters"]}
    assert w["100-acre-cove-ri"]["aliases"] == ["Hundred Acre Cove"]
    p.write_text(json.dumps({"state": "RI", "waters": [{"slug": f"w{i}-ri"} for i in range(7)]}))
    with pytest.raises(obl_waters.Partial):
        obl_waters.extract("RI", FIX / "water", p)


def test_extract_from_the_api_paged_and_falls_back_to_the_folder(api, tmp_path, capsys):
    out = tmp_path / "waters-ri.json"
    assert obl_waters.main(["--state", "RI", "--from-api", "--out", str(out)]) == 0
    d = json.loads(out.read_text())
    assert d["count"] == 3 and d["source"] == "openboatlaunch API v1 snapshot 2026-11-07"
    assert sum(1 for p, *_ in api.seen if p == "states/RI/waters") == 3          # six records, two a page
    assert d == {**json.loads(out.read_text())}
    api.down = True
    obl_api._cache_write("states/RI.json", {})                                   # no cached pages to reuse
    assert obl_waters.main(["--state", "RI", "--from-api", "--from", str(FIX / "water"), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["source"].startswith("openboatlaunch out/water snapshot")
    assert obl_waters.main(["--state", "RI", "--from-api", "--out", str(tmp_path / "x.json")]) == 1
    c = capsys.readouterr()
    no_key(c.out, c.err)


# ---------------------------------------------------------------- the national pull

def run_cli(*args, env):
    p = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "state_paths.py"), *args], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
    no_key(p.stdout)
    return p


def test_fetch_obl_pulls_checks_unpacks_and_pulls_once(api, tmp_path):
    env = {**os.environ}
    dest, sf = tmp_path / "obl" / "out", tmp_path / "obl-changes.json"
    p = run_cli("fetch-obl", "--to", str(dest), "--state-file", str(sf), env=env)
    assert p.returncode == 0, p.stdout
    assert len(list((dest / "water").glob("*.json"))) == 6 and (dest / "meta.json").is_file()
    assert (dest / SP.OBL_MARK).exists()
    st = json.loads(sf.read_text())
    assert st["national"]["snapshot"] == "20261107T025245Z" and st["national"]["records"] == 6
    p = run_cli("fetch-obl", "--to", str(dest), "--state-file", str(sf), env=env)
    assert p.returncode == SP.NOT_USED and "current" in p.stdout
    assert sum(1 for x, *_ in api.seen if x == "bulk/national.tar.gz") == 1


def test_fetch_obl_refuses_a_bad_sha_and_falls_back_when_down_or_keyless(api, tmp_path):
    dest, sf = tmp_path / "obl" / "out", tmp_path / "s.json"
    api.sha_file = "0" * 64
    p = run_cli("fetch-obl", "--to", str(dest), "--state-file", str(sf), env={**os.environ})
    assert p.returncode == SP.NOT_USED and "sha256" in p.stdout and not dest.exists()
    api.sha_file, api.down = None, True
    p = run_cli("fetch-obl", "--to", str(dest), "--state-file", str(sf), env={**os.environ})
    assert p.returncode == SP.NOT_USED and "R2 copy" in p.stdout
    env = {k: v for k, v in os.environ.items() if k != "OBL_API_KEY"}
    p = run_cli("fetch-obl", "--to", str(dest), "--state-file", str(sf), env=env)
    assert p.returncode == SP.NOT_USED and "no OBL_API_KEY" in p.stdout


def test_fetch_obl_waits_a_day_for_a_new_snapshot_unless_a_full_pull_is_needed(api, tmp_path):
    from datetime import datetime, timezone
    dest, sf = tmp_path / "obl" / "out", tmp_path / "s.json"
    t0 = datetime(2026, 11, 7, 3, tzinfo=timezone.utc)
    assert SP.fetch_obl(dest, sf, now=t0) == 0
    api.meta = {**api.meta, "snapshot": "20261107T090000Z", "built": "2026-11-07T09:00:00+00:00"}
    assert SP.fetch_obl(dest, sf, now=t0.replace(hour=10)) == SP.NOT_USED
    assert SP.fetch_obl(dest, sf, now=t0.replace(day=8, hour=4)) == 0
    st = json.loads(sf.read_text())
    st["need_full"] = True
    sf.write_text(json.dumps(st))
    assert SP.fetch_obl(dest, sf, now=t0.replace(day=10)) == 0 and "need_full" not in json.loads(sf.read_text())


def test_pack_obl_saves_only_a_changed_folder_and_not_saved_rolls_back(api, tmp_path):
    dest, sf = tmp_path / "obl" / "out", tmp_path / "s.json"
    sf.write_text(json.dumps({"until": "2026-11-07T05:00:00Z", "until_before": "2026-11-07T02:52:45+00:00"}))
    assert SP.fetch_obl(dest, sf) == 0
    tgz = tmp_path / "obl-water.tar.gz"
    assert SP.pack_obl(tgz, dest) == 0
    with tarfile.open(tgz) as tf:
        names = tf.getnames()
    assert "meta.json" in names and "water/sakonnet-river-ri.json" in names and SP.OBL_MARK not in names
    assert SP.unpack_obl(tgz, tmp_path / "again" / "out")["records"] == 6
    SP.obl_not_saved(sf, dest)
    st = json.loads(sf.read_text())
    assert st["national"] is None and st["until"] == "2026-11-07T02:52:45+00:00"
    (dest / SP.OBL_MARK).unlink()
    assert SP.pack_obl(tmp_path / "none.tar.gz", dest) == SP.ABSENT


# ---------------------------------------------------------------- the hourly changes check

def changes_setup(tmp_path, api):
    out = tmp_path / "obl" / "out"
    (out / "water").mkdir(parents=True)
    (out / "meta.json").write_text((FIX / "meta.json").read_text())
    for p in (FIX / "water").glob("*.json"):
        (out / "water" / p.name).write_text(p.read_text())
    data = tmp_path / "data"
    (data / "build").mkdir(parents=True)
    (data / "rules.json").write_text(json.dumps({"live_states": ["RI"]}))
    obl_waters.extract("RI", out / "water", data / "waters-ri.json")
    status = data / "build" / "status.json"
    status.write_text(json.dumps({"waters": {"sakonnet-river-ri": {"status": "red"},
                                             "100-acre-cove-ri": {"status": "grey"}}}))
    return out / "water", data, status


def test_changes_are_fetched_written_logged_and_the_extract_rewritten(api, tmp_path, capsys):
    water, data, status = changes_setup(tmp_path, api)
    sf = data / "build" / "obl-changes.json"
    sf.write_text(json.dumps({"until": "2026-11-07T03:00:00+00:00"}))
    sak = {**rec("sakonnet-river-ri"), "geometry_hash": "f" * 64, "previous_slugs": ["sakonnet-river-ri-old"]}
    acre = {**rec("100-acre-cove-ri"), "geometry_hash": "e" * 64}
    api.records["sakonnet-river-ri"], api.records["100-acre-cove-ri"] = sak, acre
    api.records["coddington-cove-ri"] = {**rec("coddington-cove-ri"), "status": "renamed",
                                         "successor_slug": "sakonnet-river-ri"}
    api.deleted["gone-pond-ri"] = {"slug": "gone-pond-ri", "state": "RI", "status": "deleted", "name": "Gone Pond"}
    api.changes = [{"slug": s, "change": c, "at": "2026-11-07T04:00:00+00:00", "state": "RI", "fields": f}
                   for s, c, f in (("sakonnet-river-ri", "changed", ["geometry"]), ("100-acre-cove-ri", "changed", ["geometry"]),
                                   ("coddington-cove-ri", "renamed", []), ("gone-pond-ri", "deleted", []))]
    st = obl_changes.check(water, sf, status, data_dir=data)
    assert st["until"] == "2026-11-07T05:00:00+00:00" and st["etag"]
    kinds = sorted((e["kind"], e["slug"]) for e in st["log"])
    # an outline change is logged only on a water with an active report (the 100 Acre Cove is grey)
    assert kinds == [("deleted", "gone-pond-ri"), ("outline", "sakonnet-river-ri"), ("renamed", "coddington-cove-ri")]
    assert json.loads((water / "sakonnet-river-ri.json").read_text())["geometry_hash"] == "f" * 64
    assert (water.parent / obl_changes.MARK).exists()
    ws = {w["slug"]: w for w in json.loads((data / "waters-ri.json").read_text())["waters"]}
    assert "coddington-cove-ri" not in ws
    assert "coddington-cove-ri" in ws["sakonnet-river-ri"]["slug_aliases"]
    assert "sakonnet-river-ri-old" in ws["sakonnet-river-ri"]["slug_aliases"]
    assert ws["sakonnet-river-ri"]["geometry_hash"] == "f" * 64
    assert st["pending_states"] == ["RI"]                       # behind the checked-out file until committed
    out = capsys.readouterr().out
    assert out.count("status.md: ") == 3 and "renamed coddington-cove-ri into sakonnet-river-ri" in out
    no_key(out)
    # the next hour: a 304 with the stored ETag, the extract rewritten again (no change: current, pending cleared)
    st = obl_changes.check(water, sf, status, data_dir=data)
    assert st["last_run"]["changes"] == 0 and st["pending_states"] == []


def test_a_410_asks_for_a_full_pull_and_the_api_down_keeps_until(api, tmp_path, capsys):
    water, data, status = changes_setup(tmp_path, api)
    sf = data / "build" / "obl-changes.json"
    sf.write_text(json.dumps({"until": "2026-10-01T00:00:00Z"}))
    st = obl_changes.check(water, sf, status, data_dir=data)
    assert st["need_full"] and st["until"] == "2026-11-07T02:52:45+00:00" and st["pending_states"] == []
    api.down = True
    st = obl_changes.check(water, sf, status, data_dir=data)
    assert st["until"] == "2026-11-07T02:52:45+00:00"
    no_key(capsys.readouterr().out)


def test_the_first_run_starts_at_the_folders_snapshot_and_main_never_fails(api, tmp_path, capsys, monkeypatch):
    water, data, status = changes_setup(tmp_path, api)
    sf = data / "build" / "obl-changes.json"
    st = obl_changes.check(water, sf, status, data_dir=data)
    assert st["until"] == "2026-11-07T02:52:45+00:00" and st["log"] == []
    monkeypatch.setattr(obl_changes, "check", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"boom {KEY}")))
    assert obl_changes.main([]) == 0
    no_key(capsys.readouterr().out)


# ---------------------------------------------------------------- the export and placement

def test_the_export_reads_long_keys_and_shows_published_launches_only(tmp_path, monkeypatch):
    from build import status as S
    from export import build as X
    water = tmp_path / "water"
    water.mkdir()
    for s in ("100-acre-cove-ri", "coddington-cove-ri"):
        (water / f"{s}.json").write_text((FIX / "water" / f"{s}.json").read_text())
    monkeypatch.setattr(S, "OBL_WATER_DIR", water)
    monkeypatch.setattr(X, "OBL_BUILD_DIR", tmp_path / "build")
    X._OBL_BUILD.clear()
    got = X.launches_for("100-acre-cove-ri", "RI")
    assert [o["slug"] for o in got] == ["walker-farm-ri"] and got[0]["access"] == "public"
    assert got[0]["url"] == "https://openboatlaunch.org/launch/walker-farm-ri/" and got[0]["lat"] == 41.75314
    assert X.launches_for("coddington-cove-ri", "RI") == []          # the unpublished private launch is not shown
    X._OBL_BUILD.clear()


def test_the_placement_stamp_follows_geometry_hash_not_file_times(tmp_path, monkeypatch):
    from build import status as S
    water = tmp_path / "water"
    water.mkdir()
    (water / "a-ri.json").write_text("{}")
    monkeypatch.setattr(S, "OBL_WATER_DIR", water)
    one = S.outline_files({"a-ri": {"geometry_hash": "1" * 64}})
    os.utime(water / "a-ri.json", (1, 1))
    assert S.outline_files({"a-ri": {"geometry_hash": "1" * 64}}) == one
    assert S.outline_files({"a-ri": {"geometry_hash": "2" * 64}}) != one


def test_slug_aliases_of_a_later_duplicate_record_still_resolve(tmp_path, monkeypatch):
    from build import status as S
    (tmp_path / "waters-new-england.json").write_text(json.dumps({"waters": [{"slug": "sakonnet-river-ri", "name": "S"}]}))
    (tmp_path / "waters-ri.json").write_text(json.dumps({"state": "RI", "waters": [
        {"slug": "sakonnet-river-ri", "name": "S", "slug_aliases": ["blue-bill-cove-ri"]}]}))
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    ws = S.load_waters()
    assert S.SLUG_ALIASES.get("blue-bill-cove-ri") == "sakonnet-river-ri" and ws["sakonnet-river-ri"]["name"] == "S"


def test_the_batch_extract_reads_the_api_when_the_key_is_here(monkeypatch):
    spec = importlib.util.spec_from_file_location("state_batch", ROOT / "scripts" / "state_batch.py")
    B = importlib.util.module_from_spec(spec)
    sys.modules["state_batch"] = B
    spec.loader.exec_module(B)
    monkeypatch.setenv("OBL_API_KEY", KEY)
    cmd = B.plan("RI", "extract").cmds[0]
    assert "--from-api" in cmd.argv and "--from" in cmd.argv
    assert B.extract_ready(None, "RI")[0]
    assert KEY not in " ".join(cmd.argv)
    monkeypatch.delenv("OBL_API_KEY")
    assert "--from-api" not in B.plan("RI", "extract").cmds[0].argv
