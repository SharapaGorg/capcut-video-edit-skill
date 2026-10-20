import json
import shutil
from pathlib import Path

from common import check_refs, us

FIX = Path(__file__).parent / "fixtures" / "media"


def _src(tmp_path):
    root = tmp_path / "src"
    for sub, names in {"screencasts": ["sc2.mp4", "sc1.mp4"], "camera": ["cam1.mp4"], "voice": ["voice.m4a"]}.items():
        (root / sub).mkdir(parents=True)
        for n in names:
            shutil.copy(FIX / n, root / sub / n)
    return root


def test_create_project_opens(tmp_path):
    from capcut_new_project import create_project, sources_from_dir
    dst = tmp_path / "projects"
    dst.mkdir()
    (dst / "root_meta_info.json").write_text(json.dumps(
        {"all_draft_store": [], "draft_ids": 0, "root_path": dst.as_posix()}), encoding="utf-8")
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
