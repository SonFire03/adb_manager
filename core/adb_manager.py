from __future__ import annotations

import logging
import shlex
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable

from core.utils import CommandResult, ConfigManager, HistoryDB

logger = logging.getLogger(__name__)


class ADBManager:
    def __init__(self, config: ConfigManager, history: HistoryDB) -> None:
        self.config = config
        self.history = history
        self.adb_bin = str(config.get("adb.binary", "adb"))
        self.timeout = int(config.get("adb.default_timeout", 20))
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="adb-worker")
        self._lock = Lock()
        self.safe_mode = bool(config.get("app.safe_mode", True))

    def _is_blocked_in_safe_mode(self, args: list[str]) -> bool:
        text = " ".join(args).lower()
        blocked = ["rm -rf /", "mkfs", "dd if=", "setenforce 0"]
        return self.safe_mode and any(token in text for token in blocked)

    def _run(self, args: list[str], serial: str | None = None, timeout: int | None = None) -> CommandResult:
        full_cmd: list[str] = [self.adb_bin]
        if serial:
            full_cmd.extend(["-s", serial])
        full_cmd.extend(args)
        effective_timeout = timeout or self.timeout
        logger.info("Executing command: %s", " ".join(shlex.quote(a) for a in full_cmd))
        try:
            process = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=effective_timeout,
            )
            result = CommandResult(
                ok=process.returncode == 0,
                command=full_cmd,
                stdout=process.stdout.strip(),
                stderr=process.stderr.strip(),
                returncode=process.returncode,
            )
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(
                ok=False,
                command=full_cmd,
                stdout=(exc.stdout or "").strip() if exc.stdout else "",
                stderr=f"Timeout ({effective_timeout}s)",
                returncode=124,
            )
        except FileNotFoundError:
            result = CommandResult(
                ok=False,
                command=full_cmd,
                stdout="",
                stderr=f"Binaire ADB introuvable: {self.adb_bin}",
                returncode=127,
            )
        except Exception as exc:  # noqa: BLE001
            result = CommandResult(
                ok=False,
                command=full_cmd,
                stdout="",
                stderr=f"Erreur inattendue: {exc}",
                returncode=1,
            )
        self.history.add_command_event(serial, " ".join(args), result.ok, result.stdout, result.stderr)
        return result

    def run(self, adb_args: str | list[str], serial: str | None = None, timeout: int | None = None) -> CommandResult:
        args = shlex.split(adb_args) if isinstance(adb_args, str) else adb_args
        if self._is_blocked_in_safe_mode(args):
            result = CommandResult(
                ok=False,
                command=[self.adb_bin, *args],
                stdout="",
                stderr="Commande bloquee par le mode securise.",
                returncode=126,
            )
            self.history.add_command_event(serial, " ".join(args), result.ok, result.stdout, result.stderr)
            return result
        with self._lock:
            return self._run(args=args, serial=serial, timeout=timeout)

    def run_async(
        self,
        adb_args: str | list[str],
        serial: str | None = None,
        timeout: int | None = None,
        callback: Callable[[CommandResult], None] | None = None,
    ) -> Future[CommandResult]:
        args = shlex.split(adb_args) if isinstance(adb_args, str) else adb_args
        future = self.executor.submit(self.run, args, serial, timeout)
        if callback:
            future.add_done_callback(lambda f: callback(f.result()))
        return future

    def shell(self, command: str, serial: str | None = None, timeout: int | None = None) -> CommandResult:
        return self.run(["shell", command], serial=serial, timeout=timeout)

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
