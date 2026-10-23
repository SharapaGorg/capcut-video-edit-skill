"""Stage 9 inputs: music tracks (beat grid, bar loop, loudness) and the voice level per chapter.

    python -X utf8 scripts/stage9/prepare.py --config config.json [--files a.mp3 b.mp3]

Tracks: audio files in cfg.music_dir (sorted by name, or --files names there); cfg.music_dir unset -> stop and ask.
Per track (cached by path/size/mtime in <work_dir>/stage9/work/loops.json): duration, tempo, loop [start, end) on bar
starts (beats.loop_region), integrated LUFS and the short-term (3 s) median / p90 inside the loop — the music level is
calibrated on the loop's short-term median (what plays under the voice).
Voice: the timeline voice (build_voice) short-term every 100 ms; speech windows = 3-s windows >= 70 % covered by words
of stage3/transcript_timeline.json; median per chapter (stage3/chapters_timeline.json; none -> one chapter).
Writes stage9/work/loops.json and stage9/work/voice_levels.json. Read-only for the project.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import effects  # noqa: E402
import beats  # noqa: E402
import build_voice  # noqa: E402

COVER = 0.7
WIN = 3.0


def work(cfg) -> Path:
    return cfg.work_dir / "stage9" / "work"


def music_files(cfg, names=None) -> list[Path]:
    if not cfg.music_dir:
        raise SystemExit("config.json → music_dir не задан: укажите папку с музыкой (только треки с правом использования "
                         "на YouTube — YouTube Audio Library и т.п.) — init_video.py --music DIR или поле music_dir")
    d = Path(cfg.music_dir)
    if not d.is_dir():
        raise SystemExit(f"music_dir не найден: {d}")
    files = [d / n for n in names] if names else sorted(p for p in d.iterdir() if p.suffix.lower() in effects.AUDIO_EXT)
    missing = [str(p) for p in files if not p.is_file()]
    if missing or not files:
        raise SystemExit(f"музыка не найдена в {d}: {missing or 'нет аудиофайлов'}")
    return files


def track_info(path: Path, log=lambda *a: None) -> dict:
    a = beats.analyze(path)
    r = beats.loop_region(a)
    if r is None:
        log(f"  warning: {path.name}: too short for a bar loop — looped as a whole")
        r = {"start": beats.EDGE, "end": a["dur"] - beats.EDGE, "bars": 0, "seam": beats.seam_quality(
            a, beats.EDGE, a["dur"] - beats.EDGE)}
    x = effects.pcm(path)
    T, S = effects.short_term(x)
    m = (T >= r["start"] + WIN) & (T <= r["end"]) & np.isfinite(S)
    if not m.any():
        m = np.isfinite(S)
    return {"file": path.as_posix(), "name": path.name, "dur": len(x) / effects.SR, "tempo": a["tempo"],
            "loop_start": r["start"], "loop_end": r["end"], "bars": r["bars"], "seam": r["seam"],
            "bar_starts": [a["beats"][i] for i in range(a["phase"], len(a["beats"]), 4)] if r["bars"] else [],
            "lufs": effects.loudness(x)["I"], "loop_S_median": float(np.median(S[m])),
            "loop_S_p90": float(np.percentile(S[m], 90))}


def tracks(cfg, files: list[Path], log=lambda *a: None) -> dict:
    """{file name: track_info}, cached in loops.json."""
    p = work(cfg) / "loops.json"
    cache = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    out = {}
    for f in files:
        st = f.stat()
        key = f"{f.as_posix()}|{st.st_size}|{int(st.st_mtime)}"
        if cache.get(f.name, {}).get("key") != key:
            log(f"  analysing {f.name}…")
            cache[f.name] = {**track_info(f, log), "key": key}
        out[f.name] = cache[f.name]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def chapters(cfg, dur: float) -> list[dict]:
    """stage3/chapters_timeline.json chapters ({n, title, start, end}); none -> one chapter over the whole video."""
    p = cfg.work_dir / "stage3" / "chapters_timeline.json"
    raw = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []
    ch = raw.get("chapters", []) if isinstance(raw, dict) else raw
    ch = [c for c in ch if c.get("start") is not None]
    if not ch:
        return [{"n": 1, "title": "", "start": 0.0, "end": dur}]
    ch = sorted(({**c} for c in ch), key=lambda c: c["start"])
    ch[0]["start"] = 0.0
    for a, b in zip(ch, ch[1:]):
        a["end"] = b["start"]
    ch[-1]["end"] = dur
    return ch


def speech_windows(T: np.ndarray, words: list[dict], dur: float) -> np.ndarray:
    """For each 3-s window ending at T: >= 70 % of it covered by words."""
    step = 0.01
    sp = np.zeros(int(dur / step) + 2, np.float32)
    for w in words:
        sp[int(w["start"] / step):int(np.ceil(w["end"] / step))] = 1
    c = np.concatenate([[0.0], np.cumsum(sp)])
    i1 = np.clip((T / step).astype(int), 0, len(sp))
    i0 = np.clip(((T - WIN) / step).astype(int), 0, len(sp))
    return (T >= WIN - 1e-6) & ((c[i1] - c[i0]) * step >= COVER * WIN)


def voice_levels(cfg, d: dict, words: list[dict], ch: list[dict], log=lambda *a: None) -> dict:
    x = build_voice.build(cfg, d, log)
    T, S = effects.short_term(x)
    ok = speech_windows(T, words, d["duration"] / 1e6) & np.isfinite(S)
    if not ok.any():
        raise SystemExit("нет окон речи (3 с, ≥ 70 % слов) — проверьте stage3/transcript_timeline.json")
    allv = float(np.median(S[ok]))
    out = {"all": allv, "chapters": []}
    for c in ch:
        m = ok & (T > c["start"]) & (T <= c["end"])
        out["chapters"].append({"n": c["n"], "start": c["start"], "end": c["end"],
                                "voice_S_median": float(np.median(S[m])) if m.any() else allv, "n_windows": int(m.sum())})
    return out


def run(cfg, d: dict, names=None, log=print) -> tuple[dict, dict, list[dict], list[dict]]:
    """-> (tracks, voice levels, chapters, words)."""
    files = music_files(cfg, names)
    words = common.timeline_words(cfg)
    if not words:
        raise SystemExit("нет stage3/transcript_timeline.json — сначала этап 3 (build_maps.py)")
    ch = chapters(cfg, d["duration"] / 1e6)
    tr = tracks(cfg, files, log)
    vl = voice_levels(cfg, d, words, ch, log)
    (work(cfg) / "voice_levels.json").write_text(json.dumps(vl, ensure_ascii=False, indent=1), encoding="utf-8")
    return tr, vl, ch, words


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 9: track loops + voice levels (read-only)")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--files", nargs="+", help="file names in music_dir (default: all, sorted)")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    tr, vl, ch, _ = run(cfg, common.read_draft(cfg), a.files)
    for k, t in tr.items():
        print(f"{k}: {t['dur']:.1f} s, tempo {t['tempo']:.0f}, loop {t['loop_start']:.2f}-{t['loop_end']:.2f} "
              f"({t['bars']} bars), I {t['lufs']} LUFS, loop S median {t['loop_S_median']:.1f}")
    print(f"voice: median {vl['all']:.1f} LUFS;", ", ".join(f"ch{c['n']} {c['voice_S_median']:.1f}" for c in vl["chapters"]))


if __name__ == "__main__":
    main()
