"""Stages 7–8: graphics HTML -> Playwright -> ProRes 4444 MOV, apply_graphics (idempotent), SFX under the entries."""
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

import common
import effects
from test_layout import S, TID, NID_CIRCLE, compound, make_project, seg, snapshot, vmat, wav  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


# ---------- synthetic project: screencast (voice) 0-60 s, «Камера F» 20-30 s, circle compound on top ----------
def gfx_project(make_project, tmp_path, sfx=True):
    sr = 48000
    rng = np.random.default_rng(3)
    t = np.arange(60 * sr) / sr
    voice = 0.08 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 3 * t)) + 0.01 * rng.standard_normal(len(t))
    sc = wav(tmp_path / "src" / "screencasts" / "s1.wav", voice)
    cam = (tmp_path / "src" / "camera" / "c1.mp4").as_posix()
    sfx_dir = tmp_path / "sfx"
    wav(sfx_dir / "click.wav", 0.5 * rng.standard_normal(int(0.2 * sr)))
    leaf = seg("L1", "MCAMn", 0, 60 * S, 5 * S, refs=["MASK"], volume=0.0, enable_video_mask=True,
               clip={"scale": {"x": 0.4, "y": 0.4}, "transform": {"x": 0.8, "y": -0.68}})
    dm = compound(NID_CIRCLE, "DM1", [leaf], {"videos": [vmat("MCAMn", cam)],
                                              "common_mask": [{"id": "MASK", "type": "mask", "path": "x"}]})
    d = {"id": TID, "duration": 60 * S, "materials": {
        "videos": [vmat("MSC", sc.as_posix()), vmat("MCAMF", cam), vmat("MCOMP", "")], "drafts": [dm],
        "common_mask": [], "texts": []},
        "tracks": [{"id": "T0", "type": "video", "name": "", "segments": [seg("SC", "MSC", 0, 60 * S, 0)]},
                   {"id": "T1", "type": "video", "name": "Камера F",
                    "segments": [seg("F1", "MCAMF", 20 * S, 10 * S, 25 * S, volume=0.0)]},
                   {"id": "T2", "type": "video", "name": "Кружок камеры",
                    "segments": [seg("CIR", "MCOMP", 0, 60 * S, 0, refs=["DM1"], volume=0.0)]}]}
    cfg = make_project(d, compounds={"circle": NID_CIRCLE, "cam_full": [], "mic": None, "screencast": None},
                       layout=[{"start": 0.0, "end": 20.0, "layout": "S"}, {"start": 20.0, "end": 30.0, "layout": "F"},
                               {"start": 30.0, "end": 60.0, "layout": "S"}],
                       sfx_dir=str(sfx_dir) if sfx else None)
    return cfg, voice, sr


ITEMS = [
    {"id": "p1", "type": "plate", "start": 2.0, "end": 4.5, "text": "Сначала ниша, потом формат", "accent": "ниша"},
    {"id": "sp1", "type": "split", "start": 21.0, "end": 28.0, "text": ["Пункт один", "Пункт два", "Пункт три"],
     "accent": "два"},
    {"id": "ch2", "type": "chapter", "n": 2, "start": 35.0, "end": 37.5, "text": "Подбираем конкурентов"},
    {"id": "c1", "type": "card", "start": 40.0, "end": 45.0, "text": ["Запрос", "10 конкурентов"], "accent": "10"},
]


def build(cfg, items):
    import gfx_build
    return gfx_build.build(cfg, json.loads(json.dumps(items)))


BOXES = {"top-left": [96, 80, 700, 300], "top-right": [1240, 110, 1800, 400], "left": [0, 0, 960, 1080],
         "wall": [1250, 120, 1800, 400], "bottom-left": [96, 800, 700, 960]}


def fake_render(cfg, comps, bbox=None):
    """render_meta entries without Playwright (the MOV is a stub file): the format render.py writes."""
    import render
    meta = {}
    for cid, c in comps.items():
        mov = cfg.work_dir / "graphics" / "out" / f"{cid}.mov"
        mov.parent.mkdir(parents=True, exist_ok=True)
        mov.write_bytes(b"stub")
        bb = list(bbox) if bbox else BOXES[c["position"]]
        meta[cid] = render.entry(cfg, cid, c, mov, "yuva444p10le", bb)
    (cfg.work_dir / "graphics" / "render_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


# ---------- the three brief tests ----------
def test_render_has_alpha(make_project, tmp_path):
    pytest.importorskip("playwright.sync_api")
    import render
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    comps = build(cfg, [{"id": "h1", "type": "hook", "start": 0.0, "end": 1.0, "text": ["×40 просмотров"],
                         "accent": "×40"}])
    assert set(comps) == {"h1"}
    html = Path(comps["h1"]["html"]).read_text(encoding="utf-8")
    assert "Unbounded" in Path(ROOT / "scripts/graphics/html/base.css").read_text(encoding="utf-8")
    assert "base.css" in html and "anim.js" in html
    meta = render.run(cfg, only=["h1"])
    m = meta["h1"]
    mov = Path(m["file"])
    assert mov == cfg.work_dir / "graphics" / "out" / "h1.mov" and mov.is_file()
    pix = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt,codec_name",
                          "-of", "json", str(mov)], capture_output=True, text=True).stdout
    st = json.loads(pix)["streams"][0]
    assert ("yuva" in st["pix_fmt"] or "argb" in st["pix_fmt"]) and st["codec_name"] == "prores"
    assert m["frames"] == cfg.fps and m["pix_fmt"] == st["pix_fmt"] and abs(m["duration"] - 1.0) < 1e-6
    saved = json.loads((cfg.work_dir / "graphics" / "render_meta.json").read_text(encoding="utf-8"))
    assert saved["h1"]["frames"] == cfg.fps and not m["problems"]
    x0, y0, x1, y1 = m["bbox"]
    assert 0 <= x0 < x1 <= cfg.width and 0 <= y0 < y1 <= cfg.height
    # the font really loaded (not a fallback)
    assert m["font"] == "Unbounded"


def test_apply_graphics_idempotent(make_project, tmp_path):
    import apply_graphics
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    comps = build(cfg, ITEMS)
    fake_render(cfg, comps)
    meta0 = common.read_meta(cfg)
    apply_graphics.run(cfg, dry=False, guard_seconds=0)
    d = common.read_draft(cfg)
    names = [t.get("name") for t in d["tracks"]]
    assert names == ["", "Камера F", "Графика", "Кружок камеры"]   # above the screencast and F, under the circle
    g = d["tracks"][2]
    assert g["type"] == "video" and g["flag"] == 2 and len(g["segments"]) == 4
    ix = common.index(d["materials"])
    by = {Path(common.mat_path(ix, s)).stem: s for s in g["segments"]}
    assert set(by) == {"p1", "sp1", "ch2", "c1"}
    s = by["p1"]
    m = ix[s["material_id"]][1]
    assert m["has_audio"] is False and s["volume"] == 0.0 and not s["enable_video_mask"]
    assert s["target_timerange"] == {"start": common.snap(2.0, cfg.fps), "duration": common.snap(4.5, cfg.fps) -
                                     common.snap(2.0, cfg.fps)}
    assert s["source_timerange"]["start"] == 0 and s["clip"]["scale"] == {"x": 1.0, "y": 1.0}
    # the split moved the camera right (source 35–85 % -> right half): F1 cut at the split edges, keys on the middle
    ft = common.by_start(d["tracks"][1]["segments"])
    assert [(x["target_timerange"]["start"], common.seg_end(x)) for x in ft] == [(20 * S, 21 * S), (21 * S, 28 * S),
                                                                                 (28 * S, 30 * S)]
    px = next(c for c in ft[1]["common_keyframes"] if c["property_type"] == "KFTypePositionX")
    assert [k["values"][0] for k in px["keyframe_list"]] == [0.0, 0.3, 0.3, 0.0]
    assert effects.keyframes_inside(ft[1]) and not ft[0]["common_keyframes"]
    assert not common.check_refs(d) and not common.draft_overlaps(d)
    meta1 = common.read_meta(cfg)
    added = [v for g in meta1["draft_materials"] for v in g.get("value", [])]
    assert sum(1 for v in added if v.get("file_Path", "").endswith("/p1.mov")) == 1
    rec = json.loads((cfg.work_dir / "graphics" / "graphics_applied.json").read_text(encoding="utf-8"))
    assert set(rec["items"]) == {"p1", "sp1", "ch2", "c1"} and rec["items"]["p1"]["segment_id"] == s["id"]
    assert rec["items"]["sp1"]["camera_segment_id"] == ft[1]["id"]
    assert meta0 != meta1

    # the second run: nothing new, nothing written
    before = snapshot(cfg)
    out = apply_graphics.run(cfg, dry=False, guard_seconds=0)
    assert out["added"] == [] and sorted(out["skipped"]) == ["c1", "ch2", "p1", "sp1"]
    assert snapshot(cfg) == before
    d2 = common.read_draft(cfg)
    assert len(next(t for t in d2["tracks"] if t.get("name") == "Графика")["segments"]) == 4
    # record lost -> still one segment (found by the MOV path)
    (cfg.work_dir / "graphics" / "graphics_applied.json").unlink()
    out = apply_graphics.run(cfg, dry=True)
    assert out["added"] == []


def test_no_text_materials_written(make_project, tmp_path):
    import apply_graphics
    import apply_sfx
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    comps = build(cfg, ITEMS)
    for c in comps.values():
        html = Path(c["html"]).read_text(encoding="utf-8")
        assert "<canvas" not in html and "remotion" not in html.lower()
    fake_render(cfg, comps)
    keys0 = set(common.read_draft(cfg)["materials"])
    apply_graphics.run(cfg, dry=False, guard_seconds=0)
    apply_sfx.run(cfg, dry=False, guard_seconds=0)
    d = common.read_draft(cfg)
    assert d["materials"]["texts"] == []
    assert not [t for t in d["tracks"] if t["type"] == "text"]
    assert "texts" not in set(d["materials"]) - keys0
    for p in (ROOT / "scripts" / "graphics").glob("*.py"):
        assert '"texts"' not in p.read_text(encoding="utf-8"), p.name


# ---------- placement rules (hard constraints in gfx_build) ----------
@pytest.mark.parametrize("item, msg", [
    ({"id": "x", "type": "card", "start": 21.0, "end": 25.0, "text": ["a b"]}, "card"),
    ({"id": "x", "type": "plate", "start": 18.0, "end": 21.0, "text": "через границу"}, "S/F"),
    ({"id": "x", "type": "plate", "start": 22.0, "end": 24.5, "text": "Слово рядом", "accent": "рядом",
      "position": "wall"}, "лиц"),
    ({"id": "x", "type": "plate", "start": 2.0, "end": 4.5, "text": "угол", "position": "bottom-right"}, "кружок"),
    ({"id": "x", "type": "split", "start": 2.0, "end": 6.0, "text": ["a"]}, "F"),
    ({"id": "x", "type": "plate", "start": 2.0, "end": 4.5, "text": "один два три четыре пять шесть семь"}, "6"),
    ({"id": "x", "type": "plate", "start": 2.0, "end": 3.0, "text": "коротко"}, "2.0"),
    ({"id": "x", "type": "chapter", "n": 3, "start": 2.0, "end": 6.0, "text": "Глава"}, "2.5"),
    ({"id": "x", "type": "plate", "start": 2.0, "end": 4.5, "text": "ниша", "accent": "формат"}, "accent"),
    ({"id": "x y", "type": "plate", "start": 2.0, "end": 4.5, "text": "ниша"}, "id"),
])
def test_placement_rules(make_project, tmp_path, item, msg):
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    with pytest.raises(SystemExit, match=msg):
        build(cfg, [item])
    assert not (cfg.work_dir / "graphics" / "comps.json").exists()


def test_build_overlap_zero_items_and_merge(make_project, tmp_path):
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    with pytest.raises(SystemExit, match="overlap"):
        build(cfg, [dict(ITEMS[0]), dict(ITEMS[0], id="p2", start=3.0, end=5.5)])
    assert build(cfg, []) == {}
    build(cfg, ITEMS[:1])
    comps = build(cfg, ITEMS[2:3])
    assert set(comps) == {"p1", "ch2"}          # merged by id with the earlier build
    c = comps["p1"]
    assert c["layout"] == "S" and c["position"] == "top-left" and c["sfx"] == [{"t": 2.0, "kind": "in"}]
    assert comps["ch2"]["sfx"][0]["kind"] == "chapter"
    # a focus zoom over a key phrase -> refused (STAGE_8)
    zj = cfg.work_dir / "stage6" / "zooms.json"
    zj.parent.mkdir(parents=True, exist_ok=True)
    zj.write_text(json.dumps({"focus": [{"n": 1, "start": 3.0, "end": 6.0}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="zoom"):
        build(cfg, [dict(ITEMS[0], id="p3")])


def test_bbox_rules():
    import gfx_build
    circ = {"cx": 1800.0, "cy": 812.0, "r": 160.0}
    s_card = {"type": "card", "layout": "S", "position": "top-right"}
    assert gfx_build.bbox_problems(s_card, [1240, 110, 1800, 500], 1920, 1080, circ) == []
    assert any("кружк" in p for p in gfx_build.bbox_problems(s_card, [1240, 110, 1800, 900], 1920, 1080, circ))
    low = {"type": "plate", "layout": "S", "position": "bottom-left"}
    assert any("circle" in p for p in gfx_build.bbox_problems(low, [1000, 800, 1700, 900], 1920, 1080, circ))
    assert gfx_build.bbox_problems(low, [1000, 800, 1600, 900], 1920, 1080, circ) == []   # left of the circle
    plate = {"type": "plate", "layout": "S", "position": "top-left"}
    assert any("90" in p for p in gfx_build.bbox_problems(plate, [20, 80, 600, 200], 1920, 1080))
    wall = {"type": "plate", "layout": "F", "position": "wall"}
    assert any("wall" in p for p in gfx_build.bbox_problems(wall, [1250, 120, 1860, 600], 1920, 1080))


def test_apply_refuses_stale_or_bad_render(make_project, tmp_path):
    import apply_graphics
    import render
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    comps = build(cfg, ITEMS[:1])
    fake_render(cfg, comps, bbox=(96, 80, 1900, 1000))        # outside 90 % and into the circle
    before = snapshot(cfg)
    with pytest.raises(SystemExit, match="p1"):
        apply_graphics.run(cfg, dry=False, guard_seconds=0)
    fake_render(cfg, comps)
    build(cfg, [dict(ITEMS[0], end=4.8)])                       # changed after the render
    with pytest.raises(SystemExit, match="перерендер"):
        apply_graphics.run(cfg, dry=False, guard_seconds=0)
    assert snapshot(cfg) == before
    (cfg.work_dir / "graphics" / "render_meta.json").unlink()
    with pytest.raises(SystemExit, match="render"):
        apply_graphics.run(cfg, dry=True)
    with pytest.raises(SystemExit, match="nope"):
        render.run(cfg, only=["nope"])


def test_render_without_playwright(make_project, tmp_path, monkeypatch):
    import builtins
    import render
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    build(cfg, ITEMS[:1])
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    with pytest.raises(SystemExit, match="playwright install chromium"):
        render.run(cfg)


# ---------- SFX ----------
def test_apply_sfx_levels_and_idempotent(make_project, tmp_path):
    import apply_graphics
    import apply_sfx
    cfg, voice, sr = gfx_project(make_project, tmp_path)
    comps = build(cfg, ITEMS)
    fake_render(cfg, comps)
    apply_graphics.run(cfg, dry=False, guard_seconds=0)
    out = apply_sfx.run(cfg, dry=False, guard_seconds=0)
    d = common.read_draft(cfg)
    sfx = [s for t in d["tracks"] if t["type"] == "audio" and t.get("name", "").startswith("SFX") for s in t["segments"]]
    starts = sorted(s["target_timerange"]["start"] for s in sfx)
    want = [2.0, 21.0, 28.0 - 0.4, 35.0, 40.0]           # entry of each element, split also its exit
    assert len(starts) == len(want)
    for a, w in zip(starts, want):
        assert abs(a - common.us(w)) <= S / cfg.fps, (a, w)
    voice_lu = effects.loudness(voice, sr)["I"]
    ix = common.index(d["materials"])
    by_t = {round(s["target_timerange"]["start"] / S, 1): s for s in sfx}
    for t, off in ((2.0, -12), (35.0, -15)):               # chapter cards 3 dB quieter than the zoom SFX
        s = by_t[t]
        peak = effects.loudness(effects.pcm(ix[s["material_id"]][1]["path"]) * s["volume"])["M_max"]
        assert abs(peak - (voice_lu + off)) <= 1.0, (t, peak, voice_lu)
    assert {e["id"] for e in out["added"]} == {"p1", "sp1", "ch2", "c1"}
    before = snapshot(cfg)
    again = apply_sfx.run(cfg, dry=False, guard_seconds=0)
    assert again["added"] == [] and snapshot(cfg) == before


def test_apply_sfx_needs_sfx_dir(make_project, tmp_path):
    import apply_sfx
    cfg, _v, _sr = gfx_project(make_project, tmp_path, sfx=False)
    comps = build(cfg, ITEMS[:1])
    fake_render(cfg, comps)
    before = snapshot(cfg)
    with pytest.raises(SystemExit, match="sfx_dir"):
        apply_sfx.run(cfg, dry=False, guard_seconds=0)
    assert snapshot(cfg) == before


# ---------- assets and style ----------
def test_anim_defaults_and_style():
    js = (ROOT / "scripts/graphics/html/anim.js").read_text(encoding="utf-8")
    assert "dataset.dur || '0.25'" in js and "dataset.odur || '0.2'" in js and "dataset.dist || '20'" in js
    css = (ROOT / "scripts/graphics/html/base.css").read_text(encoding="utf-8") + \
        (ROOT / "scripts/graphics/html/gfx.css").read_text(encoding="utf-8")
    assert "../../../assets/Unbounded-var.ttf" in css and (ROOT / "assets/Unbounded-var.ttf").stat().st_size > 50_000
    assert not re.search(r"background[^;]*#D46A40", css, re.I), "orange is never a fill"
    colours = {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{6}\b", css)}
    assert colours <= {"#0A0A0A", "#FFFFFF", "#D46A40"}, colours
    assert "rgba(10, 10, 10, 0.85)" in css or "#0A0A0AD9" in css.upper()
    for n in ("hook", "split", "wipe_chapter", "card"):
        h = (ROOT / "assets/examples/html" / f"{n}.html").read_text(encoding="utf-8")
        assert "пример" in h.lower() and "scripts/graphics/html/base.css" in h


FORBIDDEN = ["Гайд" + " конкуренты", "E87" + "DC4D2", "IMG" + "_E02", "AiVideo" + "Editing",
             "4-гайд-на-" + "анализ-конкурентов", "write" + "lo", "stage11" + "_intro", "illustrations" + "/", "sha" + "ra"]


def test_no_forbidden_strings_anywhere():
    bad = []
    for top in ("scripts", "tests", "assets", "references", "templates"):
        for p in (ROOT / top).rglob("*"):
            if p.suffix.lower() not in {".py", ".md", ".json", ".js", ".css", ".html"} or "__pycache__" in p.parts:
                continue
            if p.name == "test_effects.py":           # holds the older list itself
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            bad += [f"{p.relative_to(ROOT)}: {f}" for f in FORBIDDEN if f in text]
            if re.search("Compound" + r" clip\d", text):
                bad.append(f"{p.relative_to(ROOT)}: Compound clipN")
    assert not bad, bad


def test_preview_composites_over_source_frame(make_project, tmp_path):
    pytest.importorskip("playwright.sync_api")
    import preview
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    build(cfg, ITEMS[:1])
    media = Path(__file__).parent / "fixtures" / "media"
    tm = {"tracks": [{"index": 0, "name": "", "segments": [
        {"file": (media / "sc1.mp4").as_posix(), "role": "screencast", "timeline_in_us": 0, "timeline_out_us": 3 * S,
         "source_in_us": 0, "speed": 1.0},
        {"file": (media / "cam1.mp4").as_posix(), "role": "camera", "timeline_in_us": 0, "timeline_out_us": 3 * S,
         "source_in_us": 0, "speed": 1.0}]}]}
    (cfg.work_dir / "stage3").mkdir(parents=True, exist_ok=True)
    (cfg.work_dir / "stage3" / "timeline_map.json").write_text(json.dumps(tm), encoding="utf-8")
    plan = preview.background_plan(cfg, preview.map_pieces(cfg), common.read_layout(cfg), 2.5)
    assert plan["layout"] == "S" and plan["base"][0].endswith("sc1.mp4") and plan["circle"][0].endswith("cam1.mp4")
    (png,) = preview.run(cfg, "p1", [2.5])
    wh = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(png)],
                        capture_output=True, text=True).stdout.strip()
    assert wh == f"{cfg.width},{cfg.height}"


# ---------- fix round 1 ----------
def test_circle_zone_from_the_project(make_project, tmp_path):
    """The circle rule uses the project's circle: moved to the top left, a top-left plate is refused and the
    bottom-right corner is free."""
    import gfx_build
    import render
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    c0 = gfx_build.project_circle(cfg)
    assert abs(c0["cx"] - 1920 / 2 * 1.8) < 1 and abs(c0["cy"] - 540 * 1.68) < 1
    d = common.read_draft(cfg)
    leaf = d["materials"]["drafts"][0]["draft"]["tracks"][1]["segments"][0]
    leaf["clip"]["transform"] = {"x": -0.8, "y": 0.68}
    for p in (cfg.project_dir / "draft_content.json", cfg.project_dir / "Timelines" / TID / "draft_content.json"):
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    c = gfx_build.project_circle(cfg)
    assert abs(c["cx"] - 192) < 1 and abs(c["cy"] - 172.8) < 1 and abs(c["r"] - 153.6) < 1
    comps = build(cfg, ITEMS[:1])
    mov = tmp_path / "x.mov"
    e = render.entry(cfg, "p1", comps["p1"], mov, "yuva444p10le", [96, 80, 700, 300], circle=c)
    assert any("кружк" in p for p in e["problems"]) and e["circle"] == [192.0, 172.8, 153.6]
    corner = dict(comps["p1"], position="bottom-left")
    assert not [p for p in gfx_build.bbox_problems(corner, [1500, 700, 1820, 1000], 1920, 1080, c) if "circle" in p]
    assert [p for p in gfx_build.bbox_problems(corner, [1500, 700, 1820, 1000], 1920, 1080, c0) if "circle" in p]


def test_apply_sfx_only_for_graphics_on_the_timeline(make_project, tmp_path):
    import apply_graphics
    import apply_sfx
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    comps = build(cfg, ITEMS)
    fake_render(cfg, comps)
    apply_graphics.run(cfg, only=["p1"], dry=False, guard_seconds=0)
    out = apply_sfx.run(cfg, dry=False, guard_seconds=0)
    assert [e["id"] for e in out["added"]] == ["p1"]
    assert sorted(out["not_applied"]) == ["c1", "ch2", "sp1"]
    d = common.read_draft(cfg)
    assert sum(len(t["segments"]) for t in effects.sfx_tracks(d)) == 1


def test_render_meta_written_after_each_composition(make_project, tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    import render
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    build(cfg, ITEMS[:1] + ITEMS[3:])
    calls = []

    def fake_comp(page, cfg_, comp, mov):
        calls.append(mov.stem)
        if len(calls) == 2:
            raise BrokenPipeError("ffmpeg died")
        mov.parent.mkdir(parents=True, exist_ok=True)
        mov.write_bytes(b"stub")
        return [96, 80, 700, 300], "Unbounded"
    monkeypatch.setattr(render, "render_comp", fake_comp)
    monkeypatch.setattr(render, "pix_fmt_of", lambda p: "yuva444p10le")
    # an old record of the composition that fails must not survive (its MOV is being overwritten)
    render.meta_path(cfg).write_text(json.dumps({"c1": {"sha": "old"}}), encoding="utf-8")
    with pytest.raises(BrokenPipeError):
        render.run(cfg, only=["p1", "c1"])
    meta = render.read_meta(cfg)
    assert set(meta) == {"p1"} and meta["p1"]["frames"] == 75


def test_split_refuses_keys_on_a_nested_camera_leaf(make_project, tmp_path):
    """Stage 6 push-in = keys on the camera leaf inside the F compound: a split over it is refused."""
    import apply_graphics
    cfg, _v, _sr = gfx_project(make_project, tmp_path)
    d = common.read_draft(cfg)
    cam = d["materials"]["videos"][1]["path"]
    keys = [{"id": "K", "property_type": "KFTypeScaleX", "keyframe_list": [
        {"id": "k1", "time_offset": 26 * S, "values": [1.0]}, {"id": "k2", "time_offset": 28 * S, "values": [1.1]}]}]
    leaf = seg("FL", "MCAMn2", 0, 10 * S, 25 * S, volume=0.0, common_keyframes=keys)
    d["materials"]["drafts"].append(compound("F0F0F0F0-0000-4000-8000-0000000000F0", "DMF", [leaf],
                                             {"videos": [vmat("MCAMn2", cam)]}))
    d["materials"]["videos"].append(vmat("MCOMPF", ""))
    d["tracks"][1]["segments"] = [seg("F1", "MCOMPF", 20 * S, 10 * S, 0, refs=["DMF"], volume=0.0)]
    for p in (cfg.project_dir / "draft_content.json", cfg.project_dir / "Timelines" / TID / "draft_content.json"):
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    comps = build(cfg, [ITEMS[1]])
    fake_render(cfg, comps)
    before = snapshot(cfg)
    with pytest.raises(SystemExit, match="keyframes"):
        apply_graphics.run(cfg, dry=False, guard_seconds=0)
    assert snapshot(cfg) == before
    # without the keys the same split goes through and cuts the compound
    keys.clear()
    d["materials"]["drafts"][-1]["draft"]["tracks"][1]["segments"][0]["common_keyframes"] = []
    for p in (cfg.project_dir / "draft_content.json", cfg.project_dir / "Timelines" / TID / "draft_content.json"):
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert apply_graphics.run(cfg, dry=True)["added"] == ["sp1"]


def test_style_weights_and_orange_labels():
    css = (ROOT / "scripts/graphics/html/base.css").read_text(encoding="utf-8") +         (ROOT / "scripts/graphics/html/gfx.css").read_text(encoding="utf-8")
    body = re.sub(r"@font-face\s*{[^}]*}", "", css)
    weights = [int(w) for w in re.findall(r"font-weight:\s*(\d+)", body)]
    assert weights and min(weights) >= 800, weights
    for sel in (r"\.kicker", r"\.plate\.k"):
        rule = re.search(sel + r"\s*{([^}]*)}", css).group(1)
        assert "D46A40" not in rule.upper(), sel
