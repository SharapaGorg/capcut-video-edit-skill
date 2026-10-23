"""Stage 0: transcription (references/stages/STAGE_0.md).

    python -X utf8 scripts/stage0/transcribe.py --config config.json [--dry] [--audio FILE] [--out-prefix NAME]

Voice = the voice segments of the timeline (voice/ mic + screencast audio from cfg.sources; camera never),
mixed from the SOURCE files at their timeline positions -> transcript/voice_16k.wav (16 kHz mono). So transcript
time = timeline time before stage 1. --audio: transcribe that file instead (an extra piece).
faster-whisper large-v3-turbo, cpu, int8, ru, word_timestamps, vad_filter. Progress lines are flushed — run in
the background with output to a log. Outputs (transcript/): <prefix>.json (segments + words), <prefix>.txt
(`[мм:сс.с–мм:сс.с] текст`), <prefix>.srt; then the STAGE_0 checks (exit 1 on a failed check).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

SR = 16000
MODEL = "large-v3-turbo"
HALLU = re.compile(r"субтитр|продолжение следует|спасибо за просмотр", re.I)
SILENCE_DB = -50.0


def voice_segments(cfg, draft) -> list[dict]:
    """Voice pieces (mic + screencast audio, not muted) in timeline time."""
    return [x for x in common.flatten(cfg, draft, ("voice", "screencast")) if x["volume"] > 0]


def decode16k(path, tmp: Path) -> np.ndarray:
    raw = tmp / f"{abs(hash(str(path)))}.f32"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
                        "-f", "f32le", str(raw)], capture_output=True, text=True)
    if r.returncode != 0:  # e.g. a screencast without an audio stream
        return np.zeros(0, np.float32)
    return np.fromfile(raw, dtype=np.float32)


def build_voice_wav(segs: list[dict], out: Path) -> float:
    """Mix voice segments (speed 1 only) into a 16 kHz mono wav; returns duration s."""
    import soundfile as sf
    if any(abs(s["speed"] - 1.0) > 1e-6 for s in segs):
        raise SystemExit("sped voice segments on the timeline: transcribe before stage 2 (STAGE_0)")
    end = max(s["start"] + s["dur"] for s in segs)
    mix = np.zeros(int(end * SR / 1e6) + 1, np.float32)
    with tempfile.TemporaryDirectory() as tmp:
        cache: dict[str, np.ndarray] = {}
        for s in segs:
            if s["path"] not in cache:
                cache[s["path"]] = decode16k(s["path"], Path(tmp))
            a = cache[s["path"]]
            t0, s0, n = (int(round(x * SR / 1e6)) for x in (s["start"], s["src"], s["dur"]))
            chunk = a[s0:s0 + n][: len(mix) - t0]
            mix[t0:t0 + len(chunk)] += chunk
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), np.clip(mix, -1, 1), SR, subtype="PCM_16")
    return len(mix) / SR


def _ts(s: float, srt: bool = False) -> str:
    h, r = divmod(s, 3600)
    m, r = divmod(r, 60)
    if srt:
        return f"{int(h):02}:{int(m):02}:{int(r):02},{int(round((r - int(r)) * 1000)) % 1000:03}"
    return f"{int(h * 60 + m):02}:{r:04.1f}"


def transcribe(audio: Path, model_name: str = MODEL) -> dict:
    from faster_whisper import WhisperModel
    t0 = time.time()
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio), language="ru", word_timestamps=True, beam_size=5, vad_filter=True,
                                      vad_parameters=dict(min_silence_duration_ms=500), condition_on_previous_text=False)
    print(f"duration {info.duration:.1f} s", flush=True)
    segs = []
    for i, s in enumerate(segments, 1):
        words = [{"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3), "prob": round(w.probability, 3)}
                 for w in (s.words or [])]
        segs.append({"id": i, "start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip(), "words": words})
        if i % 25 == 0:
            el = time.time() - t0
            print(f"  {_ts(s.end)} / {_ts(info.duration)}  ({el:.0f} s elapsed)", flush=True)
            if el > 2 * s.end and s.end > 120:
                print("  slower than 2x audio: consider Google Colab (STAGE_0 step 3)", flush=True)
    return {"source": Path(audio).name, "model": model_name, "language": "ru", "duration": round(info.duration, 3),
            "segments": segs}


def write_outputs(T: dict, prefix: Path) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(json.dumps(T, ensure_ascii=False, indent=1), encoding="utf-8")
    srt = [f"{s['id']}\n{_ts(s['start'], True)} --> {_ts(s['end'], True)}\n{s['text']}\n" for s in T["segments"]]
    prefix.with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
    txt = [f"[{_ts(s['start'])}–{_ts(s['end'])}] {s['text']}" for s in T["segments"]]
    prefix.with_suffix(".txt").write_text("\n".join(txt) + "\n", encoding="utf-8")


def check(T: dict, audio: Path) -> list[str]:
    """STAGE_0 checks."""
    import soundfile as sf
    x, sr = sf.read(str(audio), dtype="float32")
    x = x if x.ndim == 1 else x.mean(1)
    dur = len(x) / sr
    words = [w for s in T["segments"] for w in s["words"]]
    errs = []
    if not words:
        return ["no words"]
    if dur - words[-1]["end"] > 5:
        errs.append(f"last word ends at {words[-1]['end']:.1f} s, audio {dur:.1f} s (> 5 s)")
    errs += [f"hallucination at {s['start']:.1f} s: {s['text']!r}" for s in T["segments"] if HALLU.search(s["text"])]
    errs += [f"repeated segment at {b['start']:.1f} s: {b['text']!r}" for a, b in zip(T["segments"], T["segments"][1:])
             if a["text"] and a["text"] == b["text"]]
    errs += [f"word > 2 s at {w['start']:.1f}: {w['word']!r}" for w in words if w["end"] - w["start"] > 2]
    hop = sr // 10
    n = len(x) // hop
    db = 20 * np.log10(np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    edges = [0.0] + [v for w in words for v in (w["start"], w["end"])] + [dur]
    for a, b in zip(edges[::2], edges[1::2]):
        if b - a > 10 and np.median(db[int(a * 10): int(b * 10)]) > SILENCE_DB:
            errs.append(f"{b - a:.0f} s without words at {a:.1f} s, but audio is not silent")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 0: transcription")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true", help="print the voice plan only")
    ap.add_argument("--audio", help="transcribe this file instead of the timeline voice")
    ap.add_argument("--out-prefix", default="transcript")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    tdir = cfg.work_dir / "transcript"
    if a.audio:
        audio = Path(a.audio)
        print(f"audio: {audio}")
    else:
        segs = voice_segments(cfg, common.read_draft(cfg))
        if not segs:
            raise SystemExit("no voice segments (voice/ or screencasts/ from cfg.sources) on the timeline")
        files = sorted({Path(s["path"]).name for s in segs})
        end = max(s["start"] + s["dur"] for s in segs) / 1e6
        print(f"voice: {len(segs)} segments from {len(files)} files {files}, timeline 0–{end:.1f} s")
        audio = tdir / "voice_16k.wav"
        if a.dry:
            print(f"dry run: would write {audio} and {a.out_prefix}.json/.txt/.srt")
            return
        print(f"{audio}: {build_voice_wav(segs, audio):.1f} s", flush=True)
    if a.dry:
        print("dry run: whisper not started")
        return
    T = transcribe(audio, a.model)
    write_outputs(T, tdir / a.out_prefix)
    errs = check(T, audio)
    n = sum(len(s["words"]) for s in T["segments"])
    print(f"done: {len(T['segments'])} segments, {n} words; checks: {'OK' if not errs else 'FAIL'}")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
