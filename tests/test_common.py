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
