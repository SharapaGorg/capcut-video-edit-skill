"""Stage 2 §7: assemble the «свалка» into the working structure, in one go.

    python -X utf8 scripts/stage2/assemble.py --config config.json [--dry] [--resync] [--prerender]

Material is identified by source folder (cfg.sources: camera / screencasts / voice), never by track index.
 0. sync: <work_dir>/layout/assembly.json "pairs" (camera_time = voice_time + offset_us) — computed by
    layout/xcorr.py if missing or --resync. Only pairs with ok=true are used.
 1. camera is rebuilt from the voice: the dump's camera segments are dropped; every screencast piece gets a
    circle piece (mask_circle + clip from the template, scale 0.4), every voice/ (mic) piece a full-screen piece;
    layout/layout.json "F" ranges (if present) turn the camera over the screencast full-screen there.
 2. compounds: mic -> 1 (audio), screencast -> 1, circle -> 1, full-screen camera -> 1 per F stretch
    (on the main track where it is free, else on the overlay track «Камера F»);
 3. camera volume 0 (outer and nested); voice: Voice Crisper + Reduce noise on the mic and screencast
    compounds; the mic compound volume matches the mic to the screencast voice (integrated LUFS of both, ±1 LU;
    effects.match_mic; +4.5 dB only when nothing can be measured), the chosen dB is printed;
 4. Adjustment block over every F stretch (continuous, over camera only); Adjust (Temp -18 / Sat 10) on the
    circle compound segment;
 5. writes both draft files, subdraft/, draft_meta_info, cfg.compounds in config.json, and the result into
    assembly.json "assembled". The mic compound has NO pre-render by default (audio_path "": CapCut renders it
    itself, with fades/volume as it plays them); --prerender makes Resources/combination/<cid>_audio.aac with
    ffmpeg (opt-in: it ignores volume keyframes/fades).
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "layout"))
import common  # noqa: E402
import effects  # noqa: E402
import make_compound as mc  # noqa: E402
from common import index, new_id, seg_end, source_role, subtract_ranges, us  # noqa: E402

MIC_GAIN = 10 ** (effects.MIC_REF_DB / 20)   # fallback only (effects.match_mic)
CNEW = Path(__file__).resolve().parent.parent.parent / "templates" / "capcut_new" / "templates.json"
V_EXTRAS = [("speeds", "speed"), ("placeholder_infos", "placeholder"), ("canvases", "canvas"),
            ("sound_channel_mappings", "sound_channel"), ("material_colors", "material_color"),
            ("vocal_separations", "vocal_separation")]
NAMES = {"circle": "Кружок камеры", "screencast": "Скринкаст", "mic": "Микрофон", "f": "Камера F"}


class NothingToAssemble(RuntimeError):
    pass


def _intersect(a, b, ranges):
    return [(max(a, x), min(b, y)) for x, y in ranges if x < b and y > a]


_merge = common.merge_ranges


def layout_f(cfg) -> list[tuple[int, int]]:
    return _merge([(us(r["start"]), us(r["end"])) for r in common.read_layout(cfg) if r.get("layout") == "F"])


class _Parts:
    """Camera materials/segments built from templates (capcut_new) + effect templates."""

    def __init__(self, cfg, draft, cache_root, dump_cams):
        self.cfg, self.d, self.cache_root = cfg, draft, cache_root
        self.T = json.loads(CNEW.read_text(encoding="utf-8"))
        self.dump_cams = dump_cams
        self.mask_tpl = effects.load_template("mask_circle")
        self.mats: dict[tuple, dict] = {}

    def base(self, name: str) -> dict:
        """Video material of a camera file: the dump's one, else from the template + ffprobe (not in the draft)."""
        if name not in self.dump_cams:
            from capcut_new_project import probe
            if not self.cfg.sources.get("camera"):
                raise SystemExit(f"camera file {name} is in assembly.json, but cfg.sources.camera is empty")
            path = Path(self.cfg.sources["camera"]) / name
            info = probe(path)
            m = copy.deepcopy(self.T["video"])
            m.update(path=path.as_posix(), material_name=name, duration=info["duration"], width=info["width"],
                     height=info["height"], has_audio=info["has_audio"])
            self.dump_cams[name] = m
        return self.dump_cams[name]

    def cam_material(self, name: str, group: str) -> dict:
        """One material per camera file per compound (never shared between compounds)."""
        key = (name, group)
        if key not in self.mats:
            m = copy.deepcopy(self.base(name))
            m["id"] = new_id()
            self.d["materials"].setdefault("videos", []).append(m)
            self.mats[key] = m
        return self.mats[key]

    def segment(self, track, mat, start, dur, src, speed, circle: bool) -> dict:
        M = self.d["materials"]
        refs = []
        for key, tk in V_EXTRAS:
            m = copy.deepcopy(self.T[tk])
            m["id"] = new_id()
            if key == "speeds":
                m["speed"] = float(speed)
            M.setdefault(key, []).append(m)
            refs.append(m["id"])
        seg = copy.deepcopy(self.T["video_segment"])
        seg.update(id=new_id(), material_id=mat["id"], extra_material_refs=refs, speed=float(speed), volume=0.0,
                   last_nonzero_volume=1.0, source_timerange={"start": int(src), "duration": int(round(dur * speed))},
                   target_timerange={"start": int(start), "duration": int(dur)}, common_keyframes=[], keyframe_refs=[],
                   enable_adjust=False, enable_hsl=False, track_attribute=0)
        if circle:
            refs.append(effects.make("mask_circle", self.d, cache_root=self.cache_root))
            seg.update(clip=copy.deepcopy(self.mask_tpl["clip"]), enable_video_mask=True)
        else:
            seg.update(clip=copy.deepcopy(mc.CLIP_FULL), enable_video_mask=False)
        track["segments"].append(seg)
        return seg


def _track(kind: str, name: str = "", flag: int = 2) -> dict:
    return {"id": new_id(), "type": kind, "flag": flag, "attribute": 0, "name": name,
            "is_default_name": not name, "segments": []}


def _cam_piece(s, a, b, offset, cam_dur, fps):
    """Camera piece for the voice segment s over timeline [a, b): (start, dur, cam_src) clipped to the camera file."""
    ts, sp = s["target_timerange"]["start"], float(s.get("speed", 1.0))
    src = s["source_timerange"]["start"] + int(round((a - ts) * sp)) + offset
    if src < 0:
        a += int(round(-src / sp))
        src = 0
    over = src + int(round((b - a) * sp)) - cam_dur
    if over > 0:
        b -= int(round(over / sp)) + 1
    if b - a < 1e6 / fps:
        return None
    return a, b - a, src, sp


def classify(cfg, draft: dict) -> dict[str, list]:
    """Top-level segments by source role {camera|screencast|voice: [(track, segment)]}; NothingToAssemble if the
    project has no raw screencast/voice segments or config.json already lists compounds."""
    ix = index(draft["materials"])
    roles: dict[str, list] = {"camera": [], "screencast": [], "voice": []}
    for t in draft["tracks"]:
        for s in t["segments"]:
            if s.get("material_id") in ix:
                r = source_role(cfg, common.mat_path(ix, s))
                if r:
                    roles[r].append((t, s))
    if not roles["screencast"] and not roles["voice"]:
        raise NothingToAssemble("нет сырых сегментов скринкаста/голоса на верхнем уровне — проект уже собран?")
    if (cfg.compounds or {}).get("screencast"):
        raise NothingToAssemble(f"в config.json уже есть compounds: {cfg.compounds}")
    adj = [(s["target_timerange"]["start"] / 1e6, seg_end(s) / 1e6) for t in draft["tracks"] if t["type"] == "adjust"
           for s in t["segments"]]
    if adj:   # assemble puts one block per F stretch itself; a leftover block would colour the camera twice
        raise SystemExit("в свалке уже есть блоки Adjustment: " + ", ".join(f"{a:.3f}–{b:.3f} с" for a, b in adj)
                         + ". Цвет ставит сборка (по одному блоку на участок F). Удалить эти блоки в CapCut "
                           "(или в копии проекта) и запустить снова; ничего не записано.")
    return roles


def assemble(cfg, draft: dict, pairs: list[dict], f_ranges: list[tuple[int, int]], cache_root=None, log=print,
             allow_unsynced: bool = False) -> dict:
    """Mutates draft. A voice file without an ok sync pair while camera files exist -> SystemExit (nothing written),
    unless allow_unsynced (then that part simply gets no camera). Returns {"compounds": cfg.compounds dict, "made": [Compound], "f": [(a, b)], "report": {...}}."""
    mats = draft["materials"]
    ix = index(mats)
    roles = classify(cfg, draft)
    sc_tracks = {id(t): t for t, _ in roles["screencast"]}
    v_tracks = {id(t): t for t, _ in roles["voice"]}
    if len(sc_tracks) > 1 or len(v_tracks) > 1:
        raise ValueError(f"скринкаст/голос должны лежать каждый на одной дорожке: {len(sc_tracks)} / {len(v_tracks)}")
    main = next(iter(sc_tracks.values()), None)
    vtrack = next(iter(v_tracks.values()), None)
    if vtrack is not None and vtrack["type"] != "audio":
        raise ValueError("voice/ на видеодорожке: ожидается аудиодорожка")

    # 1. drop the dump's camera (its material is reused as the template of that camera file)
    dump_cams = {}
    drop = set()
    for t, s in roles["camera"]:
        m = ix[s["material_id"]][1]
        dump_cams.setdefault(Path(m["path"]).name, copy.deepcopy(m))
        drop.add(s["id"])
    gone = {r for t, s in roles["camera"] for r in [s["material_id"]] + list(s.get("extra_material_refs") or [])}
    for t in draft["tracks"]:
        t["segments"] = [s for s in t["segments"] if s["id"] not in drop]
    keep = {r for t in draft["tracks"] for s in t["segments"] for r in [s.get("material_id")] + list(s.get("extra_material_refs") or [])}
    for k, v in mats.items():
        if isinstance(v, list):
            mats[k] = [m for m in v if not (isinstance(m, dict) and m.get("id") in gone and m["id"] not in keep)]
    cam_tracks = {id(t) for t, _ in roles["camera"]}
    draft["tracks"] = [t for t in draft["tracks"] if t["segments"] or id(t) not in cam_tracks]

    sync = {p["voice"]: p for p in pairs if p.get("ok")}
    parts = _Parts(cfg, draft, cache_root, dump_cams)
    fps = cfg.fps

    circle, fpieces, unsynced = [], [], set()
    for kind, lst in (("screencast", roles["screencast"]), ("voice", roles["voice"])):
        for t, s in sorted(lst, key=lambda x: x[1]["target_timerange"]["start"]):
            name = Path(common.mat_path(ix, s)).name
            p = sync.get(name)
            if not p:
                unsynced.add(name)
                continue
            ts, te = s["target_timerange"]["start"], seg_end(s)
            if kind == "voice":
                spans = [((ts, te), False)]
            else:
                spans = [(r, True) for r in subtract_ranges(ts, te, f_ranges)] + [(r, False) for r in _intersect(ts, te, f_ranges)]
            for (a, b), is_circle in spans:
                pc = _cam_piece(s, a, b, int(p["offset_us"]), parts.base(p["camera"])["duration"], fps)
                if pc:
                    (circle if is_circle else fpieces).append((p["camera"],) + pc)
    if unsynced:
        from capcut_new_project import list_media
        info = {p["voice"]: p for p in pairs}
        lines = [f"  {n}: " + (f"camera {info[n].get('camera')}, offset {info[n].get('offset_us', 0) / 1e6:+.3f} s, "
                                f"z {info[n].get('z')}, within_frame {info[n].get('within_frame')} -> not ok"
                                if n in info else "no pair in assembly.json") for n in sorted(unsynced)]
        if list_media(cfg.sources.get("camera")) and not allow_unsynced:
            raise SystemExit("нет синхрона с камерой (layout/assembly.json):\n" + "\n".join(lines) +
                             "\nпроверить пары (layout/xcorr.py --force) или --allow-unsynced (эти куски без камеры)")
        for line in lines:
            log("warning: no camera over" + line)

    made, comp = [], {"mic": None, "cam_full": [], "screencast": None, "circle": None}
    pos = draft["tracks"].index(main) + 1 if main is not None else 0
    # circle
    if circle:
        ct = _track("video", NAMES["circle"])
        draft["tracks"].insert(pos, ct)
        pos += 1
        segs = [parts.segment(ct, parts.cam_material(cam, "circle"), a, dur, src, sp, True) for cam, a, dur, src, sp in circle]
        c = mc.wrap(draft, ct, segs, NAMES["circle"], "overlay", 0.0, cfg.project_dir, cfg.width, cfg.height)
        for mid in effects.make_all("adjust_circle", draft, cache_root=cache_root):
            effects.attach(c.outer, mid)
        c.outer.update(enable_adjust=True, enable_hsl=True)
        made.append(c)
        comp["circle"] = c.nid
    # full-screen camera, one compound per F stretch
    stretches = _merge([(a, a + dur) for _, a, dur, _, _ in fpieces], tol=int(1e6 / fps))
    ftrack = None
    for i, (x, y) in enumerate(stretches, 1):
        free = main is None or not any(s["target_timerange"]["start"] < y and seg_end(s) > x for s in main["segments"])
        if free and main is not None:
            tr, kind = main, "main"
        else:
            if ftrack is None:
                ftrack = _track("video", NAMES["f"])
                draft["tracks"].insert(pos, ftrack)
                pos += 1
            tr, kind = ftrack, "overlay"
        segs = [parts.segment(tr, parts.cam_material(cam, f"f{i}"), a, dur, src, sp, False)
                for cam, a, dur, src, sp in fpieces if x <= a < y]
        c = mc.wrap(draft, tr, segs, f"{NAMES['f']} {i}", kind, 0.0, cfg.project_dir, cfg.width, cfg.height)
        made.append(c)
        comp["cam_full"].append(c.nid)
    if stretches:
        at = _track("adjust", flag=0)
        draft["tracks"].insert(pos, at)
        for x, y in stretches:
            effects.adjustment_segment(draft, at, x, y - x, cache_root=cache_root)
    # voice: screencast and mic compounds + effects
    for key, track, lst, kind, vol in (("screencast", main, roles["screencast"], "main", 1.0),
                                       ("mic", vtrack, roles["voice"], "audio", MIC_GAIN)):
        if not lst:
            continue
        segs = [s for _, s in lst]
        if key == "mic":   # the +4.5 dB sits on the compound segment; muted (sped) pieces stay muted
            for s in segs:
                if s.get("volume", 1.0) > 0:
                    s["volume"] = 1.0
        c = mc.wrap(draft, track, segs, NAMES[key], kind, vol, cfg.project_dir, cfg.width, cfg.height)
        effects.attach(c.outer, effects.make("voice_crisper", draft, cache_root=cache_root))
        effects.attach(c.outer, effects.make("reduce_noise", draft, cache_root=cache_root))
        made.append(c)
        comp[key] = c.nid
    gain = effects.match_mic(cfg, draft, [next(c for c in made if c.nid == comp["mic"]).outer], log=log) \
        if comp["mic"] else None
    for i, t in enumerate(draft["tracks"]):
        for s in t["segments"]:
            if t["type"] == "video":
                s["render_index"] = s["track_render_index"] = i
    draft["duration"] = max((seg_end(s) for t in draft["tracks"] for s in t["segments"]), default=draft["duration"])
    report = {"compounds": comp, "f_stretches_us": [list(r) for r in stretches], "circle_pieces": len(circle),
              "f_pieces": len(fpieces), "unsynced": sorted(unsynced), "mic_gain": gain["volume"] if gain else None,
              "mic_gain_db": gain["db"] if gain else None, "mic_gain_measured": gain["measured"] if gain else None,
              "duration_us": draft["duration"]}
    return {"compounds": comp, "made": made, "f": stretches, "report": report}


def validate(draft: dict, res: dict) -> list[str]:
    errs = mc.errors(draft, res["made"])
    ix = index(draft["materials"])
    errs += common.draft_overlaps(draft)
    comp = res["compounds"]
    by_nid = {c.nid: c for c in res["made"]}
    for nid in [comp["circle"]] + comp["cam_full"]:
        if nid:
            c = by_nid[nid]
            if c.outer["volume"] != 0.0 or any(s["volume"] != 0.0 for t in c.nested["tracks"] for s in t["segments"]):
                errs.append(f"{c.name}: camera not muted")
    for key in ("screencast", "mic"):
        if comp[key]:
            cats = {ix[e][0] for e in by_nid[comp[key]].outer["extra_material_refs"]}
            if not {"audio_effects", "realtime_denoises"} <= cats:
                errs.append(f"{key}: voice effects missing")
    if comp["circle"]:
        nd = by_nid[comp["circle"]].nested
        jx = index(nd["materials"])
        for s in nd["tracks"][-1]["segments"]:
            m = [jx[e][1] for e in s["extra_material_refs"] if jx[e][0] == "common_mask"]
            if len(m) != 1 or m[0].get("type") != "mask" or not Path(m[0].get("path", "")).is_dir():
                errs.append("circle mask: type mask / existing path expected")
                break
    adj = sorted((s["target_timerange"]["start"], seg_end(s)) for t in draft["tracks"] if t["type"] == "adjust"
                 for s in t["segments"])
    if adj != [tuple(r) for r in res["f"]]:
        errs.append(f"Adjustment blocks {adj} != F stretches {res['f']}")
    return errs


def get_pairs(cfg, resync: bool, log=print) -> list[dict]:
    p = cfg.work_dir / "layout" / "assembly.json"
    rep = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    if rep.get("pairs") and not resync:
        return rep["pairs"]
    import xcorr
    return xcorr.sync_sources(cfg, log=log)


def run(cfg, dry: bool, cache_root=None, guard_seconds: float = 5, resync: bool = False, log=print,
        allow_unsynced: bool = False, prerender: bool = False) -> dict:
    draft = common.read_draft(cfg)
    classify(cfg, draft)  # before the (slow) sync
    pairs = get_pairs(cfg, resync, log)
    res = assemble(cfg, draft, pairs, layout_f(cfg), cache_root=cache_root, log=log, allow_unsynced=allow_unsynced)
    errs = validate(draft, res)
    for c in res["made"]:
        log(f"{c.name}: {c.n} segments -> compound {c.nid}, {c.outer['target_timerange']['start'] / 1e6:.3f}"
            f"+{c.outer['target_timerange']['duration'] / 1e6:.3f} s, volume {c.outer['volume']:.3f}")
    log(f"tracks: {[(t['type'], t.get('name'), len(t['segments'])) for t in draft['tracks']]}")
    log("VALIDATION: " + ("OK" if not errs else "FAIL"))
    for e in errs:
        log("  - " + e)
    if errs:
        raise SystemExit(1)
    if dry:
        log("dry run, not written")
        return res["report"]
    common.write_draft(cfg, draft, "assemble", dry=False, guard_seconds=guard_seconds,
                       subdrafts={c.nid: c.wrapper for c in res["made"]})
    for c in res["made"]:
        if c.kind == "audio" and prerender:   # default: audio_path "" — CapCut renders the compound itself
            mc.prerender_audio(cfg.project_dir, c, log=log)
    mc.write_files(cfg, res["made"])
    common.save_config_field(cfg, "compounds", res["compounds"])
    ap = cfg.work_dir / "layout" / "assembly.json"
    rep = json.loads(ap.read_text(encoding="utf-8")) if ap.is_file() else {}
    rep.update(pairs=pairs, assembled=res["report"])
    ap.parent.mkdir(parents=True, exist_ok=True)
    ap.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    log("written")
    return res["report"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="assemble the dump: sync, circle, compounds, voice, Adjustment")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--resync", action="store_true", help="recompute camera sync (layout/xcorr.py)")
    ap.add_argument("--allow-unsynced", action="store_true",
                    help="assemble even if some voice files have no camera sync (they get no camera)")
    ap.add_argument("--prerender", action="store_true",
                    help="pre-render the mic compound audio with ffmpeg (default: none, CapCut renders it)")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    try:
        run(cfg, a.dry, resync=a.resync, allow_unsynced=a.allow_unsynced, prerender=a.prerender)
    except NothingToAssemble as e:
        print(f"nothing to assemble: {e}")
    except effects.EffectCacheMissing as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
