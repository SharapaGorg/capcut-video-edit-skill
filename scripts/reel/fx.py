"""Motion-graphic effects for camera-less reel sections (spec key "fx": [{kind, ...}]), 2026-11-03, reel «новая функция ChatGPT».

kind "grid_bg"  — the scheme's backdrop (radial dark-orange gradient + a slowly drifting grid) from `at_word` (or the
                  section start) to `out_word` (or the section end). Replaces the flat black frame of a camera-less section.
kind "connect"  — two white glyph icons (`left`, `right` — svg paths from the spec folder) fly in from the sides with an
                  overshoot at `at_word` / `at_word2`; at `link_word` a dashed arc draws between them, at `done_word`
                  an accent pulse runs along it, both icons flash and a ring expands. Out at `out_word` (fade).
kind "limits"   — four accent corner brackets clamp around the caption box at `at_word` (the "limit"), pulse at
                  `pulse_word`, and at `burst_word` fly apart to the frame corners with a spark burst from the centre.

Every function returns (html, events) with events = [(kind, t)] for the SFX (tick / whoosh) in output seconds.
Motion beyond anim.js data-in/out runs in window.seekExtra (deterministic in t)."""
from __future__ import annotations

import html as _html
import json
import math
from pathlib import Path

W, H = 1080, 1920


def _icon(src: str, base: Path) -> str:
    p = Path(src) if Path(src).is_absolute() else base / src
    if not p.is_file(): raise SystemExit(f'иконка не найдена: {p}')
    return f'<img src="{p.resolve().as_uri()}" alt="">'


def css(acc: str, txt: str) -> str:
    return f'''
.fxbg {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; overflow:hidden; z-index:1;
  background: radial-gradient(120% 60% at 50% 100%, #60260A 0%, #371606 45%, #000000 100%); }}
.fxbg .grid {{ position:absolute; left:-216px; top:-216px; width:{W + 432}px; height:{H + 432}px;
  background-image: linear-gradient(rgba(255,255,255,.22) 3px, transparent 3px), linear-gradient(90deg, rgba(255,255,255,.22) 3px, transparent 3px);
  background-size: 108px 108px; }}
.fxbg .flash {{ position:absolute; inset:0; background:{acc}; opacity:0; }}
.fxc {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; z-index:4; pointer-events:none; }}
.fxc .ic {{ position:absolute; width:300px; height:300px; transform-origin:center; filter:drop-shadow(0 0 30px rgba(255,255,255,.8)); }}
.fxc .ic img {{ width:100%; height:100%; display:block; object-fit:contain; }}
.fxc .ic.wh img {{ filter: brightness(0) invert(1); }}
.fxc svg.arc {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; overflow:visible; }}
.fxc svg.arc path.dash {{ fill:none; stroke:#E1E1E1; stroke-width:6; stroke-dasharray:16 18; stroke-linecap:round; }}
.fxc svg.arc mask path {{ fill:none; stroke:#fff; stroke-width:14; }}
.fxc .pulse {{ position:absolute; width:46px; height:46px; margin:-23px 0 0 -23px; border-radius:50%; background:{acc};
  box-shadow:0 0 30px {acc}, 0 0 70px {acc}99; opacity:0; }}
.fxc .ring {{ position:absolute; width:300px; height:300px; margin:-150px 0 0 -150px; border-radius:50%; border:6px solid {acc};
  box-shadow:0 0 30px {acc}88; opacity:0; transform-origin:center; }}
.fxc .ok {{ position:absolute; left:0; width:{W}px; text-align:center; font-family:'Unbounded',sans-serif; font-weight:800; font-size:40px;
  letter-spacing:.12em; color:{acc}; text-shadow:0 0 18px {acc}99; }}
.fxl {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; z-index:5; pointer-events:none; }}
.fxl .br {{ position:absolute; width:90px; height:90px; border:10px solid {acc}; box-shadow:0 0 22px {acc}88; opacity:0; }}
.fxl .br.tl {{ border-right:none; border-bottom:none; border-radius:18px 0 0 0; }}
.fxl .br.tr {{ border-left:none; border-bottom:none; border-radius:0 18px 0 0; }}
.fxl .br.bl {{ border-right:none; border-top:none; border-radius:0 0 0 18px; }}
.fxl .br.br2 {{ border-left:none; border-top:none; border-radius:0 0 18px 0; }}
.fxl .sp {{ position:absolute; width:18px; height:18px; margin:-9px 0 0 -9px; border-radius:50%; background:{acc}; box-shadow:0 0 16px {acc}; opacity:0; }}
.fxl .sp.w {{ background:{txt}; box-shadow:0 0 16px {txt}; }}
.fxl .lbl {{ position:absolute; left:0; width:{W}px; text-align:center; font-family:'Unbounded',sans-serif; font-weight:700; font-size:34px;
  letter-spacing:.2em; color:{acc}; text-shadow:0 0 16px {acc}99; }}
'''


# ---------------- helpers for the js ----------------
_EASE = """const eo=p=>1-Math.pow(1-Math.max(0,Math.min(1,p)),3), ei=p=>Math.pow(Math.max(0,Math.min(1,p)),3),
bk=p=>{const c=1.7;p=Math.max(0,Math.min(1,p));return 1+c*Math.pow(p-1,3)+(c-1)*Math.pow(p-1,2);};"""


def grid_bg(t0: float, t1: float, uid: str) -> tuple[str, list]:
    h = (f'<div class="fxbg fxbg_{uid}" data-in="{t0:.3f}" data-out="{t1:.3f}" data-fx="fade" data-dur="0.3" data-ofx="fade" data-odur="0.25">'
         f'<div class="grid"></div><div class="flash"></div></div>'
         f'<script>(function(){{const prev=window.seekExtra;const S=document.querySelector(".fxbg_{uid}");const g=S.querySelector(".grid");'
         f'window.seekExtra=function(t){{if(prev)prev(t);const sc=1+0.03*(0.5-0.5*Math.cos(2*Math.PI*t/7));'
         f'g.style.transform=`translate(${{(16*t)%108}}px, ${{(9*t)%108}}px) scale(${{sc}})`;}};}})();</script>')
    return h, []


def connect(f: dict, wt, s_in: float, s_out: float, base: Path, uid: str) -> tuple[str, list]:
    t_a = wt(f['at_word']) if f.get('at_word') else s_in
    t_b = wt(f['at_word2']) if f.get('at_word2') else t_a + 0.3
    t_link = wt(f['link_word']); t_done = wt(f['done_word'])
    t_out = wt(f['out_word']) if f.get('out_word') else s_out
    y = int(f.get('y', 800)); xl, xr = int(f.get('xl', 250)), int(f.get('xr', 830)); r = 150
    # arc: a quadratic curve bowing down between the icon centres, masked by discs at both ends (the dash stops at the glow)
    d = f'M{xl} {y} Q{(xl + xr) // 2} {y + 260} {xr} {y}'
    gap = r + 30
    h = [f'<div class="fxc fxc_{uid}" data-in="{t_a:.3f}" data-out="{t_out:.3f}" data-fx="cut" data-dur="0.01" data-ofx="fade" data-odur="0.3">',
         f'<svg class="arc" viewBox="0 0 {W} {H}"><defs><mask id="mfx_{uid}"><path id="pfx_{uid}" d="{d}" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/>'
         f'<circle cx="{xl}" cy="{y}" r="{gap}" fill="#000"/><circle cx="{xr}" cy="{y}" r="{gap}" fill="#000"/></mask></defs>'
         f'<path class="dash" d="{d}" mask="url(#mfx_{uid})"/><path id="gfx_{uid}" d="{d}" fill="none" stroke="none"/></svg>',
         f'<div class="ic wh l" style="left:{xl - r}px;top:{y - r}px">{_icon(f["left"], base)}</div>',
         f'<div class="ic wh r" style="left:{xr - r}px;top:{y - r}px">{_icon(f["right"], base)}</div>',
         f'<div class="pulse"></div><div class="ring" style="left:{xr}px;top:{y}px"></div><div class="ring r2" style="left:{xl}px;top:{y}px"></div>']
    if f.get('ok_text'):
        h.append(f'<div class="ok" data-in="{t_done:.3f}" data-fx="pop" data-dur="0.25" style="top:{y - 250}px">{_html.escape(f["ok_text"])}</div>')
    h.append('</div>')
    js = f'''<script>(function(){{{_EASE}
const prev=window.seekExtra;const S=document.querySelector(".fxc_{uid}");const L=S.querySelector(".ic.l"),R=S.querySelector(".ic.r");
const P=S.querySelector("#pfx_{uid}"),G=S.querySelector("#gfx_{uid}"),PU=S.querySelector(".pulse"),RG=S.querySelector(".ring:not(.r2)"),RG2=S.querySelector(".ring.r2");
const TA={t_a:.3f},TB={t_b:.3f},TL={t_link:.3f},TD={t_done:.3f},LEN=G.getTotalLength();
function fly(el,t0,from,t){{const p=bk((t-t0)/0.45);const hit=t>=TD?1-0.15*Math.exp(-(t-TD)*6)*Math.cos((t-TD)*18):1;
  const bob=4*Math.sin(2*Math.PI*t/1.9);el.style.opacity=t<t0?0:1;
  el.style.transform=`translate(${{from*(1-p)}}px, ${{bob}}px) scale(${{(0.6+0.4*p)*(t>=TD?2-hit:1)}}) rotate(${{(1-p)*from/30}}deg)`;
  const gl=t>=TD?1+1.2*Math.exp(-(t-TD)*3):0.9;el.style.filter=`drop-shadow(0 0 ${{24*gl}}px rgba(255,255,255,${{Math.min(1,.7*gl)}}))`;}}
window.seekExtra=function(t){{if(prev)prev(t);
  fly(L,TA,-700,t);fly(R,TB,700,t);
  P.style.strokeDashoffset=1-eo((t-TL)/0.4);
  const q=(t-TL-0.35)/Math.max(0.08,TD-TL-0.35);
  if(q>=0&&q<=1.05){{const pt=G.getPointAtLength(LEN*Math.min(1,eo(q)));PU.style.left=pt.x+"px";PU.style.top=pt.y+"px";PU.style.opacity=1;
    PU.style.transform=`scale(${{1+0.35*Math.sin(q*Math.PI*6)}})`;}} else PU.style.opacity=0;
  for(const [rg,dl] of [[RG,0],[RG2,0.08]]){{const u=(t-TD-dl)/0.6;rg.style.opacity=u<0?0:1-eo(u);rg.style.transform=`scale(${{0.3+1.6*eo(u)}})`;}}
}};}})();</script>'''
    ev = [('whoosh', t_a), ('whoosh', t_b), ('tick', t_link), ('tick', t_done)]
    return '\n'.join(h) + js, ev


def limits(f: dict, wt, s_in: float, s_out: float, uid: str) -> tuple[str, list]:
    t_a = wt(f['at_word']); t_p = wt(f['pulse_word']) if f.get('pulse_word') else None; t_b = wt(f['burst_word'])
    t_out = wt(f['out_word']) if f.get('out_word') else s_out
    cx, cy = W // 2, int(f.get('y', 1000)); bw, bh = int(f.get('w', 940)), int(f.get('h', 300))
    x0, y0, x1, y1 = cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2
    corners = {'tl': (x0, y0, -1, -1), 'tr': (x1 - 90, y0, 1, -1), 'bl': (x0, y1 - 90, -1, 1), 'br2': (x1 - 90, y1 - 90, 1, 1)}
    n = 18
    h = [f'<div class="fxl fxl_{uid}" data-in="{t_a:.3f}" data-out="{t_out:.3f}" data-fx="cut" data-dur="0.01" data-ofx="fade" data-odur="0.3">']
    for k, (x, y, sx, sy) in corners.items():
        h.append(f'<div class="br {k}" data-sx="{sx}" data-sy="{sy}" style="left:{x}px;top:{y}px"></div>')
    for i in range(n):
        a = 2 * math.pi * i / n + (0.3 if i % 2 else 0); sp = 520 + 260 * ((i * 7) % 5) / 4
        h.append(f'<div class="sp{" w" if i % 3 == 0 else ""}" data-a="{a:.3f}" data-s="{sp:.0f}" style="left:{cx}px;top:{cy}px"></div>')
    if f.get('label'):
        h.append(f'<div class="lbl" data-in="{t_a + 0.15:.3f}" data-out="{t_b:.3f}" data-fx="slide-up" data-dist="20" data-dur="0.2" data-ofx="fade" data-odur="0.1" '
                 f'style="top:{y0 - 70}px">{_html.escape(f["label"])}</div>')
    h.append('</div>')
    tp = f'{t_p:.3f}' if t_p is not None else 'null'
    js = f'''<script>(function(){{{_EASE}
const prev=window.seekExtra;const S=document.querySelector(".fxl_{uid}");const BR=[...S.querySelectorAll(".br")],SP=[...S.querySelectorAll(".sp")];
const TA={t_a:.3f},TP={tp},TB={t_b:.3f},FL=document.querySelector(".fxbg .flash");
window.seekExtra=function(t){{if(prev)prev(t);
  const pin=bk((t-TA)/0.4);                                   // clamp in with an overshoot
  let shake=0,pulse=1;
  if(TP!==null&&t>=TP){{const u=t-TP;shake=10*Math.exp(-u*5)*Math.sin(u*60);pulse=1+0.08*Math.exp(-u*4);}}
  const ub=(t-TB)/0.45, out=t>=TB?ei(ub):0;                            // burst out to the corners
  BR.forEach(b=>{{const sx=+b.dataset.sx,sy=+b.dataset.sy;const inx=sx*(1-pin)*420,iny=sy*(1-pin)*300;
    b.style.opacity=t<TA?0:(t>=TB?1-eo(ub):1);
    b.style.transform=`translate(${{inx+sx*out*700+shake}}px, ${{iny+sy*out*900}}px) scale(${{pulse*(1+out*0.8)}}) rotate(${{out*sx*sy*35}}deg)`;}});
  SP.forEach(s=>{{if(t<TB){{s.style.opacity=0;return;}}const u=(t-TB)/0.7,a=+s.dataset.a,d=+s.dataset.s*eo(u);
    s.style.opacity=u>1?0:1-ei(u);s.style.transform=`translate(${{Math.cos(a)*d}}px, ${{Math.sin(a)*d*0.8+160*u*u}}px) scale(${{1.4-u}})`;}});
  if(FL){{const u=t-TB;FL.style.opacity=u<0?0:0.35*Math.exp(-u*7);}}
}};}})();</script>'''
    ev = [('tick', t_a)] + ([('tick', t_p)] if t_p is not None else []) + [('whoosh', t_b)]
    return '\n'.join(h) + js, ev


def html(f: dict, wt, s_in: float, s_out: float, base: Path, uid: str) -> tuple[str, list]:
    k = f['kind']
    if k == 'grid_bg':
        t0 = wt(f['at_word']) if f.get('at_word') else s_in
        t1 = wt(f['out_word']) if f.get('out_word') else s_out
        return grid_bg(t0, t1, uid)
    if k == 'connect': return connect(f, wt, s_in, s_out, base, uid)
    if k == 'limits': return limits(f, wt, s_in, s_out, uid)
    raise SystemExit(f'fx: неизвестный kind {k!r}')
