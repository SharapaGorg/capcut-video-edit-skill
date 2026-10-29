"""Cut a phone screencast into a short demo for the phone mockup (`device.screen` of build_reel).

Spec json: {"src": "UBKT7676.MP4", "out": "work/screen_cut.mp4", "fps": 30, "xfade": 0.15,
            "segments": [{"in": 3.0, "out": 7.0, "speed": 4}, {"in": 8.0, "out": 9.1}, ...]}
Every segment is cut from src, sped up by `speed` (typing at 3-4x, results in real time), segments are joined with
a crossfade of `xfade` s (0 = hard cut). The result has no audio, keeps the source size.
Usage: python screen_cut.py spec.json
"""
import json
import subprocess
import sys
from pathlib import Path


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise SystemExit(' '.join(map(str, cmd[:12])) + '\n' + r.stderr[-2000:])
    return r


def build(spec, base):
    src = base / spec['src']; out = base / spec['out']; out.parent.mkdir(parents=True, exist_ok=True)
    fps = int(spec.get('fps', 30)); xf = float(spec.get('xfade', 0.15))
    segs = spec['segments']
    ins, fc, durs = [], [], []
    for i, s in enumerate(segs):
        sp = float(s.get('speed', 1)); d = (s['out'] - s['in']) / sp; durs.append(d)
        ins += ['-ss', f"{s['in']:.3f}", '-to', f"{s['out']:.3f}", '-i', str(src)]
        fc.append(f'[{i}:v]setpts=PTS/{sp:.4f},fps={fps},format=yuv420p,settb=AVTB[s{i}]')
    if len(segs) == 1 or xf <= 0:
        fc.append(''.join(f'[s{i}]' for i in range(len(segs))) + f'concat=n={len(segs)}:v=1:a=0[v]')
    else:
        cur, off = 's0', 0.0
        for i in range(1, len(segs)):
            off += durs[i - 1] - xf
            nxt = 'v' if i == len(segs) - 1 else f'x{i}'
            fc.append(f'[{cur}][s{i}]xfade=transition=fade:duration={xf:.3f}:offset={off:.4f}[{nxt}]'); cur = nxt
    total = sum(durs) - (len(segs) - 1) * (xf if xf > 0 else 0)
    run(['ffmpeg', '-v', 'error', '-y', *ins, '-filter_complex', ';'.join(fc), '-map', '[v]', '-an',
         '-c:v', 'libx264', '-crf', '16', '-preset', 'medium', '-pix_fmt', 'yuv420p', '-r', str(fps), str(out)])
    print(f'{out}  {total:.2f} s  ({len(segs)} segments)')
    return out, total


if __name__ == '__main__':
    p = Path(sys.argv[1]).resolve()
    build(json.loads(p.read_text(encoding='utf-8')), p.parent)
