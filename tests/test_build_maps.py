import json
from pathlib import Path

import pytest

import common

TID = "0A1B2C3D-0000-4000-8000-000000000003"
S = 1_000_000
PH = "##_draftpath_placeholder_0E685133-18CE-45ED-8CB8-2904A212EC80_##"


def vmat(mid, path, kind="video"):
    return {"id": mid, "type": kind, "path": path, "material_name": Path(path).name}


def seg(sid, mid, start, dur, src, speed=1.0, volume=1.0, refs=()):
    return {"id": sid, "material_id": mid, "target_timerange": {"start": start, "duration": dur},
            "source_timerange": {"start": src, "duration": int(round(dur * speed))}, "speed": speed,
            "volume": volume, "extra_material_refs": list(refs)}


def draft(tracks, videos=(), audios=(), drafts=(), name=""):
    segs = [s for _t, ss in tracks for s in ss]
    return {"id": TID, "name": name, "duration": max(common.seg_end(s) for s in segs),
            "materials": {"videos": list(videos), "audios": list(audios), "drafts": list(drafts)},
            "tracks": [{"type": t, "segments": ss} for t, ss in tracks]}


def words_at(*spans):
    ws = [{"word": f"w{i}", "start": a, "end": b, "prob": 1.0} for i, (a, b) in enumerate(spans)]
    return {"segments": [{"id": 1, "start": ws[0]["start"], "end": ws[-1]["end"], "text": "x", "words": ws}]}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Project (both drafts) + work dir with config.json, transcript.json and the pre-stage-1 backup (raw draft)."""
    monkeypatch.setattr(common, "ensure_capcut_closed", lambda: None)

    def make(sources, cur, raw, transcript):
        proj = tmp_path / "proj"
        for p in (proj / "draft_content.json", proj / "Timelines" / TID / "draft_content.json"):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
        (proj / "draft_meta_info.json").write_text(json.dumps({"tm_duration": cur["duration"]}), encoding="utf-8")
        work = tmp_path / "work"
        rp = work / "backups" / "stage1-before-20260101-000000" / "Timelines" / TID / "draft_content.json"
        rp.parent.mkdir(parents=True)
        rp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        (work / "transcript").mkdir()
        transcript["duration"] = raw["duration"] / S
        (work / "transcript" / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")
        cp = work / "config.json"
        cp.write_text(json.dumps({"project_dir": str(proj), "timeline_id": None, "work_dir": str(work),
                                  "sources": sources}, ensure_ascii=False), encoding="utf-8")
        return common.load_config(str(cp))

    return make


def src_dir(tmp_path, sub, names):
    d = tmp_path / "src" / sub
    d.mkdir(parents=True)
    for n in names:
        (d / n).write_bytes(b"")
    return d


def kept_words(cfg):
    tt = json.loads((cfg.work_dir / "stage3" / "transcript_timeline.json").read_text(encoding="utf-8"))
    return [w for s in tt["segments"] for w in s["words"]], tt


def test_word_maps_into_segment(project, tmp_path):
    import build_maps
    sc = src_dir(tmp_path, "screencasts", ["s1.mp4"])
    path = (sc / "s1.mp4").as_posix()
    raw = draft([("video", [seg("R1", "MR", 0, 30 * S, 0)])], videos=[vmat("MR", path)])
    cur = draft([("video", [seg("C1", "MC", 0, 10 * S, 10 * S)])], videos=[vmat("MC", path)])
    cfg = project({"camera": None, "screencasts": str(sc), "voice": None}, cur, raw,
                  words_at((12.0, 12.4), (25.0, 25.3)))
    res = build_maps.run(cfg, audio_check=False)
    assert res["errs"] == []
    words, tt = kept_words(cfg)
    assert len(words) == 1
    w = words[0]
    assert w["start"] == 2.0 and abs(w["end"] - 2.4) <= 0.011
    assert w["file"] == "s1.mp4" and w["file_start"] == 12.0 and w["speed"] == 1.0
    assert w["segment_id"] == "C1" and w["flat_id"] == "C1@0"
    assert [d["reason"] for d in tt["dropped_words"]] == ["cut"]
    tmap = json.loads((cfg.work_dir / "stage3" / "timeline_map.json").read_text(encoding="utf-8"))
    s = tmap["tracks"][0]["segments"][0]
    assert (s["timeline_in_us"], s["timeline_out_us"], s["source_in_us"], s["source_out_us"]) == (0, 10 * S, 10 * S, 20 * S)
    for f in ("transcript_timeline.txt", "chapters_timeline.json", "report.md"):
        assert (cfg.work_dir / "stage3" / f).is_file()


def test_censored_name_normalised(project, tmp_path):
    import build_maps
    sc = src_dir(tmp_path, "screencasts", ["a b.mp4"])
    cens = tmp_path / "work" / "stage5" / "a b_censored.mp4"
    cens.parent.mkdir(parents=True)
    cens.write_bytes(b"")
    raw = draft([("video", [seg("R1", "MR", 0, 20 * S, 0)])], videos=[vmat("MR", (sc / "a b.mp4").as_posix())])
    cur = draft([("video", [seg("C1", "MC", 0, 20 * S, 0)])], videos=[vmat("MC", cens.as_posix())])
    cfg = project({"camera": None, "screencasts": str(sc), "voice": None}, cur, raw, words_at((3.0, 3.5)))
    assert common.source_role(cfg, cens.as_posix()) == "screencast"
    build_maps.run(cfg, audio_check=False)
    words, _ = kept_words(cfg)
    assert [(w["start"], w["file"], w["file_start"]) for w in words] == [(3.0, "a b.mp4", 3.0)]


def test_cyrillic_path_on_E_drive(project):
    import build_maps
    sc = r"E:\Видео\Мой ролик\скринкасты"
    path = "E:/Видео/Мой ролик/скринкасты/запись 1.mp4"
    raw = draft([("video", [seg("R1", "MR", 0, 20 * S, 0)])], videos=[vmat("MR", path)])
    cur = draft([("video", [seg("C1", "MC", 0, 15 * S, 5 * S)])], videos=[vmat("MC", path)])
    cfg = project({"camera": None, "screencasts": sc, "voice": None}, cur, raw, words_at((8.0, 8.5)))
    res = build_maps.run(cfg, audio_check=False)
    words, _ = kept_words(cfg)
    assert [(w["start"], w["file"], w["file_start"]) for w in words] == [(3.0, "запись 1.mp4", 8.0)]
    txt = (cfg.work_dir / "stage3" / "transcript_timeline.txt").read_text(encoding="utf-8")
    assert txt.startswith("[00:03] w0")
    assert any("запись 1.mp4" in e for e in res["errs"])  # file absent on this machine -> reported, maps still written


def test_word_maps_through_cut_compound_with_speed(project, tmp_path):
    """A compound cut into 2 pieces in CapCut (each with its own copy of the nested draft), 2nd piece at 1.1x."""
    import build_maps
    sc = src_dir(tmp_path, "screencasts", ["s1.mp4"])
    path = (sc / "s1.mp4").as_posix()
    nested = draft([("video", [seg("N1", "MN", 0, 20 * S, 0)])], videos=[vmat("MN", path)], name="Compound A")
    nested["id"] = "NESTED-1"
    dm1 = {"id": "D1", "type": "combination", "draft": nested}
    dm2 = {"id": "D2", "type": "combination", "draft": json.loads(json.dumps(nested))}
    cur = draft([("video", [seg("P1", "O1", 0, 5 * S, 0, refs=["D1"]),
                            seg("P2", "O2", 5 * S, 4 * S, 10 * S, speed=1.1, refs=["D2"])])],
                videos=[vmat("O1", PH + "/c"), vmat("O2", PH + "/c")], drafts=[dm1, dm2])
    raw = draft([("video", [seg("R1", "MR", 0, 20 * S, 0)])], videos=[vmat("MR", path)])
    cfg = project({"camera": None, "screencasts": str(sc), "voice": None}, cur, raw,
                  words_at((1.0, 1.2), (7.0, 7.2), (12.0, 12.3)))
    build_maps.run(cfg, audio_check=False)
    words, tt = kept_words(cfg)
    assert [(w["word"], w["start"], w["speed"], w["compound"]) for w in words] == [
        ("w0", 1.0, 1.0, "Compound A#0"), ("w2", round(5 + 2 / 1.1, 3), 1.1, "Compound A#0")]
    assert [d["word"] for d in tt["dropped_words"]] == ["w1"]


def test_ripple_cut_splits_and_clears_audio_prerender(project, tmp_path):
    import ripple_cut
    vo = src_dir(tmp_path, "voice", ["mic.m4a"])
    sc = src_dir(tmp_path, "screencasts", ["s1.mp4"])
    mic, scp = (vo / "mic.m4a").as_posix(), (sc / "s1.mp4").as_posix()
    nested = draft([("audio", [seg("N1", "MN", 0, 10 * S, 0)])], audios=[vmat("MN", mic, "extract_music")], name="mic")
    nested["id"] = "NESTED-MIC-PIECE"  # CapCut re-ids nested drafts of cut pieces; draft_config_path keeps the folder
    cur = draft([("video", [seg("V1", "MV", 0, 10 * S, 0, volume=0.0)]),
                 ("audio", [seg("A1", "OA", 0, 10 * S, 0, refs=["DM"])])],
                videos=[vmat("MV", scp)], audios=[vmat("OA", PH + "/Resources/combination/C1_audio.aac")],
                drafts=[{"id": "DM", "type": "combination", "combination_id": "C1", "draft": nested,
                         "draft_config_path": PH + "\\subdraft\\NESTED-MIC\\sub_draft_config.json"}])
    raw = draft([("video", [seg("RV", "MV", 0, 10 * S, 0, volume=0.0)]), ("audio", [seg("RA", "MA", 0, 10 * S, 0)])],
                videos=[vmat("MV", scp)], audios=[vmat("MA", mic, "extract_music")])
    cfg = project({"camera": None, "screencasts": str(sc), "voice": str(vo)}, cur, raw,
                  words_at((1.0, 1.4), (2.3, 2.6), (5.0, 5.4)))
    aac = cfg.project_dir / "Resources" / "combination" / "C1_audio.aac"
    aac.parent.mkdir(parents=True)
    aac.write_bytes(b"x")
    sub = cfg.project_dir / "subdraft" / "NESTED-MIC" / "sub_draft_config.json"
    sub.parent.mkdir(parents=True)
    sub.write_text(json.dumps({"audio_path": "../../Resources/combination/C1_audio.aac", "id": "NESTED-MIC"}),
                   encoding="utf-8")
    cuts = cfg.work_dir / "cuts.json"
    cuts.write_text(json.dumps([{"start": 2.0, "end": 3.0}]), encoding="utf-8")

    ripple_cut.run(cfg, ripple_cut.load_cuts(cuts, cfg.fps), dry=False, guard_seconds=0, audio_check=False)

    d = common.read_draft(cfg)
    root = json.loads((cfg.project_dir / "draft_content.json").read_text(encoding="utf-8"))
    assert root == d and d["duration"] == 9 * S
    for t in d["tracks"]:
        assert [(s["target_timerange"]["start"], s["target_timerange"]["duration"], s["source_timerange"]["start"])
                for s in t["segments"]] == [(0, 2 * S, 0), (2 * S, 7 * S, 3 * S)]
    assert common.check_refs(d) == []
    assert not aac.exists() and json.loads(sub.read_text(encoding="utf-8"))["audio_path"] == ""
    assert json.loads((cfg.project_dir / "draft_meta_info.json").read_text(encoding="utf-8"))["tm_duration"] == 9 * S
    words, _ = kept_words(cfg)  # maps regenerated after the cut
    assert [(w["word"], w["start"]) for w in words] == [("w0", 1.0), ("w2", 4.0)]
    log = json.loads((cfg.work_dir / "stage3" / "ripple_cuts.json").read_text(encoding="utf-8"))
    assert log[-1]["cuts"] == [[2.0, 3.0]] and log[-1]["after"] == 9.0


def test_ripple_cut_maps_layout_json(project, tmp_path):
    """A cut before an F row shifts the row (and f_segments) left by the cut length."""
    import ripple_cut
    sc = src_dir(tmp_path, "screencasts", ["s1.mp4"])
    path = (sc / "s1.mp4").as_posix()
    raw = draft([("video", [seg("R1", "MR", 0, 10 * S, 0)])], videos=[vmat("MR", path)])
    cur = draft([("video", [seg("C1", "MC", 0, 10 * S, 0)])], videos=[vmat("MC", path)])
    cfg = project({"camera": None, "screencasts": str(sc), "voice": None}, cur, raw, words_at((1.0, 1.4), (6.0, 6.4)))
    common.write_layout(cfg, [{"start": 0.0, "end": 5.0, "layout": "S"}, {"start": 5.0, "end": 8.0, "layout": "F"},
                              {"start": 8.0, "end": 10.0, "layout": "S"}],
                        f_segments=[{"timeline_us": [5 * S, 8 * S], "file": "c.mp4"}])
    ripple_cut.run(cfg, [(2 * S, 3 * S)], dry=False, guard_seconds=0, audio_check=False)
    lj = json.loads((cfg.work_dir / "layout" / "layout.json").read_text(encoding="utf-8"))
    assert [(r["start"], r["end"], r["layout"]) for r in lj["layout"]] == [(0.0, 4.0, "S"), (4.0, 7.0, "F"),
                                                                            (7.0, 9.0, "S")]
    assert lj["f_segments"][0]["timeline_us"] == [4 * S, 7 * S]


def test_ripple_cut_dry_writes_nothing(project, tmp_path):
    import ripple_cut
    sc = src_dir(tmp_path, "screencasts", ["s1.mp4"])
    path = (sc / "s1.mp4").as_posix()
    cur = draft([("video", [seg("C1", "MC", 0, 10 * S, 0)])], videos=[vmat("MC", path)])
    cfg = project({"camera": None, "screencasts": str(sc), "voice": None}, cur, cur, words_at((1.0, 1.2)))
    before = (cfg.project_dir / "draft_content.json").read_bytes()
    out = ripple_cut.run(cfg, [(2 * S, 3 * S)], dry=True, guard_seconds=0, audio_check=False)
    assert out["after_us"] == 9 * S
    assert (cfg.project_dir / "draft_content.json").read_bytes() == before
    assert not (cfg.work_dir / "stage3" / "ripple_cuts.json").exists()
    assert not list((cfg.work_dir / "backups").glob("stage3-ripple*"))


def test_assembly_pairs_checked(project, tmp_path):
    """layout/assembly.json: s1 camera piece placed by its offset (good), s2 camera piece 0.5 s off (error)."""
    import build_maps
    sc = src_dir(tmp_path, "screencasts", ["s1.mp4", "s2.mp4"])
    cam = src_dir(tmp_path, "camera", ["cam1.mp4"])
    s1, s2, c1 = (sc / "s1.mp4").as_posix(), (sc / "s2.mp4").as_posix(), (cam / "cam1.mp4").as_posix()
    cur = draft([("video", [seg("V1", "M1", 0, 10 * S, 0), seg("V2", "M2", 10 * S, 10 * S, 0)]),
                 ("video", [seg("K1", "MC", 0, 10 * S + 1, 2 * S, volume=0.0),  # 1 us into V2: rounding, not an overlap
                            seg("K2", "MC2", 10 * S + 1, 10 * S - 1, 30 * S + S // 2, volume=0.0)])],
                videos=[vmat("M1", s1), vmat("M2", s2), vmat("MC", c1), vmat("MC2", c1)])
    cfg = project({"camera": str(cam), "screencasts": str(sc), "voice": None}, cur, cur, words_at((1.0, 1.2)))
    (cfg.work_dir / "layout").mkdir()
    (cfg.work_dir / "layout" / "assembly.json").write_text(json.dumps({"pairs": [
        {"voice": "s1.mp4", "camera": "cam1.mp4", "offset_us": 2 * S, "ok": True},
        {"voice": "s2.mp4", "camera": "cam1.mp4", "offset_us": 30 * S, "ok": True}]}), encoding="utf-8")
    res = build_maps.run(cfg, audio_check=False)
    sync = [e for e in res["errs"] if e.startswith("синхрон камеры")]
    assert len(sync) == 1 and "s2.mp4" in sync[0] and "+500.0 мс" in sync[0]
    assert any("assembly.json: 2 перекрытий" in n for n in res["notes"])
    assert "синхрон камеры" in (cfg.work_dir / "stage3" / "report.md").read_text(encoding="utf-8")


def test_audio_check_without_ffmpeg_is_skipped(project, tmp_path, monkeypatch):
    import build_maps
    sc = src_dir(tmp_path, "screencasts", ["s1.mp4"])
    cur = draft([("video", [seg("C1", "MC", 0, 10 * S, 0)])], videos=[vmat("MC", (sc / "s1.mp4").as_posix())])
    cfg = project({"camera": None, "screencasts": str(sc), "voice": None}, cur, cur,
                  words_at(*[(i * 0.5, i * 0.5 + 0.3) for i in range(6)]))
    monkeypatch.setattr(build_maps.shutil, "which", lambda name: None)
    res = build_maps.run(cfg, audio_check=True)
    assert "audio check skipped: ffmpeg not found" in res["notes"] and res["errs"] == []
