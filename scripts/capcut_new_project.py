"""EXPERIMENTAL. Create a new CapCut project («свалка») from source folders.

Status: CapCut 9.5 lists the project on Home with the right duration; opening it in the editor
is NOT verified yet (user check). Fallback: the user creates the project and drops files.

tracks[0] = screencasts back-to-back (sorted by name), tracks[1] = camera back-to-back (muted),
tracks[2] = voice audio (if any). Registers the project in root_meta_info.json (backed up first).
Skeleton/material templates: templates/capcut_new/templates.json (cloned from real CapCut 9.5
projects, personal paths/ids blanked). Format notes: references/capcut-format.md «Создание проекта».
CapCut.exe must not be running (it rewrites root_meta_info.json from memory).

CLI: python -X utf8 scripts/capcut_new_project.py --name NAME --sources DIR [--dst-root DIR]
     DIR contains camera/, screencasts/, voice/ subfolders (camera and voice optional).
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PROJECTS_ROOT, new_id  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "capcut_new" / "templates.json"
EXTS = {".mp4", ".mov", ".m4a", ".mp3", ".wav"}
AUDIO_EXTS = {".m4a", ".mp3", ".wav"}

V_EXTRAS = [("speeds", "speed"), ("placeholder_infos", "placeholder"), ("canvases", "canvas"),
            ("sound_channel_mappings", "sound_channel"), ("material_colors", "material_color"),
            ("vocal_separations", "vocal_separation")]
A_EXTRAS = [("speeds", "speed"), ("placeholder_infos", "placeholder"), ("beats", "beat"),
            ("sound_channel_mappings", "sound_channel"), ("vocal_separations", "vocal_separation")]


def sources_from_dir(root) -> dict:
    root = Path(root)

    def get(n):
        return str(root / n) if (root / n).is_dir() else None
    return {"camera": get("camera"), "screencasts": get("screencasts") or str(root), "voice": get("voice")}


def list_media(d) -> list[Path]:
    if not d or not Path(d).is_dir():
        return []
    return sorted((p for p in Path(d).iterdir() if p.is_file() and p.suffix.lower() in EXTS),
                  key=lambda p: p.name.lower())


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                          "-show_streams", str(path)], capture_output=True, text=True, check=True,
                         encoding="utf-8").stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s.get("codec_type") == "video"), None)
    if path.suffix.lower() in AUDIO_EXTS:
        v = None  # cover art in m4a/mp3 is not a video
    w, h = (int(v["width"]), int(v["height"])) if v else (0, 0)
    if v:  # phone footage with rotation: dims as displayed
        rot = v.get("tags", {}).get("rotate") or next(
            (sd.get("rotation") for sd in v.get("side_data_list", []) if "rotation" in sd), 0)
        if abs(int(float(rot or 0))) in (90, 270):
            w, h = h, w
    return {"duration": int(round(float(j["format"]["duration"]) * 1_000_000)), "width": w, "height": h,
            "has_audio": any(s.get("codec_type") == "audio" for s in j["streams"]), "is_video": v is not None}


def _dump(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


class _Builder:
    def __init__(self, T, now_us):
        self.T, self.now_us = T, now_us
        self.draft = copy.deepcopy(T["empty_draft"])
        self.M = self.draft["materials"]
        self.meta_mats: list[dict] = []

    def _extras(self, kinds):
        refs = []
        for key, tk in kinds:
            m = copy.deepcopy(self.T[tk])
            m["id"] = new_id()
            self.M[key].append(m)
            refs.append(m["id"])
        return refs

    def _meta(self, p: Path, info, metetype):
        mm = copy.deepcopy(self.T["meta_material"])
        mm.update(id=str(uuid.uuid4()), file_Path=p.as_posix(), extra_info=p.name, duration=info["duration"],
                  width=info["width"], height=info["height"], metetype=metetype,
                  create_time=int(p.stat().st_mtime), import_time=self.now_us // 1_000_000,
                  import_time_ms=self.now_us, roughcut_time_range={"start": 0, "duration": info["duration"]})
        self.meta_mats.append(mm)

    def video_track(self, files, mute: bool, render_index: int) -> dict:
        T = self.T
        tr = copy.deepcopy(T["video_track"])
        tr.update(id=new_id(), segments=[], attribute=1 if render_index == 0 else 0)
        t = 0
        for p in files:
            info = probe(p)
            if not info["is_video"]:
                continue
            mat = copy.deepcopy(T["video"])
            mat.update(id=new_id(), path=p.as_posix(), material_name=p.name, duration=info["duration"],
                       width=info["width"], height=info["height"], has_audio=info["has_audio"])
            self.M["videos"].append(mat)
            seg = copy.deepcopy(T["video_segment"])
            seg.update(id=new_id(), material_id=mat["id"], extra_material_refs=self._extras(V_EXTRAS),
                       source_timerange={"start": 0, "duration": info["duration"]},
                       target_timerange={"start": t, "duration": info["duration"]},
                       volume=0.0 if mute else 1.0, last_nonzero_volume=1.0,
                       render_index=render_index, track_render_index=render_index,
                       track_attribute=tr["attribute"])
            tr["segments"].append(seg)
            self._meta(p, info, "video")
            t += info["duration"]
        return tr

    def audio_track(self, files, render_index: int) -> dict:
        T = self.T
        tr = copy.deepcopy(T["audio_track"])
        tr.update(id=new_id(), segments=[])
        t = 0
        for p in files:
            info = probe(p)
            mat = copy.deepcopy(T["audio"])
            mat.update(id=new_id(), path=p.as_posix(), name=p.name, duration=info["duration"])
            self.M["audios"].append(mat)
            seg = copy.deepcopy(T["audio_segment"])
            seg.update(id=new_id(), material_id=mat["id"], extra_material_refs=self._extras(A_EXTRAS),
                       source_timerange={"start": 0, "duration": info["duration"]},
                       target_timerange={"start": t, "duration": info["duration"]},
                       volume=1.0, track_render_index=render_index)
            tr["segments"].append(seg)
            self._meta(p, info, "music")
            t += info["duration"]
        return tr


def _write_skeleton(proj: Path, T: dict, tid: str, now_us: int) -> None:
    tl = proj / "Timelines" / tid
    for k, v in T.items():
        if k.startswith("file:"):
            rel = k[5:]
            _dump((tl if rel == "attachment_editing.json" else proj) / rel, v)
    _dump(tl / "attachment_pc_common.json", T["file:attachment_pc_common.json"])
    _dump(proj / "Timelines" / "project.json", {
        "config": {"color_space": -1, "render_index_track_mode_on": False, "use_float_render": False},
        "create_time": now_us, "id": new_id(), "main_timeline_id": tid,
        "timelines": [{"create_time": now_us, "id": tid, "is_marked_delete": False,
                       "name": "Timeline 01", "update_time": now_us}],
        "update_time": now_us, "version": 0})
    _dump(proj / "timeline_layout.json", {"dockItems": [{"dockIndex": 0, "ratio": 1, "timelineIds": [tid],
                                          "timelineNames": ["Timeline 01"]}], "layoutOrientation": 1})
    s = now_us // 1_000_000
    (proj / "draft_settings").write_text(
        f"[General]\ndraft_create_time={s}\ndraft_last_edit_time={s}\nreal_edit_seconds=0\nreal_edit_keys=0\n",
        encoding="utf-8")
    for d in ["adjust_mask", "matting", "qr_upload", "smart_crop", "subdraft", "Resources/audioAlg",
              "Resources/videoAlg", "common_attachment"]:
        (proj / d).mkdir(parents=True, exist_ok=True)
    (proj / "draft_biz_config.json").write_text("", encoding="utf-8")


def _register(rmi: Path, entry: dict) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak, n = rmi.with_name(f"{rmi.name}.bak-{stamp}"), 1
    while bak.exists():
        n += 1
        bak = rmi.with_name(f"{rmi.name}.bak-{stamp}-{n}")
    shutil.copy2(rmi, bak)
    root = json.loads(rmi.read_text(encoding="utf-8"))
    root.setdefault("all_draft_store", []).insert(0, entry)
    if isinstance(root.get("draft_ids"), int):
        root["draft_ids"] += 1
    _dump(rmi, root)
    return bak


def create_project(name: str, sources: dict, dst_root: Path = PROJECTS_ROOT) -> Path:
    dst_root = Path(dst_root)
    proj = dst_root / name
    rmi = dst_root / "root_meta_info.json"
    if proj.exists():
        raise FileExistsError(proj)
    if not rmi.is_file():
        raise FileNotFoundError(rmi)
    screens = list_media(sources.get("screencasts"))
    if not screens:
        raise ValueError(f"no media in screencasts: {sources.get('screencasts')}")
    T = json.loads(TEMPLATES.read_text(encoding="utf-8"))
    now_us = int(time.time() * 1_000_000)

    b = _Builder(T, now_us)
    tracks = [b.video_track(screens, mute=False, render_index=0)]
    cams = list_media(sources.get("camera"))
    if cams:
        tracks.append(b.video_track(cams, mute=True, render_index=1))
    voice = list_media(sources.get("voice"))
    if voice:
        tracks.append(b.audio_track(voice, render_index=len(tracks)))
    draft = b.draft
    tid = new_id()
    draft.update(id=tid, tracks=tracks,
                 duration=max(sum(s["target_timerange"]["duration"] for s in t["segments"]) for t in tracks))
    first = b.M["videos"][0]
    draft["canvas_config"].update(width=first["width"], height=first["height"], ratio="original")

    proj.mkdir(parents=True)
    _dump(proj / "draft_content.json", draft)
    _dump(proj / "Timelines" / tid / "draft_content.json", draft)
    _write_skeleton(proj, T, tid, now_us)

    draft_id = new_id()
    size = (proj / "draft_content.json").stat().st_size
    meta = copy.deepcopy(T["meta"])
    meta.update(draft_id=draft_id, draft_name=name, draft_fold_path=proj.as_posix(),
                draft_root_path=str(dst_root), tm_draft_create=now_us, tm_draft_modified=now_us,
                tm_duration=draft["duration"], draft_timeline_materials_size_=size)
    for grp in meta["draft_materials"]:
        grp["value"] = b.meta_mats if grp["type"] == 0 else []
    _dump(proj / "draft_meta_info.json", meta)

    ent = copy.deepcopy(T["root_entry"])
    ent.update(draft_id=draft_id, draft_name=name, draft_fold_path=proj.as_posix(),
               draft_root_path=dst_root.as_posix(), draft_cover=proj.as_posix() + "\\draft_cover.jpg",
               draft_json_file=proj.as_posix() + "\\draft_content.json", draft_timeline_materials_size=size,
               tm_draft_create=now_us, tm_draft_modified=now_us, tm_duration=draft["duration"])
    _register(rmi, ent)
    return proj


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", required=True)
    ap.add_argument("--sources", required=True, help="folder with camera/, screencasts/, voice/")
    ap.add_argument("--dst-root", default=str(PROJECTS_ROOT))
    a = ap.parse_args(argv)
    print(create_project(a.name, sources_from_dir(a.sources), Path(a.dst_root)))


if __name__ == "__main__":
    main()
