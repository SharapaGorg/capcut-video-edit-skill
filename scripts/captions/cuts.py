"""Hard cuts of a render by frame difference. Usage: cuts.py base.mp4 cuts.json
Writes {"cuts": [frame, ...], "n": frames}. Slides / dissolves are not hard cuts: look at the contact sheet and add them by hand in layout.py."""
import json, subprocess, sys
import numpy as np
src, out = sys.argv[1:3]
w, h = 108, 192
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
fr = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)
d = np.abs(fr[1:] - fr[:-1]).mean((1, 2))
cuts = []
for i, v in enumerate(d):
    around = np.median(d[max(0, i - 6):i + 7])
    if v > 12 and v > 4 * around + 2:
        cuts.append(i + 1)
json.dump(dict(cuts=cuts, n=len(fr)), open(out, "w"))
print("frames", len(fr), "cuts", cuts, "diff", [round(float(d[c - 1]), 1) for c in cuts])
soft = [i + 1 for i, v in enumerate(d) if v > 6 and (i + 1) not in cuts]
if soft: print("strong motion (slide / dissolve? check by eye):", soft)
