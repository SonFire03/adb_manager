from __future__ import annotations

import re
import shutil
import time
from datetime import datetime

from core.adb_manager import ADBManager
from core.utils import DeviceInfo


class HealthCheckModule:
    def __init__(self, adb: ADBManager) -> None:
        self.adb = adb

    def run(self, devices: list[DeviceInfo], serial: str | None = None) -> dict:
        checks: list[dict[str, str]] = []

        adb_path = shutil.which(self.adb.adb_bin)
        if adb_path:
            checks.append(self._check("adb_binary", "OK", f"ADB trouve: {adb_path}", ""))
        else:
            checks.append(
                self._check(
                    "adb_binary",
                    "ERROR",
                    f"ADB introuvable ({self.adb.adb_bin})",
                    "Installer Android Platform Tools et verifier le PATH.",
                )
            )

        version = self.adb.run(["version"], timeout=8)
        if version.ok:
            line = (version.stdout.splitlines() or ["ADB version inconnue"])[0]
            checks.append(self._check("adb_version", "OK", line, ""))
        else:
            checks.append(
                self._check("adb_version", "ERROR", version.stderr or "Impossible de lire la version ADB", "Verifier l'installation ADB.")
            )

        server = self.adb.run(["start-server"], timeout=10)
        if server.ok:
            checks.append(self._check("adb_server", "OK", server.stderr or "Serveur ADB actif", ""))
        else:
            checks.append(
                self._check(
                    "adb_server",
                    "ERROR",
                    server.stderr or "Serveur ADB non actif",
                    "Relancer: adb kill-server && adb start-server",
                )
            )

        unauthorized = [d.serial for d in devices if d.state == "unauthorized"]
        offline = [d.serial for d in devices if d.state == "offline"]
        online = [d.serial for d in devices if d.state == "device"]

        if online:
            checks.append(self._check("device_detected", "OK", f"{len(online)} appareil(s) detecte(s)", ""))
        else:
            checks.append(
                self._check(
                    "device_detected",
                    "WARNING",
                    "Aucun appareil pret (state=device)",
                    "Reconnecter en USB puis valider RSA, ou verifier le meme reseau Wi-Fi.",
                )
            )

        if unauthorized:
            checks.append(
                self._check(
                    "device_auth",
                    "ERROR",
                    f"Appareil(s) unauthorized: {', '.join(unauthorized)}",
                    "Debloquer le telephone et accepter la cle RSA.",
                )
            )
        elif offline:
            checks.append(
                self._check(
                    "device_auth",
                    "WARNING",
                    f"Appareil(s) offline: {', '.join(offline)}",
                    "Reconnecter le cable USB ou relancer la connexion Wi-Fi ADB.",
                )
            )
        elif online:
            checks.append(self._check("device_auth", "OK", "Appareil autorise", ""))

        if online:
            transports = {d.transport for d in devices if d.state == "device"}
            checks.append(self._check("transport", "OK", f"Transport(s): {', '.join(sorted(transports))}", ""))
        else:
            checks.append(self._check("transport", "WARNING", "Transport indisponible", "Verifier USB/Wi-Fi debugging."))

        target = serial or (online[0] if online else None)
        if target:
            checks.append(self._latency_check(target))
            checks.extend(self._critical_non_destructive_checks(target))
            checks.append(self._pair_state_check(target))
        else:
            checks.append(self._check("latency", "WARNING", "Latence non testee (aucun appareil actif)", "Connecter un appareil."))

        status = self._global_status(checks)
        summary = self._build_summary(status, checks)
        return {
            "status": status,
            "summary": summary,
            "checks": checks,
            "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "target_serial": target or "",
        }

    def _latency_check(self, serial: str) -> dict[str, str]:
        t0 = time.perf_counter()
        res = self.adb.run(["shell", "echo", "ping"], serial=serial, timeout=8)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        if res.ok and "ping" in res.stdout:
            status = "OK" if dt_ms < 500 else "WARNING"
            remediation = "" if status == "OK" else "Connexion lente: preferer USB ou rapprocher le Wi-Fi."
            return self._check("latency", status, f"Latence commande simple: {dt_ms:.1f} ms", remediation)
        return self._check(
            "latency",
            "ERROR",
            res.stderr or "Echec commande de latence",
            "Verifier le cable/connexion reseau puis relancer adb server.",
        )

    def _critical_non_destructive_checks(self, serial: str) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        checks = [
            ("cmd_getprop", ["shell", "getprop", "ro.build.version.release"], "getprop inaccessible"),
            ("cmd_pm", ["shell", "pm", "list", "packages", "-3"], "pm list packages echoue"),
        ]
        for name, cmd, label in checks:
            res = self.adb.run(cmd, serial=serial, timeout=10)
            if res.ok:
                out.append(self._check(name, "OK", "Commande critique non destructive OK", ""))
            else:
                out.append(
                    self._check(
                        name,
                        "WARNING",
                        res.stderr or label,
                        "Verifier les droits ADB sur l'appareil et la stabilite de connexion.",
                    )
                )
        return out

    def _pair_state_check(self, serial: str) -> dict[str, str]:
        if ":" in serial:
            host, _sep, port = serial.partition(":")
            if re.match(r"^\d+\.\d+\.\d+\.\d+$", host) and port.isdigit():
                return self._check(
                    "pair_connect_state",
                    "OK",
                    f"Connexion Wi-Fi active ({serial})",
                    "Si instable: refaire pairing puis adb connect.",
                )
        return self._check(
            "pair_connect_state",
            "WARNING",
            "Connexion pair/connect non detectee (USB ou serial non-IP)",
            "Pour Wi-Fi debugging: activer Debogage sans fil puis lancer Pairing WiFi/QR.",
        )

    def _check(self, name: str, status: str, message: str, remediation: str) -> dict[str, str]:
        return {"name": name, "status": status, "message": message, "remediation": remediation}

    def _global_status(self, checks: list[dict[str, str]]) -> str:
        statuses = {c.get("status", "") for c in checks}
        if "ERROR" in statuses:
            return "ERROR"
        if "WARNING" in statuses:
            return "WARNING"
        return "OK"

    def _build_summary(self, status: str, checks: list[dict[str, str]]) -> str:
        total = len(checks)
        ok = sum(1 for c in checks if c.get("status") == "OK")
        warn = sum(1 for c in checks if c.get("status") == "WARNING")
        err = sum(1 for c in checks if c.get("status") == "ERROR")
        return f"Global={status} | checks={total} | OK={ok} WARNING={warn} ERROR={err}"
