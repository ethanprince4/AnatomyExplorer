import html
import re
from collections import OrderedDict
from urllib.parse import quote, unquote

from PySide6.QtCore import Signal, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from . import theme

CSS = f"""
body {{ color: {theme.TEXT}; font-size: {theme.FS_BODY}pt; }}
h1 {{ font-size: {theme.FS_H1}pt; color: {theme.TEXT_STRONG}; margin: 0 0 3px 0; font-weight: 700; }}
h3 {{ color: {theme.TEXT_STRONG}; margin: 18px 0 6px 0; font-weight: 700; }}
.overline {{ color: {theme.ACCENT_TEXT}; font-size: {theme.FS_CAPTION}pt; font-weight: 700; letter-spacing: 1px;
            margin: 20px 0 6px 0; }}
h4 {{ color: {theme.TEXT_STRONG}; font-size: {theme.FS_BODY + 0.3}pt; margin: 12px 0 3px 0; font-weight: 700; }}
p {{ margin: 3px 0 8px 0; line-height: 140%; }}
b {{ color: {theme.TEXT_STRONG}; }}
a {{ color: {theme.ACCENT_TEXT}; text-decoration: none; }}
a.sec {{ color: {theme.TEXT_STRONG}; font-weight: 700; }}
a.sub {{ color: {theme.TEXT}; font-weight: 700; }}
a.more {{ color: {theme.ACCENT_TEXT}; font-weight: 600; }}
.latin {{ color: {theme.TEXT_2}; font-style: italic; font-size: {theme.FS_LEAD}pt; }}
.muted {{ color: {theme.MUTED}; }}
.count {{ color: {theme.MUTED}; font-weight: 400; }}
.crumb {{ color: {theme.MUTED}; font-size: {theme.FS_SMALL}pt; margin-top: 3px; }}
.summary {{ color: {theme.TEXT}; font-size: {theme.FS_BODY + 0.5}pt; }}
.cap {{ color: {theme.MUTED}; font-size: {theme.FS_CAPTION}pt; }}
td.k {{ color: {theme.MUTED}; padding: 3px 12px 3px 0; }}
td.v {{ color: {theme.TEXT}; padding: 3px 0; }}
td.btn {{ background-color: {theme.HOVER}; padding: 4px 9px; white-space: nowrap; }}
td.sechead {{ background-color: {theme.RAISED}; padding: 7px 10px; }}
td.subhead {{ padding: 5px 4px 3px 6px; }}
li {{ margin: 3px 0; }}
"""

DROP_SECTIONS = {"references", "external links", "see also", "further reading", "gallery", "additional images",
                 "notes", "bibliography", "sources", "images"}
SUMMARY_CHARS = 420


def esc(s):
    return html.escape(str(s), quote=True)


def link(scheme, payload, text, cls=None):
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{scheme}:{quote(str(payload), safe="")}">{esc(text)}</a>'


def parse_definition(text):
    """Split a Wikipedia-derived text into lead paragraphs, (title, html) sections and source URLs."""
    text = re.sub(r"\(\s*[,;]\s*", "(", text)
    text = re.sub(r"\(\s*\)", "", text)
    lead, sections, sources = [], [], []
    target = lead
    bullets = []

    def flush():
        if bullets:
            target.append("<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
            bullets.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^https?://\S+$", line):
            sources.append(line)
            continue
        m = re.match(r"^(=+)\s*(.*?)\s*=+$", line)
        if m:
            flush()
            if len(m.group(1)) <= 2:
                sec = [m.group(2), []]
                sections.append(sec)
                target = sec[1]
            else:
                target.append(f"<h4>{esc(m.group(2))}</h4>")
            continue
        if line.startswith("-"):
            bullets.append(esc(line.lstrip("-• ").strip()))
            continue
        flush()
        target.append(f"<p>{esc(line)}</p>")
    flush()
    sections = [(t, "".join(body)) for t, body in sections
                if t.strip().lower() not in DROP_SECTIONS and re.sub(r"<[^>]+>", "", "".join(body)).strip()]
    return lead, sections, sources


def split_summary(lead_paragraphs):
    """First couple of sentences as a summary, the rest of the lead as 'more'."""
    if not lead_paragraphs:
        return "", ""
    first = re.sub(r"</?p>", "", lead_paragraphs[0])
    rest = lead_paragraphs[1:]
    if len(first) > SUMMARY_CHARS:
        cut = [m.end() for m in re.finditer(r"[.;]\s", first) if m.end() <= SUMMARY_CHARS]
        if cut:
            rest = [f"<p>{first[cut[-1]:].strip()}</p>"] + rest
            first = first[:cut[-1]].strip()
    return first, "".join(rest)


class InfoPanel(QWidget):
    linkActivated = Signal(str, str)

    def __init__(self, ds, content, parent=None):
        super().__init__(parent)
        self.ds = ds
        self.content = content
        self.relations = None
        self.n_radiology = 0
        self.n_lessons = 0
        self.depth = None
        self._open = {"clinical": True, "attachments": True, "innervation": True, "supplied": True,
                      "boneattach": True, "histology": True, "micro": True}
        self._view = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.document().setDefaultStyleSheet(CSS)
        self.browser.document().setDocumentMargin(16)
        self.browser.anchorClicked.connect(self._anchor)
        lay.addWidget(self.browser)
        self.show_welcome()

    # ------------------------------------------------------------------ plumbing
    def _anchor(self, url):
        s = url.toString()
        scheme, _, payload = s.partition(":")
        if scheme in ("http", "https"):
            self.linkActivated.emit("url", s)
        elif scheme == "tog":
            key = unquote(payload)
            self._open[key] = not self._open.get(key, False)
            self._rerender()
        else:
            self.linkActivated.emit(scheme, unquote(payload))

    def _rerender(self):
        if self._view:
            pos = self.browser.verticalScrollBar().value()
            fn, args = self._view
            fn(*args, keep_scroll=True)
            self.browser.verticalScrollBar().setValue(pos)

    def _set(self, body, keep_scroll=False):
        pos = self.browser.verticalScrollBar().value()
        self.browser.setHtml(f"<html><body>{body}</body></html>")
        self.browser.verticalScrollBar().setValue(pos if keep_scroll else 0)

    def set_font_scale(self, scale):
        f = self.browser.font()
        f.setPointSizeF(9.5 * scale)
        self.browser.setFont(f)
        self._rerender()

    # ------------------------------------------------------------------ building blocks
    def _swatch(self, system_key):
        col = QColor.fromRgbF(*self.ds.systems[self.ds.system_index[system_key]]["color"]).name()
        return f'<span style="color:{col}">&#9632;</span>'

    def _actions(self, items):
        cells = "".join(f'<td class="btn">{link("act", a, t)}</td>' for t, a in items)
        return f'<table cellspacing="4" style="margin-top:8px"><tr>{cells}</tr></table>'

    def _breadcrumb(self, nid):
        chain = self.ds.ancestors(nid)
        if not chain:
            return ""
        crumbs = " &rsaquo; ".join(link("node", c, self.ds.nodes[c]["name"]) for c in chain)
        return f'<div class="crumb">{crumbs}</div>'

    def _meta_table(self, rows):
        rows = [(k, v) for k, v in rows if v]
        if not rows:
            return ""
        body = "".join(f'<tr><td class="k">{esc(k)}</td><td class="v">{v}</td></tr>' for k, v in rows)
        return f'<table cellspacing="0" style="margin-top:8px">{body}</table>'

    def _section(self, key, title, body, count=None, default=False):
        if not body:
            return ""
        is_open = self._open.get(key, default)
        arrow = "&#9662;" if is_open else "&#9656;"
        cnt = f' <span class="count">({count})</span>' if count is not None else ""
        head = (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px"><tr>'
                f'<td class="sechead"><a class="sec" href="tog:{quote(key, safe="")}">{arrow}&nbsp;&nbsp;{esc(title)}</a>{cnt}</td>'
                f'</tr></table>')
        return head + (f'<div style="margin:6px 2px 4px 6px">{body}</div>' if is_open else "")

    def _subsection(self, key, title, body, default=False):
        is_open = self._open.get(key, default)
        arrow = "&#9662;" if is_open else "&#9656;"
        head = (f'<table cellspacing="0" cellpadding="0"><tr><td class="subhead">'
                f'<a class="sub" href="tog:{quote(key, safe="")}">{arrow}&nbsp; {esc(title)}</a></td></tr></table>')
        return head + (f'<div style="margin:2px 0 6px 20px">{body}</div>' if is_open else "")

    def _summary_and_description(self, def_key):
        if not def_key or def_key not in self.ds.definitions:
            return "", ""
        lead, sections, sources = parse_definition(self.ds.definitions[def_key])
        first, rest = split_summary(lead)
        summary = ""
        if first:
            summary = f'<p class="summary">{first}</p>'
            if rest:
                k = "lead-more"
                if self._open.get(k, False):
                    summary += rest + f'<p>{link("tog", k, "Show less", "more")}</p>'
                else:
                    summary += f'<p>{link("tog", k, "Read more…", "more")}</p>'
        parts = []
        for title, body in sections:
            parts.append(self._subsection("desc:" + title.lower(), title, body))
        if sources:
            parts.append('<p class="muted" style="margin-top:8px">Source: ' + ", ".join(
                f'<a href="{esc(u)}">{"Wikipedia" if "wikipedia" in u else esc(u)}</a>' for u in sources) +
                " (CC BY-SA)</p>")
        description = self._section("description", "Full description", "".join(parts), count=len(sections)) \
            if sections else ("".join(parts) if sources else "")
        return summary, description

    def _notes(self, key):
        text = self.content.notes.get(key, "")
        if text:
            body = "".join(f"<p>{esc(line)}</p>" for line in text.splitlines() if line.strip())
            body += f'<p>{link("note", key, "Edit note", "more")}</p>'
            return self._section("notes", "My notes", body, default=True)
        return f'<p style="margin-top:6px">{link("note", key, "+ Add a note", "more")}</p>'

    def _clinical(self, entries):
        if not entries:
            return ""
        items = []
        for e in entries:
            body = "".join(f"<p>{esc(p)}</p>" for p in e["text"].split("\n") if p.strip())
            if e.get("tags"):
                body += f'<p class="muted">{esc(" · ".join(e["tags"]))}</p>'
            items.append(self._subsection(f"clin:{e['title']}", e["title"], body, default=len(entries) == 1))
        return self._section("clinical", "Clinical correlations", "".join(items), count=len(entries), default=True)

    def _histology(self, tissues):
        if not tissues:
            return ""
        blocks = []
        for t in tissues:
            thumbs = []
            for i, img in enumerate(t["images"][:6]):
                src = QUrl.fromLocalFile(str(self.content.thumb_path(img))).toString()
                thumbs.append(f'<td style="padding:2px"><a href="histo:{quote(t["id"] + "|" + str(i), safe="")}">'
                              f'<img src="{src}" width="104" height="78"></a></td>')
            rows = "".join("<tr>" + "".join(thumbs[r:r + 3]) + "</tr>" for r in range(0, len(thumbs), 3))
            more = f' <span class="muted">· {len(t["images"])} images</span>'
            blocks.append(f'<p style="margin-bottom:2px"><b>{link("histo", t["id"] + "|0", t["name"])}</b>{more}</p>'
                          f'<p class="muted" style="margin-top:0">{esc(t.get("summary", ""))}</p>'
                          f'<table cellspacing="0" cellpadding="0">{rows}</table>')
        n = sum(len(t["images"]) for t in tissues)
        return self._section("histology", "Histology", "".join(blocks), count=n, default=True)

    def _micro(self, models):
        """The 3D models that show these structures: in-house models first, then procedural and downloaded ones."""
        if not models:
            return ""
        items = []
        for m in models:
            summary = m.summary
            if len(summary) > 280:                     # the first sentence is enough here; the model tab has the rest
                summary = summary[:summary.find(". ") + 1] if 0 < summary.find(". ") < 280 else summary[:277] + "…"
            credit = f'<br><span class="muted">{m.credit_html}</span>' if m.credit_html else ""
            items.append(f'<p><b>{link("micro", m.id, m.name)}</b> <span class="muted">· {esc(m.kind_name)}</span>'
                         f'<br><span class="muted">{esc(summary)}</span>{credit}</p>')
        return self._section("micro", "3D models", "".join(items), count=len(models), default=True)

    def _group_by_base(self, sids):
        groups = OrderedDict()
        for sid in sids:
            s = self.ds.structures[sid]
            groups.setdefault((s["system"], s["base"]), []).append(sid)
        return groups

    def _nearby(self, sids):
        if self.relations is None or self.ds.structures[sids[0]]["system"] in ("regions", "reference"):
            return ""
        if not self._open.get("nearby"):
            return self._section("nearby", "Neighbouring structures", "…")
        found = self.relations.neighbours(sids, limit=40)
        if found is None:
            self.relations.start()
            return self._section("nearby", "Neighbouring structures",
                                 '<p class="muted">Indexing geometry – collapse and reopen in a moment.</p>')
        found = [f for f in found if f[2] <= 0.004]
        if not found:
            return self._section("nearby", "Neighbouring structures",
                                 '<p class="muted">Nothing else lies within a few millimetres.</p>')
        depth = getattr(self, "depth", None)
        own = None
        if depth is not None:
            mine = [depth[s] for s in sids if depth[s] >= 0]
            own = sum(mine) / len(mine) if mine else None
        by_sys = OrderedDict()
        order = {sy["key"]: i for i, sy in enumerate(self.ds.systems)}
        for base, members, dist, system in sorted(found, key=lambda f: (order[f[3]], f[0].lower())):
            text = link("sids", ",".join(map(str, members)), base)
            if own is not None:
                theirs = [depth[m] for m in members if depth[m] >= 0]
                if theirs:
                    delta = sum(theirs) / len(theirs) - own
                    if abs(delta) > 0.035:
                        text += ' <span class="muted">(%s)</span>' % ("deep" if delta > 0 else "superficial")
            by_sys.setdefault(system, []).append(text)
        body = ('<p class="muted">Structures whose surfaces lie against or within a few millimetres of the '
                'selection – its anatomical relations. Where it is clear-cut, each is marked as lying '
                'superficial or deep to the selection.</p>')
        for system, links in by_sys.items():
            name = self.ds.systems[self.ds.system_index[system]]["name"]
            body += f"<p>{self._swatch(system)} <b>{esc(name)}:</b> " + " · ".join(links) + "</p>"
        return self._section("nearby", "Neighbouring structures", body, count=len(found))

    def _base_links(self, sids):
        return [link("sids", ",".join(map(str, members)), base)
                for (system, base), members in sorted(self._group_by_base(sids).items(), key=lambda kv: kv[0][1].lower())]

    # ------------------------------------------------------------------ views
    def show_welcome(self, keep_scroll=False):
        self._view = (self.show_welcome, ())
        ds = self.ds
        tris = ds.counts["triangles"] / 1e6
        attr = "".join(f"<li>{esc(a)}</li>" for a in ds.attribution)
        n_hist = sum(len(t.get("images", [])) for t in self.content.histology["tissues"])
        n_clin = len(self.content.clinical)
        extras = []
        if n_clin:
            extras.append(f"{n_clin:,} clinical correlations")
        if n_hist:
            extras.append(f"{n_hist:,} histology images")
        if self.content.micro_models:
            extras.append(f"{len(self.content.micro_models)} 3D models")
        if self.n_radiology:
            extras.append(f"{self.n_radiology} radiology cases")
        if self.n_lessons:
            extras.append(f"{self.n_lessons} guided lessons")
        self._set(f"""
<h1>Anatomy Explorer</h1>
<div class="muted">{ds.n:,} structures · {len(ds.landmarks):,} landmarks · {tris:.1f} M triangles</div>
<div class="muted">{" · ".join(extras)}</div>
<p class="overline">GETTING STARTED</p>
<p><b>Search</b> (Ctrl+F) for any structure, group, landmark or Latin term. The result is highlighted,
framed, and everything else turns to x-ray. Search also finds conditions and signs ("carpal tunnel",
"Horner"), tissues and 3D models.</p>
<p><b>Lessons</b> (Ctrl+L) are short guided walks – the brachial plexus, the inguinal canal, the circle of
Willis. Browse them by body system, by region or by level. Each one opens with what you should be able to do
by the end, sets the view up for you step by step, asks you a question before you move on, and finishes with
what to remember. The library keeps your place, and "Quiz me" tests you on everything the lesson named.</p>
<p><b>Dissect</b> with the slider on the View tab, or <b>]</b> and <b>[</b>: the body comes apart from the skin
inwards, evenly everywhere, the way a real dissection does.</p>
<p><b>Cross-sections</b> label themselves. Turn one on and every structure the plane cuts is named around the
edge of the view; click a label to select it.</p>
<p><b>Quiz</b> (Ctrl+Q) tests you on what's visible: find a structure in 3D, or name the highlighted one.
Structures come back on a spaced-repetition schedule – sooner if you miss them. Study &rsaquo; My progress
shows how you are doing.</p>
<p><b>Hunt</b> is the quiz mode with the labels off and everything switched on. You are given one structure to
find in the whole body: right-click to peel things out of the way, left-click when you think you have it.
Three tries, then it shows you the answer and what you clicked instead.</p>
<p><b>Radiology</b> (Ctrl+R) shows a radiograph, CT or MR slice beside the model, labelled on both sides and
with the 3D view set up to match the film. Click a label on the image to find it in 3D.</p>
<p><b>Measure</b> (M) gives the distance between any two points you click; Ctrl+Shift+S exports the view as a
captioned, labelled figure.</p>
<p><b>3D models</b> (Study &rsaquo; 3D models) open in a tab of their own: the whole heart, the kidney with its
nephron, cardiac muscle, the microanatomy blocks and more. They use the same mouse, keys and labels as the atlas;
PgDown and PgUp step through a model's stored views.</p>
<p><b>Filter</b> by body system, subsystem or region on the left, or browse the hierarchy in <b>Tree</b>.
The <b>Histology</b> tab browses tissue micrographs.</p>
<p><b>Click</b> anything in 3D to see its summary, clinical correlations, histology and 3D models here.
Sections are collapsible, and remember whether you left them open.</p>
<p><b>Settings</b> (Ctrl+,) has mouse sensitivity, key bindings and display options.</p>
<p class="overline">DATA SOURCES</p><ul>{attr}<li>Histology micrographs: Wikimedia Commons contributors (author and
license shown with each image)</li></ul>
""", keep_scroll)

    def show_structures(self, sids, keep_scroll=False):
        ds = self.ds
        sids = list(sids)
        if not sids:
            self.show_welcome()
            return
        self._view = (self.show_structures, (sids,))
        groups = self._group_by_base(sids)
        if len(groups) > 1:
            # the colour swatch is the bullet: a list marker in front of it as well doubled it up
            items = "".join(f"<div style='margin:3px 0'>{self._swatch(k[0])}&nbsp; "
                            f"{link('sids', ','.join(map(str, v)), k[1])}"
                            f"{' <span class=muted>(' + str(len(v)) + ')</span>' if len(v) > 1 else ''}</div>"
                            for k, v in groups.items())
            self._set(f"<h1>{len(sids)} structures selected</h1>"
                      + self._actions([("Focus", "frame"), ("X-ray others", "xray"), ("Isolate", "isolate"),
                                       ("Hide", "hide")])
                      + self._section("selection", "Selection", items, count=len(groups), default=True),
                      keep_scroll)
            return

        s = ds.structures[sids[0]]
        sysname = ds.systems[ds.system_index[s["system"]]]["name"]
        sides = sorted(set(ds.structures[x]["side"] for x in sids if ds.structures[x]["side"]))
        side_txt = " & ".join(sides) if sides else "Midline / unpaired"
        region_names = {r["key"]: r["name"] for r in ds.regions}
        region_keys = []
        for x in sids:
            region_keys += [r for r in ds.structures[x]["regions"] if r not in region_keys]
        nid = ds.node_of_structure.get(sids[0])

        parts = [f"<h1>{esc(s['name'])}</h1>"]
        if s.get("latin"):
            parts.append(f'<div class="latin">{esc(s["latin"])}</div>')
        if nid:
            parts.append(self._breadcrumb(nid))
        actions = [("Focus", "frame"), ("X-ray others", "xray"), ("Isolate", "isolate"), ("Hide", "hide")]
        if ds.counterpart(sids[0]) and len(sids) == 1:
            actions.append(("Both sides", "both"))
        parts.append(self._actions(actions))

        summary, description = self._summary_and_description(s.get("def"))
        parts.append(summary)

        rows = [("System", f"{self._swatch(s['system'])} {esc(sysname)}"),
                ("Subsystem", esc(s["subsystem"] or "")),
                ("Side", esc(side_txt)),
                ("Region", esc(", ".join(region_names[r] for r in region_keys))),
                ("TA2 ID", esc(s["ta2"] or "")),
                ("Action", esc(s.get("action") or "")), ("Blood supply", esc(s.get("blood_supply") or ""))]
        if s["system"] == "attachments":
            muscle = [m for m in ds.structures_named(s["base"]) if ds.structures[m]["system"] == "muscular"]
            muscle = [m for m in muscle if ds.structures[m]["side"] == s["side"]] or muscle
            rows.insert(1, ("Type", esc(s["role"])))
            rows.insert(2, ("Muscle", link("sids", ",".join(map(str, muscle)), s["base"]) if muscle else esc(s["base"])))
            if "on" in s:
                rows.insert(3, ("Attached to", link("sid", s["on"], ds.structures[s["on"]]["base"])))
        parts.append(self._section("facts", "Key facts", self._meta_table(rows), default=True))

        parts.append(self._notes(s["base"]))
        parts.append(self._clinical(self.content.clinical_for_structures(sids)))
        parts.append(self._histology(self.content.histology_for_structures(sids)))
        parts.append(self._micro(self.content.micro_for_structures(sids)))
        parts.append(self._nearby(sids))

        if s.get("innervation"):
            nerves = []
            for nerve in s["innervation"]:
                nids = [x for x in ds.structures_named(nerve) if ds.structures[x]["system"] == "nervous"]
                same_side = [x for x in nids if ds.structures[x]["side"] == s["side"]] or nids
                nerves.append(link("sids", ",".join(map(str, same_side)), nerve) if same_side else esc(nerve))
            parts.append(self._section("innervation", "Innervation", "<p>" + " · ".join(nerves) + "</p>",
                                       count=len(nerves), default=True))

        if s["system"] == "nervous" and s["base"] in ds.muscles_by_nerve:
            musc = ds.muscles_by_nerve[s["base"]]
            if s["side"]:
                musc = [m for m in musc if ds.structures[m]["side"] in (s["side"], "")] or musc
            links = self._base_links(musc)
            parts.append(self._section("supplied", "Muscles supplied", "<p>" + " · ".join(links) + "</p>",
                                       count=len(links), default=True))

        if s["system"] == "muscular":
            att = []
            for sid in sids:
                att.extend(ds.attachments_of_muscle.get((s["base"], ds.structures[sid]["side"]), []))
            if att:
                bones = sorted(set(ds.structures[ds.structures[a]["on"]]["base"] for a in att if "on" in ds.structures[a]))
                origins = [a for a in att if ds.structures[a]["role"] == "Origin"]
                inserts = [a for a in att if ds.structures[a]["role"] == "Insertion"]
                body = (f'<p>{link("attach", ",".join(map(str, att)), "Show origin (red) & insertion (blue)")}'
                        f' <span class="muted">({len(origins)} origin, {len(inserts)} insertion)</span></p>')
                if bones:
                    body += f'<p class="muted">On: {esc(", ".join(bones))}</p>'
                parts.append(self._section("attachments", "Attachments", body, default=True))

        if s["system"] in ("skeletal", "joints") and any(ds.attachments_on.get(x) for x in sids):
            att = [a for x in sids for a in ds.attachments_on.get(x, [])]
            by_role = {"Origin": OrderedDict(), "Insertion": OrderedDict()}
            for a in att:
                st = ds.structures[a]
                by_role[st["role"]].setdefault(st["base"], []).append(a)
            body = f'<p>{link("attach", ",".join(map(str, att)), "Show all attachment areas on this bone")}</p>'
            for role, label in (("Origin", "Origins"), ("Insertion", "Insertions")):
                if by_role[role]:
                    items = []
                    for base in sorted(by_role[role]):
                        musc = [m for m in ds.structures_named(base) if ds.structures[m]["system"] == "muscular"]
                        items.append(link("sids", ",".join(map(str, musc)), base) if musc else esc(base))
                    body += f"<p><b>{label}:</b> " + " · ".join(items) + "</p>"
            n = len(by_role["Origin"]) + len(by_role["Insertion"])
            parts.append(self._section("boneattach", "Muscle attachments", body, count=n, default=True))

        lms = []
        for x in sids[:2]:
            lms.extend(ds.landmarks_of.get(x, []))
        if lms:
            seen = OrderedDict()
            for i in lms:
                seen.setdefault(ds.landmarks[i]["name"], i)
            items = " · ".join(link("lm", i, name) for name, i in sorted(seen.items()))
            parts.append(self._section("landmarks", "Landmarks", f"<p>{items}</p>", count=len(seen)))

        if nid and ds.nodes[nid]["children"]:
            kids = ds.nodes[nid]["children"]
            items = " · ".join(link("node", c, ds.nodes[c]["name"]) for c in kids[:150])
            parts.append(self._section("parts", "Parts", f"<p>{items}</p>", count=len(kids)))

        parts.append(description)
        self._set("".join(parts), keep_scroll)

    def show_node(self, nid, keep_scroll=False):
        ds = self.ds
        node = ds.nodes[nid]
        if "sid" in node:
            self.show_structures([node["sid"]], keep_scroll)
            return
        self._view = (self.show_node, (nid,))
        sysname = ds.systems[ds.system_index[node["system"]]]["name"]
        parts = [f"<h1>{esc(node['name'])}</h1>"]
        if node.get("latin"):
            parts.append(f'<div class="latin">{esc(node["latin"])}</div>')
        parts.append(self._breadcrumb(nid))
        parts.append(self._actions([("Focus", "frame"), ("X-ray others", "xray"), ("Isolate", "isolate"),
                                    ("Hide", "hide"), ("Show", "show")]))
        summary, description = self._summary_and_description(node.get("def"))
        parts.append(summary)
        parts.append(self._section("facts", "Key facts", self._meta_table(
            [("System", f"{self._swatch(node['system'])} {esc(sysname)}"), ("Structures", str(node["count"])),
             ("TA2 ID", esc(node.get("ta2") or ""))]), default=True))
        parts.append(self._notes(node["name"]))
        parts.append(self._clinical(self.content.clinical_for_name(node["name"])))
        parts.append(self._histology(self.content.histology_for_name(node["name"])))
        parts.append(self._micro(self.content.micro_for_name(node["name"])))
        kids = node["children"]
        if kids:
            items = " · ".join(link("node", c, ds.nodes[c]["name"]) for c in kids[:200])
            parts.append(self._section("contains", "Contains", f"<p>{items}</p>", count=len(kids), default=True))
        parts.append(description)
        self._set("".join(parts), keep_scroll)

    def show_landmark(self, idx, keep_scroll=False):
        self._view = (self.show_landmark, (idx,))
        ds = self.ds
        lm = ds.landmarks[idx]
        host = ds.structures[lm["sid"]]
        parts = [f"<h1>{esc(lm['name'])}</h1>"]
        if lm.get("latin"):
            parts.append(f'<div class="latin">{esc(lm["latin"])}</div>')
        parts.append(f'<div class="crumb">Landmark on {link("sid", lm["sid"], host["name"])}'
                     f'{" (" + host["side"].lower() + ")" if host["side"] else ""}</div>')
        parts.append(self._actions([("Focus", "frame"), ("X-ray others", "xray")]))
        summary, description = self._summary_and_description(lm.get("def"))
        parts.append(summary)
        if lm.get("ta2"):
            parts.append(self._meta_table([("TA2 ID", esc(lm["ta2"]))]))
        parts.append(self._notes(lm["name"]))
        parts.append(self._clinical(self.content.clinical_for_name(lm["name"])))
        others = [i for i in ds.landmarks_of.get(lm["sid"], []) if i != idx]
        if others:
            items = " · ".join(link("lm", i, ds.landmarks[i]["name"]) for i in others)
            parts.append(self._section("otherlm", f"Other landmarks on {host['base']}", f"<p>{items}</p>",
                                       count=len(others)))
        parts.append(description)
        self._set("".join(parts), keep_scroll)

    def show_html(self, title_html, body_html, view=None):
        """Generic view used by the microanatomy and histology panels."""
        self._view = view
        self._set(title_html + body_html)
