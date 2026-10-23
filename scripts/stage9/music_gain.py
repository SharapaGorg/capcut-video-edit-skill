"""Raise / lower ALL music (tracks «Музыка», «Музыка 2», …) by N dB, e.g. after listening on laptop speakers.

    python -X utf8 scripts/stage9/music_gain.py --config config.json 3 [--dry]      (negative N = quieter)

Keeps the relative levels (under speech / pauses / ending) and the fades. CapCut volume is capped at +20 dB (10.0).
Updates <work_dir>/stage9/music.json (volume, gain_db, gain_offset_db) when present. Writes both drafts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import apply_music  # noqa: E402


def run(cfg, db: float, dry: bool = False, guard_seconds: float = 5, log=print) -> int:
    k = 10 ** (db / 20)
    d = common.read_draft(cfg)
    segs = [s for t in d["tracks"] if apply_music.is_music_track(t) for s in t["segments"]]
    if not segs:
        raise SystemExit("нет дорожек «Музыка» — сначала apply_music.py")
    capped = 0
    for s in segs:
        v = s["volume"] * k
        capped += v > apply_music.MAX_VOLUME
        s["volume"] = round(min(v, apply_music.MAX_VOLUME), 6)
        s["last_nonzero_volume"] = s["volume"]
    log(f"{len(segs)} music segments {db:+.1f} dB (x{k:.3f})" + (f", {capped} capped at +20 dB" if capped else ""))
    if dry:
        log("dry run, not written")
        return len(segs)
    common.write_draft(cfg, d, "stage9-music-gain", dry=False, guard_seconds=guard_seconds)
    mp = cfg.work_dir / "stage9" / "music.json"
    if mp.is_file():
        M = json.loads(mp.read_text(encoding="utf-8"))
        vol = {s["id"]: s["volume"] for s in segs}
        for p in M.get("pieces", []):
            if p.get("segment_id") in vol:
                p["volume"] = vol[p["segment_id"]]
                p["gain_db"] = round(p["gain_db"] + db, 2)
        M["gain_offset_db"] = round(M.get("gain_offset_db", 0.0) + db, 2)
        mp.write_text(json.dumps(M, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(segs)


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 9: all music +N dB")
    ap.add_argument("db", type=float)
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.db, a.dry)


if __name__ == "__main__":
    main()
