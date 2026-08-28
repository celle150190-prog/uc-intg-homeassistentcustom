#!/usr/bin/env python3
"""Standalone Home Assistant command integration for Unfolded Circle Remote 3."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import aiohttp
import ucapi
from ucapi import remote as uc_remote
from ucapi.ui import Buttons, Size, UiPage, create_btn_mapping, create_ui_text

_LOG = logging.getLogger("stehlampe-ha")

DRIVER_CONFIG_DIR = Path(os.getenv("UC_CONFIG_HOME") or os.getenv("HOME") or "./")
CONFIG_FILE = DRIVER_CONFIG_DIR / "stehlampe-ha.json"

# PyInstaller stores bundled data below sys._MEIPASS (on the Remote this is
# typically /app/_internal). During normal source execution there is no
# _MEIPASS, so the repository-local driver.json is used instead.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DRIVER_JSON = BUNDLE_DIR / "driver.json"

ENTITY_ID = "stehlampe"
ENTITY_NAME = "Stehlampe"
DEFAULT_HA_URL = "http://homeassistant.local:8123"

# These are the four Home Assistant scripts the user already tested successfully.
SCRIPT_ENTITIES: dict[str, str] = {
    "EIN_AUS": "script.ein_aus_stehlampe",
    "HELLER": "script.heller_stehlampe",
    "DUNKLER": "script.dunkler_stehlampe",
    "MODUS": "script.modus_stehlampe",
}


def _default_config() -> dict[str, Any]:
    return {
        "setup_complete": False,
        "ha_url": DEFAULT_HA_URL,
        "ha_token": "",
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
    url = value.strip().rstrip("/")
    if url.startswith("ws://"):
        url = f"http://{url[5:] }"
    elif url.startswith("wss://"):
        url = f"https://{url[6:] }"
    elif not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    return url.rstrip("/")


def create_button_mappings() -> list[dict[str, Any]]:
    """VOL+ and VOL- directly control the lamp brightness."""
    return [
        create_btn_mapping(Buttons.VOLUME_UP, "HELLER"),
        create_btn_mapping(Buttons.VOLUME_DOWN, "DUNKLER"),
    ]


def create_ui_pages() -> list[UiPage]:
    """Four direct controls shown on the Stehlampe device page."""
    page = UiPage("stehlampe", "Stehlampe", grid=Size(4, 6))
    page.add(create_ui_text("EIN/AUS", 0, 0, size=Size(4, 1), cmd="EIN_AUS"))
    page.add(create_ui_text("HELLER", 0, 2, size=Size(2, 1), cmd="HELLER"))
    page.add(create_ui_text("DUNKLER", 2, 2, size=Size(2, 1), cmd="DUNKLER"))
    page.add(create_ui_text("MODUS", 0, 4, size=Size(4, 1), cmd="MODUS"))
    return [page]


class HomeAssistantClient:
    """Small authenticated REST client that triggers the existing HA scripts."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.session: aiohttp.ClientSession | None = None
        self.lock = asyncio.Lock()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
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
        return normalize_ha_http_url(str(self.config.get("ha_url", DEFAULT_HA_URL)))

    async def run_script(self, simple_command: str) -> None:
        script_entity = SCRIPT_ENTITIES.get(simple_command)
        if script_entity is None:
            raise RuntimeError(f"Unknown Stehlampe command: {simple_command}")

        async with self.lock:
            session = await self._ensure_session()
            url = f"{self._base_url()}/api/services/script/turn_on"
            payload = {"entity_id": script_entity}
            _LOG.info(
                "Running Home Assistant script '%s' for command '%s'",
                script_entity,
                simple_command,
            )
            try:
                async with session.post(
                    url, headers=self._headers(), json=payload
                ) as response:
                    body = await response.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                raise RuntimeError(
                    f"Could not connect to Home Assistant: {exc}"
                ) from exc

            if 200 <= response.status < 300:
                return
            if response.status == 401:
                raise RuntimeError("Home Assistant access token is invalid")
            if response.status == 404:
                raise RuntimeError(
                    f"Home Assistant script '{script_entity}' was not found"
                )
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
    """Publish exactly one Remote entity named Stehlampe."""
    API.available_entities.clear()
    entity = ucapi.Remote(
        identifier=ENTITY_ID,
        name={"en": ENTITY_NAME, "de": ENTITY_NAME},
        features=[uc_remote.Features.SEND_CMD],
        attributes={},
        simple_commands=list(SCRIPT_ENTITIES.keys()),
        button_mapping=create_button_mappings(),
        ui_pages=create_ui_pages(),
        cmd_handler=command_handler,
        description={
            "en": "Standalone Home Assistant controls for the floor lamp",
            "de": "Eigenständige Home-Assistant-Steuerung für die Stehlampe",
        },
    )
    API.available_entities.add(entity)


async def command_handler(
    entity: ucapi.Remote,
    cmd_id: str,
    params: dict[str, Any] | None,
    *,
    websocket: Any,
) -> ucapi.StatusCodes:
    """Handle direct commands and the Core-wrapped SEND_CMD form.

    The ``websocket`` keyword is intentionally explicit so ucapi treats this as
    an extended command handler and passes the connection through correctly.
    """
    del entity, websocket

    # Remote Core wraps simple commands used by button mappings/UI elements into
    # the standard `send_cmd` command with params={"command": "<simple_command>"}.
    if cmd_id == uc_remote.Commands.SEND_CMD:
        payload = params or {}
        command = payload.get("command")
        if not isinstance(command, str):
            _LOG.error("SEND_CMD received without a valid simple command: %r", params)
            return ucapi.StatusCodes.BAD_REQUEST
    else:
        command = cmd_id

    if command not in SCRIPT_ENTITIES:
        _LOG.error("Unsupported Stehlampe command '%s'", command)
        return ucapi.StatusCodes.BAD_REQUEST

    try:
        await HA.run_script(command)
        return ucapi.StatusCodes.OK
    except Exception as exc:
        _LOG.error("Failed to run '%s': %s", command, exc)
        return ucapi.StatusCodes.SERVICE_UNAVAILABLE


async def driver_setup_handler(msg: ucapi.SetupDriver) -> ucapi.SetupAction:
    """Validate and store setup data without contacting Home Assistant."""
    if not isinstance(msg, ucapi.DriverSetupRequest):
        return ucapi.SetupError()

    try:
        setup_data = {
            str(key): str(value) for key, value in msg.setup_data.items()
        }
        ha_url = setup_data.get("ha_url", DEFAULT_HA_URL).strip()
        ha_token = setup_data.get("ha_token", "").strip()

        if not ha_url:
            _LOG.error("Setup rejected: Home Assistant URL is empty")
            return ucapi.SetupError()
        if not ha_token:
            _LOG.error("Setup rejected: Home Assistant token is empty")
            return ucapi.SetupError()

        new_config = {
            "setup_complete": True,
            "ha_url": ha_url,
            "ha_token": ha_token,
        }
        CONFIG.clear()
        CONFIG.update(new_config)
        save_config(CONFIG)
        HA.config = CONFIG
        add_stehlampe_entity()
        _LOG.info("Stehlampe setup completed")
        return ucapi.SetupComplete()
    except Exception:
        # Never let a setup exception crash the driver. The Remote Core developer
        # preview has a known failure mode where a failed setup leaves the driver
        # stopped until the custom integration is removed and installed again.
        _LOG.exception("Unexpected exception during Stehlampe setup")
        return ucapi.SetupError()


@API.listens_to(ucapi.Events.CONNECT)
async def on_connect() -> None:
    await API.set_device_state(ucapi.DeviceStates.CONNECTED)


@API.listens_to(ucapi.Events.DISCONNECT)
async def on_disconnect() -> None:
    await HA.close()
    await API.set_device_state(ucapi.DeviceStates.DISCONNECTED)


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("UC_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    if not os.getenv("UC_INTEGRATION_HTTP_PORT"):
        os.environ["UC_INTEGRATION_HTTP_PORT"] = "19123"
        _LOG.warning("UC_INTEGRATION_HTTP_PORT was not set; using fallback port 19123")
    else:
        _LOG.info(
            "Using runtime integration port %s",
            os.getenv("UC_INTEGRATION_HTTP_PORT"),
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
