"""Design tokens and the global style sheet.

One calm, clinical dark theme: deep slate surfaces that recede behind the 3D model, a single teal accent for
"this is interactive / this is selected", and semantic colours (success, warning, danger, info) that mean the
same thing in every panel. Everything that paints colour - QSS here, inline setStyleSheet calls, HTML/CSS in
the text browsers and QPainter code - takes it from the tokens below, so a colour is changed in one place.

Scales
    colour      CANVAS < SUNKEN < SURFACE < RAISED < HOVER < PRESSED   (elevation by lightness; QSS has no shadows)
    type (pt)   FS_CAPTION 8 · FS_SMALL 8.5 · FS_BODY 9.5 · FS_LEAD 10.5 · FS_TITLE 12.5 · FS_H2 15 · FS_H1 17
    spacing     SP_1 4 · SP_2 8 · SP_3 12 · SP_4 16 · SP_5 24   (px, 4-px rhythm)
    radius      R_SM 4 · R_MD 6 · R_LG 8 · R_XL 12
"""
import sys
import tempfile
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

# ---------------------------------------------------------------------------------------------- colour tokens
# surfaces, darkest to lightest
CANVAS = "#0b1016"          # app chrome: menu bar, toolbar, status bar, dock title bars
SUNKEN = "#0e141b"          # wells: text fields, combo boxes, image frames
SURFACE = "#121922"         # panel background
RAISED = "#18212c"          # cards, list rows, buttons
HOVER = "#1f2a37"           # hover on raised things
PRESSED = "#263444"         # pressed / open
OVERLAY = "#18222d"         # menus, tooltips, floating cards

# lines
BORDER_SUBTLE = "#1c2632"
BORDER = "#2a3746"
BORDER_STRONG = "#3b4c60"

# text (contrast on SURFACE: TEXT 14:1, TEXT_2 8.4:1, MUTED 5.3:1, FAINT 3.3:1 - FAINT is for disabled only)
TEXT_STRONG = "#f3f6f9"
TEXT = "#dfe6ee"
TEXT_2 = "#b2bdca"
MUTED = "#8494a7"
FAINT = "#5c6b7e"

# accent: a calm clinical teal
ACCENT = "#3cc6d3"
ACCENT_HOVER = "#62d5df"
ACCENT_PRESSED = "#2aa8b5"
ACCENT_TEXT = "#7fdce5"     # links and accent-coloured text on dark surfaces
ACCENT_SOFT = "#0f2f37"     # selected / checked background
ACCENT_SOFT_HOVER = "#143b45"
ACCENT_BORDER = "#1f6973"
ON_ACCENT = "#04191d"       # text on a filled accent

# semantic
SUCCESS = "#5bd49a"
SUCCESS_FILL = "#1b5a3d"
SUCCESS_SOFT = "#11301f"
WARNING = "#f0b45c"
WARNING_SOFT = "#33260f"
DANGER = "#ff8f86"
DANGER_FILL = "#6e2a2c"
DANGER_SOFT = "#361619"
INFO = "#86b8f5"
ON_TINT = "#0b1116"         # dark text on a light coloured tag

# study-level tags and the coloured left edges of lesson panels (hue carries meaning, so these are fixed)
LEVEL = {"foundation": "#8fd1a0", "core": "#86b8f5", "advanced": "#eea871"}
TOPIC = {"objectives": ACCENT, "mnemonic": WARNING, "pitfall": "#ee8a92", "clinical": SUCCESS,
         "takeaways": SUCCESS, "related": "#8d9bb0"}

# legacy names still imported by some modules
BG = CANVAS
PANEL = SURFACE
PANEL_2 = RAISED

# ---------------------------------------------------------------------------------------------- type / space
FS_CAPTION = 8.0
FS_SMALL = 8.5
FS_BODY = 9.5
FS_LEAD = 10.5
FS_TITLE = 12.5
FS_H2 = 15.0
FS_H1 = 17.0

SP_1, SP_2, SP_3, SP_4, SP_5 = 4, 8, 12, 16, 24
R_SM, R_MD, R_LG, R_XL = 4, 6, 8, 12

# system UI fonts only: Segoe UI on Windows, the system font on macOS, Inter / Noto if a Linux box has them
_FONT_PREFS = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans"]
FONT_FAMILY = None


def font_family():
    global FONT_FAMILY
    if FONT_FAMILY is None:
        if sys.platform == "darwin":
            FONT_FAMILY = QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
        else:
            have = set(QFontDatabase.families())
            FONT_FAMILY = next((f for f in _FONT_PREFS if f in have),
                               QFontDatabase.systemFont(QFontDatabase.GeneralFont).family())
    return FONT_FAMILY


def qc(token, alpha=None):
    """A QColor from a token, optionally with alpha 0-255."""
    c = QColor(token)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def text_css(color=TEXT_2, size=None, weight=None):
    """An inline style for a label: `lab.setStyleSheet(text_css(MUTED, FS_SMALL))`."""
    s = f"color:{color};"
    if size:
        s += f" font-size:{size}pt;"
    if weight:
        s += f" font-weight:{weight};"
    return s


def overline_css(color=MUTED):
    """Small section label (the text itself is written in upper case)."""
    return f"color:{color}; font-size:{FS_CAPTION}pt; font-weight:700; letter-spacing:1px;"


def tag_css(bg, fg=ON_TINT):
    """A small filled pill (level, question kind, modality)."""
    return (f"color:{fg}; background:{bg}; border-radius:{R_SM}px; padding:2px 8px; "
            f"font-size:{FS_SMALL}pt; font-weight:700;")


def well_css(fg=TEXT, pad=SP_2):
    """An inset box (answers, check-yourself)."""
    return (f"background:{RAISED}; border:1px solid {BORDER}; border-radius:{R_LG}px; padding:{pad}px; "
            f"color:{fg};")


def set_variant(button, variant):
    """Give a QPushButton one of the style sheet's variants: primary, success, danger, ghost."""
    button.setProperty("variant", variant)
    st = button.style()
    st.unpolish(button)
    st.polish(button)


# ---------------------------------------------------------------------------------------------- vector glyphs
# small SVGs for the style sheet (check marks, chevrons), written once to a temp folder so QSS can url() them
def _stroke(d, color, w=1.8):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="{d}" fill="none" '
            f'stroke="{color}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/></svg>')


_SVG = {
    "check": _stroke("M3.6 8.4l2.9 2.9 6-6.2", ON_ACCENT, 2.2),
    "dash": _stroke("M4 8h8", ON_ACCENT, 2.2),
    "chev_down": _stroke("M4.5 6.2L8 9.8l3.5-3.6", MUTED),
    "chev_up": _stroke("M4.5 9.8L8 6.2l3.5 3.6", MUTED),
    "chev_right": _stroke("M6.2 4.5L9.8 8l-3.6 3.5", MUTED),
    "close": _stroke("M4.8 4.8l6.4 6.4M11.2 4.8l-6.4 6.4", MUTED, 1.6),
    "close_hover": _stroke("M4.8 4.8l6.4 6.4M11.2 4.8l-6.4 6.4", TEXT_STRONG, 1.6),
    "back": _stroke("M10 3.5L5.5 8l4.5 4.5", TEXT_2),
    "forward": _stroke("M6 3.5L10.5 8 6 12.5", TEXT_2),
    "settings": (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="{TEXT_2}" '
                 f'stroke-width="1.4" stroke-linecap="round"><circle cx="8" cy="8" r="2.1"/>'
                 f'<path d="M8 1.6v2M8 12.4v2M1.6 8h2M12.4 8h2M3.5 3.5l1.4 1.4M11.1 11.1l1.4 1.4'
                 f'M3.5 12.5l1.4-1.4M11.1 4.9l1.4-1.4"/></svg>'),
}
_glyph_dir = None


def glyph(name):
    """Path (forward slashes) of a theme glyph SVG, or '' if it could not be written."""
    global _glyph_dir
    if _glyph_dir is None:
        _glyph_dir = ""
        try:
            d = Path(tempfile.gettempdir()) / "anatomy-explorer-theme"
            d.mkdir(parents=True, exist_ok=True)
            for k, svg in _SVG.items():
                p = d / f"{k}.svg"
                if not p.exists() or p.read_text(encoding="utf-8") != svg:
                    p.write_text(svg, encoding="utf-8")
            _glyph_dir = d.as_posix()
        except OSError:
            pass
    return f"{_glyph_dir}/{name}.svg" if _glyph_dir else ""


def icon(name):
    p = glyph(name)
    return QIcon(p) if p else QIcon()


def _img(name):
    p = glyph(name)
    return f'image: url("{p}");' if p else "image: none;"


# ---------------------------------------------------------------------------------------------- style sheet
def build_stylesheet(scale=1.0):
    fs = FS_BODY * scale
    small = FS_SMALL * scale
    ff = font_family()
    return f"""
QMainWindow, QWidget {{ background: {SURFACE}; color: {TEXT}; font-family: "{ff}"; font-size: {fs:.2f}pt; }}
QMainWindow::separator {{ background: {BORDER_SUBTLE}; width: 1px; height: 1px; }}
QMainWindow::separator:hover {{ background: {ACCENT_BORDER}; }}
QLabel {{ background: transparent; }}
QScrollArea {{ border: none; }}

/* ---- chrome */
QMenuBar {{ background: {CANVAS}; color: {TEXT_2}; padding: 2px 4px; border: none; }}
QMenuBar::item {{ background: transparent; padding: 4px 10px; border-radius: {R_SM}px; }}
QMenuBar::item:selected {{ background: {HOVER}; color: {TEXT_STRONG}; }}
QMenuBar::item:pressed {{ background: {PRESSED}; color: {TEXT_STRONG}; }}
QToolBar {{ background: {CANVAS}; border: none; border-bottom: 1px solid {BORDER_SUBTLE}; spacing: 2px;
            padding: 4px 8px; }}
QToolBar QWidget {{ background: transparent; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 7px 8px; }}
QToolBar QToolButton {{ background: transparent; color: {TEXT_2}; border: 1px solid transparent;
                        border-radius: {R_MD}px; padding: 5px 10px; font-weight: 600; }}
QToolBar QToolButton:hover {{ background: {HOVER}; color: {TEXT_STRONG}; border-color: transparent; }}
QToolBar QToolButton:pressed, QToolBar QToolButton:open {{ background: {PRESSED}; color: {TEXT_STRONG}; }}
QToolBar QToolButton:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT_BORDER}; color: {ACCENT_TEXT}; }}
QToolBar QToolButton[active="true"] {{ background: {ACCENT_SOFT}; border-color: {ACCENT_BORDER}; color: {ACCENT_TEXT}; }}
QToolBar QToolButton:focus {{ border-color: {ACCENT}; }}
QToolBar QToolButton:disabled {{ color: {FAINT}; background: transparent; }}
QToolBar QToolButton::menu-indicator {{ image: none; width: 0; }}
QStatusBar {{ background: {CANVAS}; color: {MUTED}; border-top: 1px solid {BORDER_SUBTLE}; font-size: {small:.2f}pt; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 10px; background: transparent; }}
QStatusBar::item {{ border: none; }}
QSizeGrip {{ background: transparent; width: 10px; height: 10px; }}
QDockWidget {{ titlebar-close-icon: none; color: {MUTED}; }}
QDockWidget::title {{ background: {CANVAS}; padding: 8px 12px 7px 14px; color: {MUTED};
                      border-bottom: 1px solid {BORDER_SUBTLE}; }}
QDockWidget::float-button, QDockWidget::close-button {{ background: transparent; border: none;
                      border-radius: {R_SM}px; padding: 2px; }}
QDockWidget::float-button:hover, QDockWidget::close-button:hover {{ background: {HOVER}; }}

/* ---- tabs */
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER_SUBTLE}; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 8px 14px; border: none;
                border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT_STRONG}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::close-button {{ {_img("close")} subcontrol-position: right; border-radius: {R_SM}px; margin: 2px; }}
QTabBar::close-button:hover {{ {_img("close_hover")} background: {DANGER_FILL}; }}

/* Explore panel: underline tabs over a segmented track */
QPushButton#navTab {{ background: transparent; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                      border-radius: 0; padding: 8px 2px 8px 2px; font-weight: 700; }}
QPushButton#navTab:hover {{ color: {TEXT}; border-bottom-color: {BORDER_STRONG}; }}
QPushButton#navTab:checked {{ color: {TEXT_STRONG}; border-bottom: 2px solid {ACCENT}; padding-bottom: 7px; }}
QPushButton#navTab:focus {{ color: {ACCENT_TEXT}; }}
QWidget#navSegTrack {{ background: {SUNKEN}; border: 1px solid {BORDER_SUBTLE}; border-radius: {R_LG}px; }}
QPushButton#navSeg {{ background: transparent; color: {MUTED}; border: 1px solid transparent; border-radius: {R_MD}px;
                      padding: 4px 2px; font-size: {small:.2f}pt; font-weight: 600; }}
QPushButton#navSeg:hover {{ color: {TEXT}; background: {RAISED}; }}
QPushButton#navSeg:checked {{ color: {TEXT_STRONG}; background: {PRESSED}; border-color: {BORDER_STRONG}; }}
QPushButton#navSeg:focus {{ border-color: {ACCENT}; }}

/* ---- lists and trees */
QListWidget, QTreeWidget, QTreeView, QListView, QTextBrowser {{ background: {SURFACE}; border: none; outline: none;
                      selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT_STRONG}; }}
QTreeWidget::item, QTreeView::item {{ padding: 3px 0; }}
QTreeWidget::item:hover, QTreeView::item:hover, QListWidget::item:hover {{ background: {RAISED}; }}
QTreeWidget::item:selected, QTreeView::item:selected, QListWidget::item:selected {{ background: {ACCENT_SOFT};
                      color: {TEXT_STRONG}; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:has-children:!has-siblings:closed, QTreeView::branch:closed:has-children:has-siblings {{
                      border-image: none; {_img("chev_right")} }}
QTreeView::branch:open:has-children:!has-siblings, QTreeView::branch:open:has-children:has-siblings {{
                      border-image: none; {_img("chev_down")} }}
QHeaderView::section {{ background: {CANVAS}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER_SUBTLE};
                      padding: 5px 6px; font-weight: 600; }}
QTextEdit, QPlainTextEdit {{ background: {SUNKEN}; border: 1px solid {BORDER}; border-radius: {R_LG}px; padding: 4px;
                      selection-background-color: {ACCENT_BORDER}; selection-color: {TEXT_STRONG}; }}
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QTableWidget, QTableView {{ background: {SURFACE}; border: none; gridline-color: {BORDER_SUBTLE};
                      selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT_STRONG}; }}
QTableCornerButton::section {{ background: {CANVAS}; border: none; }}
QTextBrowser, QTextBrowser:focus {{ background: {SURFACE}; border: none; border-radius: 0; padding: 0;
                      selection-background-color: {ACCENT_BORDER}; selection-color: {TEXT_STRONG}; }}

/* ---- scroll bars: thin, rounded, quiet until hovered */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 1px 2px 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 3px; min-height: 32px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:vertical:pressed {{ background: {BORDER_STRONG}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0 2px 1px 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 3px; min-width: 32px; margin: 2px 0; }}
QScrollBar::handle:horizontal:hover, QScrollBar::handle:horizontal:pressed {{ background: {BORDER_STRONG}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- buttons */
QPushButton, QToolButton {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: {R_MD}px;
                      padding: 5px 10px; color: {TEXT}; }}
QPushButton:hover, QToolButton:hover {{ background: {HOVER}; border-color: {BORDER_STRONG}; color: {TEXT_STRONG}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {PRESSED}; }}
QPushButton:focus, QToolButton:focus {{ border-color: {ACCENT}; }}
QPushButton:checked, QToolButton:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT_BORDER}; color: {ACCENT_TEXT}; }}
QPushButton:checked:hover, QToolButton:checked:hover {{ background: {ACCENT_SOFT_HOVER}; }}
QPushButton:disabled, QToolButton:disabled {{ background: {SURFACE}; border-color: {BORDER_SUBTLE}; color: {FAINT}; }}
QPushButton::menu-indicator, QToolButton::menu-indicator {{ image: none; width: 0; }}
QPushButton#dropButton {{ text-align: left; padding-left: 10px; background: {SUNKEN}; }}
QPushButton#dropButton:hover {{ background: {RAISED}; }}
QPushButton[variant="primary"] {{ background: {ACCENT}; border-color: {ACCENT}; color: {ON_ACCENT}; font-weight: 700; }}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; color: {ON_ACCENT}; }}
QPushButton[variant="primary"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton[variant="primary"]:focus {{ border-color: {TEXT_STRONG}; }}
QPushButton[variant="primary"]:disabled {{ background: {RAISED}; border-color: {BORDER_SUBTLE}; color: {FAINT}; }}
QPushButton[variant="success"] {{ background: {SUCCESS_FILL}; border-color: #2a7a53; color: {TEXT_STRONG}; font-weight: 700; }}
QPushButton[variant="success"]:hover {{ background: #22704c; border-color: {SUCCESS}; }}
QPushButton[variant="success"]:pressed {{ background: #174d34; }}
QPushButton[variant="success"]:disabled, QPushButton[variant="danger"]:disabled {{ background: {RAISED};
                      border-color: {BORDER_SUBTLE}; color: {FAINT}; }}
QPushButton[variant="danger"] {{ background: {DANGER_FILL}; border-color: #8e3a3c; color: {TEXT_STRONG}; }}
QPushButton[variant="danger"]:hover {{ background: #803234; border-color: {DANGER}; }}
QPushButton[variant="ghost"] {{ background: transparent; border-color: transparent; color: {TEXT_2}; }}
QPushButton[variant="ghost"]:hover {{ background: {HOVER}; color: {TEXT_STRONG}; }}
QPushButton:flat {{ background: transparent; border-color: transparent; color: {TEXT_2}; padding: 5px 8px; }}
QPushButton:flat:hover {{ background: {HOVER}; color: {TEXT_STRONG}; }}
QPushButton:flat:focus {{ border-color: {ACCENT}; }}
QPushButton[chip="true"] {{ background: transparent; border: 1px solid {BORDER}; border-radius: 12px; padding: 3px 9px;
                      color: {TEXT_2}; font-size: {small:.2f}pt; font-weight: 600; }}
QPushButton[chip="true"]:hover {{ background: {RAISED}; border-color: {BORDER_STRONG}; color: {TEXT_STRONG}; }}
QPushButton[chip="true"]:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT_BORDER}; color: {ACCENT_TEXT}; }}
QPushButton[chip="true"]:focus {{ border-color: {ACCENT}; }}
QToolButton#expander {{ border: none; background: transparent; color: {MUTED}; padding: 0; }}
QToolButton#expander:hover {{ color: {ACCENT_TEXT}; }}
QDialogButtonBox {{ dialogbuttonbox-buttons-have-icons: 0; }}

/* ---- inputs */
QLineEdit {{ background: {SUNKEN}; border: 1px solid {BORDER}; border-radius: {R_LG}px; padding: 7px 11px;
             color: {TEXT_STRONG}; selection-background-color: {ACCENT_BORDER}; }}
QLineEdit:hover {{ border-color: {BORDER_STRONG}; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ color: {FAINT}; }}
QComboBox {{ background: {SUNKEN}; border: 1px solid {BORDER}; border-radius: {R_MD}px; padding: 5px 10px;
             color: {TEXT}; }}
QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QComboBox:focus, QComboBox:on {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ {_img("chev_down")} width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {OVERLAY}; border: 1px solid {BORDER_STRONG}; outline: none; padding: 4px;
             selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT_STRONG}; }}
QAbstractSpinBox {{ background: {SUNKEN}; border: 1px solid {BORDER}; border-radius: {R_MD}px; padding: 4px 6px;
             color: {TEXT}; selection-background-color: {ACCENT_BORDER}; }}
QAbstractSpinBox:hover {{ border-color: {BORDER_STRONG}; }}
QAbstractSpinBox:focus {{ border-color: {ACCENT}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ background: transparent; border: none; width: 16px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {HOVER}; }}
QAbstractSpinBox::up-arrow {{ {_img("chev_up")} width: 10px; height: 10px; }}
QAbstractSpinBox::down-arrow {{ {_img("chev_down")} width: 10px; height: 10px; }}

QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox:focus, QRadioButton:focus {{ color: {TEXT_STRONG}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: {R_SM}px; border: 1px solid {BORDER_STRONG};
             background: {SUNKEN}; }}
QCheckBox::indicator:hover, QCheckBox::indicator:focus {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; {_img("check")} }}
QCheckBox::indicator:checked:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QCheckBox::indicator:indeterminate {{ background: {ACCENT_BORDER}; border-color: {ACCENT_BORDER}; {_img("dash")} }}
QCheckBox::indicator:disabled {{ background: {SURFACE}; border-color: {BORDER_SUBTLE}; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid {BORDER_STRONG};
             background: {SUNKEN}; }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border: 4px solid {SUNKEN}; }}
QTreeView::indicator {{ width: 13px; height: 13px; border-radius: 3px; border: 1px solid {BORDER_STRONG};
             background: {SUNKEN}; }}
QTreeView::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; {_img("check")} }}
QTreeView::indicator:indeterminate {{ background: {ACCENT_BORDER}; border-color: {ACCENT_BORDER}; {_img("dash")} }}

QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT_PRESSED}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT_STRONG}; border: 2px solid {ACCENT}; width: 10px; height: 10px;
             margin: -6px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HOVER}; }}
QSlider::handle:horizontal:disabled {{ background: {FAINT}; border-color: {BORDER}; }}
QSlider::sub-page:horizontal:disabled {{ background: {BORDER_STRONG}; }}

QGroupBox {{ border: 1px solid {BORDER}; border-radius: {R_LG}px; margin-top: 16px; padding: 12px 10px 10px 10px;
             background: transparent; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {MUTED}; font-weight: 700; }}

/* ---- popups */
QMenu {{ background: {OVERLAY}; border: 1px solid {BORDER_STRONG}; padding: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: {R_MD}px; color: {TEXT}; background: transparent; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT_STRONG}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
QToolTip {{ background: {OVERLAY}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 6px 8px; }}
QDialog {{ background: {SURFACE}; }}
"""


def apply_theme(app: QApplication, scale=1.0):
    app.setStyle(QStyleFactory.create("Fusion"))
    f = QFont(font_family())
    f.setPointSizeF(FS_BODY * scale)
    app.setFont(f)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(SURFACE))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(SUNKEN))
    pal.setColor(QPalette.AlternateBase, QColor(RAISED))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.BrightText, QColor(TEXT_STRONG))
    pal.setColor(QPalette.Button, QColor(RAISED))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT_BORDER))
    pal.setColor(QPalette.HighlightedText, QColor(TEXT_STRONG))
    pal.setColor(QPalette.ToolTipBase, QColor(OVERLAY))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.Link, QColor(ACCENT_TEXT))
    pal.setColor(QPalette.LinkVisited, QColor(ACCENT_TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    pal.setColor(QPalette.Mid, QColor(BORDER))
    pal.setColor(QPalette.Dark, QColor(CANVAS))
    pal.setColor(QPalette.Light, QColor(BORDER_STRONG))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(FAINT))
    app.setPalette(pal)
    app.setStyleSheet(build_stylesheet(scale))
