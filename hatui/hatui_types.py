from typing import Any, Literal, NotRequired, TypedDict

type HomeAssistantWebsocketResponseType = Literal["result", "event"]


class HomeAssistantWebsocketAuthRequiredResponse(TypedDict):
    type: str
    ha_version: str


class HomeAssistantWebsocketAuthResponse(TypedDict):
    type: str
    ha_version: NotRequired[str]
    message: NotRequired[str]


class HomeAssistantWebsocketCommandResponse[T](TypedDict):
    id: int
    type: str
    success: bool
    result: T


class HomeAssistantWebsocketSubscribeResponse(TypedDict):
    id: int
    type: str
    success: bool
    result: None


class HomeAssistantWebsocketEventResponse[T](TypedDict):
    id: int
    type: str
    event: T


type HomeAssistantWebsocketResponse[T] = (
    HomeAssistantWebsocketAuthRequiredResponse
    | HomeAssistantWebsocketCommandResponse[T]
    | HomeAssistantWebsocketAuthResponse
    | HomeAssistantWebsocketEventResponse[T]
    | HomeAssistantWebsocketSubscribeResponse
    | HomeAssistantWebsocketEventResponse[T]
)


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


class ConfigUnitSystem(TypedDict):
    length: str
    accumulated_precipitation: str
    area: str
    mass: str
    pressure: str
    temperature: str
    volume: str
    wind_speed: str


class Device(TypedDict):
    area_id: str | None
    configuration_url: str | None
    config_entries: list[str] | None
    config_entries_subentries: dict[str, list[str | None]] | None
    connections: list[Any] | None
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


class StateAttributes(TypedDict):
    friendly_name: NotRequired[str]
    supported_features: NotRequired[int]
    event_types: NotRequired[list[str]]
    event_type: NotRequired[str | None]
    options: NotRequired[list[str]]
    device_class: NotRequired[str]
    icon: NotRequired[str]
    has_date: NotRequired[bool]
    unit_of_measurement: NotRequired[str]
    state_class: NotRequired[str]
    supported_color_modes: NotRequired[list[str]]
    effect: NotRequired[str | None]
    color_mode: NotRequired[str | None]
    brightness: NotRequired[int | None]
    hs_color: NotRequired[list[float] | None]
    rgb_color: NotRequired[list[int] | None]


type Context = str | dict[str, str | None] | None


class State(TypedDict):
    entity_id: str
    state: str | None
    attributes: StateAttributes
    last_changed: str | None
    last_reported: str | None
    last_updated: str | None
    context: Context


type States = list[State]


class Entity(TypedDict):
    area_id: str | None
    categories: dict[str, Any] | None
    config_entry_id: str | None
    config_subentry_id: str | None
    created_at: float | None
    device_id: str | None
    disabled_by: str | None
    entity_category: str | None
    entity_id: str
    has_entity_name: bool | None
    hidden_by: str | None
    icon: str | None
    id: str
    labels: list[str] | None
    modified_at: float | None
    name: str | None
    options: dict[str, dict[str, Any]] | None
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
type IconDomains = dict[IconDomainName, IconResources]


class Icons(TypedDict):
    resources: IconDomains


class IconQuery(TypedDict):
    category: str
    integration: NotRequired[str]


type IconQueries = list[IconQuery]


class SubscribeEntitiesEventEntityDetails(TypedDict):
    s: NotRequired[str]  # state
    a: NotRequired[StateAttributes]
    c: NotRequired[Context]
    lc: NotRequired[float]  # last changed


type SubscribeEntitiesEventEntityId = str
type SubscribeEntitiesEventAddedEntities = dict[
    SubscribeEntitiesEventEntityId, SubscribeEntitiesEventEntityDetails
]


class SubscribedEntitiesEventChanged(
    TypedDict(
        "SubscribeEntitiesEventChanged",
        {"+": SubscribeEntitiesEventEntityDetails},
    )
):
    pass


type SubscribeEntitiesEventChangedEntities = dict[
    SubscribeEntitiesEventEntityId, SubscribedEntitiesEventChanged
]


class SubscribeEntitiesEvent(TypedDict):
    a: NotRequired[SubscribeEntitiesEventAddedEntities]
    c: NotRequired[SubscribeEntitiesEventChangedEntities]


class ServiceResponse(TypedDict):
    context: Context
    response: None
