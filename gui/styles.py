from __future__ import annotations

import re


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.strip().lstrip("#")
    if len(value) != 6:
        return (37, 99, 235)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


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
    color: #d8e2f0;
    background-color: #08111f;
    font-family: "Manrope", "Noto Sans", "Segoe UI", sans-serif;
    font-size: 14px;
}
QMainWindow, QWidget#mainRoot {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #071020,
        stop:0.5 #0b1528,
        stop:1 #060d18);
}
QWidget#headerBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0b172d,
        stop:1 #0d1d36);
    border: 1px solid #233452;
    border-radius: 12px;
}
QLabel#appTitle {
    color: #eef5ff;
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 0.2px;
}
QLabel#appSubtitle {
    color: #8ea4c2;
    font-size: 13px;
}
QLabel#deviceBadge, QLabel#clockLabel {
    background-color: #0b1426;
    border: 1px solid #2c3f60;
    border-radius: 8px;
    padding: 6px 10px;
    font-weight: 700;
}
QLabel#clockLabel {
    color: #93c5fd;
}
QWidget#sidebarContainer {
    background-color: rgba(12, 22, 38, 0.92);
    border: 1px solid #21324d;
    border-radius: 12px;
}
QLabel#sidebarTitle {
    color: #e5eefc;
    font-size: 14px;
    font-weight: 700;
}
QLabel#shortcutHint {
    color: #90a5c1;
    font-size: 12px;
}
QListWidget#navSidebar {
    background-color: #0a1426;
    border: 1px solid #223450;
    border-radius: 10px;
    padding: 6px;
}
QListWidget#navSidebar::item {
    color: #9fb2cc;
    padding: 10px 11px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget#navSidebar::item:selected {
    background-color: #16253d;
    color: #f3f8ff;
    border: 1px solid #2f4d76;
}
QListWidget#navSidebar::item:hover {
    background-color: #111f35;
}
QWidget#panelCard, QGroupBox, QGroupBox#paneGroup {
    background-color: rgba(14, 24, 41, 0.94);
    border: 1px solid #223451;
    border-radius: 12px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: #c2d3ea;
    background-color: transparent;
    font-weight: 700;
}
QLabel#fieldLabel {
    color: #90a4c0;
    font-weight: 600;
}
QPushButton {
    background-color: #2563eb;
    color: #f4f8ff;
    border: 1px solid #3b82f6;
    border-radius: 8px;
    padding: 9px 14px;
    font-weight: 700;
}
QPushButton:hover { background-color: #1d4ed8; }
QPushButton:pressed { background-color: #1e40af; }
QPushButton#successBtn {
    background-color: #0f8a5d;
    border: 1px solid #22c55e;
}
QPushButton#successBtn:hover { background-color: #0d7c53; }
QPushButton#dangerBtn {
    background-color: #8f1f2f;
    border: 1px solid #ef4444;
}
QPushButton#dangerBtn:hover { background-color: #9f2234; }
QPushButton#ghostBtn {
    background-color: #111c31;
    border: 1px solid #2c4263;
    color: #dce8fa;
}
QPushButton#ghostBtn:hover { background-color: #152540; }
QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget, QComboBox {
    background-color: #091425;
    border: 1px solid #2a3f60;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: #2563eb;
}
QLineEdit#pathInput {
    background-color: #0b1629;
    border-color: #314a70;
    font-weight: 600;
}
QLineEdit#searchInput {
    background-color: #09182d;
}
QListWidget#fileList, QListWidget#commandCatalog, QListWidget#batchQueue {
    border-color: #355079;
}
QListWidget#appsGrid::item {
    padding: 8px;
    margin: 4px;
    border-radius: 10px;
}
QListWidget#appsGrid::item:selected {
    background-color: #13243d;
    border: 1px solid #355079;
}
QTextEdit#commandDetails, QTextEdit#batchOutput {
    background-color: #0a1528;
    border-color: #335072;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QTreeWidget:focus, QTableWidget:focus, QComboBox:focus {
    border: 1px solid #60a5fa;
}
QTableWidget {
    gridline-color: #1f3250;
}
QHeaderView::section {
    background-color: #12233e;
    color: #e4eeff;
    border: 0;
    padding: 8px;
    font-weight: 700;
}
QTabWidget::pane {
    border: 1px solid #223753;
    border-radius: 12px;
    background-color: rgba(10, 19, 33, 0.75);
    padding: 8px;
}
QProgressBar {
    border: 1px solid #2f486c;
    border-radius: 7px;
    text-align: center;
    background-color: #0a1528;
    color: #e6f0ff;
    font-weight: 700;
}
QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 6px;
}
QSplitter::handle {
    background-color: #1f304d;
    width: 1px;
    height: 1px;
}
QStatusBar {
    background: #081321;
    border-top: 1px solid #1f3250;
}
QScrollBar:vertical {
    background: #0a1527;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #31496b;
    border-radius: 6px;
    min-height: 25px;
}
QScrollBar::handle:vertical:hover {
    background: #3f5d88;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QLabel#metricValue {
    color: #9ec5ff;
    font-size: 18px;
    font-weight: 800;
}
QLabel#metricLabel {
    color: #8ca4c0;
    font-size: 13px;
}
QCheckBox {
    spacing: 8px;
    font-weight: 600;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
}
"""


LIGHT_THEME = """
QWidget {
    color: #0f1b2d;
    background-color: #edf2f9;
    font-family: "Manrope", "Noto Sans", "Segoe UI", sans-serif;
    font-size: 14px;
}
QMainWindow, QWidget#mainRoot {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #eaf0f8,
        stop:0.5 #f5f8fc,
        stop:1 #edf3fa);
}
QWidget#headerBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ffffff,
        stop:1 #f7fbff);
    border: 1px solid #d1ddec;
    border-radius: 12px;
}
QLabel#appTitle {
    color: #0e1b2d;
    font-size: 20px;
    font-weight: 800;
    letter-spacing: 0.2px;
}
QLabel#appSubtitle {
    color: #5e718d;
    font-size: 13px;
}
QLabel#deviceBadge, QLabel#clockLabel {
    background-color: #f8fbff;
    border: 1px solid #d1ddeb;
    border-radius: 8px;
    padding: 6px 10px;
    font-weight: 700;
}
QLabel#clockLabel {
    color: #2563eb;
}
QWidget#sidebarContainer {
    background-color: rgba(255, 255, 255, 0.96);
    border: 1px solid #d3deec;
    border-radius: 12px;
}
QLabel#sidebarTitle {
    color: #0e1b2d;
    font-size: 14px;
    font-weight: 700;
}
QLabel#shortcutHint {
    color: #62748f;
    font-size: 12px;
}
QListWidget#navSidebar {
    background-color: #ffffff;
    border: 1px solid #d6e1ef;
    border-radius: 10px;
    padding: 6px;
}
QListWidget#navSidebar::item {
    color: #42556f;
    padding: 10px 11px;
    border-radius: 8px;
    margin: 2px 0;
}
QListWidget#navSidebar::item:selected {
    background-color: #e8f1ff;
    color: #0f1b2d;
    border: 1px solid #b8cfed;
}
QListWidget#navSidebar::item:hover {
    background-color: #f2f7ff;
}
QWidget#panelCard, QGroupBox, QGroupBox#paneGroup {
    background-color: #ffffff;
    border: 1px solid #d7e3f0;
    border-radius: 12px;
    margin-top: 10px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: #30445f;
    background-color: transparent;
    font-weight: 700;
}
QLabel#fieldLabel {
    color: #5d718e;
    font-weight: 600;
}
QPushButton {
    background-color: #2563eb;
    color: #ffffff;
    border: 1px solid #2563eb;
    border-radius: 8px;
    padding: 9px 14px;
    font-weight: 700;
}
QPushButton:hover { background-color: #1d4ed8; }
QPushButton:pressed { background-color: #1e40af; }
QPushButton#successBtn {
    background-color: #0f8a5d;
    border: 1px solid #0f8a5d;
}
QPushButton#successBtn:hover { background-color: #0d7c53; }
QPushButton#dangerBtn {
    background-color: #dc2626;
    border: 1px solid #dc2626;
}
QPushButton#dangerBtn:hover { background-color: #c41f1f; }
QPushButton#ghostBtn {
    background-color: #ffffff;
    color: #20334b;
    border: 1px solid #c6d5e8;
}
QPushButton#ghostBtn:hover { background-color: #f2f7ff; }
QLineEdit, QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget, QComboBox {
    background-color: #ffffff;
    border: 1px solid #c9d8eb;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: #bfdbfe;
}
QLineEdit#pathInput {
    background-color: #f7fbff;
    border-color: #bcd0e8;
    font-weight: 600;
}
QLineEdit#searchInput {
    background-color: #f9fbff;
}
QListWidget#fileList, QListWidget#commandCatalog, QListWidget#batchQueue {
    border-color: #b8cae2;
}
QListWidget#appsGrid::item {
    padding: 8px;
    margin: 4px;
    border-radius: 10px;
}
QListWidget#appsGrid::item:selected {
    background-color: #e8f1ff;
    border: 1px solid #b8cae2;
}
QTextEdit#commandDetails, QTextEdit#batchOutput {
    background-color: #fbfdff;
    border-color: #c6d7eb;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QTreeWidget:focus, QTableWidget:focus, QComboBox:focus {
    border: 1px solid #60a5fa;
}
QTableWidget {
    gridline-color: #dce6f3;
}
QHeaderView::section {
    background-color: #e9f0f9;
    color: #102037;
    border: 0;
    padding: 8px;
    font-weight: 700;
}
QTabWidget::pane {
    border: 1px solid #d5e1ef;
    border-radius: 12px;
    background-color: rgba(255, 255, 255, 0.8);
    padding: 8px;
}
QProgressBar {
    border: 1px solid #c5d5e8;
    border-radius: 7px;
    text-align: center;
    background-color: #f4f8fe;
    color: #142339;
    font-weight: 700;
}
QProgressBar::chunk {
    background-color: #2563eb;
    border-radius: 6px;
}
QSplitter::handle {
    background-color: #d4e0ef;
    width: 1px;
    height: 1px;
}
QStatusBar {
    background: #e9f0f8;
    border-top: 1px solid #d0dceb;
}
QScrollBar:vertical {
    background: #f5f8fc;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #c1d1e5;
    border-radius: 6px;
    min-height: 25px;
}
QScrollBar::handle:vertical:hover {
    background: #9fb5d1;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QLabel#metricValue {
    color: #1d4ed8;
    font-size: 18px;
    font-weight: 800;
}
QLabel#metricLabel {
    color: #526781;
    font-size: 13px;
}
QCheckBox {
    spacing: 8px;
    font-weight: 600;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
}
"""


def _with_accent(theme: str, accent: str) -> str:
    if not _valid_hex(accent):
        accent = "#2563eb"
    accent_hover = _mix(accent, "#000000", 0.12)
    accent_pressed = _mix(accent, "#000000", 0.24)
    accent_soft = _mix(accent, "#ffffff", 0.72)
    accent_text_dark = _mix(accent, "#ffffff", 0.55)

    out = theme
    replacements = {
        "#2563eb": accent,
        "#1d4ed8": accent_hover,
        "#1e40af": accent_pressed,
        "#60a5fa": accent_soft,
        "#93c5fd": accent_text_dark,
        "#bfdbfe": accent_soft,
    }
    for old, new in replacements.items():
        out = out.replace(old, new)
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


def get_theme(name: str, accent: str = "#2563eb", density: str = "comfortable") -> str:
    base = LIGHT_THEME if name.lower() == "light" else DARK_THEME
    themed = _with_accent(base, accent=accent)
    if density.lower() == "compact":
        themed += "\n" + COMPACT_OVERRIDES
    return themed
