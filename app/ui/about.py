"""About / Credits dialog: version, the app's MIT licence and the third-party credits (THIRD_PARTY_LICENSES.md)."""
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QTabWidget, QTextBrowser,
                               QVBoxLayout)

from ..actions import WORKSPACE_MODIFIER, default_key_text, key_text
from ..config import FROZEN, ROOT
from . import theme

REPO_URL = "https://github.com/ethanprince4/AnatomyExplorer"

# QTextBrowser's rich text ignores the widget stylesheet for links, tables and code, so the document gets its own
DOC_CSS = f"""
a {{ color: {theme.ACCENT_TEXT}; text-decoration: none; }}
h1, h2, h3 {{ color: {theme.TEXT_STRONG}; }}
code {{ color: {theme.ACCENT_TEXT}; }}
th {{ color: {theme.MUTED}; text-align: left; }}
td, th {{ padding: 3px 8px; }}
blockquote {{ color: {theme.WARNING}; }}
"""


def app_version():
    """The release version (written into the bundle by packaging/AnatomyExplorer.spec), or the git description
    of a source checkout."""
    try:
        v = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if v:
            return v
    except OSError:
        pass
    if not FROZEN:
        try:
            out = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=ROOT, capture_output=True,
                                 text=True, timeout=3)
            if out.returncode == 0 and out.stdout.strip():
                return f"{out.stdout.strip()} (from source)"
        except (OSError, subprocess.SubprocessError):
            pass
    return "development version"


def _read(name):
    try:
        return (ROOT / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def _browser(markdown=None, text=None):
    b = QTextBrowser()
    b.setOpenExternalLinks(True)
    b.setAccessibleName("Application licence and attribution information")
    b.document().setDefaultStyleSheet(DOC_CSS)
    b.document().setDocumentMargin(12)
    if markdown is not None:
        b.setMarkdown(markdown)
    else:
        b.setPlainText(text or "")
        b.setLineWrapMode(QTextBrowser.NoWrap)
    return b


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Anatomy Explorer")
        self.resize(820, 700)
        self.setMinimumSize(540, 420)
        self.setAccessibleName("About Anatomy Explorer and educational content credits")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(16)
        icon = QLabel()
        pix = QPixmap(str(ROOT / "app" / "resources" / "icon.png"))
        if not pix.isNull():
            icon.setPixmap(pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(icon, 0, Qt.AlignTop)
        text = QVBoxLayout()
        title = QLabel("Anatomy Explorer")
        f = QFont(self.font())
        f.setPointSizeF(theme.FS_H1 + 1)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_H1 + 1, 700))
        text.addWidget(title)
        ver = QLabel(f"Version {app_version()}")
        ver.setStyleSheet(f"color:{theme.MUTED};")
        ver.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.addWidget(ver)
        blurb = QLabel("A 3D anatomy atlas with lessons, quizzes, histology, radiology and microanatomy.<br>"
                       "© 2026 Ethan Prince. Free software under the MIT licence. "
                       f"<a href='{REPO_URL}' style='color:{theme.ACCENT_TEXT}; text-decoration:none'>Source code</a>"
                       "<br>The anatomy data, images and downloaded 3D models belong to their creators and keep "
                       "their own licences. See <b>Credits</b>.<br>A study aid, not a medical device.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet(theme.text_css(theme.TEXT_2))
        blurb.setOpenExternalLinks(True)
        text.addWidget(blurb)
        head.addLayout(text, 1)
        lay.addLayout(head)

        tabs = QTabWidget()
        tabs.setAccessibleName("About, credits and licence")
        guide = ("# Getting around\n\n"
                 f"- **{default_key_text('search')}:** Search anatomy, models, images and lessons.\n"
                 f"- **{key_text(WORKSPACE_MODIFIER + '1')}–5:** Anatomy, model library, lessons, radiology and histology.\n"
                 f"- **{key_text('Ctrl+Shift+P')}:** Find an application command.\n"
                 f"- **{default_key_text('toggle_panels')}:** Hide or show the side panels.\n"
                 "- **F:** Frame the current selection while the 3D view has focus.\n\n"
                 "Explore and Details share a dock on compact windows; their tabs keep both reachable. "
                 "Open model and image tabs retain their own subject. Closing a loading model cancels it.\n\n"
                 "Settings → Display controls interface and reading text size. Appearance changes apply on "
                 "the next launch. Settings → Keyboard lists customizable commands.\n\n"
                 "Study imagery and labels are educational references. Consult the source and licence "
                 "beside each image; illustrated anatomy is not a patient-specific registration.")
        tabs.addTab(_browser(markdown=guide), "Getting around")
        credits = _read("THIRD_PARTY_LICENSES.md") or "THIRD_PARTY_LICENSES.md was not found."
        tabs.addTab(_browser(markdown=credits), "Credits")
        tabs.addTab(_browser(text=_read("LICENSE") or "LICENSE was not found."), "Licence")
        lay.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)


def open_about(parent=None):
    dlg = AboutDialog(parent)
    dlg.exec()
    return dlg
