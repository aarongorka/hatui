# rich's Text.append returns self for chaining; assigning every call to `_` would only add noise.
# pyright: reportUnusedCallResult=false
import datetime
from collections.abc import Callable, Sequence

from rich.style import Style
from rich.text import Text

from .history import Point, Segment

# Braille dot bits, indexed [dot column][dot row]
BRAILLE = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))
LABEL_WIDTH = 9
PALETTE = ("#03a9f4", "#ff9800", "#4caf50", "#e91e63", "#9c27b0", "#00bcd4", "#ffc107")


def _clock(t: float, span: float) -> str:
    when = datetime.datetime.fromtimestamp(t)
    return when.strftime("%H:%M" if span < 86400 else "%d %b %H:%M")


def _interpolate(points: Sequence[Point], t: float) -> float:
    if t <= points[0][0]:
        return points[0][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t <= t1:
            return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return points[-1][1]


def _line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    dots: list[tuple[int, int]] = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    error = dx + dy
    while True:
        dots.append((x0, y0))
        if (x0, y0) == (x1, y1):
            return dots
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x0 += sx
        if doubled <= dx:
            error += dx
            y0 += sy


def line_chart(
    points: Sequence[Point],
    start: float,
    end: float,
    width: int,
    height: int,
    unit: str = "",
    colour: str = PALETTE[0],
) -> Text:
    """A braille line chart with y-axis labels, spanning `start`..`end`."""

    width = max(width - LABEL_WIDTH, 10)
    lo = min(v for _, v in points)
    hi = max(v for _, v in points)
    if hi == lo:
        lo, hi = lo - 1, hi + 1
    dot_w, dot_h = width * 2, height * 4
    span = max(end - start, 1.0)

    def row(value: float) -> int:
        return round((hi - value) / (hi - lo) * (dot_h - 1))

    cells = [[0] * width for _ in range(height)]
    previous: tuple[int, int] | None = None
    for x in range(dot_w):
        y = row(_interpolate(points, start + span * x / (dot_w - 1)))
        for px, py in _line(*(previous or (x, y)), x, y):
            cells[py // 4][px // 2] |= BRAILLE[px % 2][py % 4]
        previous = (x, y)

    def label(value: float) -> str:
        return f"{value:.4g}{unit}".rjust(LABEL_WIDTH - 1) + " "

    text = Text(no_wrap=True, overflow="crop")
    for r, cell_row in enumerate(cells):
        axis = (
            label(hi) if r == 0 else label(lo) if r == height - 1 else " " * LABEL_WIDTH
        )
        text.append(axis, Style(dim=True))
        text.append(
            "".join(chr(0x2800 + bits) for bits in cell_row), Style(color=colour)
        )
        text.append("\n")
    mid = _clock(start + span / 2, span)
    left, right = _clock(start, span), _clock(end, span)
    gap = max(width - len(left) - len(right) - len(mid), 2)
    text.append(
        " " * LABEL_WIDTH
        + left
        + " " * (gap // 2)
        + mid
        + " " * (gap - gap // 2)
        + right,
        Style(dim=True),
    )
    return text


def timeline(
    segments: Sequence[Segment],
    start: float,
    end: float,
    width: int,
    colour_for: Callable[[str], str],
    label_for: Callable[[str], str] = str,
) -> Text:
    """A coloured state bar plus a legend with each state's share of the period."""

    width = max(width - LABEL_WIDTH, 10)
    span = max(end - start, 1.0)
    bar = Text(no_wrap=True, overflow="crop")
    bar.append(" " * LABEL_WIDTH)
    index = 0
    for x in range(width):
        t = start + span * (x + 0.5) / width
        while index < len(segments) - 1 and segments[index][1] <= t:
            index += 1
        state = (
            segments[index][2]
            if segments and segments[index][0] <= t + span / width
            else None
        )
        bar.append(
            "█" if state else " ", Style(color=colour_for(state) if state else None)
        )

    totals: dict[str, float] = {}
    for seg_start, seg_end, state in segments:
        totals[state] = totals.get(state, 0.0) + max(
            min(seg_end, end) - max(seg_start, start), 0.0
        )
    text = Text(no_wrap=True, overflow="crop")
    for _ in range(2):
        text.append_text(bar)
        text.append("\n")
    left, right = _clock(start, span), _clock(end, span)
    text.append(
        " " * LABEL_WIDTH
        + left
        + " " * max(width - len(left) - len(right), 1)
        + right
        + "\n",
        Style(dim=True),
    )
    for state, total in sorted(totals.items(), key=lambda kv: -kv[1]):
        text.append(" " * LABEL_WIDTH)
        text.append("■ ", Style(color=colour_for(state)))
        text.append(f"{label_for(state)} {total / span:.0%}   ")
    return text
