"""Stage 6: focus zooms on the screencast (S parts) + SFX, push-ins / punch-ins on the full-screen camera (F).

    python -X utf8 scripts/stage6/apply_zooms.py --config config.json --spec stage6/zooms_spec.json [--dry]

Spec (the approved zoom_proposal.md), timeline seconds:
  {"focus":   [{n, start, end, center: [x, y] canvas px of the element (find_focus.py), scale 1.5–2.0,
                phrase, what, conf, words}],
   "pushin":  [{n, t, phrase}],        # F: x1.0 -> x1.1 over 2.5 s, held to the end of the camera piece, no SFX
   "punchin": [{n, t}],                # F: clip scale x1.15 on the camera piece at t (from jumpcuts), no animation
   "sfx":     ["a.wav", "b.wav"]}      # optional: SFX files in cfg.sfx_dir to alternate (default: first 3 there)
Focus: only where layout.json is S over the whole zoom, >= 2 s, >= 8 s apart, screencast at speed 1, inside ONE
top-level segment of the screencast track. The keys go on the screencast LEAF: a raw top-level segment, or the
segment(s) inside the screencast compound (any depth; rules.md: further cutting inside nested drafts) — the leaves
under the zoom are split at the zoom edges (CapCut-style) inside their nested draft, the outer compound stays whole
(no nested draft copies), the subdraft folder is refreshed and an audio pre-render of the compound (if any)
cleared; in 350 ms, out 300 ms: effects.zoom_keyframes on one leaf; a zoom over several leaves (cuts inside the
compound) gets the same curve split over them (effects.alpha_keyframes). SFX on every focus entry: start = zoom start, files
alternate (never the same twice in a row), level = voice − 12 LU (effects.voice_lufs over ±5 s around the zoom,
effects.sfx_volume). cfg.sfx_dir unset -> stop and ask for it. Writes both drafts (+ subdrafts touched by zooms)
and stage6/zooms.json (applied zooms, for stages 7–8). A zoom that is already there (keys on the piece / an SFX at
its start) -> refused.
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
from common import by_start, seg_end, source_role  # noqa: E402

IN_S, OUT_S = 0.35, 0.30
FOCUS_MIN, FOCUS_GAP = 2.0, 8.0
PUSH_RAMP, PUSH_SCALE, PUSH_MIN_LEFT, PUSH_EVERY = 2.5, 1.1, 3.0, 120.0
PUNCH_SCALE = 1.15
VOICE_WIN = 5.0
SFX_TRACK = effects.SFX_TRACK


def focus_pos(center, s: float, base: float, w: int, h: int) -> tuple[float, float]:
    """clip.transform at full zoom so that the element is at the canvas centre; clamped so no edge shows."""
    ex = (center[0] - w / 2) / (w / 2)
    ey = (h / 2 - center[1]) / (h / 2)
    k = s * base
    lim = max(k - 1, 0.0)
    return (round(max(-lim, min(lim, -ex * k)), 6), round(max(-lim, min(lim, -ey * k)), 6))


def sfx_files(cfg, spec: dict) -> list[Path]:
    return effects.sfx_files(cfg, spec.get("sfx"))


def screencast_track(cfg, d: dict) -> dict:
    nid = (cfg.compounds or {}).get("screencast")
    if nid:
        try:
            container, t, _s, _dm = mc.find(d, nid)
            if container is d:
                return t
        except KeyError:
            pass
    from collections import Counter
    c = Counter(p["track"] for p in common.flatten(cfg, d, ("screencast",)))
    if not c:
        raise SystemExit("на таймлайне нет скринкаста")
    return d["tracks"][c.most_common(1)[0][0]]


def cams_on_track(cfg, d: dict, track: dict, host: dict) -> bool:
    """Camera leaves under the top-level segment `host` (inside its compound) — a zoom on it would scale them too."""
    ti = d["tracks"].index(track)
    a, b = host["target_timerange"]["start"], seg_end(host)
    return any(p["track"] == ti and p["start"] < b and p["end"] > a and p["compound"]
               for p in common.flatten(cfg, d, ("camera",)))


def camera_leaf(cfg, d: dict, t_us: int):
    """(segment, its start on the timeline, nested draft id | None) of the full-screen camera piece at t_us:
    a raw top-level camera segment or a leaf inside a compound (speed 1)."""
    for tr in d["tracks"]:
        if tr["type"] != "video":
            continue
        for s in tr["segments"]:
            a = s["target_timerange"]["start"]
            if not a <= t_us < seg_end(s):
                continue
            ix = common.index(d["materials"])
            dix = common._drafts_ix(d, {})
            dm = next((dix[e] for e in s.get("extra_material_refs") or [] if e in dix), None)
            if dm is None:
                if s.get("material_id") in ix and not common.has_mask(s, ix) and \
                        source_role(cfg, common.mat_path(ix, s)) == "camera":
                    return s, a, None
                continue
            nd = dm["draft"]
            jx = common.index(nd.get("materials", {}))
            off = a - (s.get("source_timerange") or {}).get("start", 0)
            for nt in nd.get("tracks", []):
                for ns in nt["segments"]:
                    na = off + ns["target_timerange"]["start"]
                    if na <= t_us < off + seg_end(ns) and ns.get("material_id") in jx and not common.has_mask(ns, jx) \
                            and source_role(cfg, jx[ns["material_id"]][1].get("path", "")) == "camera":
                        return ns, na, nd["id"]
    return None


def zoom_target(d: dict, track: dict, host: dict, A: int, B: int):
    """Where the focus keys go for [A, B) (top timeline us) on the top-level segment `host` of `track`: descend
    through compounds to the video leaves showing that window (one track, raw segments, back to back). ->
    (container draft, its track, [leaves], x, y in container time, [drafts entries on the way]) or a str error."""
    container, tr, seg, x, y, chain = d, track, host, A, B, []
    dix = common._drafts_ix(d, {})
    while True:
        dm = next((dix[e] for e in seg.get("extra_material_refs") or [] if e in dix), None)
        if dm is None or not isinstance(dm.get("draft"), dict):
            if not (seg["target_timerange"]["start"] <= x and y <= seg_end(seg)):
                return f"the screencast piece {seg['id']} does not cover the whole zoom (a cut inside the zoom)"
            return container, tr, [seg], x, y, chain
        sp = float(seg.get("speed", 1.0))
        src0 = (seg.get("source_timerange") or {}).get("start", 0)
        a = seg["target_timerange"]["start"]
        x, y = src0 + int(round((x - a) * sp)), src0 + int(round((y - a) * sp))
        nd = dm["draft"]
        hits = [(t, s) for t in nd.get("tracks", []) if t.get("type") == "video" for s in t.get("segments", [])
                if s["target_timerange"]["start"] < y and seg_end(s) > x]
        chain.append(dm)
        dix = common._drafts_ix(nd, dix)
        container = nd
        if len(hits) == 1:
            tr, seg = hits[0]
            continue
        if not hits:
            return "no video inside the compound under the zoom"
        if len({id(t) for t, _s in hits}) != 1:
            return "video pieces on several tracks inside the compound under the zoom (move the zoom)"
        leaves = by_start([s for _t, s in hits])
        if any(e in dix and isinstance(dix[e].get("draft"), dict) for s in leaves for e in s.get("extra_material_refs") or []):
            return "a compound among several pieces under the zoom (move the zoom)"
        if leaves[0]["target_timerange"]["start"] > x or seg_end(leaves[-1]) < y or \
                any(q["target_timerange"]["start"] - seg_end(p) > 1 for p, q in zip(leaves, leaves[1:])):
            return "a hole inside the compound under the zoom"
        return container, hits[0][0], leaves, x, y, chain


def _alpha(curve: list[tuple[float, float]], t: float) -> float:
    """Piecewise-linear zoom amount 0..1 of the curve [(t, alpha)] at t (clamped at the ends)."""
    if t <= curve[0][0]:
        return curve[0][1]
    for (t0, a0), (t1, a1) in zip(curve, curve[1:]):
        if t <= t1:
            return a0 + (a1 - a0) * (t - t0) / (t1 - t0) if t1 > t0 else a1
    return curve[-1][1]


def merge_zooms(path: Path, out: dict) -> dict:
    """zooms.json = the previous runs + this one, merged by (type, n) (a later run replaces the same n)."""
    old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    res = dict(old, **{k: v for k, v in out.items() if k not in ("focus", "pushin", "punchin")})
    for k in ("focus", "pushin", "punchin"):
        by = {z["n"]: z for z in old.get(k, [])}
        by.update({z["n"]: z for z in out.get(k, [])})
        res[k] = sorted(by.values(), key=lambda z: z["start"])
    if out.get("sfx_track_id") is None and old.get("sfx_track_id"):
        res["sfx_track_id"] = old["sfx_track_id"]
    return res


def run(cfg, spec: dict, dry: bool, guard_seconds: float = 5) -> dict:
    focus = sorted(spec.get("focus") or [], key=lambda z: z["start"])
    pushin, punchin = spec.get("pushin") or [], spec.get("punchin") or []
    out = {"note": "stage 6. start/end = timeline s; center = canvas px of the element; scale = peak scale; "
                   "position = clip.transform at the peak; sfx.volume = CapCut gain (voice - 12 LU)",
           "focus": [], "pushin": [], "punchin": []}
    if not (focus or pushin or punchin):
        print("no zooms in the spec: nothing to do")
        return out
    files = sfx_files(cfg, spec) if focus else []
    rows = common.read_layout(cfg)
    if not rows:
        raise SystemExit("нет layout/layout.json (этап LAYOUT): зумы фокуса только в S, наезды только в F")
    d = common.read_draft(cfg)
    fps = cfg.fps
    frame = 1.0 / fps
    errs = []
    for z in focus:
        z["A"], z["B"] = common.snap(z["start"], fps), common.snap(z["end"], fps)
        if (z["B"] - z["A"]) / 1e6 < FOCUS_MIN - 1e-6:
            errs.append(f"focus {z['n']}: shorter than {FOCUS_MIN:.0f} s")
        lay = common.layout_of(rows, z["A"] / 1e6, z["B"] / 1e6)
        if lay != {"S"}:
            errs.append(f"focus {z['n']}: layout {sorted(lay)} — focus zooms only in S")
    for p, q in zip(focus, focus[1:]):
        if (q["A"] - p["B"]) / 1e6 < FOCUS_GAP - 1e-6:
            errs.append(f"focus {p['n']} -> {q['n']}: {(q['A'] - p['B']) / 1e6:.2f} s apart < {FOCUS_GAP:.0f} s")
    sc_pieces = common.flatten(cfg, d, ("screencast",))
    track = screencast_track(cfg, d) if focus else None
    for z in focus:
        over = [p for p in sc_pieces if p["start"] < z["B"] and p["end"] > z["A"]]
        if not over:
            errs.append(f"focus {z['n']}: no screencast at {z['start']}–{z['end']}")
        if any(abs(p["speed"] - 1.0) > 1e-6 for p in over):
            errs.append(f"focus {z['n']}: over a sped screencast piece")
        host = [s for s in track["segments"] if s["target_timerange"]["start"] < z["B"] and seg_end(s) > z["A"]]
        if len(host) != 1:
            errs.append(f"focus {z['n']}: crosses {len(host)} segments of the screencast track (one is needed)")
        elif cams_on_track(cfg, d, track, host[0]):
            errs.append(f"focus {z['n']}: the screencast segment also holds the camera (compound with the circle / "
                        "full-screen camera inside) — the zoom would scale the camera too; split the compound so the "
                        "screencast is alone on its track")
        else:
            tg = zoom_target(d, track, host[0], z["A"], z["B"])
            if isinstance(tg, str):
                errs.append(f"focus {z['n']}: {tg}")
            elif any(c.get("property_type") in effects.ZOOM_PROPS for lf in tg[2] for c in lf.get("common_keyframes") or []):
                errs.append(f"focus {z['n']}: the segment already has zoom keys (applied before?)")
    sfx_track = next((t for t in d["tracks"] if t["type"] == "audio" and t.get("name") == SFX_TRACK), None)
    for z in focus:
        if sfx_track and any(abs(s["target_timerange"]["start"] - z["A"]) <= 1e6 / fps for s in sfx_track["segments"]):
            errs.append(f"focus {z['n']}: an SFX is already at {z['start']} (applied before?)")
    if errs:
        raise SystemExit("зумы не применены:\n  - " + "\n  - ".join(errs))

    # ---- focus: split the screencast leaf (inside its compound) + keys ----
    touched, stale = set(), []
    for z in focus:
        host = next(s for s in track["segments"] if s["target_timerange"]["start"] < z["B"] and seg_end(s) > z["A"])
        container, tr, _leaves, x, y, chain = zoom_target(d, track, host, z["A"], z["B"])
        common.split_at(container, tr, [x, y])
        parts = by_start([s for s in tr["segments"] if x <= s["target_timerange"]["start"] < y])
        piece = parts[0]
        for dm in chain:
            touched.add(dm["draft"]["id"])
            r = mc.stale_prerender(cfg, dm)
            if r and r not in stale:
                stale.append(r)
        D = (y - x) / 1e6
        base = float(((piece.get("clip") or {}).get("scale") or {}).get("x", 1.0))
        px, py = focus_pos(z["center"], z["scale"], base, cfg.width, cfg.height)
        if len(parts) == 1:
            effects.zoom_keyframes(piece, 0.0, D - OUT_S - frame, D - frame, z["scale"], cx=px, cy=py, ramp_in=IN_S)
        else:   # cuts inside the compound under the zoom: the same curve over the pieces
            curve = [(0.0, 0.0), (IN_S, 1.0), (D - OUT_S - frame, 1.0), (D - frame, 0.0)]
            for s in parts:
                o, L = (s["target_timerange"]["start"] - x) / 1e6, s["target_timerange"]["duration"] / 1e6
                ts = sorted({0.0, L} | {round(t - o, 6) for t, _a in curve if 0 < t - o < L})
                effects.alpha_keyframes(s, [(t, _alpha(curve, o + t)) for t in ts], z["scale"], cx=px, cy=py)
        z.update(segment_id=piece["id"], segment_ids=[s["id"] for s in parts], position=[px, py],
                 peak=[round(z["A"] / 1e6 + IN_S, 6), round(z["B"] / 1e6 - OUT_S - frame, 6)])
    # ---- SFX ----
    if focus:
        if sfx_track is None:
            sfx_track = effects.new_sfx_track(d)
        prev = None
        lens = {}
        for i, z in enumerate(focus):
            f = files[i % len(files)]
            if f == prev and len(files) > 1:
                f = files[(i + 1) % len(files)]
            prev = f
            if f not in lens:
                lens[f] = int(round(len(effects.pcm(f)) * 1e6 / effects.SR))
            a = max(0, z["A"] - common.us(VOICE_WIN))
            b = min(d["duration"], z["B"] + common.us(VOICE_WIN))
            vlu = effects.voice_lufs(cfg, d, a, b)
            if vlu is None:
                raise SystemExit(f"focus {z['n']}: нет голоса в {a / 1e6:.1f}–{b / 1e6:.1f} с — уровень SFX не посчитать")
            lv = effects.sfx_volume(vlu, f)
            if lv["capped"]:
                print(f"  warning: SFX {f.name} too quiet, volume capped at +20 dB")
            dur = lens[f]
            nxt = min((s["target_timerange"]["start"] for s in sfx_track["segments"] if s["target_timerange"]["start"] > z["A"]),
                      default=None)
            if nxt is not None and z["A"] + dur > nxt:
                dur = nxt - z["A"]
            sid = effects.sfx_segment(d, sfx_track, f.as_posix(), z["A"], dur, lv["volume"])
            mat = common.index(d["materials"])[next(s for s in sfx_track["segments"] if s["id"] == sid)["material_id"]][1]
            mat["duration"] = lens[f]
            z["sfx"] = {"file": f.name, "start": z["A"] / 1e6, "volume": lv["volume"], "volume_db": lv["volume_db"],
                        "voice_lufs": round(vlu, 2), "sfx_peak_lufs": lv["sfx_m_max"], "segment_id": sid}
        sfx_track["segments"] = by_start(sfx_track["segments"])
    # ---- push-in / punch-in on the full-screen camera ----
    last_push = None
    for p in sorted(pushin, key=lambda p: p["t"]):
        t = common.snap(p["t"], fps)
        if common.layout_of(rows, t / 1e6, t / 1e6 + PUSH_MIN_LEFT) != {"F"}:
            errs.append(f"pushin {p['n']}: not in F")
            continue
        hit = camera_leaf(cfg, d, t)
        if hit is None:
            errs.append(f"pushin {p['n']}: no full-screen camera piece at {p['t']}")
            continue
        leaf, la, nid = hit
        left = (la + leaf["target_timerange"]["duration"] - t) / 1e6
        if left < PUSH_MIN_LEFT:
            errs.append(f"pushin {p['n']}: {left:.2f} s to the end of the piece < {PUSH_MIN_LEFT:.0f}")
            continue
        if leaf.get("common_keyframes"):
            errs.append(f"pushin {p['n']}: the piece already has keys")
            continue
        if last_push is not None and (t - last_push) / 1e6 < PUSH_EVERY:
            errs.append(f"pushin {p['n']}: more often than once per {PUSH_EVERY / 60:.0f} min")
        last_push = t
        effects.zoom_keyframes(leaf, (t - la) / 1e6, None, None, PUSH_SCALE, ramp_in=PUSH_RAMP)
        if nid:
            touched.add(nid)
        out["pushin"].append({"n": p["n"], "type": "pushin", "start": t / 1e6, "end": (la + leaf["target_timerange"]["duration"]) / 1e6,
                              "ramp_s": PUSH_RAMP, "scale": PUSH_SCALE, "segment_id": leaf["id"], "compound": nid,
                              "phrase": p.get("phrase", "")})
    for p in punchin:
        t = common.snap(p["t"], fps)
        hit = camera_leaf(cfg, d, t)
        if hit is None or common.layout_of(rows, t / 1e6, t / 1e6 + frame) != {"F"}:
            errs.append(f"punchin {p['n']}: no full-screen camera piece (F) at {p['t']}")
            continue
        leaf, la, nid = hit
        leaf.setdefault("clip", {}).setdefault("scale", {})
        leaf["clip"]["scale"] = {"x": PUNCH_SCALE, "y": PUNCH_SCALE}
        if nid:
            touched.add(nid)
        out["punchin"].append({"n": p["n"], "type": "punchin", "start": la / 1e6, "scale": PUNCH_SCALE,
                               "segment_id": leaf["id"], "compound": nid})
    errs += common.check_refs(d) + common.draft_overlaps(d)
    try:
        errs += [f"keys outside the segment {sid}" for sid, s in common.all_segments(d).items()
                 if not effects.keyframes_inside(s)]
    except ValueError as e:   # duplicate ids: the check (and zooms.json segment ids) would be ambiguous
        errs.append(str(e))
    out["focus"] = [{k: v for k, v in z.items() if k not in ("A", "B")} | {"type": "focus", "start_us": z["A"],
                                                                           "end_us": z["B"], "in_ms": int(IN_S * 1000),
                                                                           "out_ms": int(OUT_S * 1000)} for z in focus]
    for z in out["focus"]:
        print(f"  focus {z['n']}: {z['start']:.2f}–{z['end']:.2f} x{z['scale']} pos {z['position']} SFX {z['sfx']['file']} "
              f"vol {z['sfx']['volume']} ({z['sfx']['volume_db']:+.1f} dB, voice {z['sfx']['voice_lufs']} LUFS)")
    print(f"focus {len(out['focus'])}, pushin {len(out['pushin'])}, punchin {len(out['punchin'])}")
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)
    if dry:
        print("dry run, not written")
        return out
    subs = mc.subdrafts(cfg, d, touched)
    out["backup"] = str(common.write_draft(cfg, d, "stage6-zooms", dry=False, guard_seconds=guard_seconds,
                                           subdrafts=subs))
    for sub, ap in stale:
        mc.clear_prerender(cfg, sub, ap)
        print(f"  cleared audio pre-render {ap}")
    out["sfx_track_id"] = sfx_track["id"] if focus else None
    p = cfg.work_dir / "stage6" / "zooms.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(merge_zooms(p, out), ensure_ascii=False, indent=1), encoding="utf-8")
    print("written:", p)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 6: focus zooms + SFX, push-ins/punch-ins")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--spec", help="approved zooms (default <work_dir>/stage6/zooms_spec.json)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    sp = Path(a.spec) if a.spec else cfg.work_dir / "stage6" / "zooms_spec.json"
    run(cfg, json.loads(sp.read_text(encoding="utf-8")), a.dry)


if __name__ == "__main__":
    main()
