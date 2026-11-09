import asyncio
import json
import logging
import ssl
from functools import cache
from typing import Any, final, override

import websockets
from textual import work
from textual.app import App, ComposeResult
from textual.reactive import Reactive, reactive
from textual.containers import Vertical
from textual.widgets import LoadingIndicator, Static
from textual.worker import (
    get_current_worker,  # pyright: ignore[reportUnknownVariableType]
)
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed, WebSocketException

from hatui.hatui_types import (
    Areas,
    Config,
    Devices,
    Entities,
    EntitiesByGroup,
    HomeAssistantWebsocketAuthRequiredResponse,
    HomeAssistantWebsocketAuthResponse,
    HomeAssistantWebsocketCommandResponse,
    HomeAssistantWebsocketEventResponse,
    HomeAssistantWebsocketResponse,
    IconQueries,
    Icons,
    IconsResponse,
    RequestsExpectingResponseQueue,
    States,
    SubscribeEntitiesEvent,
)

from .entity_widget import EntityWidget
from .helpers import (
    check_response,
    filter_entities,
    generate_entity_name,
    get_area_of_entity,
    get_device_from_entity,
    get_domain_from_entity_id,
    get_icon_colour_and_classes,
    get_integrations_from_components,
    get_nf_icon_for_entity,
    get_state_classes,
    get_state_from_entity,
    index_devices,
    index_states,
    render_state,
    reverse_easing,
    sanitise_for_widget_id,
    split_entities_by_group,
)

logger = logging.getLogger(__name__)

try:
    from pydantic.type_adapter import (
        TypeAdapter,  # pyright: ignore[reportMissingImports, reportUnknownVariableType]
    )

    logger.info("Successfully imported pydantic.")
except Exception:
    logger.info("Could not import pydantic, running without it...")
    TypeAdapter = None  # ty: ignore[invalid-assignment] # hint to the rest of the code that pydantic isn't loaded


@cache
def get_adapter(response_type: Any) -> Any:
    """Building a TypeAdapter is expensive, so only do it once per type."""

    return TypeAdapter(response_type)  # pyright: ignore[reportOptionalCall]


@final
class HomeAssistantDashboard(App):  # pyright: ignore[reportMissingTypeArgument]
    """A Textual TUI for displaying Home Assistant entities."""

    CSS_PATH = "tcss.tcss"

    entities: Reactive[Entities] = reactive([])
    icons: Reactive[Icons] = reactive({})
    areas: Reactive[Areas] = reactive([])
    devices: Reactive[Devices] = reactive([])
    states: Reactive[States] = reactive([])
    entities_by_group: Reactive[EntitiesByGroup] = reactive({}, recompose=True)
    config: Reactive[Config | None] = reactive(None)

    def __init__(self, url: str, token: str, *args, insecure: bool = False, **kwargs):
        self.command_id: int = 1
        self.url = url
        self.token = token
        self.insecure = insecure
        self.requests_expecting_response_queue: RequestsExpectingResponseQueue = {}
        self.authed = False
        self.entity_widgets: dict[str, EntityWidget] = {}
        self.reconnect_initial_delay = 1.0
        self.reconnect_max_delay = 30.0
        self.websocket: ClientConnection | None = None
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownArgumentType]

    def get_and_increment_command_id(self) -> int:
        command_id = self.command_id
        self.command_id = command_id + 1
        return command_id

    def get_ssl_context(self) -> ssl.SSLContext | None:
        if not self.insecure or not self.url.startswith("wss://"):
            return None
        logger.warning("TLS certificate verification is disabled!")
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    async def get_websocket(self) -> ClientConnection:
        if self.websocket:
            return self.websocket
        # No frame size limit: HA registries/states easily exceed websockets' 1 MiB default.
        # websockets also rejects an explicit `ssl=None` for wss:// URIs, so only pass it when set
        ssl_context = self.get_ssl_context()
        if ssl_context:
            websocket = await websockets.connect(
                self.url, ssl=ssl_context, max_size=None
            )
        else:
            websocket = await websockets.connect(self.url, max_size=None)
        self.websocket = websocket
        return websocket

    async def auth(self, token: str) -> None:
        websocket = await self.get_websocket()

        r = await websocket.recv()
        if TypeAdapter:
            data = get_adapter(
                HomeAssistantWebsocketAuthRequiredResponse
            ).validate_python(json.loads(r), strict=True)
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]

        auth = {
            "type": "auth",
            "access_token": token,
        }
        await websocket.send(json.dumps(auth))
        r = await websocket.recv()
        if TypeAdapter:
            data = get_adapter(HomeAssistantWebsocketAuthResponse).validate_python(
                json.loads(r), strict=True
            )
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]
        if not data.get("type") == "auth_ok":
            logger.error("Auth failed: %s", r)
            raise Exception("Auth failed")

        # TODO: ...maybe
        # features = {
        #     "id": self.get_and_increment_command_id(),
        #     "type": "supported_features",
        #     "features": {"coalesce_messages": 1},
        # }
        # await websocket.send(json.dumps(features))
        # r = await websocket.recv()
        # logger.info("Feature response: %s", r)

        self.authed = True

    async def handle_response[T](
        self, response: HomeAssistantWebsocketResponse[T]
    ) -> None:
        id = response.get("id")
        if not id:
            raise Exception("No ID in response?", response)

        callback = self.requests_expecting_response_queue.get(id)
        if not callback:
            return

        # subscriptions keep receiving events under the same id; everything else is one-shot
        if callback != self.handle_entities_update:
            del self.requests_expecting_response_queue[id]

        await callback(response)

    async def fetch(self, requests: list[tuple[dict[str, Any], Any]]) -> list[Any]:
        """Send all commands up front and collect their (validated) results, in request order."""

        websocket = await self.get_websocket()
        ids: list[int] = []
        for command, _ in requests:
            command_id = self.get_and_increment_command_id()
            ids.append(command_id)
            await websocket.send(json.dumps({"id": command_id, **command}))

        raw_by_id: dict[int, Any] = {}
        while len(raw_by_id) < len(ids):
            data = json.loads(await websocket.recv())  # pyright: ignore[reportAny]
            if data.get("id") in ids:  # pyright: ignore[reportAny]
                raw_by_id[data["id"]] = data  # pyright: ignore[reportAny]

        results: list[Any] = []
        for command_id, (_, response_type) in zip(ids, requests):
            data = raw_by_id[command_id]  # pyright: ignore[reportAny]
            if TypeAdapter:
                data = get_adapter(response_type).validate_python(data, strict=True)
            check_response(data)  # pyright: ignore[reportAny]
            results.append(data["result"])  # pyright: ignore[reportAny]
        return results

    async def get_all_icons(self, config: Config) -> Icons:
        """Get icons for domains and all given integrations."""

        if self.icons:
            return self.icons

        queries: IconQueries = [
            {"category": "entity_component"},
            *[
                {"category": "entity", "integration": x}
                for x in get_integrations_from_components(config["components"])
            ],
        ]
        return await self.get_icons(queries)

    async def get_icons(self, queries: IconQueries) -> Icons:
        """Get icons for a given query."""

        responses: list[IconsResponse] = await self.fetch(
            [
                (
                    {
                        "type": "frontend/get_icons",
                        "category": query["category"],
                        "integration": query.get("integration"),
                    },
                    HomeAssistantWebsocketCommandResponse[IconsResponse],
                )
                for query in queries
            ]
        )
        icons: Icons = {}
        for response in responses:
            icons.update(response["resources"])
        return icons

    async def load_registries(self) -> None:
        """Fetch entities, areas, devices, states and config concurrently."""

        entities, areas, devices, states, config = await self.fetch(
            [
                (
                    {"type": "config/entity_registry/list"},
                    HomeAssistantWebsocketCommandResponse[Entities],
                ),
                (
                    {"type": "config/area_registry/list"},
                    HomeAssistantWebsocketCommandResponse[Areas],
                ),
                (
                    {"type": "config/device_registry/list"},
                    HomeAssistantWebsocketCommandResponse[Devices],
                ),
                (
                    {"type": "get_states"},
                    HomeAssistantWebsocketCommandResponse[States],
                ),
                (
                    {"type": "get_config"},
                    HomeAssistantWebsocketCommandResponse[Config],
                ),
            ]
        )
        self.entities = filter_entities(entities)
        self.areas = areas
        self.devices = devices
        self.states = states
        self.config = config
        logger.info(
            "Startup sequence got %d entities, %d areas, %d devices, %d states.",
            len(self.entities),
            len(areas),
            len(devices),
            len(states),
        )

    async def send_subscribe_entities(self, entity_ids: list[str]) -> None:
        websocket = await self.get_websocket()

        request_id = self.get_and_increment_command_id()
        command = {
            "id": request_id,
            "type": "subscribe_entities",
            "include": {"entities": entity_ids},
        }
        await websocket.send(json.dumps(command))
        self.requests_expecting_response_queue[request_id] = self.handle_entities_update
        logger.info("Subscribed to updates for %d entities.", len(entity_ids))

    async def handle_entities_update(
        self, response: HomeAssistantWebsocketEventResponse[SubscribeEntitiesEvent]
    ):
        if response.get("type") == "result" and response.get("success"):
            logger.info("Got subscription acknowledgement...")
            return None
        else:
            return await self.update_dashboard_with_entity_updates(response["event"])

    async def handle_toggle_light[T](
        self, response: HomeAssistantWebsocketResponse[T]
    ) -> None:
        if (
            response.get("type") == "result"
            and response.get("success")
            and response.get("result")
        ):
            logger.info("Button press successful.")
        else:
            raise Exception("Button press unsuccessful?", response)

    async def send_toggle_light(self, entity_id: str) -> None:
        websocket = await self.get_websocket()

        request_id = self.get_and_increment_command_id()
        domain = get_domain_from_entity_id(entity_id)
        command = {
            "id": request_id,
            "type": "call_service",
            "domain": domain,
            "service": "toggle",
            "service_data": {},
            "target": {
                "entity_id": entity_id,
            },
        }
        await websocket.send(json.dumps(command))
        self.requests_expecting_response_queue[request_id] = self.handle_toggle_light

    async def handle_toggle_switch[T](
        self, response: HomeAssistantWebsocketResponse[T]
    ) -> None:
        if (
            response.get("type") == "result"
            and response.get("success")
            and response.get("result")
        ):
            logger.info("Button press successful.")
        else:
            raise Exception("Button press unsuccessful?", response)

    # TODO: should each service/action function be agnostic of domain if we can infer it from the entity_id?
    async def send_toggle_switch(self, entity_id: str) -> None:
        websocket = await self.get_websocket()

        request_id = self.get_and_increment_command_id()
        domain = get_domain_from_entity_id(entity_id)
        command = {
            "id": request_id,
            "type": "call_service",
            "domain": domain,
            "service": "toggle",
            "service_data": {},
            "target": {
                "entity_id": entity_id,
            },
        }
        await websocket.send(json.dumps(command))
        self.requests_expecting_response_queue[request_id] = self.handle_toggle_switch

    async def handle_button_press[T](
        self, response: HomeAssistantWebsocketResponse[T]
    ) -> None:
        if (
            response.get("type") == "result"
            and response.get("success")
            and response.get("result")
        ):
            logger.info("Button press successful.")
        else:
            raise Exception("Button press unsuccessful?", response)

    async def send_button_press(self, entity_id: str) -> None:
        websocket = await self.get_websocket()

        request_id = self.get_and_increment_command_id()
        domain = get_domain_from_entity_id(entity_id)
        command = {
            "id": request_id,
            "type": "call_service",
            "domain": domain,
            "service": "press",
            "service_data": {},
            "target": {
                "entity_id": entity_id,
            },
        }
        await websocket.send(json.dumps(command))
        self.requests_expecting_response_queue[request_id] = self.handle_button_press

    async def get_entities_by_group(self) -> EntitiesByGroup:
        return split_entities_by_group(self.areas, self.devices, self.entities)

    async def update_dashboard_with_entity_updates(self, event: SubscribeEntitiesEvent):
        entity_additions = event.get("a", {})
        entity_changes = {k: v.get("+") for k, v in event.get("c", {}).items()}
        if len(entity_additions) > 0 or len(entity_changes) > 1:
            logger.info(
                "Got updates: %d additions and %d changes.",
                len(entity_additions),
                len(entity_changes),
            )
        entity_updates = entity_changes or entity_additions
        # additions are the initial full dump; animating all of them is expensive and meaningless
        animate = bool(entity_changes)
        with (
            self.batch_update()
        ):  # TODO: add option to use `with nullcontext()` for debugging
            logger.debug("Pausing paints while we update all entities...")
            for entity_id, details in entity_updates.items():
                wid = f"#{sanitise_for_widget_id(entity_id)}"
                entity_widget = self.entity_widgets.get(entity_id)
                if not entity_widget or not entity_widget.is_mounted:
                    logger.warning(
                        "Couldn't find node %s, may not be initialised yet...", wid
                    )
                    continue
                state_widget = entity_widget.state_widget
                state_raw = details.get("s")
                if not state_raw:
                    logger.info(
                        'No state in change for "%s", can\'t do anything with this.',
                        wid,
                    )
                    continue
                state_rendered = await render_state(
                    entity_widget.entity_id,
                    state_raw,
                    entity_widget.state_class,
                    entity_widget.device_class,
                    entity_widget.unit_of_measurement,
                )

                old_state_raw = entity_widget.state_raw
                old_state_rendered = entity_widget.state_rendered
                state_classes = await get_state_classes(
                    state_rendered, state_raw, old_state_rendered, old_state_raw
                )

                state_changed = state_rendered != entity_widget.state_rendered
                if state_changed:
                    logger.debug(
                        'Updating entity "%s" with state "%s"', wid, state_rendered
                    )
                    entity_widget.state_rendered = state_rendered

                if state_classes != "state" and state_classes != state_widget.classes:
                    logger.info(
                        'Updating entity "%s" with classes "%s"', wid, state_classes
                    )
                state_widget.classes = state_classes

                entity = entity_widget.entity
                if not entity:
                    # raise Exception("Missing entity on widget")
                    logger.debug("Missing entity on a widget: %s", entity_widget)
                    continue

                icons = self.icons
                if not icons:
                    logger.debug("No icons yet...")
                    continue
                    # raise Exception("No icons?")
                resource_type = entity_widget.device_class
                icon = get_nf_icon_for_entity(icons, entity, resource_type, state_raw)
                icon_colour, icon_classes = get_icon_colour_and_classes(
                    state_rendered, details.get("a")
                )
                icon_widget = entity_widget.icon_widget

                icon_changed = icon != entity_widget.icon
                entity_widget.icon = icon

                icon_widget.classes = icon_classes
                icon_widget.styles.color = icon_colour

                if not animate or not (
                    state_changed or icon_changed or details.get("a")
                ):
                    continue

                logger.debug("Animating entity: %s", wid)
                entity_widget.styles.animate(
                    "opacity",
                    value=0.0,
                    duration=2.0,
                    final_value=1.0,
                    easing=reverse_easing,
                )
            logger.debug("Updates finished, unpausing paints.")

    async def wait_for_responses[T](self) -> HomeAssistantWebsocketResponse[T]:
        websocket = await self.get_websocket()
        r = await websocket.recv()
        if TypeAdapter:
            data = get_adapter(HomeAssistantWebsocketResponse).validate_python(
                json.loads(r), strict=True
            )
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]
        logger.debug("Raw response from HA: %s", r)
        return data

    async def connect(self) -> None:
        self.websocket = None
        _ = await self.get_websocket()
        await self.auth(self.token)

    async def subscribe_to_all_entities(self) -> None:
        await self.send_subscribe_entities(
            entity_ids=[x["entity_id"] for x in self.entities]
        )

    async def reconnect(self) -> None:
        """Re-establish the connection and subscription, retrying with exponential backoff."""

        delay = self.reconnect_initial_delay
        while True:
            try:
                if self.websocket:
                    await self.websocket.close()
                self.requests_expecting_response_queue.clear()
                await self.connect()
                await self.subscribe_to_all_entities()
                return
            except (OSError, WebSocketException) as e:
                logger.warning("Reconnect failed (%s), retrying in %.1fs...", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max_delay)

    @work(exclusive=True)
    async def receive_responses_and_handle(self):
        # give the initial recompose time to mount widgets before the first batch of states arrives
        await asyncio.sleep(5)
        worker = get_current_worker()  # pyright: ignore[reportUnknownVariableType]
        while not worker.is_cancelled:
            try:
                while True:
                    await self.handle_response(await self.wait_for_responses())
            except ConnectionClosed:
                logger.warning("Connection to Home Assistant lost, reconnecting...")
                self.notify(
                    "Connection lost, reconnecting...",
                    title=" Home Assistant",
                    severity="warning",
                )
                await self.reconnect()
                logger.info("Reconnected.")
                self.notify("Reconnected.", title="󰄬 Home Assistant")

    async def on_unmount(self) -> None:
        if self.websocket:
            await self.websocket.close()

    @override
    def compose(self) -> ComposeResult:
        """Compose the TUI"""

        groups = self.entities_by_group

        if not groups:
            # because this is a sync function, we cannot `await self.get_entities_by_group()`
            # therefore we allow Textual to compose this immediately, then run routines to load data in `self.on_mount()`
            with Vertical(id="loading"):
                yield Static("󰟐 hatui", id="loading-title")
                yield LoadingIndicator()
                yield Static("Connecting…", id="loading-status")
            return

        devices = self.devices
        states = self.states
        icons = self.icons
        devices_by_id = index_devices(devices) if devices else {}
        states_by_entity_id = index_states(states) if states else {}

        self.entity_widgets = {}

        for group in groups:
            # with Vertical(id=f"group-{sanitise(group)}", classes="group"): # TODO: if Textual ever gets reactive layouts...
            yield Static(
                group, id=f"title-{sanitise_for_widget_id(group)}", classes="title"
            )
            for entity in groups[group]:
                entity_widget = EntityWidget(
                    entity_id=entity["entity_id"],
                    id=sanitise_for_widget_id(entity["entity_id"]),
                )
                entity_widget.entity = entity
                if devices:
                    device = get_device_from_entity(entity, devices_by_id)
                    # set everything we can on first "paint" to avoid having to wait for a refresh
                    entity_widget.device = device
                    entity_widget.entity_name = generate_entity_name(entity, device)
                    entity_widget.area_name = get_area_of_entity(entity, devices_by_id)
                if devices and states:
                    state = get_state_from_entity(entity, states_by_entity_id)
                    entity_widget.state = state
                    entity_widget.state_raw = state["state"]
                    entity_widget.device_class = state["attributes"].get("device_class")
                    entity_widget.state_class = state["attributes"].get("state_class")
                    entity_widget.unit_of_measurement = state["attributes"].get(
                        "unit_of_measurement"
                    )
                if icons:
                    entity_widget.icon = get_nf_icon_for_entity(icons, entity)
                self.entity_widgets[entity["entity_id"]] = entity_widget
                yield entity_widget

    # TODO: should we technically have this?
    # async def watch_entities(self, entities: Entities):
    #     logger.info(
    #         "Entity store updated, updating %d children widgets...", len(entities)
    #     )
    #     entity_widgets = self.query(EntityWidget)
    #     logger.info("Queried %d children.", len(entity_widgets))
    #     for entity_widget in entity_widgets:
    #         wid = entity_widget.id
    #         entity = next(
    #             (x for x in entities if sanitise_for_widget_id(x["entity_id"]) == wid)
    #         )
    #         if entity:
    #             logger.warning("Adding entity to child")
    #             entity_widget.entity = entity
    #             # self.mutate_reactive(EntityWidget.entity)

    async def watch_icons(self, icons: Icons):
        if not icons:
            logger.info("Icons updated but not actually")
            return
        entity_widgets = self.query(EntityWidget)
        logger.info("Queried %d entity widgets for icon update.", len(entity_widgets))
        for entity_widget in entity_widgets:
            if entity_widget.entity:
                entity_widget.icon = get_nf_icon_for_entity(icons, entity_widget.entity)

    def set_loading_status(self, text: str) -> None:
        for status in self.query("#loading-status").results(Static):
            status.update(text)

    async def on_mount(self):
        self.screen.add_class("booting")
        # let the loading screen paint before any blocking network or parsing work
        self.call_after_refresh(self.start_up)

    async def start_up(self):
        if not self.websocket:
            self.set_loading_status("Connecting…")
            _ = await self.get_websocket()
            await self.auth(self.token)

        if not self.entities:
            self.set_loading_status("Loading entities, devices and states…")
            await self.load_registries()

        config = self.config
        if config and not self.icons:
            self.set_loading_status("Loading icons…")
            self.icons = await self.get_all_icons(config)
            logger.info("Startup sequence got %d icons.", len(self.icons))

        if not self.entities_by_group:
            self.set_loading_status("Building dashboard…")
            await asyncio.sleep(0)
            entities_by_group = await self.get_entities_by_group()
            logger.info(
                "Startup sequence got %d entities_by_group.", len(entities_by_group)
            )
            self.entities_by_group = entities_by_group
        self.screen.remove_class("booting")

        if not self.entities:
            raise Exception("No entities yet...")

        await self.subscribe_to_all_entities()
        _ = self.receive_responses_and_handle()

    async def on_entity_widget_clicked(self, message: EntityWidget.Clicked) -> None:
        logger.info("Got message from %s!", message.entity_id)
        entity_id = message.entity_id
        domain = get_domain_from_entity_id(entity_id)
        if domain == "button":
            return await self.send_button_press(entity_id)
        if domain == "light":
            return await self.send_toggle_light(entity_id)
        if domain == "switch":
            return await self.send_toggle_switch(entity_id)
