from __future__ import annotations

import hashlib
import re
import zipfile
from datetime import datetime
from pathlib import Path

from core.adb_manager import ADBManager
from core.utils import CommandResult

SENSITIVE_PERMISSIONS = {
    "android.permission.INTERNET",
    "android.permission.READ_SMS",
    "android.permission.SEND_SMS",
    "android.permission.RECORD_AUDIO",
    "android.permission.CAMERA",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.READ_CONTACTS",
    "android.permission.READ_CALL_LOG",
    "android.permission.WRITE_SETTINGS",
    "android.permission.PACKAGE_USAGE_STATS",
}


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

    def analyze_app(self, serial: str, package_name: str) -> dict[str, object]:
        data: dict[str, object] = {
            "package": package_name,
            "label": package_name.split(".")[-1] if package_name else "app",
            "type": "unknown",
            "version": "n/a",
            "first_install_time": "n/a",
            "last_update_time": "n/a",
            "code_path": "n/a",
            "data_size": "n/a",
            "cache_size": "n/a",
            "permissions": [],
            "sensitive_permissions": [],
            "permission_count": 0,
            "risk": "LOW",
            "risk_score": 0,
            "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        dump = self.adb.run(["shell", "dumpsys", "package", package_name], serial=serial, timeout=20)
        if not dump.ok or not dump.stdout:
            data["error"] = dump.stderr or "dumpsys package failed"
            return data

        text = dump.stdout
        code_path = self._first_match(text, r"codePath=([^\n\r]+)")
        version_name = self._first_match(text, r"versionName=([^\n\r]+)")
        first_install = self._first_match(text, r"firstInstallTime=([^\n\r]+)")
        last_update = self._first_match(text, r"lastUpdateTime=([^\n\r]+)")

        if version_name:
            data["version"] = version_name
        if first_install:
            data["first_install_time"] = first_install
        if last_update:
            data["last_update_time"] = last_update
        if code_path:
            data["code_path"] = code_path

        app_type = self._infer_app_type(text, code_path)
        data["type"] = app_type

        permissions = self._extract_permissions(text)
        sensitive = sorted([p for p in permissions if p in SENSITIVE_PERMISSIONS])
        data["permissions"] = sorted(permissions)
        data["sensitive_permissions"] = sensitive
        data["permission_count"] = len(permissions)

        risk, risk_score = self.compute_risk_level(permissions=permissions, app_type=app_type, code_path=code_path)
        data["risk"] = risk
        data["risk_score"] = risk_score

        # Best effort: sizes may be unavailable without elevated permissions.
        size_data = self.adb.run(["shell", "du", "-sk", f"/data/user/0/{package_name}"], serial=serial, timeout=8)
        if size_data.ok and size_data.stdout:
            kb = self._parse_du_kb(size_data.stdout)
            if kb > 0:
                data["data_size"] = self._fmt_bytes(kb * 1024)
        size_cache = self.adb.run(["shell", "du", "-sk", f"/data/user/0/{package_name}/cache"], serial=serial, timeout=8)
        if size_cache.ok and size_cache.stdout:
            kb = self._parse_du_kb(size_cache.stdout)
            if kb >= 0:
                data["cache_size"] = self._fmt_bytes(kb * 1024)

        return data

    def compute_risk_level(self, permissions: list[str], app_type: str, code_path: str) -> tuple[str, int]:
        sensitive_count = sum(1 for p in permissions if p in SENSITIVE_PERMISSIONS)
        score = sensitive_count * 3

        total = len(permissions)
        if total >= 25:
            score += 3
        elif total >= 15:
            score += 2
        elif total >= 8:
            score += 1

        if app_type == "system":
            if code_path and not code_path.startswith("/system/"):
                # System package outside /system often means privileged vendor/update context.
                score += 2
            else:
                score += 1

        if score >= 8:
            return ("HIGH", score)
        if score >= 4:
            return ("MEDIUM", score)
        return ("LOW", score)

    def _first_match(self, text: str, pattern: str) -> str:
        m = re.search(pattern, text)
        return m.group(1).strip() if m else ""

    def _infer_app_type(self, dump: str, code_path: str) -> str:
        low = dump.lower()
        path = (code_path or "").lower()
        if "pkgflags=[" in low and (" system " in low or " privileged " in low):
            return "system"
        if path.startswith("/system/") or path.startswith("/product/") or path.startswith("/vendor/"):
            return "system"
        return "user"

    def _extract_permissions(self, dump: str) -> list[str]:
        found: set[str] = set()
        for line in dump.splitlines():
            text = line.strip()
            for perm in re.findall(r"android\\.permission\\.[A-Z0-9_]+", text):
                found.add(perm)
        return sorted(found)

    def _parse_du_kb(self, text: str) -> int:
        if not text:
            return 0
        line = text.splitlines()[0].strip()
        parts = re.split(r"\\s+", line)
        if not parts:
            return 0
        try:
            return int(parts[0])
        except ValueError:
            return 0

    def _fmt_bytes(self, value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        v = float(max(0, value))
        for unit in units:
            if v < 1024 or unit == units[-1]:
                return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} {unit}"
            v /= 1024
        return f"{int(value)} B"
