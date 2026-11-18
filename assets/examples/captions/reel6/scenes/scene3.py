"""Scene 3 «У всех есть всплески охватов во время праздников, а также инфоповодов» (reel frames 430–535).
NASA, Artemis II splashdown (12,6× the account's median views) -> glitch -> Nike, the Brazil women's team wins (19,6×).
NASA in a tall window, the capsule hits the water exactly on «всплески» -> freeze + flash + punch-in, orange frame on the splash,
the multiplier runs up -> displacement glitch -> Nike Brazil whips in, real match footage -> freeze on the celebration, 19,6× tears in."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / ".claude/skills/video-edit/scripts/captions"))
from footage_scene import use, Scene, clip, views_html, ru, main, ORANGE, W
use(Path(__file__).parent)

WIN = (0, 0, W, 1480)
SPLASH = (508, 1250)                                 # capsule splash inside the window
# multiplier reveals: NO impact/thump («тудум» on every N× annoyed the user, 2026-11-18) — only a quiet glitch2
SFX = [("cut_click", 430, -10), ("thump", 430, -13), ("tact", 436, -7), ("flash", 450, -12), ("counter", 451, -13),
       ("focus", 452, -12), ("glitch2", 474, -11), ("glitch", 476, -13), ("swish1", 479, -9), ("tact", 485, -7),
       ("glitch2", 516, -15)]


def label(sc, f, fout, tag, line, y=200):
    sc.el(f'<div class="chip" style="width:100%;height:100%;font-size:32px;justify-content:flex-start;padding-left:26px">{tag}</div>',
          (60, y, 520, 70), f, fout, k=dict(x=[(f, -40), (f + 5, 0, "expo")], o=[(f, 0), (f + 2, 1)]))
    sc.el(f'<div class="t" style="font-size:66px;font-weight:800;letter-spacing:-.03em;line-height:1.05;background:rgba(11,11,11,.85);'
          f'padding:14px 26px 20px;border-radius:20px;display:inline-block">{line}</div>', (60, y + 90, 980, 120), f + 3, fout,
          k=dict(x=[(f + 3, -40), (f + 8, 0, "expo")], o=[(f + 3, 0), (f + 5, 1)]))


def build():
    sc = Scene("scene3_spikes", 430, 535)
    # ── NASA window: reveals top-down (descent), the inner frame is 1.15x so the splash sits at 65 % of the screen
    win = sc.el("", WIN, 430, 476, style="overflow:hidden;border-bottom:2px solid rgba(255,255,255,.25)",
                k=dict(clip=[(430, [0, 0, 70, 0]), (437, [0, 0, 0, 0], "expo")]))
    nasa = clip("nasa_artemis2", 9.0, 10.3, 20)
    org = f"{SPLASH[0] / 1242 * 100:.1f}% {(SPLASH[1] + 650) / 2208 * 100:.1f}%"
    sc.el("", (0, -650, 1242, 2208), 430, 476, parent=win, origin=org, k=dict(s=[(430, 1), (450, 1.05, "lin"), (455, 1.17, "expo"), (476, 1.21, "lin")]))
    sc.footage(nasa + [nasa[-1]] * 26, 430, (0, 0, 1242, 2208), parent=sc.els[-1]["id"])
    sc.el('<div style="width:100%;height:100%;background:#fff"></div>', WIN, 450, 454, k=dict(o=[(450, .85), (454, 0, "lin")]))
    # orange frame on the splash
    bw, bh = 400, 300
    fr = sc.el("", (SPLASH[0] - bw // 2, SPLASH[1] - bh // 2 - 20, bw, bh), 452, 476, k=dict(s=[(452, 1.5), (458, 1, "expo")], o=[(452, 0), (454, 1)]))
    for st in ("left:0;top:0;border-left-width:7px;border-top-width:7px", "right:0;top:0;border-right-width:7px;border-top-width:7px",
               "left:0;bottom:0;border-left-width:7px;border-bottom-width:7px", "right:0;bottom:0;border-right-width:7px;border-bottom-width:7px"):
        sc.el(f'<div class="corner" style="{st}"></div>', (0, 0, bw, bh), 452, 476, parent=fr)
    label(sc, 436, 476, "NASA · Artemis II", "возвращение экипажа")
    # the multiplier runs up on the freeze
    tx = {f: ru(1 + 11.6 * min(1, ((f - 450) / 13) ** .55), 1) + "×" for f in range(451, 476)}
    sc.el('<div class="t acc tx" style="font-size:300px;text-align:center;width:100%"></div>', (0, 630, W, 300), 451, 476, text=tx,
          k=dict(s=[(451, .85), (456, 1, "back"), (463, 1), (466, 1.06), (470, 1)], o=[(451, 0), (452, 1)]))
    sc.el('<div class="m" style="font-size:36px;text-align:center;width:100%">к медиане просмотров аккаунта</div>', (0, 930, W, 56), 456, 476,
          k=dict(o=[(456, 0), (459, 1)]))
    for f, kind, kw in [(474, "tear", dict(n=6, dx=60)), (475, "disp", dict(n=12, dx=160)), (475, "rgb", dict(dx=14)),
                        (476, "disp", dict(n=18, dx=260)), (476, "rgb", dict(dx=26)), (477, "disp", dict(n=10, dx=140)), (477, "rgb", dict(dx=14)),
                        (478, "rgb", dict(dx=6)), (478, "tear", dict(n=4, dx=40))]:
        sc.g(f, kind, **kw)

    # ── Nike Brazil: real match footage (white flash frames of the source skipped), freeze on the celebration
    seq = (clip("nike_brazil", 8.9, 9.35, 14) + clip("nike_brazil", 9.6, 9.85, 8) + clip("nike_brazil", 10.1, 10.5, 12)
           + clip("nike_brazil", 10.7, 10.8, 3))
    hold = clip("nike_brazil", 10.85, 10.9, 1)
    wb = sc.el("", WIN, 476, 535, style="overflow:hidden;border-bottom:2px solid rgba(255,255,255,.25)",
               k=dict(x=[(476, 300), (479, 300), (486, 0, "expo")], blur=[(479, 16), (485, 0)]))
    sc.el("", (0, -120, W, 1920), 476, 535, parent=wb, origin="50% 30%",
          k=dict(s=[(479, 1.06), (516, 1, "lin"), (521, 1.1, "expo"), (535, 1.13, "lin")], br=[(516, 1), (521, .5)]))
    sc.footage([seq[0]] * 3 + seq + hold * 19, 476, (0, 0, W, 1920), parent=sc.els[-1]["id"])
    label(sc, 482, 535, "Nike · сборная Бразилии", "победы женской сборной", y=1170)   # low: the freeze has her face at the top
    sc.el('<div style="width:100%;height:100%;background:rgba(11,11,11,.85);border-radius:30px"></div>', (100, 700, 880, 400), 516, 535,
          k=dict(sy=[(516, .2), (520, 1, "expo")], o=[(516, 0), (517, 1)]))
    sc.el('<div class="t acc" style="font-size:300px;text-align:center;width:100%">19,6×</div>', (0, 740, W, 280), 516, 535,
          k=dict(s=[(516, 1.25), (521, 1, "expo")], o=[(516, 0), (517, 1)]))
    sc.el('<div class="m" style="font-size:34px;text-align:center;width:100%">к медиане просмотров аккаунта</div>', (0, 1022, W, 56), 519, 535,
          k=dict(o=[(519, 0), (522, 1)]))
    nb = (100, 690, 980, 1110)
    for f, kind, kw in [(516, "tear", dict(n=9, dx=100, box=nb)), (516, "rgb", dict(dx=12, box=nb)), (517, "tear", dict(n=6, dx=70, box=nb)),
                        (518, "tear", dict(n=4, dx=36, box=nb)), (519, "rgb", dict(dx=3, box=nb))]:
        sc.g(f, kind, **kw)
    sc.sfx = SFX
    return sc


if __name__ == "__main__":
    main(build)
