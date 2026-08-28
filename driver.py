#!/usr/bin/env python3
"""Standalone Home Assistant command integration for Unfolded Circle Remote 3."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp
import ucapi
from ucapi import remote
from ucapi.ui import Buttons, Size, UiPage, create_btn_mapping, create_ui_text

_LOG = logging.getLogger("homeassistantcustom")

DRIVER_CONFIG_DIR = Path(os.getenv("UC_CONFIG_HOME", "."))
CONFIG_FILE = DRIVER_CONFIG_DIR / "homeassistantcustom.json"
DRIVER_JSON = Path(__file__).with_name("driver.json")

ENTITY_ID = "stehlampe"
ENTITY_NAME = "Stehlampe"
DEFAULT_HA_URL = "http://homeassistant.local:8123"
DEFAULT_REMOTE_ENTITY = "remote.broadlink"
DEFAULT_DEVICE = "Stehlampe"
DEFAULT_DELAY = 0.4

COMMANDS: dict[str, str] = {
    "EIN_AUS": "EIN/AUS",
    "HELLER": "HELLER",
    "DUNKLER": "DUNKLER",
    "MODUS": "MODUS",
}


def _default_config() -> dict[str, Any]:
    return {
        "setup_complete": False,
        "ha_url": DEFAULT_HA_URL,
        "ha_token": "",
        "ha_remote_entity": DEFAULT_REMOTE_ENTITY,
        "device": DEFAULT_DEVICE,
        "delay_secs": DEFAULT_DELAY,
    }


def load_config() -> dict[str, Any]:
    config = _default_config()
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            config.update(stored)
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("Could not read configuration: %s", exc)
    return config


def save_config(config: dict[str, Any]) -> None:
    DRIVER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = CONFIG_FILE.with_suffix(".tmp")
    with tmp_file.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
    tmp_file.replace(CONFIG_FILE)


def normalize_ha_http_url(value: str) -> str:
    """Normalize a Home Assistant base URL for the REST API."""
    url = value.strip().rstrip("/")
    if url.startswith("ws://"):
        url = f"http://{url[5:]}"
    elif url.startswith("wss://"):
        url = f"https://{url[6:]}"
    elif not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    return url.rstrip("/")


def create_button_mappings() -> list[dict[str, Any]]:
    """Map the physical Remote 3 volume keys to the lamp dimming commands."""
    return [
        create_btn_mapping(Buttons.VOLUME_UP, "HELLER"),
        create_btn_mapping(Buttons.VOLUME_DOWN, "DUNKLER"),
    ]


def create_ui_pages() -> list[UiPage]:
    """Create a dedicated four-button page shown when Stehlampe is opened."""
    page = UiPage("stehlampe", "Stehlampe", grid=Size(4, 6))
    page.add(create_ui_text("EIN/AUS", 0, 0, size=Size(4, 1), cmd="EIN_AUS"))
    page.add(create_ui_text("HELLER", 0, 2, size=Size(2, 1), cmd="HELLER"))
    page.add(create_ui_text("DUNKLER", 2, 2, size=Size(2, 1), cmd="DUNKLER"))
    page.add(create_ui_text("MODUS", 0, 4, size=Size(4, 1), cmd="MODUS"))
    return [page]


class HomeAssistantClient:
    """Minimal authenticated Home Assistant REST API client."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.session: aiohttp.ClientSession | None = None
        self.lock = asyncio.Lock()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    def _headers(self) -> dict[str, str]:
        token = str(self.config.get("ha_token", "")).strip()
        if not token:
            raise RuntimeError("Home Assistant access token is not configured")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _base_url(self) -> str:
        value = str(self.config.get("ha_url", DEFAULT_HA_URL))
        return normalize_ha_http_url(value)

    async def test_connection(self) -> None:
        """Verify HTTP connectivity, authentication and the configured remote entity."""
        async with self.lock:
            session = await self._ensure_session()
            entity_id = str(
                self.config.get("ha_remote_entity", DEFAULT_REMOTE_ENTITY)
            ).strip()
            if not entity_id:
                raise RuntimeError("Home Assistant remote entity is not configured")

            url = f"{self._base_url()}/api/states/{quote(entity_id, safe='')}"
            _LOG.info("Testing Home Assistant connection: %s", url)
            try:
                async with session.get(url, headers=self._headers()) as response:
                    body = await response.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise RuntimeError(f"Could not connect to Home Assistant: {exc}") from exc

            if response.status == 200:
                return
            if response.status == 401:
                raise RuntimeError("Home Assistant access token is invalid")
            if response.status == 404:
                raise RuntimeError(f"Home Assistant entity '{entity_id}' was not found")
            detail = body.strip().replace("\n", " ")[:400]
            raise RuntimeError(
                f"Home Assistant returned HTTP {response.status}"
                + (f": {detail}" if detail else "")
            )

    async def send_remote_command(self, command: str) -> None:
        """Call Home Assistant's remote.send_command service via REST."""
        async with self.lock:
            session = await self._ensure_session()
            url = f"{self._base_url()}/api/services/remote/send_command"
            payload = {
                "entity_id": str(
                    self.config.get("ha_remote_entity", DEFAULT_REMOTE_ENTITY)
                ),
                "delay_secs": float(self.config.get("delay_secs", DEFAULT_DELAY)),
                "hold_secs": 0,
                "device": str(self.config.get("device", DEFAULT_DEVICE)),
                "command": command,
            }
            _LOG.info("Sending Home Assistant command '%s' via %s", command, url)
            try:
                async with session.post(
                    url, headers=self._headers(), json=payload
                ) as response:
                    body = await response.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise RuntimeError(f"Could not connect to Home Assistant: {exc}") from exc

            if 200 <= response.status < 300:
                return
            if response.status == 401:
                raise RuntimeError("Home Assistant access token is invalid")
            detail = body.strip().replace("\n", " ")[:400]
            raise RuntimeError(
                f"Home Assistant returned HTTP {response.status}"
                + (f": {detail}" if detail else "")
            )

    async def close(self) -> None:
        async with self.lock:
            if self.session and not self.session.closed:
                await self.session.close()
            self.session = None


CONFIG = load_config()
HA = HomeAssistantClient(CONFIG)
LOOP = asyncio.new_event_loop()
API = ucapi.IntegrationAPI(LOOP)


def add_stehlampe_entity() -> None:
    """Publish the single Stehlampe remote entity."""
    API.available_entities.clear()
    entity = ucapi.Remote(
        identifier=ENTITY_ID,
        name={"en": ENTITY_NAME, "de": ENTITY_NAME},
        features=[],
        attributes={},
        simple_commands=list(COMMANDS.keys()),
        button_mapping=create_button_mappings(),
        ui_pages=create_ui_pages(),
        cmd_handler=command_handler,
        icon="uc:lightbulb",
        description={
            "en": "Standalone Home Assistant control for the floor lamp",
            "de": "Eigenständige Home-Assistant-Steuerung für die Stehlampe",
        },
    )
    API.available_entities.add(entity)


async def command_handler(
    entity: ucapi.Remote,
    cmd_id: str,
    _params: dict[str, Any] | None,
    _websocket: Any,
) -> ucapi.StatusCodes:
    """Handle Remote 3 entity commands."""
    del entity
    command = COMMANDS.get(cmd_id)
    if command is None:
        _LOG.error("Unsupported command '%s'", cmd_id)
        return ucapi.StatusCodes.BAD_REQUEST

    try:
        await HA.send_remote_command(command)
        _LOG.info("Sent Stehlampe command '%s'", command)
        return ucapi.StatusCodes.OK
    except Exception as exc:
        _LOG.error("Failed to send '%s' to Home Assistant: %s", command, exc)
        return ucapi.StatusCodes.SERVICE_UNAVAILABLE


async def driver_setup_handler(msg: ucapi.SetupDriver) -> ucapi.SetupAction:
    """Handle initial and reconfiguration setup requests."""
    if isinstance(msg, ucapi.DriverSetupRequest):
        setup_data = {str(key): str(value) for key, value in msg.setup_data.items()}
        ha_url = setup_data.get("ha_url", DEFAULT_HA_URL).strip()
        ha_token = setup_data.get("ha_token", "").strip()
        remote_entity = setup_data.get(
            "ha_remote_entity", DEFAULT_REMOTE_ENTITY
        ).strip()
        device = setup_data.get("device", DEFAULT_DEVICE).strip()
        delay_text = setup_data.get("delay_secs", str(DEFAULT_DELAY)).strip()

        if not ha_url or not ha_token:
            return ucapi.SetupError()
        if not remote_entity:
            remote_entity = DEFAULT_REMOTE_ENTITY
        if not device:
            device = DEFAULT_DEVICE

        try:
            delay_secs = float(delay_text)
            if delay_secs < 0 or delay_secs > 10:
                raise ValueError
        except ValueError:
            return ucapi.SetupError()

        new_config = {
            "setup_complete": True,
            "ha_url": ha_url,
            "ha_token": ha_token,
            "ha_remote_entity": remote_entity,
            "device": device,
            "delay_secs": delay_secs,
        }

        test_client = HomeAssistantClient(new_config)
        try:
            await test_client.test_connection()
        except Exception as exc:
            _LOG.error("Home Assistant setup test failed: %s", exc)
            return ucapi.SetupError()
        finally:
            await test_client.close()

        CONFIG.clear()
        CONFIG.update(new_config)
        save_config(CONFIG)
        HA.config = CONFIG
        add_stehlampe_entity()
        _LOG.info("Home Assistant setup completed")
        return ucapi.SetupComplete()

    return ucapi.SetupError()


@API.listens_to(ucapi.Events.CONNECT)
async def on_connect() -> None:
    """Report the driver as connected to the Remote 3."""
    await API.set_device_state(ucapi.DeviceStates.CONNECTED)


@API.listens_to(ucapi.Events.DISCONNECT)
async def on_disconnect() -> None:
    """Report the driver as disconnected and close the HA session."""
    await HA.close()
    await API.set_device_state(ucapi.DeviceStates.DISCONNECTED)


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("UC_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    if CONFIG.get("setup_complete") and CONFIG.get("ha_token"):
        add_stehlampe_entity()
    else:
        API.available_entities.clear()

    LOOP.run_until_complete(API.init(str(DRIVER_JSON), driver_setup_handler))
    try:
        LOOP.run_forever()
    finally:
        LOOP.run_until_complete(HA.close())
        LOOP.close()
