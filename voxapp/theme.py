"""Dark theme, palette and small painting helpers."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .paths import assets_dir

BACKDROP = "#0d1015"
CARD = "#151a22"
CARD_RAISED = "#1a2029"
FIELD = "#1d2330"
BORDER = "#242c3a"
BORDER_LIGHT = "#303a4c"
TEXT = "#e8ecf4"
MUTED = "#8b95a9"
DIM = "#5f6a7f"
ACCENT = "#2dd4a7"
ACCENT_DARK = "#06110d"
WARN = "#f5b85c"
ERROR = "#f87171"
BLUE = "#60a5fa"


STYLESHEET = f"""
QMainWindow, QDialog, QMessageBox {{
    background: {BACKDROP};
}}
QWidget {{
    color: {TEXT};
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 10pt;
}}
QLabel {{ background: transparent; }}
QFrame#Card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#Logo {{
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 25pt;
    font-weight: 800;
    letter-spacing: 5px;
    color: {TEXT};
}}
QLabel#Tagline {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#CardTitle {{
    color: {MUTED};
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1.4px;
}}
QLabel#FieldLabel {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#Muted {{ color: {MUTED}; font-size: 9pt; }}
QLabel#Hint {{ color: {MUTED}; font-size: 9pt; }}
QLabel#Warn {{ color: {WARN}; font-size: 9pt; }}
QLabel#Good {{ color: {ACCENT}; font-size: 9pt; }}
QLabel#Pill {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 13px;
    padding: 5px 12px;
    font-size: 9pt;
    color: {TEXT};
}}
QLabel#Value {{ color: {TEXT}; font-size: 9.5pt; font-weight: 600; }}

QComboBox, QLineEdit {{
    background: {FIELD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    min-height: 19px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_DARK};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: {BORDER_LIGHT}; }}
QComboBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox:disabled, QLineEdit:disabled {{ color: {DIM}; background: #171c25; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {CARD_RAISED};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: #234034;
    selection-color: {TEXT};
}}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; border-radius: 4px; }}

QPushButton {{
    background: {FIELD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 15px;
    min-height: 19px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #242c3a; border-color: {BORDER_LIGHT}; }}
QPushButton:pressed {{ background: #1a2029; }}
QPushButton:disabled {{ color: {DIM}; background: #171c25; border-color: #202633; }}
QPushButton#Primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: {ACCENT_DARK};
    font-weight: 700;
    padding: 10px 26px;
}}
QPushButton#Primary:hover {{ background: #3ee3b8; border-color: #3ee3b8; }}
QPushButton#Primary:disabled {{ background: #1d3a32; border-color: #1d3a32; color: #6f9c8f; }}
QPushButton#Danger {{
    background: #3a1d22;
    border: 1px solid #6b2b35;
    color: #ffb4b4;
    font-weight: 600;
}}
QPushButton#Danger:hover {{ background: #4a2229; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {MUTED}; padding: 6px 8px; }}
QPushButton#Ghost:hover {{ color: {TEXT}; }}
QPushButton#Bypass {{ color: {MUTED}; }}
QPushButton#Bypass:checked {{
    background: #3a2f14;
    border-color: #6b531f;
    color: {WARN};
    font-weight: 600;
}}
QPushButton#Bypass:checked:hover {{ background: #4a3c1a; }}
QPushButton#SegBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    color: {MUTED};
    font-weight: 600;
}}
QPushButton#SegBtn:hover {{ color: {TEXT}; }}
QPushButton#SegBtn:checked {{ background: #22443a; color: {ACCENT}; }}
QPushButton#SegBtn:disabled {{ color: {DIM}; }}
QFrame#Seg {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 8px; }}

QCheckBox {{ color: {MUTED}; spacing: 8px; }}
QCheckBox:disabled {{ color: {DIM}; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border-radius: 4px;
    border: 1px solid {BORDER_LIGHT};
    background: {FIELD};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ border-color: {BORDER}; background: #171c25; }}

QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 14px; height: 14px; margin: -6px 0;
    border-radius: 7px; background: {ACCENT};
}}
QSlider::handle:horizontal:hover {{ background: #3ee3b8; }}
QSlider:disabled::handle:horizontal {{ background: {DIM}; }}
QSlider:disabled::sub-page:horizontal {{ background: {BORDER}; }}

QProgressBar {{
    background: {FIELD};
    border: none;
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QFrame#Banner {{
    background: #1f1a10;
    border: 1px solid #4b3a18;
    border-radius: 10px;
}}
QFrame#Banner QLabel {{ color: #e8c98e; }}
QToolTip {{
    background: {CARD_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER_LIGHT};
    padding: 5px 8px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_LIGHT}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollArea#Scroll, QScrollArea#Scroll > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QWidget#Content {{ background: {BACKDROP}; }}
"""


def app_icon() -> QIcon:
    icon_path = assets_dir() / "icon.ico"
    return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BACKDROP))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor("#12161e"))
    palette.setColor(QPalette.AlternateBase, QColor(CARD_RAISED))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(FIELD))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.BrightText, QColor(ERROR))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor(ACCENT_DARK))
    palette.setColor(QPalette.ToolTipBase, QColor(CARD_RAISED))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.PlaceholderText, QColor(DIM))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(DIM))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(DIM))
    app.setPalette(palette)
    app.setFont(QFont("Segoe UI Variable Text", 10))
    app.setStyleSheet(STYLESHEET)


def enable_dark_title_bar(widget: QWidget) -> None:
    """Ask DWM for a dark title bar on Windows 10/11."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
                )
            except Exception:
                pass
    except Exception:
        pass


def token(name: str) -> str:
    return {
        "text": TEXT,
        "muted": MUTED,
        "dim": DIM,
        "accent": ACCENT,
        "warn": WARN,
        "error": ERROR,
        "blue": BLUE,
    }.get(name, TEXT)
