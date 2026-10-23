"""Stage 2 analysis (references/stages/STAGE_2.md §1-5). All times: TRANSCRIPT time, seconds.

    python -X utf8 scripts/stage2/analyze.py --config config.json [--dry]

Input: transcript/transcript.json, transcript/voice_16k.wav (stage 0), stage1/cuts_applied.json,
stage1/chapters.json, the project (where the screencast is, to read its frames: 2 fps, 256x144 grey, cached in
stage2/frames/). Categories: pause, hesitation, filler, noise, speedup, pause_skip (info); conf auto | review | info;
verify=True -> checked by whisper in verify.py.
Output: stage2/candidates.json, stage2/stage2_review.md. --dry: print the summary, write nothing.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import subprocess
import sys
import wave
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

# ---------- parameters (STAGE_2.md) ----------
MARGIN = 0.080
KEEP = {"внутри фразы": 0.150, "предложение": 0.300, "глава": 0.600}
MIN_PAUSE_TOUCH = 0.300
HES_MIN = 0.250
SPEED_MIN_GAP = 3.0
SPEED_TARGET = 1.5
SPEED_MAX = 8.0
RMS_WIN = 0.010
REFINE_WIN = 0.150
SIL = -50.0             # dB: below = silence
BREATH_MAX = -30.0      # sound in a pause louder than this is not a breath
FILLERS = {"ну", "вот", "типа", "короче", "значит"}
FILLERS2 = {("как", "бы"), ("в", "общем")}
FW, FH, FPS2 = 256, 144, 2.0


def ends_sentence(w):
    return bool(re.search(r"[.!?…]$", w["word"]))


def norm(s):
    return re.sub(r"[^\w]", "", s.lower())


class Screen:
    """Screencast frames at transcript time t (via the stage-1 map and the current timeline)."""

    def __init__(self, cfg, cuts1, cache: Path, dry: bool):
        self.cuts1, self.cache, self.dry = cuts1, cache, dry
        self.pieces = common.flatten(cfg, common.read_draft(cfg), ("screencast",))
        self.frames: dict[str, np.ndarray | None] = {}
        m = np.ones((FH, FW), bool)
        m[92:, 167:] = False   # bottom right: camera circle / overlays
        m[140:, :] = False     # bottom strip: taskbar clock
        self.mask = m

    def t1(self, t):  # transcript s -> timeline us
        us = t * 1e6
        return us - sum(min(b, us) - a for a, b in self.cuts1 if a < us)

    def piece(self, t):
        if any(a <= t * 1e6 < b for a, b in self.cuts1):
            return None
        x = self.t1(t)
        return next((p for p in self.pieces if p["start"] <= x < p["start"] + p["dur"]), None)

    def is_screen(self, t):
        return self.piece(t) is not None

    def _file(self, path):
        if path not in self.frames:
            out = self.cache / (Path(path).name + ".gray")
            if not out.is_file() and not self.dry:
                out.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", f"fps={FPS2},scale={FW}:{FH},format=gray",
                                "-f", "rawvideo", str(out)], check=True)
            self.frames[path] = np.fromfile(out, dtype=np.uint8).reshape(-1, FH, FW) if out.is_file() else None
        return self.frames[path]

    def frame(self, t):
        p = self.piece(t)
        if p is None:
            return None
        fr = self._file(p["path"])
        if fr is None or not len(fr):
            return None
        src = (p["src"] + (self.t1(t) - p["start"]) * p["speed"]) / 1e6
        return fr[min(int(src * FPS2), len(fr) - 1)]

    def action(self, a, b, pix=0.02):
        """Share of 0.5 s steps in [a, b] where > pix of the pixels changed."""
        ts = np.arange(a, b, 1 / FPS2)
        fs = [self.frame(t) for t in ts]
        diffs = [float((np.abs(y.astype(np.int16) - x.astype(np.int16))[self.mask] > 24).mean())
                 for x, y in zip(fs, fs[1:]) if x is not None and y is not None]
        return float((np.array(diffs) > pix).mean()) if diffs else 0.0


def analyze(cfg, dry: bool = False) -> list[dict]:
    wd = cfg.work_dir
    T = json.loads((wd / "transcript" / "transcript.json").read_text(encoding="utf-8"))
    W = sorted([dict(w, seg=s["id"]) for s in T["segments"] for w in s["words"]], key=lambda w: w["start"])
    A = json.loads((wd / "stage1" / "cuts_applied.json").read_text(encoding="utf-8"))
    CUTS1 = sorted((c["start_us"] / 1e6, c["end_us"] / 1e6) for c in A["cuts"])
    chp = wd / "stage1" / "chapters.json"
    CHAPTERS = [c["start_transcript_s"] for c in json.loads(chp.read_text(encoding="utf-8"))] if chp.is_file() else [0]
    scr = Screen(cfg, [(a * 1e6, b * 1e6) for a, b in CUTS1], wd / "stage2" / "frames", dry)

    def in_cut1(t):
        return any(a <= t < b for a, b in CUTS1)

    def kept_parts(a, b):
        out, cur = [], a
        for x, y in CUTS1:
            if y <= cur or x >= b:
                continue
            if x > cur:
                out.append((cur, x))
            cur = max(cur, y)
        if cur < b:
            out.append((cur, b))
        return out

    def kept_len(a, b):
        return sum(y - x for x, y in kept_parts(a, b))

    KW = [w for w in W if not (in_cut1(w["start"]) or in_cut1(max(w["start"], w["end"] - 0.001)))]
    KW_START = [w["start"] for w in KW]
    print("words total", len(W), "kept", len(KW))

    wf = wave.open(str(wd / "transcript" / "voice_16k.wav"))
    sr = wf.getframerate()
    pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    hop = int(sr * RMS_WIN)
    n = len(pcm) // hop
    db = 20 * np.log10(np.sqrt(np.mean(pcm[: n * hop].reshape(n, hop) ** 2, axis=1)) + 1e-9)
    audio_dur = len(pcm) / sr

    def fi(t):
        return int(min(max(t, 0), audio_dur - RMS_WIN) / RMS_WIN)

    def max_db(a, b):
        i, j = fi(a), fi(b)
        return float(db[i: max(j, i + 1)].max())

    def quiet_runs(a, b, min_len=0.05):
        i0, i1 = fi(a), fi(b)
        q = db[i0:i1] < SIL
        runs, i = [], 0
        while i < len(q):
            if q[i]:
                j = i
                while j < len(q) and q[j]:
                    j += 1
                if (j - i) * RMS_WIN >= min_len:
                    runs.append(((i0 + i) * RMS_WIN, (i0 + j) * RMS_WIN))
                i = j
            else:
                i += 1
        return runs

    def chapter_in(a, b):
        return any(a - 1.0 <= c <= b + 1.0 for c in CHAPTERS[1:])

    def ctx(i, k=3):
        return " ".join(w["word"] for w in KW[max(0, i - k): i]) + " | " + " ".join(w["word"] for w in KW[i: i + k])

    cands = []

    def add(**k):
        if k["end"] - k["start"] < 0.034:
            return None
        k["id"] = len(cands) + 1
        k["start"], k["end"] = round(k["start"], 3), round(k["end"], 3)
        k["dur"] = round(k["end"] - k["start"], 3)
        cands.append(k)
        return k

    # ---------- 2. pauses + 5. speedups ----------
    used = np.zeros(n, bool)
    for i in range(len(KW) - 1):
        p, q = KW[i], KW[i + 1]
        a, b = p["end"], q["start"]
        if b - a <= 0:
            continue
        gap_kept = kept_len(a, b)
        if gap_kept < MIN_PAUSE_TOUCH:
            continue
        crossing = any(x < b and y > a for x, y in CUTS1)
        kind = "глава" if chapter_in(a, b) else ("предложение" if ends_sentence(p) else "внутри фразы")
        keep = KEEP[kind]
        is_scr = scr.is_screen(a) or scr.is_screen(b)
        act = scr.action(a, b) if is_scr else 0.0
        has_action = is_scr and act > 0.2
        text = ctx(i + 1)
        if is_scr and gap_kept >= SPEED_MIN_GAP and has_action and not crossing:
            s, e = a + MARGIN, b - MARGIN
            factor = min(max((e - s) / SPEED_TARGET, 2.0), SPEED_MAX)
            loud = max_db(s, e)
            add(cat="speedup", start=s, end=e, conf="auto", factor=round(factor, 2), text=text, verify=loud >= SIL,
                reason=f"на экране действие ({act:.0%} кадров), речи нет {gap_kept:.1f} с, пик {loud:.0f} dB")
            continue
        if has_action:
            add(cat="pause_skip", start=a, end=b, conf="info", text=text,
                reason=f"пауза {gap_kept:.2f} с не сокращена: на экране действие ({act:.0%})")
            continue
        qr = quiet_runs(a - REFINE_WIN, b + REFINE_WIN)
        if not qr:
            add(cat="pause_skip", start=a, end=b, conf="info", text=text,
                reason=f"пауза {gap_kept:.2f} с: нет тишины < {SIL:.0f} dB (сплошной звук)")
            continue
        core_s, core_e = qr[0][0], qr[-1][1]
        s = max(core_s + keep / 2, a + MARGIN)
        e = min(core_e - keep / 2, b - MARGIN)
        parts = [(x, y) for x, y in kept_parts(s, e) if y - x >= 0.034]
        if not parts:
            continue
        remaining = gap_kept - sum(y - x for x, y in parts)
        if remaining < keep - 0.02:
            continue
        for x, y in parts:
            loud = max_db(x, y)
            conf, why = "auto", f"пауза {gap_kept:.2f} с → {remaining:.2f} с ({kind})"
            if loud >= BREATH_MAX:
                conf, why = "review", why + f"; внутри звук {loud:.0f} dB (не вдох?)"
            elif loud >= SIL:
                why += f"; внутри вдох/шум {loud:.0f} dB"
            add(cat="pause", start=x, end=y, conf=conf, kind=kind, text=text, reason=why, verify=loud >= SIL,
                core=[round(core_s, 3), round(core_e, 3)])
            used[fi(x): fi(y)] = True

    # ---------- 3. hesitations / 4. noises: sound outside words ----------
    word_mask = np.zeros(n, bool)
    for w in W:
        word_mask[fi(w["start"]): fi(w["end"]) + 1] = True
    tol = int(0.04 / RMS_WIN)
    wm = word_mask.copy()
    for k in range(1, tol + 1):
        wm[k:] |= word_mask[:-k]
        wm[:-k] |= word_mask[k:]
    loud = (db >= SIL) & ~wm & ~used
    runs, i = [], 0
    while i < n:
        if loud[i]:
            j = i
            while j < n and loud[j]:
                j += 1
            if runs and i - runs[-1][1] <= int(0.08 / RMS_WIN):
                runs[-1][1] = j
            else:
                runs.append([i, j])
            i = j
        else:
            i += 1
    for i0, j0 in runs:
        a, b = i0 * RMS_WIN, j0 * RMS_WIN
        if kept_len(a, b) < 0.08:
            continue
        k = bisect.bisect_left(KW_START, a)
        prev_w = KW[k - 1] if k > 0 else None
        next_w = KW[k] if k < len(KW) else None
        s = max(a, prev_w["end"] + MARGIN) if prev_w else a
        e = min(b, next_w["start"] - MARGIN) if next_w else b
        if e - s < 0.08:
            continue
        peak, dur = max_db(a, b), b - a
        if dur >= HES_MIN and peak >= -45:
            add(cat="hesitation", start=s, end=e, conf="auto", text=ctx(k), verify=True,
                reason=f"звук {dur:.2f} с вне слов транскрипта, пик {peak:.0f} dB")
        elif peak >= -30 and dur < HES_MIN:
            add(cat="noise", start=s, end=e, conf="auto", text=ctx(k), verify=True,
                reason=f"короткий пик {dur * 1000:.0f} мс, {peak:.0f} dB вне слов")

    # ---------- 3b. filler words ----------
    for i, w in enumerate(KW):
        word, two = norm(w["word"]), None
        if i + 1 < len(KW) and (word, norm(KW[i + 1]["word"])) in FILLERS2:
            two = KW[i + 1]
        if word not in FILLERS and not two:
            continue
        if i > 0 and (norm(KW[i - 1]["word"]), word) in FILLERS2:
            continue
        prev_w = KW[i - 1] if i > 0 else None
        last = two or w
        next_w = KW[i + 2] if two else (KW[i + 1] if i + 1 < len(KW) else None)
        pause_before = (w["start"] - prev_w["end"]) if prev_w else 9
        phrase_start = (prev_w is None) or ends_sentence(prev_w) or pause_before >= MIN_PAUSE_TOUCH or \
            in_cut1(prev_w["end"] + 0.01)
        qb = quiet_runs(prev_w["end"] - 0.05 if prev_w else w["start"] - 0.5, w["start"] + 0.12, 0.03)
        qa = quiet_runs(last["end"] - 0.12, next_w["start"] + 0.05 if next_w else last["end"] + 0.5, 0.03)
        s = qb[-1][0] + 0.03 if qb else None
        e = qa[0][1] - 0.03 if qa else None
        if s is not None and prev_w and s < prev_w["end"] - 0.15:
            s = None
        if e is not None and next_w and e > next_w["start"] + 0.15:
            e = None
        if s is not None and e is not None:
            cover = (min(e, last["end"]) - max(s, w["start"])) / max(last["end"] - w["start"], 1e-3)
            if cover < 0.7:
                s = e = None
        txt = w["word"] + (" " + two["word"] if two else "")
        if s is None or e is None or e - s < 0.08:
            if phrase_start:
                add(cat="filler", start=max(w["start"] - MARGIN, prev_w["end"] + MARGIN) if prev_w else w["start"] - MARGIN,
                    end=min(last["end"] + MARGIN, next_w["start"] - MARGIN) if next_w else last["end"] + MARGIN,
                    conf="review", text=ctx(i), word=txt,
                    reason="в начале фразы, но нет чистой границы по звуку (слитно с соседним словом)")
            continue
        conf = "auto" if phrase_start and not ends_sentence(last) else "review"
        add(cat="filler", start=s, end=e, conf=conf, text=ctx(i), word=txt, verify=True,
            reason=("в начале фразы после паузы" if phrase_start else "внутри фразы") +
                   ("; заканчивает предложение" if ends_sentence(last) else ""))

    cands.sort(key=lambda c: c["start"])
    for k, c in enumerate(cands, 1):
        c["id"] = k
    return cands


def summary(cands) -> None:
    print(Counter((c["cat"], c["conf"]) for c in cands))
    for cat in ("pause", "hesitation", "filler", "noise", "speedup", "pause_skip"):
        for conf in ("auto", "review", "info"):
            cs = [c for c in cands if c["cat"] == cat and c["conf"] == conf]
            if cs:
                print(f"{cat:10} {conf:6} {len(cs):4} {sum(c['dur'] for c in cs):7.1f}s  "
                      f"verify={sum(1 for c in cs if c.get('verify'))}")


def write_review(work: Path, cands) -> Path:
    """stage2/stage2_review.md: the «под вопросом» items (STAGE_2 §6). **Стоп** — answer by numbers."""
    rows = [c for c in cands if c["conf"] == "review"]
    out = ["# Этап 2. Под вопросом", "", "| № | Время | Текст (±3 слова) | Категория | Причина |", "|---|---|---|---|---|"]
    out += [f"| {c['id']} | {c['start']:.2f}–{c['end']:.2f} | {c.get('text', '').replace('|', '/')} | {c['cat']} | "
            f"{c['reason']} |" for c in rows]
    out += ["", "**Стоп.** Ответ номерами: какие вырезать (→ stage2/approved_ids.json)."]
    p = work / "stage2" / "stage2_review.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 2: analysis")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    cands = analyze(cfg, a.dry)
    summary(cands)
    if a.dry:
        print("dry run, nothing written")
        return
    p = cfg.work_dir / "stage2" / "candidates.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cands, ensure_ascii=False, indent=1), encoding="utf-8")
    print(p, write_review(cfg.work_dir, cands))


if __name__ == "__main__":
    main()
