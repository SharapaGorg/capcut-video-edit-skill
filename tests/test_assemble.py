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
