"""Captions layer over a finished rough render (voice only, no captions, no music).
Usage: run.py <auto_dir> <stage> [--base out/rough_v1.mp4] [--name captions_v1] [--stills 10,45,90] [--music file.mp3] [--sfx-dir dir] [--force]
The SFX pack folder (files — dictionary S in audio.py): --sfx-dir, else env CAPTIONS_SFX_DIR, else "sfx_dir" in assets/captions/local.json.

Stages:
  prep    cuts, person matte, head track, whisper words of the render  -> <auto>/work/captions/   (slow: matte ≈ 4 fps)
  layout  runs <auto>/captions/layout.py  -> gfx.html, sfx_events.json
  stills  layout + the listed frames composed -> work/captions/stills/, stills.png (look at them before rendering)
  render  layout + full video + both soundtracks + checks -> out/<name>.mp4, out/<name>_music.mp4, work/captions/report.json, sheet_*.png
  audio   layout + sound only (remix and remux onto the last rendered video)
"""
import json, os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).parent
ASSETS = HERE.parent.parent / "assets" / "captions"
PY = [sys.executable, "-I", "-X", "utf8"]
auto, stage = Path(sys.argv[1]).resolve(), sys.argv[2]
opt = lambda k, d=None: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
wd = auto / "work" / "captions"; wd.mkdir(parents=True, exist_ok=True)
jobf = wd / "job.json"
job = json.load(open(jobf, encoding="utf8")) if jobf.exists() else {}
if opt("--base"):
    b = Path(opt("--base")); b = b if b.is_absolute() else auto / b
    if job.get("base") != str(b): job = dict(base=str(b))
if "base" not in job: sys.exit("first run needs --base <rough render>")
job["name"] = opt("--name", job.get("name", "captions_v1"))
DEFAULT_MUSIC = str(ASSETS / "music" / "Hyperfun.mp3")
job["music"] = opt("--music", job.get("music", DEFAULT_MUSIC))
if not Path(job["music"]).exists(): job["music"] = DEFAULT_MUSIC          # a job saved before the skill moved
local = ASSETS / "local.json"
sfx_dir = (opt("--sfx-dir") or job.get("sfx_dir") or os.environ.get("CAPTIONS_SFX_DIR")
           or (json.load(open(local, encoding="utf8")).get("sfx_dir") if local.exists() else None))
if opt("--sfx-dir"): job["sfx_dir"] = sfx_dir
json.dump(job, open(jobf, "w", encoding="utf8"), ensure_ascii=False, indent=1)
base = job["base"]
force = "--force" in sys.argv

def sh(*cmd, **kw):
    print(">", " ".join(str(c) for c in cmd[2:] if c not in ("-X", "utf8"))[:160], flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)

def stale(out):
    return force or not out.exists() or out.stat().st_mtime < os.path.getmtime(base)

def prep():
    if stale(wd / "cuts.json"): sh(*PY, HERE / "cuts.py", base, wd / "cuts.json")
    cuts = json.load(open(wd / "cuts.json"))["cuts"]
    if stale(wd / "alpha.mkv"):
        sh(*PY, HERE / "matte.py", base, wd / "alpha.mkv", ASSETS / "rvm.onnx", ",".join(f"{c / 30:.4f}" for c in cuts), stdout=open(wd / "matte.log", "w"))
    if stale(wd / "heads.json"): sh(*PY, HERE / "heads.py", wd / "alpha.mkv", wd / "heads.json", stdout=subprocess.DEVNULL)
    if stale(wd / "voice.wav"): sh("ffmpeg", "-v", "error", "-y", "-i", base, "-vn", "-ac", "1", "-ar", "48000", wd / "voice.wav")
    if stale(wd / "words.json"): sh(*PY, HERE / "words.py", wd / "voice.wav", wd / "words.json", opt("--lang", "ru"))
    if stale(wd / "words_on.json"): sh(*PY, HERE / "prep.py", wd / "voice.wav", wd / "words.json", wd / "words_on.json")
    ws = json.load(open(wd / "words_on.json", encoding="utf8"))
    print("cuts (frames):", cuts)
    print("words (index:word@frame):", " ".join(f'{i}:{w["word"]}@{round(w["on"] * 30)}' for i, w in enumerate(ws)))

def layout():
    lay = auto / "captions" / "layout.py"
    if not lay.exists(): sys.exit(f"write {lay} first (see assets/examples/captions/ and references/captions/techniques.md)")
    sh(sys.executable, "-X", "utf8", lay, wd, env={**os.environ, "PYTHONPATH": str(HERE)})

def sheet(files, out, cols=8, tw=270):
    from PIL import Image
    ims = [Image.open(f).convert("RGB").resize((tw, tw * 16 // 9)) for f in files]
    rows = (len(ims) + cols - 1) // cols
    s = Image.new("RGB", (tw * min(cols, len(ims)), tw * 16 // 9 * rows))
    for i, im in enumerate(ims): s.paste(im, (tw * (i % cols), tw * 16 // 9 * (i // cols)))
    s.save(out)

def stills():
    fr = opt("--stills")
    if not fr: sys.exit("--stills f1,f2,...")
    sd = wd / "stills"
    for f in sd.glob("*.png"): f.unlink()
    sh(*PY, HERE / "compose.py", base, wd / "alpha.mkv", wd / "gfx.html", wd / "x.mp4", "--stills", fr, sd)
    sheet(sorted(sd.glob("f*.png")), wd / "stills.png", cols=6, tw=360)
    print("look at", wd / "stills.png")

def audio():
    if not sfx_dir or not Path(sfx_dir).is_dir(): sys.exit("SFX pack folder is not set: --sfx-dir <dir> (see references/captions/sound.md)")
    os.environ["CAPTIONS_SFX_DIR"] = str(sfx_dir)
    sh(*PY, HERE / "audio.py", base, wd / "sfx_events.json", wd / "audio_sfx.m4a")
    sh(*PY, HERE / "audio.py", base, wd / "sfx_events.json", wd / "audio_music.m4a", job["music"])
    outs = []
    for a, suf in (("audio_sfx.m4a", ""), ("audio_music.m4a", "_music")):
        o = auto / "out" / f'{job["name"]}{suf}.mp4'
        sh("ffmpeg", "-v", "error", "-y", "-i", wd / "video.mp4", "-i", wd / a, "-map", "0:v", "-map", "1:a", "-c", "copy", "-movflags", "+faststart", o)
        outs.append(o)
    return outs

def check(outs):
    import re
    rep = {}
    probe = lambda p, e: subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", e, "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip().strip(",")
    rep["base"] = probe(base, "stream=width,height,nb_frames"); bad = []
    for o in outs:
        v = probe(o, "stream=width,height,nb_frames")
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(o), "-af", "loudnorm=print_format=json", "-f", "null", "-"], capture_output=True, text=True, encoding="utf8", errors="ignore")
        j = json.loads(re.findall(r"\{[^{}]+\}", r.stderr)[-1])
        rep[o.name] = dict(video=v, lufs=float(j["input_i"]), true_peak=float(j["input_tp"]))
        if v != rep["base"]: bad.append(f"{o.name}: video {v} != base {rep['base']}")
        if abs(float(j["input_i"]) + 14) > 0.6 or float(j["input_tp"]) > -1: bad.append(f"{o.name}: loudness {j['input_i']} LUFS, peak {j['input_tp']}")
    ck = json.load(open(wd / "video.check.json"))
    sil = json.load(open(wd / "sfx_events.json"))["sil"]              # ribbons leave the frame and the title sits under the head there on purpose
    in_sil = lambda f: any(a <= int(f) < b for a, b, _ in sil)
    out_of = {f: b for f, b in ck["boxes"].items() if (b[0] < 30 or b[2] > 1050) and not in_sil(f)}
    if out_of: bad.append(f"text touches the frame edge on frames {list(out_of)[:12]}")
    cov = ck["cover"]
    rep["behind_text_cover"] = dict(min=min(cov.values(), default=None), max=max(cov.values(), default=None))
    hidden = [f for f, c in cov.items() if c > 0.6 and not in_sil(f)]
    if hidden: bad.append(f"behind-text is more than 60 % hidden by the person on frames {hidden[:12]}")
    rep["problems"] = bad
    json.dump(rep, open(wd / "report.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
    # contact sheets: every 6th frame
    tmp = wd / "sheet_frames"; tmp.mkdir(exist_ok=True)
    for f in tmp.glob("*.jpg"): f.unlink()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(outs[0]), "-vf", r"select=not(mod(n\,6)),scale=270:480", "-vsync", "0", "-q:v", "4", str(tmp / "%04d.jpg")], check=True)
    fs = sorted(tmp.glob("*.jpg"))
    for old in wd.glob("sheet_*.png"): old.unlink()
    for i in range(0, len(fs), 32): sheet(fs[i:i + 32], wd / f"sheet_{i // 32:02d}.png")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print("READ every", wd / "sheet_*.png", "(each tile = 6 frames = 0.2 s) before reporting")

if stage == "prep": prep()
elif stage == "layout": layout()
elif stage == "stills": layout(); stills()
elif stage == "audio": layout(); check(audio())
elif stage == "render":
    layout()
    sh(*PY, HERE / "compose.py", base, wd / "alpha.mkv", wd / "gfx.html", wd / "video.mp4", stdout=open(wd / "compose.log", "w"))
    check(audio())
else: sys.exit(__doc__)
