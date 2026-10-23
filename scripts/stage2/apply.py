"""Stage 2 apply (references/stages/STAGE_2.md §6): cuts (pause/hesitation/filler/noise) + speedups on all
tracks at once, ripple, no holes.

    python -X utf8 scripts/stage2/apply.py --config config.json [--dry]

Input (<work_dir>): stage2/candidates.json (conf auto) + stage2/approved_ids.json (review items the user approved,
optional), stage1/cuts_applied.json (transcript -> timeline map), transcript/transcript.json.
Segments shorter than 300 ms next to a cut: wordless -> absorbed into the cut, else the cut is shrunk.
Sped pieces: speed k on the segment and its speeds material, source = target x k, voice muted.
Output: stage2/cuts2_applied.json (transcript time + timeline), both draft files, draft_meta_info tm_duration.
--dry: stage2/cuts2_dry.json only.
"""
from __future__ import annotations

import argparse
import bisect
import copy
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
from common import by_start, index, new_id, seg_end  # noqa: E402

MIN_SEG_US = 300_000
MARGIN_US = 80_000
CUT_CATS = ("pause", "hesitation", "filler", "noise", "service")


def run(cfg, dry: bool, guard_seconds: float = 5) -> dict:
    wd = cfg.work_dir
    FRAME_US = 1_000_000 / cfg.fps

    def ceil_f(x):
        return int(math.ceil(x / FRAME_US - 1e-6) * FRAME_US)

    def floor_f(x):
        return int(math.floor(x / FRAME_US + 1e-6) * FRAME_US)

    def round_f(x):
        return int(round(x / FRAME_US) * FRAME_US)

    A = json.loads((wd / "stage1" / "cuts_applied.json").read_text(encoding="utf-8"))
    CUTS1 = sorted((c["start_us"], c["end_us"]) for c in A["cuts"])

    def t1(x):  # transcript us -> timeline (after stage 1) us
        return common.map_through_cuts(x, CUTS1)

    def inv1(x):  # timeline (after stage 1) -> transcript us
        out = x
        for a, b in CUTS1:
            if t1(a) <= x:
                out += b - a
            else:
                break
        return out

    C = json.loads((wd / "stage2" / "candidates.json").read_text(encoding="utf-8"))
    ap = wd / "stage2" / "approved_ids.json"
    approved = set(json.loads(ap.read_text(encoding="utf-8"))) if ap.is_file() else set()
    cuts_src, speed_src = [], []
    for c in C:
        if not (c["conf"] == "auto" or c["id"] in approved):
            continue
        s_us, e_us = int(c["start"] * 1e6), int(c["end"] * 1e6)
        for a, b in CUTS1:  # candidates may touch a stage-1 cut edge
            if a <= s_us < b:
                s_us = b
            if a < e_us <= b:
                e_us = a
        if e_us - s_us < 34_000 or any(a < e_us and b > s_us for a, b in CUTS1):
            continue
        if c["cat"] == "speedup":
            speed_src.append((s_us, e_us, c))
        elif c["cat"] in CUT_CATS:
            cuts_src.append((s_us, e_us, c))
    cuts = sorted((ceil_f(t1(s)), floor_f(t1(e)), c) for s, e, c in cuts_src)
    cuts = [(a, b, c) for a, b, c in cuts if b - a >= FRAME_US - 1]
    merged = []
    for a, b, c in cuts:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
            merged[-1][2].append(c)
        else:
            merged.append([a, b, [c]])
    cuts = merged

    d = common.read_draft(cfg)
    orig = copy.deepcopy(d)
    mats = d["materials"]
    byid = index(mats)
    av = [t for t in d["tracks"] if t["type"] in ("video", "audio")]
    bounds = sorted({x for t in av for s in t["segments"] for x in (s["target_timerange"]["start"], seg_end(s))})
    pre_short = {s["id"] for t in d["tracks"] for s in t["segments"] if s["target_timerange"]["duration"] < MIN_SEG_US}
    gaps0 = {t["id"]: common.gap_count(t) for t in d["tracks"]}

    T = json.loads((wd / "transcript" / "transcript.json").read_text(encoding="utf-8"))
    W = sorted((int(w["start"] * 1e6), int(w["end"] * 1e6)) for s in T["segments"] for w in s["words"])
    WS = [w[0] for w in W]

    def wordless(x, y):
        a, b = inv1(x), inv1(y)
        i = bisect.bisect_left(WS, a)
        return not any(w[0] < b and w[1] > a for w in W[max(0, i - 3): i + 3])

    TB = [sorted({x for s in t["segments"] for x in (s["target_timerange"]["start"], seg_end(s))}) for t in av]

    def fix_short(cuts):
        cuts = [list(x) + [set()] for x in cuts]   # [a, b, cands, shrunk_edges]
        absorbed = shrunk = 0
        for _ in range(50):
            changed = False
            for i, cur in enumerate(cuts):
                for tb in TB:
                    a = cur[0]
                    prev_edge = cuts[i - 1][1] if i > 0 else None
                    pb = [x for x in tb if x < a]
                    edge = max([x for x in [prev_edge, pb[-1] if pb else None] if x is not None], default=None)
                    if edge is not None and 0 < a - edge < MIN_SEG_US and a not in tb:
                        if edge != prev_edge and "a" not in cur[3] and wordless(edge, a):
                            cur[0] = edge
                            absorbed += 1
                        else:
                            cur[0] = ceil_f(edge + MIN_SEG_US)
                            shrunk += 1
                            cur[3].add("a")
                        changed = True
                    b = cur[1]
                    next_edge = cuts[i + 1][0] if i + 1 < len(cuts) else None
                    nb = [x for x in tb if x > b]
                    edge = min([x for x in [next_edge, nb[0] if nb else None] if x is not None], default=None)
                    if edge is not None and 0 < edge - b < MIN_SEG_US and b not in tb:
                        if edge != next_edge and "b" not in cur[3] and wordless(b, edge):
                            cur[1] = edge
                            absorbed += 1
                        else:
                            cur[1] = floor_f(edge - MIN_SEG_US)
                            shrunk += 1
                            cur[3].add("b")
                        changed = True
            cuts = [c for c in cuts if c[1] - c[0] >= FRAME_US - 1]
            m = []
            for c in cuts:
                if m and c[0] <= m[-1][1]:
                    m[-1][1] = max(m[-1][1], c[1])
                    m[-1][2] = m[-1][2] + c[2]
                    m[-1][3] |= c[3]
                else:
                    m.append(c)
            cuts = m
            if not changed:
                break
        else:
            raise SystemExit("min-segment fix did not converge")
        print(f"min-segment fix: absorbed {absorbed}, shrunk {shrunk}")
        return [c[:3] for c in cuts]

    n_before = len(cuts)
    cuts = fix_short(cuts)
    print(f"cuts: {n_before} -> {len(cuts)} after min-segment fix; total {sum(b - a for a, b, _ in cuts) / 1e6:.1f}s")

    speeds = []
    for s, e, c in speed_src:
        a, b = ceil_f(t1(s)), floor_f(t1(e))
        inside = [x for x in cuts if x[0] < b and x[1] > a]
        if not all(a <= x[0] and x[1] <= b for x in inside):
            raise SystemExit(f"cut straddles speedup edge (candidate {c['id']})")
        cuts = [x for x in cuts if x not in inside]
        comp = max(round_f((b - a) / c["factor"]), int(FRAME_US * 10))
        speeds.append((a, b, comp, c))
    speeds.sort(key=lambda x: x[0])

    events = sorted([(a, b, "cut", b - a) for a, b, _ in cuts] + [(a, b, "speed", (b - a) - comp) for a, b, comp, _ in speeds])
    for (a1, b1, _, _), (a2, b2, _, _) in zip(events, events[1:]):
        if b1 > a2:
            raise SystemExit("overlapping ops")

    def new_t(t):
        out = t
        for a, b, _kind, loss in events:
            if t <= a:
                break
            out -= loss if t >= b else loss * (t - a) / (b - a)
        return int(round(out))

    edges = sorted({x for a, b, _, _ in events for x in (a, b)})

    def is_cut(x):
        return any(a <= x < b for a, b, _ in cuts)

    def speed_at(x):
        return next(((a, b, comp) for a, b, comp, _ in speeds if a <= x < b), None)

    applied = []
    removed = split = sped = 0
    for ti, t in enumerate(d["tracks"]):
        new_segs = []
        for s in by_start(t["segments"]):
            a, b = s["target_timerange"]["start"], seg_end(s)
            pts = sorted({a, b} | {x for x in edges if a < x < b})
            pieces = [(x, y) for x, y in zip(pts, pts[1:]) if not is_cut(x)]
            if not pieces:
                removed += 1
                applied.append({"track": ti, "segment_id": s["id"], "old_start_us": a, "old_end_us": b, "removed": True})
                continue
            if pieces == [(a, b)] and not speed_at(a):   # untouched: only moves (also a sped segment)
                s["target_timerange"] = {"start": new_t(a), "duration": new_t(b) - new_t(a)}
                new_segs.append(s)
                applied.append({"track": ti, "segment_id": s["id"], "old_start_us": a, "old_end_us": b,
                                "new_start_us": new_t(a), "new_end_us": new_t(b), "speed": float(s.get("speed", 1.0)),
                                "removed": False})
                continue
            split += len(pieces) > 1
            base = copy.deepcopy(s)
            src0 = s["source_timerange"]["start"] if s.get("source_timerange") else None
            for pi, (x, y) in enumerate(pieces):
                seg = s if pi == 0 else copy.deepcopy(base)
                if pi > 0:
                    seg["id"] = new_id()
                    kind, m = byid[seg["material_id"]]
                    mc = copy.deepcopy(m)
                    mc["id"] = new_id()
                    mats[kind].append(mc)
                    byid[mc["id"]] = (kind, mc)
                    seg["material_id"] = mc["id"]
                    refs = []
                    for e in seg["extra_material_refs"]:
                        ek, em = byid[e]
                        ec = copy.deepcopy(em)
                        ec["id"] = new_id()
                        if ek == "speeds":
                            ec["speed"] = 1.0   # the shared material may have been sped for piece 0
                        mats[ek].append(ec)
                        byid[ec["id"]] = (ek, ec)
                        refs.append(ec["id"])
                    seg["extra_material_refs"] = refs
                    seg.pop("speed", None)
                    seg["volume"] = base["volume"]
                sp = speed_at(x)
                ns, ne = new_t(x), new_t(y)
                if src0 is not None:
                    src_sp = [byid[e][1] for e in seg["extra_material_refs"] if byid[e][0] == "speeds"]
                    if not src_sp or abs(src_sp[0]["speed"] - 1.0) > 1e-6:
                        raise SystemExit(f"segment {seg['id']} already has speed != 1 and would be cut/sped here")
                    seg["source_timerange"] = {"start": src0 + (x - a), "duration": y - x}
                    if sp:
                        k = (y - x) / (ne - ns)
                        src_sp[0]["speed"] = k
                        seg["speed"] = k
                        seg["volume"] = 0.0
                        sped += 1
                seg["target_timerange"] = {"start": ns, "duration": ne - ns}
                new_segs.append(seg)
                applied.append({"track": ti, "segment_id": seg["id"], "old_start_us": x, "old_end_us": y,
                                "new_start_us": ns, "new_end_us": ne, "speed": (y - x) / (ne - ns) if sp else 1.0,
                                "removed": False})
        t["segments"] = new_segs

    old_dur = d["duration"]
    d["duration"] = new_t(old_dur)
    print(f"duration {old_dur / 1e6:.3f} -> {d['duration'] / 1e6:.3f}; removed {removed}, split {split}, sped pieces {sped}")

    # ---------- validation ----------
    errs = common.check_refs(d)
    for ti, t in enumerate(d["tracks"]):
        errs += common.overlap_errors(t, f"track {ti}")
        if common.gap_count(t) > gaps0[t["id"]]:
            errs.append(f"track {ti}: new holes ({gaps0[t['id']]} -> {common.gap_count(t)})")
        if t["type"] in ("video", "audio"):
            errs += [f"short segment track {ti} at {s['target_timerange']['start'] / 1e6:.3f} "
                     f"({s['target_timerange']['duration'] / 1e3:.0f} ms)" for s in t["segments"]
                     if s["target_timerange"]["duration"] < MIN_SEG_US - 1 and s["id"] not in pre_short]
    expected = old_dur - sum(b - a for a, b, _ in cuts) - sum((b - a) - comp for a, b, comp, _ in speeds)
    if abs(expected - d["duration"]) > 1:
        errs.append(f"duration {d['duration']} != expected {expected}")

    def near_word_outside(x, a, b):
        us_t, ca, cb = inv1(x), inv1(a), inv1(b)
        i = bisect.bisect_left(WS, us_t)
        best = 1e18
        for w in W[max(0, i - 3): i + 3]:
            if ca <= w[0] and w[1] <= cb:
                continue   # word removed by this cut
            if w[0] <= us_t <= w[1]:
                return 0
            best = min(best, abs(us_t - w[0]), abs(us_t - w[1]))
        return best
    # edges on a pre-existing splice keep it; filler cuts are bounded by audio silence (whisper words are contiguous)
    close = [(x / 1e6, inv1(x) / 1e6) for a, b, cs in cuts for x in (a, b)
             if x not in bounds and not any(c["cat"] == "filler" for c in cs) and near_word_outside(x, a, b) < MARGIN_US - 1000]
    if close:
        errs.append(f"{len(close)} cut edges closer than 80 ms to a transcript word: {close[:5]}")
    errs += ["sped segment not muted" for t in d["tracks"] for s in t["segments"]
             if s.get("speed", 1.0) != 1.0 and s.get("volume") != 0.0]
    changed = {k for k in d if d[k] != orig[k]} - {"tracks", "materials", "duration"}
    if changed:
        errs.append(f"unexpected top-level change {sorted(changed)}")
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)

    out = {"timeline_before_us": old_dur, "timeline_after_us": d["duration"],
           "cuts": [{"start_us": inv1(a), "end_us": inv1(b), "timeline_start_us": a, "timeline_end_us": b,
                     "cats": sorted({c["cat"] for c in cs}), "ids": [c["id"] for c in cs]} for a, b, cs in cuts],
           "speedups": [{"start_us": inv1(a), "end_us": inv1(b), "timeline_start_us": a, "timeline_end_us": b,
                         "new_duration_us": comp, "speed": (b - a) / comp, "id": c["id"]} for a, b, comp, c in speeds],
           "segments": applied}
    if errs or dry:
        (wd / "stage2").mkdir(parents=True, exist_ok=True)
        (wd / "stage2" / "cuts2_dry.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print("not written" if errs else "dry run, not written")
        if errs:
            raise SystemExit(1)
        return out
    common.write_draft(cfg, d, "stage2", dry=False, guard_seconds=guard_seconds)
    meta = common.read_meta(cfg)
    if "tm_duration" in meta:
        meta["tm_duration"] = d["duration"]
        common.write_meta(cfg, meta, dry=False)
    (wd / "stage2" / "cuts2_applied.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 2: apply technical cuts and speedups")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.dry)


if __name__ == "__main__":
    main()
