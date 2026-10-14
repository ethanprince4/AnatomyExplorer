/* Layered Human design mockups: shared engine.
 *
 * Every screen is plain HTML/CSS. This script only does what a static page cannot:
 *  - reads ?scheme=&screen= and sets data attributes (the CSS does the rest);
 *  - picks each scheme's plate (a real render from the app, with that scheme's selection colour baked in);
 *  - turns ID-buffer anchors (plate pixels) into page positions and draws the leader lines.
 * Anchors come from assets/plates/plates.json (tools/process_plates.py) and the *.anchors.json beside model plates.
 */
(function () {
  const params = new URLSearchParams(location.search);
  const root = document.documentElement;
  const BASE = root.dataset.base || '../../';

  function setState() {
    const schemes = (window.LH_SCHEMES || {});
    const design = root.dataset.design;
    const scheme = params.get('scheme') || root.dataset.scheme;
    const screen = params.get('screen') || root.dataset.screen;
    if (scheme) root.dataset.scheme = scheme;
    if (screen) root.dataset.screen = screen;
    const info = schemes[design] && schemes[design].schemes[root.dataset.scheme];
    if (info) root.dataset.mode = info.mode;
    return info;
  }

  function cssVar(name) {
    return getComputedStyle(root).getPropertyValue(name).trim();
  }

  async function loadJSON(url) {
    try {
      const r = await fetch(url);
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  /* ----------------------------------------------------------------------------------------- plates */
  function plateURL(name) {
    const sel = cssVar('--select').replace('#', '').toLowerCase();
    return BASE + 'assets/plates/' + name.replace('{select}', sel) + '.webp';
  }

  function waitImg(img) {
    // complete is also true for an image that already failed; never wait on one that will not load
    if (img.complete) return Promise.resolve();
    return new Promise(res => { img.addEventListener('load', res, { once: true }); img.addEventListener('error', res, { once: true }); });
  }

  /* ----------------------------------------------------------------------------------------- labels */
  // Plate pixels -> coordinates inside `stage` (the positioned ancestor that holds the SVG layer).
  function toStage(img, stage, pt) {
    const ir = img.getBoundingClientRect();
    const sr = stage.getBoundingClientRect();
    const k = ir.width / img.naturalWidth;
    return { x: ir.left - sr.left + pt.x * k, y: ir.top - sr.top + pt.y * k, k };
  }

  function svgLayer(stage) {
    let svg = stage.querySelector(':scope > svg.leaders');
    if (!svg) {
      svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('class', 'leaders');
      svg.setAttribute('aria-hidden', 'true');
      stage.appendChild(svg);
    }
    const r = stage.getBoundingClientRect();
    svg.setAttribute('viewBox', `0 0 ${r.width} ${r.height}`);
    svg.setAttribute('width', r.width);
    svg.setAttribute('height', r.height);
    return svg;
  }

  function path(svg, d, cls) {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', d);
    p.setAttribute('class', cls);
    svg.appendChild(p);
    return p;
  }

  function dot(svg, x, y, cls) {
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('cx', x); c.setAttribute('cy', y); c.setAttribute('r', 1);
    c.setAttribute('class', cls);
    svg.appendChild(c);
  }

  // Tag labels: each .lbl[data-anchor] sits at anchor + (data-dx, data-dy); the leader runs from the anchor to the
  // nearest point on the label's edge (an elbow when data-elbow is set).
  function layoutTags(stage, img, anchors) {
    const svg = svgLayer(stage);
    stage.querySelectorAll('.lbl[data-anchor]').forEach(el => {
      const a = anchors[el.dataset.anchor];
      if (!a) { el.style.display = 'none'; return; }
      const p = toStage(img, stage, a);
      const dx = parseFloat(el.dataset.dx || 0), dy = parseFloat(el.dataset.dy || 0);
      const w = el.offsetWidth, h = el.offsetHeight;
      const side = dx < 0 ? 'left' : 'right';
      const lx = side === 'left' ? p.x + dx - w : p.x + dx;
      const ly = p.y + dy - h / 2;
      el.style.left = lx + 'px';
      el.style.top = ly + 'px';
      const ex = side === 'left' ? lx + w : lx;
      const ey = ly + h / 2;
      const cls = 'leader' + (el.classList.contains('is-selected') ? ' is-selected' : '');
      const mid = side === 'left' ? ex + 14 : ex - 14;
      path(svg, `M${ex},${ey} L${mid},${ey} L${p.x},${p.y}`, cls);
      dot(svg, p.x, p.y, 'anchor' + (el.classList.contains('is-selected') ? ' is-selected' : ''));
    });
  }

  // Atlas-plate columns: labels sorted by anchor height into a left and a right column at fixed x, pushed apart
  // so they never overlap, each joined to its anchor by a horizontal run and one diagonal.
  function layoutColumns(stage, img, anchors) {
    const svg = svgLayer(stage);
    const cols = { left: [], right: [] };
    stage.querySelectorAll('.lbl[data-col]').forEach(el => {
      const a = anchors[el.dataset.anchor];
      if (!a) { el.style.display = 'none'; return; }
      const p = toStage(img, stage, a);
      cols[el.dataset.col].push({ el, p });
    });
    const sr = stage.getBoundingClientRect();
    const ir = img.getBoundingClientRect();
    const gap = parseFloat(cssVar('--col-gap') || 56);
    // Columns sit at fixed stage positions when the stage names them (an atlas plate's margins), otherwise
    // a fixed gap outside the figure.
    const leftX = stage.dataset.colLeft ? parseFloat(stage.dataset.colLeft) : ir.left - sr.left - gap;
    const rightX = stage.dataset.colRight ? parseFloat(stage.dataset.colRight) : ir.right - sr.left + gap;
    const top = parseFloat(stage.dataset.colTop || 24), bottom = sr.height - parseFloat(stage.dataset.colBottom || 24);
    for (const [side, items] of Object.entries(cols)) {
      items.sort((a, b) => a.p.y - b.p.y);
      const hs = items.map(it => it.el.offsetHeight);
      const ys = items.map((it, i) => Math.max(top, it.p.y - hs[i] / 2));
      const spacing = parseFloat(cssVar('--col-spacing') || 8);
      for (let i = 1; i < ys.length; i++) ys[i] = Math.max(ys[i], ys[i - 1] + hs[i - 1] + spacing);
      for (let i = ys.length - 1; i >= 0; i--) {
        const limit = i === ys.length - 1 ? bottom - hs[i] : ys[i + 1] - spacing - hs[i];
        ys[i] = Math.min(ys[i], limit);
      }
      items.forEach((it, i) => {
        const el = it.el, w = el.offsetWidth, h = hs[i];
        const x = side === 'left' ? leftX - w : rightX;
        el.style.left = x + 'px';
        el.style.top = ys[i] + 'px';
        const ey = ys[i] + h / 2;
        const ex = side === 'left' ? leftX + 6 : rightX - 6;
        // Run level from the label, then turn towards the anchor for the last stretch, as a plate's leaders do.
        const reach = parseFloat(stage.dataset.knee || 0);
        const knee = reach
          ? (side === 'left' ? Math.min(it.p.x - 12, Math.max(ex + 12, it.p.x - reach)) : Math.max(it.p.x + 12, Math.min(ex - 12, it.p.x + reach)))
          : (side === 'left' ? leftX + gap * 0.45 : rightX - gap * 0.45);
        const cls = 'leader' + (el.classList.contains('is-selected') ? ' is-selected' : '');
        path(svg, `M${ex},${ey} L${knee},${ey} L${it.p.x},${it.p.y}`, cls);
        dot(svg, it.p.x, it.p.y, 'anchor' + (el.classList.contains('is-selected') ? ' is-selected' : ''));
      });
    }
  }

  // Image labels (films, micrographs): .pin[data-x][data-y] in 0..1 of the image.
  function layoutPins(scope) {
    scope.querySelectorAll('.pinned').forEach(box => {
      const img = box.querySelector('img');
      box.querySelectorAll('.pin').forEach(pin => {
        pin.style.left = (parseFloat(pin.dataset.x) * 100) + '%';
        pin.style.top = (parseFloat(pin.dataset.y) * 100) + '%';
      });
    });
  }

  async function run() {
    const info = setState();
    const meta = window.LH_PLATES || { plates: {}, anchors: {} };
    const screen = root.dataset.screen;
    const section = document.querySelector(`[data-screen-id="${screen}"]`) || document;
    const imgs = [...section.querySelectorAll('img[data-plate]')];
    imgs.forEach(img => { img.src = plateURL(img.dataset.plate); });
    await Promise.all([...section.querySelectorAll('img')].map(waitImg));
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    for (const img of imgs) {
      const stage = img.closest('[data-stage]');
      if (!stage) continue;
      const sel = cssVar('--select').replace('#', '').toLowerCase();
      const key = (img.dataset.anchors || img.dataset.plate).replace('{select}', sel);
      const anchors = (meta.anchors && meta.anchors[key]) || {};
      if (stage.dataset.stage === 'columns') layoutColumns(stage, img, anchors);
      else layoutTags(stage, img, anchors);
    }
    layoutPins(section);
    root.dataset.ready = '1';
  }

  window.LH = { run, cssVar };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
})();
