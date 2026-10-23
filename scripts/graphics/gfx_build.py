"""Stages 7–8: graphics items -> one HTML composition per item + graphics/comps.json. READ-ONLY on the project.

    python -X utf8 scripts/graphics/gfx_build.py --config config.json [--spec graphics/items.json]

Spec (the approved illustrations_proposal.md / text_proposal.md; format: references/graphics.md, «items.json»):
  [{id, type: hook|plate|card|split|chapter|number, start, end, text, accent?, position?,
    at?, kicker?, caption?, n?, sfx?}]  — times in timeline seconds (stage 3 maps).
Hard rules checked here (refused with the list of problems, nothing written): unique ids [A-Za-z0-9_-]; the item
lies in ONE layout (layout/layout.json, S or F); card only on S, split only on F; positions allowed for the layout
(never bottom-right = the circle); orange (accent) not near the face (F: position wall); durations (plate 2–5 s,
≥ 0.3 s per word, ≤ 6 words; card/split/number ≥ 2.5 s, ≤ 15 s; chapter 2.5 s); accent must be in the text;
items do not overlap each other (one graphics track); plates/cards/numbers do not overlap focus zooms
(stage6/zooms.json). The real geometry (bbox of what is drawn) is checked after the render (render.py ->
bbox_problems). Output: <work_dir>/graphics/html/<id>.html, <work_dir>/graphics/comps.json (merged by id).
"""
from __future__ import annotations

import argparse
import hashlib
import html as H
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

HTML_DIR = Path(__file__).resolve().parent / "html"
TYPES = ("hook", "plate", "card", "split", "chapter", "number")
POSITIONS = ("top-left", "top-right", "wall", "bottom-left", "left")
ALLOWED = {"S": {"top-left", "top-right", "bottom-left"}, "F": {"top-left", "bottom-left", "wall", "left"}}
DEFAULT_POS = {"S": {"hook": "top-left", "plate": "top-left", "card": "top-right", "chapter": "top-left",
                     "number": "top-right"},
               "F": {"hook": "left", "plate": "top-left", "split": "left", "chapter": "left", "number": "left"}}
ONLY_LAYOUT = {"card": "S", "split": "F"}
NEAR_FACE = {"wall"}                     # F positions next to the head: no orange there
IN, OUT, DIST = 0.25, 0.2, 20            # anim.js defaults: appear 250 ms, slide 20 px, disappear 200 ms
PANEL = 0.4                              # split / chapter: slide 400 ms
STAGGER = 0.35                           # default gap between lines when `at` is not given
ZOOM_CHECK = {"plate", "card", "number"}  # STAGE_7/8: not at the same time as a focus zoom
HEAD = ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<link rel="stylesheet" href="{css}"><link rel="stylesheet" href="{gfx}">'
        '<script src="{anim}"></script><script src="{icons}"></script>')


def lines_of(item) -> list[str]:
    t = item.get("text")
    return [t] if isinstance(t, str) else [str(x) for x in (t or [])]


def words(lines) -> int:
    return sum(len(re.findall(r"\w+", x)) for x in lines)


def accented(text: str, accent: str | None) -> str:
    """Escaped text with the first occurrence of accent in orange (one key word)."""
    if not accent:
        return H.escape(text)
    i = text.lower().find(accent.lower())
    if i < 0:
        return H.escape(text)
    return (H.escape(text[:i]) + f'<span class="or">{H.escape(text[i:i + len(accent)])}</span>'
            + H.escape(text[i + len(accent):]))


def anim(tin, tout, fx="slide-left", dur=IN, odur=OUT, dist=DIST, ofx=None) -> str:
    a = f'data-in="{tin:.3f}" data-out="{tout:.3f}" data-fx="{fx}" data-dur="{dur}" data-odur="{odur}" data-dist="{dist}"'
    return a + (f' data-ofx="{ofx}"' if ofx else "")


# ---------- validation ----------
def validate(cfg, items: list[dict]) -> tuple[list[dict], list[str]]:
    """-> (normalised items, problems)."""
    rows = common.read_layout(cfg)
    fps = cfg.fps
    frame = 1.0 / fps
    zj = cfg.work_dir / "stage6" / "zooms.json"
    focus = json.loads(zj.read_text(encoding="utf-8")).get("focus", []) if zj.is_file() else []
    errs, out, seen = [], [], set()
    for it in items:
        cid = str(it.get("id", ""))
        tag = f"{cid or '?'} ({it.get('type')})"
        if not re.fullmatch(r"[A-Za-z0-9_-]+", cid):
            errs.append(f"{tag}: id must be [A-Za-z0-9_-]+ (it names the MOV file)")
            continue
        if cid in seen:
            errs.append(f"{tag}: duplicate id")
        seen.add(cid)
        ty = it.get("type")
        if ty not in TYPES:
            errs.append(f"{tag}: type must be one of {TYPES}")
            continue
        a, b = common.snap(float(it["start"]), fps), common.snap(float(it["end"]), fps)
        dur = (b - a) / 1e6
        if dur <= 0:
            errs.append(f"{tag}: end <= start")
            continue
        lines = lines_of(it)
        if not lines or not all(x.strip() for x in lines):
            errs.append(f"{tag}: empty text")
            continue
        lay = common.layout_of(rows, a / 1e6, b / 1e6)
        if len(lay) != 1:
            errs.append(f"{tag}: {a / 1e6:.2f}–{b / 1e6:.2f} crosses S/F ({sorted(lay)}) — split the item at the switch")
            continue
        lay = lay.pop()
        if ty in ONLY_LAYOUT and ONLY_LAYOUT[ty] != lay:
            errs.append(f"{tag}: {ty} only on {ONLY_LAYOUT[ty]} (here {lay}): "
                        + ("on the camera use split" if ty == "card" else "split needs the full-screen camera F"))
            continue
        pos = it.get("position") or DEFAULT_POS[lay].get(ty)
        if pos == "bottom-right" or (pos and "bottom-right" in pos):
            errs.append(f"{tag}: bottom-right is the camera circle (кружок) zone — nothing goes there")
            continue
        if pos not in POSITIONS or pos not in ALLOWED[lay]:
            errs.append(f"{tag}: position {pos!r} not allowed on {lay} (allowed: {sorted(ALLOWED[lay])})")
            continue
        if ty == "split" and pos != "left":
            errs.append(f"{tag}: split is always the left half (position left)")
            continue
        acc = it.get("accent")
        if acc and not any(acc.lower() in x.lower() for x in lines):
            errs.append(f"{tag}: accent {acc!r} is not in the text")
        orange = bool(acc) or ty in ("number", "chapter", "split")
        if lay == "F" and pos in NEAR_FACE and orange:
            errs.append(f"{tag}: orange next to the face (лицо) on the camera (position {pos}) — move it to "
                        "top-left / bottom-left / left or drop the accent")
        cap = it.get("caption")
        caps = [cap] if isinstance(cap, str) else list(cap or [])
        n_words = words(lines) + words(caps)
        if ty == "plate":
            if words(lines) > 6:
                errs.append(f"{tag}: {words(lines)} words > 6 (key phrase ≤ 6 words)")
            lo = max(2.0, 0.3 * n_words)
            if dur < lo - frame / 2:
                errs.append(f"{tag}: on screen {dur:.2f} s < {lo:.1f} s (≥ 2 s and ≥ 0.3 s per word)")
            if dur > 5.0 + frame / 2:
                errs.append(f"{tag}: on screen {dur:.2f} s > 5 s")
        elif ty in ("card", "split", "number"):
            lo = max(2.5, 0.3 * n_words)
            if dur < lo - frame / 2:
                errs.append(f"{tag}: {dur:.2f} s < {lo:.1f} s (≥ 2.5 s and ≥ 0.3 s per word)")
            if dur > 15.0 + frame / 2:
                errs.append(f"{tag}: {dur:.2f} s > 15 s — split it")
            if ty == "number" and words(caps) > 5:
                errs.append(f"{tag}: caption {words(caps)} words > 5")
        elif ty == "chapter":
            if abs(dur - 2.5) > frame:
                errs.append(f"{tag}: chapter card is 2.5 s (here {dur:.2f} s)")
            if words(lines) > 5:
                errs.append(f"{tag}: chapter title {words(lines)} words > 5")
        at = it.get("at")
        if at is not None:
            if len(at) != len(lines):
                errs.append(f"{tag}: `at` needs one time per line ({len(lines)})")
            elif any(not (a / 1e6 - frame <= float(x) <= b / 1e6 - 0.5) for x in at):
                errs.append(f"{tag}: `at` times must lie in [start, end − 0.5 s]")
        if ty in ZOOM_CHECK:
            for z in focus:
                if z["start"] < b / 1e6 and z["end"] > a / 1e6:
                    errs.append(f"{tag}: at the same time as focus zoom {z.get('n')} ({z['start']}–{z['end']}) — "
                                "drop the zoom or move the item")
        out.append(dict(it, id=cid, A=a, B=b, layout=lay, position=pos, lines=lines, caps=caps,
                        panel=ty == "split" or (ty == "number" and lay == "F")))
    return out, errs


def overlap_problems(comps: dict) -> list[str]:
    ss = sorted(comps.items(), key=lambda kv: kv[1]["start"])
    return [f"{p} and {q} overlap ({cp['end']:.3f} > {cq['start']:.3f}): one graphics track — combine them in one "
            "composition or move one" for (p, cp), (q, cq) in zip(ss, ss[1:]) if cp["end"] > cq["start"] + 1e-6]


# ---------- html ----------
def _ins(it, i, default0=0.0):
    """Entry time of line i (s from the composition start)."""
    if it.get("at"):
        return max(0.0, round(float(it["at"][i]) - it["A"] / 1e6, 3))
    return round(default0 + STAGGER * i, 3)


def body(it) -> str:
    ty, pos, D = it["type"], it["position"], (it["B"] - it["A"]) / 1e6
    acc, lines = it.get("accent"), it["lines"]
    tout = round(D - OUT, 3)
    cls = f"pos-{pos}" + (" wall" if pos == "wall" else "")
    if ty == "plate":
        spans = "".join(f'<span class="plate" {anim(round(0.08 * i, 3), tout)}>{accented(x, acc)}</span>'
                        for i, x in enumerate(lines))
        return f'<div class="{cls} phrase stack">{spans}</div>'
    if ty == "hook":
        spans = "".join(f'<span class="plate" {anim(_ins(it, i), tout, "pop" if i == 0 else "slide-left", dist=40)}>'
                        f'{accented(x, acc)}</span>' for i, x in enumerate(lines))
        return f'<div class="{cls} hook stack">{spans}</div>'
    if ty == "card":
        k = it.get("kicker")
        head = f'<span class="plate k" {anim(0.0, tout)}>{H.escape(k)}</span>' if k else ""
        spans = "".join(f'<span class="plate" {anim(_ins(it, i), tout)}>{accented(x, acc)}</span>'
                        for i, x in enumerate(lines))
        return f'<div class="{cls} card vcol">{head}{spans}</div>'
    if ty == "chapter":
        n = f'{int(it.get("n", 0)):02d}' if it.get("n") is not None else ""
        o = round(D - PANEL, 3)
        num = f'<span class="plate num" {anim(0.0, o, dur=PANEL, odur=PANEL, dist=60)}>{n}</span>' if n else ""
        titles = "".join(f'<span class="plate title" {anim(round(0.1 + 0.08 * i, 3), o, dur=PANEL, odur=PANEL, dist=60)}>'
                         f'{accented(x, acc)}</span>' for i, x in enumerate(lines))
        return f'<div class="{cls} chapter stack">{num}{titles}</div>'
    o = round(D - PANEL, 3)
    if ty == "number" and not it["panel"]:
        caps = "".join(f'<span class="plate s" {anim(round(0.3 + 0.08 * i, 3), tout)}>{H.escape(c)}</span>'
                       for i, c in enumerate(it["caps"]))
        return (f'<div class="{cls} card vcol"><div class="num" {anim(0.0, tout, "pop")}>{H.escape(lines[0])}</div>'
                f'{caps}</div>')
    # split (and a number on the camera): left half black, contents on it; the camera moves right (apply_graphics)
    inner_out = round(o - OUT, 3)
    k = it.get("kicker")
    head = f'<div class="kicker" {anim(PANEL, inner_out, "slide-up")}>{H.escape(k)}</div>' if k else ""
    if ty == "number":
        caps = "".join(f'<div style="margin-top:12px" {anim(round(PANEL + 0.3 + 0.08 * i, 3), inner_out)}>'
                       f'<span class="plate s">{H.escape(c)}</span></div>' for i, c in enumerate(it["caps"]))
        content = f'<div class="num" {anim(PANEL, inner_out, "pop", dist=40)}>{H.escape(lines[0])}</div>{caps}'
    else:
        numbered = len(lines) > 1
        content = '<div class="rows">' + "".join(
            f'<div class="row" {anim(max(PANEL, _ins(it, i, PANEL)), inner_out, dist=30)}>'
            + (f'<span class="n">{i + 1:02d}</span>' if numbered else "")
            + f'<span class="t">{accented(x, acc)}</span></div>' for i, x in enumerate(lines)) + "</div>"
    return (f'<div class="panel" {anim(0.0, o, "slide-left", dur=PANEL, odur=PANEL, dist=960)}>'
            f'<div class="{cls} split">{head}{content}</div></div>')


def page(it) -> str:
    head = HEAD.format(css=(HTML_DIR / "base.css").as_uri(), gfx=(HTML_DIR / "gfx.css").as_uri(),
                       anim=(HTML_DIR / "anim.js").as_uri(), icons=(HTML_DIR / "icons.js").as_uri())
    return f"{head}</head><body>\n{body(it)}\n</body></html>\n"


def sfx_events(it) -> list[dict]:
    a, b = it["A"] / 1e6, it["B"] / 1e6
    kind = "chapter" if it["type"] == "chapter" else "in"
    ev = [{"t": round(a, 6), "kind": kind}]
    if it["panel"]:
        ev.append({"t": round(b - PANEL, 6), "kind": "out"})
    return ev


# ---------- geometry after the render ----------
CIRCLE_MARGIN = 12          # px kept free around the camera circle


def template_circle(cfg) -> dict:
    """Camera circle of assets/templates/mask_circle.json (clip + mask config): {cx, cy, r, sx, tx, ty} canvas px."""
    import effects
    tpl = effects.load_template("mask_circle")
    clip, m = tpl["clip"], tpl["material"]["config"]
    sx, tx, ty = float(clip["scale"]["x"]), float(clip["transform"]["x"]), float(clip["transform"]["y"])
    W, H = cfg.width, cfg.height
    return {"cx": W / 2 * (1 + tx) + m["centerX"] * W * sx, "cy": H / 2 * (1 - ty) - m["centerY"] * H * sx,
            "r": m["width"] * W * sx / 2, "sx": sx, "tx": tx, "ty": ty}


def project_circle(cfg, d: dict | None = None) -> dict:
    """The camera circle of the project (stage6/check_zooms.circle_clip: the circle piece's clip transform × scale ×
    mask config), else the template's. Read-only."""
    for sub in ("stage6", "layout", "stage2"):
        p = str(Path(__file__).resolve().parent.parent / sub)
        if p not in sys.path:
            sys.path.insert(1, p)
    import check_zooms
    try:
        c = check_zooms.circle_clip(cfg, d if d is not None else common.read_draft(cfg))
    except (OSError, ValueError, KeyError):
        c = None
    return c or template_circle(cfg)


def bbox_problems(comp: dict, bbox, w: int, h: int, circle: dict | None = None) -> list[str]:
    """Placement rules on the drawn box [x0, y0, x1, y1] (px, union over the frames). circle = {cx, cy, r} of the
    project's camera circle (project_circle); None -> no circle (a video without the camera)."""
    if not bbox:
        return ["nothing visible in the composition"]
    kx, ky = w / 1920, h / 1080
    x0, y0, x1, y1 = bbox
    out = []
    if comp["layout"] == "S" and circle:
        nx, ny = min(max(circle["cx"], x0), x1), min(max(circle["cy"], y0), y1)
        if ((nx - circle["cx"]) ** 2 + (ny - circle["cy"]) ** 2) ** 0.5 < circle["r"] + CIRCLE_MARGIN:
            out.append(f"bbox {bbox} enters the camera circle (зона кружка: centre {circle['cx']:.0f}, "
                       f"{circle['cy']:.0f}, r {circle['r']:.0f} + {CIRCLE_MARGIN})")
    if comp.get("panel"):
        if x1 > w / 2 + 2:
            out.append(f"bbox {bbox}: the split panel is wider than the left half")
        return out
    if x0 < 0.05 * w - 1 or y0 < 0.05 * h - 1 or x1 > 0.95 * w + 1 or y1 > 0.95 * h + 1:
        out.append(f"bbox {bbox} outside 90 % of the frame")
    if comp["layout"] == "S" and comp["position"] == "top-right" and (x0 < 1240 * kx - 2 or x1 > 1860 * kx + 2
                                                                      or y1 > 680 * ky):
        out.append(f"bbox {bbox}: card outside x 1240–1860, y ≤ 680 (ниже — зона кружка)")
    if comp["position"] == "wall" and (x0 < 1250 * kx - 2 or x1 > 1860 * kx + 2 or y0 < 120 * ky - 2 or y1 > 420 * ky + 2):
        out.append(f"bbox {bbox}: outside the wall zone x 1250–1860, y 120–420")
    return out


# ---------- run ----------
def comps_path(cfg) -> Path:
    return cfg.work_dir / "graphics" / "comps.json"


def read_comps(cfg) -> dict:
    p = comps_path(cfg)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def build(cfg, items: list[dict]) -> dict:
    if not items:
        print("no items: nothing to build")
        return {}
    norm, errs = validate(cfg, items)
    comps = read_comps(cfg)
    new = {}
    for it in norm:
        doc = page(it)
        new[it["id"]] = {"start": round(it["A"] / 1e6, 6), "end": round(it["B"] / 1e6, 6),
                         "type": it["type"], "layout": it["layout"], "position": it["position"], "panel": it["panel"],
                         "text": it["lines"], "accent": it.get("accent"), "n": it.get("n"),
                         "sfx": sfx_events(it), "sfx_file": it.get("sfx"),
                         "sha": hashlib.sha1(doc.encode("utf-8")).hexdigest()[:16], "_doc": doc}
    merged = {k: v for k, v in comps.items() if k not in new} | new
    errs += overlap_problems(merged)
    if errs:
        raise SystemExit("графика не собрана:\n  - " + "\n  - ".join(errs))
    hd = cfg.work_dir / "graphics" / "html"
    hd.mkdir(parents=True, exist_ok=True)
    for cid, c in new.items():
        p = hd / f"{cid}.html"
        p.write_text(c.pop("_doc"), encoding="utf-8")
        c["html"] = p.as_posix()
        print(f"  {cid}: {c['type']} {c['layout']} {c['position']} {c['start']:.3f}–{c['end']:.3f} -> {p.name}")
    merged = dict(sorted(merged.items(), key=lambda kv: kv[1]["start"]))
    comps_path(cfg).write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(new)} built, {len(merged)} in {comps_path(cfg)}")
    return merged


def main(argv=None):
    ap = argparse.ArgumentParser(description="stages 7–8: items.json -> html + comps.json")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--spec", help="items (default <work_dir>/graphics/items.json)")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    sp = Path(a.spec) if a.spec else cfg.work_dir / "graphics" / "items.json"
    build(cfg, json.loads(sp.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
