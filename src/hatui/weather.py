import datetime
from collections.abc import Mapping, Sequence

from .hatui_types import ForecastItem, StateAttributes
from .present import glyph

FORECAST_SUPPORT = (("daily", 1), ("twice_daily", 2), ("hourly", 4))
MAX_ROWS = 12
CONDITION_ICONS = {
    "partlycloudy": "partly-cloudy",
    "exceptional": "alert-circle-outline",
    "clear-night": "night",
    "lightning-rainy": "lightning-rainy",
    "snowy-rainy": "snowy-rainy",
    "windy-variant": "windy-variant",
}
CONDITIONS = {
    "clear-night": "Clear, night", "cloudy": "Cloudy", "exceptional": "Exceptional",
    "fog": "Fog", "hail": "Hail", "lightning": "Lightning",
    "lightning-rainy": "Lightning, rainy", "partlycloudy": "Partly cloudy",
    "pouring": "Pouring", "rainy": "Rainy", "snowy": "Snowy",
    "snowy-rainy": "Snowy, rainy", "sunny": "Sunny", "windy": "Windy",
    "windy-variant": "Windy",
}  # fmt: skip
DETAILS = (
    ("Humidity", "humidity", "%"),
    ("Pressure", "pressure", "pressure_unit"),
    ("Wind", "wind_speed", "wind_speed_unit"),
    ("Visibility", "visibility", "visibility_unit"),
    ("Dew point", "dew_point", "temperature_unit"),
    ("Cloud cover", "cloud_coverage", "%"),
    ("UV index", "uv_index", ""),
)
COMPASS = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


def condition_glyph(condition: str | None) -> str:
    condition = condition or "exceptional"
    return glyph(f"mdi:weather-{CONDITION_ICONS.get(condition, condition)}")


def condition_name(condition: str | None) -> str:
    return CONDITIONS.get(
        condition or "", (condition or "unknown").replace("-", " ").capitalize()
    )


def forecast_type(attributes: StateAttributes) -> str | None:
    features = attributes.get("supported_features") or 0
    return next((kind for kind, bit in FORECAST_SUPPORT if features & bit), None)


def bearing_text(bearing: float | str | None) -> str:
    try:
        return COMPASS[round(float(bearing or 0) / 22.5) % 16]
    except ValueError:
        return str(bearing)


def detail_rows(attributes: StateAttributes) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    # keys come from DETAILS at runtime, so they cannot be literal TypedDict keys
    loose: Mapping[str, object] = attributes
    for label, key, unit_key in DETAILS:
        value = loose.get(key)
        if value is None:
            continue
        unit = unit_key if unit_key in ("%", "") else loose.get(unit_key, "")
        text = f"{value}{'' if unit == '%' else ' '}{unit}".strip()
        bearing = attributes.get("wind_bearing")
        if key == "wind_speed" and bearing is not None:
            text += f" {bearing_text(bearing)}"
        rows.append((label, text))
    return rows


def forecast_label(raw: str, kind: str) -> str:
    try:
        when = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if when.tzinfo:
        when = when.astimezone()
    return when.strftime("%a %H:%M" if kind != "daily" else "%a %d %b")


def forecast_rows(forecast: Sequence[ForecastItem], kind: str, unit: str) -> list[str]:
    lines: list[str] = []
    for item in forecast[:MAX_ROWS]:
        high, low = item.get("temperature"), item.get("templow")
        temps = f"{high}{unit}" if low is None else f"{low}–{high}{unit}"
        rain = item.get("precipitation_probability")
        label = forecast_label(str(item.get("datetime", "")), kind)
        condition = f"{condition_glyph(item.get('condition'))} {condition_name(item.get('condition')):<16}"
        lines.append(
            f"{label:<11} {condition} {temps:<12} {'' if rain is None else f'{rain}%'}"
        )
    return lines
