"""Stage 5, step 6: burn the blur into a copy of the screencast and point the project at it. Only after approval.

    python -X utf8 scripts/stage5/apply_censor.py --config config.json [--dry] [--encode-only]

Input: <work_dir>/stage5/censor_findings.json, findings with apply true: {file, src_start, src_end,
bbox: [x, y, w, h] | boxes: [{t, bbox}]} (source seconds / px).
Blur: boxblur 20 on bbox + 10 px, from src_start − 0.5 s to src_end + 0.5 s; a moving area -> a box per OCR second.
New file <work_dir>/stage5/censored/<stem>_censored.mp4: same resolution and fps, libx264 CRF 16, audio copied
(not re-encoded); duration / fps / size checked against the source (else stop). Only files with findings; an
existing valid output is reused (encode in the background: run with --encode-only first).
Project: the path of every video material of that file (top level and nested compounds) -> the censored copy;
segments untouched. Both drafts + subdraft/ wrappers via common.write_draft; draft_meta_info paths too.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stage2"))
import common  # noqa: E402
import make_compound as mc  # noqa: E402

PAD, BLUR, TPAD, CRF = 10, 20, 0.5, 16


def probe(p) -> tuple[dict, float]:
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate,pix_fmt:format=duration", "-of", "json", str(p)],
                       capture_output=True, text=True).stdout
    j = json.loads(o or "{}")
    if not j.get("streams"):
        raise SystemExit(f"ffprobe: no video stream in {p}")
    return j["streams"][0], float(j["format"]["duration"])


def build_filter(items: list[dict], W: int, H: int) -> tuple[str, str]:
    """split -> crop -> boxblur -> overlay(enable) per finding (and per box of a moving one)."""
    chains, last, n = [], "[0:v]", 0
    for it in items:
        boxes = it.get("boxes") or [{"t": it["src_start"], "bbox": it["bbox"]}]
        for i, b in enumerate(boxes):
            x, y, w, h = b["bbox"]
            x0, y0 = max(0, x - PAD), max(0, y - PAD)
            x1, y1 = min(W, x + w + PAD), min(H, y + h + PAD)
            w2, h2 = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
            if w2 < 4 or h2 < 4:
                continue
            r = max(2, min(BLUR, min(w2, h2) // 4 - 1))   # chroma plane radius limit (yuv420): narrow strips -> smaller r, power 2
            t1 = b["t"] if i > 0 else it["src_start"] - TPAD
            t2 = boxes[i + 1]["t"] if i + 1 < len(boxes) else it["src_end"] + TPAD
            chains.append(f"{last}split[a{n}][b{n}];[b{n}]crop={w2}:{h2}:{x0}:{y0},boxblur={r}:2[c{n}];"
                          f"[a{n}][c{n}]overlay={x0}:{y0}:enable='between(t,{max(t1, 0):.3f},{t2:.3f})'[v{n}]")
            last = f"[v{n}]"
            n += 1
    return ";".join(chains), last


def out_path(cfg, src: Path) -> Path:
    return cfg.work_dir / "stage5" / "censored" / f"{src.stem}_censored.mp4"


def same_format(a: Path, b: Path) -> bool:
    (s1, d1), (s2, d2) = probe(a), probe(b)
    return abs(d1 - d2) < 0.05 and s1["r_frame_rate"] == s2["r_frame_rate"] and (s1["width"], s1["height"]) == (s2["width"], s2["height"])


def encode(cfg, src: Path, items: list[dict], dry: bool) -> Path:
    s, dur = probe(src)
    W, H = s["width"], s["height"]
    out = out_path(cfg, src)
    fc, last = build_filter(items, W, H)
    print(f"== {src.name}: {len(items)} findings -> {out.name} ({W}x{H} {s['codec_name']} {s['r_frame_rate']} fps, {dur:.3f} s)")
    if dry:
        print("   filter_complex:", fc[:400] + ("..." if len(fc) > 400 else ""))
        return out
    if out.is_file() and same_format(src, out):
        print("   exists, format OK — not re-encoded")
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    logs = cfg.work_dir / "stage5" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "warning", "-stats", "-i", str(src), "-filter_complex", fc,
           "-map", last, "-map", "0:a?", "-c:v", "libx264", "-preset", "slow", "-crf", str(CRF), "-pix_fmt",
           s["pix_fmt"], "-r", s["r_frame_rate"], "-c:a", "copy", "-movflags", "+faststart", str(out)]
    t0 = time.time()
    with open(logs / f"encode_{src.stem}.log", "w", encoding="utf-8") as log:
        r = subprocess.run(cmd, stdout=log, stderr=log)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg failed, see {logs / f'encode_{src.stem}.log'}")
    if not same_format(src, out):
        raise SystemExit(f"{out.name}: duration / fps / size differ from the source — stop")
    print(f"   done in {time.time() - t0:.0f} s, format = source")
    return out


def sources(cfg, draft: dict) -> dict[str, Path]:
    """{file name: source path} of the screencasts on the timeline (the uncensored original)."""
    out = {}
    for p in common.flatten(cfg, draft, ("screencast",)):
        name = common.uncensored_name(p["path"])
        cand = Path(p["path"])
        if cand.name != name:   # already pointed at a censored copy: find the original
            sc = cfg.sources.get("screencasts")
            cand = Path(sc) / name if sc else cand
        out.setdefault(name, cand)
    return out


def patch(cfg, draft: dict, mapping: dict[str, str]) -> tuple[int, set]:
    """Video material paths (all levels) of mapped file names -> new path. Returns (count, nested ids touched)."""
    n, nids = 0, set()
    keys = {k.lower(): v for k, v in mapping.items()}

    def walk(d, nid):
        nonlocal n
        for v in d.get("materials", {}).get("videos", []):
            new = keys.get(common.uncensored_name(v.get("path", "")).lower())
            if new and v.get("path") != new:
                v["path"] = new
                n += 1
                if nid:
                    nids.add(nid)
        for dm in d.get("materials", {}).get("drafts", []) or []:
            if isinstance(dm.get("draft"), dict):
                walk(dm["draft"], dm["draft"].get("id"))

    walk(draft, None)
    return n, nids


def run(cfg, dry: bool, encode_only: bool = False, guard_seconds: float = 5) -> dict:
    fp = cfg.work_dir / "stage5" / "censor_findings.json"
    if not fp.is_file():
        raise SystemExit(f"нет {fp}: сначала build_findings.py и утверждение")
    findings = [f for f in json.loads(fp.read_text(encoding="utf-8")) if f.get("apply")]
    if not findings:
        print("no approved findings: nothing to censor")
        return {}
    d = common.read_draft(cfg)
    src = sources(cfg, d)
    by_file: dict[str, list] = {}
    for f in findings:
        by_file.setdefault(f["file"], []).append(f)
    mapping = {}
    for name, items in by_file.items():
        p = src.get(name)
        if p is None:
            sc = cfg.sources.get("screencasts")
            p = Path(sc) / name if sc else None
        if p is None or not p.is_file():
            raise SystemExit(f"нет исходника {name} ({p})")
        mapping[name] = encode(cfg, p, items, dry).as_posix()
    if encode_only:
        print("--encode-only: project untouched")
        return mapping
    n, nids = patch(cfg, d, mapping)
    errs = common.check_refs(d)
    print(f"material paths to change: {n} (compounds {len(nids)}): " + json.dumps(mapping, ensure_ascii=False))
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs:
        print("  -", e)
    if errs:
        raise SystemExit(1)
    if dry:
        print("dry run, not written")
        return mapping
    subs = {nid: w for nid in nids if (w := mc.refresh(cfg, d, nid)) is not None}
    common.write_draft(cfg, d, "stage5-censor", dry=False, guard_seconds=guard_seconds, subdrafts=subs)
    mp = cfg.project_dir / "draft_meta_info.json"
    if mp.is_file():
        txt = mp.read_text(encoding="utf-8")
        k = 0
        for name, newp in mapping.items():
            old = src.get(name)
            if old is not None:
                k += txt.count(old.as_posix())
                txt = txt.replace(old.as_posix(), newp)
        if k:
            mp.write_text(txt, encoding="utf-8")
        print(f"draft_meta_info.json: {k} paths")
    (cfg.work_dir / "stage5" / "censor_applied.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=1),
                                                                encoding="utf-8")
    print("written; next: verify_censor.py")
    return mapping


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 5: blur into <name>_censored.mp4 + path swap in the project")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--encode-only", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.dry, a.encode_only)


if __name__ == "__main__":
    main()
