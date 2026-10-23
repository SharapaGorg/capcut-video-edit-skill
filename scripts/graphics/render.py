"""Stages 7–8: render the compositions of graphics/comps.json frame by frame -> ProRes 4444 MOV with alpha.

    python -X utf8 scripts/graphics/render.py --config config.json [--only ID [ID ...]]

Playwright Chromium, transparent background: every frame = window.seek(frame / fps) + a PNG screenshot
(omit_background) piped to ffmpeg -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le. Frames = round(end·fps) −
round(start·fps) (the MOV lands on frame boundaries of the timeline). The project must be 16:9 (the HTML is a
1920×1080 page; another size = device scale factor). Writes <work_dir>/graphics/out/<id>.mov and merges
<work_dir>/graphics/render_meta.json {id: {file, html, sha, start, end, start_us, end_us, frames, duration, fps,
pix_fmt, bbox, font, problems}}; problems = placement rules on the drawn box (gfx_build.bbox_problems) and a font
that did not load — apply_graphics refuses such items. Long batches: run in the background.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import gfx_build  # noqa: E402

PAGE_W, PAGE_H = 1920, 1080
BOX_EVERY = 5                 # frames between bbox samples
INSTALL = "pip install playwright && python -m playwright install chromium"


def meta_path(cfg) -> Path:
    return cfg.work_dir / "graphics" / "render_meta.json"


def read_meta(cfg) -> dict:
    p = meta_path(cfg)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def frames_of(cfg, comp) -> tuple[int, int]:
    return int(round(comp["start"] * cfg.fps)), int(round(comp["end"] * cfg.fps))


def entry(cfg, cid: str, comp: dict, mov: Path, pix_fmt: str, bbox, font: str = "Unbounded") -> dict:
    """The render_meta.json record of one composition."""
    f0, f1 = frames_of(cfg, comp)
    problems = gfx_build.bbox_problems(comp, bbox, cfg.width, cfg.height)
    if font != "Unbounded":
        problems.append(f"font Unbounded did not load ({font}): check assets/Unbounded-var.ttf")
    if "yuva" not in pix_fmt and "argb" not in pix_fmt:
        problems.append(f"no alpha channel (pix_fmt {pix_fmt})")
    return {"file": Path(mov).as_posix(), "html": comp["html"], "sha": comp["sha"], "start": comp["start"],
            "end": comp["end"], "start_us": common.snap(comp["start"], cfg.fps), "end_us": common.snap(comp["end"], cfg.fps),
            "frames": f1 - f0, "duration": round((f1 - f0) / cfg.fps, 6), "fps": cfg.fps, "pix_fmt": pix_fmt,
            "bbox": list(bbox) if bbox else None, "font": font, "problems": problems}


def pix_fmt_of(path) -> str:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return out.strip()


def _union(a, b):
    if not a:
        return b
    if not b:
        return a
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def render_comp(page, cfg, comp: dict, mov: Path) -> tuple[list | None, str]:
    """Frames of one composition -> mov. Returns (bbox union in project px, font family that rendered)."""
    f0, f1 = frames_of(cfg, comp)
    n = f1 - f0
    if n <= 0:
        raise SystemExit(f"{mov.stem}: 0 frames ({comp['start']}–{comp['end']})")
    page.goto(Path(comp["html"]).as_uri())
    page.evaluate("document.fonts.ready.then(() => true)")
    font = "Unbounded" if page.evaluate("document.fonts.check('800 40px Unbounded')") else "fallback"
    k = cfg.width / PAGE_W
    mov.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-vcodec", "png", "-r", str(cfg.fps), "-i", "-",
           "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0", str(mov)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    box = None
    try:
        for i in range(n):
            page.evaluate(f"seek({i / cfg.fps})")
            if i % BOX_EVERY == 0 or i == n - 1:
                b = page.evaluate("window.visibleBox ? visibleBox() : null")
                box = _union(box, [int(round(v * k)) for v in b] if b else None)
            p.stdin.write(page.screenshot(omit_background=True, type="png",
                                          clip={"x": 0, "y": 0, "width": PAGE_W, "height": PAGE_H}))
    finally:
        p.stdin.close()
        p.wait()
    if p.returncode != 0:
        raise SystemExit(f"ffmpeg failed on {mov}")
    return box, font


def run(cfg, only=None, log=print) -> dict:
    comps = gfx_build.read_comps(cfg)
    if not comps:
        raise SystemExit(f"нет {gfx_build.comps_path(cfg)}: сначала gfx_build.py")
    ids = list(only) if only else list(comps)
    unknown = [i for i in ids if i not in comps]
    if unknown:
        raise SystemExit(f"нет в comps.json: {unknown}")
    if abs(cfg.width * PAGE_H - cfg.height * PAGE_W) > 0:
        raise SystemExit(f"project {cfg.width}×{cfg.height} is not 16:9: the HTML pages are 1920×1080")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(f"Playwright не установлен: {INSTALL}")
    meta = read_meta(cfg)
    done = {}
    out_dir = cfg.work_dir / "graphics" / "out"
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as e:                      # browser binaries missing
            raise SystemExit(f"Chromium для Playwright не запускается ({str(e).splitlines()[0]}): {INSTALL}")
        page = browser.new_page(viewport={"width": PAGE_W, "height": PAGE_H}, device_scale_factor=cfg.width / PAGE_W)
        for cid in ids:
            c = comps[cid]
            mov = out_dir / f"{cid}.mov"
            t0 = time.time()
            box, font = render_comp(page, cfg, c, mov)
            done[cid] = entry(cfg, cid, c, mov, pix_fmt_of(mov), box, font)
            meta[cid] = done[cid]
            m = done[cid]
            log(f"  {cid}: {m['frames']} frames, {m['duration']:.3f} s, {m['pix_fmt']}, bbox {m['bbox']}, "
                f"{time.time() - t0:.1f} s -> {mov.name}" + (f"  PROBLEMS: {m['problems']}" if m["problems"] else ""))
        browser.close()
    meta_path(cfg).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [k for k, v in done.items() if v["problems"]]
    log("VALIDATION:", "OK" if not bad else f"FAIL ({bad}: fix the item or the HTML, re-run gfx_build + render)")
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(description="stages 7–8: comps.json -> ProRes 4444 MOV with alpha")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--only", nargs="+", help="composition ids (default: all in comps.json)")
    a = ap.parse_args(argv)
    done = run(common.load_config(a.config), a.only)
    if any(v["problems"] for v in done.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
