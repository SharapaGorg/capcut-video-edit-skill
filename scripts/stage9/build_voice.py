"""The voice of the whole timeline as one mono track (to measure it and check the mix).

    python -X utf8 scripts/stage9/build_voice.py --config config.json

Voice = mic (cfg.sources.voice) + screencast audio, each piece x its volume (compound chain included), sped pieces
muted (effects.voice_pcm). Cached in <work_dir>/stage9/work/voice_timeline.f32 (48 kHz float32) with a key of the
pieces it was built from; a changed timeline rebuilds it. Prints integrated LUFS. Read-only for the project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
import effects  # noqa: E402

SR = effects.SR


def _key(cfg, d: dict) -> str:
    rows = [(p["path"], p["start"], p["end"], p["src"], round(p["volume"], 6), round(p["speed"], 6))
            for p in common.flatten(cfg, d, ("voice", "screencast"))]
    return hashlib.md5(json.dumps([d["duration"], rows]).encode("utf-8")).hexdigest()


def cache_paths(cfg) -> tuple[Path, Path]:
    w = cfg.work_dir / "stage9" / "work"
    return w / "voice_timeline.f32", w / "voice_timeline.json"


def build(cfg, d: dict, log=lambda *a: None) -> np.ndarray:
    """Timeline voice samples (SR), length = draft duration."""
    f, meta = cache_paths(cfg)
    key = _key(cfg, d)
    if f.is_file() and meta.is_file() and json.loads(meta.read_text(encoding="utf-8")).get("key") == key:
        return np.fromfile(f, dtype=np.float32)
    log("building the timeline voice (one ffmpeg call per voice piece)…")
    x, got = effects.voice_pcm(cfg, d, 0, d["duration"])
    if not got:
        raise SystemExit("на таймлайне нет голоса (микрофон / звук скринкаста с volume > 0) — уровень музыки не посчитать")
    f.parent.mkdir(parents=True, exist_ok=True)
    x.astype(np.float32).tofile(f)
    meta.write_text(json.dumps({"key": key, "sr": SR, "duration_us": d["duration"]}), encoding="utf-8")
    return x


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 9: timeline voice -> stage9/work/voice_timeline.f32")
    ap.add_argument("--config", default="config.json")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    x = build(cfg, common.read_draft(cfg), log=print)
    print(f"voice: {len(x) / SR:.1f} s, integrated {effects.loudness(x)['I']} LUFS -> {cache_paths(cfg)[0]}")


if __name__ == "__main__":
    main()
