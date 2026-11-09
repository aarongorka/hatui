import asyncio
import json
import logging
import ssl
from collections.abc import Mapping
from functools import cache
from typing import Any, final, override

import websockets
from textual import work
from textual.app import App, ComposeResult
from textual.reactive import Reactive, reactive
from textual.containers import Vertical
from textual.timer import Timer
from textual.widget import Widget
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
    HomeAssistantWebsocketAuthRequiredResponse,
    HomeAssistantWebsocketAuthResponse,
    HomeAssistantWebsocketCommandResponse,
    HomeAssistantWebsocketEventResponse,
    HomeAssistantWebsocketResponse,
    RequestsExpectingResponseQueue,
    States,
    SubscribeEntitiesEvent,
)

from .camera import CameraSource, CameraWidget, camera_url
from .more_info import ACTIONS, EntityModal, MoreInfo, build_more_info
from .entity_widget import CardGrid, EntityWidget, GroupCard
from .helpers import (
    check_response,
    get_domain_from_entity_id,
)
from .lovelace import (
    Card,
    DisplayEntity,
    friendly_name,
    AreaPrefs,
    generate_cards,
    parse_area_prefs,
    normalise_display_entities,
)
from .present import IconSet, present
from .services import Services
from .states import StateDict, apply_event
from .translate import Translations

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


REGISTRY_EVENTS = (
    "entity_registry_updated",
    "device_registry_updated",
    "area_registry_updated",
)
REFRESH_DEBOUNCE = 2.0


@final
class HomeAssistantDashboard(App):  # pyright: ignore[reportMissingTypeArgument]
    """A Textual TUI for displaying Home Assistant entities."""

    CSS_PATH = "tcss.tcss"

    cards: Reactive[list[Card]] = reactive([], recompose=True)

    def __init__(
        self,
        url: str,
        token: str,
        *args,
        insecure: bool = False,
        show_cameras: bool = True,
        camera_interval: float = 10.0,
        camera_live_interval: float = 1.0,
        **kwargs,
    ):
        self.entities: dict[str, DisplayEntity] = {}
        self.areas: Areas = []
        self.devices: Devices = []
        self.states_by_id: dict[str, StateDict] = {}
        self.config: Config | None = None
        self.icons = IconSet()
        self.translations = Translations()
        self.command_id: int = 1
        self.url = url
        self.token = token
        self.insecure = insecure
        self.show_cameras = show_cameras
        self.camera_interval = camera_interval
        self.camera_live_interval = camera_live_interval
        self.requests_expecting_response_queue: RequestsExpectingResponseQueue = {}
        self.authed = False
        self.area_prefs = AreaPrefs()
        self.entities_subscription_id: int | None = None
        self.registry_timer: Timer | None = None
        self.refresh_lock = asyncio.Lock()
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
        if callback not in (self.handle_entities_update, self.handle_registry_event):
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

    async def load_translations_and_icons(self) -> None:
        """Fetch state/domain translations and icon definitions for what is on screen."""

        language = self.config["language"] if self.config else "en"
        platforms = sorted({e.platform for e in self.entities.values() if e.platform})
        any_response = HomeAssistantWebsocketCommandResponse[Any]
        requests: list[tuple[dict[str, Any], Any]] = [
            (
                {
                    "type": "frontend/get_translations",
                    "language": language,
                    "category": "entity_component",
                },
                any_response,
            ),
            (
                {
                    "type": "frontend/get_translations",
                    "language": language,
                    "category": "entity",
                    "integration": platforms,
                },
                any_response,
            ),
            (
                {"type": "frontend/get_icons", "category": "entity_component"},
                any_response,
            ),
            *[
                (
                    {
                        "type": "frontend/get_icons",
                        "category": "entity",
                        "integration": platform,
                    },
                    any_response,
                )
                for platform in platforms
            ],
        ]
        component_tr, entity_tr, component_icons, *entity_icons = await self.fetch(
            requests
        )
        self.translations = Translations(
            {**component_tr["resources"], **entity_tr["resources"]}
        )
        entity_icon_resources: dict[str, Any] = {}
        for response in entity_icons:
            entity_icon_resources.update(response["resources"])
        self.icons = IconSet(component_icons["resources"], entity_icon_resources)

    async def load_area_prefs(self) -> AreaPrefs:
        """The dashboard's area order and hidden areas; absent unless the user customised them."""

        try:
            (config,) = await self.fetch(
                [
                    (
                        {"type": "lovelace/config"},
                        HomeAssistantWebsocketCommandResponse[dict[str, Any]],
                    )
                ]
            )
        except Exception as error:  # noqa: BLE001
            logger.info(
                "No custom dashboard config (%s); using default ordering.", error
            )
            return AreaPrefs()
        return parse_area_prefs(config)

    async def load_registries(self) -> None:
        """Fetch entities, areas, devices, states and config concurrently."""

        entities, areas, devices, states, config = await self.fetch(
            [
                (
                    {"type": "config/entity_registry/list_for_display"},
                    HomeAssistantWebsocketCommandResponse[dict[str, Any]],
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
        self.entities = {e.entity_id: e for e in normalise_display_entities(entities)}
        self.areas = areas
        self.devices = devices
        self.states_by_id = {s["entity_id"]: dict(s) for s in states}
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
        self.entities_subscription_id = request_id
        logger.info("Subscribed to updates for %d entities.", len(entity_ids))

    async def handle_entities_update(
        self, response: HomeAssistantWebsocketEventResponse[SubscribeEntitiesEvent]
    ):
        if response.get("type") == "result" and response.get("success"):
            logger.info("Got subscription acknowledgement...")
            return None
        else:
            return await self.update_dashboard_with_entity_updates(response["event"])

    async def subscribe_to_registry_updates(self) -> None:
        websocket = await self.get_websocket()
        for event_type in REGISTRY_EVENTS:
            request_id = self.get_and_increment_command_id()
            await websocket.send(
                json.dumps(
                    {
                        "id": request_id,
                        "type": "subscribe_events",
                        "event_type": event_type,
                    }
                )
            )
            self.requests_expecting_response_queue[request_id] = (
                self.handle_registry_event
            )

    async def handle_registry_event(self, response: Any) -> None:
        if response.get("type") != "event":  # pyright: ignore[reportAny]
            return
        logger.info("Registry changed, scheduling a layout refresh.")
        if self.registry_timer:
            self.registry_timer.stop()
        # registry changes arrive in bursts (e.g. a device with many entities)
        self.registry_timer = self.set_timer(REFRESH_DEBOUNCE, self.refresh_layout)

    def build_cards(self) -> list[Card]:
        return generate_cards(
            self.areas,  # pyright: ignore[reportArgumentType]
            self.devices,  # pyright: ignore[reportArgumentType]
            list(self.entities.values()),
            list(self.states_by_id.values()),
            self.translations.domain_name,
            self.show_cameras,
            self.area_prefs,
        )

    async def refresh_layout(self) -> None:
        """Reload registries and states, and rebuild the dashboard if its entities changed."""

        async with self.refresh_lock:
            try:
                entities, areas, devices, states = await asyncio.gather(
                    self.request({"type": "config/entity_registry/list_for_display"}),
                    self.request({"type": "config/area_registry/list"}),
                    self.request({"type": "config/device_registry/list"}),
                    self.request({"type": "get_states"}),
                )
            except Exception as e:
                logger.warning("Layout refresh failed: %s", e)
                return

            self.entities = {
                e.entity_id: e
                for e in normalise_display_entities(entities)  # pyright: ignore[reportAny]
            }
            self.areas = areas  # pyright: ignore[reportAny]
            self.devices = devices  # pyright: ignore[reportAny]
            self.states_by_id = {s["entity_id"]: dict(s) for s in states}  # pyright: ignore[reportAny]

            cards = self.build_cards()
            if not cards or cards == self.cards:
                return

            previous = set(self.entity_widget_ids())
            self.cards = cards
            current = set(self.entity_widget_ids())
            logger.info(
                "Layout refreshed: %d added, %d removed.",
                len(current - previous),
                len(previous - current),
            )
            self.notify(
                f"{len(current - previous)} added, {len(previous - current)} removed.",
                title="󰑓 Layout updated",
            )
            if self.entities_subscription_id is not None:
                self.requests_expecting_response_queue.pop(
                    self.entities_subscription_id, None
                )
                try:
                    await self.request(
                        {
                            "type": "unsubscribe_events",
                            "subscription": self.entities_subscription_id,
                        }
                    )
                except Exception as e:
                    logger.warning("Could not unsubscribe: %s", e)
            await self.subscribe_to_all_entities()

    async def request(self, command: dict[str, Any]) -> Any:
        """Send one command and await its result; safe once the receive worker is running."""

        websocket = await self.get_websocket()
        command_id = self.get_and_increment_command_id()
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()

        async def resolve(response: Any) -> None:  # pyright: ignore[reportAny]
            if response.get("success"):  # pyright: ignore[reportAny]
                future.set_result(response.get("result"))  # pyright: ignore[reportAny]
            else:
                future.set_exception(Exception("Request failed", response))

        self.requests_expecting_response_queue[command_id] = resolve
        await websocket.send(json.dumps({"id": command_id, **command}))
        return await asyncio.wait_for(future, timeout=30)

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        _ = await self.request(
            {
                "type": "call_service",
                "domain": domain,
                "service": service,
                "service_data": data or {},
                "target": {"entity_id": entity_id},
            }
        )

    def present_entity(self, entity_id: str):
        return present(
            self.entities.get(entity_id),
            entity_id,
            self.states_by_id.get(entity_id),
            self.icons,
            self.translations,
        )

    async def update_dashboard_with_entity_updates(self, event: SubscribeEntitiesEvent):
        added, changed = apply_event(self.states_by_id, event)  # pyright: ignore[reportArgumentType]
        if changed or len(added) > 1:
            logger.info(
                "Got updates: %d additions and %d changes.", len(added), len(changed)
            )
        # additions are the initial full dump; animating all of them is expensive and meaningless
        with self.batch_update():
            for entity_id in added | changed:
                widget = self.entity_widgets.get(entity_id)
                if widget:
                    widget.apply(
                        self.present_entity(entity_id),
                        animate=entity_id in changed,
                    )

        screen = self.screen
        if isinstance(screen, EntityModal) and screen.entity_id in added | changed:
            screen.refresh_content()

    async def connect(self) -> None:
        self.websocket = None
        _ = await self.get_websocket()
        await self.auth(self.token)

    async def subscribe_to_all_entities(self) -> None:
        await self.send_subscribe_entities(entity_ids=list(self.entity_widget_ids()))

    def entity_widget_ids(self) -> list[str]:
        return [row.entity_id for card in self.cards for row in card.rows]

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
                await self.subscribe_to_registry_updates()
                self.registry_timer = self.set_timer(
                    REFRESH_DEBOUNCE, self.refresh_layout
                )
                return
            except (OSError, WebSocketException) as e:
                logger.warning("Reconnect failed (%s), retrying in %.1fs...", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max_delay)

    async def wait_for_responses(self) -> Any:
        websocket = await self.get_websocket()
        return json.loads(await websocket.recv())  # pyright: ignore[reportAny]

    @work(exclusive=True)
    async def receive_responses_and_handle(self):
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

        self.entity_widgets = {}
        if not self.cards:
            # compose is sync, so show the loading screen first and load data in `start_up()`
            with Vertical(id="loading"):
                yield Static("󰟐 hatui", id="loading-title")
                yield LoadingIndicator()
                yield Static("Connecting…", id="loading-status")
            return

        group_cards: list[GroupCard] = []
        for card in self.cards:
            rows: list[Widget] = []
            for row in card.rows:
                if get_domain_from_entity_id(row.entity_id) == "camera":
                    rows.append(
                        CameraWidget(
                            CameraSource(
                                row.entity_id,
                                row.name,
                                camera_url(self.url, row.entity_id),
                                self.token,
                                self.get_ssl_context(),
                                self.camera_interval,
                                self.camera_live_interval,
                            )
                        )
                    )
                    continue
                widget = EntityWidget(
                    row.entity_id, row.name, self.present_entity(row.entity_id)
                )
                self.entity_widgets[row.entity_id] = widget
                rows.append(widget)
            group_cards.append(GroupCard(card.title, *rows))
        yield CardGrid(*group_cards)

    def set_loading_status(self, text: str) -> None:
        for status in self.query("#loading-status").results(Static):
            status.update(text)

    async def on_mount(self):
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

        self.set_loading_status("Loading translations and icons…")
        await self.load_translations_and_icons()
        logger.info("Startup sequence got %d icon domains.", len(self.icons.component))

        self.set_loading_status("Building dashboard…")
        await asyncio.sleep(0)
        self.area_prefs = await self.load_area_prefs()
        cards = self.build_cards()
        logger.info("Startup sequence got %d cards.", len(cards))
        if not cards:
            raise Exception("No entities to show...")
        self.cards = cards

        await self.subscribe_to_all_entities()
        await self.subscribe_to_registry_updates()
        _ = self.receive_responses_and_handle()

    async def activate_entity(self, entity_id: str) -> None:
        domain = get_domain_from_entity_id(entity_id)
        service = {"button": "press", "light": "toggle", "switch": "toggle"}.get(domain)
        if service:
            await self.call_service(domain, service, entity_id)

    def get_state(self, entity_id: str) -> Mapping[str, Any]:
        return self.states_by_id.get(entity_id) or {}

    def build_more_info(self, entity_id: str) -> MoreInfo:
        entity = self.entities.get(entity_id)
        state = self.states_by_id.get(entity_id)
        return build_more_info(
            entity,
            entity_id,
            friendly_name(entity_id, state or {}),
            state,
            self.present_entity(entity_id),
            self.translations,
        )

    async def on_entity_widget_clicked(self, message: EntityWidget.Clicked) -> None:
        logger.info("Got message from %s!", message.entity_id)
        if (
            message.quick_action
            and get_domain_from_entity_id(message.entity_id) in ACTIONS
        ):
            return await self.activate_entity(message.entity_id)
        _ = self.push_screen(
            EntityModal(
                message.entity_id,
                self.build_more_info,
                self.activate_entity,
                Services(self.request, self.call_service),
                self.get_state,
            )
        )
