from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass(frozen=True, slots=True)
class ADBCommandTemplate:
    name: str
    command: str
    description: str
    category: str
    root_required: str = "Non"
    placeholders: tuple[str, ...] = ()


DEFAULT_COMMAND_CATALOG: dict[str, list[ADBCommandTemplate]] = {
    "devices": [
        ADBCommandTemplate("Liste appareils", "devices -l", "Detecte les appareils connectes", "devices"),
        ADBCommandTemplate("Reboot system", "reboot", "Redemarre l'appareil", "devices"),
        ADBCommandTemplate("Reboot bootloader", "reboot bootloader", "Redemarre en bootloader", "devices"),
    ],
    "files": [
        ADBCommandTemplate("Lister /sdcard", "shell ls -la /sdcard", "Liste les fichiers du stockage", "files"),
        ADBCommandTemplate("Permissions", "shell stat /sdcard", "Affiche les permissions", "files"),
    ],
    "apps": [
        ADBCommandTemplate("Packages utilisateur", "shell pm list packages -3", "Liste apps utilisateur", "apps"),
        ADBCommandTemplate("Packages systeme", "shell pm list packages -s", "Liste apps systeme", "apps"),
        ADBCommandTemplate("Top activite", "shell dumpsys activity top", "Etat activite au premier plan", "apps"),
    ],
    "system": [
        ADBCommandTemplate("Prop build", "shell getprop", "Informations systeme Android", "system"),
        ADBCommandTemplate("Batterie", "shell dumpsys battery", "Etat batterie", "system"),
        ADBCommandTemplate("CPU", "shell top -n 1 -b", "Snapshot process CPU", "system"),
    ],
    "network": [
        ADBCommandTemplate("IP locale", "shell ip route", "Affiche route reseau", "network"),
        ADBCommandTemplate("WiFi status", "shell dumpsys wifi", "Etat du WiFi", "network"),
    ],
    "security": [
        ADBCommandTemplate("SELinux", "shell getenforce", "Etat SELinux", "security"),
        ADBCommandTemplate("Root check", "shell su -c id", "Teste l'acces root", "security"),
    ],
    "development": [
        ADBCommandTemplate("Logcat", "logcat -d", "Recupere les logs", "development"),
        ADBCommandTemplate("Bugreport", "bugreport", "Genere un rapport systeme", "development"),
    ],
    "automation": [
        ADBCommandTemplate("Wakeup", "shell input keyevent KEYCODE_WAKEUP", "Reveille l'appareil", "automation"),
        ADBCommandTemplate("Unlock swipe", "shell input swipe 300 1000 300 500", "Swipe de deblocage", "automation"),
    ],
}

DEFAULT_CATEGORY_TO_TEXT_CATEGORY = {
    "devices": "Connexion",
    "files": "Fichiers",
    "apps": "Applications",
    "system": "Système",
    "network": "Réseau",
    "security": "Sécurité",
    "development": "Debug",
    "automation": "Tests",
}


def _normalize_category_key(category: str) -> str:
    simplified = unicodedata.normalize("NFKD", category).encode("ascii", "ignore").decode("ascii")
    simplified = simplified.strip().lower()
    simplified = re.sub(r"[^a-z0-9]+", "_", simplified).strip("_")
    return simplified or "misc"


def _strip_adb_prefix(command: str) -> str:
    cmd = command.strip()
    if not cmd.lower().startswith("adb "):
        return cmd
    # Keep command payload after `adb`; UI executes through internal adb manager.
    return cmd[4:].strip()


def _normalize_external_command(command: str) -> str | None:
    cmd = command.strip()
    if not cmd.lower().startswith("adb "):
        return None
    payload = _strip_adb_prefix(cmd)

    # Skip multi-command host workflows that cannot run via a single subprocess argv.
    if "&&" in payload or "||" in payload or ";" in payload:
        return None

    # Detect shell operators in shell payload and run through sh -c on Android side.
    if payload.startswith("shell "):
        shell_payload = payload[len("shell ") :].strip()
        if re.search(r"\s(\||>|>>|<)\s", shell_payload):
            escaped = shell_payload.replace('"', '\\"')
            return f'shell sh -c "{escaped}"'
        return payload

    # Host-side redirections/pipes are not supported in this execution path.
    if re.search(r"\s(\||>|>>|<)\s", payload):
        return None

    return payload


def _auto_description(command: str, category: str) -> str:
    text = command.lower().strip()
    cat = category.strip() or "Divers"
    if text.startswith("devices"):
        return "Liste les appareils Android detectes (serial, transport, etat)."
    if text.startswith("connect "):
        return "Connecte un appareil Android en ADB TCP/IP via adresse IP:port."
    if text.startswith("disconnect"):
        return "Coupe la session ADB TCP/IP en cours."
    if text.startswith("push "):
        return "Transfere un fichier local vers l'appareil Android."
    if text.startswith("pull "):
        return "Recupere un fichier depuis l'appareil vers le poste local."
    if "pm list packages" in text:
        return "Affiche les packages Android installes selon les filtres de la commande."
    if text.startswith("install"):
        return "Installe un APK sur l'appareil Android cible."
    if "uninstall" in text:
        return "Desinstalle une application Android (suppression possible des donnees selon options)."
    if "logcat" in text:
        return "Recupere les logs Android pour debug et diagnostic."
    if "dumpsys battery" in text:
        return "Affiche l'etat batterie, temperature, charge et source d'alimentation."
    if "dumpsys" in text:
        return "Interroge un service systeme Android pour extraire son etat detaille."
    if text.startswith("shell getprop"):
        return "Lit les proprietes systeme Android (build, sdk, device, etc.)."
    if text.startswith("reboot"):
        return "Redemarre l'appareil (mode normal ou mode specifique selon argument)."
    if text.startswith("shell "):
        return f"Execute une commande shell Android dans la categorie '{cat}'."
    return f"Commande ADB de la categorie '{cat}'."


def _parse_reference_line(line: str) -> ADBCommandTemplate | None:
    # Expected format:
    # NOM | COMMANDE | CATÉGORIE | ROOT_REQUIS | DESCRIPTION
    if " | " not in line:
        return None
    parts_right = line.rsplit(" | ", 3)
    if len(parts_right) != 4:
        return None
    left, category, root_req, description = parts_right
    if " | " not in left:
        return None
    name, command = left.split(" | ", 1)
    name = name.strip()
    normalized = _normalize_external_command(command.strip())
    category = category.strip()
    root_req = root_req.strip()
    description = description.strip()
    if not name or normalized is None:
        return None
    placeholders = tuple(dict.fromkeys(re.findall(r"<([^>]+)>", normalized)))
    clean_description = description.strip()
    if clean_description.lower() in {"", "n/a", "na", "-", "todo", "tbd"}:
        clean_description = _auto_description(normalized, category)
    return ADBCommandTemplate(
        name=name,
        command=normalized,
        description=clean_description,
        category=category,
        root_required=root_req,
        placeholders=placeholders,
    )


def _load_external_commands(path: Path) -> dict[str, list[ADBCommandTemplate]]:
    catalog: dict[str, list[ADBCommandTemplate]] = {}
    if not path.exists():
        return catalog
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.exception("Unable to read external command file: %s", path)
        return catalog

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("---") or line.startswith("==="):
            continue
        if line.startswith("TOTAL:") or line.startswith("CATÉGORIES:") or line.startswith("LÉGENDE"):
            continue
        if line.lower().startswith("adb commandes compl") or line.lower().startswith("format:"):
            continue
        parsed = _parse_reference_line(line)
        if parsed is None:
            continue
        key = _normalize_category_key(parsed.category)
        catalog.setdefault(key, []).append(parsed)

    # Deduplicate by exact command per category while keeping order.
    deduped: dict[str, list[ADBCommandTemplate]] = {}
    for category, entries in catalog.items():
        seen: set[str] = set()
        cleaned: list[ADBCommandTemplate] = []
        for entry in entries:
            signature = entry.command.strip()
            if signature in seen:
                continue
            seen.add(signature)
            cleaned.append(entry)
        if cleaned:
            deduped[category] = cleaned
    return deduped


def _merge_entries(
    catalog: dict[str, list[ADBCommandTemplate]],
    category_label: str,
    entries: list[ADBCommandTemplate],
) -> None:
    key = _normalize_category_key(category_label)
    bucket = catalog.setdefault(key, [])
    known = {item.command for item in bucket}
    for entry in entries:
        if entry.command in known:
            continue
        bucket.append(entry)
        known.add(entry.command)


def load_command_catalog(external_file: Path | None = None) -> dict[str, list[ADBCommandTemplate]]:
    src = external_file or (Path(__file__).resolve().parents[1] / "adb_commands_complete.txt")
    external = _load_external_commands(src)
    if external:
        merged: dict[str, list[ADBCommandTemplate]] = {
            category: list(items) for category, items in external.items()
        }
        # Keep txt order/categories first, then append any internal fallback command not present.
        for default_key, entries in DEFAULT_COMMAND_CATALOG.items():
            label = DEFAULT_CATEGORY_TO_TEXT_CATEGORY.get(default_key, "Divers")
            remapped = [
                ADBCommandTemplate(
                    name=e.name,
                    command=e.command,
                    description=e.description,
                    category=label,
                    root_required=e.root_required,
                    placeholders=e.placeholders,
                )
                for e in entries
            ]
            _merge_entries(merged, label, remapped)
        logger.info("Loaded %s external ADB command categories from %s", len(external), src.name)
        return merged

    # No external file: expose internal defaults with FR category labels.
    merged: dict[str, list[ADBCommandTemplate]] = {}
    for default_key, entries in DEFAULT_COMMAND_CATALOG.items():
        label = DEFAULT_CATEGORY_TO_TEXT_CATEGORY.get(default_key, "Divers")
        remapped = [
            ADBCommandTemplate(
                name=e.name,
                command=e.command,
                description=e.description,
                category=label,
                root_required=e.root_required,
                placeholders=e.placeholders,
            )
            for e in entries
        ]
        _merge_entries(merged, label, remapped)
    return merged


COMMAND_CATALOG: dict[str, list[ADBCommandTemplate]] = load_command_catalog()


def all_commands() -> list[ADBCommandTemplate]:
    out: list[ADBCommandTemplate] = []
    for items in COMMAND_CATALOG.values():
        out.extend(items)
    return out
