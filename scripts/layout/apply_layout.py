"""LAYOUT B4: the camera on full screen (F) over approved timeline ranges in the screencast part.

    python -X utf8 scripts/layout/apply_layout.py --config config.json --ranges f.json [--dry]

f.json: [[start, end], ...] or [{"start", "end"}] timeline seconds (end null = timeline end), e.g.
layout/f_ranges_proposed.json after approval. For every range the camera pieces of the circle (cfg.compounds.circle,
else the track whose camera pieces have a mask) are copied out at the same source times as full-screen segments
(no mask, scale 1, volume 0) onto the overlay track «Камера F» (created above the circle if absent). The screencast
and the circle stay underneath (the voice comes from the screencast). Refused (nothing written): a range that
overlaps an existing F (full-screen camera in the project or an F row of layout.json), F < 4 s, an edge inside a
word (stage3/transcript_timeline.json), a sped screencast in the range, the camera not covering it.
Writes both drafts (common.write_draft) and layout/layout.json {layout: [{start, end, layout: S|F}]} over the whole
timeline. Next: make_compound_f.py (compound per F stretch + Adjustment), then STAGE_3 steps 1–4 (build_maps.py).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stage2"))
import common  # noqa: E402
import make_compound as mc  # noqa: E402
from common import by_start, seg_end, source_role  # noqa: E402

F_MIN = 4.0
GAP_MIN = 15.0
F_TRACK = "Камера F"


def circle_track(cfg, draft: dict) -> dict:
    """Top-level track of the circle: the track of compound cfg.compounds.circle, else the track holding most
    masked camera pieces."""
    nid = (cfg.compounds or {}).get("circle")
    if nid:
        try:
            container, t, _s, _dm = mc.find(draft, nid)
            if container is draft:
                return t
        except KeyError:
            pass
    c = Counter(p["track"] for p in common.flatten(cfg, draft, ("camera",)) if p["mask"])
    if not c:
        raise SystemExit("кружок камеры не найден (нет камеры с маской): F строится из кусков кружка")
    return draft["tracks"][c.most_common(1)[0][0]]


def check_ranges(cfg, draft: dict, ranges: list[tuple[int, int]]) -> list[str]:
    errs, notes = [], []
    dur = draft["duration"]
    existing = common.f_ranges(cfg, draft)
    words = common.timeline_words(cfg)
    sped = [(p["start"], p["end"]) for p in common.flatten(cfg, draft, ("screencast",)) if abs(p["speed"] - 1.0) > 1e-6]
    for i, (A, B) in enumerate(ranges):
        tag = f"{A / 1e6:.3f}–{B / 1e6:.3f}"
        if not (0 <= A < B <= dur):
            errs.append(f"{tag}: вне таймлайна (0–{dur / 1e6:.3f})")
            continue
        if (B - A) / 1e6 < F_MIN - 1e-6:
            errs.append(f"{tag}: F короче {F_MIN:.0f} с")
        for x, y in existing:
            if x < B and y > A:
                errs.append(f"{tag}: перекрывает существующий F {x / 1e6:.3f}–{y / 1e6:.3f}")
        for A2, B2 in ranges[i + 1:]:
            if A2 < B and B2 > A:
                errs.append(f"{tag}: перекрывает другой диапазон {A2 / 1e6:.3f}–{B2 / 1e6:.3f}")
        if any(x < B and y > A for x, y in sped):
            errs.append(f"{tag}: F поверх ускоренного скринкаста")
        for t in (A, B):
            w = common.inside_word(words, t / 1e6, tol=0.01)
            if w and t not in (0, dur):
                errs.append(f"{tag}: граница {t / 1e6:.3f} внутри слова «{w['word']}» {w['start']}–{w['end']}")
    switches = sorted(({x for A, B in ranges for x in (A, B)} | {x for a, b in existing for x in (a, b)}) - {0, dur})
    for p, q in zip(switches, switches[1:]):
        if (q - p) / 1e6 < GAP_MIN:
            notes.append(f"между переключениями {p / 1e6:.3f} и {q / 1e6:.3f} < {GAP_MIN:.0f} с (допустимо только "
                         "во вступлении/заключении)")
    for n in notes:
        print("  note:", n)
    return errs


def f_track(draft: dict, after: dict) -> dict:
    t = next((t for t in draft["tracks"] if t.get("name") == F_TRACK and t["type"] == "video"), None)
    if t is None:
        t = {"id": common.new_id(), "type": "video", "flag": 2, "attribute": 0, "name": F_TRACK,
             "is_default_name": False, "segments": []}
        draft["tracks"].insert(draft["tracks"].index(after) + 1, t)
    return t


def apply(cfg, draft: dict, ranges: list[tuple[int, int]]) -> list[dict]:
    """Mutates draft: full-screen camera pieces for every range. Returns the log [{timeline_us, file, source_us}]."""
    ct = circle_track(cfg, draft)
    ft = f_track(draft, ct)
    log = []
    for A, B in ranges:
        new = []
        for s in by_start(ct["segments"]):
            if seg_end(s) <= A or s["target_timerange"]["start"] >= B:
                continue
            for p in common.lift(draft, s, A, B):
                if source_role(cfg, p["path"]) != "camera":
                    continue
                n = common.adopt(draft, p, drop_cats=("common_mask",))
                if abs(float(n.get("speed", 1.0)) - 1.0) > 1e-6:
                    raise SystemExit(f"{A / 1e6:.3f}–{B / 1e6:.3f}: камера ускорена — F поверх ускоренного куска нельзя")
                n.update(clip=copy.deepcopy(mc.CLIP_FULL), enable_video_mask=False, volume=0.0, common_keyframes=[],
                         keyframe_refs=[])
                new.append(n)
        cover = common.merge_ranges([(n["target_timerange"]["start"], seg_end(n)) for n in new], int(1e6 / cfg.fps))
        holes = common.subtract_ranges(A, B, cover)
        if holes:
            raise SystemExit(f"{A / 1e6:.3f}–{B / 1e6:.3f}: камера кружка не покрывает "
                             + ", ".join(f"{x / 1e6:.3f}–{y / 1e6:.3f}" for x, y in holes))
        for n in new:
            if any(x["target_timerange"]["start"] < seg_end(n) and seg_end(x) > n["target_timerange"]["start"]
                   for x in ft["segments"]):
                raise SystemExit(f"дорожка «{F_TRACK}» уже занята в {A / 1e6:.3f}–{B / 1e6:.3f}")
            ft["segments"].append(n)
            m = common.index(draft["materials"])[n["material_id"]][1]
            log.append({"timeline_us": [n["target_timerange"]["start"], seg_end(n)], "file": Path(m["path"]).name,
                        "source_us": [n["source_timerange"]["start"],
                                      n["source_timerange"]["start"] + n["source_timerange"]["duration"]]})
    ft["segments"] = by_start(ft["segments"])
    for i, t in enumerate(draft["tracks"]):
        if t["type"] == "video":
            for s in t["segments"]:
                s["render_index"] = s["track_render_index"] = i
    return log


def run(cfg, ranges_s: list[tuple], dry: bool, guard_seconds: float = 5) -> list[dict]:
    d = common.read_draft(cfg)
    dur = d["duration"]
    ranges = sorted((common.snap(a, cfg.fps), dur if b is None else min(common.snap(b, cfg.fps), dur))
                    for a, b in ranges_s)
    if not ranges:
        raise SystemExit("нет диапазонов F")
    errs = check_ranges(cfg, d, ranges)
    if errs:
        raise SystemExit("F не применён:\n  - " + "\n  - ".join(errs))
    old_f = common.f_ranges(cfg, d)
    log = apply(cfg, d, ranges)
    errs = common.check_refs(d)
    for t in d["tracks"]:
        segs = by_start(t["segments"])
        errs += [f"overlap on {t.get('name') or t['type']} at {seg_end(p) / 1e6:.3f}" for p, q in zip(segs, segs[1:])
                 if seg_end(p) > q["target_timerange"]["start"] + 1]
    rows = common.layout_rows(old_f + ranges, dur, common.read_layout(cfg))
    for r in log:
        print(f"  F {r['timeline_us'][0] / 1e6:.3f}–{r['timeline_us'][1] / 1e6:.3f} <- {r['file']} "
              f"{r['source_us'][0] / 1e6:.3f}")
    f_total = sum(r["end"] - r["start"] for r in rows if r["layout"] == "F")
    print(f"layout: {len(rows)} rows, F {f_total:.1f} s of {dur / 1e6:.1f} s")
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)
    if dry:
        print("dry run, not written")
        return rows
    bk = common.write_draft(cfg, d, "layout-apply", dry=False, guard_seconds=guard_seconds)
    prev = json.loads((cfg.work_dir / "layout" / "layout.json").read_text(encoding="utf-8")).get("f_segments", []) \
        if (cfg.work_dir / "layout" / "layout.json").is_file() else []
    common.write_layout(cfg, rows, f_segments=prev + log, backup=str(bk))
    print("written; next: make_compound_f.py, then build_maps.py (STAGE_3 steps 1–4)")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="LAYOUT B4: full-screen camera over approved ranges")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--ranges", required=True, help="JSON [[start, end]] timeline seconds (end null = to the end)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    run(cfg, common.parse_ranges(json.loads(Path(a.ranges).read_text(encoding="utf-8"))), a.dry)


if __name__ == "__main__":
    main()
