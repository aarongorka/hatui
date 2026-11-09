import asyncio
import io
import logging
import ssl
import urllib.request
from dataclasses import dataclass
from typing import final, override
from urllib.parse import urlsplit, urlunsplit

from PIL import Image
from rich.color import Color
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual import work
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

logger = logging.getLogger(__name__)

CAMERA_ROWS = 12
REQUEST_TIMEOUT = 10.0


def camera_url(ws_url: str, entity_id: str) -> str:
    """Map `ws(s)://host/api/websocket` to the HTTP camera snapshot endpoint."""

    parts = urlsplit(ws_url)
    scheme = "https" if parts.scheme == "wss" else "http"
    return urlunsplit((scheme, parts.netloc, f"/api/camera_proxy/{entity_id}", "", ""))


def fetch_snapshot(
    url: str, token: str, context: ssl.SSLContext | None = None
) -> bytes:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT, context=context) as r:  # noqa: S310
        return r.read()


def image_to_text(data: bytes, columns: int, rows: int) -> Text:
    """Render an image with half-blocks: each cell shows two vertical pixels."""

    image = Image.open(io.BytesIO(data))
    # JPEG draft mode decodes at reduced size, which matters a lot on a Pi 1
    image.draft("RGB", (columns * 2, rows * 4))
    image = image.convert("RGB")
    image.thumbnail((columns, rows * 2), Image.Resampling.BILINEAR)
    width, height = image.size
    rgb = image.tobytes()

    def pixel(x: int, y: int) -> Color:
        i = (y * width + x) * 3
        return Color.from_rgb(rgb[i], rgb[i + 1], rgb[i + 2])

    text = Text(no_wrap=True, overflow="crop")
    for y in range(0, height, 2):
        for x in range(width):
            top = pixel(x, y)
            bottom = pixel(x, y + 1) if y + 1 < height else top
            text.append("▀", Style(color=top, bgcolor=bottom))
        if y + 2 < height:
            text.append("\n")
    return text


@dataclass(frozen=True)
class CameraSource:
    entity_id: str
    name: str
    url: str
    token: str
    context: ssl.SSLContext | None
    interval: float
    live_interval: float


class CameraFeed(Static):
    """Polls snapshots into a half-block image. `rows=None` fills the available height."""

    def __init__(self, source: CameraSource, interval: float, rows: int | None) -> None:
        super().__init__("Loading…", classes="picture", markup=False)
        self.source = source
        self.interval = interval
        self.rows = rows

    def on_mount(self) -> None:
        _ = self.poll()

    @work(exclusive=True)
    async def poll(self) -> None:
        source = self.source
        failures = 0
        while True:
            try:
                data = await asyncio.to_thread(
                    fetch_snapshot, source.url, source.token, source.context
                )
                columns = max(self.size.width, 8)
                rows = self.rows or max(self.size.height, 3)
                self.update(await asyncio.to_thread(image_to_text, data, columns, rows))
                failures = 0
            except Exception as e:  # noqa: BLE001  # a bad frame must never kill the dashboard
                failures += 1
                logger.warning("Camera %s frame failed: %s", source.entity_id, e)
                self.update("󰗿 Camera unavailable")
            await asyncio.sleep(self.interval * min(2**failures, 8))


@final
class CameraScreen(ModalScreen[None]):
    """Full-screen view with fast polling, opened by clicking a camera card."""

    BINDINGS = [("escape", "dismiss", "Close")]  # noqa: RUF012

    def __init__(self, source: CameraSource) -> None:
        super().__init__()
        self.source = source

    @override
    def compose(self) -> ComposeResult:
        with Vertical(id="camera-modal"):
            yield Static(
                f"󰄀 {self.source.name}  (esc / click to close)", classes="name"
            )
            yield CameraFeed(self.source, self.source.live_interval, rows=None)

    def on_click(self) -> None:
        _ = self.dismiss()


@final
class CameraWidget(Vertical):
    """A camera card row: name plus a slowly refreshing snapshot; click for a live view."""

    def __init__(self, source: CameraSource) -> None:
        super().__init__(classes="camera")
        self.source = source

    @override
    def compose(self) -> ComposeResult:
        yield Static(f"󰄀 {self.source.name}", classes="name", markup=False)
        yield CameraFeed(self.source, self.source.interval, rows=CAMERA_ROWS)

    def on_click(self) -> None:
        _ = self.app.push_screen(CameraScreen(self.source))
