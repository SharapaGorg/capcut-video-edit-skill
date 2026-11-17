"""Reel 6 «Что общего между Nike, Роналду и Кайли Дженнер?» (29.4 s): standing hook → 18 s without camera (dark grid:
full-screen typographic scenes) → close-up CTA with a hand mic."""
import sys
from kit import Layout

L = Layout(sys.argv[1])
F, w, front, back = L.F, L.w, L.front, L.back
c1, c2, c3, c4, END = 87, 222, 632, 883, L.n
# hook | intro (grid) | tips (grid) | cta | end card. 632 = the grid fades out over 4 frames; 883 = the 2.2 s tail added with extend.py
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
for s in [("accent", F(1), -8), ("impact", F(3), -10), ("thump", F(3), -13), ("thump", F(4), -14), ("snap", F(4), -12),
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

# «Забудьте про лучший день недели для постинга. Кажется, это не работает»
c = F(33)
dead = F(31)
L.group(front, 400, c, [w("забудьте", b, "sans") + w("про", F(23), "sans"),
                        w("лучший", F(24), "serif acc", style="font-size:146px") + w("день", F(25), "serif acc", style="font-size:146px")], style="line-height:1.15")
L.group(front, 790, c, [L.struck(L.tiles(["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"], F(26), c, pick=2, f_hot=F(26) + 8, f_dead=dead), F(32), c)])
L.group(front, 1000, F(29), [w("для", F(27), "sans") + w("постинга", F(28), "sans")])
L.group(front, 1000, c, [w("кажется,", F(29), "sans") + w("это", F(30), "sans"),
                         w("не", F(31), "serif", style="font-size:150px") + w("работает", F(32), "serif", style="font-size:150px")], style="line-height:1.15")
for s in [("accent", F(24), -7), ("tact", F(26), -7), ("ui", F(26) + 8, -5), ("swish2", F(32), -8), ("thump", F(32), -13)]: L.sfx(*s)

# «А, ну и да, про время тоже»
d = F(40)
L.group(front, 400, d, [w("а,", c, "sans") + w("ну", F(34), "sans") + w("и", F(35), "sans") + w("да,", F(36), "sans")])
L.clock(560, F(37), d, size=360, speed=34)
L.group(front, 980, d, [L.struck(w("про", F(37), "serif", style="font-size:170px") + w("время", F(38), "serif acc", style="font-size:170px"), F(39) + 2, d),
                        w("тоже", F(39), "sans")], style="line-height:1.2")
L.sfx("counter", F(37), -11); L.sfx("swish2", F(39) + 2, -8)

# «Главное, не постите ночью»
e = F(44)
L.group(front, 420, e, [w("главное,", d, "serif", style="font-size:150px"), w("не", F(41), "sans") + w("постите", F(42), "sans")], style="line-height:1.3")
L.big(front, "ночью", F(43), e, 840, top=800, cls="acc")
L.group(front, 1130, e, [f'<span class="w a" data-in="{F(43) + 4}" data-fx="word" style="{MONO};font-size:76px;color:{L.cream}">00:00 — 06:00</span>'])
L.sfx("accent", d, -8); L.sfx("impact2", F(43), -9); L.sfx("shutter", F(43), -10)

# «У всех есть всплески охватов во время праздников, а также инфоповодов»
g = F(55)
L.group(front, 310, g, [w("у", e, "sans") + w("всех", F(45), "sans") + w("есть", F(46), "sans"),
                        w("всплески", F(47), "serif acc", style="font-size:200px;line-height:1.05"), w("охватов", F(48), "sans")], style="line-height:1.12")
P = [(0, .12), (.08, .2), (.15, .1), (.21, .24), (.28, .95), (.35, .16), (.44, .26), (.52, .12), (.6, .22), (.68, .3), (.76, 1.0), (.84, .2), (.92, .3), (1, .18)]
box = dict(x=110, y=960, width=860, height=400)
p1 = L.chart(F(48), g, P[:6], dur=F(51) - F(48) + 2, **box)
x0, wd = 110 + .35 * 860, 860 * .65
p2 = L.chart(F(52) - 4, g, [((a_ - .35) / .65, b_) for a_, b_ in P[5:]], dur=F(54) - F(52) + 6, x=round(x0), y=960, width=round(wd), height=400, axis=False)
L.group(front, 880, g, [w("праздники", F(51), "sans", style="font-size:60px")], x=p1[4][0] - 250, width=500)
L.group(front, 860, g, [w("инфоповоды", F(54), "sans", style="font-size:60px")], x=p2[5][0] - 250, width=500)
for s in [("accent", F(47), -7), ("swish1", F(48), -10), ("snap", F(51), -10), ("swish1", F(52) - 4, -11), ("snap", F(54), -10)]: L.sfx(*s)

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

# ── cta: close-up, the head moves a lot → small lines on the chest, HUD on «анализ аккаунта», one big word at the end
Y = 1280
TAG = f"font-family:'JetBrains Mono';font-weight:700;font-size:46px;color:#fff;background:{L.orange};padding:2px 14px 5px;border-radius:8px;vertical-align:.5em;margin-right:.35em"
num = lambda n, f: f'<span class="w a" data-in="{f}" data-fx="word" style="{TAG}">{n}</span>'
L.group(front, Y, F(66), [w("кстати,", c3 + 4, "serif", fx="cut", style="font-size:130px")])
L.group(front, Y, F(69), [w("вы", F(66), "sans") + w("тоже", F(67), "sans") + w("можете", F(68), "sans")])
L.group(front, Y, F(71), [w("сделать", F(69), "sans") + w("такой", F(70), "sans")])
top = min(x["top"] for x in L.heads[F(71):F(73)] if x)       # the head bobs here: take its highest position, not the median
L.big(back, "анализ", F(71), F(73), 900, head_top=top, ratio=0.7, cx=540)
L.group(front, Y, F(73), [w("аккаунта", F(72), "serif acc", style="font-size:130px")])
L.group(front, Y - 20, F(75), [num("01", F(73)) + w("охватные", F(73), "sans"), w("всплески", F(74), "serif acc", style="font-size:130px;line-height:1")], style="line-height:1.15")
L.group(front, Y - 20, F(78), [num("02", F(75)) + w("топы‑", F(75), "serif acc", style="font-size:96px;margin-right:0") + w("антитопы", F(76), "serif", style="font-size:96px;margin-left:0"),
                               w("роликов", F(77), "sans")], style="line-height:1.15")
L.group(front, Y - 20, F(80), [num("03", F(78)) + w("повторяющиеся", F(78), "sans", style="font-size:80px"), w("форматы", F(79), "serif acc", style="font-size:130px;line-height:1")], style="line-height:1.15")
L.group(front, Y - 20, F(82), [num("04", F(80)) + w("кодовые", F(80), "sans"), w("слова", F(81), "serif acc", style="font-size:130px;line-height:1")], style="line-height:1.15")
L.group(front, Y + 30, F(85), [w("и", F(82), "sans") + w("так", F(83), "sans") + w("далее", F(84), "sans")])
# «Всё тут» — he points up: the address is typed in a bar above the head, then stays alone on the end card
L.url("writelo.io", F(85) - 6, c4, 190, accent_from=7, dur=14, size=128, bar=True)
L.group(front, Y + 30, c4, [w("всё", F(85), "sans") + w("тут", F(86), "serif acc", style="font-size:130px") + L.arrow(F(86), c4, size=110, down=False)])
for s in [("cut_cam", c3, -10), ("impact", F(71), -10), ("thump", F(71), -13), ("accent", F(72), -7), ("tact", F(73), -7), ("tact", F(75), -7),
          ("tact", F(78), -7), ("tact", F(80), -7), ("swish1", F(82), -10), ("typing", F(85) - 6, -6), ("bell", F(86), -9), ("thump", F(86), -13)]: L.sfx(*s)

# ── end card (grid): the address alone, long enough to read
L.group(front, 560, END, [w("анализ", c4, "sans", fx="cut") + w("аккаунта", c4, "sans", fx="cut")])
L.url("writelo.io", c4, END, 700, accent_from=7, dur=1, size=190)
L.group(front, 1010, END, [w("всё", c4 + 6, "serif", style="font-size:120px") + w("тут", c4 + 9, "serif acc", style="font-size:120px")])
L.sfx("cut_click", c4, -10); L.sfx("thump", c4, -12); L.sfx("ding2", c4 + 9, -9)

L.music_open = c1
L.build()
