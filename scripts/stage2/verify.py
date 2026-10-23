"""Stage 2: whisper check of every candidate with verify=True — does the region to be removed hold real words?

    python -X utf8 scripts/stage2/verify.py --config config.json [--dry]

All clips (transcript/voice_16k.wav, transcript time) are concatenated with 1 s of silence between them and
transcribed in one pass. Words heard in an «auto» candidate -> conf «review». Updates stage2/candidates.json and
stage2/stage2_review.md. --dry: count the clips, no whisper, nothing written.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import wave
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
from analyze import write_review  # noqa: E402

HES = {"э", "эм", "м", "мм", "ммм", "а", "аа", "эээ", "ээ", "хм", "угу", "ага", "ах", "ох", "ух", "эх", "мгм", "хмм"}
FILL = {"ну", "вот", "типа", "короче", "значит", "как", "бы", "в", "общем"}
HALLU = re.compile(r"субтитр|продолжение следует|спасибо за просмотр|редактор", re.I)
MODEL = "large-v3-turbo"


def toks(s):
    return re.sub(r"[^\w\s]", "", s.lower()).split()


def verdict(c, text) -> str:
    t = [] if HALLU.search(text) else toks(text)
    if not t:
        return "silent"
    if all(x in HES for x in t):
        return "hesitation"
    if c["cat"] == "filler" and all(x in HES or x in FILL for x in t):
        return "filler"
    if c["cat"] in ("pause", "noise") and all(x in HES or x in FILL for x in t) and len(t) <= 2:
        return "hesitation"
    return "words"


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 2: whisper check of candidates")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--model", default=MODEL)
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    cp = cfg.work_dir / "stage2" / "candidates.json"
    C = json.loads(cp.read_text(encoding="utf-8"))
    todo = [c for c in C if c.get("verify")]
    wf = wave.open(str(cfg.work_dir / "transcript" / "voice_16k.wav"))
    sr = wf.getframerate()
    print(f"{len(todo)} clips to check, {sum(c['dur'] for c in todo):.0f} s of audio")
    if a.dry:
        print("dry run: whisper not started, nothing written")
        return
    pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    gap = np.zeros(sr, np.float32)
    parts, pos, t = [], [], 0.0
    for c in todo:
        clip = pcm[int(max(0, c["start"] - 0.02) * sr): int((c["end"] + 0.02) * sr)]
        parts += [gap, clip]
        t += 1.0
        pos.append((t, t + len(clip) / sr))
        t += len(clip) / sr
    parts.append(gap)
    audio = np.concatenate(parts) if todo else np.zeros(0, np.float32)
    from faster_whisper import WhisperModel
    t0 = time.time()
    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs, _ = model.transcribe(audio, language="ru", beam_size=1, vad_filter=False, condition_on_previous_text=False,
                               word_timestamps=True)
    words = [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or [])]
    print(f"transcribed {len(words)} words in {time.time() - t0:.0f} s", flush=True)
    for c, (x, y) in zip(todo, pos):
        hits = [w for ws, we, w in words if ws < y + 0.3 and we > x - 0.3 and min(we, y) - max(ws, x) > 0.3 * (we - ws)]
        text = " ".join(hits)
        c["whisper"], c["verdict"] = text, verdict(c, text)
        if c["verdict"] == "words" and c["conf"] == "auto":
            c["conf"] = "review"
            c["reason"] += f"; whisper слышит слова: «{text}»"
    cp.write_text(json.dumps(C, ensure_ascii=False, indent=1), encoding="utf-8")
    write_review(cfg.work_dir, C)
    print(Counter((c["cat"], c.get("verdict")) for c in todo))
    print(Counter((c["cat"], c["conf"]) for c in C))


if __name__ == "__main__":
    main()
