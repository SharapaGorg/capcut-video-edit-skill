"""Stages 7–8: SFX under the graphics — a click at each element's entry (split: entry and exit). Idempotent.

    python -X utf8 scripts/graphics/apply_sfx.py --config config.json [--only ID ...] [--sfx FILE] [--dry]

Events = graphics/comps.json "sfx" (gfx_build: the element's start; a split / camera number also its exit at
end − 0.4 s) — only for graphics that are on the timeline (graphics_applied.json segment present, or a segment
with their MOV); the rest -> warning, no SFX. File: the item's "sfx" (a name in cfg.sfx_dir), else --sfx, else the first audio file in cfg.sfx_dir.
Level (references/graphics.md, «Уровни звука»): peak momentary loudness of the SFX = voice − 12 LU (voice measured
on the timeline ±5 s around the event, effects.voice_lufs); chapter cards 3 dB quieter (voice − 15 LU). No voice
there -> the median voice level of the other events. cfg.sfx_dir unset -> stop and ask for it. An SFX already
starting within ±1 frame of the event (any SFX track) or recorded in graphics/sfx_applied.json -> skipped. Goes on
the first SFX track with room (SFX, SFX 2, …). Writes both drafts and graphics/sfx_applied.json.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import effects  # noqa: E402
import apply_graphics  # noqa: E402
import gfx_build  # noqa: E402
import render  # noqa: E402

CHAPTER_DB = -3.0          # chapter cards: 3 dB quieter than the zoom SFX
VOICE_WIN = 5.0


def on_timeline(cfg, d: dict) -> set:
    """Graphics ids really on the timeline: their graphics_applied.json segment exists, or a segment plays their MOV."""
    seg_ids = {s["id"] for t in d["tracks"] for s in t["segments"]}
    rec = apply_graphics.read_applied(cfg)["items"]
    out = {cid for cid, r in rec.items() if r.get("segment_id") in seg_ids}
    ix = common.index(d["materials"])
    paths = {common._norm(common.mat_path(ix, s)) for t in d["tracks"] for s in t["segments"]
             if s.get("material_id") in ix and ix[s["material_id"]][0] == "videos"}
    out |= {cid for cid, m in render.read_meta(cfg).items() if common._norm(m["file"]) in paths}
    return out


def applied_path(cfg) -> Path:
    return cfg.work_dir / "graphics" / "sfx_applied.json"


def run(cfg, only=None, sfx: str | None = None, dry: bool = False, guard_seconds: float = 5, log=print) -> dict:
    comps = gfx_build.read_comps(cfg)
    if not comps:
        raise SystemExit(f"нет {gfx_build.comps_path(cfg)}: сначала gfx_build.py")
    ids = list(only) if only else list(comps)
    unknown = [i for i in ids if i not in comps]
    if unknown:
        raise SystemExit(f"нет в comps.json: {unknown}")
    default = effects.sfx_files(cfg, [sfx] if sfx else None, n=1)[0]
    d = common.read_draft(cfg)
    placed = on_timeline(cfg, d)
    missing = [i for i in ids if i not in placed]
    if missing:
        log(f"  warning: not on the timeline (apply_graphics refused or not run) — no SFX for: {missing}")
    ids = [i for i in ids if i in placed]
    fps = cfg.fps
    ap = applied_path(cfg)
    rec = json.loads(ap.read_text(encoding="utf-8")) if ap.is_file() else {"events": {}}
    seg_ids = {s["id"] for t in d["tracks"] for s in t["segments"]}
    existing = [s["target_timerange"]["start"] for t in effects.sfx_tracks(d) for s in t["segments"]]
    events, skipped = [], []
    for cid in ids:
        c = comps[cid]
        f = effects.sfx_files(cfg, [c["sfx_file"]])[0] if c.get("sfx_file") else default
        for e in c["sfx"]:
            key = f"{cid}:{e['kind']}"
            t_us = common.snap(e["t"], fps)
            r = rec["events"].get(key)
            if (r and r.get("segment_id") in seg_ids) or any(abs(x - t_us) <= 1e6 / fps for x in existing):
                skipped.append(key)
                continue
            events.append({"id": cid, "key": key, "kind": e["kind"], "t_us": t_us, "file": f})
    out = {"added": [], "skipped": skipped, "not_applied": missing}
    if not events:
        log(f"nothing new: {len(skipped)} SFX already there")
        return out
    for e in events:
        a = max(0, e["t_us"] - common.us(VOICE_WIN))
        b = min(d["duration"], e["t_us"] + common.us(VOICE_WIN))
        e["voice"] = effects.voice_lufs(cfg, d, a, b)
    have = [e["voice"] for e in events if e["voice"] is not None]
    if not have:
        raise SystemExit("нет голоса рядом ни с одним элементом — уровень SFX (голос −12 LU) не посчитать")
    med = statistics.median(have)
    lens = {}
    for e in sorted(events, key=lambda e: e["t_us"]):
        vlu = e["voice"] if e["voice"] is not None else med
        off = effects.SFX_LU + (CHAPTER_DB if e["kind"] == "chapter" else 0.0)
        lv = effects.sfx_volume(vlu, e["file"], offset_lu=off)
        if lv["capped"]:
            log(f"  warning: SFX {e['file'].name} too quiet, volume capped at +20 dB")
        if e["file"] not in lens:
            lens[e["file"]] = effects.file_len_us(e["file"])
        sid, t = effects.place_sfx(d, e["file"], e["t_us"], lv["volume"], lens[e["file"]])
        r = {"id": e["id"], "kind": e["kind"], "start": e["t_us"] / 1e6, "file": e["file"].name, "volume": lv["volume"],
             "volume_db": lv["volume_db"], "voice_lufs": round(vlu, 2), "offset_lu": off,
             "voice_measured": e["voice"] is not None, "segment_id": sid, "track": t.get("name")}
        rec["events"][e["key"]] = r
        out["added"].append(r)
        log(f"  {e['key']}: {r['start']:.3f} {r['file']} {r['volume_db']:+.1f} dB (voice {r['voice_lufs']} LUFS, "
            f"{off:+.0f} LU) -> {r['track']}")
    errs = common.check_refs(d) + common.draft_overlaps(d)
    log(f"SFX added {len(out['added'])}, skipped {len(skipped)}")
    log("VALIDATION:", "OK" if not errs else "FAIL")
    if errs:
        raise SystemExit("SFX не вставлены:\n  - " + "\n  - ".join(errs))
    if dry:
        log("dry run, not written")
        return out
    out["backup"] = str(common.write_draft(cfg, d, "graphics-sfx", dry=False, guard_seconds=guard_seconds))
    ap.parent.mkdir(parents=True, exist_ok=True)
    ap.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    log("written:", ap)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="stages 7–8: SFX under the graphics entries")
    p.add_argument("--config", default="config.json")
    p.add_argument("--only", nargs="+")
    p.add_argument("--sfx", help="file name in cfg.sfx_dir (default: the first audio file there)")
    p.add_argument("--dry", action="store_true")
    a = p.parse_args(argv)
    run(common.load_config(a.config), a.only, a.sfx, a.dry)


if __name__ == "__main__":
    main()
