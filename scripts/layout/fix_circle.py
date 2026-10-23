"""Camera circle check/fix (STAGE_LAYOUT.md A2) on the circle compound (cfg.compounds.circle).

    python -X utf8 scripts/layout/fix_circle.py --config config.json [--dry] [--keep-geometry] [--center-x CX]

Every nested camera piece: exactly one mask, type "mask" with an existing Cache/effect path (else replaced by a
fresh assets/templates/mask_circle.json clone — a dead mask is silently ignored by CapCut); mask config and clip
scale/transform = the template (--keep-geometry: leave them). --center-x CX: move the face inside the circle
(mask centerX = CX, clip transform.x shifted so the circle stays where it is). The circle compound segment
gets Adjust (Temp -18 / Sat 10, adjust_circle) if it has none.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stage2"))
import common  # noqa: E402
import effects  # noqa: E402
import make_compound as mc  # noqa: E402
from common import index  # noqa: E402


def _ok(m) -> bool:
    return m.get("type") == "mask" and m.get("category") == "video" and Path(m.get("path") or "").is_dir()


def fix(cfg, draft: dict, keep_geometry=False, center_x=None, cache_root=None) -> list[str]:
    nid = (cfg.compounds or {}).get("circle")
    if not nid:
        raise SystemExit("cfg.compounds.circle is empty: run stage2/assemble.py first")
    container, _t, outer, dm = mc.find(draft, nid)
    nd = dm["draft"]
    tpl = effects.load_template("mask_circle")
    log = []
    replaced = shifted = 0
    for s in nd["tracks"][-1]["segments"]:
        jx = index(nd["materials"])
        masks = [e for e in s.get("extra_material_refs") or [] if jx.get(e, ("",))[0] == "common_mask"]
        if len(masks) != 1 or not _ok(jx[masks[0]][1]):
            old_cfg = jx[masks[0]][1].get("config") if masks else None
            s["extra_material_refs"] = [e for e in s["extra_material_refs"] if e not in masks]
            used = {e for x in nd["tracks"][-1]["segments"] for e in x.get("extra_material_refs") or []}
            nd["materials"]["common_mask"] = [m for m in nd["materials"].get("common_mask", [])
                                             if m["id"] not in masks or m["id"] in used]
            mid = effects.make("mask_circle", nd, cache_root=cache_root)
            if keep_geometry and old_cfg:
                index(nd["materials"])[mid][1]["config"] = copy.deepcopy(old_cfg)
            effects.attach(s, mid)
            replaced += 1
        jx = index(nd["materials"])
        m = next(jx[e][1] for e in s["extra_material_refs"] if jx[e][0] == "common_mask")
        if not keep_geometry:
            m["config"] = copy.deepcopy(tpl["material"]["config"])
            s["clip"] = copy.deepcopy(tpl["clip"])
        s["enable_video_mask"] = True
        s["volume"] = 0.0
        if center_x is not None:
            old = m["config"]["centerX"]
            src_w = index(nd["materials"])[s["material_id"]][1].get("width") or cfg.width
            dx = (center_x - old) * src_w * s["clip"]["scale"]["x"] / (cfg.width / 2)  # transform.x: 1.0 = half canvas
            m["config"]["centerX"] = center_x
            s["clip"]["transform"]["x"] = round(s["clip"]["transform"]["x"] - dx, 4)
            shifted += 1
    log.append(f"pieces {len(nd['tracks'][-1]['segments'])}, masks replaced {replaced}, centre moved {shifted}")
    ix = index(container["materials"])
    have = {ix[e][1].get("type") for e in outer["extra_material_refs"] if e in ix and ix[e][0] == "effects"}
    if not {"temperature", "saturation"} <= have:
        for mid in effects.make_all("adjust_circle", container, cache_root=cache_root):
            effects.attach(outer, mid)
        log.append("Adjust (Temp -18 / Sat 10) added to the circle compound")
    outer.update(enable_adjust=True, enable_hsl=True, volume=0.0)
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(description="fix the camera circle masks / geometry / Adjust")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--keep-geometry", action="store_true")
    ap.add_argument("--center-x", type=float)
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    if not (cfg.compounds or {}).get("circle"):
        print("no circle compound yet (cfg.compounds.circle empty): run stage2/assemble.py first; nothing to fix")
        return
    d = common.read_draft(cfg)
    try:
        for line in fix(cfg, d, a.keep_geometry, a.center_x):
            print(line)
    except effects.EffectCacheMissing as e:
        raise SystemExit(str(e))
    errs = common.check_refs(d)
    print("VALIDATION:", "OK" if not errs else "FAIL", *errs, sep="\n  ")
    if errs:
        raise SystemExit(1)
    if a.dry:
        print("dry run, not written")
        return
    nid = cfg.compounds["circle"]
    w = mc.refresh(cfg, d, nid)
    common.write_draft(cfg, d, "fix-circle", dry=False, subdrafts={nid: w} if w else None)
    print("written")


if __name__ == "__main__":
    main()
