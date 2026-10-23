"""Stage3 words -> the exported master (config.json -> master_render): was the word kept there? Matched by TIME IN THE
SOURCE FILE (file, file_start), not by text: recognition in the master may spell it differently («Анти-топ» /
«Анти -топ»).

The master's maps: config.json -> master_maps (folder with timeline_map.json + transcript_timeline.json of the timeline
master_render was exported from); default <work_dir>/stage3 (one project: stage3 is regenerated after every structure
edit, so it IS the master). A separate folder only when the master was finished in a copy of the project.
"""
from __future__ import annotations

import bisect
import json
from pathlib import Path


def master_dir(cfg) -> Path:
    return Path(cfg.master_maps) if getattr(cfg, "master_maps", None) else cfg.work_dir / "stage3"


def load_json(path: Path, what: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"нет {path} ({what}): сначала scripts/stage3/build_maps.py (после любой правки структуры — заново)")
    return json.loads(path.read_text(encoding="utf-8"))


class Master:
    """Words of the master transcript indexed by source file; CW = all of them (extend_src takes words from here)."""

    def __init__(self, cfg):
        d = master_dir(cfg)
        tt = load_json(d / "transcript_timeline.json", "транскрипт мастера")
        self.CW = [w for s in tt["segments"] for w in s["words"]]
        self.idx: dict[str, list[dict]] = {}
        for w in self.CW:
            if w.get("file") is not None and w.get("file_start") is not None:
                self.idx.setdefault(w["file"], []).append(w)
        for v in self.idx.values():
            v.sort(key=lambda w: w["file_start"])
        self.keys = {f: [w["file_start"] for w in v] for f, v in self.idx.items()}

    def find(self, w3: dict, tol: float = 0.03) -> dict | None:
        """The master word at the same place of the same source file, else None (cut in the master)."""
        lst = self.idx.get(w3.get("file"), [])
        if not lst or w3.get("file_start") is None:
            return None
        ks = self.keys[w3["file"]]
        i = bisect.bisect_left(ks, w3["file_start"] - tol)
        if i < len(lst) and lst[i]["file_start"] <= w3["file_start"] + tol:
            return lst[i]
        # merged / split differently: falls inside a master word
        j = bisect.bisect_right(ks, w3["file_start"]) - 1
        if j >= 0:
            w = lst[j]
            if w["file_start"] <= w3["file_start"] < w["file_start"] + (w["end"] - w["start"]) / w.get("speed", 1.0):
                return w
        return None
