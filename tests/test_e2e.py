import json
import ssl
import subprocess
from pathlib import Path

import websockets
from websockets.asyncio.server import ServerConnection

from hatui.dashboard import HomeAssistantDashboard
from hatui.entity_widget import EntityWidget, GroupCard
from hatui.hatui_types import JsonObject
from hatui.helpers import loads

from .factories import server_port

DISPLAY_ENTITIES: JsonObject = {
    "entity_categories": {"0": "config"},
    "entities": [{"ei": "light.desk", "pl": "demo", "en": "Desk"}],
}

STATE: JsonObject = {
    "entity_id": "light.desk", "state": "on", "attributes": {},
    "last_changed": None, "last_reported": None, "last_updated": None, "context": {},
}  # fmt: skip

CONFIG: JsonObject = {
    "allowlist_external_dirs": [], "allowlist_external_urls": [], "components": [],
    "config_dir": "", "config_source": "", "country": "x" * 2_000_000,  # bigger than websockets' default 1 MiB frame limit
     "currency": "",
    "debug": False, "elevation": 0, "external_url": None, "internal_url": None,
    "language": "en", "latitude": 0.0, "longitude": 0.0, "radius": 0,
    "recovery_mode": False, "safe_mode": False, "state": "RUNNING", "time_zone": "UTC",
    "unit_system": {
        "length": "km", "accumulated_precipitation": "mm", "area": "m²", "mass": "g",
        "pressure": "Pa", "temperature": "°C", "volume": "L", "wind_speed": "m/s",
    },
    "version": "1", "whitelist_external_dirs": [],
}  # fmt: skip

RESULTS: dict[str, JsonObject | list[JsonObject]] = {
    "config/entity_registry/list_for_display": DISPLAY_ENTITIES,
    "config/area_registry/list": [],
    "config/device_registry/list": [],
    "get_states": [STATE],
    "get_config": CONFIG,
    "frontend/get_icons": {"resources": {}},
    "frontend/get_translations": {"resources": {}},
}


async def fake_home_assistant(ws: ServerConnection) -> None:
    await ws.send(json.dumps({"type": "auth_required", "ha_version": "1"}))
    _ = await ws.recv()
    await ws.send(json.dumps({"type": "auth_ok", "ha_version": "1"}))
    async for message in ws:
        command = loads(message)
        result = RESULTS.get(str(command["type"]))
        await ws.send(
            json.dumps(
                {
                    "id": command["id"],
                    "type": "result",
                    "success": True,
                    "result": result,
                }
            )
        )


async def test_app_starts_against_self_signed_wss_with_insecure(tmp_path: Path) -> None:
    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    _ = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=wrong.example", "-keyout", str(key), "-out", str(cert)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert, key)

    async with websockets.serve(
        fake_home_assistant, "localhost", 0, ssl=server_ctx
    ) as s:
        port = server_port(s)
        app = HomeAssistantDashboard(f"wss://localhost:{port}", "t", insecure=True)
        async with app.run_test() as pilot:  # pyright: ignore[reportUnknownVariableType]  # HomeAssistantDashboard subclasses an unparameterised App
            for _ in range(50):
                await pilot.pause(0.1)
                if app.entity_widgets:
                    break
            await pilot.pause(0.2)
            widget = app.entity_widgets["light.desk"]
            assert isinstance(widget, EntityWidget)
            assert widget.entity_id == "light.desk"
            assert not app.query("#loading")
            assert len(app.query(GroupCard)) == 1
