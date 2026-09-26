import _run
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import fetch
from fetch import FetchError, get_json, post_json


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        routes = {"/ok": (200, json.dumps({"a": 1}).encode()), "/text": (200, b"hello"),
                  "/big": (200, b"x" * (fetch.MAX_BYTES + 10))}
        if self.path == "/slow":
            time.sleep(1.5)
            code, body = 200, b"{}"
        elif self.path.startswith("/secret-path"):
            code, body = 500, b"boom"
        else:
            code, body = routes.get(self.path, (404, b"{}"))
        self.send_response(code)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
srv.handle_error = lambda *args: None  # the oversize route ends in a broken pipe on purpose
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def expect_error(fn) -> FetchError:
    try:
        fn()
    except FetchError as e:
        return e
    raise AssertionError("expected FetchError")


def test_json_ok():
    assert get_json(f"{BASE}/ok", {}) == {"a": 1}


def test_http_error_carries_status_but_never_the_url():
    e = expect_error(lambda: get_json(f"{BASE}/secret-path/token123", {}))
    assert e.status == 500 and str(e) == "HTTP 500"
    assert "secret" not in str(e) and "token123" not in str(e)


def test_not_json():
    assert str(expect_error(lambda: get_json(f"{BASE}/text", {}))) == "response was not JSON"


def test_oversized_response_is_refused():
    assert str(expect_error(lambda: get_json(f"{BASE}/big", {}))) == "response too large"


def test_timeout():
    fetch.TIMEOUT_S = 0.5
    try:
        e = expect_error(lambda: get_json(f"{BASE}/slow", {}))
        assert str(e).startswith("network error")
    finally:
        fetch.TIMEOUT_S = 20


def test_unreachable_host():
    e = expect_error(lambda: get_json("http://127.0.0.1:9/nothing", {}))
    assert str(e).startswith("network error")


def test_post_with_empty_reply():
    assert post_json(f"{BASE}/hook", {"content": "x"}) is None


if __name__ == "__main__":
    _run.run(globals())
