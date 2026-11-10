from typing import cast

from .hatui_types import (
    State,
    StateAttributes,
    SubscribeEntitiesEvent,
    SubscribeEntitiesEventEntityDetails,
)


def state_from_event(
    entity_id: str, details: SubscribeEntitiesEventEntityDetails
) -> State:
    attributes: StateAttributes = details["a"].copy() if "a" in details else {}
    return {
        "entity_id": entity_id,
        "state": details.get("s"),
        "attributes": attributes,
        "last_changed": details.get("lc"),
        "last_reported": None,
        "last_updated": details.get("lu"),
        "context": details.get("c"),
    }


def apply_event(
    store: dict[str, State], event: SubscribeEntitiesEvent
) -> tuple[set[str], set[str]]:
    """Merge a `subscribe_entities` event in to the store.

    Returns the ids that were (added or replaced, changed), and removes dropped entities.
    """

    added: set[str] = set()
    changed: set[str] = set()

    for entity_id, details in event.get("a", {}).items():
        store[entity_id] = state_from_event(entity_id, details)
        added.add(entity_id)

    for entity_id, diff in event.get("c", {}).items():
        current = store.get(entity_id)
        if current is None:
            continue
        plus = diff.get("+", {})
        minus = diff.get("-", {})
        if "s" in plus:
            current["state"] = plus["s"]
        attributes = current["attributes"]
        attributes.update(plus.get("a", {}))
        # attribute names are only known at runtime, which a TypedDict cannot express
        loose = cast("dict[str, object]", cast("object", attributes))
        for key in minus.get("a", []):
            _ = loose.pop(key, None)
        if "lc" in plus:
            current["last_changed"] = plus["lc"]
        if "lu" in plus:
            current["last_updated"] = plus["lu"]
        if "c" in plus:
            current["context"] = plus["c"]
        changed.add(entity_id)

    for entity_id in event.get("r", []):
        _ = store.pop(entity_id, None)

    return added, changed
