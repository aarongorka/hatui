# rich's Text.append returns self for chaining; assigning every call to `_` would only add noise.
# pyright: reportUnusedCallResult=false
import asyncio
import datetime
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import final, override

import humanize
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Static

from .chart import PALETTE, line_chart, timeline
from .hatui_types import (
    ForecastResult,
    HistoryEntry,
    LogbookEvent,
    State,
    StateAttributes,
)
from .history import (
    LINE_ATTRIBUTES,
    NO_HISTORY_DOMAINS,
    history_kind,
    numeric_points,
    parse_history,
    timeline_segments,
)
from .light import LightControls
from .lovelace import DisplayEntity, domain_of
from .media import MediaControls
from .present import Presentation, state_colour
from .services import Services
from .translate import Translations
from .weather import (
    condition_glyph,
    condition_name,
    detail_rows,
    forecast_rows,
    forecast_type,
)

HIDDEN_ATTRIBUTES = frozenset(
    {"friendly_name", "icon", "entity_picture", "supported_features", "editable"}
)
MAX_VALUE_LENGTH = 90
ACTIONS = {"light": "Toggle", "switch": "Toggle", "button": "Press"}


@dataclass(frozen=True)
class MoreInfo:
    title: str
    icon: str
    colour: str | None
    state_text: str
    rows: list[tuple[str, str]]
    action: str | None
    changed: str | None = None
    updated: str | None = None
    entity_id: str = ""


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, dict)):
        value = json.dumps(value, separators=(",", ":"), default=str)
    text = str(value)
    return text if len(text) <= MAX_VALUE_LENGTH else text[: MAX_VALUE_LENGTH - 1] + "…"


def _ago(raw: object, now: datetime.datetime) -> str | None:
    """`last_changed` is an ISO string from `get_states` and epoch seconds from events."""

    try:
        if isinstance(raw, (int, float)):
            when = datetime.datetime.fromtimestamp(raw)
        elif isinstance(raw, str):
            when = datetime.datetime.fromisoformat(raw)
            if when.tzinfo:
                when = when.astimezone().replace(tzinfo=None)
        else:
            return None
    except ValueError:
        return None
    return humanize.naturaltime(now - when)


def build_more_info(
    entity: DisplayEntity | None,
    entity_id: str,
    name: str,
    state: State | None,
    presentation: Presentation,
    translations: Translations,
    now: datetime.datetime | None = None,
) -> MoreInfo:
    now = now or datetime.datetime.now()
    domain = domain_of(entity_id)
    raw = (state.get("state") if state else None) or ""
    attributes: StateAttributes = state["attributes"] if state else {}
    unit = attributes.get("unit_of_measurement")

    translated = translations.state(
        domain,
        raw,
        attributes.get("device_class"),
        entity.platform if entity else None,
        entity.translation_key if entity else None,
    )
    # toggles render as a glyph in the card row, which is meaningless in text
    state_text = (
        translated or (f"{raw} {unit}" if unit else raw)
        if domain in ACTIONS or domain == "input_boolean"
        else presentation.state_text
    )

    rows: list[tuple[str, str]] = []
    loose: Mapping[str, object] = attributes
    changed = _ago(state.get("last_changed"), now) if state else None
    updated = _ago(state.get("last_updated"), now) if state else None
    rows.extend(
        (key.replace("_", " ").capitalize(), _format_value(value))
        for key, value in sorted(loose.items())
        if key not in HIDDEN_ATTRIBUTES and value is not None
    )
    return MoreInfo(
        name, presentation.icon, presentation.colour, state_text, rows,
        ACTIONS.get(domain), changed, updated, entity_id,
    )  # fmt: skip


HISTORY_HOURS = 24
LOGBOOK_ROWS = 30
CHART_HEIGHT = 8


def logbook_lines(events: list[LogbookEvent], now: datetime.datetime) -> list[str]:
    """Newest first, as Lovelace's logbook shows them."""

    lines: list[str] = []
    for event in sorted(events, key=lambda e: e.get("when", 0), reverse=True)[
        :LOGBOOK_ROWS
    ]:
        when = datetime.datetime.fromtimestamp(float(event.get("when", 0)))
        stamp = when.strftime(
            "%H:%M:%S" if when.date() == now.date() else "%d %b %H:%M:%S"
        )
        what = event.get("message") or f"changed to {event.get('state', '?')}"
        lines.append(f"{stamp}  {what}")
    return lines


def state_panel(info: MoreInfo) -> Text:
    """Big cocolour-coded icon and state, with when it last changed."""

    colour = info.colour or "white"
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(f" {info.icon}  ", Style(color=colour, bold=True))
    text.append(info.state_text or "Unknown", Style(color=colour, bold=True))
    when = [
        f"{label} {ago}"
        for label, ago in (("Changed", info.changed), ("Updated", info.updated))
        if ago
    ]
    if when:
        text.append("\n   " + "  ·  ".join(when), Style(dim=True))
    return text


@final
class EntityModal(ModalScreen[None]):
    """Lovelace-style "more info" popup: controls, history graph, logbook and attributes."""

    BINDINGS = [("escape", "dismiss", "Close")]  # noqa: RUF012

    def __init__(
        self,
        entity_id: str,
        build: Callable[[str], MoreInfo],
        activate: Callable[[str], Awaitable[None]],
        services: Services,
        get_state: Callable[[str], State],
    ) -> None:
        super().__init__()
        self.entity_id = entity_id
        self.build = build
        self.activate = activate
        self.services = services
        self.get_state = get_state
        self.domain = domain_of(entity_id)
        self.header = Static("", id="more-info-title", markup=False)
        self.state_line = Static("", id="more-info-state", markup=False)
        self.action = Button("", id="more-info-action", variant="primary")
        self.controls: Widget | None = None
        self.weather = Static("", id="weather-panel", markup=False)
        self.chart = Static("", id="more-info-chart", markup=False)
        self.logbook = Static("", id="more-info-logbook", markup=False)
        self.details = Static("", id="more-info-details", markup=False)

    @override
    def compose(self) -> ComposeResult:
        state = self.get_state(self.entity_id)
        if self.domain == "light":
            self.controls = LightControls(self.entity_id, state, self.services)
        elif self.domain == "media_player":
            self.controls = MediaControls(self.entity_id, state, self.services)
        with Vertical(id="more-info"):
            yield self.header
            yield self.state_line
            with VerticalScroll():
                yield self.action
                if self.controls:
                    yield self.controls
                if self.domain == "weather":
                    yield self.weather
                if self.domain not in NO_HISTORY_DOMAINS:
                    yield Static("History", classes="section")
                    yield self.chart
                    yield Static("Logbook", classes="section")
                    yield self.logbook
                yield Static("Attributes", classes="section")
                yield self.details
            with Horizontal(id="more-info-footer"):
                yield Button("Close", id="more-info-close")

    def on_mount(self) -> None:
        self.refresh_content()
        if self.domain not in NO_HISTORY_DOMAINS:
            self.chart.update("Loading…")
            self.logbook.update("Loading…")
            _ = self.load_history()
        if self.domain == "weather":
            _ = self.load_forecast()

    def refresh_content(self) -> None:
        info = self.build(self.entity_id)
        state = self.get_state(self.entity_id)
        self.header.update(
            Text.assemble((info.title, "bold"), ("\n" + info.entity_id, "dim"))
        )
        self.state_line.update(state_panel(info))
        self.action.display = info.action is not None
        self.action.label = info.action or ""
        if isinstance(self.controls, LightControls | MediaControls):
            self.controls.sync(state)
        if self.domain == "weather":
            self.show_weather(state)
        width = max((len(key) for key, _ in info.rows), default=0)
        self.details.update(
            "\n".join(f"{key:<{width}}  {value}" for key, value in info.rows)
        )

    def show_weather(self, state: State, forecast: list[str] | None = None) -> None:
        attributes = state["attributes"]
        unit = attributes.get("temperature_unit") or ""
        condition = (
            f"{condition_glyph(state['state'])}  {condition_name(state['state'])}"
        )
        lines = [
            f"{condition}   {attributes.get('temperature', '')}{unit}",
            "",
        ]
        width = max((len(k) for k, _ in detail_rows(attributes)), default=0)
        lines += [f"{k:<{width}}  {v}" for k, v in detail_rows(attributes)]
        forecast = forecast if forecast is not None else self.forecast_lines
        if forecast:
            lines += ["", "Forecast", *forecast]
        self.forecast_lines = forecast
        self.weather.update("\n".join(lines))

    forecast_lines: list[str] = []  # noqa: RUF012

    @work(exclusive=True, group="forecast")
    async def load_forecast(self) -> None:
        state = self.get_state(self.entity_id)
        attributes = state["attributes"]
        kind = forecast_type(attributes)
        if not kind:
            return
        try:
            result = await self.services.request(
                {
                    "type": "call_service",
                    "domain": "weather",
                    "service": "get_forecasts",
                    "target": {"entity_id": self.entity_id},
                    "service_data": {"type": kind},
                    "return_response": True,
                },
                ForecastResult,
            )
            items = result["response"][self.entity_id]["forecast"]
        except (Exception, asyncio.CancelledError) as error:
            if isinstance(error, asyncio.CancelledError):
                raise
            self.show_weather(state, ["Forecast unavailable"])
            return
        self.show_weather(
            state, forecast_rows(items, kind, attributes.get("temperature_unit") or "")
        )

    @work(exclusive=True, group="history")
    async def load_history(self) -> None:
        end = time.time()
        start = end - HISTORY_HOURS * 3600
        history, events = await asyncio.gather(
            self.services.request(
                {
                    "type": "history/history_during_period",
                    "start_time": iso(start),
                    "end_time": iso(end),
                    "entity_ids": [self.entity_id],
                    "minimal_response": True,
                    "no_attributes": False,
                    "significant_changes_only": False,
                },
                dict[str, list[HistoryEntry]],
            ),
            self.services.request(
                {
                    "type": "logbook/get_events",
                    "start_time": iso(start),
                    "end_time": iso(end),
                    "entity_ids": [self.entity_id],
                },
                list[LogbookEvent],
            ),
            return_exceptions=True,
        )
        if isinstance(history, BaseException):
            self.chart.update("History unavailable")
        else:
            self.chart.update(
                self.render_chart(history.get(self.entity_id) or [], start, end)
            )
        if isinstance(events, BaseException):
            self.logbook.update("Logbook unavailable")
        else:
            lines = logbook_lines(events, datetime.datetime.now())
            self.logbook.update("\n".join(lines) or "No events in the last 24 hours")

    def render_chart(
        self, entries: list[HistoryEntry], start: float, end: float
    ) -> Text | str:
        samples = parse_history(entries)
        if not samples:
            return "No history in the last 24 hours"
        width = max(self.chart.size.width, 60)
        attributes = samples[-1].attributes
        kind = history_kind(self.domain, attributes)
        if kind == "line":
            attribute = LINE_ATTRIBUTES.get(self.domain)
            points = numeric_points(samples, attribute)
            if points:
                values = [v for _, v in points]
                unit = (
                    attributes.get("unit_of_measurement")
                    or attributes.get("temperature_unit")
                    or ""
                )
                summary = f"min {min(values):.4g}{unit}   max {max(values):.4g}{unit}   now {values[-1]:.4g}{unit}"
                chart = line_chart(points, start, end, width, CHART_HEIGHT, unit)
                return Text.assemble(chart, "\n", (summary, "dim"))
        palette: dict[str, str] = {}

        def colour_for(state: str) -> str:
            return state_colour(
                self.entity_id, state, attributes
            ) or palette.setdefault(state, PALETTE[len(palette) % len(PALETTE)])

        return timeline(timeline_segments(samples, end), start, end, width, colour_for)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "more-info-action":
            await self.activate(self.entity_id)
        elif event.button.id == "more-info-close":
            _ = self.dismiss()


def iso(timestamp: float) -> str:
    return datetime.datetime.fromtimestamp(timestamp, datetime.UTC).isoformat()
