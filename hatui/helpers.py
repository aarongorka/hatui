import datetime
import logging

import humanize
import nerdfont  # pyright: ignore[reportMissingTypeStubs]
from textual.color import Color

from .hatui_types import (
    Areas,
    Device,
    DeviceClass,
    Devices,
    Entities,
    EntitiesByGroup,
    Entity,
    HomeAssistantWebsocketResponse,
    HomeAssistantWebsocketResponseType,
    Icons,
    State,
    StateAttributes,
    StateClass,
    States,
    SubscribeEntitiesEventEntityDetails,
    UnitOfMeasurement,
)

logger = logging.getLogger(__name__)


def check_response[T](
    data: HomeAssistantWebsocketResponse[T],
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


def get_icon_for_state(
    icons: Icons,
    domain_name: str,
    resource_type: str | None = None,  # pyright: ignore[reportUnusedParameter]
    state: str | None = None,  # pyright: ignore[reportUnusedParameter]
) -> str | None:
    resource_types = icons.get(domain_name)
    if not resource_types:
        return None
    default_resource_type = resource_types.get("_")  # TODO: use actual resource_type
    if not default_resource_type:
        return None
    default_icon = default_resource_type.get("default")  # TODO: use actual state
    return default_icon


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


def get_special_case_icon(entity_id: str):
    """Get icon for entities that are hardcoded in to the frontend."""

    # https://github.com/home-assistant/frontend/blob/4030ce3f889efb62f3bbfc025d5fdfa9509d5cb6/src/common/entity/state_icon.ts#L26
    if entity_id.startswith("input_datetime"):
        return "mdi:clock"  # TODO: calendar
    elif entity_id.startswith("sun"):
        return "mdi:white-balance-sunny"  # TODO: night
    else:
        domain = get_domain_from_entity_id(entity_id)
        return fallback_domain_icons.get(domain)


def get_icon_colour_and_classes(
    state: str | None, attributes: StateAttributes | None
) -> tuple[Color | None, str]:
    """Based on the state and/or attributes, return an appropriate Textual Color and tcss class name to be associated with an icon."""

    if state == "off":
        return None, "icon icon-off"

    if attributes:
        rgb_color = attributes.get("rgb_color")
        if rgb_color and len(rgb_color) >= 3:
            r, g, b = rgb_color
            logger.debug("We got a coloured bulb: %d %d %d", r, g, b)
            return Color(r, g, b), "icon"
    return None, "icon"


def get_nf_icon_for_entity(icons: Icons, entity: Entity) -> str:
    """For a given Entity, return the appropriate nerdfont glyph."""

    entity_id = entity["entity_id"]
    domain_name = get_domain_from_entity_id(entity_id)
    mdi_name = (
        entity.get("icon")
        or get_icon_for_state(icons, domain_name)
        or get_special_case_icon(entity_id)
    )
    if not mdi_name:
        logger.error("Failed to get icon for entity: %s", entity)
        raise Exception("No icon found.", entity)

    nf_name = mdi_nf_mapping.get(mdi_name) or mdi_to_nerd_font_name(mdi_name)

    if not nf_name:
        logger.error("Failed to get nf icon name?", mdi_name)
        raise Exception("Failed to nf icon name")

    nf_glyph = nerdfont.icons.get(nf_name)
    if not nf_glyph:
        logger.error(
            "Failed to get nerdfont icon glyph. mdi_name=%s, nf_name=%s",
            mdi_name,
            nf_name,
        )
        raise Exception("Failed to get icon glyph")

    return nf_glyph


def get_integrations_from_components(components: list[str]) -> set[str]:
    return set(x.split(".", 1)[0] for x in components)


def filter_entities(entities: Entities) -> Entities:
    """Filter out entities from being displayed using the same/similar logic that Lovelace uses."""

    disabled_domains = [
        "stt",
        "tts",
        "event",
        "automation",
        "update",
        "device_tracker",
        "weather",
        "assist_satellite",
        "script",
    ]
    hide_domains = [
        "device_tracker",
        "persistent_notification",
        "todo",
        "assist_satellite",
        "automation",
        "configurator",
        "event",
        "geo_location",
        "notify",
        "script",
        "sun",
        "tag",
        "zone",
        "ai_task",
    ]
    hide_platform = ["backup", "mobile_app"]

    filtered = [
        x
        for x in entities
        if not x.get("hidden_by")
        and not x.get("disabled_by")
        and get_domain_from_entity_id(x["entity_id"])
        not in [*disabled_domains, *hide_domains]
        and not x.get("entity_category") == "diagnostic"
        and not x.get("entity_category") == "config"
        and x.get("platform") not in hide_platform
        and x.get("entity_id")
    ]
    return filtered


def get_device_name_from_device_id(device_id: str, devices: Devices) -> str:
    device = next((x for x in devices if x.get("id") == device_id), None)
    if not device:
        logger.error("Could not find device for device_id %s", device_id)
        raise Exception("Missing device")
    device_name = device["name"]
    if not device_name:
        logger.error("Device has no name: %s", device)
        raise Exception("Device has no name?")
    return device_name


def get_area_name_by_area_id(area_id: str, areas: Areas) -> str:
    area = next((x for x in areas if x.get("area_id") == area_id), None)
    if not area:
        raise Exception("Could not find area?")
    area_name = area.get("name")
    if not area_name:
        raise Exception("Area does not have name?")
    return area_name


def get_entities_for_domain(domain: str, entities: Entities) -> Entities:
    return [x for x in entities if x.get("entity_id").startswith(f"{domain}.")]


def get_entities_in_area(
    area_id: str, entities: Entities, devices: Devices
) -> Entities:
    result: Entities = []
    for entity in entities:
        entity_id = entity.get("entity_id")
        if not entity_id:
            continue
        entity_area_id = get_area_of_entity(entity, devices)
        if entity_area_id == area_id:
            result.append(entity)
    return result


def get_area_of_entity(entity: Entity, devices: Devices) -> str | None:
    """Get area of entity either from the entity itself, or the device it belongs to."""

    if entity.get("area_id"):
        return entity.get("area_id")

    device_id = entity.get("device_id")
    if not device_id:
        return None
    device = next((x for x in devices if x.get("id") == device_id), None)
    if not device:
        return None
    return device.get("area_id")


def get_entities_for_device(device_id: str, entities: Entities) -> Entities:
    result: Entities = []
    for entity in entities:
        if entity.get("device_id") == device_id:
            result.append(entity)
    return result


def split_entities_by_group(
    areas: Areas, devices: Devices, entities: Entities
) -> EntitiesByGroup:
    """Group entities by area, then device, then domain."""

    area_ids: list[str] = [
        x for x in [x.get("area_id") for x in areas] if x is not None
    ]
    areas_with_entities: EntitiesByGroup = {
        k: get_entities_in_area(k, entities, devices) for k in area_ids
    }
    area_names_with_entities: EntitiesByGroup = {
        get_area_name_by_area_id(k, areas): v for k, v in areas_with_entities.items()
    }

    entity_ids_with_area = [
        x
        for x in [
            entity.get("entity_id")
            for group in areas_with_entities
            for entity in areas_with_entities[group]
        ]
    ]
    entities_without_area = [
        x for x in entities if x.get("entity_id") not in entity_ids_with_area
    ]
    device_ids = [x.get("id") for x in devices]
    devices_with_entities: EntitiesByGroup = {
        k: get_entities_for_device(k, entities_without_area) for k in device_ids
    }
    device_names_with_entities: EntitiesByGroup = {
        get_device_name_from_device_id(k, devices): v
        for k, v in devices_with_entities.items()
    }

    entity_ids_with_device = [
        entity.get("entity_id")
        for group in devices_with_entities
        for entity in devices_with_entities[group]
    ]
    other_entity_ids = [
        x.get("entity_id")
        for x in entities_without_area
        if x.get("entity_id") not in entity_ids_with_device
    ]
    domains = set(get_domain_from_entity_id(x) for x in other_entity_ids)
    other_entities: Entities = [
        x for x in entities if x.get("entity_id") in other_entity_ids
    ]
    domains_with_entities = {
        k.replace("_", " ").title(): get_entities_for_domain(k, other_entities)
        for k in domains
    }  # TODO: use translation for domain name

    return {
        k: v
        for k, v in {
            **area_names_with_entities,
            **device_names_with_entities,
            **domains_with_entities,
        }.items()
        if len(v) > 0
    }


async def render_state(
    entity_id: str,
    state_raw: str | None,
    state_class: StateClass,
    device_class: DeviceClass,
    unit_of_measurement: UnitOfMeasurement,
) -> str:
    """Best effort attempt to render raw state values in to the Lovelace equivalent."""

    domain = get_domain_from_entity_id(entity_id)

    if domain in ["input_button", "button"]:
        return "Press"  # buttons don't have state

    if not state_raw:
        return ""

    if state_raw in ["unknown", "unavailable"]:
        return state_raw

    if (
        state_class in ["measurement", "total_increasing"]
        and device_class == "duration"
        and unit_of_measurement == "s"
    ):
        parsed = datetime.timedelta(seconds=float(state_raw))
        humanized = humanize.naturaldelta(value=parsed)
        return humanized

    if device_class in ["timestamp"]:
        parsed = datetime.datetime.fromisoformat(state_raw)
        humanized = humanize.naturaldate(parsed)
        return humanized

    if (state_class in ["measurement", "total_increasing"]) or (
        not device_class
        and not state_class
        and unit_of_measurement  # is this a bug? saw one esphome entity like this
    ):
        try:
            parsed = int(state_raw)
            humanized = humanize.intcomma(parsed, 2)
            return f"{humanized}{str(unit_of_measurement)}"
        except Exception:
            logger.debug(
                'Couldn\'t parse state_value "%s" for entity %s as int, trying float...',
                state_raw,
                entity_id,
            )
            pass

        try:
            parsed = float(state_raw)
            humanized = humanize.intcomma(parsed, 2)
            return f"{humanized}{str(unit_of_measurement)}"
        except Exception:
            logger.warning(
                'Couldn\'t parse state_value "%s" for entity %s as int or float, giving up.',
                state_raw,
                entity_id,
            )
            pass

    if domain in ["light", "switch"] and state_raw == "on":
        return nerdfont.icons["nf-fa-toggle_on"]
    elif domain in ["light", "switch"] and state_raw == "off":
        return nerdfont.icons["nf-fa-toggle_off"]

    return state_raw


async def get_state_classes(
    state_rendered: str,
    state_raw: str | None = None,  # pyright: ignore[reportUnusedParameter]
    old_state_rendered: str | None = None,  # pyright: ignore[reportUnusedParameter]
    old_state_raw: str | None = None,  # pyright: ignore[reportUnusedParameter]
) -> str:
    if state_rendered == "Press":
        return "state state-button"

    if state_rendered in ["unavailable" or "unknown"]:
        return "state state-unavailable"

    if state_rendered in ["off", "closed"]:
        return "state state-off"

    if state_rendered in ["on", "open"]:
        return "state state-on"

    return "state"


def convert_subscribed_event_entity_to_state(
    entity_id: str,
    details: SubscribeEntitiesEventEntityDetails,
) -> State:
    state: State = {
        "entity_id": entity_id,
        "state": details.get("s"),
        "attributes": details.get("a", {}),
        "context": details.get("c", {}),
        "last_changed": str(details.get("lc")),
        "last_reported": None,
        "last_updated": None,
    }
    return state


def get_device_from_entity(entity: Entity, devices: Devices) -> Device | None:
    device = next((d for d in devices if d.get("id") == entity.get("device_id")), None)
    return device


def get_state_from_entity(entity: Entity, states: States) -> State:
    state = next((x for x in states if x.get("entity_id") == entity["entity_id"]))
    if not state:
        raise Exception("Could not get state?", entity)
    return state


def get_entity_from_entity_id(entity_id: str, entities: Entities) -> Entity:
    entity = next((x for x in entities if x.get("entity_id") == entity_id))
    if not entity:
        raise Exception("Could not get entity?", entity_id)
    return entity


# This is kind of useless because there's no way to remove the class afterwards
# def add_class_to_classes(
#     tcss_class: str, tcss_classes: frozenset[str] | str | Iterable[str]
# ) -> str:
#     """Idempotent method of adding a class to a list of classes."""
#     return " ".join(set([*str(tcss_classes).split(" "), tcss_class]))


def prettify_entity_id(entity_id: str, device_name: str | None = None) -> str:
    if device_name:
        logger.debug(
            "Have device name (%s), using in construction of entity (%s) name",
            device_name,
            entity_id,
        )
        entity_id_without_domain = entity_id.split(".", 1)[1]
        device_name_entity_idified = (
            device_name.lower().replace(" ", "_").replace("-", "_")
        )
        if entity_id_without_domain == device_name_entity_idified:
            return device_name
        entity_id_without_device_name = entity_id_without_domain.replace(
            f"{device_name_entity_idified}_", ""
        )
        return entity_id_without_device_name.replace("_", " ").title()
    else:
        return entity_id.split(".", 1)[1].replace("_", " ").title()


def sanitise_for_widget_id(entity_id: str) -> str:
    return (
        entity_id.replace(".", "-")
        .replace(":", "-")
        .replace("/", "-")
        .replace(" ", "-")
        .lower()
    )


# TODO: this isn't exactly correct
def generate_entity_name(entity: Entity, device: Device | None) -> str:
    name = entity.get("name")
    if name:
        return name

    original_name = entity.get("original_name")
    entity_id = entity.get("entity_id")

    if device:
        device_name = device.get("name")
        if original_name and device_name:
            return f"{device_name} {original_name}"
        else:
            return prettify_entity_id(entity_id, device_name)
    else:
        if original_name:
            return original_name
        else:
            return prettify_entity_id(entity_id)
