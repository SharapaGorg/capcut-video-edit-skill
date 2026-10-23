"""Shorts / Reels / TikTok (scripts/shorts): plan on synthetic stage3 maps, durations, voice chain, cam_lut config."""
import inspect
import json
from pathlib import Path

import numpy as np
import pytest

import build
import build_render
import cam_lut

EXAMPLE = Path(__file__).resolve().parent.parent / "assets" / "examples" / "specs" / "example.json"


def tm_seg(path: Path, a: float, b: float, role: str, src0: float, track: str = "track0") -> dict:
    return {"track": track, "track_type": "video", "compound": None, "segment_id": f"{path.name}@{a}", "kind": "videos",
            "name": path.name, "file": path.as_posix(), "role": role,
            "timeline_in_us": int(a * 1e6), "timeline_out_us": int(b * 1e6),
            "source_in_us": int(src0 * 1e6), "source_out_us": int((src0 + b - a) * 1e6),
            "flat_id": f"{path.name}@{int(a * 1e6)}", "speed": 1.0, "volume": 1.0}


def speech(a: float, b: float, file: str, src_off: float) -> list[dict]:
    """0.3-s words every 0.35 s, a 0.6-s pause after every 8th word (the planner cuts pauses > 0.3 s)."""
    out, t, k = [], a, 0
    while t + 0.3 <= b:
        k += 1
        out.append({"word": f"слово{k}" + ("." if k % 8 == 0 else ""), "start": round(t, 3), "end": round(t + 0.3, 3),
                    "file": file, "file_start": round(src_off + t, 3)})
        t += 0.35 + (0.6 if k % 8 == 0 else 0.0)
    return out


def shorts_work(tmp_path: Path, cam=True, f_rows=None, length=600.0) -> Path:
    """Work dir of a video: stage3 maps (screencast on the main track, optional camera circle), words over the whole
    timeline, optional layout/layout.json; config.json -> its path. Media files exist (empty: the plan only checks)."""
    src = tmp_path / "src"
    for d in ("camera", "screencasts"):
        (src / d).mkdir(parents=True, exist_ok=True)
    sc = src / "screencasts" / "sc.mp4"
    cf = src / "camera" / "cam.mov"
    sc.write_bytes(b"")
    cf.write_bytes(b"")
    tracks = [{"index": 0, "name": "", "type": "video", "segments": [tm_seg(sc, 0, length, "screencast", 100.0)]}]
    if cam:
        tracks.append({"index": 1, "name": "Кружок камеры", "type": "video",
                       "segments": [tm_seg(cf, 0, length, "camera", 50.0, "track1")]})
    work = tmp_path / "work"
    (work / "stage3").mkdir(parents=True)
    (work / "stage3" / "timeline_map.json").write_text(json.dumps({"duration_us": int(length * 1e6), "fps": 30,
                                                                    "tracks": tracks}), encoding="utf-8")
    words = speech(0.2, length - 1, "sc.mp4", 100.0)
    (work / "stage3" / "transcript_timeline.json").write_text(json.dumps(
        {"duration": length, "segments": [{"id": 0, "start": 0, "end": length, "text": "", "words": words}]},
        ensure_ascii=False), encoding="utf-8")
    if f_rows is not None:
        (work / "layout").mkdir()
        (work / "layout" / "layout.json").write_text(json.dumps({"layout": f_rows}), encoding="utf-8")
    cfg = {"project_dir": str(tmp_path / "proj"), "timeline_id": "x",
           "sources": {"camera": str(src / "camera"), "screencasts": str(src / "screencasts"), "voice": None},
           "work_dir": str(work), "master_render": None, "tiktok_channel": None}
    p = work / "config.json"
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return p


SPEC = {"id": "t1", "slug": "t", "title": "тест", "ranges": [{"tl": [10.0, 30.0]}],
        "hook": {"kicker": "Тема", "lines": ["строка"]}}


# ---------- plan ----------
def test_plan_without_full_camera_ranges(tmp_path):
    """No F anywhere (no layout.json, no camera on the main track), no `layout: full` in the spec: the plan is built,
    every piece is the stack (camera on top + screencast), there are no zoom accents."""
    ctx = build.load(shorts_work(tmp_path))
    pl = build.plan(ctx, SPEC)
    assert pl["pieces"] and {p["layout"] for p in pl["pieces"]} == {"stack"}
    assert all(p["cam"] and p["sc"] and p["aud"] for p in pl["pieces"])
    assert 15.0 < pl["total"] < 20.0                    # 20 s of range minus the cut pauses
    assert pl["captions"] and all(c["t_in"] >= 2.4 + 0.25 for c in pl["captions"])   # captions after the hook
    # no full-screen camera -> no zoom accents (zoom only on F)
    env = np.full(int(pl["total"] * 100) + 10, 0.1, np.float32)
    build_render.zoom_plan(pl, {"accents": ["слово"]}, env, dyn=False)
    assert pl["zoom_keys"]["bumps"] == []


def test_plan_screencast_only_and_layout_f(tmp_path):
    """No camera at all -> screencast on full screen ('scfull'); an F row of layout.json -> camera on full screen."""
    ctx = build.load(shorts_work(tmp_path, cam=False))
    pl = build.plan(ctx, SPEC)
    assert {p["layout"] for p in pl["pieces"]} == {"scfull"}

    ctx = build.load(shorts_work(tmp_path / "f", f_rows=[{"start": 0, "end": 20.0, "layout": "F"},
                                                         {"start": 20.0, "end": 600.0, "layout": "S"}]))
    pl = build.plan(ctx, SPEC)
    lay = [(round(p["tl0"], 2), p["layout"]) for p in pl["pieces"]]
    assert {x for t, x in lay if t < 19.9} == {"full"} and {x for t, x in lay if t >= 20.0} == {"stack"}
    assert any(abs(p["tl1"] - 20.0) < 1e-6 for p in pl["pieces"])      # cut on the F/S boundary
    assert all(p["sc"] is None and p["cam"]["file"].endswith("cam.mov") for p in pl["pieces"] if p["layout"] == "full")


# ---------- durations ----------
def test_reels_duration_le_30(tmp_path):
    """The example spec built with --reels: its own ranges, 4-s CTA card, <= 30 s in all; a longer reel is refused."""
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    ctx = build.load(shorts_work(tmp_path), mode="reels")
    s = build.mode_spec(ctx, spec)
    assert s["ranges"] == spec["reels"]["ranges"]
    pl = build.plan(ctx, s)
    assert ctx.end_dur == 4.0 and abs(pl["total_with_end"] - pl["total"] - 4.0) < 1e-9
    assert pl["total_with_end"] <= 30.0
    build.check_duration(ctx, pl)                       # within the limit -> no error

    long = dict(s, ranges=[{"tl": [100.0, 140.0]}])
    with pytest.raises(SystemExit, match="30"):
        build.check_duration(ctx, build.plan(ctx, long))


def test_tiktok_end_card_channel(tmp_path, capsys):
    """TikTok: <= 15 s with a 2.5-s end card; unknown channel -> no invented name, «ИЩИ ПО НАЗВАНИЮ» + a warning."""
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    ctx = build.load(shorts_work(tmp_path), mode="tiktok")
    pl = build.plan(ctx, build.mode_spec(ctx, spec))
    assert ctx.end_dur == 2.5 and pl["total_with_end"] <= 15.0
    html = build.html_end(ctx, spec, pl)
    assert "ИЩИ ПО НАЗВАНИЮ" in html and "КАНАЛ" not in html and "<img" not in html
    assert "tiktok_channel" in capsys.readouterr().out
    ctx.cfg.tiktok_channel = "Мой канал"
    assert "Полное видео на YouTube: Мой канал" in build.html_end(ctx, spec, pl)


# ---------- sound ----------
def test_voice_fx_no_afftdn(tmp_path):
    """No second noise reduction; no voice stretching: atempo only through tempo_af, for pieces sped in the project."""
    assert "afftdn" not in build_render.VOICE_FX and "atempo" not in build_render.VOICE_FX
    assert build_render.SPEED == 1.0
    assert build_render.tempo_af(1.0) == "" and "atempo=1.100000" in build_render.tempo_af(1.1)
    src = inspect.getsource(build_render)
    body = inspect.getsource(build_render.tempo_af)
    assert src.count("atempo") == body.count("atempo")
    p = {"dur": 1.0, "src_dur": 1.0, "aud": {"file": "a.wav", "start": 0.0, "speed": 1.0, "gain": 1.0}}
    assert "atempo" not in " ".join(build_render.audio_cmd(p, tmp_path / "o.wav", 1.0))
    p["aud"]["speed"] = 1.25
    assert "atempo=1.250000" in " ".join(build_render.audio_cmd(p, tmp_path / "o.wav", 1.0))


# ---------- camera colour ----------
def test_cam_lut_requires_master_render(tmp_path):
    cp = shorts_work(tmp_path)
    with pytest.raises(SystemExit, match="master_render"):
        cam_lut.main(["--config", str(cp)])
    raw = json.loads(cp.read_text(encoding="utf-8"))
    raw["master_render"] = str(tmp_path / "nope.mp4")
    cp.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(SystemExit, match="не найден"):
        cam_lut.main(["--config", str(cp)])
    # the decode chain of the build = the calibration chain
    ctx = build.load(cp)
    assert build_render.camlut(ctx).startswith(cam_lut.SRC_VF + ",lut3d=file=")
    assert "stage12_shorts" in build_render.camlut(ctx) and "cam.cube" in build_render.camlut(ctx)


def test_music_and_whoosh_dirs(tmp_path, capsys):
    """music_dir / sfx_dir unset -> mixed without them (a warning); set -> first music file, first «вуш» file."""
    ctx = build.load(shorts_work(tmp_path))
    assert build_render.music_file(ctx, {}) is None and build_render.whoosh_file(ctx, {}) is None
    out = capsys.readouterr().out
    assert "music_dir" in out and "sfx_dir" in out
    md, sd = tmp_path / "music", tmp_path / "sfx" / "pack"
    md.mkdir()
    sd.mkdir(parents=True)
    for p in (md / "b.mp3", md / "a.mp3", sd / "click.wav", sd / "короткий вуш.wav"):
        p.write_bytes(b"")
    ctx.cfg.music_dir, ctx.cfg.sfx_dir = str(md), str(tmp_path / "sfx")
    assert build_render.music_file(ctx, {}).name == "a.mp3"
    assert build_render.music_file(ctx, {"music": "b.mp3"}).name == "b.mp3"
    assert build_render.whoosh_file(ctx, {}).name == "короткий вуш.wav"
    with pytest.raises(SystemExit):
        build_render.whoosh_file(ctx, {"whoosh": "нет.wav"})


def test_cam_lut_candidates(tmp_path):
    """Calibration moments: evenly inside the ranges, off their edges; no camera in the master maps -> clear error."""
    ts = cam_lut.sample_times([(10.0, 20.0), (30.0, 31.5)], n=6)
    assert len(ts) == 6 and all(10.5 <= t <= 19.5 or 30.5 <= t <= 31.0 for t in ts)
    assert cam_lut.sample_times([(0.0, 0.8)]) == []
    cp = shorts_work(tmp_path, cam=False)
    raw = json.loads(cp.read_text(encoding="utf-8"))
    (tmp_path / "master.mp4").write_bytes(b"")
    raw["master_render"] = str(tmp_path / "master.mp4")
    cp.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(SystemExit, match="нет камеры"):
        cam_lut.main(["--config", str(cp)])


# ---------- fix round 1 ----------
def peaky_voice(path: Path, seconds=8.0, sr=48000):
    """Speech-like: 200-Hz buzz in syllable bursts at about −26 LUFS with sharp spikes near 0 dBFS (crest ~25 dB)."""
    rng = np.random.default_rng(3)
    t = np.arange(int(seconds * sr)) / sr
    env = np.clip(np.sin(2 * np.pi * 3.0 * t), 0, None) ** 2
    x = 0.04 * env * (np.sign(np.sin(2 * np.pi * 200 * t)) * 0.5 + 0.5 * rng.standard_normal(len(t)))
    for k in rng.integers(0, len(t) - 200, 40):
        x[k:k + 60] += 0.95 * np.hanning(60) * rng.choice([-1, 1])
    import subprocess
    raw = path.with_suffix(".f32")
    x.astype(np.float32).tofile(raw)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", str(raw),
                    "-c:a", "pcm_f32le", str(path)], check=True)
    raw.unlink()
    return path


def test_final_loop_converges_and_refuses_out_of_norm(tmp_path):
    pre = peaky_voice(tmp_path / "mix_pre.wav")
    r = build_render.final_loop(pre, tmp_path / "mix_final.m4a")
    m = build_render.measure(tmp_path / "mix_final.m4a")
    assert r["ok"] and abs(m["I"] + 14) <= 0.5 and m["TP"] <= -1.1, (r, m)
    # forced non-convergence: one pass only -> not in norm; delivery refuses, nothing in out/
    r1 = build_render.final_loop(pre, tmp_path / "one.m4a", iters=1)
    assert not r1["ok"]
    wfinal = tmp_path / "work" / "final.mp4"
    wfinal.parent.mkdir()
    wfinal.write_bytes(b"x")
    out = tmp_path / "out" / "01_x.mp4"
    with pytest.raises(SystemExit, match="вне нормы"):
        build_render.deliver(wfinal, out, {"in_norm": False, "final_I": r1["I"], "final_TP": r1["TP"]})
    assert not out.exists() and wfinal.exists()
    assert build_render.deliver(wfinal, out, {"in_norm": True}).is_file()


def test_cam_lut_align_flat_frame():
    """A flat frame has no ORB descriptors: not aligned, no crash."""
    flat = np.full((216, 384, 3), 0.5, np.float32)
    assert cam_lut.align(flat, flat) == (None, 0)
    rng = np.random.default_rng(0)
    noise = rng.random((216, 384, 3)).astype(np.float32)
    A, n = cam_lut.align(noise, flat)
    assert A is None or n < cam_lut.MIN_INLIERS


def test_whoosh_needs_hint_name(tmp_path):
    ctx = build.load(shorts_work(tmp_path))
    (tmp_path / "sfx").mkdir()
    (tmp_path / "sfx" / "click.wav").write_bytes(b"")
    ctx.cfg.sfx_dir = str(tmp_path / "sfx")
    with pytest.raises(SystemExit, match="whoosh"):
        build_render.whoosh_file(ctx, {})


def test_extend_piece_shifts_keys_and_mute(tmp_path):
    ctx = build.load(shorts_work(tmp_path))
    ctx.speed = 1.0
    p = {"tl0": 10.0, "tl1": 12.0, "s0": 0.0, "dur": 2.0, "src_dur": 2.0, "layout": "stack", "zoom": None,
         "sc": {"file": "sc.mp4", "start": 110.0, "speed": 1.0, "name": "sc.mp4"}, "cam": None,
         "aud": {"file": "sc.mp4", "start": 110.0, "speed": 1.0, "name": "sc.mp4", "gain": 1.0},
         "keys": [{"t": 0.0, "zoom": [0, 0, 900, 900], "ease": 0.6}, {"t": 2.5, "zoom": [100, 0, 900, 900], "ease": 0.6}],
         "mute": [[0.5, 1.0]]}
    pieces, words = [p], []
    d = build.extend_piece(ctx, p, 113.0, 2.0, pieces, words)
    e = pieces[-1]
    assert abs(d - 1.0) < 1e-9 and e["s0"] == 2.0 and e["sc"]["start"] == 112.0
    assert [k["t"] for k in e["keys"]] == [-2.0, 0.5] and "mute" not in e
    assert words and all(2.0 <= w["start"] < 3.0 for w in words)


def test_graphics_keep_shorts_timings(tmp_path):
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    ctx = build.load(shorts_work(tmp_path))
    s = dict(spec, cards=[{"tl_in": 412.0, "tl_out": 418.0, "title": "Т", "items": [{"text": "a"}]}])
    pl = build.plan(ctx, s)
    html = build.build_html(ctx, s, pl, tmp_path).read_text(encoding="utf-8")
    import re
    for cls in ("kicker", "plate", "row"):
        tags = re.findall(r'<(?:span|div) class="' + cls + r'[^"]*" data-in[^>]*>', html)
        tags = [t for t in tags if 'data-dist="40"' in t]
        assert tags and all('data-dur="0.22" data-odur="0.25"' in t for t in tags), cls


def test_concat_list_survives_quote_in_path(tmp_path):
    """M4: a ' in the work-dir path must not break the ffmpeg concat list."""
    import subprocess
    import build_render
    wd = tmp_path / "it's work"
    (wd / "pieces").mkdir(parents=True)
    out = tmp_path / "o'ut"
    out.mkdir()
    files = []
    for i, d in enumerate((wd / "pieces", wd / "pieces", out)):
        f = d / f"{i:03d}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=0.5", str(f)], check=True)
        files.append(f)
    lst = build_render.concat_list(wd / "audio.txt", files)
    assert "file 'pieces/000.wav'" in lst.read_text(encoding="utf-8")
    res = wd / "all.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(res)],
                   check=True)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(res)],
                               capture_output=True, text=True).stdout)
    assert abs(dur - 1.5) < 0.05
