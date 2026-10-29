"""Full-screen motion-graphic «footage» for a reel section without a camera (build_reel: section "footage").
Same look as the scheme panel (shorts/scheme.py): dark radial background, drifting grid, slow breathing push-in;
every element pops on its word (anim.js data-in) + continuous motion in seekExtra (idle bob, clock sweep, feed scroll,
punch on the last accent).

kind "survey" — «Я опросил N человек, K из них тратят от часа до двух в день, скролля ленту»:
  {"kind": "survey", "total": 10, "part": 8, "label": "SMM-ЩИКОВ",
   "at_total": "10", "at_part": "8", "at_clock": "часа", "at_clock2": "двух", "at_day": "день", "at_feed": "скролля",
   "at_punch": "работе", "clock_text": "1–2 Ч", "day_text": "В ДЕНЬ"}
All at_* are words of the section script (default = the keys above); a missing word -> that beat is skipped.
"""
from __future__ import annotations

import html as _html
import json

W, H = 1080, 1920
BG = dict(bottom='#60260A', mid='#371606', bg='#000000', grid=108, grid_color='rgba(255,255,255,.22)')


def _person(c, uid, i):
    return (f'<svg viewBox="0 0 120 150" class="p" id="{uid}_p{i}"><circle cx="60" cy="38" r="30" fill="{c}"/>'
            f'<path d="M6 150 q0 -76 54 -76 q54 0 54 76 z" fill="{c}"/></svg>')


def css(uid, acc, txt):
    s = f'.f{uid}'
    return f'''
{s}.ftg {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; overflow:hidden; z-index:5; font-family:'Unbounded', sans-serif; color:{txt};
  background: radial-gradient(120% 60% at 50% 100%, {BG["bottom"]} 0%, {BG["mid"]} 45%, {BG["bg"]} 100%); }}
{s} .grid {{ position:absolute; left:-{W * 2}px; top:-{H * 2}px; width:{W * 5}px; height:{H * 5}px;
  background-image: linear-gradient({BG["grid_color"]} 3px, transparent 3px), linear-gradient(90deg, {BG["grid_color"]} 3px, transparent 3px);
  background-size: {BG["grid"]}px {BG["grid"]}px; background-position: 34px 80px; }}
{s} .world {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; transform-origin:50% 55%; }}
{s} .num {{ position:absolute; left:0; top:470px; width:{W}px; display:flex; align-items:baseline; justify-content:center; gap:14px; }}
{s} .num .big {{ font-weight:900; font-size:210px; line-height:1; letter-spacing:-.05em; color:{acc}; text-shadow:0 0 40px {acc}AA, 0 0 100px {acc}44, 0 8px 20px rgba(0,0,0,.6); }}
{s} .num .of {{ font-weight:800; font-size:70px; line-height:1; color:{txt}; opacity:.55; letter-spacing:-.02em; }}
{s} .lbl {{ position:absolute; left:0; top:690px; width:{W}px; text-align:center; font-weight:700; font-size:40px; letter-spacing:.18em; color:{txt}; opacity:.85; }}
{s} .ppl {{ position:absolute; left:0; top:0; width:0; height:0; }}
{s} .fig {{ position:absolute; width:120px; height:150px; transform-origin:50% 100%; }}
{s} .fig svg {{ width:100%; height:100%; display:block; filter:drop-shadow(0 8px 16px rgba(0,0,0,.5)); }}
{s} .fig .on {{ position:absolute; left:0; top:0; width:100%; height:100%; }}
{s} .fig .on svg {{ filter:drop-shadow(0 0 22px {acc}BB) drop-shadow(0 8px 16px rgba(0,0,0,.5)); }}
{s} .fig .ring {{ position:absolute; left:-30px; top:-20px; width:180px; height:190px; border-radius:50%; border:6px solid {acc}; opacity:0; transform-origin:center; }}
{s} .fig .off {{ position:absolute; left:0; top:0; width:100%; height:100%; }}
{s} .clk {{ position:absolute; left:70px; top:1170px; width:280px; height:280px; }}
{s} .clk svg {{ width:100%; height:100%; display:block; filter:drop-shadow(0 8px 20px rgba(0,0,0,.5)); }}
{s} .ctxt {{ position:absolute; left:380px; top:1215px; display:flex; flex-direction:column; gap:6px; }}
{s} .ctxt .h {{ font-weight:900; font-size:118px; line-height:1; letter-spacing:-.04em; color:{acc}; text-shadow:0 0 30px {acc}99, 0 6px 16px rgba(0,0,0,.6); white-space:nowrap; }}
{s} .ctxt .d {{ font-weight:700; font-size:44px; letter-spacing:.14em; color:{txt}; opacity:.9; white-space:nowrap; }}
{s} .ph {{ position:absolute; left:800px; top:1140px; width:220px; height:330px; }}
{s} .ph .body {{ position:absolute; left:0; top:0; width:220px; height:330px; border-radius:34px; border:10px solid {txt}; box-sizing:border-box; overflow:hidden; background:#0C0C0C;
  box-shadow:0 12px 30px rgba(0,0,0,.6); }}
{s} .ph .feed {{ position:absolute; left:16px; top:0; width:168px; display:flex; flex-direction:column; gap:14px; }}
{s} .ph .fc {{ width:168px; height:96px; border-radius:16px; background:{txt}; opacity:.32; }}
{s} .ph .fc.hi {{ background:{acc}; opacity:1; box-shadow:0 0 18px {acc}88; }}
{s} .ph .thumb {{ position:absolute; left:60px; top:210px; width:110px; height:110px; filter:drop-shadow(0 8px 16px rgba(0,0,0,.6)); }}
'''


def survey_html(fg, sec, sp, pl, wt, acc, txt):
    """(html, events) for kind "survey". wt(word) -> output seconds of that word in the section (None if missing)."""
    uid = ''.join(ch if ch.isalnum() else '_' for ch in sec['id'])
    s_in, s_out = sp['out_in'], sp['out_out']
    total, part = int(fg.get('total', 10)), int(fg.get('part', 8))
    r = lambda t: f'{t:.3f}'
    T = dict(total=wt(fg.get('at_total', str(total))), part=wt(fg.get('at_part', str(part))), clock=wt(fg.get('at_clock', 'часа')),
             clock2=wt(fg.get('at_clock2', 'двух')), day=wt(fg.get('at_day', 'день')), feed=wt(fg.get('at_feed', 'скролля')),
             punch=wt(fg.get('at_punch', 'работе')))
    ev = []
    o = [f'<style>{css(uid, acc, txt)}</style>',
         f'<div class="ftg f{uid}" data-in="{r(s_in)}" data-out="{r(s_out)}" data-fx="cut" data-ofx="cut" data-dur="0.01" data-odur="0.01">',
         '<div class="grid"></div><div class="world">']
    # 1. big number + people grid on the total word
    t_tot = T['total'] if T['total'] is not None else s_in
    cols = 5; rows = (total + cols - 1) // cols
    gx0 = W / 2 - (cols - 1) * 175 / 2 - 60; gy0 = 790
    t_part = T['part']
    out1 = f' data-out="{r(t_part)}" data-ofx="cut" data-odur="0.01"' if t_part is not None else ''
    o.append(f'<div class="num" data-in="{r(t_tot)}"{out1} data-fx="pop" data-dur="0.3"><div class="big" data-count-from="0" data-count-to="{total}" data-cin="{r(t_tot)}" data-cdur="0.5">0</div></div>')
    o.append(f'<div class="lbl" data-in="{r(t_tot + 0.12)}" data-fx="slide-up" data-dist="30" data-dur="0.25">{_html.escape(fg.get("label", ""))}</div>')
    ev.append(('tick', t_tot))
    o.append('<div class="ppl">')
    for i in range(total):
        cx, cy = gx0 + (i % cols) * 175, gy0 + (i // cols) * 180
        ti = t_tot + 0.05 + i * 0.045
        o.append(f'<div class="fig" data-in="{r(ti)}" data-fx="pop" data-dur="0.22" style="left:{cx:.0f}px;top:{cy:.0f}px" data-i="{i}">')
        o.append(f'<div class="off">{_person(txt, uid, i)}</div>')
        if t_part is not None:
            tp = t_part + i * 0.04
            if i < part:
                o.append(f'<div class="on" data-in="{r(tp)}" data-fx="pop" data-dur="0.18">{_person(acc, uid + "a", i)}</div>'
                         f'<div class="ring" data-ring="{r(tp)}"></div>')
                ev.append(('tick', tp))
            else:
                o.append(f'<div class="off dim" data-in="{r(tp)}" data-fx="fade" data-dur="0.3" style="background:transparent">'
                         f'<div style="width:100%;height:100%;background:rgba(0,0,0,.62)"></div></div>')
        o.append('</div>')
        ev.append(('tick', ti))
    o.append('</div>')
    # 2. the number switches to part / total
    if t_part is not None:
        o.append(f'<div class="num" data-in="{r(t_part)}" data-fx="pop" data-dur="0.25"><div class="big">{part}</div><div class="of">/ {total}</div></div>')
    # 3. clock + «1–2 Ч» / «В ДЕНЬ»
    if T['clock'] is not None:
        tc, tc2 = T['clock'], T['clock2'] if T['clock2'] is not None else T['clock'] + 0.4
        o.append(f'<div class="clk" data-in="{r(tc)}" data-fx="pop" data-dur="0.3" data-t1="{r(tc)}" data-t2="{r(tc2)}">'
                 '<svg viewBox="0 0 300 300">'
                 f'<circle cx="150" cy="150" r="118" fill="rgba(0,0,0,.35)" stroke="{txt}" stroke-width="14"/>'
                 + ''.join(f'<line x1="150" y1="44" x2="150" y2="62" stroke="{txt}" stroke-width="9" stroke-linecap="round" transform="rotate({a} 150 150)"/>' for a in range(0, 360, 30))
                 + f'<path class="sweep" d="" fill="{acc}" opacity=".85"/>'
                 f'<line class="hand" x1="150" y1="150" x2="150" y2="66" stroke="{txt}" stroke-width="14" stroke-linecap="round"/>'
                 f'<line class="minute" x1="150" y1="150" x2="150" y2="52" stroke="{acc}" stroke-width="8" stroke-linecap="round"/>'
                 f'<circle cx="150" cy="150" r="12" fill="{acc}"/></svg></div>')
        o.append(f'<div class="ctxt"><div class="h" data-in="{r(tc)}" data-fx="pop" data-dur="0.25">{_html.escape(fg.get("clock_text", "1–2 Ч"))}</div>')
        td = T['day'] if T['day'] is not None else tc2 + 0.3
        o.append(f'<div class="d" data-in="{r(td)}" data-fx="slide-up" data-dist="30" data-dur="0.2">{_html.escape(fg.get("day_text", "В ДЕНЬ"))}</div></div>')
        ev += [('tick', tc), ('tick', tc2), ('tick', td)]
    # 4. phone with an endless feed
    if T['feed'] is not None:
        tf = T['feed']
        cards = ''.join(f'<div class="fc{" hi" if i % 3 == 1 else ""}"></div>' for i in range(12))
        o.append(f'<div class="ph" data-in="{r(tf)}" data-fx="slide-up" data-dist="60" data-dur="0.3" data-t0="{r(tf)}">'
                 f'<div class="body"><div class="feed">{cards}</div></div>'
                 f'<svg class="thumb" viewBox="0 0 100 100"><circle cx="50" cy="50" r="26" fill="{txt}" opacity=".95"/><circle cx="50" cy="50" r="40" fill="none" stroke="{txt}" stroke-width="6" opacity=".55"/></svg></div>')
        ev.append(('whoosh', tf))
    o.append('</div></div>')   # world, ftg
    punch = T['punch']
    o.append('<script>(function(){' + f'''
  const S = document.querySelector('.ftg.f{uid}'); if (!S) return;
  const Wd = S.querySelector('.world'), G = {BG["grid"]}, T0 = {s_in:.3f}, TP = {('null' if punch is None else f'{punch:.3f}')};
  const easeOut = p => 1 - Math.pow(1 - Math.max(0, Math.min(1, p)), 3);
  const prev = window.seekExtra;
  window.seekExtra = function (t) {{
    if (prev) prev(t);
    if (t < T0 - 0.5) return;
    const u = t - T0;
    let sc = 1 + 0.04 * (0.5 - 0.5 * Math.cos(2 * Math.PI * u / 7));
    if (TP !== null && t >= TP) {{ const p = Math.min(1, (t - TP) / 0.14); sc *= 1 + 0.07 * easeOut(p); }}
    Wd.style.transform = `scale(${{sc}})`;
    S.querySelector('.grid').style.transform = `translate(${{(16 * u) % G}}px, ${{(9 * u) % G}}px) scale(${{1 + (sc - 1) * .5}})`;
    S.querySelectorAll('.fig').forEach(f => {{
      const i = parseInt(f.dataset.i); const by = 5 * Math.sin(2 * Math.PI * u / 1.7 + i * 0.7);
      const svgs = f.querySelectorAll('.off, .on'); svgs.forEach(s => s.style.marginTop = by + 'px');
      const rg = f.querySelector('.ring');
      if (rg) {{ const t0 = parseFloat(rg.dataset.ring); const p = (t - t0) / 0.45;
        if (p < 0 || p > 1) rg.style.opacity = 0; else {{ rg.style.opacity = 0.9 * (1 - p); rg.style.transform = `scale(${{0.6 + 0.7 * easeOut(p)}})`; }} }}
    }});
    const C = S.querySelector('.clk');
    if (C) {{ const t1 = parseFloat(C.dataset.t1), t2 = parseFloat(C.dataset.t2);
      let h = 0; if (t >= t1) h = 30 * easeOut((t - t1) / 0.35); if (t >= t2) h = 30 + 30 * easeOut((t - t2) / 0.35);
      C.querySelector('.hand').setAttribute('transform', `rotate(${{h}} 150 150)`);
      const m = (t - t1) * 540; C.querySelector('.minute').setAttribute('transform', `rotate(${{m}} 150 150)`);
      const a = h * Math.PI / 180, R = 84; const big = h > 180 ? 1 : 0;
      C.querySelector('.sweep').setAttribute('d', `M150 150 L150 ${{150 - R}} A${{R}} ${{R}} 0 ${{big}} 1 ${{150 + R * Math.sin(a)}} ${{150 - R * Math.cos(a)}} Z`); }}
    const P = S.querySelector('.ph');
    if (P) {{ const t0 = parseFloat(P.dataset.t0); const y = -((Math.max(0, t - t0) * 240) % (110 * 6));
      P.querySelector('.feed').style.transform = `translateY(${{y}}px)`;
      const th = P.querySelector('.thumb'); const k = (Math.max(0, t - t0) * 240 / 110) % 1; th.style.transform = `translateY(${{-60 * k}}px) scale(${{1 - 0.25 * Math.sin(k * Math.PI)}})`; }}
  }};
''' + '})();</script>')
    return '\n'.join(o), ev
