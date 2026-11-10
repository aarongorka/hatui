from typing import final, override

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Select, Static

from .click_bar import ClickBar
from .hatui_types import State, StateAttributes
from .services import Services

PAUSE, SEEK, VOLUME_SET, VOLUME_MUTE = 1, 2, 4, 8
PREVIOUS, NEXT, SELECT_SOURCE = 16, 32, 2048
PLAYING_STATES = ("playing", "paused", "buffering", "idle", "on")
OFF_STATES = ("off", "unavailable", "unknown")


def supports(attributes: StateAttributes, feature: int) -> bool:
    return bool((attributes.get("supported_features") or 0) & feature)


def duration_text(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def progress_fraction(attributes: StateAttributes) -> float | None:
    position, duration = (
        attributes.get("media_position"),
        attributes.get("media_duration"),
    )
    if position is None or not duration:
        return None
    return min(max(position / duration, 0.0), 1.0)


def now_playing(attributes: StateAttributes) -> list[str]:
    parts = (
        attributes.get("media_title"),
        attributes.get("media_artist") or attributes.get("media_series_title"),
        attributes.get("media_album_name"),
    )
    return [p for p in parts if p]


@final
class MediaControls(Vertical):
    """Now playing, transport buttons, volume, source and progress."""

    def __init__(self, entity_id: str, state: State, services: Services) -> None:
        super().__init__(id="media-controls")
        self.entity_id = entity_id
        self.services = services
        self.duration = 0.0
        attributes = state["attributes"]
        self.info = Static("", id="media-info", markup=False)
        self.progress_text = Static("", id="media-progress-text", markup=False)
        self.progress = ClickBar(
            0.0,
            lambda _: "#03a9f4",
            interactive=supports(attributes, SEEK),
            id="media-progress",
        )
        self.volume_row = Horizontal(classes="control-row", id="media-volume-row")
        self.volume = ClickBar(
            attributes.get("volume_level") or 0.0,
            lambda _: "#4caf50",
            id="media-volume",
        )
        source_list = attributes.get("source_list") or []
        self.sources = Select[str](
            [(s, s) for s in source_list],
            prompt="Source",
            id="media-source",
        )
        self.buttons = {
            "previous": Button("⏮", id="media-previous"),
            "play": Button("⏯", id="media-play", variant="primary"),
            "next": Button("⏭", id="media-next"),
            "mute": Button("🔇", id="media-mute"),
        }

    @override
    def compose(self) -> ComposeResult:
        yield self.info
        with Horizontal(id="media-buttons"):
            yield from self.buttons.values()
        with self.volume_row:
            yield Static("Volume", classes="control-label")
            yield self.volume
        yield self.progress_text
        yield self.progress
        yield self.sources

    def sync(self, state: State) -> None:
        attributes = state["attributes"]
        on = state.get("state") not in OFF_STATES
        self.info.update("\n".join(now_playing(attributes)) or "Nothing playing")
        self.buttons["previous"].display = on and supports(attributes, PREVIOUS)
        self.buttons["next"].display = on and supports(attributes, NEXT)
        self.buttons["play"].display = on and supports(attributes, PAUSE)
        self.buttons["play"].label = "⏸" if state.get("state") == "playing" else "▶"
        self.buttons["mute"].display = on and supports(attributes, VOLUME_MUTE)
        self.buttons["mute"].label = "🔇" if attributes.get("is_volume_muted") else "🔈"
        self.volume_row.display = on and supports(attributes, VOLUME_SET)
        self.volume.set_value(attributes.get("volume_level") or 0.0)
        fraction = progress_fraction(attributes)
        self.duration = float(attributes.get("media_duration") or 0)
        self.progress.display = self.progress_text.display = on and fraction is not None
        if fraction is not None:
            self.progress.set_value(fraction)
            position = duration_text(attributes.get("media_position"))
            duration = duration_text(attributes.get("media_duration"))
            self.progress_text.update(f"{position} / {duration}")
        self.sources.display = (
            on
            and bool(attributes.get("source_list"))
            and supports(attributes, SELECT_SOURCE)
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        _ = event.stop()
        service = {
            "media-previous": "media_previous_track",
            "media-play": "media_play_pause",
            "media-next": "media_next_track",
        }.get(event.button.id or "")
        if service:
            await self.services.call("media_player", service, self.entity_id, None)
        elif event.button.id == "media-mute":
            muted = str(event.button.label) == "🔈"
            await self.services.call(
                "media_player",
                "volume_mute",
                self.entity_id,
                {"is_volume_muted": muted},
            )

    async def on_click_bar_committed(self, message: ClickBar.Committed) -> None:
        _ = message.stop()
        if message.bar is self.volume:
            await self.services.call(
                "media_player",
                "volume_set",
                self.entity_id,
                {"volume_level": round(message.value, 2)},
            )
        elif message.bar is self.progress and self.duration:
            await self.services.call(
                "media_player",
                "media_seek",
                self.entity_id,
                {"seek_position": round(message.value * self.duration)},
            )

    async def on_select_changed(self, message: Select.Changed) -> None:
        _ = message.stop()
        if isinstance(message.value, str):
            await self.services.call(
                "media_player",
                "select_source",
                self.entity_id,
                {"source": message.value},
            )
