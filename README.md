# ADB Manager Pro

Application desktop Python (PySide6) pour piloter Android via ADB avec une interface moderne, modulaire et orientée production.

- Multi-appareils USB/Wi‑Fi
- Device Inspector detaille (infos appareil consolidees)
- ADB Health Check (diagnostic + remediation)
- Explorateur fichiers local/distant en double panneau
- Gestion applications (grille d'icones + App Risk View)
- Monitoring système, terminal debug, logcat live
- Automatisation scripts et batch executor avancé
- Captures écran/vidéo + aperçu intégré
- Device Profiles (sessions sauvegardees par appareil)

---

## Sommaire

1. [Objectif](#objectif)
2. [Fonctionnalités](#fonctionnalités)
3. [Architecture du projet](#architecture-du-projet)
4. [Prérequis](#prérequis)
5. [Installation](#installation)
6. [Lancement](#lancement)
7. [Guide d'utilisation](#guide-dutilisation)
8. [Sécurité et confidentialité](#sécurité-et-confidentialité)
9. [Commandes ADB et catalogue](#commandes-adb-et-catalogue)
10. [Captures d’écran](#captures-décran)
11. [Configuration](#configuration)
12. [Tests](#tests)
13. [Troubleshooting](#troubleshooting)
14. [Roadmap](#roadmap)
15. [Licence](#licence)

---

## Objectif

`ADB Manager Pro` fournit une couche UI complète au-dessus d’ADB pour:

- accélérer les opérations quotidiennes Android,
- réduire les erreurs humaines (confirmations critiques, safe mode),
- offrir une expérience utilisable par débutants et experts,
- rester extensible (catalogue commandes externe, modules séparés).

---

## Fonctionnalités

### 1) Connexion et appareils

- Détection auto périodique (`adb devices -l`)
- Badge appareil actif en temps réel
- Connexion Wi‑Fi ADB (IP/port)
- Pairing Wi‑Fi ADB sécurisé (`adb pair` + auto-détection mDNS + `adb connect`)
- Scan réseau ADB (subnet)
- Historique SQLite des événements
- Profils appareil persistants (autoload par serial)

### 1-bis) Device Inspector

- Vue synthetique par appareil:
  - marque / constructeur / modele / serial / transport
  - version Android + SDK
  - batterie, stockage libre/total
  - ABI/CPU, IP locale
  - resolution + densite ecran
  - statut debug + root
  - horodatage du dernier refresh
- Refresh manuel et export JSON
- Non destructif (lecture uniquement)

### 1-ter) ADB Health Check / Diagnostic

- Checks automatiques:
  - presence binaire ADB
  - version ADB
  - serveur ADB actif
  - appareil detecte / unauthorized / offline
  - type de transport (USB/Wi-Fi)
  - latence commande simple
  - commandes critiques non destructives (`getprop`, `pm list packages`)
  - etat pair/connect Wi-Fi si serial IP:PORT
- Resultat global: `OK` / `WARNING` / `ERROR`
- Remediation claire pour chaque check
- Export JSON du rapport

### 2) Gestionnaire de fichiers

- Double panneau: local ↔ téléphone
- Navigation en grille avec icônes (dossiers/fichiers)
- Boutons `Home`, `Parent`, `Racine /`
- Navigation par double-clic
- Recherche distante
- Push/Pull
- Sync navigation locale/distance (niveau équivalent)

### 3) Gestion applications

- Liste apps utilisateur/système
- Vue grille avec icônes applicatives
- Extraction d’icônes APK (cache local)
- Install / uninstall / clear data
- Utilisation du package réel en backend (actions fiables)
- App Risk View (informatif, local):
  - package, label, type user/system, version
  - date install/update (si accessible)
  - taille data/cache (best effort)
  - permissions detectees + permissions sensibles
  - score de risque simple `LOW/MEDIUM/HIGH`
  - recherche package, filtres risque, tri risque/perms
  - export JSON/CSV

### 4) Système / Monitoring

- Snapshot infos système Android
- Snapshot monitoring CPU/MEM
- Export rapport JSON

### 5) Automation

- Éditeur scripts ADB
- Bibliothèque scripts JSON
- Exécution script séquentielle

### 6) Debug avancé

- Terminal ADB avec auto-complétion
- Logcat live (start/stop + filtre + auto-scroll)
- Catalogue commandes riche:
  - catégories,
  - recherche,
  - favoris,
  - niveau root,
  - niveau risque,
  - domaine inféré,
  - placeholders `<...>`
- Confirmation renforcée sur commandes critiques
- Export documentation commandes (`.md` / `.pdf`)

### 7) Remote Control (scrcpy + ADB)

- Mode remote complet via `scrcpy` depuis l’onglet `Remote`
- Démarrage/arrêt piloté dans l’app
- Multi-appareils: lancement scrcpy par appareil ou `Start All`
- Device Control Center: cartes par appareil avec actions rapides (`Activer`, `Scrcpy`, `Wake`, `Shot`)
- Options vidéo (bitrate, max-size, fps) + flags (`fullscreen`, `always-on-top`, `view-only`, etc.)
- Logs scrcpy dans l’interface
- Actions de fallback ADB: Home/Back/Recents/Power/Volume/Notifications, envoi de texte, wake/unlock
- Scope des actions ADB: appareil ciblé, appareil actif, sélection multiple, ou tous les appareils connectés

### 6-ter) Sessions / Device Profiles

- Sauvegarde d'un profil par appareil (serial match):
  - alias
  - endpoint Wi-Fi favori (si applicable)
  - chemins favoris local/distant
  - commandes favorites
  - theme / densite / langue
  - tags optionnels
- Chargement manuel d'un profil
- Suppression profil
- Auto-chargement profil si appareil correspondant detecte

### 8) Batch Executor

- File de commandes (drag & drop)
- Exécution parallèle configurable (`workers`)
- Retry, timeout, stop on first error
- Pause / reprise / stop
- Progression live + métriques
- Export rapport batch JSON

### 9) Captures

- Screenshot appareil
- Enregistrement vidéo écran Android
- Aperçu image/vidéo intégré

---

## Architecture du projet

```text
adb_manager/
├── main.py
├── core/
│   ├── adb_manager.py
│   ├── commands.py
│   ├── device_manager.py
│   ├── plugin_manager.py
│   └── utils.py
├── gui/
│   ├── main_window.py
│   ├── styles.py
│   └── widgets/
│       ├── code_editor.py
│       ├── terminal_widget.py
│       └── toast.py
├── modules/
│   ├── app_manager.py
│   ├── automation.py
│   ├── backup_restore.py
│   ├── file_manager.py
│   └── system_info.py
├── config/
│   ├── settings.json
│   ├── commands.json
│   └── scripts.json
├── resources/
│   ├── icons/
│   └── themes/
├── tests/
│   ├── test_commands.py
│   └── test_utils.py
├── docs/
│   └── screenshots/
├── tools/
│   └── capture_ui_screenshots.py
└── requirements.txt
```

### Rôles

- `core/adb_manager.py`: exécution commandes ADB sync/async + safe mode
- `core/device_manager.py`: polling appareils + connectivité Wi‑Fi
- `core/commands.py`: parsing et enrichissement du catalogue ADB
- `modules/*`: logique métier par domaine
- `gui/main_window.py`: orchestration UI + interaction modules
- `gui/styles.py`: thèmes et densité
- `config/*`: paramètres persistants

---

## Prérequis

- Python 3.10+
- Android Platform Tools (`adb`) accessible dans le `PATH`
- Débogage USB activé sur le téléphone
- Autorisation RSA validée côté appareil

Optionnel:
- Appareil rooté pour commandes root

---

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dépendances principales:

- `PySide6`
- `qdarkstyle`

---

## Lancement

```bash
source .venv/bin/activate
python main.py
```

---

## Guide d'utilisation

### Démarrage rapide

1. Brancher l’appareil Android (USB) ou connecter en Wi‑Fi ADB.
2. Cliquer `Actualiser`.
3. Vérifier l’appareil actif dans le bandeau.
4. Utiliser les onglets selon besoin.

### Pairing Wi‑Fi (Android 11+)

1. Sur le téléphone: `Options développeur > Débogage sans fil > Associer avec code`.
2. Dans l’app: bouton `Pairing WiFi`.
3. Saisir `IP:PORT` de pairing + le code 6 chiffres.
4. L’app lance `adb pair`, détecte les endpoints `_adb-tls-connect` via mDNS puis lance `adb connect`.

### Pairing par QR code depuis l'app

Le bouton `Pairing QR` utilise un helper dédié (`adb-connect-qr`) pour générer le QR et finaliser automatiquement le pairing/connect.

Installation:

```bash
source .venv/bin/activate
pip install adb-connect-qr
```

### Remote multi-appareils (usage recommandé)

1. Ouvrir l’onglet `Remote`.
2. Dans `Remote Scrcpy`, choisir une cible puis `Start Remote`, ou lancer `Start All`.
3. Dans `Actions ADB`, choisir le scope:
   - `Appareil cible`,
   - `Appareil actif (top bar)`,
   - `Selection multiple` (cocher les appareils),
   - `Tous les appareils`.
4. Utiliser les actions fallback (touches système + envoi de texte) selon la cible choisie.

### Device Inspector & Health Check

1. Ouvrir `Dashboard`.
2. Lancer `Refresh Inspector` pour rafraichir la fiche appareil.
3. Lancer `Run Health Check` pour obtenir l'etat global ADB.
4. Exporter en JSON pour un diagnostic partageable.

### App Risk View

1. Ouvrir `Applications` puis `Charger apps`.
2. Utiliser recherche + filtre de risque + tri.
3. Selectionner une app pour voir les details et permissions sensibles.
4. Exporter l'analyse en JSON/CSV.

### Raccourcis

- `Ctrl+1..9`: navigation onglets
- `Ctrl+B`: afficher/masquer sidebar
- `Ctrl+K`: focus recherche commandes (palette rapide)

### Flux fichiers recommandé

1. Se placer sur dossier local cible.
2. Se placer sur dossier distant cible.
3. `Push` ou `Pull`.
4. Utiliser `Sync local -> distant` / `Sync distant -> local` pour rester aligné.

### Flux debug recommandé

1. Filtrer le catalogue commandes.
2. Lire `Details commande` (risque + astuce).
3. Exécuter via `Executer selection`.
4. Si critique: confirmation explicite requise.

---

## Sécurité et confidentialité

Le projet est préparé pour publication sans données personnelles.

### Mesures appliquées

- Exclusion des artefacts sensibles via `.gitignore`:
  - `adb_manager.log`
  - `config/history.db`
  - `backups/`
  - `captures/`
  - environnements virtuels
- Safe mode actif par défaut (`app.safe_mode = true`)
- Blocage commandes destructrices connues en mode sécurisé
- Confirmation des commandes critiques dans l’UI
- Aucun contournement de securite / bypass / root trick n'est implemente
- Outil destine a l'administration locale et l'automatisation ADB legitime

### Safe usage

- Prerequis obligatoire: ADB installe et accessible via `PATH`
- Debogage USB ou Debogage sans fil active sur le terminal Android
- Autorisation RSA a valider sur le terminal
- Les modules Device Inspector / Health Check / App Risk sont informatifs (pas un scanner offensif)

### Avant publication (checklist)

- [ ] Vérifier qu’aucun log runtime n’est tracké
- [ ] Vérifier qu’aucun backup Android n’est présent
- [ ] Vérifier que `config/history.db` est absent
- [ ] Vérifier qu’aucune IP privée sensible n’est hardcodée

---

## Commandes ADB et catalogue

Le catalogue est alimenté par:

1. `adb_commands_complete.txt` (prioritaire)
2. fallback interne (`core/commands.py`)

Chaque commande expose:

- nom
- catégorie
- commande ADB
- statut root
- description
- placeholders
- niveau de risque
- domaine fonctionnel
- astuce d’usage

---

## Captures d’écran

Captures actuelles du projet v2 (dossier `screen/`):

![Screen V2 01](screen/screen-v2-01.png)
![Screen V2 02](screen/screen-v2-02.png)
![Screen V2 03](screen/screen-v2-03.png)
![Screen V2 04](screen/screen-v2-04.png)
![Screen V2 05](screen/screen-v2-05.png)
![Screen V2 06](screen/screen-v2-06.png)
![Screen V2 07](screen/screen-v2-07.png)
![Screen V2 08](screen/screen-v2-08.png)
![Screen V2 09](screen/screen-v2-09.png)

Génération automatique (optionnelle) de nouvelles captures:

```bash
source .venv/bin/activate
python tools/capture_ui_screenshots.py
```

---

## Configuration

Fichier principal: `config/settings.json`

Exemples clés:

- `app.theme`: `dark` / `light`
- `ui.density`: `comfortable` / `compact`
- `app.accent`: couleur d’accent
- `adb.default_timeout`
- `app.safe_mode`
- `app.scrcpy_bin`: binaire scrcpy (ex: `scrcpy`)
- `app.adb_qr_tool`: helper QR pairing (ex: `adb-connect-qr`)
- `ui.batch_workers`, `ui.batch_retry`, `ui.batch_timeout_s`
- `remote.scrcpy_*`: options remote scrcpy (bitrate/fps/flags/args)
- `remote.actions_scope`: `selected` / `active` / `checked` / `all`
- `remote.actions_checked`: liste persistée des appareils cochés
- `profiles.auto_load`: auto-load profil sur serial match
- `profiles.devices`: stockage des profils appareil

---

## Tests

```bash
python -m unittest discover -s tests -v
```

---

## Troubleshooting

### `adb` introuvable

- Installer Android Platform Tools
- Vérifier `which adb`

### Appareil `unauthorized`

- Rebrancher USB
- Accepter l’empreinte RSA sur Android
- `adb kill-server && adb start-server`

### Plugin Qt `xcb` introuvable (Linux)

Installer dépendances système Qt/XCB manquantes (ex: `libxcb-cursor0` selon distro).

### Commande root impossible

- Vérifier statut root de l’appareil
- Tester `adb shell su -c id`

### Pairing QR indisponible

- Installer le helper: `pip install adb-connect-qr`
- Vérifier ensuite le binaire: `which adb-connect-qr`

---

## Roadmap

- Prévisualisation média enrichie (thumbnail vidéo)
- Synchronisation dossiers avec stratégies (`mirror`, `two-way`)
- Plugin system plus avancé
- Profiler application Android intégré

---

## Licence

Choisir une licence (`MIT` recommandé) avant diffusion publique si nécessaire.
