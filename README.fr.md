# Docker Manager for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jeanphic/ha-docker-manager.svg)](https://github.com/jeanphic/ha-docker-manager/releases)
[![License](https://img.shields.io/github/license/jeanphic/ha-docker-manager.svg)](LICENSE)

Supervise, contrôle et mettez à jour vos conteneurs Docker directement depuis Home Assistant.

---

## Fonctionnalités

### 📊 Supervision
- État et statut de chaque conteneur (`running`, `exited`, `paused`…)
- CPU (%), RAM (MB + %), réseau (vitesse up/down, total up/down)
- Santé (`healthy`, `unhealthy`), uptime, image utilisée
- Stats globales Docker : total / running / stopped / paused / images

### 🎛 Contrôle
- **Switch** start/stop par conteneur
- **Button** restart par conteneur
- Protection : impossible d'arrêter/redémarrer le conteneur Home Assistant lui-même

### 🔄 Mises à jour
- Détection automatique des nouvelles versions (comparaison de digest)
- **Entité Update** native HA : affichée dans le tableau de bord Mises à jour
- Mise à jour en un clic : pull de l'image + recréation du conteneur avec sa config d'origine (volumes, ports, env, networks)
- Vérification toutes les heures en arrière-plan

### 🧹 Maintenance
- **Service** `docker_manager.prune_images` : supprime toutes les images inutilisées

---

## Installation

### Via HACS (recommandé)
1. Ouvrez HACS dans Home Assistant
2. Intégrations → **+** → cherchez "Docker Manager"
3. Installez et redémarrez HA

### Manuel
1. Copiez le dossier `custom_components/docker_manager` dans `<config>/custom_components/`
2. Redémarrez Home Assistant

---

## Configuration

### Prérequis selon votre installation

#### HA dans Docker (recommandé)
Montez le socket Docker dans le conteneur HA :

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
Le socket Docker n'est pas directement accessible. Utilisez un proxy :

```yaml
# docker-compose.yml — à démarrer sur la machine hôte
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

Puis configurez l'intégration avec l'URL `http://<IP_HOTE>:2375`.

### Setup dans HA
1. **Paramètres** → **Appareils & Services** → **Ajouter une intégration**
2. Cherchez "Docker Manager"
3. Choisissez **Local** (socket) ou **Distant** (TCP)
4. Testez et validez

---

## Entités créées

### Appareil global "Docker"
| Entité | Type | Description |
|--------|------|-------------|
| `sensor.docker_containers_total` | Sensor | Nombre total de conteneurs |
| `sensor.docker_containers_running` | Sensor | Conteneurs en cours |
| `sensor.docker_containers_stopped` | Sensor | Conteneurs arrêtés |
| `sensor.docker_containers_paused` | Sensor | Conteneurs en pause |
| `sensor.docker_images_total` | Sensor | Nombre d'images |
| `sensor.docker_docker_version` | Sensor | Version du démon Docker |

### Par conteneur (ex: `mon_conteneur`)
| Entité | Type | Description |
|--------|------|-------------|
| `switch.mon_conteneur_running` | Switch | Démarrer / Arrêter |
| `button.mon_conteneur_restart` | Button | Redémarrer |
| `update.mon_conteneur_update` | Update | Mise à jour disponible / installer |
| `sensor.mon_conteneur_state` | Sensor | État (`running`, `exited`…) |
| `sensor.mon_conteneur_status` | Sensor | Statut lisible ("Up 3 days") |
| `sensor.mon_conteneur_cpu` | Sensor | CPU % |
| `sensor.mon_conteneur_memory` | Sensor | RAM en MB |
| `sensor.mon_conteneur_memory_percent` | Sensor | RAM % |
| `sensor.mon_conteneur_network_up` | Sensor | Débit montant (kB/s) |
| `sensor.mon_conteneur_network_down` | Sensor | Débit descendant (kB/s) |
| `sensor.mon_conteneur_network_total_up` | Sensor | Total monté (MB) |
| `sensor.mon_conteneur_network_total_down` | Sensor | Total descendu (MB) |
| `sensor.mon_conteneur_image` | Sensor | Image utilisée |
| `sensor.mon_conteneur_health` | Sensor | Santé du conteneur |
| `sensor.mon_conteneur_started_at` | Sensor | Date de démarrage |

---

## Service : Prune images

```yaml
service: docker_manager.prune_images
```

Supprime toutes les images Docker non utilisées par un conteneur actif.  
Utile après des mises à jour pour récupérer de l'espace disque.

---

## Automatisation exemple

```yaml
# Notification quand une mise à jour est disponible
automation:
  alias: "Docker - Notification mise à jour"
  trigger:
    - platform: state
      entity_id: update.mon_conteneur_update
      to: "on"
  action:
    - service: notify.mobile_app
      data:
        title: "Docker - Mise à jour disponible"
        message: "{{ trigger.to_state.attributes.title }} peut être mis à jour."
```

---

## FAQ

**Q : Puis-je arrêter le conteneur Home Assistant ?**  
R : Non, une protection empêche l'arrêt ou le redémarrage de `homeassistant`, `hass`, `home-assistant` et `ha` via cette intégration.

**Q : La mise à jour préserve-t-elle les volumes ?**  
R : Oui. La recréation du conteneur utilise exactement la même `HostConfig` (volumes, ports, variables d'environnement, réseau).

**Q : Puis-je surveiller plusieurs hôtes Docker ?**  
R : Pas encore en v1. Prévu pour la v2 via plusieurs entrées de configuration.

**Q : La détection de mise à jour fonctionne-t-elle avec des registries privés ?**  
R : Oui, si votre démon Docker est déjà authentifié auprès du registry.

---

## Crédits

Inspiré par [Monitor Docker](https://github.com/ualex73/monitor_docker) de @ualex73.

## Licence

Apache License 2.0
