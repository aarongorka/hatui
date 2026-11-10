import logging
from typing import final, override

from textual.app import ComposeResult
from textual.color import Color
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from .helpers import reverse_easing
from .masonry import MasonryLayout
from .present import Presentation

logger = logging.getLogger(__name__)


@final
class EntityWidget(Horizontal):
    """A single-line entity row: icon, name and state."""

    def __init__(self, entity_id: str, name: str, presentation: Presentation) -> None:
        super().__init__(classes="entity-row")
        self.entity_id = entity_id
        self.icon_widget = Static(presentation.icon, classes="icon", markup=False)
        self.name_widget = Static(name, classes="name", markup=False)
        self.state_widget = Static(
            presentation.state_text, classes=presentation.state_classes, markup=False
        )
        self.presentation = presentation
        self._apply_colour(presentation.colour)

    @final
    class Clicked(Message):
        def __init__(self, entity_id: str, quick_action: bool):
            self.entity_id = entity_id
            self.quick_action = quick_action
            super().__init__()

    def on_click(self, event: Click) -> None:
        # like Lovelace: the icon/state is the quick action, anywhere else opens more-info
        quick = event.widget in (self.icon_widget, self.state_widget)
        _ = self.post_message(self.Clicked(self.entity_id, quick))

    @override
    def compose(self) -> ComposeResult:
        yield self.icon_widget
        yield self.name_widget
        yield self.state_widget

    def _apply_colour(self, colour: str | None) -> None:
        self.icon_widget.styles.color = Color.parse(colour) if colour else None

    def apply(self, presentation: Presentation, animate: bool) -> None:
        """Update the row, fading it in only when something visible changed."""

        previous = self.presentation
        self.presentation = presentation
        self.icon_widget.update(presentation.icon)
        self.state_widget.update(presentation.state_text)
        self.state_widget.classes = presentation.state_classes
        self._apply_colour(presentation.colour)

        visible_change = (
            previous.state_text != presentation.state_text
            or previous.icon != presentation.icon
            or previous.colour != presentation.colour
        )
        if animate and visible_change and self.is_mounted:
            _ = self.styles.animate(
                "opacity",
                value=0.0,
                duration=2.0,
                final_value=1.0,
                easing=reverse_easing,
            )


@final
class GroupCard(Vertical):
    """A titled, bordered group of entity rows."""

    def __init__(self, title: str, *children: Widget) -> None:
        super().__init__(*children, classes="group-card")
        self.border_title = title


@final
class CardGrid(VerticalScroll):
    """Scrolling container that lays cards out in responsive masonry columns."""

    def __init__(self, *children: GroupCard) -> None:
        super().__init__(*children, id="cards")
        self.styles.layout = MasonryLayout()
