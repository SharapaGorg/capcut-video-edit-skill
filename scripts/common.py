"""Shared helpers for video-edit scripts: config, CapCut draft read/write, id/time helpers.

Write rules (references/capcut-format.md): CapCut.exe must be 0 processes, backup the
project dir, write BOTH root draft_content.json and Timelines/<id>/draft_content.json,
bump update_time, then guard mtime (CapCut must not rewrite the file).
"""
from __future__ import annotations

import functools
import json
import os
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
    description_md: str | None = None
    config_path: Path | None = None


def detect_timeline_id(project_dir) -> str:
    tl = Path(project_dir) / "Timelines"
    dirs = sorted(p.name for p in tl.iterdir() if p.is_dir()) if tl.is_dir() else []
    if len(dirs) != 1:
        raise ValueError(f"expected exactly one folder in {tl} (Timelines), found {len(dirs)}: {dirs}")
    return dirs[0]


def load_config(path: str | None = None) -> Config:
    p = Path(path) if path else Path.cwd() / "config.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    project_dir = Path(raw["project_dir"])
    tid = raw.get("timeline_id") or detect_timeline_id(project_dir)
    src = dict(raw.get("sources") or {})
    src.setdefault("voice", None)
    return Config(
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
        description_md=raw.get("description_md"),
        config_path=p.resolve(),
    )


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


# ---- source files ----
ROLE_DIRS = (("camera", "camera"), ("screencast", "screencasts"), ("voice", "voice"))


def _norm(p) -> str:
    return str(p).replace("\\", "/").rstrip("/").lower()


@functools.lru_cache(maxsize=64)
def _listing(d: str) -> frozenset:
    p = Path(d)
    return frozenset(x.name.lower() for x in p.iterdir() if x.is_file()) if p.is_dir() else frozenset()


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
    name = Path(str(path).replace("\\", "/")).name.lower()
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
    """Source pieces of the given roles, also inside compounds, in timeline time (us), sorted by start:
    [{path, role, start, dur, src, speed, volume}]. Nested pieces are clipped to the window the outer segment shows;
    speed of compound segments is applied (speed = effective speed of the piece)."""
    out = []

    def walk(d, off, k, lo, hi, dix):  # timeline = off + (time inside d) / k; visible window [lo, hi)
        ix = index(d.get("materials", {}))
        dix = _drafts_ix(d, dix)
        for t in d.get("tracks", []):
            for s in t.get("segments", []):
                if s.get("material_id") not in ix:
                    continue
                m = ix[s["material_id"]][1]
                dm = next((dix[e] for e in s.get("extra_material_refs") or [] if e in dix), None)
                a = off + s["target_timerange"]["start"] / k
                b = off + seg_end(s) / k
                a2, b2 = max(a, lo), min(b, hi)
                if b2 <= a2:
                    continue
                sp = float(s.get("speed", 1.0)) * k
                src0 = (s.get("source_timerange") or {}).get("start", 0)
                if dm is not None and isinstance(dm.get("draft"), dict):
                    walk(dm["draft"], a - src0 / sp, sp, a2, b2, dix)
                    continue
                role = source_role(cfg, m.get("path", ""))
                if role in roles:
                    out.append({"path": m["path"], "role": role, "start": int(round(a2)), "dur": int(round(b2 - a2)),
                                "speed": sp, "src": src0 + int(round((a2 - a) * sp)), "volume": float(s.get("volume", 1.0))})

    walk(draft, 0, 1.0, 0, 1 << 62, {})
    return sorted(out, key=lambda x: x["start"])


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
