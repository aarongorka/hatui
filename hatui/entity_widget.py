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
            yield Static(id="icon", classes="icon")
            yield Static(id="name", classes="name")
            yield Static(id="state", classes="state")

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
        """Magic Textual function that fires whenever self.icon changes."""
        self.query_one("#icon", Static).update(icon)

    async def watch_entity_name(self, entity_name: str) -> None:
        """Magic Textual function that fires whenever self.entity_name changes."""
        self.query_one("#name", Static).update(entity_name)

    async def watch_state_rendered(self, state_rendered: str) -> None:
        """Magic Textual function that fires whenever self.state_rendered changes."""
        self.query_one("#state", Static).update(state_rendered)
