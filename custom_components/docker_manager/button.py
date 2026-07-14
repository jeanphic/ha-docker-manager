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

    # Clean up stale entities and fix wrong entity_ids from previous versions
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)

    # Unique_id suffixes to remove (old naming schemes)
    stale_unique_suffixes = ["_pause_unpause", "_pause", "_pause_v2"]
    # Entity_id suffixes that indicate a wrong name was used
    wrong_entity_suffixes = ["_pause_unpause"]

    for entity_entry in list(registry.entities.values()):
        if entity_entry.config_entry_id != entry.entry_id:
            continue
        uid = entity_entry.unique_id or ""
        eid = entity_entry.entity_id

        # Remove truly stale unique_ids (old versions)
        if any(uid.endswith(s) for s in stale_unique_suffixes):
            _LOGGER.info("Removing stale entity: %s (unique_id=%s)", eid, uid)
            registry.async_remove(eid)
            continue

        # Fix entity_id if it has a wrong suffix (e.g. _pause_unpause)
        if any(eid.endswith(s) for s in wrong_entity_suffixes):
            _LOGGER.info("Removing wrong entity_id: %s", eid)
            registry.async_remove(eid)
            continue

        # Fix entity_id with wrong area prefix (e.g. button.zone_xxx_pause → button.xxx_pause)
        # If unique_id ends with _pause_v3, ensure entity_id ends with _pause
        if uid.endswith("_pause_v3"):
            # Extract container name from unique_id: {entry_id}_{container}_pause_v3
            prefix = f"{entry.entry_id}_"
            if uid.startswith(prefix):
                container = uid[len(prefix):].replace("_pause_v3", "")
                expected_eid = f"button.{container}_pause"
                if eid != expected_eid:
                    _LOGGER.info(
                        "Fixing entity_id: %s → %s", eid, expected_eid
                    )
                    registry.async_remove(eid)

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
        self._attr_unique_id = f"{coordinator.entry_id}_{container_name}_pause_v3"
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
