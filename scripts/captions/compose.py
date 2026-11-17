"""Stack per frame: room -> words behind -> person (matte) -> words in front.
Usage: compose.py base.mp4 alpha.mkv gfx.html out.mp4 [--stills f1,f2,... dir] [--audio a.m4a]
Silhouette beats (SIL in the html): the room turns cream, the person turns black.
Also writes <out>.check.json: how much of the behind-text the person hides, and the text bounding box per frame."""
import io, json, subprocess, sys, time
from pathlib import Path
import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

base, alpha_f, html, out = sys.argv[1:5]
stills = audio = None
if "--stills" in sys.argv:
    i = sys.argv.index("--stills"); stills = [int(x) for x in sys.argv[i + 1].split(",")]; sdir = Path(sys.argv[i + 2]); sdir.mkdir(parents=True, exist_ok=True)
if "--audio" in sys.argv:
    audio = sys.argv[sys.argv.index("--audio") + 1]
W, H, FPS = 1080, 1920, 30
CREAM = np.array([0xED, 0xE6, 0xD8], np.float32)
INK = np.array([0x15, 0x12, 0x0F], np.float32)

def reader(path, pix, ch, start=None):
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{start:.4f}"] if start is not None else []) + ["-i", path, "-f", "rawvideo", "-pix_fmt", pix, "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE), W * H * ch

def one(path, pix, ch, f):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"select=eq(n\\,{f})", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", pix, "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, ch) if ch > 1 else np.frombuffer(raw, np.uint8).reshape(H, W)

def over(dst, rgba):
    a = rgba[..., 3:4].astype(np.float32) / 255
    return rgba[..., :3].astype(np.float32) * a + dst * (1 - a)

with sync_playwright() as p:
    br = p.chromium.launch()
    page = br.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    page.goto(Path(html).resolve().as_uri())
    page.evaluate("window.ready")
    sil = page.evaluate("SIL")          # [[from, to, fill_y or null], ...]
    print("BIG", json.dumps(page.evaluate("BIG"), ensure_ascii=False))

    boxes = {}

    def shot(f, layer):
        if page.evaluate(f"seek({f},'{layer}')") == 0:
            return None
        return np.asarray(Image.open(io.BytesIO(page.screenshot(omit_background=True, type="png"))).convert("RGBA"))

    def frame(f, B, A):
        s = next((x for x in sil if x[0] <= f < x[1]), None)
        back, front = shot(f, "back"), shot(f, "front")
        o = B.astype(np.float32)
        cov = None
        if back is not None or s:
            pa = A.astype(np.float32)[..., None] / 255
            person = o
            if s:
                # silhouette: everything under the head/shoulder outline is the person (the mic in front must not show through)
                fill_y = s[2] if s[2] is not None else H
                m = pa[fill_y:, :, 0] > 0.6
                l = np.maximum.accumulate(m, axis=1) & np.maximum.accumulate(m[:, ::-1], axis=1)[:, ::-1]   # between the outer edges
                pa = pa.copy(); pa[fill_y:, :, 0] = np.maximum(pa[fill_y:, :, 0], l.astype(np.float32))
                person = np.broadcast_to(INK, o.shape); o = np.broadcast_to(CREAM, o.shape).copy()
            if back is not None:
                ba = back[..., 3].astype(np.float32) / 255
                cov = float((ba * pa[..., 0]).sum() / max(1.0, ba.sum()))
                o = over(o, back)
            o = o * (1 - pa) + person * pa
        for lay in (back, front):                      # text bounding box per frame, for the safe-zone check
            if lay is not None:
                ys, xs = np.where(lay[..., 3] > 40)
                if len(ys): boxes[f] = [min(boxes.get(f, [9999] * 4)[0], int(xs.min())), min(boxes.get(f, [9999] * 4)[1], int(ys.min())),
                                        max(boxes.get(f, [0] * 4)[2], int(xs.max())), max(boxes.get(f, [0] * 4)[3], int(ys.max()))]
        if front is not None:
            o = over(o, front)
        return np.clip(o + 0.5, 0, 255).astype(np.uint8), cov

    if stills:
        for f in stills:
            img, cov = frame(f, one(base, "rgb24", 3, f), one(alpha_f, "gray", 1, f))
            Image.fromarray(img).save(sdir / f"f{f:04d}.png")
            print(f, "cover", None if cov is None else round(cov, 3))
    else:
        rb, nb = reader(base, "rgb24", 3); ra, na = reader(alpha_f, "gray", 1)
        enc = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
        if audio: enc += ["-i", audio, "-map", "0:v", "-map", "1:a", "-c:a", "copy", "-shortest"]
        enc += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", out]
        ep = subprocess.Popen(enc, stdin=subprocess.PIPE)
        f, t0, covs = 0, time.time(), {}
        while True:
            b = rb.stdout.read(nb); a = ra.stdout.read(na)
            if len(b) < nb or len(a) < na: break
            img, cov = frame(f, np.frombuffer(b, np.uint8).reshape(H, W, 3), np.frombuffer(a, np.uint8).reshape(H, W))
            if cov is not None: covs[f] = round(cov, 3)
            ep.stdin.write(img.tobytes()); f += 1
            if f % 30 == 0: print(f, f"{time.time() - t0:.0f}s", flush=True)
        ep.stdin.close(); ep.wait(); rb.kill(); ra.kill()
        json.dump(dict(cover=covs, boxes=boxes), open(Path(out).with_suffix(".check.json"), "w"))
        print("DONE", f, "frames")
    br.close()
