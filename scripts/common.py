"""Shared helpers for video-edit scripts: config, CapCut draft read/write, id/time helpers.

Write rules (references/capcut-format.md): CapCut.exe must be 0 processes, backup the
project dir, write BOTH root draft_content.json and Timelines/<id>/draft_content.json,
bump update_time, then guard mtime (CapCut must not rewrite the file).
"""
from __future__ import annotations

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
    )


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
    """Dangling material refs in the draft and nested drafts (materials.drafts[].draft)."""
    errs: list[str] = []

    def walk(d, label):
        jx = index(d.get("materials", {}))
        for t in d.get("tracks", []):
            for s in t.get("segments", []):
                for mid in [s.get("material_id")] + list(s.get("extra_material_refs") or []):
                    if mid and mid not in jx:
                        errs.append(f"{label}: dangling ref {mid} in segment {s.get('id')}")
        for dm in d.get("materials", {}).get("drafts", []) or []:
            if isinstance(dm.get("draft"), dict):
                walk(dm["draft"], f"{label}/{dm.get('id')}")

    walk(draft, "outer")
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
