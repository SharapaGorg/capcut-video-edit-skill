"""Stage 6, check (STAGE_6 «Проверка», validation.md §4) of stage6/zooms.json against the project.

    python -X utf8 scripts/stage6/check_zooms.py --config config.json [--no-frames]

Per focus zoom: the keys are on one segment and inside it; the element centre is inside the visible area at the
peak (40 px margin) and not under the camera circle (circle from the project: clip + mask of the circle piece);
frames at the start/end of the peak with the visible area, the circle and the element drawn -> stage6/check/NN.png
(look at them); OCR of the end frame: the word is still near the centre (no scrolling inside the zoom);
SFX start = zoom start ±1 frame; SFX level = voice − 12 LU ±1 (re-measured). Also: >= 8 s between focus zooms,
each >= 2 s. Report stage6/check/report.json; exit 1 on a problem.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "layout"))
import common  # noqa: E402
import effects  # noqa: E402
import find_focus  # noqa: E402
from apply_zooms import FOCUS_GAP, FOCUS_MIN, VOICE_WIN  # noqa: E402

MARGIN, CIRCLE_MARGIN, OCR_NEAR = 40, 60, 250


def circle_geometry(cfg, d: dict) -> tuple[float, float, float] | None:
    """(cx, cy, r) canvas px of the camera circle: clip transform/scale + mask config of the first circle piece."""
    import apply_layout
    try:
        t = apply_layout.circle_track(cfg, d)
    except SystemExit:
        return None
    for s in common.by_start(t["segments"]):
        a = s["target_timerange"]["start"]
        for p in common.lift(d, s, a, common.seg_end(s)):
            mask = next((m for k, m in p["mats"] if k == "common_mask"), None)
            if mask is None:
                continue
            clip = p["seg"].get("clip") or {}
            sx = float((clip.get("scale") or {}).get("x", 1.0))
            tx, ty = float((clip.get("transform") or {}).get("x", 0)), float((clip.get("transform") or {}).get("y", 0))
            mc_ = mask.get("config") or {}
            W, H = cfg.width, cfg.height
            cx = W / 2 * (1 + tx) + float(mc_.get("centerX", 0)) * W * sx
            cy = H / 2 * (1 - ty) - float(mc_.get("centerY", 0)) * H * sx
            return cx, cy, float(mc_.get("width", 0.4)) * W * sx / 2
    return None


def visible(pos, s, W, H):
    """Visible content rect (px) at clip transform pos and scale s: screen = s*c + pos (1 = half canvas, y up)."""
    x0, x1 = (-1 - pos[0]) / s, (1 - pos[0]) / s
    y0, y1 = (-1 - pos[1]) / s, (1 - pos[1]) / s
    return (W / 2 * (1 + x0), H / 2 * (1 - y1), W / 2 * (1 + x1), H / 2 * (1 - y0))


def on_screen(pt, pos, s, W, H):
    cx, cy = (pt[0] - W / 2) / (W / 2), (H / 2 - pt[1]) / (H / 2)
    return (W / 2 * (1 + s * cx + pos[0]), H / 2 * (1 - (s * cy + pos[1])))


def sheet(cfg, d, z, rect, circle, out: Path) -> Path | None:
    from PIL import Image, ImageDraw
    W, H = cfg.width, cfg.height
    ims = []
    for i, t in enumerate((z["peak"][0] + 0.1, z["peak"][1] - 0.1)):
        hit = find_focus.to_file(cfg, d, t)
        if hit is None:
            return None
        p = common.grab_frame(hit[0], hit[1], out.parent / f"_{z['n']:02d}_{i}.jpg")
        im = Image.open(p).convert("RGB").resize((W, H))
        dr = ImageDraw.Draw(im)
        dr.rectangle(rect, outline=(255, 80, 0), width=5)
        c = z["center"]
        dr.ellipse((c[0] - 12, c[1] - 12, c[0] + 12, c[1] + 12), outline=(0, 255, 0), width=4)
        if circle:
            s, pos = z["scale"], z["position"]
            kx = ((circle[0] - W / 2) / (W / 2) - pos[0]) / s
            ky = ((H / 2 - circle[1]) / (H / 2) - pos[1]) / s
            r = circle[2] / s
            px, py = W / 2 * (1 + kx), H / 2 * (1 - ky)
            dr.ellipse((px - r, py - r, px + r, py + r), outline=(0, 200, 255), width=4)
        dr.text((rect[0] + 10, rect[1] + 10), f"#{z['n']} t={t:.2f} x{z['scale']}", fill=(255, 80, 0))
        ims.append(im)
    sh = Image.new("RGB", (W * 2 + 20, H))
    sh.paste(ims[0], (0, 0))
    sh.paste(ims[1], (W + 20, 0))
    sh.resize((W + 10, H // 2)).save(out)
    return out


def run(cfg, frames: bool = True) -> list[dict]:
    zp = cfg.work_dir / "stage6" / "zooms.json"
    if not zp.is_file():
        raise SystemExit(f"нет {zp}: сначала apply_zooms.py")
    zj = json.loads(zp.read_text(encoding="utf-8"))
    d = common.read_draft(cfg)
    W, H = cfg.width, cfg.height
    segs = {s["id"]: s for t in d["tracks"] for s in t["segments"]}
    circle = circle_geometry(cfg, d)
    out = cfg.work_dir / "stage6" / "check"
    out.mkdir(parents=True, exist_ok=True)
    exe = env = None
    if frames:
        try:
            exe, env = common.tesseract(cfg)
        except SystemExit as e:
            print("  note: OCR skipped:", e)
    report = []
    for z in zj.get("focus", []):
        r = {"n": z["n"], "start": z["start"], "end": z["end"], "problems": []}
        seg = segs.get(z["segment_id"])
        if seg is None or not any(c.get("property_type") in effects.ZOOM_PROPS for c in seg.get("common_keyframes") or []):
            r["problems"].append("zoom keys not found on the segment")
        elif not effects.keyframes_inside(seg):
            r["problems"].append("keys outside the segment")
        rect = visible(z["position"], z["scale"], W, H)
        c = z["center"]
        if not (rect[0] + MARGIN <= c[0] <= rect[2] - MARGIN and rect[1] + MARGIN <= c[1] <= rect[3] - MARGIN):
            r["problems"].append("element not inside the visible area")
        scr = on_screen(c, z["position"], z["scale"], W, H)
        if circle and math.hypot(scr[0] - circle[0], scr[1] - circle[1]) <= circle[2] + CIRCLE_MARGIN:
            r["problems"].append(f"element under the camera circle (screen {scr[0]:.0f},{scr[1]:.0f})")
        sx = z.get("sfx") or {}
        sfx = segs.get(sx.get("segment_id"))
        if sfx is None:
            r["problems"].append("SFX segment missing")
        else:
            if abs(sfx["target_timerange"]["start"] - z["start_us"]) > 1e6 / cfg.fps + 1:
                r["problems"].append("SFX start != zoom start ±1 frame")
            path = common.index(d["materials"])[sfx["material_id"]][1]["path"]
            vlu = effects.voice_lufs(cfg, d, max(0, z["start_us"] - common.us(VOICE_WIN)),
                                     min(d["duration"], z["end_us"] + common.us(VOICE_WIN)))
            peak = effects.loudness(effects.pcm(path) * float(sfx.get("volume", 1.0)))["M_max"]
            r["sfx_level_lu"] = None if vlu is None else round(peak - vlu, 2)
            if vlu is None or abs(peak - vlu - effects.SFX_LU) > 1.0:
                r["problems"].append(f"SFX level {r['sfx_level_lu']} LU vs voice (need {effects.SFX_LU:+.0f} ±1)")
        if frames:
            png = sheet(cfg, d, z, rect, circle, out / f"{z['n']:02d}.png")
            r["png"] = str(png) if png else None
            img = out / f"_{z['n']:02d}_1.jpg"
            if exe and z.get("words") and png and img.is_file():
                from PIL import Image
                w, h = Image.open(img).size
                rows = common.ocr_rows(exe, env, img, out / f"_{z['n']:02d}_1.psm11", 11)
                hits = find_focus.match_words(rows, z["words"], W / w, H / h)
                near = min((math.hypot(x["cx"] - c[0], x["cy"] - c[1]) for x in hits), default=None)
                r["end_ocr_dist"] = None if near is None else round(near)
                if near is None or near > OCR_NEAR:
                    r["problems"].append("end of the peak: the word is not near the centre (scrolled?)")
        report.append(r)
        print(f"#{z['n']:02d} {z['start']:.2f}-{z['end']:.2f} x{z['scale']}: {'OK' if not r['problems'] else r['problems']}")
    fz = zj.get("focus", [])
    gaps = [b["start"] - a["end"] for a, b in zip(fz, fz[1:])]
    general = []
    if gaps and min(gaps) < FOCUS_GAP - 1e-6:
        general.append(f"min gap between focus zooms {min(gaps):.2f} s < {FOCUS_GAP:.0f}")
    if fz and min(z["end"] - z["start"] for z in fz) < FOCUS_MIN - 1e-6:
        general.append(f"a focus zoom shorter than {FOCUS_MIN:.0f} s")
    (out / "report.json").write_text(json.dumps({"focus": report, "general": general}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    bad = [r["n"] for r in report if r["problems"]]
    print("general:", general or "OK", "| problems:", bad or "none", "| circle:", circle)
    if bad or general:
        raise SystemExit(1)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 6: check applied zooms")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--no-frames", action="store_true", help="skip frames/png/OCR")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), frames=not a.no_frames)


if __name__ == "__main__":
    main()
