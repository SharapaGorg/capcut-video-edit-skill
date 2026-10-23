"""Stage 6, step 1: frames + OCR at the focus candidates -> where the named element is (its bbox -> zoom centre).

    python -X utf8 scripts/stage6/find_focus.py --config config.json [--cands stage6/candidates.json] [--dry] [n ...]

Candidates: [{n, t, words: ["Анализ", ...], note}] — t = timeline s of the phrase that names the element.
For each: the screencast frame at t (+ t ± 0.7 s to see scrolling: mean grey difference), OCR (tesseract rus+eng,
psm 11 + 3), the words matched (substring or difflib ratio >= 0.75) -> bbox in source px and the centre on the
canvas (cfg.width x cfg.height). A candidate in an F part of layout.json is marked (focus zooms only in S).
Nothing found -> look at the png and point the area yourself; unsure -> «под вопросом».
Output: stage6/focus_ocr.json (merged by n), frames stage6/frames/, OCR stage6/ocr/. Read-only on the project.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

SCROLL_DT = 0.7
MATCH = 0.75


def to_file(cfg, draft: dict, t: float) -> tuple[str, float] | None:
    """Timeline seconds -> (screencast file, seconds in it) of the screencast piece shown at t."""
    tu = common.us(t)
    p = next((p for p in common.flatten(cfg, draft, ("screencast",)) if p["start"] <= tu < p["end"] and p["src"] is not None), None)
    if p is None:
        return None
    return p["path"], (p["src"] + (tu - p["start"]) * p["speed"]) / 1e6


def _key(s: str) -> str:
    return re.sub(r"[^\w%]", "", s.lower())


def match_words(rows: list[dict], queries: list[str], sx: float, sy: float) -> list[dict]:
    hits = []
    for q in queries:
        ql = _key(q)
        for r in rows:
            tl = _key(r["text"])
            if not tl or not ql:
                continue
            ratio = difflib.SequenceMatcher(None, ql, tl).ratio()
            if ql in tl or ratio >= MATCH:
                hits.append(dict(q=q, text=r["text"], conf=r["conf"], l=r["l"], t=r["t"], w=r["w"], h=r["h"],
                                 cx=round((r["l"] + r["w"] / 2) * sx), cy=round((r["t"] + r["h"] / 2) * sy),
                                 ratio=round(ratio, 2)))
    return sorted(hits, key=lambda h: (-h["ratio"], -h["conf"]))


def grey_diff(a: Path, b: Path) -> float | None:
    from PIL import Image
    try:
        x = np.asarray(Image.open(a).convert("L").resize((320, 180)), dtype=np.int16)
        y = np.asarray(Image.open(b).convert("L").resize((320, 180)), dtype=np.int16)
    except OSError:
        return None
    return round(float(np.abs(x - y).mean()), 2)


def run(cfg, cands: list[dict], dry: bool = False) -> list[dict]:
    from PIL import Image
    d = common.read_draft(cfg)
    rows_l = common.read_layout(cfg)
    wd = cfg.work_dir / "stage6"
    exe = env = None
    if not dry:
        exe, env = common.tesseract(cfg)
    res = []
    for c in cands:
        n, t = c["n"], float(c["t"])
        lay = sorted(common.layout_of(rows_l, t, t + 0.04)) if rows_l else ["?"]
        hit = to_file(cfg, d, t)
        if hit is None:
            print(f"#{n:02d} t={t}: no screencast on the timeline here (layout {lay})")
            res.append(dict(c, layout=lay, file=None, hits=[]))
            continue
        path, ft = hit
        base = wd / "frames" / f"{n:02d}_{t:.2f}"
        if dry:
            print(f"#{n:02d} t={t} -> {Path(path).name} @ {ft:.3f} (layout {lay}); words {c.get('words')}")
            res.append(dict(c, layout=lay, file=Path(path).name, file_time=round(ft, 3), hits=[]))
            continue
        main = common.grab_frame(path, ft, Path(str(base) + ".jpg"))
        m1 = common.grab_frame(path, ft - SCROLL_DT, Path(str(base) + "_m1.jpg"))
        p1 = common.grab_frame(path, ft + SCROLL_DT, Path(str(base) + "_p1.jpg"))
        w, h = Image.open(main).size
        sx, sy = cfg.width / w, cfg.height / h
        rows = (common.ocr_rows(exe, env, main, wd / "ocr" / f"{main.stem}.psm11", 11)
                + common.ocr_rows(exe, env, main, wd / "ocr" / f"{main.stem}.psm3", 3))
        hits = match_words(rows, c.get("words") or [], sx, sy)[:12]
        r = dict(c, layout=lay, file=Path(path).name, file_time=round(ft, 3), frame=main.name, src_size=[w, h],
                 diff_prev=grey_diff(main, m1), diff_next=grey_diff(main, p1), hits=hits)
        res.append(r)
        print(f"#{n:02d} t={t} {r['file']}@{r['file_time']} layout {lay} diff {r['diff_prev']}/{r['diff_next']} "
              f"{c.get('note', '')}")
        for x in hits[:5]:
            print(f"     {x['q']!r}->{x['text']!r} conf {x['conf']:.0f} r{x['ratio']} canvas({x['cx']},{x['cy']}) "
                  f"src {x['l']},{x['t']},{x['w']}x{x['h']}")
        if not hits:
            print(f"     not found: look at {main} and point the area (or «под вопросом»)")
    if not dry:
        fp = wd / "focus_ocr.json"
        old = {r["n"]: r for r in json.loads(fp.read_text(encoding="utf-8"))} if fp.is_file() else {}
        old.update({r["n"]: r for r in res})
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(sorted(old.values(), key=lambda r: r["n"]), ensure_ascii=False, indent=1),
                      encoding="utf-8")
        print("written:", fp)
    else:
        print("dry run, nothing extracted")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 6: frames + OCR at focus candidates")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--cands", help="default <work_dir>/stage6/candidates.json")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("only", nargs="*", type=int, help="candidate numbers")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    cp = Path(a.cands) if a.cands else cfg.work_dir / "stage6" / "candidates.json"
    cands = json.loads(cp.read_text(encoding="utf-8"))
    if a.only:
        cands = [c for c in cands if c["n"] in a.only]
    run(cfg, cands, a.dry)


if __name__ == "__main__":
    main()
