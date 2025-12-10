import asyncio
import logging
from typing import final, override

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static
from textual.worker import (
    get_current_worker,  # pyright: ignore[reportUnknownVariableType]
)

from .entities import HomeAssistant
from .hatui_types import (
    Device,
    Entity,
)
from .helpers import (
    get_area_of_entity,
    get_device_from_entity,
    get_entity_from_entity_id,
    get_icon_colour_and_classes,
    get_nf_icon_for_entity,
    get_state_classes,
    get_state_from_entity,
    render_state,
)

logger = logging.getLogger(__name__)


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


def sanitise_for_widget_id(sensor_id: str) -> str:
    return (
        sensor_id.replace(".", "-")
        .replace(":", "-")
        .replace("/", "-")
        .replace(" ", "-")
        .lower()
    )


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


@final
class EntityWidget(Horizontal):
    icon = reactive("")
    state_rendered = reactive("")

    def __init__(
        self,
        entity_id: str,
        hass: HomeAssistant,
        **kwargs,  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
    ) -> None:
        self.entity_id = entity_id
        self.entity = get_entity_from_entity_id(entity_id, hass.entities)
        self.device = get_device_from_entity(self.entity, hass.devices)
        self.state = get_state_from_entity(self.entity, hass.states)
        self.entity_name = generate_entity_name(self.entity, self.device)
        self.area_name = get_area_of_entity(self.entity, hass.devices)
        self.state_raw = self.state["state"]
        self.device_class = self.state["attributes"].get("device_class")
        self.state_class = self.state["attributes"].get("state_class")
        self.unit_of_measurement: str = self.state["attributes"].get(
            "unit_of_measurement", ""
        )
        self.hass = hass
        super().__init__(**kwargs)  # pyright: ignore[reportUnknownArgumentType]

    def on_click(self) -> None:
        logger.info("Entity %s got clicked!", self.entity_id)
        # self.hass.press_button(self.entity_id)

    @override
    def compose(self) -> ComposeResult:
        with Horizontal(id="entity-horizontal", classes="entity-horizontal"):
            yield Static(id="icon", classes="icon")
            yield Static(self.entity_name, id="name", classes="name")
            yield Static(
                id="state",
                classes="state",
            )

    def watch_icon(self, icon: str) -> None:
        """Magic Textual function that fires whenever self.icon changes."""
        self.query_one("#icon", Static).update(icon)

    def watch_state_rendered(self, state_rendered: str) -> None:
        """Magic Textual function that fires whenever self.state_rendered changes."""
        self.query_one("#state", Static).update(state_rendered)


@final
class HomeAssistantDashboard(App):  # pyright: ignore[reportMissingTypeArgument]
    """A Textual TUI for displaying Home Assistant entities."""

    CSS_PATH = "tcss.tcss"

    def __init__(self, url: str, token: str, **kwargs):  # pyright: ignore[reportUnknownParameterType, reportMissingParameterType]
        super().__init__(**kwargs)  # pyright: ignore[reportUnknownArgumentType]
        self.hass = HomeAssistant(url, token)

    @work()
    async def _subscribe_state_worker(self, entity_ids: list[str]):
        await asyncio.sleep(
            10
        )  # hack to wait for initialisation, TODO: fix with actual progress bar
        worker = get_current_worker()  # pyright: ignore[reportUnknownVariableType]
        self.hass.subscribe_entities(self.hass.websocket, entity_ids)
        while worker:
            logger.info("Checking for new updates...")
            while subscribe_response := self.hass.wait_for_entities_update(
                self.hass.websocket
            ):
                entity_additions = subscribe_response.get("a", {})
                entity_changes = {
                    k: v.get("+") for k, v in subscribe_response.get("c", {}).items()
                }
                logger.info(
                    "Got updates: %d additions and %d changes.",
                    len(entity_additions),
                    len(entity_changes),
                )
                entity_updates = entity_changes or entity_additions
                with self.batch_update():
                    logger.debug("Pausing paints while we update all entities...")
                    # with nullcontext():
                    for entity_id, details in entity_updates.items():
                        wid = f"#{sanitise_for_widget_id(entity_id)}"
                        entity_widget = self.query_one(wid, EntityWidget)
                        state_widget = entity_widget.query_one("#state", Static)
                        # new_state = convert_subscribed_event_entity_to_state(
                        #     entity_id, details
                        # )
                        state_raw = details.get("s")
                        if not state_raw:
                            continue
                        state_rendered = render_state(
                            entity_widget.entity_id,
                            state_raw,
                            entity_widget.state_class,
                            entity_widget.device_class,
                            entity_widget.unit_of_measurement,
                        )
                        old_state_raw = entity_widget.state_raw
                        old_state_rendered = entity_widget.state_rendered
                        state_classes = get_state_classes(
                            state_rendered, state_raw, old_state_rendered, old_state_raw
                        )
                        logger.debug(
                            "State class for %s is %s.", entity_id, state_classes
                        )

                        icon = get_nf_icon_for_entity(
                            self.hass.icons, entity_widget.entity
                        )
                        icon_colour, icon_classes = get_icon_colour_and_classes(
                            state_rendered, details.get("a")
                        )
                        icon_widget = entity_widget.query_one("#icon", Static)
                        if not worker.is_cancelled:
                            # self.call_from_thread(widget.update, state_rendered)
                            logger.debug("Updating entity state: %s", wid)
                            # state_widget.update(state_rendered)

                            entity_widget.state_rendered = state_rendered
                            entity_widget.icon = icon

                            logger.debug("Updating entity classes: %s", wid)
                            state_widget.classes = state_classes

                            icon_widget.classes = icon_classes
                            icon_widget.styles.color = icon_colour

                            logger.debug("Animating entity: %s", wid)
                            entity_widget.styles.opacity = 0.1
                            entity_widget.styles.animate(
                                "opacity", value=1.0, duration=2.0
                            )
                    logger.debug("Updates finished, unpausing paints.")
            logger.debug("Finished entity state updates, sleeping for 5s...")
            await asyncio.sleep(5)

    @override
    def compose(self) -> ComposeResult:
        """Compose the TUI"""

        groups = self.hass.entities_by_group
        entities = self.hass.entities
        # states = self.hass.states
        # devices = self.hass.devices

        for group in groups:
            # with Vertical(id=f"group-{sanitise(group)}", classes="group"):
            yield Static(
                group, id=f"title-{sanitise_for_widget_id(group)}", classes="title"
            )
            for entity in groups[group]:
                yield EntityWidget(
                    entity_id=entity["entity_id"],
                    hass=self.hass,
                    id=sanitise_for_widget_id(entity["entity_id"]),
                )

        _ = self._subscribe_state_worker(entity_ids=[x["entity_id"] for x in entities])
