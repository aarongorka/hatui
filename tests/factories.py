"""Typed builders for Home Assistant payloads, so tests only spell out what matters."""

from typing import cast

from websockets.asyncio.server import Server

from hatui.hatui_types import Area, Device, State, StateAttributes


def server_port(server: Server) -> int:
    address: object = next(iter(server.sockets)).getsockname()  # pyright: ignore[reportAny]  # socket addresses are typed Any
    return cast("tuple[str, int]", address)[1]


def make_attributes(**attributes: object) -> StateAttributes:
    # tests pass arbitrary attribute names, which a TypedDict cannot express as kwargs
    return cast("StateAttributes", cast("object", attributes))


def make_state(
    entity_id: str = "sensor.x",
    state: str | None = "on",
    name: str | None = None,
    /,
    **attributes: object,
) -> State:
    if name:
        attributes["friendly_name"] = name
    return State(
        entity_id=entity_id,
        state=state,
        attributes=make_attributes(**attributes),
        last_changed=None,
        last_reported=None,
        last_updated=None,
        context=None,
    )


def make_area(area_id: str, name: str) -> Area:
    return Area(
        aliases=None,
        area_id=area_id,
        floor_id=None,
        humidity_entity_id=None,
        icon=None,
        labels=None,
        name=name,
        picture=None,
        temperature_entity_id=None,
        created_at=None,
        modified_at=None,
    )


def make_device(
    id: str,
    name: str,
    area_id: str | None = None,
    name_by_user: str | None = None,
) -> Device:
    return Device(
        area_id=area_id,
        configuration_url=None,
        config_entries=None,
        config_entries_subentries=None,
        connections=None,
        created_at=None,
        disabled_by=None,
        entry_type=None,
        hw_version=None,
        id=id,
        identifiers=None,
        labels=None,
        manufacturer=None,
        model=None,
        model_id=None,
        modified_at=None,
        name_by_user=name_by_user,
        name=name,
        primary_config_entry=None,
        serial_number=None,
        sw_version=None,
        via_device_id=None,
    )
