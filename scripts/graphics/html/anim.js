/* Deterministic time-based animation: window.seek(t) sets the styles of every element with data-in
   (t = seconds from the start of the composition; render.py calls seek(frame / fps) for every frame).
     data-in="1.25"   moment the element appears, s
     data-out="5.0"   moment its exit starts (optional; without it the element stays)
     data-fx="slide-left|slide-right|slide-up|slide-down|fade|pop|cut|wipe-left|wipe-right|wipe-up|wipe-down|grow-x"
                      entry (default slide-up)
     data-ofx="..."   exit (default = the entry reversed)
     data-dur="0.25"  entry duration, s (default 0.25: «появление 250 мс»)
     data-odur="0.2"  exit duration, s (default 0.2: «исчезновение 200 мс»)
     data-dist="20"   slide distance, px (default 20)
   Split / chapter panels: data-dur="0.4" data-odur="0.4" (slide 400 ms).
   Counters: data-count-from / data-count-to / data-cin / data-cdur.
   Style «Монолит»: hard entry, ease-out cubic. */
(function () {
  const easeOut = t => 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);
  const easeIn = t => Math.pow(Math.max(0, Math.min(1, t)), 3);
  function fx(el, name, p, dist) {
    // p: 0 = hidden, 1 = fully shown
    const d = (1 - p) * dist;
    let tr = '', op = 1, clip = '';
    switch (name) {
      case 'slide-left': tr = `translateX(${-d}px)`; op = p; break;
      case 'slide-right': tr = `translateX(${d}px)`; op = p; break;
      case 'slide-up': tr = `translateY(${d}px)`; op = p; break;
      case 'slide-down': tr = `translateY(${-d}px)`; op = p; break;
      case 'fade': op = p; break;
      case 'pop': tr = `scale(${1.18 - 0.18 * p})`; op = p < 0.5 ? p * 2 : 1; break;
      case 'cut': op = p > 0 ? 1 : 0; break;
      case 'wipe-left': clip = `inset(0 ${(1 - p) * 100}% 0 0)`; break;
      case 'wipe-right': clip = `inset(0 0 0 ${(1 - p) * 100}%)`; break;
      case 'wipe-up': clip = `inset(${(1 - p) * 100}% 0 0 0)`; break;
      case 'wipe-down': clip = `inset(0 0 ${(1 - p) * 100}% 0)`; break;
      case 'grow-x': tr = `scaleX(${p})`; break;
      default: tr = `translateY(${d}px)`; op = p;
    }
    el.style.transform = tr;
    el.style.opacity = op;
    el.style.clipPath = clip;
    el.style.visibility = p <= 0 ? 'hidden' : 'visible';
  }
  window.seek = function (t) {
    document.querySelectorAll('[data-in]').forEach(el => {
      const tin = parseFloat(el.dataset.in);
      const tout = el.dataset.out !== undefined ? parseFloat(el.dataset.out) : Infinity;
      const din = parseFloat(el.dataset.dur || '0.25');
      const dout = parseFloat(el.dataset.odur || '0.2');
      const dist = parseFloat(el.dataset.dist || '20');
      const fin = el.dataset.fx || 'slide-up';
      const fout = el.dataset.ofx || fin;
      let p;
      if (t < tin) p = 0;
      else if (t < tin + din) p = easeOut((t - tin) / din);
      else if (t < tout) p = 1;
      else if (t < tout + dout) p = 1 - easeIn((t - tout) / dout);
      else p = 0;
      fx(el, t >= tout ? fout : fin, p, dist);
    });
    document.querySelectorAll('[data-count-to]').forEach(el => {
      const a = parseFloat(el.dataset.countFrom || '0'), b = parseFloat(el.dataset.countTo);
      const t0 = parseFloat(el.dataset.cin), du = parseFloat(el.dataset.cdur || '0.6');
      const p = easeOut((t - t0) / du);
      const v = t < t0 ? a : Math.round(a + (b - a) * p);
      el.textContent = v.toLocaleString('ru-RU').replace(/\s/g, ' ');
    });
    if (window.seekExtra) window.seekExtra(t);
  };
  /* Union of the resting boxes (entry/exit transforms and clips removed) of the visible animated elements:
     render.py checks the placement rules on it. */
  window.visibleBox = function () {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const els = Array.from(document.querySelectorAll('[data-in]'));
    const vis = els.filter(el => el.style.visibility !== 'hidden' && parseFloat(el.style.opacity || '1') >= 0.01);
    const saved = els.map(el => [el.style.transform, el.style.clipPath]);
    els.forEach(el => { el.style.transform = 'none'; el.style.clipPath = ''; });
    vis.forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return;
      x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top); x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom);
    });
    els.forEach((el, i) => { el.style.transform = saved[i][0]; el.style.clipPath = saved[i][1]; });
    return x1 < x0 ? null : [x0, y0, x1, y1].map(Math.round);
  };
})();
