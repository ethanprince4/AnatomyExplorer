/* Search for the Specimen atlas (checkpoint 3). One markup, three treatments by html[data-variant]:
 *   1 On the body  - numbered circles on the matching structures, a short list lettered beside the body
 *   2 The index    - the wall becomes an atlas index; the body steps back and dims
 *   3 In the title - the room's title is the search; results letter themselves under it
 * The matcher is a line-for-line port of app/search.py SearchIndex.search/_score over a real slice of the index
 * (search-index.js). PROPOSED marks the one addition: the typo fallback also compares the query with each word's first
 * letters, so "bycep" finds biceps. URL: ?variant=1|2|3&q=<query>&state=open|chosen&hover=<row>. */
(function () {
  const R = document.documentElement, P = new URLSearchParams(location.search);
  R.dataset.variant = P.get('variant') || R.dataset.variant || '1';
  const IDX = window.LH_SEARCH, PROPOSED = P.get('matcher') !== 'today';

  /* ------------------------------------------------------------------ the matcher (app/search.py) */
  const norm = t => (t || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/—/g, ' ')
    .replace(/[^a-z0-9]+/g, ' ').trim();
  const ENTRIES = IDX.entries.map(([kind, title, subtitle, alt, system]) => {
    const n = norm(title), na = norm(alt);
    return { kind, title, subtitle, alt, system, norm: n, words: n.split(' '), normAlt: na, altWords: na ? na.split(' ') : [] };
  });
  function score(n, words, q, qw) {
    if (!n) return 0;
    if (n === q) return 100;
    if (n.startsWith(q)) return 90;
    if (qw.every(x => words.some(w => w.startsWith(x)))) return words[0] && words[0].startsWith(qw[0]) ? 80 : 75;
    if (n.includes(q)) return 65;
    return 0;
  }
  const BONUS = { structure: 3, group: 2, landmark: 0, clinical: 1, tissue: 1, micro: 1, lesson: 2, radiology: 2 };
  function lcsBlocks(a, b) {   // difflib.SequenceMatcher matching characters (no junk: the strings are short)
    if (!a.length || !b.length) return 0;
    let best = 0, bi = 0, bj = 0;
    for (let i = 0; i < a.length; i++) for (let j = 0; j < b.length; j++) {
      let k = 0; while (i + k < a.length && j + k < b.length && a[i + k] === b[j + k]) k++;
      if (k > best) { best = k; bi = i; bj = j; }
    }
    if (!best) return 0;
    return best + lcsBlocks(a.slice(0, bi), b.slice(0, bj)) + lcsBlocks(a.slice(bi + best), b.slice(bj + best));
  }
  const ratio = (a, b) => (a.length + b.length) ? 2 * lcsBlocks(a, b) / (a.length + b.length) : 0;
  function search(query) {
    let q = norm(query);
    if (!q) return { list: [], fuzzy: false };
    q = IDX.synonyms[q] || q;
    const qw = q.split(' '), out = [];
    for (const e of ENTRIES) {
      let s = score(e.norm, e.words, q, qw);
      if (e.normAlt) { const a = score(e.normAlt, e.altWords, q, qw); s = Math.max(s, a ? a - 4 : 0); }
      if (s <= 0) continue;
      s += BONUS[e.kind];
      if (e.system === 'attachments') s -= 6; else if (e.system === 'reference') s -= 3;
      s -= Math.min(e.norm.length, 80) * 0.05;
      out.push([s, e]);
    }
    let fuzzy = false;
    if (!out.length && q.length >= 4) {
      for (const e of ENTRIES) {
        let r = Math.max(0, ...e.words.map(w => Math.max(ratio(q, w), PROPOSED && w.length > q.length ? ratio(q, w.slice(0, q.length)) : 0)));
        r = Math.max(r, ratio(q, e.norm));
        if (r >= 0.78) out.push([r * 40, e]);
      }
      fuzzy = out.length > 0;
    }
    out.sort((x, y) => y[0] - x[0]);
    return { list: out.slice(0, 150).map(x => x[1]), fuzzy, q };
  }
  window.LH_SEARCH_RUN = search;

  /* ------------------------------------------------------------------ presentation: kinds, folding, places */
  const KINDS = [['Structures', ['structure', 'group', 'landmark']], ['Lessons', ['lesson']], ['Radiology', ['radiology']],
                 ['Histology', ['tissue']], ['Models', ['micro']], ['Clinical', ['clinical']]];
  const kindOf = e => KINDS.find(k => k[1].includes(e.kind))[0];
  // structures the atlas figure has a point for (assets/plates hero26 anchors, both sides)
  const ANCHOR = { 'biceps brachii muscle': 'biceps', 'long head of biceps brachii': 'biceps', 'short head of biceps brachii': 'biceps',
    'deltoid muscle': 'deltoid', 'acromial part of deltoid muscle': 'deltoid', 'clavicular part of deltoid muscle': 'deltoid',
    'scapular spinal part of deltoid muscle': 'deltoid', 'pectoralis major muscle': 'pectoralis', 'serratus anterior muscle': 'serratus',
    'rectus abdominis muscle': 'rectus_abdominis', 'brachioradialis muscle': 'brachioradialis', 'brachialis muscle': 'brachialis',
    'sartorius muscle': 'sartorius', 'rectus femoris muscle': 'rectus_femoris', 'vastus lateralis muscle': 'vastus_lateralis',
    'vastus medialis muscle': 'vastus_medialis', 'tibialis anterior muscle': 'tibialis_anterior', 'adductor longus': 'adductor_longus',
    'flexor carpi radialis': 'flexor_carpi_radialis', 'patella': 'patella', 'lateral head of gastrocnemius': 'gastrocnemius',
    'medial head of gastrocnemius': 'gastrocnemius' };
  const anchorOf = e => (e.system === 'muscular' || e.system === 'skeletal') ? ANCHOR[e.norm] || null : null;
  const SYS = { muscular: 'Muscular system', skeletal: 'Skeletal system', cardiovascular: 'Cardiovascular system', nervous: 'Nervous system',
    joints: 'Joints & ligaments', regions: 'Skin & surface regions', lymphatic: 'Lymphatic system', visceral: 'Visceral organs',
    fascia: 'Fascia', findings: 'Findings', attachments: 'Muscle attachments', reference: 'Reference' };
  const shown = t => t.replace(/ — /g, ', ');
  function meta(e) {
    const s = e.subtitle;
    if (e.kind === 'group') { const m = s.match(/(\d+) structures · (.*)$/); return m ? `${m[2]} · ${m[1]} parts` : s; }
    if (e.kind === 'structure' && e.system === 'attachments') return s.replace('Muscle attachment on ', 'Attachment on the ').replace(/the (\w+)$/, (x, b) => 'the ' + b.toLowerCase());
    if (['lesson', 'radiology', 'clinical', 'tissue'].includes(e.kind)) return s.replace(/^(Lesson|Radiology|Clinical|Histology) · /, '');
    return s;
  }
  // Fold parts under their head word, as a printed index does: "Biceps brachii muscle: long head, short head, insertion".
  function fold(structs) {
    const heads = [];
    const isMuscleHead = e => e.kind === 'group' && e.system !== 'attachments' ||
      e.kind === 'structure' && !/ — /.test(e.title) && e.system !== 'attachments' && /muscle$/.test(e.norm);
    for (const e of structs) if (isMuscleHead(e)) heads.push({ e, parts: [], core: e.norm.replace(/ muscle$/, '') });
    // a muscle known here only by its attachments ("Biceps femoris muscle", Muscle attachments) heads its own parts
    for (const e of structs) if (e.kind === 'group' && e.system === 'attachments') {
      const core = e.norm.replace(/ muscle$/, '');
      if (!heads.some(h => h.core === core)) heads.push({ e, parts: [], core });
    }
    const owner = e => heads.find(h => h.e !== e && h.core.length > 4 && (e.norm.includes(h.core + ' muscle') || e.norm.endsWith(' of ' + h.core) ||
      e.norm.includes(' of ' + h.core + ' ') || e.norm === h.core));
    const rows = [];
    for (const e of structs) {
      const h0 = heads.find(h => h.e === e);
      const h = owner(e);
      if (h0 && !(h && h0.e.system === 'attachments')) { rows.push(h0); continue; }
      if (h) {
        const [a, b] = e.title.split(new RegExp('\\s*(?:of\\s+)?' + h.core + '(?:\\s+muscle)?\\s*(?:—\\s*)?', 'i')).map(x => (x || '').trim());
        let label = a && b ? a + ', ' + b : a || b;
        if (e.kind === 'group' || !label) label = 'attachments';
        label = label.charAt(0).toLowerCase() + label.slice(1);
        if (!h.parts.some(p => p.label === label)) h.parts.push({ e, label });
      } else rows.push({ e, parts: [] });
    }
    for (const h of heads) h.parts.sort((x, y) => (x.e.system === 'attachments') - (y.e.system === 'attachments'));
    if (V() === '1') rows.sort((x, y) => !!anchorOf(y.e) - !!anchorOf(x.e));   // on the body: what is in view comes first
    return rows;
  }
  function group(list) {
    const g = KINDS.map(([name]) => ({ name, items: [] }));
    for (const e of list) g.find(x => x.name === kindOf(e)).items.push(e);
    g[0].rows = fold(g[0].items);
    for (const x of g.slice(1)) x.rows = x.items.map(e => ({ e, parts: [] }));
    return g.filter(x => x.rows.length);
  }
  const esc = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
  function mark(text, q) {   // the letters that matched: each query word at the start of a word, else the substring
    if (!q) return esc(text);
    const words = q.split(' ').filter(Boolean);
    let out = '', hit = false;
    text.split(/(\s+)/).forEach(tok => {
      const n = norm(tok), w = words.find(x => n.startsWith(x) && x.length);
      if (w && n.length) { hit = true; out += `<mark>${esc(tok.slice(0, w.length))}</mark>${esc(tok.slice(w.length))}`; }
      else out += esc(tok);
    });
    if (hit) return out;
    const i = norm(text).indexOf(q);
    return i >= 0 && norm(text).length === text.length ? esc(text.slice(0, i)) + `<mark>${esc(text.slice(i, i + q.length))}</mark>` + esc(text.slice(i + q.length)) : esc(text);
  }

  /* ------------------------------------------------------------------ state */
  const CAPS = { 1: { s: 6, o: 2 }, 2: { s: 16, o: 3 }, 3: { s: 5, o: 2 } };
  const S = { q: P.get('q') || '', open: !!P.get('q') || P.get('state') === 'open', chosen: P.get('state') === 'chosen', active: P.has('hover') && P.get('hover') !== 'auto' ? +P.get('hover') : 0,
              expand: {}, last: null };
  if (S.chosen) S.open = false;
  let app, stage, img, layer, dots, svg, field, input, title, titleLine, sectionEl, anchors, rows = [];
  const V = () => R.dataset.variant;
  const IN_VIEW = ['Biceps brachii muscle', 'Deltoid muscle', 'Serratus anterior muscle', 'Rectus abdominis muscle'];
  const RECENT = [['The coronary circulation', 'Lesson · Cardiovascular · 7 steps', 'lesson'], ['Kidney with the nephron', 'Model · 13 views', 'models'],
                  ['Chest radiograph, PA', 'Radiology · X-ray · Thorax', 'radiology']];

  function rowHTML(r, i, q) {
    const e = r.e, n = r.n ? `<span class="ndot${r.cur ? ' is-cur' : ''}">${r.n}</span>` : (r.struct ? `<span class="ndot off" title="Not in this view"></span>` : '');
    const lat = r.struct && e.alt && /^[A-Z(]/.test(e.alt) && e.kind !== 'clinical' ? `<span class="lat">${mark(e.alt.replace(/^\(|\)$/g, ''), q && !/<mark>/.test(mark(shown(e.title), q)) ? q : '')}</span>` : '';
    const own = (r.parts || []).filter(p => p.e.system !== 'attachments').map(p => esc(p.label));
    if ((r.parts || []).some(p => p.e.system === 'attachments')) own.push('attachments');
    const parts = own.length ? `<span class="pt">${own.length > 1 ? own.slice(0, -1).join(', ') + ' and ' + own[own.length - 1] : own[0]}</span>` : '';
    const where = r.struct && !r.n && V() !== '2' ? `<span class="nv">not in this view</span>` : '';
    const m0 = e.system === 'attachments' && r.parts && r.parts.find(p => p.e.system !== 'attachments');
    if (m0 && !r.meta) r.meta = meta(m0.e).replace(/ · \d+ parts$/, '');
    return `<li class="sx-r${r.struct ? ' st' : ''}" data-i="${i}">${n}<span class="tx"><span class="nm">${mark(shown(e.title), q)}</span>${lat}` +
           `<span class="mt">${esc(r.meta || meta(e))}${where}${parts}</span></span></li>`;
  }

  function build() {
    const v = V(), cap = CAPS[v];
    let groups, note = '', count = '';
    rows = [];
    if (!S.q.trim()) {
      const inView = IN_VIEW.map(t => ENTRIES.find(e => e.title === t && e.system === 'muscular')).filter(Boolean);
      groups = [{ name: 'In this view', rows: inView.map(e => ({ e, parts: [] })) },
                { name: 'Recent', rows: RECENT.map(([t, m, screen]) => ({ e: { title: t, subtitle: m, kind: 'recent', screen }, parts: [], meta: m })) }];
      note = `<p class="sx-hint">Type a name, a Latin name or a lesson.</p>`;
    } else {
      const res = search(S.q);
      S.last = res;
      count = res.list.length;
      groups = group(res.list);
      if (!res.list.length) note = `<p class="sx-none"><span class="big">Nothing for “${esc(S.q.trim())}”.</span>` +
        `<span>Check the spelling, or try one word or the Latin name.</span>` +
        `<span class="browse">Or browse <a data-go="atlas">Systems</a>, <a data-go="lessons">Lessons</a>, <a data-go="radiology">Radiology</a>, <a data-go="histology">Histology</a></span></p>`;
      else if (res.fuzzy) note = `<p class="sx-fz">No exact match for “${esc(S.q.trim())}”. Close spellings:</p>`;
      else if (v !== '3' && !res.list.some(e => anchorOf(e))) note = `<p class="sx-fz">None of these is in this view. Choosing one shows it.</p>`;
    }
    const q = S.last && S.q.trim() && !(S.last.fuzzy) ? S.last.q : '';
    const head = v === '2' ? `<div class="sx-word">${S.q.trim() ? esc(S.q.trim()) : '<span class="sx-ph">Index</span>'}<span class="sx-count num">${S.q.trim() && count ? count + (count === 1 ? ' entry' : ' entries') : ''}</span></div><button class="sx-close">Close the index</button>`
      : v === '1' && S.q.trim() && count ? `<div class="sx-count num">${count} found</div>` : '';
    const isSt = g => g.name === 'Structures' || g.name === 'In this view';
    // Each kind shows its cap, or every row when only one more would be left ("1 more" takes the room of the row it hides).
    const base = g => { const c = isSt(g) ? cap.s : cap.o; return g.rows.length === c + 1 ? c + 1 : c; };
    const keep = Object.keys(S.expand).length ? S.fit || {} : {};
    const caps = {};
    groups.forEach(g => { caps[g.name] = keep[g.name] || base(g); });
    const top = S.scroller ? S.scroller.scrollTop : 0;
    paint(groups, caps, q, head, note, v);
    // The list ends on its own "more" links: while it is taller than its room, the other kinds give up rows (the lowest
    // first, down to one each), then the structures (down to three). Opened groups are never trimmed. Whatever can still
    // overflow (opened groups, a shorter room) scrolls under the wall's own fade.
    if (!Object.keys(S.expand).length) {
      const steps = [];
      const left = (g, c) => g.rows.length - c !== 1;   // never trim to a lone "1 more"
      groups.slice().reverse().filter(g => !isSt(g)).forEach(g => { if (caps[g.name] > 1 && left(g, 1)) steps.push([g.name, 1]); });
      groups.filter(isSt).forEach(g => { for (let c = caps[g.name] - 1; c >= 3; c--) if (left(g, c)) steps.push([g.name, c]); });
      groups.slice().reverse().filter(g => !isSt(g)).forEach(g => { if (caps[g.name] > 1 && !left(g, 1)) steps.push([g.name, 1]); });   // last resort
      for (const [name, c] of steps) {
        if (fits()) break;
        caps[name] = c;
        paint(groups, caps, q, head, note, v);
      }
      S.fit = caps;
    } else S.scroller.scrollTop = top;
    if (P.get('hover') === 'auto' && !S.autoDone) { S.autoDone = true; const k = rows.findIndex(r => r.anchor); S.active = k < 0 ? 0 : k; }
    S.active = Math.min(S.active, rows.length - 1);
    placeDots();
    fade();
    paintActive();
    if (v === '3') {
      titleLine.innerHTML = S.q.trim() ? `<span class="num">${count ? count + ' found' : 'Nothing found'}</span> · <a class="sx-back">back to Muscles, anterior view</a>` : `<a class="sx-back">back to Muscles, anterior view</a>`;
    }
  }
  const fits = () => S.scroller.scrollHeight <= S.scroller.clientHeight + 1;
  // the fade shows only where a line runs under an edge: at the foot while more is below, at the head once scrolled
  function fade() {
    const el = S.scroller; if (!el) return;
    const over = !fits();
    el.classList.toggle('sx-over', over);
    el.classList.toggle('sx-below', over && el.scrollTop + el.clientHeight < el.scrollHeight - 2);
    el.classList.toggle('sx-above', over && el.scrollTop > 2);
  }

  function paint(groups, caps, q, head, note, v) {
    let num = 0, i = 0;
    rows = [];
    const html = groups.map(g => {
      const st = g.name === 'Structures' || g.name === 'In this view';
      const limit = S.expand[g.name] ? 999 : caps[g.name];
      const vis = g.rows.slice(0, limit);
      const lis = vis.map(r => {
        r.struct = st && r.e.kind !== 'recent';
        r.anchor = r.struct ? anchorOf(r.e) : null;
        if (r.anchor) { r.n = ++num; r.cur = r.anchor === 'biceps'; }
        rows.push(r);
        return rowHTML(r, i++, q);
      }).join('');
      const more = g.rows.length > vis.length ? `<button class="sx-more" data-more="${g.name}">${g.rows.length - vis.length} more ${g.name === 'Structures' ? 'structures' : g.name.toLowerCase()}</button>` : '';
      return `<section class="sx-g${st ? ' is-st' : ''}" data-kind="${g.name}"><h3 class="sx-h">${g.name}${S.q.trim() ? ` <span class="n num">${g.rows.length}</span>` : ''}</h3><ol>${lis}</ol>${more}</section>`;
    }).join('');
    layer.innerHTML = `<div class="sx-panel">${head}${note}<div class="sx-cols">${html}</div></div>`;
    S.scroller = layer.querySelector(v === '2' ? '.sx-cols' : '.sx-panel');
    S.scroller.addEventListener('scroll', () => { fade(); paintActive(); }, { passive: true });
  }

  /* ------------------------------------------------------------------ circles on the body */
  function stagePt(a) {
    const k = img.offsetHeight / img.naturalHeight;
    return { x: img.offsetLeft + a.x * k, y: img.offsetTop + a.y * k };
  }
  function placeDots() {
    dots.innerHTML = '';
    const v = V();
    if (v === '3') return;
    rows.forEach((r, i) => {
      if (!r.anchor) return;
      ['vl', 'vr'].forEach(side => {
        const a = anchors[r.anchor + '.' + side]; if (!a) return;
        const p = stagePt(a), d = document.createElement('span');
        d.className = 'ndot on-body' + (r.cur ? ' is-cur' : ''); d.textContent = r.n; d.dataset.i = i;
        d.style.left = p.x + 'px'; d.style.top = p.y + 'px';
        dots.appendChild(d);
      });
    });
  }
  function paintActive() {
    layer.querySelectorAll('.sx-r').forEach(li => li.classList.toggle('is-active', +li.dataset.i === S.active));
    dots.querySelectorAll('.ndot').forEach(d => d.classList.toggle('is-active', +d.dataset.i === S.active));
    svg.innerHTML = '';
    const r = rows[S.active], v = V();
    if (!r || !r.anchor || v === '2') return;
    const li = layer.querySelector(`.sx-r[data-i="${S.active}"]`); if (!li) return;
    const sr = S.scroller.getBoundingClientRect(), lr = li.getBoundingClientRect();   // no line to a row under the fade
    if (S.scroller.classList.contains('sx-over') && (lr.top < sr.top || lr.bottom > sr.bottom - 112)) return;
    const ar = app.getBoundingClientRect(), z = ar.width / 1920;
    const nm = li.querySelector('.nm').getBoundingClientRect();
    const side = v === '1' ? 'vr' : 'vl', p = stagePt(anchors[r.anchor + '.' + side]);
    const NS = 'http://www.w3.org/2000/svg', path = document.createElementNS(NS, 'path'), c = document.createElementNS(NS, 'circle');
    let x0, y0 = (nm.top - ar.top) / z + 13;
    if (v === '1') { const dot = li.querySelector('.ndot').getBoundingClientRect(); x0 = (dot.left - ar.left) / z - 8; y0 = (dot.top - ar.top) / z + 9; }
    else x0 = (nm.right - ar.left) / z + 14;
    const mid = v === '1' ? x0 - 40 : x0 + 40;
    path.setAttribute('d', `M${x0},${y0} H${mid} L${p.x + (v === '1' ? 12 : -12)},${p.y}`);
    path.setAttribute('class', 'sx-leader');
    svg.appendChild(path);
    if (v === '3') { c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); c.setAttribute('r', 7); c.setAttribute('class', 'sx-ring'); svg.appendChild(c); }
  }

  /* ------------------------------------------------------------------ open, close, choose */
  function setOpen(on) {
    S.open = on;
    app.classList.toggle('sx-on', on);
    app.classList.toggle('sx-typed', on && !!S.q.trim());
    if (on) { S.chosen = false; app.classList.remove('sx-chosen'); build(); }
    else { layer.innerHTML = ''; dots.innerHTML = ''; svg.innerHTML = ''; }
    syncTitle();
  }
  function syncTitle() {
    const v = V();
    if (v === '3') {
      title.contentEditable = S.open ? 'true' : 'false';
      if (S.open) { if (title.textContent !== S.q) title.textContent = S.q; title.classList.toggle('is-empty', !S.q); }
      else if (S.chosen) { title.textContent = 'Biceps brachii'; titleLine.innerHTML = `Musculus biceps brachii · <a class="sx-back">back to Muscles, anterior view</a>`; }
      else { title.textContent = 'Muscles, anterior view'; titleLine.textContent = '2,231 of 3,922 shown · 26% deep'; }
      input.value = '';
    } else input.value = S.q;
    field.classList.toggle('has-q', !!S.q && V() !== '3');
    const back = field.querySelector('.sx-again');
    back.hidden = !(S.chosen && S.q);
    if (S.chosen && S.q) { const n = search(S.q).list.length; back.textContent = `${n} results for “${S.q}”`; }
  }
  function choose(i) {
    const r = rows[i]; if (!r) return;
    const e = r.e;
    if (e.kind === 'recent') { location.search = `?scheme=${R.dataset.scheme}&screen=${e.screen}&variant=${V()}`; return; }
    const room = { lesson: 'lessons', radiology: 'radiology', tissue: 'histology', micro: 'models' }[e.kind];
    if (room) { location.search = `?scheme=${R.dataset.scheme}&screen=${room}&variant=${V()}`; return; }
    S.chosen = true; setOpen(false); app.classList.add('sx-chosen');
    const card = sectionEl.querySelector('.label-card');
    if (card && e.title !== 'Biceps brachii muscle') {   // the mockup has the biceps figure only; other choices rename the label
      card.querySelector('.t').textContent = shown(e.title).replace(/ muscle$/, '');
      card.querySelector('.lat').textContent = e.alt || '';
    }
    syncTitle();
  }

  function wire() {
    const ui = () => { S.active = 0; app.classList.toggle('sx-typed', !!S.q.trim()); build(); };
    // 3: the box hands the caret to the title, once the open search has made the title editable
    input.addEventListener('focus', () => { if (!S.open) { if (V() === '3') S.q = ''; setOpen(true); } if (V() === '3') { title.focus(); placeCaret(); } });
    input.addEventListener('input', () => { S.q = input.value; S.expand = {}; ui(); });
    title.addEventListener('click', () => { if (V() !== '3') return; if (!S.open) { S.q = ''; setOpen(true); } title.focus(); placeCaret(); });
    title.addEventListener('input', () => { S.q = title.textContent; title.classList.toggle('is-empty', !S.q); S.expand = {}; ui(); });
    title.addEventListener('keydown', e => { if (e.key === 'Enter') e.preventDefault(); });
    layer.addEventListener('mousemove', e => { const li = e.target.closest('.sx-r'); if (li && +li.dataset.i !== S.active) { S.active = +li.dataset.i; paintActive(); } });
    layer.addEventListener('click', e => {
      const li = e.target.closest('.sx-r'), more = e.target.closest('.sx-more');
      if (more) { S.expand[more.dataset.more] = true; build(); return; }
      if (e.target.closest('.sx-close')) { setOpen(false); return; }
      const go = e.target.closest('[data-go]');
      if (go) { location.search = `?scheme=${R.dataset.scheme}&screen=${go.dataset.go}&variant=${V()}`; return; }
      if (li) choose(+li.dataset.i);
    });
    dots.addEventListener('mousemove', e => { const d = e.target.closest('.ndot'); if (d && +d.dataset.i !== S.active) { S.active = +d.dataset.i; paintActive(); } });
    dots.addEventListener('click', e => { const d = e.target.closest('.ndot'); if (d) choose(+d.dataset.i); });
    sectionEl.addEventListener('click', e => { if (V() === '3' && e.target.closest('.sx-back')) { S.q = ''; S.chosen = false; setOpen(false); app.classList.remove('sx-chosen'); } });
    field.querySelector('.sx-again').addEventListener('click', e => { e.preventDefault(); setOpen(true); });
    document.addEventListener('mousedown', e => {
      if (!S.open) return;
      if (e.target.closest('.sx-panel, .find, .exhibit h1, .sx-dots .ndot')) return;
      setOpen(false);
    });
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); if (!S.open) { if (V() === '3') S.q = ''; setOpen(true); } (V() === '3' ? title : input).focus(); if (V() === '3') placeCaret(); return; }
      if (!S.open) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); S.active = (S.active + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length; paintActive();
        const li = layer.querySelector(`.sx-r[data-i="${S.active}"]`); if (li) li.scrollIntoView({ block: 'nearest' }); }
      else if (e.key === 'Enter') { e.preventDefault(); choose(S.active); }
      else if (e.key === 'Escape') { e.preventDefault(); S.q = ''; setOpen(false); input.blur(); title.blur(); }
    });
  }
  function placeCaret() {
    const rg = document.createRange(); rg.selectNodeContents(title); rg.collapse(false);
    const s = getSelection(); s.removeAllRanges(); s.addRange(rg);
  }

  function init() {
    sectionEl = document.querySelector('[data-screen-id="atlas"]');
    app = sectionEl.querySelector('.app');
    stage = app.querySelector('.stage'); img = stage.querySelector('img.plate');
    anchors = (window.LH_PLATES.anchors || {})[(img.dataset.anchors || '').replace('{select}', '7cc8da')] || {};
    field = app.querySelector('.find');
    field.innerHTML = `<svg class="i"><use href="#i-search"/></svg><input class="sx-in" type="text" placeholder="${{ 1: 'Search anatomy, lessons, radiology', 2: 'Search the index', 3: 'Search' }[V()]}" ` +
      `aria-label="Search" aria-keyshortcuts="Control+K" title="Search the atlas, lessons, radiology and histology" autocomplete="off" spellcheck="false">` +
      `<a class="sx-again" href="#" hidden></a>`;
    field.classList.add('sx-field');
    input = field.querySelector('input');
    title = app.querySelector('.exhibit h1'); titleLine = app.querySelector('.exhibit p');
    title.setAttribute('aria-label', 'Room title; click to search'); title.spellcheck = false;
    layer = document.createElement('div'); layer.className = 'sx'; app.appendChild(layer);
    dots = document.createElement('div'); dots.className = 'sx-dots'; stage.appendChild(dots);
    svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('class', 'sx-svg'); app.appendChild(svg);
    wire();
    if (S.open) setOpen(true);
    else if (S.chosen) { app.classList.add('sx-chosen'); syncTitle(); }
    if (S.open && P.get('caret') !== '0') {
      const t = V() === '3' ? title : input;
      t.focus({ preventScroll: true }); if (V() === '3') placeCaret(); else input.setSelectionRange(99, 99);
    }
    if (V() !== '3') getSelection().removeAllRanges();
    // the list is fitted to its room by measuring, so measure again once the faces have loaded
    document.fonts.ready.then(() => { if (S.open) build(); R.dataset.searchReady = '1'; });
  }
  const start = () => (R.dataset.ready === '1' ? init() : setTimeout(start, 30));
  start();
})();
