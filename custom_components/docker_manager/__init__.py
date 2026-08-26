"""Docker Manager - Home Assistant Integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
import voluptuous as vol

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_URL,
    CONF_CONTAINERS_INCLUDE,
    CONF_SCAN_INTERVAL,
    CONF_UPDATE_CHECK_INTERVAL,
    DEFAULT_URL,
    DEFAULT_SCAN_INTERVAL,
    DISABLE_UPDATE_CHECK,
)
from .coordinator import DockerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Docker Manager from a config entry."""
    url = entry.data.get(CONF_URL, DEFAULT_URL)

    included_containers: list[str] = list(
        entry.options.get(
            CONF_CONTAINERS_INCLUDE,
            entry.data.get(CONF_CONTAINERS_INCLUDE, []),
        )
    )
    scan_interval: int = int(
        entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
    )

    update_check_interval: int = int(
        entry.options.get(
            CONF_UPDATE_CHECK_INTERVAL,
            entry.data.get(CONF_UPDATE_CHECK_INTERVAL, DISABLE_UPDATE_CHECK),
        )
    )

    coordinator = DockerCoordinator(
        hass,
        url,
        entry.entry_id,
        included_containers=included_containers,
        scan_interval=scan_interval,
        update_check_interval=update_check_interval,
    )

    try:
        await coordinator.async_connect()
    except Exception as err:
        raise ConfigEntryNotReady(f"Cannot connect to Docker: {err}") from err

    await coordinator.async_config_entry_first_refresh()

    # Restore container states from before HA restart
    await coordinator.async_restore_container_states()

    # Start container state watcher for down notifications (if enabled)
    notify_on_down: bool = entry.options.get(
        "notify_on_down",
        entry.data.get("notify_on_down", False),
    )
    if notify_on_down:
        from .notify import ContainerStateWatcher
        watcher = ContainerStateWatcher(hass, coordinator)
        watcher.start()
        entry.async_on_unload(watcher.stop)
        _LOGGER.info("Container down notifications enabled")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- Service: prune unused images ---
    async def handle_prune(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        all_unused = call.data.get("all_unused", True)
        remove_stopped = call.data.get("remove_stopped_containers", False)
        if entry_id and entry_id in hass.data[DOMAIN]:
            coord: DockerCoordinator = hass.data[DOMAIN][entry_id]
        else:
            coord = coordinator

        result = await coord.async_prune_images(
            all_unused=all_unused,
            remove_stopped_containers=remove_stopped,
        )
        deleted = result.get("ImagesDeleted", 0)
        reclaimed_mb = round(result.get("SpaceReclaimed", 0) / (1024 * 1024), 2)
        stopped = result.get("StoppedContainers", [])
        total_remaining = result.get("ImagesTotal", coord.images_total)

        if deleted > 0:
            msg = f"🧹 **Prune réussi** : {deleted} image(s) supprimée(s), {reclaimed_mb} MB libérés.\nTotal images restantes : {total_remaining}."
        else:
            msg = f"ℹ️ **Prune terminé** : 0 image supprimée.\nTotal images restantes : {total_remaining}."

        if stopped:
            msg += f"\n\n⚠️ **{len(stopped)} conteneur(s) arrêté(s) détecté(s)** ({', '.join(stopped)}). Docker refuse de supprimer les images rattachées à des conteneurs arrêtés. Activez `remove_stopped_containers: true` pour les nettoyer."

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "🐳 Docker Prune",
                "message": msg,
                "notification_id": f"docker_prune_result_{coord.entry_id}",
            },
        )

    # --- Service: check all updates ---
    async def handle_check_all_updates(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        if entry_id and entry_id in hass.data[DOMAIN]:
            coord: DockerCoordinator = hass.data[DOMAIN][entry_id]
        else:
            coord = coordinator

        await coord.async_check_all_updates()

    hass.services.async_register(
        DOMAIN,
        "prune_images",
        handle_prune,
        schema=vol.Schema({
            vol.Optional("entry_id"): str,
            vol.Optional("all_unused", default=True): bool,
            vol.Optional("remove_stopped_containers", default=False): bool,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        "check_all_updates",
        handle_check_all_updates,
        schema=vol.Schema({
            vol.Optional("entry_id"): str,
        }),
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: DockerCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()

    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, "prune_images")
        hass.services.async_remove(DOMAIN, "check_all_updates")

    return unload_ok
