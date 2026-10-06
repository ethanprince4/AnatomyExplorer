"""Study-02 native chrome. No renderer or material settings are changed here."""
from pathlib import Path
import json
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtCore import Qt

ROOT = Path(__file__).parent / 'resources' / 'studio'
STAGE_BACKGROUND = '#141b22'
STAGE_TEXT = '#f4f5f7'
PALETTES = json.loads((ROOT / 'palettes.json').read_text(encoding='utf-8'))

def palette(mode=None):
    from . import theme
    return dict(PALETTES['porcelain'])

def display_font_family():
    from .theme import font_family
    return font_family()


def display_css(size=34, color=None):
    p = palette()
    return f'font-family:"{display_font_family()}";font-size:{size}px;font-weight:400;color:{color or p["text"]};background:transparent;'

def icon(name, mode=None):
    from . import theme
    key = 'porcelain'
    name = {'layers':'parts', 'eye':'labels', 'ruler':'measure'}.get(name, name)
    return QIcon(str(ROOT / 'icons' / key / (name + '.svg')))

def apply_surface(widget, name='surface'):
    """Style an existing widget, preserving its layout, signals and contents."""
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setObjectName(name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget

def build_stylesheet(scale=1.0):
    p = palette()
    return f'''
/* Study-02 surfaces are opt-in; no widget hierarchy or render surface is replaced. */
QWidget#studioSubject {{ background:transparent;border:none; }}
QWidget#studioSubject QToolButton {{ background:transparent;color:{STAGE_TEXT};border:1px solid #536171;border-radius:8px;padding:6px 10px; }}
QWidget#studioSubject QToolButton:hover {{ background:#283443;color:#ffffff; }}
QWidget#studioCollection {{ background:{STAGE_BACKGROUND};border:none; }}
QWidget#studioCollectionCard {{ background:{p['surface']};color:{p['text']};border:1px solid {p['row_edge']};border-radius:16px; }}
QWidget#studioCollection QListView, QWidget#studioCollection QTextBrowser {{ background:{p['surface']};color:{p['text']}; }}
QWidget#studioAtlasTools {{ background:{STAGE_BACKGROUND};border:none; }}
QStatusBar {{ background:{STAGE_BACKGROUND};color:#c6cdd6;border-top:1px solid #283443; }}
QStatusBar QLabel {{ background:transparent;color:#c6cdd6; }}

QTabWidget#studioWorkspaces {{ background:{STAGE_BACKGROUND};border:none;padding:0px;margin:0px; }}
QTabWidget#studioWorkspaces::pane {{ background:{STAGE_BACKGROUND};border:none;padding:0px;margin:0px;top:0px; }}
QTabWidget#studioWorkspaces > QStackedWidget {{ background:{STAGE_BACKGROUND};border:none; }}
QWidget#globalBar QPushButton#studioNavButton {{ background:transparent;color:{p['text']};border:1px solid transparent;
    border-radius:10px;padding:7px 16px;font-size:{14 * scale}px;font-weight:600; }}
QWidget#globalBar QPushButton#studioNavButton:hover {{ background:{p['raised']};color:{p['text']};border-color:{p['row_edge']}; }}
QWidget#globalBar QPushButton#studioNavButton:checked {{ background:{p['selected']};color:{p['accent']};border:1px solid {p['accent']}; }}
QWidget#globalBar QPushButton#studioNavButton:checked:hover {{ background:{p['selected']};color:{p['accent']};border-color:{p['accent']}; }}
QWidget#globalBar QPushButton#studioNavButton:focus {{ border-color:{p['accent']}; }}

QWidget#studioShell, QWidget#studioHeader, QWidget#studioScene {{ background:{STAGE_BACKGROUND}; }}

QLabel#studioBrand {{ color:{p['text']};font-size:{16 * scale}px;font-weight:600;background:transparent; }}
QFrame#studioCard > QWidget, QFrame#studioInstrument > QWidget,
QFrame#studioDock > QWidget, QWidget#studioTeaching > QWidget {{ background:transparent; }}
QPushButton#studioTool, QToolButton#studioTool {{ background:transparent;border:2px solid transparent;border-radius:10px;padding:6px 9px;color:{p['muted']}; }}
QPushButton#studioTool:hover, QToolButton#studioTool:hover {{ background:{p['raised']};color:{p['text']}; }}
QPushButton#studioTool:checked, QToolButton#studioTool:checked {{ background:{p['selected']};color:{p['accent']}; }}
QPushButton#studioTool:focus, QToolButton#studioTool:focus {{ border-color:{p['accent']}; }}
QPushButton#headerClose, QToolButton#headerClose {{ background:transparent;border:none;color:{p['muted']};border-radius:6px; }}
QPushButton#headerClose:hover, QToolButton#headerClose:hover {{ background:{p['raised']};color:{p['text']}; }}

QWidget#studioTeaching QLabel {{ color:{p['text']};background:transparent; }}
QWidget#studioTeaching QComboBox {{ background:{p['input']};color:{p['text']};border:1px solid {p['input_border']};border-radius:8px;padding:6px 10px;min-height:24px; }}
QWidget#surface, QFrame#studioCard, QWidget#studioTeaching {{ background:{p['surface']};border:1px solid {p['tool_edge']};border-radius:16px; }}
QWidget#surface > QWidget, QWidget#previewSurface > QWidget, QWidget#globalBar > QWidget,
QWidget#deep > QWidget, QWidget#dock > QWidget {{ background:transparent; }}
QWidget#selectionSurface {{ background:{p['paper']};border:none;border-radius:16px;color:{p['paper_text']}; }}
QWidget#selectionSurface QLabel {{ color:{p['paper_text']};background:transparent; }}
QWidget#selectionSurface QLabel[muted="true"] {{ color:{p['paper_muted']}; }}
QWidget#previewSurface {{ background:{p['preview']};border:none;border-radius:16px; }}
QWidget#selectedModel {{ background:{p['selected']};border-radius:10px; }}
QWidget#modelRow {{ border-bottom:1px solid {p['row_edge']}; }}
QWidget#globalBar {{ background:{p['surface']};border:none;border-radius:14px; }}
QLineEdit#globalSearch {{ background:{p['input']};border:2px solid {p['input_border']};padding:9px 13px;border-radius:8px;color:{p['text']}; }}
QLineEdit#globalSearch:focus {{ border-color:{p['accent']}; }}
QWidget#deep {{ background:{p['tool']};border:1px solid {p['tool_edge']};border-radius:14px; }}
QFrame#studioInstrument {{ background:{p['surface']};border:1px solid {p['row_edge']};border-radius:14px; }}
QWidget#dock, QFrame#studioDock {{ background:{p['surface']};border:1px solid {p['edge']};border-radius:20px; }}
QLabel#studioDisplay {{ {display_css(34 * scale, STAGE_TEXT)} }}
QLabel#studioCardTitle {{ color:{p['text']};font-size:{18 * scale}px;font-weight:600;background:transparent; }}
QLabel#studioSelectionTitle {{ {display_css(28 * scale, p['paper_text'])} }}
QLabel#studioSelectionDescription {{ color:{p['paper_muted']};font-size:{13 * scale}px;background:transparent; }}
QLabel#studioEyebrow {{ color:#c6cdd6;font-size:{11 * scale}px;font-weight:600; }}
QPushButton[variant="quiet"] {{ background:transparent;border:2px solid transparent;color:{p['muted']};border-radius:8px;padding:6px 12px; }}
QPushButton[variant="quiet"]:hover {{ background:{p['raised']};color:{p['text']}; }}
QPushButton[variant="paperAction"] {{ background:{p['paper_action']};color:{p['on_paper_action']};font-weight:600;border:2px solid transparent;border-radius:8px; }}
QPushButton[variant="paperAction"]:hover {{ border-color:{p['paper_text']}; }}
QPushButton[variant="active"] {{ background:{p['accent']};color:{p['ink']};font-weight:600;border:2px solid transparent;border-radius:8px; }}
QPushButton[variant="active"]:hover {{ background:{p['raised']};color:{p['text']};border-color:{p['accent']}; }}
QPushButton[variant="secondary"] {{ background:{p['raised']};color:{p['text']};border:2px solid {p['edge']};border-radius:8px; }}
QPushButton[variant="tab"] {{ background:{p['selected']};color:{p['text']};font-weight:600;border:2px solid transparent;border-radius:8px; }}
QPushButton[variant="quiet"]:focus,QPushButton[variant="active"]:focus,
QPushButton[variant="secondary"]:focus,QPushButton[variant="tab"]:focus {{ border-color:{p['accent']}; }}
QPushButton[variant="paperAction"]:focus {{ border-color:{p['paper_text']}; }}
QPushButton[variant="active"]:disabled,QPushButton[variant="paperAction"]:disabled,
QPushButton[variant="tab"]:disabled,QPushButton[variant="quiet"]:disabled,
QPushButton[variant="secondary"]:disabled {{ background:{p['deep']};color:{p['edge']};border-color:transparent; }}
'''
