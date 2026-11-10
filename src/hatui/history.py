"""History handling ported from the Lovelace frontend (`src/data/history.ts`)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .hatui_types import HistoryEntry, StateAttributes

NUMERIC_SENSOR_DEVICE_CLASSES = frozenset(
    {
        "absolute_humidity", "apparent_power", "aqi", "area", "atmospheric_pressure",
        "battery", "blood_glucose_concentration", "carbon_dioxide", "carbon_monoxide",
        "conductivity", "current", "data_rate", "data_size", "distance", "duration",
        "energy", "energy_distance", "energy_storage", "frequency", "gas", "humidity",
        "illuminance", "irradiance", "moisture", "monetary", "nitrogen_dioxide",
        "nitrogen_monoxide", "nitrous_oxide", "ozone", "ph", "pm1", "pm10", "pm25",
        "pm4", "power", "power_factor", "precipitation", "precipitation_intensity",
        "pressure", "radon", "reactive_energy", "reactive_power", "signal_strength",
        "sound_pressure", "speed", "sulphur_dioxide", "temperature", "temperature_delta",
        "volatile_organic_compounds", "volatile_organic_compounds_parts", "voltage",
        "volume", "volume_flow_rate", "volume_storage", "water", "weight",
        "wind_direction", "wind_speed",
    }
)  # fmt: skip
NUMERICAL_DOMAINS = frozenset({"counter", "input_number", "number"})
# not numeric themselves, but the frontend plots an attribute for them
LINE_ATTRIBUTES = {
    "climate": "current_temperature",
    "water_heater": "current_temperature",
    "humidifier": "current_humidity",
}
NO_HISTORY_DOMAINS = frozenset({"camera", "configurator"})
UNAVAILABLE = ("unavailable", "unknown")

type Kind = Literal["line", "timeline"]
type Point = tuple[float, float]
type Segment = tuple[float, float, str]


@dataclass(frozen=True)
class Sample:
    t: float
    state: str
    attributes: StateAttributes


def is_numeric_entity(domain: str, attributes: StateAttributes) -> bool:
    return (
        domain in NUMERICAL_DOMAINS
        or "unit_of_measurement" in attributes
        or "state_class" in attributes
        or (
            domain == "sensor"
            and attributes.get("device_class") in NUMERIC_SENSOR_DEVICE_CLASSES
        )
    )


def history_kind(domain: str, attributes: StateAttributes) -> Kind:
    if domain in LINE_ATTRIBUTES or domain == "zone":
        return "line"
    return "line" if is_numeric_entity(domain, attributes) else "timeline"


def parse_history(entries: Sequence[HistoryEntry]) -> list[Sample]:
    """Decode the compressed `history/history_during_period` form.

    Attributes are only sent when they change, so carry them forward.
    """

    samples: list[Sample] = []
    attributes: StateAttributes = {}
    for entry in entries:
        attributes = entry.get("a") or attributes
        t = entry.get("lc") or entry.get("lu")
        state = entry.get("s")
        if t is None or state is None:
            continue
        samples.append(Sample(float(t), state, attributes))
    return samples


def numeric_points(
    samples: Sequence[Sample], attribute: str | None = None
) -> list[Point]:
    points: list[Point] = []
    for sample in samples:
        # the attribute is chosen at runtime, so it cannot be a literal TypedDict key
        attributes: Mapping[str, object] = sample.attributes
        raw = attributes.get(attribute) if attribute else sample.state
        if sample.state in UNAVAILABLE or not isinstance(raw, str | int | float):
            continue
        try:
            points.append((sample.t, float(raw)))
        except ValueError:
            continue
    return points


def timeline_segments(samples: Sequence[Sample], end: float) -> list[Segment]:
    segments: list[Segment] = []
    for current, following in zip(samples, [*samples[1:], None]):
        stop = following.t if following else end
        if stop > current.t:
            segments.append((current.t, stop, current.state))
    return segments
