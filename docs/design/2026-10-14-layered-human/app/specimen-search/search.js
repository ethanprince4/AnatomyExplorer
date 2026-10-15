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
  /* Where a structure is when it is not on the body as shown (search3). Depth and place come from the app's data
     (search-index.js LH_WHERE: depth.npz from DepthIndex, centroids from anatomy.json). The figure is cut at 26%. */
  const WHERE = window.LH_WHERE || {}, CUT = 0.26, HEART_Z = 0.032;
  const STOPS = [0, .08, .16, .26, .40, .55, .70, .85];   // view_panel.DISSECTION_STOPS
  const stopAt = d => STOPS.filter(s => s <= d + 1e-6).pop();
  // Where the mockup has a picture that shows the structure itself: the plate and the point on it, in plate pixels.
  // peel40_ids: picking-buffer anchors (plates.json); body_back: placed by eye on the render, both sides.
  const SHOWN = {
    'Heart': { plate: 'peel40_ids', key: 'heart', one: true, depth: .40, title: 'Deep muscles', line: '1,526 of 3,922 shown · 40% deep' },
    'Trapezius muscle': { plate: 'body_back', back: true, pts: [[330, 470], [550, 470]], title: 'Muscles, posterior view' },
    'Biceps femoris muscle': { plate: 'body_back', back: true, pts: [[300, 1420], [580, 1420]], title: 'Muscles, posterior view' } };
  // Where no picture here shows it: the room that does. The lesson's plate has the left coronary artery's projected point.
  const ELSEWHERE = { 'Left coronary artery': { screen: 'lesson', say: 'Shown in the lesson The coronary circulation, step 2', chosen: 1 } };
  function whereOf(e) {
    const w = WHERE[e.title]; if (!w || anchorOf(e)) return null;
    const [d, z, heart] = w, show = SHOWN[e.title];
    let place;
    if (e.title === 'Heart') place = 'In the chest, behind the ribs';
    else if (heart) place = /leaflet|cusp|valv/i.test(e.title) ? (/aort/i.test(e.alt || '') ? 'Inside the heart, in the aortic valve' : 'Inside the heart')
      : z > HEART_Z + .015 ? 'On the front of the heart' : z < HEART_Z - .015 ? 'On the back of the heart' : 'On the heart';
    else if (e.system === 'regions') place = 'On the skin surface';
    else if (z < -.03) place = 'On the back';
    else place = d >= CUT ? 'Under this layer' : 'Above this layer, peeled away';
    const room = ELSEWHERE[e.title] || (heart && !show ? { screen: 'models', say: 'Shown whole on the Heart model' } : null);
    const to = show ? (show.back ? (d >= CUT ? CUT : stopAt(d)) : show.depth) : null;
    const go = show && show.back ? (to === CUT ? 'Choosing it turns the body round' : `Choosing it turns the body round and lifts the cut to ${Math.round(to * 100)}%`)
      : show ? `Choosing it peels to ${Math.round(to * 100)}%` : room ? room.say
      : d < CUT ? `Choosing it lifts the cut to ${Math.round(stopAt(d) * 100)}%` : 'Choosing it shows it through what lies in front';
    return { text: `${place}, ${Math.round(d * 100)}% deep`, go, d, to, show, room };
  }
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
  // A lesson, film or case found by its text rather than its name says what it mentions: "The liver · mentions the
  // coronary ligaments". The phrase is the structure name the word sits in, as the text lists it ("Severe coronary
  // stenosis"), else the word with the describing word beside it ("papillary muscles", "bicuspid aortic valve"), else
  // the word alone. Abbreviations and nerve numerals keep their capitals: "the facial nerve VII".
  const STOP = new Set(['and', 'the', 'of', 'in', 'to', 'with', 'a', 'an', 'from', 'at', 'on', 'or', 'by', 'for', 'into', 'its',
    'that', 'which', 'who', 'during', 'itself', 'when', 'while', 'is', 'are', 'was', 'were', 'be', 'as', 'than', 'then', 'also',
    'both', 'each', 'all', 'one', 'two', 'this', 'these', 'those', 'their', 'it', 'they', 'can', 'may', 'not', 'but']);
  // words that open a sentence rather than a name: "Behind the heart", "Four muscles", "Explain cervical spinal nerve
  // numbering", and the sources' own marks ("Source-marked coronary stenosis")
  const NOT_NAME = new Set(('a an behind between beneath under over above below through within inside outside about after before how why ' +
    'what when where which this that these those its their one two three four five six seven eight nine ten twelve twenty thirty both each ' +
    'all some most many name list trace explain relate describe identify compare distinguish locate follow find show use read recognise ' +
    'recognize predict state define outline palpate demonstrate contrast match label count apply map sketch draw view see note look check').split(' '));
  const notName = w => /^source-/i.test(w) || NOT_NAME.has(norm(w).split(' ')[0]);
  const DESCRIBES = /(ary|al|ic|ac|ous|ior|ar|ate|ine|ile|ent|ant|ive|oid|id|eal|ial|ian|ed|ing)$/;
  function why(e, q) {
    if (!q || !['lesson', 'radiology', 'clinical', 'tissue'].includes(e.kind) || !e.alt) return '';
    const qw = q.split(' ');
    if (score(e.norm, e.words, q, qw) > 0 || norm(e.subtitle).split(' ').some(w => w.startsWith(qw[0]))) return '';
    const ws = e.alt.split(/\s+/), hit = k => norm(ws[k]).startsWith(qw[0]);
    const cap = w => /^[A-Z]/.test(w), ends = w => /[.,;:!?)]$/.test(w);
    const plain = k => k >= 0 && k < ws.length && !cap(ws[k]) && /^[a-z]/.test(ws[k]) && !STOP.has(norm(ws[k]));
    const adj = k => DESCRIBES.test(norm(ws[k]));
    let best = null, named = false;
    for (let i = 0; i < ws.length && !best; i++) {
      if (!hit(i)) continue;
      // a name from the text's list of structures: a capitalised word and the lower-case words after it
      let a = i; while (a > 0 && !cap(ws[a]) && !ends(ws[a - 1])) a--;
      let b = i; while (b + 1 < ws.length && !ends(ws[b]) && !cap(ws[b + 1])) b++;
      if (!cap(ws[a]) || notName(ws[a])) continue;
      // a list run together ("Hip bone urethra corpus cavernosum") gives the name up to the word: "Hip bone"
      if (b - a > 5 || /ing$/.test(norm(ws[b]))) { if (adj(i) || i - a > 4) continue; b = i; }
      if (/^the$/i.test(ws[a])) a++;   // "The internal iliac artery"
      best = [a, b]; named = true;
    }
    if (!best) {
      const i = ws.findIndex((w, k) => hit(k));
      if (i < 0) return '';
      if (adj(i)) {   // "coronary ligaments", "bicuspid aortic valve": on to the thing it describes
        let b = i; while (b < i + 1 && !ends(ws[b]) && plain(b + 1) && adj(b + 1)) b++;
        best = !ends(ws[b]) && plain(b + 1) && !adj(b + 1) ? [i, b + 1] : [i, i];
      } else if (i > 0 && !ends(ws[i - 1]) && plain(i - 1) && adj(i - 1)) best = [i - 1, i];   // "papillary muscles"
      else best = !ends(ws[i]) && plain(i + 1) && !adj(i + 1) ? [i, i + 1] : [i, i];   // "nerve supply", "heart failure"
    }
    const words = ws.slice(best[0], best[1] + 1).map(w => w.replace(/[.,;:!?()]/g, ''))
      .map(w => /^[A-Z0-9]{2,}$/.test(w) || /^[IVX]+$/.test(w) ? w : w.toLowerCase());
    const last = words[words.length - 1];
    // a case names conditions ("heart failure"), and a plural reads without the article ("papillary muscles")
    const the = e.kind !== 'clinical' && (named || !/[^su]s$/.test(last));
    return 'mentions ' + (the ? 'the ' : '') + words.join(' ');
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
    const wh = r.struct && !r.n ? whereOf(e) : null;
    const where = wh ? `<span class="wh">${esc(wh.text)}</span><span class="go">${esc(wh.go)}</span>`
      : r.struct && !r.n && V() !== '2' ? `<span class="nv">not in this view</span>` : '';
    // a row found by its text says what it mentions in place of its details, so it keeps to one line
    const w = why(e, norm(q || ''));
    const m0 = e.system === 'attachments' && r.parts && r.parts.find(p => p.e.system !== 'attachments');
    if (m0 && !r.meta) r.meta = meta(m0.e).replace(/ · \d+ parts$/, '');
    return `<li class="sx-r${r.struct ? ' st' : ''}" data-i="${i}">${n}<span class="tx"><span class="nm">${mark(shown(e.title), q)}</span>${lat}` +
           `<span class="mt">${w ? mark(w, q) : esc(r.meta || meta(e))}${where}${parts}</span></span></li>`;
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
      else if (v !== '3' && !res.list.some(e => anchorOf(e))) note = `<p class="sx-fz">None of these is on the figure as shown. Each says where it is.</p>`;
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
    if (![x0, y0, p.x, p.y].every(Number.isFinite)) return;   // a room with no figure to point at (histology catalogue, viewer)
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
    if (on && app.classList.contains('sx-moved')) {   // searching again starts from the figure the circles belong to
      app.classList.remove('sx-moved'); Object.assign(img, { src: S.home.src, alt: S.home.alt }); img.style.left = S.home.left;
      title.textContent = 'Muscles, anterior view'; titleLine.textContent = '2,231 of 3,922 shown · 26% deep'; S.view = null;
    }
    if (on) { S.chosen = false; app.classList.remove('sx-chosen'); build(); }
    else { layer.innerHTML = ''; dots.innerHTML = ''; svg.innerHTML = ''; }
    syncTitle();
  }
  function syncTitle() {
    const v = V();
    if (v === '3') {
      title.contentEditable = S.open ? 'true' : 'false';
      if (S.open) { if (title.textContent !== S.q) title.textContent = S.q; title.classList.toggle('is-empty', !S.q); }
      else if (S.chosen) { const e = S.pick || { title: 'Biceps brachii', alt: 'Musculus biceps brachii' };
        title.textContent = shown(e.title).replace(/ muscle$/, ''); titleLine.innerHTML = `${esc(/^[A-Z]/.test(e.alt || '') ? e.alt : S.view ? S.view.line : '')} · <a class="sx-back">back to Muscles, anterior view</a>`; }
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
    const w = r.struct && !r.n ? whereOf(e) : null;
    if (w && w.room) { location.search = `?scheme=${R.dataset.scheme}&screen=${w.room.screen}&variant=${V()}&q=${encodeURIComponent(S.q)}${w.room.chosen ? '&state=chosen' : ''}`; return; }
    S.chosen = true; S.pick = e; setOpen(false); app.classList.add('sx-chosen');
    const card = sectionEl.querySelector('.label-card');
    if (card && e.title !== 'Biceps brachii muscle') {   // the mockup has the biceps figure only; other choices rename the label
      card.querySelector('.t').textContent = shown(e.title).replace(/ muscle$/, '');
      card.querySelector('.lat').textContent = e.alt && /^[A-Z]/.test(e.alt) ? e.alt : '';
      // the biceps facts do not belong to it: say where it is and what it belongs to
      card.querySelector('dl').innerHTML = (w ? `<dt>Where</dt><dd>${esc(w.text)}</dd>` : '') + `<dt>System</dt><dd>${esc(r.meta || meta(e))}</dd>`;
      card.querySelector('.acc').hidden = true;
    }
    if (w && w.show) turnTo(w);
    syncTitle();
    if (V() !== '3') { S.keep = true; input.focus({ preventScroll: true }); input.setSelectionRange(99, 99); S.keep = false; }   // the query stays in hand; typing or the down arrow reopens it
  }
  // Peel or turn the body to where the structure shows, then circle it at its real place on that plate.
  function turnTo(w) {
    const s = w.show, cx = img.offsetLeft + img.offsetWidth / 2;
    app.classList.add('sx-moved');
    img.removeAttribute('data-plate');
    img.alt = s.back ? 'Muscles of the body, posterior view' : 'The body dissected to 40 percent depth';
    const place = () => {
      img.style.left = (cx - img.offsetWidth / 2) + 'px';
      const an = (window.LH_PLATES.anchors || {})[s.plate] || {};
      let pts = s.pts || ['vl', 'vr'].map(sd => an[s.key + '.' + sd]).filter(Boolean);
      // one organ (the heart) has both halves' anchors a few pixels apart: one circle, on its larger visible part
      if (!s.pts) pts = (s.one && pts.length ? [pts.reduce((m, a) => a.area > m.area ? a : m)] : pts).map(a => [a.x, a.y]);
      dots.innerHTML = '';
      pts.forEach(([x, y]) => { const p = stagePt({ x, y }), d = document.createElement('span');
        d.className = 'ndot on-body is-cur sx-found'; d.style.left = p.x + 'px'; d.style.top = p.y + 'px'; dots.appendChild(d); });
    };
    img.addEventListener('load', place, { once: true });
    img.src = `../../assets/plates/${s.plate}.webp`;
    const g = app.querySelector('.gauge');   // the gauge's own [ and ] steps, as the app's Deeper / Shallower do
    for (let n = 0; g && n < 8 && Math.abs(+g.dataset.depth - w.to) > .005; n++)
      g.querySelector('.g-knob').dispatchEvent(new KeyboardEvent('keydown', { key: +g.dataset.depth < w.to ? ']' : '[', bubbles: true }));
    S.view = { title: s.title, line: s.line || (w.to === CUT ? '2,231 of 3,922 shown · 26% deep' : `Turned round · ${Math.round(w.to * 100)}% deep`) };
    title.textContent = S.view.title; titleLine.textContent = S.view.line;
  }

  function wire() {
    const ui = () => { S.active = 0; app.classList.toggle('sx-typed', !!S.q.trim()); build(); };
    // 3: the box hands the caret to the title, once the open search has made the title editable
    input.addEventListener('focus', () => { if (S.keep) { S.keep = false; return; } if (!S.open) { if (V() === '3') S.q = ''; setOpen(true); } if (V() === '3') { title.focus(); placeCaret(); } });
    input.addEventListener('input', () => { S.q = input.value; S.expand = {}; if (!S.open) setOpen(true); ui(); });
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
      if (!S.open && e.key === 'ArrowDown' && document.activeElement === input && S.q) { e.preventDefault(); setOpen(true); return; }
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

  /* ------------------------------------------------------------------ the other rooms (option 1, search3)
     One rule: answers appear where the room shows its things. The room's own list narrows in place, circles go on the
     room's picture, and matches from the other rooms sit below as quieter lines. */
  const ROOMS = {   // list: the room's own things; slot: where the other rooms' lines go; own: the index kind the room already lists
    viewer: { list: '.parts li', slot: '.parts', own: 'part', word: 'parts' },
    'histology-library': { list: '.tissues .it', slot: '.lib-main', own: 'tissue', word: 'tissues' },
    histology: { list: '.app > div[style*="left:1320px"] ol li', slot: '.app > div[style*="left:1320px"] ol', own: 'tissue', word: 'labels', keep: true },
    models: { list: '[data-collection] .spec', slot: '[data-collection]', own: 'micro', word: 'models' },
    lessons: { slot: '.lib-main', own: 'lesson', word: 'lessons' },
    lesson: { slot: null, own: 'lesson' }, radiology: { slot: null, own: 'radiology' } };
  function matches(text, q) {
    const n = norm(text), qw = q.split(' ');
    return score(n, n.split(' '), q, qw) > 0;
  }
  function markIn(el, q) {   // mark the matching letters in an element's own text, keeping its other children
    [...el.childNodes].forEach(nd => { if (nd.nodeType === 3 && nd.textContent.trim()) {
      const s = document.createElement('span'); s.className = 'sx-t'; s.innerHTML = mark(nd.textContent, q); nd.replaceWith(s); } });
  }
  function initRoom(scr) {
    const C = ROOMS[scr], sec = document.querySelector(`[data-screen-id="${scr}"]`), rapp = sec.querySelector('.app');
    const f = rapp.querySelector('.find');
    f.innerHTML = `<svg class="i"><use href="#i-search"/></svg><input class="sx-in" type="text" placeholder="Search anatomy, lessons, radiology" ` +
      `aria-label="Search" aria-keyshortcuts="Control+K" title="Search this room and the others" autocomplete="off" spellcheck="false"><a class="sx-again" href="#" hidden></a>`;
    f.classList.add('sx-field');
    const inp = f.querySelector('input'), again = f.querySelector('.sx-again');
    const items = C.list ? [...rapp.querySelectorAll(C.list)] : [];
    const orig = new Map(items.map(el => [el, el.innerHTML]));
    const stg = rapp.querySelector('.stage'), pimg = stg && stg.querySelector('img.plate');
    const rdots = document.createElement('div'); rdots.className = 'sx-dots'; if (stg) stg.appendChild(rdots);
    const filt = rapp.querySelector('.parts .filter'), filtHTML = filt && filt.innerHTML;
    let act = 0, sel = [], q0 = '';
    const go = (screen, extra = '') => { location.search = `?scheme=${R.dataset.scheme}&screen=${screen}&variant=1&q=${encodeURIComponent(q0)}${extra}`; };
    function clear() {
      items.forEach(el => { el.innerHTML = orig.get(el); el.classList.remove('sx-hide', 'sx-anc', 'sx-m', 'is-active', 'sx-dim'); });
      rapp.querySelectorAll('.sx-else, .sx-rlist, .sx-rnone').forEach(x => x.remove());
      rapp.querySelectorAll('.tissues .grp, .labs').forEach(x => x.classList.remove('sx-hide'));
      rapp.classList.remove('sx-on', 'sx-room'); rdots.innerHTML = ''; if (filt) filt.innerHTML = filtHTML; sel = [];
    }
    function run(raw) {
      clear(); q0 = raw.trim(); f.classList.toggle('has-q', !!q0);
      if (!q0) return;
      let q = norm(q0); q = IDX.synonyms[q] || q;
      rapp.classList.add('sx-on', 'sx-room');
      const res = search(q0).list;
      // 1. the room's own list narrows in place
      let own = [];
      if (scr === 'lessons') {
        const ls = res.filter(e => e.kind === 'lesson');
        const box = document.createElement('ol'); box.className = 'sx-rlist';
        box.innerHTML = ls.slice(0, 7).map((e, i) => `<li class="sx-m" data-k="${i}"><span class="nm">${mark(e.title, q)}</span><span class="mt">${esc(e.subtitle.replace(/^Lesson · /, ''))}${why(e, q) ? ` · ${mark(why(e, q), q)}` : ''}</span></li>`).join('') +
          (ls.length > 7 ? `<li class="sx-more-l">${ls.length - 7} more lessons</li>` : '');
        rapp.querySelector('.labs').classList.add('sx-hide'); rapp.querySelector('.lib-main').prepend(box);
        own = [...box.querySelectorAll('li.sx-m')].map((el, i) => ({ el, pick: () => ls[i].title === 'The coronary circulation' ? go('lesson', '&state=chosen') : null }));
      } else {
        const lv = el => +((el.className.match(/\bl(\d)\b/) || [0, 0])[1]);
        items.forEach((el, i) => {
          const tx = el.querySelector('.ti, .specimen-cap') || el, hit = matches(tx.textContent, q);
          if (hit) { el.classList.add('sx-m'); (scr === 'models' ? [...tx.children] : [tx]).forEach(x => markIn(x, q)); own.push({ el, pick: () => pickOwn(el) });
            if (scr === 'viewer') for (let j = i - 1, l = lv(el); j >= 0 && l > 0; j--) if (lv(items[j]) < l) { items[j].classList.add('sx-anc'); l = lv(items[j]); } }
        });
        items.forEach(el => { if (!el.classList.contains('sx-m') && !el.classList.contains('sx-anc')) el.classList.add(C.keep ? 'sx-dim' : 'sx-hide'); });
        rapp.querySelectorAll('.tissues .grp').forEach(g => g.classList.toggle('sx-hide', !g.querySelector('.it.sx-m')));
        if (filt) filt.innerHTML = `<svg class="i"><use href="#i-search"/></svg><span class="fq">${esc(q0)}</span><span class="fn num">${own.length} ${own.length === 1 ? 'part' : 'parts'}</span>`;
      }
      if (C.list && !own.length && C.slot) rapp.querySelector(C.slot).insertAdjacentHTML(scr === 'histology' ? 'afterend' : 'beforeend',
        `<p class="sx-rnone">No ${C.word} here match “${esc(q0)}”.</p>`);
      // 2. circles on the room's picture: the plate's labelled points that match, numbered as in the list
      let n = 0;
      if (stg && pimg) {
        const an = (window.LH_PLATES.anchors || {})[pimg.dataset.anchors || pimg.dataset.plate] || {}, k = pimg.offsetHeight / pimg.naturalHeight;
        const rowOf = l => { const t = norm(l.textContent); return own.find(o => { const r = norm(o.el.textContent); return r === t || r === t + 's'; }); };
        const at = o => o ? own.indexOf(o) : 1e9;   // numbered in the list's order, then the points with no row
        [...stg.querySelectorAll('.lbl')].filter(l => an[l.dataset.anchor] && matches(l.textContent, q)).sort((x, y) => at(rowOf(x)) - at(rowOf(y))).forEach(l => {
          const a = an[l.dataset.anchor];
          const num = ++n, d = document.createElement('span');
          d.className = 'ndot' + (l.classList.contains('is-selected') ? ' is-cur' : ''); d.textContent = num;
          d.style.left = (pimg.offsetLeft + a.x * k) + 'px'; d.style.top = (pimg.offsetTop + a.y * k) + 'px'; rdots.appendChild(d);
          const row = rowOf(l);
          if (row) { row.el.insertAdjacentHTML('afterbegin', `<span class="ndot${d.classList.contains('is-cur') ? ' is-cur' : ''}">${num}</span>`); row.dot = d; d._row = row; }
        });
      }
      if (scr === 'histology') rapp.querySelectorAll('.pinned .pin').forEach((p, i) => p.classList.toggle('sx-ring', !!(items[i] && items[i].classList.contains('sx-m'))));
      // 3. the other rooms, below, as quieter lines
      const ROOMW = [['Atlas', ['structure', 'group', 'landmark']], ['Lessons', ['lesson']], ['Radiology', ['radiology']], ['Histology', ['tissue']], ['Models', ['micro']], ['Clinical', ['clinical']]];
      const lines = ROOMW.map(([w, ks]) => [w, res.filter(e => ks.includes(e.kind) && !(scr !== 'lesson' && e.kind === C.own && C.list !== undefined) && !(scr === 'lessons' && e.kind === 'lesson'))]).filter(x => x[1].length);
      let els = [];
      if (lines.length && C.slot) {
        const el = document.createElement('div'); el.className = 'sx-else';
        el.innerHTML = lines.map(([w, es]) => `<div class="sx-l"><span class="k">${w}</span><span class="v">` +
          es.slice(0, 2).map(e => `<a class="sx-o">${mark(shown(e.title), q)}</a>`).join(', ') + (es.length > 2 ? ` <span class="n num">and ${es.length - 2} more</span>` : '') + `</span></div>`).join('');
        const slot = rapp.querySelector(C.slot);
        if (scr === 'histology') slot.after(el); else slot.appendChild(el);
        const flat = lines.flatMap(([w, es]) => es.slice(0, 2).map(e => [w, e]));
        els = [...el.querySelectorAll('.sx-o')].map((a, i) => ({ el: a, pick: () => {
          const [w, e] = flat[i]; go({ Atlas: 'atlas', Lessons: 'lessons', Radiology: 'radiology', Histology: 'histology-library', Models: 'models', Clinical: 'atlas' }[w]); } }));
      }
      sel = [...own, ...els];
      act = Math.min(act, sel.length - 1);
      if (P.get('hover') === 'auto' && !initRoom.done) { initRoom.done = 1; act = Math.max(0, sel.findIndex(s => s.dot)); }
      paint();
    }
    function paint() {
      sel.forEach((s, i) => { s.el.classList.toggle('is-active', i === act); if (s.dot) s.dot.classList.toggle('is-active', i === act); });
    }
    function pickOwn(el) {   // choosing one of the room's own things selects it there; the query stays one click away
      const t = (el.querySelector('.ti, b') || el).textContent.trim();   // a model: its name, not its caption
      const q = q0; inp.value = ''; run(''); q0 = q;
      if (scr === 'viewer') { items.forEach(x => x.classList.toggle('is-sel', x === el)); rapp.querySelector('[data-v-card] .t').textContent = t; }
      if (scr === 'histology-library') { items.forEach(x => { x.classList.toggle('is-sel', x === el); const s = x.querySelector('.ti > .is-cur'); if (s) s.replaceWith(...s.childNodes); });
        const d = rapp.querySelector('.lib-detail'), im = el.querySelector('img'); d.querySelector('.t').textContent = t; if (im) d.querySelector('.dfig img').src = im.src; }
      if (scr === 'models') { const a = el.getAttribute('href'); if (a) { location.search = a; return; } rapp.querySelectorAll('[data-collection] .is-cur-pic').forEach(x => x.classList.remove('is-cur-pic'));
        el.firstElementChild.classList.add('is-cur-pic'); }
      again.hidden = false; again.textContent = `Back to “${q}”`; inp.focus({ preventScroll: true });
    }
    inp.addEventListener('input', () => { act = 0; again.hidden = true; run(inp.value); });
    again.addEventListener('click', e => { e.preventDefault(); inp.value = q0; again.hidden = true; run(q0); inp.focus(); });
    rapp.addEventListener('mousemove', e => { const i = sel.findIndex(s => s.el.contains(e.target) || (s.dot && s.dot === e.target)); if (i >= 0 && i !== act) { act = i; paint(); } });
    rapp.addEventListener('click', e => { const s = sel.find(s => s.el.contains(e.target) || (s.dot && s.dot === e.target)); if (s && rapp.classList.contains('sx-on')) { const r = s.pick(); return r; } });
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); inp.focus(); return; }
      if (document.activeElement !== inp || !q0 || !sel.length) { if (e.key === 'Escape' && document.activeElement === inp) inp.blur(); return; }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); act = (act + (e.key === 'ArrowDown' ? 1 : -1) + sel.length) % sel.length; paint(); sel[act].el.scrollIntoView({ block: 'nearest' }); }
      else if (e.key === 'Enter') { e.preventDefault(); sel[act].pick(); }
      else if (e.key === 'Escape') { e.preventDefault(); inp.value = ''; run(''); inp.blur(); }
    });
    if (P.get('state') === 'chosen' && P.get('q')) { q0 = P.get('q'); again.hidden = false; again.textContent = `Back to “${q0}”`;
      again.onclick = ev => { ev.preventDefault(); location.search = `?scheme=${R.dataset.scheme}&screen=atlas&variant=1&q=${encodeURIComponent(q0)}`; }; }
    else if (P.get('q')) { inp.value = P.get('q'); run(inp.value); if (P.get('caret') !== '0') { inp.focus({ preventScroll: true }); inp.setSelectionRange(99, 99); } }
  }

  function init() {
    const scr = R.dataset.screen || 'atlas';
    if (scr !== 'atlas') {   // the other rooms: option 1 only (see PORT.md)
      if (V() === '1' && ROOMS[scr]) initRoom(scr);
      document.fonts.ready.then(() => { R.dataset.searchReady = '1'; });
      return;
    }
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
    S.home = { src: img.src, alt: img.alt, left: img.style.left };
    wire();
    if (S.open) setOpen(true);
    else if (S.chosen && P.has('pick') && S.q) { setOpen(true); choose(+P.get('pick')); }   // a chosen row by its place in the list
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
