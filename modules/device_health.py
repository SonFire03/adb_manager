from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from core.adb_manager import ADBManager
from core.utils import DeviceInfo


class DeviceHealthModule:
    def __init__(self, adb: ADBManager) -> None:
        self.adb = adb

    def run(self, serial: str, device: DeviceInfo | None = None) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []

        findings.extend(self._battery_checks(serial))
        findings.extend(self._storage_checks(serial))
        findings.extend(self._cpu_mem_checks(serial))
        findings.extend(self._thermal_checks(serial))
        findings.extend(self._connectivity_checks(serial))
        findings.extend(self._adb_stability_checks(serial, device))
        findings.extend(self._app_stability_hints(serial))

        score = self._score(findings)
        status = self._status_from_score(score)
        sections = self._section_summary(findings)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "serial": serial,
            "score": score,
            "status": status,
            "sections": sections,
            "findings": findings,
            "summary": f"{status} ({score}/100) - {len(findings)} findings",
        }

    def _battery_checks(self, serial: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        res = self.adb.run(["shell", "dumpsys", "battery"], serial=serial, timeout=12)
        if not res.ok:
            return [self._finding("battery", "Battery data unavailable", "medium", "unsupported", res.stderr, "Verifier acces dumpsys battery")]

        level = self._int_match(r"level:\s*(\d+)", res.stdout)
        scale = self._int_match(r"scale:\s*(\d+)", res.stdout) or 100
        status = self._int_match(r"status:\s*(\d+)", res.stdout)
        health = self._int_match(r"health:\s*(\d+)", res.stdout)
        temp_tenths = self._int_match(r"temperature:\s*(\d+)", res.stdout)

        pct = int(level * 100 / scale) if level >= 0 and scale > 0 else -1
        if pct >= 0:
            sev = "high" if pct < 10 else ("medium" if pct < 20 else "low")
            st = "fail" if pct < 10 else ("warn" if pct < 20 else "pass")
            out.append(self._finding("battery", "Battery level", sev, st, f"{pct}%", "Recharger l'appareil si niveau faible", pct))
        else:
            out.append(self._finding("battery", "Battery level", "low", "unsupported", "not available", "Verifier support dumpsys battery"))

        charge_state = {
            2: "charging",
            3: "discharging",
            4: "not_charging",
            5: "full",
        }.get(status, "unknown")
        out.append(self._finding("battery", "Charging state", "info", "pass", charge_state, ""))

        if temp_tenths >= 0:
            temp_c = temp_tenths / 10.0
            sev = "high" if temp_c >= 45 else ("medium" if temp_c >= 40 else "low")
            st = "fail" if temp_c >= 45 else ("warn" if temp_c >= 40 else "pass")
            out.append(self._finding("battery", "Battery temperature", sev, st, f"{temp_c:.1f}C", "Laisser refroidir l'appareil si temperature elevee", temp_c))

        if health is not None:
            out.append(self._finding("battery", "Battery health(raw)", "info", "pass", f"health={health}", ""))

        return out

    def _storage_checks(self, serial: str) -> list[dict[str, Any]]:
        res = self.adb.run(["shell", "df", "-k", "/data"], serial=serial, timeout=10)
        if not res.ok:
            return [self._finding("storage", "Storage data unavailable", "medium", "unsupported", res.stderr, "Verifier acces au /data")]
        total_kb, avail_kb = self._parse_df_kb(res.stdout)
        if total_kb <= 0:
            return [self._finding("storage", "Storage parse failed", "low", "unsupported", res.stdout[:120], "Verifier format df")]
        used_pct = int(((total_kb - avail_kb) * 100) / total_kb)
        sev = "high" if used_pct >= 95 else ("medium" if used_pct >= 85 else "low")
        st = "fail" if used_pct >= 95 else ("warn" if used_pct >= 85 else "pass")
        return [
            self._finding(
                "storage",
                "Storage usage",
                sev,
                st,
                f"used={used_pct}% avail={self._fmt_bytes(avail_kb*1024)} total={self._fmt_bytes(total_kb*1024)}",
                "Liberer de l'espace (cache/downloads/media) si saturation elevee",
                {"used_pct": used_pct, "avail_kb": avail_kb, "total_kb": total_kb},
            )
        ]

    def _cpu_mem_checks(self, serial: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cpu = self.adb.run(["shell", "dumpsys", "cpuinfo"], serial=serial, timeout=12)
        if cpu.ok:
            total = self._float_match(r"(\d+(?:\.\d+)?)%\s+TOTAL", cpu.stdout)
            if total >= 0:
                sev = "high" if total >= 90 else ("medium" if total >= 75 else "low")
                st = "fail" if total >= 90 else ("warn" if total >= 75 else "pass")
                out.append(self._finding("cpu_memory", "CPU load", sev, st, f"cpu_total={total:.1f}%", "Fermer apps lourdes si charge persistante", total))
            else:
                out.append(self._finding("cpu_memory", "CPU load", "low", "unsupported", "TOTAL not found", ""))
        else:
            out.append(self._finding("cpu_memory", "CPU load", "medium", "unsupported", cpu.stderr, "Verifier dumpsys cpuinfo"))

        mem = self.adb.run(["shell", "cat", "/proc/meminfo"], serial=serial, timeout=8)
        if mem.ok:
            total_kb = self._int_match(r"MemTotal:\s*(\d+)\s*kB", mem.stdout)
            avail_kb = self._int_match(r"MemAvailable:\s*(\d+)\s*kB", mem.stdout)
            if total_kb > 0 and avail_kb >= 0:
                avail_pct = int(avail_kb * 100 / total_kb)
                sev = "high" if avail_pct < 5 else ("medium" if avail_pct < 12 else "low")
                st = "fail" if avail_pct < 5 else ("warn" if avail_pct < 12 else "pass")
                out.append(self._finding("cpu_memory", "Memory availability", sev, st, f"available={avail_pct}%", "Reduire charge memoire/apps en arriere-plan", avail_pct))
            else:
                out.append(self._finding("cpu_memory", "Memory availability", "low", "unsupported", "MemAvailable parse failed", ""))
        else:
            out.append(self._finding("cpu_memory", "Memory availability", "medium", "unsupported", mem.stderr, "Verifier acces /proc/meminfo"))

        return out

    def _thermal_checks(self, serial: str) -> list[dict[str, Any]]:
        res = self.adb.run(["shell", "dumpsys", "thermalservice"], serial=serial, timeout=12)
        if not res.ok:
            return [self._finding("thermal", "Thermal service", "low", "unsupported", res.stderr, "Certains appareils limitent cette API")]
        temps = [float(x) for x in re.findall(r"(?:temp|temperature)[^\n]*?(-?\d+(?:\.\d+)?)", res.stdout, flags=re.IGNORECASE)]
        if not temps:
            return [self._finding("thermal", "Thermal service", "low", "unsupported", "No temperature tokens found", "API thermique non exposee par cet appareil")]
        max_temp = max(temps)
        sev = "high" if max_temp >= 50 else ("medium" if max_temp >= 45 else "low")
        st = "fail" if max_temp >= 50 else ("warn" if max_temp >= 45 else "pass")
        return [self._finding("thermal", "Thermal max reading", sev, st, f"max_temp={max_temp:.1f}C", "Laisser refroidir l'appareil, eviter charge intensive", max_temp)]

    def _connectivity_checks(self, serial: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        wifi = self.adb.run(["shell", "cmd", "wifi", "status"], serial=serial, timeout=10)
        if wifi.ok and wifi.stdout:
            enabled = "enabled" in wifi.stdout.lower()
            out.append(self._finding("connectivity", "Wi-Fi status", "low", "pass" if enabled else "warn", "enabled" if enabled else "disabled", "Activer Wi-Fi si connexion reseau requise"))
        else:
            out.append(self._finding("connectivity", "Wi-Fi status", "low", "unsupported", wifi.stderr or "not available", ""))

        ip = self.adb.run(["shell", "ip", "-f", "inet", "addr", "show", "wlan0"], serial=serial, timeout=8)
        ip_val = self._str_match(r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip.stdout) if ip.ok else ""
        if ip_val:
            out.append(self._finding("connectivity", "Local IP", "info", "pass", ip_val, ""))
        else:
            out.append(self._finding("connectivity", "Local IP", "low", "warn", "not detected", "Verifier connectivite Wi-Fi"))

        bt = self.adb.run(["shell", "settings", "get", "global", "bluetooth_on"], serial=serial, timeout=8)
        if bt.ok:
            state = bt.stdout.strip()
            out.append(self._finding("connectivity", "Bluetooth state", "info", "pass", "on" if state == "1" else "off", ""))
        else:
            out.append(self._finding("connectivity", "Bluetooth state", "low", "unsupported", bt.stderr, ""))
        return out

    def _adb_stability_checks(self, serial: str, device: DeviceInfo | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        state = device.state if device is not None else "unknown"
        transport = device.transport if device is not None else "unknown"
        if state == "device":
            out.append(self._finding("adb_stability", "ADB authorization", "low", "pass", "authorized", ""))
        elif state == "unauthorized":
            out.append(self._finding("adb_stability", "ADB authorization", "high", "fail", "unauthorized", "Debloquer device et accepter la cle RSA"))
        elif state == "offline":
            out.append(self._finding("adb_stability", "ADB authorization", "medium", "warn", "offline", "Reconnecter USB/Wi-Fi et relancer adb server"))
        else:
            out.append(self._finding("adb_stability", "ADB authorization", "low", "unsupported", state, ""))

        out.append(self._finding("adb_stability", "Transport", "info", "pass", transport, ""))

        t0 = time.perf_counter()
        ping = self.adb.run(["shell", "echo", "ok"], serial=serial, timeout=8)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        if ping.ok and "ok" in ping.stdout:
            sev = "medium" if latency_ms >= 600 else "low"
            st = "warn" if latency_ms >= 600 else "pass"
            out.append(self._finding("adb_stability", "ADB latency", sev, st, f"{latency_ms:.1f} ms", "Preferer USB ou ameliorer signal Wi-Fi", latency_ms))
        else:
            out.append(self._finding("adb_stability", "ADB latency", "high", "fail", ping.stderr or "latency check failed", "Relancer adb server, verifier connexion"))
        return out

    def _app_stability_hints(self, serial: str) -> list[dict[str, Any]]:
        res = self.adb.run(["logcat", "-d", "-t", "250"], serial=serial, timeout=15)
        if not res.ok:
            return [self._finding("app_stability", "Crash/ANR hints", "low", "unsupported", res.stderr, "Verifier acces logcat")]
        crash_count = len(re.findall(r"FATAL EXCEPTION", res.stdout))
        anr_count = len(re.findall(r"ANR in", res.stdout))
        total = crash_count + anr_count
        sev = "high" if total >= 5 else ("medium" if total >= 2 else "low")
        st = "fail" if total >= 5 else ("warn" if total >= 2 else "pass")
        return [
            self._finding(
                "app_stability",
                "Recent crash/ANR hints",
                sev,
                st,
                f"crashes={crash_count}, anr={anr_count}",
                "Inspecter logcat detaille et apps en erreur si compte eleve",
                {"crashes": crash_count, "anr": anr_count},
            )
        ]

    def _score(self, findings: list[dict[str, Any]]) -> int:
        score = 100
        for f in findings:
            status = str(f.get("status", "")).lower()
            sev = str(f.get("severity", "")).lower()
            if status == "fail":
                score -= {"high": 22, "medium": 14, "low": 8, "info": 4}.get(sev, 8)
            elif status == "warn":
                score -= {"high": 12, "medium": 8, "low": 4, "info": 2}.get(sev, 4)
            elif status == "unsupported":
                score -= 1
        return max(0, min(100, score))

    def _status_from_score(self, score: int) -> str:
        if score >= 90:
            return "Healthy"
        if score >= 70:
            return "Needs Attention"
        if score >= 40:
            return "Degraded"
        return "Critical"

    def _section_summary(self, findings: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for f in findings:
            cat = str(f.get("category", "general"))
            bucket = out.setdefault(cat, {"pass": 0, "warn": 0, "fail": 0, "unsupported": 0})
            st = str(f.get("status", "unsupported")).lower()
            if st not in bucket:
                st = "unsupported"
            bucket[st] += 1
        return out

    def _finding(
        self,
        category: str,
        title: str,
        severity: str,
        status: str,
        evidence: str,
        remediation: str,
        raw_value: Any | None = None,
    ) -> dict[str, Any]:
        item = {
            "category": category,
            "title": title,
            "severity": severity,
            "status": status,
            "evidence": evidence,
            "remediation": remediation,
        }
        if raw_value is not None:
            item["raw_value"] = raw_value
        return item

    def _int_match(self, pattern: str, text: str) -> int:
        m = re.search(pattern, text)
        return int(m.group(1)) if m else -1

    def _float_match(self, pattern: str, text: str) -> float:
        m = re.search(pattern, text)
        return float(m.group(1)) if m else -1.0

    def _str_match(self, pattern: str, text: str) -> str:
        m = re.search(pattern, text)
        return m.group(1) if m else ""

    def _parse_df_kb(self, raw: str) -> tuple[int, int]:
        rows = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(rows) < 2:
            return (0, 0)
        parts = re.split(r"\s+", rows[-1])
        if len(parts) < 4:
            return (0, 0)
        try:
            return (int(parts[1]), int(parts[3]))
        except ValueError:
            return (0, 0)

    def _fmt_bytes(self, value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        v = float(max(0, value))
        for unit in units:
            if v < 1024 or unit == units[-1]:
                return f"{v:.1f} {unit}" if unit != "B" else f"{int(v)} {unit}"
            v /= 1024
        return f"{int(value)} B"
