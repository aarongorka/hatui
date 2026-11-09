import json
from typing import Any, cast

from hatui.dashboard import HomeAssistantDashboard


class FakeWebsocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

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
    dashboard.websocket = cast(Any, FakeWebsocket())

    results = await dashboard.fetch(
        [({"type": "a"}, dict), ({"type": "b"}, dict), ({"type": "c"}, dict)]
    )

    assert results == ["a", "b", "c"]


async def test_handle_response_drops_one_shot_callbacks_only() -> None:
    dashboard = HomeAssistantDashboard("ws://x", "token")
    calls: list[int] = []

    async def one_shot(response: Any) -> None:
        calls.append(response["id"])

    async def subscription(response: Any) -> None:
        calls.append(response["id"])

    dashboard.handle_entities_update = subscription  # pyright: ignore[reportAttributeAccessIssue]
    dashboard.requests_expecting_response_queue = {
        1: one_shot,
        2: dashboard.handle_entities_update,
    }

    for id_ in (1, 1, 2, 2):
        await dashboard.handle_response({"id": id_, "type": "result"})  # pyright: ignore[reportArgumentType]

    assert calls == [1, 2, 2]
    assert list(dashboard.requests_expecting_response_queue) == [2]


async def test_reconnect_retries_then_resubscribes() -> None:
    dashboard = HomeAssistantDashboard("ws://x", "token")
    dashboard.reconnect_initial_delay = 0
    dashboard.requests_expecting_response_queue = {7: cast(Any, None)}
    attempts: list[str] = []

    async def connect() -> None:
        attempts.append("connect")
        if len(attempts) == 1:
            raise OSError("down")

    async def subscribe() -> None:
        attempts.append("subscribe")

    dashboard.connect = connect  # pyright: ignore[reportAttributeAccessIssue]
    dashboard.subscribe_to_all_entities = subscribe  # pyright: ignore[reportAttributeAccessIssue]

    await dashboard.reconnect()

    assert attempts == ["connect", "connect", "subscribe"]
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


async def test_connects_wss_with_and_without_insecure(tmp_path: Any) -> None:
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

    async def handler(_: Any) -> None:
        await asyncio.sleep(1)

    async with websockets.serve(handler, "localhost", 0, ssl=server_ctx) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        url = f"wss://localhost:{port}"

        strict = HomeAssistantDashboard(url, "t")
        try:
            await strict.get_websocket()
            raise AssertionError("expected certificate verification to fail")
        except ssl.SSLCertVerificationError:
            pass

        insecure = HomeAssistantDashboard(url, "t", insecure=True)
        websocket = await insecure.get_websocket()
        await websocket.close()
