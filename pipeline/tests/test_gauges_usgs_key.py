"""Security review 2026-11-17, finding 11: the optional USGS key (environment usgs_api_key) goes to USGS hosts only.
NOAA's NWPS, any other host and a redirect off USGS never see it. A stand-in transport records what each request
carried; nothing goes to the network.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

from urllib.parse import urlsplit

import pytest
import requests

from ingest import gauges as G

KEY = "usgs-key-for-the-test"


class Recorder(requests.adapters.BaseAdapter):
    """Answers every request from a table by host: (status, headers, body); records the requests."""

    def __init__(self, answers: dict | None = None):
        super().__init__()
        self.sent: list[requests.PreparedRequest] = []
        self.answers = answers or {}

    def send(self, request, **kw):
        self.sent.append(request)
        status, headers, body = self.answers.get(urlsplit(request.url).hostname, (200, {}, b'{"features": []}'))
        r = requests.Response()
        r.status_code, r.url, r.request, r._content = status, request.url, request, body
        r.headers.update(headers)
        return r

    def close(self):
        pass


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(G, "_session", None)
    monkeypatch.setattr(G, "_usgs_session", None)
    rec = Recorder()
    for s in (G.session(), G.usgs_session()):
        s.mount("https://", rec)
        s.mount("http://", rec)
    return rec


def sent_keys(rec) -> list[tuple[str, str | None]]:
    return [(urlsplit(r.url).hostname, r.headers.get("X-Api-Key")) for r in rec.sent]


def test_the_key_goes_to_usgs_and_never_to_noaa(transport, monkeypatch):
    monkeypatch.setenv("usgs_api_key", KEY)
    G.fetch_state("CT")
    G.fetch_daily("01184000", 2015, 2024)
    transport.answers["api.water.noaa.gov"] = (200, {}, b'{"usgsId": "01184000"}')
    G.fetch_nwps("TFVC3")
    assert sent_keys(transport) == [("api.waterdata.usgs.gov", KEY), ("api.waterdata.usgs.gov", KEY),
                                    ("api.water.noaa.gov", None)]
    assert "X-Api-Key" not in G.session().headers and "X-Api-Key" not in G.usgs_session().headers


def test_a_redirect_off_usgs_drops_the_key_and_one_within_usgs_keeps_it(transport, monkeypatch):
    monkeypatch.setenv("usgs_api_key", KEY)
    transport.answers["api.waterdata.usgs.gov"] = (302, {"Location": "https://waterdata.usgs.gov/next"}, b"")
    transport.answers["waterdata.usgs.gov"] = (302, {"Location": "https://elsewhere.example.org/x"}, b"")
    G.usgs_get(G.LATEST, timeout=5)
    assert sent_keys(transport) == [("api.waterdata.usgs.gov", KEY), ("waterdata.usgs.gov", KEY),
                                    ("elsewhere.example.org", None)]


def test_usgs_get_refuses_any_other_host_and_plain_http(transport, monkeypatch):
    monkeypatch.setenv("usgs_api_key", KEY)
    for url in ("https://api.water.noaa.gov/nwps/v1/gauges/X", "http://api.waterdata.usgs.gov/x",
                "https://usgs.gov.example.org/x", "https://evilusgs.gov/x"):
        with pytest.raises(ValueError):
            G.usgs_get(url)
    assert transport.sent == []


def test_without_a_key_no_key_header_is_sent(transport, monkeypatch):
    monkeypatch.delenv("usgs_api_key", raising=False)
    G.fetch_state("CT")
    assert sent_keys(transport) == [("api.waterdata.usgs.gov", None)]
