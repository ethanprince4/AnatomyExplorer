"""The checkpoint-three On the body search presentation, without a second index."""
from dataclasses import dataclass
from PySide6.QtCore import Qt, QSize, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QStyledItemDelegate, QStyle
from . import theme

ROLE_SECTION = Qt.UserRole + 2
ROLE_RANK = Qt.UserRole + 3
ROOMS = [('structure','Structures'),('lesson','Lessons'),('radiology','Radiology'),
         ('tissue','Histology'),('micro','Models'),('clinical','Clinical')]


def room(entry):
    return 'structure' if entry.kind in ('structure','group','landmark') else entry.kind


def ids(entry,ds):
    if getattr(entry,'node',None) in ds.nodes:
        return list(ds.node_structures(entry.node))
    return list(getattr(entry,'sids',None) or [])


@dataclass
class MoreResults:
    kind: str
    title: str
    subtitle: str = ''
    alt: str = ''
    sids: tuple = ()


def fold(entries,ds):
    """Fold group members without changing the search index or activation targets."""
    groups=[e for e in entries if e.kind=='group']
    group_ids={id(e):set(ids(e,ds)) for e in groups}
    body_groups=[g for g in groups if g.system not in ('attachments','reference')]
    group_bases={id(g):{str(ds.structures[sid].get('base','')).casefold() for sid in group_ids[id(g)]}
                 for g in body_groups}
    seen=set()
    result=[]
    for e in entries:
        own=set(ids(e,ds)) if e.kind in ('structure','group') else set()
        parent=next((g for g in groups if g is not e and own and own<=group_ids[id(g)] and
                     (len(own)<len(group_ids[id(g)]) or e.kind=='structure')),None)
        if e.system=='attachments':
            bases={str(ds.structures[sid].get('base','')).casefold() for sid in own}
            parent=next((g for g in body_groups if e.title.casefold()==g.title.casefold()
                         or g.title.casefold() in bases or bases & group_bases[id(g)]),parent)
        chosen=parent or e
        # Duplicate groups with identical members are one actionable result.
        signature=(chosen.kind,chosen.title,tuple(sorted(ids(chosen,ds))))
        if signature not in seen:
            seen.add(signature);result.append(chosen)
    return result


def rows(entries,ds,expanded,height):
    grouped={kind:[] for kind,_ in ROOMS}
    for e in fold(entries,ds):grouped.setdefault(room(e),[]).append(e)
    caps={kind:(6 if kind=='structure' else 2) for kind,_ in ROOMS}
    def estimate():
        return sum(28+min(len(items),caps.get(kind,2))*(96 if kind=='structure' else 46)+
                   (34 if len(items)>caps.get(kind,2) else 0) for kind,items in grouped.items() if items)
    # Fit collapsed kinds to the actual wall; opening More intentionally enables scrolling.
    if not expanded:
        for kind,_ in reversed(ROOMS):
            while estimate()>height and caps[kind]>(3 if kind=='structure' else 1):caps[kind]-=1
    output=[]
    for kind,title in ROOMS:
        items=grouped.get(kind,[])
        cap=len(items) if kind in expanded else caps[kind]
        if len(items)==cap+1:cap+=1
        for i,e in enumerate(items[:cap]):output.append((e,title if i==0 else ''))
        if len(items)>cap:output.append((MoreResults(kind,f'{len(items)-cap} more {title.lower()}'),''))
    return output


class WallResultDelegate(QStyledItemDelegate):
    def __init__(self,panel):
        super().__init__(panel.list)
        self.panel=panel

    def sizeHint(self,option,index):
        entry=index.data(Qt.UserRole+1)
        header=28 if index.data(ROLE_SECTION) else 0
        return QSize(option.rect.width(),header+(34 if isinstance(entry,MoreResults) else
                     96 if entry is not None and room(entry)=='structure' else 46))

    def _marked(self,p,rect,text,font,query):
        p.setFont(font)
        text=p.fontMetrics().elidedText(text,Qt.ElideRight,int(rect.width()))
        start=text.casefold().find(query.casefold()) if query else -1
        if start<0:
            p.drawText(rect,Qt.AlignLeft|Qt.AlignVCenter,text);return
        before,match,after=text[:start],text[start:start+len(query)],text[start+len(query):]
        baseline=rect.y()+(rect.height()+p.fontMetrics().ascent()-p.fontMetrics().descent())/2
        x=rect.x()
        p.drawText(QPointF(x,baseline),before);x+=p.fontMetrics().horizontalAdvance(before)
        font.setWeight(font.Weight.DemiBold);p.setFont(font)
        p.drawText(QPointF(x,baseline),match);x+=p.fontMetrics().horizontalAdvance(match)
        font.setWeight(font.Weight.Normal);p.setFont(font)
        p.drawText(QPointF(x,baseline),after)

    def paint(self,p,option,index):
        entry=index.data(Qt.UserRole+1)
        if entry is None:return
        p.save();p.setRenderHint(QPainter.Antialiasing);p.setRenderHint(QPainter.TextAntialiasing)
        r=QRectF(option.rect);header=index.data(ROLE_SECTION)
        if header:
            p.setPen(QPen(theme.qc(theme.BORDER),1))
            if index.row():p.drawLine(r.topLeft(),r.topRight())
            p.setFont(theme.font_for('meta',weight=500));p.setPen(theme.qc(theme.MUTED))
            p.drawText(r.adjusted(2,2,-2,0),Qt.AlignLeft|Qt.AlignTop,header)
            r.setTop(r.top()+28)
        active=bool(option.state&(QStyle.State_Selected|QStyle.State_MouseOver))
        if isinstance(entry,MoreResults):
            p.setFont(theme.font_for('meta'));p.setPen(theme.qc(theme.ACCENT_TEXT))
            p.drawText(r.adjusted(34,0,-4,0),Qt.AlignLeft|Qt.AlignVCenter,entry.title+'  ›')
            p.restore();return
        structure=room(entry)=='structure'
        x=r.x()+34 if structure else r.x()+2
        width=r.right()-x-8
        query=self.panel.edit.text().strip()
        if structure:
            rank=index.data(ROLE_RANK)
            candidates=set(ids(entry,self.panel.ds))
            markers=getattr(self.panel.wall_viewport,'on_body_search_markers',())
            in_view=any(sid in candidates for _,sid,*_ in markers)
            circle=QPointF(r.x()+13,r.y()+19)
            pen=QPen(theme.qc(theme.TEXT if active else theme.palette()['leader']),1)
            if not in_view:pen.setStyle(Qt.DashLine)
            p.setPen(pen);p.setBrush(theme.qc(theme.SURFACE))
            p.drawEllipse(circle,9,9)
            p.setFont(theme.font_for('micro',size=11));p.setPen(theme.qc(theme.TEXT if in_view else theme.MUTED))
            p.drawText(QRectF(circle.x()-9,circle.y()-9,18,18),Qt.AlignCenter,str(rank or ''))
            if active:
                p.setPen(QPen(theme.qc(theme.TEXT),1));p.setBrush(Qt.NoBrush);p.drawEllipse(circle,12,12)
            p.setPen(theme.qc(theme.TEXT))
            self._marked(p,QRectF(x,r.y()+3,width,29),entry.title.replace(' — ', ', '),theme.font_for('caption',size=21),query)
            latin=theme.font_for('prose',size=15);latin.setItalic(True)
            p.setPen(theme.qc(theme.TEXT_2));self._marked(p,QRectF(x,r.y()+32,width,22),entry.alt,latin,query)
            p.setFont(theme.font_for('meta'));p.setPen(theme.qc(theme.MUTED))
            subtitle=entry.subtitle.replace('Group · ','').replace(' structures',' parts')
            p.drawText(QRectF(x,r.y()+54,width,20),Qt.AlignLeft|Qt.AlignVCenter,p.fontMetrics().elidedText(subtitle,Qt.ElideRight,int(width)))
            p.drawText(QRectF(x,r.y()+74,width,18),Qt.AlignLeft|Qt.AlignVCenter,'On the body' if in_view else 'Not in this view')
        else:
            p.setPen(theme.qc(theme.TEXT_2));self._marked(p,QRectF(x,r.y(),width,25),entry.title,
                                                       theme.font_for('ui',size=14),query)
            p.setFont(theme.font_for('meta',size=12));p.setPen(theme.qc(theme.MUTED))
            p.drawText(QRectF(x,r.y()+24,width,18),Qt.AlignLeft|Qt.AlignVCenter,
                       p.fontMetrics().elidedText(entry.subtitle,Qt.ElideRight,int(width)))
        p.restore()
