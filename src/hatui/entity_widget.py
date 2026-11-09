import logging
from typing import final, override

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

from hatui.hatui_types import (
    Device,
    DeviceClass,
    Entity,
    State,
    StateClass,
    UnitOfMeasurement,
)

from .helpers import (
    generate_entity_name,
)

logger = logging.getLogger(__name__)


@final
class EntityWidget(Horizontal):
    icon = reactive("")
    entity_name = reactive("")
    state_rendered = reactive("")

    def __init__(
        self,
        entity_id: str,
        *args,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        **kwargs,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    ) -> None:
        self.entity_id = entity_id

        self.entity: Entity | None = None
        self.device: Device | None = None
        self.state: State | None = None
        self.area_name: str | None = None
        self.state_raw: str | None = None
        self.device_class: DeviceClass | None = None
        self.state_class: StateClass | None = None
        self.unit_of_measurement: UnitOfMeasurement | None = None
        self.icon_widget = Static(id="icon", classes="icon")
        self.name_widget = Static(id="name", classes="name")
        self.state_widget = Static(id="state", classes="state")
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownArgumentType]

    @final
    class Clicked(Message):
        def __init__(self, entity_id: str):
            self.entity_id = entity_id
            super().__init__()

    async def on_click(self) -> None:
        logger.info("Entity %s got clicked!", self.entity_id)

        parent = self.parent
        if parent:
            _ = parent.post_message(self.Clicked(self.entity_id))
        else:
            raise Exception("Couldn't get parent?")

    @override
    def compose(self) -> ComposeResult:
        with Horizontal(id="entity-horizontal", classes="entity-horizontal"):
            yield self.icon_widget
            yield self.name_widget
            yield self.state_widget

    # Magic Textual `watch_` functions that fire whenever their respective class attribute changes
    async def watch_entity(self, entity: Entity | None):
        if entity:
            device = self.device
            if device:
                self.entity_name = generate_entity_name(entity, device)

    async def watch_device(self, device: Device | None):
        if device:
            entity = self.entity
            if entity:
                self.entity_name = generate_entity_name(entity, device)

    async def watch_icon(self, icon: str) -> None:
        self.icon_widget.update(icon)

    async def watch_entity_name(self, entity_name: str) -> None:
        self.name_widget.update(entity_name)

    async def watch_state_rendered(self, state_rendered: str) -> None:
        self.state_widget.update(state_rendered)
