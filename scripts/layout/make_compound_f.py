"""LAYOUT B4 (2/2): full-screen camera pieces -> one compound per F stretch + an Adjustment block over it.

    python -X utf8 scripts/layout/make_compound_f.py --config config.json [--dry]

Takes the raw top-level camera segments without a mask (made by apply_layout.py), groups them per track into
stretches (touching within 1 frame) and wraps each stretch into its own compound (stage2/make_compound.wrap: never
mixed with the screencast or the circle, those are other tracks). Over every stretch: an Adjustment block
(effects.adjustment_segment, Temp −18 / Sat 10) on the adjust track — one continuous block per F run (a block that
touches the stretch is extended). Refused: an Adjustment block that would lie over a part without the full-screen
camera (over the screencast). Writes both drafts + subdraft/, draft_meta_info, cfg.compounds.cam_full.
Nothing raw to wrap -> no-op.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stage2"))
import common  # noqa: E402
import effects  # noqa: E402
import make_compound as mc  # noqa: E402
from common import index, seg_end, source_role  # noqa: E402

NAME = "Камера F"


def raw_f(cfg, draft: dict) -> dict[int, list[dict]]:
    """{track index: [raw full-screen camera segments]} on the top level (not compounds, no mask)."""
    ix = index(draft["materials"])
    drafts = {m["id"] for m in draft["materials"].get("drafts", []) or [] if isinstance(m, dict)}
    out: dict[int, list[dict]] = {}
    for ti, t in enumerate(draft["tracks"]):
        if t["type"] != "video":
            continue
        for s in t["segments"]:
            if s.get("material_id") not in ix or common.has_mask(s, ix) or set(s.get("extra_material_refs") or []) & drafts:
                continue
            if source_role(cfg, common.mat_path(ix, s)) == "camera":
                out.setdefault(ti, []).append(s)
    return out


def adjust_track(draft: dict, above: dict) -> dict:
    t = next((t for t in draft["tracks"] if t["type"] == "adjust"), None)
    if t is None:
        t = {"id": common.new_id(), "type": "adjust", "flag": 0, "attribute": 0, "name": "", "is_default_name": True,
             "segments": []}
        draft["tracks"].insert(draft["tracks"].index(above) + 1, t)
    return t


def run(cfg, dry: bool, cache_root=None, guard_seconds: float = 5) -> dict:
    d = common.read_draft(cfg)
    groups = raw_f(cfg, d)
    tol = int(1e6 / cfg.fps)
    if not groups:
        print("no raw full-screen camera segments: nothing to wrap")
        return {"made": [], "stretches": []}
    made, stretches = [], []
    k = len((cfg.compounds or {}).get("cam_full") or [])
    tracks = {ti: d["tracks"][ti] for ti in groups}
    for ti, segs in sorted(groups.items()):
        track = tracks[ti]
        for x, y in common.merge_ranges([(s["target_timerange"]["start"], seg_end(s)) for s in segs], tol):
            part = [s for s in segs if x <= s["target_timerange"]["start"] < y]
            k += 1
            kind = "main" if track is d["tracks"][0] else "overlay"
            c = mc.wrap(d, track, part, f"{NAME} {k}", kind, 0.0, cfg.project_dir, cfg.width, cfg.height)
            made.append(c)
            stretches.append((x, y, track))
    for x, y, track in stretches:
        at = adjust_track(d, track)
        touch = next((s for s in at["segments"] if abs(seg_end(s) - x) <= tol or abs(s["target_timerange"]["start"] - y) <= tol), None)
        if any(s["target_timerange"]["start"] < y and seg_end(s) > x for s in at["segments"]):
            print(f"  Adjustment already over {x / 1e6:.3f}–{y / 1e6:.3f}")
        elif touch is not None:
            a, b = min(touch["target_timerange"]["start"], x), max(seg_end(touch), y)
            touch["target_timerange"] = {"start": a, "duration": b - a}
            print(f"  Adjustment extended to {a / 1e6:.3f}–{b / 1e6:.3f}")
        else:
            effects.adjustment_segment(d, at, x, y - x, cache_root=cache_root)
    errs = mc.errors(d, made) + common.draft_overlaps(d)
    full = common.full_camera_ranges(cfg, d)
    for t in d["tracks"]:
        if t["type"] != "adjust":
            continue
        for s in t["segments"]:
            a, b = s["target_timerange"]["start"], seg_end(s)
            bad = [(p, q) for p, q in common.subtract_ranges(a, b, full) if q - p > tol]
            if bad:
                errs.append(f"Adjustment {a / 1e6:.3f}–{b / 1e6:.3f} over a part without full-screen camera: "
                            + ", ".join(f"{p / 1e6:.3f}–{q / 1e6:.3f}" for p, q in bad))
    for c in made:
        print(f"{c.name}: {c.n} segments -> compound {c.nid}, {c.outer['target_timerange']['start'] / 1e6:.3f}"
              f"+{c.outer['target_timerange']['duration'] / 1e6:.3f} s")
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)
    res = {"made": made, "stretches": [(x, y) for x, y, _ in stretches]}
    if dry:
        print("dry run, not written")
        return res
    common.write_draft(cfg, d, "layout-compound-f", dry=False, guard_seconds=guard_seconds,
                       subdrafts={c.nid: c.wrapper for c in made})
    mc.write_files(cfg, made)
    comp = dict(cfg.compounds or {})
    comp["cam_full"] = list(comp.get("cam_full") or []) + [c.nid for c in made]
    common.save_config_field(cfg, "compounds", comp)
    print("written")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="LAYOUT B4: compound per F stretch + Adjustment block")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    try:
        run(common.load_config(a.config), a.dry)
    except effects.EffectCacheMissing as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
