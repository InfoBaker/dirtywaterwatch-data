from ingest import nyc_dep_advisories as N


def test_an_empty_advisory_list_is_a_successful_poll_with_no_advisories(monkeypatch, tmp_path):
    """DEP's API answers [] when no water-quality advisory is in effect; that is a good poll, not a failure
    (a failure marks the source stale on the site and drops the day's poll)."""
    calls = {}
    def fake_get_json(sess, url, params=None):
        if url.endswith("advisory") or url.endswith("sensors"):
            return [], b"[]"
        return {"features": []}, b'{"features": []}'
    monkeypatch.setattr(N, "get_json", fake_get_json)
    monkeypatch.setattr(N, "layer_attrs", lambda sess, k, state: {})
    monkeypatch.setattr(N, "read_json", lambda path, default=None: {})
    monkeypatch.setattr(N, "write_json", lambda *a, **k: None)
    monkeypatch.setattr(N, "save_if_changed", lambda *a, **k: None)
    monkeypatch.setattr(N, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(N, "write_events", lambda sid, records, ok, error=None, meta=None: calls.update(sid=sid, n=len(records), ok=ok, error=error))
    assert N.main([]) == 0
    assert calls["ok"] is True and calls["n"] == 0


def test_a_non_list_answer_is_still_a_failure(monkeypatch):
    calls = {}
    monkeypatch.setattr(N, "get_json", lambda sess, url, params=None: ({"error": "down"}, b"{}"))
    monkeypatch.setattr(N, "read_json", lambda path, default=None: {})
    monkeypatch.setattr(N, "write_events", lambda sid, records, ok, error=None, meta=None: calls.update(ok=ok, error=error))
    assert N.main([]) == 1
    assert calls["ok"] is False and "advisory API answered" in calls["error"]
