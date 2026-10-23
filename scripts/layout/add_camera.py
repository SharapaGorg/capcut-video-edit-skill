"""Missing camera piece (STAGE_2.md §7.0, optional): a camera file is in cfg.sources camera/ but not under the
screencast it was recorded with. Adds circle pieces into the circle compound (cfg.compounds.circle).

    python -X utf8 scripts/layout/add_camera.py --config config.json --camera IMG_0001.MOV [--dry] [--resync]

Sync: assembly.json pairs with this camera (ok), else cross-correlation of its audio with every voice file
(layout/xcorr.py). Every screencast piece of a paired file that has no camera yet (and is not an F range of
layout/layout.json) gets a camera piece on the same source range + offset (inherits stages 1-2 cuts), volume 0,
mask and clip from the template. The compound grows if needed. A raw segment of this file dropped on the timeline
is removed. No clear peak -> the piece is new material: stages 0-2 on it (STAGE_2.md). Result in assembly.json
"added_camera".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stage2"))
import assemble  # noqa: E402
import common  # noqa: E402
import effects  # noqa: E402
import make_compound as mc  # noqa: E402
import xcorr  # noqa: E402
from common import by_start, index, seg_end  # noqa: E402


def pairs_for(cfg, camera: str, resync: bool, log=print) -> list[dict]:
    ap = cfg.work_dir / "layout" / "assembly.json"
    rep = json.loads(ap.read_text(encoding="utf-8")) if ap.is_file() else {}
    have = [p for p in rep.get("pairs", []) if p.get("camera") == camera and p.get("ok")]
    if have and not resync:
        return have
    cache = cfg.work_dir / "layout" / "wav"
    cam = xcorr.read_wav(xcorr.to_wav16k(Path(cfg.sources["camera"]) / camera, cache))
    voice, _ = xcorr.source_files(cfg)
    out = []
    for vp in voice:
        r = xcorr.sync(xcorr.read_wav(xcorr.to_wav16k(vp, cache)), cam, xcorr.SR, cfg.fps)
        r.update(voice=vp.name, camera=camera)
        log(f"{vp.name} -> {camera}: offset {r['offset_us'] / 1e6:+.3f} s, z {r['z']}, {'ok' if r['ok'] else 'no peak'}")
        if r["ok"]:
            out.append(r)
    return out


def add(cfg, draft: dict, camera: str, pairs: list[dict], cache_root=None) -> dict:
    nid = (cfg.compounds or {}).get("circle")
    if not nid:
        raise SystemExit("cfg.compounds.circle is empty: run stage2/assemble.py first")
    ps = mc.pieces(draft, nid)
    if len(ps) > 1:
        raise SystemExit(f"the circle compound is cut into {len(ps)} pieces (CapCut split / ripple / hook): add the "
                         "camera inside the piece in CapCut, or before the cuts (stage 2 / LAYOUT A)")
    container, track, outer, dm = mc.find(draft, nid)
    if container is not draft:
        raise SystemExit("the circle compound is nested inside another compound: ungroup that one in CapCut first")
    nd = dm["draft"]
    if outer["source_timerange"]["start"] != 0:
        raise SystemExit("circle compound is trimmed at the start (source_timerange.start != 0); open it in CapCut first")
    T0 = outer["target_timerange"]["start"]
    inner = nd["tracks"][-1]
    covered = [(T0 + s["target_timerange"]["start"], T0 + seg_end(s)) for s in inner["segments"]]
    blocked = assemble._merge(covered + assemble.layout_f(cfg))
    by_voice = {p["voice"]: p for p in pairs}
    parts = assemble._Parts(cfg, nd, cache_root, {})
    cam_dur = parts.base(camera)["duration"]
    pieces = []
    for p in common.flatten(cfg, draft, ("screencast",)):
        pr = by_voice.get(Path(p["path"]).name)
        if not pr:
            continue
        seg = {"target_timerange": {"start": p["start"]}, "source_timerange": {"start": p["src"]}, "speed": p["speed"]}
        for a, b in common.subtract_ranges(p["start"], p["start"] + p["dur"], blocked):
            pc = assemble._cam_piece(seg, a, b, int(pr["offset_us"]), cam_dur, cfg.fps)
            if pc:
                pieces.append(pc)
    if not pieces:
        return {"camera": camera, "added": 0}
    lo = min(min(a for a, *_ in pieces), T0)
    hi = max(max(a + dur for a, dur, *_ in pieces), T0 + nd["duration"])
    shift = T0 - lo
    for s in inner["segments"]:
        s["target_timerange"]["start"] += shift
    mat = parts.cam_material(camera, "add")
    for a, dur, src, sp in pieces:
        parts.segment(inner, mat, a - lo, dur, src, sp, True)
    inner["segments"] = by_start(inner["segments"])
    outer["target_timerange"]["start"] = lo
    mc.set_duration(draft, nid, hi - lo)
    # a raw segment of this camera file dropped on the timeline by the user: remove it (and an emptied track)
    ix = index(draft["materials"])
    raw = {s["id"] for t in draft["tracks"] for s in t["segments"]
           if s.get("material_id") in ix and Path(common.mat_path(ix, s)).name == camera}
    emptied = set()
    for t in draft["tracks"]:
        n = len(t["segments"])
        t["segments"] = [s for s in t["segments"] if s["id"] not in raw]
        if n and not t["segments"]:
            emptied.add(t["id"])
    draft["tracks"] = [t for t in draft["tracks"] if t["id"] not in emptied]
    return {"camera": camera, "added": len(pieces), "timeline_us": [lo, hi], "removed_raw_segments": len(raw),
            "pairs": [{k: p[k] for k in ("voice", "offset_us", "z")} for p in pairs]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="add a missing camera file into the circle compound")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--camera", required=True, help="file name in cfg.sources camera/")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--resync", action="store_true")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    if not cfg.sources.get("camera"):
        raise SystemExit("cfg.sources.camera is empty: no camera folder for this video")
    if not (cfg.compounds or {}).get("circle"):
        print("no circle compound yet (cfg.compounds.circle empty): run stage2/assemble.py first; nothing to do")
        return
    if not (Path(cfg.sources["camera"]) / a.camera).is_file():
        raise SystemExit(f"not found: {Path(cfg.sources['camera']) / a.camera}")
    pairs = pairs_for(cfg, a.camera, a.resync)
    if not pairs:
        raise SystemExit("no clear sync peak with any voice file: new material -> stages 0-2 on it (STAGE_2.md §7.0)")
    d = common.read_draft(cfg)
    try:
        res = add(cfg, d, a.camera, pairs)
    except effects.EffectCacheMissing as e:
        raise SystemExit(str(e))
    print(res)
    errs = common.check_refs(d)
    errs += common.draft_overlaps(d)
    print("VALIDATION:", "OK" if not errs else "FAIL", *errs, sep="\n  ")
    if errs:
        raise SystemExit(1)
    if a.dry or not res["added"]:
        print("dry run, not written" if a.dry else "nothing to add")
        return
    nid = cfg.compounds["circle"]
    common.write_draft(cfg, d, "add-camera", dry=False, subdrafts=mc.subdrafts(cfg, d, [nid]))
    mc.refresh_files(cfg, nid, mc.find(d, nid)[3]["draft"]["duration"])
    ap_ = cfg.work_dir / "layout" / "assembly.json"
    rep = json.loads(ap_.read_text(encoding="utf-8")) if ap_.is_file() else {}
    rep["pairs"] = [p for p in rep.get("pairs", []) if p.get("voice") not in {x["voice"] for x in pairs}] + pairs
    rep.setdefault("added_camera", []).append(res)
    ap_.parent.mkdir(parents=True, exist_ok=True)
    ap_.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written")


if __name__ == "__main__":
    main()
