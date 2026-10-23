"""Stage 5, check: the censored copies against the sources (STAGE_5 «Проверка»).

    python -X utf8 scripts/stage5/verify_censor.py --config config.json

For every censored file (stage5/censor_applied.json, else stage5/censored/<stem>_censored.mp4): duration, fps and size
= the source. For every applied finding: frames before/after at the middle (and at each box of a moving one) ->
stage5/verify/NN_before.png / NN_after.png (look: the blur covers it all); OCR of the after-frame (psm 11) — no
e-mail / key / password / address-bar token left inside the blurred box. Report stage5/verify/report.json; exit 1
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
from scan_patterns import SECRET, scan_rows  # noqa: E402


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
        boxes = f.get("boxes") or [{"t": (f["src_start"] + f["src_end"]) / 2, "bbox": f["bbox"]}]
        left = []
        for j, b in enumerate(boxes):
            t = b["t"] + (0.5 if f.get("boxes") else 0)
            tag = f"{i:02d}" + (f"_{j}" if len(boxes) > 1 else "")
            common.grab_frame(str(s), t, out / f"{tag}_before.png")
            if not c.is_file():
                left.append("no censored file")
                continue
            after = common.grab_frame(str(c), t, out / f"{tag}_after.png")
            rows = common.ocr_rows(exe, env, after, out / f"{tag}_after.psm11", 11)
            left += [h["match"] for h in scan_rows(rows) if h["type"] in SECRET and overlaps(h["bbox"], b["bbox"])]
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
