import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import common

FIX = Path(__file__).parent / "fixtures" / "mini_project"
TID = "0A1B2C3D-0000-4000-8000-000000000001"
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ensure_capcut_closed", lambda: None)
    p = tmp_path / "proj"
    shutil.copytree(FIX, p)
    work = tmp_path / "work"
    work.mkdir()
    cfg = {"project_dir": str(p), "timeline_id": None,
           "sources": {"camera": "c", "screencasts": "s", "voice": None},
           "sfx_dir": "x", "music_dir": "y"}
    cp = work / "config.json"
    cp.write_text(json.dumps(cfg), encoding="utf-8")
    return p, cp


def test_load_config_single_timeline(proj):
    p, cp = proj
    cfg = common.load_config(str(cp))
    assert cfg.timeline_id == TID
    assert cfg.work_dir == cp.parent
    assert cfg.sources["voice"] is None
    assert cfg.fps == 30 and cfg.width == 1920 and cfg.height == 1080
    assert [x.name for x in common.draft_paths(cfg)] == ["draft_content.json"] * 2
    assert common.read_draft(cfg)["duration"] == 10000000


def test_load_config_ambiguous_timelines(proj):
    p, cp = proj
    (p / "Timelines" / "OTHER").mkdir()
    with pytest.raises(ValueError, match="Timelines"):
        common.load_config(str(cp))


def test_write_draft_dry_writes_nothing(proj, monkeypatch):
    p, cp = proj
    def boom():
        raise AssertionError("must not kill CapCut on dry")
    monkeypatch.setattr(common, "ensure_capcut_closed", boom)
    cfg = common.load_config(str(cp))
    before = [(x, x.read_bytes()) for x in common.draft_paths(cfg)]
    d = common.read_draft(cfg)
    d["duration"] = 1
    assert common.write_draft(cfg, d, "t", dry=True) is None
    for x, b in before:
        assert x.read_bytes() == b
    assert not (cfg.work_dir / "backups").exists()


def test_write_draft_writes_both_files(proj):
    p, cp = proj
    cfg = common.load_config(str(cp))
    paths = common.draft_paths(cfg)
    m0 = [x.stat().st_mtime_ns for x in paths]
    d = common.read_draft(cfg)
    old_ut = d["update_time"]
    d["duration"] = 12345
    bk = common.write_draft(cfg, d, "stageX", dry=False,
                            subdrafts={"SUB1": {"duration": 7}}, guard_seconds=0)
    for x, m in zip(paths, m0):
        assert x.stat().st_mtime_ns != m
        j = json.loads(x.read_text(encoding="utf-8"))
        assert j["duration"] == 12345 and j["update_time"] > old_ut
    assert json.loads((p / "subdraft" / "SUB1" / "draft_content.json").read_text(encoding="utf-8"))["duration"] == 7
    assert bk.is_dir() and bk.parent == cfg.work_dir / "backups"
    assert bk.name.startswith("stageX-before-")
    assert json.loads((bk / "draft_content.json").read_text(encoding="utf-8"))["duration"] == 10000000


def test_check_refs_detects_missing_material(proj):
    p, cp = proj
    d = json.loads((FIX / "draft_content.json").read_text(encoding="utf-8"))
    assert common.check_refs(d) == []
    d["materials"]["videos"].pop(1)
    errs = common.check_refs(d)
    assert len(errs) == 1 and "M0000000-0000-4000-8000-00000000000B" in errs[0]


def test_helpers():
    d = json.loads((FIX / "draft_content.json").read_text(encoding="utf-8"))
    ix = common.index(d["materials"])
    segs = common.by_start(list(reversed(d["tracks"][0]["segments"])))
    assert common.seg_end(segs[0]) == 5000000
    assert common.mat_path(ix, segs[1]).endswith("b.mp4")
    assert common.us(1.5) == 1500000 and common.sec(2500000) == 2.5
    assert len(common.new_id()) == 36 and common.new_id().isupper()


def test_find_effect_cache(tmp_path):
    (tmp_path / "111" / "abc").mkdir(parents=True)
    (tmp_path / "222" / "h").mkdir(parents=True)
    (tmp_path / "222" / "h" / "extra.json").write_text('{"resource_id":"7777"}', encoding="utf-8")
    assert common.find_effect_cache("111", cache_root=tmp_path) == tmp_path / "111"
    assert common.find_effect_cache("7777", cache_root=tmp_path) == tmp_path / "222"
    assert common.find_effect_cache("9999", cache_root=tmp_path) is None


def test_init_creates_config_and_dirs(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    proj = tmp_path / "proj"
    shutil.copytree(FIX, proj)
    r = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "init_video.py"),
                        "--sources", str(src), "--project", str(proj)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    work = src / "edit"
    for sub in ["transcript", "stage1", "stage10", "layout", "graphics", "stage12_shorts", "backups"]:
        assert (work / sub).is_dir(), sub
    cfg = json.loads((work / "config.json").read_text(encoding="utf-8"))
    assert cfg["timeline_id"] == TID and Path(cfg["project_dir"]) == proj
    assert (work / "PROGRESS.md").read_text(encoding="utf-8").startswith("# Прогресс монтажа")
    c = common.load_config(str(work / "config.json"))
    assert c.timeline_id == TID and c.work_dir == work


def test_check_refs_segment_without_material_id():
    d = json.loads((FIX / "draft_content.json").read_text(encoding="utf-8"))
    del d["tracks"][0]["segments"][0]["material_id"]
    d["tracks"][0]["segments"][1]["material_id"] = ""
    assert common.check_refs(d) == []


def test_find_effect_cache_no_cross_match(tmp_path):
    (tmp_path / "1110").mkdir()
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "extra.json").write_text('{"resource_id":"2220"}', encoding="utf-8")
    (tmp_path / "y").mkdir()
    (tmp_path / "y" / "extra.json").write_text('{"effect_id":"222"}', encoding="utf-8")
    assert common.find_effect_cache("111", cache_root=tmp_path) is None
    assert common.find_effect_cache("1110", cache_root=tmp_path) == tmp_path / "1110"
    assert common.find_effect_cache("222", cache_root=tmp_path) == tmp_path / "y"


def test_find_effect_cache_no_localappdata(monkeypatch):
    monkeypatch.setattr(common, "EFFECT_CACHE", None)
    assert common.find_effect_cache("111") is None


def test_backup_twice_in_a_row(proj):
    p, cp = proj
    cfg = common.load_config(str(cp))
    a = common.backup(cfg, "s")
    b = common.backup(cfg, "s")
    assert a != b and a.is_dir() and b.is_dir()


def _init(src, proj, *extra):
    r = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "init_video.py"),
                        "--sources", str(src), "--project", str(proj), *extra],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r


def _fps25(proj):
    for p in [proj / "draft_content.json", *proj.glob("Timelines/*/draft_content.json")]:
        d = json.loads(p.read_text(encoding="utf-8"))
        d["fps"] = 25.0
        d["canvas_config"].update(width=1280, height=720)
        p.write_text(json.dumps(d), encoding="utf-8")


def test_init_reads_fps_and_size_from_draft(tmp_path, capsys, monkeypatch):
    """I3: a 25-fps 1280×720 project -> config fps 25, 1280×720; a config that disagrees with the draft warns,
    and fails with strict (or VIDEO_EDIT_STRICT=1)."""
    src, proj = tmp_path / "src", tmp_path / "proj"
    src.mkdir()
    shutil.copytree(FIX, proj)
    _fps25(proj)
    _init(src, proj)
    cp = src / "edit" / "config.json"
    raw = json.loads(cp.read_text(encoding="utf-8"))
    assert (raw["fps"], raw["width"], raw["height"]) == (25, 1280, 720)
    capsys.readouterr()
    c = common.load_config(str(cp))
    assert c.fps == 25 and "warning" not in capsys.readouterr().err
    raw["fps"] = 30
    cp.write_text(json.dumps(raw), encoding="utf-8")
    common.load_config(str(cp))
    assert "fps 30 != draft 25" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="fps 30 != draft 25"):
        common.load_config(str(cp), strict=True)
    monkeypatch.setenv("VIDEO_EDIT_STRICT", "1")
    with pytest.raises(SystemExit):
        common.load_config(str(cp))


def test_init_rerun_merges_config(tmp_path):
    """I4: a re-run keeps what later stages wrote (compounds, master_render, tiktok_channel); --force overwrites."""
    src, proj = tmp_path / "src", tmp_path / "proj"
    src.mkdir()
    shutil.copytree(FIX, proj)
    _init(src, proj)
    cp = src / "edit" / "config.json"
    raw = json.loads(cp.read_text(encoding="utf-8"))
    raw.update(compounds={"mic": "M", "cam_full": ["F1"], "screencast": "S", "circle": "C"}, master_render="m.mp4",
               tiktok_channel="@chan", sfx_dir="E:/sfx")
    cp.write_text(json.dumps(raw), encoding="utf-8")
    r = _init(src, proj, "--music", "E:/music")
    new = json.loads(cp.read_text(encoding="utf-8"))
    assert new["compounds"]["mic"] == "M" and new["master_render"] == "m.mp4" and new["tiktok_channel"] == "@chan"
    assert new["sfx_dir"] == "E:/sfx" and new["music_dir"] == "E:/music"   # missing value filled
    assert "merged" in r.stdout
    _init(src, proj, "--force")
    new = json.loads(cp.read_text(encoding="utf-8"))
    assert new["compounds"]["mic"] is None and new["master_render"] is None
