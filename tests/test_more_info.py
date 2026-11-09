import datetime

from hatui.lovelace import DisplayEntity
from hatui.more_info import build_more_info
from hatui.present import present
from hatui.present import IconSet
from hatui.translate import Translations

NOW = datetime.datetime(2026, 1, 1, 12, 0, 0)


def _info(entity_id: str, state: str, **extra: object):
    st = {
        "state": state,
        "attributes": {
            "friendly_name": "X",
            "icon": "mdi:x",
            "brightness": 10,
            **extra,
        },
        "last_changed": NOW.timestamp() - 3600,
        "last_updated": "2026-01-01T11:59:00",
    }
    tr = Translations()
    entity = DisplayEntity(entity_id)
    return build_more_info(
        entity,
        entity_id,
        "X",
        st,
        present(entity, entity_id, st, IconSet(), tr),
        tr,
        NOW,
    )


def test_toggle_shows_text_state_action_and_details() -> None:
    info = _info("light.a", "on")

    assert info.state_text == "on"
    assert info.action == "Toggle"
    rows = dict(info.rows)
    assert info.entity_id == "light.a"
    assert info.changed == "an hour ago"
    assert info.updated == "a minute ago"
    assert "Last changed" not in rows
    assert rows["Brightness"] == "10"
    assert "Friendly name" not in rows and "Icon" not in rows


def test_read_only_entities_have_no_action_and_keep_formatted_state() -> None:
    info = _info("sensor.t", "21.4", unit_of_measurement="°C", tags=["a", "b"])

    assert info.action is None
    assert info.state_text == "21.4°C"
    assert dict(info.rows)["Tags"] == '["a","b"]'
