"""Per-frame head geometry from the person matte. Usage: heads.py alpha.mkv heads.json"""
import json, subprocess, sys
import numpy as np
W, H = 1080, 1920
p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", sys.argv[1], "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
out, n = [], 0
while True:
    b = p.stdout.read(W * H)
    if len(b) < W * H: break
    m = np.frombuffer(b, np.uint8).reshape(H, W) > 128
    rows = np.where(m.sum(1) > 6)[0]
    if not len(rows): out.append(None)
    else:
        top = int(rows[0]); r = {"top": top, "bottom": int(rows[-1])}
        for d in (40, 120, 240):
            xs = np.where(m[min(top + d, H - 1)])[0]
            r[f"x{d}"] = [int(xs[0]), int(xs[-1])] if len(xs) else None
        out.append(r)
    n += 1
json.dump(out, open(sys.argv[2], "w"))
for f in range(0, n, 6): print(f, round(f / 30, 2), out[f])
