from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Services:
    """What the more-info popups may ask of Home Assistant."""

    request: Callable[[dict[str, Any]], Awaitable[Any]]
    call: Callable[[str, str, str, dict[str, Any] | None], Awaitable[None]]
