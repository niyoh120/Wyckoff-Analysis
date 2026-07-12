from __future__ import annotations

from email.message import Message
from types import SimpleNamespace

from cli import dashboard


def _handler(headers: dict[str, str], path: str = "/api/config"):
    handler = object.__new__(dashboard._Handler)
    parsed = Message()
    for key, value in headers.items():
        parsed[key] = value
    handler.headers = parsed
    handler.path = path
    handler.server = SimpleNamespace(server_port=8765)
    responses = []
    handler._json = lambda payload, status=200: responses.append((status, payload))
    return handler, responses


def test_dashboard_api_requires_random_token():
    handler, responses = _handler({"Host": "127.0.0.1:8765"})

    assert handler._trusted_request() is False
    assert responses == [(403, {"error": "invalid dashboard token"})]


def test_dashboard_blocks_cross_origin_write_even_with_token():
    handler, responses = _handler(
        {
            "Host": "127.0.0.1:8765",
            "Origin": "https://evil.test",
            "X-Wyckoff-Token": dashboard._DASHBOARD_TOKEN,
            "Content-Type": "application/json",
        }
    )

    assert handler._trusted_write() is False
    assert responses == [(403, {"error": "cross-origin request blocked"})]


def test_dashboard_accepts_same_origin_json_write():
    handler, responses = _handler(
        {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "X-Wyckoff-Token": dashboard._DASHBOARD_TOKEN,
            "Content-Type": "application/json; charset=utf-8",
        }
    )

    assert handler._trusted_write() is True
    assert responses == []
