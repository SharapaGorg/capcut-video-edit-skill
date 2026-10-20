"""Harvest CapCut effect templates from a finished project into assets/templates/*.json.

    python -X utf8 scripts/harvest_templates.py --project <CapCut project dir> --out assets/templates
    python -X utf8 scripts/harvest_templates.py --config config.json --out assets/templates

Looks for one instance of each structure in the root draft_content.json, nested drafts
(materials.drafts[].draft) and subdraft/*/draft_content.json. Sanitizes:
  - every UUID string -> "{{ID}}" (effects.make generates fresh ids);
  - "<...>/Cache/effect/<tail>" -> "{{CACHE}}/<tail>" (first tail part = cache dir name);
  - "<...>/CapCut/Apps/<ver>/<tail>" -> "{{CAPCUT_APP}}/<tail>";
  - any other absolute path -> "" (audio material path/name -> "{{PATH}}"/"{{NAME}}").
resource_id / effect_id are kept. Format: references/capcut-format.md, section "Шаблоны эффектов".
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import index, load_config  # noqa: E402

UUID = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
CACHE = re.compile(r"^.*/Cache/effect/(.+)$")
APPS = re.compile(r"^.*/CapCut/Apps/[^/]+/(.+)$")
ABS = re.compile(r"^([A-Za-z]:[/\\]|/|\\\\)")

UI_TO_JSON = 0.02  # UI -> JSON; confirmed on video 1: temperature UI -27 -> -0.54 (PROGRESS)
TEMP, SAT = -18 * UI_TO_JSON, 10 * UI_TO_JSON


class NotFound(SystemExit):
    pass


def sanitize(o):
    if isinstance(o, dict):
        return {k: sanitize(v) for k, v in o.items()}
    if isinstance(o, list):
        return [sanitize(v) for v in o]
    if isinstance(o, str):
        if UUID.match(o):
            return "{{ID}}"
        s = o.replace("\\", "/")
        m = CACHE.match(s)
        if m:
            return "{{CACHE}}/" + m.group(1)
        m = APPS.match(s)
        if m:
            return "{{CAPCUT_APP}}/" + m.group(1)
        if ABS.match(o):
            return ""
    return o


def cache_id(mat) -> str | None:
    m = CACHE.match(str((mat or {}).get("path", "")).replace("\\", "/"))
    return m.group(1).split("/")[0] if m else None


def need(x, what):
    if x is None:
        raise NotFound(f"NEEDS_CONTEXT: not found in project: {what}")
    return x


def all_drafts(project: Path) -> list[dict]:
    out: list[dict] = []

    def walk(d):
        out.append(d)
        for dm in d.get("materials", {}).get("drafts", []) or []:
            if isinstance(dm.get("draft"), dict):
                walk(dm["draft"])

    walk(json.loads((project / "draft_content.json").read_text(encoding="utf-8")))
    for f in sorted(glob.glob(str(project / "subdraft" / "*" / "draft_content.json"))):
        walk(json.loads(Path(f).read_text(encoding="utf-8")))
    return out


def seg_iter(d):
    for t in d.get("tracks", []):
        for s in t.get("segments", []):
            yield t, s


def first_mat(drafts, cat, pred):
    for d in drafts:
        for m in d.get("materials", {}).get(cat, []) or []:
            if isinstance(m, dict) and pred(m):
                return m
    return None


def material_tpl(name, cat, mat, notes, overrides=None, extra=()):
    mat = copy.deepcopy(mat)
    mat.update(overrides or {})
    return {"name": name, "category": cat, "resource_id": mat.get("resource_id") or None,
            "cache_id": cache_id(mat), "material": sanitize(mat),
            "extra": [{"category": c, "cache_id": cache_id(m), "material": sanitize(copy.deepcopy(m))}
                      for c, m in extra],
            "segment": None, "notes": notes}


def seg_tpl(seg):
    s = copy.deepcopy(seg)
    s["extra_material_refs"] = []
    s["common_keyframes"] = []
    return sanitize(s)


def harvest(project: Path) -> dict[str, dict]:
    drafts = all_drafts(project)
    out: dict[str, dict] = {}

    vc = copy.deepcopy(need(first_mat(drafts, "audio_effects", lambda m: "Crisper" in (m.get("name") or "")),
                            "Voice Crisper"))
    for p in vc.get("audio_adjust_params") or []:
        if p.get("name") == "strength":
            p["value"] = 1.0
    out["voice_crisper"] = material_tpl(
        "voice_crisper", "audio_effects", vc,
        "Voice changer > Voice filters > Voice Crisper, Strength 100 (strength 1.0). On voice segments.")
    dn = need(first_mat(drafts, "realtime_denoises", lambda m: m.get("is_denoise")), "realtime_denoises")
    out["reduce_noise"] = material_tpl(
        "reduce_noise", "realtime_denoises", dn,
        "Basic > Reduce noise. path is a model inside {{CAPCUT_APP}} (installed CapCut version dir), not Cache/effect.")
    deep = need(first_mat(drafts, "audio_effects", lambda m: m.get("name") == "Deep"), "Deep voice filter")
    out["deep_effect"] = material_tpl(
        "deep_effect", "audio_effects", deep, "Voice changer > Voice filters > Deep. On music segments.")
    mask = need(first_mat(drafts, "common_mask",
                          lambda m: m.get("type") == "mask" and m.get("resource_type") == "circle"), "circle mask")
    out["mask_circle"] = material_tpl(
        "mask_circle", "common_mask", mask,
        "Circle mask for the camera circle. type mask, category video; path -> Cache/effect/<cache_id>/... "
        "(cache_id differs from resource_id). config = position/size.")

    # clip-level Adjust: a segment carrying temperature + saturation effects (+ hsl)
    refs = None
    for d in drafts:
        ix = index(d.get("materials", {}))
        for _t, s in seg_iter(d):
            r = [ix[e] for e in s.get("extra_material_refs") or [] if e in ix]
            types = {m.get("type") for k, m in r if k == "effects"}
            if {"temperature", "saturation"} <= types and any(k == "hsl" for k, _ in r):
                refs = r
                break
        if refs:
            break
    refs = need(refs, "clip with temperature + saturation effects and hsl")
    temp = next(m for k, m in refs if k == "effects" and m["type"] == "temperature")
    sat = dict(copy.deepcopy(next(m for k, m in refs if k == "effects" and m["type"] == "saturation")), value=SAT)
    hsl = next(m for k, m in refs if k == "hsl")
    out["adjust_circle"] = material_tpl(
        "adjust_circle", "effects", temp,
        "Adjust on a clip (camera circle): primary = temperature (UI -18 -> -0.36), extra = saturation "
        "(UI 10 -> 0.2) + hsl. make_all() -> all ids, attach each; segment enable_adjust/enable_hsl = true.",
        overrides={"value": TEMP}, extra=[("effects", sat), ("hsl", hsl)])

    # Adjustment block: segment on a track of type adjust
    blk = None
    for d in drafts:
        ix = index(d.get("materials", {}))
        for t, s in seg_iter(d):
            if t.get("type") == "adjust" and s.get("material_id") in ix:
                blk = (s, ix[s["material_id"]])
                break
        if blk:
            break
    s, (pcat, pmat) = need(blk, "adjust-track segment")
    tpl = material_tpl(
        "adjustment_block", pcat, pmat,
        "Adjustment block on a track of type adjust: material in placeholders (type adjust); extra = temperature "
        "-0.36, saturation 0.2, hsl. Segment: source_timerange null, enable_adjust/enable_hsl true. "
        "One continuous block per full-screen camera run.",
        overrides={"name": "Adjust1"},
        extra=[("effects", dict(copy.deepcopy(temp), value=TEMP)), ("effects", sat), ("hsl", hsl)])
    tpl["segment"] = seg_tpl(s)
    out["adjustment_block"] = tpl

    # zoom keyframes
    kf = None
    for d in drafts:
        for _t, s in seg_iter(d):
            c = next((c for c in s.get("common_keyframes") or []
                      if c.get("property_type") in ("KFTypeScaleX", "KFTypeScaleY") and c.get("keyframe_list")), None)
            if c:
                kf = (s, c)
                break
        if kf:
            break
    s, c = need(kf, "segment with KFTypeScaleX/Y keyframes")
    entry = copy.deepcopy(c)
    k0 = next((k for k in entry["keyframe_list"] if k.get("curveType") == "Line"), entry["keyframe_list"][0])
    k0 = dict(k0, curveType="Line", left_control={"x": 0.0, "y": 0.0}, right_control={"x": 0.0, "y": 0.0})
    entry["keyframe_list"] = []
    out["keyframes_zoom"] = {
        "name": "keyframes_zoom", "category": None, "resource_id": None, "cache_id": None,
        "material": None, "extra": [], "segment": None,
        "entry": sanitize(entry), "keyframe": sanitize(k0), "clip": sanitize(s.get("clip")),
        "notes": "segment.common_keyframes: one entry per property_type (KFTypeScaleX/Y, KFTypePositionX/Y); "
                 "keyframe_list[].time_offset = us from segment start, values [v]. Creates no materials.",
    }

    def audio_tpl(name, pred, notes, drop=("audio_effects",)):
        for d in drafts:
            ix = index(d.get("materials", {}))
            for t, s in seg_iter(d):
                if t.get("type") == "audio" and pred((t.get("name") or "").lower()) and s.get("material_id") in ix:
                    cat, mat = ix[s["material_id"]]
                    mat = dict(copy.deepcopy(mat), path="{{PATH}}", name="{{NAME}}", unique_id="")
                    extra = [ix[e] for e in s.get("extra_material_refs") or [] if e in ix and ix[e][0] not in drop]
                    tp = material_tpl(name, cat, mat, notes, extra=extra)
                    tp["segment"] = seg_tpl(s)
                    return tp
        return None

    out["sfx_segment"] = need(audio_tpl(
        "sfx_segment", lambda n: "sfx" in n,
        "SFX: material audios (extract_music) + per-segment extra materials (speeds, placeholder_infos, beats, "
        "sound_channel_mappings, loudnesses, vocal_separations)."), "SFX audio segment (track named SFX)")
    out["music_segment"] = need(audio_tpl(
        "music_segment", lambda n: "музык" in n or "music" in n,
        "Music: like SFX + audio_fades. Deep is not included: make('deep_effect') + attach."),
        "music audio segment (track named Музыка/Music)")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Harvest CapCut effect templates")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--project", help="CapCut project dir (com.lveditor.draft/<name>)")
    g.add_argument("--config", help="config.json of the video (uses project_dir)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "assets" / "templates"))
    a = ap.parse_args(argv)
    project = Path(a.project) if a.project else load_config(a.config).project_dir
    res = harvest(project)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, tpl in res.items():
        (out / f"{name}.json").write_text(json.dumps(tpl, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{name}.json  category={tpl['category']}  resource_id={tpl['resource_id']}  cache_id={tpl['cache_id']}")


if __name__ == "__main__":
    main()
