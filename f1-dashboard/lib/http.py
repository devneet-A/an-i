"""Shared HTTP plumbing for both API clients.

Pages never import this; only lib/openf1.py and lib/jolpica.py do.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# (connect timeout, read timeout) in seconds. A short connect timeout means a
# dead server fails fast instead of freezing the page.
DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 20.0)


class APIError(Exception):
    """Raised for any failed API call. The message is safe to show to users."""


class AuthRequiredError(APIError):
    """The API refused the request because it needs (valid) credentials."""


class RateLimitError(APIError):
    """Too many requests: the API asked us to slow down (HTTP 429)."""


# On a 429 we retry ourselves, waiting at most this long each time. (urllib3
# would obey the server's Retry-After, which can be a minute: a frozen page.)
RATE_LIMIT_RETRIES = 2
RATE_LIMIT_MAX_WAIT = 4.0


class Throttle:
    """Spaces out requests so we stay under an API's rate limit.

    Streamlit serves every browser tab from its own thread, so the lock makes
    sure two tabs can't both decide "it's my turn" at the same moment.
    """

    def __init__(self, max_per_second: float) -> None:
        self._min_interval = 1.0 / max_per_second
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            sleep_for = self._last_call + self._min_interval - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_call = time.monotonic()


def build_session(user_agent: str) -> requests.Session:
    """A requests.Session that reuses connections and retries transient errors.

    Retries cover dropped connections and server hiccups (5xx). backoff_factor=0.5
    waits roughly 0.5s, 1s, 2s between attempts, short enough that a dead API
    shows a warning quickly instead of a long spinner. Rate limiting (429) is
    handled in get_json instead, with short capped waits.
    """
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        respect_retry_after_header=True,
        # Return the final response instead of raising, so we can turn it
        # into a friendly APIError below.
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
    return session


def get_json(
    session: requests.Session,
    throttle: Throttle,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET a URL and return parsed JSON, raising APIError on any failure."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        throttle.wait()
        try:
            resp = session.get(url, params=params, headers=headers, timeout=DEFAULT_TIMEOUT)
        except requests.Timeout as exc:
            raise APIError("The data service took too long to respond. Try again shortly.") from exc
        except requests.RequestException as exc:
            raise APIError(f"Could not reach the data service ({type(exc).__name__}).") from exc
        if resp.status_code != 429:
            break
        if attempt < RATE_LIMIT_RETRIES:
            time.sleep(min(_retry_after(resp), RATE_LIMIT_MAX_WAIT))
    else:
        raise RateLimitError("The data service's free rate limit was reached. "
                             "Wait about a minute, then try again.")

    if resp.status_code in (401, 403):
        raise AuthRequiredError("This data needs an authorised API account.")
    if resp.status_code == 404:
        # OpenF1 answers 404 {"detail": "No results found."} for an empty
        # query. That is "no data yet", not an error.
        return []
    if not resp.ok:
        raise APIError(f"The data service returned an error (HTTP {resp.status_code}).")

    try:
        return resp.json()
    except ValueError as exc:
        raise APIError("The data service sent a response we couldn't read.") from exc


def _retry_after(resp: requests.Response) -> float:
    """Seconds the server asked us to wait (Retry-After header), default 1."""
    try:
        return max(0.0, float(resp.headers.get("Retry-After", 1)))
    except ValueError:  # it can also be an HTTP date; not worth parsing here
        return 1.0
