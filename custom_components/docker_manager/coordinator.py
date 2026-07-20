"""DataUpdateCoordinator for Docker Manager."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import timedelta, datetime, timezone
from typing import Any, Callable

import aiohttp
import aiodocker
from aiodocker.exceptions import DockerError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    CONF_CONTAINERS_INCLUDE,
    DISABLE_UPDATE_CHECK,
    HA_CONTAINER_NAMES,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "docker_manager_container_states"


class ContainerData:
    """Holds all data for a single container."""

    def __init__(self, info: dict, stats: dict | None = None) -> None:
        self.id: str = info.get("Id", "")[:12]
        self.name: str = info.get("Name", "").lstrip("/")
        self.image: str = self._extract_image(info)
        self.image_id: str = info.get("Image", "")
        self.state: str = info.get("State", {}).get("Status", "unknown")
        self.status: str = info.get("Status", "")
        self.health: str = self._extract_health(info)
        self.started_at: datetime | None = self._parse_docker_datetime(
            info.get("State", {}).get("StartedAt", "")
        )
        self.created: str = info.get("Created", "")

        # Stats
        self.cpu_percent: float = 0.0
        self.memory_mb: float = 0.0
        self.memory_percent: float = 0.0
        self.net_speed_up: float = 0.0
        self.net_speed_down: float = 0.0
        self.net_total_up: float = 0.0
        self.net_total_down: float = 0.0

        # Update tracking
        self.update_available: bool = False
        self.latest_digest: str = ""
        self.local_digest: str = ""
        self.last_update_check: datetime | None = None

        if stats:
            self._parse_stats(stats)

    @staticmethod
    def _extract_image(info: dict) -> str:
        config = info.get("Config", {})
        image = config.get("Image", info.get("Image", ""))
        if "@sha256:" in image:
            image = image.split("@")[0]
        return image

    @staticmethod
    def _extract_health(info: dict) -> str:
        health = info.get("State", {}).get("Health", {})
        return health.get("Status", "none") if health else "none"

    @staticmethod
    def _parse_docker_datetime(dt_str: str) -> datetime | None:
        if not dt_str or dt_str.startswith("0001-01-01"):
            return None
        try:
            normalized = re.sub(r'(\.\d{6})\d+', r'\1', dt_str)
            normalized = normalized.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except Exception:
            return None

    def _parse_stats(self, stats: dict) -> None:
        try:
            cpu = stats.get("cpu_stats", {})
            precpu = stats.get("precpu_stats", {})
            cpu_delta = (
                cpu.get("cpu_usage", {}).get("total_usage", 0)
                - precpu.get("cpu_usage", {}).get("total_usage", 0)
            )
            system_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
            num_cpus = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", [1]))
            if system_delta > 0:
                self.cpu_percent = round((cpu_delta / system_delta) * num_cpus * 100.0, 2)

            mem = stats.get("memory_stats", {})
            usage = mem.get("usage", 0)
            limit = mem.get("limit", 0)
            cache = mem.get("stats", {}).get("cache", 0)
            real_usage = usage - cache
            if real_usage > 0:
                self.memory_mb = round(real_usage / (1024 * 1024), 2)
            if limit and limit > 0:
                self.memory_percent = round((real_usage / limit) * 100.0, 2)

            networks = stats.get("networks") or {}
            total_rx = sum(n.get("rx_bytes", 0) for n in networks.values())
            total_tx = sum(n.get("tx_bytes", 0) for n in networks.values())
            self.net_total_up = round(total_tx / (1024 * 1024), 4)
            self.net_total_down = round(total_rx / (1024 * 1024), 4)

        except Exception as err:
            _LOGGER.debug("Error parsing stats for %s: %s", self.name, err)


class DockerCoordinator(DataUpdateCoordinator):
    """Manages polling of Docker daemon and update checks."""

    def __init__(
        self,
        hass: HomeAssistant,
        url: str,
        entry_id: str,
        included_containers: list[str] | None = None,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        update_check_interval: int = DISABLE_UPDATE_CHECK,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.url = url
        self.entry_id = entry_id
        self.included_containers: list[str] = included_containers or []
        self.update_check_interval: int = update_check_interval
        self._update_check_task: asyncio.Task | None = None
        self._client: aiodocker.Docker | None = None
        self._prev_net: dict[str, dict] = {}
        self._prev_net_time: dict[str, datetime] = {}
        self.docker_version: str = ""
        self.images_total: int = 0
        # HA storage for persisting container states across restarts
        self._store: Store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}")
        self._desired_states: dict[str, str] = {}  # name → "running"|"stopped"|"paused"

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #

    async def async_connect(self) -> None:
        """Connect to the Docker daemon."""
        self._client = aiodocker.Docker(url=self.url)
        info = await self._client.system.info()
        self.docker_version = info.get("ServerVersion", "unknown")
        _LOGGER.info("Connected to Docker %s at %s", self.docker_version, self.url)

        # Load persisted container states
        await self._load_desired_states()

        if self.update_check_interval > 0:
            self._update_check_task = self.hass.async_create_background_task(
                self._periodic_update_check(),
                f"docker_manager_update_check_{self.entry_id}",
            )
            _LOGGER.info("Auto update check enabled every %ds", self.update_check_interval)

    async def async_disconnect(self) -> None:
        """Disconnect and clean up."""
        if self._update_check_task:
            self._update_check_task.cancel()
            self._update_check_task = None
        if self._client:
            await self._client.close()
            self._client = None

    # ------------------------------------------------------------------ #
    # Container state persistence
    # ------------------------------------------------------------------ #

    async def _load_desired_states(self) -> None:
        """Load persisted container desired states from HA storage."""
        data = await self._store.async_load()
        if data and isinstance(data, dict):
            self._desired_states = data.get("desired_states", {})
            _LOGGER.debug("Loaded %d desired container states", len(self._desired_states))

    async def _save_desired_states(self) -> None:
        """Persist container desired states to HA storage."""
        await self._store.async_save({"desired_states": self._desired_states})

    async def async_set_desired_state(self, name: str, state: str) -> None:
        """Record the desired state for a container and persist it."""
        self._desired_states[name] = state
        await self._save_desired_states()

    async def async_restore_container_states(self) -> None:
        """Restore containers to their desired states after HA restart."""
        if not self._desired_states or not self._client:
            return

        containers_raw = await self._client.containers.list(all=True)
        container_map = {}
        for c in containers_raw:
            info = await c.show()
            cname = info.get("Name", "").lstrip("/")
            container_map[cname] = (c, info)

        for name, desired in self._desired_states.items():
            if name not in container_map:
                continue
            container, info = container_map[name]
            current = info.get("State", {}).get("Status", "unknown")

            if desired == "stopped" and current == "running":
                _LOGGER.info("Restoring %s → stopped (was running before HA restart)", name)
                try:
                    await container.stop()
                except Exception as e:
                    _LOGGER.warning("Failed to stop %s: %s", name, e)

            elif desired == "paused" and current == "running":
                _LOGGER.info("Restoring %s → paused (was paused before HA restart)", name)
                try:
                    await container.pause()
                except Exception as e:
                    _LOGGER.warning("Failed to pause %s: %s", name, e)

    # ------------------------------------------------------------------ #
    # Data polling
    # ------------------------------------------------------------------ #

    async def _async_update_data(self) -> dict[str, ContainerData]:
        """Fetch all container data from Docker. Auto-reconnects if socket closed."""
        if not self._client:
            raise UpdateFailed("Not connected to Docker")

        try:
            containers_raw = await self._client.containers.list(all=True)
            images_raw = await self._client.images.list()
            self.images_total = len(images_raw)

            result: dict[str, ContainerData] = {}

            for c in containers_raw:
                try:
                    info = await c.show()
                    stats = None
                    if info.get("State", {}).get("Status") == "running":
                        raw = await c.stats(stream=False)
                        if isinstance(raw, list):
                            stats = raw[0] if raw else None
                        elif isinstance(raw, dict):
                            stats = raw

                    cdata = ContainerData(info, stats)

                    # Preserve update info from previous cycle
                    if cdata.name in (self.data or {}):
                        prev: ContainerData = self.data[cdata.name]
                        cdata.update_available = prev.update_available
                        cdata.latest_digest = prev.latest_digest
                        cdata.local_digest = prev.local_digest
                        cdata.last_update_check = prev.last_update_check

                    # Compute network speed
                    if stats and cdata.name in self._prev_net:
                        self._compute_net_speed(cdata, stats)

                    if stats:
                        networks = stats.get("networks") or {}
                        self._prev_net[cdata.name] = {
                            "rx": sum(n.get("rx_bytes", 0) for n in networks.values()),
                            "tx": sum(n.get("tx_bytes", 0) for n in networks.values()),
                        }
                        self._prev_net_time[cdata.name] = datetime.now(timezone.utc)

                    # Filter by include list
                    if self.included_containers and cdata.name not in self.included_containers:
                        continue

                    result[cdata.name] = cdata

                except DockerError as err:
                    if err.status == 404:
                        _LOGGER.debug("Container not found during poll (transient): %s", err)
                    else:
                        _LOGGER.warning("Error fetching container data: %s", err)

            # Clean up orphaned entities for containers no longer present
            if self.data:
                removed = set(self.data.keys()) - set(result.keys())
                if removed:
                    _LOGGER.info(
                        "Containers no longer present, cleaning up entities: %s",
                        ", ".join(removed),
                    )
                    from homeassistant.helpers import entity_registry as er
                    registry = er.async_get(self.hass)
                    for entity_entry in list(registry.entities.values()):
                        if entity_entry.config_entry_id != self.entry_id:
                            continue
                        # Extract container name from unique_id: {entry_id}_{name}_{suffix}
                        uid = entity_entry.unique_id or ""
                        prefix = f"{self.entry_id}_"
                        if uid.startswith(prefix):
                            remainder = uid[len(prefix):]
                            # remainder = "{name}_{suffix}" — extract name
                            for cname in removed:
                                if remainder.startswith(f"{cname}_"):
                                    _LOGGER.debug(
                                        "Removing orphaned entity: %s",
                                        entity_entry.entity_id,
                                    )
                                    registry.async_remove(entity_entry.entity_id)
                                    break

            return result

        except DockerError as err:
            raise UpdateFailed(f"Docker API error: {err}") from err
        except (RuntimeError, Exception) as err:
            err_str = str(err).lower()
            if "session is closed" in err_str or "connector is closed" in err_str:
                _LOGGER.warning(
                    "Docker socket closed — reconnecting... (%s)", err
                )
                try:
                    if self._client:
                        await self._client.close()
                except Exception:
                    pass
                self._client = None
                try:
                    await self.async_connect()
                    _LOGGER.info("Reconnected to Docker successfully")
                except Exception as reconnect_err:
                    raise UpdateFailed(f"Docker reconnect failed: {reconnect_err}") from reconnect_err
                raise UpdateFailed("Reconnected to Docker — data will refresh shortly")
            raise UpdateFailed(f"Unexpected error fetching Docker data: {err}") from err

    def _compute_net_speed(self, cdata: ContainerData, stats: dict) -> None:
        try:
            networks = stats.get("networks") or {}
            now = datetime.now(timezone.utc)
            prev = self._prev_net.get(cdata.name, {})
            prev_time = self._prev_net_time.get(cdata.name)
            if not prev or not prev_time:
                return
            elapsed = (now - prev_time).total_seconds()
            if elapsed <= 0:
                return
            cur_rx = sum(n.get("rx_bytes", 0) for n in networks.values())
            cur_tx = sum(n.get("tx_bytes", 0) for n in networks.values())
            cdata.net_speed_down = round((cur_rx - prev.get("rx", 0)) / elapsed / 1024, 2)
            cdata.net_speed_up = round((cur_tx - prev.get("tx", 0)) / elapsed / 1024, 2)
        except Exception as err:
            _LOGGER.debug("Net speed error for %s: %s", cdata.name, err)

    # ------------------------------------------------------------------ #
    # Periodic update check
    # ------------------------------------------------------------------ #

    async def _periodic_update_check(self) -> None:
        """Background task: check all containers for updates at configured interval.

        Cycle 1: runs 60s after startup — establishes RepoDigest baselines
        Cycle 2: runs immediately after cycle 1 — detects updates for containers
                 that had no RepoDigest on cycle 1 (uses stored baseline)
        Subsequent cycles: every update_check_interval seconds
        """
        _LOGGER.info(
            "Auto-check started — interval=%ds, first check in 60s",
            self.update_check_interval,
        )
        try:
            await asyncio.sleep(60)

            first_cycle = True
            while True:
                try:
                    if not self.data:
                        await asyncio.sleep(30)
                        continue

                    container_names = list(self.data.keys())
                    needs_second_pass: list[str] = []

                    _LOGGER.info(
                        "Auto-check cycle: checking %d containers", len(container_names)
                    )

                    for name in container_names:
                        cdata_before = self.get_container_data(name)
                        had_no_digest = not (cdata_before and cdata_before.local_digest)

                        try:
                            await asyncio.wait_for(
                                self.async_check_update(name), timeout=30
                            )
                        except asyncio.TimeoutError:
                            _LOGGER.warning(
                                "Auto-check timeout for %s (>30s)", name
                            )
                        except Exception as err:
                            _LOGGER.warning(
                                "Auto-check error for %s: %s", name, err
                            )

                        # Mark for second pass if baseline was just established
                        if had_no_digest:
                            cdata_after = self.get_container_data(name)
                            if cdata_after and cdata_after.local_digest:
                                needs_second_pass.append(name)

                        await asyncio.sleep(1)

                    # Second pass: immediately re-check containers that just got a baseline
                    if needs_second_pass:
                        _LOGGER.info(
                            "Auto-check second pass for %d containers: %s",
                            len(needs_second_pass), ", ".join(needs_second_pass),
                        )
                        await asyncio.sleep(2)
                        for name in needs_second_pass:
                            try:
                                await asyncio.wait_for(
                                    self.async_check_update(name), timeout=30
                                )
                            except Exception as err:
                                _LOGGER.warning("Second pass error for %s: %s", name, err)
                            await asyncio.sleep(1)

                    _LOGGER.info(
                        "Auto-check cycle complete — next in %ds",
                        self.update_check_interval,
                    )

                    # After first cycle, wait normally; second cycle fires right after
                    if first_cycle and needs_second_pass:
                        first_cycle = False
                    else:
                        first_cycle = False
                        await asyncio.sleep(self.update_check_interval)

                except asyncio.CancelledError:
                    raise
                except Exception as err:
                    _LOGGER.error(
                        "Auto-check unexpected error: %s — retrying in 60s", err
                    )
                    await asyncio.sleep(60)

        except asyncio.CancelledError:
            _LOGGER.info("Auto-check task stopped (integration unloading)")
            raise
        except Exception as err:
            _LOGGER.error("Auto-check task crashed: %s", err, exc_info=True)

    # ------------------------------------------------------------------ #
    # Registry digest helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_image_ref(image_name: str) -> tuple[str, str, str]:
        tag = "latest"
        if ":" in image_name.split("/")[-1]:
            image_name, tag = image_name.rsplit(":", 1)

        known_registries = ("ghcr.io", "gcr.io", "quay.io", "mcr.microsoft.com", "lscr.io")
        if "/" in image_name and image_name.split("/")[0] in known_registries:
            parts = image_name.split("/", 1)
            return parts[0], parts[1], tag

        if "/" not in image_name:
            return "docker.io", f"library/{image_name}", tag
        return "docker.io", image_name, tag

    async def _get_remote_digest(self, image_name: str) -> str | None:
        """Get remote image digest without downloading — try registry API directly."""
        registry, repo, tag = self._parse_image_ref(image_name)

        try:
            if registry == "docker.io":
                return await self._get_dockerhub_digest(repo, tag)
            elif registry == "ghcr.io":
                return await self._get_ghcr_digest(repo, tag)
            else:
                return await self._get_generic_registry_digest(registry, repo, tag)
        except Exception as e:
            _LOGGER.debug("Registry API failed for %s: %s", image_name, e)
            return None

    @staticmethod
    async def _get_dockerhub_digest(repo: str, tag: str) -> str | None:
        auth_url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(auth_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return None
                    token = (await resp.json()).get("token", "")
            except Exception:
                return None

            manifest_url = f"https://registry-1.docker.io/v2/{repo}/manifests/{tag}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": (
                    "application/vnd.docker.distribution.manifest.v2+json,"
                    "application/vnd.oci.image.manifest.v1+json,"
                    "application/vnd.docker.distribution.manifest.list.v2+json,"
                    "application/vnd.oci.image.index.v1+json"
                ),
            }
            try:
                async with session.head(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return resp.headers.get("Docker-Content-Digest") or None
                    _LOGGER.debug("Docker Hub HEAD %s: HTTP %s", repo, resp.status)
            except Exception as e:
                _LOGGER.debug("Docker Hub HEAD error for %s: %s", repo, e)
        return None

    @staticmethod
    async def _get_ghcr_digest(repo: str, tag: str) -> str | None:
        async with aiohttp.ClientSession() as session:
            manifest_url = f"https://ghcr.io/v2/{repo}/manifests/{tag}"
            headers = {
                "Accept": (
                    "application/vnd.docker.distribution.manifest.v2+json,"
                    "application/vnd.oci.image.manifest.v1+json,"
                    "application/vnd.docker.distribution.manifest.list.v2+json,"
                    "application/vnd.oci.image.index.v1+json"
                ),
            }
            async with session.head(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return resp.headers.get("Docker-Content-Digest") or None
                if resp.status == 401:
                    www_auth = resp.headers.get("Www-Authenticate", "")
                    params: dict[str, str] = {}
                    for part in www_auth.replace("Bearer ", "").split(","):
                        k, _, v = part.partition("=")
                        params[k.strip()] = v.strip().strip('"')
                    realm = params.get("realm", "")
                    if realm:
                        token_url = f"{realm}?service={params.get('service','')}&scope={params.get('scope','')}"
                        async with session.get(token_url, timeout=aiohttp.ClientTimeout(total=10)) as tresp:
                            token = (await tresp.json()).get("token", "")
                        headers["Authorization"] = f"Bearer {token}"
                        async with session.head(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                            return resp2.headers.get("Docker-Content-Digest") or None
        return None

    @staticmethod
    async def _get_generic_registry_digest(registry: str, repo: str, tag: str) -> str | None:
        manifest_url = f"https://{registry}/v2/{repo}/manifests/{tag}"
        accept_header = (
            "application/vnd.docker.distribution.manifest.v2+json,"
            "application/vnd.oci.image.manifest.v1+json,"
            "application/vnd.docker.distribution.manifest.list.v2+json,"
            "application/vnd.oci.image.index.v1+json"
        )
        async with aiohttp.ClientSession() as session:
            headers = {"Accept": accept_header}
            async with session.head(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return resp.headers.get("Docker-Content-Digest") or None
                if resp.status != 401:
                    return None
                www_auth = resp.headers.get("Www-Authenticate", "")

            if not www_auth.startswith("Bearer "):
                return None

            params: dict[str, str] = {}
            for part in www_auth[len("Bearer "):].split(","):
                k, _, v = part.strip().partition("=")
                params[k.strip()] = v.strip().strip('"')

            realm = params.get("realm", "")
            if not realm:
                return None

            token_params = {}
            if "service" in params:
                token_params["service"] = params["service"]
            if "scope" in params:
                token_params["scope"] = params["scope"]

            async with session.get(realm, params=token_params, timeout=aiohttp.ClientTimeout(total=10)) as tresp:
                if tresp.status != 200:
                    return None
                token_data = await tresp.json()
                token = token_data.get("token") or token_data.get("access_token", "")

            if not token:
                return None

            headers["Authorization"] = f"Bearer {token}"
            async with session.head(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                if resp2.status == 200:
                    return resp2.headers.get("Docker-Content-Digest") or None
        return None

    # ------------------------------------------------------------------ #
    # Update check
    # ------------------------------------------------------------------ #

    async def async_check_update(self, container_name: str) -> None:
        """Check if a newer image is available — zero download."""
        if not self._client:
            return

        cdata = self.get_container_data(container_name)
        if not cdata:
            return

        image_name = cdata.image
        if not image_name:
            return
        if ":" not in image_name:
            image_name += ":latest"

        _LOGGER.debug("Checking update for %s (image: %s)", container_name, image_name)

        try:
            # 1. Get local image info
            try:
                local_image = await asyncio.wait_for(
                    self._client._query_json(f"images/{image_name}/json"),
                    timeout=10
                )
            except (asyncio.TimeoutError, Exception) as e:
                _LOGGER.warning("Image inspect failed for %s: %s", container_name, e)
                cdata.last_update_check = datetime.now(timezone.utc)
                self.async_set_updated_data(self.data)
                return

            repo_digests = local_image.get("RepoDigests", [])
            local_digest = repo_digests[0].split("@")[-1] if repo_digests else ""
            local_id = local_image.get("Id", "")

            # 2. Get remote digest
            remote_digest = await self._get_remote_digest(image_name)
            if not remote_digest:
                await asyncio.sleep(5)
                remote_digest = await self._get_remote_digest(image_name)

            if not remote_digest:
                _LOGGER.debug("No remote digest for %s — skipping", container_name)
                cdata.last_update_check = datetime.now(timezone.utc)
                self.async_set_updated_data(self.data)
                return

            # 3. Compare
            if local_digest:
                update_available = local_digest != remote_digest
                local_ref = local_digest[:19]
            else:
                # No RepoDigest: use stored remote as baseline for comparison
                prev_remote = cdata.latest_digest or ""
                update_available = bool(prev_remote and prev_remote != remote_digest[:19])
                local_ref = local_id[:19] if local_id else ""

            cdata.update_available = update_available
            cdata.local_digest = local_ref
            cdata.latest_digest = remote_digest[:19]
            cdata.last_update_check = datetime.now(timezone.utc)

            _LOGGER.info(
                "Update check %s: local=%s remote=%s available=%s",
                container_name, local_ref, remote_digest[:19], update_available,
            )

        except Exception as err:
            _LOGGER.warning("Update check failed for %s: %s", container_name, err)
            cdata.last_update_check = datetime.now(timezone.utc)

        self.async_set_updated_data(self.data)

    # ------------------------------------------------------------------ #
    # Container actions
    # ------------------------------------------------------------------ #

    async def async_start_container(self, name: str) -> None:
        containers = await self._client.containers.list(all=True)
        for c in containers:
            info = await c.show()
            if info.get("Name", "").lstrip("/") == name:
                await c.start()
                await self.async_set_desired_state(name, "running")
                await self.async_request_refresh()
                return

    async def async_stop_container(self, name: str) -> None:
        if self._is_ha_container(name):
            _LOGGER.warning("Refusing to stop Home Assistant container: %s", name)
            return
        containers = await self._client.containers.list(all=True)
        for c in containers:
            info = await c.show()
            if info.get("Name", "").lstrip("/") == name:
                await c.stop()
                await self.async_set_desired_state(name, "stopped")
                await self.async_request_refresh()
                return

    async def async_restart_container(self, name: str) -> None:
        if self._is_ha_container(name):
            _LOGGER.warning("Refusing to restart Home Assistant container")
            return
        containers = await self._client.containers.list(all=True)
        for c in containers:
            info = await c.show()
            if info.get("Name", "").lstrip("/") == name:
                await c.restart()
                await self.async_set_desired_state(name, "running")
                await self.async_request_refresh()
                return

    async def async_pause_container(self, name: str) -> None:
        if self._is_ha_container(name):
            return
        containers = await self._client.containers.list(all=True)
        for c in containers:
            info = await c.show()
            if info.get("Name", "").lstrip("/") == name:
                state = info.get("State", {}).get("Status", "")
                if state != "running":
                    _LOGGER.warning(
                        "Cannot pause %s: container is '%s', not running", name, state
                    )
                    return
                await c.pause()
                await self.async_set_desired_state(name, "paused")
                await self.async_request_refresh()
                return

    async def async_unpause_container(self, name: str) -> None:
        containers = await self._client.containers.list(all=True)
        for c in containers:
            info = await c.show()
            if info.get("Name", "").lstrip("/") == name:
                state = info.get("State", {}).get("Status", "")
                if state != "paused":
                    _LOGGER.warning(
                        "Cannot unpause %s: container is '%s', not paused", name, state
                    )
                    return
                await c.unpause()
                await self.async_set_desired_state(name, "running")
                await self.async_request_refresh()
                return

    async def async_update_container(self, name: str, progress_callback=None) -> None:
        """Pull latest image and recreate the container preserving its config."""
        if self._is_ha_container(name):
            _LOGGER.warning("Refusing to update Home Assistant container")
            return
        if not self._client:
            return

        async def _cb(percent: int, label: str) -> None:
            if progress_callback:
                await progress_callback(percent, label)

        # ── 1. Find container ───────────────────────────────────────────
        containers = await self._client.containers.list(all=True)
        target = None
        for c in containers:
            info = await c.show()
            if info.get("Name", "").lstrip("/") == name:
                target = (c, info)
                break

        if not target:
            _LOGGER.error("Container %s not found for update", name)
            return

        container, info = target
        image_name = info.get("Config", {}).get("Image", "")
        if not image_name:
            _LOGGER.error("Cannot determine image for container %s", name)
            return

        was_running = info.get("State", {}).get("Status") == "running"

        # ── 2. Pull new image ────────────────────────────────────────────
        await _cb(15, "⏳ Pulling image...")
        _LOGGER.info("[%s] Pulling %s", name, image_name)
        try:
            async def _do_pull():
                try:
                    async for _ in self._client.images.pull(image_name, stream=True):
                        pass
                except TypeError:
                    await self._client.images.pull(image_name)

            await asyncio.wait_for(_do_pull(), timeout=600)
            _LOGGER.info("[%s] Pull complete", name)
        except asyncio.TimeoutError:
            raise RuntimeError(f"Pull timed out after 10min for {image_name}")

        await _cb(50, "⏳ Pull complete — preparing...")

        # ── 3. Save full container config for recreation ─────────────────
        config      = info.get("Config", {})
        host_config = info.get("HostConfig", {})
        networks    = info.get("NetworkSettings", {}).get("Networks", {})

        networking_config = {}
        for net_name, net_data in networks.items():
            networking_config[net_name] = {
                "IPAMConfig": net_data.get("IPAMConfig"),
                "Aliases": [a for a in (net_data.get("Aliases") or []) if a != name],
            }

        create_config = {
            "Image":        image_name,
            "Env":          config.get("Env") or [],
            "Labels":       config.get("Labels") or {},
            "ExposedPorts": config.get("ExposedPorts") or {},
            "Volumes":      config.get("Volumes") or {},
            "Entrypoint":   config.get("Entrypoint"),
            "Cmd":          config.get("Cmd"),
            "WorkingDir":   config.get("WorkingDir", ""),
            "User":         config.get("User", ""),
            "Hostname":     config.get("Hostname", ""),
            "Domainname":   config.get("Domainname", ""),
            "HostConfig":   host_config,
            "NetworkingConfig": {"EndpointsConfig": networking_config},
        }

        # ── 4. Stop + remove old container ──────────────────────────────
        if was_running:
            await _cb(60, "⏸️ Stopping container...")
            try:
                await container.stop(timeout=10)
            except Exception as e:
                _LOGGER.warning("[%s] Stop error (forcing): %s", name, e)

        await _cb(70, "🗑️ Removing old container...")
        try:
            await container.delete(force=True)
        except Exception as e:
            _LOGGER.error("[%s] Failed to remove container: %s", name, e)
            raise

        # ── 5. Create + start new container ─────────────────────────────
        await _cb(80, "🔨 Creating new container...")
        try:
            new_container = await self._client.containers.create(
                config=create_config, name=name
            )
        except Exception as e:
            _LOGGER.error("[%s] Failed to create container: %s", name, e)
            raise

        if was_running:
            await _cb(90, "▶️ Starting container...")
            try:
                await new_container.start()
                await self.async_set_desired_state(name, "running")
            except Exception as e:
                _LOGGER.error("[%s] Failed to start container: %s", name, e)
                raise

        _LOGGER.info("[%s] Update complete", name)

        cdata = self.get_container_data(name)
        if cdata:
            cdata.update_available = False
            cdata.local_digest = cdata.latest_digest

        await self.async_request_refresh()

    async def async_prune_images(self, all_unused: bool = False) -> dict:
        """Remove unused Docker images — multiple passes to handle large sets."""
        if not self._client:
            return {}
        try:
            import urllib.parse
            if all_unused:
                filters = urllib.parse.quote('{"dangling":["false"]}')
            else:
                filters = urllib.parse.quote('{"dangling":["true"]}')

            total_deleted = 0
            total_space = 0

            # Run up to 5 passes — Docker may not remove all images in one call
            # when there are dependency chains between images
            for pass_num in range(1, 6):
                response = await self._client._query_json(
                    f"images/prune?filters={filters}", method="POST"
                )
                deleted = response.get("ImagesDeleted") or []
                space = response.get("SpaceReclaimed", 0)
                total_deleted += len(deleted)
                total_space += space

                if not deleted:
                    break  # nothing left to prune

                _LOGGER.info(
                    "Prune pass %d: %d image(s) removed, %.1f MB reclaimed",
                    pass_num, len(deleted), space / (1024 * 1024),
                )
                await asyncio.sleep(1)

            _LOGGER.info(
                "Prune complete: %d total image(s) removed, %.1f MB reclaimed",
                total_deleted, total_space / (1024 * 1024),
            )
            await asyncio.sleep(2)
            await self.async_request_refresh()
            await asyncio.sleep(3)
            await self.async_request_refresh()
            return {"ImagesDeleted": total_deleted, "SpaceReclaimed": total_space}
        except Exception as err:
            _LOGGER.error("Prune failed: %s", err)
            return {}

    # ------------------------------------------------------------------ #
    # Container logs
    # ------------------------------------------------------------------ #

    async def async_get_container_logs(self, name: str, tail: int = 50) -> str:
        if not self._client:
            return ""
        try:
            containers = await self._client.containers.list(all=True)
            for c in containers:
                info = await c.show()
                if info.get("Name", "").lstrip("/") == name:
                    logs = await c.log(stdout=True, stderr=True, tail=tail)
                    if isinstance(logs, list):
                        return "".join(logs)
                    return logs or ""
        except Exception as err:
            _LOGGER.debug("Failed to get logs for %s: %s", name, err)
        return ""

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_ha_container(name: str) -> bool:
        return name.lower() in HA_CONTAINER_NAMES

    def get_container_data(self, name: str) -> ContainerData | None:
        if self.data:
            return self.data.get(name)
        return None

    @property
    def containers_total(self) -> int:
        return len(self.data or {})

    @property
    def containers_running(self) -> int:
        return sum(1 for c in (self.data or {}).values() if c.state == "running")

    @property
    def containers_paused(self) -> int:
        return sum(1 for c in (self.data or {}).values() if c.state == "paused")

    @property
    def containers_stopped(self) -> int:
        return sum(
            1 for c in (self.data or {}).values()
            if c.state in ("exited", "dead", "created")
        )
