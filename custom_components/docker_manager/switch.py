"""Switch platform for Docker Manager - start/stop containers."""
from __future__ import annotations

import logging

from homeassistant.helpers.entity import EntityCategory
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ICON_CONTAINER, HA_CONTAINER_NAMES
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
        DockerContainerSwitch(coordinator, name)
        for name in coordinator.data or {}
    ]
    async_add_entities(entities)

    def _handle_update() -> None:
        new = []
        existing_ids = {e.unique_id for e in entities}
        for name in coordinator.data or {}:
            uid = f"{entry.entry_id}_{name}_switch"
            if uid not in existing_ids:
                new.append(DockerContainerSwitch(coordinator, name))
        if new:
            async_add_entities(new)

    coordinator.async_add_listener(_handle_update)


class DockerContainerSwitch(DockerContainerEntity, SwitchEntity):
    """Switch to start/stop a Docker container."""

    _attr_icon = ICON_CONTAINER

    def __init__(self, coordinator: DockerCoordinator, container_name: str) -> None:
        super().__init__(coordinator, container_name)
        self._attr_unique_id = f"{coordinator.entry_id}_{container_name}_switch"
        self._attr_name = "Container"
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        if not self.container_data:
            return False
        return self.container_data.state == "running"

    @property
    def icon(self) -> str:
        return "mdi:play-circle" if self.is_on else "mdi:stop-circle"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.container_data
        if not data:
            return {}
        return {
            "state": data.state,
            "status": data.status,
            "image": data.image,
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Start the container."""
        await self.coordinator.async_start_container(self._container_name)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Stop the container (blocked for HA itself)."""
        if self._container_name.lower() in HA_CONTAINER_NAMES:
            _LOGGER.warning(
                "Refusing to stop Home Assistant container '%s'",
                self._container_name,
            )
            return
        await self.coordinator.async_stop_container(self._container_name)
        await self.coordinator.async_request_refresh()
