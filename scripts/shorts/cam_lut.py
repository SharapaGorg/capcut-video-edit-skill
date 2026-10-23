"""3D LUT for the camera (iPhone HLG HDR) fitted to the reference: frames of the master render (CapCut: HDR->SDR + grade).
Source/render frame pairs at moments of «camera on full screen», aligned by ORB+RANSAC, LUT 33^3 -> cam.cube.
The camera decode in build_render.py must be exactly SRC_VF + lut3d=cam.cube (byte for byte).

    python -X utf8 scripts/shorts/cam_lut.py [--config config.json] [--times T1 T2 …]

Input: config.json -> master_render (the exported master; required), its maps (rmap.master_dir: master_maps or
<work_dir>/stage3) + layout/layout.json -> moments with the camera on full screen.
Output: <work_dir>/stage12_shorts/cam.cube, <work_dir>/stage12_shorts/work/lut_check.jpg (source | LUT | render).
Recalibrate for every video. Never change cam.cube while a build is running (a mix of old and new colour).
Model (references/shorts.md §1): honest HLG->BT.709 (npl=1000, no tone mapping) + per-channel curves + ONE saturation
factor + lips desaturation; never a free LUT/matrix on a grey scene (pink lips).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import rmap  # noqa: E402

# honest HLG/BT.2020 -> BT.709 (peak 1000 nit = 1.0, no tone mapping); the LUT on top = brightness/balance curves only
SRC_VF = 'zscale=t=linear:npl=1000,format=gbrpf32le,zscale=p=bt709,zscale=t=bt709:m=bt709:r=full,format=rgb48le'
REN_VF = 'scale=in_color_matrix=bt709:in_range=tv,format=rgb48le'
N = 33
N_SAMPLES, TEST_EVERY = 17, 5        # aligned frames of «camera on full screen»; every 5th is a test frame, the rest train
MAX_CANDIDATES = 60                  # moments tried at most (auto)
MIN_TRAIN = 6                        # aligned training frames at least
LIPS_HUE, LIPS_WIDTH, LIPS_DESAT = 350.0, 14.0, 0.30     # lips ~351°, skin ~7–12° (measured on the first video)


def cube_path(cfg) -> Path:
    return cfg.work_dir / "stage12_shorts" / "cam.cube"


def master_render(cfg) -> Path:
    if not cfg.master_render:
        raise SystemExit("config.json → master_render не задан: укажите экспорт мастера (этап 10) — по нему "
                         "калибруется цвет камеры для шортсов")
    p = Path(cfg.master_render)
    if not p.is_file():
        raise SystemExit(f"master_render не найден: {p}")
    return p


def probe_wh(path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
    return w, h


def camera_segments(cfg) -> tuple[list[dict], list[tuple[float, float]], list[tuple[float, float]]]:
    """Camera segments of the master timeline, the ranges (s) where the camera is surely on full screen
    (layout/layout.json F rows when the master maps are stage3 + camera on the main video track) and all camera ranges."""
    tm = rmap.load_json(rmap.master_dir(cfg) / "timeline_map.json", "карта таймлайна мастера")
    cams, full, every = [], [], []
    vids = [t for t in tm["tracks"] if t.get("type") == "video"]
    for ti, t in enumerate(vids):
        for s in t["segments"]:
            role = s.get("role") or (common.source_role(cfg, s["file"]) if s.get("file") else None)
            if role == "camera" and s.get("source_in_us") is not None:
                cams.append(s)
                every.append((s["timeline_in_us"], s["timeline_out_us"]))
                if ti == 0:
                    full.append((s["timeline_in_us"], s["timeline_out_us"]))
    if rmap.master_dir(cfg) == cfg.work_dir / "stage3":
        full += [(common.us(r["start"]), common.us(r["end"])) for r in common.read_layout(cfg) if r.get("layout") == "F"]
    sec = lambda rs: [(a / 1e6, b / 1e6) for a, b in common.merge_ranges(rs)]
    return cams, sec(full), sec(every)


def sample_times(full: list[tuple[float, float]], n: int = N_SAMPLES, margin: float = 0.5) -> list[float]:
    """n moments spread evenly over the ranges (margin from every range edge); [] if there is nothing."""
    rs = [(a + margin, b - margin) for a, b in full if b - a > 2 * margin]
    total = sum(b - a for a, b in rs)
    if total <= 0:
        return []
    out = []
    for k in range(n):
        x = (k + 0.5) * total / n
        for a, b in rs:
            if x <= b - a:
                out.append(round(a + x, 3))
                break
            x -= b - a
    return out


def src_at(cams, c):
    us = c * 1e6
    for s in cams:
        if s["timeline_in_us"] <= us < s["timeline_out_us"]:
            return s["file"], s["source_in_us"] / 1e6 + (us - s["timeline_in_us"]) / 1e6 * s.get("speed", 1.0)
    return None, None


def grab(path, t, vf, w, h):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.4f}', '-i', str(path), '-frames:v', '1', '-vf', vf,
                        '-f', 'rawvideo', '-'], capture_output=True)
    return np.frombuffer(r.stdout, np.uint16)[:w * h * 3].reshape(h, w, 3).astype(np.float32) / 65535


def pair(cams, render, c):
    import cv2
    f, t = src_at(cams, c)
    if f is None:
        print(f'  {c}: нет куска камеры (роль по cfg.sources) — пропуск')
        return np.empty((0, 3), np.float32), np.empty((0, 3), np.float32), (None, None, None)
    sw, sh = probe_wh(f)
    rw_, rh_ = probe_wh(render)
    s = grab(f, t, SRC_VF, sw, sh)
    r = grab(render, c, REN_VF, rw_, rh_)
    g1 = cv2.equalizeHist((s.mean(2) * 255).astype(np.uint8))
    g2 = cv2.equalizeHist((r.mean(2) * 255).astype(np.uint8))
    orb = cv2.ORB_create(4000)
    k1, d1 = orb.detectAndCompute(g1, None)
    k2, d2 = orb.detectAndCompute(g2, None)
    m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d2, d1), key=lambda x: x.distance)[:800]
    A, inl = cv2.estimateAffinePartial2D(np.float32([k2[x.queryIdx].pt for x in m]),
                                         np.float32([k1[x.trainIdx].pt for x in m]), ransacReprojThreshold=2.0)
    rw = cv2.warpAffine(r, A, (sw, sh), flags=cv2.INTER_LINEAR, borderValue=(-1, -1, -1))
    valid = (rw[..., 0] >= 0)
    yy, xx = np.mgrid[0:sh, 0:sw]
    kx, ky = sw / 1920, sh / 1080
    center = ((xx - 1150 * kx) / (700 * kx)) ** 2 + ((yy - 540 * ky) / (520 * ky)) ** 2 < 1      # no vignette at the edges
    # drop object edges (motion / alignment error)
    edge = cv2.dilate(cv2.Canny((s.mean(2) * 255).astype(np.uint8), 20, 60), np.ones((5, 5), np.uint8)) > 0
    msk = valid & center & ~edge
    print(f'  {c}: {Path(f).name} @ {t:.2f}, масштаб {np.hypot(A[0, 0], A[0, 1]):.3f}, inliers {int(inl.sum())}, '
          f'пикселей {int(msk.sum())}')
    if inl.sum() < 200:
        msk[:] = False                   # not aligned
    return s[msk], rw[msk], (s, rw, valid)


def lips(P):
    """Less red on the lips: lower the saturation of saturated red-pink only, skin untouched."""
    mx, mn = P.max(1), P.min(1)
    d = np.maximum(mx - mn, 1e-6)
    r, g, b = P.T
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    dist = np.abs((h - LIPS_HUE + 180) % 360 - 180)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    w = np.clip(1 - dist / LIPS_WIDTH, 0, 1) * np.clip((sat - 0.30) / 0.15, 0, 1) * LIPS_DESAT
    y = (P @ np.array([0.2126, 0.7152, 0.0722]))[:, None]
    return np.clip(y + (1 - w)[:, None] * (P - y), 0, 1)


def fit_global(S, R, it=4, matrix=False):
    """Rigid model: R = curve_k((M @ [S,1])_k) — 3x4 matrix (identity unless matrix=True) + monotone per-channel curves
    + one saturation factor. It cannot paint single hues."""
    X = np.c_[S, np.ones(len(S))]
    knots = np.linspace(-0.2, 1.2, 57)
    T = R.copy()
    curves = None
    M = None
    for _ in range(it):
        M = np.linalg.lstsq(X, T, rcond=None)[0] if matrix else np.r_[np.eye(3), np.zeros((1, 3))]
        Y = X @ M
        curves = []
        for k in range(3):
            idx = np.clip(np.searchsorted(knots, Y[:, k]), 1, len(knots) - 1)
            cnt = np.bincount(idx, minlength=len(knots))
            sm = np.bincount(idx, R[:, k], minlength=len(knots))
            v = np.where(cnt > 50, sm / np.maximum(cnt, 1), np.nan)
            ok = ~np.isnan(v)
            v = np.interp(knots, knots[ok], v[ok])
            v = np.maximum.accumulate(np.convolve(np.pad(v, 2, mode='edge'), np.ones(5) / 5, mode='valid'))
            curves.append(v)
        # target for the matrix: inverse curve of R
        T = np.stack([np.interp(R[:, k], curves[k] + np.arange(len(knots)) * 1e-6, knots) for k in range(3)], 1)

    def fc(Z):
        Y = np.c_[Z.reshape(-1, 3), np.ones(Z.size // 3)] @ M
        return np.clip(np.stack([np.interp(Y[:, k], knots, curves[k]) for k in range(3)], 1), 0, 1)
    # one common saturation factor (CapCut Saturation +10 etc.)
    lw = np.array([0.2126, 0.7152, 0.0722])
    P = fc(S)
    cp = P - (P @ lw)[:, None]
    cr = R - (R @ lw)[:, None]
    sat = float((cp * cr).sum() / (cp * cp).sum())
    print(f'  насыщенность x{sat:.3f}')

    def f(Z):
        P = fc(Z)
        y = (P @ lw)[:, None]
        P = np.clip(y + sat * (P - y), 0, 1)
        return lips(P).reshape(Z.shape)
    g = np.linspace(0, 1, N)
    grid = np.stack(np.meshgrid(g, g, g, indexing='ij'), -1)
    print('  матрица:', M.T.round(3).tolist())
    return f(grid)


def apply(lut, X):
    i = np.clip(np.round(X * (N - 1)).astype(int), 0, N - 1)
    return lut[i[..., 0], i[..., 1], i[..., 2]]


def write_cube(lut, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        f.write(f'TITLE "cam_hlg_to_capcut"\nLUT_3D_SIZE {N}\n')
        for b in range(N):
            for g in range(N):
                for r in range(N):
                    f.write('%.6f %.6f %.6f\n' % tuple(lut[r, g, b]))


def run(cfg, times=None):
    """Candidates: moments of the sure full-screen camera first, then of any camera piece (circle moments do not align
    with the render and are dropped: < 200 ORB inliers). The first N_SAMPLES aligned frames: every 5th is a test frame."""
    import cv2
    render = master_render(cfg)
    cams, full, every = camera_segments(cfg)
    if times:
        cands = list(times)
    else:
        cands = sample_times(full)
        cands += [t for t in sample_times(every, MAX_CANDIDATES) if all(abs(t - c) > 1.0 for c in cands)]
    if not cands:
        raise SystemExit("в карте мастера нет камеры: калибровать не по чему")
    S, R, rows, n_ok = [], [], [], 0
    for c in (cands if times else cands[:MAX_CANDIDATES]):
        s, r, (sf, rf, valid) = pair(cams, render, c)
        if not len(s):
            continue
        if n_ok % TEST_EVERY == TEST_EVERY // 2:          # test frame: not fitted, shown on the check sheet
            rows.append((c, s, r, sf, rf, valid))
        else:
            step = max(1, len(s) // 60000)
            S.append(s[::step])
            R.append(r[::step])
        n_ok += 1
        if n_ok >= N_SAMPLES:
            break
    if len(S) < MIN_TRAIN:
        raise SystemExit(f"совместилось кадров с рендером мастера: {n_ok} (обучающих {len(S)} < {MIN_TRAIN}) — мало. "
                         "Укажите моменты мастера с камерой во весь кадр: --times T1 T2 … (секунды таймлайна мастера), "
                         "проверьте master_render и master_maps")
    print(f"  кадров: {len(S)} обучение, {len(rows)} тест")
    lut = fit_global(np.concatenate(S), np.concatenate(R))
    out = cube_path(cfg)
    write_cube(lut, out)
    sheet_rows = []
    for c, s, r, sf, rf, valid in rows:
        e = np.abs(apply(lut, s) - r).mean(0) * 255
        print(f'  тест {c}: средняя ошибка R/G/B {e.round(1)} (из 255), исходник без LUT: '
              f'{(np.abs(s - r).mean(0) * 255).round(1)}')
        o = apply(lut, sf)
        o[~valid] = 0
        sheet_rows.append(np.concatenate([sf, o, np.where(valid[..., None], rf, 0)], 1))
    chk = cfg.work_dir / "stage12_shorts" / "work" / "lut_check.jpg"
    if sheet_rows:
        sheet = (np.concatenate(sheet_rows, 0)[..., ::-1] * 255).astype(np.uint8)
        chk.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(chk), cv2.resize(sheet, (sheet.shape[1] // 3, sheet.shape[0] // 3)))
    print(f'{out}, {chk} (исходник | LUT | рендер) — сверить крупный план лица (губы, щёки), не среднюю ошибку')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="camera LUT (HLG -> CapCut look) from the master render")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--times", nargs="+", type=float,
                    help="master timeline moments (s) with the camera on full screen, instead of the automatic choice")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    master_render(cfg)                 # fail early with a clear message
    run(cfg, a.times)


if __name__ == '__main__':
    main()
