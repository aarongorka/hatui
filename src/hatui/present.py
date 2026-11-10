"""Turn an entity and its state in to what a row displays: icon, colour and state text."""

import datetime
import logging
from dataclasses import dataclass, field
from functools import cache

import humanize
import nerdfont  # pyright: ignore[reportMissingTypeStubs]

from .hatui_types import EntityIcons, IconResourceType, Icons, State, StateAttributes
from .helpers import (
    fallback_domain_icons,
    mdi_nf_mapping,
    mdi_to_nerd_font_name,
)
from .lovelace import DisplayEntity, domain_of
from .translate import Translations

logger = logging.getLogger(__name__)

FALLBACK_GLYPH_NAME = "nf-md-help_circle_outline"

PALETTE = {
    "red": "#f44336",
    "orange": "#ff9800",
    "deep-orange": "#ff6f22",
    "amber": "#ffc107",
    "yellow": "#ffeb3b",
    "lime": "#cddc39",
    "green": "#4caf50",
    "teal": "#009688",
    "cyan": "#00bcd4",
    "light-blue": "#03a9f4",
    "blue": "#2196f3",
    "indigo": "#3f51b5",
    "purple": "#926bc7",
    "deep-purple": "#6e41ab",
    "blue-grey": "#607d8b",
    "grey": "#9e9e9e",
    "light-grey": "#bdbdbd",
}
UNAVAILABLE_COLOUR = "#bdbdbd"

# From the HA frontend's default theme (color.globals.ts), keyed as `domain[-device_class]-state`
_NAMED_COLOURS = {
    "active": "amber",
    "inactive": "grey",
    "alarm_control_panel-armed_away": "green",
    "alarm_control_panel-armed_custom_bypass": "green",
    "alarm_control_panel-armed_home": "green",
    "alarm_control_panel-armed_night": "green",
    "alarm_control_panel-armed_vacation": "green",
    "alarm_control_panel-arming": "orange",
    "alarm_control_panel-disarming": "orange",
    "alarm_control_panel-pending": "orange",
    "alarm_control_panel-triggered": "red",
    "alert-off": "orange",
    "alert-on": "red",
    "binary_sensor-active": "amber",
    "climate-auto": "green",
    "climate-cool": "blue",
    "climate-dry": "orange",
    "climate-fan_only": "cyan",
    "climate-heat": "deep-orange",
    "climate-heat_cool": "amber",
    "cover-active": "purple",
    "device_tracker-active": "blue",
    "device_tracker-home": "green",
    "fan-active": "cyan",
    "humidifier-on": "blue",
    "lawn_mower-active": "teal",
    "lawn_mower-error": "red",
    "light-active": "amber",
    "lock-jammed": "red",
    "lock-locked": "green",
    "lock-locking": "orange",
    "lock-unlocked": "red",
    "lock-unlocking": "orange",
    "lock-open": "red",
    "lock-opening": "orange",
    "media_player-active": "light-blue",
    "person-active": "blue",
    "person-home": "green",
    "plant-active": "red",
    "siren-active": "red",
    "sun-above_horizon": "amber",
    "sun-below_horizon": "indigo",
    "switch-active": "amber",
    "update-active": "orange",
    "vacuum-active": "teal",
    "vacuum-error": "red",
    "valve-active": "blue",
    "sensor-battery-high": "green",
    "sensor-battery-low": "red",
    "sensor-battery-medium": "orange",
    "water_heater-eco": "green",
    "water_heater-electric": "orange",
    "water_heater-gas": "orange",
    "water_heater-heat_pump": "orange",
    "water_heater-high_demand": "deep-orange",
    "water_heater-performance": "deep-orange",
    "weather-clear_night": "deep-purple",
    "weather-cloudy": "light-grey",
    "weather-exceptional": "red",
    "weather-fog": "grey",
    "weather-hail": "cyan",
    "weather-lightning_rainy": "lime",
    "weather-lightning": "yellow",
    "weather-partlycloudy": "blue-grey",
    "weather-pouring": "indigo",
    "weather-rainy": "blue",
    "weather-snowy_rainy": "light-blue",
    "weather-sunny": "amber",
    "weather-windy_variant": "green",
    "weather-windy": "green",
}
for _device_class in (
    "battery",
    "carbon_monoxide",
    "gas",
    "glass_break",
    "heat",
    "lock",
    "moisture",
    "problem",
    "safety",
    "smoke",
    "sound",
    "tamper",
):
    _NAMED_COLOURS[f"binary_sensor-{_device_class}-on"] = "red"

STATE_COLOURS = {k: PALETTE[v] for k, v in _NAMED_COLOURS.items()}
STATE_COLOURS["weather-snowy"] = "#c0e0ff"

STATE_COLORED_DOMAINS = frozenset(
    {
        "alarm_control_panel", "alert", "automation", "binary_sensor", "calendar",
        "camera", "climate", "cover", "device_tracker", "fan", "group", "humidifier",
        "input_boolean", "lawn_mower", "light", "lock", "media_player", "person",
        "plant", "remote", "schedule", "script", "siren", "sun", "switch", "timer",
        "update", "vacuum", "valve", "water_heater", "weather",
    }
)  # fmt: skip

TOGGLE_DOMAINS = frozenset({"light", "switch", "input_boolean"})
NUMERIC_DOMAINS = frozenset({"sensor", "number", "input_number", "counter"})
INACTIVE_STATES = frozenset(
    {"off", "closed", "not_home", "idle", "standby", "docked", "paused", "disarmed", "unavailable", "unknown"}
)  # fmt: skip
MUTED_STATES = INACTIVE_STATES | {"locked"}


@dataclass
class IconSet:
    """Icon definitions: `component[domain][device_class|"_"]` and `entity[platform][domain][translation_key]`."""

    component: Icons = field(default_factory=dict)
    entity: EntityIcons = field(default_factory=dict)


@dataclass
class Presentation:
    icon: str
    colour: str | None
    state_text: str
    state_classes: str


def _pick(resource: IconResourceType | None, state: str | None) -> str | None:
    if not resource:
        return None
    by_state = resource.get("state") or {}
    return (state and by_state.get(state)) or resource.get("default")


def resolve_icon_name(
    entity: DisplayEntity | None,
    entity_id: str,
    state: str | None,
    attributes: StateAttributes,
    icons: IconSet,
) -> str:
    domain = domain_of(entity_id)
    if entity and entity.icon:
        return entity.icon
    icon = attributes.get("icon")
    if icon:
        return icon

    if entity and entity.platform and entity.translation_key:
        platform_icons = icons.entity.get(entity.platform, {}).get(domain, {})
        found = _pick(platform_icons.get(entity.translation_key), state)
        if found:
            return found

    component = icons.component.get(domain, {})
    device_class = attributes.get("device_class")
    for key in (device_class, "_"):
        found = _pick(component.get(key) if key else None, state)
        if found:
            return found
    return fallback_domain_icons.get(domain, "mdi:help-circle-outline")


@cache
def glyph(mdi_name: str) -> str:
    """Nerd Font glyph for an `mdi:` icon name, never raising for unknown names."""

    nf_name = mdi_nf_mapping.get(mdi_name) or (
        mdi_to_nerd_font_name(mdi_name) if ":" in mdi_name else None
    )
    found = nerdfont.icons.get(nf_name) if nf_name else None
    return found or nerdfont.icons[FALLBACK_GLYPH_NAME]


def is_active(domain: str, state: str) -> bool:
    if state in ("unavailable", "unknown"):
        return False
    if state == "off" and domain != "alert":
        return False
    custom: dict[str, bool] = {
        "alarm_control_panel": state != "disarmed",
        "alert": state != "idle",
        "cover": state != "closed",
        "device_tracker": state != "not_home",
        "person": state != "not_home",
        "lawn_mower": state not in ("docked", "paused", "idle"),
        "lock": state != "locked",
        "media_player": state != "standby",
        "vacuum": state not in ("idle", "docked", "paused"),
        "valve": state != "closed",
        "plant": state == "problem",
        "group": state in ("on", "home", "open", "locked", "problem"),
        "timer": state == "active",
        "camera": state in ("streaming", "recording"),
    }
    return custom.get(domain, True)


def _scale(hex_colour: str, factor: float) -> str:
    r, g, b = (int(hex_colour[i : i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(min(255, int(c * factor)) for c in (r, g, b)))


def state_colour(
    entity_id: str, state: str | None, attributes: StateAttributes
) -> str | None:
    """Port of the frontend's `stateColorCss`; None means the default text colour."""

    domain = domain_of(entity_id)
    device_class = attributes.get("device_class")

    if domain == "sensor" and device_class == "battery":
        try:
            level = float(state or "")
        except ValueError:
            return None
        band = "high" if level >= 70 else "medium" if level >= 30 else "low"
        return STATE_COLOURS[f"sensor-battery-{band}"]
    if domain not in STATE_COLORED_DOMAINS or state is None:
        return None
    if state == "unavailable":
        return UNAVAILABLE_COLOUR

    activity = "active" if is_active(domain, state) else "inactive"
    candidates = [
        f"{domain}-{device_class}-{state}" if device_class else None,
        f"{domain}-{state}",
        f"{domain}-{device_class}-{activity}" if device_class else None,
        f"{domain}-{activity}",
        activity,
    ]
    colour = next((STATE_COLOURS[k] for k in candidates if k in STATE_COLOURS), None)

    if domain == "light" and colour:
        rgb = attributes.get("rgb_color")
        if state == "on" and rgb and len(rgb) >= 3:
            colour = "#{:02x}{:02x}{:02x}".format(*(int(c) for c in rgb[:3]))
        brightness = attributes.get("brightness")
        if state == "on" and isinstance(brightness, int | float):
            colour = _scale(colour, (brightness + 245) / 500)
    return colour


def state_classes(domain: str, state: str | None) -> str:
    if domain in ("button", "input_button"):
        return "state state-button"
    if state in ("unavailable", "unknown"):
        return "state state-unavailable"
    if state in MUTED_STATES:
        return "state state-off"
    if state in ("on", "open"):
        return "state state-on"
    return "state"


def _decimals(raw: str) -> int:
    return len(raw.split(".", 1)[1]) if "." in raw else 0


def format_number(raw: str, precision: int | None, unit: str | None) -> str | None:
    try:
        value = float(raw)
    except ValueError:
        return None
    places = precision if precision is not None else _decimals(raw)
    text = f"{value:,.{places}f}"
    if not unit:
        return text
    joiner = "" if unit == "%" or unit.startswith("°") else " "
    return f"{text}{joiner}{unit}"


def _humanise_timestamp(raw: str) -> str | None:
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return humanize.naturaltime(parsed)


def render_state(
    entity: DisplayEntity | None,
    entity_id: str,
    state: str | None,
    attributes: StateAttributes,
    translations: Translations,
) -> str:
    domain = domain_of(entity_id)
    if domain in ("button", "input_button"):
        return "Press"
    if not state:
        return ""
    if state in ("unavailable", "unknown"):
        return translations.state(domain, state) or state

    device_class = attributes.get("device_class")
    unit = attributes.get("unit_of_measurement")

    if domain in TOGGLE_DOMAINS and state in ("on", "off"):
        return nerdfont.icons[f"nf-fa-toggle_{state}"]
    if device_class == "timestamp":
        return _humanise_timestamp(state) or state
    if device_class == "duration" and unit == "s":
        try:
            return humanize.naturaldelta(datetime.timedelta(seconds=float(state)))
        except ValueError:
            return state
    if domain in NUMERIC_DOMAINS and device_class != "enum":
        precision = entity.display_precision if entity else None
        formatted = format_number(state, precision, unit)
        if formatted is not None:
            return formatted

    return (
        translations.state(
            domain,
            state,
            device_class,
            entity.platform if entity else None,
            entity.translation_key if entity else None,
        )
        or state
    )


def present(
    entity: DisplayEntity | None,
    entity_id: str,
    state: State | None,
    icons: IconSet,
    translations: Translations,
) -> Presentation:
    raw = state.get("state") if state else None
    attributes: StateAttributes = state["attributes"] if state else {}
    return Presentation(
        icon=glyph(resolve_icon_name(entity, entity_id, raw, attributes, icons)),
        colour=state_colour(entity_id, raw, attributes),
        state_text=render_state(entity, entity_id, raw, attributes, translations),
        state_classes=state_classes(domain_of(entity_id), raw),
    )
