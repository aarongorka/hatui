import colorsys
from typing import final, override

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Select, Static

from .click_bar import ClickBar
from .hatui_types import ServiceData, State, StateAttributes
from .services import Services

COLOUR_MODES = frozenset({"hs", "rgb", "rgbw", "rgbww", "xy"})
DEFAULT_KELVIN = (2000, 6500)


def hex_rgb(r: float, g: float, b: float) -> str:
    return f"#{round(r):02x}{round(g):02x}{round(b):02x}"


def kelvin_colour(fraction: float) -> str:
    """Warm amber to cool white, which is close enough for a swatch."""

    warm, cool = (255, 167, 87), (207, 224, 255)
    return hex_rgb(*(w + (c - w) * fraction for w, c in zip(warm, cool)))


def hue_colour(fraction: float) -> str:
    return hex_rgb(*(c * 255 for c in colorsys.hsv_to_rgb(fraction, 1, 1)))


def saturation_colour(hue: float, fraction: float) -> str:
    return hex_rgb(*(c * 255 for c in colorsys.hsv_to_rgb(hue, fraction, 1)))


def brightness_fraction(attributes: StateAttributes) -> float:
    return float(attributes.get("brightness") or 0) / 255


def kelvin_range(attributes: StateAttributes) -> tuple[int, int]:
    low = int(attributes.get("min_color_temp_kelvin") or DEFAULT_KELVIN[0])
    high = int(attributes.get("max_color_temp_kelvin") or DEFAULT_KELVIN[1])
    return low, max(high, low + 1)


def kelvin_fraction(attributes: StateAttributes) -> float:
    low, high = kelvin_range(attributes)
    return (float(attributes.get("color_temp_kelvin") or low) - low) / (high - low)


def hs_fractions(attributes: StateAttributes) -> tuple[float, float]:
    hue, saturation = attributes.get("hs_color") or (0.0, 100.0)
    return hue / 360, saturation / 100


def light_modes(attributes: StateAttributes) -> frozenset[str]:
    return frozenset(attributes.get("supported_color_modes") or ())


@final
class LightControls(Vertical):
    """Brightness, colour temperature, colour and effect controls for a light."""

    def __init__(self, entity_id: str, state: State, services: Services) -> None:
        super().__init__(id="light-controls")
        self.entity_id = entity_id
        self.services = services
        attributes = state["attributes"]
        modes = light_modes(attributes)
        self.kelvin = kelvin_range(attributes)
        hue, saturation = hs_fractions(attributes)
        self.brightness = (
            ClickBar(
                brightness_fraction(attributes),
                lambda f: kelvin_colour(f * 0.6 + 0.4),
                id="light-brightness",
            )
            if modes - {"onoff"}
            else None
        )
        self.temperature = (
            ClickBar(kelvin_fraction(attributes), kelvin_colour, id="light-temperature")
            if "color_temp" in modes
            else None
        )
        has_colour = bool(modes & COLOUR_MODES)
        self.hue = ClickBar(hue, hue_colour, id="light-hue") if has_colour else None
        self.saturation = (
            ClickBar(
                saturation,
                lambda f: saturation_colour(self.hue_now, f),
                id="light-saturation",
            )
            if has_colour
            else None
        )
        self.hue_now = hue
        effects: list[str] = attributes.get("effect_list") or []
        self.effects = (
            Select[str](
                [(e, e) for e in effects],
                value=attributes.get("effect") or Select.BLANK,
                prompt="Effect",
                id="light-effect",
            )
            if effects
            else None
        )

    @override
    def compose(self) -> ComposeResult:
        for label, bar in (
            ("Brightness", self.brightness),
            ("Temperature", self.temperature),
            ("Hue", self.hue),
            ("Saturation", self.saturation),
        ):
            if bar:
                with Horizontal(classes="control-row"):
                    yield Static(label, classes="control-label")
                    yield bar
        if self.effects:
            yield self.effects

    def sync(self, state: State) -> None:
        attributes = state["attributes"]
        if self.brightness:
            self.brightness.set_value(brightness_fraction(attributes))
        if self.temperature:
            self.temperature.set_value(kelvin_fraction(attributes))
        if self.hue and self.saturation:
            self.hue_now, saturation = hs_fractions(attributes)
            self.hue.set_value(self.hue_now)
            self.saturation.set_value(saturation)

    async def on_click_bar_committed(self, message: ClickBar.Committed) -> None:
        _ = message.stop()
        bar, value = message.bar, message.value
        data: ServiceData
        if bar is self.brightness:
            data = {"brightness_pct": max(round(value * 100), 1)}
        elif bar is self.temperature:
            low, high = self.kelvin
            data = {"color_temp_kelvin": round(low + (high - low) * value)}
        elif bar is self.hue and self.saturation:
            self.hue_now = value
            data = {
                "hs_color": [round(value * 360), round(self.saturation.value * 100)]
            }
        elif bar is self.saturation and self.hue:
            data = {"hs_color": [round(self.hue.value * 360), round(value * 100)]}
        else:
            return
        await self.services.call("light", "turn_on", self.entity_id, data)

    async def on_select_changed(self, message: Select.Changed) -> None:
        _ = message.stop()
        if isinstance(message.value, str):
            await self.services.call(
                "light", "turn_on", self.entity_id, {"effect": message.value}
            )
