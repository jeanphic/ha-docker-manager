"""Config flow for Docker Manager."""
from __future__ import annotations

import logging
from typing import Any

import aiodocker
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import OptionsFlowWithReload
from homeassistant.config_entries import OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
)

from .const import (
    DOMAIN,
    CONF_URL,
    CONF_CONTAINERS_INCLUDE,
    CONF_SCAN_INTERVAL,
    CONF_UPDATE_CHECK_INTERVAL,
    DEFAULT_URL,
    DEFAULT_SCAN_INTERVAL,
    DISABLE_UPDATE_CHECK,
)

_LOGGER = logging.getLogger(__name__)

CONN_TYPE_LOCAL = "local"
CONN_TYPE_REMOTE = "remote"


async def _fetch_container_names(url: str) -> list[str]:
    """Connect to Docker and return sorted list of all container names."""
    client = aiodocker.Docker(url=url)
    try:
        containers = await client.containers.list(all=True)
        names = []
        for c in containers:
            info = await c.show()
            name = info.get("Name", "").lstrip("/")
            if name:
                names.append(name)
        return sorted(names)
    finally:
        await client.close()


class DockerManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Docker Manager."""

    VERSION = 1

    def __init__(self) -> None:
        self._url: str = DEFAULT_URL
        self._scan_interval: int = DEFAULT_SCAN_INTERVAL
        self._available_containers: list[str] = []

    # ------------------------------------------------------------------ #
    # Step 1 — Connection type
    # ------------------------------------------------------------------ #

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose local vs remote connection."""
        if user_input is not None:
            if user_input["connection_type"] == CONN_TYPE_LOCAL:
                self._url = DEFAULT_URL
                return await self.async_step_local()
            return await self.async_step_remote()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("connection_type", default=CONN_TYPE_LOCAL): vol.In(
                        {
                            CONN_TYPE_LOCAL: "Local (Unix socket)",
                            CONN_TYPE_REMOTE: "Remote (TCP / TLS)",
                        }
                    )
                }
            ),
        )

    # ------------------------------------------------------------------ #
    # Step 2a — Local socket
    # ------------------------------------------------------------------ #

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input.get(CONF_URL, DEFAULT_URL)
            containers, error = await self._test_and_list(url)
            if not error:
                self._url = url
                self._scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                self._available_containers = containers
                return await self.async_step_containers()
            errors["base"] = error

        return self.async_show_form(
            step_id="local",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_URL): str,
                    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                        int, vol.Range(min=5, max=300)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"example": "unix:///var/run/docker.sock"},
        )

    # ------------------------------------------------------------------ #
    # Step 2b — Remote TCP
    # ------------------------------------------------------------------ #

    async def async_step_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL]
            containers, error = await self._test_and_list(url)
            if not error:
                self._url = url
                self._scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                self._available_containers = containers
                return await self.async_step_containers()
            errors["base"] = error

        return self.async_show_form(
            step_id="remote",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default="http://192.168.1.x:2375"): str,
                    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                        int, vol.Range(min=5, max=300)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={"example": "http://192.168.1.10:2375"},
        )

    # ------------------------------------------------------------------ #
    # Step 3 — Container selection (multi-select checkboxes)
    # ------------------------------------------------------------------ #

    async def async_step_containers(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user pick which containers to monitor."""
        if user_input is not None:
            selected: list[str] = user_input.get(CONF_CONTAINERS_INCLUDE, [])
            # Empty selection = monitor all
            return self.async_create_entry(
                title=f"Docker ({self._url.split('/')[-1]})",
                data={
                    CONF_URL: self._url,
                    CONF_SCAN_INTERVAL: self._scan_interval,
                    CONF_CONTAINERS_INCLUDE: selected,
                },
            )

        options = [
            SelectOptionDict(value=name, label=name)
            for name in self._available_containers
        ]

        return self.async_show_form(
            step_id="containers",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_CONTAINERS_INCLUDE, default=self._available_containers): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "count": str(len(self._available_containers))
            },
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _test_and_list(url: str) -> tuple[list[str], str | None]:
        """Test connection and return (container_names, error_key|None)."""
        try:
            names = await _fetch_container_names(url)
            return names, None
        except Exception as err:
            _LOGGER.debug("Connection failed for %s: %s", url, err)
            return [], "cannot_connect"

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DockerManagerOptionsFlow:
        return DockerManagerOptionsFlow()


# ------------------------------------------------------------------ #
# Options flow — edit container selection + scan interval after setup
# ------------------------------------------------------------------ #

class DockerManagerOptionsFlow(OptionsFlowWithReload):
    """Allow changing container selection and scan interval after setup.

    Uses OptionsFlowWithReload so HA automatically reloads the integration
    when options are saved — no manual update_listener needed.
    config_entry is injected automatically by HA as a property.
    """

    _available_containers: list[str] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reload container list from Docker and show options."""
        url = self.config_entry.data.get(CONF_URL, DEFAULT_URL)

        # Fetch current container list from Docker
        try:
            self._available_containers = await _fetch_container_names(url)
        except Exception:
            self._available_containers = list(
                self.config_entry.data.get(CONF_CONTAINERS_INCLUDE, [])
            )

        if user_input is not None:
            return self.async_create_entry(title="", data={
                CONF_CONTAINERS_INCLUDE: user_input.get(CONF_CONTAINERS_INCLUDE, []),
                CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                CONF_UPDATE_CHECK_INTERVAL: user_input.get(CONF_UPDATE_CHECK_INTERVAL, DISABLE_UPDATE_CHECK),
            })

        current_include: list[str] = list(
            self.config_entry.options.get(
                CONF_CONTAINERS_INCLUDE,
                self.config_entry.data.get(CONF_CONTAINERS_INCLUDE, self._available_containers),
            )
        )
        current_interval: int = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        # Keep selected containers that may no longer exist in Docker
        # but add any new ones as available options
        all_options = sorted(
            set(self._available_containers) | set(current_include)
        )
        options = [SelectOptionDict(value=n, label=n) for n in all_options]

        current_update_interval: int = self.config_entry.options.get(
            CONF_UPDATE_CHECK_INTERVAL,
            self.config_entry.data.get(CONF_UPDATE_CHECK_INTERVAL, DISABLE_UPDATE_CHECK),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CONTAINERS_INCLUDE, default=current_include
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_interval
                    ): vol.All(int, vol.Range(min=5, max=300)),
                    vol.Optional(
                        CONF_UPDATE_CHECK_INTERVAL, default=current_update_interval
                    ): vol.All(int, vol.Range(min=0, max=86400)),
                    vol.Optional(
                        "notify_on_down",
                        default=self.config_entry.options.get(
                            "notify_on_down",
                            self.config_entry.data.get("notify_on_down", False),
                        ),
                    ): bool,
                    vol.Optional(
                        "enable_logs",
                        default=self.config_entry.options.get(
                            "enable_logs",
                            self.config_entry.data.get("enable_logs", False),
                        ),
                    ): bool,
                    vol.Optional(
                        "logs_tail",
                        default=int(self.config_entry.options.get(
                            "logs_tail",
                            self.config_entry.data.get("logs_tail", 50),
                        )),
                    ): vol.All(int, vol.Range(min=10, max=500)),
                }
            ),
            description_placeholders={
                "count": str(len(all_options))
            },
        )
