"""Update platform for Docker Manager - detect and apply image updates."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ICON_UPDATE, HA_CONTAINER_NAMES
from .coordinator import DockerCoordinator, ContainerData
from .entity import DockerContainerEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DockerCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        DockerContainerUpdate(coordinator, name)
        for name in coordinator.data or {}
    ]
    async_add_entities(entities)

    def _handle_update() -> None:
        new = []
        existing_ids = {e.unique_id for e in entities}
        for name in coordinator.data or {}:
            uid = f"{coordinator.entry_id}_{name}_update"
            if uid not in existing_ids:
                new.append(DockerContainerUpdate(coordinator, name))
        if new:
            async_add_entities(new)

    coordinator.async_add_listener(_handle_update)


class DockerContainerUpdate(DockerContainerEntity, UpdateEntity):
    """Update entity for a Docker container image."""

    _attr_icon = ICON_UPDATE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
    )
    _attr_auto_update = False

    def __init__(self, coordinator: DockerCoordinator, container_name: str) -> None:
        super().__init__(coordinator, container_name)
        self._attr_unique_id = f"{coordinator.entry_id}_{container_name}_update"
        self._attr_name = "Update"
        self._in_progress: bool = False

    @property
    def title(self) -> str:
        data = self.container_data
        return data.image if data else self._container_name

    @property
    def installed_version(self) -> str | None:
        data = self.container_data
        if not data:
            return None
        # Show short digest or "local"
        if data.local_digest:
            return data.local_digest[:12]
        return "local"

    @property
    def latest_version(self) -> str | None:
        data = self.container_data
        if not data:
            return None
        if not data.update_available:
            # No update known yet or up to date
            return self.installed_version
        if data.latest_digest:
            return data.latest_digest[:12]
        return "latest"

    @property
    def update_percentage(self) -> int | None:
        return 50 if self._in_progress else None

    @property
    def in_progress(self) -> bool:
        return self._in_progress

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.container_data
        if not data:
            return {}
        return {
            "image": data.image,
            "local_digest": data.local_digest,
            "remote_digest": data.latest_digest,
            "last_check": (
                data.last_update_check.isoformat()
                if data.last_update_check
                else None
            ),
        }

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Pull latest image and recreate the container."""
        if self._container_name.lower() in HA_CONTAINER_NAMES:
            _LOGGER.warning(
                "Refusing to update Home Assistant container '%s' via Docker Manager",
                self._container_name,
            )
            return

        self._in_progress = True
        self.async_write_ha_state()

        try:
            await self.coordinator.async_update_container(self._container_name)
        finally:
            self._in_progress = False
            self.async_write_ha_state()

    async def async_check_for_update(self) -> None:
        """Manually trigger an update check for this container."""
        data = self.container_data
        if data:
            await self.coordinator._check_container_update(data)
            self.async_write_ha_state()
