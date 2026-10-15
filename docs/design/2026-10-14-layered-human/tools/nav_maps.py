"""The navigation maps of checkpoint 3 (renders/checkpoint-3/nav/map_1..3): the places and the ways between them, in
the Specimen style (Gallery slate).

    python tools/nav_maps.py OUT              writes OUT/map_<n>.svg and OUT/jobs.json
    node tools/raster_svg.mjs OUT/jobs.json   draws them to OUT/map_<n>.png, 2400 px square

The renders are those PNGs saved as WebP."""
import base64, json, math, os, sys

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # the design folder
F = D + '/assets/fonts/'
def font(fam, file, weight, style='normal'):
    b = base64.b64encode(open(F + file, 'rb').read()).decode()
    return f"@font-face{{font-family:'{fam}';font-weight:{weight};font-style:{style};src:url(data:font/woff2;base64,{b}) format('woff2')}}"
FONTS = (font('Literata', 'Literata-latin-normal-200_900.woff2', '200 900') +
         font('Literata', 'Literata-latin-italic-200_900.woff2', '200 900', 'italic') +
         font('Fira Sans', 'FiraSans-latin-normal-400.woff2', 400) + font('Fira Sans', 'FiraSans-latin-normal-500.woff2', 500))
C = dict(top='#2a3138', bottom='#1d2227', spot='#3d4750', text='#efece6', text2='#c7c6c1', text3='#a2a39f',
         hair='#44494d', leader='#949594', accent='#d4b47e', line2='#56616b')
W = 1600

def esc(s): return s.replace('&', '&amp;').replace('<', '&lt;')

class Svg:
    def __init__(self):
        self.o = []
    def add(self, s): self.o.append(s)
    def text(self, x, y, s, size=17, fam='sans', fill=None, weight=400, anchor='start', italic=False, ls=0):
        f = "'Literata'" if fam == 'serif' else "'Fira Sans'"
        st = ' font-style="italic"' if italic else ''
        opsz = ' style="font-variation-settings:\'opsz\' 36"' if fam == 'serif' else ''
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{f}" font-size="{size}" font-weight="{weight}" fill="{fill or C["text"]}" '
                 f'text-anchor="{anchor}" letter-spacing="{ls}"{st}{opsz}>{esc(s)}</text>')
    def line(self, x1, y1, x2, y2, stroke=None, w=1.2, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ''
        self.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke or C["leader"]}" stroke-width="{w}"{d}/>')
    def path(self, d, stroke=None, w=1.2, dash=None, fill='none', marker=False):
        da = f' stroke-dasharray="{dash}"' if dash else ''
        m = ' marker-end="url(#arr)"' if marker else ''
        self.add(f'<path d="{d}" fill="{fill}" stroke="{stroke or C["leader"]}" stroke-width="{w}"{da}{m}/>')
    def ring(self, x, y, r=4.5, fill=None, stroke=None):
        self.add(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill or "none"}" stroke="{stroke or C["leader"]}" stroke-width="1.4"/>')
    def out(self, title, sentence):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {W}" width="{W}" height="{W}">'
                f'<defs><style>{FONTS}</style>'
                f'<linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{C["top"]}"/><stop offset="1" stop-color="{C["bottom"]}"/></linearGradient>'
                f'<radialGradient id="pool"><stop offset="0" stop-color="{C["spot"]}"/><stop offset=".45" stop-color="{C["spot"]}" stop-opacity=".55"/><stop offset="1" stop-color="{C["spot"]}" stop-opacity="0"/></radialGradient>'
                f'<marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M1 1L9 5L1 9" fill="none" stroke="{C["accent"]}" stroke-width="1.4"/></marker>'
                f'</defs><rect width="{W}" height="{W}" fill="url(#wall)"/>')
        t = Svg()
        t.text(80, 118, title, 50, 'serif', weight=340)
        t.text(80, 160, sentence, 20, fill=C['text2'])
        return head + ''.join(self.pool) + ''.join(t.o) + ''.join(self.o) + '</svg>'

ROOMS = [
    ('Atlas', 'the whole body', ['Peel: the depth gauge', 'Section', 'Full entry']),
    ('Lessons', '303 lessons', ['Lesson overview', 'Step 2 of 7']),
    ('Models', '41 models', ['Model viewer', 'A stored view']),
    ('Radiology', '104 cases', ['Case: film and model']),
    ('Histology', '101 tissues', ['Slide']),
    ('Practice', '12 due', ['Review what is due', 'Quiz by topic', 'Session']),
]
UTIL = [('Saved views', ['Save this view', 'A saved view opens the atlas']),
        ('Settings', ['Appearance', 'Mouse & camera', 'Labels', 'Behaviour', 'Keyboard']),
        ('Menu', ['My progress', 'All my notes', 'Open a model file', 'Export a figure', 'Help and About'])]
# cross links inside rooms: (from item, to item, label)
LINKS = [('Slide', 'Model viewer', 'Jejunum model'), ('Model viewer', 'Atlas', 'In the atlas'),
         ('Model viewer', 'Lessons', 'Lessons (6)'), ('Slide', 'Atlas', 'Show in 3D'),
         ('Lessons', 'Review what is due', 'Review what is due'), ('Lesson overview', 'Session', 'Practice')]

def legend(s, y, extra=()):
    x = 80
    s.line(x, y, x + 46, y, C['leader'], 1.2); s.text(x + 60, y + 6, 'one click, in the chrome', 16, fill=C['text2'])
    x += 300
    s.line(x, y, x + 46, y, C['line2'], 1); s.text(x + 23, y + 6, '›', 18, fill=C['text3'], anchor='middle'); s.text(x + 60, y + 6, 'a step down; the trail leads back up', 16, fill=C['text2'])
    x += 400
    s.text(x, y + 6, '→ Atlas', 16, fill=C['accent']); s.text(x + 70, y + 6, 'a link inside a room to another place', 16, fill=C['text2'])
    x += 420
    for e in extra:
        s.text(x, y + 6, e, 16, fill=C['text2']); x += 300

WAYS = {'Full entry': '→ Models, Histology, Lessons', 'Model viewer': '→ In the atlas, Lessons (6)',
        'Slide': '→ Jejunum model, Show in 3D', 'Lesson overview': '→ Practice', 'Session': '← Back to the lesson',
        'Review what is due': '← from Lessons and the Lobby'}
def item_stack(s, x, y, items, P, step=40, size=17):
    """Items under a node, joined by a hairline, each with its ways out in brass. Returns the y after."""
    for it in items:
        s.line(x + 6, y - 24, x + 6, y - 6 + 0, C['line2'], 1)
        s.text(x + 18, y + 4, it, size, fill=C['text2'])
        P[it] = (x + 18, y)
        if it in WAYS:
            y += 24; s.text(x + 18, y + 3, WAYS[it], 14, fill=C['accent'])
        y += step
    return y

def links(s, P, lk=LINKS, bend=60):
    for a, b, lab in lk:
        if a not in P or b not in P: continue
        (x1, y1), (x2, y2) = P[a], P[b]
        mx, my = (x1 + x2) / 2, min(y1, y2) - bend - abs(x2 - x1) * .08
        s.path(f'M{x1:.1f} {y1 - 14:.1f}Q{mx:.1f} {my:.1f} {x2:.1f} {y2 - 14:.1f}', C['accent'], 1.3, '5 5', marker=True)
        s.text(mx, (y1 + y2) / 2 * .5 + my * .5 - 2, lab, 15, fill=C['accent'], anchor='middle')

def map1():
    s = Svg(); s.pool = []; P = {}
    # the bar, drawn as the header: hairline above and below
    y0 = 250
    s.line(80, y0 - 42, 1520, y0 - 42, C['hair'], 1); s.line(80, y0 + 30, 1520, y0 + 30, C['hair'], 1)
    s.text(84, y0 + 4, 'Layered Human', 20, 'serif')
    xs = [300 + i * 158 for i in range(6)]
    for i, (name, count, items) in enumerate(ROOMS):
        x = xs[i]
        s.text(x, y0 + 4, name, 18, weight=500, fill=C['text'] if i == 1 else C['text2'])
        if i == 1: s.add(f'<rect x="{x}" y="{y0+12}" width="62" height="2.5" fill="{C["accent"]}"/>')
        if name == 'Practice': s.text(x + 72, y0 + 4, '12', 16, weight=500, fill=C['accent'])
    s.text(1260, y0 + 4, 'Back to Atlas', 17, fill=C['text2'])
    s.text(1405, y0 + 4, 'Saved views · Settings · ≡', 15, fill=C['text3'])
    s.text(80, y0 + 70, 'The trail line on item pages:', 16, fill=C['text3'])
    s.text(310, y0 + 70, 'Lessons  ›  The coronary circulation  ›  Step 2 of 7', 16, fill=C['text2'])
    # rooms as columns
    top = 470
    for i, (name, count, items) in enumerate(ROOMS):
        x = 80 + i * 222
        s.line(xs[i] + 20, y0 + 32, xs[i] + 20, y0 + 44, C['leader'])
        s.path(f'M{xs[i]+20} {y0+96}C{xs[i]+20} {top-80} {x+8} {top-90} {x+8} {top-38}', C['leader'], 1.2)
        s.ring(x + 8, top - 34, 4)
        s.text(x, top, name, 30, 'serif', weight=400); P[name] = (x, top)
        s.text(x, top + 28, count, 16, fill=C['text3'])
        item_stack(s, x, top + 84, items, P, 46)
    # utilities, from the bar's right end
    top2 = 1040
    for i, (name, items) in enumerate(UTIL):
        x = 80 + i * 330
        s.text(x, top2, name, 26, 'serif'); P[name] = (x, top2)
        item_stack(s, x, top2 + 50, items, P, 36, 16)
    s.text(1080, top2, 'Back', 26, 'serif')
    for k, t in enumerate(['returns to the last place,', 'as you left it: the room, the item', 'and what was on screen.',
                           'Its label names it.', 'Steps and selections are not places;', 'the lesson’s own Back and Next', 'move through steps.']):
        s.text(1080, top2 + 44 + k * 28, t, 17, fill=C['text2'])
    legend(s, 1530)
    return s.out('1  Rooms bar', 'The top bar made fully clear: six rooms, Back that names where it goes, a trail on item pages.')

def map2():
    s = Svg(); s.pool = []; P = {}
    x0, top = 80, 270
    s.line(x0 + 150, top - 50, x0 + 150, 1440, C['hair'], 1)
    s.text(x0, top - 70, 'Layered Human', 15, 'serif', fill=C['text2'])
    s.line(x0 + 170, 212, 1520, 212, C['hair'], 1)
    s.text(x0 + 190, 200, '‹ ›   Lessons  ›  The coronary circulation  ›  Step 2 of 7', 17, fill=C['text2'])
    s.text(1520, 200, 'Search', 17, fill=C['text3'], anchor='end')
    s.text(x0 + 190, 236, 'The header carries the trail and search; the rail carries the rooms.', 15, fill=C['text3'])
    for i, (name, count, items) in enumerate(ROOMS):
        y = top + 60 + i * 132
        s.text(x0, y, name, 19, weight=500, fill=C['text'] if i == 1 else C['text2'])
        if i == 1: s.add(f'<rect x="{x0}" y="{y+10}" width="66" height="2.5" fill="{C["accent"]}"/>')
        if name == 'Practice': s.text(x0 + 82, y - 12, '12', 15, weight=500, fill=C['accent'])
        s.line(x0 + 150, y - 6, 360, y - 6, C['leader'])
        s.ring(364, y - 6, 4)
        s.text(380, y, name, 30, 'serif'); P[name] = (380, y)
        s.text(380, y + 28, count, 16, fill=C['text3'])
        x = 640
        for it in items:
            s.text(x - 26, y, '›', 22, fill=C['text3'])
            s.text(x, y, it, 17, fill=C['text2']); P[it] = (x, y)
            if it in WAYS: s.text(x, y + 26, WAYS[it], 14, fill=C['accent'])
            x += 70 + max(len(it) * 8.6, len(WAYS.get(it, '')) * 6.6)
    fy = top + 60 + 6 * 132 + 30
    s.line(x0, fy - 40, x0 + 120, fy - 40, C['hair'], 1)
    for i, (name, items) in enumerate(UTIL):
        y = fy + i * 96
        s.text(x0, y, name, 17, fill=C['text2'])
        s.line(x0 + 150, y - 6, 360, y - 6, C['leader']); s.ring(364, y - 6, 4)
        s.text(380, y, ' · '.join(items), 17, fill=C['text2'])
    legend(s, 1530)
    return s.out('2  Side rail', 'A slim rail of rooms down the left edge of the wall; the header keeps the trail and search.')

def map3():
    s = Svg(); s.pool = [f'<ellipse cx="800" cy="850" rx="330" ry="330" fill="url(#pool)"/>']; P = {}
    cx, cy = 800, 850
    s.text(cx, cy - 70, 'Lobby', 46, 'serif', anchor='middle', weight=340)
    s.text(cx, cy - 30, 'the app opens here', 16, fill=C['text3'], anchor='middle')
    s.text(cx, cy + 20, 'Continue: The coronary circulation', 17, fill=C['text2'], anchor='middle')
    s.text(cx, cy + 50, 'Review 12 due', 17, fill=C['accent'], anchor='middle')
    s.text(cx, cy + 80, 'Saved views', 17, fill=C['text2'], anchor='middle')
    angs = [-150, -90, -30, 30, 90, 150]
    R = 470
    for i, (name, count, items) in enumerate(ROOMS):
        a = math.radians(angs[i])
        x, y = cx + R * math.cos(a), cy + R * math.sin(a) * .86
        x1, y1 = cx + 200 * math.cos(a), cy + 200 * math.sin(a) * .9
        x2, y2 = cx + (R - 70) * math.cos(a), cy + (R - 70) * math.sin(a) * .86
        s.line(x1, y1, x2, y2, C['leader'])
        anchor = 'middle'
        tx = x - 90 if abs(math.cos(a)) > .2 else x + 24
        s.text(tx, y, name, 30, 'serif'); P[name] = (tx, y)
        s.text(tx, y + 28, count, 16, fill=C['text3'])
        item_stack(s, tx, y + 76, items, P, 38, 16)
    # the room row: room to room in one click
    s.add(f'<ellipse cx="{cx}" cy="{cy}" rx="{R+170}" ry="{(R+170)*.86}" fill="none" stroke="{C["hair"]}" stroke-width="1" stroke-dasharray="2 6"/>')
    s.line(80, 212, 1520, 212, C['hair'], 1)
    s.text(84, 200, 'Lobby  ›  Lessons  ›  The coronary circulation', 17, fill=C['text2'])
    s.text(1520, 200, 'Search   Atlas  Lessons  Models  Radiology  Histology  Practice   Settings  ≡', 15, fill=C['text3'], anchor='end')
    s.text(84, 240, 'Every room’s trail starts at the Lobby. The rooms stay one click apart on the right.', 15, fill=C['text3'])
    legend(s, 1530, ['dotted ring: the room row'])
    return s.out('3  Lobby', 'A home room the app opens to, with every room a doorway from it and a way back from each.')

if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: python tools/nav_maps.py OUT')
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    jobs = []
    for n, fn in ((1, map1), (2, map2), (3, map3)):
        p = f'{out}/map_{n}.svg'
        open(p, 'w').write(fn())
        jobs.append({'svg': p, 'out': f'{out}/map_{n}.png', 'size': 2400})
    json.dump(jobs, open(f'{out}/jobs.json', 'w'))
    print('ok')
