"""Beat grid and a bar-aligned loop of a music track (librosa).

    python -X utf8 scripts/stage9/beats.py <track> ...      (prints the grid and the chosen loop)

analyze(): beats, downbeat phase (beat index mod 4 with the strongest onsets), RMS per beat.
loop_region(): [start, end) on bar starts, a multiple of 4 bars, from the first "energetic" bar; the end with the
smallest jump in RMS / amplitude across the splice (no click). A track too short for 16 bars -> at least 4 bars.
Leaves >= EDGE s before the start and after the end, so a 60-ms seam overlap stays inside the file.
"""
from __future__ import annotations

import sys

import numpy as np

EDGE = 0.1
MIN_BARS = 16


def analyze(path, sr: int = 22050) -> dict:
    import librosa
    y, sr = librosa.load(str(path), sr=sr, mono=True)
    oenv = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, trim=False)
    bt = librosa.frames_to_time(beats, sr=sr)
    phase = int(np.argmax([np.mean(oenv[beats[i::4]]) if len(beats[i::4]) else 0 for i in range(4)]))
    hop = 512
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    rt = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
    beat_rms = [float(np.mean(rms[(rt >= bt[i]) & (rt < bt[i + 1])]) if np.any((rt >= bt[i]) & (rt < bt[i + 1])) else 0.0)
                for i in range(len(bt) - 1)]
    return {"path": str(path), "sr": sr, "dur": len(y) / sr, "tempo": float(np.atleast_1d(tempo)[0]),
            "beats": [float(b) for b in bt], "phase": phase, "beat_rms": beat_rms, "y": y}


def seam_quality(a: dict, s: float, e: float) -> dict:
    """Splice e -> s: amplitude jump |y[e-1] - y[s]| relative to the local RMS (10 ms) and the RMS step 50 ms before/after."""
    y, sr = a["y"], a["sr"]
    i0, i1 = int(s * sr), int(e * sr)
    jump = abs(float(y[i1 - 1]) - float(y[i0]))
    w = int(0.01 * sr)
    loc = float(np.sqrt(np.mean(np.concatenate([y[i1 - w:i1], y[i0:i0 + w]]) ** 2))) + 1e-9
    w2 = int(0.05 * sr)
    rb = float(np.sqrt(np.mean(y[i1 - w2:i1] ** 2)))
    ra = float(np.sqrt(np.mean(y[i0:i0 + w2] ** 2)))
    return {"jump_rel": jump / loc, "rms_db": float(20 * np.log10((ra + 1e-9) / (rb + 1e-9)))}


def loop_region(a: dict, min_bars: int = MIN_BARS) -> dict | None:
    """{"start", "end", "bars", "seam"} or None when the grid has < 5 bars inside the file edges."""
    bt, ph, br = a["beats"], a["phase"], np.array(a["beat_rms"])
    bars = [i for i in range(ph, len(bt) - 1, 4) if EDGE <= bt[i] <= a["dur"] - EDGE]
    if len(bars) < 5:
        return None
    bar_rms = np.array([br[i:i + 4].mean() if i + 4 <= len(br) else br[i:].mean() for i in bars])
    med = float(np.median(bar_rms))
    first = next(k for k, r in enumerate(bar_rms) if r >= 0.7 * med)
    last_e = max(k for k, r in enumerate(bar_rms) if r >= 0.5 * med)
    span = len(bars) - 1 - first
    need = min_bars if span >= min_bars else max(4, span - span % 4)
    if span < need:
        first, need = 0, max(4, (len(bars) - 1) - (len(bars) - 1) % 4)
        if need > len(bars) - 1:
            return None
    best = None
    for k in range(first + need, min(last_e + 2, len(bars))):
        if (k - first) % 4:
            continue
        s, e = bt[bars[first]], bt[bars[k]]
        q = seam_quality(a, s, e)
        score = abs(q["rms_db"]) + 0.5 * q["jump_rel"]
        if best is None or score < best[0]:
            best = (score, s, e, k - first, q)
    if best is None:  # the energetic part ends early: take the longest multiple of 4 bars
        k = first + need
        s, e = bt[bars[first]], bt[bars[k]]
        best = (0.0, s, e, need, seam_quality(a, s, e))
    _, s, e, nb, q = best
    return {"start": float(s), "end": float(e), "bars": int(nb), "seam": q}


def main(argv=None):
    for p in (argv if argv is not None else sys.argv[1:]):
        a = analyze(p)
        r = loop_region(a)
        print(f"{p}: dur {a['dur']:.1f} s, tempo {a['tempo']:.1f}, beats {len(a['beats'])}, phase {a['phase']}, "
              + (f"loop {r['start']:.3f}-{r['end']:.3f} ({r['bars']} bars), seam jump_rel {r['seam']['jump_rel']:.2f} "
                 f"rms {r['seam']['rms_db']:+.1f} dB" if r else "no loop (too short)"))


if __name__ == "__main__":
    main()
