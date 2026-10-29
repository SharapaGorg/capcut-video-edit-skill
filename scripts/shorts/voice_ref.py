"""Voice profile «ref»: the editor's reference renders (fit: <video work dir>/refs/train/voice/REPORT.md).

The reference voice is the raw dark mic: 4–6k −21, 6–8k −22, 8–12k −28 dB rel. 500–1 kHz, −17.5 LUFS, TP −1,
crest 18–19, no EQ / denoise / Crisper on top. A short cut from the long video takes its voice from the SCREENCAST
audio (brighter, less compressed than the mic), so a fixed chain cannot land on that spectrum. `match_fx` measures
the source's band spectrum (speech frames only, Welch 4096 — the method of the fit report) and fits one peaking
equalizer per band (target − source, clipped ±max_gain), re-measures after the whole chain and corrects the residual
once (two passes), then appends the fixed stages: HPF 70, light de-esser, compressor 1.8:1, dual mono.
`process` = chain + gain/limiter loop to a loudness target (standalone mic files, the A/B check).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

# Target: mean of the two reference shorts (REPORT.md §2, rows «ref A» / «ref B»), dB rel. 500–1000 Hz.
# 40–80 Hz is not fitted (music bass in the refs) — the HPF 70 takes care of it.
BANDS = [(80, 160), (160, 250), (250, 500), (1000, 2000), (2000, 4000), (4000, 6000), (6000, 8000), (8000, 12000)]
REF_BANDS = {'80-160': 1.5, '160-250': 6.4, '250-500': 6.8, '1000-2000': -9.5, '2000-4000': -14.0,
             '4000-6000': -21.3, '6000-8000': -22.4, '8000-12000': -27.6}
MEAS_BANDS = [(40, 80)] + BANDS            # measured (40–80 reported, not fitted)
REF_BAND = (500, 1000)
FIT_LO, FIT_HI = 80, 8000                  # the ±2 dB pass band of the fit (8–12k: music/SFX in the refs, fitted softly)
MAX_GAIN = 8.0
TOL_DB = 2.0

FIXED = [
    'highpass=f=70:p=2',                                                              # rumble only; the body 80–250 Hz stays
    'deesser=i=0.3:m=0.5:f=0.5:s=o',                                                  # light; ref sibilants ≈ raw
    'acompressor=threshold=-18dB:ratio=1.8:attack=10:release=150:knee=4:makeup=1',   # LRA only; crest stays 18–19
    'aformat=channel_layouts=mono,pan=stereo|c0=c0|c1=c0',                            # voice = mono centre of a stereo file
]
# Fixed chain for RAW MIC files (the fit of REPORT.md §5): the mic already has the reference spectrum, only 6–8k −2 dB.
VOICE_FX_REF = ','.join([FIXED[0], 'equalizer=f=7000:t=q:w=1.0:g=-2'] + FIXED[1:])


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError(' '.join(map(str, cmd[:12])) + '\n' + r.stderr[-1500:])
    return r


def measure(path):
    """ebur128 of a file -> {I, LRA, TP}."""
    r = subprocess.run(['ffmpeg', '-nostats', '-i', str(path), '-map', '0:a:0', '-af', 'ebur128=peak=true', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    s = r.stderr[r.stderr.rfind('Summary'):]
    m = {k: re.search(k + r':\s*(-?[\d.]+|-inf)', s) for k in ('I', 'LRA', 'Peak')}
    if not (m['I'] and m['Peak']):
        raise RuntimeError('ebur128: ' + r.stderr[-1500:])
    f = lambda k: float(m[k].group(1)) if m[k] and m[k].group(1) != '-inf' else -99.0
    return dict(I=f('I'), LRA=f('LRA'), TP=f('Peak'))


def load_mono(path, sr=48000, af=None):
    """Decode any audio file to float32 mono at sr (ffmpeg); af = filter applied before the decode (for a dry fit)."""
    cmd = ['ffmpeg', '-v', 'error', '-i', str(path)]
    if af: cmd += ['-af', af]
    cmd += ['-ac', '1', '-ar', str(sr), '-f', 'f32le', '-']
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        raise RuntimeError('ffmpeg decode: ' + r.stderr.decode('utf-8', 'replace')[-1500:])
    return np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64), sr


def _welch(m, sr, nperseg=4096):
    """Welch PSD (hann, 50 % overlap, constant detrend) — same as scipy.signal.welch defaults; only relative values are used."""
    step = nperseg // 2
    if len(m) < nperseg:
        m = np.pad(m, (0, nperseg - len(m)))
    w = np.hanning(nperseg + 1)[:-1]
    n = (len(m) - nperseg) // step + 1
    idx = np.arange(nperseg)[None, :] + step * np.arange(n)[:, None]
    seg = m[idx]; seg = seg - seg.mean(axis=1, keepdims=True)
    p = (np.abs(np.fft.rfft(seg * w, axis=1)) ** 2).mean(axis=0)
    f = np.fft.rfftfreq(nperseg, 1 / sr)
    return f, p


def crest_db(m):
    rms = np.sqrt(np.mean(m ** 2)) + 1e-12; pk = np.max(np.abs(m)) + 1e-12
    return round(float(20 * np.log10(pk / rms)), 1)


def band_spectrum(m, sr, bands=MEAS_BANDS):
    """{'lo-hi': dB rel. 500–1000 Hz} over speech frames only (50 ms frames with rms > p95 − 20 dB)."""
    n = int(sr * 0.05); k = max(len(m) // n, 1)
    fr = m[:k * n].reshape(k, n) if len(m) >= n else m[None, :]
    r = 20 * np.log10(np.sqrt(np.mean(fr ** 2, axis=1)) + 1e-12)
    sel = r > np.percentile(r, 95) - 20
    sp = fr[sel].ravel() if sel.any() else m
    f, p = _welch(sp, sr)
    def band(lo, hi):
        s = (f >= lo) & (f < hi)
        return 10 * np.log10(p[s].mean() + 1e-20)
    ref = band(*REF_BAND)
    return {f'{lo}-{hi}': round(float(band(lo, hi) - ref), 1) for lo, hi in bands}


def spectrum_of(path, af=None):
    m, sr = load_mono(path, af=af)
    return band_spectrum(m, sr)


def eq_string(gains):
    """One peaking equalizer per band at the geometric centre, width = the band in octaves (t=o). Zero gains are skipped."""
    parts = []
    for lo, hi in BANDS:
        g = gains.get(f'{lo}-{hi}', 0.0)
        if abs(g) < 0.05: continue
        fc = (lo * hi) ** 0.5; w = np.log2(hi / lo)
        parts.append(f'equalizer=f={fc:.0f}:t=o:w={w:.2f}:g={g:.2f}')
    return ','.join(parts)


def chain(gains):
    eq = eq_string(gains)
    return ','.join([FIXED[0]] + ([eq] if eq else []) + FIXED[1:])


def residual(meas, target=REF_BANDS):
    return {k: round(target[k] - meas[k], 1) for k in target}


def within(meas, target=REF_BANDS, tol=TOL_DB, lo=FIT_LO, hi=FIT_HI):
    """True when every fitted band inside [lo, hi] Hz is within ±tol of the target."""
    for k, t in target.items():
        a, b = (int(x) for x in k.split('-'))
        if a >= lo and b <= hi and abs(meas[k] - t) > tol:
            return False
    return True


def match_fx(src, max_gain=MAX_GAIN, target=REF_BANDS, passes=2, report=None):
    """Source file -> ffmpeg -af string that lands its speech spectrum on `target` (±2 dB, 80 Hz–8 kHz) plus the fixed
    stages. Pass 1: gains = target − source (clipped); pass 2: re-measure through the whole chain, add the residual.
    `report` (path) -> json {source, target, passes: [{gains, after}], after, ok, fx}. Returns the fx string; the fit
    details are in match_fx.last."""
    src = Path(src)
    source = spectrum_of(src)
    gains = {k: float(np.clip(target[k] - source[k], -max_gain, max_gain)) for k in target}
    hist, after, fx = [], None, chain(gains)
    for n in range(passes):
        after = spectrum_of(src, af=fx)
        hist.append(dict(gains={k: round(v, 2) for k, v in gains.items()}, after=after))
        if within(after, target) or n == passes - 1:
            break
        res = residual(after, target)
        gains = {k: float(np.clip(gains[k] + res[k], -max_gain, max_gain)) for k in target}
        fx = chain(gains)
    info = dict(source=source, target=target, passes=hist, gains=hist[-1]['gains'], after=after,
                ok=within(after, target), fx=fx, max_gain=max_gain)
    match_fx.last = info
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
    return fx


match_fx.last = None


def _gain_lim(src, out, g, lim, codec):
    _run(['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-af',
          f'aresample=192000,volume={g:.2f}dB,alimiter=limit={10 ** (lim / 20):.4f}:attack=3:release=80:level=false,aresample=48000',
          *codec, str(out)])
    return measure(out)


def process(in_path, out_path, target_lufs=-17.5, tp=-1.0, fx=None, tol=0.3, iters=6):
    """file -> processed voice at target_lufs (±tol) with true peak <= tp. fx: None = match_fx(in_path) (spectrum
    matching), or an explicit chain (VOICE_FX_REF for raw mic). Output codec by extension: .wav = pcm_f32le 48k stereo
    (dual mono), .m4a/.aac = aac 192k; loudness measured after the codec. Returns the measurement dict (+ gain, limit,
    passes, ok, fx)."""
    in_path, out_path = Path(in_path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fx is None: fx = match_fx(in_path)
    pre = out_path.with_name(out_path.stem + '_pre.wav')
    _run(['ffmpeg', '-v', 'error', '-y', '-i', str(in_path), '-af', fx, '-ar', '48000', '-c:a', 'pcm_f32le', str(pre)])
    codec = ['-c:a', 'aac', '-b:a', '192k'] if out_path.suffix.lower() in ('.m4a', '.aac') else ['-c:a', 'pcm_f32le']
    m0 = measure(pre); g, lim = target_lufs - m0['I'], tp - 0.1
    best, tmp, hist = None, out_path.with_name(out_path.stem + '_try' + out_path.suffix), []
    for n in range(1, iters + 1):
        m = _gain_lim(pre, tmp, g, lim, codec)
        ok = abs(m['I'] - target_lufs) <= tol and m['TP'] <= tp
        key = (not ok, m['TP'] > tp, abs(m['I'] - target_lufs))
        if best is None or key < best[0]:
            best = (key, dict(m, gain=round(g, 2), limit=round(lim, 2), passes=n, ok=ok, fx=fx)); shutil.copy(tmp, out_path)
        if ok: break
        if m['TP'] > tp: lim -= m['TP'] - tp + 0.05; hist = []; continue
        hist.append((g, m['I']))
        if len(hist) >= 2 and abs(hist[-1][1] - hist[-2][1]) > 0.05:   # secant: behind the limiter 1 dB gain < 1 LU
            slope = (hist[-1][1] - hist[-2][1]) / (hist[-1][0] - hist[-2][0]); step = (target_lufs - m['I']) / max(slope, 0.3)
        else:
            step = target_lufs - m['I']
        g += max(-12, min(12, step))
    tmp.unlink(missing_ok=True); pre.unlink(missing_ok=True)
    return best[1]


def table(rows, bands=MEAS_BANDS):
    """{name: {bands…}} -> text table (name, then one column per band)."""
    keys = [f'{lo}-{hi}' for lo, hi in bands]
    head = f"{'':10}" + ''.join(f'{k:>11}' for k in keys)
    out = [head]
    for name, d in rows.items():
        out.append(f'{name:10}' + ''.join(f"{d.get(k, float('nan')):>11.1f}" for k in keys))
    return '\n'.join(out)


if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    fx = VOICE_FX_REF if '--mic' in sys.argv else None
    r = process(src, dst, fx=fx)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if fx is None:
        print(table({'source': match_fx.last['source'], 'ours': spectrum_of(dst), 'target': REF_BANDS}))
