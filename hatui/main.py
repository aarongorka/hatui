#!/usr/bin/env python
import logging
import os

from textual.logging import TextualHandler

from .dashboard import HomeAssistantDashboard
from .entities import HomeAssistant

logging.basicConfig(
    level=logging.INFO,
    handlers=[TextualHandler()],
)
logger = logging.getLogger(__name__)

url = os.environ["HATUI_WS_URL"]
token = os.environ["HATUI_TOKEN"]


def run():
    """To be used with `textual run --dev main:run`"""

    dashboard = HomeAssistantDashboard(url, token)
    return dashboard


if __name__ == "__main__":
    hass = HomeAssistant(url, token)
    websocket = hass.websocket
    # debuggy stuff goes here
