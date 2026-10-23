"""Shared helpers for video-edit scripts: config, CapCut draft read/write, id/time helpers.

Write rules (references/capcut-format.md): CapCut.exe must be 0 processes, backup the
project dir, write BOTH root draft_content.json and Timelines/<id>/draft_content.json,
bump update_time, then guard mtime (CapCut must not rewrite the file).
"""
from __future__ import annotations

import copy
import functools
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_LAD = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else None
_CC = _LAD / "CapCut" / "User Data" if _LAD else Path("__no_localappdata__")
PROJECTS_ROOT = _CC / "Projects" / "com.lveditor.draft"
EFFECT_CACHE = _CC / "Cache" / "effect" if _LAD else None


@dataclass
class Config:
    project_dir: Path
    timeline_id: str
    sources: dict
    fps: int = 30
    width: int = 1920
    height: int = 1080
    compounds: dict = field(default_factory=dict)
    sfx_dir: str | None = None
    music_dir: str | None = None
    master_render: str | None = None
    work_dir: Path = Path(".")
    tiktok_channel: str | None = None
    tiktok_thumbnail: str | None = None   # screenshot of the long video in YouTube search (TikTok end card), optional
    reels_word: str | None = None         # Reels CTA code word (spec "code_word" overrides)
    master_maps: str | None = None        # maps of the timeline master_render came from; None = <work_dir>/stage3
    description_md: str | None = None
    tessdata: str | None = None      # folder with rus/eng.traineddata if the tesseract install lacks rus
    config_path: Path | None = None


def detect_timeline_id(project_dir) -> str:
    tl = Path(project_dir) / "Timelines"
    dirs = sorted(p.name for p in tl.iterdir() if p.is_dir()) if tl.is_dir() else []
    if len(dirs) != 1:
        raise ValueError(f"expected exactly one folder in {tl} (Timelines), found {len(dirs)}: {dirs}")
    return dirs[0]


def load_config(path: str | None = None, strict: bool | None = None) -> Config:
    """config.json (default: cwd). fps / width / height are compared with the project's draft (fps,
    canvas_config): a difference -> a warning on stderr, or SystemExit with strict (strict=None -> the env var
    VIDEO_EDIT_STRICT=1). No readable draft -> no check."""
    p = Path(path) if path else Path.cwd() / "config.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    project_dir = Path(raw["project_dir"])
    tid = raw.get("timeline_id") or detect_timeline_id(project_dir)
    src = dict(raw.get("sources") or {})
    src.setdefault("voice", None)
    cfg = Config(
        project_dir=project_dir,
        timeline_id=tid,
        sources=src,
        fps=raw.get("fps", 30),
        width=raw.get("width", 1920),
        height=raw.get("height", 1080),
        compounds=raw.get("compounds") or {"mic": None, "cam_full": [], "screencast": None, "circle": None},
        sfx_dir=raw.get("sfx_dir"),
        music_dir=raw.get("music_dir"),
        master_render=raw.get("master_render"),
        work_dir=Path(raw["work_dir"]) if raw.get("work_dir") else p.resolve().parent,
        tiktok_channel=raw.get("tiktok_channel"),
        tiktok_thumbnail=raw.get("tiktok_thumbnail"),
        reels_word=raw.get("reels_word"),
        master_maps=raw.get("master_maps"),
        description_md=raw.get("description_md"),
        tessdata=raw.get("tessdata"),
        config_path=p.resolve(),
    )
    if strict is None:
        strict = os.environ.get("VIDEO_EDIT_STRICT") == "1"
    diff = format_mismatch(cfg)
    if diff:
        msg = (f"config.json ≠ проект: {'; '.join(diff)} — исправить fps/width/height в {p} "
               "(init_video.py --force перечитает их из драфта)")
        if strict:
            raise SystemExit(msg)
        import sys
        print("warning: " + msg, file=sys.stderr)
    return cfg


def format_mismatch(cfg: Config) -> list[str]:
    """['fps 30 != draft 25', ...] between cfg and the draft's fps / canvas_config; [] if equal or no draft."""
    try:
        d = read_draft(cfg)
    except (OSError, ValueError):
        return []
    out = []
    fps = d.get("fps")
    if isinstance(fps, (int, float)) and abs(float(fps) - float(cfg.fps)) > 1e-3:
        out.append(f"fps {cfg.fps} != draft {fps:g}")
    cc = d.get("canvas_config") or {}
    for k in ("width", "height"):
        if isinstance(cc.get(k), (int, float)) and int(cc[k]) != int(getattr(cfg, k)):
            out.append(f"{k} {getattr(cfg, k)} != draft {cc[k]}")
    return out


def save_config_field(cfg: Config, key: str, value) -> None:
    """Set one top-level key in config.json (e.g. compounds after assemble) and in cfg."""
    if cfg.config_path is None:
        raise ValueError("cfg has no config_path (not loaded by load_config)")
    raw = json.loads(cfg.config_path.read_text(encoding="utf-8"))
    raw[key] = value
    cfg.config_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    if hasattr(cfg, key):
        setattr(cfg, key, value)


def draft_paths(cfg: Config) -> list[Path]:
    """[root mirror, real timeline Timelines/<id>]."""
    return [cfg.project_dir / "draft_content.json",
            cfg.project_dir / "Timelines" / cfg.timeline_id / "draft_content.json"]


def read_draft(cfg: Config) -> dict:
    """Reads the real timeline (Timelines/<id>); falls back to root if absent."""
    root, real = draft_paths(cfg)
    src = real if real.is_file() else root
    return json.loads(src.read_text(encoding="utf-8"))


def ensure_capcut_closed() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Stop-Process -Name CapCut -Force -ErrorAction SilentlyContinue"],
                   capture_output=True)
    for _ in range(10):
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/NH"],
                             capture_output=True, text=True).stdout
        if "capcut.exe" not in out.lower():
            return
        time.sleep(1)
    raise RuntimeError("CapCut.exe is still running after Stop-Process; close it and retry")


def backup(cfg: Config, stage: str) -> Path:
    base = cfg.work_dir / "backups" / f"{stage}-before-{time.strftime('%Y%m%d-%H%M%S')}"
    base.parent.mkdir(parents=True, exist_ok=True)
    dst, n = base, 1
    while dst.exists():
        n += 1
        dst = base.with_name(f"{base.name}-{n}")
    shutil.copytree(cfg.project_dir, dst)
    return dst


def _now_like(old) -> int:
    """Current time in the same scale as the existing update_time (CapCut uses µs)."""
    t = time.time()
    if isinstance(old, (int, float)) and 0 < old < 1e11:
        return int(t)
    if isinstance(old, (int, float)) and 0 < old < 1e14:
        return int(t * 1e3)
    return int(t * 1e6)


def _dump(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def write_draft(cfg: Config, draft: dict, stage: str, dry: bool,
                subdrafts: dict[str, dict] | None = None, guard_seconds: float = 5) -> Path | None:
    """Kill CapCut, backup, write root + Timelines (+ subdraft/<id>), guard mtime. Returns backup path."""
    if dry:
        return None
    ensure_capcut_closed()
    bk = backup(cfg, stage)
    draft["update_time"] = _now_like(draft.get("update_time"))
    written = []
    for p in draft_paths(cfg):
        _dump(p, draft)
        written.append(p)
    for did, sd in (subdrafts or {}).items():
        p = cfg.project_dir / "subdraft" / did / "draft_content.json"
        _dump(p, sd)
        written.append(p)
    m0 = {p: p.stat().st_mtime_ns for p in written}
    if guard_seconds:
        time.sleep(guard_seconds)
    changed = [str(p) for p in written if p.stat().st_mtime_ns != m0[p]]
    if changed:
        raise RuntimeError(f"files rewritten after write (CapCut alive?): {changed}; backup: {bk}")
    return bk


def read_meta(cfg: Config) -> dict:
    return json.loads((cfg.project_dir / "draft_meta_info.json").read_text(encoding="utf-8"))


def write_meta(cfg: Config, meta: dict, dry: bool) -> None:
    """draft_meta_info.json; call after write_draft (which made the backup and checked CapCut is closed)."""
    if not dry:
        _dump(cfg.project_dir / "draft_meta_info.json", meta)


_CNEW_TPL = Path(__file__).resolve().parent.parent / "templates" / "capcut_new" / "templates.json"


def add_meta_material(meta: dict, path, duration_us: int, width: int, height: int, metetype: str = "video") -> dict:
    """An imported-media entry (draft_materials type 0, as CapCut's import makes it) for path; an entry with the same
    file_Path is replaced, so a re-run adds nothing. Returns the entry."""
    tpl = json.loads(_CNEW_TPL.read_text(encoding="utf-8"))["meta_material"]
    p = Path(path)
    now = time.time()
    mm = copy.deepcopy(tpl)
    mm.update(id=str(uuid.uuid4()), file_Path=p.as_posix(), extra_info=p.name, duration=int(duration_us),
              width=int(width), height=int(height), metetype=metetype,
              create_time=int(p.stat().st_mtime) if p.exists() else int(now), import_time=int(now),
              import_time_ms=int(now * 1e6), roughcut_time_range={"start": 0, "duration": int(duration_us)})
    groups = meta.setdefault("draft_materials", [])
    g0 = next((g for g in groups if g.get("type") == 0), None)
    if g0 is None:
        g0 = {"type": 0, "value": []}
        groups.insert(0, g0)
    g0["value"] = [v for v in g0.get("value", []) if v.get("file_Path") != mm["file_Path"]] + [mm]
    return mm


# ---- source files ----
ROLE_DIRS = (("camera", "camera"), ("screencast", "screencasts"), ("voice", "voice"))


def _norm(p) -> str:
    return str(p).replace("\\", "/").rstrip("/").lower()


@functools.lru_cache(maxsize=64)
def _listing(d: str) -> frozenset:
    p = Path(d)
    return frozenset(x.name.lower() for x in p.iterdir() if x.is_file()) if p.is_dir() else frozenset()


def uncensored_name(path) -> str:
    """Base name with the stage-5 suffix dropped: «a b_censored.mp4» -> «a b.mp4» (a censored copy = its source)."""
    name = Path(str(path).replace("\\", "/")).name
    return re.sub(r"_censored(\.[^.]+)$", r"\1", name, flags=re.I)


def source_role(cfg: Config, path: str) -> str | None:
    """'camera' | 'screencast' | 'voice' | None for a material path: by folder prefix from cfg.sources,
    else by file name present in that folder (the project may use a local copy of the sources)."""
    if not path:
        return None
    p = _norm(path)
    dirs = [(role, cfg.sources.get(key)) for role, key in ROLE_DIRS]
    for role, d in dirs:
        if d and p.startswith(_norm(d) + "/"):
            return role
    name = uncensored_name(path).lower()
    for role, d in dirs:
        if d and name in _listing(d):
            return role
    return None


def _drafts_ix(d: dict, inherited: dict) -> dict:
    """drafts materials visible inside d: its own + its ancestors' (CapCut keeps the drafts of a compound nested in
    a compound in the ROOT materials.drafts, not in the nested draft)."""
    own = {m["id"]: m for m in d.get("materials", {}).get("drafts", []) or [] if isinstance(m, dict) and "id" in m}
    return {**inherited, **own}


def flatten(cfg: Config, draft: dict, roles=("camera", "screencast", "voice")) -> list[dict]:
    """Leaf pieces (also inside compounds, any depth) in timeline time (us), sorted by start:
    [{path, role, start, end, dur, src, src_end, speed, volume, segment_id, track, compound, kind, name, mask}].
    roles: source roles to keep; None = every leaf segment (texts, effects… too, role None).
    Nested pieces are clipped to the window the outer segment shows. speed = effective speed (product down the
    compound chain), volume = product of the volumes down the chain, track = index of the top-level track,
    compound = "nested name#track > …" (None on the top level), src/src_end = None without source_timerange."""
    out = []

    def walk(d, off, k, lo, hi, dix, chain, vol, top):  # timeline = off + (time inside d) / k; window [lo, hi)
        ix = index(d.get("materials", {}))
        dix = _drafts_ix(d, dix)
        for ti, t in enumerate(d.get("tracks", [])):
            ch = chain if top is None else chain + [f"{d.get('name', '')}#{ti}"]
            for s in t.get("segments", []):
                if s.get("material_id") not in ix:
                    continue
                kind, m = ix[s["material_id"]]
                dm = next((dix[e] for e in s.get("extra_material_refs") or [] if e in dix), None)
                a = off + s["target_timerange"]["start"] / k
                b = off + seg_end(s) / k
                a2, b2 = max(a, lo), min(b, hi)
                if b2 <= a2:
                    continue
                sp = float(s.get("speed", 1.0)) * k
                sv = vol * float(s.get("volume", 1.0))
                tr = ti if top is None else top
                st = s.get("source_timerange")
                src0 = (st or {}).get("start", 0)
                if dm is not None and isinstance(dm.get("draft"), dict):
                    walk(dm["draft"], a - src0 / sp, sp, a2, b2, dix, ch, sv, tr)
                    continue
                role = source_role(cfg, m.get("path", ""))
                if roles is None or role in roles:
                    s0, s1 = int(round(a2)), int(round(b2))
                    out.append({"path": m.get("path", "") or "", "role": role, "start": s0, "end": s1, "dur": s1 - s0,
                                "speed": sp, "volume": sv,
                                "src": src0 + int(round((a2 - a) * sp)) if st else None,
                                "src_end": src0 + int(round((b2 - a) * sp)) if st else None,
                                "segment_id": s.get("id"), "track": tr, "kind": kind,
                                "mask": has_mask(s, ix),
                                "name": m.get("material_name") or m.get("name") or "",
                                "compound": " > ".join(ch) if ch else None})

    walk(draft, 0, 1.0, 0, 1 << 62, {}, [], 1.0, None)
    return sorted(out, key=lambda x: x["start"])


def all_segments(draft: dict) -> dict:
    """segment id -> segment for every segment of the draft and of every nested draft (any depth)."""
    out = {}
    stack = [draft]
    while stack:
        d = stack.pop()
        for t in d.get("tracks", []):
            for s in t.get("segments", []):
                out.setdefault(s.get("id"), s)
        stack += [m["draft"] for m in d.get("materials", {}).get("drafts", []) or []
                  if isinstance(m, dict) and isinstance(m.get("draft"), dict)]
    return out


def has_mask(seg: dict, ix: dict) -> bool:
    """The segment really shows a mask: enable_video_mask and a common_mask material of type "mask" (CapCut ignores
    enable_video_mask without one, or with type "none" — capcut-format.md)."""
    return bool(seg.get("enable_video_mask")) and any(
        e in ix and ix[e][0] == "common_mask" and ix[e][1].get("type") == "mask" for e in seg.get("extra_material_refs") or [])


# ---- ids, materials, time ----
def new_id() -> str:
    return str(uuid.uuid4()).upper()


def index(materials: dict) -> dict:
    """material id -> (materials key, material dict)."""
    return {m["id"]: (k, m) for k, v in materials.items() if isinstance(v, list)
            for m in v if isinstance(m, dict) and "id" in m}


def seg_end(seg) -> int:
    return seg["target_timerange"]["start"] + seg["target_timerange"]["duration"]


def by_start(segs):
    return sorted(segs, key=lambda s: s["target_timerange"]["start"])


def mat_path(ix, seg) -> str:
    return ix[seg["material_id"]][1].get("path", "") or ""


def check_refs(draft) -> list[str]:
    """Dangling material refs in the draft and nested drafts (materials.drafts[].draft). A nested segment may
    reference a drafts material of an ancestor draft (compound inside a compound) — that is not dangling."""
    errs: list[str] = []

    def walk(d, label, dix):
        jx = index(d.get("materials", {}))
        dix = _drafts_ix(d, dix)
        for t in d.get("tracks", []):
            for s in t.get("segments", []):
                for mid in [s.get("material_id")] + list(s.get("extra_material_refs") or []):
                    if mid and mid not in jx and mid not in dix:
                        errs.append(f"{label}: dangling ref {mid} in segment {s.get('id')}")
        for dm in d.get("materials", {}).get("drafts", []) or []:
            if isinstance(dm.get("draft"), dict):
                walk(dm["draft"], f"{label}/{dm.get('id')}", dix)

    walk(draft, "outer", {})
    return errs


def subtract_ranges(a, b, ranges) -> list[tuple]:
    """Parts of [a, b) not covered by `ranges` (sorted, non-overlapping [x, y) pairs)."""
    out, cur = [], a
    for x, y in ranges:
        if y <= cur or x >= b:
            continue
        if x > cur:
            out.append((cur, x))
        cur = max(cur, y)
    if cur < b:
        out.append((cur, b))
    return out


def map_through_cuts(t, cuts):
    """Time t after removing the [a, b) ranges `cuts` (ripple): t minus the cut length before it. A point inside a
    cut maps to the cut start. Used for transcript time -> timeline time after stage 1."""
    return t - sum(min(b, t) - a for a, b in cuts if a < t)


def ripple(draft: dict, cuts: list[tuple[int, int]]) -> list[dict]:
    """Remove [a, b) ranges (top-level timeline us, sorted, non-overlapping) from every track and shift the rest
    left. A segment crossing a cut is split: the 2nd+ piece gets a cloned material and cloned extra refs (as CapCut
    split does; a compound piece gets its own copy of the nested draft). source_timerange is rewritten only for
    trimmed/split segments: start += offset x speed, duration = target x speed. Returns per-piece records
    (track, segment_id, old_start_us, old_end_us, new_start_us, shift_us, removed, cut = trimmed/split)."""
    clone = _Cloner(draft)
    rec = []
    for ti, t in enumerate(draft["tracks"]):
        segs = []
        for s in by_start(t["segments"]):
            a, b = s["target_timerange"]["start"], seg_end(s)
            parts = subtract_ranges(a, b, cuts)
            if not parts:
                rec.append({"track": ti, "segment_id": s["id"], "old_start_us": a, "old_end_us": b, "removed": True})
                continue
            cut = parts != [(a, b)]
            sp = float(s.get("speed", 1.0))
            src0 = (s.get("source_timerange") or {}).get("start")
            for pi, (x, y) in enumerate(parts):
                seg = s if pi == 0 else clone.piece(s)
                if cut:
                    _retime(seg, a, x, y, sp, src0)
                nx = map_through_cuts(x, cuts)
                seg["target_timerange"] = {"start": nx, "duration": y - x}
                segs.append(seg)
                rec.append({"track": ti, "segment_id": seg["id"], "old_start_us": x, "old_end_us": y,
                            "new_start_us": nx, "shift_us": x - nx, "removed": False, "cut": cut})
        t["segments"] = segs
    draft["duration"] = map_through_cuts(draft["duration"], cuts)
    return rec


class _Cloner:
    """Fresh copies of materials for a split piece, as CapCut split does: a compound piece gets its own copy of the
    nested draft with a FRESH nested draft id, but keeps the combination_id and the draft_*_path of the original
    (all pieces share the original subdraft/<id>/ folder — seen on a real project: 45 drafts entries, 11 folders).
    Refs not in the index are kept as they are. self.drafts: [(original nested id, cloned drafts entry)]."""

    def __init__(self, draft: dict):
        self.mats = draft["materials"]
        self.byid = index(self.mats)
        self.drafts: list[tuple[str, dict]] = []

    def __call__(self, mid):
        if mid not in self.byid:
            return mid
        k, m = self.byid[mid]
        c = copy.deepcopy(m)
        c["id"] = new_id()
        if k == "drafts" and isinstance(c.get("draft"), dict):
            old = c["draft"].get("id")
            c["draft"]["id"] = new_id()
            self.drafts.append((old, c))
        self.mats[k].append(c)
        self.byid[c["id"]] = (k, c)
        return c["id"]

    def piece(self, s: dict) -> dict:
        seg = copy.deepcopy(s)
        seg["id"] = new_id()
        seg["material_id"] = self(seg["material_id"])
        seg["extra_material_refs"] = [self(e) for e in seg.get("extra_material_refs") or []]
        return seg


def _retime(seg: dict, a: int, x: int, y: int, sp: float, src0) -> None:
    """Piece [x, y) of a segment that starts at a: source start += offset x speed, duration = target x speed."""
    if src0 is not None:
        seg["source_timerange"] = {"start": src0 + int(round((x - a) * sp)), "duration": int(round((y - x) * sp))}


def clone_piece(draft: dict, seg: dict, x: int, y: int, clone: _Cloner | None = None) -> dict:
    """A copy of the part [x, y) (timeline us) of a top-level segment, as CapCut copy/split makes it: fresh ids, own
    copies of the material and extras (a compound piece: own drafts entry + nested draft copy with a fresh id, same
    subdraft folder — _Cloner), source retimed,
    target [x, y) (move it yourself). The draft gets the new materials; the segment is not added to a track."""
    clone = clone or _Cloner(draft)
    c = clone.piece(seg)
    _retime(c, seg["target_timerange"]["start"], x, y, float(seg.get("speed", 1.0)),
            (seg.get("source_timerange") or {}).get("start"))
    c["target_timerange"] = {"start": x, "duration": y - x}
    return c


def split_at(draft: dict, track: dict, times) -> list[dict]:
    """Split the segments of `track` at timeline times (us; a time on a boundary or outside every segment is
    ignored), like CapCut split: the 2nd+ piece gets a cloned material + extras. ValueError for a segment with
    keyframes (they would have to be redistributed). Returns the track's segments sorted by start."""
    clone = _Cloner(draft)
    out = []
    for s in by_start(track["segments"]):
        a, b = s["target_timerange"]["start"], seg_end(s)
        cut = sorted({int(t) for t in times if a < t < b})
        if not cut:
            out.append(s)
            continue
        if s.get("common_keyframes"):
            raise ValueError(f"segment {s['id']} at {a / 1e6:.3f} s has keyframes: cannot split it here")
        sp = float(s.get("speed", 1.0))
        src0 = (s.get("source_timerange") or {}).get("start")
        bounds = [a] + cut + [b]
        for pi, (x, y) in enumerate(zip(bounds, bounds[1:])):
            seg = s if pi == 0 else clone.piece(s)
            _retime(seg, a, x, y, sp, src0)
            seg["target_timerange"] = {"start": x, "duration": y - x}
            out.append(seg)
    track["segments"] = out
    return out


def lift(draft: dict, seg: dict, a: int, b: int) -> list[dict]:
    """Copies of the leaf segments that the top-level segment `seg` (also a compound, any depth) shows in the
    timeline window [a, b), as top-level segments: target in top timeline us, source clipped, speed = effective
    speed, volume = product down the chain. Each copy has fresh ids and fresh copies of its material and extras
    (taken from the draft that holds the leaf). The draft is not changed: returns
    [{"seg", "mats": [(category, material)], "path"}] sorted by start — add them with adopt()."""
    out = []

    def walk(s, d, dix, off, k, lo, hi, vol):
        jx = index(d.get("materials", {}))
        dix = _drafts_ix(d, dix)
        ta = off + s["target_timerange"]["start"] / k
        tb = off + seg_end(s) / k
        x, y = max(ta, lo), min(tb, hi)
        if y <= x:
            return
        sp = float(s.get("speed", 1.0)) * k
        v = vol * float(s.get("volume", 1.0))
        st = s.get("source_timerange")
        src0 = (st or {}).get("start", 0)
        dm = next((dix[e] for e in s.get("extra_material_refs") or [] if e in dix), None)
        if dm is not None and isinstance(dm.get("draft"), dict):
            nd = dm["draft"]
            for t in nd.get("tracks", []):
                for ns in t.get("segments", []):
                    walk(ns, nd, dix, ta - src0 / sp, sp, x, y, v)
            return
        if s.get("material_id") not in jx:
            return
        mats = []
        for mid in [s["material_id"]] + list(s.get("extra_material_refs") or []):
            if mid in jx:
                c = copy.deepcopy(jx[mid][1])
                c["id"] = new_id()
                mats.append((jx[mid][0], c))
        c = copy.deepcopy(s)
        x0, y0 = int(round(x)), int(round(y))
        c.update(id=new_id(), material_id=mats[0][1]["id"], extra_material_refs=[m["id"] for _, m in mats[1:]],
                 speed=sp, volume=v, target_timerange={"start": x0, "duration": y0 - x0})
        if st:
            c["source_timerange"] = {"start": src0 + int(round((x - ta) * sp)), "duration": int(round((y - x) * sp))}
        out.append({"seg": c, "mats": mats, "path": mats[0][1].get("path", "") or ""})

    walk(seg, draft, {}, 0, 1.0, a, b, 1.0)
    return sorted(out, key=lambda p: p["seg"]["target_timerange"]["start"])


def adopt(draft: dict, piece: dict, drop_cats=()) -> dict:
    """Add a lift() piece's materials to the draft, minus extras of drop_cats (e.g. common_mask); returns the segment."""
    s = piece["seg"]
    drop = {m["id"] for k, m in piece["mats"][1:] if k in drop_cats}
    for k, m in piece["mats"]:
        if m["id"] not in drop:
            draft["materials"].setdefault(k, []).append(m)
    s["extra_material_refs"] = [e for e in s.get("extra_material_refs") or [] if e not in drop]
    return s


def merge_ranges(ranges, tol: int = 0) -> list[tuple]:
    """Sorted union of [a, b) ranges; ranges closer than tol are joined."""
    out = []
    for x, y in sorted(ranges):
        if out and x <= out[-1][1] + tol:
            out[-1][1] = max(out[-1][1], y)
        else:
            out.append([x, y])
    return [tuple(r) for r in out]


def snap(t_s: float, fps: int) -> int:
    """Seconds -> us on the nearest frame boundary (frame k starts at trunc(k * 1e6 / fps), as in CapCut)."""
    return int(round(t_s * fps)) * 1_000_000 // fps


def parse_ranges(obj) -> list[tuple]:
    """[[a, b]] | [{"start": a, "end": b}] (seconds; b may be null = to the end) -> [(a, b | None)]."""
    if isinstance(obj, dict):
        obj = obj.get("ranges") or obj.get("pieces") or []
    out = []
    for r in obj:
        a, b = (r["start"], r.get("end")) if isinstance(r, dict) else (r[0], r[1] if len(r) > 1 else None)
        out.append((float(a), None if b is None else float(b)))
    return out


def full_camera_ranges(cfg: Config, draft: dict) -> list[tuple[int, int]]:
    """Timeline ranges (us) where the camera is on full screen: camera leaf pieces without a mask (any depth)."""
    tol = int(1e6 / cfg.fps)
    return merge_ranges([(p["start"], p["end"]) for p in flatten(cfg, draft, ("camera",)) if not p["mask"]], tol)


def f_ranges(cfg: Config, draft: dict) -> list[tuple[int, int]]:
    """Layout F on the timeline (us): full-screen camera in the draft + F rows of layout/layout.json."""
    rows = [(us(r["start"]), us(r["end"])) for r in read_layout(cfg) if r.get("layout") == "F"]
    return merge_ranges(full_camera_ranges(cfg, draft) + rows, int(1e6 / cfg.fps))


def layout_rows(f: list[tuple[int, int]], duration_us: int, old: list[dict] = ()) -> list[dict]:
    """Full layout over [0, duration): F ranges, S in between (seconds, 6 decimals); notes of identical old rows kept."""
    notes = {(round(r["start"], 3), round(r["end"], 3), r["layout"]): r["note"] for r in old if r.get("note")}
    rows, cur = [], 0
    for a, b in merge_ranges(f):
        a, b = max(a, 0), min(b, duration_us)
        if b <= a:
            continue
        if a > cur:
            rows.append(("S", cur, a))
        rows.append(("F", a, b))
        cur = b
    if cur < duration_us:
        rows.append(("S", cur, duration_us))
    out = []
    for lay, a, b in rows:
        r = {"start": round(a / 1e6, 6), "end": round(b / 1e6, 6), "layout": lay}
        n = notes.get((round(r["start"], 3), round(r["end"], 3), lay))
        if n:
            r["note"] = n
        out.append(r)
    return out


# ---- work-dir files shared by stages ----
def read_layout(cfg: Config) -> list[dict]:
    """layout/layout.json rows [{start, end, layout: S|F, note?}] (seconds), [] if absent."""
    p = cfg.work_dir / "layout" / "layout.json"
    return json.loads(p.read_text(encoding="utf-8")).get("layout", []) if p.is_file() else []


def write_layout(cfg: Config, rows: list[dict], **extra) -> Path:
    p = cfg.work_dir / "layout" / "layout.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    old.update(extra, layout=rows)
    p.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def update_layout(cfg: Config, fn) -> bool:
    """Apply fn(obj) -> obj to layout/layout.json in place; False if there is no layout.json."""
    p = cfg.work_dir / "layout" / "layout.json"
    if not p.is_file():
        return False
    obj = fn(json.loads(p.read_text(encoding="utf-8")))
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def layout_cut(obj: dict, cuts: list[tuple[int, int]]) -> dict:
    """layout.json content after a ripple cut of [a, b) us ranges: rows and f_segments mapped through the cuts
    (common.map_through_cuts), rows that vanish are dropped. Counterpart of layout_insert."""
    rows = []
    for r in obj.get("layout", []):
        a, b = map_through_cuts(us(r["start"]), cuts), map_through_cuts(us(r["end"]), cuts)
        if b > a:
            rows.append(dict(r, start=round(a / 1e6, 6), end=round(b / 1e6, 6)))
    segs = []
    for f in obj.get("f_segments", []):
        a, b = (map_through_cuts(x, cuts) for x in f["timeline_us"])
        if b > a:
            segs.append(dict(f, timeline_us=[a, b]))
    out = dict(obj, layout=rows)
    if "f_segments" in obj:
        out["f_segments"] = segs
    return out


def layout_insert(obj: dict, pieces: list[tuple[int, int]], L: int, note: str = "хук (этап 4)") -> dict:
    """layout.json content after copies of the timeline pieces [(a, b)] us (total L) were put at the start (stage 4):
    rows for the copies in front (the layout of the copied parts; S where nothing was), everything else + L,
    f_segments + L."""
    rows = obj.get("layout", [])
    out, off = [], 0
    for a, b in pieces:
        tag = f"{note}: копия {a / 1e6:.3f}–{b / 1e6:.3f}"
        for r in rows:
            x, y = max(us(r["start"]), a), min(us(r["end"]), b)
            if y > x:
                out.append({"start": round((off + x - a) / 1e6, 6), "end": round((off + y - a) / 1e6, 6),
                            "layout": r["layout"], "note": tag})
        if not any(us(r["start"]) < b and us(r["end"]) > a for r in rows):
            out.append({"start": round(off / 1e6, 6), "end": round((off + b - a) / 1e6, 6), "layout": "S", "note": tag})
        off += b - a
    out += [dict(r, start=round(r["start"] + L / 1e6, 6), end=round(r["end"] + L / 1e6, 6)) for r in rows]
    res = dict(obj, layout=out)
    if "f_segments" in obj:
        res["f_segments"] = [dict(f, timeline_us=[x + L for x in f["timeline_us"]]) for f in obj["f_segments"]]
    return res


def layout_of(rows: list[dict], a: float, b: float) -> set:
    """Layouts ('S'/'F') that the rows give over [a, b) seconds; an uncovered part counts as 'S'."""
    hit = {r["layout"] for r in rows if r["start"] < b and r["end"] > a}
    covered = sorted((max(r["start"], a), min(r["end"], b)) for r in rows if r["start"] < b and r["end"] > a)
    if subtract_ranges(a, b, covered):
        hit.add("S")
    return hit


def timeline_words(cfg: Config) -> list[dict]:
    """Words of stage3/transcript_timeline.json (timeline seconds), sorted; [] if absent."""
    p = cfg.work_dir / "stage3" / "transcript_timeline.json"
    if not p.is_file():
        return []
    tt = json.loads(p.read_text(encoding="utf-8"))
    return sorted((w for s in tt["segments"] for w in s["words"]), key=lambda w: w["start"])


def inside_word(words: list[dict], t: float, tol: float = 0.0) -> dict | None:
    """The word that the time t (s) falls strictly inside (more than tol from both edges), else None."""
    return next((w for w in words if w["start"] + tol < t < w["end"] - tol), None)


# ---- screen frames (2 fps, 256x144 grey) ----
FW, FH, FPS2 = 256, 144, 2.0


def screen_mask():
    import numpy as np
    m = np.ones((FH, FW), bool)
    m[92:, 167:] = False   # bottom right: camera circle / overlays
    m[140:, :] = False     # bottom strip: taskbar clock
    return m


def screen_frames(path: str, cache: Path, dry: bool = False):
    """All frames of a screencast file at FPS2, FWxFH grey (cached in cache/<name>.gray); None if not cached and dry."""
    import numpy as np
    out = Path(cache) / (Path(path).name + ".gray")
    if not out.is_file():
        if dry:
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", f"fps={FPS2},scale={FW}:{FH},format=gray",
                        "-f", "rawvideo", str(out)], check=True)
    return np.fromfile(out, dtype=np.uint8).reshape(-1, FH, FW)


# ---- OCR (tesseract rus+eng) ----
TESSERACT_DEFAULT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def tesseract(cfg: Config) -> tuple[str, dict]:
    """(tesseract exe, env) with rus+eng available: cfg.tessdata, else TESSDATA_PREFIX, else the install's tessdata.
    SystemExit with what to do if tesseract or the rus/eng data is missing."""
    exe = shutil.which("tesseract") or (str(TESSERACT_DEFAULT) if TESSERACT_DEFAULT.is_file() else None)
    if not exe:
        raise SystemExit("tesseract не найден: установить Tesseract-OCR (UB Mannheim) или добавить в PATH")
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    if cfg.tessdata:
        env["TESSDATA_PREFIX"] = str(cfg.tessdata)
    out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, env=env)
    langs = set((out.stdout + out.stderr).split())
    if not {"rus", "eng"} <= langs:
        raise SystemExit(f"tesseract: нет языков rus/eng ({sorted(langs)[:8]}…): положить rus.traineddata и "
                         "eng.traineddata в папку и указать её в config.json → tessdata")
    return exe, env


def ocr_rows(exe: str, env: dict, img: Path, out_base: Path, psm: int = 11) -> list[dict]:
    """tesseract TSV of img (cached as <out_base>.tsv): words [{l, t, w, h, conf, text, block, par, line}] (px of img)."""
    tsv = Path(str(out_base) + ".tsv")
    if not (tsv.is_file() and tsv.stat().st_size):
        tsv.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([exe, str(img), str(out_base), "-l", "rus+eng", "--psm", str(psm), "tsv"], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return read_tsv(tsv)


def read_tsv(tsv: Path) -> list[dict]:
    """Words of a tesseract TSV: [{l, t, w, h, conf, text, block, par, line}]; [] if the file is absent."""
    rows = []
    if not Path(tsv).is_file():
        return rows
    for line in Path(tsv).read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        p = line.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        try:
            rows.append({"block": int(p[2]), "par": int(p[3]), "line": int(p[4]), "l": int(p[6]), "t": int(p[7]),
                         "w": int(p[8]), "h": int(p[9]), "conf": float(p[10]), "text": p[11].strip()})
        except ValueError:
            continue
    return rows


def grab_frame(path: str, t: float, out: Path) -> Path:
    """One frame of a video file at t seconds -> out (png/jpg), cached."""
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(t, 0):.3f}", "-i", path,
                        "-frames:v", "1", "-q:v", "2", str(out)], check=True)
    return out


def overlap_errors(track: dict, label: str | None = None) -> list[str]:
    """Segments of one track that overlap (> 1 us), as validation messages."""
    name = label or track.get("name") or track["type"]
    ss = by_start(track["segments"])
    return [f"overlap on {name} at {seg_end(p) / 1e6:.3f}" for p, q in zip(ss, ss[1:])
            if seg_end(p) > q["target_timerange"]["start"] + 1]


def draft_overlaps(draft: dict) -> list[str]:
    """overlap_errors over every top-level track."""
    return [e for i, t in enumerate(draft["tracks"]) for e in overlap_errors(t, t.get("name") or f"{t['type']}#{i}")]


def piece_overlaps(pieces: list[dict], tol: int = 1) -> list[str]:
    """Flat pieces (common.flatten) that overlap in timeline time (> tol us), as messages with the range and both
    files — e.g. voice pieces of the dump lying on top of each other (they would be mixed into one transcript)."""
    out, cur = [], None
    for p in sorted(pieces, key=lambda x: x["start"]):
        if cur is not None and p["start"] < cur["end"] - tol:
            out.append(f"{p['start'] / 1e6:.3f}–{min(p['end'], cur['end']) / 1e6:.3f} s: "
                       f"{Path(cur['path']).name} and {Path(p['path']).name}")
        if cur is None or p["end"] > cur["end"]:
            cur = p
    return out


def gap_count(track) -> int:
    """Holes (> 1 us) between consecutive segments of a track."""
    segs = by_start(track["segments"])
    return sum(1 for p, q in zip(segs, segs[1:]) if q["target_timerange"]["start"] - seg_end(p) > 1)


def us(sec: float) -> int:
    return int(round(sec * 1_000_000))


def sec(us: int) -> float:
    return us / 1_000_000


_ID_KEYS = {"resource_id", "effect_id", "id"}


def _json_has_id(obj, rid: str) -> bool:
    if isinstance(obj, dict):
        return any((k in _ID_KEYS and str(v) == rid) or _json_has_id(v, rid) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_json_has_id(v, rid) for v in obj)
    return False


def find_effect_cache(resource_id: str, cache_root: Path | None = None) -> Path | None:
    """Cache/effect/<dir> whose name equals resource_id, or whose JSON (extra.json etc.) has
    resource_id/effect_id/id == resource_id exactly. None if not found or LOCALAPPDATA unset."""
    root = Path(cache_root) if cache_root else EFFECT_CACHE
    if root is None or not root.is_dir():
        return None
    rid = str(resource_id)
    dirs = sorted(d for d in root.iterdir() if d.is_dir())
    for d in dirs:
        if d.name == rid:
            return d
    for d in dirs:
        for j in d.rglob("*.json"):
            try:
                if _json_has_id(json.loads(j.read_text(encoding="utf-8", errors="ignore")), rid):
                    return d
            except (OSError, ValueError):
                pass
    return None
