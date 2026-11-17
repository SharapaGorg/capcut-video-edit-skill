"""Every block of the editorial set (reference 2, see REFERENCES.md) on the footage of reel 5 — a test sheet, not a finished reel:
the blocks are stacked to show them all. Stills: ref2_blocks.jpg (frames 6, 12, 24, 50, 70, 112, 200, 280, 330, 493, 514, 530)."""
import sys
from kit import Layout

L = Layout(sys.argv[1])
F, w, front, back = L.F, L.w, L.front, L.back
c1, c2, c3, c4, c5, END = 32, 88, 291, 422, 493, L.n
L.theme("red")
L.meta(0, END, tl="ИИ-тренды → каждый день", tr="ВЫПУСК 005", bl="Меньше листать.\nБольше снимать.")

# wide hook: silhouette on red with a halo, glitch blocks, handwriting; then outline + stairs
h = L.head(0, 16)
L.fill(back, 0, 16, L.orange, halo=((h["x0"] + h["x1"]) // 2, h["top"] + 150, 330, "#F0641E"))
L.silhouette(0, 16)
L.blocks(0, 8)
L.hand(front, "стой.", 3, 16, 640, 1050, size=230, color="#8FD8F0", rot=-8)
L.rim(16, c1)
L.stairs(front, [("ты", 16), ("нейро", 19), ("креатор?", 24)], 90, 480, c1, size=80, grow=1.45, dx=30, accent=(2,))

# close-up: scribble around the face + handwriting + arrow
L.track(c1, c2)
fx, fy, fw, fh = L.FACE[str(50)]
L.scribble(front, "circle", c1 + 4, c2, (fx - 60, fy - 90, fw + 120, fh + 170), dur=9)
L.hand(front, "это\nты?", c1 + 10, c2, 60, 380, size=190, rot=-7)
L.scribble(front, "arrow", c1 + 16, c2, (330, 600, fx - 40, fy + 60), width=8, dur=6, seed=3)
L.scribble(front, "underline", c1 + 20, c2, (120, 1420, 760, 26), color="#fff", seed=5)

# phone section: glow card, then prompt bar; sketch box
L.glowcard(100, 130, [[("И ЭТО", 100)], [("ЖЕСТЬ", 108)]])
L.scribble(front, "box", 140, 290, (200, 420, 680, 760), color="#fff", width=10, dur=10, seed=2)
L.prompt("Найди ИИ-тренды для рилсов за последнюю неделю и покажи лучшие", 150, 290, y=1240, dur=40, model="GPT")

# split: wall behind
L.wall(["ТРЕН", "ДЫ"], 300, 420, top=120, height=760)

# CTA: flash + outline + growing stairs + rotated accent
L.flash(c5, 2, "invert")
L.flash(c5 + 20, 2, "duo")
L.rim(c5, END)
L.stairs(front, [("и", c5 + 2), ("я", c5 + 5), ("пришлю", c5 + 8), ("тебе.", c5 + 12)], 560, 300, END, size=56, grow=1.35, dx=26)
L.at(front, w("ссылку", c5 + 14, "sans acc", style="font-size:150px"), 540, 1380, END, rot=-14, align="center")
for s in [("glitch2", 0, -11), ("impact", 0, -8), ("marker", 3, -9), ("focus", 16, -11), ("tact", 16, -8), ("tact", 19, -8), ("thump", 24, -12),
          ("marker2", c1 + 4, -9), ("marker", c1 + 10, -9), ("impact2", 100, -9), ("thump", 108, -12), ("doom", 100, -16),
          ("swish2", 150, -10), ("typing", 153, -7), ("impact", 300, -9), ("cut_long", 300, -10), ("flash", c5, -10), ("glitch2", c5 + 20, -12)]:
    L.sfx(*s)
L.build()
