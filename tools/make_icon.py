"""Render the approved Vitruvian logo into application and installer icons."""
import struct
import sys
from pathlib import Path
from PySide6.QtCore import QByteArray,QBuffer,QIODevice,QRectF,Qt
from PySide6.QtGui import QColor,QGuiApplication,QImage,QPainter
from PySide6.QtSvg import QSvgRenderer


def render_icon(renderer,size):
    image=QImage(size,size,QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen);painter.setBrush(QColor('#f2f6f8'))
    painter.drawRoundedRect(QRectF(size*.02,size*.02,size*.96,size*.96),size*.20,size*.20)
    renderer.render(painter,QRectF(size*.065,size*.065,size*.87,size*.87))
    painter.end()
    return image


def main():
    app=QGuiApplication(sys.argv)
    out=Path(__file__).resolve().parents[1]/'app'/'resources'
    renderer=QSvgRenderer(str(out/'logo.svg'))
    if not renderer.isValid():raise RuntimeError('Cannot render application logo')
    render_icon(renderer,512).save(str(out/'icon.png'))
    # Windows supports PNG-backed ICO entries; include sizes for taskbar and installer use.
    sizes=(16,24,32,48,64,128,256);frames=[]
    for size in sizes:
        data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.WriteOnly)
        render_icon(renderer,size).save(buffer,'PNG');buffer.close();frames.append(bytes(data))
    offset=6+16*len(sizes);directory=[]
    for size,frame in zip(sizes,frames):
        directory.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(frame),offset))
        offset+=len(frame)
    (out/'icon.ico').write_bytes(struct.pack('<HHH',0,1,len(sizes))+b''.join(directory)+b''.join(frames))
    print('Application PNG and multi-size Windows ICO updated.')


if __name__=='__main__':main()
