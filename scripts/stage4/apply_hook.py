"""Stage 4: the hook — copies of timeline pieces put at the very start; everything shifts right.

    python -X utf8 scripts/stage4/apply_hook.py --config config.json --hook hook.json [--dry] [--force]
                                                [--no-maps] [--no-audio-check]

hook.json: the approved variant (hook_proposal.md), pieces in CURRENT timeline seconds, in hook order:
[[a, b], ...] | [{"start", "end"}] | {"variant": "B", "pieces": [...]}. Edges snap to frames and must not cut a word
(stage3/transcript_timeline.json).
For every track, the segments under the piece are copied to the hook position on the same track, clipped to the
piece, as CapCut copy/split does (common.clone_piece: own material + extras — voice effects, Adjust, mask stay;
a compound piece keeps pointing at the same nested draft, like a compound CapCut cut into pieces). The originals stay
where they were, shifted by the hook length together with everything else (nested drafts untouched). Then: draft_meta_info tm_duration, stage4/hook_applied.json, layout.json
shifted with the hook rows in front, and STAGE_3 steps 1–4 (build_maps.run) — unless --no-maps.
Ending check (STAGE_4): the last 20 s should be F in layout.json — printed as a note.
A second run is refused (stage4/hook_applied.json exists) unless --force.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stage3"))
import common  # noqa: E402
from common import by_start, seg_end  # noqa: E402

END_S = 20.0
HOOK_MAX = 30.0


def load(path) -> tuple[str | None, list[tuple]]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    variant = obj.get("variant") if isinstance(obj, dict) else None
    return variant, common.parse_ranges(obj)


def build(cfg, d: dict, pieces: list[tuple[int, int]]) -> tuple[list[tuple], int]:
    """Mutates d: hook copies at the start of each track, the rest shifted. Returns ([(track index, new seg)], L)."""
    L = sum(b - a for a, b in pieces)
    new = []
    for ti, t in enumerate(d["tracks"]):
        made = []
        off = 0
        for a, b in pieces:
            for s in by_start(t["segments"]):
                x, y = max(a, s["target_timerange"]["start"]), min(b, seg_end(s))
                if y <= x:
                    continue
                n = common.clone_piece(d, s, x, y)
                n["target_timerange"]["start"] = off + x - a
                made.append(n)
            off += b - a
        for s in t["segments"]:
            s["target_timerange"]["start"] += L
        t["segments"] = by_start(t["segments"] + made)
        new += [(ti, n) for n in made]
    d["duration"] += L
    return new, L


def validate(cfg, d: dict, orig: dict, new: list, L: int) -> list[str]:
    errs = common.check_refs(d)
    for t in d["tracks"]:
        ss = by_start(t["segments"])
        errs += [f"overlap on {t.get('name') or t['type']} at {seg_end(p) / 1e6:.3f}" for p, q in zip(ss, ss[1:])
                 if seg_end(p) > q["target_timerange"]["start"] + 1]
    main = by_start(d["tracks"][0]["segments"]) if d["tracks"] else []
    if main and main[0]["target_timerange"]["start"] != 0:
        errs.append("main track does not start at 0")
    errs += [f"main track hole at {seg_end(p) / 1e6:.3f}" for p, q in zip(main, main[1:])
             if q["target_timerange"]["start"] - seg_end(p) > 1]
    ids = {n["id"] for _, n in new}
    old = {s["id"]: s for t in orig["tracks"] for s in t["segments"]}
    for t in d["tracks"]:
        for s in t["segments"]:
            if s["id"] in ids:
                continue
            o = old.get(s["id"])
            if o is None or s["target_timerange"]["start"] != o["target_timerange"]["start"] + L \
                    or s["target_timerange"]["duration"] != o["target_timerange"]["duration"] \
                    or s.get("source_timerange") != o.get("source_timerange"):
                errs.append(f"original segment changed: {s['id']}")
    if len(old) + len(new) != sum(len(t["segments"]) for t in d["tracks"]):
        errs.append("segment count")
    if [m.get("draft") for m in d["materials"].get("drafts", [])][:len(orig["materials"].get("drafts", []))] != \
            [m.get("draft") for m in orig["materials"].get("drafts", [])]:
        errs.append("nested drafts changed")
    return errs


def shift_layout(rows: list[dict], pieces: list[tuple[int, int]], L: int) -> list[dict]:
    """Hook rows (layout of the copied parts) in front, the old rows shifted by L (seconds)."""
    out, off = [], 0
    for a, b in pieces:
        for r in rows:
            x, y = max(r["start"] * 1e6, a), min(r["end"] * 1e6, b)
            if y > x:
                out.append({"start": round((off + x - a) / 1e6, 6), "end": round((off + y - a) / 1e6, 6),
                            "layout": r["layout"], "note": f"хук (этап 4): копия {a / 1e6:.3f}–{b / 1e6:.3f}"})
        if not any(r["start"] * 1e6 < b and r["end"] * 1e6 > a for r in rows):
            out.append({"start": round(off / 1e6, 6), "end": round((off + b - a) / 1e6, 6), "layout": "S",
                        "note": f"хук (этап 4): копия {a / 1e6:.3f}–{b / 1e6:.3f}"})
        off += b - a
    sh = L / 1e6
    for r in rows:
        r = dict(r, start=round(r["start"] + sh, 6), end=round(r["end"] + sh, 6))
        out.append(r)
    return out


def run(cfg, pieces_s: list[tuple], dry: bool, guard_seconds: float = 5, maps: bool = True,
        audio_check: bool = True, force: bool = False, variant: str | None = None) -> dict:
    logp = cfg.work_dir / "stage4" / "hook_applied.json"
    if logp.is_file() and not force:
        raise SystemExit(f"хук уже применён ({logp}); повторно — только с --force")
    d = common.read_draft(cfg)
    orig = copy.deepcopy(d)
    dur0 = d["duration"]
    pieces = [(common.snap(a, cfg.fps), dur0 if b is None else min(common.snap(b, cfg.fps), dur0)) for a, b in pieces_s]
    words = common.timeline_words(cfg)
    errs = []
    for a, b in pieces:
        if not 0 <= a < b <= dur0:
            errs.append(f"piece {a / 1e6:.3f}–{b / 1e6:.3f} outside the timeline")
        for t in (a, b):
            w = common.inside_word(words, t / 1e6, tol=0.01)
            if w:
                errs.append(f"edge {t / 1e6:.3f} inside the word «{w['word']}» {w['start']}–{w['end']}")
    if errs:
        raise SystemExit("хук не применён:\n  - " + "\n  - ".join(errs))
    new, L = build(cfg, d, pieces)
    errs = validate(cfg, d, orig, new, L)
    text = " ".join(w["word"] for a, b in pieces for w in words if a / 1e6 - 1e-6 <= w["start"] and w["end"] <= b / 1e6 + 1e-6)
    ix = common.index(d["materials"])
    segs = [{"track": d["tracks"][ti].get("name") or f"{d['tracks'][ti]['type']}#{ti}", "segment_id": n["id"],
             "timeline_us": [n["target_timerange"]["start"], seg_end(n)],
             "file": ix[n["material_id"]][1].get("path", "") if n["material_id"] in ix else "",
             "source_us": [n["source_timerange"]["start"], n["source_timerange"]["start"] + n["source_timerange"]["duration"]]
             if n.get("source_timerange") else None} for ti, n in new]
    for s in segs:
        print(f"  hook {s['track']}: {s['timeline_us'][0] / 1e6:.3f}–{s['timeline_us'][1] / 1e6:.3f} <- "
              f"{Path(s['file']).name} {s['source_us'][0] / 1e6 if s['source_us'] else '-'}")
    print(f"hook {L / 1e6:.3f} s: {text}")
    if L / 1e6 > HOOK_MAX:
        print(f"  note: hook {L / 1e6:.1f} s > {HOOK_MAX:.0f} s (STAGE_4: ≤ 30 s to the promise and the result)")
    rows = common.read_layout(cfg)
    new_rows = shift_layout(rows, pieces, L) if rows else []
    end0 = d["duration"] / 1e6 - END_S
    if new_rows and common.layout_of(new_rows, end0, d["duration"] / 1e6) != {"F"}:
        print(f"  note: the last {END_S:.0f} s are not all F (end screen needs camera on full screen, no overlays)")
    print(f"duration {dur0 / 1e6:.3f} -> {d['duration'] / 1e6:.3f}")
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)
    out = {"variant": variant, "pieces_us": [[a, b] for a, b in pieces], "hook_len_us": L, "shift_us": L, "text": text,
           "duration_before_us": dur0, "duration_after_us": d["duration"], "hook_segments": segs}
    if dry:
        print("dry run, not written")
        return out
    out["backup"] = str(common.write_draft(cfg, d, "stage4-hook", dry=False, guard_seconds=guard_seconds))
    meta = common.read_meta(cfg)
    meta["tm_duration"] = d["duration"]
    common.write_meta(cfg, meta, dry=False)
    logp.parent.mkdir(parents=True, exist_ok=True)
    logp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if rows:
        common.write_layout(cfg, new_rows, stage4_hook={"shift_us": L, "log": str(logp)})
    print("written:", logp)
    if maps:
        import build_maps
        print("regenerating maps (build_maps) ...")
        out["maps"] = build_maps.run(cfg, expect_us=d["duration"], audio_check=audio_check)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 4: hook pieces copied to the start, everything shifted")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--hook", required=True, help='JSON: [[a, b]] | {"variant", "pieces": [...]}, timeline seconds')
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--force", action="store_true", help="apply although stage4/hook_applied.json exists")
    ap.add_argument("--no-maps", action="store_true", help="do not run build_maps afterwards")
    ap.add_argument("--no-audio-check", action="store_true", help="passed to build_maps")
    a = ap.parse_args(argv)
    variant, pieces = load(a.hook)
    out = run(common.load_config(a.config), pieces, a.dry, maps=not a.no_maps, audio_check=not a.no_audio_check,
              force=a.force, variant=variant)
    if out.get("maps", {}).get("errs"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
