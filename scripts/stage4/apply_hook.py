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
Refused (nothing written): hook > 30 s; first word later than 0.5 s from the start; no transcript_timeline;
after the insert the last 20 s not full-screen camera or with overlays (STAGE_4 ending: end screen).
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
FIRST_WORD_MAX = 0.5


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
    errs = common.check_refs(d) + common.draft_overlaps(d)
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


def first_word_s(words: list[dict], pieces: list[tuple[int, int]]) -> float | None:
    """Hook time (s) of the first word inside the hook pieces; None if the hook has no speech."""
    off = 0
    for a, b in pieces:
        ws = [w for w in words if a / 1e6 - 1e-6 <= w["start"] and w["end"] <= b / 1e6 + 1e-6]
        if ws:
            return round((off + common.us(ws[0]["start"]) - a) / 1e6, 3)
        off += b - a
    return None


def ending_errors(cfg, d: dict) -> list[str]:
    """STAGE_4 ending: the last END_S seconds = camera on full screen, no overlays (circle, graphics, texts,
    stickers, effects — leaves without a source role, except audio and Adjustment)."""
    b = d["duration"]
    a = max(0, b - common.us(END_S))
    tol = int(1e6 / cfg.fps)
    errs = [f"ending: no full-screen camera at {x / 1e6:.3f}–{y / 1e6:.3f}"
            for x, y in common.subtract_ranges(a, b, common.full_camera_ranges(cfg, d)) if y - x > tol]
    over = sorted({(p["name"] or p["kind"] or "?") for p in common.flatten(cfg, d, None)
                   if p["start"] < b - tol and p["end"] > a + tol
                   and ((p["role"] is None and p["kind"] not in ("audios", "placeholders"))
                        or (p["role"] == "camera" and p["mask"]))})
    if over:
        errs.append(f"ending: overlays in the last {END_S:.0f} s: {', '.join(over)[:200]}")
    return errs


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
    if not words:
        errs.append("нет stage3/transcript_timeline.json: границы и первое слово не проверить (этап 3)")
    L = sum(b - a for a, b in pieces)
    if L / 1e6 > HOOK_MAX:
        errs.append(f"hook {L / 1e6:.2f} s > {HOOK_MAX:.0f} s")
    fw = first_word_s(words, pieces)
    if words and (fw is None or fw > FIRST_WORD_MAX):
        errs.append(f"first word of the hook at {fw} s (needs ≤ {FIRST_WORD_MAX} s from the start)")
    if errs:
        raise SystemExit("хук не применён:\n  - " + "\n  - ".join(errs))
    new, L = build(cfg, d, pieces)
    errs = validate(cfg, d, orig, new, L) + ending_errors(cfg, d)
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
    print(f"hook {L / 1e6:.3f} s, first word at {fw} s: {text}")
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
    common.update_layout(cfg, lambda o: dict(common.layout_insert(o, pieces, L),
                                             stage4_hook={"shift_us": L, "log": str(logp)}))
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
