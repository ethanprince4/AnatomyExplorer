"""Native styling for the chosen Specimen world.

Colors and identity assets come from the approved design package. This module
styles chrome and surfaces only; model geometry and materials remain owned by
the renderer.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QIcon

ROOT = Path(__file__).parent / "resources" / "studio"
RAIL_WIDTH = 104


def palette(mode=None):
    """Return the active wall plus the legacy studio aliases used by panels."""
    from . import theme

    p = theme.palette(mode)
    return {
        **p,
        # Legacy panel aliases must continue the selected wall. The archived
        # card tokens are pale, which is not the Specimen surface treatment.
        "card": p["surface"], "card_text": p["text"], "card_text_2": p["text_2"],
        "bg": p["stage_bottom"], "deep": p["surface_2"], "raised": p["surface_3"],
        "muted": p["text_2"], "edge": p["line_2"], "selected": p["accent_soft"],
        "ink": p["on_accent"], "coral": "#e69a91", "mint": "#8fd6b4", "lilac": "#b6a5d8",
        "paper": p["surface"], "paper_text": p["text"], "paper_muted": p["text_2"],
        "tool": p["surface_2"], "tool_edge": p["line_2"], "header": p["surface"],
        "input": p["sunken"], "input_border": p["line_2"], "preview": p["stage_bottom"],
        "row_edge": p["line"], "paper_action": p["accent"], "on_paper_action": p["on_accent"],
        "stage_text": p["text"], "stage_muted": p["text_2"],
    }


def display_font_family():
    from .theme import display_font_family as family
    return family()


def display_css(size=34, color=None, weight=400, optical_size=None):
    from . import theme

    p = palette()
    family = display_font_family()
    # Qt's stylesheet engine does not parse CSS font-variation-settings. Variable
    # axis values are applied through theme.font_for() on the actual QFont.
    return (f'font-family:"{family}";font-size:{size}px;font-weight:{weight};'
            f'color:{color or p["text"]};background:transparent;')


_NAV_ICONS = {"atlas", "lessons", "models", "radiology", "histology", "practice", "bookmark", "more", "back", "forward"}


def icon(name, mode=None):
    """Load a bundled vector mark or UI glyph for the selected wall."""
    from . import theme

    name = {"layers": "parts", "eye": "labels", "ruler": "measure", "explore": "atlas",
            "collection": "models", "saved": "bookmark", "menu": "more"}.get(name, name)
    if name == "brand":
        path = ROOT / "brand" / "symbol.svg"
    elif name in _NAV_ICONS:
        path = ROOT / "icons" / "specimen" / (name + ".svg")
    else:
        path = ROOT / "icons" / "graphite" / (name + ".svg")
    return QIcon(str(path)) if path.is_file() else QIcon()


def apply_surface(widget, name="surface"):
    """Style an existing widget without replacing its layout or content."""
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setObjectName(name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget


def build_stylesheet(scale=1.0):
    p = palette()
    menu_arrow = (ROOT / "icons" / "graphite" / "down.svg").as_posix()
    wall = (f'qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {p["stage_top"]},'
            f'stop:1 {p["stage_bottom"]})')
    return f'''
/* One continuous gallery wall; no light panels interrupt the stage. */
QWidget#studioShell, QWidget#studioWorkspaces, QWidget#studioWorkspaces::pane,
QWidget#studioCollection, QWidget#studioScene {{ background:{wall}; color:{p['text']}; border:0; }}
QWidget#studioHeader {{ background:transparent; color:{p['text']}; }}
QWidget#studioRail {{ background:transparent; border-right:1px solid {p['hair']}; }}
QWidget#studioRailMark {{ background:transparent; border:0; }}
QToolButton#studioRailRoom, QToolButton#studioRailUtility {{
  background:transparent; color:{p['text_2']}; border:0; border-bottom:2px solid transparent;
  border-radius:0; padding:7px 2px 5px; font-size:{13 * scale:.1f}px; font-weight:400;
}}
QToolButton#studioRailRoom:hover, QToolButton#studioRailUtility:hover {{ color:{p['text']}; background:{p['spot']}; }}
QToolButton#studioRailRoom:checked {{ color:{p['text']}; border-bottom:2px solid {p['accent']}; font-weight:500; }}
QToolButton#studioRailRoom:focus, QToolButton#studioRailUtility:focus {{ border:2px solid {p['text']}; }}
QToolButton#studioRailRoom:disabled, QToolButton#studioRailUtility:disabled {{ color:{p['text_3']}; }}
QLabel#studioRailCount {{ color:{p['text_2']}; background:transparent; font-size:{12 * scale:.1f}px; }}
QToolButton#labelsPairMain, QToolButton#labelsPairAll {{ color:{p['text_2']}; background:transparent;
  border:0; border-bottom:2px solid transparent; border-radius:0; padding:6px 9px; }}
QToolButton#labelsPairMain:hover, QToolButton#labelsPairAll:hover {{ color:{p['text']}; background:{p['spot']}; }}
QToolButton#labelsPairMain:checked {{ color:{p['accent_2']}; border-bottom-color:{p['accent']}; }}
QToolButton#labelsPairMain:focus, QToolButton#labelsPairAll:focus {{ border:2px solid {p['text']}; }}
QToolButton#labelsPairMain:disabled, QToolButton#labelsPairAll:disabled {{ color:{p['text_3']}; }}
QFrame#studioLoadingCover {{ background:{p['surface']}; }}

QWidget#globalBar {{ background:transparent; border:0; border-bottom:1px solid {p['hair']}; border-radius:0; }}
QLabel#studioBrand {{ color:{p['text']}; background:transparent; font-family:"Literata"; font-size:{20 * scale:.1f}px; }}
QToolButton#studioPlaceButton, QToolButton#studioUtilityButton {{
  background:transparent; color:{p['text_2']}; border:0; border-bottom:2px solid transparent;
  border-radius:0; padding:7px 8px; font-size:{15 * scale:.1f}px;
}}
QToolButton#studioPlaceButton:hover, QToolButton#studioUtilityButton:hover {{ color:{p['text']}; background:{p['spot']}; }}
QToolButton#studioPlaceButton:disabled {{ color:{p['text_3']}; }}
QToolButton#studioPlaceButton:focus, QToolButton#studioUtilityButton:focus {{ border:2px solid {p['text']}; }}
QToolButton#studioPlaceButton {{ border:0; border-bottom:2px solid transparent; padding:6px 8px; }}
QToolButton#studioPlaceButton:hover {{ border-bottom-color:{p['accent']}; }}
QToolButton#studioPlaceButton:disabled {{ color:{p['text_3']}; border-bottom-color:transparent; }}
QToolButton#studioPlaceButton:focus {{ border:2px solid {p['text']}; }}
QToolButton#studioPlaceButton::menu-indicator {{ image:url("{menu_arrow}"); width:8px; height:8px;
  subcontrol-origin:padding; subcontrol-position:right center; right:3px; }}
QToolButton#studioPlaceButton:disabled::menu-indicator {{ image:none; width:0; }}
QLineEdit#globalSearch {{ background:transparent; color:{p['text']}; border:0; border-bottom:1px solid {p['line_2']};
  border-radius:0; padding:7px 5px; selection-background-color:{p['accent']}; selection-color:{p['on_accent']}; }}
QLineEdit#globalSearch:focus {{ border-bottom:2px solid {p['accent']}; }}
QLineEdit#globalSearch::placeholder {{ color:{p['text_2']}; }}
QWidget#studioSubject {{ background:transparent; border:0; }}
QLabel#studioDisplay, QLabel#studioSceneTitle {{ color:{p['text']}; background:transparent;
  font-family:"Literata"; font-size:{42 * scale:.1f}px; font-weight:400; }}
QLabel#studioEyebrow, QLabel#studioSceneBreadcrumb {{ color:{p['text_2']}; background:transparent;
  font-family:"Fira Sans"; font-size:{14 * scale:.1f}px; }}
QLabel#studioSceneSummary, QLabel#studioSceneStatus {{ color:{p['text_2']}; background:transparent; }}

/* Wall-lettered tool groups and selection details. */
QWidget#studioCollectionCard, QFrame#studioCard, QFrame#studioInstrument,
QFrame#studioDock, QWidget#studioTeaching, QWidget#selectionSurface {{
  background:transparent; color:{p['text']}; border:0; border-radius:0;
}}
QWidget#studioCollection QListView, QWidget#studioCollection QTextBrowser,
QWidget#studioCollection QTreeView {{ background:transparent; color:{p['text']}; border:0; }}
QLabel#studioCardTitle {{ color:{p['text']}; background:transparent; font-family:"Fira Sans";
  font-size:{18 * scale:.1f}px; font-weight:500; }}
QLabel#studioSelectionTitle {{ color:{p['text']}; background:transparent; font-family:"Literata";
  font-size:{24 * scale:.1f}px; font-weight:400; }}
QLabel#studioSelectionDescription {{ color:{p['text_2']}; background:transparent; font-family:"Literata";
  font-size:{18 * scale:.1f}px; }}
QWidget#studioTeaching QLabel {{ color:{p['text']}; background:transparent; }}
QWidget#studioAtlasTools {{ background:transparent; border:0; }}
QWidget#studioDock {{ background:transparent; color:{p['text']}; border:0; }}
QWidget#studioAtlasDock {{ background:transparent; color:{p['text']}; border:0; border-top:1px solid {p['hair']}; }}
QToolButton#studioAtlasTool {{ background:transparent; color:{p['text_2']}; border:0;
  border-bottom:2px solid transparent; border-radius:0; padding:6px 8px; }}
QToolButton#studioAtlasTool:hover {{ color:{p['text']}; background:{p['spot']}; }}
QToolButton#studioAtlasTool:checked {{ color:{p['accent_2']}; border-bottom-color:{p['accent']}; }}
QToolButton#studioAtlasTool:focus {{ border:2px solid {p['text']}; }}
QToolButton#studioAtlasTool:disabled {{ color:{p['text_3']}; }}
QToolButton#studioAtlasTool::menu-indicator {{ image:url("{menu_arrow}"); width:8px; height:8px;
  subcontrol-origin:padding; subcontrol-position:right center; right:4px; }}
QDockWidget#studioFloatingPanel {{ background:transparent; color:{p['text']}; border:0; border-radius:0; }}
QWidget[studioWallSurface="true"] {{ background:transparent; color:{p['text']}; border:0; border-radius:0; }}
QDockWidget#studioFloatingPanel QScrollArea, QDockWidget#studioFloatingPanel QScrollArea > QWidget {{
  background:transparent; color:{p['text']}; border:0; border-radius:0; }}
QWidget#studioFloatingTitleBar {{ background:transparent; border:0; }}
QLabel#studioFloatingTitle {{ background:transparent; color:{p['text']}; font-family:"Fira Sans";
  font-size:{16 * scale:.1f}px; font-weight:500; }}
QPushButton#studioFloatingClose {{ background:transparent; color:{p['text_2']}; border:0;
  border-bottom:2px solid transparent; border-radius:0; padding:5px 8px; }}
QPushButton#studioFloatingClose:hover {{ color:{p['text']}; background:{p['spot']}; }}
QPushButton#studioFloatingClose:focus {{ border:2px solid {p['text']}; }}
QPushButton#studioFloatingClose:disabled {{ color:{p['text_3']}; }}
QStatusBar {{ background:transparent; color:{p['text_2']}; border-top:1px solid {p['hair']}; }}
QStatusBar QLabel {{ background:transparent; color:{p['text_2']}; }}
QLabel#studioLoadingCover {{ color:{p['text']}; background:transparent; }}

/* Flat controls remain visible on the wall and keep a clear focus state. */
QPushButton, QToolButton {{ background:transparent; color:{p['text']}; border:1px solid {p['line_2']};
  border-radius:2px; padding:5px 10px; }}
QPushButton:hover, QToolButton:hover {{ background:{p['spot']}; color:{p['text']}; border-color:{p['text_2']}; }}
QPushButton:pressed, QToolButton:pressed {{ background:{p['surface_3']}; }}
QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus {{ border:2px solid {p['text']}; }}
QPushButton:checked, QToolButton:checked {{ color:{p['text']}; border-color:{p['accent']}; }}
QPushButton:disabled, QToolButton:disabled {{ color:{p['text_3']}; border-color:{p['hair']}; }}
QPushButton[variant="primary"] {{ background:{p['accent']}; color:{p['on_accent']}; border-color:{p['accent']}; font-weight:600; }}
QPushButton[variant="primary"]:hover {{ background:{p['accent_2']}; border-color:{p['accent_2']}; }}
QPushButton[variant="quiet"], QPushButton[variant="ghost"], QPushButton:flat {{ background:transparent; border-color:transparent; }}
QPushButton[variant="quiet"]:hover, QPushButton[variant="ghost"]:hover, QPushButton:flat:hover {{ background:{p['spot']}; }}
QPushButton[variant="active"] {{ color:{p['accent_2']}; border-color:{p['accent']}; }}
QPushButton[variant="secondary"], QPushButton[variant="tab"] {{ background:{p['surface_2']}; border-color:{p['line_2']}; }}
QPushButton[variant="paperAction"] {{ background:{p['accent']}; color:{p['on_accent']}; border-color:{p['accent']}; }}
QPushButton[variant="success"] {{ background:#29453a; color:{p['text']}; border-color:#8fd6b4; }}
QPushButton[variant="danger"] {{ background:#4a2928; color:{p['text']}; border-color:#e69a91; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background:{p['sunken']}; color:{p['text']};
  border:1px solid {p['line_2']}; border-radius:2px; padding:5px 8px; selection-background-color:{p['accent']};
  selection-color:{p['on_accent']}; }}
QLineEdit::placeholder {{ color:{p['text_2']}; }}
QListWidget, QListView, QTreeView, QTableWidget, QTableView, QTextBrowser, QTextEdit, QPlainTextEdit {{
  background:transparent; color:{p['text']}; border:0; selection-background-color:{p['surface_3']};
  selection-color:{p['text']}; }}
QListWidget::item:hover, QTreeView::item:hover {{ background:{p['spot']}; }}
QListWidget::item:selected, QTreeView::item:selected {{ background:{p['surface_3']}; color:{p['text']}; }}
QHeaderView::section {{ background:transparent; color:{p['text_2']}; border:0; border-bottom:1px solid {p['hair']}; }}
QMenu {{ background:{p['surface']}; color:{p['text']}; border:1px solid {p['line_2']}; padding:4px; }}
QMenu::item {{ padding:6px 18px; }}
QMenu::item:selected {{ background:{p['surface_3']}; color:{p['text']}; }}
QMenu::item:disabled {{ color:{p['text_3']}; }}
QToolTip {{ background:{p['surface_2']}; color:{p['text']}; border:1px solid {p['line_2']}; padding:5px 7px; }}
QTabWidget::pane {{ border:0; }}
QTabBar::tab {{ background:transparent; color:{p['text_2']}; border:0; border-bottom:2px solid transparent; padding:7px 10px; }}
QTabBar::tab:selected {{ color:{p['text']}; border-bottom-color:{p['accent']}; }}
QScrollBar:vertical {{ background:transparent; width:7px; margin:2px 0; }}
QScrollBar::handle:vertical {{ background:{p['line_2']}; min-height:28px; }}
QScrollBar:horizontal {{ background:transparent; height:7px; }}
QScrollBar::handle:horizontal {{ background:{p['line_2']}; min-width:28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
'''
