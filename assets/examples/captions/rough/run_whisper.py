import json, glob, os, sys
from faster_whisper import WhisperModel
m = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8", local_files_only=True)
out = {}
for f in sorted(glob.glob("voice/*.m4a")) + sorted(glob.glob("camera/*.MOV")):
    segs, info = m.transcribe(f, language="ru", word_timestamps=True, vad_filter=True, beam_size=5)
    words = [dict(word=w.word.strip(), start=round(w.start, 3), end=round(w.end, 3), p=round(w.probability, 2)) for s in segs for w in s.words]
    out[os.path.basename(f)] = words
    print(f, " ".join(f"{w['word']}[{w['start']:.2f}]" for w in words), flush=True)
    json.dump(out, open("auto/transcript/words.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("DONE")
