"""Stage 5, step 2: OCR (tesseract rus+eng, psm 3 and psm 11) of stage5/frames.

    python -X utf8 scripts/stage5/run_ocr.py --config config.json [--jobs 8] [--dry]

Output: <work_dir>/stage5/ocr/<stem>_<sec>.tsv (psm 3) and <stem>_<sec>.psm11.tsv; done files are skipped
(restartable; run in the background). Languages: config.json → tessdata (a folder with rus/eng.traineddata) or
TESSDATA_PREFIX or the install's tessdata (common.tesseract stops with what to do if rus/eng are missing).
"""
from __future__ import annotations

import argparse
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402


def out_base(ocr_dir: Path, img: Path, psm: int) -> Path:
    stem, sec = img.parent.name, img.stem
    return ocr_dir / (f"{stem}_{sec}" if psm == 3 else f"{stem}_{sec}.psm{psm}")


def _job(args):
    exe, env, img, base, psm = args
    common.ocr_rows(exe, env, img, base, psm)
    tsv = Path(str(base) + ".tsv")
    return 0 if tsv.is_file() and tsv.stat().st_size else 1


def run(cfg, jobs: int = 8, dry: bool = False) -> dict:
    root = cfg.work_dir / "stage5"
    imgs = sorted((root / "frames").glob("*/*.jpg"))
    ocr_dir = root / "ocr"
    todo = [(img, psm) for img in imgs for psm in (3, 11)
            if not (Path(str(out_base(ocr_dir, img, psm)) + ".tsv").is_file())]
    print(f"frames {len(imgs)}, OCR jobs to do {len(todo)} (of {2 * len(imgs)})")
    if dry or not todo:
        print("dry run" if dry else "nothing to do")
        return {"frames": len(imgs), "todo": len(todo)}
    exe, env = common.tesseract(cfg)
    ocr_dir.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    t0, done, fails = time.time(), 0, 0
    with open(root / "logs" / "ocr.log", "a", encoding="utf-8") as log, Pool(jobs) as pool:
        for rc in pool.imap_unordered(_job, [(exe, env, i, out_base(ocr_dir, i, p), p) for i, p in todo], chunksize=4):
            done += 1
            fails += rc != 0
            if done % 100 == 0 or done == len(todo):
                log.write(f"{done}/{len(todo)} fails={fails} {time.time() - t0:.0f}s\n")
                log.flush()
        log.write("DONE\n")
    print(f"done {done}, fails {fails}, {time.time() - t0:.0f} s")
    return {"frames": len(imgs), "done": done, "fails": fails}


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 5: OCR of the frames")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.jobs, a.dry)


if __name__ == "__main__":
    main()
