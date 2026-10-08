"""Tests for HTTP error handling: rate limits, empty results, not caching empties."""

import pandas as pd
import pytest
import requests

from lib import http, openf1


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.ok = status < 400

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0

    def get(self, *a, **k):
        self.calls += 1
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda s: None)


def test_429_then_success_retries():
    s = FakeSession([FakeResp(429, headers={"Retry-After": "60"}), FakeResp(200, [{"a": 1}])])
    assert http.get_json(s, http.Throttle(1000), "u") == [{"a": 1}] and s.calls == 2


def test_429_gives_up_with_clear_error():
    s = FakeSession([FakeResp(429)] * 3)
    with pytest.raises(http.RateLimitError, match="rate limit"):
        http.get_json(s, http.Throttle(1000), "u")
    assert s.calls == 3


def test_404_is_empty_and_401_is_auth():
    assert http.get_json(FakeSession([FakeResp(404, {"detail": "No results found."})]),
                         http.Throttle(1000), "u") == []
    with pytest.raises(http.AuthRequiredError):
        http.get_json(FakeSession([FakeResp(401)]), http.Throttle(1000), "u")


def test_timeout_becomes_api_error():
    class Boom:
        def get(self, *a, **k):
            raise requests.Timeout()
    with pytest.raises(http.APIError, match="too long"):
        http.get_json(Boom(), http.Throttle(1000), "u")


def test_empty_static_results_are_not_cached(monkeypatch):
    answers = [[], [{"driver_number": 1, "lap_number": 1}]]
    monkeypatch.setattr(openf1, "get_json", lambda *a, **k: answers.pop(0))
    openf1._fetch_static.clear()
    assert openf1.get_laps(999).empty                 # OpenF1 not ready yet
    assert len(openf1.get_laps(999)) == 1             # asked again, not stuck empty
    assert isinstance(openf1.get_laps(999), pd.DataFrame) and answers == []  # now cached
