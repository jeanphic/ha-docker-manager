"""Button platform for Docker Manager - restart containers."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ICON_RESTART, HA_CONTAINER_NAMES
from .coordinator import DockerCoordinator
from .entity import DockerContainerEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DockerCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        DockerRestartButton(coordinator, name)
        for name in coordinator.data or {}
    ]
    async_add_entities(entities)

    def _handle_update() -> None:
        new = []
        existing_ids = {e.unique_id for e in entities}
        for name in coordinator.data or {}:
            uid = f"{coordinator.entry_id}_{name}_restart"
            if uid not in existing_ids:
                new.append(DockerRestartButton(coordinator, name))
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

    async def async_press(self) -> None:
        """Restart the container."""
        if self._container_name.lower() in HA_CONTAINER_NAMES:
            _LOGGER.warning(
                "Refusing to restart Home Assistant container '%s'",
                self._container_name,
            )
            return
        await self.coordinator.async_restart_container(self._container_name)
        await self.coordinator.async_request_refresh()
