# Docker Manager for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jeanphic/ha-docker-manager.svg)](https://github.com/jeanphic/ha-docker-manager/releases)
[![License](https://img.shields.io/github/license/jeanphic/ha-docker-manager.svg)](LICENSE)

**Supervise, control and update your Docker containers directly from Home Assistant.**

> 🇫🇷 [Documentation en français disponible ici](README.fr.md)

---

## Features

### 📊 Monitoring
- Container state and status (`running`, `exited`, `paused`…)
- CPU (%), RAM (MB + %), network (speed up/down, total up/down)
- Health check status (`healthy`, `unhealthy`), uptime, image name
- Global Docker stats: total / running / stopped / paused containers, images count

### 🎛 Control
- **Switch** to start/stop each container
- **Button** to restart each container
- **Safety lock**: the Home Assistant container itself cannot be stopped or restarted through this integration

### 🔄 Updates
- Automatic update detection (digest comparison against registry)
- Native HA **Update entity**: shows up in the HA Updates dashboard
- One-click update: pulls the latest image and recreates the container preserving its full config (volumes, ports, env vars, networks)
- Background check every hour

### 🧹 Maintenance
- **Service** `docker_manager.prune_images`: removes all unused Docker images to reclaim disk space

---

## Installation

### Via HACS (recommended)
1. Open HACS in Home Assistant
2. Integrations → **+** → search for "Docker Manager"
3. Install and restart HA

### Manual
1. Copy the `custom_components/docker_manager` folder into `<config>/custom_components/`
2. Restart Home Assistant

---

## Configuration

### Prerequisites depending on your setup

#### HA running in Docker (recommended)
Mount the Docker socket into the HA container:

```yaml
# docker-compose.yml
services:
  homeassistant:
    image: homeassistant/home-assistant
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config
```

#### HA OS / Supervised
The Docker socket is not directly accessible. Use a socket proxy instead:

```yaml
# docker-compose.yml — run this on the host machine
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

Then configure the integration with the URL `http://<HOST_IP>:2375`.

### Setup in HA
1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "Docker Manager"
3. Choose **Local** (Unix socket) or **Remote** (TCP)
4. Test the connection and confirm

---

## Entities

### Global "Docker" device
| Entity | Type | Description |
|--------|------|-------------|
| `sensor.docker_containers_total` | Sensor | Total number of containers |
| `sensor.docker_containers_running` | Sensor | Running containers |
| `sensor.docker_containers_stopped` | Sensor | Stopped containers |
| `sensor.docker_containers_paused` | Sensor | Paused containers |
| `sensor.docker_images_total` | Sensor | Total images |
| `sensor.docker_docker_version` | Sensor | Docker daemon version |

### Per container (e.g. `my_container`)
| Entity | Type | Description |
|--------|------|-------------|
| `switch.my_container_running` | Switch | Start / Stop |
| `button.my_container_restart` | Button | Restart |
| `update.my_container_update` | Update | Update available / install |
| `sensor.my_container_state` | Sensor | State (`running`, `exited`…) |
| `sensor.my_container_status` | Sensor | Human-readable status ("Up 3 days") |
| `sensor.my_container_cpu` | Sensor | CPU % |
| `sensor.my_container_memory` | Sensor | RAM in MB |
| `sensor.my_container_memory_percent` | Sensor | RAM % |
| `sensor.my_container_network_up` | Sensor | Upload speed (kB/s) |
| `sensor.my_container_network_down` | Sensor | Download speed (kB/s) |
| `sensor.my_container_network_total_up` | Sensor | Total uploaded (MB) |
| `sensor.my_container_network_total_down` | Sensor | Total downloaded (MB) |
| `sensor.my_container_image` | Sensor | Image in use |
| `sensor.my_container_health` | Sensor | Container health |
| `sensor.my_container_started_at` | Sensor | Start timestamp |

---

## Service: Prune images

```yaml
service: docker_manager.prune_images
```

Removes all Docker images not used by any active container.
Useful after updates to reclaim disk space.

---

## Automation example

```yaml
# Notify when a container update is available
automation:
  alias: "Docker - Update available notification"
  trigger:
    - platform: state
      entity_id: update.my_container_update
      to: "on"
  action:
    - service: notify.mobile_app
      data:
        title: "Docker - Update available"
        message: "{{ trigger.to_state.attributes.title }} can be updated."
```

---

## FAQ

**Q: Can I stop the Home Assistant container?**
A: No. The integration refuses to stop or restart containers named `homeassistant`, `hass`, `home-assistant` or `ha`.

**Q: Does the update preserve my volumes and settings?**
A: Yes. Recreation uses the exact same `HostConfig` (volumes, ports, environment variables, networks) as the original container.

**Q: Can I monitor multiple Docker hosts?**
A: Not yet in v1. Planned for v2 via multiple config entries.

**Q: Does update detection work with private registries?**
A: Yes, as long as your Docker daemon is already authenticated with the registry (`docker login`).

**Q: Does it work with images that don't have a `:latest` tag?**
A: Yes. If no tag is specified, `:latest` is assumed. Pinned tags (e.g. `:1.2.3`) are also compared against the registry.

---

## Roadmap

- **v1** ✅ Monitoring + start/stop/restart + update detection + prune
- **v2** 🔜 Multi-host Docker, recent logs access, dedicated Lovelace card, scheduled auto-update

---

## Credits

Inspired by [Monitor Docker](https://github.com/ualex73/monitor_docker) by @ualex73.

## License

[Apache License 2.0](LICENSE)
