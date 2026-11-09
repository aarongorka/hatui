from typing import Any, cast

from hatui.helpers import split_entities_by_group
from hatui.hatui_types import Areas, Devices, Entities


def _entity(entity_id: str, **kwargs: Any) -> dict[str, Any]:
    return {"entity_id": entity_id, "area_id": None, "device_id": None, **kwargs}


def test_split_entities_by_group() -> None:
    areas = cast(Areas, [{"area_id": "kitchen", "name": "Kitchen"}])
    devices = cast(
        Devices,
        [
            {"id": "d1", "name": "Lamp", "area_id": "kitchen"},
            {"id": "d2", "name": "Hub", "area_id": None},
            {"id": "d3", "name": "Empty", "area_id": None},
        ],
    )
    entities = cast(
        Entities,
        [
            _entity("light.direct", area_id="kitchen"),
            _entity("light.lamp", device_id="d1"),
            _entity("sensor.hub_temp", device_id="d2"),
            _entity("sensor.orphan"),
            _entity("switch.orphan", device_id="unknown"),
            _entity("sensor.orphan2", area_id="unknown_area"),
        ],
    )

    result = split_entities_by_group(areas, devices, entities)

    assert {k: [e["entity_id"] for e in v] for k, v in result.items()} == {
        "Kitchen": ["light.direct", "light.lamp"],
        "Hub": ["sensor.hub_temp"],
        "Sensor": ["sensor.orphan", "sensor.orphan2"],
        "Switch": ["switch.orphan"],
    }
