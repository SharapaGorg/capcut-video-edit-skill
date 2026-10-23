"""Stage 5, check: the censored copies against the sources (STAGE_5 «Проверка»).

    python -X utf8 scripts/stage5/verify_censor.py --config config.json

For every censored file (stage5/censor_applied.json, else stage5/censored/<stem>_censored.mp4): duration, fps and size
= the source. For every applied finding: the SAME frames as its OCR (the seconds of its boxes, else every whole second
of its range) re-OCRed (psm 11) from the censored copy — no hidden pattern type (build_findings.HIDE: e-mail, key,
password, address-bar token, card) left inside the blurred box; before/after png of its first frame ->
stage5/verify/NN_before.png / NN_after.png (look: the blur covers it all). Report stage5/verify/report.json; exit 1
on a problem.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
from apply_censor import PAD, out_path, same_format, sources  # noqa: E402
from build_findings import HIDE  # noqa: E402
from scan_patterns import scan_rows  # noqa: E402

SECRET = set(HIDE)   # the pattern types that are hidden must be gone after the blur


def ocr_seconds(f: dict) -> list[float]:
    """The frames the finding came from: the OCR seconds of its boxes, else every whole second of its range (the
    frames extract_frames made, 1/s), at least one."""
    if f.get("boxes"):
        return [float(b["t"]) for b in f["boxes"]]
    import math
    secs = [float(s) for s in range(math.ceil(f["src_start"]), math.ceil(f["src_end"]))]
    return secs or [(f["src_start"] + f["src_end"]) / 2]


def overlaps(a, b, pad=PAD) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw + pad and bx - pad < ax + aw and ay < by + bh + pad and by - pad < ay + ah


def run(cfg) -> dict:
    root = cfg.work_dir / "stage5"
    fp = root / "censor_findings.json"
    if not fp.is_file():
        raise SystemExit(f"нет {fp}")
    findings = [f for f in json.loads(fp.read_text(encoding="utf-8")) if f.get("apply")]
    d = common.read_draft(cfg)
    src = sources(cfg, d)
    ap = root / "censor_applied.json"
    applied = json.loads(ap.read_text(encoding="utf-8")) if ap.is_file() else {}
    exe, env = common.tesseract(cfg)
    out = root / "verify"
    out.mkdir(parents=True, exist_ok=True)
    rep = {"files": {}, "findings": []}
    bad = 0
    for name in sorted({f["file"] for f in findings}):
        s = src.get(name) or (Path(cfg.sources.get("screencasts") or ".") / name)
        c = Path(applied.get(name) or out_path(cfg, s))
        ok = c.is_file() and s.is_file() and same_format(s, c)
        rep["files"][name] = {"censored": str(c), "format_ok": ok}
        bad += not ok
        print(f"{name}: {c.name} format = source: {'OK' if ok else 'FAIL'}")
    for i, f in enumerate(findings, 1):
        s = src.get(f["file"]) or (Path(cfg.sources.get("screencasts") or ".") / f["file"])
        c = Path(applied.get(f["file"]) or out_path(cfg, s))
        boxes = {float(b["t"]): b["bbox"] for b in f.get("boxes") or []}
        left = []
        if not c.is_file():
            left.append("no censored file")
        for j, t in enumerate(ocr_seconds(f) if c.is_file() else []):
            bb = boxes.get(t, f["bbox"])
            tag = f"{i:02d}_{j:03d}"
            if j == 0:   # before/after pngs of the first frame, to look at
                common.grab_frame(str(s), t, out / f"{i:02d}_before.png")
                common.grab_frame(str(c), t, out / f"{i:02d}_after.png")
            after = common.grab_frame(str(c), t, out / "frames" / f"{tag}_after.jpg")
            rows = common.ocr_rows(exe, env, after, out / "ocr" / f"{tag}_after.psm11", 11)
            left += [f"{t:.0f}s {h['match']}" for h in scan_rows(rows) if h["type"] in SECRET and overlaps(h["bbox"], bb)]
        rep["findings"].append({"n": i, "file": f["file"], "what": f.get("what"), "left": left})
        bad += bool(left)
        print(f"{i:02d} {f['file']} {f['src_start']:.2f}–{f['src_end']:.2f} {str(f.get('what'))[:60]} -> "
              f"{'CLEAN' if not left else left}")
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print("FAIL" if bad else "OK", "— before/after frames in", out)
    if bad:
        raise SystemExit(1)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 5: verify the censored copies")
    ap.add_argument("--config", default="config.json")
    a = ap.parse_args(argv)
    run(common.load_config(a.config))


if __name__ == "__main__":
    main()
