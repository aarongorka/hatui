from hatui.hatui_types import EntityRegistryDisplay, LovelaceConfig, State
from hatui.lovelace import (
    AreaPrefs,
    Card,
    DisplayEntity,
    generate_cards,
    natural_key,
    normalise_display_entities,
    parse_area_prefs,
)
from hatui.translate import Translations

from .factories import make_area, make_device, make_state


def _state(entity_id: str, name: str | None = None, **attrs: object) -> State:
    return make_state(entity_id, "on", name, **attrs)


def _titles(cards: list[Card]) -> dict[str, list[str]]:
    return {c.title: [r.entity_id for r in c.rows] for c in cards}


def test_normalise_expands_compressed_registry() -> None:
    result: EntityRegistryDisplay = {
        "entity_categories": {"0": "config", "1": "diagnostic"},
        "entities": [
            {"ei": "sensor.a", "pl": "x", "di": "d1", "ec": 1, "hb": True, "dp": 2},
            {"ei": "light.b"},
            {"ei": ""},
        ],
    }

    a, b = normalise_display_entities(result)

    assert (a.entity_category, a.hidden, a.display_precision, a.device_id) == (
        "diagnostic", True, 2, "d1",
    )  # fmt: skip
    assert (b.entity_category, b.hidden) == (None, False)


def test_cards_follow_lovelace_grouping_filtering_and_order() -> None:
    areas = [make_area("kitchen", "Kitchen")]
    devices = [
        make_device("d1", "Lamp", "kitchen"),
        make_device("d2", "Hub", name_by_user="Zed Hub"),
        make_device("d3", "Solo"),
        make_device("d4", "Twin"),
        make_device("d5", "Twin"),
    ]
    entities = [
        DisplayEntity("light.direct", area_id="kitchen"),
        DisplayEntity("light.lamp", device_id="d1"),
        DisplayEntity("sensor.hub_temp", device_id="d2", entity_name="Temp"),
        DisplayEntity("switch.hub_relay", device_id="d2", entity_name="Relay"),
        DisplayEntity("sensor.solo", device_id="d3"),
        DisplayEntity("sensor.twin_a", device_id="d4"),
        DisplayEntity("switch.twin_a", device_id="d4"),
        DisplayEntity("sensor.twin_b", device_id="d5"),
        DisplayEntity("switch.twin_b", device_id="d5"),
        DisplayEntity("sensor.diag", device_id="d2", entity_category="diagnostic"),
        DisplayEntity("sensor.hidden", hidden=True),
        DisplayEntity("sensor.backup", platform="backup"),
        DisplayEntity("input_boolean.flag"),
        DisplayEntity("counter.clicks"),
    ]
    states = [
        _state(e.entity_id, f"{e.entity_id.split('.')[1].title()}")
        for e in entities
        if e.entity_id != "sensor.disabled"
    ] + [
        _state("conversation.home_assistant"),
        _state("automation.x"),
        _state("camera.front"),
        _state("update.firmware"),
        _state("switch.states_only", "Only In States"),
    ]

    cards = generate_cards(areas, devices, entities, states, Translations().domain_name)

    by_title = _titles(cards)
    assert by_title["Kitchen"] == ["light.direct", "light.lamp"]
    assert by_title["Helpers"] == ["counter.clicks", "input_boolean.flag"]
    assert by_title["Sensor"] == ["sensor.solo"]
    assert by_title["Switch"] == ["switch.states_only"]
    assert by_title["Zed Hub"] == ["switch.hub_relay", "sensor.hub_temp"]
    assert [c.title for c in cards] == [
        "Kitchen", "Helpers", "Sensor", "Switch", "Update",
        "Twin", "Twin", "Zed Hub",
    ]  # fmt: skip


def test_duplicate_device_names_keep_all_entities() -> None:
    devices = [
        make_device("d1", "Dyson"),
        make_device("d2", "Dyson"),
    ]
    entities = [
        DisplayEntity("sensor.a1", device_id="d1"),
        DisplayEntity("sensor.a2", device_id="d1"),
        DisplayEntity("sensor.b1", device_id="d2"),
        DisplayEntity("sensor.b2", device_id="d2"),
    ]
    states = [_state(e.entity_id) for e in entities]

    cards = generate_cards([], devices, entities, states, Translations().domain_name)

    assert sorted(len(c.rows) for c in cards) == [2, 2]


def test_device_card_rows_drop_device_name_prefix() -> None:
    devices = [make_device("d1", "Heater")]
    entities = [
        DisplayEntity("sensor.heater_power", device_id="d1"),
        DisplayEntity("switch.heater", device_id="d1"),
    ]
    states = [
        _state("sensor.heater_power", "Heater Power"),
        _state("switch.heater", "Heater"),
    ]

    (card,) = generate_cards([], devices, entities, states, Translations().domain_name)

    assert [r.name for r in card.rows] == ["Heater", "Power"]


def test_natural_key_orders_numbers_and_case_like_the_frontend() -> None:
    names = ["Light 10", "light 2", "Light 1", "Fan"]
    assert sorted(names, key=natural_key) == ["Fan", "Light 1", "light 2", "Light 10"]


def test_order_is_areas_groups_people_domains_devices() -> None:
    areas = [
        make_area("a1", "Attic"),
        make_area("a2", "Bath"),
        make_area("a3", "Cellar"),
    ]
    devices = [make_device("d1", "Hub")]
    entities = [
        DisplayEntity("light.a", area_id="a1"),
        DisplayEntity("light.b", area_id="a2"),
        DisplayEntity("light.c", area_id="a3"),
        DisplayEntity("sensor.h1", device_id="d1"),
        DisplayEntity("sensor.h2", device_id="d1"),
    ]
    states = [_state(e.entity_id) for e in entities] + [
        _state("person.zed", "Zed"),
        _state("fan.f", "Fan"),
        _state("light.grouped", "Grouped"),
        make_state("group.living", "on", "Living", entity_id=["light.grouped"]),
    ]
    prefs = AreaPrefs(order=["a3", "a1"], hidden=["a2"])

    cards = generate_cards(
        areas, devices, entities, states, Translations().domain_name, prefs=prefs
    )

    assert [c.title for c in cards] == ["Cellar", "Attic", "Living", "", "Fan", "Hub"]
    assert [r.entity_id for r in cards[2].rows] == ["light.grouped"]
    assert all("light.grouped" not in [r.entity_id for r in c.rows] for c in cards[3:])


def test_parse_area_prefs() -> None:
    config: LovelaceConfig = {
        "strategy": {
            "type": "original-states",
            "areas": {"order": ["b"], "hidden": ["c"]},
            "hide_entities_without_area": True,
        }
    }
    assert parse_area_prefs(config) == AreaPrefs(["b"], ["c"], True)
    assert parse_area_prefs({"views": [{}]}) == AreaPrefs()
    assert parse_area_prefs(None) == AreaPrefs()
