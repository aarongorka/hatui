from collections.abc import Mapping
from dataclasses import dataclass, field

BUILTIN_STATES = {"unavailable": "Unavailable", "unknown": "Unknown"}


@dataclass
class Translations:
    """Flat `frontend/get_translations` resources for the `entity_component` and `entity` categories."""

    resources: Mapping[str, str] = field(default_factory=dict[str, str])

    def domain_name(self, domain: str) -> str:
        return (
            self.resources.get(f"component.{domain}.entity_component._.name")
            or domain.replace("_", " ").title()
        )

    def state(
        self,
        domain: str,
        state: str,
        device_class: str | None = None,
        platform: str | None = None,
        translation_key: str | None = None,
    ) -> str | None:
        """Most specific translation of a state, or None."""

        if state in BUILTIN_STATES:
            return BUILTIN_STATES[state]
        keys: list[str] = []
        if platform and translation_key:
            keys.append(
                f"component.{platform}.entity.{domain}.{translation_key}.state.{state}"
            )
        if device_class:
            keys.append(
                f"component.{domain}.entity_component.{device_class}.state.{state}"
            )
        keys.append(f"component.{domain}.entity_component._.state.{state}")
        return next((v for k in keys if (v := self.resources.get(k))), None)
