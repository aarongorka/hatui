import json
import logging
from collections.abc import Mapping
from functools import cache
from typing import cast

import nerdfont  # pyright: ignore[reportMissingTypeStubs]

from .hatui_types import HomeAssistantWebsocketResponseType, JsonObject

logger = logging.getLogger(__name__)


def loads(raw: str | bytes) -> JsonObject:
    """Decode a websocket frame; `json.loads` is typed `Any`, but frames are always objects."""

    parsed: object = json.loads(raw)  # pyright: ignore[reportAny]  # json.loads is typed Any
    return cast("JsonObject", parsed)


def check_response(
    data: Mapping[str, object],
    expected_type: HomeAssistantWebsocketResponseType = "result",
) -> None:
    """Check a few things in the websocket response from HomeAssistant for validity."""

    if not data.get("type") == expected_type:
        logger.error("Wrong response type: %s", data)
        raise Exception("Wrong response type")

    if expected_type == "result" and not data.get("success"):
        logger.error("Command failed: %s", data)
        raise Exception("Command failed")


def get_domain_from_entity_id(entity_id: str) -> str:
    domain = entity_id.split(".", 1)[0]
    return domain


@cache
def mdi_to_nerd_font_name(mdi_name: str) -> str | None:
    """Attempt to translate from MDI's `mdi:some-thing` to nerdfont's `nf-md-some_thing`."""

    mdi_name_suffix = mdi_name.split(":", 1)[1]
    nf_name = f"nf-md-{mdi_name_suffix.replace('-', '_')}"
    if nerdfont.icons.get(nf_name):
        return nf_name
    else:
        return None


# These MDI icons don't exist in Nerdfont, need to manually map to alternatives
mdi_nf_mapping: dict[str, str] = {
    "mdi:button-pointer": "nf-md-gesture_tap_button",
    "mdi:radiobox-blank": "nf-fa-toggle_off",
    "mdi:radiobox-marked": "nf-fa-toggle_on",
    "mdi:speaker-play": "nf-md-speaker",
    "mdi:speaker-pause": "nf-md-speaker_off",
    "mdi:speaker-stop": "nf-md-speaker_off",
}

# https://github.com/home-assistant/frontend/blob/4030ce3f889efb62f3bbfc025d5fdfa9509d5cb6/src/data/icons.ts#L72-L126
fallback_domain_icons: dict[str, str] = {
    "ai_task": "mdi:star-four-points",
    "air_quality": "mdi:air-filter",
    "alert": "mdi:alert",
    "automation": "mdi:robot",
    "calendar": "mdi:calendar",
    "climate": "mdi:thermostat",
    "configurator": "mdi:cog",
    "conversation": "mdi:forum-outline",
    "counter": "mdi:counter",
    "date": "mdi:calendar",
    "datetime": "mdi:calendar-clock",
    "demo": "mdi:home-assistant",
    "device_tracker": "mdi:account",
    "google_assistant": "mdi:google-assistant",
    "group": "mdi:google-circles-communities",
    "homeassistant": "mdi:home-assistant",
    "homekit": "mdi:home-automation",
    "image_processing": "mdi:image-filter-frames",
    "image": "mdi:image",
    "input_boolean": "mdi:toggle-switch",
    "input_button": "mdi:button-pointer",
    "input_datetime": "mdi:calendar-clock",
    "input_number": "mdi:ray-vertex",
    "input_select": "mdi:format-list-bulleted",
    "input_text": "mdi:form-textbox",
    "lawn_mower": "mdi:robot-mower",
    "light": "mdi:lightbulb",
    "notify": "mdi:comment-alert",
    "number": "mdi:ray-vertex",
    "persistent_notification": "mdi:bell",
    "person": "mdi:account",
    "plant": "mdi:flower",
    "proximity": "mdi:apple-safari",
    "remote": "mdi:remote",
    "scene": "mdi:palette",
    "schedule": "mdi:calendar-clock",
    "script": "mdi:script-text",
    "select": "mdi:format-list-bulleted",
    "sensor": "mdi:eye",
    "simple_alarm": "mdi:bell",
    "siren": "mdi:bullhorn",
    "stt": "mdi:microphone-message",
    "sun": "mdi:white-balance-sunny",
    "text": "mdi:form-textbox",
    "time": "mdi:clock",
    "timer": "mdi:timer-outline",
    "template": "mdi:code-braces",
    "todo": "mdi:clipboard-list",
    "tts": "mdi:speaker-message",
    "vacuum": "mdi:robot-vacuum",
    "wake_word": "mdi:chat-sleep",
    "weather": "mdi:weather-partly-cloudy",
    "zone": "mdi:map-marker-radius",
}


def get_integrations_from_components(components: list[str]) -> set[str]:
    return set(x.split(".", 1)[0] for x in components)


def interpolate(x1: float, x2: float, y1: float, y2: float, x: float):
    """Perform linear interpolation for x between (x1,y1) and (x2,y2)"""

    return ((y2 - y1) * x + x2 * y1 - x1 * y2) / (x2 - x1)


def reverse_easing(i: float) -> float:
    return interpolate(0, 1, 1, 0, i)
