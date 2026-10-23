import json
import shutil
from pathlib import Path

import numpy as np
import pytest

import common

MEDIA = Path(__file__).parent / "fixtures" / "media"


@pytest.fixture
def cache(tmp_path):
    """Fake CapCut layout: <tmp>/capcut/User Data/Cache/effect/<id>/<hash>, <tmp>/capcut/Apps/9.9.0/..."""
    base = tmp_path / "capcut"
    root = base / "User Data" / "Cache" / "effect"
    for rid in ("7491147795483659521", "1068046525", "7501974767453474064"):
        (root / rid / "h").mkdir(parents=True)
    (base / "Apps" / "9.9.0" / "Resources" / "audiosami").mkdir(parents=True)
    return root


@pytest.fixture
def dump(tmp_path, monkeypatch):
    """A «свалка» project made by capcut_new_project from fixture media (camera, 2 screencasts, no voice/)."""
    import capcut_new_project as cnp
    monkeypatch.setattr(cnp, "ensure_capcut_closed", lambda: None)
    monkeypatch.setattr(common, "ensure_capcut_closed", lambda: None)

    def make(layout, pairs, layout_f=None):
        src = tmp_path / "src"
        for sub, names in layout.items():
            (src / sub).mkdir(parents=True)
            for n in names:
                shutil.copy(MEDIA / n, src / sub / n)
        dst = tmp_path / "projects"
        dst.mkdir()
        (dst / "root_meta_info.json").write_text(json.dumps(
            {"all_draft_store": [], "draft_ids": 0, "root_path": dst.as_posix()}), encoding="utf-8")
        proj = cnp.create_project("zz-dump", cnp.sources_from_dir(src), dst_root=dst)
        work = tmp_path / "work"
        (work / "layout").mkdir(parents=True)
        (work / "layout" / "assembly.json").write_text(json.dumps({"pairs": pairs}), encoding="utf-8")
        if layout_f:
            (work / "layout" / "layout.json").write_text(json.dumps(
                {"layout": [{"start": a, "end": b, "layout": "F"} for a, b in layout_f]}), encoding="utf-8")
        voice = src / "voice"
        cfg = {"project_dir": str(proj), "timeline_id": None, "work_dir": str(work),
               "sources": {"camera": str(src / "camera"), "screencasts": str(src / "screencasts"),
                           "voice": str(voice) if voice.is_dir() else None}}
        cp = work / "config.json"
        cp.write_text(json.dumps(cfg), encoding="utf-8")
        return proj, cp

    return make


def pair(voice, cam, off_us=0):
    return {"voice": voice, "camera": cam, "offset_us": off_us, "z": 30.0, "ok": True}


def nested_of(draft, seg):
    ix = common.index(draft["materials"])
    return next(ix[e][1]["draft"] for e in seg["extra_material_refs"] if ix[e][0] == "drafts")


def outer_by_compound(draft, nested_id):
    ix = common.index(draft["materials"])
    for t in draft["tracks"]:
        for s in t["segments"]:
            if any(ix[e][0] == "drafts" and ix[e][1]["draft"]["id"] == nested_id for e in s["extra_material_refs"]):
                return s
    raise AssertionError(f"no outer segment for compound {nested_id}")


def test_assemble_without_voice_uses_screencast(dump, cache):
    import assemble
    proj, cp = dump({"screencasts": ["sc1.mp4", "sc2.mp4"], "camera": ["cam1.mp4"]},
                    [pair("sc1.mp4", "cam1.mp4"), pair("sc2.mp4", "cam1.mp4")])
    assemble.run(common.load_config(str(cp)), dry=False, cache_root=cache, guard_seconds=0)

    comp = json.loads(cp.read_text(encoding="utf-8"))["compounds"]
    assert comp["mic"] is None and comp["screencast"] and comp["circle"]
    cfg = common.load_config(str(cp))
    d = common.read_draft(cfg)
    assert common.check_refs(d) == []
    root = json.loads((proj / "draft_content.json").read_text(encoding="utf-8"))
    assert root == d  # root mirror written too
    ix = common.index(d["materials"])
    sc = outer_by_compound(d, comp["screencast"])
    kinds = [ix[e][0] for e in sc["extra_material_refs"]]
    assert "audio_effects" in kinds and "realtime_denoises" in kinds and sc["volume"] == 1.0
    assert ix[[e for e in sc["extra_material_refs"] if ix[e][0] == "audio_effects"][0]][1]["name"] == "Voice Crisper"
    # nothing left on the outer timeline but compounds: every video/audio segment points at a drafts material
    for t in d["tracks"]:
        if t["type"] in ("video", "audio"):
            for s in t["segments"]:
                assert any(ix[e][0] == "drafts" for e in s["extra_material_refs"]), t
    # circle: mask (type mask, existing cache path), scale 0.4, adjust on the compound segment
    circ = outer_by_compound(d, comp["circle"])
    nd = nested_of(d, circ)
    jx = common.index(nd["materials"])
    inner = nd["tracks"][-1]["segments"]
    assert len(inner) == 2
    for s in inner:
        m = next(jx[e][1] for e in s["extra_material_refs"] if jx[e][0] == "common_mask")
        assert m["type"] == "mask" and Path(m["path"]).is_dir()
        assert s["clip"]["scale"] == {"x": 0.4, "y": 0.4}
    assert {ix[e][1].get("type") for e in circ["extra_material_refs"] if ix[e][0] == "effects"} == \
        {"temperature", "saturation"}
    # subdraft folders and draft_meta_info entries for every compound
    meta = json.loads((proj / "draft_meta_info.json").read_text(encoding="utf-8"))
    files = {e["file_Path"] for g in meta["draft_materials"] if g["type"] == 18 for e in g["value"]}
    for nid in (comp["screencast"], comp["circle"]):
        assert (proj / "subdraft" / nid / "draft_content.json").is_file()
        assert f"./subdraft/{nid}/sub_draft_config.json" in files
    rep = json.loads((cfg.work_dir / "layout" / "assembly.json").read_text(encoding="utf-8"))
    assert rep["pairs"] and rep["assembled"]["compounds"] == comp


def test_assemble_mutes_camera(dump, cache):
    import assemble
    proj, cp = dump({"screencasts": ["sc1.mp4", "sc2.mp4"], "camera": ["cam1.mp4"]},
                    [pair("sc1.mp4", "cam1.mp4"), pair("sc2.mp4", "cam1.mp4", -1_000_000)],
                    layout_f=[(0.0, 1.0), (4.0, 5.0)])
    cfg = common.load_config(str(cp))
    before = common.read_draft(cfg)
    assert any(s["volume"] == 0.0 for t in before["tracks"] for s in t["segments"])  # dump: camera muted already
    for t in before["tracks"]:  # un-mute the dump to prove assemble mutes it itself
        for s in t["segments"]:
            s["volume"] = 1.0
    common.write_draft(cfg, before, "test", dry=False, guard_seconds=0)

    assemble.run(cfg, dry=False, cache_root=cache, guard_seconds=0)
    comp = json.loads(cp.read_text(encoding="utf-8"))["compounds"]
    assert len(comp["cam_full"]) == 2
    d = common.read_draft(cfg)
    assert common.check_refs(d) == []
    for nid in [comp["circle"]] + comp["cam_full"]:
        outer = outer_by_compound(d, nid)
        assert outer["volume"] == 0.0
        assert all(s["volume"] == 0.0 for t in nested_of(d, outer)["tracks"] for s in t["segments"])
    # F stretches: full-screen camera, one Adjustment block each, exactly over the stretch
    adj = [s for t in d["tracks"] if t["type"] == "adjust" for s in t["segments"]]
    spans = sorted((s["target_timerange"]["start"], common.seg_end(s)) for s in adj)
    assert spans == [(0, 1_000_000), (4_000_000, 5_000_000)]
    for nid in comp["cam_full"]:
        outer = outer_by_compound(d, nid)
        assert (outer["target_timerange"]["start"], common.seg_end(outer)) in spans
        for s in nested_of(d, outer)["tracks"][-1]["segments"]:
            assert s["clip"]["scale"] == {"x": 1.0, "y": 1.0}
    # circle = screencast minus F; camera of sc2 synced with offset -1 s (cam = sc - 1 s), negative part dropped
    co = outer_by_compound(d, comp["circle"])
    t0 = co["target_timerange"]["start"]
    got = sorted((t0 + s["target_timerange"]["start"], s["source_timerange"]["start"])
                 for s in nested_of(d, co)["tracks"][-1]["segments"])
    assert got == [(1_000_000, 1_000_000), (5_000_000, 1_000_000)]
    for nid in comp["cam_full"]:
        assert [s["source_timerange"]["start"] for s in nested_of(d, outer_by_compound(d, nid))["tracks"][-1]["segments"]] == [0]


def test_xcorr_finds_known_offset():
    import xcorr
    sr, fps = 16000, 30
    rng = np.random.default_rng(7)
    n = sr * 40
    # speech-like: noise with a random on/off syllable envelope (pure white noise has a flat envelope)
    env = np.repeat(rng.random(n // 1600) > 0.5, 1600).astype(np.float32) * rng.uniform(0.2, 1.0, n // 1600).repeat(1600)
    voice = (rng.standard_normal(n).astype(np.float32) * env)
    shift = int(1.5 * sr)
    cam = np.concatenate([rng.standard_normal(shift).astype(np.float32) * 0.01, voice])  # camera started 1.5 s earlier
    cam = cam + rng.standard_normal(len(cam)).astype(np.float32) * 0.02
    res = xcorr.sync(voice, cam, sr)
    assert abs(res["offset_us"] - 1_500_000) <= 1_000_000 / fps
    assert res["ok"] and len(res["checks"]) >= 3


def test_assemble_refuses_unsynced_pair(dump, cache):
    import assemble
    bad = dict(pair("sc2.mp4", "cam1.mp4"), ok=False, z=3.1, within_frame=1)
    proj, cp = dump({"screencasts": ["sc1.mp4", "sc2.mp4"], "camera": ["cam1.mp4"]},
                    [pair("sc1.mp4", "cam1.mp4"), bad])
    cfg = common.load_config(str(cp))
    before = [p.read_bytes() for p in common.draft_paths(cfg)]
    with pytest.raises(SystemExit) as e:
        assemble.run(cfg, dry=False, cache_root=cache, guard_seconds=0)
    assert "sc2.mp4" in str(e.value) and "--allow-unsynced" in str(e.value)
    assert [p.read_bytes() for p in common.draft_paths(cfg)] == before
    assert json.loads(cp.read_text(encoding="utf-8")).get("compounds") is None  # config untouched
    assemble.run(cfg, dry=False, cache_root=cache, guard_seconds=0, allow_unsynced=True)
    d = common.read_draft(cfg)
    comp = json.loads(cp.read_text(encoding="utf-8"))["compounds"]
    assert len(nested_of(d, outer_by_compound(d, comp["circle"]))["tracks"][-1]["segments"]) == 1  # sc1 only


def test_assemble_refuses_dump_with_adjustment(dump):
    import assemble
    proj, cp = dump({"screencasts": ["sc1.mp4"], "camera": ["cam1.mp4"]}, [pair("sc1.mp4", "cam1.mp4")])
    cfg = common.load_config(str(cp))
    d = common.read_draft(cfg)
    d["tracks"].append({"id": "adj", "type": "adjust", "segments": [
        {"id": "a1", "material_id": "x", "target_timerange": {"start": 0, "duration": 2_000_000}}]})
    with pytest.raises(SystemExit, match="Adjustment: 0.000–2.000"):
        assemble.classify(cfg, d)


def test_make_compound_refuses_camera_role():
    import make_compound
    with pytest.raises(SystemExit) as e:
        make_compound.main(["--role", "camera", "--config", "unused.json"])
    assert "assemble.py" in str(e.value)


def test_range_helpers():
    assert common.subtract_ranges(0, 10, [(2, 3), (5, 7)]) == [(0, 2), (3, 5), (7, 10)]
    assert common.subtract_ranges(0, 10, [(0, 10)]) == []
    assert common.map_through_cuts(10, [(2, 3), (5, 7)]) == 7
    assert common.map_through_cuts(6, [(2, 3), (5, 7)]) == 4   # inside a cut -> its start
    assert common.map_through_cuts(2, [(2, 3)]) == 2
    tr = {"segments": [{"target_timerange": {"start": 0, "duration": 5}}, {"target_timerange": {"start": 7, "duration": 1}}]}
    assert common.gap_count(tr) == 1


def _mic_first(cfg):
    """Dump as recorded: the mic (voice/) in the intro, the screencasts after it — shift the screencast track."""
    d = common.read_draft(cfg)
    ix = common.index(d["materials"])
    vdur = max(common.seg_end(s) for t in d["tracks"] if t["type"] == "audio" for s in t["segments"])
    for t in d["tracks"]:
        for s in t["segments"]:
            if common.source_role(cfg, common.mat_path(ix, s)) == "screencast":
                s["target_timerange"]["start"] += vdur
    d["duration"] = max(common.seg_end(s) for t in d["tracks"] for s in t["segments"])
    common.write_draft(cfg, d, "test", dry=False, guard_seconds=0)
    return vdur


def test_assemble_with_voice(dump, cache):
    """I1: the mic path: mic compound (audio) with Crisper + Reduce noise and the +4.5 dB reference (the fixture
    screencasts have no audio -> nothing to match against), F from the mic pieces with Adjustment over it,
    cfg.compounds.mic, no pre-render by default (audio_path "": CapCut renders it)."""
    import assemble
    proj, cp = dump({"screencasts": ["sc1.mp4", "sc2.mp4"], "camera": ["cam1.mp4"], "voice": ["voice.m4a"]},
                    [pair("voice.m4a", "cam1.mp4"), pair("sc1.mp4", "cam1.mp4"), pair("sc2.mp4", "cam1.mp4")])
    cfg = common.load_config(str(cp))
    vdur = _mic_first(cfg)
    rep = assemble.run(cfg, dry=False, cache_root=cache, guard_seconds=0)
    comp = json.loads(cp.read_text(encoding="utf-8"))["compounds"]
    assert comp["mic"] and comp["screencast"] and comp["circle"] and len(comp["cam_full"]) == 1
    d = common.read_draft(cfg)
    assert common.check_refs(d) == [] and common.draft_overlaps(d) == []
    ix = common.index(d["materials"])
    mic = outer_by_compound(d, comp["mic"])
    assert abs(mic["volume"] - 10 ** (4.5 / 20)) < 1e-9 and rep["mic_gain_db"] == 4.5 and not rep["mic_gain_measured"]
    cats = {ix[e][0] for e in mic["extra_material_refs"]}
    assert {"audio_effects", "realtime_denoises"} <= cats
    assert ix[next(e for e in mic["extra_material_refs"] if ix[e][0] == "audio_effects")][1]["name"] == "Voice Crisper"
    assert next(t for t in d["tracks"] if mic in t["segments"])["type"] == "audio"
    # F over the mic part: full-screen camera compound + one Adjustment block exactly over it
    f = outer_by_compound(d, comp["cam_full"][0])
    assert (f["target_timerange"]["start"], common.seg_end(f)) == (0, vdur) and f["volume"] == 0.0
    adj = [(s["target_timerange"]["start"], common.seg_end(s)) for t in d["tracks"] if t["type"] == "adjust"
           for s in t["segments"]]
    assert adj == [(0, vdur)]
    # the circle only over the screencast part
    circ = outer_by_compound(d, comp["circle"])
    assert circ["target_timerange"]["start"] >= vdur
    # no pre-render by default
    sub = json.loads((proj / "subdraft" / comp["mic"] / "sub_draft_config.json").read_text(encoding="utf-8"))
    assert sub["audio_path"] == "" and not list((proj / "Resources").rglob("*_audio.aac"))


def test_assemble_with_voice_prerender_opt_in(dump, cache):
    import assemble
    proj, cp = dump({"screencasts": ["sc1.mp4"], "voice": ["voice.m4a"]}, [])
    cfg = common.load_config(str(cp))
    _mic_first(cfg)
    assemble.run(cfg, dry=False, cache_root=cache, guard_seconds=0, prerender=True)
    comp = json.loads(cp.read_text(encoding="utf-8"))["compounds"]
    sub = json.loads((proj / "subdraft" / comp["mic"] / "sub_draft_config.json").read_text(encoding="utf-8"))
    assert sub["audio_path"].endswith("_audio.aac") and Path(sub["audio_path"]).is_file()


def _synth(path: Path, amp: float, video: bool):
    """3 s of speech-like noise at amplitude amp; with video: a 320x180 mp4 with that audio, else an m4a."""
    path.parent.mkdir(parents=True, exist_ok=True)
    noise = f"anoisesrc=d=3:c=pink:a={amp}:seed=3,volume=1"
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if video:
        cmd += ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:d=3", "-f", "lavfi", "-i", noise,
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)]
    else:
        cmd += ["-f", "lavfi", "-i", noise, "-c:a", "aac", str(path)]
    import subprocess
    subprocess.run(cmd, check=True)
    return path


def test_assemble_matches_mic_to_screencast_loudness(tmp_path, dump, cache):
    """I2: mic and screencast recorded at different levels -> the mic compound volume makes them equal (±1 LU),
    the dB is reported; measure_lufs agrees; --set-mic restores a broken volume through write_draft."""
    import assemble
    import effects
    import measure_lufs
    syn = tmp_path / "syn"
    sc = _synth(syn / "sc1.mp4", 0.05, True)
    vo = _synth(syn / "voice.m4a", 0.3, False)
    sc_lu = effects.loudness(effects.pcm(sc))["I"]
    vo_lu = effects.loudness(effects.pcm(vo))["I"]
    assert vo_lu - sc_lu > 8      # really different levels
    proj, cp = _dump_from(dump, tmp_path, {"screencasts": [sc], "voice": [vo]})
    cfg = common.load_config(str(cp))
    _mic_first(cfg)
    rep = assemble.run(cfg, dry=False, cache_root=cache, guard_seconds=0)
    assert rep["mic_gain_measured"] and abs(rep["mic_gain_db"] - (sc_lu - vo_lu)) <= 0.5
    comp = json.loads(cp.read_text(encoding="utf-8"))["compounds"]
    d = common.read_draft(cfg)
    assert abs(outer_by_compound(d, comp["mic"])["volume"] - 10 ** (rep["mic_gain_db"] / 20)) < 1e-6
    res = measure_lufs.run(cfg, log=lambda *a: None)
    assert res["ok"] and abs(res["mic_gain_db_to_match"]) <= 1.0
    # break it, then --set-mic fixes it
    outer_by_compound(d, comp["mic"])["volume"] = 1.0
    common.write_draft(cfg, d, "test", dry=False, guard_seconds=0)
    assert not measure_lufs.run(cfg, log=lambda *a: None)["ok"]
    g = measure_lufs.set_mic(cfg, dry=False, guard_seconds=0, log=lambda *a: None)
    assert g["measured"] and measure_lufs.run(cfg, log=lambda *a: None)["ok"]
    root = json.loads((proj / "draft_content.json").read_text(encoding="utf-8"))
    assert root == common.read_draft(cfg)


def _dump_from(dump, tmp_path, files: dict):
    """dump() with arbitrary source files (the fixture copies from MEDIA: point it at a temporary media dir)."""
    import shutil as sh
    media = tmp_path / "media"
    media.mkdir()
    names = {}
    for sub, paths in files.items():
        names[sub] = []
        for p in paths:
            sh.copy(p, media / p.name)
            names[sub].append(p.name)
    global MEDIA
    old = MEDIA
    MEDIA = media
    try:
        return dump(names, [])
    finally:
        MEDIA = old
