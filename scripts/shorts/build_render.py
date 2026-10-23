"""Shorts render (called by build.py): pieces from the SOURCES (camera through cam.cube = CapCut colour) -> ffmpeg
vertical 1080x1920, zoom on the full-screen camera, graphics HTML -> Playwright -> ProRes 4444 MOV, final mix.
Rules and why: references/shorts.md (§1 colour, §2 zooms, §5 sound, §7 splice/crop).
"""
from __future__ import annotations

import functools
import math
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "stage10"))
import cam_lut  # noqa: E402
from loudnorm import measure  # noqa: E402  (shared EBU R128 / true-peak meter of the export stage)

FPS = 30; W, H = 1080, 1920
CAM_H = 840            # top: camera 1080x840
SC_H = H - CAM_H       # bottom: screencast 1080x1080
SC_REF_W = 2560        # spec zoom px are screencast px; the default window below is for a 2560-wide screencast
DEF_ZOOM = [560, 90, 1300, 1300]   # content centre without the browser bar and the taskbar (2560x1440)
SPEED = 1.0            # no speed-up: any voice time-stretch filter spoils the sound — user's A/B choice
DYN_PUNCH, DYN_SFX_PEAK = 1.18, -27.0
# the source voice is already clean (noise reduction at recording, pauses −84 dB): no second noise reduction, it dulls
# the highs. EQ fitted by spectrum to the CapCut render with Voice Crisper: highs 2–8 kHz +5…+6 dB.
VOICE_FX = ('highpass=f=80,equalizer=f=250:t=q:w=1:g=-1.5,highshelf=g=5:f=2500:t=q:w=0.7,'
            'equalizer=f=5000:t=q:w=1.2:g=1.5,acompressor=threshold=-20dB:ratio=2.5:attack=5:release=120:makeup=2')
VOICE_LUFS, MUSIC_REL, SFX_PEAK = -19.0, -13.0, -22.0   # music = voice −13 LU; whoosh peak −22 dBFS before the final gain
FINAL_I, FINAL_TOL, FINAL_TP, FINAL_ITER = -14.0, 0.5, -1.1, 6
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
WHOOSH_HINTS = ("вуш", "whoosh", "swoosh")     # default whoosh: first file in sfx_dir (recursive) with one in its name

ZOOM_BASE_MAX = 0.10       # background: slow wave 1.00 <-> 1.10
ZOOM_PERIOD = 10.0         # wave period, s
ZOOM_ACC = 0.14            # accent push-in
ZOOM_EASE = 0.6            # smooth accent, s
ZOOM_HOLD = 1.2            # from the accent to the next cut at least, s (no zoom right before a cut)
ZOOM_GAP = 2.5             # between accents at least, s


def fr(t): return int(round(t * FPS))
def q(t): return fr(t) / FPS            # on the frame grid
def strip(w): return re.sub(r'[^\wа-яё×%]+', '', w.lower(), flags=re.I)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError(' '.join(map(str, cmd[:12])) + '\n' + r.stderr[-2000:])
    return r


@functools.lru_cache(maxsize=64)
def size_of(path: str) -> tuple[int, int]:
    return cam_lut.probe_wh(path)


# ---------------- screencast crop ----------------
def zoom_rect(z, aspect, scw=2560, sch=1440):
    """z=[x,y,w,h] in screencast px; fitted to aspect (w/h), clamped."""
    if not z:
        z = [v * scw / SC_REF_W for v in DEF_ZOOM]
    x, y, w, h = z
    if abs(w / h - aspect) > 0.01:
        h = w / aspect
    w, h = min(w, scw), min(h, sch)
    if w / h > aspect: w = h * aspect
    else: h = w / aspect
    x = min(max(0, x), scw - w); y = min(max(0, y), sch - h)
    return [int(round(x)), int(round(y)), int(round(w)), int(round(h))]


def key_expr(keys, idx, aspect, scw=2560, sch=1440):
    """ffmpeg expression of component idx (0=x,1=y,2=w) of the zoom window as a function of t (piece time).
    Keys with t<=0 = the state at the piece start, then a smooth transition over ease (smoothstep)."""
    ks = sorted((k['t'], zoom_rect(k['zoom'], aspect, scw, sch), k['ease']) for k in keys)
    past = [k for k in ks if k[0] <= 0.0]
    fut = [k for k in ks if k[0] > 0.0]
    if not past: past = [ks[0]]
    cur = past[-1][1][idx]
    if past[-1][0] + past[-1][2] > 0.0 and len(past) >= 2:     # cut inside a transition: continue from its middle
        a = past[-2][1][idx]; b = past[-1][1][idx]; u = min(1, -past[-1][0] / past[-1][2]); cur = a + (b - a) * (u * u * (3 - 2 * u))
    expr = f'{cur:.3f}'; prev = cur
    for t, z, e in fut:          # keys in order, spaced more than ease -> before a key the state = the previous key
        v = z[idx]
        expr = f"if(lt(t,{t:.4f}),{expr},if(lt(t,{t + e:.4f}),{prev:.3f}+({v - prev:.3f})*(st(0,(t-{t:.4f})/{e:.4f})*ld(0)*(3-2*ld(0))),{v:.3f}))"
        prev = v
    return expr


def sc_filter(p, outw, outh, scw=2560, sch=1440):
    """Screencast crop: static (p['zoom']) or animated by p['keys'] (zoom after the cursor)."""
    aspect = outw / outh
    if not p.get('keys'):
        x, y, w, h = zoom_rect(p['zoom'], aspect, scw, sch)
        if p.get('punch'):
            x, y, w, h = zoom_rect([x + w * (1 - 1 / DYN_PUNCH) / 2, y + h * (1 - 1 / DYN_PUNCH) / 2, w / DYN_PUNCH, h / DYN_PUNCH], aspect, scw, sch)
        return f"crop={w}:{h}:{x}:{y},scale={outw}:{outh}:flags=lanczos"
    ex, ey, ew = (key_expr(p['keys'], i, aspect, scw, sch) for i in range(3))
    # scale s = outw / w(t); the whole frame is scaled per frame, then an outw x outh crop at (x*s, y*s)
    return (f"scale=w='round({scw}*{outw}/({ew}))':h='round({sch}*{outw}/({ew}))':eval=frame:flags=bicubic,"
            f"crop={outw}:{outh}:x='({ex})*{outw}/({ew})':y='({ey})*{outw}/({ew})'")


# ---------------- camera: colour by the render reference (cam_lut.py -> cam.cube) ----------------
TOYUV = 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p'


def camlut(ctx) -> str:
    """Decode chain of the camera = the calibration chain of cam_lut.py + lut3d (no trailing comma)."""
    cube = cam_lut.cube_path(ctx.cfg).as_posix().replace(':', r'\:')
    return f"{cam_lut.SRC_VF},lut3d=file='{cube}':interp=tetrahedral"


def need_cube(ctx):
    p = cam_lut.cube_path(ctx.cfg)
    if not p.is_file():
        raise SystemExit(f"нет {p}: сначала scripts/shorts/cam_lut.py --config … (калибровка цвета камеры по master_render)")


@functools.lru_cache(maxsize=1)
def _face():
    import cv2
    c = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if c.empty():
        raise SystemExit('opencv без haarcascade (opencv 5.x?): pip install "opencv-python<5"')
    return c


def face_center(fr_):
    import cv2
    h, w = fr_.shape[:2]
    g = cv2.cvtColor(cv2.resize(fr_, (w // 3, h // 3)), cv2.COLOR_BGR2GRAY)
    fs = _face().detectMultiScale(g, 1.1, 5, minSize=(30, 30))
    if len(fs) == 0: return None
    x, y, fw, fh = max(fs, key=lambda f: f[2] * f[3])
    return (x + fw / 2) * 3, (y + fh / 2) * 3


def frame_full(fr_, z, cx):
    """9:16 crop (full height at z=1), scale strictly from the frame centre — like Scale in CapCut; cx = one per short"""
    import cv2
    sh, sw = fr_.shape[:2]
    hw = sh / z; ww = hw * W / H
    x0 = min(max(0, cx - ww / 2), sw - ww); y0 = (sh - hw) / 2
    k = H / hw
    M = np.float32([[k, 0, -x0 * k], [0, k, -y0 * k]])
    return cv2.warpAffine(fr_, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def grab_cam(ctx, c, dt=0.0):
    cw, ch = size_of(c['file'])
    r = subprocess.run(['ffmpeg', '-v', 'error', '-ss', f"{c['start'] + dt:.4f}", '-i', c['file'], '-frames:v', '1',
                        '-vf', f'{camlut(ctx)},format=bgr24', '-f', 'rawvideo', '-'], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8)[:cw * ch * 3].reshape(ch, cw, 3)


def short_cam_x(ctx, pl):
    """One crop centre for the whole short: median x of the face over the «camera on full screen» pieces (else over the
    stack camera pieces; no face -> the frame centre). A number in spec cam_cx overrides it."""
    if isinstance(ctx.cam_cx, (int, float)):
        pl['cam_x'] = float(ctx.cam_cx)
        return pl['cam_x']
    xs = []
    for lay in ('full', 'stack'):
        for p in pl['pieces']:
            if p['layout'] != lay or not p.get('cam'): continue
            f = face_center(grab_cam(ctx, p['cam'], min(0.3, p['src_dur'] / 2)))
            if f: xs.append(f[0])
        if xs: break
    cams = [p['cam'] for p in pl['pieces'] if p.get('cam')]
    pl['cam_x'] = float(np.median(xs)) if xs else (size_of(cams[0]['file'])[0] / 2 if cams else 0.0)
    return pl['cam_x']


def cam_cx(ctx, pl, name):
    return float(ctx.cam_cx.get(name, pl['cam_x'])) if isinstance(ctx.cam_cx, dict) else pl['cam_x']


def piece_full(ctx, p, zcurve, cx, out_v):
    """camera on full screen: frames through python (zoom with sub-pixel precision)"""
    n = fr(p['dur']); c = p['cam']
    cw, ch = size_of(c['file'])
    dec = subprocess.Popen(['ffmpeg', '-v', 'error', '-ss', f"{c['start']:.6f}", '-t', f"{p['src_dur'] * c['speed'] + 0.5:.6f}", '-i', c['file'],
                            '-vf', f"setpts=PTS/{c['speed'] * ctx.speed:.6f},{camlut(ctx)},fps={FPS},format=bgr24", '-f', 'rawvideo', '-'], stdout=subprocess.PIPE)
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                            '-vf', TOYUV, '-c:v', 'libx264', '-preset', 'fast', '-crf', '14', '-g', '30', str(out_v)], stdin=subprocess.PIPE)
    fsz = cw * ch * 3; last = None
    for i in range(n):
        buf = dec.stdout.read(fsz)
        if len(buf) == fsz: last = np.frombuffer(buf, np.uint8).reshape(ch, cw, 3)
        if last is None: raise RuntimeError(f"{c['file']}: no frames at {c['start']:.3f}")
        enc.stdin.write(np.ascontiguousarray(frame_full(last, zcurve(p['s0'] + i / FPS), cx)).tobytes())
    dec.stdout.close(); dec.kill(); enc.stdin.close(); enc.wait()
    if enc.returncode != 0: raise RuntimeError(f'ffmpeg encode failed: {out_v}')


# ---------------- zoom (camera on full screen only) ----------------
def envelope(wav):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(wav), '-ac', '1', '-ar', '8000', '-f', 'f32le', '-'], capture_output=True)
    a = np.frombuffer(r.stdout, np.float32)
    hop = 80                                     # 10 ms
    n = len(a) // hop
    return np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)


def stress_time(env, w):
    """loudness peak inside the word ≈ the stressed syllable"""
    i0 = int(w['start'] * 100); i1 = max(i0 + 1, int(w['end'] * 100))
    seg = env[i0:i1]
    if not len(seg): return w['start']
    sm = np.convolve(seg, np.ones(5) / 5, mode='same')
    return (i0 + int(np.argmax(sm))) / 100


def zoom_plan(pl, spec, env, dyn=False):
    """Zoom only on «camera on full screen», scale from the centre.
    Background: a continuous slow push/pull wave (period 10 s), cuts do not reset it.
    Accent: digits + spec["accents"] (word substrings), instant / 0.6-s push that lands on the stressed syllable (loudness
    peak of the word); held to the next cut. Not placed if the cut is closer than ZOOM_HOLD."""
    full = [p for p in pl['pieces'] if p['layout'] == 'full']
    accw = [a.lower() for a in spec.get('accents', [])]
    acc = []
    for w in pl['words']:
        sw = strip(w['word'])
        if re.search(r'\d', sw) or any(a in sw for a in accw): acc.append(w)

    def piece_of(t):
        for p in full:
            if p['s0'] - 1e-6 <= t < p['s0'] + p['dur']: return p
    bumps = []; last = -9; kind = 0
    for w in acc:
        ts = stress_time(env, w); p = piece_of(ts)
        if not p or ts - last < (1.5 if dyn else ZOOM_GAP): continue
        end = p['s0'] + p['dur']
        if end - ts < (0.5 if dyn else ZOOM_HOLD): continue
        mode = 'snap' if kind % 2 == 0 or ts - p['s0'] < ZOOM_EASE + 0.1 else 'ease'
        bumps.append(dict(t=ts, mode=mode, end=end, word=w['word'])); last = ts; kind += 1
    t_first = full[0]['s0'] if full else 0.0
    pl['zoom_keys'] = dict(bumps=bumps)

    def z(t):
        v = 1.0 + ZOOM_BASE_MAX / 2 * (1 - math.cos(2 * math.pi * (t - t_first) / ZOOM_PERIOD))     # ~5 s in, ~5 s out
        for bp in bumps:
            if t >= bp['end'] - 1e-6: continue
            if bp['mode'] == 'snap': v += ZOOM_ACC if t >= bp['t'] - 0.02 else 0
            else:
                u = min(max((t - (bp['t'] - ZOOM_EASE)) / ZOOM_EASE, 0), 1); v += ZOOM_ACC * (u * u * (3 - 2 * u))
        return v
    return z


# ---------------- ffmpeg pieces ----------------
def tempo_af(t):
    return '' if abs(t - 1) < 1e-4 else f'atempo={t:.6f},'      # only for a piece sped in the project


def audio_cmd(p, out_a, speed=SPEED):
    dur = p['dur']; a = p['aud']
    mute = ''.join(f",volume=0:enable='between(t,{m0:.3f},{m1:.3f})'" for m0, m1 in p.get('mute', []))
    return ['ffmpeg', '-v', 'error', '-y', '-ss', f"{a['start']:.6f}", '-t', f"{p['src_dur'] * a['speed'] + 0.5:.6f}", '-i', a['file'],
            '-af', f"aresample=48000,{tempo_af(a['speed'] * speed)}" f"pan=mono|c0=0.5*c0+0.5*c1,volume={a['gain']},atrim=end={dur:.6f}{mute},afade=t=in:d=0.008,afade=t=out:st={max(0, dur - 0.01):.6f}:d=0.01",
            '-t', f'{dur:.6f}', '-c:a', 'pcm_s16le', str(out_a)]


def piece_cmd(ctx, p, out_v, cx):
    n = fr(p['dur'])
    ins, fc = [], []

    def add(src):
        ins.extend(['-ss', f"{src['start']:.6f}", '-t', f"{p['src_dur'] * src['speed'] + 0.5:.6f}", '-i', src['file']]); return len(ins) // 6 - 1
    sp = lambda src: f"setpts=PTS/{src['speed'] * ctx.speed:.6f},"
    scw, sch = size_of(p['sc']['file'])
    k = sch / 1440
    if p['layout'] == 'scfull':
        i = add(p['sc']); z = p['zoom'] or [v * scw / SC_REF_W for v in DEF_ZOOM]
        h0 = int(round(1290 * k)); y0 = int(round(90 * k))
        h = h0; w = int(h * 9 / 16); x = int(min(max(0, z[0] + z[2] / 2 - w / 2), scw - w)); y = y0
        if p.get('punch'): h = int(h0 / DYN_PUNCH); w = int(h * 9 / 16); x = int(min(max(0, z[0] + z[2] / 2 - w / 2), scw - w)); y = y0 + int((h0 - h) / 2)
        fc.append(f"[{i}:v]{sp(p['sc'])}fps={FPS},crop={w}:{h}:{x}:{y},scale={W}:{H}:flags=lanczos,setsar=1,format=yuv420p[v]")
    else:
        i = add(p['cam']); j = add(p['sc'])
        camw, camh = size_of(p['cam']['file'])
        cw0, ch0 = min(camw, int(round(camh * W / CAM_H))), camh      # 1389x1080 for a 1920x1080 camera
        cw, ch = (int(cw0 / DYN_PUNCH), int(ch0 / DYN_PUNCH)) if p.get('punch') else (cw0, ch0)
        cx0 = int(round(cx))
        fc.append(f"[{i}:v]{sp(p['cam'])}{camlut(ctx)},{TOYUV},fps={FPS},crop={cw}:{ch}:{min(max(0, cx0 - cw // 2), camw - cw)}:{(camh - ch) // 2},scale={W}:{CAM_H}:flags=lanczos,setsar=1[top]")
        fc.append(f"[{j}:v]{sp(p['sc'])}fps={FPS},{sc_filter(p, W, SC_H, scw, sch)},setsar=1,format=yuv420p[bot]")
        fc.append('[top][bot]vstack[v]')
    return ['ffmpeg', '-v', 'error', '-y', *ins, '-filter_complex', ';'.join(fc),
            '-map', '[v]', '-frames:v', str(n), '-r', str(FPS), '-c:v', 'libx264', '-preset', 'fast', '-crf', '14', '-pix_fmt', 'yuv420p', '-g', '30', str(out_v)]


def concat_list(listfile: Path, paths) -> Path:
    """ffmpeg concat demuxer list: each path relative to the list's folder when inside it, single-quoted with every
    ' written as '\'' (a ' in the work-dir path broke the list before)."""
    lines = []
    for f in paths:
        f = Path(f)
        try:
            f = f.relative_to(listfile.parent)
        except ValueError:
            pass
        q = f.as_posix().replace("'", "'\\''")
        lines.append(f"file '{q}'\n")
    listfile.write_text(''.join(lines), encoding='utf-8')
    return listfile


def extract(ctx, pl, wd, spec):
    need_cube(ctx)
    bad = [i for i, p in enumerate(pl['pieces']) if not p.get('aud') or (p['layout'] != 'full' and not p.get('sc'))
           or (p['layout'] in ('full', 'stack') and not p.get('cam'))]
    if bad:
        raise SystemExit(f"куски без исходника (нет файла / нет голоса): {bad[:10]} — см. «НЕТ ФАЙЛОВ» выше")
    pdir = wd / 'pieces'
    if pdir.exists(): shutil.rmtree(pdir)
    pdir.mkdir()
    N = len(pl['pieces'])
    with ThreadPoolExecutor(4) as ex: list(ex.map(lambda i: run(audio_cmd(pl['pieces'][i], pdir / f'{i:03d}.wav', ctx.speed)), range(N)))
    concat_list(wd / 'audio.txt', [pdir / f'{i:03d}.wav' for i in range(N)])
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(wd / 'audio.txt'), '-c', 'copy', str(wd / 'voice_raw.wav')])
    zc = zoom_plan(pl, spec, envelope(wd / 'voice_raw.wav'), ctx.dyn)
    cx = short_cam_x(ctx, pl)

    def vid(i):
        p = pl['pieces'][i]; ov = pdir / f'{i:03d}.mp4'
        if p['layout'] == 'full': piece_full(ctx, p, zc, cx, ov)
        else: run(piece_cmd(ctx, p, ov, cam_cx(ctx, pl, p['cam']['name']) if p.get('cam') else cx))
    with ThreadPoolExecutor(4) as ex: list(ex.map(vid, range(N)))
    for i, p in enumerate(pl['pieces']):
        n = int(run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', str(pdir / f'{i:03d}.mp4')]).stdout.strip().strip(','))
        if n != fr(p['dur']): raise RuntimeError(f'{i:03d}: {n} кадров, ждали {fr(p["dur"])}')
    concat_list(wd / 'video.txt', [pdir / f'{i:03d}.mp4' for i in range(N)])
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(wd / 'video.txt'), '-c', 'copy', str(wd / 'video.mp4')])


# ---------------- graphics ----------------
def render(html_path, n, mov):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(); page = b.new_page(viewport={'width': W, 'height': H}, device_scale_factor=1)
        page.goto(Path(html_path).as_uri()); page.evaluate('document.fonts.ready'); page.evaluate('seek(0)')
        cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'image2pipe', '-vcodec', 'png', '-r', str(FPS), '-i', '-',
               '-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', str(mov)]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE); t = time.time()
        for i in range(n):
            page.evaluate(f'seek({i / FPS})')
            p.stdin.write(page.screenshot(omit_background=True, type='png', clip={'x': 0, 'y': 0, 'width': W, 'height': H}))
        p.stdin.close(); p.wait(); b.close()
        if p.returncode != 0: raise RuntimeError(f'ffmpeg ProRes encode failed: {mov}')
        print(f'  графика: {n} кадров за {time.time() - t:.0f} с')


def preview_frames(wd, final, times):
    """png frames of THIS build's final (not a stale final.mp4 of another mode) into work/<id>/check"""
    (wd / 'check').mkdir(exist_ok=True)
    for t in times:
        run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(final), '-frames:v', '1', '-vf', 'scale=540:-1', str(wd / 'check' / f'{t:06.2f}.png')])


# ---------------- mix ----------------
def _pick(path_or_name, folder):
    p = Path(path_or_name)
    return p if p.is_absolute() else Path(folder) / p


def music_file(ctx, spec):
    """spec "music" (a name in music_dir or an absolute path), else the first audio file of music_dir (sorted).
    music_dir unset -> None (a warning; the short is mixed without music)."""
    d = ctx.cfg.music_dir
    if spec.get('music'):
        p = _pick(spec['music'], d or '.')
        if not p.is_file(): raise SystemExit(f'музыка не найдена: {p}')
        return p
    if not d:
        print('  ВНИМАНИЕ: config.json → music_dir не задан — шортс без музыки')
        return None
    if not Path(d).is_dir(): raise SystemExit(f'music_dir не найден: {d}')
    files = sorted(p for p in Path(d).iterdir() if p.suffix.lower() in AUDIO_EXT)
    if not files: raise SystemExit(f'в music_dir нет аудиофайлов: {d}')
    print(f'  музыка: {files[0].name} (первый файл music_dir; другой — "music" в спеке)')
    return files[0]


def whoosh_file(ctx, spec):
    """spec "whoosh" (a path inside sfx_dir or absolute), else the first file in sfx_dir (recursive, sorted) whose name
    has «вуш»/«whoosh»/«swoosh» (none -> error). sfx_dir unset -> None (a warning, no whoosh)."""
    d = ctx.cfg.sfx_dir
    if spec.get('whoosh'):
        p = _pick(spec['whoosh'], d or '.')
        if not p.is_file(): raise SystemExit(f'вуш не найден: {p}')
        return p
    if not d:
        print('  ВНИМАНИЕ: config.json → sfx_dir не задан — без вуша')
        return None
    if not Path(d).is_dir(): raise SystemExit(f'sfx_dir не найден: {d}')
    files = sorted((p for p in Path(d).rglob('*') if p.suffix.lower() in AUDIO_EXT), key=lambda p: p.as_posix().lower())
    hit = [p for p in files if any(h in p.name.lower() for h in WHOOSH_HINTS)]
    if not hit:
        raise SystemExit(f'в sfx_dir ({d}) нет файла с «вуш» / «whoosh» / «swoosh» в имени: задать "whoosh" в спеке '
                         '(путь внутри sfx_dir)')
    print(f'  вуш: {hit[0].name} (другой — "whoosh" в спеке)')
    return hit[0]


def _gain_lim(pre, out, g, lim):
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(pre), '-af',
         f"aresample=192000,volume={g:.2f}dB,alimiter=limit={10 ** (lim / 20):.4f}:attack=3:release=80:level=false,"
         "aresample=48000",       # limiter at 4x oversampling: sample peaks ≈ true peaks, TP after AAC stays near the limit
         '-c:a', 'aac', '-b:a', '192k', str(out)])
    return measure(out)


def in_norm(I, tp):
    return abs(I - FINAL_I) <= FINAL_TOL and tp <= FINAL_TP


def final_loop(pre, out, iters=None):
    """Final gain + limiter -> AAC, measured AFTER AAC, until −14 ±0.5 LUFS and TP <= −1.1 (at most FINAL_ITER passes).
    Gain step = secant over the last two (gain, I) passes at the same limiter level (behind the limiter 1 dB of gain
    gives less than 1 LU on peaky voice; a full-error step undershoots forever), clamped to 1..12 dB per pass and
    never into a region already known to overshoot/undershoot. TP over → the limiter goes down and the secant restarts.
    The best pass (in norm, else the nearest to −14 with TP ok) is kept in `out`. -> {I, TP, gain, limit, passes, ok}"""
    iters = iters or FINAL_ITER
    I_pre = measure(pre)['I']
    g, lim = FINAL_I - I_pre + 1.0, -2.0
    hist, best = [], None
    tmp = Path(out).with_name(Path(out).stem + '_try' + Path(out).suffix)
    for n in range(1, iters + 1):
        m = _gain_lim(pre, tmp, g, lim)
        I, tp = m['I'], m['TP']
        print(f'  громкость, проход {n}: гейн {g:+.2f} dB, лимит {lim:.1f} dBFS -> I {I} LUFS, TP {tp}')
        key = (not in_norm(I, tp), tp > FINAL_TP, abs(I - FINAL_I))
        if best is None or key < best[0]:
            best = (key, dict(I=I, TP=tp, gain=round(g, 2), limit=round(lim, 2), passes=n, ok=in_norm(I, tp)))
            shutil.copy(tmp, out)
        if in_norm(I, tp):
            break
        if tp > FINAL_TP:                         # peaks: lower the ceiling, keep the gain, restart the secant
            lim -= tp - FINAL_TP + 0.1
            hist = []
            continue
        hist.append((g, I))
        if len(hist) >= 2 and abs(hist[-1][1] - hist[-2][1]) > 0.05 and abs(hist[-1][0] - hist[-2][0]) > 0.01:
            slope = (hist[-1][1] - hist[-2][1]) / (hist[-1][0] - hist[-2][0])
            slope = min(max(slope, 0.05), 1.0)
            step = (FINAL_I - I) / slope
        else:
            step = FINAL_I - I
        step = max(-12.0, min(12.0, step))
        g += step
    tmp.unlink(missing_ok=True)
    best[1]['passes_total'] = n
    return best[1]


def deliver(wd_final, out_final, rep):
    """Copy the final to out/ only when the loudness is in norm; else stop with exit 1 and leave it in work/."""
    if not rep['in_norm']:
        raise SystemExit(f"громкость вне нормы: I {rep['final_I']} LUFS, TP {rep['final_TP']} (нужно −14 ±0.5, TP ≤ −1.1) — "
                         f"файл оставлен в {wd_final}, в out/ не скопирован; проверить микс (report*.json → loop)")
    Path(out_final).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(wd_final, out_final)
    return Path(out_final)


def mix(ctx, spec, pl, wd, final, gfx):
    total = pl['total']; T = total + ctx.end_dur
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(wd / 'voice_raw.wav'), '-af', VOICE_FX, str(wd / 'voice.wav')])
    v = measure(wd / 'voice.wav')['I']; gv = VOICE_LUFS - v
    music, whoosh = music_file(ctx, spec), whoosh_file(ctx, spec)
    ins = ['-i', str(wd / 'voice.wav')]
    parts = [f"[0:a]volume={gv:.2f}dB,apad=whole_dur={T:.3f}[v]"]; labels = ['[v]']
    gm = gs = None
    if music:
        ins += ['-stream_loop', '-1', '-i', str(music)]; k = ins.count('-i') - 1
        gm = VOICE_LUFS + MUSIC_REL - measure(music)['I']
        parts.append(f"[{k}:a]atrim=end={T:.3f},volume={gm:.2f}dB,afade=t=in:d=0.8,afade=t=out:st={T - 1.5:.3f}:d=1.5[m]"); labels.append('[m]')
    if whoosh:
        ins += ['-i', str(whoosh)]; k = ins.count('-i') - 1
        tp = measure(whoosh)['TP']; gs = SFX_PEAK - tp
        hits = [(0.1, gs), (total, gs)]                       # under the hook and the end card
        if ctx.dyn:                                           # tiktok: quiet whoosh on every punch-in cut
            hits += [(p['s0'], DYN_SFX_PEAK - tp) for p in pl['pieces'] if p.get('punch') and p['s0'] > 0.6]
        for n, (t, g) in enumerate(hits):
            parts.append(f"[{k}:a]volume={g:.2f}dB,adelay={int(t * 1000)}|{int(t * 1000)}[s{n}]"); labels.append(f'[s{n}]')
    fc = ';'.join(parts) + ';' + ''.join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first[a]"
    # pass 1: the mix without the final gain, measured
    run(['ffmpeg', '-v', 'error', '-y', *ins, '-filter_complex', fc, '-map', '[a]', '-t', f'{T:.3f}', '-c:a', 'pcm_f32le', str(wd / 'mix_pre.wav')])
    loud = final_loop(wd / 'mix_pre.wav', wd / 'mix_final.m4a')
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(wd / 'video.mp4'), '-i', str(gfx), '-i', str(wd / 'mix_final.m4a'),
         '-filter_complex', f"[0:v]tpad=stop_mode=clone:stop_duration={ctx.end_dur}[v0];[v0][1:v]overlay=format=auto:shortest=1[vo]",
         '-map', '[vo]', '-map', '2:a', '-t', f'{T:.3f}', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', str(FPS),
         '-c:a', 'copy', '-movflags', '+faststart', str(final)])
    fin = measure(final)
    return dict(voice_lufs_pre=v, gain_voice=gv, gain_music=gm, gain_sfx=gs, music=str(music) if music else None,
                whoosh=str(whoosh) if whoosh else None, loop=loud, final_I=fin['I'], final_TP=fin['TP'],
                in_norm=abs(fin['I'] - FINAL_I) <= FINAL_TOL and fin['TP'] <= FINAL_TP)
