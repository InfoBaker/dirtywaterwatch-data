"""Security review 2026-11-17, finding 7: a failure's text in a saved or published file (an events file's error and
meta, the feeds' health in out/sources.json, the waters' stale reasons, out/meta.json's problems, a module's state
file) and in the public workflow log carries the pipeline's own words, the exception's kind, a fixed category and the
host at most: never a full address with its query string, an account id, a provider's words or an answer's body.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import requests

import common
from common import error_detail, error_text, public_error, public_meta_errors

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = "0123456789abcdef0123456789abcdef"            # invented, account-id shaped
QUERY_URL = "https://gis.example.gov/arcgis/rest/services/x/FeatureServer/0/query?where=1%3D1&token=SECRETTOKEN"
BODY = '{"error": {"code": 498, "message": "Invalid token for account ' + ACCOUNT + '"}}'

LIBRARY_TEXTS = [
    f"HTTPError: 404 Client Error: Not Found for url: {QUERY_URL}",
    "ConnectionError: HTTPSConnectionPool(host='gis.example.gov', port=443): Max retries exceeded with url: "
    "/arcgis/rest/q?where=1&token=SECRETTOKEN (Caused by NewConnectionError('<urllib3.connection.HTTPSConnection "
    "object at 0x7f>: Failed to establish a new connection: [Errno 111] Connection refused'))",
    "ReadTimeout: HTTPSConnectionPool(host='gis.example.gov', port=443): Read timed out. (read timeout=60)",
    f"ValueError: no features: {BODY}",
    f"RuntimeError: HTTP 401: {BODY}",
    f"D1 failed for account {ACCOUNT} at https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/d1?x=1",
    f"page: the layer answered <html><body>Login for {ACCOUNT}</body></html>",
    "JSONDecodeError: Expecting value: line 1 column 1 (char 0)",
]


def assert_safe(text: str) -> None:
    assert "?" not in text and "token=" not in text.lower() and "SECRETTOKEN" not in text, text
    assert ACCOUNT not in text, text
    assert "Invalid token" not in text and "{" not in text and "<html" not in text.lower(), text
    assert "https://" not in text and "http://" not in text, text


@pytest.mark.parametrize("text", LIBRARY_TEXTS)
def test_public_error_keeps_no_query_string_account_id_or_body_and_is_idempotent(text):
    out = public_error(text)
    assert_safe(out)
    assert public_error(out) == out


def test_public_error_keeps_the_pipelines_words_the_kind_the_category_and_the_host():
    assert public_error(LIBRARY_TEXTS[0]) == "HTTPError: HTTP 404 at gis.example.gov"
    assert public_error(LIBRARY_TEXTS[1]) == "ConnectionError: refused at gis.example.gov"
    assert public_error(LIBRARY_TEXTS[2]) == "ReadTimeout: timeout at gis.example.gov"
    assert public_error(LIBRARY_TEXTS[3]) == "ValueError: no features (code 498)"   # the answer's code stays
    assert public_error(LIBRARY_TEXTS[4]) == "RuntimeError: HTTP 401 (code 498)"
    assert public_error("MA0101508:82220: " + LIBRARY_TEXTS[0]) == "MA0101508:82220: HTTPError: HTTP 404 at gis.example.gov"
    # the pipeline's own sentences pass as they were, part by part
    assert public_error("3 notice(s) unreadable; advisory wording not recognised: Beach closed") == \
        "3 notice(s) unreadable; advisory wording not recognised: Beach closed"
    assert public_error(None) is None


def test_the_job_account_id_and_endpoint_never_pass(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct-id-1234")
    monkeypatch.setenv("R2_S3_ENDPOINT", "https://acct-id-1234.r2.cloudflarestorage.com")
    out = public_error("S3 put refused at acct-id-1234 (contact jane.doe@example.org)")
    assert "acct-id-1234" not in out and "jane.doe" not in out and "@" not in out


def _raise(exc):
    try:
        raise exc
    except BaseException as e:      # noqa: BLE001
        return e


def test_error_text_of_a_library_exception_is_its_kind_category_and_host():
    r = requests.Response()
    r.status_code, r.url = 403, QUERY_URL
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        assert error_text(e) == "HTTPError: HTTP 403 at gis.example.gov"
        assert error_detail(e) == "HTTP 403 at gis.example.gov"
    try:
        json.loads("<html>" + BODY)
    except ValueError as e:
        assert error_text(e) == "JSONDecodeError: not JSON"
    e = _raise(requests.ConnectionError(LIBRARY_TEXTS[1].split(": ", 1)[1]))
    assert error_text(e) == "ConnectionError: refused at gis.example.gov"
    e = _raise(requests.ReadTimeout("HTTPSConnectionPool(host='a.example.gov', port=443): Read timed out."))
    assert error_text(e) == "ReadTimeout: timeout at a.example.gov"


def test_error_text_of_the_pipelines_own_exception_keeps_its_words_up_to_the_answer():
    e = _raise(ValueError(f"layer 3 did not answer with features: {BODY}"))
    assert error_text(e) == "ValueError: layer 3 did not answer with features (code 498)"
    e = _raise(ValueError("layer 3 did not answer with features: {'features': None, 'token': 'SECRETTOKEN'}"))
    assert error_text(e) == "ValueError: layer 3 did not answer with features"
    e = _raise(RuntimeError(f"no CSRF_TOKEN cookie from {QUERY_URL}"))
    assert error_text(e) == "RuntimeError: no CSRF_TOKEN cookie from gis.example.gov"


def test_write_events_saves_no_query_string_account_id_or_body_in_error_or_meta(tmp_path):
    path = tmp_path / "x.json"
    common.write_events("x", [], ok=False, path=path, error=f"page: {LIBRARY_TEXTS[0]}",
                        meta={"url": QUERY_URL,                                   # a citation: kept whole
                              "errors": {QUERY_URL: f"RuntimeError: HTTP 401: {BODY}"},
                              "layer_error": LIBRARY_TEXTS[5],
                              "grid": {"problems": [LIBRARY_TEXTS[6], LIBRARY_TEXTS[1]]},
                              "last_error": BODY})
    d = json.loads(path.read_text())
    assert d["error"] == "page: HTTPError: HTTP 404 at gis.example.gov"
    assert d["meta"]["url"] == QUERY_URL
    rest = {k: v for k, v in d["meta"].items() if k != "url"}
    assert_safe(json.dumps(rest).replace('"', "").replace("{", "").replace("}", ""))
    assert ACCOUNT not in json.dumps(rest) and "SECRETTOKEN" not in json.dumps(rest)
    assert list(d["meta"]["errors"]) == ["gis.example.gov"]
    two = public_meta_errors({"errors": {QUERY_URL: "a", QUERY_URL.replace("/0/", "/1/"): "b"}})
    assert two == {"errors": {"gis.example.gov": "a", "gis.example.gov (2)": "b"}}


def test_a_meta_key_that_holds_ids_is_left_as_it_was():
    meta = {"failed": [f"https://x.example.gov/a?b={ACCOUNT}"], "permits_failed": {"MA0101508": "x"}, "count": 3}
    assert public_meta_errors(meta) == meta


def test_the_feed_health_and_its_stale_reason_carry_only_the_public_error():
    from datetime import UTC, datetime
    from build import status
    f = {"ok": False, "error": f"page: {LIBRARY_TEXTS[0]}", "last_ok_at": None, "fetched_at": "2026-11-21T00:00:00Z"}
    h = status.source_health("x", f, {}, datetime(2026, 11, 21, tzinfo=UTC))
    assert h["error"] == "page: HTTPError: HTTP 404 at gis.example.gov"
    assert "HTTP 404 at gis.example.gov" in h["stale_reason"]
    assert_safe(h["stale_reason"].replace("2026-11-21T00:00:00Z", ""))


def test_the_coverage_refusal_rule_still_reads_a_403():
    from export.coverage import unreadable
    feeds = [{"ok": False, "last_ok_at": None, "error": public_error(LIBRARY_TEXTS[0].replace("404", "403"))}]
    assert unreadable(feeds) == "refused"


def test_the_openrouter_error_carries_the_status_only(monkeypatch):
    from build import llm_judge
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    j = llm_judge.Judge.__new__(llm_judge.Judge)
    j._session = None

    class R:
        status_code, text = 401, BODY

    class S:
        def post(self, *a, **k):
            return R()
    j._session = S()
    with pytest.raises(RuntimeError) as ei:
        j._post("https://openrouter.ai/api/v1/x", {})
    assert str(ei.value) == "HTTP 401"


def test_the_obl_api_keeps_an_error_code_and_never_a_sentence():
    import obl_api
    assert obl_api._error_word(b'{"error": "rate_limited"}') == "rate_limited"
    assert obl_api._error_word(json.dumps({"error": f"key for {ACCOUNT} is not valid"}).encode()) == ""


def test_zoho_and_arcgis_answers_are_kept_as_codes():
    from common import answer_error
    from ingest import ct_deep
    assert ct_deep.zoho_error("STATUS_MESSAGE_START The privatelink of a person is invalid STATUS_MESSAGE_END") == \
        "with a status message"
    assert answer_error({"code": 499, "message": "Token Required"}) == "error code 499"
    assert answer_error({"message": "x"}) == "error"


def test_the_radar_export_error_never_quotes_the_answer():
    from ingest import mrms_grid

    class R:
        status_code, headers, content = 200, {"content-type": "application/json"}, BODY.encode()

        def raise_for_status(self):
            return None

    class S:
        def get(self, *a, **k):
            return R()
    with pytest.raises(mrms_grid.ExportError) as ei:
        mrms_grid.export(S(), 1, {"xmin": -80, "ymin": 40, "xmax": -79, "ymax": 41, "width": 10, "height": 10})
    assert "Invalid token" not in str(ei.value) and ei.value.content == BODY.encode()


# ------------------------------------------------------------------ no raw exception text in the pipeline's code

def _raw_exception_text(path: Path) -> list[str]:
    """Places inside `except ... as NAME:` that put NAME's own text (NAME, str(NAME), repr(NAME)) into an f-string,
    a print, an error field or a state value without error_text/error_detail."""
    src = path.read_text()
    tree = ast.parse(src)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    found = []
    for h in ast.walk(tree):
        if not isinstance(h, ast.ExceptHandler) or not h.name:
            continue
        if h.type is not None and any(x in ast.unparse(h.type) for x in ("re.error", "YAMLError")):
            continue
        name = h.name
        for node in (n for b in h.body for n in ast.walk(b)):
            direct = isinstance(node, ast.Name) and node.id == name
            text = (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("str", "repr")
                    and len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == name)
            if not (direct or text):
                continue
            p = parents.get(node)
            if isinstance(p, ast.Subscript):
                p = parents.get(p)
            if isinstance(p, ast.FormattedValue) or (direct and isinstance(p, ast.Call) and getattr(p.func, "id", "") == "print") \
                    or (text and isinstance(p, (ast.keyword, ast.Assign, ast.Dict, ast.Return))):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def test_no_except_block_puts_an_exceptions_own_text_in_a_log_line_or_an_error_field():
    files = [p for p in (ROOT / "pipeline").rglob("*.py")
             if ".venv" not in p.parts and "tests" not in p.parts and not p.name.endswith("_test.py")]
    found = [x for p in files for x in _raw_exception_text(p)]
    assert not found, f"use common.error_text / error_detail: {found[:20]}"


# ------------------------------------------------------------------ the log filter (scripts/log_redact.py)

LOG_REDACT = ROOT / "scripts" / "log_redact.py"


def run_filter(data: bytes, **env) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(LOG_REDACT)], input=data, capture_output=True, timeout=60,
                          env={**os.environ, **env})


def test_the_log_filter_keeps_scheme_host_and_path_and_drops_queries_users_and_keys():
    lines = (f"GET {QUERY_URL}#frag ok\n"
             "GET https://user:pw@gis.example.gov/a/b?x=1 ok\n"
             "Max retries exceeded with url: /arcgis/rest/q?where=1&token=SECRETTOKEN (Caused by x)\n"
             "::warning::a warning line stays\n"
             "api_key=SECRETTOKEN and Authorization: Bearer SECRETTOKEN1234 and jane.doe@example.org\n"
             f"https://{ACCOUNT}.r2.cloudflarestorage.com/dirtywaterwatch-data/state/x?X-Amz-Signature=SECRETTOKEN\n")
    p = run_filter(lines.encode(), CLOUDFLARE_ACCOUNT_ID=ACCOUNT,
                   R2_S3_ENDPOINT=f"https://{ACCOUNT}.r2.cloudflarestorage.com")
    out = p.stdout.decode()
    assert p.returncode == 0
    assert out.splitlines() == [
        "GET https://gis.example.gov/arcgis/rest/services/x/FeatureServer/0/query ok",
        "GET https://gis.example.gov/a/b ok",
        "Max retries exceeded with url: /arcgis/rest/q (Caused by x)",
        "::warning::a warning line stays",
        "api_key=[redacted] and Authorization: Bearer [redacted] and [redacted]",
        "[endpoint]/dirtywaterwatch-data/state/x",
    ]


def test_the_log_filter_passes_bytes_it_cannot_decode_withholds_an_overlong_line_and_always_exits_0():
    data = b"binary \xff\xfe line\n" + b"x" * (3 << 20) + b"\nlast line without newline"
    p = run_filter(data)
    assert p.returncode == 0
    assert p.stdout.startswith(b"binary \xff\xfe line\n") and p.stdout.endswith(b"last line without newline")
    assert len(p.stdout) < 200 and b"withheld" in p.stdout


# ------------------------------------------------------------------ Astra review 2026-11-21 (fix pass)

def test_a_semicolon_inside_an_answer_never_splits_it_into_a_kept_part():
    # P1-3: the body is taken out whole before the parts are split
    out = public_error('ValueError: layer: {"message": "failure; BODY_SENTINEL", "code": 400}; 2 rows unread')
    assert "BODY_SENTINEL" not in out and out.endswith("2 rows unread")
    out = public_error("RuntimeError: x: {'error': {'message': 'a; LEFT_OPEN")
    assert "LEFT_OPEN" not in out


def test_an_answers_numeric_code_is_kept_and_a_refusal_still_reads_as_one():
    # P2-8: ArcGIS's error object (and any {"code": ...} answer) keeps its code, so coverage still says "refused"
    from export.coverage import unreadable
    from ingest.generic.arcgis import ArcGISError
    e = _raise(ArcGISError({"code": 403, "message": "Forbidden: secret words", "details": []}))
    assert error_text(e) == "ArcGISError: ArcGIS error (code 403)"
    assert unreadable([{"ok": False, "last_ok_at": None, "error": error_text(e)}]) == "refused"
    assert public_error("ValueError: layer 3 answered an error: {'code': 498, 'message': 'Invalid token'}") == \
        "ValueError: layer 3 answered an error (code 498)"


def test_a_host_that_holds_the_account_id_is_redacted_too(monkeypatch):
    # P2-7: the host is redacted with the rest, on the first pass
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    r = requests.Response()
    r.status_code, r.url = 403, f"https://{ACCOUNT}.r2.cloudflarestorage.com/b/k?X-Amz-Signature=1"
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        assert ACCOUNT not in error_text(e)
    legacy = f"HTTPError: 403 Client Error: Forbidden for url: https://{ACCOUNT}.r2.cloudflarestorage.com/b/k?x=1"
    once = public_error(legacy)
    assert ACCOUNT not in once and public_error(once) == once


def test_provider_messages_raised_by_the_modules_are_kept_as_codes():
    # P1-2: an error object's message never rides in an exception the pipeline raises
    src = {p: (ROOT / "pipeline" / p).read_text() for p in
           ("ingest/oh_columbus_overflows.py", "ingest/nc_dwr_sso.py", "ingest/generic/socrata.py", "build/llm_judge.py")}
    assert ".get('message')" not in src["ingest/oh_columbus_overflows.py"]
    assert "d['error'].get('message')" not in src["ingest/nc_dwr_sso.py"]
    assert "page.get('message')" not in src["ingest/generic/socrata.py"]
    assert "no JSON answer: {text" not in src["build/llm_judge.py"]


def test_a_failed_documents_label_and_the_unread_layout_keep_no_query_string():
    # P1-6
    from common import url_label
    assert url_label("https://x.example.gov/docs/week%2012.pdf?customer=SECRET#p") == "week%2012.pdf"
    assert url_label("https://x.example.gov/") == "x.example.gov"
    meta = public_meta_errors({"unread": {"https://x.example.gov/a.pdf?customer=SECRET": "ValueError: bad"}})
    assert "SECRET" not in json.dumps(meta)
    for p in ("ingest/in_fort_wayne_cso.py", "ingest/oh_cso_pdf_notices.py"):
        assert "rsplit('/', 1)[-1]}: " not in (ROOT / "pipeline" / p).read_text(), p


def test_an_uncaught_exception_on_the_runner_prints_its_frames_and_error_text_only(tmp_path):
    # P1-4: a module that crashes on GitHub's runner prints no message of a library or provider
    code = "import common, os\nraise ValueError(os.environ['MSG'])\n"      # the message only at run time
    msg = f'no features: {{"token": "SECRETTOKEN"}} at {QUERY_URL}'
    run = lambda env: subprocess.run([sys.executable, "-c", code], cwd=ROOT / "pipeline", capture_output=True,
                                     text=True, timeout=60, env={**os.environ, "MSG": msg, **env})
    p = run({"GITHUB_ACTIONS": "true"})
    assert p.returncode == 1 and "Traceback" in p.stderr and "\nValueError: " in p.stderr
    assert "SECRETTOKEN" not in p.stderr and "?" not in p.stderr
    assert "SECRETTOKEN" in run({"GITHUB_ACTIONS": ""}).stderr          # a developer's run is unchanged


def test_no_module_prints_a_raw_traceback():
    files = [p for p in (ROOT / "pipeline").rglob("*.py")
             if ".venv" not in p.parts and "tests" not in p.parts and p.name != "common.py"]
    bad = [f"{p.relative_to(ROOT)}" for p in files
           if re.search(r"traceback\.(print_exc|format_exc|print_exception)\(", p.read_text())]
    assert not bad, bad


def test_the_log_filter_withholds_a_line_too_long_to_read_whole():
    # P2-9: a line over the limit is never cut into pieces that each pass on their own
    data = b"a" * ((1 << 20) - 3) + b"?token=SECRETTOKEN&x=1 tail\nnext line\n"
    p = run_filter(data)
    assert p.returncode == 0 and b"SECRETTOKEN" not in p.stdout
    assert p.stdout.endswith(b"next line\n") and b"withheld" in p.stdout
