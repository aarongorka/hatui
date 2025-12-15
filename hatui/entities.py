import json
import logging

import websockets.sync.client as ws
from websockets.sync.connection import Connection

from .hatui_types import (
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
    HomeAssistantWebsocketSubscribeResponse,
    IconDomains,
    IconQueries,
    Icons,
    ServiceResponse,
    State,
    States,
    SubscribeEntitiesEvent,
)
from .helpers import (
    check_response,
    filter_entities,
    get_domain_from_entity_id,
    get_integrations_from_components,
    split_entities_by_group,
)

logger = logging.getLogger(__name__)


try:
    from pydantic.type_adapter import TypeAdapter
except ImportError:
    logger.warning(
        "Could not import pydantic, continuing without request/response validation."
    )
    TypeAdapter = None


class HomeAssistant:
    def __init__(self, url: str, token: str) -> None:
        self.command_id: int = 1
        self.websocket: Connection = self.get_websocket(url, token)
        self.config: Config = self.get_config(self.websocket)
        self.icons: Icons = self.get_all_icons(self.websocket, self.config)
        self.entities: Entities = self.get_entities(self.websocket)
        self.areas: Areas = self.get_areas(self.websocket)
        self.devices: Devices = self.get_devices(self.websocket)
        self.states: States = self.get_states(self.websocket)
        self.entities_by_group: EntitiesByGroup = self.get_entities_by_group(
            self.websocket
        )

    def get_and_increment_command_id(self) -> int:
        command_id = self.command_id
        self.command_id = command_id + 1
        return command_id

    def get_all_icons(self, websocket: Connection, config: Config) -> Icons:
        """Get icons for domains and all given integrations."""

        try:
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
        icons = self.get_icons(websocket, queries)
        return icons

    def get_icons(self, websocket: Connection, queries: IconQueries) -> Icons:
        """Get icons for a given query."""

        resources: IconDomains = {}

        for query in queries:
            command = {
                "id": self.get_and_increment_command_id(),
                "type": "frontend/get_icons",
                "category": query["category"],
                "integration": query.get("integration"),
            }
            websocket.send(json.dumps(command))
            r = websocket.recv()
            if TypeAdapter:
                adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[Icons])
                data = adapter.validate_python(json.loads(r))
            else:
                data = json.loads(r)
            check_response(data)
            result = data["result"]
            result_resources = result["resources"]
            resources = {**resources, **result_resources}

        icons: Icons = {"resources": resources}
        return icons

    def get_websocket(self, url: str, token: str) -> Connection:
        try:
            return self.websocket
        except AttributeError:
            pass

        websocket = ws.connect(url)

        r = websocket.recv()
        if TypeAdapter:
            auth_required_adapter = TypeAdapter(
                HomeAssistantWebsocketAuthRequiredResponse
            )
            data = auth_required_adapter.validate_python(json.loads(r))
        else:
            data = json.loads(r)

        auth = {
            "type": "auth",
            "access_token": token,
        }
        websocket.send(json.dumps(auth))
        r = websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketAuthResponse)
            data = adapter.validate_python(json.loads(r))
        else:
            data = json.loads(r)
        if not data.get("type") == "auth_ok":
            logger.error("Auth failed", r)
            raise Exception("Auth failed")

        # TODO: ...maybe
        # features = {
        #     "id": self.get_and_increment_command_id(),
        #     "type": "supported_features",
        #     "features": {"coalesce_messages": 1},
        # }
        # websocket.send(json.dumps(features))
        # r = websocket.recv()
        # logger.info("Feature response: %s", r)

        return websocket

    def get_config(self, websocket: Connection) -> Config:
        """Get 'config', namely all the integrations loaded in HA."""

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "get_config",
        }
        websocket.send(json.dumps(command))
        r = websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[Config])
            data = adapter.validate_python(json.loads(r))
        else:
            data = json.loads(r)
        check_response(data)
        result = data["result"]
        return result

    def get_entities(self, websocket: Connection) -> list[Entity]:
        try:
            return self.entities
        except AttributeError:
            pass

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "config/entity_registry/list",
        }
        websocket.send(json.dumps(command))
        r = websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[Entities])
            data = adapter.validate_python(json.loads(r))
        else:
            data = json.loads(r)
        check_response(data)
        entities: list[Entity] = data.get("result", [])
        filtered_entities = filter_entities(entities)
        logger.debug("Entities: %s", filtered_entities)
        return filtered_entities

    def get_states(self, websocket: Connection) -> list[State]:
        try:
            return self.states
        except AttributeError:
            pass

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "get_states",
        }
        websocket.send(json.dumps(command))
        r = websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[States])
            data = adapter.validate_python(json.loads(r))
        else:
            data = json.loads(r)
        check_response(data)
        result = data.get("result", [])
        logger.debug("States: %s", result)
        return result

    def get_devices(self, websocket: Connection) -> Devices:
        try:
            return self.devices
        except AttributeError:
            pass

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "config/device_registry/list",
        }
        websocket.send(json.dumps(command))
        r = websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[Devices])
            data = adapter.validate_python(json.loads(r))
        else:
            data = json.loads(r)
        check_response(data)
        return data["result"]

    def subscribe_entities(self, websocket: Connection, entity_ids: list[str]) -> None:
        command = {
            "id": self.get_and_increment_command_id(),
            "type": "subscribe_entities",
            "include": {"entities": entity_ids},
        }
        websocket.send(json.dumps(command))
        r = websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketSubscribeResponse)
            data = adapter.validate_python(json.loads(r))
        else:
            data = json.loads(r)
        check_response(data)

    def wait_for_entities_update(
        self, websocket: Connection
    ) -> SubscribeEntitiesEvent | None:
        try:
            r = websocket.recv(timeout=0)
            logger.debug("Subscribe response: %s", r)
            if TypeAdapter:
                adapter = TypeAdapter(
                    HomeAssistantWebsocketEventResponse[SubscribeEntitiesEvent]
                )
                data = adapter.validate_python(json.loads(r))
            else:
                data = json.loads(r)
            check_response(data, "event")
            event = data["event"]
            return event
        except TimeoutError:
            return None

    def get_areas(self, websocket: Connection) -> list[Area]:
        try:
            return self.areas
        except AttributeError:
            pass

        command = {
            "id": self.get_and_increment_command_id(),
            "type": "config/area_registry/list",
        }
        websocket.send(json.dumps(command))
        r = websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(HomeAssistantWebsocketCommandResponse[Areas])
            data = adapter.validate_python(json.loads(r))
        else:
            data = json.loads(r)
        check_response(data)
        areas = data["result"]
        return areas

    def press_button(self, entity_id: str, websocket: Connection | None = None) -> None:
        if not websocket:
            websocket = self.websocket

        domain = get_domain_from_entity_id(entity_id)
        command = {
            "id": self.get_and_increment_command_id(),
            "type": "call_service",
            "domain": domain,
            "service_data": {},
            "target": {
                "entity_id": entity_id,
            },
        }
        websocket.send(json.dumps(command))
        r = websocket.recv()
        if TypeAdapter:
            adapter = TypeAdapter(
                HomeAssistantWebsocketCommandResponse[ServiceResponse]
            )
            data = adapter.validate_python(json.loads(r))
        else:
            data = json.loads(r)
        check_response(data)
        return None

    def get_entities_by_group(self, websocket: Connection) -> EntitiesByGroup:
        entities = self.get_entities(websocket)
        areas = self.get_areas(websocket)
        devices = self.get_devices(websocket)
        entities_by_group = split_entities_by_group(areas, devices, entities)
        return entities_by_group

    # TODO: remove? doesn't actually seem like it's useful for anything
    # def get_entities_detail(self,  websocket: Connection, entity_ids: list[str]):
    #     # try:
    #     #     return self.entities
    #     # except AttributeError:
    #     #     pass
    #
    #     command = {
    #         "id": self.get_and_increment_command_id(),
    #         "type": "config/entity_registry/get_entries",
    #         "entity_ids": entity_ids,
    #     }
    #     websocket.send(json.dumps(command))
    #     r = websocket.recv()
    #     data = json.loads(r)
    #     check_response(data)
    #     result = data.get("result", [])
    #     return result
