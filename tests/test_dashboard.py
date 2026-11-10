import json
from pathlib import Path
from typing import cast

import pytest
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.server import ServerConnection

from hatui.dashboard import HomeAssistantDashboard, parse
from hatui.hatui_types import Command, DisplayEntityRaw, JsonObject, State
from hatui.helpers import loads

from .factories import make_state, server_port


def _noop(*_args: object, **_kwargs: object) -> None:
    return None


def _attach(dashboard: HomeAssistantDashboard, websocket: "FakeWebsocket") -> None:
    dashboard.websocket = cast("ClientConnection", cast("object", websocket))


def _id(response: JsonObject) -> int:
    id_ = response["id"]
    assert isinstance(id_, int)
    return id_


async def _ignore(_response: JsonObject) -> None:
    return None


class FakeWebsocket:
    def __init__(self) -> None:
        self.sent: list[JsonObject] = []

    async def send(self, message: str) -> None:
        self.sent.append(loads(message))

    async def recv(self) -> str:
        # Replies arrive in reverse order to prove results are matched by id
        command = self.sent.pop()
        return json.dumps(
            {
                "id": command["id"],
                "type": "result",
                "success": True,
                "result": command["type"],
            }
        )


async def test_fetch_sends_all_commands_before_reading() -> None:
    dashboard = HomeAssistantDashboard("ws://x", "token")
    _attach(dashboard, FakeWebsocket())

    results = await dashboard.fetch_raw([{"type": "a"}, {"type": "b"}, {"type": "c"}])

    assert results == ["a", "b", "c"]


async def test_handle_response_drops_one_shot_callbacks_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard = HomeAssistantDashboard("ws://x", "token")
    calls: list[int] = []

    async def one_shot(response: JsonObject) -> None:
        calls.append(_id(response))

    async def subscription(response: JsonObject) -> None:
        calls.append(_id(response))

    monkeypatch.setattr(dashboard, "handle_entities_update", subscription)
    dashboard.requests_expecting_response_queue = {
        1: one_shot,
        2: dashboard.handle_entities_update,
    }

    for id_ in (1, 1, 2, 2):
        await dashboard.handle_response({"id": id_, "type": "result"})

    assert calls == [1, 2, 2]
    assert list(dashboard.requests_expecting_response_queue) == [2]


async def test_reconnect_retries_then_resubscribes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard = HomeAssistantDashboard("ws://x", "token")
    dashboard.reconnect_initial_delay = 0
    dashboard.requests_expecting_response_queue = {7: _ignore}
    attempts: list[str] = []

    async def connect() -> None:
        attempts.append("connect")
        if len(attempts) == 1:
            raise OSError("down")

    async def subscribe() -> None:
        attempts.append("subscribe")

    async def subscribe_registry() -> None:
        attempts.append("registry")

    monkeypatch.setattr(dashboard, "connect", connect)
    monkeypatch.setattr(dashboard, "subscribe_to_all_entities", subscribe)
    monkeypatch.setattr(dashboard, "subscribe_to_registry_updates", subscribe_registry)
    monkeypatch.setattr(dashboard, "set_timer", _noop)

    await dashboard.reconnect()

    assert attempts == ["connect", "connect", "subscribe", "registry"]
    assert dashboard.requests_expecting_response_queue == {}


def test_ssl_context_only_relaxed_when_insecure_wss() -> None:
    import ssl

    secure = HomeAssistantDashboard("wss://x", "t")
    assert secure.get_ssl_context() is None

    plain = HomeAssistantDashboard("ws://x", "t", insecure=True)
    assert plain.get_ssl_context() is None

    context = HomeAssistantDashboard("wss://x", "t", insecure=True).get_ssl_context()
    assert context is not None
    assert context.verify_mode == ssl.CERT_NONE
    assert not context.check_hostname


async def test_connects_wss_with_and_without_insecure(tmp_path: Path) -> None:
    import asyncio
    import ssl
    import subprocess

    import websockets

    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    _ = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=wrong.example", "-keyout", str(key), "-out", str(cert)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert, key)

    async def handler(_: ServerConnection) -> None:
        await asyncio.sleep(1)

    async with websockets.serve(handler, "localhost", 0, ssl=server_ctx) as server:
        port = server_port(server)
        url = f"wss://localhost:{port}"

        strict = HomeAssistantDashboard(url, "t")
        try:
            _ = await strict.get_websocket()
            raise AssertionError("expected certificate verification to fail")
        except ssl.SSLCertVerificationError:
            pass

        insecure = HomeAssistantDashboard(url, "t", insecure=True)
        websocket = await insecure.get_websocket()
        await websocket.close()


async def test_refresh_layout_rebuilds_and_resubscribes_on_new_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard = HomeAssistantDashboard("ws://x", "token")
    sent: list[Command] = []
    subscribed: list[int] = []
    registry: list[DisplayEntityRaw] = [{"ei": "light.a", "en": "A"}]
    states: list[State] = [make_state("light.a", "on")]

    async def request(command: Command, _result_type: type[object]) -> object:
        sent.append(command)
        return {
            "config/entity_registry/list_for_display": {"entities": registry},
            "get_states": states,
        }.get(str(command["type"]), [])

    async def subscribe() -> None:
        subscribed.append(1)

    monkeypatch.setattr(dashboard, "request", request)
    monkeypatch.setattr(dashboard, "subscribe_to_all_entities", subscribe)
    monkeypatch.setattr(dashboard, "notify", _noop)
    dashboard.entities_subscription_id = 7

    await dashboard.refresh_layout()
    assert dashboard.entity_widget_ids() == ["light.a"]
    assert len(subscribed) == 1
    assert {"type": "unsubscribe_events", "subscription": 7} in sent

    await dashboard.refresh_layout()
    assert len(subscribed) == 1  # unchanged layout is left alone

    registry.append({"ei": "light.b", "en": "B"})
    states.append(make_state("light.b", "off"))
    await dashboard.refresh_layout()
    assert sorted(dashboard.entity_widget_ids()) == ["light.a", "light.b"]
    assert len(subscribed) == 2


def test_parse_keeps_undeclared_keys() -> None:
    pytest.importorskip("pydantic")
    raw: JsonObject = {
        "entity_id": "light.a",
        "state": "on",
        "attributes": {"friendly_name": "A", "mystery": 1},
        "last_changed": "x",
        "last_reported": "x",
        "last_updated": "x",
        "context": {"id": "c", "parent_id": None, "user_id": None},
        "extra_top_level": True,
    }
    [state] = parse(list[State], [raw])
    assert state["attributes"].get("mystery") == 1
    assert state.get("extra_top_level") is True
