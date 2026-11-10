#!/usr/bin/env python
import logging
import os
from typing import Annotated, cast

import typer

from .dashboard import HomeAssistantDashboard

logger = logging.getLogger(__name__)

url = os.environ["HATUI_WS_URL"]
token = os.environ["HATUI_TOKEN"]


def get_dashboard(
    insecure: bool = False,
    show_cameras: bool = True,
    camera_interval: float = 10.0,
    camera_live_interval: float = 1.0,
):
    """To be used with `textual run --dev main:run`"""

    dashboard = HomeAssistantDashboard(
        url,
        token,
        insecure=insecure,
        show_cameras=show_cameras,
        camera_interval=camera_interval,
        camera_live_interval=camera_live_interval,
    )
    return dashboard


app = typer.Typer(pretty_exceptions_enable=False)


@app.command()
def run(
    enable_file_logging: Annotated[
        bool,
        typer.Option(
            help="Enable outputting logs to hatui.log",
            envvar="HATUI_ENABLE_FILE_LOGGING",
        ),
    ] = False,
    debug: Annotated[
        bool, typer.Option(help="Enable debug logging", envvar="HATUI_DEBUG")
    ] = False,
    insecure: Annotated[
        bool,
        typer.Option(
            help="Skip TLS certificate verification (e.g. self-signed certs, corporate MITM proxies)",
            envvar="HATUI_INSECURE",
        ),
    ] = False,
    cameras: Annotated[
        bool,
        typer.Option(
            help="Show live ASCII-art camera feeds (disable on slow devices like a Pi 1)",
            envvar="HATUI_CAMERAS",
        ),
    ] = True,
    camera_interval: Annotated[
        float,
        typer.Option(
            min=0.2,
            help="Seconds between camera card refreshes",
            envvar="HATUI_CAMERA_INTERVAL",
        ),
    ] = 10.0,
    camera_live_interval: Annotated[
        float,
        typer.Option(
            min=0.2,
            help="Seconds between frames in the camera popup (click a camera)",
            envvar="HATUI_CAMERA_LIVE_INTERVAL",
        ),
    ] = 1.0,
):
    """CLI entrypoint."""

    if enable_file_logging:
        handler = logging.FileHandler("hatui.log")

        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)

    if debug:
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)

    dashboard = get_dashboard(insecure, cameras, camera_interval, camera_live_interval)
    _ = cast("object", dashboard.run())


if __name__ == "__main__":
    app()
