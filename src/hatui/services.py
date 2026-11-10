from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .hatui_types import RequestFunction, ServiceData


@dataclass(frozen=True)
class Services:
    """What the more-info popups may ask of Home Assistant."""

    request: RequestFunction
    call: Callable[[str, str, str, ServiceData | None], Awaitable[None]]
