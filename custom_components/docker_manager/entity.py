"""Base entity for Docker Manager."""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, ICON_DOCKER
from .coordinator import DockerCoordinator, ContainerData


class DockerBaseEntity(CoordinatorEntity[DockerCoordinator]):
    """Base class for all Docker Manager entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DockerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry_id)},
            name="Docker",
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry_id}_{container_name}")},
            name=container_name,
            manufacturer="Docker",
            model="Container",
            via_device=(DOMAIN, coordinator.entry_id),
        )

    @property
    def container_data(self) -> ContainerData | None:
        return self.coordinator.get_container_data(self._container_name)

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.container_data is not None
        )
