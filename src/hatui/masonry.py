from textual.layouts.factory import LAYOUT_MAP
from textual.geometry import NULL_OFFSET, Region, Size, Spacing
from textual.layout import ArrangeResult, Layout, WidgetPlacement
from textual.widget import Widget


def column_layout(width: int, min_column_width: int, gap: int) -> tuple[int, int]:
    """Return (column count, column width) for the available width."""

    columns = max(1, (width + gap) // (min_column_width + gap))
    return columns, max(1, (width - gap * (columns - 1)) // columns)


class MasonryLayout(Layout):
    """Responsive columns where each child goes in to the currently shortest column, like Lovelace."""

    name = "masonry"

    def __init__(self, min_column_width: int = 44, gap: int = 1) -> None:
        super().__init__()
        self.min_column_width = min_column_width
        self.gap = gap

    def arrange(
        self,
        parent: Widget,
        children: list[Widget],
        size: Size,
        greedy: bool = True,
    ) -> ArrangeResult:
        parent.pre_layout(self)
        columns, column_width = column_layout(
            size.width, self.min_column_width, self.gap
        )
        viewport = parent.app.viewport_size
        heights = [0] * columns
        placements: list[WidgetPlacement] = []

        for child in children:
            column = heights.index(min(heights))
            content_height = child.get_content_height(
                Size(column_width, size.height), viewport, column_width
            )
            height = content_height + child.styles.gutter.height
            x = column * (column_width + self.gap)
            placements.append(
                WidgetPlacement(
                    Region(x, heights[column], column_width, height),
                    NULL_OFFSET,
                    Spacing(),
                    child,
                )
            )
            heights[column] += height
        return placements


LAYOUT_MAP["masonry"] = MasonryLayout
