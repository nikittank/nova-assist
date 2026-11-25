"""Nova Assistant — exact "Pitch Black" design system.

Tokens distilled 1:1 from the uploaded HTML mockups
(nova_*_pitch_black.html). Pure black canvas, #0a0a0c/#0c0c0e panels,
hairline #1a1a1f borders, white primary buttons, emerald status pills,
Inter for UI text and JetBrains Mono for telemetry/labels.

Font scaling: the app ships at a slightly larger default (13px base on a
12px design baseline). All stylesheets must be written with literal
"design px" values and applied through set_style()/build_qss() — scaling
is applied centrally so the Font Size setting works live without
breaking any layout.
"""
from __future__ import annotations

import os
import re

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# ------------------------------------------------------------------ tokens
BLACK = "#000000"
PANEL = "#0a0a0c"          # containers / editors / lists
PANEL_2 = "#0c0c0e"        # cards, inputs, telemetry tiles
PANEL_3 = "#0d0d0f"        # inner items on cards
PANEL_HOVER = "#111115"
PANEL_ACTIVE = "#141418"   # active nav / user bubble
RAISED = "#181818"

BORDER = "#1a1a1f"         # subtle border (white/5-ish)
BORDER_2 = "#26262b"       # light border / icon buttons
BORDER_3 = "#272730"       # active border / user bubble border
BORDER_INPUT = "#22232b"

WIDGET_BG = "#101014"      # graphite card body for desktop widgets
WIDGET_BORDER = "#26262b"  # visible graphite separation on black
GRID_BG = "#0b0b0e"        # widgets-page grid cell background

WHITE = "#ffffff"
TEXT = "#d1d5db"           # gray-300 body
TEXT_BRIGHT = "#e5e7eb"
MUTED = "#9ca3af"          # neutral-400
FAINT = "#71717a"          # neutral-500
GHOST = "#52525b"          # neutral-600

EMERALD = "#34d399"        # emerald-400 dots / ok text
EMERALD_500 = "#10b981"
EMERALD_BG = "rgba(6, 78, 59, 0.30)"      # emerald-950/30-ish
EMERALD_BORDER = "rgba(16, 185, 129, 0.40)"

RED = "#ef4444"
RED_TEXT = "#f87171"
RED_SOFT = "#fca5a5"
ERROR_BG = "#13080a"
ERROR_BORDER = "#3b1216"
CODE_BG = "#08080a"
CODE_BORDER = "#1c1c24"

FOCUS_RING = "#3b82f6"     # settings inputs focus (mockup exact)

# Keep these stacks identical to nova_conversation_pitch_black.html.
FONT_SANS = "'-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', sans-serif"
FONT_MONO = "'JetBrains Mono', 'Fira Code', 'Consolas', 'Courier New', monospace"

SCROLL_THUMB = "#1f1f23"
SCROLL_THUMB_HOVER = "#2e2e36"

# ------------------------------------------------------------------ scale
# All UI stylesheets are authored against a 12px design baseline; the
# effective font size = baseline * FONT_SCALE. Default 13/12 (~+8%) per
# the "slightly larger default font" requirement.
FONT_BASE = 12.0
_scale = 14.0 / 12.0

_FS_RE = re.compile(r"font-size:\s*(\d+)px")


def set_font_scale(scale: float) -> None:
    """Set the live font scale (1.0 = 12px design baseline)."""
    global _scale
    _scale = max(0.8, min(2.2, float(scale)))


def font_scale() -> float:
    return _scale


def font_base_px() -> int:
    return max(8, round(FONT_BASE * _scale))


def fs(px: int) -> int:
    """Scale a design-baseline px font size for the current setting."""
    return max(8, int(round(px * _scale)))


def _rescale_css(css: str, scale: float) -> str:
    if abs(scale - 1.0) < 0.001:
        return css
    return _FS_RE.sub(
        lambda m: f"font-size: {max(8, round(int(m.group(1)) * scale))}px", css)


def set_style(widget, css: str) -> None:
    """setStyleSheet + record the unscaled css as the rescale baseline.

    Use this EVERYWHERE a per-widget stylesheet is assigned so the
    Settings font-size control can rescale the whole live UI. The css may
    be written with literal design-px sizes; scaling happens here.
    """
    widget.setStyleSheet(_rescale_css(css, _scale))
    widget.setProperty("fsBase", css)


def apply_unified_font(widget) -> None:
    """ONE-FONT RULE — force the technical (mono) font stack across a whole
    widget subtree.

    Nova uses a single typeface everywhere (titlebar, sidebar, and the
    standard pages): the same font as the technical/header UI. Qt style
    sheets cascade, so appending a `* { font-family }` rule on a container
    restyles the container AND every descendant, while anything outside the
    container (desktop widgets, the widgets page, the overlay) keeps its
    current font untouched. Existing per-widget rules that already pin
    FONT_MONO keep resolving to the same family.

    Safe to call once at construction; the appended rule carries no font
    sizes, so the font-size scaling system is unaffected.
    """
    extra = f"* {{ font-family: {FONT_SANS}; }}"
    base = widget.property("fsBase")
    if isinstance(base, str) and base:
        widget.setProperty("fsBase", base + "\n" + extra)
        widget.setStyleSheet(_rescale_css(base + "\n" + extra, _scale))
    else:
        cur = widget.styleSheet()
        merged = (cur + "\n" + extra) if cur else extra
        widget.setStyleSheet(merged)
        widget.setProperty("fsBase", merged)


def apply_scale_to_tree(root) -> int:
    """Re-apply the current font scale to every stylesheet under `root`.

    Call after construction and whenever the scale changes. Styles are
    recomputed from each widget's recorded baseline, so repeated calls are
    idempotent. Returns the number of widgets touched.
    """
    count = 0
    from PySide6.QtWidgets import QWidget
    try:
        # NOTE: findChildren(QWidget) — every descendant, not just widgets
        # of the root's own type (the previous type(root) call matched no
        # descendants at all, so per-widget sizes never rescaled).
        widgets = [root, *root.findChildren(QWidget)]
    except Exception:
        return 0
    seen = set()
    for w in widgets:
        if not isinstance(w, QWidget) or w in seen:
            continue
        seen.add(w)
        base = w.property("fsBase")
        cur = w.styleSheet()
        if base is None:
            if "font-size" not in cur:
                continue
            base = cur
            w.setProperty("fsBase", base)
        new = _rescale_css(base, _scale)
        if new != cur:
            w.setStyleSheet(new)
            count += 1
    return count


def apply_dark_palette(app) -> None:
    """Force the pitch-black palette everywhere QSS doesn't reach (Qt paints
    plain QWidget backgrounds from the palette once a stylesheet is active)."""
    from PySide6.QtGui import QColor, QPalette

    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(BLACK))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(PANEL_2))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL))
    pal.setColor(QPalette.Text, QColor(TEXT_BRIGHT))
    pal.setColor(QPalette.PlaceholderText, QColor("#6b7280"))
    pal.setColor(QPalette.Button, QColor("#0d0d0f"))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ToolTipBase, QColor(PANEL_2))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT_BRIGHT))
    pal.setColor(QPalette.BrightText, QColor(RED_TEXT))
    pal.setColor(QPalette.Highlight, QColor("#2f2f36"))
    pal.setColor(QPalette.HighlightedText, QColor(WHITE))
    pal.setColor(QPalette.Link, QColor(FOCUS_RING))
    pal.setColor(QPalette.PlaceholderText, QColor("#6b7280"))
    app.setPalette(pal)


def build_qss() -> str:
    """Global application stylesheet replicating the mockup look.

    All font sizes go through fs() so the Settings font-size control works
    globally; per-widget stylesheets use theme.set_style() for the same
    reason.
    """
    return f"""
* {{
    font-family: {FONT_SANS};
    font-size: {fs(12)}px;
    color: {TEXT};
    selection-background-color: #2f2f36;
    selection-color: {WHITE};
    outline: none;
}}
QMainWindow {{ background: {BLACK}; }}
QWidget#RootWindow {{ background: {BLACK}; }}
QWidget#Panel {{ background: {PANEL}; }}
QToolTip {{
    background: {PANEL_2}; color: {TEXT_BRIGHT};
    border: 1px solid {BORDER_2}; font-size: {fs(11)}px; padding: 4px 8px;
}}

/* ---------------------------------------------------------- labels */
QLabel {{ background: transparent; }}
QLabel[role="display"] {{ color: {WHITE}; font-size: {fs(20)}px; font-weight: 800; letter-spacing: -0.2px; }}
QLabel[role="title"] {{ color: {WHITE}; font-size: {fs(16)}px; font-weight: 700; }}
QLabel[role="strong"] {{ color: {WHITE}; font-weight: 600; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="faint"] {{ color: {FAINT}; }}
QLabel[role="tiny"] {{ color: {FAINT}; font-size: {fs(10)}px; }}
QLabel[role="overline"] {{
    color: {MUTED}; font-size: {fs(10)}px; font-weight: 700;
    letter-spacing: 1.2px; text-transform: uppercase;
}}
QLabel[role="mono"] {{ font-family: {FONT_MONO}; }}
QLabel[role="monoMuted"] {{ font-family: {FONT_MONO}; color: {FAINT}; font-size: {fs(10)}px; }}
QLabel[role="monoTiny"] {{
    font-family: {FONT_MONO}; color: {FAINT};
    font-size: {fs(9)}px; letter-spacing: 1.5px; text-transform: uppercase;
}}
QLabel[role="monoBright"] {{ font-family: {FONT_MONO}; color: {TEXT_BRIGHT}; }}
QLabel[role="ok"] {{ color: {EMERALD}; }}
QLabel[role="err"] {{ color: {RED_TEXT}; }}

/* --------------------------------------------------------- buttons */
QPushButton {{ background: transparent; border: none; padding: 0; }}
QPushButton[variant="primary"] {{
    background: {WHITE}; color: {BLACK}; font-weight: 600;
    border: none; border-radius: 8px; padding: 8px 16px; font-size: {fs(12)}px;
}}
QPushButton[variant="primary"]:hover {{ background: #e5e5e5; }}
QPushButton[variant="primary"]:pressed {{ background: #d4d4d4; }}
QPushButton[variant="primary"]:disabled {{ background: #3f3f46; color: #18181b; }}

QPushButton[variant="ghost"] {{
    background: #0d0d0f; color: #d4d4d8; border: 1px solid {BORDER};
    border-radius: 8px; padding: 7px 14px; font-size: {fs(12)}px; font-weight: 500;
}}
QPushButton[variant="ghost"]:hover {{ background: #141414; border-color: #4b4b52; color: {WHITE}; }}
QPushButton[variant="ghost"]:pressed {{ background: #1a1a1a; }}

QPushButton[variant="danger"] {{
    background: #0d0d0f; color: #a1a1aa; border: 1px solid {BORDER_2};
    border-radius: 8px; padding: 7px 14px; font-size: {fs(12)}px; font-weight: 500;
}}
QPushButton[variant="danger"]:hover {{ background: #1a0d10; border-color: #4a1d24; color: {RED_TEXT}; }}

QPushButton[variant="chip"] {{
    background: #0d0d0f; color: {MUTED}; border: 1px solid {BORDER_2};
    border-radius: 6px; padding: 5px 10px; font-size: {fs(11)}px;
}}
QPushButton[variant="chip"]:hover {{ background: {WHITE}; color: {BLACK}; border-color: {WHITE}; }}

QPushButton[variant="icon"] {{
    background: transparent; border: none; border-radius: 8px; padding: 6px;
}}
QPushButton[variant="icon"]:hover {{ background: #1f1f23; }}
QPushButton[variant="icon"]:pressed {{ background: #26262b; }}

QPushButton[variant="titlebtn"] {{
    background: transparent; border: none; border-radius: 6px; padding: 0;
}}
QPushButton[variant="titlebtn"]:hover {{ background: #1f1f23; }}

QPushButton[variant="roundMic"] {{
    background: {WHITE}; border: none; border-radius: 24px;
}}
QPushButton[variant="roundMic"]:hover {{ background: #e5e5e5; }}

/* ----------------------------------------------------------- inputs */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {PANEL_2}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 8px 12px; font-size: {fs(12)}px; color: {TEXT_BRIGHT};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {WHITE}; }}
QLineEdit[role="mono"] {{ font-family: {FONT_MONO}; }}
QLineEdit[role="flat"], QTextEdit[role="flat"] {{
    background: transparent; border: none; padding: 0;
}}
QTextEdit[role="editor"] {{
    background: transparent; border: none; padding: 0;
    font-family: {FONT_MONO}; font-size: {fs(12)}px; color: #d4d4d8; line-height: 1.6;
}}
QLineEdit:disabled, QTextEdit:disabled {{ color: {GHOST}; }}

QComboBox {{
    background: {PANEL_2}; border: 1px solid {BORDER_INPUT};
    border-radius: 8px; padding: 7px 28px 7px 12px; font-size: {fs(12)}px; color: {TEXT_BRIGHT};
}}
QComboBox:hover {{ border-color: #3a3a44; }}
QComboBox:focus {{ border: 1px solid {WHITE}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    image: url(:/noop); width: 0; height: 0;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {FAINT}; margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background: #0c0c0e; border: 1px solid {BORDER_2}; border-radius: 8px;
    color: {TEXT_BRIGHT}; selection-background-color: #1f1f23;
    selection-color: {WHITE}; outline: none; padding: 4px;
}}

/* ---------------------------------------------------------- slider */
QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{
    height: 4px; border-radius: 2px; background: #1f1f24;
}}
QSlider::sub-page:horizontal {{
    background: #e5e5e5; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {WHITE}; width: 14px; height: 14px; margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QSlider::groove:vertical {{ width: 4px; border-radius: 2px; background: #1f1f24; }}
QSlider::handle:vertical {{ background: {WHITE}; height: 14px; width: 14px; margin: 0 -5px; border-radius: 7px; }}

/* -------------------------------------------------------- checkbox */
QCheckBox {{ spacing: 10px; background: transparent; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid #3f3f46; background: #0d0d10;
}}
QCheckBox::indicator:hover {{ border-color: #71717a; }}
QCheckBox::indicator:checked {{
    background: {FOCUS_RING}; border-color: {FOCUS_RING};
    image: url({ASSETS_DIR.replace(chr(92), '/')}/check.svg);
}}
QCheckBox::indicator:checked:disabled {{ background: #27272a; border-color: #27272a; }}

/* ------------------------------------------------------ scrollbars */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: {BLACK}; width: 6px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {SCROLL_THUMB}; border-radius: 3px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {SCROLL_THUMB_HOVER}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ background: {BLACK}; height: 6px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {SCROLL_THUMB}; border-radius: 3px; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: {SCROLL_THUMB_HOVER}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ------------------------------------------------------ separators */
QFrame[frameShape="4"] {{ border: none; }}          /* HLine */
QFrame[hline="thin"] {{ border: none; border-top: 1px solid {BORDER}; }}
QFrame[hline="faint"] {{ border: none; border-top: 1px solid rgba(255,255,255,0.05); }}

/* ------------------------------------------------------------ misc */
QProgressBar {{
    background: #141416; border: none; border-radius: 3px;
    height: 6px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {WHITE}; border-radius: 3px; }}
QSplitter::handle {{ background: {BORDER}; }}
QMenu {{
    background: #0c0c0e; border: 1px solid {BORDER_2}; border-radius: 10px; padding: 6px;
}}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; color: {TEXT}; }}
QMenu::item:selected {{ background: #1f1f23; color: {WHITE}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
QSystemTrayIcon {{ }}
"""
