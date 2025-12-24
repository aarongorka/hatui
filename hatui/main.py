#!/usr/bin/env python
import logging
import os

from textual.logging import TextualHandler

from .dashboard import HomeAssistantDashboard

logging.basicConfig(
    level=logging.INFO,
    handlers=[TextualHandler()],
)
logger = logging.getLogger(__name__)

url = os.environ["HATUI_WS_URL"]
token = os.environ["HATUI_TOKEN"]


def get_dashboard():
    """To be used with `textual run --dev main:run`"""

    dashboard = HomeAssistantDashboard(url, token)
    return dashboard


def run():
    """CLI entrypoint."""

    dashboard = get_dashboard()
    _ = dashboard.run()


if __name__ == "__main__":
    run()
