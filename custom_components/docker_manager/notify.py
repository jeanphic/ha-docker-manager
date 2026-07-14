"""Container down notification support for Docker Manager."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant

from .coordinator import DockerCoordinator

_LOGGER = logging.getLogger(__name__)


class ContainerStateWatcher:
    """Watch for container state changes and fire HA persistent notifications."""

    def __init__(self, hass: HomeAssistant, coordinator: DockerCoordinator) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._prev_states: dict[str, str] = {}
        self._unsubscribe = None

    def start(self) -> None:
        """Subscribe to coordinator updates."""
        self._unsubscribe = self._coordinator.async_add_listener(self._on_update)

    def stop(self) -> None:
        """Unsubscribe."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _on_update(self) -> None:
        """Called on every coordinator data refresh."""
        data = self._coordinator.data or {}

        for name, cdata in data.items():
            prev = self._prev_states.get(name)
            curr = cdata.state

            # Container went down unexpectedly
            if (
                prev == "running"
                and curr in ("exited", "dead")
                and name.lower() not in ("homeassistant", "hass", "home-assistant", "ha")
            ):
                _LOGGER.warning(
                    "Container %s went down (was running, now %s)", name, curr
                )
                self._hass.async_create_task(
                    self._notify_down(name, curr)
                )

            # Container recovered
            elif prev in ("exited", "dead") and curr == "running":
                _LOGGER.info("Container %s recovered (now running)", name)
                self._hass.async_create_task(
                    self._notify_recovered(name)
                )

            self._prev_states[name] = curr

        # Remove entries for containers no longer tracked
        for name in list(self._prev_states.keys()):
            if name not in data:
                del self._prev_states[name]

    async def _notify_down(self, name: str, state: str) -> None:
        """Fire a persistent notification when a container goes down."""
        await self._hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"🐳 Container down: {name}",
                "message": (
                    f"**{name}** is now `{state}`.\n\n"
                    f"Check the container logs or restart it from the Docker Manager dashboard.\n\n"
                    f"*{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*"
                ),
                "notification_id": f"docker_manager_down_{name}",
            },
        )

    async def _notify_recovered(self, name: str) -> None:
        """Dismiss the down notification when container recovers."""
        await self._hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": f"docker_manager_down_{name}"},
        )
