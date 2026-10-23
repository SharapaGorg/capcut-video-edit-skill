"""Stage 3 structural fix (STAGE_3.md §7): ripple cut on the top-level timeline — every [a, b) is removed from ALL
tracks, everything after it shifts left; a segment crossing a cut is split (cloned material + extra refs, as CapCut
split does; a compound piece gets its own copy of the nested draft).

    python -X utf8 scripts/stage3/ripple_cut.py --config config.json --cuts cuts.json [--dry] [--no-audio-check]

cuts.json: [{"start": s, "end": s}, ...] or [[a, b], ...] — timeline seconds, snapped to the frame grid inwards.
Speed != 1 pieces: source = target x speed (capcut-format.md). Keyframes on a split segment -> warning (check by eye).
Writes both drafts via common.write_draft (CapCut killed, backup), draft_meta_info tm_duration. Audio compounds
(also nested ones) under a trimmed/split segment: pre-render Resources/combination/<combination_id>_audio.aac
deleted and audio_path in subdraft/<id>/sub_draft_config.json cleared, else CapCut plays stale audio.
Log: <work_dir>/stage3/ripple_cuts.json (appended). Then build_maps runs (maps regenerated, --expect = new duration).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
from common import by_start, seg_end  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_maps  # noqa: E402

PLACEHOLDER_RE = re.compile(r"^##_draftpath_placeholder_[^#]*_##")


def load_cuts(path, fps: int) -> list[tuple[int, int]]:
    out = []
    for c in json.loads(Path(path).read_text(encoding="utf-8")):
        a, b = (c["start"], c["end"]) if isinstance(c, dict) else c
        fa, fb = math.ceil(a * fps - 1e-6), math.floor(b * fps + 1e-6)   # inwards
        x, y = fa * 1_000_000 // fps, fb * 1_000_000 // fps   # frame k starts at trunc(k / fps us), as in CapCut
        if y > x:
            out.append((x, y))
    out.sort()
    for (a1, b1), (a2, b2) in zip(out, out[1:]):
        if b1 > a2:
            raise SystemExit(f"cuts overlap: {a1 / 1e6:.3f}-{b1 / 1e6:.3f} and {a2 / 1e6:.3f}-{b2 / 1e6:.3f}")
    return out


def prerenders(cfg, draft: dict, seg_ids: set) -> list[tuple[Path, str]]:
    """(sub_draft_config path, audio_path) of every pre-rendered compound under the given top-level segments, nested
    ones too. The config is found by the drafts material's draft_config_path (CapCut gives every cut piece a new
    nested draft id, but all pieces keep pointing at the original subdraft/<id>/), else subdraft/<nested id>/."""
    dix = {m["id"]: m for m in draft["materials"].get("drafts", []) or [] if isinstance(m, dict) and "id" in m}
    cfgs: list[Path] = []

    def walk(segs, dix):
        for s in segs:
            for e in s.get("extra_material_refs") or []:
                dm = dix.get(e) or {}
                nd = dm.get("draft")
                if not isinstance(nd, dict):
                    continue
                cp = dm.get("draft_config_path")
                p = Path(project_path(cfg, cp)) if cp else \
                    cfg.project_dir / "subdraft" / str(nd.get("id")) / "sub_draft_config.json"
                if p not in cfgs:
                    cfgs.append(p)
                inner = {**dix, **{m["id"]: m for m in nd.get("materials", {}).get("drafts", []) or []}}
                walk([x for t in nd.get("tracks", []) for x in t.get("segments", [])], inner)

    walk([s for t in draft["tracks"] for s in t["segments"] if s["id"] in seg_ids], dix)
    out = []
    for p in cfgs:
        if p.is_file():
            ap = json.loads(p.read_text(encoding="utf-8")).get("audio_path") or ""
            if ap:
                out.append((p, ap))
    return out


def project_path(cfg, p: str) -> str:
    """CapCut path with the draft placeholder -> real path, forward slashes."""
    return PLACEHOLDER_RE.sub(lambda _m: cfg.project_dir.as_posix(), p.replace("\\", "/"))


def clear_prerender(cfg, sub: Path, audio_path: str) -> None:
    aac = Path(project_path(cfg, audio_path))
    if not aac.is_absolute():  # CapCut writes it relative to subdraft/<id>/ (../../Resources/combination/…)
        aac = sub.parent / aac
    if aac.is_file():
        aac.unlink()
    c = json.loads(sub.read_text(encoding="utf-8"))
    c["audio_path"] = ""
    sub.write_text(json.dumps(c, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def run(cfg, cuts: list[tuple[int, int]], dry: bool, guard_seconds: float = 5, audio_check: bool = True) -> dict:
    d = common.read_draft(cfg)
    old = d["duration"]
    cuts = [(a, min(b, old)) for a, b in cuts if a < old]
    if not cuts:
        raise SystemExit("no cuts inside the timeline")
    gaps0 = [common.gap_count(t) for t in d["tracks"]]
    rec = common.ripple(d, cuts)
    total = sum(b - a for a, b in cuts)
    print("cuts:", ", ".join(f"{a / 1e6:.3f}–{b / 1e6:.3f}" for a, b in cuts), f"(total {total / 1e6:.3f} s)")
    touched = {r["segment_id"] for r in rec if not r["removed"] and r["cut"]}
    errs = common.check_refs(d)
    for ti, t in enumerate(d["tracks"]):
        segs = by_start(t["segments"])
        name = t.get("name") or f"{t['type']}#{ti}"
        removed = sum(1 for r in rec if r["track"] == ti and r["removed"])
        print(f"  {name}: removed {removed}, trimmed/split pieces {sum(1 for s in segs if s['id'] in touched)}, "
              f"now {len(segs)}")
        errs += common.overlap_errors(t, name)
        if common.gap_count(t) > gaps0[ti]:
            errs.append(f"{name}: new holes ({gaps0[ti]} -> {common.gap_count(t)})")
        for s in segs:
            if s["id"] not in touched:
                continue
            if s.get("common_keyframes"):
                print(f"  WARNING: keyframes on a split segment {name} @ {s['target_timerange']['start'] / 1e6:.3f}")
            sr, sp = s.get("source_timerange"), float(s.get("speed", 1.0))
            if sr and abs(sr["duration"] - s["target_timerange"]["duration"] * sp) > 1:
                errs.append(f"{name} @ {s['target_timerange']['start'] / 1e6:.3f}: source != target x speed")
    end = max((seg_end(s) for t in d["tracks"] for s in t["segments"]), default=0)
    if end > d["duration"] + 1:
        errs.append(f"segments end at {end / 1e6:.3f} after duration {d['duration'] / 1e6:.3f}")
    stale = prerenders(cfg, d, touched)
    print(f"duration {old / 1e6:.3f} -> {d['duration'] / 1e6:.3f}; audio pre-renders to clear: {len(stale)}")
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)
    out = {"cuts": [[round(a / 1e6, 6), round(b / 1e6, 6)] for a, b in cuts], "before_us": old, "after_us": d["duration"],
           "segments": rec}
    if dry:
        for sub, ap in stale:
            print(f"  would clear {ap} ({sub.parent.name})")
        print("dry run, not written")
        return out
    bk = common.write_draft(cfg, d, "stage3-ripple", dry=False, guard_seconds=guard_seconds)
    meta = common.read_meta(cfg)
    if "tm_duration" in meta:
        meta["tm_duration"] = d["duration"]
        common.write_meta(cfg, meta, dry=False)
    for sub, ap in stale:
        clear_prerender(cfg, sub, ap)
        print(f"  cleared pre-render {ap}")
    log = cfg.work_dir / "stage3" / "ripple_cuts.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    prev = json.loads(log.read_text(encoding="utf-8")) if log.is_file() else []
    prev.append({"stamp": time.strftime("%Y%m%d-%H%M%S"), "cuts": out["cuts"], "before": old / 1e6,
                 "after": d["duration"] / 1e6, "backup": str(bk)})
    log.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    if common.update_layout(cfg, lambda o: common.layout_cut(o, cuts)):
        print("layout/layout.json mapped through the cuts")
    print("written, backup", bk)
    print("regenerating maps (build_maps) ...")
    out["maps"] = build_maps.run(cfg, expect_us=d["duration"], audio_check=audio_check)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 3: ripple cut on all tracks + maps regenerated")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--cuts", required=True, help='JSON: [{"start": s, "end": s}] or [[a, b]], timeline seconds')
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-audio-check", action="store_true", help="passed to build_maps")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    out = run(cfg, load_cuts(a.cuts, cfg.fps), a.dry, audio_check=not a.no_audio_check)
    if out.get("maps", {}).get("errs"):
        raise SystemExit(1)
    return out


if __name__ == "__main__":
    main()
