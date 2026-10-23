"""LAYOUT part B (candidates, apply_layout, make_compound_f), stage 4 hook, stage 6 zooms + SFX level."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

import common
import effects

TID = "0A1B2C3D-0000-4000-8000-000000000007"
S = 1_000_000
NID_CIRCLE = "C1C1C1C1-0000-4000-8000-00000000C1C1"
NID_SC = "5C5C5C5C-0000-4000-8000-000000005C5C"


# ---------- synthetic projects ----------
def vmat(mid, path, kind="video"):
    return {"id": mid, "type": kind, "path": path, "material_name": Path(path).name if path else mid}


def seg(sid, mid, start, dur, src, refs=(), volume=1.0, speed=1.0, **kw):
    s = {"id": sid, "material_id": mid, "target_timerange": {"start": start, "duration": dur},
         "source_timerange": {"start": src, "duration": int(round(dur * speed))}, "speed": speed, "volume": volume,
         "extra_material_refs": list(refs), "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}},
         "enable_video_mask": False, "common_keyframes": []}
    s.update(kw)
    return s


def compound(nid, dm_id, leaves, mats):
    nested = {"id": nid, "name": nid[:4], "duration": max(common.seg_end(s) for s in leaves),
              "materials": mats, "tracks": [{"type": "video", "segments": []}, {"type": "video", "segments": leaves}]}
    return {"id": dm_id, "type": "combination", "draft": nested}


@pytest.fixture
def make_project(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ensure_capcut_closed", lambda: None)

    def make(draft, compounds=None, layout=None, sfx_dir=None, sources=None):
        proj = tmp_path / "proj"
        for p in (proj / "draft_content.json", proj / "Timelines" / TID / "draft_content.json"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        (proj / "draft_meta_info.json").write_text(json.dumps({"tm_duration": draft["duration"]}), encoding="utf-8")
        work = tmp_path / "work"
        (work / "layout").mkdir(parents=True, exist_ok=True)
        if layout is not None:
            (work / "layout" / "layout.json").write_text(json.dumps({"layout": layout}), encoding="utf-8")
        src = sources or {"camera": str(tmp_path / "src" / "camera"), "screencasts": str(tmp_path / "src" / "screencasts"),
                          "voice": None}
        cp = work / "config.json"
        cp.write_text(json.dumps({"project_dir": str(proj), "timeline_id": TID, "work_dir": str(work), "sources": src,
                                  "sfx_dir": sfx_dir, "compounds": compounds or {"mic": None, "cam_full": [],
                                                                                  "screencast": None, "circle": None}},
                                 ensure_ascii=False), encoding="utf-8")
        return common.load_config(str(cp))

    return make


def snapshot(cfg):
    return {p: p.read_bytes() for p in cfg.project_dir.rglob("*") if p.is_file()}


def layout_draft(tmp_path):
    """60 s: screencast on the main track; circle compound (camera c1 src = timeline + 5 s, mask);
    «Камера F»: a full-screen camera piece at 20–30 s (an existing F)."""
    cam = (tmp_path / "src" / "camera" / "c1.mp4").as_posix()
    sc = (tmp_path / "src" / "screencasts" / "s1.mp4").as_posix()
    leaf = seg("L1", "MCAMn", 0, 60 * S, 5 * S, refs=["MASK"], volume=0.0, enable_video_mask=True,
               clip={"scale": {"x": 0.4, "y": 0.4}, "transform": {"x": 0.8, "y": -0.68}})
    dm = compound(NID_CIRCLE, "DM1", [leaf], {"videos": [vmat("MCAMn", cam)],
                                              "common_mask": [{"id": "MASK", "type": "mask", "path": "x"}]})
    return {"id": TID, "duration": 60 * S, "materials": {
        "videos": [vmat("MSC", sc), vmat("MCOMP", ""), vmat("MCAMF", cam)], "drafts": [dm], "common_mask": []},
        "tracks": [{"type": "video", "name": "", "segments": [seg("SC", "MSC", 0, 60 * S, 0)]},
                   {"type": "video", "name": "Кружок камеры", "segments": [seg("CIR", "MCOMP", 0, 60 * S, 0, refs=["DM1"],
                                                                              volume=0.0)]},
                   {"type": "video", "name": "Камера F", "segments": [seg("F1", "MCAMF", 20 * S, 10 * S, 25 * S,
                                                                         volume=0.0, enable_video_mask=True)]}]}


@pytest.fixture
def cache(tmp_path):
    root = tmp_path / "capcut" / "User Data" / "Cache" / "effect"
    for rid in ("7491147795483659521", "1068046525", "7501974767453474064"):
        (root / rid / "h").mkdir(parents=True)
    (tmp_path / "capcut" / "Apps" / "9.9.0" / "Resources" / "audiosami").mkdir(parents=True)
    return root


# ---------- B4: apply_layout ----------
def test_layout_rejects_overlap_with_existing_F(make_project, tmp_path):
    import apply_layout
    cfg = make_project(layout_draft(tmp_path), compounds={"circle": NID_CIRCLE, "cam_full": [], "mic": None,
                                                          "screencast": None},
                       layout=[{"start": 20.0, "end": 30.0, "layout": "F"}])
    # enable_video_mask without a mask material = full screen (CapCut ignores it)
    assert common.full_camera_ranges(cfg, common.read_draft(cfg)) == [(20 * S, 30 * S)]
    before = snapshot(cfg)
    lj = (cfg.work_dir / "layout" / "layout.json").read_bytes()
    with pytest.raises(SystemExit, match="F"):
        apply_layout.run(cfg, [(25.0, 35.0)], dry=False, guard_seconds=0)
    with pytest.raises(SystemExit, match="F"):
        apply_layout.run(cfg, [(10.0, 21.0)], dry=False, guard_seconds=0)
    assert snapshot(cfg) == before
    assert (cfg.work_dir / "layout" / "layout.json").read_bytes() == lj

    rows = apply_layout.run(cfg, [(40.0, 50.0)], dry=False, guard_seconds=0)
    assert [(r["start"], r["end"], r["layout"]) for r in rows] == [
        (0.0, 20.0, "S"), (20.0, 30.0, "F"), (30.0, 40.0, "S"), (40.0, 50.0, "F"), (50.0, 60.0, "S")]
    saved = json.loads((cfg.work_dir / "layout" / "layout.json").read_text(encoding="utf-8"))["layout"]
    assert [(r["start"], r["end"], r["layout"]) for r in saved] == [(r["start"], r["end"], r["layout"]) for r in rows]
    d = common.read_draft(cfg)
    ft = next(t for t in d["tracks"] if t.get("name") == "Камера F")
    new = [s for s in ft["segments"] if s["id"] != "F1"]
    assert len(new) == 1
    n = new[0]
    assert n["target_timerange"] == {"start": 40 * S, "duration": 10 * S}
    assert n["source_timerange"]["start"] == 45 * S
    assert n["volume"] == 0.0 and not n["enable_video_mask"] and n["clip"]["scale"] == {"x": 1.0, "y": 1.0}
    ix = common.index(d["materials"])
    assert "common_mask" not in {ix[e][0] for e in n["extra_material_refs"]}
    assert not common.check_refs(d)
    # the screencast underneath stays (voice comes from it)
    assert [s["id"] for s in d["tracks"][0]["segments"]] == ["SC"]
    # a range over an F applied just now is rejected too
    with pytest.raises(SystemExit):
        apply_layout.run(cfg, [(45.0, 55.0)], dry=True)


def test_make_compound_f_wraps_each_stretch_and_adds_adjustment(make_project, tmp_path, cache):
    import apply_layout
    import make_compound_f
    cfg = make_project(layout_draft(tmp_path), compounds={"circle": NID_CIRCLE, "cam_full": [], "mic": None,
                                                          "screencast": None},
                       layout=[{"start": 20.0, "end": 30.0, "layout": "F"}])
    apply_layout.run(cfg, [(40.0, 50.0)], dry=False, guard_seconds=0)
    res = make_compound_f.run(cfg, dry=False, cache_root=cache, guard_seconds=0)
    assert len(res["made"]) == 2
    d = common.read_draft(cfg)
    adj = sorted((s["target_timerange"]["start"], common.seg_end(s)) for t in d["tracks"] if t["type"] == "adjust"
                 for s in t["segments"])
    assert adj == [(20 * S, 30 * S), (40 * S, 50 * S)]
    cfg2 = common.load_config(str(cfg.config_path))
    assert len(cfg2.compounds["cam_full"]) == 2
    ft = next(t for t in d["tracks"] if t.get("name") == "Камера F")
    assert len(ft["segments"]) == 2
    import make_compound as mc
    for nid in cfg2.compounds["cam_full"]:
        _c, _t, outer, dm = mc.find(d, nid)
        assert outer["volume"] == 0.0
        assert (cfg.project_dir / "subdraft" / nid / "draft_content.json").is_file()
    assert not common.check_refs(d)
    # nothing left to wrap -> a no-op
    assert make_compound_f.run(cfg, dry=True, cache_root=cache)["made"] == []


# ---------- B1: candidates ----------
def words(*items):
    return [{"word": w, "start": a, "end": b} for w, a, b in items]


def plain(t0, t1, step=0.8, gap=0.2):
    out, t, i = [], t0, 0
    while t + step <= t1 + 1e-9:
        out.append((f"слово{i}", round(t, 3), round(t + step, 3)))
        t += step + gap
        i += 1
    return out


def test_candidates_filter_screen_words():
    import candidates
    ws = words(*plain(20.0, 33.0), ("вот", 34.0, 34.3), *plain(34.5, 37.0), ("нажимаем", 38.0, 38.5),
               *plain(38.7, 41.0))
    res = candidates.propose(ws, static_tl=[(18.0, 45.0)], sped=[], intro_end=5.0, duration=100.0)
    cands = res["candidates_all"]
    assert len(cands) == 1
    c = cands[0]
    assert 19.8 <= c["start"] <= 20.0 and 32.8 <= c["end"] <= 33.2
    for c in cands:
        assert "вот" not in c["text"].split() and "нажимаем" not in c["text"].split()
        assert c["end"] - c["start"] >= 4.0
        assert not any(c["start"] <= t <= c["end"] for t in (34.0, 38.0))
    # pointing at the screen every few seconds -> no candidate at all
    ws = []
    for k in range(6):
        t = 50.0 + 4 * k
        ws += words(("смотрите", t, t + 0.4), *plain(t + 0.6, t + 3.5))
    assert candidates.propose(ws, static_tl=[(49.0, 80.0)], sped=[], intro_end=5.0, duration=100.0)["candidates_all"] == []
    # a static run over a sped screencast is not a candidate
    ws = words(*plain(20.0, 33.0))
    assert candidates.propose(ws, static_tl=[(18.0, 45.0)], sped=[(30.0, 31.0)], intro_end=5.0,
                              duration=100.0)["candidates_all"] == []


# ---------- stage 4: hook ----------
def test_hook_copies_pieces_to_start_and_shifts_everything(make_project, tmp_path):
    import apply_hook
    d = layout_draft(tmp_path)
    sc = d["materials"]["videos"][0]["path"]
    # main track = screencast compound (leaf src = timeline + 100 s) with voice effects on the outer segment
    sc_leaf = seg("SL", "MSCn", 0, 60 * S, 100 * S)
    d["materials"]["drafts"].append(compound(NID_SC, "DM2", [sc_leaf], {"videos": [vmat("MSCn", sc)]}))
    d["materials"]["audio_effects"] = [{"id": "VC", "type": "audio_effect", "name": "Voice Crisper"}]
    d["materials"]["videos"].append(vmat("MCOMP2", ""))
    d["tracks"][0]["segments"] = [seg("SCO", "MCOMP2", 0, 60 * S, 0, refs=["DM2", "VC"])]
    d["tracks"][2]["segments"] = []
    cfg = make_project(d, compounds={"circle": NID_CIRCLE, "screencast": NID_SC, "cam_full": [], "mic": None},
                       layout=[{"start": 0.0, "end": 60.0, "layout": "S"}])
    nested_before = [json.dumps(x["draft"], sort_keys=True) for x in d["materials"]["drafts"]]
    res = apply_hook.run(cfg, [(10.0, 13.0)], dry=False, guard_seconds=0, maps=False)
    assert res["hook_len_us"] == 3 * S
    d2 = common.read_draft(cfg)
    assert d2["duration"] == 63 * S
    ix = common.index(d2["materials"])
    main = common.by_start(d2["tracks"][0]["segments"])
    h = main[0]   # a piece of the screencast compound, like CapCut copy: own drafts entry, same nested draft
    assert h["target_timerange"] == {"start": 0, "duration": 3 * S} and h["source_timerange"]["start"] == 10 * S
    assert h["id"] != "SCO" and "audio_effects" in {ix[e][0] for e in h["extra_material_refs"]}
    dm = next(ix[e][1] for e in h["extra_material_refs"] if ix[e][0] == "drafts")
    assert dm["id"] != "DM2" and dm["draft"]["id"] == NID_SC
    assert main[1]["id"] == "SCO" and main[1]["target_timerange"]["start"] == 3 * S
    cir = common.by_start(d2["tracks"][1]["segments"])
    assert cir[1]["id"] == "CIR" and cir[1]["target_timerange"]["start"] == 3 * S
    # what the hook shows = the original 10–13 s: same files at the same source times
    flat = common.flatten(cfg, d2)
    at = {(p["role"], p["src"], p["mask"]) for p in flat if p["start"] == 0}
    assert at == {("screencast", 110 * S, False), ("camera", 15 * S, True)}
    assert all(p["end"] == 3 * S for p in flat if p["start"] == 0)
    assert [json.dumps(x["draft"], sort_keys=True) for x in d2["materials"]["drafts"]][:2] == nested_before
    assert not common.check_refs(d2)
    rows = common.read_layout(cfg)
    assert [(r["start"], r["end"], r["layout"]) for r in rows] == [(0.0, 3.0, "S"), (3.0, 63.0, "S")]
    log = json.loads((cfg.work_dir / "stage4" / "hook_applied.json").read_text(encoding="utf-8"))
    assert log["shift_us"] == 3 * S and log["pieces_us"] == [[10 * S, 13 * S]]
    assert json.loads((cfg.project_dir / "draft_meta_info.json").read_text())["tm_duration"] == 63 * S


# ---------- stage 6: zooms + SFX level ----------
def wav(path: Path, x: np.ndarray, sr=48000):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = path.with_suffix(".f32")
    x.astype(np.float32).tofile(raw)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", str(raw), str(path)],
                   check=True)
    raw.unlink()
    return path


def zoom_project(make_project, tmp_path, sfx_dir=True):
    sr = 48000
    rng = np.random.default_rng(1)
    t = np.arange(20 * sr) / sr
    voice = (0.08 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t))
             + 0.01 * rng.standard_normal(len(t)))
    sc = wav(tmp_path / "src" / "screencasts" / "s1.wav", voice)
    sfx = tmp_path / "sfx"
    wav(sfx / "a whoosh.wav", 0.6 * rng.standard_normal(int(0.25 * sr)))
    wav(sfx / "b whoosh.wav", 0.3 * rng.standard_normal(int(0.3 * sr)))
    d = {"id": TID, "duration": 20 * S, "materials": {"videos": [vmat("MSC", sc.as_posix())]},
         "tracks": [{"type": "video", "name": "", "segments": [seg("SC", "MSC", 0, 20 * S, 0)]}]}
    cfg = make_project(d, layout=[{"start": 0.0, "end": 20.0, "layout": "S"}],
                       sfx_dir=str(sfx) if sfx_dir else None)
    spec = {"focus": [{"n": 1, "start": 5.0, "end": 9.0, "center": [1400, 300], "scale": 1.5, "phrase": "кнопка",
                       "what": "кнопка", "conf": "высокая", "words": ["кнопка"]}]}
    return cfg, spec, voice, sr


def test_zoom_sfx_level(make_project, tmp_path):
    import apply_zooms
    cfg, spec, voice, sr = zoom_project(make_project, tmp_path)
    out = apply_zooms.run(cfg, spec, dry=False, guard_seconds=0)
    d = common.read_draft(cfg)
    main = common.by_start(d["tracks"][0]["segments"])
    assert [(s["target_timerange"]["start"], common.seg_end(s)) for s in main] == [(0, 5 * S), (5 * S, 9 * S),
                                                                                    (9 * S, 20 * S)]
    z = main[1]
    assert {c["property_type"] for c in z["common_keyframes"]} >= {"KFTypeScaleX", "KFTypePositionX"}
    assert effects.keyframes_inside(z) and not main[0]["common_keyframes"] and not main[2]["common_keyframes"]
    sfx_t = next(t for t in d["tracks"] if t["type"] == "audio")
    (s,) = sfx_t["segments"]
    assert abs(s["target_timerange"]["start"] - 5 * S) <= S / cfg.fps
    ix = common.index(d["materials"])
    sfx_path = ix[s["material_id"]][1]["path"]
    # the meter itself: a 1 kHz sine at -20 dBFS reads -23 LUFS (EBU R128)
    sine = 0.1 * np.sin(2 * np.pi * 1000 * np.arange(5 * sr) / sr)
    assert abs(effects.loudness(sine, sr)["I"] - (-23.0)) <= 0.3
    # independent check: the SFX at that volume peaks at voice - 12 LU (±1)
    voice_lu = effects.loudness(voice, sr)["I"]
    peak = effects.loudness(effects.pcm(sfx_path) * s["volume"])["M_max"]
    assert abs(peak - (voice_lu - 12)) <= 1.0, (peak, voice_lu)
    zj = json.loads((cfg.work_dir / "stage6" / "zooms.json").read_text(encoding="utf-8"))
    assert zj["focus"][0]["sfx"]["segment_id"] == s["id"] and out["focus"][0]["start"] == 5.0
    # applied twice -> refused (keys already there)
    with pytest.raises(SystemExit):
        apply_zooms.run(cfg, spec, dry=True)
    import check_zooms
    (rep,) = check_zooms.run(cfg, frames=False)
    assert rep["problems"] == [] and abs(rep["sfx_level_lu"] - (-12)) <= 1.0


def test_zooms_need_sfx_dir(make_project, tmp_path):
    import apply_zooms
    cfg, spec, _v, _sr = zoom_project(make_project, tmp_path, sfx_dir=False)
    before = snapshot(cfg)
    with pytest.raises(SystemExit, match="sfx_dir"):
        apply_zooms.run(cfg, spec, dry=False, guard_seconds=0)
    assert snapshot(cfg) == before
    assert apply_zooms.run(cfg, {"focus": [], "pushin": []}, dry=True)["focus"] == []


# ---------- stage 5: censorship ----------
def test_scan_patterns_finds_secrets_not_noise():
    import scan_patterns
    rows = [{"block": 1, "par": 1, "line": 1, "l": 10 + 60 * i, "t": 20, "w": 50, "h": 12, "conf": 90, "text": t}
            for i, t in enumerate(["mail:", "ivan.petrov@example.com", "card", "4111", "1111", "1111", "1111"])]
    rows += [{"block": 2, "par": 1, "line": 1, "l": 10, "t": 60, "w": 50, "h": 12, "conf": 90, "text": t}
             for t in ["1234", "5678", "1234", "5678"]]   # not a Luhn number
    hits = scan_patterns.scan_rows(rows)
    types = sorted({h["type"] for h in hits})
    assert "email" in types and "card" in types
    card = next(h for h in hits if h["type"] == "card")
    assert card["match"].startswith("4111") and card["bbox"][1] == 20
    email = next(h for h in hits if h["type"] == "email")
    assert email["bbox"][0] == 70


def test_censor_burns_blur_and_swaps_path(make_project, tmp_path):
    import shutil
    import apply_censor
    import build_findings
    sc_dir = tmp_path / "src" / "screencasts"
    sc_dir.mkdir(parents=True)
    src = sc_dir / "rec 1.mp4"
    shutil.copy(Path(__file__).parent / "fixtures" / "media" / "sc1.mp4", src)
    d = {"id": TID, "duration": 3 * S, "materials": {"videos": [vmat("MSC", src.as_posix())]},
         "tracks": [{"type": "video", "name": "", "segments": [seg("SC", "MSC", 0, 3 * S, 0)]}]}
    cfg = make_project(d)
    st = cfg.work_dir / "stage5"
    st.mkdir(parents=True)
    hits = [{"file": "rec 1", "sec": s, "psm": "3", "type": "email", "match": "a@b.co", "line": "a@b.co",
             "bbox": [100, 60, 80, 20]} for s in (0, 1)]
    hits.append({"file": "rec 1", "sec": 2, "psm": "3", "type": "phone", "match": "+7 900 123 45 67", "line": "",
                 "bbox": [10, 10, 50, 10]})
    (st / "pattern_hits.json").write_text(json.dumps(hits), encoding="utf-8")
    findings = build_findings.run(cfg)
    assert [(f["type"], f["apply"], f["src_start"], f["src_end"]) for f in findings] == [
        ("email", True, 0.0, 2.0), ("phone", False, 2.0, 3.0)]
    assert findings[0]["file"] == "rec 1.mp4" and findings[0]["timeline"] == [[0.0, 2.0]]
    assert (st / "censor_proposal.md").is_file()
    apply_censor.run(cfg, dry=False, guard_seconds=0)
    out = st / "censored" / "rec 1_censored.mp4"
    assert out.is_file() and apply_censor.same_format(src, out)
    for p in (cfg.project_dir / "draft_content.json", cfg.project_dir / "Timelines" / TID / "draft_content.json"):
        dd = json.loads(p.read_text(encoding="utf-8"))
        assert dd["materials"]["videos"][0]["path"] == out.as_posix()
        assert dd["tracks"][0]["segments"][0]["source_timerange"] == {"start": 0, "duration": 3 * S}
    assert common.source_role(cfg, out.as_posix()) == "screencast"
    # the blurred box differs from the source there, the rest of the frame does not
    from PIL import Image
    fa = common.grab_frame(str(src), 1.0, tmp_path / "a.png")
    fb = common.grab_frame(str(out), 1.0, tmp_path / "b.png")
    x = np.asarray(Image.open(fa).convert("L"), dtype=np.int16)
    y = np.asarray(Image.open(fb).convert("L"), dtype=np.int16)
    inside = np.abs(x[60:80, 100:180] - y[60:80, 100:180]).mean()
    outside = np.abs(x[:40, :80] - y[:40, :80]).mean()
    assert outside < 3 and inside > outside


def test_censor_nothing_found(make_project, tmp_path):
    import apply_censor
    import build_findings
    d = {"id": TID, "duration": 3 * S, "materials": {"videos": []}, "tracks": []}
    cfg = make_project(d)
    assert build_findings.run(cfg) == []
    assert apply_censor.run(cfg, dry=False) == {}


def test_wb_fix_temperature_on_camera_pieces_of_the_file(make_project, tmp_path, cache):
    import wb_fix
    cfg = make_project(layout_draft(tmp_path), compounds={"circle": NID_CIRCLE, "cam_full": [], "mic": None,
                                                          "screencast": None})
    assert wb_fix.run(cfg, "c1.mp4", [(100.0, 120.0)], -27, dry=False, cache_root=cache, guard_seconds=0)["new"] == 0
    res = wb_fix.run(cfg, "c1.mp4", [(30.0, 40.0)], -27, dry=False, cache_root=cache, guard_seconds=0)
    assert res == {"new": 2, "updated": 0, "value": -0.54}   # the circle leaf (src 5–65) + the F piece (src 25–35)
    d = common.read_draft(cfg)
    nd = d["materials"]["drafts"][0]["draft"]
    leaf = nd["tracks"][1]["segments"][0]
    jx = common.index(nd["materials"])
    temps = [jx[e][1] for e in leaf["extra_material_refs"] if jx[e][0] == "effects"]
    assert [(m["type"], m["value"]) for m in temps] == [("temperature", -0.54)] and leaf["enable_adjust"]
    assert not common.check_refs(d)
    res = wb_fix.run(cfg, "c1.mp4", [(30.0, 40.0)], -10, dry=False, cache_root=cache, guard_seconds=0)
    assert res == {"new": 0, "updated": 2, "value": -0.2}
    nd = common.read_draft(cfg)["materials"]["drafts"][0]["draft"]
    assert sum(1 for m in nd["materials"]["effects"] if m["type"] == "temperature") == 1
