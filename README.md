# Docker Manager for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jeanphic/ha-docker-manager.svg)](https://github.com/jeanphic/ha-docker-manager/releases)
[![License](https://img.shields.io/github/license/jeanphic/ha-docker-manager.svg)](LICENSE)

**Supervise, control and update your Docker containers directly from Home Assistant.**

> 🇫🇷 [Documentation en français disponible ici](README.fr.md)

---

## Features

### 📊 Monitoring
- Container state and status (`running`, `exited`, `paused`, `restarting`, `dead`, `created`, `removing`)
- CPU (%), RAM (MB + %), network speed (up/down kB/s), network totals (MB)
- Health check status, uptime, image name
- Global Docker stats: total / running / stopped / paused containers, image count, Docker version

### 🎛 Control
- **Switch** to start/stop each container
- **Button** to restart each container
- **Safety lock**: the Home Assistant container cannot be stopped or restarted

### 🔄 Updates
- **Check for update** button per container — zero download, pure registry API query
  - Supports Docker Hub, GHCR, lscr.io and any OCI-compliant registry with Bearer auth
- **Update** entity: one-click pull + recreate preserving full config (volumes, ports, env, networks)
- Step-by-step progress display during update
- `update_available` automatically reset after install — whether triggered from the card, the HA Updates panel, or an automation
- **Auto update check**: configurable background interval (disabled by default)

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

#### HA OS / Supervised
Use a socket proxy:
```yaml
services:
  dockerproxy:
    image: tecnativa/docker-socket-proxy
    container_name: dockerproxy
    privileged: true
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    ports:
      - "2375:2375"
    environment:
      CONTAINERS: 1
      IMAGES: 1
      INFO: 1
      POST: 1
      BUILD: 1
      EXEC: 1
      NETWORKS: 1
      SERVICES: 1
```
Then configure with URL `http://<HOST_IP>:2375`.

### Setup in HA
1. **Settings** → **Devices & Services** → **Add Integration** → "Docker Manager"
2. Choose **Local** (Unix socket) or **Remote** (TCP)
3. Select which containers to monitor (all selected by default)
4. Save

### Options (after setup)
Go to **Settings** → **Devices & Services** → Docker Manager → **Configure**:

| Option | Default | Description |
|--------|---------|-------------|
| Containers to monitor | all | Add/remove containers anytime |
| Update interval | 30s | How often stats are refreshed (5–300s) |
| Auto update check interval | 0 (disabled) | Background check: 0=off, 3600=hourly, 86400=daily |

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
| `button.nginx_check_for_update` | Control | Check registry for update (no download) |
| `update.nginx_update` | Update | Shows update status, triggers install |
| `sensor.nginx_state` | Sensor | State (`running`, `exited`…) |
| `sensor.nginx_image` | Sensor | Image in use |
| `sensor.nginx_status` | Diagnostic | Human-readable status ("Up 3 days") |
| `sensor.nginx_health` | Diagnostic | Health check result (only if HEALTHCHECK configured) |
| `sensor.nginx_started_at` | Diagnostic | Start timestamp |
| `sensor.nginx_cpu` | Diagnostic | CPU % |
| `sensor.nginx_memory` | Diagnostic | RAM in MB |
| `sensor.nginx_memory_2` | Diagnostic | RAM in % |
| `sensor.nginx_network_up` | Diagnostic | Upload speed (kB/s) |
| `sensor.nginx_network_down` | Diagnostic | Download speed (kB/s) |
| `sensor.nginx_network_total_up` | Diagnostic | Total uploaded (MB) |
| `sensor.nginx_network_total_down` | Diagnostic | Total downloaded (MB) |

---

## Service: Prune images

```yaml
# Remove only dangling (untagged) images — safe default
service: docker_manager.prune_images

# Remove ALL images not used by any container
service: docker_manager.prune_images
data:
  all_unused: true
```

---

## Lovelace Cards

Two dedicated cards are available in the **[Docker Manager Card](https://github.com/jeanphic/ha-docker-manager-card)** package:

### Container card
Displays a single container with compact view and expandable stats.

```yaml
type: custom:docker-manager-card
entity: sensor.nginx_state
name: Nginx                   # optional
language: en                  # optional: en, fr, de, es, nl (auto-detected)
icon: mdi:nginx               # optional
icon_color: "#009639"         # optional
```

Supports entity overrides if renamed in HA:
```yaml
entity_switch: switch.my_custom_name
entity_memory_pct: sensor.nginx_memory_2
# ... see card README for full list
```

### Overview card
Displays global Docker stats and a prune button.

```yaml
type: custom:docker-overview-card
name: Docker        # optional
all_unused: false   # true = prune all unused images
```

Both cards support **card_mod** via CSS variables (`--dmc-bg`, `--dmc-text`, `--dmc-btn-stop-color`…).

---

## Automation example

```yaml
# Notify when an update is available
automation:
  alias: "Docker - Update available"
  trigger:
    - platform: state
      entity_id: update.nginx_update
      to: "on"
  action:
    - service: notify.mobile_app
      data:
        title: "Docker update available"
        message: "{{ trigger.to_state.attributes.title }} can be updated."

# Auto check for updates every night at 3am
automation:
  alias: "Docker - Nightly update check"
  trigger:
    - platform: time
      at: "03:00:00"
  action:
    - service: button.press
      target:
        entity_id:
          - button.nginx_check_for_update
          - button.zigbee2mqtt_check_for_update
```

---

## FAQ

**Q: Can I stop the Home Assistant container?**
A: No. Containers named `homeassistant`, `hass`, `home-assistant` or `ha` are protected.

**Q: Does the update preserve my volumes and settings?**
A: Yes. The container is recreated with the exact same `HostConfig` (volumes, ports, env vars, networks).

**Q: Does update detection work with private registries?**
A: Yes, as long as your Docker daemon is already authenticated (`docker login`).

**Q: What does "auto update check" do exactly?**
A: It queries the registry API (no download) for each monitored container at the configured interval and updates the `update.*` entities. It does NOT automatically install updates — that remains manual.

**Q: The health sensor shows "none" — is that normal?**
A: Yes. Docker only reports a health status if the image defines a `HEALTHCHECK` directive. Most images don't, so `none` is the expected value. The Lovelace card automatically hides the health tile when it is `none`.

**Q: Can I monitor multiple Docker hosts?**
A: Not in v2. Planned for a future version.

---

## Roadmap

- **v1** ✅ Monitoring, start/stop/restart, update detection, prune
- **v2** ✅ Step-by-step update progress, auto update check interval, Lovelace cards, update_available reset after install
- **v3** 🔜 Multi-host Docker, container logs

---

## Credits

Inspired by [Monitor Docker](https://github.com/ualex73/monitor_docker) by @ualex73.

## License

[Apache License 2.0](LICENSE)
