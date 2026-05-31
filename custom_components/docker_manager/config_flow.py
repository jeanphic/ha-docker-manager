"""Config flow for Docker Manager."""
from __future__ import annotations

import logging
from typing import Any

import aiodocker
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_URL,
    CONF_CONTAINERS_EXCLUDE,
    CONF_SCAN_INTERVAL,
    DEFAULT_URL,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

CONN_TYPE_LOCAL = "local"
CONN_TYPE_REMOTE = "remote"


class DockerManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Docker Manager."""

    VERSION = 1

    def __init__(self) -> None:
        self._conn_type: str = CONN_TYPE_LOCAL
        self._url: str = DEFAULT_URL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Choose connection type."""
        if user_input is not None:
            self._conn_type = user_input["connection_type"]
            if self._conn_type == CONN_TYPE_LOCAL:
                self._url = DEFAULT_URL
                return await self.async_step_local()
            return await self.async_step_remote()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("connection_type", default=CONN_TYPE_LOCAL): vol.In(
                        {
                            CONN_TYPE_LOCAL: "Local (socket Unix)",
                            CONN_TYPE_REMOTE: "Remote (TCP / TLS)",
                        }
                    )
                }
            ),
        )

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2a: Local socket config."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input.get(CONF_URL, DEFAULT_URL)
            error = await self._test_connection(url)
            if not error:
                return self.async_create_entry(
                    title=f"Docker (local)",
                    data={
                        CONF_URL: url,
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="local",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_URL): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): vol.All(int, vol.Range(min=5, max=300)),
                }
            ),
            errors=errors,
            description_placeholders={
                "example": "unix:///var/run/docker.sock"
            },
        )

    async def async_step_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2b: Remote TCP config."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL]
            error = await self._test_connection(url)
            if not error:
                return self.async_create_entry(
                    title=f"Docker ({url})",
                    data={
                        CONF_URL: url,
                        CONF_SCAN_INTERVAL: user_input.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    },
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="remote",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default="http://192.168.1.x:2375"): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                    ): vol.All(int, vol.Range(min=5, max=300)),
                }
            ),
            errors=errors,
            description_placeholders={
                "example": "http://192.168.1.10:2375 ou tcp://192.168.1.10:2376"
            },
        )

    @staticmethod
    async def _test_connection(url: str) -> str | None:
        """Try connecting to Docker. Returns error key or None on success."""
        try:
            client = aiodocker.Docker(url=url)
            await client.system.info()
            await client.close()
            return None
        except Exception as err:
            _LOGGER.debug("Connection test failed for %s: %s", url, err)
            return "cannot_connect"

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DockerManagerOptionsFlow:
        return DockerManagerOptionsFlow(config_entry)


class DockerManagerOptionsFlow(config_entries.OptionsFlow):
    """Options flow to adjust settings after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(int, vol.Range(min=5, max=300)),
                    vol.Optional(
                        CONF_CONTAINERS_EXCLUDE,
                        default=current.get(CONF_CONTAINERS_EXCLUDE, ""),
                    ): str,
                }
            ),
            description_placeholders={
                "example_exclude": "portainer, traefik, watchtower"
            },
        )
