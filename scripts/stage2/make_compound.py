"""Compound clips: move segments of a track into a nested draft (materials.drafts[].draft), leave one outer
segment, plus the subdraft/<id>/ folder and the draft_meta_info.json entry (type 18) — the structure CapCut
makes itself (skeletons in assets/templates/compound.json, harvested by harvest_templates.py).

    python -X utf8 scripts/stage2/make_compound.py --config config.json --role screencast|voice [--dry]

The CLI wraps all segments of one source role (screencast or voice) on their track; camera compounds (circle,
full-screen per stretch) only via assemble.py, which uses wrap()/write_files().
Audio compounds: CapCut plays a pre-render Resources/combination/<combination_id>_audio.aac; prerender_audio()
makes it with ffmpeg, else audio_path stays "" and CapCut renders it itself (capcut-format.md).
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
from common import by_start, index, new_id, seg_end  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent.parent / "assets" / "templates" / "compound.json"
PLACEHOLDER = "##_draftpath_placeholder_0E685133-18CE-45ED-8CB8-2904A212EC80_##"  # CapCut constant, all projects
UNIT_CROP = {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0,
             "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0}
CLIP_FULL = {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "transform": {"x": 0.0, "y": 0.0},
             "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0}
SR = 48000


@dataclass
class Compound:
    nid: str              # nested draft id = subdraft/<nid>; this is what cfg.compounds stores
    cid: str              # combination_id (audio pre-render name)
    name: str
    kind: str             # main | overlay | audio
    nested: dict
    outer: dict           # outer segment
    wrapper: dict = field(default_factory=dict)
    subcfg: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    n: int = 0


def _tpl() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def _fresh(o, name: str):
    if isinstance(o, dict):
        return {k: _fresh(v, name) for k, v in o.items()}
    if isinstance(o, list):
        return [_fresh(v, name) for v in o]
    if o == "{{ID}}":
        return new_id()
    if o == "{{NAME}}":
        return name
    return o


def _refs(seg) -> list[str]:
    return [seg["material_id"]] + list(seg.get("extra_material_refs") or [])


def wrap(draft: dict, track: dict, segs: list[dict], name: str, kind: str, volume: float,
         project_dir: Path, width: int = 1920, height: int = 1080) -> Compound:
    """Move segs (all on `track`) into a new nested draft; one outer segment replaces them on `track`.
    Materials only used by segs move; ones still used by other outer segments are copied."""
    tpl = _tpl()
    mats = draft["materials"]
    keys = [k for k, v in mats.items() if isinstance(v, list)]
    segs = by_start(segs)
    ids = {s["id"] for s in segs}
    T0 = segs[0]["target_timerange"]["start"]
    dur = max(seg_end(s) for s in segs) - T0
    nid, cid = new_id(), new_id()

    nested = _fresh(tpl["nested"], name)
    nested.update(id=nid, name=name, duration=dur, materials={k: [] for k in keys})
    inner = {"id": new_id(), "type": "audio" if kind == "audio" else "video", "flag": 2 if kind == "overlay" else 0,
             "attribute": 0, "name": "", "is_default_name": True, "segments": []}
    base = [] if kind == "main" else [{"id": new_id(), "type": "video", "flag": 0, "attribute": 0, "name": "",
                                       "is_default_name": True, "segments": []}]
    nested["tracks"] = base + [inner]
    moved = set()
    for s in segs:
        s = copy.deepcopy(s)
        s["target_timerange"]["start"] -= T0
        inner["segments"].append(s)
        moved.update(_refs(s))
    track["segments"] = [x for x in track["segments"] if x["id"] not in ids]
    still = {r for t in draft["tracks"] for x in t["segments"] for r in _refs(x)}
    for k in keys:
        nested["materials"][k] = [copy.deepcopy(m) for m in mats[k] if isinstance(m, dict) and m.get("id") in moved]
        mats[k] = [m for m in mats[k] if not (isinstance(m, dict) and m.get("id") in moved and m["id"] not in still)]

    sub = f"{PLACEHOLDER}\\subdraft\\{nid}"
    dm = _fresh(tpl["drafts_entry"], name)
    dm.update(id=new_id(), combination_id=cid, draft=nested, draft_file_path=f"{sub}\\draft_content.json",
              draft_cover_path=f"{sub}\\draft_cover.jpg", draft_config_path=f"{sub}\\sub_draft_config.json")
    mats.setdefault("drafts", []).append(dm)

    part = tpl["audio" if kind == "audio" else "video"]
    omat = _fresh(part["material"], name)
    omat.update(id=new_id(), duration=dur)
    if kind == "audio":
        omat.update(name=name, path=f"{PLACEHOLDER}/Resources/combination/{cid}_audio.aac")
        mats.setdefault("audios", []).append(omat)
    else:
        omat.update(material_name=name, path="", media_path="", width=width, height=height, has_audio=True,
                    crop=copy.deepcopy(UNIT_CROP), crop_ratio="free", crop_scale=1.0)
        mats.setdefault("videos", []).append(omat)
    extras = [dm["id"]]
    extra_mats = []
    for e in part["extra"]:
        m = _fresh(e["material"], name)
        m["id"] = new_id()
        if e["category"] == "speeds":
            m.update(speed=1.0, curve_speed=None)
        mats.setdefault(e["category"], []).append(m)
        extras.append(m["id"])
        extra_mats.append((e["category"], m))
    oseg = _fresh(part["segment"], name)
    first = segs[0]
    oseg.update(id=new_id(), material_id=omat["id"], extra_material_refs=extras, speed=1.0, volume=float(volume),
                last_nonzero_volume=float(volume) or 1.0, source_timerange={"start": 0, "duration": dur},
                target_timerange={"start": T0, "duration": dur}, keyframe_refs=[], common_keyframes=[],
                render_index=first.get("render_index", 0), track_render_index=first.get("track_render_index", 0),
                track_attribute=first.get("track_attribute", 0))
    if kind != "audio":
        oseg.update(clip=copy.deepcopy(CLIP_FULL), enable_video_mask=False)
    track["segments"].append(oseg)
    cfgd = draft.setdefault("config", {})
    cfgd["combination_max_index"] = max(cfgd.get("combination_max_index", 1), len(mats["drafts"]) + 1)

    # subdraft/<nid>/draft_content.json: a one-segment draft holding the drafts entry (absolute paths)
    proj = str(project_dir).replace("\\", "/")
    wrapper = _fresh(tpl["wrapper"], name)
    wrapper.update(id=new_id(), duration=dur)
    wrapper["materials"] = {k: ([] if isinstance(v, list) else v) for k, v in wrapper["materials"].items()}
    dabs = copy.deepcopy(dm)
    for k in ("draft_file_path", "draft_cover_path", "draft_config_path"):
        dabs[k] = dabs[k].replace(PLACEHOLDER, proj)
    wrapper["materials"].setdefault("drafts", []).append(dabs)
    wrapper["materials"].setdefault("audios" if kind == "audio" else "videos", []).append(copy.deepcopy(omat))
    for k, m in extra_mats:
        wrapper["materials"].setdefault(k, []).append(copy.deepcopy(m))
    wseg = copy.deepcopy(oseg)
    wseg.update(id=new_id(), target_timerange={"start": 0, "duration": dur})
    wrapper["tracks"] = [{"id": new_id(), "type": inner["type"], "flag": 0, "attribute": 0, "name": "",
                          "is_default_name": True, "segments": [wseg]}]
    now = int(time.time())
    subcfg = _fresh(tpl["sub_draft_config"], name)
    subcfg.update(audio_path="", id=nid, project_id=nid, name=name, rough_cut_duration=dur, rough_cut_start=0,
                  create_time=now, import_time_ms=now * 1000, type="audio" if kind == "audio" else "video",
                  cover_height=0 if kind == "audio" else height, cover_width=0 if kind == "audio" else width,
                  cover_path=f"{proj}\\subdraft\\{nid}\\draft_cover.jpg" if kind == "audio" else "draft_cover.jpg")
    meta = _fresh(tpl["meta_entry"], name)
    meta.update(id=new_id(), create_time=now, import_time=now, import_time_ms=now * 1000, duration=dur,
                extra_info=name, file_Path=f"./subdraft/{nid}/sub_draft_config.json",
                roughcut_time_range={"start": 0, "duration": dur})
    return Compound(nid=nid, cid=cid, name=name, kind=kind, nested=nested, outer=oseg, wrapper=wrapper,
                    subcfg=subcfg, meta=meta, n=len(segs))


def prerender_audio(project_dir: Path, comp: Compound, log=print) -> Path | None:
    """Mix the nested segments (speed 1 only) into Resources/combination/<cid>_audio.aac and point the
    sub_draft_config at it. None (audio_path stays "") if it cannot: CapCut renders it on open."""
    nd = comp.nested
    jx = index(nd["materials"])
    segs = [s for t in nd["tracks"] for s in t["segments"] if t["type"] == "audio"]
    if any(abs(float(s.get("speed", 1.0)) - 1.0) > 1e-6 for s in segs):
        log(f"{comp.name}: sped segments, no pre-render (CapCut renders it)")
        return None
    out = np.zeros((int(round(nd["duration"] * SR / 1e6)) + 1, 2), dtype=np.float32)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            decoded: dict[str, np.ndarray] = {}
            for s in segs:
                path = jx[s["material_id"]][1].get("path") or ""
                if path not in decoded:
                    raw = Path(tmp) / f"{len(decoded)}.f32"
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "2", "-ar", str(SR),
                                    "-f", "f32le", str(raw)], check=True)
                    decoded[path] = np.fromfile(raw, dtype=np.float32).reshape(-1, 2)
                a = decoded[path]
                t0 = int(round(s["target_timerange"]["start"] * SR / 1e6))
                s0 = int(round(s["source_timerange"]["start"] * SR / 1e6))
                n = int(round(s["source_timerange"]["duration"] * SR / 1e6))
                chunk = a[s0:s0 + n][: len(out) - t0] * float(s.get("volume", 1.0))
                out[t0:t0 + len(chunk)] += chunk
            mix = Path(tmp) / "mix.f32"
            out.tofile(mix)
            aac = project_dir / "Resources" / "combination" / f"{comp.cid}_audio.aac"
            aac.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(mix),
                            "-c:a", "aac", "-b:a", "256k", str(aac)], check=True)
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        log(f"{comp.name}: pre-render failed ({e}); CapCut renders it on open")
        return None
    comp.subcfg["audio_path"] = aac.as_posix()
    return aac


def write_files(cfg, comps: list[Compound]) -> None:
    """subdraft/<nid>/{sub_draft_config.json, draft_cover.jpg} + draft_meta_info entries (type 18).
    subdraft/<nid>/draft_content.json goes through common.write_draft(subdrafts=...)."""
    proj = cfg.project_dir
    meta = common.read_meta(cfg)
    groups = meta.setdefault("draft_materials", [])
    g18 = next((g for g in groups if g.get("type") == 18), None)
    if g18 is None:
        g18 = {"type": 18, "value": []}
        groups.append(g18)
    cover = proj / "draft_cover.jpg"
    for c in comps:
        sd = proj / "subdraft" / c.nid
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "sub_draft_config.json").write_text(json.dumps(c.subcfg, ensure_ascii=False, separators=(",", ":")),
                                                  encoding="utf-8")
        if cover.is_file():
            shutil.copy(cover, sd / "draft_cover.jpg")
        g18["value"].append(c.meta)
    common.write_meta(cfg, meta, dry=False)


def find(draft: dict, nid: str):
    """(container draft, track, outer segment, drafts material) of the compound whose nested draft id is nid — by
    segment ref, never by name (CapCut renames nested drafts); also when it was later nested into another compound."""
    def walk(d, dix):
        ix = index(d.get("materials", {}))
        dix = common._drafts_ix(d, dix)
        for t in d.get("tracks", []):
            for s in t["segments"]:
                for e in s.get("extra_material_refs") or []:
                    if e in dix and (dix[e].get("draft") or {}).get("id") == nid:
                        return d, t, s, dix[e]
        for t in d.get("tracks", []):
            for s in t["segments"]:
                dm = next((dix[e] for e in s.get("extra_material_refs") or [] if e in dix), None)
                if dm and isinstance(dm.get("draft"), dict) and s.get("material_id") in ix:
                    r = walk(dm["draft"], dix)
                    if r:
                        return r
        return None

    r = walk(draft, {})
    if r is None:
        raise KeyError(f"compound {nid} not found on the timeline (cfg.compounds stale?)")
    return r


def set_duration(draft: dict, nid: str, dur: int) -> None:
    """Nested draft, outer segment and outer material durations after a change inside the compound."""
    container, _t, s, dm = find(draft, nid)
    dm["draft"]["duration"] = dur
    s["target_timerange"]["duration"] = dur
    s["source_timerange"] = {"start": 0, "duration": dur}
    index(container["materials"])[s["material_id"]][1]["duration"] = dur


def refresh(cfg, draft: dict, nid: str) -> dict | None:
    """subdraft/<nid>/draft_content.json with the current nested draft and duration (for write_draft(subdrafts=));
    None if the folder is absent. Durations in sub_draft_config / draft_meta_info: refresh_files()."""
    p = cfg.project_dir / "subdraft" / nid / "draft_content.json"
    if not p.is_file():
        return None
    nd = find(draft, nid)[3]["draft"]
    w = json.loads(p.read_text(encoding="utf-8"))
    w["duration"] = nd["duration"]
    for t in w.get("tracks", []):
        for s in t["segments"]:
            s["target_timerange"]["duration"] = nd["duration"]
            s["source_timerange"] = {"start": 0, "duration": nd["duration"]}
    for k in ("videos", "audios"):
        for m in w["materials"].get(k, []):
            m["duration"] = nd["duration"]
    for x in w["materials"].get("drafts", []):
        x["draft"] = copy.deepcopy(nd)
    return w


def refresh_files(cfg, nid: str, dur: int) -> None:
    """sub_draft_config rough_cut_duration + draft_meta_info entry duration (call after write_draft)."""
    cp = cfg.project_dir / "subdraft" / nid / "sub_draft_config.json"
    if cp.is_file():
        c = json.loads(cp.read_text(encoding="utf-8"))
        c["rough_cut_duration"] = dur
        cp.write_text(json.dumps(c, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    meta = common.read_meta(cfg)
    for g in meta.get("draft_materials", []):
        for e in g.get("value", []):
            if nid in (e.get("file_Path") or ""):
                e["duration"] = dur
                e["roughcut_time_range"] = {"start": 0, "duration": dur}
    common.write_meta(cfg, meta, dry=False)


def errors(draft: dict, comps: list[Compound]) -> list[str]:
    errs = common.check_refs(draft)
    for c in comps:
        segs = by_start(c.nested["tracks"][-1]["segments"])
        if segs[0]["target_timerange"]["start"] != 0 or max(seg_end(s) for s in segs) != c.nested["duration"]:
            errs.append(f"{c.name}: nested range != duration")
        errs += common.overlap_errors(c.nested["tracks"][-1], f"{c.name} (inside)")
    return errs


ROLE_KIND = {"screencast": ("main", 1.0), "voice": ("audio", 1.0)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="wrap all segments of one source role into a compound clip")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--role", required=True, choices=sorted(ROLE_KIND) + ["camera"])
    ap.add_argument("--name")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    if a.role == "camera":
        raise SystemExit("camera is not wrapped here: circle -> 1 compound and full-screen camera -> 1 per stretch "
                         "are built by scripts/stage2/assemble.py")
    cfg = common.load_config(a.config)
    d = common.read_draft(cfg)
    ix = index(d["materials"])
    hits = [(t, s) for t in d["tracks"] for s in t["segments"]
            if s.get("material_id") in ix and common.source_role(cfg, common.mat_path(ix, s)) == a.role]
    tracks = {id(t): t for t, _ in hits}
    if len(tracks) != 1:
        raise SystemExit(f"{a.role}: expected segments on exactly one track, found {len(tracks)}")
    track = next(iter(tracks.values()))
    kind, vol = ROLE_KIND[a.role]
    c = wrap(d, track, [s for _, s in hits], a.name or a.role, kind, vol, cfg.project_dir, cfg.width, cfg.height)
    errs = errors(d, [c])
    print(f"{a.role}: {c.n} segments -> compound {c.nid} ({c.outer['target_timerange']['duration'] / 1e6:.3f} s)")
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)
    if a.dry:
        print("dry run, not written")
        return
    common.write_draft(cfg, d, f"compound-{a.role}", dry=False, subdrafts={c.nid: c.wrapper})
    if kind == "audio":
        prerender_audio(cfg.project_dir, c)
    write_files(cfg, [c])
    key = {"screencast": "screencast", "voice": "mic"}.get(a.role)
    if key:
        common.save_config_field(cfg, "compounds", dict(cfg.compounds, **{key: c.nid}))
    print("written")


if __name__ == "__main__":
    main()
