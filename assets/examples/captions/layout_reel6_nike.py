"""Reel 6 «Что общего между Nike, Роналду и Кайли Дженнер?» (29.4 s): standing hook → 18 s without camera (dark grid:
full-screen typographic scenes) → close-up CTA with a hand mic."""
import sys, subprocess
from pathlib import Path
from kit import Layout

L = Layout(sys.argv[1])
F, w, front, back = L.F, L.w, L.front, L.back
c1, c2, c3, c4, END = 87, 222, 632, 883, L.n
# hook | intro (grid) | tips (grid) | cta | end card. 632 = the grid fades out over 4 frames; 883 = the 2.2 s tail added with extend.py
ASSETS = Path(__file__).parent.parent / "assets"
def card(img, f, f_out, x, y, width=330, rot=0, pad=0, bg="#fff"):
    """photo card (white frame, tilted) over the speaker: the brand's real logo / the person's photo on their name"""
    front.append(f'<div class="a" data-in="{f}" data-out="{f_out}" data-fx="pop" style="position:absolute;left:{x}px;top:{y}px;width:{width}px">'
                 f'<div style="transform:rotate({rot}deg);background:#fff;padding:12px;border-radius:22px;box-shadow:0 18px 50px rgba(0,0,0,.5)">'
                 f'<div style="aspect-ratio:4/5;border-radius:12px;overflow:hidden;background:{bg};display:flex;align-items:center;justify-content:center">'
                 f'<img style="display:block;width:{100 - pad * 2}%;{"height:100%;object-fit:cover" if not pad else ""}" src="{(ASSETS / img).as_uri()}"></div></div></div>')
MONO = f"font-family:'JetBrains Mono';font-weight:600;font-size:44px;color:{L.orange};letter-spacing:.04em;text-shadow:0 2px 8px rgba(0,0,0,.6)"

# ── hook: the question on the wall, two names behind the head, the third one as the silhouette beat
fs = F(6)                                    # «Кайли»
L.group(front, 300, F(3), [w("что", 0, "sans", fx="cut"), w("общего", F(1), "serif", style="font-size:210px;line-height:.95"),
                           w("между", F(2), "sans")], style="line-height:1.1")
h = L.head(F(3), F(4)); L.big(back, "NIKE", F(3), F(4), 880, head_top=h["top"], ratio=0.62, cx=(h["x0"] + h["x1"]) // 2)
h = L.head(F(4), fs); L.big(back, "РОНАЛДУ", F(4), fs, 960, head_top=h["top"], ratio=0.6, cx=540)
L.silhouette(fs, c1)
L.ribbon(back, fs, c1, "M -90 1120 C 120 1080, 210 800, 470 640 S 900 700, 850 1000 S 800 1200, 1180 1260")
L.group(back, 150, c1, [w("и", fs, "sans ink", fx="cut", style="font-size:80px") + w("Кайли", fs, "serif ink", fx="pop", style="font-size:200px"),
                        w("Дженнер?", F(7), "serif ink", fx="pop", style="font-size:200px")], style="line-height:1.08")
L.ribbon(front, fs + 4, c1, "M 1180 1260 C 900 1400, 600 1290, 320 1470 S -40 1730, -140 1640", reverse=True)
L.eyes(fs + 2, c1, devil=True)
L.devil(fs + 3, c1, size=1.15, tail=(650, 1540, 1.35))             # the user asked for «more devilish» here
card("nike.svg", F(3), c1, 36, 1100, 340, rot=-7, pad=12)
card("ronaldo.jpg", F(4), c1, 704, 1130, 340, rot=6)
card("kylie.jpg", fs, c1, 350, 1190, 380, rot=-3)
for s in [("swish2", F(3), -11), ("swish2", F(4), -11), ("accent", F(1), -8), ("impact", F(3), -10), ("thump", F(3), -13), ("thump", F(4), -14), ("snap", F(4), -12),
          ("riser", fs, -10), ("impact", fs, -8), ("shutter", fs, -10), ("swish2", fs, -12), ("blip", fs + 2, -11), ("swish2", fs + 4, -12),
          ("doom", fs, -15), ("glitch", fs + 3, -13)]: L.sfx(*s)

# ── intro (grid): «Разобрали 100 инстаграм-аккаунтов бизнесов и знаменитостей, чтобы узнать секреты их популярности»
a = F(15)                                    # «чтобы»
L.group(front, 290, a, [w("разобрали", c1, "sans", fx="cut")])
L.counter(390, F(9), a, 100, dur=12, size=340)
L.group(front, 740, F(12), [w("инстаграм‑аккаунтов", F(10), "serif", style="font-size:92px")])
L.group(front, 730, a, [w("бизнесов", F(12), "serif acc", style="font-size:92px"),
                        w("и", F(13), "sans", style="font-size:60px") + w("знаменитостей", F(14), "serif", style="font-size:92px")], style="line-height:1.12")
L.dots(980, F(10), a, n=100, cols=10, per=6, size=36, gap=10, hot_at=F(12), hot_every=3)
L.group(front, 600, c2, [w("чтобы", a, "sans") + w("узнать", F(16), "sans"),
                         w("секреты", F(17), "serif acc", style="font-size:240px;line-height:1.05"),
                         w("их", F(18), "sans") + w("популярности", F(19), "serif", style="font-size:118px")], style="line-height:1.2")
for s in [("cut_click", c1, -10), ("thump", c1, -13), ("counter", F(9), -12), ("typing", F(10), -10), ("accent", F(12), -7), ("ding", F(14), -10),
          ("swish1", a, -9), ("impact2", F(17), -10), ("shutter", F(17), -11)]: L.sfx(*s)

# ── tips (grid)
# «Итак, начнём»
b = F(22)
L.group(front, 600, b, [w("итак,", max(F(20), c2), "serif", style="font-size:200px")])
L.big(front, "начнём", F(21), b, 820, top=880, cls="acc")
L.sfx("swish1", F(20), -10); L.sfx("impact2", F(21), -9); L.sfx("shutter", F(21), -10)

# ── v5 (2026-11-18): the three tips are FOOTAGE SCENES now — the real reels from ../footage instead of day tiles / clock / chart.
# Built by auto/scenes/scene{1,2,3}.py (engine.py: footage frames + HTML motion graphics + glitch post, drawn over the base frames
# of this very render, so the grid matches); here their frames become the picture of those frames (L.plate), with their sounds.
#   scene1 250–352 «забудьте про лучший день…»: two Messi reels, both on Wednesday, 1,47 млрд vs 21,3 млн -> 69×
#   scene2 352–430 «про время тоже / не постите ночью»: Nike 19:01 (135 млн) vs 19:02 (2,2 млн) -> 61×
#   scene3 430–535 «всплески… инфоповоды»: NASA Artemis II splashdown 12,6× -> Nike Brazil women 19,6× (to the account median)
# Edit a scene: change scenes/sceneN.py, `python -X utf8 sceneN.py` there, then `run.py <auto> render --range <f0>,<f1>`.
c, d, e, g = F(33), F(40), F(44), F(55)
sys.path.insert(0, str(Path(__file__).parent.parent / "scenes"))
import scene1, scene2, scene3
for m in (scene1, scene2, scene3):
    sc = m.build()
    files = sorted((Path(__file__).parent.parent / "scenes" / "out" / sc.name).glob("*.jpg"))
    assert len(files) == sc.f1 - sc.f0, f"{sc.name}: render the scene first ({len(files)} frames)"
    L.plate(sc.f0, files)
    for s in sc.sfx: L.sfx(*s)

# «Всегда будьте начеку»
i = F(59)
L.group(front, 540, i, [w("всегда", g, "sans") + w("будьте", F(56), "sans")])
L.big(front, "начеку", F(57), i, 880, top=700, cls="acc")
L.sfx("thump", F(57), -12); L.sfx("snap", F(57), -10)

# «А остальные инсайды читайте в описании»
L.group(front, 430, c3, [w("а", i, "sans") + w("остальные", F(60), "sans"),
                         w("инсайды", F(61), "serif acc", style="font-size:220px;line-height:1.05"),
                         w("читайте", F(62), "sans"),
                         w("в", F(63), "serif", style="font-size:150px") + w("описании", F(64), "serif", style="font-size:150px"),
                         L.arrow(F(64) + 3, c3, size=150)], style="line-height:1.2")
L.sfx("accent", F(61), -7); L.sfx("ding", F(64) + 3, -9)

# ── cta: close-up. v3: from «сделать такой анализ аккаунта» the REAL mobile screencast of the account analysis (writelo.io landing,
# 1080x2336) rides up full height over the speaker (the user allowed to cover the face); every item of the list shows ITS screen:
# link pasted → «Разобрать», views chart with spikes, top reels, formats, code words. Words live in the black strip at the bottom
# of the phone (it also hides the Safari toolbar with the staging address).
Y = 1280
TAG = f"font-family:'JetBrains Mono';font-weight:700;font-size:40px;color:#fff;background:{L.orange};padding:2px 12px 4px;border-radius:8px;vertical-align:.35em;margin-right:.35em"
num = lambda n, f: f'<span class="w a" data-in="{f}" data-fx="word" style="{TAG}">{n}</span>'
SRC = ASSETS / "writelo_analysis_mobile.mp4"
PW, PH, PT, STRIP = 940, 1430, 110, 240       # v4 (the user: «скринкаст чуть увеличишь»): the screen is 44 % bigger — almost the frame width,
# so only a part of the phone screen fits by height: every piece shows ITS part (`top` = where the window starts, share of the source height)
SH = round(2336 * PW / 1080 / 2) * 2           # source height after scaling to the window width
def cast(name, t0, t1, f, f_out, top=0.0):
    """real screencast, a new source frame on EVERY frame of the reel; window PW x PH cut from the scaled source at `top`"""
    n = f_out - f
    y = min(round(top * SH), SH - PH)
    d = ASSETS / f"cast4_{name}_{n}_{round(t0 * 10)}_{round(t1 * 10)}_{y}"
    if len(list(d.glob("*.jpg"))) != n:
        d.mkdir(exist_ok=True)
        for old in d.glob("*.jpg"): old.unlink()
        fps = n / (t1 - t0)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t0), "-t", str(t1 - t0 + 0.2), "-i", str(SRC),
                        "-vf", f"fps={fps:.4f},scale={PW}:{SH},crop={PW}:{PH}:0:{y}", "-frames:v", str(n), "-q:v", "3", str(d / "%04d.jpg")], check=True)
    files = sorted(d.glob("*.jpg"))
    return "".join(f'<img class="a" data-in="{f + k}" data-out="{f + k + 1}" data-fx="cut" style="position:absolute;inset:0;width:100%;height:100%" src="{files[min(k, len(files) - 1)].as_uri()}">'
                   for k in range(n))
def pphone(body, f, f_out):
    x = (1080 - PW - 24) // 2
    front.append(f'<div class="a" data-in="{f}" data-out="{f_out}" data-fx="pop" style="position:absolute;left:{x}px;top:{PT - 12}px;width:{PW + 24}px">'
                 f'<div style="border-radius:54px;background:#0A0A0A;border:3px solid #3A3A3A;padding:9px;box-shadow:0 26px 70px rgba(0,0,0,.6)">'
                 f'<div style="position:relative;height:{PH}px;border-radius:44px;overflow:hidden;background:#0A0A0A">{body}'
                 f'<div style="position:absolute;left:0;right:0;bottom:0;height:{STRIP}px;background:#0A0A0A;border-top:2px solid #3A2A20"></div></div></div></div>')
def cap(f_out, *lines):
    y = PT + PH - STRIP + (72 if len(lines) == 1 else 16)
    L.group(front, y, f_out, list(lines), x=(1080 - PW) // 2, width=PW, style="line-height:1.12")
def cw(t, f, size=54, cls="sans", extra="", fx="word"): return w(t, f, cls, fx=fx, style=f"font-size:{size}px;{extra}")

L.group(front, Y, F(66), [w("кстати,", c3 + 4, "serif", fx="cut", style="font-size:130px")])
L.group(front, Y, F(69), [w("вы", F(66), "sans") + w("тоже", F(67), "sans") + w("можете", F(68), "sans")])
p0, p1 = F(69), F(85) - 6                    # phone: «сделать» … till the address starts typing
i1, i2, i3, i4, i5 = F(73), F(75), F(78), F(80), F(82)
# source (s): 1.3–3.3 link pasted and «Разобрать» tapped · 3.4–4.4 progress steps · 4.4–6.6 report opens, top reels (+28×) ·
# 14.9–17 views chart, spikes highlighted · 27.4–29.4 formats · 30–31.2 code words · 32.5–34.6 calls to action, audience
a1, a2 = p0 + 30, p0 + 38
pphone(cast("open", 1.3, 3.3, p0, a1, 0.03) + cast("load", 3.4, 4.4, a1, a2, 0.03) + cast("rep", 4.4, 4.4 + (i1 - a2) / 30 * 1.5, a2, i1, 0.03)
       + cast("spikes", 14.9, 17.0, i1, i2, 0.16)
       + cast("tops", 4.6, 6.6, i2, i3, 0.16)
       + cast("formats", 27.4, 29.4, i3, i4, 0.28)
       + cast("words", 30.0, 31.2, i4, i5, 0.17)
       + cast("etc", 32.5, 34.6, i5, p1, 0.2), p0, p1)
cap(F(71), cw("сделать", p0, 64) + cw("такой", F(70), 64))
cap(i1, cw("анализ", F(71), 104, "serif", "line-height:1", fx="pop") + cw("аккаунта", F(72), 104, "serif acc", "line-height:1"))
cap(i2, num("01", i1) + cw("охватные", i1, 62), cw("всплески", F(74), 110, "serif acc", "line-height:1"))
cap(i3, num("02", i2) + cw("топы‑", i2, 76, "serif acc", "margin-right:0") + cw("антитопы", F(76), 76, "serif", "margin-left:0"), cw("роликов", F(77), 62))
cap(i4, num("03", i3) + cw("повторяющиеся", i3, 60), cw("форматы", F(79), 110, "serif acc", "line-height:1"))
cap(i5, num("04", i4) + cw("кодовые", i4, 62), cw("слова", F(81), 110, "serif acc", "line-height:1"))
cap(p1, cw("и", i5, 70) + cw("так", F(83), 70) + cw("далее", F(84), 70))
# «Всё тут» — he points up: the address is typed in a bar above the head, then stays alone on the end card
L.url("writelo.io", p1, c4, 190, accent_from=7, dur=14, size=128, bar=True)
L.group(front, Y + 30, c4, [w("всё", F(85), "sans") + w("тут", F(86), "serif acc", style="font-size:130px") + L.arrow(F(86), c4, size=110, down=False)])
for s in [("cut_cam", c3, -10), ("swish2", p0, -9), ("ui", p0 + 24, -6), ("impact", F(71), -11), ("accent", F(72), -7), ("tact", i1, -7), ("tact", i2, -7),
          ("tact", i3, -7), ("tact", i4, -7), ("swish1", i5, -10), ("swish2", p1, -10), ("typing", p1, -6), ("bell", F(86), -9), ("thump", F(86), -13)]: L.sfx(*s)

# ── end card (grid): the address alone, long enough to read
L.group(front, 560, END, [w("анализ", c4, "sans", fx="cut") + w("аккаунта", c4, "sans", fx="cut")])
L.url("writelo.io", c4, END, 700, accent_from=7, dur=1, size=190)
L.group(front, 1010, END, [w("всё", c4 + 6, "serif", style="font-size:120px") + w("тут", c4 + 9, "serif acc", style="font-size:120px")])
L.sfx("cut_click", c4, -10); L.sfx("thump", c4, -12); L.sfx("ding2", c4 + 9, -9)

L.music_open = c1
L.build()
