# Docker Manager pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jeanphic/ha-docker-manager.svg)](https://github.com/jeanphic/ha-docker-manager/releases)
[![License](https://img.shields.io/github/license/jeanphic/ha-docker-manager.svg)](LICENSE)

**Supervisez, contrôlez et mettez à jour vos conteneurs Docker directement depuis Home Assistant.**

> 🇬🇧 [English documentation available here](README.md)

---

## Fonctionnalités

### 📊 Supervision
- État et statut de chaque conteneur (`running`, `exited`, `paused`, `restarting`, `dead`, `created`, `removing`)
- CPU (%), RAM (MB + %), débit réseau (montant/descendant kB/s), totaux réseau (MB)
- Santé (si HEALTHCHECK configuré dans l'image), uptime, image utilisée
- Stats globales Docker : total / running / stopped / paused, nombre d'images, version Docker

### 🎛 Contrôle
- **Switch** start/stop par conteneur
- **Bouton** restart par conteneur
- **Protection** : le conteneur Home Assistant ne peut pas être arrêté

### 🔄 Mises à jour
- **Bouton "Check for update"** par conteneur — zéro téléchargement, simple requête API registry
  - Compatible Docker Hub, GHCR, lscr.io et tout registry OCI avec authentification Bearer
- **Entité Update** native HA : pull + recréation en un clic avec config préservée (volumes, ports, env, réseaux)
- Progression par étapes pendant la mise à jour
- `update_available` remis à `False` automatiquement après installation — que ce soit depuis la carte, le panneau Mises à jour de HA, ou une automation
- **Vérification automatique** : intervalle configurable en arrière-plan (désactivé par défaut)

### 🧹 Maintenance
- **Service** `docker_manager.prune_images` : supprime les images inutilisées
  - `all_unused: false` (défaut) — uniquement les images sans tag (dangling)
  - `all_unused: true` — toutes les images non utilisées par un conteneur

---

## Installation

### Via HACS (recommandé)
1. HACS → Intégrations → **+** → cherchez "Docker Manager"
2. Installez et redémarrez HA

### Manuel
1. Copiez `custom_components/docker_manager` dans `<config>/custom_components/`
2. Redémarrez Home Assistant

---

## Configuration

### Prérequis

#### HA dans Docker
Montez le socket Docker :
```yaml
services:
  homeassistant:
    image: homeassistant/home-assistant
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config
```

#### HA OS / Supervised
Utilisez un proxy de socket :
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
Puis configurez avec l'URL `http://<IP_HOTE>:2375`.

### Configuration dans HA
1. **Paramètres** → **Appareils & Services** → **Ajouter une intégration** → "Docker Manager"
2. Choisissez **Local** (socket Unix) ou **Distant** (TCP)
3. Sélectionnez les conteneurs à superviser (tous cochés par défaut)
4. Validez

### Options (après installation)
**Paramètres** → **Appareils & Services** → Docker Manager → **Configurer** :

| Option | Défaut | Description |
|--------|--------|-------------|
| Conteneurs à superviser | tous | Ajouter/retirer des conteneurs à tout moment |
| Intervalle de mise à jour | 30s | Fréquence de rafraîchissement des stats (5–300s) |
| Intervalle de vérification automatique | 0 (désactivé) | 0=désactivé, 3600=toutes les heures, 86400=quotidien |

---

## Entités créées

### Appareil global "Docker"
| Entité | Type | Description |
|--------|------|-------------|
| `sensor.docker_containers_total` | Capteur | Total conteneurs |
| `sensor.docker_containers_running` | Capteur | Conteneurs en cours |
| `sensor.docker_containers_stopped` | Capteur | Conteneurs arrêtés |
| `sensor.docker_containers_paused` | Capteur | Conteneurs en pause |
| `sensor.docker_images_total` | Capteur | Total images |
| `sensor.docker_docker_version` | Capteur (diagnostic) | Version du démon Docker |

### Par conteneur (ex: `nginx`)
| Entité | Catégorie | Description |
|--------|-----------|-------------|
| `switch.nginx_container` | Contrôle | Démarrer / Arrêter |
| `button.nginx_restart` | Contrôle | Redémarrer |
| `button.nginx_check_for_update` | Contrôle | Vérifier le registry (sans téléchargement) |
| `update.nginx_update` | Mise à jour | Statut + installation |
| `sensor.nginx_state` | Capteur | État (`running`, `exited`…) |
| `sensor.nginx_image` | Capteur | Image utilisée |
| `sensor.nginx_status` | Diagnostic | Statut lisible ("Up 3 days") |
| `sensor.nginx_health` | Diagnostic | Résultat du healthcheck (si configuré dans l'image) |
| `sensor.nginx_started_at` | Diagnostic | Date de démarrage |
| `sensor.nginx_cpu` | Diagnostic | CPU % |
| `sensor.nginx_memory` | Diagnostic | RAM en MB |
| `sensor.nginx_memory_2` | Diagnostic | RAM en % |
| `sensor.nginx_network_up` | Diagnostic | Débit montant (kB/s) |
| `sensor.nginx_network_down` | Diagnostic | Débit descendant (kB/s) |
| `sensor.nginx_network_total_up` | Diagnostic | Total monté (MB) |
| `sensor.nginx_network_total_down` | Diagnostic | Total descendu (MB) |

---

## Service : Nettoyage des images

```yaml
# Supprimer uniquement les images sans tag (défaut, plus sûr)
service: docker_manager.prune_images

# Supprimer toutes les images non utilisées
service: docker_manager.prune_images
data:
  all_unused: true
```

---

## Cartes Lovelace

Deux cartes dédiées sont disponibles dans le package **[Docker Manager Card](https://github.com/jeanphic/ha-docker-manager-card)** :

### Carte conteneur
Affiche un conteneur avec vue compacte et détails dépliables.

```yaml
type: custom:docker-manager-card
entity: sensor.nginx_state
name: Nginx                   # optionnel
language: fr                  # optionnel : en, fr, de, es, nl (auto-détecté)
icon: mdi:nginx               # optionnel
icon_color: "#009639"         # optionnel
```

Overrides d'entités si renommées dans HA :
```yaml
entity_switch: switch.mon_nom_custom
entity_memory_pct: sensor.nginx_memory_2
# ... voir README de la carte pour la liste complète
```

### Carte globale
Affiche les stats globales Docker et un bouton de nettoyage.

```yaml
type: custom:docker-overview-card
name: Docker        # optionnel
all_unused: false   # true = nettoyer toutes les images inutilisées
```

Les deux cartes supportent **card_mod** via des variables CSS (`--dmc-bg`, `--dmc-text`, `--dmc-btn-stop-color`…).

---

## Exemples d'automations

```yaml
# Notification quand une mise à jour est disponible
automation:
  alias: "Docker - Mise à jour disponible"
  trigger:
    - platform: state
      entity_id: update.nginx_update
      to: "on"
  action:
    - service: notify.mobile_app
      data:
        title: "Mise à jour Docker disponible"
        message: "{{ trigger.to_state.attributes.title }} peut être mis à jour."

# Vérification automatique chaque nuit à 3h
automation:
  alias: "Docker - Vérification nocturne"
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

**Q : Peut-on arrêter le conteneur Home Assistant ?**
R : Non. Les conteneurs nommés `homeassistant`, `hass`, `home-assistant` ou `ha` sont protégés.

**Q : La mise à jour préserve-t-elle les volumes ?**
R : Oui. Le conteneur est recréé avec exactement la même `HostConfig` (volumes, ports, variables d'environnement, réseaux).

**Q : La détection fonctionne-t-elle avec des registries privés ?**
R : Oui, si votre démon Docker est déjà authentifié (`docker login`).

**Q : Que fait exactement la vérification automatique ?**
R : Elle interroge l'API du registry (sans téléchargement) pour chaque conteneur supervisé et met à jour les entités `update.*`. Elle n'installe PAS automatiquement les mises à jour.

**Q : Le capteur santé affiche "none" — est-ce normal ?**
R : Oui. Docker ne rapporte un état de santé que si l'image définit une directive `HEALTHCHECK`. La plupart des images ne l'ont pas. La carte Lovelace masque automatiquement cette tuile quand la valeur est `none`.

**Q : Peut-on superviser plusieurs hôtes Docker ?**
R : Pas encore en v2. Prévu pour une version future.

---

## Feuille de route

- **v1** ✅ Supervision, start/stop/restart, détection de mises à jour, prune
- **v2** ✅ Progression par étapes, vérification auto configurable, cartes Lovelace, reset update_available après installation
- **v3** 🔜 Multi-hôtes Docker, logs des conteneurs

---

## Crédits

Inspiré par [Monitor Docker](https://github.com/ualex73/monitor_docker) de @ualex73.

## Licence

[Apache License 2.0](LICENSE)
