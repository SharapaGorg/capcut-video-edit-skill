"""Camera <-> voice sync by audio cross-correlation (STAGE_2.md §7.0, STAGE_LAYOUT.md).

    python -X utf8 scripts/layout/xcorr.py --config config.json [--dry] [--force]

Voice files = cfg.sources screencasts (with audio) + voice/; camera files = cfg.sources camera.
For every voice file: envelope cross-correlation (log RMS, 10 ms) against every camera file -> best camera
and coarse offset; then 3 control windows refined on the band-passed waveform (300-3000 Hz). Convention:
camera_time = voice_time + offset = median of the windows. ok = global peak z >= Z_MIN and >= 3 control windows
within 1 frame of that offset (real recordings: window spread is ~50 ms, single windows can be off by ~0.1 s).
Output: <work_dir>/layout/assembly.json {"pairs": [...]} (16 kHz wavs cached in layout/wav/). --dry: print only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy.signal as sg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import load_config  # noqa: E402

SR = 16000
HOP_S = 0.010
Z_MIN = 8.0          # global envelope peak, in std of the correlation
Z_WIN = 5.0          # control window peak
WIN_S = 30.0         # control window length (shorter for short files)
SEARCH_S = 1.0       # fine search: +-1 s around the coarse offset
WINDOWS = (0.1, 0.23, 0.37, 0.5, 0.63, 0.77, 0.9)   # control window centres, share of the overlap


def envelope(x: np.ndarray, sr: int = SR) -> tuple[np.ndarray, float]:
    hop = int(sr * HOP_S)
    n = len(x) // hop
    e = np.sqrt((x[: n * hop].astype(np.float32).reshape(n, hop) ** 2).mean(1))
    e = np.log1p(e * 1000)
    e -= e.mean()
    e /= e.std() + 1e-9
    return e, sr / hop


def _z(c: np.ndarray, i: int) -> float:
    return float((c[i] - c.mean()) / (c.std() + 1e-12))


def coarse(voice: np.ndarray, cam: np.ndarray, sr: int = SR) -> tuple[float, float]:
    """(offset_s, z): camera_time = voice_time + offset_s."""
    v, fr = envelope(voice, sr)
    c, _ = envelope(cam, sr)
    cc = sg.correlate(c, v, mode="full", method="fft")
    i = int(cc.argmax())
    return (i - (len(v) - 1)) / fr, _z(cc, i)


def _band(x: np.ndarray, sr: int) -> np.ndarray:
    b, a = sg.butter(4, [300 / (sr / 2), 3000 / (sr / 2)], "band")
    return sg.filtfilt(b, a, x.astype(np.float64))


def sync(voice: np.ndarray, cam: np.ndarray, sr: int = SR, fps: int = 30) -> dict:
    """Offset of cam relative to voice with 3 control windows. Arrays: mono float, same sample rate."""
    off, z = coarse(voice, cam, sr)
    v, c = voice, cam
    lo, hi = max(0.0, -off), min(len(v) / sr, len(c) / sr - off)   # overlap in voice time
    L = min(WIN_S, (hi - lo) / 8)
    checks = []
    if L > 0.5:
        for q in WINDOWS:
            w0 = lo + q * (hi - lo) - L / 2
            seg = _band(v[int(w0 * sr): int((w0 + L) * sr)], sr)
            a0 = max(0, int((w0 + off - SEARCH_S) * sr))
            a1 = min(len(c), int((w0 + off + L + SEARCH_S) * sr))
            if a1 - a0 <= len(seg):
                continue
            cc = sg.correlate(_band(c[a0:a1], sr), seg, mode="valid", method="fft")
            j = int(cc.argmax())
            checks.append({"voice_s": round(w0, 3), "offset_us": int(round(((a0 + j) / sr - w0) * 1e6)),
                           "z": round(_z(cc, j), 1)})
    good = [k["offset_us"] for k in checks if k["z"] >= Z_WIN]
    frame = 1e6 / fps
    med = int(np.median(good)) if good else int(round(off * 1e6))
    for k in checks:
        k["dev_us"] = k["offset_us"] - med
    within = [k for k in checks if k["z"] >= Z_WIN and abs(k["dev_us"]) <= frame]
    ok = z >= Z_MIN and len(within) >= 3
    return {"offset_us": med, "coarse_offset_us": int(round(off * 1e6)), "z": round(z, 1), "checks": checks,
            "within_frame": len(within), "ok": ok}


# ---- files ----
def to_wav16k(path: Path, cache_dir: Path) -> Path:
    out = cache_dir / (Path(path).name + ".16k.wav")
    if not out.is_file():
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{out.stem}.{os.getpid()}.tmp.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                        str(tmp)], check=True)
        os.replace(tmp, out)   # atomic: a parallel run never reads a half-written wav
    return out


def read_wav(path: Path) -> np.ndarray:
    import soundfile as sf
    x, sr = sf.read(str(path), dtype="float32")
    assert sr == SR, (path, sr)
    return x if x.ndim == 1 else x.mean(1)


def source_files(cfg) -> tuple[list[Path], list[Path]]:
    """(voice files: screencasts with audio + voice/, camera files)."""
    from capcut_new_project import list_media, probe
    voice = [p for p in list_media(cfg.sources.get("screencasts")) if probe(p)["has_audio"]]
    voice += list_media(cfg.sources.get("voice"))
    return voice, list_media(cfg.sources.get("camera"))


def sync_sources(cfg, cache_dir: Path | None = None, log=print) -> list[dict]:
    """Best camera for every voice file; one dict per voice file (ok False when no clear peak)."""
    cache_dir = cache_dir or cfg.work_dir / "layout" / "wav"
    voice, cams = source_files(cfg)
    cam_x = {p.name: read_wav(to_wav16k(p, cache_dir)) for p in cams}
    pairs = []
    for vp in voice:
        vx = read_wav(to_wav16k(vp, cache_dir))
        cand = sorted(((coarse(vx, cx, SR)[1], name) for name, cx in cam_x.items()), reverse=True)
        if not cand:
            continue
        z, name = cand[0]
        r = sync(vx, cam_x[name], SR, cfg.fps)
        r.update(voice=vp.name, camera=name, candidates=[{"camera": n, "z": round(zz, 1)} for zz, n in cand])
        pairs.append(r)
        log(f"{vp.name} -> {name}: offset {r['offset_us'] / 1e6:+.3f} s, z {r['z']}, "
            f"{r['within_frame']}/{len(r['checks'])} windows within 1 frame (dev ms {[k['dev_us'] // 1000 for k in r['checks']]}), "
            f"{'ok' if r['ok'] else 'NOT OK'}")
    return pairs


def main(argv=None):
    ap = argparse.ArgumentParser(description="camera <-> voice sync (assembly.json)")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true", help="print, do not write assembly.json")
    ap.add_argument("--force", action="store_true", help="recompute even if assembly.json has pairs")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    out = cfg.work_dir / "layout" / "assembly.json"
    rep = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    if rep.get("pairs") and not a.force:
        print(f"{out}: {len(rep['pairs'])} pairs already (use --force to recompute)")
        return
    rep["pairs"] = sync_sources(cfg)
    if a.dry:
        print("dry run, assembly.json not written")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
