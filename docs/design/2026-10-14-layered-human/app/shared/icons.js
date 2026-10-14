/* One authored icon set for all three directions: 24px grid, 1.6px round stroke, no fills except dots.
 * Each design sets stroke width and colour through CSS (.i { stroke: currentColor }). */
(function () {
  const P = {
    search: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5 5"/>',
    layers: '<path d="M12 4l8 4.2-8 4.2-8-4.2z"/><path d="M4 12.2l8 4.2 8-4.2"/><path d="M4 16l8 4.2 8-4.2"/>',
    section: '<path d="M4 15.5l8-4.5 8 4.5-8 4.5z"/><path d="M12 3v8"/><path d="M8.5 6.5L12 3l3.5 3.5"/>',
    xray: '<circle cx="12" cy="12" r="7.5" stroke-dasharray="2.2 2.4"/><circle cx="12" cy="12" r="3.2"/>',
    isolate: '<rect x="4" y="4" width="16" height="16" rx="2.5" stroke-dasharray="2.4 2.6"/><circle cx="12" cy="12" r="3.6"/>',
    hide: '<path d="M3.5 12s3.2-6 8.5-6 8.5 6 8.5 6-3.2 6-8.5 6-8.5-6-8.5-6z"/><path d="M5 19L19 5"/>',
    show: '<path d="M3.5 12s3.2-6 8.5-6 8.5 6 8.5 6-3.2 6-8.5 6-8.5-6-8.5-6z"/><circle cx="12" cy="12" r="2.6"/>',
    measure: '<path d="M4.5 16.5l12-12 3 3-12 12z"/><path d="M8 13l1.6 1.6M10.6 10.4l1.6 1.6M13.2 7.8l1.6 1.6"/>',
    labels: '<path d="M4 7.5h9.5l4 4.5-4 4.5H4z"/><circle cx="8" cy="12" r="1.2"/>',
    reset: '<path d="M5 12a7 7 0 1 0 2.1-5"/><path d="M5 4.5V9h4.5"/>',
    menu: '<path d="M5 7h14M5 12h14M5 17h14"/>',
    bookmark: '<path d="M7 4h10v16l-5-3.6L7 20z"/>',
    review: '<path d="M12 7v5l3.2 2"/><circle cx="12" cy="12" r="8"/>',
    chevron: '<path d="M9 6l6 6-6 6"/>',
    chevdown: '<path d="M6 9l6 6 6-6"/>',
    back: '<path d="M15 6l-6 6 6 6"/>',
    check: '<path d="M5 12.5l4.2 4.2L19 7"/>',
    close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    note: '<path d="M6 4h9l3 3v13H6z"/><path d="M9 10h6M9 13.5h6M9 17h3.5"/>',
    play: '<path d="M8 5.5v13l10.5-6.5z"/>',
    grid: '<rect x="4" y="4" width="6.5" height="6.5" rx="1"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1"/>',
    book: '<path d="M4 5.5c3-1.2 5.6-1 8 .8 2.4-1.8 5-2 8-.8v13c-3-1.2-5.6-1-8 .8-2.4-1.8-5-2-8-.8z"/><path d="M12 6.3v13"/>',
    film: '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 3.5v17M16 3.5v17M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4"/>',
    micro: '<circle cx="12" cy="12" r="8"/><circle cx="9.5" cy="10" r="1.6"/><circle cx="14.5" cy="9" r="1.2"/><circle cx="13.5" cy="14.5" r="1.8"/>',
    cube: '<path d="M12 3.5l7.5 4.2v8.6L12 20.5l-7.5-4.2V7.7z"/><path d="M4.5 7.7L12 12l7.5-4.3M12 12v8.5"/>',
    person: '<circle cx="12" cy="5.5" r="2.2"/><path d="M8 21l1.2-8.5H7.5L9 8.5h6l1.5 4H14.8L16 21"/>',
    settings: '<circle cx="12" cy="12" r="2.8"/><path d="M12 3.5v2.6M12 17.9v2.6M3.5 12h2.6M17.9 12h2.6M6 6l1.8 1.8M16.2 16.2L18 18M6 18l1.8-1.8M16.2 7.8L18 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    minus: '<path d="M5 12h14"/>',
    fit: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    flip: '<path d="M12 3v18" stroke-dasharray="2 2.4"/><path d="M9 7l-5 5 5 5zM15 7l5 5-5 5z"/>',
    pin: '<path d="M12 21s-6-5.6-6-10.5a6 6 0 1 1 12 0C18 15.4 12 21 12 21z"/><circle cx="12" cy="10.5" r="2.2"/>',
    download: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5"/><path d="M5 19.5h14"/>',
    windows: '<path d="M4 5.6l7-1v6.9H4zM13 4.3l7-1V11.5h-7zM4 12.5h7v6.9l-7-1zM13 12.5h7v8.2l-7-1z"/>',
    apple: '<path d="M15.8 12.6c0-2.3 1.9-3.4 2-3.5-1.1-1.6-2.8-1.8-3.4-1.8-1.4-.1-2.8.9-3.5.9s-1.8-.9-3-.8C6.4 7.4 5 8.3 4.3 9.7c-1.6 2.7-.4 6.8 1.1 9 .8 1.1 1.6 2.3 2.8 2.3 1.1 0 1.6-.7 2.9-.7s1.8.7 3 .7 2-1.1 2.7-2.2c.8-1.2 1.2-2.4 1.2-2.5-.1 0-2.2-.8-2.2-3.7zM13.6 5.8c.6-.8 1-1.8.9-2.8-.9 0-2 .6-2.6 1.4-.6.7-1.1 1.7-1 2.7 1 .1 2-.5 2.7-1.3z"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v6H4V6h6"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
    keyboard: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h.01M10 10h.01M13 10h.01M16 10h.01M7 14h10"/>',
    mouse: '<rect x="7" y="3.5" width="10" height="17" rx="5"/><path d="M12 3.5v6"/>',
    target: '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3"/>',
  };
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', 0); svg.setAttribute('height', 0);
  svg.style.position = 'absolute';
  svg.innerHTML = Object.entries(P).map(([k, v]) =>
    `<symbol id="i-${k}" viewBox="0 0 24 24" fill="none" stroke-linecap="round" stroke-linejoin="round">${v}</symbol>`).join('');
  const put = () => document.body.prepend(svg);
  if (document.body) put(); else document.addEventListener('DOMContentLoaded', put);
})();
