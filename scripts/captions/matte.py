"""Person alpha matte for a video with RVM (ONNX). Usage: matte.py in.mp4 out_alpha.mkv rvm.onnx cut1,cut2,...
Recurrent state resets at each cut (seconds) so the matte doesn't smear across hard cuts."""
import subprocess, sys, time
import numpy as np, onnxruntime as ort

src, dst, model, cuts = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
W, H, FPS = 1080, 1920, 30
cut_frames = {round(float(c) * FPS) for c in cuts.split(",") if c}

sess = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS),
                        "-i", "-", "-c:v", "ffv1", dst], stdin=subprocess.PIPE)

def zero_state():
    return [np.zeros((1, 1, 1, 1), np.float32)] * 4

rec = zero_state()
ds = np.array([0.25], np.float32)
n, t0 = 0, time.time()
while True:
    buf = dec.stdout.read(W * H * 3)
    if len(buf) < W * H * 3:
        break
    if n in cut_frames:
        rec = zero_state()
    img = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
    if img.max() < 8:  # black frame (section without camera)
        pha = np.zeros((H, W), np.uint8)
        rec = zero_state()
    else:
        x = (img.astype(np.float32) / 255).transpose(2, 0, 1)[None]
        fgr, p, *rec = sess.run(None, {"src": x, "r1i": rec[0], "r2i": rec[1], "r3i": rec[2], "r4i": rec[3], "downsample_ratio": ds})
        pha = (np.clip(p[0, 0], 0, 1) * 255).astype(np.uint8)
    enc.stdin.write(pha.tobytes())
    n += 1
    if n % 30 == 0:
        print(f"{n} frames {time.time()-t0:.0f}s", flush=True)
enc.stdin.close(); enc.wait(); dec.wait()
print("DONE", n)
