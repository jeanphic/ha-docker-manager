"""Button platform for Docker Manager."""
from __future__ import annotations

import logging

from homeassistant.helpers.entity import EntityCategory
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ICON_RESTART, ICON_UPDATE, HA_CONTAINER_NAMES
from .coordinator import DockerCoordinator
from .entity import DockerContainerEntity

_LOGGER = logging.getLogger(__name__)

BUTTON_CLASSES = [
    ("restart",      "DockerRestartButton"),
    ("pause",        "DockerPauseButton"),
    ("check_update", "DockerCheckUpdateButton"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DockerCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Clean up stale entities from previous naming (e.g. button.xxx_pause_unpause)
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    stale_suffixes = ["_pause_unpause"]
    for entity_entry in list(registry.entities.values()):
        if entity_entry.config_entry_id == entry.entry_id:
            for suffix in stale_suffixes:
                if entity_entry.entity_id.endswith(suffix):
                    _LOGGER.info("Removing stale entity: %s", entity_entry.entity_id)
                    registry.async_remove(entity_entry.entity_id)
                    break

    entities: list[ButtonEntity] = []
    for name in coordinator.data or {}:
        entities.append(DockerRestartButton(coordinator, name))
        entities.append(DockerPauseButton(coordinator, name))
        entities.append(DockerCheckUpdateButton(coordinator, name))

    async_add_entities(entities)

    def _handle_update() -> None:
        new = []
        existing_ids = {e.unique_id for e in entities}
        for name in coordinator.data or {}:
            for cls, suffix in [
                (DockerRestartButton, "restart"),
                (DockerPauseButton, "pause"),
                (DockerCheckUpdateButton, "check_update"),
            ]:
                uid = f"{coordinator.entry_id}_{name}_{suffix}"
                if uid not in existing_ids:
                    new.append(cls(coordinator, name))
        if new:
            async_add_entities(new)

    coordinator.async_add_listener(_handle_update)


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
            _LOGGER.warning("Refusing to restart Home Assistant container '%s'", self._container_name)
            return
        await self.coordinator.async_restart_container(self._container_name)
        await self.coordinator.async_request_refresh()


class DockerPauseButton(DockerContainerEntity, ButtonEntity):
    """Button to pause or unpause a Docker container (toggle)."""

    def __init__(self, coordinator: DockerCoordinator, container_name: str) -> None:
        super().__init__(coordinator, container_name)
        self._attr_unique_id = f"{coordinator.entry_id}_{container_name}_pause"
        self._attr_name = "Pause"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:pause-circle"

    async def async_press(self) -> None:
        if self._container_name.lower() in HA_CONTAINER_NAMES:
            _LOGGER.warning("Refusing to pause/unpause Home Assistant container '%s'", self._container_name)
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
