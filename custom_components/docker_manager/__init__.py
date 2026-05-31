"""Docker Manager - Home Assistant Integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
import voluptuous as vol

from .const import DOMAIN, PLATFORMS, CONF_URL, CONF_CONTAINERS_INCLUDE, DEFAULT_URL
from .coordinator import DockerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Docker Manager from a config entry."""
    url = entry.data.get(CONF_URL, DEFAULT_URL)

    # included_containers: from options (if changed after setup) or initial data
    # Empty list = monitor all containers
    included_containers: list[str] = list(
        entry.options.get(
            CONF_CONTAINERS_INCLUDE,
            entry.data.get(CONF_CONTAINERS_INCLUDE, []),
        )
    )

    coordinator = DockerCoordinator(
        hass, url, entry.entry_id, included_containers=included_containers
    )

    try:
        await coordinator.async_connect()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to Docker: {err}") from err

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload integration when options change (container selection updated)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # --- Service: prune unused images ---
    async def handle_prune(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id", entry.entry_id)
        coord: DockerCoordinator = hass.data[DOMAIN].get(entry_id, coordinator)
        result = await coord.async_prune_images()
        _LOGGER.info(
            "Docker prune completed: %s images deleted, %s bytes reclaimed",
            len(result.get("ImagesDeleted") or []),
            result.get("SpaceReclaimed", 0),
        )

    hass.services.async_register(
        DOMAIN,
        "prune_images",
        handle_prune,
        schema=vol.Schema({vol.Optional("entry_id"): str}),
    )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: DockerCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()

    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, "prune_images")

    return unload_ok
