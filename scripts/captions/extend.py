"""Append a silent tail to a render for an end card (the address stays on screen so people can read it).
Usage: extend.py base.mp4 out.mp4 seconds from_frame
The tail repeats `seconds` of the base starting at from_frame — point it at a stretch of the empty dark grid (a section without camera);
if the reel has none, any calm stretch works: the end card then needs its own opaque background.
Afterwards: run.py <auto> prep --base <out.mp4> --force (the matte and tracks are rebuilt for the new length)."""
import subprocess, sys
base, out, sec, f0 = sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4])
n = round(sec * 30)
fc = (f"[0:v]split[a][b];[b]trim=start_frame={f0}:end_frame={f0 + n},setpts=PTS-STARTPTS[t];[a][t]concat=n=2:v=1:a=0,format=yuv420p[v];"
      f"[0:a]apad=pad_dur={n / 30:.4f}[au]")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", base, "-filter_complex", fc, "-map", "[v]", "-map", "[au]",
                "-c:v", "libx264", "-preset", "slow", "-crf", "14", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out], check=True)
print("tail:", n, "frames from", f0)
