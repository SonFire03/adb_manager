from __future__ import annotations

import ipaddress
import json
import logging
import os
import csv
import re
import shlex
import shutil
import signal
import time
from threading import Event
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from html import escape
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QProcess, QPropertyAnimation, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QShortcut, QTextCursor, QTextDocument
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QListView,
    QScrollArea,
    QDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSplitter,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStyle,
    QGraphicsOpacityEffect,
)

from core.adb_manager import ADBManager
from core.commands import COMMAND_CATALOG
from core.device_manager import DeviceManager
from core.utils import CommandResult, ConfigManager, DeviceInfo, HistoryDB
from gui.styles import get_theme
from gui.widgets import ScriptEditor, TerminalWidget, Toast
from modules.app_manager import AppManagerModule
from modules.automation import AutomationModule
from modules.backup_restore import BackupRestoreModule
from modules.data_transfer import DataTransferModule
from modules.device_health import DeviceHealthModule
from modules.device_inspector import DeviceInspectorModule
from modules.device_profiles import DeviceProfile, DeviceProfilesModule
from modules.file_manager import FileManagerModule
from modules.health_check import HealthCheckModule
from modules.session_audit import SessionAuditModule
from modules.snapshot_compare import SnapshotCompareModule
from modules.system_info import SystemInfoModule

logger = logging.getLogger(__name__)


class UiBridge(QObject):
    device_list_updated = Signal(object)
    command_done = Signal(object)
    status_text = Signal(str)


class HealthTimelineChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scores: list[int] = []
        self.setMinimumHeight(120)
        self.setMaximumHeight(170)

    def set_scores(self, scores: list[int]) -> None:
        self._scores = [max(0, min(100, int(s))) for s in scores if isinstance(s, int)]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(8, 8, -8, -8)
        p.fillRect(self.rect(), QColor("#071023"))
        if rect.width() <= 10 or rect.height() <= 10:
            return
        p.setPen(QPen(QColor("#1f2a44"), 1))
        for y_pct in (0, 25, 50, 75, 100):
            y = rect.bottom() - (rect.height() * y_pct / 100.0)
            p.drawLine(rect.left(), int(y), rect.right(), int(y))
        if len(self._scores) < 2:
            p.setPen(QPen(QColor("#6b7280"), 1))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Pas assez de donnees pour la courbe")
            return
        step = rect.width() / max(1, len(self._scores) - 1)
        pts = []
        for i, score in enumerate(reversed(self._scores)):
            x = rect.left() + i * step
            y = rect.bottom() - (rect.height() * score / 100.0)
            pts.append((x, y, score))
        poly = QPolygonF([QPointF(x, y) for x, y, _ in pts])
        p.setPen(QPen(QColor("#22c55e"), 2))
        p.drawPolyline(poly)
        p.setPen(QPen(QColor("#60a5fa"), 1))
        for x, y, _score in pts:
            p.drawEllipse(QPointF(x, y), 2.5, 2.5)


class MainWindow(QMainWindow):
    def __init__(self, base_dir: Path, config: ConfigManager) -> None:
        super().__init__()
        self.base_dir = base_dir
        self.config = config

        self.history = HistoryDB(base_dir / "config" / "history.db")
        self.adb = ADBManager(config=config, history=self.history)
        self.device_manager = DeviceManager(self.adb)
        self.file_module = FileManagerModule(self.adb)
        self.app_module = AppManagerModule(self.adb)
        self.system_module = SystemInfoModule(self.adb)
        self.transfer_module = DataTransferModule(self.adb)
        self.device_health_module = DeviceHealthModule(self.adb)
        self.inspector_module = DeviceInspectorModule(self.adb)
        self.health_module = HealthCheckModule(self.adb)
        self.automation_module = AutomationModule(self.adb, base_dir / "config")
        self.backup_module = BackupRestoreModule(self.adb, base_dir / "backups")
        self.profiles_module = DeviceProfilesModule(config)
        self.audit_module = SessionAuditModule(base_dir / "config" / "session_audit.db")
        self.snapshot_module = SnapshotCompareModule(
            self.adb,
            self.app_module,
            self.inspector_module,
            base_dir / "reports" / "snapshots",
        )

        self.bridge = UiBridge()
        self.bridge.device_list_updated.connect(self._on_devices_updated)
        self.bridge.command_done.connect(self._on_command_done)
        self.bridge.status_text.connect(self.statusBar().showMessage)

        self._last_devices: list[DeviceInfo] = []
        self._last_system_info: dict[str, str] = {}
        self.logcat_process: QProcess | None = None
        self.record_process: QProcess | None = None
        self.scrcpy_process: QProcess | None = None
        self.scrcpy_processes: dict[str, QProcess] = {}
        self.qr_pair_process: QProcess | None = None
        self._qr_pair_buffer = ""
        self._qr_service_name = ""
        self._qr_password = ""
        self._qr_popup: QDialog | None = None
        self._record_remote_file: str | None = None
        self._record_local_file: Path | None = None
        self._record_serial: str | None = None
        self._commands_config_file = self.base_dir / "config" / "commands.json"
        self._favorite_commands = self._load_favorite_commands()
        self._tab_shortcuts: list[QShortcut] = []
        self._tab_icons: list[QIcon] = []
        self._sidebar_shortcut: QShortcut | None = None
        self._command_palette_shortcut: QShortcut | None = None
        self._auto_sidebar_collapsed = False
        self._tab_anim: QPropertyAnimation | None = None
        self._batch_cancel_event: Event | None = None
        self._batch_pause_event: Event | None = None
        self._batch_running = False
        self._batch_paused = False
        self._batch_results: list[dict] = []
        self._app_icon_cache_dir = self.base_dir / "resources" / "icons" / "app_cache"
        self._app_icon_cache_dir.mkdir(parents=True, exist_ok=True)
        self._app_icon_pending: set[str] = set()
        self._app_icon_queue: list[str] = []
        self._app_icon_max_pending = 6
        self._app_icon_total = 0
        self._app_icon_done = 0
        self._app_icon_success = 0
        self._app_icon_generation = 0
        self._device_inspector_data: dict[str, str] = {}
        self._health_report: dict = {}
        self._profiles_suppress_autoload = False
        self._profiles_last_loaded_serial = ""
        self._apps_all_packages: list[str] = []
        self._app_analysis: dict[str, dict[str, object]] = {}
        self._app_analysis_queue: list[str] = []
        self._app_analysis_pending: set[str] = set()
        self._app_analysis_max_pending = 3
        self._app_analysis_generation = 0
        self._session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
        self._current_session_started = datetime.utcnow().isoformat() + "Z"
        self._audit_last_events: list[dict[str, Any]] = []
        self._snapshot_diff: dict[str, Any] = {}
        self._snapshot_last_captured_file = ""
        self._snapshot_name_to_path: dict[str, str] = {}
        self._last_device_serials: set[str] = set()
        self._transfer_queue: list[dict[str, Any]] = []
        self._transfer_reports: list[dict[str, Any]] = []
        self._transfer_running = False
        self._last_device_health_report: dict[str, Any] = {}
        self._health_history_rows: list[dict[str, Any]] = []

        self.setWindowTitle("ADB Manager Pro")
        self.resize(1440, 920)
        self.audit_module.start_session(self._session_id)
        self.audit_module.log_event(
            self._session_id,
            event_type="session",
            action="session_start",
            status="ok",
            message="Session started",
            payload={"started_at": self._current_session_started},
        )
        self._setup_ui()
        self._apply_theme(str(self.config.get("app.theme", "dark")))
        self._setup_polling()
        self._set_terminal_suggestions()

    def _setup_ui(self) -> None:
        root = QWidget()
        root.setObjectName("mainRoot")
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(14, 14, 14, 10)
        main_layout.setSpacing(10)

        self.header_bar = QWidget()
        self.header_bar.setObjectName("headerBar")
        header_layout = QVBoxLayout(self.header_bar)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(8)

        header_top = QHBoxLayout()
        header_top.setSpacing(8)
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        self.app_title = QLabel("ADB Manager Pro")
        self.app_title.setObjectName("appTitle")
        self.app_subtitle = QLabel("Gestion centralisee Android • USB / WiFi • Debug / Automation")
        self.app_subtitle.setObjectName("appSubtitle")
        title_col.addWidget(self.app_title)
        title_col.addWidget(self.app_subtitle)
        header_top.addLayout(title_col)
        header_top.addStretch()
        self.device_badge = QLabel("Aucun appareil")
        self.device_badge.setObjectName("deviceBadge")
        self.clock_label = QLabel("--:--:--")
        self.clock_label.setObjectName("clockLabel")
        header_top.addWidget(self.device_badge)
        header_top.addWidget(self.clock_label)
        header_layout.addLayout(header_top)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.sidebar_toggle_btn = QPushButton("☰")
        self.refresh_btn = QPushButton("Actualiser")
        self.connect_wifi_btn = QPushButton("Connecter WiFi")
        self.pair_wifi_btn = QPushButton("Pairing WiFi")
        self.pair_qr_btn = QPushButton("Pairing QR")
        self.scan_wifi_btn = QPushButton("Scanner WiFi")
        self.accent_btn = QPushButton("Accent")
        self.sidebar_toggle_btn.setObjectName("ghostBtn")
        self.refresh_btn.setObjectName("successBtn")
        self.connect_wifi_btn.setObjectName("ghostBtn")
        self.pair_wifi_btn.setObjectName("ghostBtn")
        self.pair_qr_btn.setObjectName("ghostBtn")
        self.scan_wifi_btn.setObjectName("ghostBtn")
        self.accent_btn.setObjectName("ghostBtn")
        self.sidebar_toggle_btn.setMaximumWidth(44)
        self.theme_box = QComboBox()
        self.theme_box.addItems(["dark", "light"])
        self.theme_box.setCurrentText(str(self.config.get("app.theme", "dark")))
        self.density_box = QComboBox()
        self.density_box.addItems(["comfortable", "compact"])
        self.density_box.setCurrentText(str(self.config.get("ui.density", "comfortable")))
        self.lang_box = QComboBox()
        self.lang_box.addItems(["fr", "en"])
        self.lang_box.setCurrentText(str(self.config.get("app.language", "fr")))
        self.device_box = QComboBox()
        self.device_box.setMinimumWidth(260)
        self.profile_box = QComboBox()
        self.profile_box.setMinimumWidth(210)
        self.profile_box.addItem("Profil: aucun", "")
        self.profile_save_btn = QPushButton("Sauver profil")
        self.profile_load_btn = QPushButton("Charger profil")
        self.profile_delete_btn = QPushButton("Supprimer profil")
        self.profile_save_btn.setObjectName("ghostBtn")
        self.profile_load_btn.setObjectName("ghostBtn")
        self.profile_delete_btn.setObjectName("dangerBtn")
        self.quick_command_input = QLineEdit()
        self.quick_command_input.setObjectName("quickCommandInput")
        self.quick_command_input.setPlaceholderText("Commande rapide (ex: shell getprop ro.product.model)")
        self.quick_command_btn = QPushButton("Executer")
        self.quick_command_btn.setObjectName("successBtn")

        toolbar.addWidget(self.sidebar_toggle_btn)
        toolbar.addWidget(QLabel("Appareil actif:"))
        toolbar.addWidget(self.device_box)
        toolbar.addWidget(QLabel("Profil:"))
        toolbar.addWidget(self.profile_box)
        toolbar.addWidget(self.profile_save_btn)
        toolbar.addWidget(self.profile_load_btn)
        toolbar.addWidget(self.profile_delete_btn)
        toolbar.addWidget(self.refresh_btn)
        toolbar.addWidget(self.connect_wifi_btn)
        toolbar.addWidget(self.pair_wifi_btn)
        toolbar.addWidget(self.pair_qr_btn)
        toolbar.addWidget(self.scan_wifi_btn)
        toolbar.addWidget(self.accent_btn)
        toolbar.addWidget(self.quick_command_input, 1)
        toolbar.addWidget(self.quick_command_btn)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Theme"))
        toolbar.addWidget(self.theme_box)
        toolbar.addWidget(QLabel("Density"))
        toolbar.addWidget(self.density_box)
        toolbar.addWidget(QLabel("Langue"))
        toolbar.addWidget(self.lang_box)
        header_layout.addLayout(toolbar)
        main_layout.addWidget(self.header_bar)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.tabBar().hide()
        self.sidebar_container = QWidget()
        self.sidebar_container.setObjectName("sidebarContainer")
        sidebar_layout = QVBoxLayout(self.sidebar_container)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(8)
        self.sidebar_title = QLabel("Navigation")
        self.sidebar_title.setObjectName("sidebarTitle")
        self.shortcut_hint = QLabel("Ctrl+1..9 onglets  •  Ctrl+B sidebar  •  Ctrl+K commandes")
        self.shortcut_hint.setObjectName("shortcutHint")
        self.nav_sidebar = QListWidget()
        self.nav_sidebar.setObjectName("navSidebar")
        self.nav_sidebar.setMaximumWidth(220)
        self.nav_sidebar.setMinimumWidth(170)
        sidebar_layout.addWidget(self.sidebar_title)
        sidebar_layout.addWidget(self.shortcut_hint)
        sidebar_layout.addWidget(self.nav_sidebar, 1)

        content_row = QHBoxLayout()
        content_row.setSpacing(10)
        content_row.addWidget(self.sidebar_container)
        content_row.addWidget(self.tabs, 1)
        main_layout.addLayout(content_row)

        self._build_dashboard_tab()
        self._build_files_tab()
        self._build_apps_tab()
        self._build_system_tab()
        self._build_automation_tab()
        self._build_debug_tab()
        self._build_remote_tab()
        self._build_backup_tab()
        self._build_captures_tab()
        self._build_transfer_tab()
        self._build_device_health_tab()
        self._build_reports_tab()
        self._set_tab_icons()
        self._build_sidebar_nav()
        self._setup_tab_shortcuts()
        self._setup_sidebar_shortcut()
        self._setup_palette_shortcut()
        self._apply_sidebar_state(bool(self.config.get("ui.sidebar_collapsed", False)))

        self.refresh_btn.clicked.connect(self._manual_refresh)
        self.connect_wifi_btn.clicked.connect(self._wifi_connect_dialog)
        self.pair_wifi_btn.clicked.connect(self._wifi_pair_dialog)
        self.pair_qr_btn.clicked.connect(self._wifi_pair_qr_dialog)
        self.scan_wifi_btn.clicked.connect(self._scan_wifi_dialog)
        self.accent_btn.clicked.connect(self._choose_accent_color)
        self.theme_box.currentTextChanged.connect(self._apply_theme)
        self.density_box.currentTextChanged.connect(self._apply_density)
        self.tabs.currentChanged.connect(self._sync_sidebar_to_tab)
        self.tabs.currentChanged.connect(self._animate_tab_transition)
        self.nav_sidebar.currentRowChanged.connect(self._on_sidebar_nav_changed)
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        self.quick_command_btn.clicked.connect(self._run_quick_command)
        self.quick_command_input.returnPressed.connect(self._run_quick_command)
        self.device_box.currentIndexChanged.connect(self._on_active_device_changed)
        self.profile_save_btn.clicked.connect(self._save_device_profile)
        self.profile_load_btn.clicked.connect(self._load_selected_profile)
        self.profile_delete_btn.clicked.connect(self._delete_selected_profile)
        self.profile_box.currentIndexChanged.connect(self._profile_selection_changed)
        self._refresh_profile_box()

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1000)
        self._tick_clock()
        self._update_responsive_layout()

    def _on_active_device_changed(self, _index: int) -> None:
        serial = self._selected_serial() or ""
        if serial:
            self._autoload_profile_for_device(serial)
        self._refresh_device_inspector()
        self._run_health_check()
        self._refresh_health_timeline()

    def _build_dashboard_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        metrics = QHBoxLayout()
        self.metric_devices = self._build_metric_card("Appareils connectes", "0", "metric_devices_value")
        self.metric_root = self._build_metric_card("Appareils root", "0", "metric_root_value")
        self.metric_active = self._build_metric_card("Actif", "-", "metric_active_value")
        metrics.addWidget(self.metric_devices)
        metrics.addWidget(self.metric_root)
        metrics.addWidget(self.metric_active)
        layout.addLayout(metrics)

        quick = QHBoxLayout()
        self.reboot_btn = QPushButton("Reboot")
        self.capture_btn = QPushButton("Capture ecran")
        self.record_start_btn = QPushButton("Start video")
        self.record_stop_btn = QPushButton("Stop video")
        self.export_report_btn = QPushButton("Exporter rapport")
        self.reboot_btn.setObjectName("dangerBtn")
        self.capture_btn.setObjectName("successBtn")
        self.record_start_btn.setObjectName("successBtn")
        self.record_stop_btn.setObjectName("dangerBtn")
        self.export_report_btn.setObjectName("ghostBtn")
        quick.addWidget(self.reboot_btn)
        quick.addWidget(self.capture_btn)
        quick.addWidget(self.record_start_btn)
        quick.addWidget(self.record_stop_btn)
        quick.addWidget(self.export_report_btn)
        quick.addStretch()
        layout.addLayout(quick)

        split = QSplitter()
        split.setChildrenCollapsible(False)
        left = QWidget()
        right = QWidget()
        left.setObjectName("panelCard")
        right.setObjectName("panelCard")
        left_layout = QVBoxLayout(left)
        right_layout = QVBoxLayout(right)
        left_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setContentsMargins(10, 10, 10, 10)

        self.device_table = QTableWidget(0, 6)
        self.device_table.setHorizontalHeaderLabels(["Serial", "Etat", "Modele", "Transport", "Android", "Root"])
        left_layout.addWidget(QLabel("Appareils connectes"))
        left_layout.addWidget(self.device_table)

        self.history_box = QTextEdit()
        self.history_box.setReadOnly(True)
        right_layout.addWidget(QLabel("Historique"))
        right_layout.addWidget(self.history_box)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split)

        insight_split = QSplitter()
        insight_split.setChildrenCollapsible(False)
        inspector_group = QGroupBox("Device Inspector")
        inspector_group.setObjectName("panelCard")
        inspector_layout = QVBoxLayout(inspector_group)
        inspector_layout.setContentsMargins(10, 10, 10, 10)
        inspector_top = QHBoxLayout()
        self.inspector_refresh_btn = QPushButton("Refresh Inspector")
        self.inspector_refresh_btn.setObjectName("successBtn")
        self.inspector_export_btn = QPushButton("Export Inspector JSON")
        self.inspector_export_btn.setObjectName("ghostBtn")
        inspector_top.addWidget(self.inspector_refresh_btn)
        inspector_top.addWidget(self.inspector_export_btn)
        inspector_top.addStretch()
        inspector_layout.addLayout(inspector_top)
        self.inspector_text = QTextEdit()
        self.inspector_text.setReadOnly(True)
        self.inspector_text.setPlaceholderText("Inspector appareil: marque, modele, batterie, stockage, ecran, IP, debug...")
        self.inspector_text.setMinimumHeight(180)
        inspector_layout.addWidget(self.inspector_text)

        health_group = QGroupBox("ADB Health Check")
        health_group.setObjectName("panelCard")
        health_layout = QVBoxLayout(health_group)
        health_layout.setContentsMargins(10, 10, 10, 10)
        health_top = QHBoxLayout()
        self.health_run_btn = QPushButton("Run Health Check")
        self.health_run_btn.setObjectName("successBtn")
        self.health_export_btn = QPushButton("Export Health JSON")
        self.health_export_btn.setObjectName("ghostBtn")
        self.health_status_badge = QLabel("Global: n/a")
        self.health_status_badge.setObjectName("deviceBadge")
        health_top.addWidget(self.health_run_btn)
        health_top.addWidget(self.health_export_btn)
        health_top.addStretch()
        health_top.addWidget(self.health_status_badge)
        health_layout.addLayout(health_top)
        self.health_text = QTextEdit()
        self.health_text.setReadOnly(True)
        self.health_text.setPlaceholderText("Checks ADB: binaire, serveur, auth RSA, latence, commandes critiques...")
        self.health_text.setMinimumHeight(180)
        health_layout.addWidget(self.health_text)

        insight_split.addWidget(inspector_group)
        insight_split.addWidget(health_group)
        insight_split.setStretchFactor(0, 1)
        insight_split.setStretchFactor(1, 1)
        layout.addWidget(insight_split)
        self.tabs.addTab(tab, "Dashboard")

        self.reboot_btn.clicked.connect(self._reboot_device)
        self.capture_btn.clicked.connect(self._capture_screen)
        self.record_start_btn.clicked.connect(self._start_screen_record)
        self.record_stop_btn.clicked.connect(self._stop_screen_record)
        self.export_report_btn.clicked.connect(self._export_report)
        self.inspector_refresh_btn.clicked.connect(self._refresh_device_inspector)
        self.inspector_export_btn.clicked.connect(self._export_device_inspector)
        self.health_run_btn.clicked.connect(self._run_health_check)
        self.health_export_btn.clicked.connect(self._export_health_report)

    def _build_metric_card(self, label: str, value: str, value_attr: str) -> QWidget:
        card = QWidget()
        card.setObjectName("panelCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        title = QLabel(label)
        title.setObjectName("metricLabel")
        number = QLabel(value)
        number.setObjectName("metricValue")
        setattr(self, value_attr, number)
        card_layout.addWidget(title)
        card_layout.addWidget(number)
        card_layout.addStretch()
        return card

    def _build_files_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        split = QSplitter()
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)

        left = QGroupBox("Ordinateur")
        left.setObjectName("paneGroup")
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(10, 10, 10, 10)
        left_l.setSpacing(8)
        self.local_path = QLineEdit(str(self.base_dir))
        self.local_path.setObjectName("pathInput")
        self.local_list = QListWidget()
        self.local_list.setObjectName("fileList")
        self.local_list.setViewMode(QListView.ViewMode.IconMode)
        self.local_list.setIconSize(QSize(34, 34))
        self.local_list.setGridSize(QSize(130, 82))
        self.local_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.local_list.setMovement(QListView.Movement.Static)
        self.local_list.setWrapping(True)
        self.local_list.setWordWrap(True)
        self.local_list.setSpacing(8)
        self.local_refresh_btn = QPushButton("Lister local")
        self.local_home_btn = QPushButton("Home")
        self.local_up_btn = QPushButton("Parent ..")
        self.local_refresh_btn.setObjectName("ghostBtn")
        self.local_home_btn.setObjectName("ghostBtn")
        self.local_up_btn.setObjectName("ghostBtn")
        local_path_row = QHBoxLayout()
        local_path_label = QLabel("Chemin")
        local_path_label.setObjectName("fieldLabel")
        local_path_label.setMinimumWidth(74)
        local_path_row.addWidget(local_path_label)
        local_path_row.addWidget(self.local_path, 1)
        local_path_row.addWidget(self.local_home_btn)
        local_path_row.addWidget(self.local_up_btn)
        local_path_row.addWidget(self.local_refresh_btn)
        left_l.addLayout(local_path_row)
        left_l.addWidget(self.local_list)

        right = QGroupBox("Telephone")
        right.setObjectName("paneGroup")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(10, 10, 10, 10)
        right_l.setSpacing(8)
        self.remote_path = QLineEdit("/")
        self.remote_path.setObjectName("pathInput")
        self.remote_list = QListWidget()
        self.remote_list.setObjectName("fileList")
        self.remote_list.setViewMode(QListView.ViewMode.IconMode)
        self.remote_list.setIconSize(QSize(34, 34))
        self.remote_list.setGridSize(QSize(130, 82))
        self.remote_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.remote_list.setMovement(QListView.Movement.Static)
        self.remote_list.setWrapping(True)
        self.remote_list.setWordWrap(True)
        self.remote_list.setSpacing(8)
        self.remote_search = QLineEdit()
        self.remote_search.setPlaceholderText("Recherche distante")
        self.remote_search.setObjectName("searchInput")
        self.remote_refresh_btn = QPushButton("Lister distant")
        self.remote_root_btn = QPushButton("Racine /")
        self.remote_up_btn = QPushButton("Parent ..")
        self.remote_refresh_btn.setObjectName("ghostBtn")
        self.remote_root_btn.setObjectName("ghostBtn")
        self.remote_up_btn.setObjectName("ghostBtn")
        remote_path_row = QHBoxLayout()
        remote_path_label = QLabel("Chemin")
        remote_path_label.setObjectName("fieldLabel")
        remote_path_label.setMinimumWidth(74)
        remote_path_row.addWidget(remote_path_label)
        remote_path_row.addWidget(self.remote_path, 1)
        remote_path_row.addWidget(self.remote_root_btn)
        remote_path_row.addWidget(self.remote_up_btn)
        remote_path_row.addWidget(self.remote_refresh_btn)
        right_l.addLayout(remote_path_row)
        remote_search_row = QHBoxLayout()
        remote_search_label = QLabel("Recherche")
        remote_search_label.setObjectName("fieldLabel")
        remote_search_label.setMinimumWidth(74)
        remote_search_row.addWidget(remote_search_label)
        remote_search_row.addWidget(self.remote_search, 1)
        right_l.addLayout(remote_search_row)
        right_l.addWidget(self.remote_list)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        layout.addWidget(split)

        actions = QHBoxLayout()
        self.push_btn = QPushButton("Push ->")
        self.pull_btn = QPushButton("<- Pull")
        self.sync_to_remote_btn = QPushButton("Sync local -> distant")
        self.sync_to_local_btn = QPushButton("Sync distant -> local")
        self.push_btn.setObjectName("successBtn")
        self.pull_btn.setObjectName("ghostBtn")
        self.sync_to_remote_btn.setObjectName("ghostBtn")
        self.sync_to_local_btn.setObjectName("ghostBtn")
        actions.addWidget(self.push_btn)
        actions.addWidget(self.pull_btn)
        actions.addWidget(self.sync_to_remote_btn)
        actions.addWidget(self.sync_to_local_btn)
        actions.addStretch()
        layout.addLayout(actions)
        self.tabs.addTab(tab, "Fichiers")

        self.local_refresh_btn.clicked.connect(self._list_local)
        self.local_home_btn.clicked.connect(self._go_local_home)
        self.local_up_btn.clicked.connect(self._go_local_parent)
        self.local_path.returnPressed.connect(self._list_local)
        self.local_list.itemDoubleClicked.connect(self._open_local_item)
        self.remote_refresh_btn.clicked.connect(self._list_remote)
        self.remote_root_btn.clicked.connect(self._go_remote_root)
        self.remote_up_btn.clicked.connect(self._go_remote_parent)
        self.remote_path.returnPressed.connect(self._list_remote)
        self.remote_search.returnPressed.connect(self._search_remote)
        self.remote_list.itemDoubleClicked.connect(self._open_remote_item)
        self.push_btn.clicked.connect(self._push_file)
        self.pull_btn.clicked.connect(self._pull_file)
        self.sync_to_remote_btn.clicked.connect(self._sync_local_to_remote_level)
        self.sync_to_local_btn.clicked.connect(self._sync_remote_to_local_level)

    def _build_apps_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QHBoxLayout()
        self.apps_scope = QComboBox()
        self.apps_scope.addItems(["Utilisateur", "Systeme+Utilisateur"])
        self.apps_search = QLineEdit()
        self.apps_search.setPlaceholderText("Rechercher package/app...")
        self.apps_risk_filter = QComboBox()
        self.apps_risk_filter.addItems(["Tous risques", "LOW", "MEDIUM", "HIGH", "Sans analyse"])
        self.apps_sort_box = QComboBox()
        self.apps_sort_box.addItems(["Tri: Nom", "Tri: Risque", "Tri: Permissions"])
        self.apps_refresh_btn = QPushButton("Charger apps")
        self.apps_install_btn = QPushButton("Installer APK")
        self.apps_uninstall_btn = QPushButton("Desinstaller")
        self.apps_clear_btn = QPushButton("Nettoyer data")
        self.apps_fetch_icons_btn = QPushButton("Recuperer icones")
        self.apps_export_json_btn = QPushButton("Export Apps JSON")
        self.apps_export_csv_btn = QPushButton("Export Apps CSV")
        self.apps_refresh_btn.setObjectName("successBtn")
        self.apps_install_btn.setObjectName("successBtn")
        self.apps_uninstall_btn.setObjectName("dangerBtn")
        self.apps_clear_btn.setObjectName("ghostBtn")
        self.apps_fetch_icons_btn.setObjectName("ghostBtn")
        self.apps_export_json_btn.setObjectName("ghostBtn")
        self.apps_export_csv_btn.setObjectName("ghostBtn")
        controls.addWidget(self.apps_scope)
        controls.addWidget(self.apps_search, 1)
        controls.addWidget(self.apps_risk_filter)
        controls.addWidget(self.apps_sort_box)
        controls.addWidget(self.apps_refresh_btn)
        controls.addWidget(self.apps_install_btn)
        controls.addWidget(self.apps_uninstall_btn)
        controls.addWidget(self.apps_clear_btn)
        controls.addWidget(self.apps_fetch_icons_btn)
        controls.addWidget(self.apps_export_json_btn)
        controls.addWidget(self.apps_export_csv_btn)
        controls.addStretch()
        layout.addLayout(controls)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        self.apps_list = QListWidget()
        self.apps_list.setObjectName("appsGrid")
        self.apps_list.setViewMode(QListView.ViewMode.IconMode)
        self.apps_list.setIconSize(QSize(56, 56))
        self.apps_list.setGridSize(QSize(132, 108))
        self.apps_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.apps_list.setMovement(QListView.Movement.Static)
        self.apps_list.setWrapping(True)
        self.apps_list.setWordWrap(True)
        self.apps_list.setSpacing(8)
        self.apps_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        split.addWidget(self.apps_list)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(8)

        self.apps_detail_text = QTextEdit()
        self.apps_detail_text.setReadOnly(True)
        self.apps_detail_text.setObjectName("commandDetails")
        self.apps_detail_text.setPlaceholderText("Selectionne une app pour voir package, version, permissions sensibles et risque.")
        self.apps_detail_text.setMinimumHeight(180)
        right_l.addWidget(self.apps_detail_text)

        self.apps_risk_summary = QLabel("Risque apps: LOW=0 MEDIUM=0 HIGH=0")
        self.apps_risk_summary.setObjectName("metricLabel")
        right_l.addWidget(self.apps_risk_summary)

        self.apps_risk_table = QTableWidget(0, 7)
        self.apps_risk_table.setHorizontalHeaderLabels(
            ["Package", "Label", "Type", "Risque", "Perms", "Sensibles", "Version"]
        )
        self.apps_risk_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.apps_risk_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.apps_risk_table.setSortingEnabled(True)
        right_l.addWidget(self.apps_risk_table, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)
        self.tabs.addTab(tab, "Applications")

        self.apps_refresh_btn.clicked.connect(self._list_apps)
        self.apps_install_btn.clicked.connect(self._install_apk)
        self.apps_uninstall_btn.clicked.connect(self._uninstall_app)
        self.apps_clear_btn.clicked.connect(self._clear_app_data)
        self.apps_fetch_icons_btn.clicked.connect(self._fetch_all_app_icons)
        self.apps_export_json_btn.clicked.connect(self._export_apps_analysis_json)
        self.apps_export_csv_btn.clicked.connect(self._export_apps_analysis_csv)
        self.apps_search.textChanged.connect(self._apply_apps_filters)
        self.apps_risk_filter.currentTextChanged.connect(self._apply_apps_filters)
        self.apps_sort_box.currentTextChanged.connect(self._apply_apps_filters)
        self.apps_list.currentItemChanged.connect(self._on_apps_item_changed)
        self.apps_risk_table.itemSelectionChanged.connect(self._sync_apps_selection_from_table)

    def _build_system_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        top = QHBoxLayout()
        self.system_refresh_btn = QPushButton("Refresh Infos")
        self.system_monitor_btn = QPushButton("Snapshot Monitoring")
        self.system_refresh_btn.setObjectName("successBtn")
        self.system_monitor_btn.setObjectName("ghostBtn")
        top.addWidget(self.system_refresh_btn)
        top.addWidget(self.system_monitor_btn)
        top.addStretch()
        layout.addLayout(top)

        self.system_info_text = QTextEdit()
        self.system_info_text.setReadOnly(True)
        layout.addWidget(self.system_info_text)
        self.tabs.addTab(tab, "Systeme")

        self.system_refresh_btn.clicked.connect(self._refresh_system_info)
        self.system_monitor_btn.clicked.connect(self._monitor_system)

    def _build_automation_tab(self) -> None:
        tab = QWidget()
        layout = QGridLayout(tab)
        self.script_editor = ScriptEditor()
        self.script_run_btn = QPushButton("Executer script")
        self.script_save_btn = QPushButton("Sauver script")
        self.script_run_btn.setObjectName("successBtn")
        self.script_save_btn.setObjectName("ghostBtn")
        self.script_name = QLineEdit()
        self.script_name.setPlaceholderText("Nom du script")
        self.script_library = QListWidget()
        self.script_output = QTextEdit()
        self.script_output.setReadOnly(True)

        layout.addWidget(QLabel("Editeur"), 0, 0)
        layout.addWidget(QLabel("Bibliotheque"), 0, 1)
        layout.addWidget(self.script_editor, 1, 0)
        layout.addWidget(self.script_library, 1, 1)
        layout.addWidget(self.script_name, 2, 0)
        layout.addWidget(self.script_save_btn, 2, 1)
        layout.addWidget(self.script_run_btn, 3, 0, 1, 2)
        layout.addWidget(self.script_output, 4, 0, 1, 2)
        self.tabs.addTab(tab, "Automation")

        self.script_save_btn.clicked.connect(self._save_script)
        self.script_run_btn.clicked.connect(self._run_script)
        self.script_library.itemDoubleClicked.connect(self._load_script)
        self._refresh_script_library()

    def _build_debug_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(2)

        left_col = QWidget()
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        right_col = QWidget()
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        live_group = QGroupBox("Console et Logcat")
        live_group.setObjectName("panelCard")
        live_layout = QVBoxLayout(live_group)
        live_layout.setContentsMargins(10, 10, 10, 10)
        live_layout.setSpacing(10)
        self.terminal = TerminalWidget()
        self.terminal.command_submitted.connect(self._run_terminal_command)
        live_layout.addWidget(self.terminal)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.logcat_btn = QPushButton("Charger logcat")
        self.logcat_live_start_btn = QPushButton("Start live")
        self.logcat_live_stop_btn = QPushButton("Stop live")
        self.logcat_btn.setObjectName("ghostBtn")
        self.logcat_live_start_btn.setObjectName("successBtn")
        self.logcat_live_stop_btn.setObjectName("dangerBtn")
        self.logcat_filter = QLineEdit()
        self.logcat_filter.setPlaceholderText("Filtre live logcat (optionnel)")
        controls.addWidget(self.logcat_btn)
        controls.addWidget(self.logcat_live_start_btn)
        controls.addWidget(self.logcat_live_stop_btn)
        controls.addWidget(self.logcat_filter, 1)
        live_layout.addLayout(controls)
        self.live_log_output = QTextEdit()
        self.live_log_output.setReadOnly(True)
        self.live_log_output.setPlaceholderText("Flux logcat temps reel...")
        self.live_log_output.setMinimumHeight(120)
        live_layout.addWidget(self.live_log_output)
        left_layout.addWidget(live_group)

        command_group = QGroupBox("Catalogue commandes")
        command_group.setObjectName("panelCard")
        command_layout = QVBoxLayout(command_group)
        command_layout.setContentsMargins(10, 10, 10, 10)
        command_layout.setSpacing(8)
        command_filters = QHBoxLayout()
        command_filters.setSpacing(8)
        command_filters.addWidget(QLabel("Filtre"))
        self.command_filter_box = QComboBox()
        self.command_filter_box.addItems(["Toutes", "Sans root", "Root parfois", "Root oui"])
        self.command_filter_box.setMinimumWidth(150)
        command_filters.addWidget(self.command_filter_box)
        self.command_search = QLineEdit()
        self.command_search.setPlaceholderText("Rechercher commande (nom, commande, categorie)")
        command_filters.addWidget(self.command_search, 1)
        command_layout.addLayout(command_filters)
        command_actions = QHBoxLayout()
        command_actions.setSpacing(8)
        self.favorites_only = QCheckBox("Favoris seulement")
        command_actions.addWidget(self.favorites_only)
        self.favorite_toggle_btn = QPushButton("Ajouter/Retirer favori")
        self.favorite_toggle_btn.setObjectName("ghostBtn")
        command_actions.addWidget(self.favorite_toggle_btn)
        self.copy_command_btn = QPushButton("Copier")
        self.copy_command_btn.setObjectName("ghostBtn")
        command_actions.addWidget(self.copy_command_btn)
        self.execute_selected_btn = QPushButton("Executer selection")
        self.execute_selected_btn.setObjectName("successBtn")
        command_actions.addWidget(self.execute_selected_btn)
        command_actions.addStretch()
        command_layout.addLayout(command_actions)
        options_row = QHBoxLayout()
        options_row.setSpacing(8)
        self.confirm_critical_box = QCheckBox("Confirmation commandes critiques")
        self.confirm_critical_box.setChecked(bool(self.config.get("ui.confirm_critical_commands", True)))
        self.logcat_autoscroll_box = QCheckBox("Auto-scroll logcat live")
        self.logcat_autoscroll_box.setChecked(bool(self.config.get("ui.logcat_auto_scroll", True)))
        options_row.addWidget(self.confirm_critical_box)
        options_row.addWidget(self.logcat_autoscroll_box)
        options_row.addStretch()
        command_layout.addLayout(options_row)
        self.command_catalog = QListWidget()
        self.command_catalog.setObjectName("commandCatalog")
        self.command_catalog.setMinimumHeight(230)
        self._command_entries: list[tuple[str, str, str, str, str, str, tuple[str, ...]]] = []
        for category, items in COMMAND_CATALOG.items():
            label = items[0].category if items else category
            for item in items:
                root_state = self._root_state_from_requirement(item.root_required)
                self._command_entries.append(
                    (category, label, item.name, item.command, root_state, item.description, item.placeholders)
                )
        self.command_filter_box.setCurrentText(str(self.config.get("ui.command_root_filter", "Toutes")))
        self.command_search.setText(str(self.config.get("ui.command_search", "")))
        self.favorites_only.setChecked(bool(self.config.get("ui.command_favorites_only", False)))
        self._rebuild_command_catalog()
        command_layout.addWidget(self.command_catalog)
        left_layout.addWidget(command_group, 1)

        details_group = QGroupBox("Details commande")
        details_group.setObjectName("panelCard")
        details_layout = QVBoxLayout(details_group)
        details_layout.setContentsMargins(10, 10, 10, 10)
        details_layout.setSpacing(8)
        details_top = QHBoxLayout()
        details_top.setSpacing(8)
        self.export_commands_btn = QPushButton("Exporter docs commandes")
        self.export_commands_btn.setObjectName("successBtn")
        details_top.addWidget(self.export_commands_btn)
        details_top.addStretch()
        details_layout.addLayout(details_top)
        self.command_details = QTextEdit()
        self.command_details.setObjectName("commandDetails")
        self.command_details.setReadOnly(True)
        self.command_details.setPlaceholderText("Selectionnez une commande pour voir sa description detaillee.")
        self.command_details.setMinimumHeight(180)
        self.command_details.setMaximumHeight(320)
        details_layout.addWidget(self.command_details)
        right_layout.addWidget(details_group)

        batch_group = QGroupBox("Batch Executor")
        batch_group.setObjectName("panelCard")
        batch_layout = QVBoxLayout(batch_group)
        batch_layout.setContentsMargins(10, 10, 10, 10)
        batch_layout.setSpacing(8)
        batch_controls = QHBoxLayout()
        batch_controls.setSpacing(8)
        self.batch_add_btn = QPushButton("Ajouter a la file")
        self.batch_remove_btn = QPushButton("Retirer")
        self.batch_clear_btn = QPushButton("Vider")
        self.batch_run_btn = QPushButton("Executer file")
        self.batch_pause_btn = QPushButton("Pause")
        self.batch_stop_btn = QPushButton("Stop")
        self.batch_export_btn = QPushButton("Exporter rapport batch")
        self.batch_add_btn.setObjectName("ghostBtn")
        self.batch_remove_btn.setObjectName("ghostBtn")
        self.batch_clear_btn.setObjectName("ghostBtn")
        self.batch_run_btn.setObjectName("successBtn")
        self.batch_pause_btn.setObjectName("ghostBtn")
        self.batch_stop_btn.setObjectName("dangerBtn")
        self.batch_export_btn.setObjectName("successBtn")
        batch_controls.addWidget(self.batch_add_btn)
        batch_controls.addWidget(self.batch_remove_btn)
        batch_controls.addWidget(self.batch_clear_btn)
        batch_controls.addWidget(self.batch_run_btn)
        batch_controls.addWidget(self.batch_pause_btn)
        batch_controls.addWidget(self.batch_stop_btn)
        batch_controls.addWidget(self.batch_export_btn)
        batch_controls.addStretch()
        batch_layout.addLayout(batch_controls)
        batch_options = QHBoxLayout()
        batch_options.setSpacing(8)
        batch_options.addWidget(QLabel("Workers"))
        self.batch_workers_spin = QSpinBox()
        self.batch_workers_spin.setRange(1, 8)
        self.batch_workers_spin.setValue(int(self.config.get("ui.batch_workers", 2)))
        batch_options.addWidget(self.batch_workers_spin)
        batch_options.addWidget(QLabel("Retry"))
        self.batch_retry_spin = QSpinBox()
        self.batch_retry_spin.setRange(0, 5)
        self.batch_retry_spin.setValue(int(self.config.get("ui.batch_retry", 1)))
        batch_options.addWidget(self.batch_retry_spin)
        batch_options.addWidget(QLabel("Timeout(s)"))
        self.batch_timeout_spin = QSpinBox()
        self.batch_timeout_spin.setRange(5, 900)
        self.batch_timeout_spin.setValue(int(self.config.get("ui.batch_timeout_s", 120)))
        batch_options.addWidget(self.batch_timeout_spin)
        self.batch_stop_on_error = QCheckBox("Stop on first error")
        self.batch_stop_on_error.setChecked(bool(self.config.get("ui.batch_stop_on_error", False)))
        batch_options.addWidget(self.batch_stop_on_error)
        batch_options.addStretch()
        batch_layout.addLayout(batch_options)
        self.batch_queue_list = QListWidget()
        self.batch_queue_list.setObjectName("batchQueue")
        self.batch_queue_list.setMinimumHeight(100)
        self.batch_queue_list.setMaximumHeight(200)
        self.batch_queue_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.batch_queue_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.batch_queue_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.batch_progress = QProgressBar()
        self.batch_progress.setMinimum(0)
        self.batch_progress.setMaximum(100)
        self.batch_progress.setValue(0)
        self.batch_progress_label = QLabel("Batch inactif")
        self.batch_output = QTextEdit()
        self.batch_output.setObjectName("batchOutput")
        self.batch_output.setReadOnly(True)
        self.batch_output.setPlaceholderText("Resultats batch...")
        self.batch_output.setMaximumHeight(230)
        batch_layout.addWidget(self.batch_queue_list)
        batch_layout.addWidget(self.batch_progress)
        batch_layout.addWidget(self.batch_progress_label)
        batch_layout.addWidget(self.batch_output)
        self.batch_pause_btn.setEnabled(False)
        self.batch_stop_btn.setEnabled(False)
        right_layout.addWidget(batch_group, 1)

        split.addWidget(left_col)
        split.addWidget(right_col)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        layout.addWidget(split, 1)
        self.tabs.addTab(tab, "Debug")

        self.logcat_btn.clicked.connect(lambda: self._run_terminal_command("logcat -d"))
        self.logcat_live_start_btn.clicked.connect(self._start_live_logcat)
        self.logcat_live_stop_btn.clicked.connect(self._stop_live_logcat)
        self.command_filter_box.currentTextChanged.connect(self._rebuild_command_catalog)
        self.command_search.textChanged.connect(self._rebuild_command_catalog)
        self.favorites_only.toggled.connect(self._rebuild_command_catalog)
        self.favorite_toggle_btn.clicked.connect(self._toggle_selected_favorite)
        self.copy_command_btn.clicked.connect(self._copy_selected_command)
        self.execute_selected_btn.clicked.connect(self._execute_selected_command)
        self.export_commands_btn.clicked.connect(self._export_command_docs)
        self.confirm_critical_box.toggled.connect(self._save_command_options)
        self.logcat_autoscroll_box.toggled.connect(self._save_command_options)
        self.batch_add_btn.clicked.connect(self._add_selected_to_batch)
        self.batch_remove_btn.clicked.connect(self._remove_batch_item)
        self.batch_clear_btn.clicked.connect(self._clear_batch_items)
        self.batch_run_btn.clicked.connect(self._run_batch_queue)
        self.batch_pause_btn.clicked.connect(self._toggle_batch_pause)
        self.batch_stop_btn.clicked.connect(self._stop_batch_queue)
        self.batch_export_btn.clicked.connect(self._export_batch_report)
        self.batch_workers_spin.valueChanged.connect(self._save_batch_options)
        self.batch_retry_spin.valueChanged.connect(self._save_batch_options)
        self.batch_timeout_spin.valueChanged.connect(self._save_batch_options)
        self.batch_stop_on_error.toggled.connect(self._save_batch_options)
        self.command_catalog.itemDoubleClicked.connect(self._run_catalog_item)
        self.command_catalog.currentItemChanged.connect(self._on_command_selected)

    def _build_remote_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        center_group = QGroupBox("Device Control Center")
        center_group.setObjectName("panelCard")
        center_layout = QVBoxLayout(center_group)
        center_layout.setContentsMargins(10, 10, 10, 10)
        center_layout.setSpacing(8)
        center_head = QHBoxLayout()
        self.remote_center_refresh_btn = QPushButton("Rafraichir cartes")
        self.remote_center_refresh_btn.setObjectName("ghostBtn")
        self.remote_center_summary = QLabel("0 appareil")
        self.remote_center_summary.setObjectName("deviceBadge")
        center_head.addWidget(self.remote_center_refresh_btn)
        center_head.addStretch()
        center_head.addWidget(self.remote_center_summary)
        center_layout.addLayout(center_head)

        self.remote_center_scroll = QScrollArea()
        self.remote_center_scroll.setWidgetResizable(True)
        self.remote_center_scroll.setObjectName("panelCard")
        self.remote_center_container = QWidget()
        self.remote_center_grid = QGridLayout(self.remote_center_container)
        self.remote_center_grid.setContentsMargins(4, 4, 4, 4)
        self.remote_center_grid.setHorizontalSpacing(10)
        self.remote_center_grid.setVerticalSpacing(10)
        self.remote_center_scroll.setWidget(self.remote_center_container)
        self.remote_center_scroll.setMinimumHeight(210)
        center_layout.addWidget(self.remote_center_scroll)
        layout.addWidget(center_group)

        scrcpy_group = QGroupBox("Remote Scrcpy")
        scrcpy_group.setObjectName("panelCard")
        scrcpy_layout = QVBoxLayout(scrcpy_group)
        scrcpy_layout.setContentsMargins(10, 10, 10, 10)
        scrcpy_layout.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel("Cible"))
        self.remote_device_box = QComboBox()
        self.remote_device_box.setMinimumWidth(300)
        self.remote_device_box.addItem("Aucun appareil", "")
        top.addWidget(self.remote_device_box)
        top.addWidget(QLabel("scrcpy"))
        self.scrcpy_path_input = QLineEdit(str(self.config.get("app.scrcpy_bin", "scrcpy")))
        self.scrcpy_path_input.setPlaceholderText("Binaire scrcpy (ex: scrcpy ou /usr/bin/scrcpy)")
        self.scrcpy_detect_btn = QPushButton("Verifier")
        self.scrcpy_detect_btn.setObjectName("ghostBtn")
        self.scrcpy_start_btn = QPushButton("Start Remote")
        self.scrcpy_start_btn.setObjectName("successBtn")
        self.scrcpy_start_all_btn = QPushButton("Start All")
        self.scrcpy_start_all_btn.setObjectName("successBtn")
        self.scrcpy_stop_btn = QPushButton("Stop Remote")
        self.scrcpy_stop_btn.setObjectName("dangerBtn")
        self.scrcpy_stop_all_btn = QPushButton("Stop All")
        self.scrcpy_stop_all_btn.setObjectName("dangerBtn")
        self.scrcpy_stop_btn.setEnabled(False)
        self.scrcpy_stop_all_btn.setEnabled(False)
        top.addWidget(self.scrcpy_path_input, 1)
        top.addWidget(self.scrcpy_detect_btn)
        top.addWidget(self.scrcpy_start_btn)
        top.addWidget(self.scrcpy_start_all_btn)
        top.addWidget(self.scrcpy_stop_btn)
        top.addWidget(self.scrcpy_stop_all_btn)
        scrcpy_layout.addLayout(top)

        opts = QHBoxLayout()
        opts.setSpacing(8)
        opts.addWidget(QLabel("Bitrate(M)"))
        self.scrcpy_bitrate = QSpinBox()
        self.scrcpy_bitrate.setRange(1, 80)
        self.scrcpy_bitrate.setValue(int(self.config.get("remote.scrcpy_bitrate_m", 12)))
        opts.addWidget(self.scrcpy_bitrate)
        opts.addWidget(QLabel("Max-size"))
        self.scrcpy_max_size = QSpinBox()
        self.scrcpy_max_size.setRange(0, 4096)
        self.scrcpy_max_size.setValue(int(self.config.get("remote.scrcpy_max_size", 1280)))
        self.scrcpy_max_size.setSpecialValueText("auto")
        opts.addWidget(self.scrcpy_max_size)
        opts.addWidget(QLabel("FPS"))
        self.scrcpy_max_fps = QSpinBox()
        self.scrcpy_max_fps.setRange(0, 120)
        self.scrcpy_max_fps.setValue(int(self.config.get("remote.scrcpy_max_fps", 60)))
        self.scrcpy_max_fps.setSpecialValueText("auto")
        opts.addWidget(self.scrcpy_max_fps)
        opts.addStretch()
        scrcpy_layout.addLayout(opts)

        flags = QHBoxLayout()
        flags.setSpacing(8)
        self.scrcpy_no_audio = QCheckBox("No audio")
        self.scrcpy_no_audio.setChecked(bool(self.config.get("remote.scrcpy_no_audio", True)))
        self.scrcpy_fullscreen = QCheckBox("Fullscreen")
        self.scrcpy_fullscreen.setChecked(bool(self.config.get("remote.scrcpy_fullscreen", False)))
        self.scrcpy_always_on_top = QCheckBox("Always on top")
        self.scrcpy_always_on_top.setChecked(bool(self.config.get("remote.scrcpy_always_on_top", False)))
        self.scrcpy_turn_screen_off = QCheckBox("Turn screen off")
        self.scrcpy_turn_screen_off.setChecked(bool(self.config.get("remote.scrcpy_turn_screen_off", False)))
        self.scrcpy_stay_awake = QCheckBox("Stay awake")
        self.scrcpy_stay_awake.setChecked(bool(self.config.get("remote.scrcpy_stay_awake", False)))
        self.scrcpy_show_touches = QCheckBox("Show touches")
        self.scrcpy_show_touches.setChecked(bool(self.config.get("remote.scrcpy_show_touches", False)))
        self.scrcpy_no_control = QCheckBox("View only")
        self.scrcpy_no_control.setChecked(bool(self.config.get("remote.scrcpy_no_control", False)))
        for w in (
            self.scrcpy_no_audio,
            self.scrcpy_fullscreen,
            self.scrcpy_always_on_top,
            self.scrcpy_turn_screen_off,
            self.scrcpy_stay_awake,
            self.scrcpy_show_touches,
            self.scrcpy_no_control,
        ):
            flags.addWidget(w)
        flags.addStretch()
        scrcpy_layout.addLayout(flags)

        extra_row = QHBoxLayout()
        extra_row.addWidget(QLabel("Args extra"))
        self.scrcpy_extra_args = QLineEdit(str(self.config.get("remote.scrcpy_extra_args", "")))
        self.scrcpy_extra_args.setPlaceholderText("Ex: --prefer-text --window-borderless")
        extra_row.addWidget(self.scrcpy_extra_args, 1)
        self.scrcpy_status_label = QLabel("Etat: inactif")
        self.scrcpy_status_label.setObjectName("deviceBadge")
        extra_row.addWidget(self.scrcpy_status_label)
        scrcpy_layout.addLayout(extra_row)
        layout.addWidget(scrcpy_group)

        actions_group = QGroupBox("Actions ADB (fallback tactile/clavier)")
        actions_group.setObjectName("panelCard")
        actions_layout = QVBoxLayout(actions_group)
        actions_layout.setContentsMargins(10, 10, 10, 10)
        actions_layout.setSpacing(8)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Cible actions"))
        self.remote_action_scope_box = QComboBox()
        self.remote_action_scope_box.addItem("Appareil cible", "selected")
        self.remote_action_scope_box.addItem("Appareil actif (top bar)", "active")
        self.remote_action_scope_box.addItem("Selection multiple", "checked")
        self.remote_action_scope_box.addItem("Tous les appareils", "all")
        scope_saved = str(self.config.get("remote.actions_scope", "selected"))
        scope_idx = self.remote_action_scope_box.findData(scope_saved)
        self.remote_action_scope_box.setCurrentIndex(scope_idx if scope_idx >= 0 else 0)
        scope_row.addWidget(self.remote_action_scope_box)
        self.remote_targets_select_all_btn = QPushButton("Tout cocher")
        self.remote_targets_select_all_btn.setObjectName("ghostBtn")
        self.remote_targets_clear_btn = QPushButton("Vider")
        self.remote_targets_clear_btn.setObjectName("ghostBtn")
        scope_row.addWidget(self.remote_targets_select_all_btn)
        scope_row.addWidget(self.remote_targets_clear_btn)
        scope_row.addStretch()
        actions_layout.addLayout(scope_row)

        self.remote_targets_list = QListWidget()
        self.remote_targets_list.setObjectName("remoteTargetsList")
        self.remote_targets_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.remote_targets_list.setMaximumHeight(112)
        self.remote_targets_list.setToolTip("Appareils cibles quand le mode 'Selection multiple' est active.")
        actions_layout.addWidget(self.remote_targets_list)

        nav_row = QHBoxLayout()
        self.remote_back_btn = QPushButton("Back")
        self.remote_home_btn = QPushButton("Home")
        self.remote_recent_btn = QPushButton("Recents")
        self.remote_power_btn = QPushButton("Power")
        self.remote_vol_up_btn = QPushButton("Vol+")
        self.remote_vol_down_btn = QPushButton("Vol-")
        self.remote_notif_btn = QPushButton("Notifications")
        self.remote_quick_settings_btn = QPushButton("QuickSettings")
        for b in (
            self.remote_back_btn,
            self.remote_home_btn,
            self.remote_recent_btn,
            self.remote_power_btn,
            self.remote_vol_up_btn,
            self.remote_vol_down_btn,
            self.remote_notif_btn,
            self.remote_quick_settings_btn,
        ):
            b.setObjectName("ghostBtn")
            nav_row.addWidget(b)
        nav_row.addStretch()
        actions_layout.addLayout(nav_row)

        input_row = QHBoxLayout()
        self.remote_text_input = QLineEdit()
        self.remote_text_input.setPlaceholderText("Texte a envoyer (input text)")
        self.remote_send_text_btn = QPushButton("Envoyer texte")
        self.remote_send_text_btn.setObjectName("successBtn")
        self.remote_wakeup_unlock_btn = QPushButton("Wake+Unlock")
        self.remote_wakeup_unlock_btn.setObjectName("ghostBtn")
        input_row.addWidget(self.remote_text_input, 1)
        input_row.addWidget(self.remote_send_text_btn)
        input_row.addWidget(self.remote_wakeup_unlock_btn)
        actions_layout.addLayout(input_row)

        self.remote_log_output = QTextEdit()
        self.remote_log_output.setReadOnly(True)
        self.remote_log_output.setPlaceholderText("Logs remote scrcpy/ADB...")
        self.remote_log_output.setMaximumHeight(190)
        actions_layout.addWidget(self.remote_log_output)
        layout.addWidget(actions_group)

        self.tabs.addTab(tab, "Remote")

        self.remote_center_refresh_btn.clicked.connect(self._refresh_remote_control_center)
        self.scrcpy_detect_btn.clicked.connect(self._detect_scrcpy)
        self.scrcpy_start_btn.clicked.connect(self._start_scrcpy_remote)
        self.scrcpy_start_all_btn.clicked.connect(self._start_scrcpy_remote_all)
        self.scrcpy_stop_btn.clicked.connect(self._stop_scrcpy_remote)
        self.scrcpy_stop_all_btn.clicked.connect(self._stop_all_scrcpy_remote)
        self.remote_action_scope_box.currentIndexChanged.connect(self._save_remote_action_scope)
        self.remote_targets_select_all_btn.clicked.connect(lambda: self._toggle_all_remote_targets(True))
        self.remote_targets_clear_btn.clicked.connect(lambda: self._toggle_all_remote_targets(False))
        self.remote_targets_list.itemChanged.connect(self._save_remote_action_scope)
        self.remote_back_btn.clicked.connect(lambda: self._remote_keyevent("KEYCODE_BACK"))
        self.remote_home_btn.clicked.connect(lambda: self._remote_keyevent("KEYCODE_HOME"))
        self.remote_recent_btn.clicked.connect(lambda: self._remote_keyevent("KEYCODE_APP_SWITCH"))
        self.remote_power_btn.clicked.connect(lambda: self._remote_keyevent("KEYCODE_POWER"))
        self.remote_vol_up_btn.clicked.connect(lambda: self._remote_keyevent("KEYCODE_VOLUME_UP"))
        self.remote_vol_down_btn.clicked.connect(lambda: self._remote_keyevent("KEYCODE_VOLUME_DOWN"))
        self.remote_notif_btn.clicked.connect(lambda: self._remote_shell("cmd statusbar expand-notifications"))
        self.remote_quick_settings_btn.clicked.connect(lambda: self._remote_shell("cmd statusbar expand-settings"))
        self.remote_send_text_btn.clicked.connect(self._remote_send_text)
        self.remote_text_input.returnPressed.connect(self._remote_send_text)
        self.remote_wakeup_unlock_btn.clicked.connect(self._remote_wakeup_unlock)
        self._refresh_remote_targets_list()
        self._refresh_remote_control_center()

    def _save_command_options(self) -> None:
        self.config.set("ui.confirm_critical_commands", bool(self.confirm_critical_box.isChecked()))
        self.config.set("ui.logcat_auto_scroll", bool(self.logcat_autoscroll_box.isChecked()))
        self.config.save()

    def _save_batch_options(self) -> None:
        self.config.set("ui.batch_workers", int(self.batch_workers_spin.value()))
        self.config.set("ui.batch_retry", int(self.batch_retry_spin.value()))
        self.config.set("ui.batch_timeout_s", int(self.batch_timeout_spin.value()))
        self.config.set("ui.batch_stop_on_error", bool(self.batch_stop_on_error.isChecked()))
        self.config.save()

    def _root_state_from_requirement(self, root_required: str) -> str:
        lower = root_required.lower()
        if lower.startswith("oui"):
            return "ROOT:Oui"
        if lower.startswith("parfois"):
            return "ROOT:Parfois"
        if lower.startswith("non"):
            return "ROOT:Non"
        return "ROOT:Inconnu"

    def _root_color(self, root_state: str) -> QColor:
        if root_state.endswith("Oui"):
            return QColor("#fca5a5")
        if root_state.endswith("Parfois"):
            return QColor("#fcd34d")
        if root_state.endswith("Non"):
            return QColor("#86efac")
        return QColor("#d1d5db")

    def _load_favorite_commands(self) -> set[str]:
        if not self._commands_config_file.exists():
            return set()
        try:
            data = json.loads(self._commands_config_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return set()
        favorites = data.get("favorites", [])
        out: set[str] = set()
        for item in favorites:
            if isinstance(item, dict):
                cmd = str(item.get("command", "")).strip()
            else:
                cmd = str(item).strip()
            if cmd:
                out.add(cmd)
        return out

    def _save_favorite_commands(self) -> None:
        self._commands_config_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "favorites": [{"name": cmd, "command": cmd} for cmd in sorted(self._favorite_commands)],
            "custom": [],
        }
        self._commands_config_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _toggle_selected_favorite(self) -> None:
        item = self.command_catalog.currentItem()
        if item is None:
            Toast(self, "Selectionnez une commande")
            return
        command = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not command:
            return
        if command in self._favorite_commands:
            self._favorite_commands.remove(command)
            Toast(self, "Commande retiree des favoris")
        else:
            self._favorite_commands.add(command)
            Toast(self, "Commande ajoutee aux favoris")
        self._save_favorite_commands()
        self._rebuild_command_catalog()

    def _grouped_command_entries(self) -> dict[str, list[tuple[str, str, str, str, tuple[str, ...]]]]:
        grouped: dict[str, list[tuple[str, str, str, str, tuple[str, ...]]]] = {}
        for _key, label, name, command, root_state, description, placeholders in self._command_entries:
            grouped.setdefault(label, []).append(
                (name, command, root_state, description or "Aucune description disponible.", placeholders)
            )
        return grouped

    def _build_commands_markdown(self) -> str:
        lines = [
            "# Catalogue des commandes ADB",
            "",
            f"Genere le: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        grouped = self._grouped_command_entries()
        for category, rows in grouped.items():
            lines.append(f"## {category}")
            lines.append("")
            for name, command, root_state, description, placeholders in rows:
                risk = self._command_risk_level(command, root_state)
                domain = self._infer_command_domain(command)
                lines.append(f"- **{name}**")
                lines.append(f"  - Root: `{root_state}`")
                lines.append(f"  - Risque: `{risk}`")
                lines.append(f"  - Domaine: `{domain}`")
                lines.append(f"  - Commande: `adb {command}`")
                lines.append(f"  - Parametres: {', '.join(placeholders) if placeholders else 'aucun'}")
                lines.append(f"  - Description: {description}")
                lines.append(f"  - Astuce: {self._command_usage_tip(command)}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _build_commands_html(self) -> str:
        rows = [
            "<h1>Catalogue des commandes ADB</h1>",
            f"<p>Genere le: {escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</p>",
        ]
        grouped = self._grouped_command_entries()
        for category, entries in grouped.items():
            rows.append(f"<h2>{escape(category)}</h2>")
            rows.append("<ul>")
            for name, command, root_state, description, placeholders in entries:
                risk = self._command_risk_level(command, root_state)
                domain = self._infer_command_domain(command)
                rows.append(
                    "<li>"
                    f"<b>{escape(name)}</b><br/>"
                    f"Root: <code>{escape(root_state)}</code><br/>"
                    f"Risque: <code>{escape(risk)}</code><br/>"
                    f"Domaine: <code>{escape(domain)}</code><br/>"
                    f"Commande: <code>adb {escape(command)}</code><br/>"
                    f"Parametres: {escape(', '.join(placeholders) if placeholders else 'aucun')}<br/>"
                    f"Description: {escape(description)}<br/>"
                    f"Astuce: {escape(self._command_usage_tip(command))}"
                    "</li>"
                )
            rows.append("</ul>")
        return "<html><body>" + "".join(rows) + "</body></html>"

    def _export_command_docs(self) -> None:
        default_name = f"adb_commands_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Exporter documentation des commandes",
            str(self.base_dir / default_name),
            "Markdown (*.md);;PDF (*.pdf)",
        )
        if not path:
            return
        target = Path(path)
        try:
            if "PDF" in selected_filter or target.suffix.lower() == ".pdf":
                if target.suffix.lower() != ".pdf":
                    target = target.with_suffix(".pdf")
                printer = QPrinter(QPrinter.PrinterMode.HighResolution)
                printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                printer.setOutputFileName(str(target))
                doc = QTextDocument()
                doc.setHtml(self._build_commands_html())
                doc.print(printer)
            else:
                if target.suffix.lower() != ".md":
                    target = target.with_suffix(".md")
                target.write_text(self._build_commands_markdown(), encoding="utf-8")
            Toast(self, f"Export termine: {target.name}")
        except Exception as exc:  # noqa: BLE001
            Toast(self, f"Echec export: {exc}")

    def _passes_root_filter(self, root_state: str, selected_filter: str) -> bool:
        if selected_filter == "Toutes":
            return True
        if selected_filter == "Sans root":
            return root_state.endswith("Non")
        if selected_filter == "Root parfois":
            return root_state.endswith("Parfois")
        if selected_filter == "Root oui":
            return root_state.endswith("Oui")
        return True

    def _rebuild_command_catalog(self) -> None:
        selected = self.command_filter_box.currentText() if hasattr(self, "command_filter_box") else "Toutes"
        search_text = self.command_search.text().strip().lower() if hasattr(self, "command_search") else ""
        favorites_only = bool(self.favorites_only.isChecked()) if hasattr(self, "favorites_only") else False
        self.config.set("ui.command_root_filter", selected)
        self.config.set("ui.command_search", search_text)
        self.config.set("ui.command_favorites_only", favorites_only)
        self.config.save()
        self.command_catalog.clear()

        grouped: dict[str, list[tuple[str, str, str, str]]] = {}
        for _key, label, name, command, root_state, description, placeholders in self._command_entries:
            if not self._passes_root_filter(root_state, selected):
                continue
            if favorites_only and command not in self._favorite_commands:
                continue
            haystack = f"{label} {name} {command} {description}".lower()
            if search_text and search_text not in haystack:
                continue
            grouped.setdefault(label, []).append((name, command, root_state, description, placeholders))

        for label, rows in grouped.items():
            header = QListWidgetItem(f"[{label}]")
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            header.setForeground(QColor("#93c5fd"))
            self.command_catalog.addItem(header)
            for name, command, root_state, description, placeholders in rows:
                favorite = "★ " if command in self._favorite_commands else "  "
                risk = self._command_risk_level(command, root_state)
                risk_short = {"critique": "CRIT", "attention": "WARN", "safe": "SAFE"}.get(risk, "INFO")
                row = QListWidgetItem(f"{favorite}{name} [{root_state} | {risk_short}] :: {command}")
                row.setForeground(self._risk_color(risk, root_state))
                row.setData(Qt.ItemDataRole.UserRole, command)
                row.setData(
                    Qt.ItemDataRole.UserRole + 1,
                    {
                        "name": name,
                        "command": command,
                        "root_state": root_state,
                        "risk": risk,
                        "domain": self._infer_command_domain(command),
                        "description": description or "Aucune description disponible.",
                        "category": label,
                        "placeholders": list(placeholders),
                    },
                )
                placeholder_hint = ", ".join(placeholders) if placeholders else "aucun"
                row.setToolTip(f"{description}\nRoot: {root_state}\nParametres: {placeholder_hint}")
                self.command_catalog.addItem(row)
        if hasattr(self, "command_details"):
            self.command_details.clear()
            self.command_details.setPlainText("Selectionnez une commande pour voir sa description detaillee.")

    def _on_command_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self.command_details.clear()
            return
        meta = current.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(meta, dict):
            self.command_details.clear()
            return
        risk = str(meta.get("risk", "safe"))
        risk_label = {"critique": "Critique", "attention": "Attention", "safe": "Safe"}.get(risk, risk)
        risk_color = self._risk_color_hex(risk)
        placeholders = ", ".join(meta.get("placeholders", [])) if meta.get("placeholders") else "aucun"
        tip = self._command_usage_tip(str(meta.get("command", "")))
        details_html = (
            "<div style='font-family: Segoe UI; line-height:1.45;'>"
            f"<div style='font-size:15px;font-weight:700;margin-bottom:6px;'>{escape(str(meta.get('name', '')))}</div>"
            f"<div><b>Categorie:</b> {escape(str(meta.get('category', '')))}</div>"
            f"<div><b>Domaine:</b> {escape(str(meta.get('domain', 'divers')))}</div>"
            f"<div><b>Root:</b> {escape(str(meta.get('root_state', '')))}</div>"
            f"<div><b>Risque:</b> <span style='color:{risk_color};font-weight:700'>{escape(risk_label)}</span></div>"
            f"<div style='margin-top:6px'><b>Commande:</b> <code>adb {escape(str(meta.get('command', '')))}</code></div>"
            f"<div><b>Parametres:</b> {escape(placeholders)}</div>"
            f"<div style='margin-top:8px'><b>Description:</b><br/>{escape(str(meta.get('description', 'Aucune description disponible.')))}</div>"
            f"<div style='margin-top:6px'><b>Astuce:</b> {escape(tip)}</div>"
            "</div>"
        )
        self.command_details.setHtml(details_html)

    def _build_backup_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        controls = QHBoxLayout()
        self.full_backup_btn = QPushButton("Sauvegarde complete")
        self.selective_backup_btn = QPushButton("Sauvegarde selective")
        self.restore_btn = QPushButton("Restaurer backup")
        self.full_backup_btn.setObjectName("successBtn")
        self.selective_backup_btn.setObjectName("ghostBtn")
        self.restore_btn.setObjectName("dangerBtn")
        controls.addWidget(self.full_backup_btn)
        controls.addWidget(self.selective_backup_btn)
        controls.addWidget(self.restore_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.backup_output = QTextEdit()
        self.backup_output.setReadOnly(True)
        layout.addWidget(self.backup_output)
        self.tabs.addTab(tab, "Backup/Restore")

        self.full_backup_btn.clicked.connect(self._full_backup)
        self.selective_backup_btn.clicked.connect(self._selective_backup)
        self.restore_btn.clicked.connect(self._restore_backup)

    def _build_captures_tab(self) -> None:
        self.captures_tab = QWidget()
        layout = QVBoxLayout(self.captures_tab)

        controls = QHBoxLayout()
        self.captures_refresh_btn = QPushButton("Actualiser captures")
        self.captures_delete_btn = QPushButton("Supprimer capture")
        self.captures_refresh_btn.setObjectName("successBtn")
        self.captures_delete_btn.setObjectName("dangerBtn")
        controls.addWidget(self.captures_refresh_btn)
        controls.addWidget(self.captures_delete_btn)
        controls.addStretch()
        layout.addLayout(controls)

        split = QSplitter()
        split.setChildrenCollapsible(False)
        left = QWidget()
        left.setObjectName("panelCard")
        left_layout = QVBoxLayout(left)
        right = QWidget()
        right.setObjectName("panelCard")
        right_layout = QVBoxLayout(right)

        self.captures_list = QListWidget()
        self.captures_info = QLabel("Aucune capture selectionnee")
        left_layout.addWidget(self.captures_list)
        left_layout.addWidget(self.captures_info)

        self.captures_preview = QLabel("Apercu capture")
        self.captures_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.captures_preview.setMinimumSize(480, 320)
        self.captures_preview.setStyleSheet("border: 1px solid #334155; border-radius: 8px;")
        right_layout.addWidget(self.captures_preview)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(480, 320)
        self.video_widget.hide()
        right_layout.addWidget(self.video_widget)

        self.video_controls = QHBoxLayout()
        self.video_play_btn = QPushButton("Play")
        self.video_pause_btn = QPushButton("Pause")
        self.video_stop_btn = QPushButton("Stop")
        self.video_play_btn.setObjectName("successBtn")
        self.video_pause_btn.setObjectName("ghostBtn")
        self.video_stop_btn.setObjectName("dangerBtn")
        self.video_controls.addWidget(self.video_play_btn)
        self.video_controls.addWidget(self.video_pause_btn)
        self.video_controls.addWidget(self.video_stop_btn)
        self.video_controls.addStretch()
        right_layout.addLayout(self.video_controls)

        self.media_player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        layout.addWidget(split)
        self.tabs.addTab(self.captures_tab, "Captures")

        self.captures_refresh_btn.clicked.connect(self._refresh_captures)
        self.captures_delete_btn.clicked.connect(self._delete_selected_capture)
        self.captures_list.currentTextChanged.connect(self._preview_capture)
        self.video_play_btn.clicked.connect(self.media_player.play)
        self.video_pause_btn.clicked.connect(self.media_player.pause)
        self.video_stop_btn.clicked.connect(self.media_player.stop)

        self._refresh_captures()

    def _build_reports_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        left = QGroupBox("Session Reports / Audit Trail")
        left.setObjectName("panelCard")
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(10, 10, 10, 10)
        left_l.setSpacing(8)
        row1 = QHBoxLayout()
        self.audit_session_box = QComboBox()
        self.audit_refresh_btn = QPushButton("Refresh")
        self.audit_export_json_btn = QPushButton("Export JSON")
        self.audit_export_html_btn = QPushButton("Export HTML")
        self.audit_refresh_btn.setObjectName("ghostBtn")
        self.audit_export_json_btn.setObjectName("successBtn")
        self.audit_export_html_btn.setObjectName("ghostBtn")
        row1.addWidget(QLabel("Session"))
        row1.addWidget(self.audit_session_box, 1)
        row1.addWidget(self.audit_refresh_btn)
        row1.addWidget(self.audit_export_json_btn)
        row1.addWidget(self.audit_export_html_btn)
        left_l.addLayout(row1)

        filters = QHBoxLayout()
        self.audit_device_filter = QComboBox()
        self.audit_device_filter.addItem("Tous devices", "")
        self.audit_type_filter = QComboBox()
        self.audit_type_filter.addItems(
            ["Tous types", "session", "device", "file", "app", "system", "debug", "capture", "batch", "script", "snapshot", "error"]
        )
        self.audit_date_from = QLineEdit()
        self.audit_date_from.setPlaceholderText("Date from YYYY-MM-DD")
        self.audit_date_to = QLineEdit()
        self.audit_date_to.setPlaceholderText("Date to YYYY-MM-DD")
        filters.addWidget(self.audit_device_filter)
        filters.addWidget(self.audit_type_filter)
        filters.addWidget(self.audit_date_from)
        filters.addWidget(self.audit_date_to)
        left_l.addLayout(filters)

        self.audit_table = QTableWidget(0, 6)
        self.audit_table.setHorizontalHeaderLabels(["Timestamp", "Device", "Type", "Action", "Status", "Message"])
        self.audit_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.audit_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        left_l.addWidget(self.audit_table, 1)
        self.audit_payload_text = QTextEdit()
        self.audit_payload_text.setReadOnly(True)
        self.audit_payload_text.setPlaceholderText("Payload evenement selectionne...")
        self.audit_payload_text.setMaximumHeight(170)
        left_l.addWidget(self.audit_payload_text)

        right = QGroupBox("Compare Snapshots")
        right.setObjectName("panelCard")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(10, 10, 10, 10)
        right_l.setSpacing(8)
        snap_top = QHBoxLayout()
        self.snapshot_capture_btn = QPushButton("Capture Snapshot")
        self.snapshot_refresh_btn = QPushButton("Refresh List")
        self.snapshot_compare_btn = QPushButton("Compare A/B")
        self.snapshot_export_json_btn = QPushButton("Export Diff JSON")
        self.snapshot_export_html_btn = QPushButton("Export Diff HTML")
        self.snapshot_capture_btn.setObjectName("successBtn")
        self.snapshot_refresh_btn.setObjectName("ghostBtn")
        self.snapshot_compare_btn.setObjectName("successBtn")
        self.snapshot_export_json_btn.setObjectName("ghostBtn")
        self.snapshot_export_html_btn.setObjectName("ghostBtn")
        snap_top.addWidget(self.snapshot_capture_btn)
        snap_top.addWidget(self.snapshot_refresh_btn)
        snap_top.addWidget(self.snapshot_compare_btn)
        snap_top.addWidget(self.snapshot_export_json_btn)
        snap_top.addWidget(self.snapshot_export_html_btn)
        right_l.addLayout(snap_top)
        snap_sel = QHBoxLayout()
        self.snapshot_a_box = QComboBox()
        self.snapshot_b_box = QComboBox()
        snap_sel.addWidget(QLabel("Snapshot A"))
        snap_sel.addWidget(self.snapshot_a_box, 1)
        snap_sel.addWidget(QLabel("Snapshot B"))
        snap_sel.addWidget(self.snapshot_b_box, 1)
        right_l.addLayout(snap_sel)
        self.snapshot_diff_text = QTextEdit()
        self.snapshot_diff_text.setReadOnly(True)
        self.snapshot_diff_text.setPlaceholderText("Diff snapshot (packages, stockage, CPU/memoire, props systeme, etat device)...")
        right_l.addWidget(self.snapshot_diff_text, 1)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)
        self.tabs.addTab(tab, "Reports")

        self.audit_refresh_btn.clicked.connect(self._refresh_audit_views)
        self.audit_session_box.currentIndexChanged.connect(self._refresh_audit_events)
        self.audit_device_filter.currentIndexChanged.connect(self._refresh_audit_events)
        self.audit_type_filter.currentIndexChanged.connect(self._refresh_audit_events)
        self.audit_date_from.textChanged.connect(self._refresh_audit_events)
        self.audit_date_to.textChanged.connect(self._refresh_audit_events)
        self.audit_table.itemSelectionChanged.connect(self._on_audit_row_selected)
        self.audit_export_json_btn.clicked.connect(self._export_selected_session_json)
        self.audit_export_html_btn.clicked.connect(self._export_selected_session_html)
        self.snapshot_capture_btn.clicked.connect(self._capture_device_snapshot)
        self.snapshot_refresh_btn.clicked.connect(self._refresh_snapshot_boxes)
        self.snapshot_compare_btn.clicked.connect(self._compare_selected_snapshots)
        self.snapshot_export_json_btn.clicked.connect(self._export_snapshot_diff_json)
        self.snapshot_export_html_btn.clicked.connect(self._export_snapshot_diff_html)

        self._refresh_audit_views()
        self._refresh_snapshot_boxes()

    def _build_transfer_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.transfer_direction = QComboBox()
        self.transfer_direction.addItems(["device -> host", "host -> device"])
        self.transfer_preset = QComboBox()
        self.transfer_preset.addItems(
            ["Custom folders", "Photos & Videos", "Documents", "Downloads", "DCIM", "Screenshots", "Export APK only"]
        )
        self.transfer_source = QLineEdit("/sdcard")
        self.transfer_destination = QLineEdit(str(self.base_dir / "transfers"))
        self.transfer_pick_source_btn = QPushButton("Parcourir source")
        self.transfer_pick_dest_btn = QPushButton("Parcourir destination")
        self.transfer_add_btn = QPushButton("Ajouter file")
        self.transfer_add_btn.setObjectName("successBtn")
        self.transfer_pick_source_btn.setObjectName("ghostBtn")
        self.transfer_pick_dest_btn.setObjectName("ghostBtn")
        top.addWidget(self.transfer_direction)
        top.addWidget(self.transfer_preset)
        top.addWidget(self.transfer_source, 1)
        top.addWidget(self.transfer_pick_source_btn)
        top.addWidget(self.transfer_destination, 1)
        top.addWidget(self.transfer_pick_dest_btn)
        top.addWidget(self.transfer_add_btn)
        layout.addLayout(top)

        action_row = QHBoxLayout()
        self.transfer_dry_run = QCheckBox("Dry-run (preview uniquement)")
        self.transfer_start_btn = QPushButton("Executer queue")
        self.transfer_clear_btn = QPushButton("Vider queue")
        self.transfer_export_btn = QPushButton("Export rapport transfert")
        self.transfer_start_btn.setObjectName("successBtn")
        self.transfer_clear_btn.setObjectName("dangerBtn")
        self.transfer_export_btn.setObjectName("ghostBtn")
        action_row.addWidget(self.transfer_dry_run)
        action_row.addStretch()
        action_row.addWidget(self.transfer_start_btn)
        action_row.addWidget(self.transfer_clear_btn)
        action_row.addWidget(self.transfer_export_btn)
        layout.addLayout(action_row)

        self.transfer_queue_table = QTableWidget(0, 7)
        self.transfer_queue_table.setHorizontalHeaderLabels(["ID", "Direction", "Preset", "Source", "Destination", "Dry-run", "Etat"])
        self.transfer_queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.transfer_queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.transfer_queue_table, 1)

        self.transfer_progress = QProgressBar()
        self.transfer_progress.setMinimum(0)
        self.transfer_progress.setMaximum(100)
        self.transfer_progress.setValue(0)
        layout.addWidget(self.transfer_progress)

        self.transfer_log = QTextEdit()
        self.transfer_log.setReadOnly(True)
        self.transfer_log.setPlaceholderText("Logs de transfert, verifications et remediations...")
        self.transfer_log.setMaximumHeight(190)
        layout.addWidget(self.transfer_log)

        self.tabs.addTab(tab, "Transfers")
        self.transfer_preset.currentTextChanged.connect(self._on_transfer_preset_changed)
        self.transfer_pick_source_btn.clicked.connect(self._pick_transfer_source)
        self.transfer_pick_dest_btn.clicked.connect(self._pick_transfer_destination)
        self.transfer_add_btn.clicked.connect(self._add_transfer_task)
        self.transfer_clear_btn.clicked.connect(self._clear_transfer_queue)
        self.transfer_start_btn.clicked.connect(self._run_transfer_queue)
        self.transfer_export_btn.clicked.connect(self._export_transfer_report)
        self._on_transfer_preset_changed(self.transfer_preset.currentText())

    def _build_device_health_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.health_refresh_btn2 = QPushButton("Run Device Health Checks")
        self.health_refresh_btn2.setObjectName("successBtn")
        self.health_export_json_btn2 = QPushButton("Export Health JSON")
        self.health_export_html_btn2 = QPushButton("Export Health HTML")
        self.health_history_refresh_btn = QPushButton("Refresh Timeline")
        self.health_history_export_btn = QPushButton("Export Timeline CSV")
        self.health_export_json_btn2.setObjectName("ghostBtn")
        self.health_export_html_btn2.setObjectName("ghostBtn")
        self.health_history_refresh_btn.setObjectName("ghostBtn")
        self.health_history_export_btn.setObjectName("ghostBtn")
        self.health_score_badge = QLabel("Score: n/a")
        self.health_score_badge.setObjectName("deviceBadge")
        top.addWidget(self.health_refresh_btn2)
        top.addWidget(self.health_export_json_btn2)
        top.addWidget(self.health_export_html_btn2)
        top.addWidget(self.health_history_refresh_btn)
        top.addWidget(self.health_history_export_btn)
        top.addStretch()
        top.addWidget(self.health_score_badge)
        layout.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        left = QWidget()
        right = QWidget()
        left_l = QVBoxLayout(left)
        right_l = QVBoxLayout(right)
        left_l.setContentsMargins(0, 0, 0, 0)
        right_l.setContentsMargins(0, 0, 0, 0)

        self.health_sections_text = QTextEdit()
        self.health_sections_text.setReadOnly(True)
        self.health_sections_text.setPlaceholderText("Resume par section (battery, storage, cpu/memory, thermal, connectivity, adb stability...)")
        left_l.addWidget(self.health_sections_text)

        self.health_findings_table = QTableWidget(0, 6)
        self.health_findings_table.setHorizontalHeaderLabels(["Category", "Title", "Severity", "Status", "Evidence", "Remediation"])
        self.health_findings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.health_findings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        right_l.addWidget(self.health_findings_table, 1)

        self.health_finding_raw = QTextEdit()
        self.health_finding_raw.setReadOnly(True)
        self.health_finding_raw.setPlaceholderText("Raw value finding selectionne...")
        self.health_finding_raw.setMaximumHeight(160)
        right_l.addWidget(self.health_finding_raw)

        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        layout.addWidget(split, 1)

        history_box = QGroupBox("Health Timeline")
        history_box.setObjectName("panelCard")
        history_l = QVBoxLayout(history_box)
        history_l.setContentsMargins(10, 10, 10, 10)
        history_l.setSpacing(6)
        self.health_timeline_summary = QLabel("Aucune donnee timeline")
        self.health_timeline_summary.setObjectName("metricLabel")
        history_l.addWidget(self.health_timeline_summary)
        self.health_timeline_chart = HealthTimelineChart()
        history_l.addWidget(self.health_timeline_chart)
        self.health_timeline_table = QTableWidget(0, 5)
        self.health_timeline_table.setHorizontalHeaderLabels(["Timestamp", "Device", "Score", "Status", "Summary"])
        self.health_timeline_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.health_timeline_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.health_timeline_table.setMaximumHeight(220)
        history_l.addWidget(self.health_timeline_table)
        layout.addWidget(history_box)

        self.tabs.addTab(tab, "Health")
        self.health_refresh_btn2.clicked.connect(self._run_device_health_checks)
        self.health_export_json_btn2.clicked.connect(self._export_device_health_json)
        self.health_export_html_btn2.clicked.connect(self._export_device_health_html)
        self.health_findings_table.itemSelectionChanged.connect(self._on_health_finding_selected)
        self.health_history_refresh_btn.clicked.connect(self._refresh_health_timeline)
        self.health_history_export_btn.clicked.connect(self._export_health_timeline_csv)
        self._refresh_health_timeline()

    def _on_transfer_preset_changed(self, preset: str) -> None:
        direction = self.transfer_direction.currentText().strip()
        if preset == "Export APK only":
            self.transfer_direction.setCurrentText("device -> host")
            self.transfer_source.setText("/data/app")
            self.transfer_destination.setText(str(self.base_dir / "transfers" / "apk_export"))
            return
        if preset == "Custom folders":
            if direction == "device -> host":
                self.transfer_source.setText("/sdcard")
                self.transfer_destination.setText(str(self.base_dir / "transfers"))
            else:
                self.transfer_source.setText(str(self.base_dir))
                self.transfer_destination.setText("/sdcard/Download")
            return
        preset_sources = self.transfer_module.preset_sources(preset)
        if direction == "device -> host":
            self.transfer_source.setText(preset_sources[0] if preset_sources else "/sdcard")
            self.transfer_destination.setText(str(self.base_dir / "transfers" / preset.lower().replace(" ", "_")))
        else:
            self.transfer_source.setText(str(self.base_dir / "transfers" / preset.lower().replace(" ", "_")))
            self.transfer_destination.setText("/sdcard/Download")

    def _pick_transfer_source(self) -> None:
        direction = self.transfer_direction.currentText().strip()
        if direction == "host -> device":
            path = QFileDialog.getExistingDirectory(self, "Choisir dossier source", self.transfer_source.text().strip() or str(self.base_dir))
            if path:
                self.transfer_source.setText(path)
            return
        text, ok = QInputDialog.getText(
            self,
            "Source device",
            "Chemin source sur l'appareil",
            text=self.transfer_source.text().strip() or "/sdcard",
        )
        if ok and text.strip():
            self.transfer_source.setText(text.strip())

    def _pick_transfer_destination(self) -> None:
        direction = self.transfer_direction.currentText().strip()
        if direction == "device -> host":
            path = QFileDialog.getExistingDirectory(
                self,
                "Choisir dossier destination",
                self.transfer_destination.text().strip() or str(self.base_dir / "transfers"),
            )
            if path:
                self.transfer_destination.setText(path)
            return
        text, ok = QInputDialog.getText(
            self,
            "Destination device",
            "Chemin destination sur l'appareil",
            text=self.transfer_destination.text().strip() or "/sdcard/Download",
        )
        if ok and text.strip():
            self.transfer_destination.setText(text.strip())

    def _refresh_transfer_queue_table(self) -> None:
        self.transfer_queue_table.setRowCount(len(self._transfer_queue))
        for row, item in enumerate(self._transfer_queue):
            self.transfer_queue_table.setItem(row, 0, QTableWidgetItem(str(item.get("task_id", ""))))
            self.transfer_queue_table.setItem(row, 1, QTableWidgetItem(str(item.get("direction", ""))))
            self.transfer_queue_table.setItem(row, 2, QTableWidgetItem(str(item.get("preset", ""))))
            self.transfer_queue_table.setItem(row, 3, QTableWidgetItem(str(item.get("source", ""))))
            self.transfer_queue_table.setItem(row, 4, QTableWidgetItem(str(item.get("destination", ""))))
            self.transfer_queue_table.setItem(row, 5, QTableWidgetItem("yes" if bool(item.get("dry_run")) else "no"))
            status_item = QTableWidgetItem(str(item.get("status", "queued")))
            status = str(item.get("status", "")).lower()
            if status in {"error", "fail"}:
                status_item.setForeground(QColor("#fca5a5"))
            elif status in {"partial", "warn", "warning"}:
                status_item.setForeground(QColor("#fcd34d"))
            elif status in {"success", "ok", "done", "dry_run"}:
                status_item.setForeground(QColor("#86efac"))
            self.transfer_queue_table.setItem(row, 6, status_item)

    def _add_transfer_task(self) -> None:
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        direction_ui = self.transfer_direction.currentText().strip()
        direction = "device_to_host" if direction_ui == "device -> host" else "host_to_device"
        preset = self.transfer_preset.currentText().strip()
        source = self.transfer_source.text().strip()
        destination = self.transfer_destination.text().strip()
        if not source or not destination:
            Toast(self, "Source/destination requises")
            return

        sources = [source]
        if preset not in {"Custom folders", "Export APK only"}:
            preset_sources = self.transfer_module.preset_sources(preset)
            if preset_sources and direction == "device_to_host":
                sources = preset_sources

        created = 0
        for src in sources:
            task = self.transfer_module.make_task(
                serial=serial,
                direction=direction,
                source=src,
                destination=destination,
                preset=preset,
                dry_run=bool(self.transfer_dry_run.isChecked()),
            )
            row = {
                "task_id": task.task_id,
                "created_at": task.created_at,
                "serial": task.serial,
                "direction": task.direction,
                "source": task.source,
                "destination": task.destination,
                "preset": task.preset,
                "dry_run": task.dry_run,
                "status": "queued",
            }
            self._transfer_queue.append(row)
            created += 1
        self._refresh_transfer_queue_table()
        self.transfer_log.append(f"[queue] {created} tache(s) ajoutees (preset={preset})")

    def _clear_transfer_queue(self) -> None:
        if self._transfer_running:
            Toast(self, "Transfer queue en cours")
            return
        self._transfer_queue.clear()
        self.transfer_progress.setValue(0)
        self._refresh_transfer_queue_table()
        self.transfer_log.append("[queue] videe")

    def _run_transfer_queue(self) -> None:
        if self._transfer_running:
            return
        if not self._transfer_queue:
            Toast(self, "Queue vide")
            return
        self._transfer_running = True
        self.transfer_start_btn.setEnabled(False)
        self.transfer_clear_btn.setEnabled(False)
        self.transfer_progress.setMaximum(max(1, len(self._transfer_queue)))
        self.transfer_progress.setValue(0)
        snapshot = [dict(item) for item in self._transfer_queue]
        self.transfer_log.append(f"[run] execution queue ({len(snapshot)} taches)")

        def _run_queue() -> dict[str, Any]:
            results: list[dict[str, Any]] = []
            total = len(snapshot)
            for idx, item in enumerate(snapshot, start=1):
                task = self.transfer_module.make_task(
                    serial=str(item.get("serial", "")),
                    direction=str(item.get("direction", "device_to_host")),
                    source=str(item.get("source", "")),
                    destination=str(item.get("destination", "")),
                    preset=str(item.get("preset", "")),
                    dry_run=bool(item.get("dry_run", False)),
                )
                task.task_id = str(item.get("task_id", task.task_id))
                result = self.transfer_module.execute_task(task)
                result["task_id"] = task.task_id
                results.append(result)
                self.bridge.command_done.emit(("transfer_progress", {"done": idx, "total": total, "result": result}))
            return {"results": results, "total": total}

        self._run_in_worker("transfer_queue_execute", _run_queue, {"serial": self._selected_serial() or ""})

    def _export_transfer_report(self) -> None:
        if not self._transfer_reports:
            Toast(self, "Aucun rapport transfert")
            return
        default = self.base_dir / "reports" / f"transfer_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Exporter rapport transfert", str(default), "JSON (*.json)")
        if not path:
            return
        payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "session_id": self._session_id,
            "reports": self._transfer_reports,
            "summary": {
                "total": len(self._transfer_reports),
                "ok": sum(1 for r in self._transfer_reports if bool(r.get("ok"))),
                "partial": sum(1 for r in self._transfer_reports if str(r.get("status", "")) == "partial"),
                "error": sum(1 for r in self._transfer_reports if str(r.get("status", "")) in {"error", "fail"}),
            },
        }
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        html_path = out.with_suffix(".html")
        rows = []
        for rep in self._transfer_reports:
            task = rep.get("task", {}) if isinstance(rep, dict) else {}
            rows.append(
                "<tr>"
                f"<td>{escape(str(rep.get('task_id', task.get('task_id', ''))))}</td>"
                f"<td>{escape(str(task.get('serial', '')))}</td>"
                f"<td>{escape(str(task.get('direction', '')))}</td>"
                f"<td>{escape(str(task.get('source', '')))}</td>"
                f"<td>{escape(str(task.get('destination', '')))}</td>"
                f"<td>{escape(str(rep.get('status', '')))}</td>"
                f"<td>{escape(str(rep.get('message', '')))}</td>"
                "</tr>"
            )
        html = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Transfer Report</title>"
            "<style>body{font-family:Arial;background:#0b1220;color:#e5e7eb;margin:20px}"
            "table{width:100%;border-collapse:collapse}th,td{border:1px solid #1f2937;padding:6px;font-size:12px}"
            "th{background:#111827}</style></head><body>"
            f"<h1>Transfer Report</h1><p>Session: {escape(self._session_id)}</p>"
            "<table><thead><tr><th>ID</th><th>Serial</th><th>Direction</th><th>Source</th><th>Destination</th><th>Status</th><th>Message</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></body></html>"
        )
        html_path.write_text(html, encoding="utf-8")
        Toast(self, "Rapport transfert exporte (JSON + HTML)")

    def _run_device_health_checks(self) -> None:
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        self._run_in_worker(
            "device_health_checks",
            lambda: self.device_health_module.run(serial, self._current_device_info()),
            {"serial": serial},
        )

    def _render_device_health_report(self, report: dict[str, Any]) -> None:
        self._last_device_health_report = report
        score = int(report.get("score", 0))
        status = str(report.get("status", "n/a"))
        self.health_score_badge.setText(f"Score: {score}/100 • {status}")

        sections = report.get("sections", {})
        section_lines = [f"Global: {status} ({score}/100)", ""]
        if isinstance(sections, dict):
            for name, summary in sections.items():
                if isinstance(summary, dict):
                    section_lines.append(
                        f"[{name}] pass={summary.get('pass',0)} warn={summary.get('warn',0)} fail={summary.get('fail',0)} unsupported={summary.get('unsupported',0)}"
                    )
        self.health_sections_text.setPlainText("\n".join(section_lines))

        findings = report.get("findings", [])
        if not isinstance(findings, list):
            findings = []
        self.health_findings_table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            f = finding if isinstance(finding, dict) else {}
            self.health_findings_table.setItem(row, 0, QTableWidgetItem(str(f.get("category", ""))))
            self.health_findings_table.setItem(row, 1, QTableWidgetItem(str(f.get("title", ""))))
            sev_item = QTableWidgetItem(str(f.get("severity", "")))
            severity = str(f.get("severity", "")).lower()
            if severity == "high":
                sev_item.setForeground(QColor("#fca5a5"))
            elif severity == "medium":
                sev_item.setForeground(QColor("#fcd34d"))
            elif severity in {"low", "info"}:
                sev_item.setForeground(QColor("#86efac"))
            self.health_findings_table.setItem(row, 2, sev_item)
            status_item = QTableWidgetItem(str(f.get("status", "")))
            st = str(f.get("status", "")).lower()
            if st == "fail":
                status_item.setForeground(QColor("#fca5a5"))
            elif st == "warn":
                status_item.setForeground(QColor("#fcd34d"))
            elif st == "pass":
                status_item.setForeground(QColor("#86efac"))
            self.health_findings_table.setItem(row, 3, status_item)
            self.health_findings_table.setItem(row, 4, QTableWidgetItem(str(f.get("evidence", ""))))
            self.health_findings_table.setItem(row, 5, QTableWidgetItem(str(f.get("remediation", ""))))
        self._refresh_health_timeline()

    def _health_trend_label(self, scores: list[int]) -> str:
        if len(scores) < 2:
            return "stable"
        recent = scores[:5]
        older = scores[-5:]
        r_avg = sum(recent) / len(recent)
        o_avg = sum(older) / len(older)
        delta = r_avg - o_avg
        if delta >= 5:
            return f"improving (+{delta:.1f})"
        if delta <= -5:
            return f"declining ({delta:.1f})"
        return f"stable ({delta:+.1f})"

    def _refresh_health_timeline(self) -> None:
        if not hasattr(self, "health_timeline_table"):
            return
        serial = self._selected_serial() or ""
        timeline = self.audit_module.list_health_timeline(device_serial=serial or None, limit=250)
        rows: list[dict[str, Any]] = []
        for item in timeline:
            rows.append(
                {
                    "timestamp": str(item.get("timestamp", "")),
                    "serial": str(item.get("device_serial", "")),
                    "score": int(item.get("score", -1)) if str(item.get("score", "-1")).lstrip("-").isdigit() else -1,
                    "status": str(item.get("status", "")),
                    "summary": str(item.get("summary", "")),
                }
            )
        self._health_history_rows = rows
        self.health_timeline_table.setRowCount(len(rows))
        scores: list[int] = []
        for r, row in enumerate(rows):
            self.health_timeline_table.setItem(r, 0, QTableWidgetItem(row["timestamp"]))
            self.health_timeline_table.setItem(r, 1, QTableWidgetItem(row["serial"]))
            score_item = QTableWidgetItem(str(row["score"]) if row["score"] >= 0 else "n/a")
            if row["score"] >= 0:
                scores.append(int(row["score"]))
                if row["score"] < 40:
                    score_item.setForeground(QColor("#fca5a5"))
                elif row["score"] < 70:
                    score_item.setForeground(QColor("#fcd34d"))
                else:
                    score_item.setForeground(QColor("#86efac"))
            self.health_timeline_table.setItem(r, 2, score_item)
            self.health_timeline_table.setItem(r, 3, QTableWidgetItem(row["status"]))
            self.health_timeline_table.setItem(r, 4, QTableWidgetItem(row["summary"]))
        if rows:
            latest = rows[0]
            trend = self._health_trend_label(scores)
            self.health_timeline_summary.setText(
                f"Timeline: {len(rows)} checks | latest={latest['score'] if latest['score'] >= 0 else 'n/a'}/100 ({latest['status']}) | trend={trend}"
            )
            self.health_timeline_chart.set_scores(scores)
        else:
            self.health_timeline_summary.setText("Aucun health check historise pour ce filtre.")
            self.health_timeline_chart.set_scores([])

    def _export_health_timeline_csv(self) -> None:
        if not self._health_history_rows:
            Toast(self, "Aucune timeline a exporter")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Health Timeline CSV",
            str(self.base_dir / "reports" / f"health_timeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"),
            "CSV (*.csv)",
        )
        if not path:
            return
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "device_serial", "score", "status", "summary"])
            for row in self._health_history_rows:
                writer.writerow([row["timestamp"], row["serial"], row["score"], row["status"], row["summary"]])
        Toast(self, "Timeline exportee (CSV)")

    def _on_health_finding_selected(self) -> None:
        if not self._last_device_health_report:
            return
        findings = self._last_device_health_report.get("findings", [])
        if not isinstance(findings, list):
            return
        row = self.health_findings_table.currentRow()
        if row < 0 or row >= len(findings):
            return
        finding = findings[row]
        if not isinstance(finding, dict):
            self.health_finding_raw.setPlainText("{}")
            return
        self.health_finding_raw.setPlainText(json.dumps(finding, indent=2, ensure_ascii=False))

    def _export_device_health_json(self) -> None:
        if not self._last_device_health_report:
            Toast(self, "Aucun rapport health")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Device Health JSON",
            str(self.base_dir / "reports" / f"device_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._last_device_health_report, indent=2, ensure_ascii=False), encoding="utf-8")
        Toast(self, "Device health exporte (JSON)")

    def _export_device_health_html(self) -> None:
        if not self._last_device_health_report:
            Toast(self, "Aucun rapport health")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Device Health HTML",
            str(self.base_dir / "reports" / f"device_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"),
            "HTML (*.html)",
        )
        if not path:
            return
        report = self._last_device_health_report
        findings = report.get("findings", [])
        rows = []
        if isinstance(findings, list):
            for finding in findings:
                f = finding if isinstance(finding, dict) else {}
                rows.append(
                    "<tr>"
                    f"<td>{escape(str(f.get('category', '')))}</td>"
                    f"<td>{escape(str(f.get('title', '')))}</td>"
                    f"<td>{escape(str(f.get('severity', '')))}</td>"
                    f"<td>{escape(str(f.get('status', '')))}</td>"
                    f"<td>{escape(str(f.get('evidence', '')))}</td>"
                    f"<td>{escape(str(f.get('remediation', '')))}</td>"
                    "</tr>"
                )
        html = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Device Health Report</title>"
            "<style>body{font-family:Arial;background:#0b1220;color:#e5e7eb;margin:20px}"
            "table{width:100%;border-collapse:collapse}th,td{border:1px solid #1f2937;padding:6px;font-size:12px}"
            "th{background:#111827}</style></head><body>"
            f"<h1>Device Health</h1><p>Serial: {escape(str(report.get('serial','')))} | Score: {escape(str(report.get('score','')))} | Status: {escape(str(report.get('status','')))}</p>"
            "<table><thead><tr><th>Category</th><th>Title</th><th>Severity</th><th>Status</th><th>Evidence</th><th>Remediation</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></body></html>"
        )
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
        Toast(self, "Device health exporte (HTML)")

    def _resolve_scrcpy_bin(self) -> str | None:
        raw = self.scrcpy_path_input.text().strip() if hasattr(self, "scrcpy_path_input") else "scrcpy"
        if not raw:
            raw = "scrcpy"
        self.config.set("app.scrcpy_bin", raw)
        self.config.save()
        if Path(raw).exists():
            return raw
        found = shutil.which(raw)
        return found

    def _detect_scrcpy(self) -> None:
        resolved = self._resolve_scrcpy_bin()
        if resolved:
            self.scrcpy_status_label.setText(f"Etat: disponible ({Path(resolved).name})")
            Toast(self, f"scrcpy detecte: {resolved}")
        else:
            self.scrcpy_status_label.setText("Etat: scrcpy introuvable")
            QMessageBox.warning(
                self,
                "scrcpy manquant",
                "scrcpy n'est pas installe ou introuvable dans PATH.\n"
                "Installe-le puis renseigne le binaire.",
            )

    def _save_scrcpy_options(self) -> None:
        self.config.set("remote.scrcpy_bitrate_m", int(self.scrcpy_bitrate.value()))
        self.config.set("remote.scrcpy_max_size", int(self.scrcpy_max_size.value()))
        self.config.set("remote.scrcpy_max_fps", int(self.scrcpy_max_fps.value()))
        self.config.set("remote.scrcpy_no_audio", bool(self.scrcpy_no_audio.isChecked()))
        self.config.set("remote.scrcpy_fullscreen", bool(self.scrcpy_fullscreen.isChecked()))
        self.config.set("remote.scrcpy_always_on_top", bool(self.scrcpy_always_on_top.isChecked()))
        self.config.set("remote.scrcpy_turn_screen_off", bool(self.scrcpy_turn_screen_off.isChecked()))
        self.config.set("remote.scrcpy_stay_awake", bool(self.scrcpy_stay_awake.isChecked()))
        self.config.set("remote.scrcpy_show_touches", bool(self.scrcpy_show_touches.isChecked()))
        self.config.set("remote.scrcpy_no_control", bool(self.scrcpy_no_control.isChecked()))
        self.config.set("remote.scrcpy_extra_args", str(self.scrcpy_extra_args.text().strip()))
        self.config.save()

    def _save_remote_action_scope(self, *_args) -> None:
        scope = "selected"
        if hasattr(self, "remote_action_scope_box"):
            scope = str(self.remote_action_scope_box.currentData() or "selected")
        checked_serials: list[str] = []
        if hasattr(self, "remote_targets_list"):
            for i in range(self.remote_targets_list.count()):
                item = self.remote_targets_list.item(i)
                if item is not None and item.checkState() == Qt.CheckState.Checked:
                    serial = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                    if serial:
                        checked_serials.append(serial)
        self.config.set("remote.actions_scope", scope)
        self.config.set("remote.actions_checked", checked_serials)
        self.config.save()

    def _refresh_remote_device_box(self) -> None:
        if not hasattr(self, "remote_device_box"):
            return
        current = str(self.remote_device_box.currentData() or "")
        self.remote_device_box.blockSignals(True)
        self.remote_device_box.clear()
        for dev in self._last_devices:
            self.remote_device_box.addItem(f"{dev.serial} ({dev.model})", dev.serial)
        if self.remote_device_box.count() == 0:
            self.remote_device_box.addItem("Aucun appareil", "")
        if current:
            idx = self.remote_device_box.findData(current)
            if idx >= 0:
                self.remote_device_box.setCurrentIndex(idx)
        self.remote_device_box.blockSignals(False)

    def _refresh_remote_targets_list(self) -> None:
        if not hasattr(self, "remote_targets_list"):
            return
        saved = self.config.get("remote.actions_checked", [])
        saved_set: set[str] = set()
        if isinstance(saved, list):
            saved_set = {str(x).strip() for x in saved if str(x).strip()}
        self.remote_targets_list.blockSignals(True)
        self.remote_targets_list.clear()
        for dev in self._last_devices:
            item = QListWidgetItem(f"{dev.serial} ({dev.model})")
            item.setData(Qt.ItemDataRole.UserRole, dev.serial)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if dev.serial in saved_set else Qt.CheckState.Unchecked)
            self.remote_targets_list.addItem(item)
        self.remote_targets_list.blockSignals(False)

    def _toggle_all_remote_targets(self, checked: bool) -> None:
        if not hasattr(self, "remote_targets_list"):
            return
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.remote_targets_list.blockSignals(True)
        for i in range(self.remote_targets_list.count()):
            item = self.remote_targets_list.item(i)
            if item is not None:
                item.setCheckState(state)
        self.remote_targets_list.blockSignals(False)
        self._save_remote_action_scope()

    def _selected_remote_target_serials(self) -> list[str]:
        out: list[str] = []
        if not hasattr(self, "remote_targets_list"):
            return out
        for i in range(self.remote_targets_list.count()):
            item = self.remote_targets_list.item(i)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            serial = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if serial:
                out.append(serial)
        return out

    def _remote_selected_serial(self) -> str | None:
        if not hasattr(self, "remote_device_box"):
            return self._selected_serial()
        serial = str(self.remote_device_box.currentData() or "").strip()
        if serial:
            return serial
        return self._selected_serial()

    def _remote_target_serials_for_actions(self) -> list[str]:
        scope = "selected"
        if hasattr(self, "remote_action_scope_box"):
            scope = str(self.remote_action_scope_box.currentData() or "selected")
        if scope == "all":
            return [d.serial for d in self._last_devices]
        if scope == "active":
            serial = self._selected_serial()
            return [serial] if serial else []
        if scope == "checked":
            serials = self._selected_remote_target_serials()
            return serials if serials else []
        serial = self._remote_selected_serial()
        return [serial] if serial else []

    def _update_scrcpy_status_ui(self) -> None:
        count = len(self.scrcpy_processes)
        if count == 0:
            self.scrcpy_status_label.setText("Etat: inactif")
            self.scrcpy_stop_btn.setEnabled(False)
            self.scrcpy_stop_all_btn.setEnabled(False)
            self.scrcpy_start_btn.setEnabled(True)
            self.scrcpy_start_all_btn.setEnabled(True)
            return
        running = ", ".join(list(self.scrcpy_processes.keys())[:3])
        if count > 3:
            running += ", ..."
        self.scrcpy_status_label.setText(f"Etat: actif ({count}) {running}")
        self.scrcpy_stop_btn.setEnabled(True)
        self.scrcpy_stop_all_btn.setEnabled(True)
        self.scrcpy_start_btn.setEnabled(True)
        self.scrcpy_start_all_btn.setEnabled(True)

    def _start_scrcpy_remote(self) -> None:
        serial = self._remote_selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        if serial in self.scrcpy_processes:
            Toast(self, f"Remote scrcpy deja actif sur {serial}")
            return
        resolved = self._resolve_scrcpy_bin()
        if not resolved:
            self._detect_scrcpy()
            return

        self._save_scrcpy_options()
        args: list[str] = ["-s", serial, "--window-title", f"ADB Manager Remote - {serial}"]
        bitrate = int(self.scrcpy_bitrate.value())
        max_size = int(self.scrcpy_max_size.value())
        max_fps = int(self.scrcpy_max_fps.value())
        if bitrate > 0:
            args += ["--video-bit-rate", f"{bitrate}M"]
        if max_size > 0:
            args += ["--max-size", str(max_size)]
        if max_fps > 0:
            args += ["--max-fps", str(max_fps)]
        if self.scrcpy_no_audio.isChecked():
            args.append("--no-audio")
        if self.scrcpy_fullscreen.isChecked():
            args.append("--fullscreen")
        if self.scrcpy_always_on_top.isChecked():
            args.append("--always-on-top")
        if self.scrcpy_turn_screen_off.isChecked():
            args.append("--turn-screen-off")
        if self.scrcpy_stay_awake.isChecked():
            args.append("--stay-awake")
        if self.scrcpy_show_touches.isChecked():
            args.append("--show-touches")
        if self.scrcpy_no_control.isChecked():
            args.append("--no-control")
        extra = self.scrcpy_extra_args.text().strip()
        if extra:
            try:
                args += shlex.split(extra)
            except ValueError:
                Toast(self, "Args extra invalides")
                return

        proc = QProcess(self)
        self.scrcpy_process = proc
        self.scrcpy_processes[serial] = proc
        proc.setProperty("serial", serial)
        proc.setProgram(resolved)
        proc.setArguments(args)
        proc.readyReadStandardOutput.connect(self._consume_scrcpy_stdout)
        proc.readyReadStandardError.connect(self._consume_scrcpy_stderr)
        proc.finished.connect(self._on_scrcpy_finished)
        proc.start()

        self._update_scrcpy_status_ui()
        self.remote_log_output.append(f"[scrcpy:{serial}] start: {resolved} {' '.join(args)}")

    def _start_scrcpy_remote_all(self) -> None:
        if not self._last_devices:
            Toast(self, "Aucun appareil connecte")
            return
        for dev in self._last_devices:
            if dev.serial in self.scrcpy_processes:
                continue
            if hasattr(self, "remote_device_box"):
                idx = self.remote_device_box.findData(dev.serial)
                if idx >= 0:
                    self.remote_device_box.setCurrentIndex(idx)
            self._start_scrcpy_remote()
        self._update_scrcpy_status_ui()

    def _stop_scrcpy_remote(self, silent: bool = False) -> None:
        serial = self._remote_selected_serial()
        proc = self.scrcpy_processes.pop(serial or "", None)
        if proc is None and self.scrcpy_processes:
            # Fallback: stop any running session if selected serial is not running.
            serial, proc = next(iter(self.scrcpy_processes.items()))
            self.scrcpy_processes.pop(serial, None)
        if proc is None:
            return
        if self.scrcpy_process is proc:
            self.scrcpy_process = None
        if proc.state() != QProcess.ProcessState.NotRunning:
            proc.terminate()
            if not proc.waitForFinished(1200):
                proc.kill()
                proc.waitForFinished(800)
        proc.deleteLater()
        self._update_scrcpy_status_ui()
        if not silent:
            self.remote_log_output.append(f"[scrcpy:{serial}] stop")

    def _stop_all_scrcpy_remote(self, silent: bool = False) -> None:
        for serial in list(self.scrcpy_processes.keys()):
            proc = self.scrcpy_processes.pop(serial, None)
            if proc is None:
                continue
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.terminate()
                if not proc.waitForFinished(1200):
                    proc.kill()
                    proc.waitForFinished(800)
            proc.deleteLater()
            if not silent:
                self.remote_log_output.append(f"[scrcpy:{serial}] stop")
        self.scrcpy_process = None
        self._update_scrcpy_status_ui()

    def _consume_scrcpy_stdout(self) -> None:
        proc = self.sender()
        if not isinstance(proc, QProcess):
            return
        serial = str(proc.property("serial") or "?")
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
        if data:
            self.remote_log_output.append(f"[scrcpy:{serial}] {data}")

    def _consume_scrcpy_stderr(self) -> None:
        proc = self.sender()
        if not isinstance(proc, QProcess):
            return
        serial = str(proc.property("serial") or "?")
        data = bytes(proc.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if data:
            self.remote_log_output.append(f"[scrcpy:{serial}] {data}")

    def _on_scrcpy_finished(self, _code: int, _status: QProcess.ExitStatus) -> None:
        proc = self.sender()
        serial = "?"
        if isinstance(proc, QProcess):
            serial = str(proc.property("serial") or "?")
            self.scrcpy_processes.pop(serial, None)
            if self.scrcpy_process is proc:
                self.scrcpy_process = None
        self._update_scrcpy_status_ui()
        self.remote_log_output.append(f"[scrcpy:{serial}] termine")

    def _remote_shell(self, shell_command: str) -> None:
        serials = self._remote_target_serials_for_actions()
        if not serials:
            Toast(self, "Aucun appareil actif")
            return

        for serial in serials:
            def done(result: CommandResult, s=serial) -> None:
                self.bridge.command_done.emit(("remote_shell", {"serial": s, "result": result}))
            self.adb.run_async(["shell", "sh", "-c", shell_command], serial=serial, callback=done)

    def _remote_keyevent(self, keycode: str) -> None:
        self._remote_shell(f"input keyevent {keycode}")

    def _remote_send_text(self) -> None:
        text = self.remote_text_input.text().strip()
        if not text:
            return
        payload = text.replace(" ", "%s").replace('"', "")
        self._remote_shell(f'input text "{payload}"')
        self.remote_text_input.clear()

    def _remote_wakeup_unlock(self) -> None:
        self._remote_shell("input keyevent KEYCODE_WAKEUP")
        self._remote_shell("input swipe 300 1000 300 500")

    def _set_active_serial(self, serial: str) -> None:
        if not serial:
            return
        idx = self.device_box.findData(serial) if hasattr(self, "device_box") else -1
        if idx >= 0:
            self.device_box.setCurrentIndex(idx)
        if hasattr(self, "remote_device_box"):
            ridx = self.remote_device_box.findData(serial)
            if ridx >= 0:
                self.remote_device_box.setCurrentIndex(ridx)

    def _start_scrcpy_for_serial(self, serial: str) -> None:
        self._set_active_serial(serial)
        self._start_scrcpy_remote()

    def _remote_shell_for_serial(self, serial: str, shell_command: str) -> None:
        if not serial:
            return

        def done(result: CommandResult, s=serial) -> None:
            self.bridge.command_done.emit(("remote_shell", {"serial": s, "result": result}))

        self.adb.run_async(["shell", "sh", "-c", shell_command], serial=serial, callback=done)

    def _capture_screen_for_serial(self, serial: str, open_captures_tab: bool = False) -> None:
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        captures_dir = self.base_dir / "captures"
        captures_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_serial = re.sub(r"[^a-zA-Z0-9._-]", "_", serial)
        local_file = captures_dir / f"capture_{safe_serial}_{stamp}.png"
        remote_tmp = "/sdcard/__adb_manager_capture.png"

        shot = self.adb.run(["shell", "screencap", "-p", remote_tmp], serial=serial)
        if not shot.ok:
            Toast(self, f"Capture echec {serial}: {shot.stderr}")
            return
        pull = self.adb.run(["pull", remote_tmp, str(local_file)], serial=serial)
        self.adb.run(["shell", "rm", "-f", remote_tmp], serial=serial)
        if pull.ok:
            Toast(self, f"Capture {serial}: {local_file.name}")
            self._refresh_captures(selected_file=local_file.name)
            if open_captures_tab:
                self.tabs.setCurrentWidget(self.captures_tab)
        else:
            Toast(self, f"Pull capture echec {serial}: {pull.stderr}")

    def _clear_grid_layout(self, layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _refresh_remote_control_center(self) -> None:
        if not hasattr(self, "remote_center_grid"):
            return
        self._clear_grid_layout(self.remote_center_grid)
        devices = self._last_devices
        self.remote_center_summary.setText(f"{len(devices)} appareil(s)")
        if not devices:
            empty = QLabel("Aucun appareil connecte")
            empty.setObjectName("metricLabel")
            self.remote_center_grid.addWidget(empty, 0, 0)
            return

        columns = 3
        for idx, dev in enumerate(devices):
            card = QWidget()
            card.setObjectName("panelCard")
            card_l = QVBoxLayout(card)
            card_l.setContentsMargins(10, 10, 10, 10)
            card_l.setSpacing(6)
            title = QLabel(f"{dev.model or 'Android'}")
            title.setObjectName("appTitle")
            title.setStyleSheet("font-size:15px;")
            card_l.addWidget(title)
            card_l.addWidget(QLabel(f"Serial: {dev.serial}"))
            card_l.addWidget(QLabel(f"Etat: {dev.state} | Android: {dev.android_version}"))
            card_l.addWidget(QLabel(f"Transport: {dev.transport} | Root: {'yes' if dev.root else 'no'}"))

            row = QHBoxLayout()
            btn_active = QPushButton("Activer")
            btn_scrcpy = QPushButton("Scrcpy")
            btn_wake = QPushButton("Wake")
            btn_shot = QPushButton("Shot")
            btn_active.setObjectName("ghostBtn")
            btn_scrcpy.setObjectName("successBtn")
            btn_wake.setObjectName("ghostBtn")
            btn_shot.setObjectName("ghostBtn")
            btn_active.clicked.connect(lambda _=False, s=dev.serial: self._set_active_serial(s))
            btn_scrcpy.clicked.connect(lambda _=False, s=dev.serial: self._start_scrcpy_for_serial(s))
            btn_wake.clicked.connect(lambda _=False, s=dev.serial: self._remote_shell_for_serial(s, "input keyevent KEYCODE_WAKEUP"))
            btn_shot.clicked.connect(lambda _=False, s=dev.serial: self._capture_screen_for_serial(s, open_captures_tab=False))
            row.addWidget(btn_active)
            row.addWidget(btn_scrcpy)
            row.addWidget(btn_wake)
            row.addWidget(btn_shot)
            row.addStretch()
            card_l.addLayout(row)

            r = idx // columns
            c = idx % columns
            self.remote_center_grid.addWidget(card, r, c)

    def _setup_polling(self) -> None:
        self.device_manager.add_listener(lambda devices: self.bridge.device_list_updated.emit(devices))
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(int(self.config.get("app.refresh_interval_ms", 2500)))
        self.poll_timer.timeout.connect(self.device_manager.poll_async)
        self.poll_timer.start()
        self.device_manager.poll_async()

    def _apply_theme(self, theme_name: str) -> None:
        accent = str(self.config.get("app.accent", "#2563eb"))
        density = str(self.config.get("ui.density", "comfortable"))
        self.setStyleSheet(get_theme(theme_name, accent=accent, density=density))
        self.config.set("app.theme", theme_name)
        self.config.save()
        self._apply_density_settings(density)

    def _apply_density(self, density_name: str) -> None:
        self.config.set("ui.density", density_name)
        self.config.save()
        self._apply_theme(str(self.theme_box.currentText()))

    def _choose_accent_color(self) -> None:
        current = QColor(str(self.config.get("app.accent", "#2563eb")))
        color = QColorDialog.getColor(current, self, "Choisir une couleur d'accent")
        if not color.isValid():
            return
        self.config.set("app.accent", color.name())
        self._apply_theme(str(self.theme_box.currentText()))

    def _set_tab_icons(self) -> None:
        self._tab_icons = [
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon),
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView),
            self.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon),
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay),
            self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation),
            self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon),
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon),
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon),
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight),
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton),
        ]
        for idx, icon in enumerate(self._tab_icons):
            if idx < self.tabs.count():
                self.tabs.setTabIcon(idx, icon)

    def _build_sidebar_nav(self) -> None:
        self.nav_sidebar.clear()
        for idx in range(self.tabs.count()):
            title = self.tabs.tabText(idx)
            icon = self._tab_icons[idx] if idx < len(self._tab_icons) else QIcon()
            item = QListWidgetItem(icon, f"{idx + 1}. {title}")
            item.setToolTip(f"Ctrl+{idx + 1} pour ouvrir {title}")
            self.nav_sidebar.addItem(item)
        if self.tabs.count() > 0:
            self.nav_sidebar.setCurrentRow(0)

    def _on_sidebar_nav_changed(self, row: int) -> None:
        if row < 0 or row >= self.tabs.count():
            return
        if self.tabs.currentIndex() != row:
            self.tabs.setCurrentIndex(row)

    def _sync_sidebar_to_tab(self, index: int) -> None:
        if index < 0:
            return
        if self.nav_sidebar.currentRow() != index:
            self.nav_sidebar.setCurrentRow(index)
        self.statusBar().showMessage(f"Onglet actif: {self.tabs.tabText(index)}")

    def _setup_tab_shortcuts(self) -> None:
        self._tab_shortcuts.clear()
        for idx in range(min(9, self.tabs.count())):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{idx + 1}"), self)
            shortcut.activated.connect(lambda i=idx: self.tabs.setCurrentIndex(i))
            self._tab_shortcuts.append(shortcut)

    def _setup_sidebar_shortcut(self) -> None:
        self._sidebar_shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self._sidebar_shortcut.activated.connect(self._toggle_sidebar)

    def _setup_palette_shortcut(self) -> None:
        self._command_palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._command_palette_shortcut.activated.connect(self._focus_command_palette)

    def _focus_command_palette(self) -> None:
        debug_index = self._tab_index_by_title("Debug")
        if debug_index >= 0:
            self.tabs.setCurrentIndex(debug_index)
        self.command_search.setFocus()
        self.command_search.selectAll()

    def _tab_index_by_title(self, title: str) -> int:
        normalized = title.strip().lower()
        for idx in range(self.tabs.count()):
            if self.tabs.tabText(idx).strip().lower() == normalized:
                return idx
        return -1

    def _apply_sidebar_state(self, collapsed: bool, persist: bool = True) -> None:
        self.sidebar_container.setVisible(not collapsed)
        self.sidebar_toggle_btn.setText("➤" if collapsed else "☰")
        self.sidebar_toggle_btn.setToolTip("Afficher la sidebar (Ctrl+B)" if collapsed else "Masquer la sidebar (Ctrl+B)")
        if persist:
            self.config.set("ui.sidebar_collapsed", collapsed)
            self.config.save()

    def _toggle_sidebar(self) -> None:
        self._auto_sidebar_collapsed = False
        collapsed = self.sidebar_container.isVisible()
        self._apply_sidebar_state(collapsed)

    def _apply_density_settings(self, density: str) -> None:
        compact = density.lower() == "compact"
        row_h = 26 if compact else 34
        if hasattr(self, "device_table"):
            self.device_table.verticalHeader().setDefaultSectionSize(row_h)
        if hasattr(self, "command_details"):
            self.command_details.setMaximumHeight(160 if compact else 240)
            self.command_details.setMinimumHeight(96 if compact else 120)
        if hasattr(self, "command_catalog"):
            self.command_catalog.setMinimumHeight(160 if compact else 210)
        if hasattr(self, "live_log_output"):
            self.live_log_output.setMinimumHeight(90 if compact else 120)
        if hasattr(self, "batch_output"):
            self.batch_output.setMaximumHeight(180 if compact else 230)
        if hasattr(self, "batch_queue_list"):
            self.batch_queue_list.setMaximumHeight(150 if compact else 190)
        if hasattr(self, "nav_sidebar"):
            self.nav_sidebar.setSpacing(2 if compact else 5)

    def _animate_tab_transition(self, _index: int) -> None:
        page = self.tabs.currentWidget()
        if page is None:
            return
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(170)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._tab_anim = anim
        anim.finished.connect(lambda: page.setGraphicsEffect(None))
        anim.start()

    def _run_quick_command(self) -> None:
        command = self.quick_command_input.text().strip()
        if not command:
            return
        self._run_terminal_command(command)
        self.quick_command_input.clear()

    def _tick_clock(self) -> None:
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))

    def _update_responsive_layout(self) -> None:
        width = self.width()
        if width < 1180 and self.sidebar_container.isVisible():
            self._auto_sidebar_collapsed = True
            self._apply_sidebar_state(True, persist=False)
        elif width >= 1260 and self._auto_sidebar_collapsed:
            self._auto_sidebar_collapsed = False
            self._apply_sidebar_state(False, persist=False)

    def _set_terminal_suggestions(self) -> None:
        suggestions = []
        for items in COMMAND_CATALOG.values():
            suggestions.extend(item.command for item in items)
        suggestions.extend([
            "connect 192.168.1.10:5555",
            "disconnect",
            "tcpip 5555",
            "shell getprop",
            "shell settings list global",
            "shell wm size",
            "exec-out screencap -p",
        ])
        self.terminal.set_suggestions(suggestions)

    @Slot(object)
    def _on_devices_updated(self, devices: list[DeviceInfo]) -> None:
        self._last_devices = devices
        current_serials = {d.serial for d in devices}
        new_serials = current_serials - self._last_device_serials
        gone_serials = self._last_device_serials - current_serials
        for serial in sorted(new_serials):
            dev = next((d for d in devices if d.serial == serial), None)
            self._audit_event(
                event_type="device",
                action="device_connected",
                status="ok",
                message=f"Device connected: {serial}",
                payload={"model": dev.model if dev else "", "transport": dev.transport if dev else ""},
                serial=serial,
            )
        for serial in sorted(gone_serials):
            self._audit_event(
                event_type="device",
                action="device_disconnected",
                status="warning",
                message=f"Device disconnected: {serial}",
                payload={},
                serial=serial,
            )
        self._last_device_serials = current_serials
        root_count = sum(1 for d in devices if d.root)
        if devices:
            active = devices[0]
            self.device_badge.setText(f"{len(devices)} appareil(s) • actif: {active.serial}")
        else:
            self.device_badge.setText("Aucun appareil")
        if hasattr(self, "metric_devices_value"):
            self.metric_devices_value.setText(str(len(devices)))
        if hasattr(self, "metric_root_value"):
            self.metric_root_value.setText(str(root_count))
        if hasattr(self, "metric_active_value"):
            self.metric_active_value.setText(devices[0].serial if devices else "-")
        previous_serial = str(self.device_box.currentData() or "") if self.device_box.count() else ""
        self.device_box.blockSignals(True)
        self.device_box.clear()
        for dev in devices:
            self.device_box.addItem(f"{dev.serial} ({dev.model})", dev.serial)
        if previous_serial:
            idx_prev = self.device_box.findData(previous_serial)
            if idx_prev >= 0:
                self.device_box.setCurrentIndex(idx_prev)
        current_serial = str(self.device_box.currentData() or "") if self.device_box.count() else ""
        self.device_box.blockSignals(False)
        self._refresh_profile_box()
        if current_serial:
            self._autoload_profile_for_device(current_serial)
        self._refresh_remote_device_box()
        self._refresh_remote_targets_list()
        self._refresh_remote_control_center()
        if current_serial != previous_serial:
            self._on_active_device_changed(-1)

        self.device_table.setRowCount(len(devices))
        for row, dev in enumerate(devices):
            self.device_table.setItem(row, 0, QTableWidgetItem(dev.serial))
            self.device_table.setItem(row, 1, QTableWidgetItem(dev.state))
            self.device_table.setItem(row, 2, QTableWidgetItem(dev.model))
            self.device_table.setItem(row, 3, QTableWidgetItem(dev.transport))
            self.device_table.setItem(row, 4, QTableWidgetItem(dev.android_version))
            self.device_table.setItem(row, 5, QTableWidgetItem("yes" if dev.root else "no"))

        hist_rows = self.history.recent_device_history(limit=20)
        self.history_box.setPlainText("\n".join(f"{ts} | {serial} | {model} | {event}" for serial, model, event, ts in hist_rows))

    def _selected_serial(self) -> str | None:
        if self.device_box.count() == 0:
            return None
        return str(self.device_box.currentData() or "")

    def _manual_refresh(self) -> None:
        self.device_manager.poll_async()
        self._list_local()
        self._list_remote()
        self._refresh_captures()
        self._refresh_device_inspector()
        self._run_health_check()
        self._audit_event(
            event_type="system",
            action="manual_refresh",
            status="ok",
            message="Manual refresh triggered",
        )

    def _current_transport(self, serial: str | None) -> str:
        if not serial:
            return ""
        for dev in self._last_devices:
            if dev.serial == serial:
                return dev.transport
        return ""

    def _audit_event(
        self,
        *,
        event_type: str,
        action: str,
        status: str,
        message: str = "",
        payload: dict[str, Any] | None = None,
        serial: str | None = None,
    ) -> None:
        device_serial = serial or (self._selected_serial() or "")
        transport = self._current_transport(device_serial)
        self.audit_module.log_event(
            self._session_id,
            event_type=event_type,
            action=action,
            status=status,
            device_serial=device_serial,
            transport=transport,
            message=message,
            payload=payload or {},
        )
        if hasattr(self, "audit_session_box"):
            # Light refresh only if Reports tab exists.
            self._refresh_audit_events()

    def _refresh_audit_views(self) -> None:
        self._refresh_audit_session_box()
        self._refresh_audit_events()

    def _refresh_audit_session_box(self) -> None:
        if not hasattr(self, "audit_session_box"):
            return
        current = str(self.audit_session_box.currentData() or "")
        sessions = self.audit_module.list_sessions(limit=200)
        self.audit_session_box.blockSignals(True)
        self.audit_session_box.clear()
        for sess in sessions:
            sid = str(sess.get("session_id", ""))
            label = f"{sid} | {sess.get('started_at', '')}"
            self.audit_session_box.addItem(label, sid)
        if self.audit_session_box.count() == 0:
            self.audit_session_box.addItem("Aucune session", "")
        if current:
            idx = self.audit_session_box.findData(current)
            if idx >= 0:
                self.audit_session_box.setCurrentIndex(idx)
        self.audit_session_box.blockSignals(False)

    def _normalize_date_filter(self, raw: str) -> str:
        text = raw.strip()
        if not text:
            return ""
        if re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", text):
            return text
        return ""

    def _refresh_audit_events(self) -> None:
        if not hasattr(self, "audit_table"):
            return
        session_id = str(self.audit_session_box.currentData() or "").strip()
        serial = str(self.audit_device_filter.currentData() or "").strip() if hasattr(self, "audit_device_filter") else ""
        event_type = self.audit_type_filter.currentText() if hasattr(self, "audit_type_filter") else "Tous types"
        event_type = "" if event_type == "Tous types" else event_type
        date_from = self._normalize_date_filter(self.audit_date_from.text() if hasattr(self, "audit_date_from") else "")
        date_to = self._normalize_date_filter(self.audit_date_to.text() if hasattr(self, "audit_date_to") else "")

        events = self.audit_module.list_events(
            session_id=session_id or None,
            device_serial=serial or None,
            event_type=event_type or None,
            date_from=date_from or None,
            date_to=date_to or None,
            limit=int(self.config.get("reports.audit_ui_limit", 2000)),
        )
        self._audit_last_events = events
        self.audit_table.setRowCount(len(events))
        for row, event in enumerate(events):
            self.audit_table.setItem(row, 0, QTableWidgetItem(str(event.get("ts", ""))))
            self.audit_table.setItem(row, 1, QTableWidgetItem(str(event.get("device_serial", ""))))
            self.audit_table.setItem(row, 2, QTableWidgetItem(str(event.get("event_type", ""))))
            self.audit_table.setItem(row, 3, QTableWidgetItem(str(event.get("action", ""))))
            status_item = QTableWidgetItem(str(event.get("status", "")))
            st = str(event.get("status", "")).lower()
            if st in {"error", "failed"}:
                status_item.setForeground(QColor("#fca5a5"))
            elif st in {"warning"}:
                status_item.setForeground(QColor("#fcd34d"))
            elif st in {"ok", "success"}:
                status_item.setForeground(QColor("#86efac"))
            self.audit_table.setItem(row, 4, status_item)
            self.audit_table.setItem(row, 5, QTableWidgetItem(str(event.get("message", ""))))

        if hasattr(self, "audit_device_filter"):
            current_dev = str(self.audit_device_filter.currentData() or "")
            serials = sorted({str(e.get("device_serial", "")).strip() for e in events if str(e.get("device_serial", "")).strip()})
            self.audit_device_filter.blockSignals(True)
            self.audit_device_filter.clear()
            self.audit_device_filter.addItem("Tous devices", "")
            for s in serials:
                self.audit_device_filter.addItem(s, s)
            if current_dev:
                idx = self.audit_device_filter.findData(current_dev)
                if idx >= 0:
                    self.audit_device_filter.setCurrentIndex(idx)
            self.audit_device_filter.blockSignals(False)

        if not events:
            self.audit_payload_text.setPlainText("Aucun evenement pour les filtres courants.")

    def _on_audit_row_selected(self) -> None:
        if not hasattr(self, "audit_table"):
            return
        row = self.audit_table.currentRow()
        if row < 0 or row >= len(self._audit_last_events):
            return
        event = self._audit_last_events[row]
        payload = event.get("payload", {})
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        self.audit_payload_text.setPlainText(text if text else "{}")

    def _export_selected_session_json(self) -> None:
        session_id = str(self.audit_session_box.currentData() or "").strip()
        if not session_id:
            Toast(self, "Aucune session selectionnee")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export session JSON",
            str(self.base_dir / "reports" / f"{session_id}.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        self.audit_module.export_session_json(session_id, Path(path))
        Toast(self, "Session exportee (JSON)")

    def _export_selected_session_html(self) -> None:
        session_id = str(self.audit_session_box.currentData() or "").strip()
        if not session_id:
            Toast(self, "Aucune session selectionnee")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export session HTML",
            str(self.base_dir / "reports" / f"{session_id}.html"),
            "HTML (*.html)",
        )
        if not path:
            return
        self.audit_module.export_session_html(session_id, Path(path))
        Toast(self, "Session exportee (HTML)")

    def _capture_device_snapshot(self) -> None:
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        device = self._current_device_info()
        snapshot = self.snapshot_module.capture_snapshot(serial, device)
        self._snapshot_last_captured_file = str(snapshot.get("file", ""))
        self._refresh_snapshot_boxes()
        self._audit_event(
            event_type="snapshot",
            action="capture_snapshot",
            status="ok",
            message="Snapshot captured",
            payload={"file": self._snapshot_last_captured_file},
            serial=serial,
        )
        Toast(self, f"Snapshot capture: {Path(self._snapshot_last_captured_file).name}")

    def _refresh_snapshot_boxes(self) -> None:
        if not hasattr(self, "snapshot_a_box"):
            return
        files = self.snapshot_module.list_snapshots()
        names = [p.name for p in files]
        map_paths = {p.name: str(p) for p in files}
        current_a = self.snapshot_a_box.currentText().strip()
        current_b = self.snapshot_b_box.currentText().strip()
        self.snapshot_a_box.blockSignals(True)
        self.snapshot_b_box.blockSignals(True)
        self.snapshot_a_box.clear()
        self.snapshot_b_box.clear()
        self.snapshot_a_box.addItems(names)
        self.snapshot_b_box.addItems(names)
        if current_a:
            idx = self.snapshot_a_box.findText(current_a)
            if idx >= 0:
                self.snapshot_a_box.setCurrentIndex(idx)
        if current_b:
            idx = self.snapshot_b_box.findText(current_b)
            if idx >= 0:
                self.snapshot_b_box.setCurrentIndex(idx)
        self.snapshot_a_box.blockSignals(False)
        self.snapshot_b_box.blockSignals(False)
        self._snapshot_name_to_path = map_paths

    def _compare_selected_snapshots(self) -> None:
        name_a = self.snapshot_a_box.currentText().strip() if hasattr(self, "snapshot_a_box") else ""
        name_b = self.snapshot_b_box.currentText().strip() if hasattr(self, "snapshot_b_box") else ""
        if not name_a or not name_b:
            Toast(self, "Selectionne snapshot A et B")
            return
        if name_a == name_b:
            Toast(self, "Choisis deux snapshots differents")
            return
        path_a = Path(self._snapshot_name_to_path.get(name_a, ""))
        path_b = Path(self._snapshot_name_to_path.get(name_b, ""))
        if not path_a.exists() or not path_b.exists():
            Toast(self, "Fichiers snapshot introuvables")
            return
        snap_a = self.snapshot_module.load_snapshot(path_a)
        snap_b = self.snapshot_module.load_snapshot(path_b)
        # Compare oldest -> newest by capture date.
        older, newer = (snap_a, snap_b)
        if str(snap_a.get("captured_at", "")) > str(snap_b.get("captured_at", "")):
            older, newer = (snap_b, snap_a)
        diff = self.snapshot_module.compare(older, newer)
        self._snapshot_diff = diff
        self._render_snapshot_diff(diff)
        self._audit_event(
            event_type="snapshot",
            action="compare_snapshots",
            status="ok",
            message="Snapshots compared",
            payload={"snapshot_a": name_a, "snapshot_b": name_b, "summary": diff.get("summary", {})},
            serial=self._selected_serial(),
        )

    def _render_snapshot_diff(self, diff: dict[str, Any]) -> None:
        summary = diff.get("summary", {})
        packages = diff.get("packages", {})
        props = diff.get("system_properties", {})
        device_changes = diff.get("device_changes", {})
        lines = [
            f"From: {diff.get('from', {}).get('captured_at', 'n/a')} ({diff.get('from', {}).get('serial', '')})",
            f"To:   {diff.get('to', {}).get('captured_at', 'n/a')} ({diff.get('to', {}).get('serial', '')})",
            "",
            f"Summary: {json.dumps(summary, ensure_ascii=False)}",
            "",
            f"Packages added: {len(packages.get('added', []))}",
            f"Packages removed: {len(packages.get('removed', []))}",
            "",
        ]
        if packages.get("added"):
            lines.append("Added:")
            lines.extend(f"+ {p}" for p in packages.get("added", [])[:60])
            lines.append("")
        if packages.get("removed"):
            lines.append("Removed:")
            lines.extend(f"- {p}" for p in packages.get("removed", [])[:60])
            lines.append("")
        if device_changes:
            lines.append("Device changes:")
            lines.append(json.dumps(device_changes, indent=2, ensure_ascii=False))
            lines.append("")
        if props:
            lines.append(f"System properties changed: {len(props)}")
            lines.append(json.dumps(props, indent=2, ensure_ascii=False)[:6000])
        self.snapshot_diff_text.setPlainText("\n".join(lines))

    def _export_snapshot_diff_json(self) -> None:
        if not self._snapshot_diff:
            Toast(self, "Aucun diff a exporter")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export diff snapshots JSON",
            str(self.base_dir / "reports" / f"snapshot_diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        self.snapshot_module.export_diff_json(self._snapshot_diff, Path(path))
        Toast(self, "Diff snapshots exporte (JSON)")

    def _export_snapshot_diff_html(self) -> None:
        if not self._snapshot_diff:
            Toast(self, "Aucun diff a exporter")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export diff snapshots HTML",
            str(self.base_dir / "reports" / f"snapshot_diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"),
            "HTML (*.html)",
        )
        if not path:
            return
        self.snapshot_module.export_diff_html(self._snapshot_diff, Path(path))
        Toast(self, "Diff snapshots exporte (HTML)")

    def _refresh_profile_box(self) -> None:
        if not hasattr(self, "profile_box"):
            return
        current = str(self.profile_box.currentData() or "")
        profiles = self.profiles_module.list_profiles()
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        self.profile_box.addItem("Profil: aucun", "")
        for profile in profiles:
            label = f"{profile.alias} [{profile.serial}]"
            self.profile_box.addItem(label, profile.profile_id)
        if current:
            idx = self.profile_box.findData(current)
            if idx >= 0:
                self.profile_box.setCurrentIndex(idx)
        self.profile_box.blockSignals(False)

    def _selected_profile(self) -> DeviceProfile | None:
        profile_id = str(self.profile_box.currentData() or "").strip() if hasattr(self, "profile_box") else ""
        if not profile_id:
            return None
        for profile in self.profiles_module.list_profiles():
            if profile.profile_id == profile_id:
                return profile
        return None

    def _profile_selection_changed(self, _index: int) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        self.statusBar().showMessage(f"Profil selectionne: {profile.alias}")

    def _save_device_profile(self) -> None:
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        current = self.profiles_module.find_match(serial)
        default_alias = current.alias if current else (self._current_device_info().model if self._current_device_info() else serial)
        alias, ok = QInputDialog.getText(self, "Sauver profil appareil", "Alias du profil", text=default_alias)
        if not ok or not alias.strip():
            return
        tags_raw, _ = QInputDialog.getText(self, "Tags profil", "Tags (optionnel, separes par virgule)")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
        remote = self.remote_path.text().strip() if hasattr(self, "remote_path") else ""
        local = self.local_path.text().strip() if hasattr(self, "local_path") else ""
        wifi_endpoint = serial if ":" in serial else ""
        profile = DeviceProfile(
            profile_id=current.profile_id if current is not None else "",
            alias=alias.strip(),
            serial=serial,
            wifi_endpoint=wifi_endpoint,
            favorite_local_path=local,
            favorite_remote_path=remote,
            last_actions=[f"saved:{datetime.now().strftime('%H:%M:%S')}"],
            favorite_commands=sorted(self._favorite_commands),
            ui_theme=str(self.theme_box.currentText()),
            ui_density=str(self.density_box.currentText()),
            language=str(self.lang_box.currentText()),
            tags=tags,
        )
        saved = self.profiles_module.save_profile(profile)
        self._refresh_profile_box()
        idx = self.profile_box.findData(saved.profile_id)
        if idx >= 0:
            self.profile_box.setCurrentIndex(idx)
        Toast(self, f"Profil sauve: {saved.alias}")

    def _load_selected_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            Toast(self, "Selectionne un profil")
            return
        self._apply_profile(profile)
        Toast(self, f"Profil charge: {profile.alias}")

    def _apply_profile(self, profile: DeviceProfile) -> None:
        self._profiles_suppress_autoload = True
        try:
            if hasattr(self, "device_box"):
                idx = self.device_box.findData(profile.serial)
                if idx >= 0:
                    self.device_box.setCurrentIndex(idx)
            if profile.favorite_local_path and hasattr(self, "local_path"):
                self.local_path.setText(profile.favorite_local_path)
            if profile.favorite_remote_path and hasattr(self, "remote_path"):
                self.remote_path.setText(profile.favorite_remote_path)
            if profile.ui_theme and hasattr(self, "theme_box"):
                self.theme_box.setCurrentText(profile.ui_theme)
            if profile.ui_density and hasattr(self, "density_box"):
                self.density_box.setCurrentText(profile.ui_density)
            if profile.language and hasattr(self, "lang_box"):
                self.lang_box.setCurrentText(profile.language)
            if profile.favorite_commands:
                self._favorite_commands = set(profile.favorite_commands)
                self._save_favorite_commands()
                self._rebuild_command_catalog()
            self._profiles_last_loaded_serial = profile.serial
            if hasattr(self, "local_path"):
                self._list_local()
            if hasattr(self, "remote_path"):
                self._list_remote()
        finally:
            self._profiles_suppress_autoload = False

    def _delete_selected_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        reply = QMessageBox.question(self, "Suppression profil", f"Supprimer le profil '{profile.alias}' ?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.profiles_module.delete_profile(profile.profile_id)
        self._refresh_profile_box()
        Toast(self, "Profil supprime")

    def _autoload_profile_for_device(self, serial: str) -> None:
        if self._profiles_suppress_autoload:
            return
        if serial == self._profiles_last_loaded_serial:
            return
        if not bool(self.config.get("profiles.auto_load", True)):
            return
        profile = self.profiles_module.find_match(serial)
        if profile is None:
            return
        idx = self.profile_box.findData(profile.profile_id) if hasattr(self, "profile_box") else -1
        if idx >= 0:
            self.profile_box.setCurrentIndex(idx)
        self._apply_profile(profile)
        self.statusBar().showMessage(f"Profil auto-charge: {profile.alias}")

    def _refresh_device_inspector(self) -> None:
        serial = self._selected_serial()
        if not serial:
            if hasattr(self, "inspector_text"):
                self.inspector_text.setPlainText("Aucun appareil actif.")
            return
        self._run_in_worker("device_inspector", lambda: self.inspector_module.inspect(serial, self._current_device_info()), {"serial": serial})

    def _render_device_inspector(self, info: dict[str, str]) -> None:
        self._device_inspector_data = info
        lines = [
            f"Marque: {info.get('brand', 'n/a')}",
            f"Constructeur: {info.get('manufacturer', 'n/a')}",
            f"Modele: {info.get('model', 'n/a')}",
            f"Serial: {info.get('serial', 'n/a')}",
            f"Transport: {info.get('transport', 'n/a')}",
            f"Etat ADB: {info.get('state', 'n/a')}",
            f"Android: {info.get('android_version', 'n/a')} (SDK {info.get('sdk', 'n/a')})",
            f"Batterie: {info.get('battery_level', 'n/a')} (status {info.get('battery_status', 'n/a')})",
            f"Stockage: {info.get('storage_available', 'n/a')} libres / {info.get('storage_total', 'n/a')}",
            f"ABI CPU: {info.get('abi', 'n/a')}",
            f"ABI list: {info.get('abi_list', 'n/a')}",
            f"IP locale: {info.get('ip_local', 'n/a')}",
            f"Ecran: {info.get('screen_resolution', 'n/a')} | densite {info.get('screen_density', 'n/a')}",
            f"Root: {info.get('root', 'n/a')}",
            f"Debug: {info.get('debug_status', 'n/a')} (ro.debuggable={info.get('debuggable', 'n/a')})",
            f"Dernier refresh: {info.get('last_refresh', 'n/a')}",
        ]
        self.inspector_text.setPlainText("\n".join(lines))

    def _export_device_inspector(self) -> None:
        if not self._device_inspector_data:
            Toast(self, "Aucune donnee inspector a exporter")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter Device Inspector",
            str(self.base_dir / f"device_inspector_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        Path(path).write_text(json.dumps(self._device_inspector_data, indent=2, ensure_ascii=False), encoding="utf-8")
        Toast(self, "Inspector exporte")

    def _run_health_check(self) -> None:
        serial = self._selected_serial()
        self._run_in_worker("health_check", lambda: self.health_module.run(self._last_devices, serial), {"serial": serial or ""})

    def _render_health_report(self, report: dict) -> None:
        self._health_report = report
        status = str(report.get("status", "n/a"))
        self.health_status_badge.setText(f"Global: {status}")
        parts = [str(report.get("summary", "")), ""]
        for check in report.get("checks", []):
            if not isinstance(check, dict):
                continue
            parts.append(f"[{check.get('status', 'n/a')}] {check.get('name', 'check')}: {check.get('message', '')}")
            remediation = str(check.get("remediation", "")).strip()
            if remediation:
                parts.append(f"  -> Remediation: {remediation}")
        self.health_text.setPlainText("\n".join(parts))

    def _export_health_report(self) -> None:
        if not self._health_report:
            Toast(self, "Aucun rapport health check")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter Health Check",
            str(self.base_dir / f"adb_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        Path(path).write_text(json.dumps(self._health_report, indent=2, ensure_ascii=False), encoding="utf-8")
        Toast(self, "Health check exporte")

    def _run_in_worker(self, task: str, fn, context: dict | None = None) -> None:
        self.statusBar().showMessage(f"Operation en cours: {task}...")

        def _done(future) -> None:
            try:
                value = future.result()
                payload = {"task": task, "ok": True, "value": value, "context": context or {}, "error": ""}
            except Exception as exc:  # noqa: BLE001
                payload = {"task": task, "ok": False, "value": None, "context": context or {}, "error": str(exc)}
            self.bridge.command_done.emit(("worker", payload))

        self.adb.executor.submit(fn).add_done_callback(_done)

    def _handle_worker_result(self, payload: dict) -> None:
        task = str(payload.get("task", "unknown"))
        ok = bool(payload.get("ok", False))
        value = payload.get("value")
        context = payload.get("context", {})
        error = str(payload.get("error", ""))

        if not ok:
            self._audit_event(
                event_type="error",
                action=task,
                status="error",
                message=error or f"{task} failed",
                payload={"context": context},
                serial=str(context.get("serial", "") if isinstance(context, dict) else ""),
            )
            Toast(self, f"{task}: {error}")
            return

        if task == "apps_list":
            apps = value if isinstance(value, list) else []
            self._populate_apps_grid(apps)
            self.statusBar().showMessage(f"{len(apps)} applications chargees")
            self._audit_event(
                event_type="app",
                action="list_apps",
                status="ok",
                message=f"{len(apps)} apps loaded",
                payload={"count": len(apps), "include_system": bool(context.get("include_system", False))},
                serial=str(context.get("serial", "")),
            )
            return

        if task == "system_info":
            info = value if isinstance(value, dict) else {}
            self._last_system_info = info
            self.system_info_text.setPlainText("\n".join(f"{k}: {v}" for k, v in info.items()))
            self.statusBar().showMessage("Informations systeme rafraichies")
            self._audit_event(
                event_type="system",
                action="system_info",
                status="ok",
                message="System info refreshed",
                payload={"keys": list(info.keys())[:20]},
                serial=str(context.get("serial", "")),
            )
            return

        if task == "system_monitor":
            snap = value if isinstance(value, dict) else {}
            self.system_info_text.setPlainText(
                "=== TOP ===\n" + str(snap.get("top", ""))[:5000] + "\n\n=== MEMINFO ===\n" + str(snap.get("meminfo", ""))[:5000]
            )
            self.statusBar().showMessage("Snapshot monitoring termine")
            self._audit_event(
                event_type="system",
                action="monitor_snapshot",
                status="ok",
                message="System monitor snapshot captured",
                payload={"has_top": bool(snap.get("top")), "has_meminfo": bool(snap.get("meminfo"))},
                serial=str(context.get("serial", "")),
            )
            return

        if task == "device_inspector":
            info = value if isinstance(value, dict) else {}
            self._render_device_inspector({str(k): str(v) for k, v in info.items()})
            self.statusBar().showMessage("Device Inspector rafraichi")
            self._audit_event(
                event_type="device",
                action="device_inspector",
                status="ok",
                message="Device inspector refreshed",
                payload={"serial": info.get("serial", ""), "android": info.get("android_version", "")},
                serial=str(context.get("serial", "")),
            )
            return

        if task == "health_check":
            report = value if isinstance(value, dict) else {}
            self._render_health_report(report)
            self.statusBar().showMessage("ADB Health Check termine")
            self._audit_event(
                event_type="system",
                action="health_check",
                status=str(report.get("status", "ok")).lower(),
                message=str(report.get("summary", "Health check")),
                payload={"target_serial": report.get("target_serial", ""), "checks": len(report.get("checks", []))},
                serial=str(context.get("serial", "")),
            )
            return

        if task == "device_health_checks":
            report = value if isinstance(value, dict) else {}
            self._render_device_health_report(report)
            self.statusBar().showMessage("Device Health Checks termines")
            findings = report.get("findings", []) if isinstance(report, dict) else []
            self._audit_event(
                event_type="system",
                action="device_health_checks",
                status="ok",
                message=str(report.get("summary", "Device health checks"))[:220] if isinstance(report, dict) else "Device health checks",
                payload={"score": report.get("score", 0), "status": report.get("status", ""), "findings": len(findings) if isinstance(findings, list) else 0},
                serial=str(context.get("serial", "")),
            )
            return

        if task == "transfer_queue_execute":
            payload = value if isinstance(value, dict) else {}
            results = payload.get("results", []) if isinstance(payload, dict) else []
            total = int(payload.get("total", len(results))) if isinstance(payload, dict) else len(results)
            self._transfer_running = False
            self.transfer_start_btn.setEnabled(True)
            self.transfer_clear_btn.setEnabled(True)
            ok_count = 0
            partial_count = 0
            err_count = 0
            if isinstance(results, list):
                for rep in results:
                    if not isinstance(rep, dict):
                        continue
                    self._transfer_reports.append(rep)
                    st = str(rep.get("status", "")).lower()
                    if st in {"success", "ok", "dry_run"}:
                        ok_count += 1
                    elif st in {"partial", "warn", "warning"}:
                        partial_count += 1
                    else:
                        err_count += 1
                    task_data = rep.get("task", {})
                    if isinstance(task_data, dict):
                        self._audit_event(
                            event_type="file",
                            action="data_transfer",
                            status="ok" if st in {"success", "ok", "dry_run"} else ("warning" if st in {"partial", "warn", "warning"} else "error"),
                            message=f"{task_data.get('source', '')} -> {task_data.get('destination', '')} [{st}]",
                            payload={
                                "task_id": rep.get("task_id", ""),
                                "direction": task_data.get("direction", ""),
                                "preset": task_data.get("preset", ""),
                                "estimate": rep.get("estimate", {}),
                                "verification": rep.get("verification", {}),
                                "returncode": rep.get("returncode", 0),
                            },
                            serial=str(task_data.get("serial", context.get("serial", ""))),
                        )
            self.transfer_progress.setMaximum(max(1, total))
            self.transfer_progress.setValue(total)
            self.transfer_log.append(f"[done] total={total} ok={ok_count} partial={partial_count} error={err_count}")
            Toast(self, f"Transfers termines: ok={ok_count} partial={partial_count} err={err_count}")
            return

        if task in {"push_file", "pull_file", "install_apk", "uninstall_app", "clear_app_data", "full_backup", "selective_backup", "restore_backup"}:
            result = value if isinstance(value, CommandResult) else None
            if result is None:
                Toast(self, f"{task}: resultat invalide")
                return
            msg = result.stdout or result.stderr or "(aucune sortie)"
            if task in {"push_file", "pull_file", "full_backup", "selective_backup", "restore_backup"}:
                self.backup_output.append(f"{task.upper()} {'OK' if result.ok else 'ERR'}\n{msg}\n")
            else:
                Toast(self, msg if not result.ok else f"{task} termine")
            if task == "uninstall_app" and result.ok:
                self._list_apps()
            event_type = "file" if task in {"push_file", "pull_file"} else ("app" if task in {"install_apk", "uninstall_app", "clear_app_data"} else "system")
            self._audit_event(
                event_type=event_type,
                action=task,
                status="ok" if result.ok else "error",
                message=msg[:200],
                payload={"returncode": result.returncode, "context": context},
                serial=str(context.get("serial", "")),
            )
            return

        if task == "batch_run":
            self._batch_running = False
            self._batch_paused = False
            self.batch_run_btn.setEnabled(True)
            self.batch_pause_btn.setEnabled(False)
            self.batch_pause_btn.setText("Pause")
            self.batch_stop_btn.setEnabled(False)
            payload = value if isinstance(value, dict) else {}
            results = payload.get("results", [])
            canceled = bool(payload.get("canceled", False))
            executed = int(payload.get("executed", 0))
            requested = int(payload.get("requested", 0))
            workers = int(payload.get("workers", 1))
            retries = int(payload.get("retries", 0))
            total_duration = float(payload.get("total_duration_s", 0.0))
            self._batch_results = results if isinstance(results, list) else []
            self.batch_progress.setMaximum(max(1, requested))
            self.batch_progress.setValue(executed)
            self.batch_progress_label.setText(f"Termine: {executed}/{requested}")
            self.batch_output.append(
                f"[BATCH] Termine: {executed}/{requested} executees"
                + (" (annule)" if canceled else "")
            )
            self.batch_output.append(f"[BATCH] workers={workers} retries={retries}")
            ok_count = sum(1 for r in self._batch_results if isinstance(r, dict) and bool(r.get("ok")))
            err_count = max(0, executed - ok_count)
            self.batch_output.append(f"[BATCH] OK={ok_count} | ERR={err_count}")
            total_attempts = sum(int(r.get("attempt_count", 0)) for r in self._batch_results if isinstance(r, dict))
            self.batch_output.append(f"[BATCH] Tentatives totales={total_attempts}")
            self.batch_output.append(f"[BATCH] Duree cumulée={total_duration:.3f}s")
            for row in self._batch_results[-15:]:
                if not isinstance(row, dict):
                    continue
                state = "OK" if row.get("ok") else "ERR"
                cmd = str(row.get("command", ""))
                out = str(row.get("stdout", "") or row.get("stderr", ""))[:160]
                attempts = int(row.get("attempt_count", 0))
                duration = float(row.get("duration_s", 0.0))
                self.batch_output.append(f"  [{state}] ({attempts} tentative(s), {duration:.3f}s) {cmd}\n    {out}")
            Toast(self, "Batch termine")
            self._audit_event(
                event_type="batch",
                action="batch_run",
                status="ok" if err_count == 0 else "warning",
                message=f"Batch {executed}/{requested} done (err={err_count})",
                payload={
                    "executed": executed,
                    "requested": requested,
                    "ok": ok_count,
                    "err": err_count,
                    "workers": workers,
                    "retries": retries,
                    "duration_s": total_duration,
                },
                serial=str(context.get("serial", "")),
            )
            return

        self.statusBar().showMessage(f"{task}: termine")

    def _wifi_connect_dialog(self) -> None:
        ip_text, ok = QInputDialog.getText(self, "Connexion WiFi", "Adresse IP appareil (ex: 192.168.1.50)")
        if not ok or not ip_text.strip():
            return
        ip_text = ip_text.strip()
        port = 5555
        if ":" in ip_text:
            host, port_text = ip_text.rsplit(":", 1)
            ip_text = host.strip()
            if port_text.isdigit():
                port = int(port_text)
        try:
            ipaddress.ip_address(ip_text)
        except ValueError:
            Toast(self, "IP invalide")
            return

        ok = self.device_manager.connect_wifi(ip_text, port=port)
        if ok:
            Toast(self, f"Connecte a {ip_text}:{port}")
            self.device_manager.poll_async()
            self._audit_event(
                event_type="device",
                action="wifi_connect",
                status="ok",
                message=f"Connected to {ip_text}:{port}",
                payload={"ip": ip_text, "port": port},
                serial=f"{ip_text}:{port}",
            )
        else:
            Toast(self, f"Echec connexion {ip_text}:{port}")
            self._audit_event(
                event_type="error",
                action="wifi_connect",
                status="error",
                message=f"Failed connect {ip_text}:{port}",
                payload={"ip": ip_text, "port": port},
                serial=f"{ip_text}:{port}",
            )

    def _wifi_pair_dialog(self) -> None:
        host_port, ok = QInputDialog.getText(
            self,
            "Pairing WiFi ADB",
            "Adresse pairing (depuis le telephone)\nFormat: IP:PORT (ex: 192.168.1.50:37199)",
        )
        if not ok or not host_port.strip():
            return
        host_port = host_port.strip()
        if ":" not in host_port:
            Toast(self, "Format invalide. Exemple: 192.168.1.50:37199")
            return
        host, port_text = host_port.rsplit(":", 1)
        host = host.strip()
        if not port_text.isdigit():
            Toast(self, "Port pairing invalide")
            return
        try:
            ipaddress.ip_address(host)
        except ValueError:
            Toast(self, "IP pairing invalide")
            return

        pair_code, ok = QInputDialog.getText(
            self,
            "Code de pairing",
            "Code de pairing (6 chiffres) affiche sur le telephone",
        )
        if not ok or not pair_code.strip():
            return
        pair_code = pair_code.strip()
        if not re.fullmatch(r"[0-9]{6}", pair_code):
            Toast(self, "Code pairing invalide (attendu: 6 chiffres)")
            return

        self.statusBar().showMessage(f"Pairing en cours vers {host_port}...")
        result = self.adb.run(["pair", host_port, pair_code], timeout=30)
        if not result.ok:
            msg = result.stderr or result.stdout or "Echec pairing"
            QMessageBox.warning(self, "Pairing WiFi", f"Pairing echoue:\n{msg}")
            self._audit_event(
                event_type="error",
                action="wifi_pair",
                status="error",
                message=msg[:200],
                payload={"host_port": host_port},
                serial=host_port,
            )
            return

        connect_targets = self._discover_tls_connect_targets(prefer_host=host)
        if connect_targets:
            target = connect_targets[0]
            connect_result = self.adb.run(["connect", target], timeout=20)
            if connect_result.ok:
                Toast(self, f"Pairing OK + connecte a {target}")
                self._audit_event(
                    event_type="device",
                    action="wifi_pair_connect",
                    status="ok",
                    message=f"Pairing/connect OK: {target}",
                    payload={"pair": host_port, "connect_target": target},
                    serial=target,
                )
            else:
                Toast(self, f"Pairing OK mais echec connect {target}")
                self._audit_event(
                    event_type="error",
                    action="wifi_pair_connect",
                    status="error",
                    message=f"Pairing OK but connect failed: {target}",
                    payload={"pair": host_port, "connect_target": target},
                    serial=target,
                )
        else:
            Toast(self, "Pairing OK. Lance ensuite 'Connecter WiFi' avec l'IP:PORT de debug.")
            self._audit_event(
                event_type="device",
                action="wifi_pair",
                status="ok",
                message="Pairing OK without auto-connect target",
                payload={"pair": host_port},
                serial=host_port,
            )
        self.device_manager.poll_async()

    def _wifi_pair_qr_dialog(self) -> None:
        tool = str(self.config.get("app.adb_qr_tool", "adb-connect-qr")).strip() or "adb-connect-qr"
        fallback_venv = self.base_dir / ".venv" / "bin" / "adb-connect-qr"
        resolved = shutil.which(tool) or (tool if Path(tool).exists() else "") or (str(fallback_venv) if fallback_venv.exists() else "")
        if not resolved:
            QMessageBox.information(
                self,
                "Pairing QR",
                "Le helper QR n'est pas installe.\n\n"
                "Installe-le dans ton environnement:\n"
                "pip install adb-connect-qr\n\n"
                "Puis relance l'application et clique 'Pairing QR'.",
            )
            return
        if self.qr_pair_process is not None:
            Toast(self, "Un pairing QR est deja en cours")
            return

        self.config.set("app.adb_qr_tool", tool)
        self.config.save()
        self._qr_pair_buffer = ""
        self._qr_service_name = ""
        self._qr_password = ""
        self._close_qr_popup()

        proc = QProcess(self)
        self.qr_pair_process = proc
        proc.setProgram(resolved)
        proc.setArguments([])
        proc.readyReadStandardOutput.connect(self._consume_qr_pair_stdout)
        proc.readyReadStandardError.connect(self._consume_qr_pair_stderr)
        proc.finished.connect(self._on_qr_pair_finished)
        proc.start()

        self.statusBar().showMessage("Pairing QR: en cours (scanne le QR sur ton telephone)")
        if hasattr(self, "remote_log_output"):
            self.remote_log_output.append("[pair-qr] start")
            self.remote_log_output.append("Scanne le QR code graphique qui s'ouvre.")

    def _close_qr_popup(self) -> None:
        if self._qr_popup is not None:
            self._qr_popup.close()
            self._qr_popup.deleteLater()
            self._qr_popup = None

    def _qr_payload(self, service_name: str, password: str) -> str:
        return f"WIFI:T:ADB;S:{service_name};P:{password};;"

    def _render_qr_pixmap(self, payload: str, scale: int = 8, border: int = 4) -> QPixmap | None:
        try:
            import qrcode
        except Exception:  # noqa: BLE001
            return None
        qr = qrcode.QRCode(border=border)
        qr.add_data(payload)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        if not matrix:
            return None
        h = len(matrix)
        w = len(matrix[0])
        img = QImage(w * scale, h * scale, QImage.Format.Format_RGB32)
        white = QColor("#ffffff").rgb()
        black = QColor("#000000").rgb()
        for y, row in enumerate(matrix):
            for x, cell in enumerate(row):
                color = black if cell else white
                x0 = x * scale
                y0 = y * scale
                for yy in range(y0, y0 + scale):
                    for xx in range(x0, x0 + scale):
                        img.setPixel(xx, yy, color)
        return QPixmap.fromImage(img)

    def _show_qr_popup(self, service_name: str, password: str) -> None:
        payload = self._qr_payload(service_name, password)
        pix = self._render_qr_pixmap(payload, scale=8, border=4)
        if pix is None:
            return
        self._close_qr_popup()
        dialog = QDialog(self)
        dialog.setWindowTitle("QR Pairing ADB")
        dialog.setModal(False)
        dialog.resize(420, 500)
        lay = QVBoxLayout(dialog)
        info = QLabel("Scanne ce QR sur le telephone:\nOptions developpeur > Debogage sans fil > Associer via QR")
        info.setWordWrap(True)
        lay.addWidget(info)
        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setPixmap(pix.scaled(360, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
        lay.addWidget(qr_label)
        lay.addWidget(QLabel(f"Service: {service_name}"))
        lay.addWidget(QLabel(f"Password: {password}"))
        close_btn = QPushButton("Fermer")
        close_btn.setObjectName("ghostBtn")
        close_btn.clicked.connect(dialog.close)
        lay.addWidget(close_btn)
        dialog.show()
        self._qr_popup = dialog

    def _consume_qr_pair_stdout(self) -> None:
        if self.qr_pair_process is None:
            return
        data = bytes(self.qr_pair_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self._qr_pair_buffer += data
            if not self._qr_service_name:
                m = re.search(r"Service Name:\s*([A-Za-z0-9._-]+)", self._qr_pair_buffer)
                if m:
                    self._qr_service_name = m.group(1).strip()
            if not self._qr_password:
                m = re.search(r"Password:\s*([A-Za-z0-9._-]+)", self._qr_pair_buffer)
                if m:
                    self._qr_password = m.group(1).strip()
            if self._qr_service_name and self._qr_password and self._qr_popup is None:
                self._show_qr_popup(self._qr_service_name, self._qr_password)
        if data.strip() and hasattr(self, "remote_log_output"):
            self.remote_log_output.append(data.rstrip())

    def _consume_qr_pair_stderr(self) -> None:
        if self.qr_pair_process is None:
            return
        data = bytes(self.qr_pair_process.readAllStandardError()).decode("utf-8", errors="replace")
        if data.strip() and hasattr(self, "remote_log_output"):
            self.remote_log_output.append(data.rstrip())

    def _on_qr_pair_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        self.qr_pair_process = None
        self.statusBar().showMessage("Pairing QR termine")
        self._close_qr_popup()
        if hasattr(self, "remote_log_output"):
            self.remote_log_output.append(f"[pair-qr] termine (code={code})")
        self.device_manager.poll_async()

    def _discover_tls_connect_targets(self, prefer_host: str | None = None) -> list[str]:
        result = self.adb.run(["mdns", "services"], timeout=12)
        if not result.ok or not result.stdout:
            return []
        targets: list[str] = []
        for line in result.stdout.splitlines():
            text = line.strip()
            if not text or "_adb-tls-connect._tcp" not in text:
                continue
            match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d+)", text)
            if not match:
                continue
            host = match.group(1)
            port = match.group(2)
            targets.append(f"{host}:{port}")
        if prefer_host:
            preferred = [t for t in targets if t.startswith(f"{prefer_host}:")]
            others = [t for t in targets if not t.startswith(f"{prefer_host}:")]
            targets = preferred + others
        # unique preserving order
        deduped: list[str] = []
        seen: set[str] = set()
        for t in targets:
            if t in seen:
                continue
            seen.add(t)
            deduped.append(t)
        return deduped

    def _scan_wifi_dialog(self) -> None:
        subnet, ok = QInputDialog.getText(self, "Scan WiFi ADB", "Prefixe subnet (ex: 192.168.1.)")
        if not ok or not subnet.strip():
            return
        subnet = subnet.strip()
        if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.$", subnet):
            Toast(self, "Format attendu: 192.168.1.")
            return

        self.statusBar().showMessage(f"Scan en cours sur {subnet}0/24...")

        def work() -> None:
            found = self.device_manager.scan_for_wifi(subnet)
            self.bridge.command_done.emit(("wifi_scan", found))

        self.device_manager.pool.submit(work)

    def _list_local(self) -> None:
        path = self._normalize_local_path(self.local_path.text().strip() or ".")
        if not path.exists():
            Toast(self, f"Chemin invalide: {path}")
            return
        if not path.is_dir():
            Toast(self, "Le chemin local doit etre un dossier")
            return
        self.local_path.setText(str(path))
        self.local_list.clear()
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        rows: list[Path] = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        for child in rows:
            icon = folder_icon if child.is_dir() else file_icon
            item = QListWidgetItem(icon, child.name)
            item.setData(Qt.ItemDataRole.UserRole, str(child))
            item.setData(Qt.ItemDataRole.UserRole + 2, child.is_dir())
            item.setToolTip(str(child))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.local_list.addItem(item)

    def _normalize_local_path(self, raw_path: str) -> Path:
        raw = raw_path.strip() or "."
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = (self.base_dir / p).resolve()
        try:
            return p.resolve()
        except Exception:  # noqa: BLE001
            return p

    def _go_local_home(self) -> None:
        self.local_path.setText(str(Path.home()))
        self._list_local()

    def _go_local_parent(self) -> None:
        current = self._normalize_local_path(self.local_path.text())
        parent = current.parent if current.parent != current else current
        self.local_path.setText(str(parent))
        self._list_local()

    def _open_local_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        is_dir = bool(item.data(Qt.ItemDataRole.UserRole + 2))
        path_text = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not path_text:
            return
        if is_dir:
            self.local_path.setText(path_text)
            self._list_local()

    def _sync_local_to_remote_level(self) -> None:
        local_current = self._normalize_local_path(self.local_path.text())
        if not local_current.exists() or not local_current.is_dir():
            Toast(self, "Chemin local invalide pour synchronisation")
            return
        remote_current = self._normalize_remote_path(self.remote_path.text())
        remote_parent = self._remote_parent_path(remote_current)
        target = self._join_remote_path(remote_parent, local_current.name)
        self.remote_path.setText(target)
        self._list_remote()

    def _sync_remote_to_local_level(self) -> None:
        local_current = self._normalize_local_path(self.local_path.text())
        if not local_current.exists() or not local_current.is_dir():
            Toast(self, "Chemin local invalide pour synchronisation")
            return
        remote_current = self._normalize_remote_path(self.remote_path.text())
        remote_leaf = Path(remote_current).name.strip()
        if not remote_leaf:
            Toast(self, "Impossible de synchroniser depuis la racine distante")
            return
        target = local_current.parent / remote_leaf
        if not target.exists() or not target.is_dir():
            Toast(self, f"Dossier local introuvable: {target}")
            return
        self.local_path.setText(str(target))
        self._list_local()

    def _list_remote(self) -> None:
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil connecte")
            return
        remote_path = self._normalize_remote_path(self.remote_path.text().strip() or "/")
        self.remote_path.setText(remote_path)

        def done(result: CommandResult) -> None:
            self.bridge.command_done.emit(("remote_ls", result))

        self.adb.run_async(["shell", "ls", "-1", "-a", "-p", remote_path], serial=serial, callback=done)

    def _normalize_remote_path(self, value: str) -> str:
        path = value.strip() or "/"
        if not path.startswith("/"):
            path = "/" + path
        path = re.sub(r"/{2,}", "/", path)
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return path or "/"

    def _join_remote_path(self, base: str, name: str) -> str:
        clean_base = self._normalize_remote_path(base)
        clean_name = name.strip().strip("/")
        if not clean_name:
            return clean_base
        if clean_base == "/":
            return f"/{clean_name}"
        return f"{clean_base}/{clean_name}"

    def _remote_parent_path(self, path: str) -> str:
        clean = self._normalize_remote_path(path)
        if clean == "/":
            return "/"
        parts = [p for p in clean.split("/") if p]
        if len(parts) <= 1:
            return "/"
        return "/" + "/".join(parts[:-1])

    def _go_remote_root(self) -> None:
        self.remote_path.setText("/")
        self._list_remote()

    def _go_remote_parent(self) -> None:
        self.remote_path.setText(self._remote_parent_path(self.remote_path.text()))
        self._list_remote()

    def _open_remote_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        is_dir = bool(item.data(Qt.ItemDataRole.UserRole + 2))
        remote_path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if is_dir and remote_path:
            self.remote_path.setText(remote_path)
            self._list_remote()

    def _search_remote(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        base = self.remote_path.text().strip() or "/sdcard"
        pattern = self.remote_search.text().strip()
        if not pattern:
            self._list_remote()
            return
        matches = self.file_module.search_remote(serial, base, pattern)
        self.remote_list.clear()
        file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        for line in matches[:500]:
            remote_full = line.strip()
            if not remote_full:
                continue
            name = Path(remote_full).name or remote_full
            item = QListWidgetItem(file_icon, name)
            item.setData(Qt.ItemDataRole.UserRole, remote_full)
            item.setData(Qt.ItemDataRole.UserRole + 2, False)
            item.setToolTip(remote_full)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.remote_list.addItem(item)
        self.statusBar().showMessage(f"{len(matches)} fichier(s) trouves")

    def _push_file(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Choisir fichier a envoyer")
        if not file_path:
            return
        remote = self.remote_path.text().strip() or "/sdcard"
        self._run_in_worker(
            "push_file",
            lambda: self.file_module.push(serial, Path(file_path), remote),
            {"serial": serial, "file": file_path},
        )

    def _pull_file(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        selected = self.remote_list.currentItem()
        if not selected:
            Toast(self, "Selectionnez un fichier distant")
            return
        is_dir = bool(selected.data(Qt.ItemDataRole.UserRole + 2))
        if is_dir:
            Toast(self, "Selectionnez un fichier (pas un dossier) pour Pull")
            return
        remote_full = str(selected.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not remote_full:
            name = selected.text().strip()
            remote_full = self._join_remote_path(self.remote_path.text(), name)
        name = Path(remote_full).name or "file"
        dest_dir = QFileDialog.getExistingDirectory(self, "Dossier destination")
        if not dest_dir:
            return
        self._run_in_worker(
            "pull_file",
            lambda: self.file_module.pull(serial, remote_full, Path(dest_dir) / name),
            {"serial": serial, "file": remote_full},
        )

    def _list_apps(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        include_system = self.apps_scope.currentIndex() == 1
        for marker in self._app_icon_cache_dir.glob("*.missing"):
            marker.unlink(missing_ok=True)
        self._app_icon_pending.clear()
        self._app_icon_queue.clear()
        self._app_icon_total = 0
        self._app_icon_done = 0
        self._app_icon_success = 0
        self._app_analysis.clear()
        self._app_analysis_queue.clear()
        self._app_analysis_pending.clear()
        self._app_analysis_generation += 1
        self.apps_detail_text.clear()
        self.apps_risk_table.setRowCount(0)
        self.apps_risk_summary.setText("Risque apps: LOW=0 MEDIUM=0 HIGH=0")
        self._run_in_worker(
            "apps_list",
            lambda: self.app_module.list_packages(serial, include_system=include_system),
            {"serial": serial, "include_system": include_system},
        )

    def _display_name_for_package(self, package: str) -> str:
        text = package.strip()
        if not text:
            return "App"
        parts = [p for p in text.split(".") if p]
        label = parts[-1] if parts else text
        label = label.replace("_", " ").replace("-", " ").strip()
        if not label:
            label = text
        if len(label) > 18:
            label = label[:17] + "…"
        return label

    def _selected_app_package(self) -> str:
        item = self.apps_list.currentItem()
        if not item:
            return ""
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, str) and data.strip():
            return data.strip()
        return item.text().strip()

    def _default_app_icon(self) -> QIcon:
        return self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def _populate_apps_grid(self, apps: list[str]) -> None:
        self.apps_list.clear()
        default_icon = self._default_app_icon()
        serial = self._selected_serial()
        self._apps_all_packages = list(apps)
        self._app_icon_generation += 1
        self._app_icon_queue.clear()
        self._app_icon_pending.clear()
        self._app_icon_total = 0
        self._app_icon_done = 0
        self._app_icon_success = 0
        for package in apps:
            item = QListWidgetItem(default_icon, self._display_name_for_package(package))
            item.setData(Qt.ItemDataRole.UserRole, package)
            item.setToolTip(package)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.apps_list.addItem(item)
        if not serial:
            return
        # Charge tous les logos progressivement sans bloquer l'UI.
        for idx in range(self.apps_list.count()):
            row_item = self.apps_list.item(idx)
            if row_item is None:
                continue
            package = str(row_item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if package:
                self._app_icon_queue.append(package)
        self._app_icon_total = len(self._app_icon_queue)
        self._pump_app_icon_queue(serial)
        self._start_app_analysis(serial, apps)
        self._apply_apps_filters()

    def _fetch_all_app_icons(self) -> None:
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        if self.apps_list.count() == 0:
            Toast(self, "Charge d'abord les applications")
            return
        self._app_icon_generation += 1
        for marker in self._app_icon_cache_dir.glob("*.missing"):
            marker.unlink(missing_ok=True)
        self._app_icon_pending.clear()
        self._app_icon_queue.clear()
        self._app_icon_total = 0
        self._app_icon_done = 0
        self._app_icon_success = 0
        for idx in range(self.apps_list.count()):
            item = self.apps_list.item(idx)
            if item is None:
                continue
            package = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if package:
                self._app_icon_queue.append(package)
        self._app_icon_total = len(self._app_icon_queue)
        self.statusBar().showMessage(f"Recuperation icones: 0/{self._app_icon_total}")
        self._pump_app_icon_queue(serial)

    def _pump_app_icon_queue(self, serial: str) -> None:
        if not serial:
            return
        while len(self._app_icon_pending) < self._app_icon_max_pending and self._app_icon_queue:
            package = self._app_icon_queue.pop(0)
            self._queue_app_icon_load(serial, package)

    def _queue_app_icon_load(self, serial: str, package: str) -> None:
        generation = self._app_icon_generation
        key = f"{serial}:{package}"
        if key in self._app_icon_pending:
            return
        self._app_icon_pending.add(key)

        def work() -> dict[str, str]:
            path = self.app_module.fetch_app_icon(serial, package, self._app_icon_cache_dir)
            return {
                "serial": serial,
                "package": package,
                "icon_path": str(path) if path else "",
                "generation": str(generation),
            }

        def done(future) -> None:
            try:
                payload = future.result()
            except Exception:  # noqa: BLE001
                payload = {"serial": serial, "package": package, "icon_path": "", "generation": str(generation)}
            self.bridge.command_done.emit(("app_icon", payload))

        self.adb.executor.submit(work).add_done_callback(done)

    def _update_app_icon(self, package: str, icon_path: str) -> None:
        if not icon_path:
            return
        icon_file = Path(icon_path)
        if not icon_file.exists():
            return
        icon = QIcon(str(icon_file))
        if icon.isNull():
            return
        for i in range(self.apps_list.count()):
            item = self.apps_list.item(i)
            if item is None:
                continue
            if str(item.data(Qt.ItemDataRole.UserRole) or "").strip() == package:
                item.setIcon(icon)
                break

    def _start_app_analysis(self, serial: str | None, packages: list[str]) -> None:
        if not serial:
            return
        self._app_analysis_generation += 1
        self._app_analysis_queue = list(packages)
        self._app_analysis_pending.clear()
        self._pump_app_analysis_queue(serial)

    def _pump_app_analysis_queue(self, serial: str) -> None:
        while len(self._app_analysis_pending) < self._app_analysis_max_pending and self._app_analysis_queue:
            package = self._app_analysis_queue.pop(0)
            self._queue_app_analysis(serial, package)

    def _queue_app_analysis(self, serial: str, package: str) -> None:
        key = f"{serial}:{package}"
        generation = self._app_analysis_generation
        if key in self._app_analysis_pending:
            return
        self._app_analysis_pending.add(key)

        def work() -> dict:
            out = self.app_module.analyze_app(serial, package)
            out["serial"] = serial
            out["package"] = package
            out["generation"] = generation
            return out

        def done(future) -> None:
            try:
                payload = future.result()
            except Exception as exc:  # noqa: BLE001
                payload = {
                    "serial": serial,
                    "package": package,
                    "generation": generation,
                    "error": f"analysis failed: {exc}",
                }
            self.bridge.command_done.emit(("app_risk", payload))

        self.adb.executor.submit(work).add_done_callback(done)

    def _risk_rank(self, risk: str) -> int:
        mapping = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        return mapping.get(risk.upper(), 0)

    def _apply_apps_filters(self) -> None:
        search = self.apps_search.text().strip().lower() if hasattr(self, "apps_search") else ""
        risk_filter = self.apps_risk_filter.currentText() if hasattr(self, "apps_risk_filter") else "Tous risques"

        for i in range(self.apps_list.count()):
            item = self.apps_list.item(i)
            if item is None:
                continue
            package = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            display = item.text().strip().lower()
            analysis = self._app_analysis.get(package, {})
            risk = str(analysis.get("risk", "")).upper()
            match_search = (not search) or (search in package.lower()) or (search in display)
            if risk_filter == "Tous risques":
                match_risk = True
            elif risk_filter == "Sans analyse":
                match_risk = not risk
            else:
                match_risk = risk == risk_filter
            item.setHidden(not (match_search and match_risk))

        self._refresh_apps_risk_table(search=search, risk_filter=risk_filter)

    def _refresh_apps_risk_table(self, search: str = "", risk_filter: str = "Tous risques") -> None:
        rows: list[dict[str, object]] = []
        for package in self._apps_all_packages:
            analysis = self._app_analysis.get(package, {})
            risk = str(analysis.get("risk", "")).upper()
            label = str(analysis.get("label", self._display_name_for_package(package)))
            if search and search not in package.lower() and search not in label.lower():
                continue
            if risk_filter != "Tous risques":
                if risk_filter == "Sans analyse":
                    if risk:
                        continue
                elif risk != risk_filter:
                    continue
            rows.append({
                "package": package,
                "label": label,
                "type": str(analysis.get("type", "n/a")),
                "risk": risk or "n/a",
                "perm_count": int(analysis.get("permission_count", 0) or 0),
                "sensitive_count": len(analysis.get("sensitive_permissions", []) or []),
                "version": str(analysis.get("version", "n/a")),
                "risk_score": int(analysis.get("risk_score", 0) or 0),
            })

        sort_mode = self.apps_sort_box.currentText() if hasattr(self, "apps_sort_box") else "Tri: Nom"
        if "Risque" in sort_mode:
            rows.sort(key=lambda r: (self._risk_rank(str(r["risk"])), int(r["risk_score"]), int(r["perm_count"]), str(r["package"]).lower()), reverse=True)
        elif "Permissions" in sort_mode:
            rows.sort(key=lambda r: (int(r["perm_count"]), int(r["sensitive_count"]), self._risk_rank(str(r["risk"]))), reverse=True)
        else:
            rows.sort(key=lambda r: str(r["package"]).lower())

        self.apps_risk_table.setSortingEnabled(False)
        self.apps_risk_table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            self.apps_risk_table.setItem(row, 0, QTableWidgetItem(str(item["package"])))
            self.apps_risk_table.setItem(row, 1, QTableWidgetItem(str(item["label"])))
            self.apps_risk_table.setItem(row, 2, QTableWidgetItem(str(item["type"])))
            risk_item = QTableWidgetItem(str(item["risk"]))
            risk = str(item["risk"]).upper()
            if risk == "HIGH":
                risk_item.setForeground(QColor("#fca5a5"))
            elif risk == "MEDIUM":
                risk_item.setForeground(QColor("#fcd34d"))
            elif risk == "LOW":
                risk_item.setForeground(QColor("#86efac"))
            self.apps_risk_table.setItem(row, 3, risk_item)
            self.apps_risk_table.setItem(row, 4, QTableWidgetItem(str(item["perm_count"])))
            self.apps_risk_table.setItem(row, 5, QTableWidgetItem(str(item["sensitive_count"])))
            self.apps_risk_table.setItem(row, 6, QTableWidgetItem(str(item["version"])))
        self.apps_risk_table.setSortingEnabled(True)

        low = sum(1 for a in self._app_analysis.values() if str(a.get("risk", "")).upper() == "LOW")
        med = sum(1 for a in self._app_analysis.values() if str(a.get("risk", "")).upper() == "MEDIUM")
        high = sum(1 for a in self._app_analysis.values() if str(a.get("risk", "")).upper() == "HIGH")
        self.apps_risk_summary.setText(f"Risque apps: LOW={low} MEDIUM={med} HIGH={high}")

    def _show_app_analysis(self, package: str) -> None:
        info = self._app_analysis.get(package)
        if not info:
            self.apps_detail_text.setPlainText(f"Analyse en cours pour {package} ...")
            return
        perms = info.get("permissions", []) or []
        sens = info.get("sensitive_permissions", []) or []
        lines = [
            f"Package: {package}",
            f"Label: {info.get('label', self._display_name_for_package(package))}",
            f"Type: {info.get('type', 'n/a')}",
            f"Version: {info.get('version', 'n/a')}",
            f"Install: {info.get('first_install_time', 'n/a')}",
            f"Update: {info.get('last_update_time', 'n/a')}",
            f"Code path: {info.get('code_path', 'n/a')}",
            f"Data size: {info.get('data_size', 'n/a')} | Cache size: {info.get('cache_size', 'n/a')}",
            f"Permissions: {len(perms)} | Sensibles: {len(sens)}",
            f"Risque: {info.get('risk', 'n/a')} (score={info.get('risk_score', 0)})",
        ]
        if sens:
            lines.append("")
            lines.append("Permissions sensibles:")
            lines.extend(f"- {perm}" for perm in sens)
        if info.get("error"):
            lines.append("")
            lines.append(f"Erreur analyse: {info.get('error')}")
        self.apps_detail_text.setPlainText("\n".join(lines))

    def _sync_apps_selection_from_table(self) -> None:
        selected = self.apps_risk_table.selectedItems()
        if not selected:
            return
        package = selected[0].text().strip()
        if not package:
            return
        for i in range(self.apps_list.count()):
            item = self.apps_list.item(i)
            if item is None:
                continue
            if str(item.data(Qt.ItemDataRole.UserRole) or "").strip() == package:
                self.apps_list.setCurrentRow(i)
                break

    def _export_apps_analysis_json(self) -> None:
        serial = self._selected_serial() or ""
        payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "serial": serial,
            "apps_total": len(self._apps_all_packages),
            "apps_analyzed": len(self._app_analysis),
            "analysis": self._app_analysis,
        }
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter analyse apps (JSON)",
            str(self.base_dir / f"apps_risk_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        Toast(self, "Analyse apps exportee (JSON)")

    def _export_apps_analysis_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter analyse apps (CSV)",
            str(self.base_dir / f"apps_risk_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"),
            "CSV (*.csv)",
        )
        if not path:
            return
        rows = []
        for package in self._apps_all_packages:
            info = self._app_analysis.get(package, {})
            rows.append(
                {
                    "package": package,
                    "label": str(info.get("label", self._display_name_for_package(package))),
                    "type": str(info.get("type", "n/a")),
                    "risk": str(info.get("risk", "n/a")),
                    "risk_score": int(info.get("risk_score", 0) or 0),
                    "permission_count": int(info.get("permission_count", 0) or 0),
                    "sensitive_count": len(info.get("sensitive_permissions", []) or []),
                    "version": str(info.get("version", "n/a")),
                    "first_install_time": str(info.get("first_install_time", "n/a")),
                    "last_update_time": str(info.get("last_update_time", "n/a")),
                }
            )
        with Path(path).open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "package",
                    "label",
                    "type",
                    "risk",
                    "risk_score",
                    "permission_count",
                    "sensitive_count",
                    "version",
                    "first_install_time",
                    "last_update_time",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
        Toast(self, "Analyse apps exportee (CSV)")

    def _on_apps_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        serial = self._selected_serial()
        if not serial:
            return
        package = str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
        if package:
            self._queue_app_icon_load(serial, package)
            self._pump_app_icon_queue(serial)
            if package not in self._app_analysis:
                self._queue_app_analysis(serial, package)
                self._pump_app_analysis_queue(serial)
            self._show_app_analysis(package)

    def _install_apk(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        apk, _ = QFileDialog.getOpenFileName(self, "Choisir APK", filter="APK (*.apk)")
        if not apk:
            return
        self._run_in_worker(
            "install_apk",
            lambda: self.app_module.install_apk(serial, Path(apk)),
            {"serial": serial, "apk": apk},
        )

    def _uninstall_app(self) -> None:
        serial = self._selected_serial()
        package = self._selected_app_package()
        if not serial or not package:
            return
        self._run_in_worker(
            "uninstall_app",
            lambda: self.app_module.uninstall_package(serial, package),
            {"serial": serial, "package": package},
        )

    def _clear_app_data(self) -> None:
        serial = self._selected_serial()
        package = self._selected_app_package()
        if not serial or not package:
            return
        self._run_in_worker(
            "clear_app_data",
            lambda: self.app_module.clear_app_data(serial, package),
            {"serial": serial, "package": package},
        )

    def _refresh_system_info(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        self._run_in_worker("system_info", lambda: self.system_module.gather(serial), {"serial": serial})

    def _monitor_system(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        self._run_in_worker("system_monitor", lambda: self.system_module.monitor_snapshot(serial), {"serial": serial})

    def _save_script(self) -> None:
        name = self.script_name.text().strip() or "script_sans_nom"
        steps = [line.strip() for line in self.script_editor.toPlainText().splitlines() if line.strip()]
        if not steps:
            Toast(self, "Script vide")
            return
        self.automation_module.save_script(name, steps)
        self._refresh_script_library()
        Toast(self, f"Script '{name}' enregistre")

    def _run_script(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        steps = [line.strip() for line in self.script_editor.toPlainText().splitlines() if line.strip()]
        if not steps:
            return
        results = self.automation_module.run_script(serial, steps)
        self.script_output.clear()
        err_count = 0
        for cmd, ok, msg in results:
            self.script_output.append(f"[{'OK' if ok else 'ERR'}] {cmd}\n{msg}\n")
            if not ok:
                err_count += 1
        self._audit_event(
            event_type="script",
            action="run_script",
            status="ok" if err_count == 0 else "warning",
            message=f"Script executed with {len(steps)} steps (err={err_count})",
            payload={"steps": len(steps), "errors": err_count},
            serial=serial,
        )

    def _load_script(self) -> None:
        item = self.script_library.currentItem()
        if not item:
            return
        name = item.text()
        for script in self.automation_module.list_scripts():
            if script.get("name") == name:
                self.script_name.setText(name)
                self.script_editor.setPlainText("\n".join(script.get("steps", [])))
                self.script_editor.highlight_keywords()
                break

    def _refresh_script_library(self) -> None:
        self.script_library.clear()
        for script in self.automation_module.list_scripts():
            self.script_library.addItem(script.get("name", "sans_nom"))

    def _run_terminal_command(self, command: str) -> None:
        serial = self._selected_serial()
        self.terminal.append_line(f"$ adb {'-s ' + serial if serial else ''} {command}")

        def done(result: CommandResult) -> None:
            self.bridge.command_done.emit(("terminal", result))

        self.adb.run_async(command, serial=serial, callback=done)

    def _run_catalog_item(self) -> None:
        self._execute_selected_command()

    def _copy_selected_command(self) -> None:
        item = self.command_catalog.currentItem()
        if item is None:
            Toast(self, "Selectionnez une commande")
            return
        meta = item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(meta, dict):
            return
        command = self._prepare_command_from_meta(meta, allow_cancel=True)
        if not command:
            return
        QApplication.clipboard().setText(f"adb {command}")
        Toast(self, "Commande copiee dans le presse-papiers")

    def _execute_selected_command(self) -> None:
        item = self.command_catalog.currentItem()
        if item is None:
            Toast(self, "Selectionnez une commande")
            return
        meta = item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(meta, dict):
            return
        command = self._prepare_command_from_meta(meta, allow_cancel=True)
        if not command:
            return
        if self._should_confirm_command(command, str(meta.get("root_state", ""))):
            if self._is_critical_command(command):
                check, ok = QInputDialog.getText(
                    self,
                    "Commande critique",
                    "Commande critique detectee.\nTapez EXEC pour confirmer:",
                )
                if not ok or check.strip().upper() != "EXEC":
                    Toast(self, "Execution annulee")
                    return
            else:
                reply = QMessageBox.question(
                    self,
                    "Confirmation",
                    f"Executer cette commande ?\nadb {command}",
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
        self._run_terminal_command(command)

    def _add_selected_to_batch(self) -> None:
        item = self.command_catalog.currentItem()
        if item is None:
            Toast(self, "Selectionnez une commande")
            return
        meta = item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(meta, dict):
            return
        command = self._prepare_command_from_meta(meta, allow_cancel=True)
        if not command:
            return
        label = f"{meta.get('name', 'Commande')} :: {command}"
        row = QListWidgetItem(label)
        row.setData(Qt.ItemDataRole.UserRole, command)
        self.batch_queue_list.addItem(row)
        Toast(self, "Commande ajoutee a la file batch")

    def _remove_batch_item(self) -> None:
        row = self.batch_queue_list.currentRow()
        if row < 0:
            return
        self.batch_queue_list.takeItem(row)

    def _clear_batch_items(self) -> None:
        self.batch_queue_list.clear()

    def _run_batch_queue(self) -> None:
        if self._batch_running:
            Toast(self, "Un batch est deja en cours")
            return
        commands: list[str] = []
        for i in range(self.batch_queue_list.count()):
            cmd = str(self.batch_queue_list.item(i).data(Qt.ItemDataRole.UserRole) or "").strip()
            if cmd:
                commands.append(cmd)
        if not commands:
            Toast(self, "File batch vide")
            return

        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        self._save_batch_options()
        workers = int(self.batch_workers_spin.value())
        retries = int(self.batch_retry_spin.value())
        timeout_s = int(self.batch_timeout_spin.value())
        stop_on_error = bool(self.batch_stop_on_error.isChecked())
        self._batch_running = True
        self._batch_paused = False
        self.batch_run_btn.setEnabled(False)
        self.batch_pause_btn.setEnabled(True)
        self.batch_pause_btn.setText("Pause")
        self.batch_stop_btn.setEnabled(True)
        self.batch_progress.setMaximum(len(commands))
        self.batch_progress.setValue(0)
        self.batch_progress_label.setText(f"En cours: 0/{len(commands)}")
        self._batch_cancel_event = Event()
        self._batch_pause_event = Event()
        self.batch_output.append(
            f"[BATCH] Demarrage ({len(commands)} commande(s)) sur {serial} | workers={workers} retry={retries} timeout={timeout_s}s"
        )
        self._audit_event(
            event_type="batch",
            action="batch_start",
            status="ok",
            message=f"Batch started ({len(commands)} commands)",
            payload={"commands": len(commands), "workers": workers, "retries": retries, "timeout_s": timeout_s},
            serial=serial,
        )
        self._run_in_worker(
            "batch_run",
            lambda: self._execute_batch_commands(
                commands=commands,
                serial=serial,
                cancel=self._batch_cancel_event,
                pause=self._batch_pause_event,
                workers=workers,
                retries=retries,
                timeout_s=timeout_s,
                stop_on_error=stop_on_error,
            ),
            {"serial": serial, "count": len(commands), "workers": workers, "retries": retries, "timeout_s": timeout_s},
        )

    def _stop_batch_queue(self) -> None:
        if not self._batch_running or self._batch_cancel_event is None:
            Toast(self, "Aucun batch en cours")
            return
        self._batch_cancel_event.set()
        if self._batch_pause_event is not None:
            self._batch_pause_event.clear()
        self.batch_output.append("[BATCH] Arret demande...")
        self._batch_paused = False
        self.batch_pause_btn.setText("Pause")
        self.batch_pause_btn.setEnabled(False)
        self.batch_stop_btn.setEnabled(False)

    def _toggle_batch_pause(self) -> None:
        if not self._batch_running or self._batch_pause_event is None:
            Toast(self, "Aucun batch en cours")
            return
        if not self._batch_paused:
            self._batch_pause_event.set()
            self._batch_paused = True
            self.batch_pause_btn.setText("Resume")
            self.batch_progress_label.setText("Batch en pause")
            self.batch_output.append("[BATCH] Pause demandee")
        else:
            self._batch_pause_event.clear()
            self._batch_paused = False
            self.batch_pause_btn.setText("Pause")
            self.batch_output.append("[BATCH] Reprise")

    def _execute_batch_commands(
        self,
        commands: list[str],
        serial: str,
        cancel: Event,
        pause: Event,
        workers: int,
        retries: int,
        timeout_s: int,
        stop_on_error: bool,
    ) -> dict:
        results: list[dict] = []
        started_at = datetime.utcnow().isoformat() + "Z"

        work_items = list(enumerate(commands, start=1))
        next_idx = 0
        max_workers = max(1, min(workers, len(work_items)))

        def run_one(idx: int, command: str) -> dict:
            started = time.perf_counter()
            attempts: list[dict] = []
            final_result: CommandResult | None = None
            for attempt in range(1, retries + 2):
                while pause.is_set() and not cancel.is_set():
                    time.sleep(0.2)
                if cancel.is_set():
                    break
                result = self.adb.run(command, serial=serial, timeout=timeout_s)
                attempts.append(
                    {
                        "attempt": attempt,
                        "ok": result.ok,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                )
                final_result = result
                if result.ok:
                    break
            if final_result is None:
                final_result = CommandResult(
                    ok=False,
                    command=[],
                    stdout="",
                    stderr="Commande annulee avant execution",
                    returncode=130,
                )
            return {
                "index": idx,
                "command": command,
                "ok": final_result.ok,
                "returncode": final_result.returncode,
                "stdout": final_result.stdout,
                "stderr": final_result.stderr,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "attempts": attempts,
                "attempt_count": len(attempts),
                "duration_s": round(time.perf_counter() - started, 3),
            }

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="batch-worker") as pool:
            pending: dict = {}
            completed = 0
            ok_count = 0
            err_count = 0

            def schedule_one() -> None:
                nonlocal next_idx
                if next_idx >= len(work_items) or cancel.is_set():
                    return
                if pause.is_set():
                    return
                idx, cmd = work_items[next_idx]
                next_idx += 1
                future = pool.submit(run_one, idx, cmd)
                pending[future] = (idx, cmd)

            for _ in range(max_workers):
                schedule_one()

            while pending:
                done, _not_done = wait(list(pending.keys()), return_when=FIRST_COMPLETED)
                for future in done:
                    _meta = pending.pop(future, None)
                    row = future.result()
                    results.append(row)
                    completed += 1
                    if bool(row.get("ok")):
                        ok_count += 1
                    else:
                        err_count += 1
                    self.bridge.command_done.emit(
                        (
                            "batch_progress",
                            {
                                "done": completed,
                                "total": len(commands),
                                "ok": ok_count,
                                "err": err_count,
                                "last_command": row.get("command", ""),
                                "last_ok": bool(row.get("ok")),
                            },
                        )
                    )
                    if stop_on_error and not bool(row.get("ok")):
                        cancel.set()
                while not cancel.is_set() and not pause.is_set() and len(pending) < max_workers and next_idx < len(work_items):
                    schedule_one()

        finished_at = datetime.utcnow().isoformat() + "Z"
        results.sort(key=lambda r: int(r.get("index", 0)))
        total_duration = round(sum(float(r.get("duration_s", 0.0)) for r in results), 3)
        return {
            "started_at": started_at,
            "finished_at": finished_at,
            "serial": serial,
            "canceled": cancel.is_set(),
            "requested": len(commands),
            "executed": len(results),
            "workers": max_workers,
            "retries": retries,
            "timeout_s": timeout_s,
            "total_duration_s": total_duration,
            "results": results,
        }

    def _export_batch_report(self) -> None:
        if not self._batch_results:
            Toast(self, "Aucun resultat batch a exporter")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter rapport batch",
            str(self.base_dir / f"batch_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "results": self._batch_results,
        }
        Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        Toast(self, "Rapport batch exporte")

    def _prepare_command_from_meta(self, meta: dict, allow_cancel: bool = True) -> str | None:
        command = str(meta.get("command", "")).strip()
        if not command:
            return None
        placeholders = [str(p).strip() for p in meta.get("placeholders", []) if str(p).strip()]
        for placeholder in placeholders:
            default_value = str(self.config.get(f"ui.placeholders.{placeholder}", ""))
            value, ok = QInputDialog.getText(
                self,
                "Parametre commande",
                f"Valeur pour <{placeholder}>",
                text=default_value,
            )
            if not ok:
                return None if allow_cancel else command
            clean_value = value.strip()
            self.config.set(f"ui.placeholders.{placeholder}", clean_value)
            command = command.replace(f"<{placeholder}>", clean_value)
        if placeholders:
            self.config.save()
        return command

    def _current_device_info(self) -> DeviceInfo | None:
        serial = self._selected_serial()
        if not serial:
            return None
        for dev in self._last_devices:
            if dev.serial == serial:
                return dev
        return None

    def _is_critical_command(self, command: str) -> bool:
        text = command.lower()
        signatures = [
            "reboot",
            "uninstall",
            "rm -rf",
            "wipe",
            "format",
            "make_ext4fs",
            "setenforce 0",
            "dd if=",
            "oem unlock",
            "disable-user",
            "pm clear",
        ]
        return any(sig in text for sig in signatures)

    def _command_risk_level(self, command: str, root_state: str) -> str:
        text = command.lower()
        if self._is_critical_command(command):
            return "critique"
        if "root:oui" in root_state.lower() or "su -c" in text:
            return "attention"
        if any(token in text for token in ["settings put", "svc ", "am force-stop", "pm disable"]):
            return "attention"
        return "safe"

    def _infer_command_domain(self, command: str) -> str:
        text = command.lower()
        if text.startswith("logcat") or "dumpsys" in text:
            return "diagnostic"
        if text.startswith("install") or "pm " in text or "am " in text:
            return "applications"
        if text.startswith("push") or text.startswith("pull") or " ls " in f" {text} ":
            return "fichiers"
        if "wifi" in text or "ip " in text or "ifconfig" in text:
            return "reseau"
        if "input " in text or "monkey" in text:
            return "automation"
        return "systeme"

    def _command_usage_tip(self, command: str) -> str:
        text = command.lower()
        if "logcat" in text:
            return "Ajoute un filtre tag/niveau pour reduire le bruit et garder des logs exploitables."
        if text.startswith("pull") or text.startswith("push"):
            return "Verifie le chemin source/destination et l'espace libre avant transfert."
        if "pm clear" in text or "uninstall" in text:
            return "Fais une sauvegarde des donnees avant execution."
        if "settings put" in text:
            return "Note la valeur d'origine pour pouvoir revenir en arriere."
        if "reboot" in text:
            return "Evite de lancer un reboot pendant une operation de transfert en cours."
        return "Teste d'abord sur un appareil non critique puis reproduis en batch."

    def _risk_color(self, risk_level: str, root_state: str) -> QColor:
        if risk_level == "critique":
            return QColor("#fca5a5")
        if risk_level == "attention":
            return QColor("#fcd34d")
        return self._root_color(root_state)

    def _risk_color_hex(self, risk_level: str) -> str:
        if risk_level == "critique":
            return "#ef4444"
        if risk_level == "attention":
            return "#f59e0b"
        return "#22c55e"

    def _should_confirm_command(self, command: str, root_state: str) -> bool:
        if not bool(self.config.get("ui.confirm_critical_commands", True)):
            return False
        if self._is_critical_command(command):
            return True
        if root_state.endswith("Oui"):
            device = self._current_device_info()
            if device is not None and not device.root:
                QMessageBox.warning(
                    self,
                    "Commande root",
                    "La commande demande root mais l'appareil actif ne semble pas root.",
                )
            return True
        return False

    def _start_live_logcat(self) -> None:
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        self._stop_live_logcat()
        self.logcat_process = QProcess(self)
        self.logcat_process.setProgram(self.adb.adb_bin)
        self.logcat_process.setArguments(["-s", serial, "logcat"])
        self.logcat_process.readyReadStandardOutput.connect(self._consume_live_logcat)
        self.logcat_process.readyReadStandardError.connect(self._consume_live_logcat_error)
        self.logcat_process.start()
        self.live_log_output.append(f"[LIVE] logcat start sur {serial}")

    def _stop_live_logcat(self) -> None:
        if self.logcat_process is None:
            return
        self.logcat_process.kill()
        self.logcat_process.deleteLater()
        self.logcat_process = None
        self.live_log_output.append("[LIVE] logcat stop")

    def _consume_live_logcat(self) -> None:
        if self.logcat_process is None:
            return
        data = bytes(self.logcat_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        filter_text = self.logcat_filter.text().strip().lower()
        auto_scroll = bool(self.config.get("ui.logcat_auto_scroll", True))
        for line in data.splitlines():
            if not filter_text or filter_text in line.lower():
                self.live_log_output.append(line)
        if auto_scroll:
            self.live_log_output.moveCursor(QTextCursor.MoveOperation.End)

    def _consume_live_logcat_error(self) -> None:
        if self.logcat_process is None:
            return
        data = bytes(self.logcat_process.readAllStandardError()).decode("utf-8", errors="replace")
        if data.strip():
            self.live_log_output.append(f"[ERR] {data.strip()}")

    def _reboot_device(self) -> None:
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        reply = QMessageBox.question(self, "Confirmation", f"Redemarrer l'appareil {serial} ?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        res = self.adb.run("reboot", serial=serial)
        Toast(self, "Reboot envoye" if res.ok else res.stderr)

    def _capture_screen(self) -> None:
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return
        captures_dir = self.base_dir / "captures"
        captures_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_serial = re.sub(r"[^a-zA-Z0-9._-]", "_", serial)
        local_file = captures_dir / f"capture_{safe_serial}_{stamp}.png"
        remote_tmp = "/sdcard/__adb_manager_capture.png"

        shot = self.adb.run(["shell", "screencap", "-p", remote_tmp], serial=serial)
        if not shot.ok:
            Toast(self, f"Capture echec: {shot.stderr}")
            return
        pull = self.adb.run(["pull", remote_tmp, str(local_file)], serial=serial)
        self.adb.run(["shell", "rm", "-f", remote_tmp], serial=serial)
        if pull.ok:
            Toast(self, f"Capture sauvee: {local_file.name}")
            self._refresh_captures(selected_file=local_file.name)
            self.tabs.setCurrentWidget(self.captures_tab)
            self._audit_event(
                event_type="capture",
                action="screenshot",
                status="ok",
                message=f"Screenshot saved: {local_file.name}",
                payload={"file": str(local_file)},
                serial=serial,
            )
        else:
            Toast(self, f"Pull capture echec: {pull.stderr}")
            self._audit_event(
                event_type="capture",
                action="screenshot",
                status="error",
                message=pull.stderr or "Screenshot pull failed",
                payload={"remote": remote_tmp},
                serial=serial,
            )

    def _start_screen_record(self) -> None:
        if self.record_process is not None:
            Toast(self, "Enregistrement deja en cours")
            return
        serial = self._selected_serial()
        if not serial:
            Toast(self, "Aucun appareil actif")
            return

        captures_dir = self._captures_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_serial = re.sub(r"[^a-zA-Z0-9._-]", "_", serial)
        self._record_local_file = captures_dir / f"record_{safe_serial}_{stamp}.mp4"
        self._record_remote_file = f"/sdcard/__adb_manager_record_{safe_serial}_{stamp}.mp4"
        self._record_serial = serial

        self.record_process = QProcess(self)
        self.record_process.setProgram(self.adb.adb_bin)
        self.record_process.setArguments(["-s", serial, "shell", "screenrecord", self._record_remote_file])
        self.record_process.finished.connect(self._on_record_process_finished)
        self.record_process.start()
        self.statusBar().showMessage("Enregistrement video en cours...")
        Toast(self, "Enregistrement video demarre")
        self._audit_event(
            event_type="capture",
            action="record_start",
            status="ok",
            message="Screen record started",
            payload={"remote_file": self._record_remote_file, "local_file": str(self._record_local_file) if self._record_local_file else ""},
            serial=serial,
        )

    def _stop_screen_record(self, silent: bool = False) -> None:
        if self.record_process is None:
            if not silent:
                Toast(self, "Aucun enregistrement en cours")
            return

        # Graceful stop first (Ctrl+C semantics) so MP4 gets finalized with moov atom.
        try:
            pid = int(self.record_process.processId())
            if pid > 0:
                os.kill(pid, signal.SIGINT)
        except Exception:  # noqa: BLE001
            self.record_process.terminate()

        if self.record_process.waitForFinished(10000):
            return

        serial = self._record_serial
        if serial:
            # Fallback: ask Android side process to stop gracefully.
            self.adb.run(["shell", "pkill", "-INT", "-x", "screenrecord"], serial=serial, timeout=5)
            if self.record_process.waitForFinished(3000):
                return

        self.record_process.terminate()
        if not self.record_process.waitForFinished(3000):
            self.record_process.kill()
            self.record_process.waitForFinished(2000)

    def _on_record_process_finished(self) -> None:
        self.statusBar().showMessage("Finalisation de la video...")
        serial = self._record_serial
        remote = self._record_remote_file
        local = self._record_local_file

        self.record_process.deleteLater()
        self.record_process = None
        self._record_remote_file = None
        self._record_local_file = None
        self._record_serial = None

        if not serial or not remote or local is None:
            return
        pull = self._pull_record_with_retry(serial=serial, remote=remote, local=local)
        self.adb.run(["shell", "rm", "-f", remote], serial=serial)
        if pull.ok:
            Toast(self, f"Video sauvee: {local.name}")
            self._refresh_captures(selected_file=local.name)
            self.tabs.setCurrentWidget(self.captures_tab)
            self._audit_event(
                event_type="capture",
                action="record_finish",
                status="ok",
                message=f"Video saved: {local.name}",
                payload={"file": str(local)},
                serial=serial,
            )
        else:
            Toast(self, f"Echec recuperation video: {pull.stderr}")
            self._audit_event(
                event_type="capture",
                action="record_finish",
                status="error",
                message=pull.stderr or "Video recovery failed",
                payload={"remote": remote, "local": str(local)},
                serial=serial,
            )

    def _pull_record_with_retry(self, serial: str, remote: str, local: Path) -> CommandResult:
        last = CommandResult(
            ok=False,
            command=["adb", "-s", serial, "pull", remote, str(local)],
            stdout="",
            stderr="Echec recuperation video",
            returncode=1,
        )
        for _ in range(3):
            time.sleep(0.6)
            last = self.adb.run(["pull", remote, str(local)], serial=serial, timeout=300)
            if last.ok and local.exists() and local.stat().st_size > 100 * 1024:
                return last
        return last

    def _captures_dir(self) -> Path:
        captures_dir = self.base_dir / "captures"
        captures_dir.mkdir(parents=True, exist_ok=True)
        return captures_dir

    def _refresh_captures(self, selected_file: str | None = None) -> None:
        captures_dir = self._captures_dir()
        files = sorted(
            [*captures_dir.glob("*.png"), *captures_dir.glob("*.mp4")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        self.captures_list.clear()
        for file in files:
            self.captures_list.addItem(file.name)
        if not files:
            self.captures_info.setText("Aucune capture disponible")
            self.captures_preview.setText("Apercu capture")
            self.captures_preview.show()
            self.video_widget.hide()
            return

        target_name = selected_file or files[0].name
        for idx in range(self.captures_list.count()):
            if self.captures_list.item(idx).text() == target_name:
                self.captures_list.setCurrentRow(idx)
                break

    def _preview_capture(self, filename: str) -> None:
        if not filename:
            return
        file_path = self._captures_dir() / filename
        if not file_path.exists():
            self.captures_info.setText("Capture introuvable")
            return

        suffix = file_path.suffix.lower()
        if suffix == ".mp4":
            self.captures_preview.hide()
            self.video_widget.show()
            self.media_player.setSource(QUrl.fromLocalFile(str(file_path)))
            self.media_player.pause()
            size_mb = file_path.stat().st_size / (1024 * 1024)
            self.captures_info.setText(f"{filename} | {size_mb:.2f} MB | video")
            return

        pixmap = QPixmap(str(file_path))
        if pixmap.isNull():
            self.captures_info.setText("Impossible de charger l'image")
            self.captures_preview.setText("Format non supporte")
            return

        self.media_player.stop()
        self.video_widget.hide()
        self.captures_preview.show()
        scaled = pixmap.scaled(
            self.captures_preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.captures_preview.setPixmap(scaled)
        size_kb = file_path.stat().st_size / 1024
        self.captures_info.setText(f"{filename} | {size_kb:.1f} KB")

    def _delete_selected_capture(self) -> None:
        item = self.captures_list.currentItem()
        if item is None:
            Toast(self, "Selectionnez une capture")
            return
        file_path = self._captures_dir() / item.text()
        if not file_path.exists():
            self._refresh_captures()
            return
        reply = QMessageBox.question(self, "Suppression", f"Supprimer {file_path.name} ?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        if file_path.suffix.lower() == ".mp4":
            self.media_player.stop()
        file_path.unlink(missing_ok=True)
        self._refresh_captures()

    def _export_report(self) -> None:
        serial = self._selected_serial()
        path, _ = QFileDialog.getSaveFileName(self, "Exporter rapport", "adb_report.json", "JSON (*.json)")
        if not path:
            return
        payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "active_device": serial,
            "devices": [
                {
                    "serial": d.serial,
                    "state": d.state,
                    "model": d.model,
                    "transport": d.transport,
                    "android_version": d.android_version,
                    "root": d.root,
                }
                for d in self._last_devices
            ],
            "system_info": self._last_system_info,
            "history": [
                {"serial": s, "model": m, "event": e, "timestamp": ts}
                for s, m, e, ts in self.history.recent_device_history(limit=200)
            ],
        }
        Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        Toast(self, "Rapport exporte")
        self._audit_event(
            event_type="system",
            action="export_report",
            status="ok",
            message="Global report exported",
            payload={"file": path},
            serial=serial,
        )

    def _full_backup(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        self._run_in_worker("full_backup", lambda: self.backup_module.full_backup(serial), {"serial": serial})

    def _selective_backup(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        package = self._selected_app_package()
        if not package:
            Toast(self, "Selectionnez une application dans l'onglet Applications")
            return
        self._run_in_worker(
            "selective_backup",
            lambda: self.backup_module.selective_backup(serial, [package]),
            {"serial": serial, "package": package},
        )

    def _restore_backup(self) -> None:
        serial = self._selected_serial()
        if not serial:
            return
        backup, _ = QFileDialog.getOpenFileName(self, "Choisir backup", filter="Backup (*.ab)")
        if not backup:
            return
        self._run_in_worker(
            "restore_backup",
            lambda: self.backup_module.restore(serial, Path(backup)),
            {"serial": serial, "backup": backup},
        )

    @Slot(object)
    def _on_command_done(self, payload: object) -> None:
        name, result = payload  # type: ignore[misc]
        if name == "remote_ls":
            self.remote_list.clear()
            if result.ok:
                folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
                file_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
                base = self._normalize_remote_path(self.remote_path.text())
                rows: list[tuple[str, bool]] = []
                for raw in result.stdout.splitlines():
                    line = raw.strip()
                    if not line or line in {".", "./"}:
                        continue
                    is_dir = line.endswith("/")
                    name_only = line[:-1] if is_dir else line
                    if not name_only or name_only == ".":
                        continue
                    if name_only == "..":
                        rows.append((name_only, True))
                        continue
                    rows.append((name_only, is_dir))

                def sort_key(item: tuple[str, bool]) -> tuple[int, str]:
                    n, d = item
                    if n == "..":
                        return (0, n)
                    return (1 if d else 2, n.lower())

                for name_only, is_dir in sorted(rows, key=sort_key):
                    if name_only == "..":
                        full_path = self._remote_parent_path(base)
                        label = ".."
                    else:
                        full_path = self._join_remote_path(base, name_only)
                        label = name_only
                    item = QListWidgetItem(folder_icon if is_dir else file_icon, label)
                    item.setData(Qt.ItemDataRole.UserRole, full_path)
                    item.setData(Qt.ItemDataRole.UserRole + 2, is_dir)
                    item.setToolTip(full_path)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                    self.remote_list.addItem(item)
            else:
                err = QListWidgetItem(f"Erreur: {result.stderr}")
                err.setData(Qt.ItemDataRole.UserRole + 2, False)
                self.remote_list.addItem(err)
        elif name == "terminal":
            output = result.stdout or result.stderr or "(aucune sortie)"
            self.terminal.append_line(output)
            command_line = " ".join(result.command[1:]) if isinstance(result, CommandResult) and result.command else ""
            self._audit_event(
                event_type="debug",
                action="adb_command",
                status="ok" if result.ok else "error",
                message=(result.stderr or result.stdout or "")[:200],
                payload={"command": command_line, "returncode": result.returncode},
                serial=self._selected_serial(),
            )
        elif name == "remote_shell":
            serial = "?"
            command_result: CommandResult | None = None
            if isinstance(result, dict):
                serial = str(result.get("serial", "?"))
                value = result.get("result")
                if isinstance(value, CommandResult):
                    command_result = value
            elif isinstance(result, CommandResult):
                command_result = result
            if command_result is not None:
                output = command_result.stdout or command_result.stderr or "(aucune sortie)"
                self.remote_log_output.append(f"[adb:{serial}] {output}")
                self._audit_event(
                    event_type="debug",
                    action="remote_shell",
                    status="ok" if command_result.ok else "error",
                    message=output[:200],
                    payload={"returncode": command_result.returncode},
                    serial=serial,
                )
        elif name == "wifi_scan":
            hosts = result
            if not hosts:
                QMessageBox.information(self, "Scan WiFi", "Aucun host ADB detecte sur le subnet.")
                return
            picks = [f"{h}:5555" for h in hosts[:30]]
            pick, ok = QInputDialog.getItem(self, "Hosts detectes", "Choisissez une IP a connecter:", picks, 0, False)
            if not ok or not pick:
                return
            ip = pick.split(":", 1)[0]
            connected = self.device_manager.connect_wifi(ip, 5555)
            Toast(self, f"Connecte a {pick}" if connected else f"Echec connexion {pick}")
            if connected:
                self.device_manager.poll_async()
        elif name == "batch_progress":
            payload = result if isinstance(result, dict) else {}
            done = int(payload.get("done", 0))
            total = int(payload.get("total", 0))
            ok = int(payload.get("ok", 0))
            err = int(payload.get("err", 0))
            last_command = str(payload.get("last_command", ""))
            self.batch_progress.setMaximum(max(1, total))
            self.batch_progress.setValue(done)
            self.batch_progress_label.setText(f"En cours: {done}/{total} | OK={ok} ERR={err}")
            if last_command:
                self.statusBar().showMessage(f"Batch: {done}/{total} - {last_command[:100]}")
        elif name == "transfer_progress":
            payload = result if isinstance(result, dict) else {}
            done = int(payload.get("done", 0))
            total = int(payload.get("total", 0))
            rep = payload.get("result", {})
            if isinstance(rep, dict):
                tid = str(rep.get("task_id", ""))
                status = str(rep.get("status", ""))
                msg = str(rep.get("message", ""))
                for row in self._transfer_queue:
                    if str(row.get("task_id", "")) == tid:
                        row["status"] = status
                        break
                self.transfer_log.append(f"[{done}/{total}] {tid} -> {status}: {msg[:220]}")
                self._refresh_transfer_queue_table()
            self.transfer_progress.setMaximum(max(1, total))
            self.transfer_progress.setValue(done)
        elif name == "app_icon":
            payload = result if isinstance(result, dict) else {}
            serial = str(payload.get("serial", "")).strip()
            package = str(payload.get("package", "")).strip()
            icon_path = str(payload.get("icon_path", "")).strip()
            try:
                generation = int(str(payload.get("generation", "-1")))
            except ValueError:
                generation = -1
            if generation != self._app_icon_generation:
                return
            counted = False
            if serial and package:
                key = f"{serial}:{package}"
                if key in self._app_icon_pending:
                    self._app_icon_pending.discard(key)
                    self._app_icon_done += 1
                    counted = True
            if package and icon_path:
                self._update_app_icon(package, icon_path)
                if counted:
                    self._app_icon_success += 1
            if self._app_icon_done > self._app_icon_total:
                self._app_icon_done = self._app_icon_total
            if self._app_icon_success > self._app_icon_done:
                self._app_icon_success = self._app_icon_done
            if self._app_icon_total > 0:
                self.statusBar().showMessage(
                    f"Icones apps: {self._app_icon_done}/{self._app_icon_total} "
                    f"(ok={self._app_icon_success})"
                )
            if serial:
                self._pump_app_icon_queue(serial)
        elif name == "app_risk":
            payload = result if isinstance(result, dict) else {}
            serial = str(payload.get("serial", "")).strip()
            package = str(payload.get("package", "")).strip()
            try:
                generation = int(str(payload.get("generation", "-1")))
            except ValueError:
                generation = -1
            if generation != self._app_analysis_generation:
                return
            if serial and package:
                self._app_analysis_pending.discard(f"{serial}:{package}")
                payload.pop("serial", None)
                payload.pop("generation", None)
                self._app_analysis[package] = payload
                current = self._selected_app_package()
                if current == package:
                    self._show_app_analysis(package)
                self._apply_apps_filters()
                self._pump_app_analysis_queue(serial)
        elif name == "worker":
            self._handle_worker_result(result if isinstance(result, dict) else {})

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_screen_record(silent=True)
        self._stop_live_logcat()
        self._stop_all_scrcpy_remote(silent=True)
        self._close_qr_popup()
        if self.qr_pair_process is not None:
            self.qr_pair_process.kill()
            self.qr_pair_process.deleteLater()
            self.qr_pair_process = None
        self.media_player.stop()
        summary = self.audit_module.summarize_session(self._session_id)
        summary["started_at"] = self._current_session_started
        summary["ended_at"] = datetime.utcnow().isoformat() + "Z"
        self.audit_module.end_session(self._session_id, summary=summary, status="completed")
        self.config.save()
        self.device_manager.shutdown()
        self.adb.shutdown()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._update_responsive_layout()
        super().resizeEvent(event)
