import asyncio
import json
import logging
from typing import final, override

import websockets
from pydantic.type_adapter import TypeAdapter
from textual import work
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.reactive import Reactive, reactive
from textual.widgets import Static
from textual.worker import (
    get_current_worker,  # pyright: ignore[reportUnknownVariableType]
)
from websockets.asyncio.client import ClientConnection

from hatui.hatui_types import (
    Area,
    Areas,
    Config,
    Devices,
    Entities,
    EntitiesByGroup,
    Entity,
    HomeAssistantWebsocketAuthRequiredResponse,
    HomeAssistantWebsocketAuthResponse,
    HomeAssistantWebsocketCommandResponse,
    HomeAssistantWebsocketEventResponse,
    HomeAssistantWebsocketResponse,
    IconQueries,
    Icons,
    IconsResponse,
    RequestsExpectingResponseQueue,
    State,
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
    render_state,
    sanitise_for_widget_id,
    split_entities_by_group,
)

logger = logging.getLogger(__name__)


@final
class HomeAssistantDashboard(App):  # pyright: ignore[reportMissingTypeArgument]
    """A Textual TUI for displaying Home Assistant entities."""

    CSS_PATH = "tcss.tcss"

    entities: Reactive[Entities] = reactive([], recompose=True)
    icons: Reactive[Icons] = reactive({}, recompose=True)
    areas: Reactive[Areas] = reactive([], recompose=True)
    devices: Reactive[Devices] = reactive([], recompose=True)
    states: Reactive[States] = reactive([], recompose=True)
    entities_by_group: Reactive[EntitiesByGroup] = reactive({}, recompose=True)
    config: Reactive[Config | None] = reactive(None, recompose=True)

    def __init__(self, url: str, token: str, *args, **kwargs):
        self.command_id: int = 1
        self.url = url
        self.token = token
        self.requests_expecting_response_queue: RequestsExpectingResponseQueue = []
        self.authed = False
        self.websocket: ClientConnection | None = None
        super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownArgumentType]

    def get_and_increment_command_id(self) -> int:
        command_id = self.command_id
        self.command_id = command_id + 1
        return command_id

    async def get_websocket(self) -> ClientConnection:
        if self.websocket:
            return self.websocket
        websocket = await websockets.connect(self.url)
        self.websocket = websocket
        return websocket

    async def auth(self, token: str) -> None:
        websocket = await self.get_websocket()

        r = await websocket.recv()
        if TypeAdapter:
            auth_required_adapter = TypeAdapter(
                HomeAssistantWebsocketAuthRequiredResponse
            )
            data = auth_required_adapter.validate_python(json.loads(r), strict=True)
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]

        auth = {
            "type": "auth",
            "access_token": token,
        }
        await websocket.send(json.dumps(auth))
        r = await websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketAuthResponse)
            data = adapter.validate_python(json.loads(r), strict=True)
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]
        if not data.get("type") == "auth_ok":
            logger.error("Auth failed", r)
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

        matching_requests = [
            x for x in self.requests_expecting_response_queue if x["id"] == id
        ]
        if len(matching_requests) > 1:
            raise Exception("Too many matching requests?", matching_requests)
        elif len(matching_requests) == 0:
            return None

        matching_request = matching_requests[0]

        callback = matching_request["callback"]

        await callback(response)

        # TODO: logic to clear from queue?
        # self.requests_expecting_response_queue = [
        #     x for x in self.requests_expecting_response_queue if x["id"] != id
        # ]

    async def get_all_icons(self, config: Config) -> Icons:
        """Get icons for domains and all given integrations."""

        try:
            if self.icons:
                return self.icons
        except AttributeError:
            pass

        components = config["components"]
        queries: IconQueries = [
            {"category": "entity_component"},
            *[
                {"category": "entity", "integration": x}
                for x in get_integrations_from_components(components)
            ],
        ]
        icons = await self.get_icons(queries)
        # self.icons = icons
        return icons

    async def get_icons(self, queries: IconQueries) -> Icons:
        """Get icons for a given query."""

        websocket = await self.get_websocket()
        icons: Icons = {}

        for query in queries:
            command = {
                "id": self.get_and_increment_command_id(),
                "type": "frontend/get_icons",
                "category": query["category"],
                "integration": query.get("integration"),
            }
            await websocket.send(json.dumps(command))
            r = await websocket.recv()
            if TypeAdapter:
                adapter = TypeAdapter(
                    HomeAssistantWebsocketCommandResponse[IconsResponse]
                )
                data = adapter.validate_python(json.loads(r), strict=True)
            else:
                data = json.loads(r)  # pyright: ignore[reportAny]
            check_response(data)
            result = data["result"]
            result_icons = result["resources"]
            icons = {**icons, **result_icons}

        return icons

    async def get_config(self) -> Config:
        """Get 'config', namely all the integrations loaded in HA."""

        websocket = await self.get_websocket()

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "get_config",
        }
        await websocket.send(json.dumps(command))
        r = await websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[Config])
            data = adapter.validate_python(json.loads(r), strict=True)
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]
        check_response(data)
        config = data["result"]
        # self.config = config
        return config

    async def get_entities(self) -> list[Entity]:
        try:
            if self.entities:
                return self.entities
        except AttributeError:
            pass
        websocket = await self.get_websocket()

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "config/entity_registry/list",
        }
        await websocket.send(json.dumps(command))
        r = await websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[Entities])
            data = adapter.validate_python(json.loads(r), strict=True)
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]
        check_response(data)
        entities: list[Entity] = data.get("result", [])
        filtered_entities = filter_entities(entities)
        logger.debug("Entities: %s", filtered_entities)
        return filtered_entities

    async def get_states(self) -> list[State]:
        try:
            if self.states:
                return self.states
        except AttributeError:
            pass
        websocket = await self.get_websocket()

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "get_states",
        }
        await websocket.send(json.dumps(command))
        r = await websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[States])
            data = adapter.validate_python(json.loads(r), strict=True)
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]
        check_response(data)
        states = data.get("result")
        logger.debug("States: %s", states)
        # self.states = states
        return states

    async def get_devices(self, websocket: ClientConnection | None = None) -> Devices:
        try:
            if self.devices:
                return self.devices
        except AttributeError:
            pass
        if not websocket:
            if self.websocket:
                websocket = self.websocket
            else:
                raise Exception("Couldn't get websocket")

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "config/device_registry/list",
        }
        await websocket.send(json.dumps(command))
        r = await websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[Devices])
            data = adapter.validate_python(json.loads(r), strict=True)
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]
        check_response(data)
        devices = data["result"]
        # self.devices = devices
        return devices

    async def send_subscribe_entities(self, entity_ids: list[str]) -> None:
        websocket = await self.get_websocket()

        request_id = self.get_and_increment_command_id()
        command = {
            "id": request_id,
            "type": "subscribe_entities",
            "include": {"entities": entity_ids},
        }
        await websocket.send(json.dumps(command))
        self.requests_expecting_response_queue.append(
            {"id": request_id, "callback": self.handle_entities_update}
        )
        logger.info("Subscribed to updates for %d entities.", len(entity_ids))

    async def handle_entities_update(
        self, response: HomeAssistantWebsocketEventResponse[SubscribeEntitiesEvent]
    ):
        if response.get("type") == "result" and response.get("success"):
            logger.info("Got subscrition acknowledgement...")
            return None
        else:
            return await self.update_dashboard_with_entity_updates(response["event"])

    async def get_areas(self) -> list[Area]:
        try:
            if self.areas:
                return self.areas
        except AttributeError:
            pass
        websocket = await self.get_websocket()

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "config/area_registry/list",
        }
        await websocket.send(json.dumps(command))
        r = await websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[Areas])
            data = adapter.validate_python(json.loads(r), strict=True)
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]
        check_response(data)
        areas = data["result"]
        # self.areas = areas
        return areas

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
        self.requests_expecting_response_queue.append(
            {"id": request_id, "callback": self.handle_toggle_light}
        )

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
        self.requests_expecting_response_queue.append(
            {"id": request_id, "callback": self.handle_toggle_switch}
        )

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
        self.requests_expecting_response_queue.append(
            {"id": request_id, "callback": self.handle_button_press}
        )

    async def get_entities_by_group(self) -> EntitiesByGroup:
        # TODO: run each of these concurrently
        # entities = self.get_entities(websocket)
        # areas = self.get_areas(websocket)
        # devices = self.get_devices(websocket)

        # entities_by_group = split_entities_by_group(
        #     *await asyncio.gather(areas, devices, entities)
        # )
        # return entities_by_group

        areas = await self.get_areas()
        devices = await self.get_devices()
        entities = await self.get_entities()
        entities_by_group = split_entities_by_group(areas, devices, entities)
        # self.entities_by_group = entities_by_group
        return entities_by_group

    async def update_dashboard_with_entity_updates(self, event: SubscribeEntitiesEvent):
        entity_additions = event.get("a", {})
        entity_changes = {k: v.get("+") for k, v in event.get("c", {}).items()}
        logger.info(
            "Got updates: %d additions and %d changes.",
            len(entity_additions),
            len(entity_changes),
        )
        entity_updates = entity_changes or entity_additions
        with (
            self.batch_update()
        ):  # TODO: add option to use `with nullcontext()` for debugging
            logger.debug("Pausing paints while we update all entities...")
            for entity_id, details in entity_updates.items():
                wid = f"#{sanitise_for_widget_id(entity_id)}"
                try:
                    entity_widget = self.query_one(wid, EntityWidget)
                    state_widget = entity_widget.query_one("#state", Static)
                except NoMatches:
                    logger.warning(
                        "Couldn't find node %s, may not be initialised yet...", wid
                    )
                    continue
                state_raw = details.get("s")
                if not state_raw:
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
                logger.debug("State class for %s is %s.", entity_id, state_classes)

                logger.debug("Updating entity state: %s", wid)
                entity_widget.state_rendered = state_rendered

                logger.debug("Updating entity classes: %s", wid)
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
                icon = get_nf_icon_for_entity(icons, entity)
                icon_colour, icon_classes = get_icon_colour_and_classes(
                    state_rendered, details.get("a")
                )
                icon_widget = entity_widget.query_one("#icon", Static)

                entity_widget.icon = icon

                icon_widget.classes = icon_classes
                icon_widget.styles.color = icon_colour

                # TODO: fix animation
                # logger.debug("Animating entity: %s", wid)
                # entity_widget.styles.opacity = 0.1
                # entity_widget.styles.animate(
                #     "opacity", value=1.0, duration=2.0
                # )
            logger.debug("Updates finished, unpausing paints.")

    async def wait_for_responses[T](
        self, websocket: ClientConnection | None
    ) -> HomeAssistantWebsocketResponse[T] | None:
        if not websocket:
            if self.websocket:
                websocket = self.websocket
            else:
                raise Exception("Couldn't get websocket")

        try:
            r = await websocket.recv()
        except TimeoutError:
            logger.info("Timed out waiting for responses, returning None...")
            return None
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketResponse[T])
            data = adapter.validate_python(json.loads(r), strict=True)
        else:
            data = json.loads(r)  # pyright: ignore[reportAny]
        logger.debug("Raw response from HA: %s", r)
        return data

    @work(exclusive=True)
    async def receive_responses_and_handle(self):
        await asyncio.sleep(5)
        worker = get_current_worker()  # pyright: ignore[reportUnknownVariableType]
        websocket = self.websocket
        if not websocket:
            raise Exception("Could not get websocket.")
        while worker:
            logger.info("Checking for responses...")
            while response := await self.wait_for_responses(self.websocket):
                await self.handle_response(response)
            logger.info("Finished checking for updates.")
            await asyncio.sleep(5)

    @override
    def compose(self) -> ComposeResult:
        """Compose the TUI"""

        groups = self.entities_by_group

        if not groups:
            # because this is a sync function, we cannot `await self.get_entities_by_group()`
            # therefore we allow Textual to compose this immediately, then run routines to load data in `self.on_mount()`
            return

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
                devices = self.devices
                states = self.states
                if devices:
                    device = get_device_from_entity(entity, devices)
                    # set everything we can on first "paint" to avoid having to wait for a refresh
                    entity_widget.device = device
                    entity_widget.entity_name = generate_entity_name(entity, device)
                    entity_widget.area_name = get_area_of_entity(entity, devices)
                if devices and states:
                    state = get_state_from_entity(entity, states)
                    entity_widget.state = state
                    entity_widget.state_raw = state["state"]
                    entity_widget.device_class = state["attributes"].get("device_class")
                    entity_widget.state_class = state["attributes"].get("state_class")
                    entity_widget.unit_of_measurement = state["attributes"].get(
                        "unit_of_measurement"
                    )
                icons = self.icons
                if icons:
                    entity_widget.icon = get_nf_icon_for_entity(icons, entity)
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

    async def on_mount(self):
        if not self.websocket:
            _ = await self.get_websocket()
            await self.auth(self.token)

        if not self.entities:
            entities = await self.get_entities()
            logger.info("Startup sequence got %d entities.", len(entities))
            self.entities = entities

        if not self.areas:
            areas = await self.get_areas()
            logger.info("Startup sequence got %d areas.", len(areas))
            self.areas = areas

        if not self.devices:
            devices = await self.get_devices()
            logger.info("Startup sequence got %d devices.", len(devices))
            self.devices = devices

        if not self.states:
            states = await self.get_states()
            logger.info("Startup sequence got %d states.", len(states))
            self.states = states

        if not self.config:
            config = await self.get_config()
            logger.info(
                "Startup sequence got config with %d integrations.",
                len(config["components"]),
            )

            if not self.icons:
                icons = await self.get_all_icons(config)
                logger.info("Startup sequence got %d icons.", len(icons))
                self.icons = icons

        if not self.entities_by_group:
            entities_by_group = await self.get_entities_by_group()
            logger.info(
                "Startup sequence got %d entities_by_group.", len(entities_by_group)
            )
            self.entities_by_group = entities_by_group

        if not self.entities:
            raise Exception("No entities yet...")

        _ = await self.send_subscribe_entities(
            entity_ids=[x["entity_id"] for x in self.entities]
        )
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
