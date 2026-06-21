"""Sensor platform for Docker Manager."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
    EntityCategory,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfInformation,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ICON_DOCKER, ICON_CPU, ICON_MEMORY, ICON_NETWORK, ICON_CONTAINER
from .coordinator import DockerCoordinator, ContainerData
from .entity import DockerBaseEntity, DockerContainerEntity

_LOGGER = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Status helper
# ------------------------------------------------------------------ #

def _format_status(d: ContainerData) -> str | None:
    """Return a human-readable status string from Docker state info.

    Docker's raw 'Status' field (e.g. 'Up 3 days', 'Exited (0) 2 hours ago')
    can be empty for freshly created containers. We build a fallback from state.
    """
    raw = (d.status or "").strip()
    if raw:
        return raw
    # Fallback based on state
    state_labels = {
        "running":    "Running",
        "paused":     "Paused",
        "exited":     "Stopped",
        "dead":       "Dead",
        "created":    "Created",
        "restarting": "Restarting",
        "removing":   "Removing",
    }
    return state_labels.get(d.state, d.state or None)


# ------------------------------------------------------------------ #
# Global Docker sensors
# ------------------------------------------------------------------ #

@dataclass(frozen=True)
class GlobalSensorDescription(SensorEntityDescription):
    value_fn: Any = None


GLOBAL_SENSORS: tuple[GlobalSensorDescription, ...] = (
    GlobalSensorDescription(
        key="containers_total",
        name="Containers Total",
        icon=ICON_DOCKER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.containers_total,
    ),
    GlobalSensorDescription(
        key="containers_running",
        name="Containers Running",
        icon="mdi:play-circle",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.containers_running,
    ),
    GlobalSensorDescription(
        key="containers_stopped",
        name="Containers Stopped",
        icon="mdi:stop-circle",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.containers_stopped,
    ),
    GlobalSensorDescription(
        key="containers_paused",
        name="Containers Paused",
        icon="mdi:pause-circle",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.containers_paused,
    ),
    GlobalSensorDescription(
        key="images_total",
        name="Images Total",
        icon="mdi:layers",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.images_total,
    ),
    GlobalSensorDescription(
        key="docker_version",
        name="Docker Version",
        icon=ICON_DOCKER,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.docker_version,
    ),
)


# ------------------------------------------------------------------ #
# Per-container sensors
# ------------------------------------------------------------------ #

@dataclass(frozen=True)
class ContainerSensorDescription(SensorEntityDescription):
    value_fn: Any = None


CONTAINER_SENSORS: tuple[ContainerSensorDescription, ...] = (

    # --- Capteurs (primary info) ---
    ContainerSensorDescription(
        key="state",
        name="State",
        icon=ICON_CONTAINER,
        # No entity_category → appears in main "Capteurs" section
        value_fn=lambda d: d.state,
    ),
    ContainerSensorDescription(
        key="image",
        name="Image",
        icon="mdi:layers",
        # No entity_category → appears in main "Capteurs" section
        value_fn=lambda d: d.image,
    ),

    # --- Diagnostic ---
    ContainerSensorDescription(
        key="status",
        name="Status",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_format_status,
    ),
    ContainerSensorDescription(
        key="health",
        name="Health",
        icon="mdi:heart-pulse",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.health,
    ),
    ContainerSensorDescription(
        key="uptime",
        name="Started At",
        icon="mdi:clock-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.started_at,
    ),
    ContainerSensorDescription(
        key="cpu_percent",
        name="CPU",
        icon=ICON_CPU,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.cpu_percent,
    ),
    ContainerSensorDescription(
        key="memory_mb",
        name="Memory",
        icon=ICON_MEMORY,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.memory_mb,
    ),
    ContainerSensorDescription(
        key="memory_percent",
        name="Memory %",
        icon=ICON_MEMORY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.memory_percent,
    ),
    ContainerSensorDescription(
        key="net_speed_up",
        name="Network Up",
        icon=ICON_NETWORK,
        native_unit_of_measurement="kB/s",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.net_speed_up,
    ),
    ContainerSensorDescription(
        key="net_speed_down",
        name="Network Down",
        icon=ICON_NETWORK,
        native_unit_of_measurement="kB/s",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.net_speed_down,
    ),
    ContainerSensorDescription(
        key="net_total_up",
        name="Network Total Up",
        icon=ICON_NETWORK,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.net_total_up,
    ),
    ContainerSensorDescription(
        key="net_total_down",
        name="Network Total Down",
        icon=ICON_NETWORK,
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.net_total_down,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator: DockerCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list = []

    for desc in GLOBAL_SENSORS:
        entities.append(DockerGlobalSensor(coordinator, desc))

    for container_name in coordinator.data or {}:
        for desc in CONTAINER_SENSORS:
            entities.append(DockerContainerSensor(coordinator, container_name, desc))

    async_add_entities(entities)

    def _handle_coordinator_update() -> None:
        new_entities = []
        existing = {e.unique_id for e in entities}
        for container_name in coordinator.data or {}:
            for desc in CONTAINER_SENSORS:
                uid = f"{entry.entry_id}_{container_name}_{desc.key}"
                if uid not in existing:
                    new_entities.append(
                        DockerContainerSensor(coordinator, container_name, desc)
                    )
        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(_handle_coordinator_update)


class DockerGlobalSensor(DockerBaseEntity, SensorEntity):
    """A sensor for global Docker stats."""

    entity_description: GlobalSensorDescription

    def __init__(self, coordinator: DockerCoordinator, description: GlobalSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry_id}_global_{description.key}"
        self._attr_name = description.name

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)


class DockerContainerSensor(DockerContainerEntity, SensorEntity):
    """A sensor for a specific container."""

    entity_description: ContainerSensorDescription

    def __init__(
        self,
        coordinator: DockerCoordinator,
        container_name: str,
        description: ContainerSensorDescription,
    ) -> None:
        super().__init__(coordinator, container_name)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.entry_id}_{container_name}_{description.key}"
        self._attr_name = description.name

    @property
    def native_value(self) -> Any:
        if not self.container_data:
            return None
        return self.entity_description.value_fn(self.container_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.entity_description.key == "state" and self.container_data:
            return {
                "container_id": self.container_data.id,
                "created": self.container_data.created,
                "update_available": self.container_data.update_available,
                "last_update_check": (
                    self.container_data.last_update_check.isoformat()
                    if self.container_data.last_update_check
                    else None
                ),
            }
        return {}
