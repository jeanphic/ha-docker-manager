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
from .coordinator import DockerCoordinator
from .entity import DockerContainerEntity

_LOGGER = logging.getLogger(__name__)

# Update steps: (progress_percent, label)
UPDATE_STEPS = [
    (10, "⏳ Pulling image..."),
    (35, "⏳ Pulling image..."),
    (55, "⏸️ Stopping container..."),
    (70, "🗑️ Removing old container..."),
    (85, "🔨 Creating new container..."),
    (95, "▶️ Starting container..."),
]


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
        self._in_progress: bool | int = False
        self._step_label: str = ""

    @property
    def title(self) -> str:
        data = self.container_data
        return data.image if data else self._container_name

    @property
    def installed_version(self) -> str | None:
        data = self.container_data
        if not data:
            return None
        return data.local_digest[:12] if data.local_digest else "local"

    @property
    def latest_version(self) -> str | None:
        data = self.container_data
        if not data:
            return None
        if not data.update_available:
            return self.installed_version
        return data.latest_digest[:12] if data.latest_digest else "latest"

    @property
    def in_progress(self) -> bool | int:
        return self._in_progress

    @property
    def release_summary(self) -> str | None:
        # Show step label during update, last check otherwise
        if self._step_label:
            return self._step_label
        data = self.container_data
        if not data:
            return None
        if data.last_update_check:
            return f"Last checked: {data.last_update_check.strftime('%Y-%m-%d %H:%M')}"
        return "Click 'Check for Update' to verify availability."

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

    async def _set_step(self, percent: int, label: str) -> None:
        """Update progress percent and step label, then push state to HA."""
        self._in_progress = percent
        self._step_label = label
        self.async_write_ha_state()

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Pull latest image and recreate the container with step-by-step progress."""
        if self._container_name.lower() in HA_CONTAINER_NAMES:
            _LOGGER.warning(
                "Refusing to update Home Assistant container '%s'",
                self._container_name,
            )
            return

        try:
            await self._set_step(10, "⏳ Pulling image...")
            await self.coordinator.async_update_container(
                self._container_name,
                progress_callback=self._set_step,
            )
            await self._set_step(100, "✅ Update complete")

        except Exception as err:
            _LOGGER.error("Update failed for %s: %s", self._container_name, err)
            self._step_label = f"❌ Update failed: {err}"
            self._in_progress = False
            self.async_write_ha_state()
            return

        finally:
            # Reset progress after a short delay so user sees "complete"
            import asyncio
            await asyncio.sleep(3)
            self._in_progress = False
            self._step_label = ""
            self.async_write_ha_state()

    async def async_check_for_update(self) -> None:
        """Manually trigger an update check for this container."""
        await self.coordinator.async_check_update(self._container_name)
