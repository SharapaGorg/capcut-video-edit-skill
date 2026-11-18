"""Layout kit for the captions layer. A reel's `layout.py` builds a Layout out of these blocks; `build()` writes
gfx.html (two layers: back = behind the person, front = on top) and sfx_events.json into the work dir.
All times are FRAMES of the 30 fps base render. Catalogue with pictures of use: references/captions/techniques.md"""
import json, subprocess
from pathlib import Path
import numpy as np

HERE = Path(__file__).parent
FPS, W, H = 30, 1080, 1920
CREAM, ORANGE, INK = "#F5EFE4", "#E0703F", "#15120F"
RED = "#D5121B"


class Layout:
    def __init__(self, work):
        self.wd = Path(work)
        job = json.load(open(self.wd / "job.json", encoding="utf8"))
        self.base = job["base"]
        self.words = json.load(open(self.wd / "words_on.json", encoding="utf8"))
        self.heads = json.load(open(self.wd / "heads.json"))
        self.n = len(self.heads)                       # frames in the render
        self.cuts = json.load(open(self.wd / "cuts.json"))["cuts"]
        self.back, self.front, self.ev = [], [], []
        self.sil, self.FACE, self.EYES, self.SEAMY = [], {}, {}, {}
        self.rims, self.flashes = [], []
        self.plates = []                               # [f0, [jpg, ...]]: pre-rendered full frames (footage scenes)
        self.cream, self.orange, self.ink = CREAM, ORANGE, INK
        self._uid = 0
        self.music_rel = -16.0                         # music level under the voice, LU (−12 was «пиздец громкая», 2026-11-17)
        self.music_open = None                         # frame where the muffled music opens up (default: the first cut)

    # ───── words and time
    def F(self, i):
        """frame on which word i is spoken"""
        return round(self.words[i]["on"] * FPS)

    def find(self, text, start=0):
        """index of the first word (from `start`) that begins with `text` — refer to words by text, not by number"""
        t = text.lower()
        for i in range(start, len(self.words)):
            if self.words[i]["word"].lower().strip("«»\"'(").startswith(t):
                return i
        raise KeyError(f"word {text!r} not found from {start}: " + " ".join(f'{i}:{w["word"]}' for i, w in enumerate(self.words)))

    def ht(self, f0, f1):
        """median top of the head over frames [f0, f1)"""
        v = sorted(h["top"] for h in self.heads[f0:f1] if h)
        return v[len(v) // 2]

    def head(self, f0, f1):
        """median head geometry: top and the x-span 120 px below it (≈ widest part of the head)"""
        hs = [h for h in self.heads[f0:f1] if h and h.get("x120")]
        med = lambda v: sorted(v)[len(v) // 2]
        return dict(top=med([h["top"] for h in hs]), x0=med([h["x120"][0] for h in hs]), x1=med([h["x120"][1] for h in hs]))

    # ───── text
    def w(self, text, f, cls="", fx="word", out=None, style=""):
        """one word that lands on frame f. cls: sans | serif | acc | ink ; fx: word | pop | cut"""
        a = f' data-out="{out}"' if out is not None else ""
        return f'<span class="w a {cls}" data-in="{f}"{a} data-fx="{fx}" style="{style}">{text}</span>'

    def group(self, layer, y, f_out, lines, cls="sans", x=0, width=1080, style=""):
        """a centred block of lines (each line = html made of w()); every word hides at f_out. layer: self.front / self.back"""
        body = "".join(f'<div class="ln">{ln}</div>' for ln in lines).replace('data-fx=', f'data-out="{f_out}" data-fx=')
        layer.append(f'<div class="g {cls}" style="top:{y}px;left:{x}px;width:{width}px;{style}">{body}</div>')

    def big(self, layer, text, f, f_out, width, head_top=None, ratio=0.5, top=None, cx=540, cls="", clip=None, style=""):
        """Oswald capitals fitted to `width` px. Behind the head: layer=self.back, head_top=self.ht(f, f_out), ratio = part of the
        cap height that stays ABOVE the top of the head (0.5–0.56 wide shot; 0.6–0.75 lifts the word when the head eats a letter). On top: layer=self.front, top=y of the cap top.
        clip: css like "top:0;height:960px" when the camera occupies only a part of the frame."""
        pos = f'data-ht="{head_top}" data-r="{ratio}"' if top is None else f'data-top="{top}"'
        el = (f'<div class="big a fit {cls}" data-in="{f}" data-out="{f_out}" data-fx="pop" data-w="{width}" data-cx="{cx}" {pos} '
              f'style="{style}">{text}</div>')
        layer.append(f'<div class="clip" style="{clip}">{el}</div>' if clip else el)

    def struck(self, inner, f_strike, f_out):
        """wrap words html with a line that crosses them out at f_strike"""
        return f'<span class="strikebox">{inner}<i class="strike a" data-in="{f_strike}" data-out="{f_out}" data-fx="strike"></i></span>'

    def underline(self, f, f_out, y, x=150, width=780):
        self.front.append(f'<div class="uline a" data-in="{f}" data-out="{f_out}" data-fx="strike" style="top:{y}px;left:{x}px;width:{width}px"></div>')

    def bookmark(self, f, f_out):
        """inline bookmark icon (html, put it inside a line)"""
        return (f'<svg class="bm a" data-in="{f}" data-out="{f_out}" data-fx="pop" viewBox="0 0 60 80">'
                f'<path d="M6 4 H54 V76 L30 56 L6 76 Z" fill="{self.orange}" stroke="{self.orange}" stroke-width="6" stroke-linejoin="round"/></svg>')

    # ───── UI props
    def chip(self, y, f, f_on, f_out, words):
        """filter chip: appears at f, fills orange ("pressed") at f_on. words: [(text, frame), ...]"""
        ws = "".join(self.w(t, wf, "sans", out=f_out) for t, wf in words)
        self.front.append(f'<div class="g" style="top:{y}px"><div class="chip a" data-in="{f}" data-out="{f_out}" data-fx="chip" data-on="{f_on}">'
                          f'<span class="dot"></span>{ws}</div></div>')

    def scroll(self, y, f, f_out, word, lead="", size=176):
        """the word keeps scrolling up as a column with ghost copies («листаем»)"""
        lead = f'<span class="sans" style="font-size:72px;margin-right:.3em;vertical-align:.25em">{lead}</span>' if lead else ""
        self.front.append(f'<div class="g serif a" data-in="{f}" data-out="{f_out}" data-fx="scroll" style="top:{y}px;font-size:{size}px;line-height:1.05">'
                          f'<div class="gh">{word}</div><div>{lead}{word}</div><div class="gh">{word}</div></div>')

    def url(self, text, f, f_out, y, accent_from=None, dur=16, underline=True, size=142, bar=False):
        """address typed letter by letter over `dur` frames, with a cursor; letters from accent_from are orange.
        bar=True — on a dark pill like a browser address bar: use it over a light wall (cream letters are unreadable there);
        dur=1 — the whole address at once (end card)."""
        acc = len(text) if accent_from is None else accent_from
        chars = "".join(f'<span class="ch{" acc" if i >= acc else ""}">{c}</span>' for i, c in enumerate(text))
        self.front.append(f'<div class="g url{" bar" if bar else ""} a" data-in="{f}" data-out="{f_out}" data-fx="type" data-dur="{dur}" style="top:{y}px;font-size:{size}px">{chars}<i class="cur"></i></div>')
        if underline and not bar:
            self.underline(f + dur, f_out, y + round(size * 1.225))

    def ribbon(self, layer, f, f_out, d, dur=9, reverse=False):
        """orange ribbon drawn along svg path `d` (1080×1920 coordinates) over `dur` frames. Draw one half in self.back and the
        other in self.front so it wraps around the person."""
        self._uid += 1
        g = f"rg{self._uid}"
        stops = ["#F0925F", self.orange, "#B9532A"][::-1 if reverse else 1]
        layer.append(f'''<svg class="rib a" data-in="{f}" data-out="{f_out}" data-fx="draw" data-dur="{dur}" viewBox="0 0 1080 1920">
 <defs><linearGradient id="{g}" x1="{int(reverse)}" y1="0" x2="{int(not reverse)}" y2="1"><stop offset="0" stop-color="{stops[0]}"/><stop offset=".5" stop-color="{stops[1]}"/><stop offset="1" stop-color="{stops[2]}"/></linearGradient></defs>
 <path style="stroke:url(#{g})" d="{d}" /></svg>''')

    # ───── full-screen scenes (sections without camera: the base there is a dark grid, everything goes to self.front)
    def counter(self, y, f, f_out, to, dur=14, size=420, suffix=""):
        """big orange number that runs 0 → `to` over `dur` frames"""
        self.front.append(f'<div class="num a" data-in="{f}" data-out="{f_out}" data-fx="count" data-to="{to}" data-dur="{dur}" '
                          f'style="position:absolute;left:0;width:1080px;text-align:center;top:{y}px;font-size:{size}px"><span>0</span>{suffix}</div>')

    def dots(self, y, f, f_out, n=100, cols=10, per=6, size=58, gap=18, hot_at=None, hot_every=3, x=None):
        """grid of n dots that fills `per` dots a frame («100 аккаунтов»); from hot_at every hot_every-th dot is orange"""
        wpx = cols * size + (cols - 1) * gap
        x = (1080 - wpx) // 2 if x is None else x
        hot = f' data-hot="{hot_at}"' if hot_at is not None else ""
        self.front.append(f'<div class="dots a" data-in="{f}" data-out="{f_out}" data-fx="dots" data-per="{per}" data-every="{hot_every}"{hot} '
                          f'style="left:{x}px;top:{y}px;grid-template-columns:repeat({cols},{size}px);gap:{gap}px">' + f'<i style="width:{size}px;height:{size}px"></i>' * n + '</div>')

    def tiles(self, labels, f, f_out, pick=None, f_hot=None, f_dead=None):
        """row of small tiles (days of the week, hours…) — html for a line. Tile `pick` turns orange at f_hot; all fade at f_dead
        (wrap into L.struck to cross the row out)"""
        a = (f' data-pick="{pick}" data-hot="{f_hot}"' if pick is not None else "") + (f' data-dead="{f_dead}"' if f_dead is not None else "")
        return f'<span class="tiles a" data-in="{f}" data-out="{f_out}" data-fx="tiles"{a}>' + "".join(f'<span class="tile">{t}</span>' for t in labels) + '</span>'

    def chart(self, f, f_out, pts, dur=18, x=110, y=760, width=860, height=420, axis=True):
        """line chart drawn over `dur` frames. pts: [(x 0..1, y 0..1), ...] (y up). Returns pixel coordinates of the points —
        put labels at the spikes with them."""
        px = [(round(x + a * width), round(y + height - b * height)) for a, b in pts]
        d = "M " + " L ".join(f"{a} {b}" for a, b in px)
        ax = f'<path class="axis" d="M {x} {y + height + 26} H {x + width}"/>' if axis else ""
        self.front.append(f'<svg class="line a" data-in="{f}" data-out="{f_out}" data-fx="draw" data-dur="{dur}" viewBox="0 0 1080 1920">{ax}<path class="d" d="{d}"/></svg>')
        return px

    def clock(self, y, f, f_out, size=300, speed=30, x=None):
        """clock face with a spinning hand («время»)"""
        x = (1080 - size) // 2 if x is None else x
        c = self.cream
        self.front.append(f'<svg class="clock a" data-in="{f}" data-out="{f_out}" data-fx="clock" data-speed="{speed}" viewBox="0 0 200 200" '
                          f'style="left:{x}px;top:{y}px;width:{size}px;height:{size}px">'
                          f'<circle cx="100" cy="100" r="90" fill="none" stroke="{c}" stroke-width="9"/>'
                          f'<line class="hand2" x1="100" y1="100" x2="100" y2="58" stroke="{c}" stroke-width="10" stroke-linecap="round"/>'
                          f'<line class="hand" x1="100" y1="100" x2="100" y2="30" stroke="{self.orange}" stroke-width="8" stroke-linecap="round"/>'
                          f'<circle cx="100" cy="100" r="9" fill="{self.orange}"/></svg>')

    def arrow(self, f, f_out, size=120, down=True):
        """nodding arrow (html for a line): «в описании ↓», «ссылка тут ↓»"""
        rot = "" if down else ' transform="rotate(180 30 40)"'
        return (f'<svg class="arrow a" data-in="{f}" data-out="{f_out}" data-fx="bob" viewBox="0 0 60 80" style="width:{size * .75:.0f}px;height:{size}px">'
                f'<path{rot} d="M30 6 V66 M8 44 L30 70 L52 44" fill="none" stroke="{self.orange}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/></svg>')

    # ───── editorial set (reference 2, «красный монтаж»): free-placed words, colour walls, glow cards, doodles, handwriting
    def theme(self, name):
        """accent colour of the whole reel: "orange" (default, the brand) | "red" (reference 2) | "violet" | "blue" | any "#RRGGBB"
        (take it from the footage: the colour of the interface or the light in the frame, so the accent belongs to the picture)"""
        self.orange = {"orange": ORANGE, "red": RED, "violet": "#8B5CF6", "blue": "#3B82F6"}.get(name, name)

    def at(self, layer, html, x, y, f_out=None, cls="", rot=0, ry=0, align="left", style=""):
        """free-placed line: html made of w() (give every word its font-size in style). (x, y) — left top corner; align "center" /
        "right" — x is the centre / the right edge. rot — tilt in degrees, ry — turn in perspective (words on a wall or a screen)."""
        tx = {"left": "0", "center": "-50%", "right": "-100%"}[align]
        org = {"left": "0 50%", "center": "50% 50%", "right": "100% 50%"}[align]
        if f_out is not None:
            html = html.replace('data-fx=', f'data-out="{f_out}" data-fx=')
        tf = f"translateX({tx})" + (f" perspective(1100px) rotateY({ry}deg)" if ry else "") + (f" rotate({rot}deg)" if rot else "")
        layer.append(f'<div class="at {cls}" style="left:{x}px;top:{y}px;transform:{tf};transform-origin:{org};{style}">{html}</div>')

    def stairs(self, layer, words, x, y, f_out, size=84, grow=1.0, dx=46, accent=(), cls="sans", align="left"):
        """words step down a diagonal, one word a line: [(text, frame), ...]. dx — shift of every next word (negative — to the left),
        grow — every next word this many times bigger (1.25: «and I'll send it to YOU.»), accent — indexes in the accent colour"""
        s, cy = size, y
        for i, (t, f) in enumerate(words):
            self.at(layer, self.w(t, f, cls + (" acc" if i in accent else ""), style=f"font-size:{s:.0f}px;margin:0"), x + i * dx, round(cy), f_out, align=align)
            cy += s * 0.96
            s *= grow

    def fill(self, layer, f, f_out, color, halo=None):
        """flat colour over the whole frame. In self.back: the room is replaced and the person stays (cut-out on a colour); together
        with L.silhouette — a black figure on this colour. halo=(cx, cy, r, color): a glowing disc behind the head.
        In self.front: a card over everything (put its text after it)."""
        h = ""
        if halo:
            cx, cy, r, c = halo
            h = f'<i class="halo" style="left:{cx - r}px;top:{cy - r}px;width:{2 * r}px;height:{2 * r}px;background:radial-gradient(circle,{c} 0,{c} 58%,transparent 72%)"></i>'
        el = f'<div class="fill a" data-in="{f}" data-out="{f_out}" data-fx="cut" style="background:{color}">{h}</div>'
        layer.insert(0, el) if layer is self.back else layer.append(el)

    def wall(self, lines, f, f_out, bg=None, color=None, top=380, height=1100, pad=36):
        """the room turns into a colour wall with a word in tall condensed capitals from edge to edge; the person (or the object the
        matte keeps) stays in front. lines: ["WORK", "FLOW"] — every line is stretched to the full width, together they take `height`."""
        bg, color = bg or self.orange, color or self.cream
        lh = height / len(lines)
        body = "".join(f'<span class="wl" data-w="{W - 2 * pad}" data-h="{lh * .9:.0f}" data-x="{pad}" data-y="{top + i * lh:.0f}">{t}</span>' for i, t in enumerate(lines))
        self.back.insert(0, f'<div class="fill wall a" data-in="{f}" data-out="{f_out}" data-fx="wall" style="background:{bg};color:{color}">{body}</div>')

    def glowcard(self, f, f_out, lines, width=940, bg="#060606", color=None):
        """black card with glowing condensed capitals that build word by word («AND IT'S / INSANE»). lines: [[(text, frame), ...], ...];
        every line is fitted to `width`. One card a reel, 0.8–1.2 s, on the punch line."""
        color = color or self.orange
        body = "".join('<div class="fitw gl" data-w="%d">%s</div>' % (width, "".join(
            f'<span class="w a" data-in="{wf}" data-out="{f_out}" data-fx="pop" style="margin:0 .08em">{t}</span>' for t, wf in ln)) for ln in lines)
        self.front.append(f'<div class="fill card a" data-in="{f}" data-out="{f_out}" data-fx="cut" style="background:{bg};color:{color};'
                          f'text-shadow:0 0 14px {color},0 0 46px {color},0 0 120px {color}">{body}</div>')

    def scribble(self, layer, kind, f, f_out, box, color=None, width=9, dur=8, seed=1, boil=True):
        """hand-drawn mark that draws itself over `dur` frames and keeps «boiling». kind: "circle" (box = x, y, w, h — around a face or
        a thing), "box" (rough frame), "underline" (box = x, y, w, wave height), "arrow" (box = x0, y0, x1, y1 — from, to), "cross"."""
        import math, random
        r = random.Random(seed)
        j = lambda v, a: v + r.uniform(-a, a)
        if kind == "circle":
            x, y, w_, h = box; cx, cy = x + w_ / 2, y + h / 2
            a0 = r.uniform(0, 6.28)
            pts = [(cx + math.cos(a0 + t / 60 * 6.283) * w_ / 2 * (1 + .07 * math.sin(t / 27) + r.uniform(-.006, .006)),     # 1.8 turns, 6° a step
                    cy + math.sin(a0 + t / 60 * 6.283) * h / 2 * (1 + .07 * math.cos(t / 21) + r.uniform(-.006, .006))) for t in range(0, 108)]
        elif kind == "box":
            x, y, w_, h = box; c = [(x, y), (x + w_, y), (x + w_, y + h), (x, y + h)]; a = min(w_, h) * .035; pts = []
            for k in range(9):                              # two passes and a bit: the lines overshoot the corners
                px, py = c[k % 4]; qx, qy = c[(k + 1) % 4]; ex, ey = (qx - px) * .06, (qy - py) * .06
                pts += [(j(px - ex, a), j(py - ey, a)), (j(qx + ex, a), j(qy + ey, a))]
        elif kind == "underline":
            x, y, w_, h = box
            pts = [(x + w_ * t / 12, y + (h if t % 2 else -h) * .5 + r.uniform(-3, 3)) for t in range(13)] + [(x + w_ * t / 6 + 20, y + h * 1.6 + r.uniform(-4, 4)) for t in range(6, -1, -1)]
        elif kind == "cross":
            x, y, w_, h = box
            pts = [(j(x, 8), j(y, 8)), (j(x + w_, 8), j(y + h, 8)), (j(x + w_ * .5, 8), j(y + h * .5, 8)), (j(x + w_, 8), j(y, 8)), (j(x, 8), j(y + h, 8))]
        elif kind == "arrow":
            x0, y0, x1, y1 = box; dx, dy = x1 - x0, y1 - y0; ln = math.hypot(dx, dy); nx, ny = -dy / ln, dx / ln; bulge = ln * .18
            pts = [(x0 + dx * t / 10 + nx * bulge * math.sin(t / 10 * math.pi) + r.uniform(-3, 3), y0 + dy * t / 10 + ny * bulge * math.sin(t / 10 * math.pi) + r.uniform(-3, 3)) for t in range(11)]
            ax, ay = pts[-1][0] - pts[-3][0], pts[-1][1] - pts[-3][1]; al = math.hypot(ax, ay); ax, ay = ax / al, ay / al; hl = min(90, ln * .28)
            barb = lambda s: (x1 - ax * hl + s * -ay * hl * .55, y1 - ay * hl + s * ax * hl * .55)
            pts += [barb(1), (x1, y1), barb(-1)]
        else:
            raise ValueError(kind)
        d = "M " + " L ".join(f"{a:.0f} {b:.0f}" for a, b in pts)
        layer.append(f'<svg class="doodle a" data-in="{f}" data-out="{f_out}" data-fx="draw" data-dur="{dur}" viewBox="0 0 1080 1920">'
                     f'<path class="d{" boil" if boil else ""}" style="stroke:{color or self.orange};stroke-width:{width}" d="{d}"/></svg>')

    def hand(self, layer, text, f, f_out, x, y, size=170, color=None, rot=-5, dur=7, align="left"):
        """handwritten marker text (Caveat) written letter by letter over `dur` frames; "\\n" — next line. For the word the speaker
        stresses as personal («your style», «мой», «сам») or a note next to a scribble; not for regular captions."""
        tx = {"left": "0", "center": "-50%", "right": "-100%"}[align]
        body = "".join('<div>' + "".join(f'<span class="ch">{c if c != " " else "&nbsp;"}</span>' for c in ln) + '</div>' for ln in text.split("\n"))
        layer.append(f'<div class="hand boil a" data-in="{f}" data-out="{f_out}" data-fx="write" data-dur="{dur}" '
                     f'style="left:{x}px;top:{y}px;font-size:{size}px;color:{color or self.orange};text-align:{align};transform:translateX({tx}) rotate({rot}deg)">{body}</div>')

    def blocks(self, f, f_out, n=7, seed=1, layer=None):
        """small black / white / accent rectangles that flicker for a few frames (glitch on the very first frames or on a hard cut)"""
        import random
        r = random.Random(seed); cols = ["#000", "#000", "#fff", self.orange]
        body = "".join(f'<i style="left:{r.randint(40, 900)}px;top:{r.randint(200, 1500)}px;width:{r.choice([60, 120, 220, 380])}px;height:{r.choice([24, 40, 70, 110])}px;background:{r.choice(cols)}"></i>' for _ in range(n))
        (self.front if layer is None else layer).append(f'<div class="blocks a" data-in="{f}" data-out="{f_out}" data-fx="blocks">{body}</div>')

    def meta(self, f, f_out, tl="", tr="", bl="", br=""):
        """tiny corner labels that stay for the whole reel or a chapter («ITERATION 001», the thesis in two lines); "\\n" — line break"""
        for pos, t in (("tl", tl), ("tr", tr), ("bl", bl), ("br", br)):
            if t:
                self.front.append(f'<div class="meta {pos} a" data-in="{f}" data-out="{f_out}" data-fx="cut">{t.replace(chr(10), "<br>")}</div>')

    def prompt(self, text, f, f_out, y=1250, dur=30, mode="Chat", model="AI", width=960):
        """glass chat-input bar with a prompt typed over `dur` frames — «пишу промт», «спросил у нейросети», «сказал ИИ».
        Sections without a face or the lower part of a wide shot; it must not cover hands or the screen the person points at."""
        chars = "".join(f'<span class="ch">{c}</span>' if c != " " else " " for c in text)
        self.front.append(f'<div class="prompt a" data-in="{f}" data-out="{f_out}" data-fx="prompt" data-dur="{dur}" style="top:{y}px;left:{(W - width) // 2}px;width:{width}px">'
                          f'<div class="pt">{chars}<i class="cur"></i></div><div class="pb"><b>+</b><span class="chipm">{mode}</span><span class="sp"></span><span class="mdl">{model}</span>'
                          '<span class="bars"><i></i><i></i><i></i><i></i></span></div></div>')

    def rim(self, f, f_out, color=None, width=7):
        """outline around the person (matte edge) in the accent colour — the speaker is «selected» like an object: on the product
        name or the offer. Wide and medium shots; needs a clean matte (look at a still)."""
        c = (color or self.orange).lstrip("#")
        self.rims.append([f, f_out, [int(c[i:i + 2], 16) for i in (0, 2, 4)], width])

    def plate(self, f, files):
        """pre-rendered FULL frames (a footage scene made outside the kit, already drawn over this base) from frame f on, one jpg per frame.
        compose takes them as the picture of those frames instead of room + person + back layer; the front layer still goes on top.
        Not <img> in the html: hundreds of 1080x1920 images make Chromium time out on load / screenshot."""
        self.plates.append([f, [str(p) for p in files]])

    def flash(self, f, n=2, kind="invert"):
        """the whole frame flashes for n frames on a hard cut: "invert" (negative), "white", "duo" (two-tone poster in the accent colour)"""
        c = self.orange.lstrip("#")
        self.flashes.append([f, f + n, kind, [int(c[i:i + 2], 16) for i in (0, 2, 4)]])

    # ───── tracking: face HUD, silhouette, eyes
    def track(self, f0, f1):
        """face boxes and eye centres for frames [f0, f1) of the base (Haar, smoothed); cached in the work dir"""
        cache = self.wd / f"track_{f0}_{f1}.json"
        if cache.exists():
            d = json.load(open(cache))
        else:
            import cv2
            fc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            ec = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
            cap = cv2.VideoCapture(self.base); cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
            faces, eyes, hit = [], [], 0
            for f in range(f0, f1):
                ok, img = cap.read()
                g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY); box = eye = None
                fs = fc.detectMultiScale(cv2.resize(g, (540, 960)), 1.1, 5, minSize=(80, 80))
                if len(fs):
                    x, y, w_, h = [int(v) * 2 for v in max(fs, key=lambda r: r[2] * r[3])]
                    box = [x, y, w_, h]
                    es = sorted(ec.detectMultiScale(g[y:y + h * 6 // 10, x:x + w_], 1.1, 6, minSize=(w_ // 10, w_ // 10)), key=lambda r: -r[2])[:2]
                    if len(es) == 2:
                        a, b = sorted(es, key=lambda r: r[0])
                        if b[0] - a[0] > w_ * .2:
                            eye = [x + a[0] + a[2] / 2, y + a[1] + a[3] / 2, x + b[0] + b[2] / 2, y + b[1] + b[3] / 2]; hit += 1
                    if eye is None:
                        eye = [x + .31 * w_, y + .42 * h, x + .69 * w_, y + .42 * h]
                faces.append(box); eyes.append(eye)
            if not any(faces):
                raise RuntimeError(f"no face found in frames {f0}-{f1}: HUD / eyes need a frontal face")
            def smooth(rows, k):
                last = next(r for r in rows if r); sm, res = None, {}
                for i, r in enumerate(rows):
                    last = r or last; v = np.array(last, float)
                    sm = v if sm is None else sm * (1 - k) + v * k
                    res[str(f0 + i)] = [round(float(z), 1) for z in sm]
                return res
            d = dict(face=smooth(faces, .4), eyes=smooth(eyes, .5), found=sum(b is not None for b in faces), eyes_found=hit, frames=f1 - f0)
            json.dump(d, open(cache, "w"))
        print(f"track {f0}-{f1}: face on {d['found']}/{d['frames']} frames, both eyes on {d['eyes_found']}")
        self.FACE.update(d["face"]); self.EYES.update(d["eyes"])

    def hud(self, f, f_out, label="", track_to=None):
        """face-tracking brackets with crosses on the eyes and a mono read-out; `label` goes on an orange tag"""
        self.track(f, track_to or f_out)
        tag = f"<br><em>{label}</em>" if label else ""
        self.front.append(f'<div class="hud a" data-in="{f}" data-out="{f_out}" data-fx="hud">'
                          '<i class="c tl"></i><i class="c tr"></i><i class="c bl"></i><i class="c br"></i>'
                          '<b class="e e1">+</b><b class="e e2">+</b>'
                          f'<div class="lab"><span class="h1"></span><br><span class="h2"></span>{tag}</div></div>')

    def silhouette(self, f, f_out, fill_y=None):
        """the room turns cream and the person black for frames [f, f_out). fill_y: below this y everything between the outer
        edges of the body is filled (use when a mic / prop in front of the chest would show as a hole)."""
        self.sil.append([f, f_out, fill_y])

    def eyes(self, f, f_out, blink=11, devil=False):
        """glowing orange eyes on the silhouette (the user's must-have for every silhouette with a frontal face).
        devil=True — red-hot, bigger, slanted and flickering (use together with L.devil)"""
        self.track(f, f_out)
        dv, cls = (' data-devil="1"', "eye evil") if devil else ("", "eye")
        self.front.append(f'<div class="a" data-in="{f}" data-out="{f_out}" data-fx="eyes" data-blink="{blink}"{dv}><i class="{cls}"></i><i class="{cls}"></i></div>')

    def devil(self, f, f_out, size=1.0, tail=None, glow=True):
        """devil mode for a silhouette (the user finds it hilarious on a celebrity name / a «villain» of the story): horns grow out of
        the head and follow it, a red vignette pulses behind, an optional tail sways. tail=(x, y, scale): the point on the body where
        the tail starts (pick on a still, e.g. the hip), scale 1 = 300 px long. Use with L.silhouette + L.eyes(devil=True)."""
        self.track(f, f_out)
        if glow:
            self.back.insert(0, f'<div class="hell a" data-in="{f}" data-out="{f_out}" data-fx="hell"></div>')
        horn = "M -70 -95 C -150 -150, -205 -250, -168 -345 C -150 -285, -105 -240, -20 -170 Z"     # the base sinks into the head
        t = ""
        if tail:
            t = (f' data-tx="{tail[0]}" data-ty="{tail[1]}" data-ts="{tail[2]}"',
                 f'<g class="tail"><path style="fill:none;stroke:{self.ink};stroke-width:24;stroke-linecap:round" d="M 0 0 C 120 40, 250 0, 250 -130 C 250 -190, 230 -230, 215 -262"/>'
                 '<path d="M 160 -252 L 264 -240 L 198 -352 Z"/></g>')
        ds = sorted(((e[2] - e[0]) ** 2 + (e[3] - e[1]) ** 2) ** .5 for k, e in self.EYES.items() if f <= int(k) < f_out)
        dist = ds[len(ds) // 2]                         # one size for the whole beat: the eye distance jitters on small faces
        self.front.append(f'<svg class="devil a" data-in="{f}" data-out="{f_out}" data-fx="devil" data-size="{size}" data-dist="{dist:.1f}"{t[0] if t else ""} viewBox="0 0 1080 1920">'
                          f'<g class="horns"><path d="{horn}"/><path transform="scale(-1 1)" d="{horn}"/></g>{t[1] if t else ""}</svg>')

    def ride_edge(self, f0, n, y, rest, html, f_out, x=1000, cls="sans seam"):
        """a caption that rides the moving edge of a sliding split (camera slides in from the top and stops at y=`rest`)"""
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", self.base, "-vf", r"select=between(n\,%d\,%d),crop=60:1920:%d:0" % (f0, f0 + n - 1, x),
                              "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
        strips = np.frombuffer(raw, np.uint8).reshape(-1, 1920, 60).mean(2)
        e = {}
        for i, col in enumerate(strips):
            bright = np.where(col[:rest + 40] > 60)[0]
            e[f0 + i] = int(bright[-1]) + 1 if len(bright) else 0
        ks = sorted(e)
        for i in range(len(ks) - 1):                   # glow gives stray rows: keep the edge moving one way
            if e[ks[i]] > e[ks[i + 1]]:
                e[ks[i]] = (e[ks[i - 1]] + e[ks[i + 1]]) // 2 if i else 0
        self.SEAMY.update({str(k): v for k, v in e.items()})
        self.front.append(f'<div class="g {cls} a" data-in="{f0}" data-out="{f_out}" data-fx="seam" data-y="{y}" data-rest="{rest}" style="top:{y}px">'
                          f'<div class="ln">{html}</div></div>')

    # ───── sound
    def sfx(self, name, f, db):
        """sound `name` (see audio.py / references/sound.md) with its hit on frame f, peak `db` dBFS"""
        self.ev.append((name, f, db))

    def build(self):
        html = (HERE / "template.html").read_text(encoding="utf8")
        data = f"const FACE={json.dumps(self.FACE)};const EYES={json.dumps(self.EYES)};const SIL={json.dumps(self.sil)};const SEAMY={json.dumps(self.SEAMY)};const RIM={json.dumps(self.rims)};const FLASH={json.dumps(self.flashes)};const PLATE={json.dumps(self.plates)};"
        html = (html.replace("/*FONTS*/", (HERE.parent.parent / "assets" / "captions" / "fonts").as_uri())
                .replace("<!--BACK-->", "\n".join(self.back)).replace("<!--FRONT-->", "\n".join(self.front))
                .replace("/*DATA*/", data).replace("224,112,63", ",".join(str(int(self.orange[i:i + 2], 16)) for i in (1, 3, 5)))     # glows follow the accent
                .replace("CREAM", self.cream).replace("ORANGE", self.orange).replace("INK", self.ink))
        (self.wd / "gfx.html").write_text(html, encoding="utf8")
        mo = self.music_open if self.music_open is not None else (self.cuts[0] if self.cuts else 0)
        json.dump(dict(music_open=round(mo / FPS, 4), music_rel=self.music_rel, sil=self.sil, events=[[k, round(f / FPS, 4), db] for k, f, db in self.ev]), open(self.wd / "sfx_events.json", "w"))
        print(f"gfx.html ok; {len(self.ev)} sounds; silhouettes {self.sil}")
