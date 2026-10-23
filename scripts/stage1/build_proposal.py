"""Stage 1 proposal (references/stages/STAGE_1.md §2-4).

    python -X utf8 scripts/stage1/build_proposal.py --config config.json [--dry]

Input (written by the agent after reading transcript/transcript.txt), in <work_dir>/stage1/:
  candidates_input.json  [{"hint_s": 45, "first": "first words of the cut", "last": "last words",
                           "cat": "Дубль|Фальстарт|Служебное|Повтор|Отступление|Затянуто", "why": "...",
                           "conf": "точно|под вопросом"}]
  chapters_input.json    [{"n": 1, "title": "...", "start_transcript_s": 0}]  (= stage1/chapters.json format)
Words are located in transcript/transcript.json near hint_s (±25 s); cut edges: 80 ms from the neighbouring kept
words, never inside a word. Frames of the screen at both edges -> stage1/frames/NN_a.png, NN_b.png; «Экран»:
камера (no screencast at that time) / действие (frames differ) / статика.
Output: stage1/cuts_candidates.json, stage1/cuts_proposal.md. --dry: print, write nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

MARGIN = 0.080
HINT_RANGE = 25.0
ACTION_DIFF = 6.0      # mean abs grey difference (0-255) between the two edge frames


def norm(s: str) -> str:
    return re.sub(r"[^\w]+", "", s.lower().replace("ё", "е"))


class Words:
    def __init__(self, T: dict):
        self.T = T
        self.W = [w for s in T["segments"] for w in s["words"]]
        self.N = [norm(w["word"]) for w in self.W]

    def span_from(self, i: int, target: str) -> int | None:
        acc = ""
        for k in range(i, min(len(self.W), i + 40)):
            acc += self.N[k]
            if acc == target:
                return k
            if not target.startswith(acc):
                return None
        return None

    def find(self, hint: float, words: str) -> int:
        target = norm(words)
        best = min(((abs(self.W[i]["start"] - hint), i) for i in range(len(self.W))
                    if self.span_from(i, target) is not None), default=None)
        if best is None or best[0] > HINT_RANGE:
            raise SystemExit(f"not found near {hint} s: {words!r}")
        return best[1]

    def cut(self, c: dict) -> dict:
        i = self.find(c["hint_s"], c["first"])
        target = norm(c["last"])
        j = next((e for k in range(i, min(len(self.W), i + 140)) if (e := self.span_from(k, target)) is not None), None)
        if j is None:
            raise SystemExit(f"end not found after {c['hint_s']} s: {c['last']!r}")
        W = self.W
        prev_end = W[i - 1]["end"] if i > 0 else 0.0
        next_start = W[j + 1]["start"] if j + 1 < len(W) else self.T["duration"]
        cs = max(prev_end + MARGIN, W[i]["start"] - 0.1)
        ce = min(next_start - MARGIN, W[j]["end"] + 0.1)
        warn = []
        if cs > W[i]["start"]:
            cs = (prev_end + W[i]["start"]) / 2
            warn.append("зазор<80мс в начале")
        if ce < W[j]["end"]:
            ce = (W[j]["end"] + next_start) / 2
            warn.append("зазор<80мс в конце")
        return dict(start=round(cs, 3), end=round(ce, 3), first_word=i, last_word=j,
                    text=" ".join(w["word"] for w in W[i:j + 1]), cat=c["cat"], why=c["why"], conf=c["conf"],
                    warn=" ".join(warn))


def screen_at(pieces: list[dict], t_us: int):
    """(path, source s) of the screencast shown at timeline t, or None."""
    for p in pieces:
        if p["start"] <= t_us < p["start"] + p["dur"]:
            return p["path"], (p["src"] + (t_us - p["start"]) * p["speed"]) / 1e6
    return None


def grab(path: str, t: float, out: Path) -> np.ndarray:
    from PIL import Image
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                        "-vf", "scale=480:-1", str(out)], check=True)
    return np.asarray(Image.open(out).convert("L"), dtype=np.float32)


def _ts(t: float) -> str:
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def check_chapters(ch: list[dict]) -> list[str]:
    errs = []
    if not ch or ch[0]["start_transcript_s"] != 0:
        errs.append("first chapter must start at 00:00")
    if len(ch) < 3:
        errs.append("YouTube needs >= 3 chapters")
    for a, b in zip(ch, ch[1:]):
        if b["start_transcript_s"] - a["start_transcript_s"] < 10:
            errs.append(f"chapter «{a['title']}» shorter than 10 s")
    errs += [f"chapter title > 5 words: «{c['title']}»" for c in ch if len(c["title"].split()) > 5]
    return errs


def proposal_md(rows: list[dict], chapters: list[dict], duration: float) -> str:
    def new_time(t):
        return common.map_through_cuts(t, [(r["start"], r["end"]) for r in rows])
    out = ["# Этап 1. Предложение смысловой резки", "",
           "Границы по словам `transcript/transcript.json`, отступ ≥ 80 мс; где слова вплотную — середина зазора (пометка).",
           "Кадры начала/конца: `stage1/frames/NN_a.png`, `NN_b.png`.", "",
           "| № | Начало | Конец | Длит. | Категория | Начало…конец текста | Причина | Уверенность | Экран |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        words = r["text"].replace("|", "/").split()
        txt = " ".join(words) if len(words) <= 12 else " ".join(words[:6]) + " … " + " ".join(words[-5:])
        scr = r["screen"] + (" (" + r["warn"] + ")" if r["warn"] else "")
        out.append(f"| {r['id']} | {_ts(r['start'])} | {_ts(r['end'])} | {r['end'] - r['start']:.1f} с | {r['cat']} | "
                   f"{txt} | {r['why']} | {r['conf']} | {scr} |")
    out += ["", "## Главы (после всех предложенных вырезок; в скобках — по исходнику)", ""]
    out += [f"{i}. {_ts(new_time(c['start_transcript_s']))[:8]} — {c['title']} (исх. {_ts(c['start_transcript_s'])[:8]})"
            for i, c in enumerate(chapters, 1)]
    tot = sum(r["end"] - r["start"] for r in rows)
    sure = sum(r["end"] - r["start"] for r in rows if r["conf"] == "точно")
    out += ["", "## Итог", "", f"- Было: {_ts(duration)}",
            f"- Вырезается всего: {tot:.1f} с ({len(rows)}), «точно» {sure:.1f} с, «под вопросом» {tot - sure:.1f} с",
            f"- Станет при всех вырезках: {_ts(duration - tot)}; только «точно»: {_ts(duration - sure)}", "",
            "**Стоп.** Ответ номерами."]
    return "\n".join(out) + "\n"


def build(cfg, dry: bool) -> list[dict]:
    s1 = cfg.work_dir / "stage1"
    T = json.loads((cfg.work_dir / "transcript" / "transcript.json").read_text(encoding="utf-8"))
    C = json.loads((s1 / "candidates_input.json").read_text(encoding="utf-8"))
    chp = s1 / "chapters_input.json"
    chapters = json.loads(chp.read_text(encoding="utf-8")) if chp.is_file() else []
    W = Words(T)
    rows = sorted((W.cut(c) for c in C), key=lambda r: r["start"])
    for a, b in zip(rows, rows[1:]):
        if a["end"] > b["start"]:
            raise SystemExit(f"cuts overlap: {a['text'][:40]!r} / {b['text'][:40]!r}")
    pieces = [p for p in common.flatten(cfg, common.read_draft(cfg), ("screencast",))]
    for n, r in enumerate(rows, 1):
        r["id"] = n
        if r["end"] - r["start"] < 1.0:
            r["warn"] = (r["warn"] + " короче 1 с (это этап 2)").strip()
        a, b = screen_at(pieces, common.us(r["start"])), screen_at(pieces, common.us(r["end"]))
        if not a or not b:
            r["screen"] = "камера"
        elif dry:
            r["screen"] = "?"
        else:
            fa = grab(a[0], a[1], s1 / "frames" / f"{n:02d}_a.png")
            fb = grab(b[0], b[1], s1 / "frames" / f"{n:02d}_b.png")
            diff = float(np.abs(fa - fb).mean()) if fa.shape == fb.shape else 255.0
            r["frame_diff"] = round(diff, 1)
            r["screen"] = "действие" if diff > ACTION_DIFF else "статика"
    errs = check_chapters(chapters) if chapters else ["no stage1/chapters_input.json"]
    for e in errs:
        print("chapters:", e)
    tot = sum(r["end"] - r["start"] for r in rows)
    print(f"{len(rows)} cuts, {tot:.1f} s; sure {sum(r['end'] - r['start'] for r in rows if r['conf'] == 'точно'):.1f} s")
    for r in rows:
        print(r["id"], r["start"], r["end"], r["cat"], r["conf"], r["screen"], r["warn"], "|", r["text"][:70])
    if dry:
        print("dry run, nothing written")
        return rows
    (s1 / "cuts_candidates.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    (s1 / "cuts_proposal.md").write_text(proposal_md(rows, chapters, T["duration"]), encoding="utf-8")
    print(s1 / "cuts_proposal.md")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 1: cuts proposal")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    build(common.load_config(a.config), a.dry)


if __name__ == "__main__":
    main()
