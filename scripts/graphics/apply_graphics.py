"""Stages 7–8: put the rendered MOVs (graphics/out/<id>.mov) on the «Графика» track. Idempotent.

    python -X utf8 scripts/graphics/apply_graphics.py --config config.json [--only ID ...] [--replace] [--dry]

Reads graphics/comps.json + graphics/render_meta.json. Refused (nothing written): an item not rendered, rendered
from another version of the HTML / other times (re-render), with placement problems (render_meta.problems), MOV
missing, overlapping another segment of the track. Already applied = a video segment with this MOV path is on the
timeline (or graphics_applied.json says so) -> skipped; --replace swaps it for the new render (same times only).
Track «Графика» (video, overlay flag 2): above every screencast / full-screen camera / Adjustment track, below the
camera circle — created there on the first run. MOV = video material has_audio false, full frame, volume 0.
Split (and a number on the camera): the full-screen camera piece under it is cut at the split edges and moved right
(Position X 0 -> +0.3 -> 0 = source 35–85 % of the width in the right half; slide 400 ms in and out), like CapCut.
Keys on that camera (the segment itself or a leaf inside its compound: a stage 6 push-in) -> refused: remove them or
move the split. Writes both drafts, the media entries in draft_meta_info, graphics/graphics_applied.json. Never adds texts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import effects  # noqa: E402
import gfx_build  # noqa: E402
import render  # noqa: E402
from common import by_start, seg_end  # noqa: E402

TRACK = "Графика"
SPLIT_SHIFT = 0.3          # clip.transform.x: the camera's 35–85 % of the width lands in the right half


def applied_path(cfg) -> Path:
    return cfg.work_dir / "graphics" / "graphics_applied.json"


def read_applied(cfg) -> dict:
    p = applied_path(cfg)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"items": {}}


def graphics_track(cfg, d: dict, log=print) -> dict:
    """The «Графика» track; created above the screencast / F camera / Adjustment tracks and under the circle."""
    t = next((t for t in d["tracks"] if t["type"] == "video" and t.get("name") == TRACK), None)
    if t is not None:
        return t
    leaves = common.flatten(cfg, d, ("camera", "screencast"))
    below = {p["track"] for p in leaves if not p["mask"]} | {i for i, t in enumerate(d["tracks"]) if t["type"] == "adjust"}
    circle = {p["track"] for p in leaves if p["mask"]} - below
    pos = max(below) + 1 if below else min(circle, default=len(d["tracks"]))
    if any(i < pos for i in circle):
        log("  warning: the camera circle is below a screencast/F track — «Графика» goes above it too "
            "(nothing may enter the circle zone: checked on the render bbox)")
    t = {"id": common.new_id(), "type": "video", "flag": 2, "attribute": 0, "name": TRACK, "is_default_name": False,
         "segments": []}
    d["tracks"].insert(pos, t)
    return t


def camera_host(cfg, d: dict, a: int, b: int) -> tuple[dict, dict]:
    """(track, top-level segment) that shows the full-screen camera over the whole [a, b)."""
    leaves = [p for p in common.flatten(cfg, d, ("camera",)) if not p["mask"] and p["start"] < b and p["end"] > a]
    tracks = {p["track"] for p in leaves}
    cover = sum(min(p["end"], b) - max(p["start"], a) for p in leaves)
    if len(tracks) != 1 or cover < (b - a) - 1000:
        raise ValueError(f"no single full-screen camera track under {a / 1e6:.2f}–{b / 1e6:.2f}")
    t = d["tracks"][tracks.pop()]
    host = [s for s in t["segments"] if s["target_timerange"]["start"] < b and seg_end(s) > a]
    if len(host) != 1 or host[0]["target_timerange"]["start"] > a or seg_end(host[0]) < b:
        raise ValueError(f"the camera under {a / 1e6:.2f}–{b / 1e6:.2f} is not one segment (cut inside?)")
    return t, host[0]


def _nested_segments(d: dict):
    """Every segment of every nested draft (compounds at any depth)."""
    stack = [m.get("draft") for m in d.get("materials", {}).get("drafts", []) or [] if isinstance(m, dict)]
    while stack:
        nd = stack.pop()
        if not isinstance(nd, dict):
            continue
        for t in nd.get("tracks", []):
            yield from t.get("segments", [])
        stack += [m.get("draft") for m in nd.get("materials", {}).get("drafts", []) or [] if isinstance(m, dict)]


def keyed_leaves(cfg, d: dict, ti: int, a: int, b: int) -> list[str]:
    """Leaves of top-level track ti shown in [a, b) (inside compounds too) that carry keyframes — e.g. a stage 6
    push-in on the camera leaf inside the F compound."""
    ids = {p["segment_id"] for p in common.flatten(cfg, d, None)
           if p["track"] == ti and p["compound"] and p["start"] < b and p["end"] > a}
    return sorted({s["id"] for s in _nested_segments(d) if s.get("id") in ids and s.get("common_keyframes")})


def shift_camera(cfg, d: dict, a: int, b: int) -> str:
    """Cut the camera at a, b and slide the middle piece right (400 ms in/out). Returns its segment id.
    Keys on the camera there (top-level segment or a leaf inside its compound, e.g. a stage 6 push-in) -> ValueError."""
    t, host = camera_host(cfg, d, a, b)
    nested = keyed_leaves(cfg, d, d["tracks"].index(t), a, b)
    if host.get("common_keyframes") or nested:
        where = "the camera segment" if host.get("common_keyframes") else f"camera pieces inside its compound {nested}"
        raise ValueError(f"{where} under {a / 1e6:.2f}–{b / 1e6:.2f} has keyframes (push-in, stage 6?) — "
                         "remove them or move the split")
    common.split_at(d, t, [a, b])
    piece = next(s for s in t["segments"] if s["target_timerange"]["start"] == a)
    D = (seg_end(piece) - a) / 1e6
    frame = 1.0 / cfg.fps
    tx = float(((piece.get("clip") or {}).get("transform") or {}).get("x", 0.0))
    effects.zoom_keyframes(piece, 0.0, D - gfx_build.PANEL - frame, D - frame, 1.0, cx=round(tx + SPLIT_SHIFT, 6),
                           ramp_in=gfx_build.PANEL)
    t["segments"] = by_start(t["segments"])
    return piece["id"]


def drop_segment(d: dict, seg: dict) -> None:
    for t in d["tracks"]:
        if seg in t["segments"]:
            t["segments"].remove(seg)
    vids = d["materials"].get("videos", [])
    d["materials"]["videos"] = [m for m in vids if m.get("id") != seg["material_id"]]


def run(cfg, only=None, dry: bool = False, replace: bool = False, guard_seconds: float = 5, log=print) -> dict:
    comps = gfx_build.read_comps(cfg)
    if not comps:
        raise SystemExit(f"нет {gfx_build.comps_path(cfg)}: сначала gfx_build.py и render.py")
    rmeta = render.read_meta(cfg)
    if not rmeta:
        raise SystemExit(f"нет {render.meta_path(cfg)}: сначала render.py")
    ids = list(only) if only else list(comps)
    errs = [f"{i}: not in comps.json" for i in ids if i not in comps]
    for cid in [i for i in ids if i in comps]:
        c, m = comps[cid], rmeta.get(cid)
        if m is None:
            errs.append(f"{cid}: not rendered — render.py --only {cid}")
        elif m["sha"] != c["sha"] or abs(m["start"] - c["start"]) > 1e-6 or abs(m["end"] - c["end"]) > 1e-6:
            errs.append(f"{cid}: render_meta устарел (HTML/время изменились) — перерендерить: render.py --only {cid}")
        elif m["problems"]:
            errs.append(f"{cid}: placement problems after the render: {m['problems']}")
        elif not Path(m["file"]).is_file():
            errs.append(f"{cid}: MOV missing: {m['file']}")
    if errs:
        raise SystemExit("графика не вставлена:\n  - " + "\n  - ".join(errs))

    d = common.read_draft(cfg)
    rec = read_applied(cfg)
    ix = common.index(d["materials"])
    by_path = {}
    for t in d["tracks"]:
        for s in t["segments"]:
            if s.get("material_id") in ix and ix[s["material_id"]][0] == "videos":
                by_path.setdefault(common._norm(common.mat_path(ix, s)), s)
    out = {"added": [], "skipped": [], "replaced": []}
    todo = []
    for cid in ids:
        m = rmeta[cid]
        old = by_path.get(common._norm(m["file"]))
        r = rec["items"].get(cid)
        if old is None and r:
            old = next((s for t in d["tracks"] for s in t["segments"] if s["id"] == r.get("segment_id")), None)
        if old is not None:
            same_time = (old["target_timerange"]["start"] == m["start_us"]
                         and seg_end(old) == m["end_us"])
            fresh = r is not None and r.get("sha") == m["sha"]
            if not replace or (fresh and same_time):
                out["skipped"].append(cid)
                continue
            if not same_time:
                errs.append(f"{cid}: already on the timeline at other times — --replace only for the same times "
                            "(restore the backup or remove it in CapCut)")
                continue
            drop_segment(d, old)
            out["replaced"].append(cid)
        todo.append(cid)
    if errs:
        raise SystemExit("графика не вставлена:\n  - " + "\n  - ".join(errs))
    if not todo:
        log(f"nothing new: {len(out['skipped'])} already applied")
        return out

    track = graphics_track(cfg, d, log)
    meta = common.read_meta(cfg)
    for cid in sorted(todo, key=lambda i: rmeta[i]["start_us"]):
        c, m = comps[cid], rmeta[cid]
        a, b = m["start_us"], m["end_us"]
        clash = [s for s in track["segments"] if s["target_timerange"]["start"] < b and seg_end(s) > a]
        if clash:
            errs.append(f"{cid}: overlaps another segment of «{TRACK}» at {a / 1e6:.3f}–{b / 1e6:.3f}")
            continue
        cam = None
        if c.get("panel") and not (cid in out["replaced"] and rec["items"].get(cid, {}).get("camera_segment_id")):
            try:
                cam = shift_camera(cfg, d, a, b)
            except ValueError as e:
                errs.append(f"{cid}: split: {e}")
                continue
        seg, mat = effects.overlay_video_segment(d, track, m["file"], a, b - a, cfg.width, cfg.height)
        common.add_meta_material(meta, m["file"], b - a, cfg.width, cfg.height)
        r = {"segment_id": seg["id"], "material_id": mat["id"], "track_id": track["id"], "start": m["start"],
             "end": m["end"], "start_us": a, "end_us": b, "mov": m["file"], "sha": m["sha"], "type": c["type"]}
        if cam or rec["items"].get(cid, {}).get("camera_segment_id"):
            r.update(camera_segment_id=cam or rec["items"][cid]["camera_segment_id"], camera_shift=SPLIT_SHIFT)
        rec["items"][cid] = r
        out["added"].append(cid)
        log(f"  {cid}: {a / 1e6:.3f}–{b / 1e6:.3f} {Path(m['file']).name}" + (" + camera right" if cam else ""))
    track["segments"] = by_start(track["segments"])
    errs += common.check_refs(d) + common.draft_overlaps(d)
    errs += [f"keys outside the segment {s['id']}" for t in d["tracks"] for s in t["segments"]
             if not effects.keyframes_inside(s)]
    log(f"added {len(out['added'])}, skipped {len(out['skipped'])}; «{TRACK}» has {len(track['segments'])} segments")
    log("VALIDATION:", "OK" if not errs else "FAIL")
    if errs:
        raise SystemExit("графика не вставлена:\n  - " + "\n  - ".join(errs))
    if dry:
        log("dry run, not written")
        return out
    out["backup"] = str(common.write_draft(cfg, d, "graphics", dry=False, guard_seconds=guard_seconds))
    common.write_meta(cfg, meta, dry=False)
    rec["track_id"] = track["id"]
    applied_path(cfg).parent.mkdir(parents=True, exist_ok=True)
    applied_path(cfg).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    log("written:", applied_path(cfg))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="stages 7–8: rendered MOVs -> «Графика» track")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--replace", action="store_true", help="swap an applied item for its new render (same times)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.only, a.dry, a.replace)


if __name__ == "__main__":
    main()
