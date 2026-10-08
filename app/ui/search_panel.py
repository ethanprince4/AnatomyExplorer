"""Native search and a metadata-only browser for the complete installed model catalog."""
import html
import unicodedata

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QFont, QPainter, QDesktopServices
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPushButton, QStyle, QStyledItemDelegate,
                               QStyleOptionFocusRect, QTextBrowser, QVBoxLayout, QWidget)

from . import theme
from .stable_rows import fill_list

ROLE_ENTRY = Qt.UserRole + 1
KIND_BADGE = {"structure": "Structure", "group": "Group", "landmark": "Landmark", "clinical": "Clinical",
              "tissue": "Histology", "micro": "3D model", "lesson": "Lesson", "radiology": "Radiology"}
# Kept as a public compatibility constant; semantic colors come from the shared theme.
KIND_COLOR = {"clinical": theme.DANGER, "tissue": theme.INFO, "micro": theme.SUCCESS,
              "lesson": theme.ACCENT_TEXT, "radiology": theme.INFO}


def shown_alt(entry):
    """Useful alternative text, without repeating the radiology modality."""
    alt = entry.alt or ""
    if entry.kind == "radiology":
        parts = entry.subtitle.split(" · ")
        modality = parts[1] if len(parts) > 1 else ""
        if modality and alt.startswith(modality + " "):
            alt = alt[len(modality) + 1:]
    return alt


def normalized(text):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(text or ""))
                            if not unicodedata.combining(c)).casefold().split())


class ResultDelegate(QStyledItemDelegate):
    """Font-scaled two-line native rows, with selection and keyboard focus distinct."""
    def __init__(self, ds=None, parent=None, compact=False):
        super().__init__(parent)
        self.ds = ds
        self.compact = compact

    def sizeHint(self, option, index):
        return QSize(max(0, option.rect.width()), max(32,option.fontMetrics.height()+14) if self.compact else max(56, option.fontMetrics.height() * 2 + 18))

    def paint(self, p: QPainter, option, index):
        entry = index.data(ROLE_ENTRY)
        if entry is None:
            super().paint(p, option, index)
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        rect = QRectF(r).adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.qc(theme.ACCENT_SOFT if selected else theme.HOVER if hovered else theme.SURFACE))
        p.drawRoundedRect(rect, theme.R_MD, theme.R_MD)
        tx, width = r.x() + 12, max(0, r.width() - 24)
        font = QFont(option.font)
        font.setBold(True)
        p.setFont(font)
        p.setPen(theme.qc(theme.TEXT_STRONG))
        line_height = p.fontMetrics().height()
        title = getattr(entry, "title", getattr(entry, "name", ""))
        p.drawText(QRectF(tx, r.y() + 7, width, line_height), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(title, Qt.ElideRight, width))
        if self.compact:
            p.restore()
            return
        font.setBold(False)
        p.setFont(font)
        p.setPen(theme.qc(theme.TEXT_2))
        if hasattr(entry, "subtitle"):
            kind = KIND_BADGE.get(entry.kind, entry.kind.capitalize())
            alt = shown_alt(entry) if entry.kind in ("structure", "group", "landmark") else ""
            subtitle = f"{kind} · {entry.subtitle}" + (f" · {alt}" if alt else "")
        else:
            subtitle = getattr(entry, "kind_name", "3D model")
        p.drawText(QRectF(tx, r.y() + 9 + line_height, width, line_height), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(subtitle, Qt.ElideRight, width))
        p.restore()


class SearchLine(QLineEdit):
    navigate = Signal(int)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            self.navigate.emit(1 if e.key() == Qt.Key_Down else -1)
            e.accept()
            return
        if e.key() == Qt.Key_Escape and self.text():
            self.clear()
            e.accept()
            return
        super().keyPressEvent(e)


class SearchPanel(QWidget):
    activated = Signal(object)
    queryActive = Signal(bool)

    def __init__(self, ds, index, parent=None):
        super().__init__(parent)
        self.ds, self.index = ds, index
        self.setObjectName("studySearch")
        self.setMinimumWidth(240)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 8)
        lay.setSpacing(8)
        self.edit = SearchLine()
        self.edit.setObjectName("studySearchInput")
        self.edit.setAccessibleName("Search anatomy and study content")
        self.edit.setPlaceholderText("Search anatomy, models, lessons…")
        self.edit.setToolTip(f"Search {ds.n:,} atlas structures, Latin terms, landmarks and installed study content. "
                             "Up/Down chooses a result; Enter opens it; Escape clears the query.")
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        self.info = QLabel("Search the atlas and study library")
        self.info.setWordWrap(True)
        self.info.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        row.addWidget(self.info, 1)
        self.kind_filter = QComboBox()
        self.kind_filter.setAccessibleName("Search content type")
        self.kind_filter.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.kind_filter.setMinimumContentsLength(8)
        for name, key in (("All content", ""), ("Structures", "structure"), ("Groups", "group"),
                          ("Landmarks", "landmark"), ("3D models", "micro"), ("Histology", "tissue"),
                          ("Lessons", "lesson"), ("Radiology", "radiology"), ("Clinical", "clinical")):
            self.kind_filter.addItem(name, key)
        row.addWidget(self.kind_filter)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setObjectName("studySearchResults")
        self.list.setAccessibleName("Search results")
        self.list.setItemDelegate(ResultDelegate(ds, self.list))
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.list, 1)
        self.list.hide()
        self.shown = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._run)
        self.edit.textChanged.connect(self._query_changed)
        self.kind_filter.currentIndexChanged.connect(self._query_changed)
        self.edit.returnPressed.connect(self._activate_current)
        self.edit.navigate.connect(self._navigate)
        self.list.itemActivated.connect(lambda it: self.activated.emit(it.data(ROLE_ENTRY)))
        self.list.itemClicked.connect(lambda it: self.activated.emit(it.data(ROLE_ENTRY)))

    def results_widget(self):
        return self.list

    def focus_search(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def _query_changed(self, *_):
        # A cleared query must not leave stale results actionable during the debounce. The rows are hidden rather
        # than removed: this runs on every keystroke with the results on screen (see stable_rows).
        self._show_results([])
        if not self.edit.text().strip() and not self.kind_filter.currentData():
            self._timer.stop()
            self._run()
        else:
            self._timer.start()

    def _show_results(self, entries):
        def fill(item, entry):
            description = f"{entry.title}\n{KIND_BADGE.get(entry.kind, entry.kind)} · {entry.subtitle}"
            if entry.kind in ("structure", "group", "landmark") and entry.alt:
                description += f"\nLatin: {entry.alt}"
            item.setData(ROLE_ENTRY, entry)
            item.setToolTip(description)
            item.setData(Qt.AccessibleTextRole, description.replace("\n", ". "))

        self.shown = fill_list(self.list, entries, fill)
        self.list.setCurrentRow(0 if self.shown else -1)

    def _run(self):
        q, kind = self.edit.text().strip(), self.kind_filter.currentData()
        if not q and not kind:
            self._show_results([])
            self.info.setText("Search the atlas and study library")
            self.list.hide()
            self.queryActive.emit(False)
            return
        try:
            # Filter before the display cap so a popular anatomy term cannot hide model/lesson matches.
            results = (self.index.search(q, limit=max(150, len(self.index.entries))) if q
                       else list(self.index.entries))
            if kind:
                results = [entry for entry in results if entry.kind == kind]
        except Exception:
            self._show_results([])
            self.info.setText("Search is unavailable. Edit the query to retry, or use Browse.")
            self.list.hide()
            self.queryActive.emit(False)
            return
        count = len(results)
        self._show_results(results[:150])
        if not count:
            self.info.setText("No matches. Try a shorter name, a Latin term, or All content.")
        elif count > 150:
            self.info.setText(f"Showing 150 of {count:,} matches. Refine your search.")
        else:
            self.info.setText(f"{count:,} result{'s' if count != 1 else ''} · Enter to open")
        self.list.setVisible(bool(count))
        self.queryActive.emit(True)

    def _navigate(self, step):
        if self._timer.isActive():
            self._timer.stop()
            self._run()
        if self.shown:
            row = max(0, min(self.shown - 1, self.list.currentRow() + step))
            self.list.setCurrentRow(row)
            self.list.scrollToItem(self.list.currentItem())

    def _activate_current(self):
        if self._timer.isActive():
            self._timer.stop()
            self._run()
        item = self.list.currentItem()
        if item and not item.isHidden():
            self.activated.emit(item.data(ROLE_ENTRY))


class ModelOverview(QTextBrowser):
    """Keep the overview and its open button together, without a full-height empty pane."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.document().contentsChanged.connect(self.fit_content)

    def fit_content(self):
        natural=int(self.document().documentLayout().documentSize().height())+24
        available=max(160,self.parentWidget().height()-130) if self.parentWidget() else 650
        self.setFixedHeight(min(available,650,max(140,natural)))

    def resizeEvent(self,event):
        super().resizeEvent(event)
        self.fit_content()

class ModelCatalogPanel(QWidget):
    """Browse every registered model without loading geometry or touching its cache."""
    activated = Signal(str)
    linkActivated = Signal(str, str)
    variantChosen = Signal(str, str)
    verificationRequested = Signal()
    verificationCancelled = Signal()

    def __init__(self, content, parent=None):
        super().__init__(parent)
        self.content = content
        self.setObjectName("modelCatalog")
        self.setMinimumWidth(240)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        title = QLabel("3D models")
        title.setStyleSheet(theme.text_css(theme.TEXT_STRONG, theme.FS_TITLE, 700))
        lay.addWidget(title)
        self.edit = SearchLine()
        self.edit.setAccessibleName("Filter all 3D models")
        self.edit.setPlaceholderText("Find a model or linked structure…")
        self.edit.setClearButtonEnabled(True)
        lay.addWidget(self.edit)
        self.kind_filter = QComboBox()
        self.kind_filter.setAccessibleName("Model collection")
        self.kind_filter.addItem("All models", "")
        self.kind_filter.addItem("3D models", "inhouse")
        self.kind_filter.addItem("Microanatomy", "procedural")
        if not getattr(content.micro_models, "is_new_catalog", False):
            self.kind_filter.addItem("Downloaded models", "downloaded")
        lay.addWidget(self.kind_filter)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        lay.addWidget(self.info)
        self.list = QListWidget()
        self.list.setAccessibleName("Installed model catalog")
        self.list.setItemDelegate(ResultDelegate(parent=self.list, compact=True))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.shown = 0
        lay.addWidget(self.list, 3)
        self.preview = ModelOverview()
        self.preview.setAccessibleName("Selected model overview")
        self.preview.setOpenLinks(False)
        self.preview.anchorClicked.connect(self._overview_link)
        self.preview.setMinimumHeight(110)
        self.preview.document().setDefaultStyleSheet(
            f"body {{ color:{theme.TEXT}; font-size:{theme.FS_BODY}pt; }} "
            f"h3 {{ color:{theme.TEXT_STRONG}; margin:0 0 10px; font-size:18pt; }} "
            f"h4 {{ color:{theme.TEXT_STRONG}; margin:16px 0 6px; }} "
            f"a {{ color:{theme.ACCENT_TEXT}; }} p {{ margin:5px 0; }}")
        lay.addWidget(self.preview, 2)
        from .variant_choice import VariantChoice
        self.variant_choice = VariantChoice(self)
        self.variant_choice.requested.connect(self._choose_variant)
        lay.addWidget(self.variant_choice)
        self.open_button = QPushButton("Open model")
        self.open_button.setObjectName("primary")
        self.open_button.setAccessibleName("Open selected 3D model")
        self.open_button.clicked.connect(self._activate_current)
        lay.addWidget(self.open_button)
        hint = QLabel("Up/Down to choose · Enter to open")
        hint.setStyleSheet(theme.text_css(theme.MUTED, theme.FS_SMALL))
        lay.addWidget(hint)
        self.edit.textChanged.connect(self._run)
        self.kind_filter.currentIndexChanged.connect(self._run)
        self.edit.navigate.connect(self._navigate)
        self.edit.returnPressed.connect(self._activate_current)
        self.list.itemActivated.connect(lambda _: self._activate_current())
        self.list.currentItemChanged.connect(lambda *_: self._preview())
        self._run()

    def focus_search(self):
        self.edit.setFocus()
        self.edit.selectAll()

    def _entries(self):
        return sorted(self.content.micro_models.values(),
                      key=lambda e: ({"glb": 0, "procedural": 1, "downloaded": 2}.get(e.kind, 3),
                                     getattr(e, "order", 100), e.name.casefold()))

    def _run(self, *_):
        current = self.list.currentItem()
        old_id = current.data(ROLE_ENTRY).id if current is not None and not current.isHidden() else None
        terms = normalized(self.edit.text()).split()
        kind = self.kind_filter.currentData()
        entries = self._entries()
        shown = []
        for entry in entries:
            targets = " ".join(str(value) for value in (getattr(entry, "targets", {}) or {}).values())
            haystack = normalized(f"{entry.name} {entry.summary} {targets} {entry.kind_name}")
            if (kind == "inhouse" and entry.kind not in ("glb", "procedural")) or (kind and kind != "inhouse" and entry.kind != kind) or not all(word in haystack for word in terms):
                continue
            shown.append(entry)

        def fill(item, entry):
            item.setData(ROLE_ENTRY, entry)
            item.setData(Qt.AccessibleTextRole, f"{entry.name}. {entry.kind_name}")
            item.setToolTip(f"{entry.name}\n{entry.kind_name}\n{entry.summary}")

        # Runs after a model opens and while models are verified, with this list focused: never remove its rows.
        self.list.blockSignals(True)
        self.shown = count = fill_list(self.list, shown, fill)
        self.list.setCurrentRow(next((row for row, entry in enumerate(shown) if entry.id == old_id), 0 if count else -1))
        self.list.blockSignals(False)
        if not entries:
            text = getattr(self.content, "model_catalog_error", "") or "No validated new models are installed. Run or resume the preparation launcher."
        elif not count:
            text = "No models match. Clear the search or choose All models."
        else:
            text = f"{count} of {len(entries)} models · Select one to read its overview"
            catalog = self.content.micro_models
            if getattr(catalog, "verification_state", None) in ("pending", "verifying"):
                text += " · Verification pending; the selected version is checked when opened"
            error = getattr(self.content, "model_catalog_error", "")
            if error:
                text += "\n" + error
        self.info.setText(text)
        is_new = getattr(self.content.micro_models, "is_new_catalog", False)
        verifying = getattr(self.content.micro_models, "verification_state", None) == "verifying"
        self._preview()

    def _overview_link(self,url):
        if url.scheme()=="histo":self.linkActivated.emit("histo",url.path())
        elif url.scheme() in ("https","http"):QDesktopServices.openUrl(url)

    def _preview(self):
        item = self.list.currentItem()
        self.open_button.setEnabled(item is not None)
        if item is None:
            self.variant_choice.set_entry(None)
            self.preview.setPlainText("Choose a model to see its summary, scale and source information.")
            return
        e = item.data(ROLE_ENTRY)
        self.variant_choice.set_entry(e)
        esc = lambda value: html.escape(str(value or ""), quote=True)
        parts = [f"<h3>{esc(e.name)}</h3><h4>Overview</h4>",
                 f"<p>{esc(e.summary) or 'No summary is included with this model.'}</p>"]
        if getattr(e, "variant", None) == "post" and getattr(e, "outcome", None) == "no_change":
            parts.append("<p>No changes from microrefine</p>")
        if e.scale_note:
            parts.append(f"<h4>Scale</h4><p>{esc(e.scale_note)}</p>")
        links=[]
        for tid in e.histology:
            tissue=self.content.tissues.get(tid,{})
            if tissue.get("images"):
                links.append(f'<li><a href="histo:{esc(tid)}">{esc(tissue.get("name",tid))}</a></li>')
        if links:parts.append("<h4>Related histology</h4><ul>"+"".join(links)+"</ul>")
        if e.credit_html:
            parts.append(f"<p>{e.credit_html}</p>")
        self.preview.setHtml("".join(parts))
        self.open_button.setToolTip(f"Open {e.name} in its own viewer tab")

    def _navigate(self, step):
        if self.shown:
            self.list.setCurrentRow(max(0, min(self.shown - 1, self.list.currentRow() + step)))
            self.list.scrollToItem(self.list.currentItem())

    def _activate_current(self):
        item = self.list.currentItem()
        if item and not item.isHidden():
            self.activated.emit(item.data(ROLE_ENTRY).id)

    def _choose_variant(self, variant):
        item = self.list.currentItem()
        if item is not None:
            self.variantChosen.emit(item.data(ROLE_ENTRY).id, variant)

    def select_model(self, model_id):
        if model_id not in self.content.micro_models:
            return False
        self.edit.blockSignals(True)
        self.kind_filter.blockSignals(True)
        self.edit.clear()
        self.kind_filter.setCurrentIndex(0)
        self.edit.blockSignals(False)
        self.kind_filter.blockSignals(False)
        self._run()
        for row in range(self.shown):
            item = self.list.item(row)
            if item.data(ROLE_ENTRY).id == model_id:
                self.list.setCurrentItem(item)
                self.list.scrollToItem(item)
                return True
        return False
