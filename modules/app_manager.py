from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

from core.adb_manager import ADBManager
from core.utils import CommandResult


class AppManagerModule:
    def __init__(self, adb: ADBManager) -> None:
        self.adb = adb

    def list_packages(self, serial: str, include_system: bool = True) -> list[str]:
        flag = "-s" if include_system else "-3"
        result = self.adb.run(["shell", "pm", "list", "packages", flag], serial=serial)
        if not result.ok:
            return []
        return [line.replace("package:", "").strip() for line in result.stdout.splitlines() if line.strip()]

    def install_apk(self, serial: str, apk_path: Path, replace: bool = True) -> CommandResult:
        cmd = ["install"]
        if replace:
            cmd.append("-r")
        cmd.append(str(apk_path))
        return self.adb.run(cmd, serial=serial, timeout=180)

    def uninstall_package(self, serial: str, package_name: str, keep_data: bool = False) -> CommandResult:
        cmd = ["uninstall"]
        if keep_data:
            cmd.append("-k")
        cmd.append(package_name)
        return self.adb.run(cmd, serial=serial, timeout=60)

    def clear_app_data(self, serial: str, package_name: str) -> CommandResult:
        return self.adb.run(["shell", "pm", "clear", package_name], serial=serial)

    def enable_app(self, serial: str, package_name: str, enabled: bool = True) -> CommandResult:
        action = "enable" if enabled else "disable-user"
        return self.adb.run(["shell", "pm", action, package_name], serial=serial)

    def backup_apk(self, serial: str, package_name: str, dest_file: Path) -> CommandResult:
        path_result = self.adb.run(["shell", "pm", "path", package_name], serial=serial)
        if not path_result.ok or not path_result.stdout:
            return path_result
        apk_line = path_result.stdout.splitlines()[0].strip().replace("package:", "")
        return self.adb.run(["pull", apk_line, str(dest_file)], serial=serial)

    def apk_remote_paths(self, serial: str, package_name: str) -> list[str]:
        result = self.adb.run(["shell", "pm", "path", package_name], serial=serial)
        if not result.ok or not result.stdout:
            return []
        paths: list[str] = []
        for line in result.stdout.splitlines():
            text = line.strip()
            if not text.startswith("package:"):
                continue
            path = text.replace("package:", "", 1).strip()
            if path.endswith(".apk"):
                paths.append(path)
        if not paths:
            return []
        # Base APK first whenever possible, then the rest.
        paths.sort(key=lambda p: (0 if p.endswith("/base.apk") else 1, len(p)))
        return paths

    def fetch_app_icon(self, serial: str, package_name: str, cache_dir: Path) -> Path | None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(f"{serial}:{package_name}".encode("utf-8")).hexdigest()[:20]
        missing_marker = cache_dir / f"{key}.missing"

        for ext in ("png", "webp", "jpg", "jpeg"):
            cached = cache_dir / f"{key}.{ext}"
            if cached.exists() and cached.stat().st_size > 0:
                return cached
        if missing_marker.exists():
            return None

        remote_apks = self.apk_remote_paths(serial, package_name)
        if not remote_apks:
            missing_marker.touch(exist_ok=True)
            return None

        for index, remote_apk in enumerate(remote_apks):
            local_apk = cache_dir / f"{key}.{index}.apk"
            pull = self.adb.run(["pull", remote_apk, str(local_apk)], serial=serial, timeout=120)
            if not pull.ok or not local_apk.exists():
                local_apk.unlink(missing_ok=True)
                continue

            best_name = self._pick_best_icon_file(local_apk)
            if not best_name:
                local_apk.unlink(missing_ok=True)
                continue

            out_ext = Path(best_name).suffix.lower().lstrip(".") or "png"
            icon_out = cache_dir / f"{key}.{out_ext}"
            try:
                with zipfile.ZipFile(local_apk) as zf:
                    data = zf.read(best_name)
                icon_out.write_bytes(data)
                if icon_out.stat().st_size == 0:
                    icon_out.unlink(missing_ok=True)
                    continue
                missing_marker.unlink(missing_ok=True)
                return icon_out
            except Exception:  # noqa: BLE001
                icon_out.unlink(missing_ok=True)
                continue
            finally:
                local_apk.unlink(missing_ok=True)

        missing_marker.touch(exist_ok=True)
        return None

    def _pick_best_icon_file(self, apk_file: Path) -> str | None:
        try:
            with zipfile.ZipFile(apk_file) as zf:
                names = zf.namelist()
                infos = {info.filename: info.file_size for info in zf.infolist()}
        except Exception:  # noqa: BLE001
            return None

        base_candidates: list[str] = []
        for name in names:
            low = name.lower()
            if not low.startswith("res/"):
                continue
            if not (low.endswith(".png") or low.endswith(".webp") or low.endswith(".jpg") or low.endswith(".jpeg")):
                continue
            if "/mipmap" not in low and "/drawable" not in low:
                continue
            base_candidates.append(name)

        if not base_candidates:
            return None

        keyword_candidates = [
            name
            for name in base_candidates
            if any(token in name.lower() for token in ("launcher", "icon", "logo", "app"))
            or re.search(r"/ic_[a-z0-9_]+", name.lower())
        ]
        candidates = keyword_candidates or base_candidates

        def score(path: str) -> tuple[int, int, int, int]:
            low = path.lower()
            density_score = 0
            for marker, value in (
                ("xxxhdpi", 6),
                ("xxhdpi", 5),
                ("xhdpi", 4),
                ("hdpi", 3),
                ("mdpi", 2),
                ("ldpi", 1),
            ):
                if marker in low:
                    density_score = value
                    break
            launcher_bonus = 3 if "ic_launcher" in low else 0
            keyword_bonus = 2 if any(token in low for token in ("launcher", "icon", "logo")) else 0
            mipmap_bonus = 1 if "/mipmap" in low else 0
            extension_bonus = 1 if low.endswith(".png") else 0
            size_bonus = int(min(infos.get(path, 0), 2_000_000) / 4096)
            return (
                density_score + launcher_bonus + keyword_bonus + mipmap_bonus,
                size_bonus,
                extension_bonus,
                len(path),
            )

        candidates.sort(key=score, reverse=True)
        return candidates[0]
