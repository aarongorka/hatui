from typing import Any

from hatui.lovelace import DisplayEntity
from hatui.present import IconSet, present, resolve_icon_name, state_colour
from hatui.states import apply_event
from hatui.translate import Translations
import nerdfont  # pyright: ignore[reportMissingTypeStubs]


def _state(state: str, **attrs: Any) -> dict[str, Any]:
    return {"state": state, "attributes": attrs}


def test_number_formatting_uses_precision_unit_and_never_prints_none() -> None:
    tr = Translations()
    entity = DisplayEntity("sensor.t", display_precision=1)

    temp = present(
        entity, "sensor.t", _state("21.456", unit_of_measurement="°C"), IconSet(), tr
    )
    humidity = present(
        None, "sensor.h", _state("45", unit_of_measurement="%"), IconSet(), tr
    )
    power = present(
        None, "sensor.p", _state("1234.5", unit_of_measurement="W"), IconSet(), tr
    )
    plain = present(None, "sensor.n", _state("5"), IconSet(), tr)

    assert temp.state_text == "21.5°C"
    assert humidity.state_text == "45%"
    assert power.state_text == "1,234.5 W"
    assert plain.state_text == "5"


def test_state_text_translation_order_and_builtins() -> None:
    tr = Translations(
        {
            "component.binary_sensor.entity_component.motion.state.on": "Detected",
            "component.binary_sensor.entity_component._.state.on": "On",
            "component.demo.entity.sensor.mode.state.eco": "Eco!",
        }
    )
    motion = present(
        None, "binary_sensor.m", _state("on", device_class="motion"), IconSet(), tr
    )
    generic = present(None, "binary_sensor.g", _state("on"), IconSet(), tr)
    entity = DisplayEntity("sensor.s", platform="demo", translation_key="mode")
    eco = present(entity, "sensor.s", _state("eco", device_class="enum"), IconSet(), tr)
    gone = present(None, "sensor.x", _state("unavailable"), IconSet(), tr)

    assert (motion.state_text, generic.state_text) == ("Detected", "On")
    assert eco.state_text == "Eco!"
    assert gone.state_text == "Unavailable"
    assert gone.state_classes == "state state-unavailable"


def test_toggle_domains_show_glyph_and_buttons_show_press() -> None:
    tr = Translations()

    light = present(None, "light.a", _state("on"), IconSet(), tr)
    button = present(None, "button.b", _state("2024-01-01T00:00:00"), IconSet(), tr)

    assert light.state_text == nerdfont.icons["nf-fa-toggle_on"]
    assert button.state_text == "Press"


def test_icon_resolution_order_and_never_raises() -> None:
    icons = IconSet(
        component={"sensor": {"temperature": {"default": "mdi:thermometer"}}},
        entity={
            "demo": {
                "sensor": {
                    "mode": {"default": "mdi:leaf", "state": {"eco": "mdi:flower"}}
                }
            }
        },
    )
    entity = DisplayEntity("sensor.s", platform="demo", translation_key="mode")

    assert (
        resolve_icon_name(None, "sensor.s", "1", {"icon": "mdi:custom"}, icons)
        == "mdi:custom"
    )
    assert (
        resolve_icon_name(
            DisplayEntity("sensor.s", icon="mdi:reg"),
            "sensor.s",
            "1",
            {"icon": "mdi:custom"},
            icons,
        )
        == "mdi:reg"
    )
    assert resolve_icon_name(entity, "sensor.s", "eco", {}, icons) == "mdi:flower"
    assert (
        resolve_icon_name(None, "sensor.t", "1", {"device_class": "temperature"}, icons)
        == "mdi:thermometer"
    )
    assert (
        resolve_icon_name(None, "weird.thing", "1", {}, icons)
        == "mdi:help-circle-outline"
    )

    unknown = present(
        None, "sensor.q", _state("1", icon="mdi:not-a-real-icon"), icons, Translations()
    )
    assert unknown.icon == nerdfont.icons["nf-md-help_circle_outline"]


def test_colours_follow_lovelace_rules() -> None:
    assert state_colour("switch.a", "on", {}) == "#ffc107"
    assert state_colour("switch.a", "off", {}) == "#9e9e9e"
    assert state_colour("switch.a", "unavailable", {}) == "#bdbdbd"
    assert state_colour("lock.a", "locked", {}) == "#4caf50"
    assert state_colour("lock.a", "unlocked", {}) == "#f44336"
    assert state_colour("binary_sensor.a", "on", {"device_class": "smoke"}) == "#f44336"
    assert (
        state_colour("binary_sensor.a", "on", {"device_class": "motion"}) == "#ffc107"
    )
    assert state_colour("climate.a", "heat", {}) == "#ff6f22"
    assert state_colour("sensor.a", "1", {}) is None
    assert state_colour("sensor.b", "80", {"device_class": "battery"}) == "#4caf50"
    assert state_colour("sensor.b", "10", {"device_class": "battery"}) == "#f44336"
    assert (
        state_colour("light.a", "on", {"rgb_color": [255, 0, 0], "brightness": 255})
        == "#ff0000"
    )
    assert state_colour("light.a", "on", {"brightness": 5}) != "#ffc107"


def test_apply_event_merges_diffs_and_removals() -> None:
    store: dict[str, Any] = {}
    _ = apply_event(
        store,
        {
            "a": {
                "light.a": {"s": "on", "a": {"rgb_color": [1, 2, 3], "brightness": 9}},
                "light.b": {"s": "on"},
            }
        },
    )

    added, changed = apply_event(
        store,
        {
            "c": {
                "light.a": {
                    "+": {"s": "off", "a": {"brightness": 4}},
                    "-": {"a": ["rgb_color"]},
                }
            },
            "r": ["light.b"],
        },
    )

    assert (added, changed) == (set(), {"light.a"})
    assert store["light.a"]["state"] == "off"
    assert store["light.a"]["attributes"] == {"brightness": 4}
    assert "light.b" not in store
