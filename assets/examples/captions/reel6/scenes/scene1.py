"""Scene 1 «Забудьте про лучший день недели для постинга. Кажется, это не работает» (reel frames 250–352).
Two Messi reels, both posted on a WEDNESDAY: Mastercard 1,47 млрд views vs Lay's 21,3 млн -> 69×.
A (Mastercard, the shirt number runs 30 -> 18 -> 19 -> 10) big -> glitch cut -> B (Lay's, Messi on a video call) big ->
B shrinks to the right, A slides back on the left: two Instagram cards, both «СРЕДА» light up at once -> view counters + bars
on one scale (B's bar is 1/69 of A's) -> cards recede, 69× lands through an RGB split."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".claude/skills/video-edit/scripts/captions"))
from footage_scene import use, Scene, clip, views_html, ru, main, ORANGE, W
use(Path(__file__).parent)

SPEECH = {"забудьте": 250, "лучший": 268, "день": 276, "постинга": 296, "кажется": 316, "не": 337}
BIG = (150, 250, 780, 1387)
A_, B_ = (40, 330, 480, 853), (560, 330, 480, 853)
# multiplier reveals: NO impact/thump («тудум» on every N× annoyed the user, 2026-11-18) — only a quiet glitch2
SFX = [("swish2", 250, -9), ("thump", 250, -13), ("tact", 268, -7), ("glitch2", 281, -11), ("cut_click", 283, -10),
       ("swish1", 300, -9), ("ui", 304, -5), ("counter", 312, -12), ("snap", 326, -10),
       ("glitch2", 332, -15)]


def chip(sc, parent, box, f, fout, size=34, on_at=None):
    sc.el(f'<div class="chip" style="width:100%;height:100%;font-size:{size}px">СРЕДА</div>', box, f, fout, parent=parent,
          k=dict(s=[(f, .7), (f + 5, 1, "back")], o=[(f, 0), (f + 2, 1)]))
    if on_at:
        sc.el(f'<div class="chip on" style="width:100%;height:100%;font-size:{size}px">СРЕДА</div>', box, on_at, fout, parent=parent,
              k=dict(s=[(on_at, 1.18), (on_at + 5, 1, "back")], o=[(on_at, 0), (on_at + 1, 1)]))


def build():
    sc = Scene("scene1_day", 250, 352)
    s = .6154                                           # big card -> split card
    # ── A big: Mastercard, the shirt number changes to 10. Frame skip on the way out (279 -> 282 jumps 4 source frames)
    a = clip("messi_mastercard", 39.65, 41.0, 36)
    a = a[:29] + a[32:]
    ca = sc.el("", BIG, 250, 283, cls="card", k=dict(clip=[(250, [50, 0, 50, 0]), (259, [0, 0, 0, 0], "expo")], rad=36,
                                                     s=[(250, 1.14), (266, 1.0)], y=[(250, 40), (266, 0)]))
    sc.footage(a, 250, (0, 0, BIG[2], BIG[3]), parent=ca)
    sc.el('<div class="shadet"></div>', (0, 0, BIG[2], BIG[3]), 250, 283, parent=ca)
    chip(sc, ca, (36, 36, 250, 78), SPEECH["лучший"], 283)
    for f, kind, kw in [(280, "tear", dict(n=5, dx=50)), (281, "disp", dict(n=12, dx=140)), (281, "rgb", dict(dx=16)),
                        (282, "disp", dict(n=16, dx=200)), (282, "rgb", dict(dx=24)), (283, "rgb", dict(dx=12)), (283, "tear", dict(n=6, dx=70)),
                        (284, "rgb", dict(dx=5))]:
        sc.g(f, kind, **kw)

    # ── B big -> right split card: Lay's, Messi on the call (12.27 -> 13.1 plays at half speed under the counters)
    cb = sc.el("", BIG, 283, 352, cls="card",
               k=dict(s=[(283, 1.06), (290, 1), (300, 1), (310, s, "expo"), (324, s), (330, s * .95)],
                      x=[(300, 0), (310, 260, "expo")], y=[(300, 0), (310, -187, "expo")],
                      br=[(324, 1), (330, .55), (332, .55), (338, .3)], blur=[(332, 0), (338, 5)], sat=[(324, 1), (330, .5)]))
    sc.footage(clip("messi_lays", 11.7, 12.27, 17) + clip("messi_lays", 12.27, 13.1, 52), 283, (0, 0, BIG[2], BIG[3]), parent=cb)
    sc.el('<div class="shadet"></div>', (0, 0, BIG[2], BIG[3]), 283, 300, parent=cb)
    chip(sc, cb, (36, 36, 250, 78), 286, 300)

    # ── A comes back on the left
    ca2 = sc.el("", A_, 300, 352, cls="card",
                k=dict(x=[(300, -640), (311, 0, "expo")], r=[(300, -7), (311, 0, "expo")],
                       s=[(324, 1), (330, 1.04), (332, 1.04), (338, .94)], br=[(332, 1), (338, .3)], blur=[(332, 0), (338, 5)]))
    sc.footage(clip("messi_mastercard", 41.0, 42.7, 52), 300, (0, 0, A_[2], A_[3]), parent=ca2)

    # both posted on Wednesday: chips above the cards light up together, a line joins them
    for x in (A_[0] + 110, B_[0] + 110):
        chip(sc, None, (x, 236, 260, 78), 302, 352, size=34, on_at=305)
    sc.el(f'<div style="width:100%;height:100%;background:{ORANGE};border-radius:3px"></div>', (A_[0] + 370, 273, 300, 5), 305, 352,
          k=dict(clip=[(305, [0, 100, 0, 0]), (311, [0, 0, 0, 0], "expo")], o=[(332, 1), (336, .35)]))

    # ── views: counters run, then the bars on ONE scale (B = 1/69 of A)
    ta = {f: (ru(v / 1000, 2) + " млрд") if v >= 1000 else f"{v:.0f} млн" for f in range(312, 352) for v in [1470 * min(1, ((f - 311) / 14) ** .6)]}
    tb = {f: ru(21.3 * min(1, ((f - 311) / 14) ** .6), 1) + " млн" for f in range(312, 352)}
    dim = dict(o=[(312, 0), (314, 1), (332, 1), (336, .3)], y=[(312, 24), (316, 0)])
    sc.el(views_html(74), (A_[0] + 18, 1208, 470, 100), 312, 352, text=ta, k=dim)
    sc.el(views_html(74), (B_[0] + 18, 1208, 470, 100), 312, 352, text=tb, k=dict(dim, br=[(324, 1), (330, .6)]))
    for x in (A_[0] + 18, B_[0] + 18):
        sc.el('<div style="width:100%;height:100%;background:rgba(255,255,255,.2)"></div>', (x, 1318, 444, 4), 316, 352, k=dict(o=[(332, 1), (336, .3)]))
    sc.el(f'<div style="width:100%;height:100%;background:{ORANGE};border-radius:4px"></div>', (A_[0] + 18, 1312, 444, 16), 316, 352,
          k=dict(clip=[(316, [0, 100, 0, 0]), (328, [0, 0, 0, 0], "out")], o=[(332, 1), (336, .3)]))
    sc.el('<div style="width:100%;height:100%;background:#fff;border-radius:3px"></div>', (B_[0] + 18, 1312, 7, 16), 326, 352,
          k=dict(o=[(326, 0), (327, 1), (332, 1), (336, .3)]))

    # ── 69×
    sc.el(f'<div class="t acc" style="font-size:460px;text-align:center;width:100%">69×</div>', (0, 560, W, 420), 332, 352,
          k=dict(s=[(332, 1.32), (338, 1, "expo")], o=[(332, 0), (333, 1)]))
    sc.el('<div class="m" style="font-size:40px;text-align:center;width:100%">разница в просмотрах</div>', (0, 1010, W, 60), 337, 352,
          k=dict(o=[(337, 0), (340, 1)], y=[(337, 20), (341, 0)]))
    nb = (40, 540, 1040, 1000)
    for f, kind, kw in [(332, "rgb", dict(dx=28, box=nb)), (332, "tear", dict(n=7, dx=90, box=nb)), (333, "tear", dict(n=5, dx=50, box=nb)),
                        (333, "rgb", dict(dx=14, box=nb)), (334, "rgb", dict(dx=7, box=nb)), (335, "rgb", dict(dx=3, box=nb))]:
        sc.g(f, kind, **kw)
    sc.sfx = SFX
    return sc


if __name__ == "__main__":
    main(build)
