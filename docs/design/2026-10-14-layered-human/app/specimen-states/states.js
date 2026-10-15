/* Layered Human, Specimen: three states the mockup did not show (checkpoint 2).
 *   ?state=search_open | search_empty                         the catalogue drawer on the atlas (Ctrl K or a click opens it)
 *   ?state=lesson_hover_term | lesson_hover_label | lesson_hover_dot   lesson text that points at the model
 *   ?state=practice_wrong | practice_right                    practice feedback in the model
 * Hover works live as well; ?state= only forces the same classes so the moment can be rendered.
 * Runs before mock.js (it sets the screen and removes labels the moment does not show), then finishes once mock.js has
 * drawn the leaders (data-ready), and sets <html data-states="1">. */
(function () {
  const R = document.documentElement;
  const q = new URLSearchParams(location.search);
  const SCREEN = { search_open: 'atlas', search_empty: 'atlas', lesson_hover_term: 'lesson', lesson_hover_label: 'lesson',
    lesson_hover_dot: 'lesson', practice_wrong: 'practice', practice_right: 'practice' };
  let state = SCREEN[q.get('state')] ? q.get('state') : '';
  if (state) R.dataset.screen = SCREEN[state];
  R.dataset.state = state || 'base';
  R.dataset.states = '0';

  // Labels that belong to another moment never reach the layout; everything else with data-show is shown or hidden.
  const shows = el => el.dataset.show.split(' ').includes(state || 'base');
  document.querySelectorAll('.lbl[data-show]').forEach(el => { if (!shows(el)) el.remove(); });
  function applyShow() { document.querySelectorAll('[data-show]').forEach(el => { el.hidden = !shows(el); }); }
  applyShow();

  /* ------------------------------------------------------------------------------------------- search drawer */
  const atlas = document.querySelector('[data-screen-id="atlas"]');
  const QUERY = { search_open: 'biceps', search_empty: 'bycep' };
  function setFind(open) {
    const find = atlas.querySelector('.find');
    if (!find) return;
    find.classList.toggle('is-open', !!open);
    find.innerHTML = open
      ? `<svg class="i"><use href="#i-search"/></svg><span class="qt">${QUERY[open]}</span><span class="caret"></span><kbd>Esc</kbd>`
      : `<svg class="i"><use href="#i-search"/></svg>Search the atlas, lessons, cases<kbd>Ctrl K</kbd>`;
    const dr = atlas.querySelectorAll('[data-drawer]');
    dr.forEach(d => { d.style.left = (find.getBoundingClientRect().left - atlas.querySelector('.app').getBoundingClientRect().left) + 'px'; });
  }
  function openSearch(which) {
    state = which; R.dataset.state = which || 'base'; applyShow(); setFind(which);
  }
  function moveFocus(step) {
    const rows = [...atlas.querySelectorAll('[data-show="search_open"] .dr-row')];
    let i = rows.findIndex(r => r.classList.contains('is-focus'));
    i = Math.max(0, Math.min(rows.length - 1, i + step));
    rows.forEach((r, k) => r.classList.toggle('is-focus', k === i));
  }

  /* ------------------------------------------------------------------------------------------- lesson */
  const lesson = document.querySelector('[data-screen-id="lesson"]');
  const STEPS = ['Where they start', 'The left coronary artery', 'The right coronary artery', 'Dominance', 'Veins',
    'Reading the infarct off the ECG', 'An infarct can upset a valve without injuring its leaflets'];   // data/content/lessons_cardio_heart.json
  const pairs = {};      // anchor key -> { lbl, leader, anchor, halo, terms }
  function light(key, on) {
    const p = pairs[key]; if (!p) return;
    const stage = lesson.querySelector('.stage');
    stage.classList.toggle('is-pointing', on);
    [p.lbl, p.leader, p.anchor, p.halo, ...p.terms].forEach(el => el && el.classList.toggle('is-lit', on));
  }
  function stepLine(i) {
    const line = lesson.querySelector('[data-step-line]');
    const dots = [...lesson.querySelectorAll('.dots.steps i')];
    dots.forEach((d, k) => d.classList.toggle('is-hover', k === i));
    line.innerHTML = i == null ? 'Step 2 of 7 · The coronary circulation · Advanced'
      : `Step ${i + 1} of 7 · <span class="step-t">${STEPS[i]}</span>`;
  }
  function wireLesson() {
    const stage = lesson.querySelector('.stage');
    const svg = stage.querySelector('svg.leaders');
    const lbls = [...stage.querySelectorAll('.lbl[data-anchor]')].filter(l => l.style.display !== 'none');
    const leaders = svg ? [...svg.querySelectorAll('path.leader')] : [];
    const anchors = svg ? [...svg.querySelectorAll('circle.anchor')] : [];
    lbls.forEach((lbl, i) => {
      const key = lbl.dataset.anchor, a = anchors[i];
      let halo = null;
      if (a) {
        halo = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        halo.setAttribute('cx', a.getAttribute('cx')); halo.setAttribute('cy', a.getAttribute('cy')); halo.setAttribute('r', 9);
        halo.setAttribute('class', 'halo'); svg.appendChild(halo);
      }
      pairs[key] = { lbl, leader: leaders[i], anchor: a, halo, terms: [...lesson.querySelectorAll(`.term[data-for="${key}"]`)] };
      lbl.addEventListener('mouseenter', () => light(key, true));
      lbl.addEventListener('mouseleave', () => light(key, false));
    });
    lesson.querySelectorAll('.term[data-for]').forEach(t => {
      t.addEventListener('mouseenter', () => { if (lesson.querySelector('.app').dataset.labels === 'on') light(t.dataset.for, true); });
      t.addEventListener('mouseleave', () => light(t.dataset.for, false));
    });
    lesson.querySelectorAll('.dots.steps i').forEach((d, i) => {
      d.title = STEPS[i];
      d.addEventListener('mouseenter', () => stepLine(i));
      d.addEventListener('mouseleave', () => stepLine(null));
    });
    // the dock's Labels button turns the labels, and with them the terms' hairlines, on and off
    const btn = [...lesson.querySelectorAll('.dock button')].find(b => b.textContent.trim() === 'Labels');
    if (btn) btn.addEventListener('click', () => {
      const app = lesson.querySelector('.app'), on = app.dataset.labels !== 'on';
      app.dataset.labels = on ? 'on' : 'off'; btn.classList.toggle('on', on);
    });
  }

  /* ------------------------------------------------------------------------------------------- practice */
  function wirePractice() {
    const stage = document.querySelector('[data-screen-id="practice"] .stage');
    const svg = stage.querySelector('svg.leaders');
    const lbls = [...stage.querySelectorAll('.lbl[data-anchor]')].filter(l => l.style.display !== 'none');
    const leaders = svg ? [...svg.querySelectorAll('path.leader')] : [];
    const anchors = svg ? [...svg.querySelectorAll('circle.anchor')] : [];
    lbls.forEach((lbl, i) => {
      const miss = lbl.classList.contains('miss'), hit = lbl.classList.contains('is-selected');
      if (!(miss || hit) || !anchors[i]) return;
      // one ring at the structure's anchor (a point read from the renderer's picking buffer), in two colours:
      // neutral for the structure clicked by mistake, brass for the right answer
      if (miss) leaders[i].classList.add('is-miss');
      const ring = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      ring.setAttribute('cx', anchors[i].getAttribute('cx')); ring.setAttribute('cy', anchors[i].getAttribute('cy'));
      ring.setAttribute('r', 11); ring.setAttribute('class', miss ? 'miss-ring' : 'hit-ring'); svg.appendChild(ring);
    });
  }

  /* ------------------------------------------------------------------------------------------- after mock.js */
  function finish() {
    if (atlas) {
      setFind(QUERY[state] ? state : '');
      atlas.querySelector('.find').addEventListener('click', () => openSearch('search_open'));
      atlas.querySelectorAll('.dr-row').forEach(r => r.addEventListener('click', () => {
        atlas.querySelectorAll('.dr-row').forEach(x => x.classList.toggle('is-focus', x === r));
      }));
      document.addEventListener('keydown', e => {
        if (R.dataset.screen !== 'atlas') return;
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openSearch('search_open'); }
        else if (e.key === 'Escape') openSearch('');
        else if (state === 'search_open' && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { e.preventDefault(); moveFocus(e.key === 'ArrowDown' ? 1 : -1); }
      });
    }
    if (lesson) wireLesson();
    if (document.querySelector('[data-screen-id="practice"]')) wirePractice();
    if (state === 'lesson_hover_term') light('lad', true);
    if (state === 'lesson_hover_label') light('lcx', true);
    if (state === 'lesson_hover_dot') stepLine(2);
    R.dataset.states = '1';
  }
  // mock.js lays out only the current screen; wire the others' hover too, but only the visible one matters.
  const wait = () => (R.dataset.ready === '1' ? finish() : setTimeout(wait, 30));
  wait();
})();
