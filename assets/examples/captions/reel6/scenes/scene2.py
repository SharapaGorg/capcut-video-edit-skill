"""Scene 2 «А, ну и да, про время тоже. Главное, не постите ночью» (reel frames 352–430).
Two Nike reels a minute apart by the clock: Rip The Script 19:01 МСК (135 млн) vs Breaking4 19:02 МСК, another date (2,2 млн) -> 61×.
Rip The Script as a tilted card with fast cuts (explosion -> two cameo shots; the seated cameo again in its band), the big «19:01» above it ->
glitch: the last digit turns into 2, the card into Breaking4 -> two horizontal bands slam in from both sides, «+1 мин» on the seam,
counters -> the lower band sinks -> 61× through a digital glitch."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".claude/skills/video-edit/scripts/captions"))
from footage_scene import use, Scene, clip, views_html, ru, main, ORANGE, W
use(Path(__file__).parent)

CARD = (170, 430, 740, 1316)
B1, B2 = (40, 300, 1000, 540), (40, 900, 1000, 540)
# multiplier reveals: NO impact/thump («тудум» on every N× annoyed the user, 2026-11-18) — only a quiet glitch2
SFX = [("swish2", 352, -9), ("thump", 352, -13), ("cut_click", 360, -12), ("cut_click", 365, -12), ("glitch2", 371, -11), ("snap", 373, -10),
       ("swish1", 390, -9), ("swish2", 391, -10), ("tact", 395, -7), ("counter", 397, -12), ("thump", 407, -14),
       ("glitch2", 412, -15)]


def build():
    sc = Scene("scene2_time", 352, 430)
    # ── the clock reading, big, above the card (parallax: it drifts up while the card drifts down)
    tt = {f: ("19:01" if f < 373 else "19:02") for f in range(352, 390)}
    sc.el('<div class="t tx" style="font-size:250px;text-align:center;width:100%"></div>', (0, 150, W, 240), 352, 390, text=tt,
          k=dict(y=[(352, 60), (360, 0, "expo"), (390, -16, "lin")], o=[(352, 0), (354, 1)]))
    sc.el('<div class="m" style="font-size:34px;text-align:center;width:100%;opacity:.8">время публикации · мск</div>', (0, 110, W, 50), 354, 390,
          k=dict(o=[(354, 0), (358, 1)]))
    tb = (60, 120, 1020, 400)
    for f, kind, kw in [(371, "rgb", dict(dx=22, box=tb)), (371, "tear", dict(n=6, dx=80, box=tb)), (372, "tear", dict(n=5, dx=60, box=tb)),
                        (372, "rgb", dict(dx=14, box=tb)), (373, "rgb", dict(dx=6, box=tb)), (374, "rgb", dict(dx=3, box=tb))]:
        sc.g(f, kind, **kw)

    # ── A: Rip The Script, three fast cuts inside one card
    ca = sc.el("", CARD, 352, 373, cls="card", k=dict(y=[(352, 760), (361, 0, "expo"), (373, 22, "lin")], r=[(352, -9), (361, -2.5, "expo")],
                                                    s=[(361, 1.03), (373, 1, "lin")]))
    seq = clip("nike_ripthescript", 38.3, 38.6, 8) + clip("nike_ripthescript", 43.6, 43.8, 5) + clip("nike_ripthescript", 54.62, 54.95, 8)
    sc.footage(seq, 352, (0, 0, CARD[2], CARD[3]), parent=ca)
    sc.g(360, "rgb", dx=8, box=(150, 400, 930, 1780)); sc.g(365, "rgb", dx=8, box=(150, 400, 930, 1780))
    cbox = (150, 400, 930, 1780)
    for f, kind, kw in [(371, "disp", dict(n=12, dx=150, box=cbox)), (372, "disp", dict(n=16, dx=220, box=cbox)), (372, "rgb", dict(dx=20, box=cbox)),
                        (373, "tear", dict(n=6, dx=70, box=cbox))]:
        sc.g(f, kind, **kw)

    # ── B: Breaking4, the other way tilted
    cb = sc.el("", CARD, 373, 390, cls="card", k=dict(r=[(373, 5), (378, 2.5, "expo")], s=[(373, 1.06), (378, 1, "expo"), (390, .98, "lin")]))
    sc.footage(clip("nike_breaking4", 17.95, 18.5, 17), 373, (0, 0, CARD[2], CARD[3]), parent=cb)

    # ── bands: one minute apart, 61 times apart
    def band(box, src, t0, t1, f, side, label, views, n_to, d, pos="50% 45%"):
        b = sc.el("", box, f, 430, cls="card", k=dict(x=[(f, side * 1150), (f + 8, 0, "expo")],
                                                     br=[(412, 1), (417, .3)], blur=[(412, 0), (417, 4)], **d))
        sc.footage(clip(src, t0, t1, 430 - f), f, (0, 0, box[2], box[3]), parent=b, fit=f"object-position:{pos}")
        sc.el('<div class="shade" style="height:55%"></div>', (0, 0, box[2], box[3]), f, 430, parent=b)
        sc.el(f'<div class="chip" style="width:100%;height:100%;font-size:34px">{label}</div>', (28, 28, 290, 74), f + 3, 430, parent=b,
              k=dict(o=[(f + 3, 0), (f + 5, 1)]))
        txt = {fr: views(n_to * min(1, ((fr - f - 5) / 12) ** .6)) for fr in range(f + 5, 430)}
        sc.el(views_html(92), (30, box[3] - 132, 700, 110), f + 5, 430, parent=b, text=txt, k=dict(o=[(f + 5, 0), (f + 7, 1)]))
    band(B1, "nike_ripthescript", 43.25, 44.2, 390, -1, "19:01 мск", lambda v: f"{v:.0f} млн", 135,
         dict(s=[(406, 1), (412, 1.02)]), pos="50% 73%")   # the seated cameo (source 43.2–44.2)
    band(B2, "nike_breaking4", 18.5, 18.95, 391, 1, "19:02 мск", lambda v: ru(v, 1) + " млн", 2.2,
         dict(s=[(406, 1), (412, .95)], y=[(406, 0), (412, 26)], sat=[(406, 1), (412, .35)], o=[(406, 1), (412, .8)]), pos="50% 26%")
    sc.el(f'<div class="chip on" style="width:100%;height:100%;font-size:36px">+1 мин</div>', (420, 844, 240, 74), 395, 430,
          k=dict(s=[(395, .6), (400, 1, "back")], o=[(395, 0), (397, 1), (412, 1), (416, 0)]))

    # ── 61×
    sc.el(f'<div class="t acc" style="font-size:460px;text-align:center;width:100%">61×</div>', (0, 640, W, 420), 412, 430,
          k=dict(s=[(412, 1.3), (418, 1, "expo")], o=[(412, 0), (413, 1)]))
    sc.el('<div class="m" style="font-size:40px;text-align:center;width:100%">разница в просмотрах</div>', (0, 1090, W, 60), 417, 430,
          k=dict(o=[(417, 0), (420, 1)], y=[(417, 20), (421, 0)]))
    nb = (40, 600, 1040, 1100)
    for f, kind, kw in [(412, "disp", dict(n=10, dx=160, box=nb)), (412, "rgb", dict(dx=26, box=nb)), (413, "tear", dict(n=7, dx=90, box=nb)),
                        (413, "rgb", dict(dx=12, box=nb)), (414, "rgb", dict(dx=6, box=nb)), (415, "rgb", dict(dx=2, box=nb))]:
        sc.g(f, kind, **kw)
    sc.sfx = SFX
    return sc


if __name__ == "__main__":
    main(build)
