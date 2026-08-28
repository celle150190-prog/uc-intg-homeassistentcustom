#!/usr/bin/env python3
"""Standalone Home Assistant custom-command integration for Unfolded Circle."""

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp
import ucapi

_LOG = logging.getLogger("homeassistantcustom")

CONFIG_FILE = os.path.join(os.getenv("UC_CONFIG_HOME", "."), "homeassistantcustom.json")
ENTITY_ID = "stehlampe"
ENTITY_NAME = "Stehlampe"
HA_DEFAULT_URL = "ws://homeassistant.local:8123/api/websocket"

COMMANDS = {
    "EIN_AUS": "EIN/AUS",
    "HELLER": "HELLER",
    "DUNKLER": "DUNKLER",
    "MODUS": "MODUS",
}


def load_config() -> dict[str, Any]:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {
            "ha_url": HA_DEFAULT_URL,
            "ha_token": "",
            "ha_remote_entity": "remote.broadlink",
            "area_id": "wohnzimmer",
            "device": "Stehlampe",
            "delay_secs": 0.4,
        }


class HomeAssistantClient:
    """Small Home Assistant WebSocket API client."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.session: aiohttp.ClientSession | None = None
        self.msg_id = 0
        self.authenticated = False

    async def connect(self) -> None:
        if self.ws and not self.ws.closed and self.authenticated:
            return

        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.cfg.get("ha_url", HA_DEFAULT_URL))

        hello = await self.ws.receive_json()
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected Home Assistant websocket response: {hello}")

        await self.ws.send_json({
            "type": "auth",
            "access_token": self.cfg.get("ha_token", ""),
        })
        auth = await self.ws.receive_json()
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"Home Assistant authentication failed: {auth}")
        self.authenticated = True

    async def call_service(self, command: str) -> None:
        await self.connect()
        self.msg_id += 1
        payload = {
            "id": self.msg_id,
            "type": "call_service",
            "domain": "remote",
            "service": "send_command",
            "target": {
                "entity_id": self.cfg.get("ha_remote_entity", "remote.broadlink"),
            },
            "service_data": {
                "delay_secs": float(self.cfg.get("delay_secs", 0.4)),
                "hold_secs": 0,
                "device": self.cfg.get("device", "Stehlampe"),
                "command": command,
            },
        }
        await self.ws.send_json(payload)

        while True:
            response = await self.ws.receive_json()
            if response.get("id") != self.msg_id:
                continue
            if response.get("success") is False:
                raise RuntimeError(str(response))
            return

    async def close(self) -> None:
        self.authenticated = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session and not self.session.closed:
            await self.session.close()


CONFIG = load_config()
HA = HomeAssistantClient(CONFIG)
LOOP = asyncio.new_event_loop()
API = ucapi.IntegrationAPI(LOOP)


def command_handler_factory():
    async def handler(entity: ucapi.Remote, cmd_id: str, params: dict[str, Any] | None) -> ucapi.StatusCodes:
        del entity, params

        command = COMMANDS.get(cmd_id)
        if command is None:
            _LOG.error("Unknown command: %s", cmd_id)
            return ucapi.StatusCodes.NOT_IMPLEMENTED

        try:
            await HA.call_service(command)
            _LOG.info("Sent %s to Home Assistant", command)
            return ucapi.StatusCodes.OK
        except Exception:
            _LOG.exception("Failed to send %s to Home Assistant", command)
            return ucapi.StatusCodes.SERVICE_UNAVAILABLE

    return handler


@API.listens_to(ucapi.Events.CONNECT)
async def on_connect(_websocket) -> None:
    _LOG.info("Remote connected")
    await API.set_device_state(ucapi.DeviceStates.CONNECTED)


@API.listens_to(ucapi.Events.DISCONNECT)
async def on_disconnect() -> None:
    _LOG.info("Remote disconnected")
    await API.set_device_state(ucapi.DeviceStates.DISCONNECTED)


@API.listens_to(ucapi.Events.CLIENT_CONNECTED)
async def on_client_connected() -> None:
    _LOG.debug("Remote websocket client connected")


@API.listens_to(ucapi.Events.CLIENT_DISCONNECTED)
async def on_client_disconnected() -> None:
    _LOG.debug("Remote websocket client disconnected")


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("UC_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    definition = ucapi.Remote(
        identifier=ENTITY_ID,
        name={"en": ENTITY_NAME, "de": ENTITY_NAME},
        features=[],
        attributes={},
        simple_commands=list(COMMANDS.keys()),
        cmd_handler=command_handler_factory(),
        icon="uc:lightbulb",
        description={
            "en": "Custom Home Assistant control for the floor lamp",
            "de": "Eigene Home-Assistant-Steuerung für die Stehlampe",
        },
    )
    API.available_entities.add(definition)

    _LOG.info("Home Assistant Custom integration started")
    await API.init()

    try:
        await LOOP.run_in_executor(None, lambda: None)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        LOOP.run_until_complete(main())
        LOOP.run_forever()
    finally:
        LOOP.run_until_complete(HA.close())
        LOOP.close()
