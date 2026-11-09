#!/usr/bin/env python
import logging
import os
from typing import Annotated

import typer

from .dashboard import HomeAssistantDashboard

logger = logging.getLogger(__name__)

url = os.environ["HATUI_WS_URL"]
token = os.environ["HATUI_TOKEN"]


def get_dashboard(insecure: bool = False):
    """To be used with `textual run --dev main:run`"""

    dashboard = HomeAssistantDashboard(url, token, insecure=insecure)
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

    dashboard = get_dashboard(insecure)
    _ = dashboard.run()


if __name__ == "__main__":
    app()
