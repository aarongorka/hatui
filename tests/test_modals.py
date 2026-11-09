from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult

from hatui.chart import line_chart, timeline
from hatui.history import (
    Sample,
    history_kind,
    numeric_points,
    parse_history,
    timeline_segments,
)
from hatui.light import kelvin_fraction, light_modes
from hatui.media import duration_text, progress_fraction, supports
from hatui.more_info import EntityModal, MoreInfo, logbook_lines, state_panel
from hatui.services import Services
from hatui.weather import condition_name, forecast_rows, forecast_type
import datetime


def test_history_kind_follows_lovelace() -> None:
    assert history_kind("sensor", {"unit_of_measurement": "W"}) == "line"
    assert history_kind("sensor", {"device_class": "temperature"}) == "line"
    assert history_kind("sensor", {"device_class": "enum"}) == "timeline"
    assert history_kind("input_number", {}) == "line"
    assert history_kind("climate", {}) == "line"
    assert history_kind("binary_sensor", {}) == "timeline"
    assert history_kind("light", {"state_class": "measurement"}) == "line"


def test_parse_history_carries_attributes_and_skips_unavailable() -> None:
    samples = parse_history(
        [
            {"s": "1.5", "a": {"unit_of_measurement": "W"}, "lu": 10.0},
            {"s": "unavailable", "lu": 20.0},
            {"s": "3", "lc": 30.0, "lu": 31.0},
        ]
    )
    assert [s.t for s in samples] == [10.0, 20.0, 30.0]
    assert samples[2].attributes["unit_of_measurement"] == "W"
    assert numeric_points(samples) == [(10.0, 1.5), (30.0, 3.0)]


def test_timeline_segments_extend_to_the_end() -> None:
    samples = [Sample(0, "on", {}), Sample(10, "off", {})]
    assert timeline_segments(samples, 30) == [(0, 10, "on"), (10, 30, "off")]


def test_line_chart_shape_and_flat_series() -> None:
    rising = line_chart([(0, 0), (100, 10)], 0, 100, 40, 4, "W")
    rows = rising.plain.split("\n")
    assert len(rows) == 5
    assert "10W" in rows[0]
    assert "0W" in rows[3]
    assert any("\u2800" < c <= "\u28ff" for c in rows[0])
    flat = line_chart([(0, 5), (100, 5)], 0, 100, 40, 4)
    assert "6" in flat.plain


def test_timeline_legend_shows_shares() -> None:
    text = timeline([(0, 75, "on"), (75, 100, "off")], 0, 100, 40, lambda _: "red")
    assert "on 75%" in text.plain
    assert "off 25%" in text.plain


def test_logbook_lines_newest_first() -> None:
    now = datetime.datetime(2026, 1, 2, 12)
    stamp = now.timestamp()
    lines = logbook_lines(
        [{"when": stamp - 60, "state": "off"}, {"when": stamp, "state": "on"}], now
    )
    assert lines[0].endswith("changed to on")
    assert lines[1].endswith("changed to off")


def test_media_helpers() -> None:
    assert supports({"supported_features": 1200653}, 4)
    assert not supports({"supported_features": 1}, 4)
    assert progress_fraction({"media_position": 30, "media_duration": 120}) == 0.25
    assert progress_fraction({}) is None
    assert duration_text(3725) == "1:02:05"


def test_light_and_weather_helpers() -> None:
    attrs = {
        "min_color_temp_kelvin": 2000,
        "max_color_temp_kelvin": 6000,
        "color_temp_kelvin": 4000,
        "supported_color_modes": ["color_temp", "hs"],
    }
    assert kelvin_fraction(attrs) == 0.5
    assert light_modes(attrs) == {"color_temp", "hs"}
    assert forecast_type({"supported_features": 6}) == "twice_daily"
    assert condition_name("partlycloudy") == "Partly cloudy"
    rows = forecast_rows(
        [
            {
                "datetime": "2026-01-01T00:00:00",
                "condition": "sunny",
                "templow": 10,
                "temperature": 20,
            }
        ],
        "daily",
        "°C",
    )
    assert "10–20°C" in rows[0]


class _ModalApp(App[None]):
    CSS_PATH = Path(__file__).parent.parent / "src/hatui/tcss.tcss"

    def __init__(
        self, calls: list[tuple[str, str, str, dict[str, Any] | None]]
    ) -> None:
        super().__init__()
        self.calls = calls

    async def request(self, command: dict[str, Any]) -> Any:
        raise Exception("no history in tests")

    async def call(
        self, domain: str, service: str, entity_id: str, data: dict[str, Any] | None
    ) -> None:
        self.calls.append((domain, service, entity_id, data))

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        state = {
            "state": "on",
            "attributes": {
                "brightness": 128,
                "supported_color_modes": ["brightness"],
            },
        }
        info = MoreInfo(
            "Lamp", "x", None, "on", [("Entity ID", "light.lamp")], "Toggle"
        )

        async def activate(_: str) -> None:
            return None

        _ = self.push_screen(
            EntityModal(
                "light.lamp",
                lambda _: info,
                activate,
                Services(self.request, self.call),
                lambda _: state,
            )
        )


async def test_light_brightness_bar_calls_service() -> None:
    calls: list[tuple[str, str, str, dict[str, Any] | None]] = []
    app = _ModalApp(calls)
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        await pilot.click("#light-brightness", offset=(1, 0))
        await pilot.pause()
    assert calls
    domain, service, entity_id, data = calls[-1]
    assert (domain, service, entity_id) == ("light", "turn_on", "light.lamp")
    assert data is not None
    assert data["brightness_pct"] < 20


def test_state_panel_shows_state_and_ages() -> None:
    info = MoreInfo(
        "Lamp", "x", "#ffffff", "On", [], None, "an hour ago", "a minute ago"
    )
    plain = state_panel(info).plain
    assert "On" in plain
    assert "Changed an hour ago" in plain
    assert "Updated a minute ago" in plain
