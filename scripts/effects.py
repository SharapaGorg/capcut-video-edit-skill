"""Clone CapCut effect templates (assets/templates/*.json) into a draft.

Templates are harvested by harvest_templates.py; format and rules: references/capcut-format.md
("Шаблоны эффектов"). Placeholders: {{ID}} -> fresh id, {{CACHE}}/<cache_id>/<hash>/... -> the
actual Cache/effect dir found by find_effect_cache(cache_id), {{CAPCUT_APP}}/... -> newest
CapCut/Apps/<version> dir. Nothing is added to the draft if any placeholder cannot be resolved.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import common
from common import find_effect_cache, new_id

TEMPLATES = Path(__file__).resolve().parent.parent / "assets" / "templates"
_CACHE_RE = re.compile(r"^\{\{CACHE\}\}/([^/]+)(?:/([^/]+))?(/.*)?$")
_APP = "{{CAPCUT_APP}}/"


class EffectCacheMissing(RuntimeError):
    def __init__(self, name: str, resource_id: str):
        self.name, self.resource_id = name, resource_id
        super().__init__(f'Эффект "{name}" не найден в кэше CapCut (resource_id {resource_id}): '
                         "примените его в CapCut один раз вручную, затем повторите")


def load_template(name: str) -> dict:
    return json.loads((TEMPLATES / f"{name}.json").read_text(encoding="utf-8"))


def _app_dir(cache_root: Path | None) -> Path | None:
    root = Path(cache_root) if cache_root else common.EFFECT_CACHE
    if root is None:
        return None
    apps = root.parents[2] / "Apps"  # <CapCut>/User Data/Cache/effect -> <CapCut>/Apps
    vers = [d for d in apps.iterdir() if d.is_dir()] if apps.is_dir() else []
    key = lambda d: [int(x) if x.isdigit() else -1 for x in d.name.split(".")]  # noqa: E731
    return max(vers, key=key) if vers else None


def _resolve(obj, tpl: dict, cache_root):
    """Deep-copy with placeholders resolved. Raises EffectCacheMissing."""
    found: dict[str, Path | None] = {}
    app = []

    def res_str(s: str):
        if s == "{{ID}}":
            return new_id()
        m = _CACHE_RE.match(s)
        if m:
            cid, h, rest = m.group(1), m.group(2), m.group(3) or ""
            if cid not in found:
                found[cid] = find_effect_cache(cid, cache_root)
            d = found[cid]
            if d is None:
                raise EffectCacheMissing(tpl["name"], tpl.get("resource_id") or cid)
            if h:
                if not (d / h).is_dir():
                    subs = sorted(x for x in d.iterdir() if x.is_dir())
                    if subs:
                        h = subs[0].name
                d = d / h
            return (d.as_posix() + rest)
        if s.startswith(_APP):
            if not app:
                app.append(_app_dir(cache_root))
            if app[0] is None:
                raise EffectCacheMissing(tpl["name"], tpl.get("resource_id") or "CapCut/Apps")
            return app[0].as_posix() + "/" + s[len(_APP):]
        return s

    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, str):
            return res_str(o)
        return o

    return walk(copy.deepcopy(obj))


def _set_dotted(d: dict, key: str, value) -> None:
    parts = key.split(".")
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def _build(name: str, cache_root, overrides) -> tuple[dict, list[tuple[str, dict]]]:
    tpl = load_template(name)
    if not tpl.get("category") or tpl.get("material") is None:
        raise ValueError(f"template {name} has no material (use the dedicated helper)")
    items = [(tpl["category"], tpl["material"])] + [(e["category"], e["material"]) for e in tpl.get("extra", [])]
    built = [(cat, _resolve(m, tpl, cache_root)) for cat, m in items]
    for k, v in overrides.items():
        _set_dotted(built[0][1], k, v)
    return tpl, built


def _append(draft: dict, built) -> list[str]:
    mats = draft.setdefault("materials", {})
    for cat, m in built:
        mats.setdefault(cat, []).append(m)
    return [m["id"] for _, m in built]


def make_all(name: str, draft: dict, cache_root=None, **overrides) -> list[str]:
    """Like make(), returns ids of the primary material and of all template extras (e.g. adjust_circle:
    temperature, saturation, hsl). Overrides apply to the primary material only."""
    _tpl, built = _build(name, cache_root, overrides)
    return _append(draft, built)


def make(name: str, draft: dict, cache_root=None, **overrides) -> str:
    """Clone template <name> into draft['materials'][<category>] (+ its extras), return primary id.
    Overrides: dotted keys into the primary material, e.g. **{'config.centerX': 0.5}."""
    return make_all(name, draft, cache_root=cache_root, **overrides)[0]


def attach(seg: dict, material_id: str) -> None:
    refs = seg.setdefault("extra_material_refs", [])
    if material_id not in refs:
        refs.append(material_id)


# ---- zoom ----
def zoom_keyframes(seg: dict, t_in: float, t_hold: float, t_out: float, scale: float,
                   cx: float = 0.0, cy: float = 0.0) -> None:
    """Zoom on a segment; times in seconds from segment start.
    t_in: zoom-in starts (1.0); ramp = t_out - t_hold; t_in+ramp .. t_hold: hold at `scale`;
    t_out: back to 1.0. cx/cy: clip.transform x/y at full zoom (PositionX/Y keys only if non-zero).
    Replaces existing Scale/Position keyframes. ValueError if any key falls outside the segment."""
    dur = seg["target_timerange"]["duration"]
    ramp = t_out - t_hold
    times = [common.us(t) for t in (t_in, t_in + ramp, t_hold, t_out)]
    if not (ramp > 0 and 0 <= times[0] < times[1] <= times[2] < times[3] <= dur):
        raise ValueError(f"zoom keys {times} us must be increasing and within segment duration {dur} us "
                         f"(t_in + (t_out - t_hold) <= t_hold)")
    tpl = load_template("keyframes_zoom")
    props = {"KFTypeScaleX": [1.0, scale, scale, 1.0], "KFTypeScaleY": [1.0, scale, scale, 1.0]}
    if cx or cy:
        props["KFTypePositionX"] = [0.0, cx, cx, 0.0]
        props["KFTypePositionY"] = [0.0, cy, cy, 0.0]
    kept = [c for c in seg.get("common_keyframes") or []
            if c.get("property_type") not in ("KFTypeScaleX", "KFTypeScaleY", "KFTypePositionX", "KFTypePositionY")]
    for prop, vals in props.items():
        e = copy.deepcopy(tpl["entry"])
        e.update(id=new_id(), property_type=prop, keyframe_list=[])
        for t, v in zip(times, vals):
            k = copy.deepcopy(tpl["keyframe"])
            k.update(id=new_id(), time_offset=t, values=[float(v)])
            e["keyframe_list"].append(k)
        kept.append(e)
    seg["common_keyframes"] = kept
    clip = seg.get("clip")
    if isinstance(clip, dict):
        clip.setdefault("scale", {})
        clip["scale"].update(x=1.0, y=1.0)


# ---- audio ----
def _audio_segment(name: str, draft, track, path, start_us, duration_us, volume) -> str:
    tpl = load_template(name)
    mat = _resolve(tpl["material"], tpl, None)
    p = str(path).replace("\\", "/")
    mat.update(path=p, name=Path(p).name, duration=int(duration_us))
    extras = [(e["category"], _resolve(e["material"], tpl, None)) for e in tpl.get("extra", [])]
    _append(draft, [(tpl["category"], mat)] + extras)
    seg = _resolve(tpl["segment"], tpl, None)
    seg.update(material_id=mat["id"], extra_material_refs=[m["id"] for _, m in extras], volume=float(volume),
               source_timerange={"start": 0, "duration": int(duration_us)},
               target_timerange={"start": int(start_us), "duration": int(duration_us)})
    track.setdefault("segments", []).append(seg)
    return seg["id"]


def sfx_segment(draft: dict, track: dict, path, start_us: int, duration_us: int, volume: float) -> str:
    """Add an SFX audio material + segment to track; returns segment id. material.duration = duration_us
    (set the real file length afterwards if the clip is trimmed)."""
    return _audio_segment("sfx_segment", draft, track, path, start_us, duration_us, volume)


def music_segment(draft: dict, track: dict, path, start_us: int, duration_us: int, volume: float) -> str:
    """Like sfx_segment, with audio_fades. Deep: make('deep_effect', draft) + attach(seg, id)."""
    return _audio_segment("music_segment", draft, track, path, start_us, duration_us, volume)
