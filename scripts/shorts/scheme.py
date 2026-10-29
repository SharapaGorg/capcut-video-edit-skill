"""Full-screen «scheme» card of the shorts pipeline (references/shorts.md «Схема (type: scheme)»): nodes with an icon,
captions appearing word by word, numbers in the accent colour, dashed arcs and a camera pan from node to node over an
endless grid. The panel is opaque: it hides the camera / screencast for its whole interval (no captions, no hook).

Library (build.py): normalize(card) -> validate(card, kept) -> html_fragment(card, tmap, icon_base) — the fragment
(style + panel + seekExtra script) is dropped into the shorts gfx.html next to the hook / captions; events(card) gives
the SFX moments (node pop -> tick, pan -> whoosh).
Standalone check:
    python -X utf8 scripts/shorts/scheme.py --spec spec.json --out DIR --t 7.0 8.3 [--t-offset 300] [--html out.html]
                                            [--config config.json]
  spec = a shorts spec (first card with "type": "scheme", or --id) or a single card; --t are timeline seconds
  (+ --t-offset) -> DIR/B_<t>.png via Playwright (the composition starts at the card's start). Icon paths resolve
  from the config's work_dir when the config exists (as in the build), else from the spec's folder.
"""
from __future__ import annotations

import argparse
import html as _html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 1080, 1920
STYLE = dict(accent='#F8DE03', bg='#000000', bottom='#60260A', mid='#371606', grid=108, grid_color='rgba(255,255,255,.22)',
             center_y=870, pan=0.45, arc_delay=0.1, arc_dur=0.35, node_dur=0.35, word_dur=0.12)
SHAPES = ('circle', 'plate')
# Built-in icons. «avatar» is the generic person; «ayugram» / «funpay» are PLACEHOLDER silhouettes of the prototype —
# a real logo goes in as a png/svg path (card nodes[].icon), see references/shorts.md.
ICONS = {
    'avatar': ('circle', '<svg viewBox="0 0 404 404"><circle cx="202" cy="202" r="202" fill="#49504F"/>'
               '<clipPath id="cav{u}"><circle cx="202" cy="202" r="202"/></clipPath><g clip-path="url(#cav{u})">'
               '<circle cx="202" cy="166" r="72" fill="#F3F3F3"/>'
               '<path d="M80 420 C80 318 130 290 202 290 C274 290 324 318 324 420Z" fill="#F3F3F3"/>'
               '<path d="M118 150h168v14h-14v22h-62v-22h-16v22h-62v-22h-14z" fill="#111"/></g></svg>'),
    'ayugram': ('circle', '<svg viewBox="0 0 404 404"><circle cx="202" cy="202" r="202" fill="#2D234A"/>'
                '<path d="M202 10 L300 404 L104 404Z" fill="#3A2F5C" opacity=".6"/>'
                '<path d="M60 280 L190 78 L170 300Z" fill="#F5F2FF"/><path d="M212 78 L344 280 L228 300Z" fill="#C9B6F2"/>'
                '<path d="M196 92 L198 320 L186 300Z M208 92 L206 320 L218 300Z" fill="#F5F2FF"/></svg>'),
    'funpay': ('plate', '<span class="fpt">FU</span><svg viewBox="0 0 60 120" class="n">'
               '<path d="M30 2 L52 34 H38 V86 H52 L30 118 L8 86 H22 V34 H8Z" fill="#52A0E6"/>'
               '<path d="M12 30 L48 90" stroke="#111" stroke-width="12"/></svg><span class="fpt">PAY</span>'),
}


# ---------------- spec ----------------
def normalize(card: dict) -> dict:
    """A copy with defaults: start/end (tl_in/tl_out accepted), style, node offsets/shape/at/pan_at, phrase outs."""
    c = dict(card)
    c['id'] = c.get('id') or 'scheme'
    c['start'] = float(c['start'] if 'start' in c else c['tl_in'])
    c['end'] = float(c['end'] if 'end' in c else c['tl_out'])
    if c['end'] <= c['start']:
        raise ValueError(f"scheme {c['id']}: end <= start")
    st = dict(STYLE); st.update(c.get('style') or {}); c['style'] = st
    nodes = []
    for i, n in enumerate(c.get('nodes') or []):
        n = dict(n)
        n['id'] = n.get('id') or f'n{i}'
        n['icon'] = n.get('icon') or 'avatar'
        n['offset'] = list(n.get('offset') or ([0, 0] if i == 0 else [830, 900]))
        n['shape'] = n.get('shape') or (ICONS[n['icon']][0] if n['icon'] in ICONS else 'circle')
        if n['shape'] not in SHAPES:
            raise ValueError(f"scheme {c['id']}: node {n['id']}: shape {n['shape']!r} (circle | plate)")
        if 'at' not in n:
            n['at'] = c['start'] if i == 0 else float(n.get('pan_at', c['start'])) + st['pan']
        n['at'] = float(n['at'])
        if i and 'pan_at' not in n:
            n['pan_at'] = n['at'] - st['pan']
        if i: n['pan_at'] = float(n['pan_at'])
        phrases = []
        for ph in n.get('phrases') or []:
            ph = dict(ph)
            ph['words'] = [[str(w), float(t)] for w, t in ph.get('words') or []]
            ph['line3'] = [[str(w), float(t)] for w, t in ph.get('line3') or []]
            if ph.get('number'): ph['number'] = [str(ph['number'][0]), float(ph['number'][1])]
            times = [t for _, t in ph['words'] + ph['line3']] + ([ph['number'][1]] if ph.get('number') else [])
            if not times:
                raise ValueError(f"scheme {c['id']}: node {n['id']}: a phrase without words")
            ph['in'] = min(times)
            phrases.append(ph)
        for a, b in zip(phrases, phrases[1:]):          # cut: the next phrase replaces this one
            if 'out' not in a: a['out'] = b['in']
        n['phrases'] = phrases
        nodes.append(n)
    if not nodes:
        raise ValueError(f"scheme {c['id']}: no nodes")
    c['nodes'] = nodes
    return c


def words(card: dict):
    """Every timed text of the card: (text, timeline s, node id)."""
    for n in card['nodes']:
        for ph in n['phrases']:
            for w, t in ph['words']: yield w, t, n['id']
            if ph.get('number'): yield ph['number'][0], ph['number'][1], n['id']
            for w, t in ph['line3']: yield w, t, n['id']


def events(card: dict):
    """SFX moments: ('node', t) for every node pop, ('pan', t) for every camera pan (timeline s)."""
    for i, n in enumerate(card['nodes']):
        yield 'node', n['at']
        if i: yield 'pan', n['pan_at']


def validate(card: dict, kept=None) -> list[str]:
    """Problems: a word / node / pan outside [start, end], a word outside a kept piece (kept(t) -> bool), a bad icon."""
    a, b = card['start'], card['end']
    bad = []
    for w, t, nid in words(card):
        if not a <= t <= b: bad.append(f'слово «{w}» ({nid}) {t} вне схемы {a}–{b}')
        elif kept and not kept(t): bad.append(f'слово «{w}» ({nid}) {t} попадает в вырезанную паузу')
    for n in card['nodes']:
        if not a <= n['at'] <= b: bad.append(f'узел {n["id"]} at {n["at"]} вне схемы {a}–{b}')
        if 'pan_at' in n and not a <= n['pan_at'] <= b: bad.append(f'узел {n["id"]} pan_at {n["pan_at"]} вне схемы {a}–{b}')
    return bad


def icon_html(icon: str, shape: str, base: Path | None, uid: str) -> str:
    if icon in ICONS:
        return ICONS[icon][1].replace('{u}', uid)
    p = Path(icon)
    if not p.is_absolute() and base: p = Path(base) / p
    if not p.is_file():
        raise ValueError(f'иконка схемы не найдена: {icon} (встроенные: {", ".join(ICONS)}; иначе png/svg в папке ролика)')
    return f'<img src="{p.resolve().as_uri()}" alt="">'


# ---------------- html ----------------
def layout(card: dict):
    """World positions of the nodes, camera keys [(tl, x, y)], arcs [(d, tl, dur)]."""
    st = card['style']; pos = {}; x = y = 0
    for n in card['nodes']:
        x += n['offset'][0]; y += n['offset'][1]; pos[n['id']] = (x, y)
    cam = [(card['start'], 0, 0)] + [(n['pan_at'], *pos[n['id']]) for n in card['nodes'][1:]]
    arcs = []
    for a, b in zip(card['nodes'], card['nodes'][1:]):
        (x0, y0), (x1, y1) = pos[a['id']], pos[b['id']]
        arcs.append((f'M{x0} {y0} Q{x1} {y0} {x1} {y1}', b['pan_at'] + st['arc_delay'], st['arc_dur']))
    return pos, cam, arcs


def css(uid: str, st: dict) -> str:
    s = f'.s{uid}'
    return f'''
{s}.scheme {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; overflow:hidden; z-index:5;
  background: radial-gradient(120% 60% at 50% 100%, {st["bottom"]} 0%, {st["mid"]} 45%, {st["bg"]} 100%); }}
{s} .grid {{ position:absolute; left:-{W * 2}px; top:-{H * 2}px; width:{W * 5}px; height:{H * 5}px;
  background-image: linear-gradient({st["grid_color"]} 3px, transparent 3px), linear-gradient(90deg, {st["grid_color"]} 3px, transparent 3px);
  background-size: {st["grid"]}px {st["grid"]}px; background-position: 34px 80px; }}
{s} .world {{ position:absolute; left:0; top:0; }}
{s} svg.arcs {{ position:absolute; left:-3000px; top:-3000px; width:6000px; height:6000px; overflow:visible; }}
{s} svg.arcs path.dash {{ fill:none; stroke:#E1E1E1; stroke-width:5; stroke-dasharray:14 17; stroke-linecap:round; }}
{s} svg.arcs mask path {{ fill:none; stroke:#fff; stroke-width:12; }}
{s} .node {{ position:absolute; width:0; height:0; }}
{s} .ic {{ position:absolute; left:-202px; top:-202px; width:404px; height:404px; border-radius:50%; overflow:hidden;
  filter: drop-shadow(0 0 30px rgba(255,255,255,.8)); }}
{s} .ic svg, {s} .ic img {{ width:100%; height:100%; display:block; object-fit:cover; }}
{s} .idle {{ position:absolute; left:0; top:0; width:0; height:0; }}
{s} .idle .ic {{ transform-origin:center; }}
{s} .ring {{ position:absolute; left:-250px; top:-250px; width:500px; height:500px; transform-origin:center; opacity:.9; }}
{s} .ring.pl {{ left:-330px; top:-165px; width:660px; height:330px; }}
{s} .badge {{ position:absolute; left:110px; top:110px; width:150px; height:150px; border-radius:50%; background:#fff; display:flex; align-items:center;
  justify-content:center; font-size:88px; font-family:'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif; box-shadow:0 6px 18px rgba(0,0,0,.4);
  transform-origin:center; opacity:0; }}
{s} .ic.pl {{ left:-286px; top:-122px; width:572px; height:244px; border-radius:36px; background:#fff; color:#111; display:flex; align-items:center;
  justify-content:center; font-family: Arial, Helvetica, sans-serif; font-weight:900; font-size:150px; letter-spacing:-.02em;
  box-shadow:0 0 26px rgba(255,255,255,.75); filter:none; }}
{s} .ic.pl img {{ width:auto; height:auto; max-width:520px; max-height:196px; object-fit:contain; }}
{s} .ic.pl svg.n {{ width:70px; height:140px; margin:0 -6px; }}
{s} .cap {{ position:absolute; left:-540px; top:282px; width:{W}px; display:flex; flex-direction:column; align-items:center; gap:0; }}
{s} .cap .line {{ display:flex; justify-content:center; gap:14px; }}
{s} .cap .w {{ font-family:'{st.get("font", "Unbounded")}', sans-serif; font-weight:700; font-size:50px; line-height:1.3; color:#FBFBFB;
  text-shadow:0 2px 6px rgba(0,0,0,.6); white-space:nowrap; text-transform:none; }}
{s} .cap .num {{ font-weight:800; font-size:84px; line-height:1.2; color:{st["accent"]}; letter-spacing:-.03em; text-shadow:0 0 18px {st["accent"]}8C; }}
{s} .node.pl .cap {{ top:202px; }}
'''


def html_fragment(card: dict, tmap=None, icon_base: Path | None = None) -> str:
    """<style> + the opaque panel + <script> (seekExtra: camera, arcs, node pops) in composition seconds.
    tmap: timeline s -> composition s (default: t - start). Word / phrase appearances use anim.js data-in."""
    tmap = tmap or (lambda t: t - card['start'])
    r = lambda t: f'{tmap(t):.3f}'
    uid = ''.join(ch if ch.isalnum() else '_' for ch in str(card['id']))
    st = card['style']; pos, cam, arcs = layout(card)
    cx, cy = W / 2, st['center_y']
    esc = _html.escape
    o = [f'<style>{css(uid, st)}</style>',
         f'<div class="scheme s{uid}" data-in="{r(card["start"])}" data-out="{r(card["end"])}" data-fx="cut" data-ofx="cut" data-dur="0.01" data-odur="0.01">',
         '<div class="grid"></div>',
         f'<div class="world" data-cam=\'{json.dumps([[r(t), x, y] for t, x, y in cam])}\' data-pan="{st["pan"]}">',
         '<svg class="arcs" viewBox="-3000 -3000 6000 6000"><defs>']
    for i, (d, t, dur) in enumerate(arcs):
        o.append(f'<mask id="m{uid}_{i}"><path d="{d}" pathLength="1" stroke-dasharray="1" class="draw" data-t="{r(t)}" data-dur="{dur}"/></mask>')
    o.append('</defs>')
    for i, (d, t, dur) in enumerate(arcs):
        o.append(f'<path class="dash" d="{d}" mask="url(#m{uid}_{i})"/>')
    o.append('</svg>')

    def line(ws, kind='w'):
        return '<div class="line">' + ''.join(
            f'<span class="{kind} word" data-in="{r(t)}" data-fx="slide-up" data-dist="28" data-dur="{st["word_dur"]}">{esc(w)}</span>'
            for w, t in ws) + '</div>'
    for n in card['nodes']:
        px, py = pos[n['id']]
        o.append(f'<div class="node{" pl" if n["shape"] == "plate" else ""}" style="left:{px}px;top:{py}px">')
        ic = f'<div class="ic{" pl" if n["shape"] == "plate" else ""}">{icon_html(n["icon"], n["shape"], icon_base, uid)}</div>'
        if n.get('anim'):                      # a live node: bob, rotating dashed ring, pulsing glow, a popping badge
            badge = _html.escape(n.get('badge') or '')
            if n['shape'] == 'plate':
                ring = (f'<svg class="ring pl" viewBox="0 0 660 330"><rect x="8" y="8" width="644" height="314" rx="52" fill="none" stroke="{st["accent"]}" '
                        f'stroke-width="6" stroke-dasharray="26 22" stroke-linecap="round"/></svg>')
            else:
                ring = (f'<svg class="ring" viewBox="0 0 500 500"><circle cx="250" cy="250" r="236" fill="none" stroke="{st["accent"]}" '
                        f'stroke-width="6" stroke-dasharray="26 22" stroke-linecap="round"/></svg>')
            ic = (f'<div class="idle">{ic}{ring}' +
                  (f'<div class="badge" data-t="{r(n["at"] + 0.45)}" data-dur="{st["node_dur"]}">{badge}</div>' if badge else '') + '</div>')
        o.append(f'<div class="pop" data-t="{r(n["at"])}" data-dur="{st["node_dur"]}">{ic}</div>')
        for ph in n['phrases']:
            out = f' data-out="{r(ph["out"])}"' if 'out' in ph else ''
            o.append(f'<div class="cap" data-in="{r(ph["in"])}"{out} data-fx="cut" data-ofx="cut" data-dur="0.01" data-odur="0.01">')
            num = ph.get('number')
            if num and ph['words'] and ph['words'][0][1] < num[1]:     # «более чем на» / 50 000
                o.append(line(ph['words'])); o.append(line([num], 'num'))
            else:                                                     # 1 000 000 / активных пользователей
                if num: o.append(line([num], 'num'))
                if ph['words']: o.append(line(ph['words']))
            if ph['line3']: o.append(line(ph['line3']))
            o.append('</div>')
        o.append('</div>')
    o.append('</div></div>')
    o.append('''<script>
(function () {
  const easeIO = p => p < .5 ? 4*p*p*p : 1 - Math.pow(-2*p + 2, 3) / 2;
  const easeOut = p => 1 - Math.pow(1 - p, 3);
  const back = p => { const c = 1.4; return 1 + c * Math.pow(p - 1, 3) + (c - 1) * Math.pow(p - 1, 2); };  // overshoot ~8 %
  const S = document.querySelector('.scheme.s''' + uid + '''');
  const Wd = S.querySelector('.world'), CAM = JSON.parse(Wd.dataset.cam), PAN = parseFloat(Wd.dataset.pan);
  const CX = ''' + str(cx) + ', CY = ' + str(cy) + ', G = ' + str(st['grid']) + ''';
  const prev = window.seekExtra;
  window.seekExtra = function (t) {
    if (prev) prev(t);
    let x = CAM[0][1], y = CAM[0][2];
    for (let i = 1; i < CAM.length; i++) {
      const t0 = parseFloat(CAM[i][0]); if (t < t0) break;
      const p = easeIO(Math.min(1, (t - t0) / PAN));
      x = CAM[i-1][1] + (CAM[i][1] - CAM[i-1][1]) * p; y = CAM[i-1][2] + (CAM[i][2] - CAM[i-1][2]) * p;
    }
    const sc = 1 + 0.04 * (0.5 - 0.5 * Math.cos(2 * Math.PI * t / 7));          // slow breathing push-in, 7 s period
    Wd.style.transform = `translate(${CX}px, ${CY}px) scale(${sc}) translate(${-x}px, ${-y}px)`;
    const gx = CX - x + 16 * t, gy = CY - y + 9 * t;                                 // the grid drifts, never static
    S.querySelector('.grid').style.transform = `translate(${gx % G}px, ${gy % G}px) scale(${1 + (sc - 1) * .5})`;
    S.querySelectorAll('mask path.draw').forEach(p => {
      const t0 = parseFloat(p.dataset.t), d = parseFloat(p.dataset.dur);
      const q = t < t0 ? 0 : easeOut(Math.min(1, (t - t0) / d));
      p.style.strokeDashoffset = 1 - q;
    });
    S.querySelectorAll('.idle').forEach(el => {
      const ic = el.querySelector('.ic'), rg = el.querySelector('.ring'), bd = el.querySelector('.badge');
      const by = 10 * Math.sin(2 * Math.PI * t / 1.7), rz = 3 * Math.sin(2 * Math.PI * t / 2.3);
      ic.style.transform = `translateY(${by}px) rotate(${rz}deg)`;
      const gl = .55 + .45 * (.5 + .5 * Math.sin(2 * Math.PI * t / 1.1));
      ic.style.filter = `drop-shadow(0 0 ${18 + 26 * gl}px rgba(255,255,255,${(.35 + .55 * gl).toFixed(2)}))`;
      rg.style.transform = (rg.classList.contains('pl') ? '' : `rotate(${(t * 40) % 360}deg) `) + `scale(${1 + .03 * Math.sin(2 * Math.PI * t / 1.7)})`;
      if (rg.classList.contains('pl')) rg.style.strokeDashoffset = `${-(t * 30) % 48}px`;
      if (bd) { const t0 = parseFloat(bd.dataset.t), d = parseFloat(bd.dataset.dur), p = t < t0 ? 0 : Math.min(1, (t - t0) / d);
        bd.style.transform = `translateY(${-by * .6}px) rotate(${-rz * 2}deg) scale(${p <= 0 ? 0 : back(p)})`; bd.style.opacity = p > 0 ? 1 : 0; }
    });
    S.querySelectorAll('.pop').forEach(el => {
      const t0 = parseFloat(el.dataset.t), d = parseFloat(el.dataset.dur);
      const p = t < t0 ? 0 : Math.min(1, (t - t0) / d);
      el.style.transform = `scale(${p <= 0 ? 0 : back(p)})`; el.style.opacity = p > 0 ? 1 : 0;
    });
  };
})();
</script>''')
    return '\n'.join(o)


def standalone_html(card: dict, tmap=None, icon_base: Path | None = None, css_href: str | None = None, anim_href: str | None = None) -> str:
    """A whole page (shorts.css + anim.js of the skill): the panel alone, composition starts at the card's start."""
    css_href = css_href or (HERE / 'shorts.css').as_uri()
    anim_href = anim_href or (HERE.parent / 'graphics' / 'html' / 'anim.js').as_uri()
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8">\n'
            f'<!-- Схема «кто есть кто» (type: scheme, references/shorts.md): полноэкранная вставка, узлы по словам речи. '
            f'Пример-заглушка: иконки — встроенные силуэты. seek(t) в консоли, t от начала схемы. -->\n'
            f'<link rel="stylesheet" href="{css_href}"><script src="{anim_href}"></script></head><body>\n'
            + html_fragment(card, tmap, icon_base) + '\n</body></html>')


# ---------------- CLI ----------------
def pick_card(spec: dict, cid: str | None = None) -> dict:
    cards = [spec] if spec.get('type') == 'scheme' or 'nodes' in spec else [c for c in spec.get('cards', []) if c.get('type') == 'scheme']
    if cid: cards = [c for c in cards if c.get('id') == cid]
    if not cards: raise SystemExit('в спеке нет карточки type: scheme' + (f' с id {cid}' if cid else ''))
    return cards[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description='standalone render of a scheme card')
    ap.add_argument('--spec', required=True); ap.add_argument('--id')
    ap.add_argument('--config', default='config.json', help='config.json of the video (icon paths from its work_dir)')
    ap.add_argument('--out', required=True, help='folder for B_<t>.png and scheme.html')
    ap.add_argument('--t', nargs='*', type=float, default=[], help='timeline seconds (+ --t-offset) to screenshot')
    ap.add_argument('--t-offset', type=float, default=0.0)
    ap.add_argument('--html', help='also write the page here (relative css/anim links for assets/examples)')
    a = ap.parse_args(argv)
    sp = Path(a.spec)
    base = sp.parent
    if Path(a.config).is_file():
        base = Path(json.loads(Path(a.config).read_text(encoding='utf-8')).get('work_dir') or Path(a.config).resolve().parent)
    card = normalize(pick_card(json.loads(sp.read_text(encoding='utf-8')), a.id))
    bad = validate(card)
    if bad: raise SystemExit('схема: ' + '; '.join(bad))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    page = out / 'scheme.html'
    page.write_text(standalone_html(card, icon_base=base), encoding='utf-8')
    if a.html:
        hp = Path(a.html); rel = Path(*(['..'] * (len(hp.resolve().relative_to(HERE.parent.parent).parts) - 1)))
        hp.write_text(standalone_html(card, icon_base=base, css_href=(rel / 'scripts/shorts/shorts.css').as_posix(),
                                      anim_href=(rel / 'scripts/graphics/html/anim.js').as_posix()), encoding='utf-8')
        print('html:', hp)
    if not a.t: print('html:', page); return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(viewport={'width': W, 'height': H}, device_scale_factor=1)
        pg.goto(page.as_uri()); pg.evaluate('document.fonts.ready')
        for t in a.t:
            pg.evaluate(f'seek({t + a.t_offset - card["start"]:.4f})')
            pg.screenshot(path=str(out / f'B_{t}.png'), omit_background=True)
            print('frame', t)
        b.close()


if __name__ == '__main__':
    main()
