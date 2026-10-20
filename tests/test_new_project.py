import json

import pytest
import shutil
from pathlib import Path

from common import check_refs, us

FIX = Path(__file__).parent / "fixtures" / "media"


LAYOUT = {"screencasts": ["sc2.mp4", "sc1.mp4"], "camera": ["cam1.mp4"], "voice": ["voice.m4a"]}


@pytest.fixture(autouse=True)
def no_kill(monkeypatch):
    import capcut_new_project as m
    calls = []
    monkeypatch.setattr(m, "ensure_capcut_closed", lambda: calls.append(1))
    return calls


def _dst(tmp_path):
    dst = tmp_path / "projects"
    dst.mkdir()
    (dst / "root_meta_info.json").write_text(json.dumps(
        {"all_draft_store": [], "draft_ids": 0, "root_path": dst.as_posix()}), encoding="utf-8")
    return dst


def _src(tmp_path, layout=LAYOUT):
    root = tmp_path / "src"
    for sub, names in layout.items():
        (root / sub).mkdir(parents=True)
        for n in names:
            shutil.copy(FIX / n, root / sub / n)
    return root


def test_create_project_structure(tmp_path, no_kill):
    from capcut_new_project import create_project, sources_from_dir
    dst = _dst(tmp_path)
    proj = create_project("zz-test", sources_from_dir(_src(tmp_path)), dst_root=dst)

    assert proj == dst / "zz-test"
    tl = [p for p in (proj / "Timelines").iterdir() if p.is_dir()]
    assert len(tl) == 1
    root_d = json.loads((proj / "draft_content.json").read_text(encoding="utf-8"))
    real_d = json.loads((tl[0] / "draft_content.json").read_text(encoding="utf-8"))
    assert root_d == real_d and real_d["id"] == tl[0].name
    assert check_refs(real_d) == []
    v0, v1, a = real_d["tracks"]
    assert [t["type"] for t in (v0, v1, a)] == ["video", "video", "audio"]
    ix = {m["id"]: m for m in real_d["materials"]["videos"] + real_d["materials"]["audios"]}
    names = [Path(ix[s["material_id"]]["path"]).name for s in v0["segments"]]
    assert names == ["sc1.mp4", "sc2.mp4"]
    assert all("/" in ix[s["material_id"]]["path"] and "\\" not in ix[s["material_id"]]["path"]
               for t in (v0, v1, a) for s in t["segments"])
    # back-to-back, durations from ffprobe (~3 s each)
    total = sum(s["target_timerange"]["duration"] for s in v0["segments"])
    assert abs(total - us(6)) < us(0.1)
    assert v0["segments"][1]["target_timerange"]["start"] == v0["segments"][0]["target_timerange"]["duration"]
    assert real_d["duration"] == max(sum(s["target_timerange"]["duration"] for s in t["segments"]) for t in (v0, v1, a))
    assert len(v1["segments"]) == 1 and len(a["segments"]) == 1
    assert ix[v1["segments"][0]["material_id"]]["height"] == 320

    meta = json.loads((proj / "draft_meta_info.json").read_text(encoding="utf-8"))
    assert meta["draft_name"] == "zz-test"
    assert len(meta["draft_materials"][0]["value"]) == 4
    rm = json.loads((dst / "root_meta_info.json").read_text(encoding="utf-8"))
    ent = [e for e in rm["all_draft_store"] if e["draft_name"] == "zz-test"]
    assert len(ent) == 1 and ent[0]["draft_id"] == meta["draft_id"]
    assert ent[0]["draft_fold_path"] == proj.as_posix()
    assert list(dst.glob("root_meta_info.json.bak-*"))
    assert no_kill == [1]
    assert "\\" in meta["draft_root_path"] and "/" not in meta["draft_root_path"]
    assert "\\" not in ent[0]["draft_root_path"]


def _tracks(proj):
    return json.loads((proj / "draft_content.json").read_text(encoding="utf-8"))["tracks"]


def test_no_camera_no_voice(tmp_path):
    from capcut_new_project import create_project, sources_from_dir
    proj = create_project("zz", sources_from_dir(_src(tmp_path, {"screencasts": ["sc1.mp4"]})), _dst(tmp_path))
    assert [t["type"] for t in _tracks(proj)] == ["video"]


def test_no_voice_dir(tmp_path):
    from capcut_new_project import create_project, sources_from_dir
    lay = {"screencasts": ["sc1.mp4"], "camera": ["cam1.mp4"]}
    proj = create_project("zz", sources_from_dir(_src(tmp_path, lay)), _dst(tmp_path))
    assert [t["type"] for t in _tracks(proj)] == ["video", "video"]


def test_non_media_ignored_and_empty_camera(tmp_path):
    from capcut_new_project import create_project, sources_from_dir
    src = _src(tmp_path, {"screencasts": ["sc1.mp4"], "camera": []})
    (src / "screencasts" / "notes.txt").write_text("x", encoding="utf-8")
    shutil.copy(FIX / "voice.m4a", src / "camera" / "a.m4a")  # audio in camera: not a video
    proj = create_project("zz", sources_from_dir(src), _dst(tmp_path))
    tr = _tracks(proj)
    assert [t["type"] for t in tr] == ["video"] and len(tr[0]["segments"]) == 1


def test_cyrillic_space_name(tmp_path):
    from capcut_new_project import create_project, sources_from_dir
    dst = _dst(tmp_path)
    proj = create_project("Новый ролик 1", sources_from_dir(_src(tmp_path)), dst)
    rm = json.loads((dst / "root_meta_info.json").read_text(encoding="utf-8"))
    assert proj.is_dir() and rm["all_draft_store"][0]["draft_name"] == "Новый ролик 1"


def test_screencasts_without_video(tmp_path):
    from capcut_new_project import create_project, sources_from_dir
    dst = _dst(tmp_path)
    src = _src(tmp_path, {"screencasts": ["voice.m4a"]})
    with pytest.raises(ValueError, match="нет видео в screencasts"):
        create_project("zz", sources_from_dir(src), dst)
    assert not (dst / "zz").exists()


def test_failure_removes_project(tmp_path, monkeypatch):
    import capcut_new_project as m
    dst = _dst(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(m, "_register", boom)
    with pytest.raises(RuntimeError):
        m.create_project("zz", m.sources_from_dir(_src(tmp_path)), dst)
    assert not (dst / "zz").exists()


def test_no_kill_refuses_when_running(tmp_path, monkeypatch, no_kill):
    import capcut_new_project as m
    dst = _dst(tmp_path)
    monkeypatch.setattr(m, "capcut_running", lambda: True)
    with pytest.raises(RuntimeError, match="CapCut.exe is running"):
        m.create_project("zz", m.sources_from_dir(_src(tmp_path)), dst, kill=False)
    assert no_kill == [] and not (dst / "zz").exists()


def test_fallback_warns(tmp_path, capsys):
    from capcut_new_project import sources_from_dir
    s = sources_from_dir(tmp_path)
    assert s["screencasts"] == str(tmp_path) and "warning" in capsys.readouterr().err
