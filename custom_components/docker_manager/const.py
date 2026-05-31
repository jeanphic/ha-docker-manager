"""Constants for Docker Manager integration."""

DOMAIN = "docker_manager"

PLATFORMS = ["sensor", "switch", "button", "update"]

# Config
CONF_URL = "url"
CONF_CONTAINERS_EXCLUDE = "containers_exclude"
CONF_CONTAINERS_INCLUDE = "containers_include"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_URL = "unix:///var/run/docker.sock"
DEFAULT_SCAN_INTERVAL = 30  # seconds
DEFAULT_UPDATE_CHECK_INTERVAL = 3600  # 1 hour

# Container states
STATE_RUNNING = "running"
STATE_EXITED = "exited"
STATE_PAUSED = "paused"
STATE_RESTARTING = "restarting"
STATE_DEAD = "dead"
STATE_CREATED = "created"
STATE_REMOVING = "removing"

# Sensor types - global Docker stats
SENSOR_CONTAINERS_TOTAL = "containers_total"
SENSOR_CONTAINERS_RUNNING = "containers_running"
SENSOR_CONTAINERS_PAUSED = "containers_paused"
SENSOR_CONTAINERS_STOPPED = "containers_stopped"
SENSOR_DOCKER_VERSION = "docker_version"
SENSOR_IMAGES_TOTAL = "images_total"

# Sensor types - per container
SENSOR_STATE = "state"
SENSOR_STATUS = "status"
SENSOR_UPTIME = "uptime"
SENSOR_IMAGE = "image"
SENSOR_HEALTH = "health"
SENSOR_CPU_PERCENT = "cpu_percent"
SENSOR_MEMORY_MB = "memory_mb"
SENSOR_MEMORY_PERCENT = "memory_percent"
SENSOR_NET_SPEED_UP = "network_speed_up"
SENSOR_NET_SPEED_DOWN = "network_speed_down"
SENSOR_NET_TOTAL_UP = "network_total_up"
SENSOR_NET_TOTAL_DOWN = "network_total_down"

# HA container name (to prevent accidental stop)
HA_CONTAINER_NAMES = [
    "homeassistant",
    "home-assistant",
    "hass",
    "ha",
]

# Icon mapping
ICON_DOCKER = "mdi:docker"
ICON_CONTAINER = "mdi:package-variant"
ICON_CPU = "mdi:chip"
ICON_MEMORY = "mdi:memory"
ICON_NETWORK = "mdi:network"
ICON_UPDATE = "mdi:update"
ICON_RESTART = "mdi:restart"
ICON_PRUNE = "mdi:broom"
