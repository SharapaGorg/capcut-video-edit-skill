"""Layout of reel 5 «Ты нейрокреатор?» (18 s): wide hook → close-up → phone on a grid → split (camera top, phone bottom)
→ letterboxed camera → close-up CTA. Copy the structure, not the numbers: every y / width here was tuned on stills of that footage.
Result: 5-ты-нейрокреатор/auto/out/captions_v5_music.mp4"""
import sys
from kit import Layout

L = Layout(sys.argv[1])
F, w, front, back = L.F, L.w, L.front, L.back
# section borders = hard cuts of the render (cuts.json) + the slide at 291 seen on the sheet
c1, c2, c3, c4, c5, END = 32, 88, 291, 422, 493, L.n

# ── hook 1 «Ты нейрокреатор?» — wide shot: the question on the wall, the last word behind the head
L.group(front, 540, c1, [w("ты", 0, "sans", fx="cut", style="font-size:92px"),
                         w("нейро", F(1), "serif", style="font-size:236px;line-height:.92")])
L.big(back, "КРЕАТОР?", 13, c1, 900, head_top=L.ht(13, c1), ratio=0.52)
L.sfx("accent", F(1), -8); L.sfx("impact", 13, -10); L.sfx("thump", 13, -13)

# ── hook 2 «Сейчас покажу, где искать» — close-up with a face HUD, then the silhouette beat on «ИИ-тренды»
fs = 65                                                # silhouette starts on «ИИ»
L.group(front, 1318, F(5), [w("сейчас", max(F(3), c1), "sans") + w("покажу,", F(4), "sans")])
L.group(front, 1300, fs, [w("где", F(5), "sans") + w("искать", F(6), "serif acc", style="font-size:118px")])
L.hud(c1 + 3, fs, "нейрокреатор ✓")
L.silhouette(fs, c2, fill_y=1250)                      # the mic in front of the chest must not show as a hole
L.ribbon(back, fs, c2, "M -90 760 C 160 700, 330 420, 620 380 S 1060 520, 990 860 S 900 1100, 1180 1180")
L.group(back, 120, c2, [w("ии‑", fs, "sans ink", fx="pop", style="font-size:118px;letter-spacing:-.03em;margin-right:0")
                        + w("тренды", fs + 2, "serif ink", fx="pop", style="font-size:172px;margin-left:0")], style="line-height:1.1")
L.ribbon(front, fs + 4, c2, "M 1180 1180 C 900 1330, 560 1180, 260 1400 S -40 1720, -140 1600", reverse=True)
L.eyes(fs + 2, c2)
for s in [("cut_cam", c1, -10), ("riser", fs, -10), ("focus", c1 + 3, -12), ("scan", c1 + 6, -20), ("impact", fs, -8), ("shutter", fs, -10),
          ("swish2", fs, -12), ("blip", fs + 2, -11), ("swish2", fs + 4, -12)]: L.sfx(*s)

# ── screen: phone on a grid — kinetic lines above the phone, never on its screen
Y = 300
L.group(front, Y + 40, F(10), [w("заходим,", max(F(9), c2), "serif", style="font-size:168px")])
L.group(front, Y - 10, F(13), [w("нажимаем", F(10), "sans") + w("на", F(11), "sans"),
                               w("фильтр", F(12), "serif acc", style="font-size:176px;line-height:1")], style="line-height:1.15")
L.chip(Y + 60, F(13), F(14), F(15), [("только", F(13)), ("ИИ", F(14))])
L.scroll(Y + 40, F(15), F(17), "листаем", lead="и")
L.group(front, Y - 10, F(20), [w("быстренько", F(17), "serif acc", style="font-size:128px;line-height:1.1"),
                               w("набираем", F(18), "sans") + w("себе", F(19), "sans")], style="line-height:1.2")
L.group(front, Y + 50, F(21), [w("понравившиеся", F(20), "serif", style="font-size:124px")])
L.group(front, Y - 30, F(23), [w("в", F(21), "sans")])
L.big(front, "референсы", F(22), F(23), 860, top=Y + 70, cls="acc")
L.group(front, Y - 10, c3, [w("и", F(23), "sans") + w("приступаем", F(24), "sans"),
                            w("к", F(25), "sans") + w("работе", F(26), "serif acc", style="font-size:176px;line-height:1")], style="line-height:1.15")
for s in [("cut_click", c2, -10), ("thump", c2, -13), ("accent", F(12), -7), ("tact", F(13), -7), ("ui", F(14), -5), ("mouse", F(14), -8),
          ("swish3", F(16), -8), ("swish3", F(16) + 6, -11), ("swish3", F(16) + 12, -14), ("swish1", F(17), -9), ("ding", F(20), -9),
          ("impact2", F(22), -9), ("shutter", F(22), -10), ("keysolo", F(26), -6)]: L.sfx(*s)

# ── dates: camera in the top half, phone below — big words behind the head, a small line on the seam
CLIP, SEAM = "top:0;height:960px", 944
def seam(f_out, *ws): L.group(front, SEAM, f_out, ["".join(ws)], cls="sans seam")
L.ride_edge(c3, 20, SEAM, 960, w("можно", c3, "", fx="cut", out=F(29)) + w("тут", F(28), "", out=F(29)), F(29))
seam(F(32), w("и по", F(29)), w("датам", F(31), "acc"))
seam(F(33), w("смотреть", F(32)))
seam(F(36), w("и по", F(33)), w("цифрам,", F(35), "acc"))
seam(F(38), w("можно", F(36)), w("даже", F(37)))
seam(F(41), w("что‑то", F(38)), w("конкретное", F(40)))
seam(c4, w("найти", F(41)), w("через", F(42)), w("поиск", F(43), "acc"))
L.big(back, "датам", F(31), F(33), 700, head_top=L.ht(F(31), F(33)), ratio=0.5, clip=CLIP)
L.big(back, "цифрам", F(35), F(38), 800, head_top=L.ht(F(35), F(38)), ratio=0.5, clip=CLIP)
L.big(back, "поиск", F(43), c4, 700, head_top=L.ht(F(43), c4), ratio=0.5, clip=CLIP)
L.sfx("cut_long", c3 + 6, -8)
for i in (31, 35, 43): L.sfx("thump", F(i), -14); L.sfx("snap", F(i), -12)
L.sfx("counter", F(35), -12); L.sfx("typing", F(43) + 3, -12)

# ── link: letterboxed camera — words above, the address typed below
L.group(front, 380, F(46), [w("делюсь", F(44), "sans"), w("ссылкой", F(45), "serif acc", style="font-size:170px;line-height:1")], style="line-height:1.15")
L.group(front, 440, F(48), [w("на", F(46), "sans", style="font-size:84px") + w("сайт", F(47), "sans", style="font-size:84px")])
L.group(front, 380, c5, [w("даже", F(48), "sans") + w("без", F(49), "sans"),
                         L.struck(w("кодового", F(50), "serif", style="font-size:120px") + w("слова", F(51), "serif", style="font-size:120px"), F(51) + 4, c5)],
        style="line-height:1.25")
L.url("writelo.io", F(45), c5, 1318, accent_from=7)
for s in [("cut_cam2", c4, -10), ("accent", F(45), -7), ("typing", F(45), -6), ("swish2", F(45) + 16, -9), ("swish2", F(51) + 4, -8)]: L.sfx(*s)

# ── cta «Сохраняй, чтобы не потерять»
L.big(back, "сохраняй", F(52), END, 930, head_top=L.ht(F(52), END), ratio=0.56)
L.group(front, 1290, END, [w("чтобы", F(53), "sans") + w("не", F(54), "sans") + L.bookmark(F(55) + 3, END),
                           w("потерять", F(55), "serif acc", style="font-size:112px;line-height:1")], x=300, width=680, style="line-height:1.15")
for s in [("cut_click", c5, -10), ("bell", F(52), -9), ("thump", F(52), -13), ("accent", F(55), -7), ("ding2", F(55) + 3, -8)]: L.sfx(*s)

L.music_open = c2                                      # muffled under the hook, opens on the cut to the phone
L.build()
