"""Fake Home Assistant websocket server with a demo dataset, for screenshots.

uv run scripts/mock_ha.py
HATUI_WS_URL=ws://localhost:8123 HATUI_TOKEN=demo uv run hatui
"""

import asyncio
import json
import math
import io
import time
from collections.abc import Mapping
from http import HTTPStatus

import websockets
from PIL import Image, ImageDraw
from websockets.asyncio.server import ServerConnection
from websockets.http11 import Request, Response

from hatui.hatui_types import JsonObject, JsonValue
from hatui.helpers import loads

PORT = 8123

AREAS = {
    "living_room": "Living Room",
    "kitchen": "Kitchen",
    "bedroom": "Bedroom",
    "study": "Study",
    "bathroom": "Bathroom",
    "hallway": "Hallway",
    "balcony": "Balcony",
}

DEVICES = {
    "sonos": ("Sonos Beam", "living_room"),
    "fridge": ("Smart Fridge", "kitchen"),
    "nest": ("Nest Thermostat", "hallway"),
    "weather_station": ("Weather Station", "balcony"),
    "garden-node": ("garden-node", None),
    "roomba": ("Roomba", "living_room"),
    "garage": ("Garage Door Opener", None),
    "solar": ("Solar Inverter", None),
    "pool": ("Pool Controller", None),
    "prusa": ("prusa-mk4", None),
}

NOW = time.time()
ISO = "2026-11-10T09:00:00+00:00"

TEMP = {
    "device_class": "temperature",
    "unit_of_measurement": "°C",
    "state_class": "measurement",
}
HUMIDITY = {
    "device_class": "humidity",
    "unit_of_measurement": "%",
    "state_class": "measurement",
}
DIMMER = {"supported_color_modes": ["brightness"], "color_mode": "brightness"}
WHITE = {
    "supported_color_modes": ["color_temp"], "color_mode": "color_temp",
    "min_color_temp_kelvin": 2000, "max_color_temp_kelvin": 6500,
}  # fmt: skip

# entity_id: (name, area, device, state, attributes)
ENTITIES: dict[str, tuple[str, str | None, str | None, str, JsonObject]] = {
    "light.living_room_ceiling": ("Ceiling", "living_room", None, "on", {**WHITE, "brightness": 204, "color_temp_kelvin": 3200}),
    "light.living_room_lamp": ("Lamp", "living_room", None, "on", {"supported_color_modes": ["hs"], "color_mode": "hs", "brightness": 128, "hs_color": [30.0, 80.0]}),
    "light.living_room_strip": ("LED strip", "living_room", None, "off", {"supported_color_modes": ["hs"]}),
    "media_player.living_room_sonos": ("Sonos Beam", "living_room", "sonos", "playing", {"media_title": "Everything In Its Right Place", "media_artist": "Radiohead", "media_album_name": "Kid A", "media_duration": 251, "media_position": 96, "media_position_updated_at": ISO, "volume_level": 0.35, "is_volume_muted": False, "supported_features": 21437}),
    "sensor.living_room_temperature": ("Temperature", "living_room", None, "22.4", TEMP),
    "sensor.living_room_humidity": ("Humidity", "living_room", None, "48", HUMIDITY),
    "binary_sensor.living_room_motion": ("Motion", "living_room", None, "on", {"device_class": "motion"}),
    "light.kitchen_ceiling": ("Ceiling", "kitchen", None, "on", {**DIMMER, "brightness": 255}),
    "light.kitchen_bench": ("Bench", "kitchen", None, "off", DIMMER),
    "switch.kitchen_kettle": ("Kettle", "kitchen", None, "off", {"device_class": "outlet"}),
    "sensor.fridge_temperature": ("Fridge temperature", "kitchen", "fridge", "3.8", TEMP),
    "binary_sensor.fridge_door": ("Fridge door", "kitchen", "fridge", "off", {"device_class": "door"}),
    "light.bedroom_bedside": ("Bedside", "bedroom", None, "off", DIMMER),
    "fan.bedroom_fan": ("Fan", "bedroom", None, "on", {"percentage": 66, "supported_features": 1}),
    "sensor.bedroom_temperature": ("Temperature", "bedroom", None, "20.1", TEMP),
    "light.study_desk": ("Desk", "study", None, "on", {**WHITE, "brightness": 178, "color_temp_kelvin": 4500}),
    "sensor.study_power": ("Desk power", "study", None, "186", {"device_class": "power", "unit_of_measurement": "W", "state_class": "measurement"}),
    "sensor.study_energy": ("Desk energy", "study", None, "14.72", {"device_class": "energy", "unit_of_measurement": "kWh", "state_class": "total_increasing"}),
    "light.bathroom_mirror": ("Mirror", "bathroom", None, "off", DIMMER),
    "sensor.bathroom_humidity": ("Humidity", "bathroom", None, "71", HUMIDITY),
    "binary_sensor.bathroom_window": ("Window", "bathroom", None, "on", {"device_class": "window"}),
    "light.hallway": ("Hallway", "hallway", None, "on", {**DIMMER, "brightness": 90}),
    "binary_sensor.front_door": ("Front door", "hallway", None, "off", {"device_class": "door"}),
    "sensor.nest_temperature": ("Nest temperature", "hallway", "nest", "21.5", TEMP),
    "sensor.balcony_temperature": ("Temperature", "balcony", "weather_station", "17.8", TEMP),
    "sensor.balcony_wind_speed": ("Wind speed", "balcony", "weather_station", "14", {"device_class": "wind_speed", "unit_of_measurement": "km/h", "state_class": "measurement"}),
    "sensor.balcony_pressure": ("Pressure", "balcony", "weather_station", "1014", {"device_class": "pressure", "unit_of_measurement": "hPa", "state_class": "measurement"}),
    "weather.home": ("Home", None, None, "partlycloudy", {"temperature": 18.0, "temperature_unit": "°C", "humidity": 62, "pressure": 1014, "pressure_unit": "hPa", "wind_speed": 14, "wind_speed_unit": "km/h", "wind_bearing": 225, "supported_features": 3}),
    "person.alex": ("Alex", None, None, "home", {}),
    "person.sam": ("Sam", None, None, "not_home", {}),
    "sensor.garden_node_temperature": ("Temperature", None, "garden-node", "26.3", TEMP),
    "sensor.garden_node_soil_moisture": ("Soil moisture", None, "garden-node", "34", {"device_class": "moisture", "unit_of_measurement": "%", "state_class": "measurement"}),
    "sensor.garden_node_battery": ("Battery", None, "garden-node", "87", {"device_class": "battery", "unit_of_measurement": "%", "state_class": "measurement"}),
    "sensor.garden_node_rssi": ("Signal strength", None, "garden-node", "-67", {"device_class": "signal_strength", "unit_of_measurement": "dBm", "state_class": "measurement"}),
    "sensor.prusa_progress": ("Progress", None, "prusa", "42", {"unit_of_measurement": "%", "state_class": "measurement"}),
    "sensor.prusa_nozzle": ("Nozzle temperature", None, "prusa", "215", TEMP),
    "button.prusa_pause": ("Pause print", None, "prusa", "unknown", {}),
    "input_boolean.guest_mode": ("Guest mode", None, None, "off", {}),
    "camera.front_door": ("Front door", "hallway", None, "idle", {"supported_features": 2}),
    "cover.living_room_blinds": ("Blinds", "living_room", None, "open", {"current_position": 70, "device_class": "blind", "supported_features": 15}),
    "cover.bedroom_curtains": ("Curtains", "bedroom", None, "closed", {"current_position": 0, "device_class": "curtain", "supported_features": 15}),
    "cover.garage_door": ("Garage door", None, "garage", "closed", {"device_class": "garage", "supported_features": 3}),
    "lock.front_door": ("Front door lock", "hallway", None, "locked", {}),
    "lock.back_door": ("Back door lock", "balcony", None, "unlocked", {}),
    "climate.hallway_nest": ("Nest", "hallway", "nest", "heat", {"current_temperature": 21.5, "temperature": 22.0, "hvac_modes": ["off", "heat", "cool"], "hvac_action": "heating", "supported_features": 1}),
    "climate.bedroom_aircon": ("Air conditioner", "bedroom", None, "cool", {"current_temperature": 20.1, "temperature": 19.0, "hvac_modes": ["off", "cool", "heat"], "hvac_action": "cooling", "supported_features": 1}),
    "vacuum.roomba": ("Roomba", "living_room", "roomba", "docked", {"battery_level": 100, "supported_features": 12292}),
    "sensor.roomba_battery": ("Roomba battery", "living_room", "roomba", "100", {"device_class": "battery", "unit_of_measurement": "%", "state_class": "measurement"}),
    "lock.garage_side_door": ("Garage side door", None, "garage", "locked", {}),
    "switch.pool_pump": ("Pool pump", None, "pool", "on", {"device_class": "switch"}),
    "switch.pool_heater": ("Pool heater", None, "pool", "off", {"device_class": "switch"}),
    "sensor.pool_temperature": ("Pool temperature", None, "pool", "27.1", TEMP),
    "sensor.pool_ph": ("Pool pH", None, "pool", "7.4", {"device_class": "ph", "state_class": "measurement"}),
    "sensor.solar_power": ("Solar power", None, "solar", "3.42", {"device_class": "power", "unit_of_measurement": "kW", "state_class": "measurement"}),
    "sensor.solar_energy_today": ("Solar energy today", None, "solar", "18.6", {"device_class": "energy", "unit_of_measurement": "kWh", "state_class": "total_increasing"}),
    "sensor.grid_power": ("Grid power", None, "solar", "-1.12", {"device_class": "power", "unit_of_measurement": "kW", "state_class": "measurement"}),
    "binary_sensor.garage_door_open": ("Garage door open", None, "garage", "off", {"device_class": "garage_door"}),
    "binary_sensor.smoke_hallway": ("Smoke", "hallway", None, "off", {"device_class": "smoke"}),
    "binary_sensor.kitchen_leak": ("Leak", "kitchen", None, "off", {"device_class": "moisture"}),
    "light.balcony_fairy": ("Fairy lights", "balcony", None, "on", {**DIMMER, "brightness": 140}),
    "light.study_shelf": ("Shelf", "study", None, "on", {"supported_color_modes": ["hs"], "color_mode": "hs", "brightness": 200, "hs_color": [260.0, 70.0]}),
    "light.bedroom_ceiling": ("Ceiling", "bedroom", None, "off", {**WHITE}),
    "switch.study_monitor": ("Monitor", "study", None, "on", {"device_class": "outlet"}),
    "switch.living_room_tv": ("TV", "living_room", None, "off", {"device_class": "outlet"}),
    "switch.kitchen_dishwasher": ("Dishwasher", "kitchen", None, "on", {"device_class": "outlet"}),
    "sensor.dishwasher_remaining": ("Dishwasher time left", "kitchen", None, "42", {"device_class": "duration", "unit_of_measurement": "min", "state_class": "measurement"}),
    "sensor.study_co2": ("CO₂", "study", None, "812", {"device_class": "carbon_dioxide", "unit_of_measurement": "ppm", "state_class": "measurement"}),
    "sensor.study_temperature": ("Temperature", "study", None, "23.2", TEMP),
    "sensor.bathroom_temperature": ("Temperature", "bathroom", None, "24.6", TEMP),
    "sensor.balcony_uv": ("UV index", "balcony", "weather_station", "6", {"unit_of_measurement": "UV index", "state_class": "measurement"}),
    "sensor.balcony_rain": ("Rainfall", "balcony", "weather_station", "0.4", {"device_class": "precipitation", "unit_of_measurement": "mm", "state_class": "total_increasing"}),
    "media_player.study_speaker": ("Study speaker", "study", None, "paused", {"media_title": "Teardrop", "media_artist": "Massive Attack", "media_album_name": "Mezzanine", "media_duration": 330, "media_position": 41, "media_position_updated_at": ISO, "volume_level": 0.2, "is_volume_muted": False, "supported_features": 21437}),
    "media_player.bedroom_tv": ("Bedroom TV", "bedroom", None, "off", {"supported_features": 21437}),
    "fan.study_fan": ("Fan", "study", None, "off", {"percentage": 0, "supported_features": 1}),
    "person.jordan": ("Jordan", None, None, "home", {}),
    "input_boolean.holiday_mode": ("Holiday mode", None, None, "on", {}),
}  # fmt: skip

TRANSLATIONS = {
    "component.light.entity_component._.name": "Light",
    "component.light.entity_component._.state.on": "On",
    "component.light.entity_component._.state.off": "Off",
    "component.switch.entity_component._.state.on": "On",
    "component.switch.entity_component._.state.off": "Off",
    "component.fan.entity_component._.state.on": "On",
    "component.fan.entity_component._.state.off": "Off",
    "component.input_boolean.entity_component._.state.on": "On",
    "component.input_boolean.entity_component._.state.off": "Off",
    "component.binary_sensor.entity_component._.name": "Binary sensor",
    "component.binary_sensor.entity_component.motion.state.on": "Detected",
    "component.binary_sensor.entity_component.motion.state.off": "Clear",
    "component.binary_sensor.entity_component.door.state.on": "Open",
    "component.binary_sensor.entity_component.door.state.off": "Closed",
    "component.binary_sensor.entity_component.window.state.on": "Open",
    "component.binary_sensor.entity_component.window.state.off": "Closed",
    "component.media_player.entity_component._.name": "Media player",
    "component.media_player.entity_component._.state.playing": "Playing",
    "component.cover.entity_component._.state.open": "Open",
    "component.cover.entity_component._.state.closed": "Closed",
    "component.lock.entity_component._.state.locked": "Locked",
    "component.lock.entity_component._.state.unlocked": "Unlocked",
    "component.climate.entity_component._.state.heat": "Heat",
    "component.climate.entity_component._.state.cool": "Cool",
    "component.vacuum.entity_component._.state.docked": "Docked",
    "component.media_player.entity_component._.state.paused": "Paused",
    "component.media_player.entity_component._.state.off": "Off",
    "component.camera.entity_component._.state.idle": "Idle",
    "component.binary_sensor.entity_component.smoke.state.off": "Clear",
    "component.binary_sensor.entity_component.smoke.state.on": "Detected",
    "component.binary_sensor.entity_component.moisture.state.off": "Dry",
    "component.binary_sensor.entity_component.moisture.state.on": "Wet",
    "component.binary_sensor.entity_component.garage_door.state.off": "Closed",
    "component.binary_sensor.entity_component.garage_door.state.on": "Open",
    "component.person.entity_component._.state.home": "Home",
    "component.person.entity_component._.state.not_home": "Away",
    "component.weather.entity_component._.state.partlycloudy": "Partly cloudy",
}


def display_entities() -> JsonObject:
    return {
        "entity_categories": {},
        "entities": [
            {
                "ei": entity_id,
                "pl": "demo",
                "en": name,
                **({"ai": area} if area else {}),
                **({"di": device} if device else {}),
            }
            for entity_id, (name, area, device, _, _) in ENTITIES.items()
        ],
    }


def areas() -> list[JsonObject]:
    return [
        {
            "aliases": [], "area_id": area_id, "floor_id": None,
            "humidity_entity_id": None, "icon": None, "labels": [], "name": name,
            "picture": None, "temperature_entity_id": None,
            "created_at": 0, "modified_at": 0,
        }
        for area_id, name in AREAS.items()
    ]  # fmt: skip


def devices() -> list[JsonObject]:
    return [
        {
            "area_id": area, "configuration_url": None, "config_entries": [],
            "config_entries_subentries": {}, "connections": [], "created_at": 0,
            "disabled_by": None, "entry_type": None, "hw_version": None,
            "id": device_id, "identifiers": [], "labels": [], "manufacturer": None,
            "model": None, "model_id": None, "modified_at": 0, "name_by_user": None,
            "name": name, "primary_config_entry": None, "serial_number": None,
            "sw_version": None, "via_device_id": None,
        }
        for device_id, (name, area) in DEVICES.items()
    ]  # fmt: skip


def states() -> list[JsonObject]:
    return [
        {
            "entity_id": entity_id,
            "state": state,
            "attributes": {"friendly_name": name, **attrs},
            "last_changed": ISO,
            "last_reported": ISO,
            "last_updated": ISO,
            "context": {"id": "x", "parent_id": None, "user_id": None},
        }
        for entity_id, (name, _, _, state, attrs) in ENTITIES.items()
    ]


CONFIG: JsonObject = {
    "allowlist_external_dirs": [], "allowlist_external_urls": [], "components": [],
    "config_dir": "", "config_source": "", "country": "AU", "currency": "AUD",
    "debug": False, "elevation": 0, "external_url": None, "internal_url": None,
    "language": "en", "latitude": 0.0, "longitude": 0.0, "radius": 0,
    "recovery_mode": False, "safe_mode": False, "state": "RUNNING", "time_zone": "UTC",
    "unit_system": {
        "length": "km", "accumulated_precipitation": "mm", "area": "m²", "mass": "g",
        "pressure": "hPa", "temperature": "°C", "volume": "L", "wind_speed": "km/h",
    },
    "version": "2026.11.0", "whitelist_external_dirs": [],
}  # fmt: skip


def history(entity_id: str) -> list[JsonObject]:
    _, _, _, state, attrs = ENTITIES[entity_id]
    first: JsonObject = {"s": state, "a": attrs, "lu": NOW - 86400}
    try:
        base = float(state)
    except ValueError:
        return [first, {"s": state, "lu": NOW - 43200}]
    points = [
        {"s": f"{base + 2 * math.sin(i / 3.0):.1f}", "lu": NOW - 86400 + i * 1800}
        for i in range(1, 48)
    ]
    return [first, *points]


def forecast() -> list[JsonObject]:
    days = [
        ("sunny", 24),
        ("partlycloudy", 22),
        ("rainy", 17),
        ("cloudy", 19),
        ("sunny", 25),
    ]
    return [
        {
            "datetime": f"2026-11-{11 + i}T00:00:00+00:00",
            "condition": condition,
            "temperature": high,
            "templow": high - 8,
        }
        for i, (condition, high) in enumerate(days)
    ]


def handle(command: JsonObject) -> JsonValue:
    kind = command["type"]
    if kind == "config/entity_registry/list_for_display":
        return display_entities()
    if kind == "config/area_registry/list":
        return areas()
    if kind == "config/device_registry/list":
        return devices()
    if kind == "get_states":
        return states()
    if kind == "get_config":
        return CONFIG
    if kind == "frontend/get_translations":
        return {"resources": TRANSLATIONS}
    if kind == "frontend/get_icons":
        return {"resources": {}}
    if kind == "history/history_during_period":
        wanted = command.get("entity_ids", [])
        assert isinstance(wanted, list)
        return {e: history(e) for e in wanted if isinstance(e, str) and e in ENTITIES}
    if kind == "logbook/get_events":
        return [
            {"when": NOW - 600, "state": "on"},
            {"when": NOW - 7200, "state": "off"},
            {"when": NOW - 28800, "state": "on"},
        ]
    if kind == "call_service" and command.get("return_response"):
        target = command["target"]
        assert isinstance(target, Mapping)
        entity_id = str(target["entity_id"])
        return {"response": {entity_id: {"forecast": forecast()}}}
    return None


def snapshot(entity_id: str) -> bytes:
    """A little animated scene so the ASCII art has something to chew on."""

    width, height = 320, 180
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        shade = int(255 * (1 - y / height))
        draw.line([(0, y), (width, y)], fill=(shade // 3, shade // 2, shade))
    phase = (time.time() / 8 + hash(entity_id) % 7) % 1
    sun_x = int(width * phase)
    draw.ellipse([sun_x - 18, 30, sun_x + 18, 66], fill=(255, 220, 90))
    draw.polygon(
        [
            (0, 140),
            (90, 80),
            (170, 130),
            (250, 70),
            (width, 120),
            (width, height),
            (0, height),
        ],
        fill=(40, 90, 50),
    )
    draw.rectangle([0, 150, width, height], fill=(30, 60, 35))
    draw.rectangle([120, 100, 200, 160], fill=(160, 70, 60))
    draw.polygon([(110, 100), (160, 65), (210, 100)], fill=(90, 40, 40))
    draw.rectangle([150, 125, 170, 160], fill=(240, 200, 120))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


def serve_http(_: ServerConnection, request: Request) -> Response | None:
    prefix = "/api/camera_proxy/"
    if not request.path.startswith(prefix):
        return None
    body = snapshot(request.path.removeprefix(prefix))
    response = Response(
        HTTPStatus.OK, "OK", websockets.Headers({"Content-Type": "image/jpeg"}), body
    )
    return response


async def serve(ws: ServerConnection) -> None:
    await ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.11.0"}))
    _ = await ws.recv()
    await ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.11.0"}))
    async for message in ws:
        command = loads(message)
        if command["type"] == "lovelace/config":
            reply = {
                "id": command["id"], "type": "result", "success": False,
                "error": {"code": "config_not_found", "message": "No config found."},
            }  # fmt: skip
        else:
            reply = {
                "id": command["id"],
                "type": "result",
                "success": True,
                "result": handle(command),
            }
        await ws.send(json.dumps(reply))


async def main() -> None:
    async with websockets.serve(
        serve, "localhost", PORT, max_size=None, process_request=serve_http
    ):
        print(f"󰢩 Mock Home Assistant on ws://localhost:{PORT}")
        _ = await asyncio.Future[None]()


if __name__ == "__main__":
    asyncio.run(main())
