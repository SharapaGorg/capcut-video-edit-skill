"""Stage 10: loudness of the CapCut export + export checks (references/stages/STAGE_10.md, validation.md §10).

    python -X utf8 scripts/stage10/loudnorm.py <export.mp4> --config config.json [--dry] [--no-whisper]

1. ffprobe: resolution / fps = cfg (width x height, fps); audio duration = video ±1 frame.
2. ebur128: integrated LUFS, LRA, true peak. Norm −14 ±1 LUFS, TP <= −1 dBTP. Out of norm -> two-pass loudnorm
   (I −14, TP −1.5, LRA 11, measured_*, linear) with the video copied, AAC 320k 48 kHz -> <name>_final.mp4 ->
   measured again. In norm -> the export is the final file. --dry: measure and check only, no _final.
3. A frame every 10 s -> <work_dir>/stage10/export_frames/*.png (480x270); mean brightness < 3 % -> black frame;
   an almost flat, non-black frame (std < 2 % of full scale) -> possible missing-media placeholder. Both fail
   (look at the png).
4. 5 random srt lines (<work_dir>/stage10/subtitles.srt) vs the sound ±0.3 s: faster-whisper (base) — missing or
   --no-whisper -> speech onset by RMS. The export length vs the timeline (transcript_timeline duration) > 0.5 s ->
   fail (rebuild the srt with a shift).
Report: <work_dir>/stage10/export_report.md; exit 0 (all OK) / 1. The CapCut project is not touched.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

TARGET_I, TOL_I, TARGET_TP, LRA = -14.0, 1.0, -1.0, 11.0
LOUDNORM_TP = -1.5        # margin: TP stays <= −1 after AAC encoding
DARK = 0.03
FLAT_STD = 0.02
SYNC_TOL = 0.3
STEP = 10.0


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def stream_info(path) -> dict:
    r = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    if r.returncode:
        raise SystemExit(f"ffprobe: {r.stderr}")
    info = json.loads(r.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if not v or not a:
        raise SystemExit(f"{path}: нет видео- или аудиопотока")
    num, den = v["r_frame_rate"].split("/")

    def dur(s):
        if s.get("duration"):
            return float(s["duration"])
        if s.get("tags", {}).get("DURATION"):
            h, m, x = s["tags"]["DURATION"].split(":")
            return int(h) * 3600 + int(m) * 60 + float(x)
        return float(info["format"]["duration"])

    return {"width": int(v["width"]), "height": int(v["height"]), "fps": float(num) / float(den),
            "vcodec": v["codec_name"], "acodec": a["codec_name"], "a_rate": a.get("sample_rate"),
            "v_dur": dur(v), "a_dur": dur(a)}


def measure(path) -> dict:
    """ebur128 of the first audio stream: {"I", "LRA", "TP"}."""
    err = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=true",
                "-f", "null", "-"]).stderr
    tail = err[err.rfind("Summary:"):] if "Summary:" in err else err
    m_i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    m_lra = re.search(r"LRA:\s+(-?[\d.]+) LU", tail)
    m_tp = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", tail)
    if not (m_i and m_tp):
        raise SystemExit("ebur128: не удалось разобрать вывод:\n" + tail[-2000:])
    return {"I": float(m_i.group(1)), "LRA": float(m_lra.group(1)) if m_lra else None,
            "TP": float(m_tp.group(1)) if m_tp.group(1) != "-inf" else -99.0}


def in_norm(m: dict) -> bool:
    return abs(m["I"] - TARGET_I) <= TOL_I and m["TP"] <= TARGET_TP


def loudnorm(src: Path, out: Path, a_dur: float) -> tuple[dict, str]:
    """Two-pass loudnorm, video copied; the audio trimmed back to the export's audio length (loudnorm pads ~0.1 s)."""
    base = f"loudnorm=I={TARGET_I}:TP={LOUDNORM_TP}:LRA={LRA}"
    err = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-map", "0:a:0", "-af", f"{base}:print_format=json",
                "-f", "null", "-"]).stderr
    p1 = json.loads(err[err.rfind("{"):err.rfind("}") + 1])
    af = (f"{base}:measured_I={p1['input_i']}:measured_TP={p1['input_tp']}:measured_LRA={p1['input_lra']}:"
          f"measured_thresh={p1['input_thresh']}:offset={p1['target_offset']}:linear=true:print_format=summary,"
          f"aresample=48000,atrim=duration={a_dur:.6f}")
    r = _run(["ffmpeg", "-hide_banner", "-y", "-nostats", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
              "-af", af, "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", str(out)])
    if r.returncode:
        raise SystemExit("loudnorm, проход 2:\n" + r.stderr[-3000:])
    return p1, af


def frames(path: Path, duration: float, outdir: Path, step: float = STEP) -> list[dict]:
    """A frame every step s: png 480x270 + grey stats (mean, std; 0..1). None stats = not extracted."""
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("*.png"):
        old.unlink()
    res, t = [], 0.0
    while t < duration - 1e-3:
        png = outdir / f"f_{int(t):05d}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=480:270", str(png)], capture_output=True)
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(png), "-vf", "scale=64:36,format=gray", "-f", "rawvideo",
                              "-"], capture_output=True).stdout if png.is_file() else b""
        if raw:
            g = np.frombuffer(raw, np.uint8) / 255.0
            res.append({"t": t, "png": png.name, "mean": float(g.mean()), "std": float(g.std())})
        else:
            res.append({"t": t, "png": None, "mean": None, "std": None})
        t += step
    return res


def parse_srt(path: Path) -> list[dict]:
    out = []
    for b in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()):
        ls = b.strip().split("\n")
        m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", ls[1]) if len(ls) >= 3 else None
        if m:
            g = list(map(int, m.groups()))
            out.append({"n": int(ls[0]), "start": g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1e3,
                        "end": g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1e3, "text": " ".join(ls[2:])})
    return out


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", s.lower().replace("ё", "е"))


def onset_rms(x: np.ndarray, sr: int, win: float = 0.02) -> float | None:
    """Speech onset: the first two 20-ms windows above max(noise floor + 12 dB, −60 dBFS)."""
    n = int(sr * win)
    if len(x) < 3 * n:
        return None
    r = np.sqrt(np.mean(x[: len(x) // n * n].reshape(-1, n) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(r, 1e-6))
    thr = max(np.sort(db)[len(db) // 10] + 12, -60)
    hit = np.nonzero((db[:-1] > thr) & (db[1:] > thr))[0]
    return float(hit[0] * win) if len(hit) else None


def srt_sync(path: Path, blocks: list[dict], n: int, use_whisper: bool, log, seed: int = 10) -> tuple[list[dict], str]:
    import effects
    rnd = random.Random(seed)
    cands = [b for b in blocks if b["end"] - b["start"] >= 2.0 and len(_words(b["text"])) >= 4] or blocks
    picks = sorted(rnd.sample(cands, min(n, len(cands))), key=lambda b: b["start"])
    model, why = None, "--no-whisper"
    if use_whisper:
        try:
            from faster_whisper import WhisperModel
            model, why = WhisperModel("base", device="cpu", compute_type="int8"), ""
        except Exception as e:  # noqa: BLE001 — any import / model failure -> RMS fallback
            why = f"faster-whisper недоступен ({e.__class__.__name__}: {e})"
            log("  " + why + " — начало реплики по RMS")
    rows, PRE = [], 1.5
    for b in picks:
        st = max(0.0, b["start"] - PRE)
        x = effects.pcm(path, st, b["end"] - b["start"] + PRE + 1.0, sr=16000)
        found, heard, method = None, "", "rms"
        if model is not None and len(x):
            segs, _ = model.transcribe(x, language="ru", word_timestamps=True, beam_size=1, vad_filter=False)
            ws = [w for s in segs for w in (s.words or [])]
            heard = " ".join(w.word.strip() for w in ws)
            target = _words(b["text"])[:1]
            hw = [(_words(w.word) or [""])[0] for w in ws]
            idx = next((i for i, w in enumerate(hw) if target and (w == target[0] or (
                len(w) > 3 and len(target[0]) > 3 and w[:4] == target[0][:4]))), None)
            if idx is not None:
                found, method = st + ws[idx].start, "whisper"
            elif ws:
                found, method = st + ws[0].start, "whisper (первое слово)"
        if found is None:
            on = onset_rms(x, 16000)
            found = st + on if on is not None else None
            method = "rms"
        delta = None if found is None else found - b["start"]
        rows.append({**b, "found": found, "delta": delta, "ok": delta is not None and abs(delta) <= SYNC_TOL,
                     "method": method, "heard": heard[:120]})
    return rows, why


def _t(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:06.3f}"


def run(export, cfg, dry: bool = False, no_whisper: bool = False, n_srt: int = 5, step: float = STEP,
        log=print) -> tuple[int, Path, Path]:
    """-> (exit code, report path, final file)."""
    src = Path(export)
    if not src.is_file():
        raise SystemExit(f"нет файла {src}")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("нужны ffmpeg и ffprobe в PATH")
    out_dir = cfg.work_dir / "stage10"
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = [f"# Отчёт экспорта — {src.name}", "", f"Дата: {time.strftime('%Y-%m-%d %H:%M')}", ""]
    fails = []
    si = stream_info(src)
    frame = 1.0 / cfg.fps
    res_ok = (si["width"], si["height"]) == (cfg.width, cfg.height)
    fps_ok = abs(si["fps"] - cfg.fps) < 0.01
    sync_ok = abs(si["a_dur"] - si["v_dur"]) <= frame + 1e-6
    rep += ["## 1. ffprobe", "",
            f"- разрешение: {si['width']}x{si['height']} ({'OK' if res_ok else f'FAIL, проект {cfg.width}x{cfg.height}'})",
            f"- fps: {si['fps']:.3f} ({'OK' if fps_ok else f'FAIL, проект {cfg.fps}'})",
            f"- кодеки: видео {si['vcodec']}, аудио {si['acodec']} {si['a_rate']} Гц",
            f"- длительность: видео {si['v_dur']:.3f} с, аудио {si['a_dur']:.3f} с, разница "
            f"{abs(si['a_dur'] - si['v_dur']) * 1000:.1f} мс ({'OK' if sync_ok else 'FAIL > 1 кадр'})", ""]
    fails += [n for ok, n in ((res_ok, "разрешение"), (fps_ok, "fps"), (sync_ok, "длительность аудио ≠ видео")) if not ok]
    log(f"ffprobe: {si['width']}x{si['height']} {si['fps']:.3f} fps, video {si['v_dur']:.3f} s, audio {si['a_dur']:.3f} s")

    m0 = measure(src)
    log(f"ebur128: I {m0['I']} LUFS, LRA {m0['LRA']}, TP {m0['TP']} dBTP — {'in norm' if in_norm(m0) else 'OUT OF NORM'}")
    rep += ["## 2. Громкость (ebur128)", "",
            f"- экспорт: I = {m0['I']} LUFS, LRA = {m0['LRA']} LU, TP = {m0['TP']} dBTP → "
            f"{'в норме' if in_norm(m0) else f'вне нормы ({TARGET_I:g} ±{TOL_I:g} LUFS, TP ≤ {TARGET_TP:g})'}"]
    final = src
    if in_norm(m0):
        rep.append("- loudnorm не нужен, финальный файл = экспорт")
    elif dry:
        rep.append("- --dry: loudnorm не выполнялся")
        fails.append("громкость вне нормы (--dry)")
    else:
        out = src.with_name(src.stem + "_final.mp4")
        p1, af = loudnorm(src, out, si["a_dur"])
        m1, si1 = measure(out), stream_info(out)
        sync1 = abs(si1["a_dur"] - si1["v_dur"]) <= frame + 1e-6
        log(f"loudnorm -> {out.name}: I {m1['I']} LUFS, TP {m1['TP']} dBTP — {'OK' if in_norm(m1) else 'FAIL'}")
        rep += [f"- loudnorm, проход 1: I {p1['input_i']}, TP {p1['input_tp']}, LRA {p1['input_lra']}, "
                f"thresh {p1['input_thresh']}, offset {p1['target_offset']}",
                f"- проход 2: `{af}`, видео copy, aac 320k → `{out.name}`",
                f"- после loudnorm: I = {m1['I']} LUFS, LRA = {m1['LRA']} LU, TP = {m1['TP']} dBTP → "
                f"{'OK' if in_norm(m1) else 'FAIL'}",
                f"- `{out.name}`: видео {si1['v_dur']:.3f} с, аудио {si1['a_dur']:.3f} с ({'OK' if sync1 else 'FAIL > 1 кадр'})"]
        fails += [n for ok, n in ((in_norm(m1), "громкость после loudnorm"), (sync1, "длительность аудио после loudnorm"))
                  if not ok]
        final = out
    rep.append("")

    fr = frames(final, si["v_dur"], out_dir / "export_frames", step)
    dark = [f for f in fr if f["mean"] is not None and f["mean"] < DARK]
    flat = [f for f in fr if f["mean"] is not None and f["mean"] >= DARK and f["std"] < FLAT_STD]
    miss = [f for f in fr if f["mean"] is None]
    log(f"frames: {len(fr)}, black {len(dark)}, flat {len(flat)}, not extracted {len(miss)}")
    lst = lambda xs: ", ".join(f"{_t(f['t'])} ({f['png']})" for f in xs)  # noqa: E731
    rep += [f"## 3. Кадры раз в {step:g} с ({len(fr)} шт., `{final.name}` → `export_frames/`)", "",
            f"- чёрные (средняя яркость < {DARK:.0%}): {len(dark)}" + (f" — {lst(dark)}" if dark else ""),
            f"- однотонные не чёрные (возможна плашка отсутствующего медиа): {len(flat)}" + (f" — {lst(flat)}" if flat else ""),
            f"- не извлечено: {len(miss)}" + (" — " + ", ".join(_t(f["t"]) for f in miss) if miss else ""), ""]
    fails += [f"{n} ({len(x)}) — посмотреть png" for n, x in (("чёрные кадры", dark), ("однотонные кадры", flat),
                                                                 ("кадры не извлечены", miss)) if x]

    srt_p = out_dir / "subtitles.srt"
    tt = cfg.work_dir / "stage3" / "transcript_timeline.json"
    tl_dur = json.loads(tt.read_text(encoding="utf-8")).get("duration") if tt.is_file() else None
    if tl_dur is not None:
        dd = si["v_dur"] - tl_dur
        rep += ["## 4. Длительность", "", f"- экспорт {si['v_dur']:.3f} с, таймлайн {tl_dur:.3f} с, разница {dd:+.3f} с"
                + ("" if abs(dd) <= 0.5 else " — FAIL > 0.5 с: пересобрать srt со сдвигом"), ""]
        if abs(dd) > 0.5:
            fails.append("длительность экспорта ≠ таймлайн")
    if srt_p.is_file():
        blocks = parse_srt(srt_p)
        rows, why = srt_sync(final, blocks, n_srt, not no_whisper, log)
        ok = sum(r["ok"] for r in rows)
        rep += [f"## 5. Субтитры `{srt_p.name}` ({len(blocks)} блоков), {len(rows)} случайных реплик ±{SYNC_TOL:g} с", "",
                *([f"- метод: начало речи по RMS ({why})", ""] if why else []),
                "| блок | srt | найдено | Δ, с | метод | текст | услышано |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            rep.append(f"| {r['n']} | {_t(r['start'])} | {_t(r['found']) if r['found'] is not None else '-'} | "
                       f"{'%+.2f' % r['delta'] if r['delta'] is not None else '-'} {'OK' if r['ok'] else 'FAIL'} | "
                       f"{r['method']} | {r['text'][:60]} | {r['heard'][:60]} |")
        rep += ["", f"- совпало: {ok} из {len(rows)}", ""]
        log(f"srt: {ok}/{len(rows)} within ±{SYNC_TOL:g} s")
        if ok < len(rows):
            fails.append(f"синхрон srt ({ok}/{len(rows)})")
    else:
        rep += ["## 5. Субтитры", "", f"- {srt_p} нет (build_srt.py) — проверка пропущена", ""]
    rep += ["## Итог", "", f"- финальный файл: `{final}`", "- " + ("ВСЁ OK" if not fails else "ПРОВАЛЫ: " + "; ".join(fails)), ""]
    rp = out_dir / "export_report.md"
    rp.write_text("\n".join(rep), encoding="utf-8")
    log(f"report: {rp}")
    log("RESULT:", "OK" if not fails else "FAIL: " + "; ".join(fails))
    return (0 if not fails else 1), rp, final


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 10: export loudness (-14 LUFS, TP <= -1) + export checks")
    ap.add_argument("export")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-whisper", action="store_true")
    ap.add_argument("--n-srt", type=int, default=5)
    a = ap.parse_args(argv)
    code, _, _ = run(a.export, common.load_config(a.config), a.dry, a.no_whisper, a.n_srt)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
