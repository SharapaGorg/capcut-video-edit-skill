"""Stages 7–8: preview a composition over the real frame of the timeline -> png. READ-ONLY on the project.

    python -X utf8 scripts/graphics/preview.py --config config.json --id ID [--t SEC ...]

Background at timeline time t (stage3/timeline_map.json + layout/layout.json): F -> the full-screen camera frame;
S -> the screencast frame + the camera circle (clip and mask of the project's circle, else
assets/templates/mask_circle.json); under a split the camera is moved right as apply_graphics moves it. Foreground =
the HTML at seek(t − start) (Playwright, transparent). Composited with ffmpeg ->
<work_dir>/graphics/preview/<id>_<t>.png; prints the drawn box and the placement problems at that moment.
Default t: 25 %, 50 %, 85 % of the composition. The camera is HLG on iPhone: colours of the camera frame in the
preview are not CapCut's (check placement, font and text here; colour in CapCut).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _sub in ("stage6", "layout", "stage2"):
    sys.path.insert(1, str(Path(__file__).resolve().parent.parent / _sub))
import check_zooms  # noqa: E402
import common  # noqa: E402
import effects  # noqa: E402
import gfx_build  # noqa: E402
import render  # noqa: E402


def map_pieces(cfg) -> list[dict]:
    p = cfg.work_dir / "stage3" / "timeline_map.json"
    if not p.is_file():
        raise SystemExit(f"нет {p}: сначала stage3/build_maps.py (после любой правки структуры — заново)")
    tm = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for t in tm["tracks"]:
        for s in t["segments"]:
            role = s.get("role") or (common.source_role(cfg, s["file"]) if s.get("file") else None)
            if role in ("camera", "screencast"):
                out.append(dict(s, role=role))
    return out


def source_at(pieces, role: str, t_us: int):
    """(file, source seconds) of the first piece of role at timeline t_us, else (None, None)."""
    for s in pieces:
        if s["role"] == role and s["timeline_in_us"] <= t_us < s["timeline_out_us"] and s["source_in_us"] is not None:
            return s["file"], (s["source_in_us"] + (t_us - s["timeline_in_us"]) * float(s.get("speed", 1.0))) / 1e6
    return None, None


def background_plan(cfg, pieces, rows, t: float, circle: dict | None = None, shift: float = 0.0) -> dict:
    """What is under the graphics at t: F -> camera (moved right by `shift` canvas halves for a split);
    S -> screencast + the circle (`circle` = check_zooms.circle_clip of the project, else the template's)."""
    t_us = common.us(t)
    lay = common.layout_of(rows, t, t + 1e-3).pop()
    if lay == "F":
        return {"layout": "F", "base": source_at(pieces, "camera", t_us), "shift": shift, "circle": None}
    return {"layout": "S", "base": source_at(pieces, "screencast", t_us), "shift": 0.0,
            "circle": source_at(pieces, "camera", t_us), "geom": circle or template_circle(cfg)}


def template_circle(cfg) -> dict:
    tpl = effects.load_template("mask_circle")
    clip, m = tpl["clip"], tpl["material"]["config"]
    sx, tx, ty = float(clip["scale"]["x"]), float(clip["transform"]["x"]), float(clip["transform"]["y"])
    W, H = cfg.width, cfg.height
    return {"cx": W / 2 * (1 + tx) + m["centerX"] * W * sx, "cy": H / 2 * (1 - ty) - m["centerY"] * H * sx,
            "r": m["width"] * W * sx / 2, "sx": sx, "tx": tx, "ty": ty}


def compose(cfg, plan: dict, fg: Path, out: Path) -> Path:
    W, H = cfg.width, cfg.height
    inputs, chains = [], []
    f, s = plan["base"]
    if f:
        inputs += ["-ss", f"{max(s, 0):.3f}", "-i", f]
        dx = int(round(plan.get("shift", 0.0) * W / 2))
        chains.append(f"[0:v]setpts=0,scale={W}:{H},format=rgba,pad={W + dx}:{H}:{dx}:0:black,crop={W}:{H}:0:0[b]")
    else:
        inputs += ["-f", "lavfi", "-i", f"color=c=0x202020:s={W}x{H}:d=1"]
        chains.append("[0:v]format=rgba[b]")
    last = "b"
    if plan["circle"] and plan["circle"][0]:
        g = plan["geom"]
        cw, ch = int(round(W * g["sx"])), int(round(H * g["sx"]))
        x0 = int(round(W / 2 * (1 + g["tx"]) - cw / 2))
        y0 = int(round(H / 2 * (1 - g["ty"]) - ch / 2))
        mx, my = g["cx"] - x0, g["cy"] - y0
        cf, cs = plan["circle"]
        inputs += ["-ss", f"{max(cs, 0):.3f}", "-i", cf]
        chains.append(f"[1:v]setpts=0,scale={cw}:{ch},format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                      f"a='if(lte(hypot(X-{mx:.1f},Y-{my:.1f}),{g['r']:.1f}),255,0)'[c]")
        chains.append(f"[b][c]overlay={x0}:{y0}[bc]")
        last = "bc"
    k = len([x for x in inputs if x == "-i"])
    inputs += ["-i", str(fg)]
    chains.append(f"[{k}:v]setpts=0[f]")
    chains.append(f"[{last}][f]overlay=0:0,format=rgb24[o]")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chains), "-map", "[o]",
                    "-frames:v", "1", str(out)], check=True)
    return out


def run(cfg, cid: str, times=None, log=print) -> list[Path]:
    comps = gfx_build.read_comps(cfg)
    if cid not in comps:
        raise SystemExit(f"нет в comps.json: {cid}")
    c = comps[cid]
    D = c["end"] - c["start"]
    ts = [float(x) for x in times] if times else [round(c["start"] + D * k, 3) for k in (0.25, 0.5, 0.85)]
    pieces, rows = map_pieces(cfg), common.read_layout(cfg)
    circle = check_zooms.circle_clip(cfg, common.read_draft(cfg))
    shift = 0.0
    if c.get("panel"):
        import apply_graphics
        shift = apply_graphics.SPLIT_SHIFT
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(f"Playwright не установлен: {render.INSTALL}")
    outs = []
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": render.PAGE_W, "height": render.PAGE_H},
                          device_scale_factor=cfg.width / render.PAGE_W)
        page.goto(Path(c["html"]).as_uri())
        page.evaluate("document.fonts.ready.then(() => true)")
        for t in ts:
            page.evaluate(f"seek({t - c['start']})")
            fg = Path(tmp) / f"fg_{t}.png"
            fg.write_bytes(page.screenshot(omit_background=True, type="png",
                                           clip={"x": 0, "y": 0, "width": render.PAGE_W, "height": render.PAGE_H}))
            bb = page.evaluate("visibleBox()")
            box = [int(round(v * cfg.width / render.PAGE_W)) for v in bb] if bb else None
            out = cfg.work_dir / "graphics" / "preview" / f"{cid}_{t:.2f}.png"
            compose(cfg, background_plan(cfg, pieces, rows, t, circle, shift), fg, out)
            probs = gfx_build.bbox_problems(c, box, cfg.width, cfg.height) if box else []
            log(f"  {cid} t={t:.2f}: bbox {box} -> {out}" + (f"  PROBLEMS: {probs}" if probs else ""))
            outs.append(out)
        b.close()
    return outs


def main(argv=None):
    ap = argparse.ArgumentParser(description="stages 7–8: composition over the real frame -> png")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--id", required=True)
    ap.add_argument("--t", nargs="+", type=float, help="timeline seconds (default 25/50/85 % of the composition)")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.id, a.t)


if __name__ == "__main__":
    main()
