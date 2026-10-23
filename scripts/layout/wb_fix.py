"""White balance fix: an extra temperature (Adjust) on the camera pieces of one file within source ranges.

    python -X utf8 scripts/layout/wb_fix.py --config config.json --file IMG_0001.MOV --ranges r.json --temp -27 [--dry]

The iPhone auto white balance drifts to yellow on a white screen (STAGE_LAYOUT A2): after the R/B scan of the wall,
put a temperature effect on every camera piece of --file (any depth: circle, full-screen compounds, raw pieces)
whose SOURCE range overlaps --ranges ([[a, b]] seconds of that file, a JSON file or inline "758-806,856-1066").
--temp in CapCut UI units (Adjust → Temp), stored as UI x 0.02, on top of the common Temp −18 (which lives on the
compound segment / Adjustment block). The effect is the temperature of the adjust_circle template; the ids made are
kept in layout/wb_fix.json, so a rerun updates the value instead of adding a second effect.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stage2"))
import common  # noqa: E402
import effects  # noqa: E402
import make_compound as mc  # noqa: E402

UI_SCALE = 0.02


def parse(spec: str) -> list[tuple[float, float]]:
    p = Path(spec)
    if p.is_file():
        return [(a, b) for a, b in common.parse_ranges(json.loads(p.read_text(encoding="utf-8")))]
    out = []
    for part in spec.split(","):
        a, b = part.strip().split("-")
        out.append((float(a), float(b)))
    return out


def run(cfg, file: str, ranges: list[tuple[float, float]], temp_ui: float, dry: bool, cache_root=None,
        guard_seconds: float = 5) -> dict:
    d = common.read_draft(cfg)
    logp = cfg.work_dir / "layout" / "wb_fix.json"
    log = json.loads(logp.read_text(encoding="utf-8")) if logp.is_file() else {"materials": {}}
    ours = log["materials"]          # material id -> file
    value = round(temp_ui * UI_SCALE, 4)
    name = common.uncensored_name(file).lower()
    touched_nids, n_new, n_upd = set(), 0, 0

    def walk(dr, nid):
        nonlocal n_new, n_upd
        ix = common.index(dr.get("materials", {}))
        for t in dr.get("tracks", []):
            for s in t.get("segments", []):
                if s.get("material_id") not in ix:
                    continue
                m = ix[s["material_id"]][1]
                st = s.get("source_timerange")
                if not st or common.uncensored_name(m.get("path", "")).lower() != name:
                    continue
                if common.source_role(cfg, m.get("path", "")) != "camera":
                    continue
                a, b = st["start"] / 1e6, (st["start"] + st["duration"]) / 1e6
                if not any(a < y and b > x for x, y in ranges):
                    continue
                mine = [e for e in s.get("extra_material_refs") or [] if e in ours and e in ix]
                if mine:
                    ix[mine[0]][1]["value"] = value
                    n_upd += 1
                else:
                    mid = effects.make("adjust_circle", dr, cache_root=cache_root, with_extras=False, value=value)
                    effects.attach(s, mid)
                    s["enable_adjust"] = True
                    ours[mid] = file
                    n_new += 1
                if nid:
                    touched_nids.add(nid)
        for dm in dr.get("materials", {}).get("drafts", []) or []:
            if isinstance(dm.get("draft"), dict):
                walk(dm["draft"], dm["draft"].get("id"))

    walk(d, None)
    errs = common.check_refs(d)
    print(f"{file}: temperature {temp_ui:+g} (value {value}) — new {n_new}, updated {n_upd}; compounds {len(touched_nids)}")
    if not (n_new or n_upd):
        print("no camera piece of this file overlaps the ranges")
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)
    res = {"new": n_new, "updated": n_upd, "value": value}
    if dry or not (n_new or n_upd):
        print("dry run, not written" if dry else "nothing to write")
        return res
    subs = {nid: w for nid in touched_nids if (w := mc.refresh(cfg, d, nid)) is not None}
    common.write_draft(cfg, d, "layout-wb", dry=False, guard_seconds=guard_seconds, subdrafts=subs)
    log.setdefault("runs", []).append({"file": file, "ranges": ranges, "temp_ui": temp_ui, "value": value})
    logp.parent.mkdir(parents=True, exist_ok=True)
    logp.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="extra temperature on camera pieces of one file (white balance drift)")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--file", required=True, help="camera file name, e.g. IMG_0001.MOV")
    ap.add_argument("--ranges", required=True, help='source seconds: JSON file [[a, b]] or "a-b,c-d"')
    ap.add_argument("--temp", type=float, required=True, help="UI units (Adjust → Temp), e.g. -27")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    try:
        run(common.load_config(a.config), a.file, parse(a.ranges), a.temp, a.dry)
    except effects.EffectCacheMissing as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
