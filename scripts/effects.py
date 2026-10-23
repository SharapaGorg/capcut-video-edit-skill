"""Clone CapCut effect templates (assets/templates/*.json) into a draft.

Templates are harvested by harvest_templates.py; format and rules: references/capcut-format.md
("Шаблоны эффектов"). Placeholders: {{ID}} -> fresh id, {{CACHE}}/<cache_id>/<hash>/... -> the
actual Cache/effect dir found by find_effect_cache(cache_id), {{CAPCUT_APP}}/... -> newest
CapCut/Apps/<version> dir. Every {{ID}} gets its own fresh id (in the source project id and
constant_material_id differ, so they are not kept equal). Nothing is added to the draft if any placeholder cannot be resolved.
"""
from __future__ import annotations

import copy
import functools
import json
import re
import subprocess
import tempfile
from pathlib import Path

import common
from common import find_effect_cache, new_id

TEMPLATES = Path(__file__).resolve().parent.parent / "assets" / "templates"
_CACHE_RE = re.compile(r"^\{\{CACHE\}\}/([^/]+)(?:/([^/]+))?(/.*)?$")
_APP = "{{CAPCUT_APP}}/"


class EffectCacheMissing(RuntimeError):
    def __init__(self, name: str, resource_id: str):
        self.name, self.resource_id = name, resource_id
        super().__init__(f'Эффект "{name}" не найден в кэше CapCut (resource_id {resource_id}): '
                         "примените его в CapCut один раз вручную, затем повторите")


def load_template(name: str) -> dict:
    return json.loads((TEMPLATES / f"{name}.json").read_text(encoding="utf-8"))


def _app_dir(cache_root: Path | None) -> Path | None:
    root = Path(cache_root) if cache_root else common.EFFECT_CACHE
    if root is None:
        return None
    apps = root.parents[2] / "Apps"  # <CapCut>/User Data/Cache/effect -> <CapCut>/Apps
    vers = [d for d in apps.iterdir() if d.is_dir()] if apps.is_dir() else []
    key = lambda d: [int(x) if x.isdigit() else -1 for x in d.name.split(".")]  # noqa: E731
    return max(vers, key=key) if vers else None


def _resolve(obj, tpl: dict, cache_root):
    """Deep-copy with placeholders resolved. Raises EffectCacheMissing."""
    found: dict[str, Path | None] = {}
    app = []

    def res_str(s: str):
        if s == "{{ID}}":
            return new_id()
        m = _CACHE_RE.match(s)
        if m:
            cid, h, rest = m.group(1), m.group(2), m.group(3) or ""
            if cid not in found:
                found[cid] = find_effect_cache(cid, cache_root)
            d = found[cid]
            if d is None:
                raise EffectCacheMissing(tpl["name"], tpl.get("resource_id") or cid)
            if h:
                if not (d / h).is_dir():
                    subs = [x for x in d.iterdir() if x.is_dir()]
                    if not subs:  # empty cache dir -> dead path; CapCut would silently ignore the effect
                        raise EffectCacheMissing(tpl["name"], tpl.get("resource_id") or cid)
                    h = max(subs, key=lambda x: x.stat().st_mtime).name  # newest download
                d = d / h
            elif not any(d.iterdir()):
                raise EffectCacheMissing(tpl["name"], tpl.get("resource_id") or cid)
            return (d.as_posix() + rest)
        if s.startswith(_APP):
            if not app:
                app.append(_app_dir(cache_root))
            if app[0] is None:
                raise EffectCacheMissing(tpl["name"], tpl.get("resource_id") or "CapCut/Apps")
            return app[0].as_posix() + "/" + s[len(_APP):]
        return s

    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, str):
            return res_str(o)
        return o

    return walk(copy.deepcopy(obj))


def _set_dotted(d: dict, key: str, value) -> None:
    parts = key.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def _build(name: str, cache_root, overrides) -> tuple[dict, list[tuple[str, dict]]]:
    tpl = load_template(name)
    if not tpl.get("category") or tpl.get("material") is None or name in ("sfx_segment", "music_segment"):
        raise ValueError(f"template {name}: use the dedicated helper "
                         "(sfx_segment()/music_segment()/zoom_keyframes())")
    items = [(tpl["category"], tpl["material"])] + [(e["category"], e["material"]) for e in tpl.get("extra", [])]
    built = [(cat, _resolve(m, tpl, cache_root)) for cat, m in items]
    for k, v in overrides.items():
        _set_dotted(built[0][1], k, v)
    return tpl, built


def _append(draft: dict, built) -> list[str]:
    mats = draft.setdefault("materials", {})
    for cat, m in built:
        mats.setdefault(cat, []).append(m)
    return [m["id"] for _, m in built]


def make_all(name: str, draft: dict, cache_root=None, with_extras: bool = True, **overrides) -> list[str]:
    """Like make(), returns ids of the primary material and of all template extras (e.g. adjust_circle:
    temperature, saturation, hsl). Overrides apply to the primary material only."""
    _tpl, built = _build(name, cache_root, overrides)
    return _append(draft, built if with_extras else built[:1])


def make(name: str, draft: dict, cache_root=None, with_extras: bool = True, **overrides) -> str:
    """Clone template <name> into draft['materials'][<category>] (+ its extras unless with_extras=False), return
    primary id. Overrides: dotted keys into the primary material, e.g. **{'config.centerX': 0.5}."""
    return make_all(name, draft, cache_root=cache_root, with_extras=with_extras, **overrides)[0]


def attach(seg: dict, material_id: str) -> None:
    refs = seg.setdefault("extra_material_refs", [])
    if material_id not in refs:
        refs.append(material_id)


# ---- zoom ----
ZOOM_PROPS = ("KFTypeScaleX", "KFTypeScaleY", "KFTypePositionX", "KFTypePositionY")


def zoom_keyframes(seg: dict, t_in: float, t_hold: float | None, t_out: float | None, scale: float,
                   cx: float | None = None, cy: float | None = None, ramp_in: float | None = None) -> None:
    """Zoom on a segment; t_* in seconds of TIMELINE from the segment start.
    Keys: t_in (base) -> t_in + ramp_in (base*scale) -> t_hold (base*scale) -> t_out (base);
    ramp_in defaults to t_out - t_hold. t_hold = t_out = None: push-in, 2 keys (t_in base -> t_in + ramp_in zoomed),
    the zoom holds to the segment end. Base = current clip.scale (0.4 for the circle); clip.scale is untouched.
    cx/cy: clip.transform x/y at full zoom (1.0 = half the canvas, y up); Position keys go from the clip's current
    transform to cx/cy and back, only when cx or cy is given.
    CapCut format (checked on real projects): time_offset = SOURCE time of the key (source_timerange.start +
    offset x speed); uniform scale (clip uniform_scale.on; x == y if the flag is absent) -> only KFTypeScaleX. Replaces existing Scale/Position keys.
    ValueError if the keys are not increasing or fall outside the segment."""
    dur = seg["target_timerange"]["duration"]
    push = t_hold is None and t_out is None
    if push:
        if not ramp_in or ramp_in <= 0:
            raise ValueError("push-in needs ramp_in > 0")
        tl = [t_in, t_in + ramp_in]
    else:
        ramp = t_out - t_hold
        ri = ramp if ramp_in is None else ramp_in
        if ramp <= 0 or ri <= 0:
            raise ValueError(f"zoom ramps must be > 0 (in {ri}, out {ramp})")
        tl = [t_in, t_in + ri, t_hold, t_out]
    times = [common.us(t) for t in tl]
    ok = times[0] >= 0 and times[-1] <= dur and times[0] < times[1]
    if not push:
        ok = ok and times[1] <= times[2] < times[3]
    if not ok:
        raise ValueError(f"zoom keys {times} us must be increasing and within segment duration {dur} us")
    sp = float(seg.get("speed", 1.0))
    src0 = (seg.get("source_timerange") or {}).get("start", 0)
    offs = [src0 + int(round(t * sp)) for t in times]
    tpl = load_template("keyframes_zoom")
    clip = seg.get("clip") or {}
    sc, tr = clip.get("scale") or {}, clip.get("transform") or {}
    bx, by = float(sc.get("x", 1.0)), float(sc.get("y", 1.0))
    tx, ty = float(tr.get("x", 0.0)), float(tr.get("y", 0.0))

    def shape(base, top):
        return [base, top] if push else [base, top, top, base]

    props = {"KFTypeScaleX": shape(bx, bx * scale)}
    us_flag = (seg.get("uniform_scale") or {}).get("on")
    uniform = us_flag if us_flag is not None else abs(bx - by) <= 1e-9   # the clip's flag; x == y only without it
    if not uniform:
        props["KFTypeScaleY"] = shape(by, by * scale)
    if cx is not None or cy is not None:
        props["KFTypePositionX"] = shape(tx, tx if cx is None else cx)
        props["KFTypePositionY"] = shape(ty, ty if cy is None else cy)
    kept = [c for c in seg.get("common_keyframes") or [] if c.get("property_type") not in ZOOM_PROPS]
    for prop, vals in props.items():
        e = copy.deepcopy(tpl["entry"])
        e.update(id=new_id(), property_type=prop, keyframe_list=[])
        for t, v in zip(offs, vals):
            k = copy.deepcopy(tpl["keyframe"])
            k.update(id=new_id(), time_offset=t, values=[float(v)])
            e["keyframe_list"].append(k)
        kept.append(e)
    seg["common_keyframes"] = kept


def keyframes_inside(seg: dict) -> bool:
    """All keys of the segment lie within its source range (keys are in source time)."""
    st = seg.get("source_timerange") or {"start": 0, "duration": seg["target_timerange"]["duration"]}
    lo, hi = st["start"], st["start"] + st["duration"]
    return all(lo <= k["time_offset"] <= hi for c in seg.get("common_keyframes") or [] for k in c["keyframe_list"])


# ---- audio ----
def _audio_segment(name: str, draft, track, path, start_us, duration_us, volume) -> str:
    tpl = load_template(name)
    mat = _resolve(tpl["material"], tpl, None)
    p = str(path).replace("\\", "/")
    mat.update(path=p, name=Path(p).name, duration=int(duration_us))
    extras = [(e["category"], _resolve(e["material"], tpl, None)) for e in tpl.get("extra", [])]
    for cat, m in extras:
        if cat == "audio_fades":
            m["fade_out_duration"] = min(300_000, int(duration_us) // 2)
    _append(draft, [(tpl["category"], mat)] + extras)
    seg = _resolve(tpl["segment"], tpl, None)
    seg.update(material_id=mat["id"], extra_material_refs=[m["id"] for _, m in extras], volume=float(volume),
               source_timerange={"start": 0, "duration": int(duration_us)},
               target_timerange={"start": int(start_us), "duration": int(duration_us)})
    track.setdefault("segments", []).append(seg)
    return seg["id"]


def sfx_segment(draft: dict, track: dict, path, start_us: int, duration_us: int, volume: float) -> str:
    """Add an SFX audio material + segment to track; returns segment id. material.duration = duration_us
    (set the real file length afterwards if the clip is trimmed)."""
    return _audio_segment("sfx_segment", draft, track, path, start_us, duration_us, volume)


def music_segment(draft: dict, track: dict, path, start_us: int, duration_us: int, volume: float) -> str:
    """Like sfx_segment, with audio_fades. Deep: make('deep_effect', draft) + attach(seg, id)."""
    return _audio_segment("music_segment", draft, track, path, start_us, duration_us, volume)


def adjustment_segment(draft: dict, track: dict, start_us: int, duration_us: int, cache_root=None) -> str:
    """Adjustment block (Temp -18 / Sat 10) on a track of type adjust: placeholder material + effects + hsl,
    segment from the template; returns segment id. One continuous block per full-screen camera run."""
    tpl = load_template("adjustment_block")
    seg = _resolve(tpl["segment"], tpl, cache_root)
    ids = make_all("adjustment_block", draft, cache_root=cache_root)
    seg.update(material_id=ids[0], extra_material_refs=ids[1:], source_timerange=None,
               target_timerange={"start": int(start_us), "duration": int(duration_us)},
               enable_adjust=True, enable_hsl=True)
    track.setdefault("segments", []).append(seg)
    return seg["id"]


# ---- loudness (ffmpeg ebur128) ----
SR = 48000
SFX_LU = -12.0      # SFX / overlay sound = voice - 12 LU (rules.md, «Звук»)


def pcm(path, start: float = 0.0, dur: float | None = None, sr: int = SR):
    """Mono float32 samples of an audio/video file from start (s) for dur (s); empty array if there is no audio."""
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(start, 0):.6f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.6f}"]
    cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True)
    return np.frombuffer(out.stdout, dtype=np.float32).copy()


def _ebur128(samples, sr: int) -> str:
    """ffmpeg ebur128 framelog (stderr) of mono float32 samples padded with 0.5 s of silence."""
    import numpy as np
    x = np.concatenate([np.asarray(samples, dtype=np.float32), np.zeros(int(0.5 * sr), np.float32)])
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "a.f32"
        x.tofile(f)
        return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-f", "f32le", "-ar", str(sr), "-ac", "1",
                               "-i", str(f), "-af", "ebur128=framelog=info", "-f", "null", "-"],
                              capture_output=True, text=True).stderr


def loudness(samples, sr: int = SR) -> dict:
    """EBU R128 of mono float32 samples: {"I": integrated LUFS, "M_max": max momentary (400 ms) LUFS}.
    Padded with 0.5 s of silence, so a sound shorter than 400 ms has an M. -70 = silence."""
    err = _ebur128(samples, sr)
    ms = [float(v) for v in re.findall(r"\bM:\s*(-?[\d.]+)", err)]
    summ = err[err.rfind("Summary:"):] if "Summary:" in err else err
    m = re.search(r"I:\s*(-?[\d.]+) LUFS", summ)
    return {"I": float(m.group(1)) if m else -70.0, "M_max": max(ms) if ms else -70.0}


def short_term(samples, sr: int = SR):
    """Short-term (3 s window) loudness every 100 ms: (T, S) numpy arrays; T = window END time, s; S = LUFS
    (-inf for silence)."""
    import numpy as np
    err = _ebur128(samples, sr)
    rows = re.findall(r"\bt:\s*([\d.]+)\s+TARGET.*?\bS:\s*(-?[\d.]+|-inf|nan)", err)
    T = np.array([float(a) for a, _ in rows])
    S = np.array([float(b) if b not in ("-inf", "nan") else -np.inf for _, b in rows])
    n = len(samples) / sr
    keep = T <= n + 1e-6
    return T[keep], S[keep]


def encode(samples, out, sr: int = SR, args=()) -> Path:
    """Write mono float32 samples to an audio file (format by extension; extra ffmpeg args e.g. -b:a 160k)."""
    import numpy as np
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", *args, str(out)],
                   input=np.asarray(samples, dtype=np.float32).tobytes(), check=True)
    return out


def voice_pcm(cfg, draft: dict, a_us: int, b_us: int, sr: int = SR, roles=("voice", "screencast")):
    """The voice heard on the timeline in [a_us, b_us) as mono samples: leaf pieces of the given roles with volume > 0
    at speed 1 (sped voice is muted), each x its volume (compound chain included). -> (samples, got_any)."""
    import numpy as np
    n = int(round((b_us - a_us) * sr / 1e6))
    buf = np.zeros(n, np.float32)
    got = False
    for p in common.flatten(cfg, draft, roles):
        if (p["volume"] <= 0 or abs(p["speed"] - 1.0) > 1e-6 or p["src"] is None
                or p["end"] <= a_us or p["start"] >= b_us):
            continue
        x, y = max(p["start"], a_us), min(p["end"], b_us)
        a = pcm(p["path"], (p["src"] + (x - p["start"])) / 1e6, (y - x) / 1e6, sr) * float(p["volume"])
        i0 = int(round((x - a_us) * sr / 1e6))
        a = a[: max(0, n - i0)]
        buf[i0:i0 + len(a)] += a
        got = got or len(a) > 0
    return buf, got


def voice_lufs(cfg, draft: dict, a_us: int, b_us: int, sr: int = SR) -> float | None:
    """Integrated loudness of the voice heard on the timeline in [a_us, b_us) (voice_pcm). None if there is no
    voice there."""
    buf, got = voice_pcm(cfg, draft, a_us, b_us, sr)
    if not got:
        return None
    lu = loudness(buf, sr)["I"]
    return None if lu <= -69.9 else lu


# ---- SFX files and tracks (stage 6 zooms, stages 7–8 graphics) ----
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
SFX_TRACK = "SFX"


def sfx_files(cfg, names=None, n: int = 3) -> list[Path]:
    """SFX files in cfg.sfx_dir: the given names, else the first n audio files there (sorted).
    SystemExit with what to do when sfx_dir is unset / missing / has no such files."""
    if not cfg.sfx_dir:
        raise SystemExit("config.json → sfx_dir не задан: укажите папку со звуками SFX (вуши/клики) — "
                         "init_video.py --sfx DIR или поле sfx_dir в config.json")
    d = Path(cfg.sfx_dir)
    if not d.is_dir():
        raise SystemExit(f"sfx_dir не найден: {d}")
    files = [d / x for x in names] if names else sorted(p for p in d.iterdir() if p.suffix.lower() in AUDIO_EXT)[:n]
    missing = [str(p) for p in files if not p.is_file()]
    if missing or not files:
        raise SystemExit(f"SFX не найдены в {d}: {missing or 'нет аудиофайлов'}")
    return files


def new_sfx_track(draft: dict, name: str = SFX_TRACK) -> dict:
    t = {"id": new_id(), "type": "audio", "flag": 0, "attribute": 0, "name": name, "is_default_name": False,
         "segments": []}
    draft["tracks"].append(t)
    return t


def sfx_tracks(draft: dict) -> list[dict]:
    """Audio tracks named SFX, SFX 2, … (in draft order)."""
    return [t for t in draft["tracks"] if t["type"] == "audio" and re.fullmatch(rf"{SFX_TRACK}( \d+)?", t.get("name") or "")]


def file_len_us(path) -> int:
    return int(round(len(pcm(path)) * 1e6 / SR))


def place_sfx(draft: dict, path, start_us: int, volume: float, length_us: int) -> tuple[str, dict]:
    """An SFX segment at start_us on the first SFX track where it fits (nothing playing at start_us; trimmed to the
    next segment's start), else on a new track «SFX N». material.duration = the file length. -> (segment id, track)."""
    tracks = sfx_tracks(draft)
    for t in tracks:
        if any(s["target_timerange"]["start"] <= start_us < common.seg_end(s) for s in t["segments"]):
            continue
        nxt = min((s["target_timerange"]["start"] for s in t["segments"] if s["target_timerange"]["start"] > start_us),
                  default=None)
        dur = length_us if nxt is None else min(length_us, nxt - start_us)
        if dur * 2 >= length_us:            # at least half of the sound fits
            break
    else:
        t = new_sfx_track(draft, SFX_TRACK if not tracks else f"{SFX_TRACK} {len(tracks) + 1}")
        dur = length_us
    sid = sfx_segment(draft, t, Path(path).as_posix(), start_us, dur, volume)
    t["segments"] = common.by_start(t["segments"])
    seg = next(s for s in t["segments"] if s["id"] == sid)
    common.index(draft["materials"])[seg["material_id"]][1]["duration"] = length_us
    return sid, t


# ---- overlay video (graphics MOV) ----
CNEW = Path(__file__).resolve().parent.parent / "templates" / "capcut_new" / "templates.json"
V_EXTRAS = [("speeds", "speed"), ("placeholder_infos", "placeholder"), ("canvases", "canvas"),
            ("sound_channel_mappings", "sound_channel"), ("material_colors", "material_color"),
            ("vocal_separations", "vocal_separation")]
CLIP_FULL = {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "transform": {"x": 0.0, "y": 0.0},
             "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0}


@functools.lru_cache(maxsize=1)
def _cnew() -> dict:
    return json.loads(CNEW.read_text(encoding="utf-8"))


def overlay_video_segment(draft: dict, track: dict, path, start_us: int, duration_us: int, width: int,
                          height: int) -> tuple[dict, dict]:
    """A video material (has_audio false: graphics MOV with alpha) + a full-frame segment at start_us on track, from
    the capcut_new templates (V_EXTRAS cloned per segment, volume 0, no mask, no colour). -> (segment, material)."""
    T = _cnew()
    p = Path(path).as_posix()
    mat = copy.deepcopy(T["video"])
    mat.update(id=new_id(), path=p, material_name=Path(p).name, duration=int(duration_us), width=int(width),
               height=int(height), has_audio=False)
    M = draft["materials"]
    M.setdefault("videos", []).append(mat)
    refs = []
    for key, tk in V_EXTRAS:
        m = copy.deepcopy(T[tk])
        m["id"] = new_id()
        M.setdefault(key, []).append(m)
        refs.append(m["id"])
    seg = copy.deepcopy(T["video_segment"])
    ti = draft["tracks"].index(track) if track in draft["tracks"] else 0
    seg.update(id=new_id(), material_id=mat["id"], extra_material_refs=refs, speed=1.0, volume=0.0,
               last_nonzero_volume=1.0, source_timerange={"start": 0, "duration": int(duration_us)},
               target_timerange={"start": int(start_us), "duration": int(duration_us)}, common_keyframes=[],
               keyframe_refs=[], clip=copy.deepcopy(CLIP_FULL), uniform_scale={"on": True, "value": 1.0},
               enable_video_mask=False, enable_adjust=False, enable_hsl=False, track_attribute=0,
               render_index=ti, track_render_index=ti)
    track.setdefault("segments", []).append(seg)
    return seg, mat


def sfx_volume(voice_lu: float, sfx_path, offset_lu: float = SFX_LU, max_volume: float = 10.0) -> dict:
    """CapCut volume (linear gain: 1.0 = 0 dB, CapCut allows up to +20 dB = 10) for which the SFX peak momentary
    loudness = voice_lu + offset_lu. Returns {volume, volume_db, sfx_m_max, target, capped}."""
    m = loudness(pcm(sfx_path))["M_max"]
    target = voice_lu + offset_lu
    db = target - m
    vol = 10 ** (db / 20)
    return {"volume": round(min(vol, max_volume), 5), "volume_db": round(db, 2), "sfx_m_max": m,
            "target": round(target, 2), "capped": vol > max_volume}
