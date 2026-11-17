"""Word starts snapped to where the voice gets loud (whisper is often ~0.1 s off). Usage: prep.py voice.wav words.json words_on.json"""
import json, subprocess, sys
import numpy as np
voice, src, out = sys.argv[1:4]
pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", voice, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
a = np.frombuffer(pcm, np.float32)
db = 20 * np.log10(np.array([np.sqrt(np.mean(a[i:i + 320] ** 2) + 1e-12) for i in range(0, len(a) - 320, 160)]))
def onset(t):
    i0, i1 = max(0, int((t - 0.08) * 100)), min(len(db) - 1, int((t + 0.09) * 100))
    floor = db[max(0, i0 - 5):i0 + 3].min()
    for i in range(i0, i1):
        if db[i] > max(-38, floor + 10): return round(i / 100, 3)
    return t
words = json.load(open(src, encoding="utf8")); prev = 0
for w in words:
    w["on"] = max(prev, min(max(onset(w["start"]), w["start"] - 0.08), w["start"] + 0.08)); prev = w["on"]
json.dump(words, open(out, "w", encoding="utf8"), ensure_ascii=False, indent=0)
print(" ".join(f'{i}:{w["word"]}[{w["start"]}>{w["on"]}]' for i, w in enumerate(words)))
