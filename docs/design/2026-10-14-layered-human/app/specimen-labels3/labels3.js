/* Layered Human, Specimen, checkpoint 3: the owner's labels mixture.
 *   Labels on  -> numbered circles on the body, nothing else.
 *   Click a circle -> its caption rail (name on a rail beside the specimen, knee leader); click again to close.
 *   Show all / Hide all -> every rail; Esc closes every rail. The selected structure keeps its brass circle, rail open.
 *   Hover a circle -> its rail drawn faint until clicked. Circles are buttons in number order (aria-expanded).
 * Options (<html data-variant>) only move "Show all": 1 in the dock beside Labels, 2 in the room's caption line,
 * 3 at the head of a compact numbered key in the top right corner, level with the room's title.
 * URL: ?variant=1|2|3  ?lstate=circles|one|all (atlas, section)  default|term|all (lesson)  wrong1|wrong2|right (practice)
 * Runs after mock.js has set data-ready; sets <html data-labels="1"> when done. */
(function () {
  const R = document.documentElement, q = new URLSearchParams(location.search), NS = 'http://www.w3.org/2000/svg';
  const LSTATE = q.get('lstate') || '';
  // Per room: x of the two rails (null = no rail on that side), how far a knee leader runs before it turns to its
  // anchor, the wall area names may use, and where the anchors come from.
  const ROOM = {
    atlas:   { rails: [704, 1258], reach: 44, area: [40, 96, 1880, 1010], one: 'rectus_femoris.vl' },
    section: { rails: [390, 1610], reach: 40, area: [40, 238, 1880, 1006], one: 'trapezius.vr' },
    lesson:  { rails: [null, 1652], reach: 36, area: [40, 96, 1880, 1000], term: 'lad' },
  };
  const svgEl = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };
  const rooms = {};

  function anchorsFor(img) {
    const sel = getComputedStyle(R).getPropertyValue('--select').trim().replace('#', '').toLowerCase();
    const key = (img.dataset.anchors || img.dataset.plate).replace('{select}', sel);
    const lbl = window.LBL_DATA && window.LBL_DATA[img.dataset.anchors || img.dataset.plate];
    if (lbl) return lbl.anchors;
    return (window.LH_PLATES && window.LH_PLATES.anchors[key]) || {};
  }

  /* ----------------------------------------------------------------------------------------- one room */
  function setup(section) {
    const id = section.dataset.screenId, cfg = ROOM[id];
    const stage = section.querySelector('[data-stage="wall"]');
    if (!cfg || !stage) return null;
    const app = section.querySelector('.app'), img = stage.querySelector('img.plate'), A = anchorsFor(img);
    const sr = stage.getBoundingClientRect(), ir = img.getBoundingClientRect();
    const k = ir.width / img.naturalWidth, ox = ir.left - sr.left, oy = ir.top - sr.top, midX = ox + ir.width / 2;
    const svg = stage.querySelector(':scope > svg.leaders') || svgEl('svg', { class: 'leaders', 'aria-hidden': 'true' }, stage);
    svg.setAttribute('viewBox', `0 0 ${sr.width} ${sr.height}`); svg.setAttribute('width', sr.width); svg.setAttribute('height', sr.height);

    let items = [...stage.querySelectorAll('.lbl[data-a]')].map(e => {
      const a = A[e.dataset.a];
      if (!a) { e.hidden = true; console.error('LBL3 no anchor for', e.dataset.a); return null; }
      const x = ox + a.x * k, y = oy + a.y * k;
      return { key: e.dataset.a, e, x, y, name: e.textContent.trim(), sel: e.classList.contains('is-selected'),
               side: cfg.rails[0] == null ? 'right' : cfg.rails[1] == null ? 'left' : (x < midX ? 'left' : 'right') };
    }).filter(Boolean);
    // numbers fixed for the view: top to bottom, then left to right
    items.sort((a, b) => (Math.round(a.y) - Math.round(b.y)) || (a.x - b.x));
    items.forEach((it, i) => {
      it.n = i + 1;
      it.e.hidden = true;
      it.e.classList.add(it.side);
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'ndot' + (it.sel ? ' is-selected' : ''); b.textContent = it.n;
      b.style.left = it.x + 'px'; b.style.top = it.y + 'px';
      b.setAttribute('aria-label', `${it.n}, ${it.name}`); b.setAttribute('aria-expanded', 'false');
      b.title = it.name;
      stage.appendChild(b);       // appended in number order, so Tab walks them 1, 2, 3 ...
      it.btn = b;
    });
    const room = { id, cfg, section, app, stage, svg, items, open: new Set(items.filter(it => it.sel).map(it => it.key)),
                   ghost: null, term: null };
    items.forEach(it => {
      it.btn.addEventListener('click', () => toggle(room, it.key));
      it.btn.addEventListener('mouseenter', () => { room.ghost = it.key; render(room); });
      it.btn.addEventListener('mouseleave', () => { room.ghost = null; render(room); });
      it.btn.addEventListener('focus', () => { room.ghost = it.key; render(room); });
      it.btn.addEventListener('blur', () => { room.ghost = null; render(room); });
    });
    buildControls(room);
    return room;
  }

  const labelsOn = room => room.app.dataset.labels !== 'off';
  function toggle(room, key) { room.open.has(key) ? room.open.delete(key) : room.open.add(key); room.ghost = null; render(room); }
  function setAll(room, on) { room.open = new Set(on ? room.items.map(it => it.key) : []); render(room); }
  const allOpen = room => room.items.every(it => room.open.has(it.key));

  /* ----------------------------------------------------------------------------------------- Show all, the key */
  function buildControls(room) {
    const { section, items } = room;
    // 1: the second half of a two-part Labels control in the dock
    const lab = [...section.querySelectorAll('.dock button')].find(b => b.textContent.trim() === 'Labels');
    if (lab) {
      lab.classList.add('lb-main');
      lab.setAttribute('aria-pressed', labelsOn(room) ? 'true' : 'false');
      const pair = document.createElement('span'); pair.className = 'lb-pair';
      pair.innerHTML = '<i class="lb-div" aria-hidden="true"></i><button type="button" class="showall" data-showall>Show all</button>';
      lab.after(pair);
      lab.addEventListener('click', () => { room.app.dataset.labels = labelsOn(room) ? 'off' : 'on'; render(room); });
    }
    // 2: the room's caption line gains "· 12 labels · Show all"
    const cap = section.querySelector('[data-lcap]');
    if (cap) {
      const s = document.createElement('span'); s.className = 'lcount';
      s.innerHTML = ` · <span class="num">${items.length}</span> labels · <button type="button" class="showall" data-showall>Show all</button>`;
      cap.appendChild(s);
    }
    // 3: the compact key in the top right corner
    const key = section.querySelector('[data-key]');
    if (key) {
      key.innerHTML = `<div class="lk-head"><span class="colhead">Labels</span><button type="button" class="showall" data-showall>Show all</button></div>` +
        `<ol style="${(() => { const c = items.length <= 4 ? 1 : 4, r = Math.ceil(items.length / c); return `grid-template-columns: repeat(${c}, auto); grid-template-rows: repeat(${r}, 26px)`; })()}">${items.map(it => `<li><button type="button" class="lk-row${it.sel ? ' is-selected' : ''}" data-k="${it.key}" aria-expanded="false">` +
        `<span class="ndot${it.sel ? ' is-selected' : ''}" aria-hidden="true">${it.n}</span><span class="nm">${it.name}</span></button></li>`).join('')}</ol>`;
      key.querySelectorAll('.lk-row').forEach(b => {
        const it = items.find(x => x.key === b.dataset.k);
        it.row = b;
        b.addEventListener('click', () => toggle(room, it.key));
        b.addEventListener('mouseenter', () => { room.ghost = it.key; render(room); });
        b.addEventListener('mouseleave', () => { room.ghost = null; render(room); });
      });
    }
    section.querySelectorAll('[data-showall]').forEach(b => b.addEventListener('click', () => setAll(room, !allOpen(room))));
    // lesson: a bold term shows its circle and its rail while it is hovered, labels on or off
    section.querySelectorAll('.term[data-for]').forEach(t => {
      t.addEventListener('mouseenter', () => { room.term = t.dataset.for; render(room); });
      t.addEventListener('mouseleave', () => { room.term = null; render(room); });
    });
  }

  /* ----------------------------------------------------------------------------------------- draw */
  function render(room) {
    const { cfg, svg, items, section } = room, on = labelsOn(room);
    const [, ay0r, , ay1] = cfg.area;
    // the corner key (option 3) sits top right: names on the right rail stay below it
    const key = section.querySelector('[data-key]');
    const keyB = key && key.offsetHeight ? key.getBoundingClientRect().bottom - section.querySelector('.app').getBoundingClientRect().top + 24 : 0;
    svg.innerHTML = '';
    const shown = it => on || it.key === room.term;                         // circle visible
    const railed = it => shown(it) && (room.open.has(it.key) && on || it.key === room.term || it.key === room.ghost);
    items.forEach(it => {
      const vis = shown(it), open = on && room.open.has(it.key);
      it.btn.hidden = !vis;
      it.btn.classList.toggle('is-open', open || it.key === room.term);
      it.btn.classList.toggle('is-term', it.key === room.term);
      it.btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (it.row) { it.row.setAttribute('aria-expanded', open ? 'true' : 'false'); it.row.classList.toggle('is-open', open);
                    it.row.classList.toggle('is-hover', it.key === room.ghost); }
      it.e.hidden = !railed(it);
      it.e.classList.toggle('is-ghost', railed(it) && !open && it.key !== room.term);
      it.e.classList.toggle('is-term', it.key === room.term);
    });
    for (const side of ['left', 'right']) {
      const X = side === 'left' ? cfg.rails[0] : cfg.rails[1];
      const col = items.filter(it => it.side === side && railed(it)).sort((a, b) => a.y - b.y);
      if (X == null || !col.length) continue;
      const ay0 = side === 'right' ? Math.max(ay0r, keyB) : ay0r;
      const pitch = 30, ys = col.map(it => it.y);
      for (let i = 1; i < ys.length; i++) ys[i] = Math.max(ys[i], ys[i - 1] + pitch);
      for (let i = ys.length - 1; i >= 0; i--) ys[i] = Math.min(ys[i], i === ys.length - 1 ? ay1 - 12 : ys[i + 1] - pitch);
      for (let i = 0; i < ys.length; i++) ys[i] = Math.max(ys[i], i ? ys[i - 1] + pitch : ay0 + 12);
      const solid = col.filter(it => !it.e.classList.contains('is-ghost'));
      const sy = (solid.length ? solid : col).map(it => ys[col.indexOf(it)]);
      svgEl('path', { d: `M${X},${Math.min(...sy) - 9} L${X},${Math.max(...sy) + 9}`, class: 'rail' }, svg);
      col.forEach((it, i) => {
        const w = it.e.offsetWidth, h = it.e.offsetHeight;
        const x0 = side === 'left' ? X - 12 - w : X + 12;
        it.e.style.left = x0 + 'px'; it.e.style.top = (ys[i] - h / 2) + 'px';
        const kx = side === 'left' ? Math.max(X + 12, it.x - cfg.reach) : Math.min(X - 12, it.x + cfg.reach);
        // the leader stops at the circle's edge (r 9 plus a 2 px gap)
        const dx = it.x - kx, dy = it.y - ys[i], d = Math.hypot(dx, dy) || 1, ex = it.x - dx / d * 11, ey = it.y - dy / d * 11;
        const cls = 'leader' + (it.sel ? ' is-selected' : '') + (it.e.classList.contains('is-ghost') ? ' is-ghost' : '') + (it.key === room.term ? ' is-term' : '');
        svgEl('path', { d: `M${X},${ys[i]} L${kx},${ys[i]} L${ex},${ey}`, class: cls }, svg);
        it.lead = Math.hypot(X - kx, 0) + d - 11;
      });
    }
    section.querySelectorAll('[data-showall]').forEach(b => { b.textContent = allOpen(room) && on ? 'Hide all' : 'Show all'; });
    const lab = section.querySelector('.dock .lb-main');
    if (lab) { lab.classList.toggle('on', on); lab.setAttribute('aria-pressed', on ? 'true' : 'false'); }
    room.app.classList.toggle('labels-all', on && allOpen(room));
  }

  /* ----------------------------------------------------------------------------------------- practice markers */
  function practice(section) {
    const stage = section.querySelector('[data-stage="markers"]');
    if (!stage) return;
    const state = ['wrong1', 'wrong2', 'right'].includes(LSTATE) ? LSTATE : 'wrong2';
    section.querySelector('.app').dataset.pstate = state;
    const hunt = q.get('mode') === 'hunt';
    section.querySelector('.app').dataset.mode = hunt ? 'hunt' : 'find';
    const img = stage.querySelector('img.plate'), A = anchorsFor(img);
    const sr = stage.getBoundingClientRect(), ir = img.getBoundingClientRect();
    const k = ir.width / img.naturalWidth, ox = ir.left - sr.left, oy = ir.top - sr.top;
    const svg = stage.querySelector(':scope > svg.leaders') || svgEl('svg', { class: 'leaders', 'aria-hidden': 'true' }, stage);
    svg.innerHTML = '';
    svg.setAttribute('viewBox', `0 0 ${sr.width} ${sr.height}`); svg.setAttribute('width', sr.width); svg.setAttribute('height', sr.height);
    const RAILS = { left: 492, right: 1544 }, reach = 40;
    const marks = [...stage.querySelectorAll('.pmark')].filter(m => m.dataset.show.split(' ').includes(state));
    stage.querySelectorAll('.pmark, .lbl[data-a]').forEach(m => { m.hidden = true; });
    const items = marks.map(m => {
      const a = A[m.dataset.a]; const x = ox + a.x * k, y = oy + a.y * k;
      m.hidden = false; m.style.left = x + 'px'; m.style.top = y + 'px';
      const e = stage.querySelector(`.lbl[data-a="${m.dataset.a}"]`);
      return { m, e, x, y, side: m.dataset.side, right: m.classList.contains('is-right') };
    });
    if (!hunt) for (const side of ['left', 'right']) {
      const col = items.filter(it => it.side === side && it.e).sort((a, b) => a.y - b.y), X = RAILS[side];
      if (!col.length) continue;
      const ys = col.map(it => it.y);
      for (let i = 1; i < ys.length; i++) ys[i] = Math.max(ys[i], ys[i - 1] + 30);
      svgEl('path', { d: `M${X},${ys[0] - 9} L${X},${ys[ys.length - 1] + 9}`, class: 'rail' }, svg);
      col.forEach((it, i) => {
        it.e.hidden = false; it.e.classList.add(side);
        const w = it.e.offsetWidth, h = it.e.offsetHeight, x0 = side === 'left' ? X - 12 - w : X + 12;
        it.e.style.left = x0 + 'px'; it.e.style.top = (ys[i] - h / 2) + 'px';
        const kx = side === 'left' ? Math.max(X + 12, it.x - reach) : Math.min(X - 12, it.x + reach);
        const r = it.right ? 15 : 14, dx = it.x - kx, dy = it.y - ys[i], d = Math.hypot(dx, dy) || 1;
        svgEl('path', { d: `M${X},${ys[i]} L${kx},${ys[i]} L${it.x - dx / d * r},${it.y - dy / d * r}`, class: 'leader' + (it.right ? ' is-right' : ' is-miss') }, svg);
      });
    }
    section.querySelectorAll('[data-pshow]').forEach(el => { el.hidden = !el.dataset.pshow.split(' ').includes(hunt ? state + '-hunt' : state) && !el.dataset.pshow.split(' ').includes(state); });
  }

  /* ----------------------------------------------------------------------------------------- states, keys */
  function run() {
    const id = R.dataset.screen, section = document.querySelector(`[data-screen-id="${id}"]`);
    if (section && id === 'practice') practice(section);
    const room = section && setup(section);
    if (room) {
      rooms[id] = room;
      if (id === 'lesson') {
        room.open.clear();
        room.app.dataset.labels = LSTATE === 'all' ? 'on' : 'off';
        if (LSTATE === 'all') room.items.forEach(it => room.open.add(it.key));
        if (LSTATE === 'term') room.term = room.cfg.term;
      } else {
        room.app.dataset.labels = 'on';
        if (LSTATE === 'one' && room.cfg.one) room.open.add(room.cfg.one);
        if (LSTATE === 'all') room.items.forEach(it => room.open.add(it.key));
      }
      render(room);
      if (LSTATE === 'term') section.querySelectorAll(`.term[data-for="${room.cfg.term}"]`).forEach(t => t.classList.add('is-lit'));
      document.addEventListener('keydown', e => { if (e.key === 'Escape') { room.open.clear(); room.ghost = null; render(room); } });
      section.querySelectorAll('.term[data-for]').forEach(t => {
        t.addEventListener('mouseenter', () => t.classList.add('is-lit'));
        t.addEventListener('mouseleave', () => t.classList.remove('is-lit'));
      });
      window.LBL3 = room;
    }
    R.dataset.labels = '1';
  }
  (function wait() { R.dataset.ready === '1' ? run() : setTimeout(wait, 25); })();
})();
