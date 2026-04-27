from __future__ import annotations

import logging
import re
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Lock

from core.adb_manager import ADBManager
from core.utils import DeviceInfo

logger = logging.getLogger(__name__)

DEVICES_RE = re.compile(r"^(?P<serial>\S+)\s+(?P<state>device|offline|unauthorized)(?P<extra>.*)$")
MODEL_RE = re.compile(r"model:(\S+)")
TRANSPORT_RE = re.compile(r"transport_id:(\d+)")


class DeviceManager:
    def __init__(self, adb: ADBManager) -> None:
        self.adb = adb
        self._lock = Lock()
        self._devices: dict[str, DeviceInfo] = {}
        self._listeners: list[Callable[[list[DeviceInfo]], None]] = []
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="device-poll")

    def add_listener(self, listener: Callable[[list[DeviceInfo]], None]) -> None:
        self._listeners.append(listener)

    def _notify(self, devices: list[DeviceInfo]) -> None:
        for listener in self._listeners:
            try:
                listener(devices)
            except Exception:  # noqa: BLE001
                logger.exception("Listener error")

    def list_devices(self) -> list[DeviceInfo]:
        result = self.adb.run("devices -l")
        devices: list[DeviceInfo] = []
        if not result.ok:
            logger.warning("Unable to list devices: %s", result.stderr)
            self._notify([])
            return []
        for line in result.stdout.splitlines():
            m = DEVICES_RE.match(line.strip())
            if not m:
                continue
            serial = m.group("serial")
            state = m.group("state")
            extra = m.group("extra")
            model_match = MODEL_RE.search(extra)
            model = model_match.group(1) if model_match else "unknown"
            transport = "usb" if "usb:" in extra or TRANSPORT_RE.search(extra) else "wifi"
            info = DeviceInfo(serial=serial, state=state, model=model, transport=transport)
            if state == "device":
                info.android_version = self._android_version(serial)
                info.root = self._has_root(serial)
            devices.append(info)
        with self._lock:
            current = {d.serial: d for d in devices}
            self._track_events(self._devices, current)
            self._devices = current
        self._notify(devices)
        return devices

    def _track_events(self, old: dict[str, DeviceInfo], new: dict[str, DeviceInfo]) -> None:
        for serial, info in new.items():
            if serial not in old:
                self.adb.history.add_device_event(serial, info.model, "connected")
        for serial, info in old.items():
            if serial not in new:
                self.adb.history.add_device_event(serial, info.model, "disconnected")

    def _android_version(self, serial: str) -> str:
        result = self.adb.run("shell getprop ro.build.version.release", serial=serial, timeout=8)
        return result.stdout.strip() if result.ok and result.stdout else "unknown"

    def _has_root(self, serial: str) -> bool:
        result = self.adb.run("shell su -c id", serial=serial, timeout=6)
        return result.ok and "uid=0" in result.stdout

    def poll_async(self) -> None:
        self.pool.submit(self.list_devices)

    def current_devices(self) -> list[DeviceInfo]:
        with self._lock:
            return [DeviceInfo(**asdict(v)) for v in self._devices.values()]

    def connect_wifi(self, ip: str, port: int = 5555) -> bool:
        result = self.adb.run(f"connect {ip}:{port}")
        return result.ok and "connected" in result.stdout.lower()

    def scan_for_wifi(self, subnet_prefix: str, timeout: float = 0.15) -> list[str]:
        # Typical scan: 192.168.1., tries port 5555.
        discovered: list[str] = []
        for host in range(1, 255):
            ip = f"{subnet_prefix}{host}"
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            try:
                if sock.connect_ex((ip, 5555)) == 0:
                    discovered.append(ip)
            finally:
                sock.close()
        return discovered

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)

