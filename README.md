# Docker Manager for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jeanphic/ha-docker-manager.svg)](https://github.com/jeanphic/ha-docker-manager/releases)
[![License](https://img.shields.io/github/license/jeanphic/ha-docker-manager.svg)](LICENSE)

**Supervise, control and update your Docker containers directly from Home Assistant.**

> 🇫🇷 [Documentation en français disponible ici](README.fr.md)

---

## Features

### 📊 Monitoring
- Container state (`running`, `exited`, `paused`, `restarting`, `dead`, `created`, `removing`)
- CPU (%), RAM (MB + %), network speed (up/down kB/s), network totals (MB)
- Health check status, uptime, image name
- Global Docker stats: total / running / stopped / paused containers, image count, Docker version

### 🎛 Control
- **Switch** start/stop per container
- **Restart** button per container
- **Pause / Unpause** button per container
- **Safety lock**: Home Assistant container cannot be stopped, restarted or paused

### 🔄 Updates
- **Check for Update** button per container — zero download, pure registry API query
  - Supports Docker Hub, GHCR, lscr.io and any OCI-compliant registry with Bearer auth
- **Update** entity: one-click pull + recreate preserving full config (volumes, ports, env, networks)
- Step-by-step progress display during update
- `update_available` automatically reset after install from card, HA Updates panel, or automation
- **Auto update check**: configurable background interval — first check 60s after startup, then at configured interval. Double-pass for images without RepoDigest

### 💾 State persistence
- Containers stopped or paused before a HA restart are automatically restored to their previous state after reboot

### 🧹 Maintenance
- **Service** `docker_manager.prune_images`: removes unused Docker images
  - `all_unused: false` (default) — dangling/untagged images only
  - `all_unused: true` — all images not used by any container

---

## Installation

### Via HACS (recommended)
1. Open HACS → Integrations → **+** → search "Docker Manager"
2. Install and restart HA

### Manual
1. Copy `custom_components/docker_manager` to `<config>/custom_components/`
2. Restart Home Assistant

---

## Configuration

### Prerequisites

#### HA running in Docker
Mount the Docker socket:
```yaml
services:
  homeassistant:
    image: homeassistant/home-assistant
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config
```

#### HA OS / Supervised — use a socket proxy
```yaml
services:
  dockerproxy:
    image: tecnativa/docker-socket-proxy
    container_name: dockerproxy
    restart: unless-stopped
    privileged: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "2375:2375"
    environment:
      CONTAINERS: 1
      IMAGES: 1
      INFO: 1
      POST: 1
      NETWORKS: 1
```
Then configure with URL `http://<HOST_IP>:2375`.

### Setup in HA
1. **Settings** → **Devices & Services** → **Add Integration** → "Docker Manager"
2. Choose **Local** (Unix socket) or **Remote** (TCP)
3. Select which containers to monitor
4. Save

### Options (after setup)
**Settings** → **Devices & Services** → Docker Manager → **Configure**:

| Option | Default | Description |
|--------|---------|-------------|
| Containers to monitor | all | Add/remove containers anytime |
| Update interval | 30s | How often stats are refreshed (5–300s) |
| Auto update check interval | 0 (disabled) | 0=off, 3600=hourly, 86400=daily |

---

## Entities

### Global "Docker" device
| Entity | Type | Description |
|--------|------|-------------|
| `sensor.docker_containers_total` | Sensor | Total containers |
| `sensor.docker_containers_running` | Sensor | Running containers |
| `sensor.docker_containers_stopped` | Sensor | Stopped containers |
| `sensor.docker_containers_paused` | Sensor | Paused containers |
| `sensor.docker_images_total` | Sensor | Total images |
| `sensor.docker_docker_version` | Sensor (diagnostic) | Docker daemon version |

### Per container (e.g. `nginx`)
| Entity | Category | Description |
|--------|----------|-------------|
| `switch.nginx_container` | Control | Start / Stop |
| `button.nginx_restart` | Control | Restart |
| `button.nginx_pause` | Control | Pause / Unpause (toggle) |
| `button.nginx_check_for_update` | Control | Check registry (no download) |
| `update.nginx_update` | Update | Shows update status, triggers install |
| `sensor.nginx_state` | Sensor | State (`running`, `exited`…) |
| `sensor.nginx_image` | Sensor | Image in use |
| `sensor.nginx_health` | Diagnostic | Health check (if HEALTHCHECK configured) |
| `sensor.nginx_started_at` | Diagnostic | Start timestamp |
| `sensor.nginx_cpu` | Diagnostic | CPU % |
| `sensor.nginx_memory` | Diagnostic | RAM in MB |
| `sensor.nginx_memory_2` | Diagnostic | RAM in % |
| `sensor.nginx_network_up` | Diagnostic | Upload speed (kB/s) |
| `sensor.nginx_network_down` | Diagnostic | Download speed (kB/s) |

---

## Service: Prune images

```yaml
service: docker_manager.prune_images           # dangling only
service: docker_manager.prune_images
data:
  all_unused: true                             # all unused
```

---

## Lovelace Cards

Three dedicated cards: **[Docker Manager Card](https://github.com/jeanphic/ha-docker-manager-card)**

### docker-manager-card (per container)
```yaml
type: custom:docker-manager-card
entity: sensor.nginx_state
name: Nginx
icon: mdi:nginx
```

### docker-overview-card (single host)
```yaml
type: custom:docker-overview-card
name: Docker
suffix: ""        # "_2" for second instance
tap_action:
  action: navigate
  navigation_path: /lovelace/docker
```

### docker-multi-overview-card (multiple hosts)
```yaml
type: custom:docker-multi-overview-card
name: Docker Hosts
hosts:
  - name: Local
    prefix: docker
  - name: Remote Server
    prefix: docker
    suffix: "_2"
```

---

## Automation examples

```yaml
# Notify when update available
automation:
  alias: "Docker - Update available"
  trigger:
    - platform: state
      entity_id: update.nginx_update
      to: "on"
  action:
    - service: notify.mobile_app
      data:
        message: "{{ trigger.to_state.attributes.title }} can be updated."
```

---

## FAQ

**Q: Can I stop the Home Assistant container?**
A: No. Containers named `homeassistant`, `hass`, `home-assistant` or `ha` are protected.

**Q: Does update preserve volumes and settings?**
A: Yes. The container is recreated with the exact same `HostConfig`.

**Q: The health sensor shows "none" — normal?**
A: Yes, only if the Docker image defines a `HEALTHCHECK` directive. The card hides this tile automatically.

**Q: What does auto update check do?**
A: Queries the registry API (no download). Does NOT automatically install updates.

**Q: Can I monitor multiple Docker hosts?**
A: Yes — add multiple instances of the integration (one per host). Use `docker-multi-overview-card` to display all hosts in one card.

---

## License

[Apache License 2.0](LICENSE)
