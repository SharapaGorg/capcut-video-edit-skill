"""Stage 1 apply (references/stages/STAGE_1.md §5): approved cuts on all tracks at once, ripple, no holes.

    python -X utf8 scripts/stage1/apply_cuts.py --config config.json [--dry]

Input (<work_dir>/stage1/): cuts_candidates.json (build_proposal.py); approved_ids.json [ids] — the user's answer
(absent -> all «точно»); chapters_input.json. Times = transcript time (= timeline before stage 1).
Cut edges are snapped to the frame grid inwards (margins to the kept words only grow).
Output: cuts_approved.json [{id, start_us, end_us, text}], cuts_applied.json (cuts + shift of every kept piece),
chapters.json; both draft files + draft_meta_info tm_duration.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
from common import by_start, index, new_id, seg_end  # noqa: E402


def approved_cuts(s1: Path, fps: int) -> list[dict]:
    cand = json.loads((s1 / "cuts_candidates.json").read_text(encoding="utf-8"))
    ap = s1 / "approved_ids.json"
    ids = set(json.loads(ap.read_text(encoding="utf-8"))) if ap.is_file() else {r["id"] for r in cand if r["conf"] == "точно"}
    frame = 1_000_000 / fps
    out = []
    for r in cand:
        if r["id"] not in ids:
            continue
        out.append({"id": r["id"], "start_us": int(math.ceil(r["start"] * fps - 1e-6) * frame),
                    "end_us": int(math.floor(r["end"] * fps + 1e-6) * frame), "text": r["text"]})
    out.sort(key=lambda c: c["start_us"])
    for a, b in zip(out, out[1:]):
        if a["end_us"] > b["start_us"]:
            raise SystemExit(f"approved cuts {a['id']} and {b['id']} overlap")
    return [c for c in out if c["end_us"] > c["start_us"]]


def gaps(track) -> int:
    segs = by_start(track["segments"])
    return sum(1 for p, q in zip(segs, segs[1:]) if q["target_timerange"]["start"] - seg_end(p) > 1)


def ripple(draft: dict, cuts: list[tuple[int, int]]) -> list[dict]:
    """Remove [a, b) ranges (timeline us) from every track, shift the rest left. Returns per-piece records."""
    mats = draft["materials"]
    byid = index(mats)

    def new_t(t):
        return t - sum(min(b, t) - a for a, b in cuts if a < t)

    def kept(a, b):
        out, cur = [], a
        for x, y in cuts:
            if y <= cur or x >= b:
                continue
            if x > cur:
                out.append((cur, x))
            cur = max(cur, y)
        if cur < b:
            out.append((cur, b))
        return out

    def clone(mid):
        k, m = byid[mid]
        c = copy.deepcopy(m)
        c["id"] = new_id()
        mats[k].append(c)
        byid[c["id"]] = (k, c)
        return c["id"]

    rec = []
    for ti, t in enumerate(draft["tracks"]):
        segs = []
        for s in by_start(t["segments"]):
            a, b = s["target_timerange"]["start"], seg_end(s)
            parts = kept(a, b)
            if not parts:
                rec.append({"track": ti, "segment_id": s["id"], "old_start_us": a, "old_end_us": b, "removed": True})
                continue
            sp = float(s.get("speed", 1.0))
            src0 = (s.get("source_timerange") or {}).get("start")
            for pi, (x, y) in enumerate(parts):
                seg = s if pi == 0 else copy.deepcopy(s)
                if pi > 0:
                    seg["id"] = new_id()
                    seg["material_id"] = clone(seg["material_id"])
                    seg["extra_material_refs"] = [clone(e) for e in seg.get("extra_material_refs") or []]
                if src0 is not None:
                    seg["source_timerange"] = {"start": src0 + int(round((x - a) * sp)), "duration": int(round((y - x) * sp))}
                seg["target_timerange"] = {"start": new_t(x), "duration": y - x}
                segs.append(seg)
                rec.append({"track": ti, "segment_id": seg["id"], "old_start_us": x, "old_end_us": y,
                            "new_start_us": new_t(x), "shift_us": x - new_t(x), "removed": False})
        t["segments"] = segs
    draft["duration"] = new_t(draft["duration"])
    return rec


def run(cfg, dry: bool, guard_seconds: float = 5) -> dict:
    s1 = cfg.work_dir / "stage1"
    cuts = approved_cuts(s1, cfg.fps)
    d = common.read_draft(cfg)
    orig = copy.deepcopy(d)
    gaps0 = [gaps(t) for t in d["tracks"]]
    old = d["duration"]
    rec = ripple(d, [(c["start_us"], c["end_us"]) for c in cuts])
    total = sum(c["end_us"] - c["start_us"] for c in cuts if c["start_us"] < old)
    errs = common.check_refs(d)
    for ti, t in enumerate(d["tracks"]):
        segs = by_start(t["segments"])
        errs += [f"overlap track {ti} at {seg_end(p) / 1e6:.3f}" for p, q in zip(segs, segs[1:])
                 if seg_end(p) > q["target_timerange"]["start"] + 1]
        if gaps(t) > gaps0[ti]:
            errs.append(f"track {ti}: new holes ({gaps0[ti]} -> {gaps(t)})")
    end = max((seg_end(s) for t in d["tracks"] for s in t["segments"]), default=0)
    if end > d["duration"] + 1:
        errs.append(f"segments end at {end} after duration {d['duration']}")
    for c in cuts:
        if any(not r["removed"] and r["old_start_us"] < c["end_us"] and r["old_end_us"] > c["start_us"] for r in rec):
            errs.append(f"a kept piece overlaps cut {c['id']}")
    changed = {k for k in d if d[k] != orig[k]} - {"tracks", "materials", "duration"}
    if changed:
        errs.append(f"unexpected top-level change {sorted(changed)}")
    print(f"cuts: {len(cuts)}, {total / 1e6:.3f} s; duration {old / 1e6:.3f} -> {d['duration'] / 1e6:.3f}")
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)
    out = {"source_duration_us": old, "new_duration_us": d["duration"], "cuts": cuts, "segments": rec}
    if dry:
        print("dry run, not written")
        return out
    common.write_draft(cfg, d, "stage1", dry=False, guard_seconds=guard_seconds)
    meta = common.read_meta(cfg)
    if "tm_duration" in meta:
        meta["tm_duration"] = d["duration"]
        common.write_meta(cfg, meta, dry=False)
    (s1 / "cuts_approved.json").write_text(json.dumps(cuts, ensure_ascii=False, indent=1), encoding="utf-8")
    (s1 / "cuts_applied.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    chp = s1 / "chapters_input.json"
    if chp.is_file():
        (s1 / "chapters.json").write_text(chp.read_text(encoding="utf-8"), encoding="utf-8")
    print("written")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 1: apply approved cuts")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.dry)


if __name__ == "__main__":
    main()
