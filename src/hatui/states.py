from collections.abc import Mapping
from typing import Any

type StateDict = dict[str, Any]


def state_from_event(entity_id: str, details: Mapping[str, Any]) -> StateDict:
    return {
        "entity_id": entity_id,
        "state": details.get("s"),
        "attributes": dict(details.get("a", {})),
        "last_changed": details.get("lc"),
        "last_updated": details.get("lu"),
        "context": details.get("c"),
    }


def apply_event(
    store: dict[str, StateDict], event: Mapping[str, Any]
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
        plus: Mapping[str, Any] = diff.get("+", {})
        minus: Mapping[str, Any] = diff.get("-", {})
        if "s" in plus:
            current["state"] = plus["s"]
        attributes: dict[str, Any] = current.setdefault("attributes", {})
        attributes.update(plus.get("a", {}))
        for key in minus.get("a", []):
            _ = attributes.pop(key, None)
        for short, long in (
            ("lc", "last_changed"),
            ("lu", "last_updated"),
            ("c", "context"),
        ):
            if short in plus:
                current[long] = plus[short]
        changed.add(entity_id)

    for entity_id in event.get("r", []):
        _ = store.pop(entity_id, None)

    return added, changed
