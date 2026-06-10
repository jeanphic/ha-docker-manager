"""DataUpdateCoordinator for Docker Manager."""
from __future__ import annotations

import logging
import re
from datetime import timedelta, datetime, timezone
from typing import Any

import aiohttp
import aiodocker
from aiodocker.exceptions import DockerError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    CONF_CONTAINERS_INCLUDE,
    HA_CONTAINER_NAMES,
)

_LOGGER = logging.getLogger(__name__)


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

        # Stats (may be None if container is stopped)
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
        # Normalize: remove sha256 prefix if present
        if "@sha256:" in image:
            image = image.split("@")[0]
        return image

    @staticmethod
    def _extract_health(info: dict) -> str:
        health = info.get("State", {}).get("Health", {})
        return health.get("Status", "none") if health else "none"

    @staticmethod
    def _parse_docker_datetime(dt_str: str) -> datetime | None:
        """Parse Docker datetime string to aware datetime.

        Docker returns nanosecond precision ISO strings like:
          2026-05-31T15:02:05.702900281Z
        Python's fromisoformat only handles up to microseconds (6 digits),
        so we truncate the sub-second part to 6 digits before parsing.
        Returns None for zero/empty values (container never started).
        """
        if not dt_str or dt_str.startswith("0001-01-01"):
            return None
        try:
            # Truncate nanoseconds to microseconds (keep only 6 sub-second digits)
            normalized = re.sub(r'(\.\d{6})\d+', r'\1', dt_str)
            # Replace trailing Z with +00:00 for fromisoformat compatibility
            normalized = normalized.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except Exception:
            return None

    def _parse_stats(self, stats: dict) -> None:
        """Parse Docker stats API response."""
        try:
            # CPU
            cpu = stats.get("cpu_stats", {})
            precpu = stats.get("precpu_stats", {})
            cpu_delta = (
                cpu.get("cpu_usage", {}).get("total_usage", 0)
                - precpu.get("cpu_usage", {}).get("total_usage", 0)
            )
            system_delta = cpu.get("system_cpu_usage", 0) - precpu.get(
                "system_cpu_usage", 0
            )
            num_cpus = cpu.get("online_cpus") or len(
                cpu.get("cpu_usage", {}).get("percpu_usage", [1])
            )
            if system_delta > 0:
                self.cpu_percent = round(
                    (cpu_delta / system_delta) * num_cpus * 100.0, 2
                )

            # Memory
            mem = stats.get("memory_stats", {})
            usage = mem.get("usage", 0)
            limit = mem.get("limit", 0)
            # Subtract cache
            cache = mem.get("stats", {}).get("cache", 0)
            real_usage = usage - cache
            if real_usage > 0:
                self.memory_mb = round(real_usage / (1024 * 1024), 2)
            if limit and limit > 0:
                self.memory_percent = round((real_usage / limit) * 100.0, 2)

            # Network
            networks = stats.get("networks") or {}
            total_rx = sum(n.get("rx_bytes", 0) for n in networks.values())
            total_tx = sum(n.get("tx_bytes", 0) for n in networks.values())
            self.net_total_up = round(total_tx / (1024 * 1024), 4)
            self.net_total_down = round(total_rx / (1024 * 1024), 4)

        except Exception as err:
            _LOGGER.debug("Error parsing stats for %s: %s", self.name, err)


class DockerCoordinator(DataUpdateCoordinator):
    """Manages polling of Docker daemon and update checks."""

    def __init__(self, hass: HomeAssistant, url: str, entry_id: str, included_containers: list[str] | None = None, scan_interval: int = DEFAULT_SCAN_INTERVAL) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.url = url
        self.entry_id = entry_id
        # Empty list = monitor all containers
        self.included_containers: list[str] = included_containers or []
        self._client: aiodocker.Docker | None = None
        self._prev_net: dict[str, dict] = {}
        self._prev_net_time: dict[str, datetime] = {}
        # Global Docker info
        self.docker_version: str = ""
        self.images_total: int = 0

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #

    async def async_connect(self) -> None:
        """Connect to the Docker daemon."""
        self._client = aiodocker.Docker(url=self.url)
        # Test connection
        info = await self._client.system.info()
        self.docker_version = info.get("ServerVersion", "unknown")
        _LOGGER.info("Connected to Docker %s at %s", self.docker_version, self.url)

    async def async_disconnect(self) -> None:
        """Disconnect and clean up."""
        if self._client:
            await self._client.close()
            self._client = None

    # ------------------------------------------------------------------ #
    # Data polling
    # ------------------------------------------------------------------ #

    async def _async_update_data(self) -> dict[str, ContainerData]:
        """Fetch all container data from Docker."""
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
                        # aiodocker returns a list of snapshots; take the first
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

                    # Compute network speed (delta / time)
                    if stats and cdata.name in self._prev_net:
                        self._compute_net_speed(cdata, stats)

                    # Save raw net totals for next delta
                    if stats:
                        networks = stats.get("networks") or {}
                        self._prev_net[cdata.name] = {
                            "rx": sum(n.get("rx_bytes", 0) for n in networks.values()),
                            "tx": sum(n.get("tx_bytes", 0) for n in networks.values()),
                        }
                        self._prev_net_time[cdata.name] = datetime.now(timezone.utc)

                    # Filter: skip containers not in include list (empty = all)
                    if self.included_containers and cdata.name not in self.included_containers:
                        continue

                    result[cdata.name] = cdata

                except DockerError as err:
                    if err.status == 404:
                        # Container disappeared temporarily (e.g. during update — normal)
                        _LOGGER.debug("Container not found during poll (transient): %s", err)
                    else:
                        _LOGGER.warning("Error fetching container data: %s", err)

            return result

        except DockerError as err:
            raise UpdateFailed(f"Docker API error: {err}") from err

    def _compute_net_speed(self, cdata: ContainerData, stats: dict) -> None:
        """Compute network speed in kB/s using delta from last poll."""
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

            cdata.net_speed_down = round(
                (cur_rx - prev.get("rx", 0)) / elapsed / 1024, 2
            )
            cdata.net_speed_up = round(
                (cur_tx - prev.get("tx", 0)) / elapsed / 1024, 2
            )
        except Exception as err:
            _LOGGER.debug("Net speed error for %s: %s", cdata.name, err)

    # ------------------------------------------------------------------ #
    # Update check (digest comparison)
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Registry digest helpers (no pull, no download)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_image_ref(image_name: str) -> tuple[str, str, str]:
        """Parse image reference into (registry, repository, tag).

        Examples:
          nginx                        → docker.io, library/nginx, latest
          nginx:1.25                   → docker.io, library/nginx, 1.25
          ghcr.io/user/repo:latest     → ghcr.io, user/repo, latest
          myregistry.com/img:tag       → myregistry.com, img, tag
        """
        tag = "latest"
        if ":" in image_name.split("/")[-1]:
            image_name, tag = image_name.rsplit(":", 1)

        known_registries = ("ghcr.io", "gcr.io", "quay.io", "mcr.microsoft.com", "lscr.io")
        if "/" in image_name and image_name.split("/")[0] in known_registries:
            parts = image_name.split("/", 1)
            return parts[0], parts[1], tag

        # Default: Docker Hub
        if "/" not in image_name:
            # Official image (e.g. nginx → library/nginx)
            return "docker.io", f"library/{image_name}", tag
        return "docker.io", image_name, tag

    async def _get_remote_digest(self, image_name: str) -> str | None:
        """Get the remote digest for an image without downloading it.

        Tries in order:
        1. Docker daemon distributions.inspect (works when daemon has auth token cached)
        2. Direct registry API call (works for public images on Docker Hub, GHCR, etc.)

        Returns the digest string (sha256:...) or None if unavailable.
        """
        # --- Method 1: Docker daemon distributions API ---
        try:
            dist = await self._client.distributions.inspect(image_name)
            digest = dist.get("Descriptor", {}).get("digest", "") or ""
            if digest:
                _LOGGER.debug("Got remote digest via distributions.inspect: %s", digest[:19])
                return digest
        except Exception as e:
            _LOGGER.debug("distributions.inspect failed (%s), trying registry API", e)

        # --- Method 2: Direct registry API (no auth for public images) ---
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
        """Get digest from Docker Hub API (no auth needed for public images)."""
        # Step 1: get anonymous token
        auth_url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
        async with aiohttp.ClientSession() as session:
            async with session.get(auth_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                token_data = await resp.json()
                token = token_data.get("token", "")

            # Step 2: fetch manifest digest (HEAD request — no layer download)
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
            async with session.head(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    digest = resp.headers.get("Docker-Content-Digest", "")
                    _LOGGER.debug("Docker Hub digest for %s:%s → %s", repo, tag, digest[:19] if digest else "none")
                    return digest or None
        return None

    @staticmethod
    async def _get_ghcr_digest(repo: str, tag: str) -> str | None:
        """Get digest from GitHub Container Registry (public images, no auth)."""
        async with aiohttp.ClientSession() as session:
            # GHCR accepts anonymous for public images
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
                if resp.status == 401:
                    # Need token
                    www_auth = resp.headers.get("Www-Authenticate", "")
                    realm, service, scope = "", "", ""
                    for part in www_auth.replace("Bearer ", "").split(","):
                        k, _, v = part.partition("=")
                        v = v.strip('"')
                        if k == "realm": realm = v
                        elif k == "service": service = v
                        elif k == "scope": scope = v
                    if realm:
                        token_url = f"{realm}?service={service}&scope={scope}"
                        async with session.get(token_url, timeout=aiohttp.ClientTimeout(total=10)) as tresp:
                            token = (await tresp.json()).get("token", "")
                        headers["Authorization"] = f"Bearer {token}"
                        async with session.head(manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp2:
                            return resp2.headers.get("Docker-Content-Digest") or None
                elif resp.status == 200:
                    return resp.headers.get("Docker-Content-Digest") or None
        return None

    @staticmethod
    async def _get_generic_registry_digest(registry: str, repo: str, tag: str) -> str | None:
        """Get digest from any OCI-compliant registry with automatic Bearer auth.

        Handles registries that require a Bearer token challenge (lscr.io, quay.io,
        gcr.io, mcr.microsoft.com, etc.) by parsing the WWW-Authenticate header
        on a 401 response and fetching an anonymous token.
        """
        manifest_url = f"https://{registry}/v2/{repo}/manifests/{tag}"
        accept_header = (
            "application/vnd.docker.distribution.manifest.v2+json,"
            "application/vnd.oci.image.manifest.v1+json,"
            "application/vnd.docker.distribution.manifest.list.v2+json,"
            "application/vnd.oci.image.index.v1+json"
        )

        async with aiohttp.ClientSession() as session:
            headers = {"Accept": accept_header}

            # First attempt — anonymous
            async with session.head(
                manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return resp.headers.get("Docker-Content-Digest") or None

                if resp.status != 401:
                    _LOGGER.debug(
                        "Registry %s returned %s for %s:%s",
                        registry, resp.status, repo, tag
                    )
                    return None

                # Parse WWW-Authenticate: Bearer realm="...",service="...",scope="..."
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

            # Fetch anonymous token from the registry's auth server
            token_params = {}
            if "service" in params:
                token_params["service"] = params["service"]
            if "scope" in params:
                token_params["scope"] = params["scope"]

            async with session.get(
                realm, params=token_params, timeout=aiohttp.ClientTimeout(total=10)
            ) as tresp:
                if tresp.status != 200:
                    _LOGGER.debug("Token fetch failed for %s: %s", registry, tresp.status)
                    return None
                token_data = await tresp.json()
                token = token_data.get("token") or token_data.get("access_token", "")

            if not token:
                return None

            # Second attempt — with Bearer token
            headers["Authorization"] = f"Bearer {token}"
            async with session.head(
                manifest_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp2:
                if resp2.status == 200:
                    digest = resp2.headers.get("Docker-Content-Digest", "")
                    _LOGGER.debug(
                        "Got digest for %s/%s:%s via Bearer auth → %s",
                        registry, repo, tag, digest[:19] if digest else "none"
                    )
                    return digest or None
                _LOGGER.debug(
                    "Registry %s returned %s after auth for %s:%s",
                    registry, resp2.status, repo, tag
                )

        return None

    # ------------------------------------------------------------------ #
    # Update check
    # ------------------------------------------------------------------ #

    async def async_check_update(self, container_name: str) -> None:
        """Check if a newer image is available — zero download, pure API calls.

        1. Get local digest from Docker inspect (RepoDigests)
        2. Get remote digest via distributions.inspect or direct registry API
        3. Compare — no pull, no layer download
        """
        if not self._client:
            return

        cdata = self.get_container_data(container_name)
        if not cdata:
            _LOGGER.warning("async_check_update: container %s not found", container_name)
            return

        image_name = cdata.image
        if not image_name:
            return
        if ":" not in image_name:
            image_name += ":latest"

        _LOGGER.info("Checking update for %s (image: %s) — no download", container_name, image_name)

        try:
            # 1. Local digest
            local_image = await self._client.images.inspect(image_name)
            repo_digests = local_image.get("RepoDigests", [])
            local_digest = repo_digests[0].split("@")[-1] if repo_digests else ""
            local_id = local_image.get("Id", "")

            if not local_digest:
                _LOGGER.debug(
                    "No RepoDigest for %s (locally built or never pulled from registry) — cannot check",
                    image_name
                )
                cdata.update_available = False
                cdata.last_update_check = datetime.now(timezone.utc)
                self.async_set_updated_data(self.data)
                return

            # 2. Remote digest (no download)
            remote_digest = await self._get_remote_digest(image_name)

            if not remote_digest:
                _LOGGER.warning(
                    "Could not retrieve remote digest for %s — update check inconclusive",
                    image_name
                )
                cdata.update_available = False
                cdata.last_update_check = datetime.now(timezone.utc)
                self.async_set_updated_data(self.data)
                return

            # 3. Compare
            cdata.update_available = local_digest != remote_digest
            cdata.local_digest = local_digest[:19]
            cdata.latest_digest = remote_digest[:19]
            cdata.last_update_check = datetime.now(timezone.utc)

            _LOGGER.info(
                "Update check %s: local=%s remote=%s available=%s",
                container_name,
                local_digest[:19],
                remote_digest[:19],
                cdata.update_available,
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
                return

    async def async_restart_container(self, name: str) -> None:
        if self._is_ha_container(name):
            _LOGGER.warning("Refusing to restart Home Assistant container via Docker Manager")
            return
        containers = await self._client.containers.list(all=True)
        for c in containers:
            info = await c.show()
            if info.get("Name", "").lstrip("/") == name:
                await c.restart()
                return

    async def async_update_container(self, name: str) -> None:
        """Pull latest image and recreate the container preserving its config."""
        if self._is_ha_container(name):
            _LOGGER.warning("Refusing to update Home Assistant container via Docker Manager")
            return

        if not self._client:
            return

        # --- Find the container ---
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

        _LOGGER.info("[%s] Starting update — image: %s", name, image_name)

        # --- 1. Pull latest image with progress logging ---
        _LOGGER.info("[%s] Pulling image %s ...", name, image_name)
        try:
            # aiodocker pull returns an async generator of progress events
            async for line in self._client.images.pull(image_name, stream=True):
                status = line.get("status", "")
                progress = line.get("progress", "")
                detail = line.get("progressDetail", {})
                if status and status not in ("Waiting", "Pulling fs layer"):
                    if progress:
                        _LOGGER.debug("[%s] Pull: %s %s", name, status, progress)
                    else:
                        _LOGGER.info("[%s] Pull: %s", name, status)
        except TypeError:
            # Some aiodocker versions return a coroutine, not an async generator
            await self._client.images.pull(image_name)

        _LOGGER.info("[%s] Pull complete", name)

        # --- 2. Snapshot full container config before touching it ---
        config = info.get("Config", {})
        host_config = info.get("HostConfig", {})
        networks = info.get("NetworkSettings", {}).get("Networks", {})
        was_running = info.get("State", {}).get("Status") == "running"

        # Build network config (reconnect to same networks after recreation)
        networking_config = {
            net_name: {
                "IPAMConfig": net_data.get("IPAMConfig"),
                "Aliases": net_data.get("Aliases", []),
            }
            for net_name, net_data in networks.items()
        }

        # --- 3. Stop old container ---
        if was_running:
            _LOGGER.info("[%s] Stopping container...", name)
            await container.stop()

        # --- 4. Remove old container ---
        _LOGGER.info("[%s] Removing old container...", name)
        await container.delete()

        # --- 5. Create new container with same config ---
        _LOGGER.info("[%s] Creating new container...", name)
        create_config = {
            "Image": image_name,
            "Env": config.get("Env") or [],
            "Labels": config.get("Labels") or {},
            "ExposedPorts": config.get("ExposedPorts") or {},
            "Volumes": config.get("Volumes") or {},
            "Entrypoint": config.get("Entrypoint"),
            "Cmd": config.get("Cmd"),
            "WorkingDir": config.get("WorkingDir", ""),
            "User": config.get("User", ""),
            "HostConfig": host_config,
            "NetworkingConfig": {"EndpointsConfig": networking_config},
        }

        new_container = await self._client.containers.create(
            config=create_config,
            name=name,
        )

        # --- 6. Start new container if it was running ---
        if was_running:
            _LOGGER.info("[%s] Starting new container...", name)
            await new_container.start()

        _LOGGER.info("[%s] Update complete ✓", name)

        # --- 7. Reset update flag and refresh ---
        cdata = self.get_container_data(name)
        if cdata:
            cdata.update_available = False

        await self.async_request_refresh()

    async def async_prune_images(self) -> dict:
        """Remove unused Docker images."""
        if not self._client:
            return {}
        result = await self._client.images.prune(filters={"dangling": False})
        await self.async_request_refresh()
        return result

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
