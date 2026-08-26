"""Button platform for Docker Manager."""
from __future__ import annotations

import logging

from homeassistant.helpers.entity import EntityCategory
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ICON_RESTART, ICON_UPDATE, ICON_PRUNE, HA_CONTAINER_NAMES
from .coordinator import DockerCoordinator
from .entity import DockerBaseEntity, DockerContainerEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DockerCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Global buttons attached to main Docker device
    entities: list[ButtonEntity] = [
        DockerPruneButton(coordinator),
        DockerCheckAllUpdatesButton(coordinator),
    ]

    # Per-container buttons
    for name in coordinator.data or {}:
        entities.append(DockerRestartButton(coordinator, name))
        entities.append(DockerPauseButton(coordinator, name))
        entities.append(DockerCheckUpdateButton(coordinator, name))

    async_add_entities(entities)

    def _handle_update() -> None:
        new: list[ButtonEntity] = []
        existing_ids = {e.unique_id for e in entities}
        for name in coordinator.data or {}:
            uid_restart = f"{coordinator.entry_id}_{name}_restart"
            uid_pause   = f"{coordinator.entry_id}_{name}_pause_v3"
            uid_check   = f"{coordinator.entry_id}_{name}_check_update"

            if uid_restart not in existing_ids:
                new.append(DockerRestartButton(coordinator, name))
            if uid_pause not in existing_ids:
                new.append(DockerPauseButton(coordinator, name))
            if uid_check not in existing_ids:
                new.append(DockerCheckUpdateButton(coordinator, name))

        if new:
            async_add_entities(new)
            for e in new:
                entities.append(e)

    coordinator.async_add_listener(_handle_update)


class DockerPruneButton(DockerBaseEntity, ButtonEntity):
    """Button to prune unused Docker images on the host."""

    _attr_icon = ICON_PRUNE
    _attr_name = "Prune Unused Images"

    def __init__(self, coordinator: DockerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_prune_images"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        _LOGGER.info("Prune unused images button pressed")
        res = await self.coordinator.async_prune_images(all_unused=True)
        _LOGGER.info(
            "Prune result: %s image(s) removed, %s bytes reclaimed",
            res.get("ImagesDeleted", 0),
            res.get("SpaceReclaimed", 0),
        )


class DockerCheckAllUpdatesButton(DockerBaseEntity, ButtonEntity):
    """Button to check for updates on all monitored containers."""

    _attr_icon = ICON_UPDATE
    _attr_name = "Check All Updates"

    def __init__(self, coordinator: DockerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_check_all_updates"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        _LOGGER.info("Check all container updates button pressed")
        await self.coordinator.async_check_all_updates()


class DockerRestartButton(DockerContainerEntity, ButtonEntity):
    """Button to restart a Docker container."""

    _attr_icon = ICON_RESTART

    def __init__(self, coordinator: DockerCoordinator, container_name: str) -> None:
        super().__init__(coordinator, container_name)
        self._attr_unique_id = f"{coordinator.entry_id}_{container_name}_restart"
        self._attr_name = "Restart"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        if self._container_name.lower() in HA_CONTAINER_NAMES:
            _LOGGER.warning("Refusing to restart HA container '%s'", self._container_name)
            return
        await self.coordinator.async_restart_container(self._container_name)
        await self.coordinator.async_request_refresh()


class DockerPauseButton(DockerContainerEntity, ButtonEntity):
    """Button to pause or unpause a Docker container (toggle)."""

    def __init__(self, coordinator: DockerCoordinator, container_name: str) -> None:
        super().__init__(coordinator, container_name)
        self._attr_unique_id = f"{coordinator.entry_id}_{container_name}_pause_v3"
        self._attr_name = "Pause"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:pause-circle"

    async def async_press(self) -> None:
        if self._container_name.lower() in HA_CONTAINER_NAMES:
            _LOGGER.warning("Refusing to pause/unpause HA container '%s'", self._container_name)
            return
        cdata = self.coordinator.get_container_data(self._container_name)
        if not cdata:
            return
        if cdata.state == "paused":
            await self.coordinator.async_unpause_container(self._container_name)
        else:
            await self.coordinator.async_pause_container(self._container_name)
        await self.coordinator.async_request_refresh()


class DockerCheckUpdateButton(DockerContainerEntity, ButtonEntity):
    """Button to manually check for a newer image."""

    _attr_icon = ICON_UPDATE

    def __init__(self, coordinator: DockerCoordinator, container_name: str) -> None:
        super().__init__(coordinator, container_name)
        self._attr_unique_id = f"{coordinator.entry_id}_{container_name}_check_update"
        self._attr_name = "Check for Update"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        await self.coordinator.async_check_update(self._container_name)
