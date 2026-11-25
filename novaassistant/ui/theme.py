"""Pitch-black futuristic theme + stylesheet for the Nova desktop UI.

Design language (see DESIGN.md "Obsidian Kinetic"):
  * ultra-deep neutral surfaces (#0a0a0c canvas) with 1px subtle borders
  * mono/uppercase technical labels (JetBrains Mono stack)
  * chromatic state accents: violet = generation, cyan = audio capture,
    amber = processing, emerald = success, red = recording
"""

from __future__ import annotations

MONO = "'JetBrains Mono', 'Fira Code', 'Consolas', 'Courier New', monospace"
SANS = "'-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', sans-serif"

BG = "#0a0a0c"
SIDEBAR = "#0d0d0f"
CARD = "#111115"
CARD_2 = "#1a1a1f"
CARD_3 = "#232329"
INPUT = "#08080a"
BORDER = "#1e1e24"
BORDER_2 = "#2a2a32"
TEXT = "#e8e8ee"
DIM = "#8b8b95"
FAINT = "#5b5b64"

ACCENT = "#8b5cf6"          # electric violet - AI / generation
ACCENT_HOVER = "#a78bfa"
CYAN = "#06b6d4"            # audio capture / telemetry
CYAN_HOVER = "#22d3ee"
GREEN = "#10b981"
RED = "#ef4444"
AMBER = "#f59e0b"

USER_BUBBLE = "#26262e"
ASSISTANT_BUBBLE = "#141419"
TOOL_BUBBLE = "#101014"
ERROR_BUBBLE = "#1f1214"

STATUS_COLORS = {
    "idle": "#6b7280",
    "listening": CYAN,
    "recording": RED,
    "processing": AMBER,
    "speaking": ACCENT,
}
STATUS_LABELS = {
    "idle": "IDLE",
    "listening": "LISTENING",
    "recording": "RECORDING",
    "processing": "THINKING",
    "speaking": "SPEAKING",
}

# pill CSS fragments shared by the sidebar, overlay and pages
def status_pill_css(color: str) -> str:
    return (f"font-family: {MONO}; font-size: 10px; font-weight: 600; "
            f"letter-spacing: 1.6px; padding: 6px 12px; border-radius: 999px;"
            f"background: {CARD_2}; border: 1px solid {color}; color: {color};")


STYLESHEET = f"""
* {{
    font-family: {SANS};
    font-size: 13px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QMainWindow, QDialog {{
    background: {BG};
}}
QWidget#sidebar {{
    background: {SIDEBAR};
    border-right: 1px solid {BORDER};
}}
QLabel#appTitle {{
    font-family: {MONO};
    font-size: 18px; font-weight: 700; color: {TEXT}; letter-spacing: 4px;
}}
QLabel#appSubtitle {{
    font-family: {MONO};
    font-size: 9px; color: {FAINT}; letter-spacing: 2.2px;
}}
QLabel#statusPill {{
    font-family: {MONO}; font-size: 10px; font-weight: 600; letter-spacing: 1.6px;
    padding: 6px 12px; border-radius: 999px;
    background: {CARD}; border: 1px solid {BORDER};
}}
QListWidget#nav {{
    background: transparent; border: none; outline: 0;
    font-size: 13px; font-weight: 500;
}}
QListWidget#nav::item {{
    padding: 10px 14px; border-radius: 8px; margin: 2px 8px; color: {DIM};
}}
QListWidget#nav::item:selected {{
    background: {CARD_2}; color: {TEXT}; border-left: 3px solid {ACCENT};
}}
QListWidget#nav::item:hover {{
    background: {CARD}; color: {TEXT};
}}
QPushButton {{
    background: {CARD}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {CARD_2}; border-color: {BORDER_2}; }}
QPushButton:pressed {{ background: {INPUT}; }}
QPushButton:disabled {{ color: {FAINT}; background: {CARD}; }}
QPushButton#micButton {{
    border-radius: 10px; padding: 14px 16px; font-size: 13px; font-weight: 700;
    background: {CARD_2}; border: 1px solid {BORDER};
}}
QPushButton#micButton:checked {{
    background: #2a1113; border: 1px solid {RED}; color: #ff8a80;
}}
QPushButton#sendButton {{
    background: {ACCENT}; border: none; color: white; padding: 10px 18px;
}}
QPushButton#sendButton:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#stopButton {{
    background: #2a1113; border: 1px solid {RED}; color: #ff8a80;
}}
QPushButton#primaryButton {{ background: {ACCENT}; border: none; color: white; }}
QPushButton#primaryButton:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#cyanButton {{ background: #0b2a31; border: 1px solid {CYAN}; color: {CYAN_HOVER}; }}
QPushButton#cyanButton:hover {{ background: #0e3640; }}
QPushButton#dangerButton {{ background: #2a1113; border: 1px solid {RED}; color: #ff8a80; }}
QPushButton#dangerButton:hover {{ background: #3a1618; }}
QPushButton#approveButton {{ background: #0d221b; border: 1px solid {GREEN}; color: {GREEN}; }}
QPushButton#ghostButton {{
    background: transparent; border: 1px solid {BORDER}; color: {DIM};
}}
QPushButton#ghostButton:hover {{ color: {TEXT}; border-color: {BORDER_2}; }}
QPushButton#iconButton {{
    background: transparent; border: none; color: {DIM};
    font-size: 14px; padding: 4px 8px;
}}
QPushButton#iconButton:hover {{ color: {TEXT}; }}
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px; font-size: 13px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit#searchInput {{ background: {CARD}; }}
QComboBox {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 10px; min-width: 150px;
}}
QComboBox:hover {{ border: 1px solid {BORDER_2}; }}
QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER_2};
    selection-background-color: {CARD_2};
    outline: 0;
}}
QCheckBox {{ spacing: 8px; color: {TEXT}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {BORDER_2}; background: {INPUT};
}}
QCheckBox::indicator:hover {{ border-color: {DIM}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
}}
QRadioButton {{ spacing: 6px; }}
QRadioButton::indicator {{
    width: 14px; height: 14px; border-radius: 999px;
    border: 1px solid {BORDER_2}; background: {INPUT};
}}
QRadioButton::indicator:checked {{
    background: {ACCENT}; border: 3px solid {CARD_2};
}}
QSpinBox, QDoubleSpinBox {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px;
}}
QDateEdit, QTimeEdit {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px;
}}
QListWidget#listPanel {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 4px; outline: 0;
}}
QListWidget#listPanel::item {{
    padding: 9px 10px; border-radius: 7px; margin: 1px 2px;
}}
QListWidget#listPanel::item:selected {{ background: {CARD_2}; border: 1px solid {ACCENT}; }}
QListWidget#listPanel::item:hover {{ background: {CARD_2}; }}
QTableWidget {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: {BORDER}; outline: 0;
}}
QTableWidget::item {{ padding: 6px; }}
QTableWidget::item:selected {{ background: {CARD_2}; color: {TEXT}; }}
QHeaderView::section {{
    background: {SIDEBAR}; color: {DIM};
    font-family: {MONO}; font-size: 10px; letter-spacing: 1.2px;
    border: none; border-bottom: 1px solid {BORDER};
    padding: 8px;
}}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_2}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_2}; border-radius: 5px; }}
QToolTip {{
    background: {CARD_3}; color: {TEXT}; border: 1px solid {BORDER_2};
    padding: 6px 8px; border-radius: 6px; font-size: 12px;
}}
QLabel#pageHeader {{ font-size: 18px; font-weight: 700; letter-spacing: -0.2px; }}
QLabel#monoHeader {{
    font-family: {MONO}; font-size: 10px; font-weight: 600; color: {DIM};
    letter-spacing: 2px;
}}
QLabel#sectionHeader {{
    font-family: {MONO}; font-size: 10px; font-weight: 700; color: {ACCENT_HOVER};
    letter-spacing: 2px; padding: 4px 0;
}}
QLabel#hintLabel {{ color: {FAINT}; font-size: 11px; }}
QLabel#chipLabel {{
    font-family: {MONO}; font-size: 10px;
    background: {CARD_2}; border: 1px solid {BORDER};
    border-radius: 999px; padding: 4px 10px; color: {DIM}; letter-spacing: 0.6px;
}}
QLabel#chipOk {{
    font-family: {MONO}; font-size: 10px;
    background: rgba(16, 185, 129, 0.10); border: 1px solid rgba(16, 185, 129, 0.35);
    border-radius: 999px; padding: 4px 10px; color: {GREEN}; letter-spacing: 0.6px;
}}
QLabel#chipWarn {{
    font-family: {MONO}; font-size: 10px;
    background: rgba(245, 158, 11, 0.10); border: 1px solid rgba(245, 158, 11, 0.35);
    border-radius: 999px; padding: 4px 10px; color: {AMBER}; letter-spacing: 0.6px;
}}
QLabel#chipBad {{
    font-family: {MONO}; font-size: 10px;
    background: rgba(239, 68, 68, 0.10); border: 1px solid rgba(239, 68, 68, 0.35);
    border-radius: 999px; padding: 4px 10px; color: #ff8a80; letter-spacing: 0.6px;
}}
QFrame#bubbleUser {{
    background: {USER_BUBBLE}; border-radius: 12px; border: 1px solid {BORDER_2};
}}
QFrame#bubbleAssistant {{
    background: {ASSISTANT_BUBBLE}; border-radius: 12px; border: 1px solid {BORDER};
}}
QFrame#bubbleTool {{
    background: {TOOL_BUBBLE}; border-radius: 10px; border: 1px solid {BORDER};
}}
QFrame#bubbleError {{
    background: {ERROR_BUBBLE}; border-radius: 10px; border: 1px solid rgba(239,68,68,0.4);
}}
QLabel#bubbleRole {{
    font-family: {MONO}; color: {FAINT}; font-size: 9px; font-weight: 600;
    letter-spacing: 1.4px;
}}
QLabel#bubbleText {{ font-size: 13px; }}
QLabel#toolText {{
    font-family: {MONO}; color: {DIM}; font-size: 11px; letter-spacing: 0.2px;
}}
QLabel#errorText {{ color: #ff9e9e; font-size: 12px; }}
QGroupBox {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px;
    margin-top: 14px; padding: 12px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {DIM};
    font-family: {MONO}; font-size: 10px; letter-spacing: 2px;
}}
QProgressBar {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 6px;
    text-align: center; color: {DIM}; font-size: 10px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
"""
