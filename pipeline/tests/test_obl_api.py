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
    p.write_text(json.dumps({"state": "RI", "waters": [{"slug": f"w{i}-ri"} for i in range(13)]}))
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


def test_an_extract_from_another_source_is_never_rewritten_and_leaves_pending(api, tmp_path):
    # DC's extract is built from NHD (openboatlaunch has no DC records): a 410 marks every live state pending, and the
    # rewrite must neither refuse DC every hour nor ever write it from the folder (review 2026-11-07)
    water, data, status = changes_setup(tmp_path, api)
    (data / "rules.json").write_text(json.dumps({"live_states": ["RI", "DC"]}))
    dc = {"state": "DC", "source": "USGS National Map NHD flowlines", "waters": [{"slug": "rock-creek-dc"}]}
    (data / "waters-dc.json").write_text(json.dumps(dc))
    before = (data / "waters-dc.json").read_bytes()
    sf = data / "build" / "obl-changes.json"
    sf.write_text(json.dumps({"until": "2026-11-07T03:00:00+00:00", "pending_states": ["DC", "RI"]}))
    st = obl_changes.check(water, sf, status, data_dir=data)
    assert (data / "waters-dc.json").read_bytes() == before
    assert st["pending_states"] == []


def test_the_refresh_rolls_back_when_the_pack_itself_fails():
    yml = (ROOT / ".github" / "workflows" / "refresh.yml").read_text()
    step = yml.split("Save openboatlaunch's folder to R2", 1)[1].split("- name:", 1)[0]
    assert 'elif [ "$rc" != 3 ]' in step and step.count("state_paths.py obl-not-saved") == 2


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


# ---------------------------------------------------------------- review 2026-11-07 (P1-1, P2-1, P2-2, P2-3, P3)

def folder_copy(tmp_path):
    w = tmp_path / "obl" / "out" / "water"
    w.mkdir(parents=True)
    (w.parent / "meta.json").write_text((FIX / "meta.json").read_text())
    for p in (FIX / "water").glob("*.json"):
        (w / p.name).write_text(p.read_text())
    return w


def test_a_deleted_or_moved_water_on_file_stays_as_a_tombstone(tmp_path):
    w = folder_copy(tmp_path)
    p = tmp_path / "waters-ri.json"
    obl_waters.extract("RI", w, p)
    # openboatlaunch deletes 100 Acre Cove and moves Coddington Cove into another state's record
    (w / "100-acre-cove-ri.json").write_text(json.dumps({**rec("100-acre-cove-ri"), "status": "deleted",
                                                          "geometry": None, "retired_at": "2026-11-08T00:00:00+00:00"}))
    (w / "coddington-cove-ri.json").write_text(json.dumps({**rec("coddington-cove-ri"), "status": "renamed",
                                                           "successor_slug": "coddington-cove-ma"}))
    out = obl_waters.extract("RI", w, p)
    ws = {x["slug"]: x for x in json.loads(p.read_text())["waters"]}
    assert ws["100-acre-cove-ri"]["status"] == "deleted" and ws["100-acre-cove-ri"]["name"] == "100 Acre Cove"
    assert ws["100-acre-cove-ri"]["retired_at"] == "2026-11-08T00:00:00+00:00"
    assert ws["coddington-cove-ri"]["status"] == "moved" and ws["coddington-cove-ri"]["successor_slug"] == "coddington-cove-ma"
    assert out["_read"]["kept as deleted"] == 1 and out["_read"]["kept as moved"] == 1
    # a record no longer served at all is kept too, and a merge within the state is an alias, not a tombstone
    (w / "sakonnet-river-ri.json").unlink()
    obl_waters.extract("RI", w, p)
    ws = {x["slug"]: x for x in json.loads(p.read_text())["waters"]}
    assert ws["sakonnet-river-ri"]["status"] == "not_in_snapshot" and "blue-bill-cove-ri" not in ws
    # the tombstone is still a water record the status build resolves
    assert ws["sakonnet-river-ri"]["slug"] == "sakonnet-river-ri"


def test_a_deletion_in_the_changes_keeps_the_water_and_says_so(api, tmp_path, capsys):
    water, data, status = changes_setup(tmp_path, api)
    sf = data / "build" / "obl-changes.json"
    sf.write_text(json.dumps({"until": "2026-11-07T03:00:00+00:00"}))
    status.write_text(json.dumps({"waters": {"100-acre-cove-ri": {"status": "red", "events": ["e1", "e2"]}}}))
    del api.records["100-acre-cove-ri"]
    api.deleted["100-acre-cove-ri"] = {**rec("100-acre-cove-ri"), "status": "deleted", "geometry": None}
    api.changes = [{"slug": "100-acre-cove-ri", "change": "deleted", "at": "2026-11-07T04:12:00+00:00", "state": "RI"}]
    obl_changes.check(water, sf, status, data_dir=data)
    ws = {x["slug"]: x for x in json.loads((data / "waters-ri.json").read_text())["waters"]}
    assert ws["100-acre-cove-ri"]["status"] == "deleted"
    out = capsys.readouterr().out
    assert ("status.md: - 04:12Z: openboatlaunch deleted 100-acre-cove-ri (RI); kept in the extract as deleted "
            "(2 report(s) on it), until its reports and outfalls are moved by hand.") in out
    no_key(out)


def test_the_state_extract_wins_over_the_new_england_file_after_a_rename(tmp_path, monkeypatch):
    from build import status as S
    old = {"slug": "old-pond-ri", "name": "Old Pond", "state": "RI", "aliases": ["The Old Pond"]}
    keep = {"slug": "big-pond-ri", "name": "Big Pond (2026-11-01)", "state": "RI", "osm_note": "kept"}
    other = {"slug": "far-pond-xx", "name": "Far Pond", "state": "XX"}
    (tmp_path / "waters-new-england.json").write_text(json.dumps({"waters": [old, keep, other]}))
    (tmp_path / "waters-ri.json").write_text(json.dumps({"state": "RI", "waters": [
        {"slug": "new-pond-ri", "name": "New Pond", "state": "RI", "slug_aliases": ["old-pond-ri"]},
        {"slug": "big-pond-ri", "name": "Big Pond", "state": "RI"}]}))
    monkeypatch.setattr(S, "DATA_DIR", tmp_path)
    ws = S.load_waters()
    assert "old-pond-ri" not in ws and S.SLUG_ALIASES["old-pond-ri"] == "new-pond-ri"
    assert ws["big-pond-ri"]["name"] == "Big Pond" and ws["big-pond-ri"]["osm_note"] == "kept"
    assert "far-pond-xx" in ws                       # a regional record of a state with no extract of its own


def test_more_changes_than_a_run_fetches_are_logged_from_the_list_and_move_on(api, tmp_path, capsys):
    water, data, status = changes_setup(tmp_path, api)
    sf = data / "build" / "obl-changes.json"
    sf.write_text(json.dumps({"until": "2026-11-07T03:00:00+00:00"}))
    api.changes = [{"slug": f"w{i}-ri", "change": "changed", "at": "2026-11-07T04:00:00+00:00", "state": "RI"}
                   for i in range(5)]
    api.changes.append({"slug": "sapowet-cove-ri", "change": "merged", "successor_slug": "sakonnet-river-ri",
                        "at": "2026-11-07T04:30:00+00:00", "state": "RI"})
    st = obl_changes.check(water, sf, status, max_records=3, data_dir=data)
    assert st["need_full"] and st["until"] == "2026-11-07T05:00:00+00:00"
    assert [e["slug"] for e in st["log"]] == ["sapowet-cove-ri"]
    assert not any(p.startswith("waters/") for p, *_ in api.seen)            # nothing fetched one by one
    # need_full overrides the once-a-day limit, and the run after the pull rewrites every live state
    from datetime import datetime, timezone
    t = datetime(2026, 11, 7, 6, tzinfo=timezone.utc)
    st = json.loads(sf.read_text())
    st["national"] = {"snapshot": api.meta["snapshot"], "fetched_at": "2026-11-07T05:30:00Z"}
    sf.write_text(json.dumps(st))
    dest = water.parent.parent / "pulled" / "out"
    assert SP.fetch_obl(dest, sf, now=t) == 0
    st = json.loads(sf.read_text())
    assert st["full_pulled"] and "need_full" not in st
    st["pending_states"] = []
    sf.write_text(json.dumps(st))
    st = obl_changes.check(water, sf, status, data_dir=data)
    assert "full_pulled" not in st
    assert "every live state's extract is rewritten" in capsys.readouterr().out


def test_a_full_pull_whose_folder_was_not_saved_is_asked_for_again(api, tmp_path):
    """SOL wave2 P2-8: cap -> full pull -> failed upload (obl-not-saved) -> the next run, within twenty-four hours of the
    last national pull, pulls the national file again instead of asking for changes after the advanced until."""
    from datetime import datetime, timezone
    water, data, status = changes_setup(tmp_path, api)
    sf = data / "build" / "obl-changes.json"
    sf.write_text(json.dumps({"until": "2026-11-07T03:00:00+00:00",
                              "national": {"snapshot": api.meta["snapshot"], "fetched_at": "2026-11-07T02:00:00Z"}}))
    api.changes = [{"slug": f"w{i}-ri", "change": "changed", "at": "2026-11-07T04:00:00+00:00", "state": "RI"}
                   for i in range(5)]
    st = obl_changes.check(water, sf, status, max_records=3, data_dir=data)       # the cap: until moves on
    assert st["need_full"] and st["until"] == "2026-11-07T05:00:00+00:00"
    dest = tmp_path / "pulled" / "out"
    t = datetime(2026, 11, 7, 6, tzinfo=timezone.utc)
    assert SP.fetch_obl(dest, sf, now=t) == 0                                       # the full pull
    assert "need_full" not in json.loads(sf.read_text())
    obl_changes.check(dest / "water", sf, status, data_dir=data)                    # the same run's changes check
    SP.obl_not_saved(sf, dest)                                                      # its upload failed
    st = json.loads(sf.read_text())
    assert st["need_full"] and "full_pulled" not in st
    assert st["national"]["fetched_at"] == "2026-11-07T02:00:00Z"
    (dest / SP.OBL_MARK).unlink()
    api.seen.clear()
    assert SP.fetch_obl(dest, sf, now=t.replace(hour=7)) == 0                       # within 24 h: pulled again
    assert any("national" in path for path, *_ in api.seen)
    st = json.loads(sf.read_text())
    assert st["full_pulled"] and "need_full" not in st
    # this time the folder is saved: nothing is rolled back, and the next run does not pull again
    (dest / SP.OBL_MARK).unlink()
    obl_changes.check(dest / "water", sf, status, data_dir=data)
    st = json.loads(sf.read_text())
    assert "need_full" not in st
    assert SP.fetch_obl(dest, sf, now=t.replace(hour=8)) == SP.NOT_USED
    assert "need_full_before" not in json.loads(sf.read_text())


def test_the_daily_pull_request_carries_the_rewrites_and_the_review_lines(tmp_path):
    spec = importlib.util.spec_from_file_location("obl_extracts", ROOT / "scripts" / "obl_extracts.py")
    E = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(E)
    w = folder_copy(tmp_path)
    data = tmp_path / "data"
    (data / "build").mkdir(parents=True)
    (data / "rules.json").write_text(json.dumps({"live_states": ["RI", "DC", "IL"]}))
    (data / "waters-ri.json").write_text(json.dumps({"state": "RI", "source": "openboatlaunch out/water snapshot 2026-11-01",
                                                     "waters": [{"slug": "100-acre-cove-ri", "advisories": ["x"]}]}))
    (data / "waters-dc.json").write_text(json.dumps({"source": "USGS NHD", "waters": [{"slug": "rock-creek-dc"}]}))
    sf = data / "build" / "obl-changes.json"
    line = "- 04:12Z: openboatlaunch merged sapowet-cove-ri into sakonnet-river-ri (RI); its reports and outfalls follow by slug_aliases."
    sf.write_text(json.dumps({"until": "2026-11-07T05:00:00+00:00",
                              "log": [{"at": "2026-11-07T04:12:00+00:00", "status_line": line}]}))
    from datetime import datetime, timezone
    body = tmp_path / "body.md"
    res = E.run(w, body, data_dir=data, state_file=sf, now=datetime(2026, 11, 7, 6, tzinfo=timezone.utc))
    assert res["RI"] == "rewritten" and res["DC"] == "not an openboatlaunch extract"
    assert res["IL"] == "no extract on file" and not (data / "waters-il.json").exists()
    text = body.read_text()
    assert "| RI | rewritten | 1 to 3 | 2 |" in text and line in text
    ws = {x["slug"]: x for x in json.loads((data / "waters-ri.json").read_text())["waters"]}
    assert ws["100-acre-cove-ri"]["advisories"] == ["x"]          # the API has none: the ones on file are kept
    B = sys.modules.get("state_batch") or E._batch()
    c = B.publish_cmds("RI", "2026-11-07", body, ["data/waters-ri.json"], label="obl",
                       pr_title="openboatlaunch extracts, 2026-11-07")
    assert c["branch"] == "batch/obl-2026-11-07" and "main" not in c["commit"][-1][-1]
    wf = (ROOT / ".github" / "workflows" / "obl-extracts.yml").read_text()
    assert "obl_extracts.py publish" in wf and "object put" not in wf and "${{ secrets.OBL_API_KEY }}" in wf


def test_meta_and_changes_answer_quickly_or_give_up(api):
    assert obl_api.QUICK_TIMEOUT <= 30 and obl_api.QUICK_TRIES <= 2
    rt = (ROOT / ".github" / "workflows" / "refresh.yml").read_text()
    assert rt.index("- name: Restore the raw caches from R2") < rt.index("python3 -I scripts/state_paths.py fetch-obl ||")


# ---------------------------------------------------------------- the District of Columbia (an NHD-built extract merged)

DC_FIX = FIX / "dc"


def test_gnis_ids_compare_as_numbers():
    from common import gnis_num
    assert gnis_num("00597915") == gnis_num(597915) == gnis_num("597915") == 597915
    assert gnis_num(None) is None and gnis_num("") is None and gnis_num("n/a") is None and gnis_num("0") is None
    assert gnis_num(True) is None
    from common import same_gnis
    assert same_gnis("00532032", 532032) and not same_gnis("00532032", "532033") and not same_gnis(None, None)
    assert same_gnis("long-river-nc", "long-river-nc") and not same_gnis("", "")


def dc_setup(tmp_path):
    """Our NHD-built DC extract (three records: the Anacostia under another slug, two streams openboatlaunch lacks)
    and a folder with openboatlaunch's real Anacostia and Kingman Lake records."""
    water = tmp_path / "obl" / "out" / "water"
    water.mkdir(parents=True)
    (water.parent / "meta.json").write_text((FIX / "meta.json").read_text())
    for p in DC_FIX.glob("*.json"):
        (water / p.name).write_text(p.read_text())
    line = {"type": "LineString", "coordinates": [[-77.0, 38.9], [-76.99, 38.91]]}
    ours = {"source": "USGS National Map NHD flowlines (pipeline/ingest/dc_waters.py)", "built": "2026-11-03T02:27:57Z",
            "skipped": [{"slug": "kingman-lake-dc"}], "count": 3, "waters": [
                {"slug": "anacostia-river-nhd-dc", "name": "Anacostia River", "kind": "river", "state": "DC",
                 "gnis_id": "00532032", "geometry": line, "bbox": [-77.0, 38.9, -76.99, 38.91], "towns": ["Washington"],
                 "launches": [], "advisories": [], "aliases": ["Eastern Branch"], "reachcodes": ["02070010000001"]},
                {"slug": "rock-creek-dc", "name": "Rock Creek", "kind": "river", "state": "DC", "gnis_id": "00531463",
                 "geometry": line, "launches": [], "advisories": []},
                {"slug": "oxon-run-dc", "name": "Oxon Run", "kind": "stream", "state": "DC", "gnis_id": "00532036",
                 "geometry": line, "launches": [], "advisories": []}]}
    data = tmp_path / "data"
    (data / "build").mkdir(parents=True)
    (data / "waters-dc.json").write_text(json.dumps(ours))
    (data / "rules.json").write_text(json.dumps({"live_states": ["DC"]}))
    return water, data


def test_an_nhd_built_extract_is_merged_by_slug_and_numeric_gnis_id(tmp_path):
    water, data = dc_setup(tmp_path)
    p = data / "waters-dc.json"
    out = obl_waters.extract("DC", water, p)
    d = json.loads(p.read_text())
    ws = {w["slug"]: w for w in d["waters"]}
    assert sorted(ws) == ["anacostia-river-nhd-dc", "kingman-lake-dc", "oxon-run-dc", "rock-creek-dc"]
    ana = ws["anacostia-river-nhd-dc"]                   # ours, matched by GNIS 00532032 = 532032
    assert ana["record_from"] == "nhd+openboatlaunch" and ana["outline_from"] == "openboatlaunch"
    assert ana["geometry"] == rec_dc("anacostia-river-dc")["geometry"] and ana["bbox"] == rec_dc("anacostia-river-dc")["bbox"]
    assert ana["water_id"] == "anacostia-river-md" and ana["gnis_id"] == "00532032"     # shared id recorded; our text kept
    assert ana["slug_aliases"] == ["anacostia-river-dc"] and ana["aliases"] == ["Eastern Branch"]
    assert ana["reachcodes"] == ["02070010000001"] and ana["name"] == "Anacostia River"
    assert len(ana["launches"]) == 4 and len(ana["launches_unpublished"]) == 1
    king = ws["kingman-lake-dc"]
    assert king["record_from"] == "openboatlaunch" and king["geometry"]["type"] == "Polygon" and king["advisories"] == []
    assert ws["rock-creek-dc"].get("record_from") is None and "water_id" not in ws["rock-creek-dc"]   # ours, kept
    assert d["merged"]["matched"] == ["anacostia-river-nhd-dc"] and d["merged"]["added"] == ["kingman-lake-dc"]
    assert sorted(d["merged"]["own"]) == ["oxon-run-dc", "rock-creek-dc"] and d["count"] == 4
    assert d["source"].startswith("USGS National Map NHD flowlines") and "kingman-lake-dc added from openboatlaunch" in d["source"]
    assert d["built"] == "2026-11-03T02:27:57Z" and d["state"] == "DC" and out["_read"]["matched"] == 1
    # a second merge changes nothing
    before = p.read_bytes()
    obl_waters.extract("DC", water, p)
    assert json.loads(p.read_text()) == json.loads(before)


def rec_dc(slug):
    return json.loads((DC_FIX / f"{slug}.json").read_text())


def test_the_hourly_rewrite_merges_dc_and_leaves_it_alone_without_dc_records(api, tmp_path):
    water, data = dc_setup(tmp_path)
    assert obl_changes.rewrite({"DC"}, water, None, data) == {"DC": "rewritten"}
    assert obl_changes.rewrite({"DC"}, water, None, data) == {"DC": "current"}
    for p in water.glob("*-dc.json"):
        p.unlink()
    water2, data2 = dc_setup(tmp_path / "b")
    for p in water2.glob("*-dc.json"):
        p.unlink()
    before = (data2 / "waters-dc.json").read_bytes()
    assert obl_changes.rewrite({"DC"}, water2, None, data2) == {"DC": "current"}
    assert (data2 / "waters-dc.json").read_bytes() == before


def dc_after_first_merge(tmp_path, gnis=True):
    """DC merged once (Kingman Lake added from openboatlaunch); returns the folder, the extract and a writer of
    folder records."""
    water, data = dc_setup(tmp_path)
    if not gnis:                                    # the reviewer's case: the added record without the optional GNIS id
        k = rec_dc("kingman-lake-dc")
        (water / "kingman-lake-dc.json").write_text(json.dumps({**k, "gnis_id": None}))
    p = data / "waters-dc.json"
    obl_waters.extract("DC", water, p)
    assert json.loads(p.read_text())["merged"]["added"] == ["kingman-lake-dc"]

    def put(src, **kw):
        base = json.loads((water / f"{src}.json").read_text())
        (water / f"{kw.get('slug', src)}.json").write_text(json.dumps({**base, **kw}))
    return water, p, put


def dc_waters(p):
    return {w["slug"]: w for w in json.loads(p.read_text())["waters"]}


@pytest.mark.parametrize("gnis", [False, True])
def test_dc_merge_follows_a_rename_of_a_record_it_added(tmp_path, gnis):
    """SOL wave2 P2-9: old-pond renamed to new-pond after the first merge: one record, the old slug an alias."""
    from build import status as S
    water, p, put = dc_after_first_merge(tmp_path, gnis)
    put("kingman-lake-dc", status="renamed", successor_slug="kingman-pond-dc", retired_at="2026-11-07T08:00:00+00:00")
    put("kingman-lake-dc", slug="kingman-pond-dc", name="Kingman Pond", previous_slugs=["kingman-lake-dc"],
        status="active", successor_slug=None, retired_at=None)
    obl_waters.extract("DC", water, p)
    ws = dc_waters(p)
    assert "kingman-lake-dc" not in ws and ws["kingman-pond-dc"]["record_from"] == "openboatlaunch"
    assert S.slug_aliases(ws) == {"anacostia-river-dc": "anacostia-river-nhd-dc", "kingman-lake-dc": "kingman-pond-dc"}


def test_dc_merge_follows_a_merge_of_a_record_it_added_into_one_of_ours(tmp_path):
    from build import status as S
    water, p, put = dc_after_first_merge(tmp_path)
    put("kingman-lake-dc", status="merged", successor_slug="anacostia-river-dc", retired_at="2026-11-07T08:00:00+00:00")
    obl_waters.extract("DC", water, p)
    ws = dc_waters(p)
    assert "kingman-lake-dc" not in ws
    assert S.slug_aliases(ws)["kingman-lake-dc"] == "anacostia-river-nhd-dc"           # ours, NHD's slug kept
    assert ws["anacostia-river-nhd-dc"]["record_from"] == "nhd+openboatlaunch"


@pytest.mark.parametrize("how,status,successor", [("deleted", "deleted", None),
                                                  ("moved", "moved", "kingman-lake-md"),
                                                  ("vanished", "not_in_snapshot", None)])
def test_dc_merge_keeps_a_retired_record_it_added_as_a_tombstone(tmp_path, how, status, successor):
    """Deleted, merged into another state's record (a cross-state successor), or no longer served: kept, marked."""
    water, p, put = dc_after_first_merge(tmp_path)
    if how == "deleted":
        put("kingman-lake-dc", status="deleted", geometry=None, retired_at="2026-11-07T08:00:00+00:00")
    elif how == "moved":
        put("kingman-lake-dc", status="merged", successor_slug="kingman-lake-md", retired_at="2026-11-07T08:00:00+00:00")
    else:
        (water / "kingman-lake-dc.json").unlink()
    obl_waters.extract("DC", water, p)
    d = json.loads(p.read_text())
    k = dc_waters(p)["kingman-lake-dc"]
    assert k["status"] == status and k["successor_slug"] == successor and k["record_from"] == "openboatlaunch"
    assert k["geometry"]                                          # the outline it had stays with its reports
    assert d["merged"]["retired"] == ["kingman-lake-dc"] and "kingman-lake-dc kept as retired" in d["source"]
    before = p.read_bytes()
    obl_waters.extract("DC", water, p)                            # stable on the next run
    assert json.loads(p.read_text()) == json.loads(before)


def test_dc_merge_keeps_our_record_matched_through_a_rename_at_openboatlaunch(tmp_path):
    """Our NHD record matched to anacostia-river-dc stays ours and matched when openboatlaunch renames it (no GNIS id
    to fall back on): the new slug becomes an alias, never a second record."""
    water, p, put = dc_after_first_merge(tmp_path)
    a = rec_dc("anacostia-river-dc")
    (water / "anacostia-river-dc.json").write_text(json.dumps({**a, "status": "renamed",
                                                               "successor_slug": "anacostia-dc"}))
    (water / "anacostia-dc.json").write_text(json.dumps({**a, "slug": "anacostia-dc", "gnis_id": None,
                                                         "previous_slugs": ["anacostia-river-dc"]}))
    obl_waters.extract("DC", water, p)
    ws = dc_waters(p)
    assert "anacostia-dc" not in ws and "anacostia-river-dc" not in ws
    assert ws["anacostia-river-nhd-dc"]["record_from"] == "nhd+openboatlaunch"
    assert set(ws["anacostia-river-nhd-dc"]["slug_aliases"]) == {"anacostia-river-dc", "anacostia-dc"}
    # deleted at openboatlaunch: our record is NHD's identity and stays as it is
    (water / "anacostia-dc.json").write_text(json.dumps({**a, "slug": "anacostia-dc", "status": "deleted"}))
    obl_waters.extract("DC", water, p)
    ours = dc_waters(p)["anacostia-river-nhd-dc"]
    assert ours["name"] == "Anacostia River" and ours.get("status") != "deleted"


def test_an_extract_is_kept_when_the_state_files_are_there_but_none_decode(tmp_path):
    """SOL wave1 P2-11: the expected *-ri.json files exist but hold malformed JSON: refused, the extract on file kept;
    with no extract on file, nothing empty is written either."""
    water = tmp_path / "obl" / "out" / "water"
    water.mkdir(parents=True)
    (water.parent / "meta.json").write_text((FIX / "meta.json").read_text())
    for q in (FIX / "water").glob("*.json"):
        (water / q.name).write_text(q.read_text())
    out = tmp_path / "waters-ri.json"
    obl_waters.extract("RI", water, out)
    before = out.read_bytes()
    assert json.loads(before)["count"] > 0
    for q in water.glob("*-ri.json"):
        q.write_text("{not json")
    with pytest.raises(obl_waters.Partial, match="could not be read"):
        obl_waters.extract("RI", water, out)
    assert out.read_bytes() == before
    assert obl_waters.main(["--state", "RI", "--from", str(water), "--out", str(out)]) == 1
    assert out.read_bytes() == before
    fresh = tmp_path / "waters-ri-new.json"
    with pytest.raises(obl_waters.Partial):
        obl_waters.extract("RI", water, fresh)
    assert not fresh.exists()
    # one damaged file of six is a half-written file, skipped as before
    for q in (FIX / "water").glob("*.json"):
        (water / q.name).write_text(q.read_text())
    next(iter(sorted(water.glob("*-ri.json")))).write_text("{not json")
    assert obl_waters.extract("RI", water, out)["_read"]["unreadable"] == 1


def test_dc_merge_refuses_a_folder_whose_dc_files_do_not_decode(tmp_path):
    water, data = dc_setup(tmp_path)
    p = data / "waters-dc.json"
    before = p.read_bytes()
    for q in water.glob("*-dc.json"):
        q.write_text("[")
    with pytest.raises(obl_waters.Partial):
        obl_waters.extract("DC", water, p)
    assert p.read_bytes() == before
    assert obl_changes.rewrite({"DC"}, water, None, data)["DC"].startswith("refused")


def test_the_nhd_build_drops_its_record_of_a_water_openboatlaunch_has_by_gnis_id(monkeypatch):
    from ingest import waters_from_nhd as N
    line = {"type": "LineString", "coordinates": [[-77.0, 38.9], [-76.99, 38.91]]}
    doc = {"waters": [{"slug": "eastern-branch-dc", "name": "Eastern Branch", "kind": "river", "state": "DC",
                       "gnis_id": "00532032", "geometry": line, "towns": []}], "targets": []}
    existing = {"anacostia-river-dc": {**rec_dc("anacostia-river-dc"), "launches": []}}
    new, actions, aliases = N.resolve_existing_duplicates(doc, existing, ["DC"], when="2026-11-07")
    assert new["waters"] == [] and aliases == {"anacostia-river-dc": ["Eastern Branch"]}
