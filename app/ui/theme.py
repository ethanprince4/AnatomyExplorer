from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

BG = "#14171c"
PANEL = "#1a1e24"
PANEL_2 = "#20252c"
BORDER = "#2b313a"
TEXT = "#d9dee6"
MUTED = "#8a94a3"
ACCENT = "#4fc3f7"

def build_stylesheet(scale=1.0):
    fs = 9.5 * scale
    return f"""
QMainWindow, QWidget {{ background: {PANEL}; color: {TEXT}; font-size: {fs:.2f}pt; }}
QMainWindow::separator {{ background: {BORDER}; width: 1px; height: 1px; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{ background: {BG}; padding: 6px 10px; color: {MUTED}; font-weight: 600; }}
QToolButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 10px; color: {TEXT}; }}
QToolButton:hover {{ border-color: #3d6f89; background: #232b33; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolBar {{ background: {BG}; border: none; border-bottom: 1px solid {BORDER}; spacing: 2px; padding: 3px 6px; }}
QToolBar QToolButton {{ background: transparent; color: {TEXT}; border: 1px solid transparent; border-radius: 5px; padding: 4px 8px; }}
QToolBar QToolButton:hover {{ background: {PANEL_2}; border-color: {BORDER}; }}
QToolBar QToolButton:checked {{ background: #1f3a4a; border-color: #2f6d8c; color: #bfe9ff; }}
QToolBar QToolButton:pressed {{ background: #26303a; }}
QToolBar QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 6px; }}
QStatusBar {{ background: {BG}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 8px; background: transparent; }}
QLineEdit {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 7px; padding: 7px 10px; color: {TEXT};
             selection-background-color: #2f6d8c; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 7px 10px; border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QPushButton#navTab {{ background: transparent; color: {MUTED}; border: 1px solid transparent; border-radius: 6px;
                      padding: 5px 2px; margin-bottom: 6px; }}
QPushButton#navTab:hover {{ color: {TEXT}; background: {PANEL_2}; }}
QPushButton#navTab:checked {{ color: #e6f7ff; background: #1f3a4a; border-color: #2f6d8c; }}
QListWidget, QTreeWidget, QTextBrowser {{ background: {PANEL}; border: none; outline: none; }}
QTreeWidget::item {{ padding: 2px 0; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: #1f3a4a; color: #e6f7ff; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {PANEL_2}; }}
QHeaderView::section {{ background: {BG}; color: {MUTED}; border: none; padding: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #333a45; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #45505e; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #333a45; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QPushButton {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 10px; color: {TEXT}; }}
QPushButton:hover {{ border-color: #3d6f89; background: #232b33; }}
QPushButton:pressed {{ background: #1f3a4a; }}
QPushButton:checked {{ background: #1f3a4a; border-color: #2f6d8c; }}
QCheckBox {{ spacing: 7px; background: transparent; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid #46505d; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: none; }}
QCheckBox::indicator:indeterminate {{ background: #2f6d8c; border-color: #2f6d8c; }}
QTreeView::indicator {{ width: 13px; height: 13px; border-radius: 3px; border: 1px solid #46505d; background: {BG}; }}
QTreeView::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: none; }}
QTreeView::indicator:indeterminate {{ background: #2f6d8c; border-color: #2f6d8c; image: none; }}
QDialogButtonBox {{ dialogbuttonbox-buttons-have-icons: 0; }}
QSlider::groove:horizontal {{ height: 4px; background: #2d333c; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: #3a8fb8; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 12px; height: 12px; margin: -5px 0; border-radius: 6px; }}
QComboBox {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {BORDER}; selection-background-color: #1f3a4a; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; background: transparent; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QMenu {{ background: {PANEL_2}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: #1f3a4a; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 5px; }}
QLabel {{ background: transparent; }}
QScrollArea {{ border: none; }}
QToolButton#expander {{ border: none; background: transparent; color: {MUTED}; padding: 0; }}
QToolButton#expander:hover {{ color: {TEXT}; }}
"""


def apply_theme(app: QApplication, scale=1.0):
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(PANEL))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(BG))
    pal.setColor(QPalette.AlternateBase, QColor(PANEL_2))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(PANEL_2))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor("#2f6d8c"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(PANEL_2))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.Link, QColor(ACCENT))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(build_stylesheet(scale))
