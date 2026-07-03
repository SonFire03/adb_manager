from __future__ import annotations

import re


DEFAULT_ACCENT = "#f59e0b"
DEFAULT_ACCENT_HOVER = "#d97706"
DEFAULT_ACCENT_PRESSED = "#b45309"
DEFAULT_ACCENT_SOFT = "#fcd34d"
DEFAULT_ACCENT_TEXT = "#fde68a"

SUCCESS = "#16a34a"
SUCCESS_HOVER = "#15803d"
SUCCESS_BORDER = "#22c55e"

DANGER = "#b42318"
DANGER_HOVER = "#991b1b"
DANGER_BORDER = "#ef4444"

BG_DARK = "#050b14"
BG_DARK_ALT = "#09111e"
BG_DARK_PANEL = "#0f1724"
BG_DARK_PANEL_ALT = "#121c2c"
BG_DARK_INPUT = "#101a28"
BG_DARK_INPUT_ALT = "#0d1623"
BG_DARK_BORDER = "#223247"
BG_DARK_BORDER_SOFT = "#31465f"
TEXT_DARK = "#e5ecf5"
TEXT_DARK_MUTED = "#8fa4be"
TEXT_DARK_TITLE = "#f6f9ff"

BG_LIGHT = "#eef4fb"
BG_LIGHT_ALT = "#f7fbff"
BG_LIGHT_PANEL = "#ffffff"
BG_LIGHT_PANEL_ALT = "#f9fcff"
BG_LIGHT_INPUT = "#ffffff"
BG_LIGHT_INPUT_ALT = "#f7fbff"
BG_LIGHT_BORDER = "#d4dfeb"
BG_LIGHT_BORDER_SOFT = "#c8d7e6"
TEXT_LIGHT = "#0f1b2d"
TEXT_LIGHT_MUTED = "#60758f"
TEXT_LIGHT_TITLE = "#07101c"


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.strip().lstrip("#")
    if len(value) != 6:
        return (245, 158, 11)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return (
        f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"
    )


def _mix(color: str, target: str, ratio: float) -> str:
    c1 = _hex_to_rgb(color)
    c2 = _hex_to_rgb(target)
    mixed = (
        int(c1[0] * (1 - ratio) + c2[0] * ratio),
        int(c1[1] * (1 - ratio) + c2[1] * ratio),
        int(c1[2] * (1 - ratio) + c2[2] * ratio),
    )
    return _rgb_to_hex(mixed)


def _valid_hex(color: str) -> bool:
    return bool(re.match(r"^#[0-9a-fA-F]{6}$", color.strip()))


DARK_THEME = """
QWidget {
    color: __TEXT__;
    background-color: __BG__;
    font-family: "Manrope", "Noto Sans", "Segoe UI", sans-serif;
    font-size: 14px;
}
QMainWindow, QWidget#mainRoot {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 __BG__,
        stop:0.5 __BG_ALT__,
        stop:1 #02060c);
}
QWidget#headerBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 __PANEL__,
        stop:1 __PANEL_ALT__);
    border: 1px solid __BORDER__;
    border-radius: 12px;
}
QLabel#appTitle {
    color: __TITLE__;
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 0.2px;
}
QLabel#appSubtitle {
    color: __MUTED__;
    font-size: 13px;
}
QLabel#deviceBadge, QLabel#clockLabel {
    background-color: __INPUT__;
    border: 1px solid __BORDER_SOFT__;
    border-radius: 8px;
    padding: 6px 10px;
    font-weight: 700;
}
QLabel#clockLabel {
    color: __ACCENT_SOFT__;
}
QWidget#sidebarContainer {
    background-color: rgba(11, 18, 30, 0.92);
    border: 1px solid __BORDER__;
    border-radius: 12px;
}
QLabel#sidebarTitle {
    color: __TITLE__;
    font-size: 14px;
    font-weight: 700;
}
QLabel#shortcutHint {
    color: __MUTED__;
    font-size: 12px;
}
QListWidget#navSidebar {
    background-color: __PANEL__;
    border: 1px solid __BORDER__;
    border-radius: 10px;
    padding: 6px;
}
QListWidget#navSidebar::item {
    color: __MUTED__;
    padding: 10px 11px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget#navSidebar::item:selected {
    background-color: rgba(245, 158, 11, 0.14);
    color: __TITLE__;
    border: 1px solid __ACCENT__;
}
QListWidget#navSidebar::item:hover {
    background-color: rgba(245, 158, 11, 0.08);
}
QWidget#panelCard, QGroupBox, QGroupBox#paneGroup {
    background-color: rgba(15, 23, 36, 0.96);
    border: 1px solid __BORDER__;
    border-radius: 12px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: __TITLE__;
    background-color: transparent;
    font-weight: 700;
}
QLabel#fieldLabel {
    color: __MUTED__;
    font-weight: 600;
}
QPushButton {
    background-color: __ACCENT__;
    color: #fffdf7;
    border: 1px solid __ACCENT__;
    border-radius: 8px;
    padding: 9px 14px;
    font-weight: 700;
}
QPushButton:hover { background-color: __ACCENT_HOVER__; }
QPushButton:pressed { background-color: __ACCENT_PRESSED__; }
QPushButton#successBtn {
    background-color: __SUCCESS__;
    border: 1px solid __SUCCESS_BORDER__;
}
QPushButton#successBtn:hover { background-color: __SUCCESS_HOVER__; }
QPushButton#dangerBtn {
    background-color: __DANGER__;
    border: 1px solid __DANGER_BORDER__;
}
QPushButton#dangerBtn:hover { background-color: __DANGER_HOVER__; }
QPushButton#ghostBtn {
    background-color: __PANEL_ALT__;
    border: 1px solid __BORDER_SOFT__;
    color: __TEXT__;
}
QPushButton#ghostBtn:hover { background-color: rgba(245, 158, 11, 0.12); }
QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget, QComboBox {
    background-color: __INPUT__;
    border: 1px solid __BORDER_SOFT__;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: __ACCENT__;
}
QLineEdit#pathInput {
    background-color: __INPUT_ALT__;
    border-color: __BORDER__;
    font-weight: 600;
}
QLineEdit#searchInput {
    background-color: __INPUT_ALT__;
}
QListWidget#fileList, QListWidget#commandCatalog, QListWidget#batchQueue {
    border-color: __BORDER_SOFT__;
}
QListWidget#appsGrid::item {
    padding: 8px;
    margin: 4px;
    border-radius: 10px;
}
QListWidget#appsGrid::item:selected {
    background-color: rgba(245, 158, 11, 0.14);
    border: 1px solid __ACCENT_SOFT__;
}
QTextEdit#commandDetails, QTextEdit#batchOutput {
    background-color: __INPUT_ALT__;
    border-color: __BORDER__;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QTreeWidget:focus, QTableWidget:focus, QComboBox:focus {
    border: 1px solid __ACCENT_SOFT__;
}
QTableWidget {
    gridline-color: __BORDER__;
}
QHeaderView::section {
    background-color: __PANEL_ALT__;
    color: __TITLE__;
    border: 0;
    padding: 8px;
    font-weight: 700;
}
QTabWidget::pane {
    border: 1px solid __BORDER__;
    border-radius: 12px;
    background-color: rgba(9, 15, 24, 0.72);
    padding: 8px;
}
QProgressBar {
    border: 1px solid __BORDER_SOFT__;
    border-radius: 7px;
    text-align: center;
    background-color: __INPUT_ALT__;
    color: __TEXT__;
    font-weight: 700;
}
QProgressBar::chunk {
    background-color: __ACCENT__;
    border-radius: 6px;
}
QSplitter::handle {
    background-color: __BORDER__;
    width: 1px;
    height: 1px;
}
QStatusBar {
    background: __BG_ALT__;
    border-top: 1px solid __BORDER__;
}
QScrollBar:vertical {
    background: __BG_ALT__;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: __BORDER_SOFT__;
    border-radius: 6px;
    min-height: 25px;
}
QScrollBar::handle:vertical:hover {
    background: __ACCENT_HOVER__;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QLabel#metricValue {
    color: __ACCENT_SOFT__;
    font-size: 18px;
    font-weight: 800;
}
QLabel#metricLabel {
    color: __MUTED__;
    font-size: 13px;
}
QCheckBox {
    spacing: 8px;
    font-weight: 600;
}
QCheckBox:hover {
    color: __TITLE__;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
}
"""


LIGHT_THEME = """
QWidget {
    color: __TEXT__;
    background-color: __BG__;
    font-family: "Manrope", "Noto Sans", "Segoe UI", sans-serif;
    font-size: 14px;
}
QMainWindow, QWidget#mainRoot {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 __BG__,
        stop:0.5 __BG_ALT__,
        stop:1 #e7eef6);
}
QWidget#headerBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 __PANEL__,
        stop:1 __PANEL_ALT__);
    border: 1px solid __BORDER__;
    border-radius: 12px;
}
QLabel#appTitle {
    color: __TITLE__;
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 0.2px;
}
QLabel#appSubtitle {
    color: __MUTED__;
    font-size: 13px;
}
QLabel#deviceBadge, QLabel#clockLabel {
    background-color: __PANEL__;
    border: 1px solid __BORDER_SOFT__;
    border-radius: 8px;
    padding: 6px 10px;
    font-weight: 700;
}
QLabel#clockLabel {
    color: __ACCENT__;
}
QWidget#sidebarContainer {
    background-color: rgba(255, 255, 255, 0.96);
    border: 1px solid __BORDER__;
    border-radius: 12px;
}
QLabel#sidebarTitle {
    color: __TITLE__;
    font-size: 14px;
    font-weight: 700;
}
QLabel#shortcutHint {
    color: __MUTED__;
    font-size: 12px;
}
QListWidget#navSidebar {
    background-color: __PANEL__;
    border: 1px solid __BORDER__;
    border-radius: 10px;
    padding: 6px;
}
QListWidget#navSidebar::item {
    color: __MUTED__;
    padding: 10px 11px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget#navSidebar::item:selected {
    background-color: rgba(245, 158, 11, 0.12);
    color: __TITLE__;
    border: 1px solid __ACCENT_SOFT__;
}
QListWidget#navSidebar::item:hover {
    background-color: rgba(245, 158, 11, 0.06);
}
QWidget#panelCard, QGroupBox, QGroupBox#paneGroup {
    background-color: __PANEL__;
    border: 1px solid __BORDER__;
    border-radius: 12px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: __TITLE__;
    background-color: transparent;
    font-weight: 700;
}
QLabel#fieldLabel {
    color: __MUTED__;
    font-weight: 600;
}
QPushButton {
    background-color: __ACCENT__;
    color: #fffdf7;
    border: 1px solid __ACCENT__;
    border-radius: 8px;
    padding: 9px 14px;
    font-weight: 700;
}
QPushButton:hover { background-color: __ACCENT_HOVER__; }
QPushButton:pressed { background-color: __ACCENT_PRESSED__; }
QPushButton#successBtn {
    background-color: __SUCCESS__;
    border: 1px solid __SUCCESS_BORDER__;
}
QPushButton#successBtn:hover { background-color: __SUCCESS_HOVER__; }
QPushButton#dangerBtn {
    background-color: __DANGER__;
    border: 1px solid __DANGER_BORDER__;
}
QPushButton#dangerBtn:hover { background-color: __DANGER_HOVER__; }
QPushButton#ghostBtn {
    background-color: __PANEL_ALT__;
    color: __TEXT__;
    border: 1px solid __BORDER_SOFT__;
}
QPushButton#ghostBtn:hover { background-color: rgba(245, 158, 11, 0.10); }
QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget, QComboBox {
    background-color: __INPUT__;
    border: 1px solid __BORDER_SOFT__;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: __ACCENT__;
}
QLineEdit#pathInput {
    background-color: __INPUT_ALT__;
    border-color: __BORDER__;
    font-weight: 600;
}
QLineEdit#searchInput {
    background-color: __INPUT_ALT__;
}
QListWidget#fileList, QListWidget#commandCatalog, QListWidget#batchQueue {
    border-color: __BORDER_SOFT__;
}
QListWidget#appsGrid::item {
    padding: 8px;
    margin: 4px;
    border-radius: 10px;
}
QListWidget#appsGrid::item:selected {
    background-color: rgba(245, 158, 11, 0.12);
    border: 1px solid __ACCENT_SOFT__;
}
QTextEdit#commandDetails, QTextEdit#batchOutput {
    background-color: __INPUT_ALT__;
    border-color: __BORDER__;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QTreeWidget:focus, QTableWidget:focus, QComboBox:focus {
    border: 1px solid __ACCENT_SOFT__;
}
QTableWidget {
    gridline-color: __BORDER__;
}
QHeaderView::section {
    background-color: __PANEL_ALT__;
    color: __TITLE__;
    border: 0;
    padding: 8px;
    font-weight: 700;
}
QTabWidget::pane {
    border: 1px solid __BORDER__;
    border-radius: 12px;
    background-color: rgba(255, 255, 255, 0.82);
    padding: 8px;
}
QProgressBar {
    border: 1px solid __BORDER_SOFT__;
    border-radius: 7px;
    text-align: center;
    background-color: __INPUT_ALT__;
    color: __TEXT__;
    font-weight: 700;
}
QProgressBar::chunk {
    background-color: __ACCENT__;
    border-radius: 6px;
}
QSplitter::handle {
    background-color: __BORDER__;
    width: 1px;
    height: 1px;
}
QStatusBar {
    background: __BG_ALT__;
    border-top: 1px solid __BORDER__;
}
QScrollBar:vertical {
    background: __BG_ALT__;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: __BORDER_SOFT__;
    border-radius: 6px;
    min-height: 25px;
}
QScrollBar::handle:vertical:hover {
    background: __ACCENT_HOVER__;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QLabel#metricValue {
    color: __ACCENT__;
    font-size: 18px;
    font-weight: 800;
}
QLabel#metricLabel {
    color: __MUTED__;
    font-size: 13px;
}
QCheckBox {
    spacing: 8px;
    font-weight: 600;
}
QCheckBox:hover {
    color: __TITLE__;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
}
"""


def _fill_template(template: str, accent: str, *, dark: bool) -> str:
    if not _valid_hex(accent):
        accent = DEFAULT_ACCENT
    accent_hover = _mix(accent, "#000000", 0.12)
    accent_pressed = _mix(accent, "#000000", 0.24)
    accent_soft = _mix(accent, "#ffffff", 0.68)
    palette = {
        "__ACCENT__": accent,
        "__ACCENT_HOVER__": accent_hover,
        "__ACCENT_PRESSED__": accent_pressed,
        "__ACCENT_SOFT__": accent_soft,
        "__SUCCESS__": SUCCESS,
        "__SUCCESS_HOVER__": SUCCESS_HOVER,
        "__SUCCESS_BORDER__": SUCCESS_BORDER,
        "__DANGER__": DANGER,
        "__DANGER_HOVER__": DANGER_HOVER,
        "__DANGER_BORDER__": DANGER_BORDER,
        "__BG__": BG_DARK if dark else BG_LIGHT,
        "__BG_ALT__": BG_DARK_ALT if dark else BG_LIGHT_ALT,
        "__PANEL__": BG_DARK_PANEL if dark else BG_LIGHT_PANEL,
        "__PANEL_ALT__": BG_DARK_PANEL_ALT if dark else BG_LIGHT_PANEL_ALT,
        "__INPUT__": BG_DARK_INPUT if dark else BG_LIGHT_INPUT,
        "__INPUT_ALT__": BG_DARK_INPUT_ALT if dark else BG_LIGHT_INPUT_ALT,
        "__BORDER__": BG_DARK_BORDER if dark else BG_LIGHT_BORDER,
        "__BORDER_SOFT__": BG_DARK_BORDER_SOFT if dark else BG_LIGHT_BORDER_SOFT,
        "__TEXT__": TEXT_DARK if dark else TEXT_LIGHT,
        "__MUTED__": TEXT_DARK_MUTED if dark else TEXT_LIGHT_MUTED,
        "__TITLE__": TEXT_DARK_TITLE if dark else TEXT_LIGHT_TITLE,
    }
    out = template
    for key, value in palette.items():
        out = out.replace(key, value)
    return out


COMPACT_OVERRIDES = """
QWidget { font-size: 12px; }
QPushButton { padding: 5px 9px; border-radius: 7px; }
QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget, QComboBox {
    padding: 4px;
    border-radius: 7px;
}
QTabBar::tab { padding: 6px 10px; }
QLabel#appTitle { font-size: 17px; }
QLabel#appSubtitle { font-size: 11px; }
QLabel#metricValue { font-size: 16px; }
QLabel#metricLabel { font-size: 11px; }
QListWidget#navSidebar::item { padding: 6px 8px; }
QCheckBox::indicator { width: 14px; height: 14px; }
"""


def get_theme(name: str, accent: str = DEFAULT_ACCENT, density: str = "comfortable") -> str:
    dark = name.lower() != "light"
    base = DARK_THEME if dark else LIGHT_THEME
    themed = _fill_template(base, accent, dark=dark)
    if density.lower() == "compact":
        themed += "\n" + COMPACT_OVERRIDES
    return themed
