from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Literal, NotRequired, Protocol, TypedDict

# Covariant containers so that e.g. a `list[str]` is a valid `JsonValue`.
type JsonValue = (
    str | int | float | bool | None | Sequence[JsonValue] | Mapping[str, JsonValue]
)
type JsonObject = Mapping[str, JsonValue]
type Command = JsonObject
type ServiceData = JsonObject

type HomeAssistantWebsocketResponseType = Literal["result", "event"]


class HomeAssistantWebsocketAuthRequiredResponse(TypedDict):
    type: str
    ha_version: str


class HomeAssistantWebsocketError(TypedDict):
    code: str
    message: str


class HomeAssistantWebsocketAuthResponse(TypedDict):
    type: str
    ha_version: NotRequired[str]
    message: NotRequired[str]
    error: NotRequired[HomeAssistantWebsocketError]


class HomeAssistantWebsocketCommandResponse[T](TypedDict):
    id: int
    type: str
    success: bool
    result: T
    error: NotRequired[HomeAssistantWebsocketError]


class HomeAssistantWebsocketSubscribeResponse(TypedDict):
    id: int
    type: str
    success: bool
    result: None
    error: NotRequired[HomeAssistantWebsocketError]


class HomeAssistantWebsocketEventResponse[T](TypedDict):
    id: int
    type: str
    event: T
    error: NotRequired[HomeAssistantWebsocketError]


type HomeAssistantWebsocketResponse[T] = (
    HomeAssistantWebsocketAuthRequiredResponse
    | HomeAssistantWebsocketCommandResponse[T]
    | HomeAssistantWebsocketAuthResponse
    | HomeAssistantWebsocketEventResponse[T]
    | HomeAssistantWebsocketSubscribeResponse
)


type ResponseCallback = Callable[[JsonObject], Awaitable[None]]
type RequestsExpectingResponseQueue = dict[int, ResponseCallback]


class ConfigUnitSystem(TypedDict):
    length: str
    accumulated_precipitation: str
    area: str
    mass: str
    pressure: str
    temperature: str
    volume: str
    wind_speed: str


class Config(TypedDict):
    allowlist_external_dirs: list[str]
    allowlist_external_urls: list[str]
    components: list[str]
    config_dir: str
    config_source: str
    country: str
    currency: str
    debug: bool
    elevation: int
    external_url: str | None
    internal_url: str | None
    language: str
    latitude: float
    longitude: float
    radius: int
    recovery_mode: bool
    safe_mode: bool
    state: str
    time_zone: str
    unit_system: ConfigUnitSystem
    version: str
    whitelist_external_dirs: list[str]


class Device(TypedDict):
    area_id: str | None
    configuration_url: str | None
    config_entries: list[str] | None
    config_entries_subentries: dict[str, list[str | None]] | None
    connections: list[list[str]] | None
    created_at: float | None
    disabled_by: str | None
    entry_type: str | None
    hw_version: str | None
    id: str
    identifiers: list[list[str]] | None
    labels: list[str] | None
    manufacturer: str | None
    model: str | None
    model_id: str | None
    modified_at: float | None
    name_by_user: str | None
    name: str | None
    primary_config_entry: str | None
    serial_number: str | None
    sw_version: str | None
    via_device_id: str | None


type Devices = list[Device]
type DevicesById = dict[str, Device]

type StateClass = str | None
type DeviceClass = str | None
type UnitOfMeasurement = str | None


class StateAttributes(TypedDict):
    friendly_name: NotRequired[str]
    supported_features: NotRequired[int]
    event_types: NotRequired[list[str]]
    event_type: NotRequired[str | None]
    options: NotRequired[list[str]]
    device_class: NotRequired[DeviceClass]
    icon: NotRequired[str]
    has_date: NotRequired[bool]
    unit_of_measurement: NotRequired[UnitOfMeasurement]
    state_class: NotRequired[StateClass]
    supported_color_modes: NotRequired[list[str]]
    effect: NotRequired[str | None]
    color_mode: NotRequired[str | None]
    brightness: NotRequired[int | None]
    hs_color: NotRequired[list[float] | None]
    rgb_color: NotRequired[list[int] | None]
    entity_picture: NotRequired[str | None]
    order: NotRequired[float | None]
    entity_id: NotRequired[list[str] | None]  # members of a group
    effect_list: NotRequired[list[str] | None]
    min_color_temp_kelvin: NotRequired[int | None]
    max_color_temp_kelvin: NotRequired[int | None]
    color_temp_kelvin: NotRequired[int | None]
    media_title: NotRequired[str | None]
    media_artist: NotRequired[str | None]
    media_series_title: NotRequired[str | None]
    media_album_name: NotRequired[str | None]
    media_position: NotRequired[float | None]
    media_duration: NotRequired[float | None]
    volume_level: NotRequired[float | None]
    is_volume_muted: NotRequired[bool | None]
    source: NotRequired[str | None]
    source_list: NotRequired[list[str] | None]
    temperature: NotRequired[float | None]
    temperature_unit: NotRequired[str | None]
    humidity: NotRequired[float | None]
    pressure: NotRequired[float | None]
    pressure_unit: NotRequired[str | None]
    wind_speed: NotRequired[float | None]
    wind_speed_unit: NotRequired[str | None]
    wind_bearing: NotRequired[float | str | None]
    visibility: NotRequired[float | None]
    visibility_unit: NotRequired[str | None]
    dew_point: NotRequired[float | None]
    cloud_coverage: NotRequired[float | None]
    uv_index: NotRequired[float | None]
    current_temperature: NotRequired[float | None]
    current_humidity: NotRequired[float | None]


type Context = str | dict[str, str | None] | None


class State(TypedDict):
    entity_id: str
    state: str | None
    attributes: StateAttributes
    last_changed: str | float | None  # ISO from `get_states`, epoch seconds from events
    last_reported: str | float | None
    last_updated: str | float | None
    context: Context


type States = list[State]
type StatesByEntityId = dict[str, State]


class Entity(TypedDict):
    area_id: str | None
    categories: dict[str, str] | None
    config_entry_id: str | None
    config_subentry_id: str | None
    created_at: float | None
    device_id: str | None
    disabled_by: str | None
    entity_category: str | None
    entity_id: str
    has_entity_name: NotRequired[bool | None]
    hidden_by: str | None
    icon: str | None
    id: str
    labels: list[str] | None
    modified_at: float | None
    name: str | None
    options: dict[str, dict[str, object]] | None
    original_name: str | None
    platform: str | None
    translation_key: str | None
    unique_id: str | None


type Entities = list[Entity]


class Area(TypedDict):
    aliases: list[str] | None
    area_id: str | None
    floor_id: str | None
    humidity_entity_id: str | None
    icon: str | None
    labels: list[str] | None
    name: str | None
    picture: str | None
    temperature_entity_id: str | None
    created_at: float | None
    modified_at: float | None


type Areas = list[Area]

type EntitiesByGroup = dict[str, list[Entity]]


class IconResourceType(TypedDict):
    default: NotRequired[str]
    state: NotRequired[dict[str, str]]


type IconResourcesTypeName = str
type IconResources = dict[IconResourcesTypeName, IconResourceType]
type IconDomainName = str
type Icons = dict[IconDomainName, IconResources]


class IconsResponse(TypedDict):
    resources: Icons


type EntityIcons = dict[str, Icons]  # platform -> domain -> translation key


class EntityIconsResponse(TypedDict):
    resources: EntityIcons


class TranslationsResponse(TypedDict):
    resources: dict[str, str]


class IconQuery(TypedDict):
    category: str
    integration: NotRequired[str]


type IconQueries = list[IconQuery]


class SubscribeEntitiesEventEntityDetails(TypedDict):
    s: NotRequired[str]  # state
    a: NotRequired[StateAttributes]
    c: NotRequired[Context]
    lc: NotRequired[float]  # last changed
    lu: NotRequired[float]  # last updated


type SubscribeEntitiesEventEntityId = str
type SubscribeEntitiesEventAddedEntities = dict[
    SubscribeEntitiesEventEntityId, SubscribeEntitiesEventEntityDetails
]


class SubscribeEntitiesEventRemovedDetails(TypedDict):
    a: NotRequired[list[str]]  # names of removed attributes


SubscribedEntitiesEventChanged = TypedDict(
    "SubscribedEntitiesEventChanged",
    {
        "+": NotRequired[SubscribeEntitiesEventEntityDetails],
        "-": NotRequired[SubscribeEntitiesEventRemovedDetails],
    },
)


type SubscribeEntitiesEventChangedEntities = dict[
    SubscribeEntitiesEventEntityId, SubscribedEntitiesEventChanged
]


class SubscribeEntitiesEvent(TypedDict):
    a: NotRequired[SubscribeEntitiesEventAddedEntities]
    c: NotRequired[SubscribeEntitiesEventChangedEntities]
    r: NotRequired[list[str]]  # removed entity ids


class ServiceResponse(TypedDict):
    context: Context
    response: None


class DisplayEntityRaw(TypedDict):
    """One compressed row of `config/entity_registry/list_for_display`."""

    ei: str  # entity id
    pl: NotRequired[str | None]  # platform
    di: NotRequired[str | None]  # device id
    ai: NotRequired[str | None]  # area id
    tk: NotRequired[str | None]  # translation key
    ec: NotRequired[int | None]  # entity category, an index in to `entity_categories`
    en: NotRequired[str | None]  # entity name
    dp: NotRequired[int | None]  # display precision
    ic: NotRequired[str | None]  # icon
    hb: NotRequired[bool | None]  # hidden


class EntityRegistryDisplay(TypedDict):
    entities: list[DisplayEntityRaw]
    entity_categories: NotRequired[dict[str, str]]


class LovelaceAreasStrategy(TypedDict):
    order: NotRequired[list[str] | None]
    hidden: NotRequired[list[str] | None]


class LovelaceStrategy(TypedDict):
    type: NotRequired[str]
    areas: NotRequired[LovelaceAreasStrategy | None]
    hide_entities_without_area: NotRequired[bool | None]


class LovelaceView(TypedDict):
    strategy: NotRequired[LovelaceStrategy | None]


class LovelaceConfig(TypedDict):
    strategy: NotRequired[LovelaceStrategy | None]
    views: NotRequired[list[LovelaceView] | None]


class HistoryEntry(TypedDict):
    """Compressed `history/history_during_period` row; attributes are sent only when they change."""

    s: NotRequired[str]  # state
    a: NotRequired[StateAttributes]
    lc: NotRequired[float]  # last changed
    lu: NotRequired[float]  # last updated


type HistoryResult = dict[str, list[HistoryEntry]]


class LogbookEvent(TypedDict):
    when: NotRequired[float]
    message: NotRequired[str | None]
    state: NotRequired[str | None]


class ForecastItem(TypedDict):
    datetime: NotRequired[str]
    condition: NotRequired[str | None]
    temperature: NotRequired[float | None]
    templow: NotRequired[float | None]
    precipitation_probability: NotRequired[float | None]


class EntityForecast(TypedDict):
    forecast: list[ForecastItem]


class ForecastResult(TypedDict):
    response: dict[str, EntityForecast]


class RequestFunction(Protocol):
    """Send one command and get its result, validated as `result_type` when pydantic is available."""

    def __call__[T](
        self, command: Command, result_type: type[T], /
    ) -> Awaitable[T]: ...
