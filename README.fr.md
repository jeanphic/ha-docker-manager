# Docker Manager pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/jeanphic/ha-docker-manager.svg)](https://github.com/jeanphic/ha-docker-manager/releases)

**Supervisez, contrôlez et mettez à jour vos conteneurs Docker depuis Home Assistant.**

> 🇬🇧 [English documentation](README.md)

---

## Fonctionnalités

### 📊 Supervision
- État des conteneurs (`running`, `exited`, `paused`, `restarting`, `dead`, `created`, `removing`)
- CPU (%), RAM (MB + %), débit réseau (montant/descendant kB/s)
- Santé, uptime, image utilisée
- Stats globales Docker : total / running / stopped / paused, images, version

### 🎛 Contrôle
- **Switch** start/stop par conteneur
- **Bouton Restart** par conteneur
- **Bouton Pause / Reprendre** par conteneur (toggle)
- **Protection** : le conteneur Home Assistant ne peut pas être arrêté, redémarré ou mis en pause

### 🔄 Mises à jour
- **Bouton Check** par conteneur — zéro téléchargement, API registry uniquement
- **Entité Update** : pull + recréation en un clic (volumes, ports, env, réseaux préservés)
- `update_available` remis à `False` automatiquement après installation
- **Vérification automatique** : premier check 60s après démarrage, puis à l'intervalle configuré. Double-passe pour les images sans RepoDigest

### 💾 Persistence des états
- Les conteneurs arrêtés ou en pause avant un reboot HA retrouvent leur état automatiquement après redémarrage

### 🧹 Maintenance
- **Service** `docker_manager.prune_images` : supprime les images inutilisées
  - `all_unused: false` (défaut) — images sans tag uniquement
  - `all_unused: true` — toutes les images non utilisées

---

## Installation

### Via HACS (recommandé)
1. HACS → Intégrations → **+** → "Docker Manager"
2. Installez et redémarrez HA

### Manuel
1. Copiez `custom_components/docker_manager` dans `<config>/custom_components/`
2. Redémarrez Home Assistant

---

## Configuration

### Prérequis

#### HA dans Docker
```yaml
services:
  homeassistant:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config
```

#### HA OS / Supervised — proxy de socket
```yaml
services:
  dockerproxy:
    image: tecnativa/docker-socket-proxy
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
URL à configurer : `http://<IP_HOTE>:2375`

### Configuration dans HA
1. **Paramètres** → **Appareils & Services** → **Ajouter** → "Docker Manager"
2. Choisissez **Local** ou **Distant (TCP)**
3. Sélectionnez les conteneurs à superviser
4. Validez

### Options
**Paramètres** → Docker Manager → **Configurer** :

| Option | Défaut | Description |
|--------|--------|-------------|
| Conteneurs à superviser | tous | Modifiable à tout moment |
| Intervalle de mise à jour | 30s | Fréquence de rafraîchissement (5–300s) |
| Intervalle de vérification auto | 0 (désactivé) | 0=désactivé, 3600=horaire, 86400=quotidien |

---

## Entités créées

### Appareil global "Docker"
| Entité | Description |
|--------|-------------|
| `sensor.docker_containers_total` | Total conteneurs |
| `sensor.docker_containers_running` | En cours |
| `sensor.docker_containers_stopped` | Arrêtés |
| `sensor.docker_containers_paused` | En pause |
| `sensor.docker_images_total` | Total images |
| `sensor.docker_docker_version` | Version Docker |

### Par conteneur (ex: `nginx`)
| Entité | Catégorie | Description |
|--------|-----------|-------------|
| `switch.nginx_container` | Contrôle | Démarrer / Arrêter |
| `button.nginx_restart` | Contrôle | Redémarrer |
| `button.nginx_pause` | Contrôle | Pause / Reprendre |
| `button.nginx_check_for_update` | Contrôle | Vérifier le registry |
| `update.nginx_update` | Mise à jour | Statut + installation |
| `sensor.nginx_state` | Capteur | État |
| `sensor.nginx_cpu` | Diagnostic | CPU % |
| `sensor.nginx_memory` | Diagnostic | RAM MB |
| `sensor.nginx_memory_2` | Diagnostic | RAM % |
| `sensor.nginx_network_up` | Diagnostic | Débit montant (kB/s) |
| `sensor.nginx_network_down` | Diagnostic | Débit descendant (kB/s) |
| `sensor.nginx_health` | Diagnostic | Santé (si HEALTHCHECK configuré) |

---

## Service : Nettoyage des images

```yaml
service: docker_manager.prune_images           # images sans tag
service: docker_manager.prune_images
data:
  all_unused: true                             # toutes les images inutilisées
```

---

## Cartes Lovelace

Trois cartes disponibles : **[Docker Manager Card](https://github.com/jeanphic/ha-docker-manager-card)**

### docker-manager-card (par conteneur)
```yaml
type: custom:docker-manager-card
entity: sensor.nginx_state
name: Nginx
icon: mdi:nginx
```

### docker-overview-card (hôte unique)
```yaml
type: custom:docker-overview-card
name: Docker
suffix: ""        # "_2" pour la deuxième instance
tap_action:
  action: navigate
  navigation_path: /lovelace/docker
```

### docker-multi-overview-card (multi-hôtes)
```yaml
type: custom:docker-multi-overview-card
name: Hôtes Docker
hosts:
  - name: Local
    prefix: docker
  - name: Serveur distant
    prefix: docker
    suffix: "_2"
```

---

## FAQ

**Q : Peut-on arrêter le conteneur Home Assistant ?**
R : Non. Les conteneurs `homeassistant`, `hass`, `home-assistant` et `ha` sont protégés.

**Q : La mise à jour préserve-t-elle les volumes ?**
R : Oui. Le conteneur est recréé avec exactement la même `HostConfig`.

**Q : Le capteur santé affiche "none" — est-ce normal ?**
R : Oui, uniquement si l'image définit un `HEALTHCHECK`. La carte masque cette tuile automatiquement.

**Q : Peut-on superviser plusieurs hôtes Docker ?**
R : Oui — ajoutez plusieurs instances de l'intégration (une par hôte). Utilisez `docker-multi-overview-card` pour tout afficher dans une seule carte.

---

## Licence

[Apache License 2.0](LICENSE)
