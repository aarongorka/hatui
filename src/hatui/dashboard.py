import asyncio
import importlib
import json
import logging
import ssl
from collections.abc import Sequence
from functools import cache
from typing import TYPE_CHECKING, cast, final, is_typeddict, override

import websockets
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.reactive import Reactive, reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static
from textual.worker import (
    get_current_worker,  # pyright: ignore[reportUnknownVariableType]
)
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed, WebSocketException

from hatui.hatui_types import (
    Area,
    Command,
    Config,
    Device,
    EntityIcons,
    EntityIconsResponse,
    EntityRegistryDisplay,
    HomeAssistantWebsocketAuthRequiredResponse,
    HomeAssistantWebsocketAuthResponse,
    IconsResponse,
    JsonObject,
    LovelaceConfig,
    RequestsExpectingResponseQueue,
    ServiceData,
    State,
    SubscribeEntitiesEvent,
    TranslationsResponse,
)

from .camera import CameraSource, CameraWidget, camera_url
from .entity_widget import CardGrid, EntityWidget, GroupCard
from .helpers import (
    check_response,
    get_domain_from_entity_id,
    loads,
)
from .lovelace import (
    AreaPrefs,
    Card,
    DisplayEntity,
    friendly_name,
    generate_cards,
    normalise_display_entities,
    parse_area_prefs,
)
from .more_info import ACTIONS, EntityModal, MoreInfo, build_more_info
from .present import IconSet, present
from .services import Services
from .states import apply_event
from .translate import Translations

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pydantic import TypeAdapter


@cache
def has_pydantic() -> bool:
    """Pydantic is optional: it is not loadable on a Pi 1."""

    try:
        _ = importlib.import_module("pydantic")
    except Exception:
        logger.info("Could not import pydantic, running without it...")
        return False
    logger.info("Successfully imported pydantic.")
    return True


@cache
def get_adapter[T](response_type: type[T]) -> "TypeAdapter[T]":
    """Building a TypeAdapter is expensive, so only do it once per type.

    Home Assistant sends many attributes we do not declare; `extra="allow"` keeps them.
    """

    from pydantic import ConfigDict, TypeAdapter

    config = ConfigDict(extra="allow")
    if is_typeddict(response_type):
        # TypeAdapter rejects `config=` for a bare TypedDict; pydantic reads this attribute instead.
        setattr(response_type, "__pydantic_config__", config)  # noqa: B010
        return TypeAdapter(response_type)
    return TypeAdapter(response_type, config=config)


def parse[T](response_type: type[T], data: object, *, strict: bool = False) -> T:
    """Validate `data` as `response_type`, or trust it where pydantic is unavailable."""

    if has_pydantic():
        return get_adapter(response_type).validate_python(data, strict=strict)
    return cast("T", data)


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
        *,
        insecure: bool = False,
        show_cameras: bool = True,
        camera_interval: float = 10.0,
        camera_live_interval: float = 1.0,
    ):
        self.entities: dict[str, DisplayEntity] = {}
        self.areas: list[Area] = []
        self.devices: list[Device] = []
        self.states_by_id: dict[str, State] = {}
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
        super().__init__()

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

        _ = parse(
            HomeAssistantWebsocketAuthRequiredResponse,
            loads(await websocket.recv()),
            strict=True,
        )

        auth = {
            "type": "auth",
            "access_token": token,
        }
        await websocket.send(json.dumps(auth))
        data = parse(
            HomeAssistantWebsocketAuthResponse,
            loads(await websocket.recv()),
            strict=True,
        )
        if data["type"] != "auth_ok":
            logger.error("Auth failed: %s", data)
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

    async def handle_response(self, response: JsonObject) -> None:
        id = response.get("id")
        if not isinstance(id, int) or not id:
            raise Exception("No ID in response?", response)

        callback = self.requests_expecting_response_queue.get(id)
        if not callback:
            return

        # subscriptions keep receiving events under the same id; everything else is one-shot
        if callback not in (self.handle_entities_update, self.handle_registry_event):
            del self.requests_expecting_response_queue[id]

        await callback(response)

    async def fetch_raw(self, commands: Sequence[Command]) -> list[object]:
        """Send all commands up front and collect their results, in request order.

        Only safe before the receive worker starts; afterwards use `request`.
        """

        websocket = await self.get_websocket()
        ids: list[int] = []
        for command in commands:
            command_id = self.get_and_increment_command_id()
            ids.append(command_id)
            await websocket.send(json.dumps({"id": command_id, **command}))

        raw_by_id: dict[int, JsonObject] = {}
        while len(raw_by_id) < len(ids):
            data = loads(await websocket.recv())
            response_id = data.get("id")
            if isinstance(response_id, int) and response_id in ids:
                raw_by_id[response_id] = data

        results: list[object] = []
        for command_id in ids:
            data = raw_by_id[command_id]
            check_response(data)
            results.append(data.get("result"))
        return results

    async def load_translations_and_icons(self) -> None:
        """Fetch state/domain translations and icon definitions for what is on screen."""

        language = self.config["language"] if self.config else "en"
        platforms = sorted({e.platform for e in self.entities.values() if e.platform})
        component_tr, entity_tr, component_icons, *entity_icons = await self.fetch_raw(
            [
                {
                    "type": "frontend/get_translations",
                    "language": language,
                    "category": "entity_component",
                },
                {
                    "type": "frontend/get_translations",
                    "language": language,
                    "category": "entity",
                    "integration": platforms,
                },
                {"type": "frontend/get_icons", "category": "entity_component"},
                *[
                    {
                        "type": "frontend/get_icons",
                        "category": "entity",
                        "integration": platform,
                    }
                    for platform in platforms
                ],
            ]
        )
        self.translations = Translations(
            {
                **parse(TranslationsResponse, component_tr)["resources"],
                **parse(TranslationsResponse, entity_tr)["resources"],
            }
        )
        entity_icon_resources: EntityIcons = {}
        for response in entity_icons:
            entity_icon_resources.update(
                parse(EntityIconsResponse, response)["resources"]
            )
        self.icons = IconSet(
            parse(IconsResponse, component_icons)["resources"], entity_icon_resources
        )

    async def load_area_prefs(self) -> AreaPrefs:
        """The dashboard's area order and hidden areas; absent unless the user customised them."""

        try:
            (config,) = await self.fetch_raw([{"type": "lovelace/config"}])
            return parse_area_prefs(parse(LovelaceConfig, config))
        except Exception as error:  # noqa: BLE001
            logger.info(
                "No custom dashboard config (%s); using default ordering.", error
            )
            return AreaPrefs()

    async def load_registries(self) -> None:
        """Fetch entities, areas, devices, states and config concurrently."""

        entities, areas, devices, states, config = await self.fetch_raw(
            [
                {"type": "config/entity_registry/list_for_display"},
                {"type": "config/area_registry/list"},
                {"type": "config/device_registry/list"},
                {"type": "get_states"},
                {"type": "get_config"},
            ]
        )
        self.entities = {
            e.entity_id: e
            for e in normalise_display_entities(parse(EntityRegistryDisplay, entities))
        }
        self.areas = parse(list[Area], areas, strict=True)
        self.devices = parse(list[Device], devices, strict=True)
        parsed_states = parse(list[State], states, strict=True)
        self.states_by_id = {s["entity_id"]: s for s in parsed_states}
        self.config = parse(Config, config, strict=True)
        logger.info(
            "Startup sequence got %d entities, %d areas, %d devices, %d states.",
            len(self.entities),
            len(self.areas),
            len(self.devices),
            len(self.states_by_id),
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

    async def handle_entities_update(self, response: JsonObject) -> None:
        if response.get("type") == "result" and response.get("success"):
            logger.info("Got subscription acknowledgement...")
            return
        await self.update_dashboard_with_entity_updates(
            parse(SubscribeEntitiesEvent, response.get("event"))
        )

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

    async def handle_registry_event(self, response: JsonObject) -> None:
        if response.get("type") != "event":
            return
        logger.info("Registry changed, scheduling a layout refresh.")
        if self.registry_timer:
            self.registry_timer.stop()
        # registry changes arrive in bursts (e.g. a device with many entities)
        self.registry_timer = self.set_timer(REFRESH_DEBOUNCE, self.refresh_layout)

    def build_cards(self) -> list[Card]:
        return generate_cards(
            self.areas,
            self.devices,
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
                    self.request(
                        {"type": "config/entity_registry/list_for_display"},
                        EntityRegistryDisplay,
                    ),
                    self.request({"type": "config/area_registry/list"}, list[Area]),
                    self.request({"type": "config/device_registry/list"}, list[Device]),
                    self.request({"type": "get_states"}, list[State]),
                )
            except Exception as e:
                logger.warning("Layout refresh failed: %s", e)
                return

            self.entities = {
                e.entity_id: e for e in normalise_display_entities(entities)
            }
            self.areas = areas
            self.devices = devices
            self.states_by_id = {s["entity_id"]: s for s in states}

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
                _ = self.requests_expecting_response_queue.pop(
                    self.entities_subscription_id, None
                )
                try:
                    _ = await self.request(
                        {
                            "type": "unsubscribe_events",
                            "subscription": self.entities_subscription_id,
                        },
                        object,
                    )
                except Exception as e:
                    logger.warning("Could not unsubscribe: %s", e)
            await self.subscribe_to_all_entities()

    async def request[T](self, command: Command, result_type: type[T]) -> T:
        """Send one command and await its result; safe once the receive worker is running."""

        websocket = await self.get_websocket()
        command_id = self.get_and_increment_command_id()
        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()

        async def resolve(response: JsonObject) -> None:
            if response.get("success"):
                future.set_result(response.get("result"))
            else:
                future.set_exception(Exception("Request failed", response))

        self.requests_expecting_response_queue[command_id] = resolve
        await websocket.send(json.dumps({"id": command_id, **command}))
        return parse(result_type, await asyncio.wait_for(future, timeout=30))

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: ServiceData | None = None,
    ) -> None:
        _ = await self.request(
            {
                "type": "call_service",
                "domain": domain,
                "service": service,
                "service_data": data or {},
                "target": {"entity_id": entity_id},
            },
            object,
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
        added, changed = apply_event(self.states_by_id, event)
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

        # Textual types the screen as Screen[object], which can never narrow to a ModalScreen[None]
        screen = cast("object", self.screen)
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

    async def wait_for_responses(self) -> JsonObject:
        websocket = await self.get_websocket()
        return loads(await websocket.recv())

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
        _ = self.call_after_refresh(self.start_up)

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

    def get_state(self, entity_id: str) -> State:
        return self.states_by_id.get(entity_id) or State(
            entity_id=entity_id,
            state=None,
            attributes={},
            last_changed=None,
            last_reported=None,
            last_updated=None,
            context=None,
        )

    def build_more_info(self, entity_id: str) -> MoreInfo:
        entity = self.entities.get(entity_id)
        state = self.states_by_id.get(entity_id)
        return build_more_info(
            entity,
            entity_id,
            friendly_name(entity_id, state),
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
