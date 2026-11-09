"""Group entities in to cards the same way Home Assistant's auto-generated Lovelace dashboard does."""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

HIDE_DOMAINS = frozenset(
    {
        "ai_task",
        "automation",
        "image",
        "configurator",
        "device_tracker",
        "event",
        "geo_location",
        "notify",
        "persistent_notification",
        "script",
        "sun",
        "tag",
        "todo",
        "zone",
        # assist entities
        "assist_satellite",
        "conversation",
        "stt",
        "tts",
    }
)
HIDE_PLATFORMS = frozenset({"backup", "mobile_app"})
HELPER_DOMAINS = frozenset(
    {
        "input_boolean",
        "input_button",
        "input_text",
        "input_number",
        "input_datetime",
        "input_select",
        "counter",
        "timer",
        "schedule",
    }
)
SENSOR_DOMAINS = frozenset(
    {
        "sensor",
        "binary_sensor",
        "calendar",
        "camera",
        "device_tracker",
        "image",
        "weather",
    }
)


@dataclass
class DisplayEntity:
    """The subset of the entity registry that we care about, normalised from `list_for_display`."""

    entity_id: str
    platform: str | None = None
    device_id: str | None = None
    area_id: str | None = None
    translation_key: str | None = None
    entity_category: str | None = None
    entity_name: str | None = None
    display_precision: int | None = None
    icon: str | None = None
    hidden: bool = False


@dataclass
class CardRow:
    entity_id: str
    name: str


@dataclass
class Card:
    title: str
    rows: list[CardRow]


@dataclass
class AreaPrefs:
    """The `areas` options of the dashboard's `original-states` strategy."""

    order: list[str] = field(default_factory=list[str])
    hidden: list[str] = field(default_factory=list[str])
    hide_entities_without_area: bool = False


def parse_area_prefs(config: Mapping[str, Any] | None) -> AreaPrefs:
    """Read the `original-states` strategy options out of a `lovelace/config` result."""

    strategy: Mapping[str, Any] = (config or {}).get("strategy") or {}
    if not strategy:
        views = (config or {}).get("views") or []
        strategy = (views[0].get("strategy") if views else None) or {}
    if strategy.get("type") != "original-states":
        return AreaPrefs()
    areas: Mapping[str, Any] = strategy.get("areas") or {}
    return AreaPrefs(
        list(areas.get("order") or []),
        list(areas.get("hidden") or []),
        bool(strategy.get("hide_entities_without_area")),
    )


type DomainName = Callable[[str], str]


def natural_key(text: str) -> list[tuple[int, int, str]]:
    """Approximates the frontend's numeric, case-insensitive `Intl.Collator` ordering."""

    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part.casefold())
        for part in re.split(r"(\d+)", text)
        if part
    ]


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def normalise_display_entities(result: Mapping[str, Any]) -> list[DisplayEntity]:
    """Expand the compressed `config/entity_registry/list_for_display` response."""

    categories: Mapping[str, str] = result.get("entity_categories", {})
    entities: list[DisplayEntity] = []
    for raw in result.get("entities", []):
        entity_id = raw.get("ei")
        if not entity_id:
            continue
        category = raw.get("ec")
        entities.append(
            DisplayEntity(
                entity_id=entity_id,
                platform=raw.get("pl"),
                device_id=raw.get("di"),
                area_id=raw.get("ai"),
                translation_key=raw.get("tk"),
                entity_category=categories.get(str(category))
                if category is not None
                else None,
                entity_name=raw.get("en"),
                display_precision=raw.get("dp"),
                icon=raw.get("ic"),
                hidden=bool(raw.get("hb")),
            )
        )
    return entities


def prettify_entity_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1].replace("_", " ").title()


def friendly_name(entity_id: str, state: Mapping[str, Any]) -> str:
    name = state.get("attributes", {}).get("friendly_name")
    return str(name) if name else prettify_entity_id(entity_id)


def device_title(device: Mapping[str, Any]) -> str:
    return device.get("name_by_user") or device.get("name") or "Unnamed device"


def name_within_device(
    entity: DisplayEntity | None, state: Mapping[str, Any], device_name: str
) -> str:
    """Name of an entity without its device's name, as shown on a device card."""

    if entity and entity.entity_name:
        return entity.entity_name
    full = friendly_name(state["entity_id"], state)
    prefix = f"{device_name} "
    if full.lower().startswith(prefix.lower()) and len(full) > len(prefix):
        return full[len(prefix) :]
    return full


def is_visible(
    entity: DisplayEntity | None, entity_id: str, show_cameras: bool = False
) -> bool:
    domain = domain_of(entity_id)
    if domain == "camera" and not show_cameras:
        return False
    if domain in HIDE_DOMAINS:
        return False
    if entity is None:
        return True
    return not (
        entity.hidden or entity.entity_category or (entity.platform in HIDE_PLATFORMS)
    )


def _row_sort_key(row: CardRow) -> tuple[bool, list[tuple[int, int, str]]]:
    return (domain_of(row.entity_id) in SENSOR_DOMAINS, natural_key(row.name))


def _rows(
    entity_ids: Iterable[str],
    state_by_id: Mapping[str, Mapping[str, Any]],
    entity_by_id: Mapping[str, DisplayEntity],
    device_name: str | None = None,
) -> list[CardRow]:
    rows: list[CardRow] = []
    for entity_id in entity_ids:
        state = state_by_id[entity_id]
        if device_name:
            name = name_within_device(entity_by_id.get(entity_id), state, device_name)
        else:
            name = friendly_name(entity_id, state)
        rows.append(CardRow(entity_id, name))
    return sorted(rows, key=_row_sort_key)


def generate_cards(
    areas: Sequence[Mapping[str, Any]],
    devices: Sequence[Mapping[str, Any]],
    entities: list[DisplayEntity],
    states: Sequence[Mapping[str, Any]],
    domain_name: DomainName,
    show_cameras: bool = False,
    prefs: AreaPrefs | None = None,
) -> list[Card]:
    """Areas, groups, people, domains, then devices: the order Lovelace generates."""

    prefs = prefs or AreaPrefs()

    state_by_id = {s["entity_id"]: s for s in states}
    entity_by_id = {e.entity_id: e for e in entities}
    device_by_id = {d["id"]: d for d in devices}
    area_ids = {a["area_id"] for a in areas if a.get("area_id")}

    area_buckets: dict[str, list[str]] = {}
    device_buckets: dict[str, list[str]] = {}
    ungrouped: list[str] = []

    # entities without a state are disabled; entities without a registry entry still show
    for entity_id in state_by_id:
        entity = entity_by_id.get(entity_id)
        if not is_visible(entity, entity_id, show_cameras):
            continue
        device = (
            device_by_id.get(entity.device_id) if entity and entity.device_id else None
        )
        area_id = (entity.area_id if entity else None) or (
            device.get("area_id") if device else None
        )
        if area_id is not None and area_id in area_ids:
            area_buckets.setdefault(area_id, []).append(entity_id)
        elif device is not None:
            device_buckets.setdefault(device["id"], []).append(entity_id)
        else:
            ungrouped.append(entity_id)

    # a device with a single entity is just noise as a card of its own
    for device_id in [k for k, v in device_buckets.items() if len(v) == 1]:
        ungrouped.extend(device_buckets.pop(device_id))

    if prefs.hide_entities_without_area:
        device_buckets.clear()
        ungrouped.clear()

    area_position = {area_id: i for i, area_id in enumerate(prefs.order)}
    ordered_areas = sorted(
        (a for a in areas if a.get("area_id") not in prefs.hidden),
        key=lambda a: area_position.get(str(a.get("area_id")), len(area_position)),
    )
    area_cards = [
        Card(a["name"], _rows(area_buckets[a["area_id"]], state_by_id, entity_by_id))
        for a in ordered_areas
        if a.get("area_id") in area_buckets and a.get("name")
    ]

    groups = sorted(
        (e for e in ungrouped if domain_of(e) == "group"),
        key=lambda e: state_by_id[e]["attributes"].get("order") or 0,
    )
    group_cards: list[Card] = []
    grouped: set[str] = set()
    for group_id in groups:
        state = state_by_id[group_id]
        members = [
            m
            for m in state["attributes"].get("entity_id") or []
            if m in state_by_id and is_visible(entity_by_id.get(m), m, show_cameras)
        ]
        grouped.update(state["attributes"].get("entity_id") or [])
        group_cards.append(
            Card(
                friendly_name(group_id, state),
                _rows(members, state_by_id, entity_by_id),
            )
        )
    ungrouped = [e for e in ungrouped if domain_of(e) != "group" and e not in grouped]

    people = [e for e in ungrouped if domain_of(e) == "person"]
    person_cards = (
        [Card("", _rows(people, state_by_id, entity_by_id))] if people else []
    )

    by_domain: dict[str, list[str]] = {}
    for entity_id in ungrouped:
        domain = domain_of(entity_id)
        if domain == "person":
            continue
        key = "helpers" if domain in HELPER_DOMAINS else domain
        by_domain.setdefault(key, []).append(entity_id)
    domain_cards = sorted(
        (
            Card(
                "Helpers" if key == "helpers" else domain_name(key),
                _rows(ids, state_by_id, entity_by_id),
            )
            for key, ids in by_domain.items()
        ),
        key=lambda c: natural_key(c.title),
    )

    device_cards = sorted(
        (
            Card(
                device_title(device_by_id[device_id]),
                _rows(
                    ids,
                    state_by_id,
                    entity_by_id,
                    device_title(device_by_id[device_id]),
                ),
            )
            for device_id, ids in device_buckets.items()
        ),
        key=lambda c: natural_key(c.title),
    )
    return [*area_cards, *group_cards, *person_cards, *domain_cards, *device_cards]
