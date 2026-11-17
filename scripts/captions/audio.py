"""Sound design for the captions layer: the base render's voice + a sound on every move (+ optional music).
Usage: audio.py base.mp4 sfx_events.json out.m4a [music.mp3]   -> -14 LUFS, TP <= -1
Events are [sound, seconds, peak dBFS]; the sound's `at` point (its hit) lands on that time."""
import json, os, re, subprocess, sys
import numpy as np

base, ev_f, out = sys.argv[1:4]
music = sys.argv[4] if len(sys.argv) > 4 else None
SR = 48000
A = os.environ["CAPTIONS_SFX_DIR"].replace("\\", "/").rstrip("/") + "/"     # the SFX pack folder, set by run.py
P = A + "Old Sport SFX Pack/"
# name: (file, segment start, segment end, hit point inside the file, fade-in s, fade-out s)
S = {
    "impact":    (P + "Разгоны+удары/Импакт.wav", 0.30, 2.30, 0.52, 0.0, 1.2),
    "impact2":   (P + "Разгоны+удары/Импакт 5.wav", 0.40, 2.00, 0.53, 0.0, 1.0),
    "bell":      (P + "Разгоны+удары/Импакт (колокольчик).wav", 0.40, 1.75, 0.53, 0.0, 0.5),
    "riser":     (P + "Разгоны+удары/Разгон.wav", 1.85, 2.98, 2.93, 0.5, 0.03),
    "thump":     (A + "ПЕРЕХОДЫ/быстрый свуш .mp3", 0.10, 0.50, 0.27, 0.02, 0.1),
    "cut_cam":   (P + "Для Переходов (вуши)/вуш с камерой.wav", 0.45, 1.00, 0.69, 0.02, 0.1),
    "cut_cam2":  (P + "Для Переходов (вуши)/вуш с камерой 2.wav", 0.20, 0.65, 0.39, 0.02, 0.1),
    "cut_click": (P + "Для Переходов (вуши)/вуш с щелчком.wav", 0.05, 0.55, 0.31, 0.02, 0.1),
    "cut_long":  (P + "Для Переходов (вуши)/затяжной вуш.wav", 0.60, 1.60, 1.11, 0.05, 0.2),
    "swish1":    (P + "Для появления (вуши)/короткий вуш.wav", 0.0, 0.20, 0.03, 0.0, 0.05),
    "swish2":    (P + "Для появления (вуши)/короткий вуш 2.wav", 0.0, 0.20, 0.05, 0.0, 0.05),
    "swish3":    (P + "Для появления (вуши)/короткий вуш 3.wav", 0.0, 0.15, 0.05, 0.0, 0.04),
    "focus":     (A + "CAPCUT_БИБЛИОТЕКА/Sound when the lens is in focus.mp3", 0.0, 0.20, 0.09, 0.0, 0.03),
    "scan":      (A + "CAPCUT_БИБЛИОТЕКА/Scanning.mp3", 0.0, 0.85, 0.0, 0.05, 0.2),
    "shutter":   (P + "Фото - щелчки/фото (весомый).wav", 0.05, 0.75, 0.11, 0.0, 0.2),
    "blip":      (A + "ПОЯВЛЕНИЕ_ТЕКСТА/creatorshome-digital-click-357350.mp3", 0.0, 0.30, 0.04, 0.0, 0.08),
    "accent":    (P + "Интерфейсы/тактильный щелчок.wav", 0.0, 0.18, 0.03, 0.0, 0.03),
    "tact":      (P + "Интерфейсы/тактильный щелчок.wav", 0.0, 0.18, 0.03, 0.0, 0.03),
    "ui":        (A + "ЭФФЕКТЫ/КОРОТКИЕ/Modern UI - Perfect Click.mp3", 0.70, 1.00, 0.78, 0.0, 0.05),
    "mouse":     (A + "ЭФФЕКТЫ/КОРОТКИЕ/Клик мышкой.wav", 0.15, 0.40, 0.20, 0.0, 0.05),
    "ding":      (P + "Интерфейсы/Уведомление 6.wav", 0.0, 0.40, 0.10, 0.0, 0.1),
    "ding2":     (P + "Интерфейсы/Уведомление 2.wav", 0.0, 0.25, 0.0, 0.0, 0.08),
    "keysolo":   (P + "Клавиатура - мышь/клавиатура соло.wav", 0.0, 0.15, 0.01, 0.0, 0.03),
    "snap":      (P + "Фото - щелчки/щелчки 3.wav", 0.0, 0.15, 0.04, 0.0, 0.04),
    "counter":   (A + "ЭФФЕКТЫ/ДЛИННЫЕ/счетчик.mp3", 0.12, 0.80, 0.15, 0.0, 0.05),
    "typing":    (P + "Клавиатура - мышь/клавиатура (печать).wav", 0.03, 0.58, 0.03, 0.0, 0.04),
    "doom":      (A + "ЭФФЕКТЫ/ДЛИННЫЕ/downers 2.wav", 0.0, 1.5, 0.0, 0.03, 0.7),
    "glitch":    (P + "Глитчи/Глитч 5.wav", 0.55, 1.0, 0.72, 0.02, 0.1),
    "tick":      (P + "Фото - щелчки/щёлк.wav", 0.0, 0.10, 0.01, 0.0, 0.03),
}
MUSIC_REL, MUSIC_FROM, TARGET = -12.0, 20.0, -14.0
job = json.load(open(ev_f))
EVENTS, MUSIC_IN = job["events"], job["music_open"]      # the music is muffled under the hook and opens on the cut at MUSIC_IN

def load(path, pre=None):
    import glob, os
    if not os.path.exists(path):                       # some pack names carry odd spaces
        import unicodedata as u                        # ...or decomposed «й»/«ё»
        d = os.path.dirname(path); key = u.normalize("NFC", os.path.basename(path)).replace(" ", "")
        path = d + "/" + next(n for n in os.listdir(d) if u.normalize("NFC", n).replace(" ", "").replace(" ", "") == key)
    cmd = ["ffmpeg", "-v", "error", "-i", path] + (["-af", pre] if pre else []) + ["-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32).reshape(-1, 2).copy()

def measure(path, pre=""):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", pre + "loudnorm=print_format=json", "-f", "null", "-"], capture_output=True, text=True, encoding="utf8", errors="ignore")
    j = json.loads(re.findall(r"\{[^{}]+\}", r.stderr)[-1])
    return float(j["input_i"]), float(j["input_tp"])

def write(path, a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "pcm_f32le", path], input=a.astype(np.float32).tobytes(), check=True)

voice = load(base)
N = len(voice)
mix = voice.copy()
sfx = np.zeros_like(mix)
cache = {}
for name, t, db in EVENTS:
    f, s0, s1, at, fi, fo = S[name]
    if f not in cache: cache[f] = load(f)
    c = cache[f][int(s0 * SR):int(s1 * SR)].copy()
    if fi: n = int(fi * SR); c[:n] *= np.linspace(0, 1, n)[:, None] ** 2
    if fo: n = min(len(c), int(fo * SR)); c[-n:] *= np.linspace(1, 0, n)[:, None] ** 2
    c *= 10 ** (db / 20) / max(1e-6, np.abs(c).max())
    i = int(round((t - (at - s0)) * SR))
    if i < 0: c, i = c[-i:], 0
    c = c[:max(0, N - i)]
    sfx[i:i + len(c)] += c
mix += sfx
if music:
    dur = N / SR
    vi, _ = measure(base)
    mi, _ = measure(music, f"atrim={MUSIC_FROM}:{MUSIC_FROM + dur},")
    g = 10 ** ((vi + MUSIC_REL - mi) / 20)
    seg = f"atrim={MUSIC_FROM}:{MUSIC_FROM + dur + 0.1},asetpts=PTS-STARTPTS,"
    full = load(music, seg + "highshelf=g=-5:f=5000")[:N] * g
    muf = load(music, seg + "lowpass=f=420,lowpass=f=420")[:N] * g * 1.25
    k = np.clip((np.arange(N) / SR - (MUSIC_IN - 0.12)) / 0.12, 0, 1)[:, None] if MUSIC_IN > 0.2 else np.ones((N, 1))   # opens over the last 4 frames before the cut
    m = muf * (1 - k) + full * k
    m[:int(0.25 * SR)] *= np.linspace(0, 1, int(0.25 * SR))[:, None]
    m[-SR:] *= np.linspace(1, 0, SR)[:, None]
    mix += m
    print(f"music gain {20 * np.log10(g):.1f} dB (voice {vi:.1f} LUFS, music {mi:.1f} LUFS)")
pre = out + ".pre.wav"
write(pre, mix)
write(out + ".sfx.wav", sfx)
gain = 0.0
for _ in range(4):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", pre, "-af", f"volume={gain:.2f}dB,alimiter=limit=0.8:level=disabled:attack=2:release=40",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out], check=True)
    i, tp = measure(out)
    print(f"gain {gain:+.2f} dB -> {i:.2f} LUFS, TP {tp:.2f}")
    if abs(i - TARGET) <= 0.3: break
    gain += TARGET - i
