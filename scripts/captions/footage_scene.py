"""Footage scenes: REAL frames of downloaded reels / clips + HTML motion graphics (Playwright, frame by frame) + glitch post (numpy).
Frames are ABSOLUTE frames of the reel (30 fps), same numbers as layout.py. Background = the frames of the rough render itself
(dark grid that slowly scrolls + glow), so a scene drops into the reel without a seam.

A scene script builds a Scene: elements with keyframes, footage (one source frame per reel frame), glitch events.
render() -> <scenes>/out/<name>/%04d.jpg (frames for layout.py: L.plate) + <scenes>/out/<name>.mp4 (silent scene, 1080x1920) + sheet.
Folders: <reel>/footage/<src>.mp4 (the reels), <reel>/auto/scenes/sceneN.py (one script per scene), base = the rough render.
A scene script:   sys.path.insert(0, <skill>/scripts/captions); from footage_scene import *; use(Path(__file__).parent)
Run:              python -X utf8 sceneN.py [--stills 260,300]      Guide: references/captions/techniques.md, «Сцены из реальных роликов».
Example: assets/examples/captions/reel6/scenes/ (reel 6 v6, approved 2026-11-18)."""
import io, json, math, random, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image

FONTS = Path(__file__).resolve().parent.parent.parent / "assets" / "captions" / "fonts"
P = {}


def use(scenes_dir, base="../out/rough_v1_end.mp4", footage="../../footage"):
    """where the reel lives: scenes_dir = <reel>/auto/scenes; base and footage relative to it"""
    d = Path(scenes_dir).resolve()
    P.update(base=(d / base).resolve(), footage=(d / footage).resolve(), cache=d / "cache", out=d / "out", work=d / "work")
W, H, FPS = 1080, 1920, 30
ORANGE, BG, WHITE = "#D4683F", "#0B0B0B", "#FFFFFF"

EASE = {
    "lin": lambda k: k,
    "out": lambda k: 1 - (1 - k) ** 3,
    "in": lambda k: k ** 3,
    "io": lambda k: 4 * k ** 3 if k < .5 else 1 - (-2 * k + 2) ** 3 / 2,
    "expo": lambda k: 1 if k >= 1 else 1 - 2 ** (-10 * k),
    "back": lambda k: 1 + 2.4 * (k - 1) ** 3 + 1.4 * (k - 1) ** 2,
    "step": lambda k: 0 if k < 1 else 1,
}


def interp(keys, f):
    """keys: [(frame, value[, ease of the segment that ENDS here])]; value = number or list"""
    if not isinstance(keys, list): return keys
    if f <= keys[0][0]: return keys[0][1]
    for a, b in zip(keys, keys[1:]):
        if f <= b[0]:
            e = EASE[b[2] if len(b) > 2 else "out"]((f - a[0]) / max(1e-9, b[0] - a[0]))
            if isinstance(a[1], (list, tuple)): return [x + (y - x) * e for x, y in zip(a[1], b[1])]
            return a[1] + (b[1] - a[1]) * e
    return keys[-1][1]


# ───── footage
def clip(src, t0, t1, n, tag=""):
    """n frames evenly covering source seconds t0..t1 (n / (t1-t0) = playback speed x 30), scaled to 1080x1920"""
    d = P["cache"] / f"{src}_{t0:.2f}_{t1:.2f}_{n}{tag}"
    if len(list(d.glob("*.jpg"))) < n:
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.jpg"): old.unlink()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0 + 0.4:.3f}", "-i", str(P["footage"] / f"{src}.mp4"),
                        "-vf", f"fps={n / (t1 - t0):.5f},scale={W}:{H}:flags=lanczos", "-frames:v", str(n), "-q:v", "2", str(d / "%04d.jpg")], check=True)
    fs = sorted(d.glob("*.jpg"))
    return [fs[min(i, len(fs) - 1)] for i in range(n)]


def base_frames(f0, f1):
    d = P["cache"] / f"base_{f0}_{f1}"
    if len(list(d.glob("*.jpg"))) != f1 - f0:
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(P["base"]), "-vf", f"select=between(n\\,{f0}\\,{f1 - 1})", "-vsync", "0",
                        "-q:v", "2", str(d / "%04d.jpg")], check=True)
    return sorted(d.glob("*.jpg"))


# ───── glitch post (2–5 frames each, on purpose only at key moments)
def _box(img, box):
    x0, y0, x1, y1 = box if box else (0, 0, img.shape[1], img.shape[0])
    return max(0, int(x0)), max(0, int(y0)), min(img.shape[1], int(x1)), min(img.shape[0], int(y1))


def g_rgb(img, rng, dx=12, dy=0, box=None):
    """RGB split: red one way, blue the other"""
    x0, y0, x1, y1 = _box(img, box); r = img[y0:y1, x0:x1].copy()
    out = img.copy()
    out[y0:y1, x0:x1, 0] = np.roll(np.roll(r[..., 0], dx, 1), dy, 0)
    out[y0:y1, x0:x1, 2] = np.roll(np.roll(r[..., 2], -dx, 1), -dy, 0)
    return out


def g_tear(img, rng, n=6, dx=60, hmin=6, hmax=70, box=None):
    """frame tearing: horizontal bands slide sideways"""
    x0, y0, x1, y1 = _box(img, box); out = img.copy()
    for _ in range(n):
        h = rng.randint(hmin, hmax); y = rng.randint(y0, max(y0, y1 - h)); s = rng.randint(-dx, dx)
        out[y:y + h, x0:x1] = np.roll(img[y:y + h, x0:x1], s, 1)
    return out


def g_disp(img, rng, n=10, dx=120, box=None):
    """digital displacement: blocks copied from shifted places, each block with its own channel offset"""
    x0, y0, x1, y1 = _box(img, box); out = img.copy()
    for _ in range(n):
        bw, bh = rng.randint(120, 700), rng.randint(16, 150)
        x, y = rng.randint(x0, max(x0, x1 - bw)), rng.randint(y0, max(y0, y1 - bh))
        sx, sy = x + rng.randint(-dx, dx), y + rng.randint(-dx // 3, dx // 3)
        sx, sy = min(max(0, sx), img.shape[1] - bw), min(max(0, sy), img.shape[0] - bh)
        blk = img[sy:sy + bh, sx:sx + bw].copy()
        c = rng.choice([0, 2]); blk[..., c] = np.roll(blk[..., c], rng.randint(6, 18), 1)
        out[y:y + bh, x:x + bw] = blk
    return out


GL = {"rgb": g_rgb, "tear": g_tear, "disp": g_disp}


# ───── scene
class Scene:
    def __init__(self, name, f0, f1):
        self.name, self.f0, self.f1 = name, f0, f1
        self.els, self.glitch, self.css = [], [], []

    def el(self, html="", box=(0, 0, W, H), fin=None, fout=None, k=None, src=None, text=None, parent=None, cls="", style="", origin="50% 50%"):
        """one layer. box = x, y, w, h (relative to the parent's box). k = {prop: keyframes}: x, y (px), s, sx, sy, r (deg), o,
        clip = [top, right, bottom, left] inset %, blur (px), br (brightness), sat. src = {frame: jpg} footage, text = {frame: html}."""
        e = dict(id=f"e{len(self.els)}", html=html, box=box, fin=self.f0 if fin is None else fin, fout=self.f1 if fout is None else fout,
                 k=k or {}, src=src, text=text, parent=parent, cls=cls, style=style, origin=origin)
        self.els.append(e)
        return e["id"]

    def footage(self, seq, f, box=(0, 0, W, H), parent=None, k=None, style="", fout=None, fit=None):
        """footage frames seq[0..] from reel frame f on (one source frame per reel frame). fit = css object-position etc."""
        src = {f + i: str(p) for i, p in enumerate(seq)}
        return self.el(f'<img style="position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover;{fit or ""}">', box,
                       fin=f, fout=fout if fout is not None else f + len(seq), src=src, parent=parent, k=k, style=style)

    def g(self, f, kind, seed=None, **kw):
        self.glitch.append((f, kind, seed if seed is not None else f * 7 + len(self.glitch), kw))

    # state of every element on frame f
    def _state(self, f):
        st = []
        for e in self.els:
            if not e["fin"] <= f < e["fout"]: continue
            v = {p: interp(kf, f) for p, kf in e["k"].items()}
            tf = (f"translate({v.get('x', 0):.2f}px,{v.get('y', 0):.2f}px) rotate({v.get('r', 0):.3f}deg) "
                  f"scale({v.get('s', 1) * v.get('sx', 1):.4f},{v.get('s', 1) * v.get('sy', 1):.4f})")
            fl = []
            if v.get("blur", 0) > .05: fl.append(f"blur({v['blur']:.2f}px)")
            if abs(v.get("br", 1) - 1) > .005: fl.append(f"brightness({v['br']:.3f})")
            if abs(v.get("sat", 1) - 1) > .005: fl.append(f"saturate({v['sat']:.3f})")
            cl = v.get("clip")
            cp = f"inset({cl[0]:.2f}% {cl[1]:.2f}% {cl[2]:.2f}% {cl[3]:.2f}% round {v.get('rad', 0):.0f}px)" if cl else ""
            src = None
            if e["src"]:
                src = e["src"].get(f) or e["src"][max(k_ for k_ in e["src"] if k_ <= f)] if any(k_ <= f for k_ in e["src"]) else None
                src = Path(src).as_uri() if src else None
            txt = e["text"].get(f) if e["text"] else None
            st.append([e["id"], tf, round(v.get("o", 1), 3), cp, " ".join(fl), src, txt])
        return st

    def html(self, bgs):
        kids = {}
        for e in self.els: kids.setdefault(e["parent"], []).append(e)

        def emit(p):
            out = []
            for e in kids.get(p, []):
                x, y, w, h = e["box"]
                out.append(f'<div id="{e["id"]}" class="L {e["cls"]}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;'
                           f'transform-origin:{e["origin"]};{e["style"]}">{e["html"]}{"".join(emit(e["id"]))}</div>')
            return out
        S = {f: self._state(f) for f in range(self.f0, self.f1)}
        B = {f: bgs[f - self.f0].as_uri() for f in range(self.f0, self.f1)}
        return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{{font-family:"Inter";src:url("{(FONTS / 'Inter.ttf').as_uri()}");font-weight:100 900}}
@font-face{{font-family:"JetBrains Mono";src:url("{(FONTS / 'JetBrainsMono.ttf').as_uri()}");font-weight:100 800}}
@font-face{{font-family:"Oswald";src:url("{(FONTS / 'Oswald.ttf').as_uri()}");font-weight:200 700}}
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:{BG}}}
#bg{{position:absolute;left:0;top:0;width:{W}px;height:{H}px}}
.L{{position:absolute;box-sizing:border-box}}
.t{{font-family:Inter;font-weight:900;color:#fff;letter-spacing:-.045em;line-height:.86;white-space:nowrap}}
.m{{font-family:"JetBrains Mono";font-weight:700;color:#fff;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap}}
.acc{{color:{ORANGE}}}
.card{{border-radius:36px;overflow:hidden;background:#111;box-shadow:0 30px 90px rgba(0,0,0,.7),0 0 0 2px rgba(255,255,255,.12)}}
.shade{{position:absolute;left:0;right:0;bottom:0;height:36%;background:linear-gradient(to top,rgba(0,0,0,.82),rgba(0,0,0,0))}}
.shadet{{position:absolute;left:0;right:0;top:0;height:40%;background:linear-gradient(to bottom,rgba(0,0,0,.7),rgba(0,0,0,0))}}
.chip{{display:flex;align-items:center;justify-content:center;border:3px solid rgba(255,255,255,.55);border-radius:999px;
  font-family:"JetBrains Mono";font-weight:700;letter-spacing:.1em;color:#fff;background:rgba(11,11,11,.72)}}
.chip.on{{border-color:{ORANGE};color:{ORANGE}}}
.views{{display:flex;align-items:center;gap:.28em;font-family:Inter;font-weight:900;color:#fff;letter-spacing:-.03em;white-space:nowrap;
  text-shadow:0 4px 18px rgba(0,0,0,.6)}}
.views svg{{width:.78em;height:.78em;flex:none}}
.corner{{position:absolute;width:56px;height:56px;border:0 solid {ORANGE}}}
{"".join(self.css)}
</style></head><body><img id="bg">{"".join(emit(None))}
<script>
const S={json.dumps(S)};const B={json.dumps(B)};
const ALL=[...document.querySelectorAll('.L')];
window.seek=async f=>{{
  const bg=document.getElementById('bg'); bg.src=B[f];
  for(const el of ALL) el.style.display='none';
  const imgs=[bg];
  for(const [id,tf,o,cp,fl,src,txt] of S[f]){{
    const el=document.getElementById(id); el.style.display='block';
    el.style.transform=tf; el.style.opacity=o; el.style.clipPath=cp; el.style.filter=fl;
    if(src){{const im=el.querySelector(':scope > img'); if(im.getAttribute('src')!==src) im.src=src; imgs.push(im);}}
    if(txt!==null) {{const t=el.querySelector('.tx'); if(t.innerHTML!==txt) t.innerHTML=txt;}}
  }}
  await Promise.all(imgs.map(i=>i.decode().catch(()=>0)));
  return 1;
}};
window.ready=document.fonts.ready.then(()=>Promise.all(['900 80px Inter','700 40px "JetBrains Mono"'].map(x=>document.fonts.load(x,'Жж19'))));
</script></body></html>"""

    def render(self, stills=None):
        from playwright.sync_api import sync_playwright
        bgs = base_frames(self.f0, self.f1)
        od = P["out"] / self.name; od.mkdir(parents=True, exist_ok=True)
        hp = P["work"] / f"{self.name}.html"; hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(self.html(bgs), encoding="utf8")
        frames = stills or list(range(self.f0, self.f1))
        enc = None
        if not stills:
            for old in od.glob("*.jpg"): old.unlink()
            enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                                    "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "15",
                                    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-movflags", "+faststart",
                                    str(P["out"] / f"{self.name}.mp4")], stdin=subprocess.PIPE)
        with sync_playwright() as p:
            br = p.chromium.launch()
            page = br.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            page.goto(hp.resolve().as_uri()); page.evaluate("window.ready")
            for f in frames:
                page.evaluate(f"seek({f})")
                img = np.asarray(Image.open(io.BytesIO(page.screenshot(type="png"))).convert("RGB"))
                for gf, kind, seed, kw in self.glitch:
                    if gf == f: img = GL[kind](img, random.Random(seed), **kw)
                if stills: Image.fromarray(img).save(od.parent / f"still_{self.name}_{f}.jpg", quality=90)
                else:
                    Image.fromarray(img).save(od / f"{f - self.f0:04d}.jpg", quality=94)
                    enc.stdin.write(np.ascontiguousarray(img).tobytes())
            br.close()
        if enc: enc.stdin.close(); enc.wait(); self.sheet()

    def sheet(self, every=3):
        fs = sorted((P["out"] / self.name).glob("*.jpg"))[::every]
        cols, tw, th = 9, 240, 427
        rows = math.ceil(len(fs) / cols)
        o = Image.new("RGB", (cols * tw, rows * th))
        for i, p in enumerate(fs):
            o.paste(Image.open(p).resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
        o.save(P["out"] / f"sheet_{self.name}.jpg", quality=85)


def views_html(size, txt_cls="tx"):
    play = '<svg viewBox="0 0 24 24"><path d="M7 4.5v15l12.5-7.5z" fill="none" stroke="#fff" stroke-width="2.6" stroke-linejoin="round"/></svg>'
    return f'<div class="views" style="font-size:{size}px">{play}<span class="{txt_cls}"></span></div>'


def ru(x, d):
    return f"{x:.{d}f}".replace(".", ",")


def main(build):
    sc = build()
    st = None
    if "--stills" in sys.argv: st = [int(v) for v in sys.argv[sys.argv.index("--stills") + 1].split(",")]
    sc.render(st)
    print("DONE", sc.name, "stills" if st else f"{sc.f1 - sc.f0} frames")
