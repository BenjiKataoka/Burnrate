"""The one HTTP client every collector and the Discord sender use: JSON only, a hard
timeout, a size cap, and error messages that never contain the URL."""
import json
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_S: float = 20
MAX_BYTES = 5_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: urllib would resend the Authorization header to the new host."""
    def redirect_request(self, req: urllib.request.Request, fp: object, code: int, msg: str,
                         headers: object, newurl: str) -> None:
        return None  # urllib then raises HTTPError for the 3xx, which _send turns into FetchError


_OPENER = urllib.request.build_opener(_NoRedirect)


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def get_json(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "burnrate", **headers})
    return _send(req)


def post_json(url: str, body: dict) -> Any:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "burnrate"})
    return _send(req)


def _send(req: urllib.request.Request) -> Any:
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            body = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        # Never the URL: it can hold a project id or, for Discord, the webhook secret.
        raise FetchError(f"HTTP {e.code}", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(f"network error ({type(e).__name__})") from None
    if len(body) > MAX_BYTES:
        raise FetchError("response too large")
    try:
        return json.loads(body) if body else None
    except ValueError:
        raise FetchError("response was not JSON") from None
