from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from uuid import uuid4

from core.utils import ConfigManager


@dataclass(slots=True)
class DeviceProfile:
    profile_id: str
    alias: str
    serial: str
    wifi_endpoint: str = ""
    favorite_local_path: str = ""
    favorite_remote_path: str = ""
    last_actions: list[str] | None = None
    favorite_commands: list[str] | None = None
    ui_theme: str = "dark"
    ui_density: str = "comfortable"
    language: str = "fr"
    tags: list[str] | None = None
    last_seen: str = ""


class DeviceProfilesModule:
    def __init__(self, config: ConfigManager) -> None:
        self.config = config

    def list_profiles(self) -> list[DeviceProfile]:
        raw = self.config.get("profiles.devices", [])
        out: list[DeviceProfile] = []
        if not isinstance(raw, list):
            return out
        for row in raw:
            if not isinstance(row, dict):
                continue
            profile_id = str(row.get("profile_id") or uuid4().hex[:10])
            alias = str(row.get("alias", "")).strip()
            serial = str(row.get("serial", "")).strip()
            if not alias or not serial:
                continue
            out.append(
                DeviceProfile(
                    profile_id=profile_id,
                    alias=alias,
                    serial=serial,
                    wifi_endpoint=str(row.get("wifi_endpoint", "")).strip(),
                    favorite_local_path=str(row.get("favorite_local_path", "")).strip(),
                    favorite_remote_path=str(row.get("favorite_remote_path", "")).strip(),
                    last_actions=self._to_list(row.get("last_actions")),
                    favorite_commands=self._to_list(row.get("favorite_commands")),
                    ui_theme=str(row.get("ui_theme", "dark")).strip() or "dark",
                    ui_density=str(row.get("ui_density", "comfortable")).strip() or "comfortable",
                    language=str(row.get("language", "fr")).strip() or "fr",
                    tags=self._to_list(row.get("tags")),
                    last_seen=str(row.get("last_seen", "")).strip(),
                )
            )
        out.sort(key=lambda p: p.alias.lower())
        return out

    def save_profile(self, profile: DeviceProfile) -> DeviceProfile:
        current = self.list_profiles()
        profile.last_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not profile.profile_id:
            profile.profile_id = uuid4().hex[:10]

        updated: list[DeviceProfile] = []
        replaced = False
        for p in current:
            if p.profile_id == profile.profile_id:
                updated.append(profile)
                replaced = True
            else:
                updated.append(p)
        if not replaced:
            updated.append(profile)
        self._persist(updated)
        return profile

    def delete_profile(self, profile_id: str) -> None:
        profile_id = profile_id.strip()
        if not profile_id:
            return
        current = [p for p in self.list_profiles() if p.profile_id != profile_id]
        self._persist(current)

    def find_match(self, serial: str) -> DeviceProfile | None:
        serial = serial.strip()
        if not serial:
            return None
        for p in self.list_profiles():
            if p.serial == serial:
                return p
        return None

    def _persist(self, profiles: list[DeviceProfile]) -> None:
        payload = []
        for p in profiles:
            data = asdict(p)
            data["last_actions"] = data.get("last_actions") or []
            data["favorite_commands"] = data.get("favorite_commands") or []
            data["tags"] = data.get("tags") or []
            payload.append(data)
        self.config.set("profiles.devices", payload)
        self.config.save()

    def _to_list(self, value) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return out
