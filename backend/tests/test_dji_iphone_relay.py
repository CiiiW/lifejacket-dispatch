import importlib.util
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

spec = importlib.util.spec_from_file_location(
    "dji_iphone_relay", Path(__file__).resolve().parents[2] / "scripts/dji_iphone_relay.py"
)
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)

GRANT = f"rtmp://127.0.0.1:19350/live/{'a' * 32}?user=publisher&pass={'b' * 43}"


def test_requires_private_scoped_grant(tmp_path):
    path = tmp_path / "grant.txt"
    path.touch(mode=0o600)
    path.write_text(GRANT + "\n")
    assert relay.publish_url_from(path) == GRANT
    path.write_text(GRANT.replace("127.0.0.1", "8.8.8.8"))
    with pytest.raises(ValueError):
        relay.publish_url_from(path)
    path.write_text(GRANT)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        relay.publish_url_from(path)


def test_rejects_wrong_code_and_browser_origin():
    client = TestClient(relay.create_app(GRANT, "expected-code", "unused", 24))
    for headers in (
        {},
        {"Authorization": "Bearer wrong-code"},
        {
            "Authorization": "Bearer expected-code",
            "Origin": "http://example.org",
        },
    ):
        with (
            pytest.raises(WebSocketDisconnect) as rejected,
            client.websocket_connect("/camera", headers=headers),
        ):
            pytest.fail("Unauthorized publisher was accepted")
        assert rejected.value.code == 1008
