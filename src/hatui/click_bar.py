# rich's Text.append returns self for chaining; assigning every call to `_` would only add noise.
# pyright: reportUnusedCallResult=false
from collections.abc import Callable
from typing import final, override

from rich.style import Style
from rich.text import Text
from textual.events import MouseDown, MouseMove, MouseUp
from textual.message import Message
from textual.widget import Widget


@final
class ClickBar(Widget):
    """A horizontal slider: click or drag to choose a 0..1 value, committed on release."""

    @final
    class Committed(Message):
        def __init__(self, bar: "ClickBar", value: float) -> None:
            super().__init__()
            self.bar = bar
            self.value = value

    def __init__(
        self,
        value: float,
        colour_at: Callable[[float], str],
        interactive: bool = True,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self.value = value
        self.colour_at = colour_at
        self.interactive = interactive
        self.dragging = False

    def set_value(self, value: float) -> None:
        if self.dragging:
            return
        self.value = min(max(value, 0.0), 1.0)
        _ = self.refresh()

    def _value_at(self, x: int) -> float:
        return min(max((x + 0.5) / max(self.size.width, 1), 0.0), 1.0)

    @override
    def render(self) -> Text:
        width = max(self.size.width, 1)
        text = Text(no_wrap=True, overflow="crop")
        marker = min(int(self.value * width), width - 1)
        for i in range(width):
            fraction = (i + 0.5) / width
            if i == marker and self.interactive:
                text.append("┃", Style(color="white", bold=True))
            elif fraction <= self.value:
                text.append("█", Style(color=self.colour_at(fraction)))
            else:
                text.append("░", Style(color=self.colour_at(fraction), dim=True))
        return text

    def _set_from(self, x: int) -> None:
        self.value = self._value_at(x)
        _ = self.refresh()

    def on_mouse_down(self, event: MouseDown) -> None:
        if not self.interactive:
            return
        event.stop()
        self.dragging = True
        self.capture_mouse()
        self._set_from(event.x)

    def on_mouse_move(self, event: MouseMove) -> None:
        if self.dragging:
            self._set_from(event.x)

    def on_mouse_up(self, event: MouseUp) -> None:
        if not self.dragging:
            return
        event.stop()
        self.dragging = False
        self.release_mouse()
        self._set_from(event.x)
        _ = self.post_message(self.Committed(self, self.value))
