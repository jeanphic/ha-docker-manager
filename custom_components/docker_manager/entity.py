"""Base entity for Docker Manager."""
from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, ICON_DOCKER
from .coordinator import DockerCoordinator, ContainerData


def _host_device_id(coordinator: DockerCoordinator) -> str | None:
    """Return the device-registry id of the Docker host device.

    Recent Home Assistant versions deprecate ``via_device`` (an identifier
    tuple) in favour of ``via_device_id`` (the registry id). Returns None on
    older versions, or when the host device is not registered yet.
    """
    registry = dr.async_get(coordinator.hass)
    lookup = getattr(registry, "async_get_device_by_identifier", None)
    if lookup is None:
        return None
    device = lookup((DOMAIN, coordinator.entry_id), coordinator.entry_id)
    return device.id if device else None


class DockerBaseEntity(CoordinatorEntity[DockerCoordinator]):
    """Base class for all Docker Manager entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DockerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry_id)},
            name="Docker Host",
            manufacturer="Docker Inc.",
            model=f"Docker Engine {coordinator.docker_version}",
            sw_version=coordinator.docker_version,
        )


class DockerContainerEntity(CoordinatorEntity[DockerCoordinator]):
    """Base class for per-container entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DockerCoordinator, container_name: str) -> None:
        super().__init__(coordinator)
        self._container_name = container_name
        info: dict = {
            "identifiers": {(DOMAIN, f"{coordinator.entry_id}_{container_name}")},
            "name": container_name,
            "manufacturer": "Docker",
            "model": "Container",
        }
        host_id = _host_device_id(coordinator)
        if host_id:
            info["via_device_id"] = host_id
        else:  # older Home Assistant, or host device not registered yet
            info["via_device"] = (DOMAIN, coordinator.entry_id)
        self._attr_device_info = DeviceInfo(**info)

    @property
    def container_data(self) -> ContainerData | None:
        return self.coordinator.get_container_data(self._container_name)

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.container_data is not None
        )
