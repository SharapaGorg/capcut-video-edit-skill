/* <i data-icon="name"></i> -> inline SVG (24x24 viewBox, stroke, цвет задаёт .tile). */
(function () {
  const I = {
    lock: '<rect x="4" y="11" width="16" height="10"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    profile: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>',
    text: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.5 1.5"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.5-1.5"/>',
    tag: '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.3"/>',
    clip: '<rect x="5" y="3" width="14" height="18"/><path d="M10 9l5 3-5 3z"/>',
    eye: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    heart: '<path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10z"/>',
    comment: '<path d="M4 5h16v11H9l-5 4z"/>',
    save: '<path d="M6 3h12v18l-6-4-6 4z"/>',
    share: '<path d="M4 12v8h16v-8"/><path d="M12 15V3M7 8l5-5 5 5"/>',
    calendar: '<rect x="3" y="5" width="18" height="16"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    ratio: '<path d="M5 19L19 5"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/>',
    table: '<rect x="3" y="4" width="18" height="16"/><path d="M3 10h18M3 15h18M9 4v16"/>',
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    cursor: '<path d="M5 3l14 8-6 2-3 6z"/>',
    folder: '<path d="M3 6h7l2 2h9v11H3z"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    tg: '<path d="M21 4L3 11l6 2 2 6 3-4 5 3z"/><path d="M9 13l9-7"/>',
    mail: '<rect x="3" y="5" width="18" height="14"/><path d="M3 6l9 7 9-7"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
    screen: '<rect x="3" y="4" width="18" height="12"/><path d="M8 20h8M12 16v4"/>',
    header: '<rect x="3" y="4" width="18" height="16"/><path d="M3 10h18"/><circle cx="7" cy="7" r="1.3"/>',
    trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    pin: '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/><path d="M12 14v7"/>',
    story: '<circle cx="12" cy="12" r="9" stroke-dasharray="4 3"/><circle cx="12" cy="12" r="5"/>',
    play: '<path d="M6 4l14 8-14 8z"/>',
    coin: '<circle cx="12" cy="12" r="8"/><path d="M12 7v10M9.5 9.5h4a1.5 1.5 0 0 1 0 3h-3a1.5 1.5 0 0 0 0 3h4"/>',
    api: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/>',
    ig: '<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1"/>',
    shop: '<path d="M4 9h16l-1 11H5z"/><path d="M3 9l2-5h14l2 5"/><path d="M9 13v3M15 13v3"/>',
    cloud: '<path d="M7 18a4 4 0 0 1-.5-8 6 6 0 0 1 11.3 1.5A3.5 3.5 0 0 1 17.5 18z"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
    nochart: '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/><path d="M3 3l18 18"/>',
    tiktok: '<path d="M14 3v11a3.5 3.5 0 1 1-3.5-3.5"/><path d="M14 3c0 3 2.5 5 5 5"/>',
    yt: '<rect x="3" y="6" width="18" height="12" rx="3"/><path d="M10 9l5 3-5 3z"/>',
    reels: '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M3 9h18M8 3l3 6M14 3l3 6M10.5 12.5l4 2.5-4 2.5z"/>',
    browser: '<rect x="3" y="4" width="18" height="16"/><path d="M3 9h18M6 6.5h.01M9 6.5h.01"/>',
    check: '<path d="M4 12l5 5L20 7"/>',
    arrow: '<path d="M4 12h15M13 6l6 6-6 6"/>',
  };
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('i[data-icon]').forEach(el => {
      el.outerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${I[el.dataset.icon] || ''}</svg>`;
    });
  });
})();
