"""LAYOUT B1–B3: candidates for the full-screen camera (F) -> proposal (references/stages/STAGE_LAYOUT.md).

    python -X utf8 scripts/layout/candidates.py --config config.json [--dry]

A candidate: speech, the screencast is static >= 6 s (frames every 0.5 s do not differ), no words pointing at the
screen (DEICTIC), F >= 4 s, >= 15 s between switches (greedy, longest first), edges on phrase boundaries, no sped
screencast. Always F: the intro before the first screen, the conclusion after the last screen action.
Inputs: stage3/transcript_timeline.json (timeline time), the project (screencast pieces, common.flatten), frames
2 fps 256x144 grey per screencast file (cache <work_dir>/stage2/frames, shared with stage 2), layout/layout.json.
Outputs (<work_dir>/layout/): layout_candidates.json, layout_proposal.md, f_ranges_proposed.json — the new F
ranges (already-F parts subtracted) for apply_layout.py --ranges. --dry: print only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

STATIC_MIN = 6.0
F_MIN = 4.0
GAP_MIN = 15.0
PHRASE_GAP = 0.25
PIX_DIFF, CHANGED = 24, 0.02   # a pixel changed if |diff| > 24; a frame changed if > 2 % of the pixels did
DEICTIC = ["вот", "здесь", "тут", "смотрите", "смотрим", "видите", "видим", "нажимаем", "нажмите", "нажать",
           "эта кнопка", "эту кнопку", "кнопк", "открываем", "открыть", "откроем", "выбираем", "выберите", "выбрать",
           "справа", "слева", "сверху", "снизу", "сюда", "вот этот", "вот эту", "вот это"]


def _norm(w: str) -> str:
    return re.sub(r"[^\w\s]", "", w.lower())


def deictic_flags(ws: list[dict]) -> list[bool]:
    """Per word: it points at the screen (a DEICTIC word, a prefix of 5+ letters, or a two-word DEICTIC phrase)."""
    xs = [_norm(w["word"]) for w in ws]
    single = [k for k in DEICTIC if " " not in k]
    pairs = {tuple(k.split()) for k in DEICTIC if " " in k}
    out = [any(x == k or (len(k) > 4 and x.startswith(k)) for k in single) for x in xs]
    for i in range(len(xs) - 1):
        if (xs[i], xs[i + 1]) in pairs:
            out[i] = out[i + 1] = True
    return out


def _ends_phrase(ws, i) -> bool:
    return i == len(ws) - 1 or ws[i + 1]["start"] - ws[i]["end"] >= PHRASE_GAP or bool(re.search(r"[.!?…]$", ws[i]["word"]))


def _starts_phrase(ws, i) -> bool:
    return i == 0 or ws[i]["start"] - ws[i - 1]["end"] >= PHRASE_GAP or bool(re.search(r"[.!?…]$", ws[i - 1]["word"]))


def propose(words: list[dict], static_tl: list[tuple[float, float]], sped: list[tuple[float, float]],
            intro_end: float, duration: float, last_change: float | None = None) -> dict:
    """B1-B2 on timeline seconds. words: [{word, start, end}] sorted; static_tl: static screencast runs;
    sped: sped screencast ranges; intro_end: first screen on the timeline; last_change: last screen action.
    Returns {"candidates_all", "proposed" (rows incl. intro/conclusion), "conclusion"}."""
    words = sorted(words, key=lambda w: w["start"])
    flags = deictic_flags(words)
    cands = []
    for a, b in static_tl:
        if b - a < STATIC_MIN or b <= intro_end or any(x < b and y > a for x, y in sped):
            continue
        idx = [i for i, w in enumerate(words) if w["start"] >= a - 1e-6 and w["end"] <= b + 1e-6]
        blocks, cur = [], []
        for i in idx:
            if flags[i]:
                if cur:
                    blocks.append(cur)
                cur = []
            else:
                cur.append(i)
        if cur:
            blocks.append(cur)
        for blk in blocks:
            starts = [i for i in blk if _starts_phrase(words, i)]
            ends = [i for i in blk if _ends_phrase(words, i)]
            if not starts or not ends or ends[-1] <= starts[0]:
                continue
            s_i, e_i = starts[0], ends[-1]
            s = max(words[s_i]["start"] - 0.1, a, words[s_i - 1]["end"] if s_i > 0 else a)
            e = min(words[e_i]["end"] + 0.1, b, words[e_i + 1]["start"] if e_i + 1 < len(words) else b)
            if e - s < F_MIN:
                continue
            text = " ".join(words[i]["word"] for i in range(s_i, e_i + 1))
            cands.append({"start": round(s, 2), "end": round(e, 2), "dur": round(e - s, 2), "text": text,
                          "static": [round(a, 1), round(b, 1)]})
    conclusion = None
    if last_change is not None:
        tail = [w for w in words if w["start"] >= last_change]
        if tail:
            ci = next(i for i, w in enumerate(words) if w["start"] >= last_change)
            k = next((i for i in range(ci, len(words)) if _starts_phrase(words, i)), ci)
            cs = max(words[k]["start"] - 0.1, words[k - 1]["end"] if k > 0 else 0.0)
            conclusion = {"start": round(cs, 2), "end": round(duration, 2), "dur": round(duration - cs, 2),
                          "text": " ".join(w["word"] for w in words[k:]), "always": "заключение"}
            cands = [c for c in cands if c["end"] <= cs]
    chosen = []
    for c in sorted(cands, key=lambda c: -c["dur"]):
        far = all(c["start"] - x["end"] >= GAP_MIN or x["start"] - c["end"] >= GAP_MIN for x in chosen)
        if far and (conclusion is None or conclusion["start"] - c["end"] >= GAP_MIN):
            chosen.append(c)
    chosen.sort(key=lambda c: c["start"])
    rows = []
    if intro_end > 0:
        rows.append({"start": 0.0, "end": round(intro_end, 2), "dur": round(intro_end, 2),
                     "text": " ".join(w["word"] for w in words if w["end"] <= intro_end), "always": "вступление"})
    rows += chosen + ([conclusion] if conclusion else [])
    return {"candidates_all": sorted(cands, key=lambda c: c["start"]), "proposed": rows, "conclusion": conclusion}


class Screen:
    """Screencast frame at timeline time t (first screencast piece covering t)."""

    def __init__(self, cfg, draft, dry):
        self.pieces = [p for p in common.flatten(cfg, draft, ("screencast",)) if p["src"] is not None]
        self.cache = cfg.work_dir / "stage2" / "frames"
        self.dry = dry
        self.frames = {}
        self.mask = common.screen_mask()

    def frame(self, t_us):
        p = next((p for p in self.pieces if p["start"] <= t_us < p["end"]), None)
        if p is None:
            return None
        if p["path"] not in self.frames:
            self.frames[p["path"]] = common.screen_frames(p["path"], self.cache, self.dry)
        fr = self.frames[p["path"]]
        if fr is None or not len(fr):
            return None
        src = (p["src"] + (t_us - p["start"]) * p["speed"]) / 1e6
        return fr[min(int(src * common.FPS2), len(fr) - 1)]

    def runs(self, duration_us) -> tuple[list[tuple[float, float]], float | None, int]:
        """(static runs >= STATIC_MIN on the timeline, last screen change, frames missing)."""
        step = int(1e6 / common.FPS2)
        ts = list(range(0, duration_us, step))
        fs = [self.frame(t) for t in ts]
        missing = sum(1 for t, f in zip(ts, fs) if f is None and any(p["start"] <= t < p["end"] for p in self.pieces))
        changed = []
        for x, y in zip(fs, fs[1:]):
            if x is None or y is None:
                changed.append(None)
            else:
                changed.append(float((np.abs(y.astype(np.int16) - x.astype(np.int16))[self.mask] > PIX_DIFF).mean()) > CHANGED)
        runs, i = [], 0
        while i < len(changed):
            if changed[i] is False:
                j = i
                while j < len(changed) and changed[j] is False:
                    j += 1
                a, b = ts[i] / 1e6, ts[j] / 1e6
                if b - a >= STATIC_MIN:
                    runs.append((a, b))
                i = j
            else:
                i += 1
        last = max((ts[k + 1] / 1e6 for k, c in enumerate(changed) if c), default=None)
        return runs, last, missing


def mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def proposal_md(res: dict, duration: float, existing: list[tuple[float, float]]) -> str:
    rows = res["proposed"]
    lines = ["# Предложение раскладки (STAGE_LAYOUT B3)", "",
             f"Таймлайн {duration:.1f} с. Условия: скринкаст статичен ≥ {STATIC_MIN:.0f} с, есть речь, нет указаний на "
             f"экран, F ≥ {F_MIN:.0f} с, между переключениями ≥ {GAP_MIN:.0f} с, границы — по паузам между словами. "
             "Ускоренный скринкаст исключён.", "",
             "| № | Начало | Конец | Длит. | Раскладка | Текст (начало…конец) | Причина |",
             "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        t = r["text"] if len(r["text"]) <= 90 else r["text"][:45] + " … " + r["text"][-40:]
        why = r.get("always") or f"экран статичен {r['static'][0]}–{r['static'][1]} с, речь без указаний на экран"
        lines.append(f"| {i} | {mmss(r['start'])} | {mmss(r['end'])} | {r['dur']:.1f} с | F | {t} | {why} |")
    f_total = sum(r["dur"] for r in rows)
    lines += ["", f"Итого F: {f_total:.1f} с ({f_total / max(duration, 1e-9):.0%}), S: {duration - f_total:.1f} с. "
                  f"Кандидатов до фильтра 15 с: {len(res['candidates_all'])}.",
              f"Уже F в проекте: {', '.join(f'{mmss(a)}–{mmss(b)}' for a, b in existing) or 'нет'}.", "",
              "**Стоп до утверждения.** Новые диапазоны: f_ranges_proposed.json → apply_layout.py --ranges."]
    return "\n".join(lines)


def run(cfg, dry: bool = False) -> dict:
    words = common.timeline_words(cfg)
    if not words:
        raise SystemExit("нет stage3/transcript_timeline.json: сначала этап 3 (build_maps.py)")
    d = common.read_draft(cfg)
    dur_us = d["duration"]
    scr = Screen(cfg, d, dry)
    if not scr.pieces:
        raise SystemExit("на таймлайне нет скринкаста: раскладка S/F не нужна")
    static, last, missing = scr.runs(dur_us)
    if missing:
        print(f"warning: no frames for {missing} points (dry run without cached frames?)")
    sped = [(p["start"] / 1e6, p["end"] / 1e6) for p in scr.pieces if abs(p["speed"] - 1.0) > 1e-6]
    intro_end = min(p["start"] for p in scr.pieces) / 1e6
    res = propose(words, static, sped, intro_end, dur_us / 1e6, last)
    existing = [(a / 1e6, b / 1e6) for a, b in common.f_ranges(cfg, d)]
    new = []
    for r in res["proposed"]:
        for a, b in common.subtract_ranges(r["start"], r["end"], existing):
            if b - a >= F_MIN:
                new.append([round(a, 3), round(b, 3)])
    md = proposal_md(res, dur_us / 1e6, existing)
    print(md)
    print(f"static runs >= {STATIC_MIN:.0f} s: {len(static)}; sped: {sped}; new F ranges: {len(new)}")
    if not dry:
        out = cfg.work_dir / "layout"
        out.mkdir(parents=True, exist_ok=True)
        (out / "layout_proposal.md").write_text(md, encoding="utf-8")
        (out / "layout_candidates.json").write_text(json.dumps(
            {"intro_end": intro_end, "last_screen_change_tl": last, "static_runs_tl": static, "existing_f": existing,
             **res}, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "f_ranges_proposed.json").write_text(json.dumps(new), encoding="utf-8")
        print("written:", out)
    else:
        print("dry run, nothing written")
    return dict(res, new_ranges=new)


def main(argv=None):
    ap = argparse.ArgumentParser(description="LAYOUT B1-B3: full-screen camera candidates -> layout_proposal.md")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.dry)


if __name__ == "__main__":
    main()
