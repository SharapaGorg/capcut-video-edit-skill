"""Word timestamps of the render's own audio (faster-whisper). Usage: words.py voice.wav words.json [lang]"""
import json, sys
from faster_whisper import WhisperModel
src, out = sys.argv[1:3]
lang = sys.argv[3] if len(sys.argv) > 3 else "ru"
m = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", local_files_only=True)
segs, _ = m.transcribe(src, language=lang, word_timestamps=True, vad_filter=False, beam_size=5)
words = [dict(word=w.word.strip(), start=round(w.start, 3), end=round(w.end, 3)) for s in segs for w in s.words]
json.dump(words, open(out, "w", encoding="utf8"), ensure_ascii=False, indent=0)
print(" ".join(f'{i}:{w["word"]}[{w["start"]}]' for i, w in enumerate(words)))
