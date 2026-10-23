"""Stage 5, step 1: frames once a second from the USED ranges of the screencasts (references/stages/STAGE_5.md).

    python -X utf8 scripts/stage5/extract_frames.py --config config.json [--only SUBSTR] [--dry]

Used ranges = the screencast pieces on the timeline (common.flatten, compounds expanded). Frames:
<work_dir>/stage5/frames/<file stem>/<sec>.jpg (source resolution, q 2) + _used.json; seconds outside the used
ranges are deleted after decoding. Also <work_dir>/stage5/segment_starts.json: the first frame of every screencast
piece (step 3: look at them for messenger notifications, private tabs, bookmarks, avatars).
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402


def used_ranges(cfg, draft: dict) -> dict[str, list[tuple[float, float]]]:
    """{screencast path: [(src_a, src_b)] seconds} of what the timeline shows."""
    out: dict[str, list] = {}
    for p in common.flatten(cfg, draft, ("screencast",)):
        if p["src"] is not None:
            out.setdefault(p["path"], []).append((p["src"] / 1e6, p["src_end"] / 1e6))
    return {k: sorted(v) for k, v in out.items()}


def seconds(ranges) -> list[int]:
    return sorted({s for a, b in ranges for s in range(math.floor(a), math.ceil(b) + 1)})


def run(cfg, only: str | None = None, dry: bool = False) -> dict:
    d = common.read_draft(cfg)
    files = used_ranges(cfg, d)
    root = cfg.work_dir / "stage5"
    starts = [{"file": Path(p["path"]).name, "timeline": round(p["start"] / 1e6, 3), "src": round(p["src"] / 1e6, 3),
               "frame": f"frames/{Path(p['path']).stem}/{int(p['src'] // 1e6)}.jpg"}
              for p in common.flatten(cfg, d, ("screencast",)) if p["src"] is not None]
    res = {}
    for f, rngs in files.items():
        if only and only not in f:
            continue
        stem = Path(f).stem
        secs = seconds(rngs)
        res[f] = len(secs)
        print(f"{stem}: {len(rngs)} ranges, {len(secs)} seconds, {secs[0]}–{secs[-1]}", flush=True)
        if dry:
            continue
        if not Path(f).is_file():
            raise SystemExit(f"нет исходника {f}")
        out = root / "frames" / stem
        out.mkdir(parents=True, exist_ok=True)
        (out / "_used.json").write_text(json.dumps({"file": f, "ranges": rngs, "seconds": secs}), encoding="utf-8")
        lo, hi = secs[0], secs[-1]
        logs = root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / f"extract_{stem}.log", "w", encoding="utf-8") as log:
            subprocess.run(["ffmpeg", "-hide_banner", "-y", "-loglevel", "warning", "-ss", str(lo), "-to", str(hi + 1),
                            "-i", f, "-vf", "fps=1", "-q:v", "2", "-start_number", str(lo), str(out / "%d.jpg")],
                           stdout=log, stderr=log)
        keep = set(secs)
        removed = 0
        for p in out.glob("*.jpg"):
            if p.stem.isdigit() and int(p.stem) not in keep:
                p.unlink()
                removed += 1
        print(f"  kept {len(list(out.glob('*.jpg')))}, removed {removed}", flush=True)
    if not dry:
        root.mkdir(parents=True, exist_ok=True)
        (root / "segment_starts.json").write_text(json.dumps(starts, ensure_ascii=False, indent=0), encoding="utf-8")
    else:
        print("dry run, nothing extracted")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 5: frames 1/s of the used screencast ranges")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--only", help="only files whose path contains this")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.only, a.dry)


if __name__ == "__main__":
    main()
