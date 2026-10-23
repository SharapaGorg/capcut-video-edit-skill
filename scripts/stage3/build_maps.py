"""Stage 3 (references/stages/STAGE_3.md §1-5): timeline map + transcript in timeline time. READ-ONLY on the project.

    python -X utf8 scripts/stage3/build_maps.py --config config.json [--dry] [--raw FILE|DIR] [--expect SEC]
                                                [--no-audio-check]

Inputs: the project (Timelines/<id>; compounds walked via common.flatten at any depth, also when cut into pieces,
speed applied on every level); transcript/transcript.json (stage 0: transcript time = timeline before stage 1);
the RAW draft = the timeline that was transcribed (default: the earliest <work_dir>/backups/stage1-before-*;
--raw a draft file or a project/backup dir) — it maps transcript time -> (voice file, time in the file);
stage1/chapters.json (optional); cut logs stage1/cuts_applied.json, stage2/cuts2_applied.json,
stage3/ripple_cuts.json (optional, cross-check -> report notes); layout/assembly.json (optional: camera <->
voice sync by offset_us, ±1 frame -> errors).
Voice = mic (cfg.sources.voice, if set) + screencast audio, matched by base name; «x_censored.mp4» = «x.mp4».
Words in sped pieces are kept (field speed); words cut by less than half are kept with partial; a source piece
placed twice -> the 2nd entry gets duplicate: true. Cut words -> dropped_words (reason cut | cut_edge).
Outputs (<work_dir>/stage3/): timeline_map.json, transcript_timeline.json/.txt, chapters_timeline.json, report.md.
--expect: expected duration (s), ±1 frame. --dry: print only. Exit 1 on a failed check (files are written anyway).
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

STEP = 10_000          # word sampling step, us
VOICE_ROLES = ("voice", "screencast")
MEDIA = ("videos", "audios")


def vkey(path) -> str:
    return common.uncensored_name(path).lower()


def find_raw(cfg, raw=None) -> Path:
    if raw:
        p = Path(raw)
    else:
        bks = sorted((cfg.work_dir / "backups").glob("stage1-before-*"))
        if not bks:
            raise SystemExit("no backups/stage1-before-* (the timeline that was transcribed): pass --raw")
        p = bks[0]
    if p.is_dir():
        real = p / "Timelines" / cfg.timeline_id / "draft_content.json"
        p = real if real.is_file() else p / "draft_content.json"
    if not p.is_file():
        raise SystemExit(f"raw draft not found: {p}")
    return p


# ---------- 1. timeline_map ----------
def timeline_map(cfg, d: dict) -> dict:
    flat = common.flatten(cfg, d, roles=None)
    ix = common.index(d["materials"])
    drafts = {m["id"]: m for m in d["materials"].get("drafts", []) or [] if isinstance(m, dict) and "id" in m}
    tracks = []
    for ti, t in enumerate(d["tracks"]):
        name = t.get("name") or f"track{ti}"
        segs = [{"track": name, "track_type": t["type"], "compound": p["compound"], "segment_id": p["segment_id"],
                 "kind": p["kind"], "name": p["name"], "file": p["path"] if p["kind"] in MEDIA else "", "role": p["role"],
                 "timeline_in_us": p["start"], "timeline_out_us": p["end"],
                 "source_in_us": p["src"], "source_out_us": p["src_end"],
                 "flat_id": f"{p['segment_id']}@{p['start']}",  # a nested segment cut by outer cuts -> several pieces
                 "speed": round(p["speed"], 6), "volume": round(p["volume"], 6)}
                for p in flat if p["track"] == ti]
        segs.sort(key=lambda x: (x["compound"] or "", x["timeline_in_us"]))
        tops = []
        for s in common.by_start(t["segments"]):
            k, m = ix.get(s.get("material_id"), (None, {}))
            sr = s.get("source_timerange")
            dm = next((drafts[e] for e in s.get("extra_material_refs") or [] if e in drafts), None)
            tops.append({"id": s["id"], "material": m.get("material_name") or m.get("name") or "", "kind": k,
                         "draft_id": (dm.get("draft") or {}).get("id") if dm else None,
                         "timeline_in_us": s["target_timerange"]["start"], "timeline_out_us": common.seg_end(s),
                         "source_in_us": sr["start"] if sr else None,
                         "source_out_us": sr["start"] + sr["duration"] if sr else None,
                         "speed": s.get("speed", 1.0), "volume": s.get("volume", 1.0)})
        tracks.append({"index": ti, "name": t.get("name") or "", "type": t["type"], "top_level_segments": tops,
                       "segments": segs})
    return {"project": str(cfg.project_dir), "duration_us": d["duration"], "fps": cfg.fps,
            "note": "segments = flat list, compounds expanded (timeline_* = top timeline, source_* = time in the file, "
                    "speed = source s per timeline s incl. outer speeds, volume = product down the compound chain). "
                    "top_level_segments = as in CapCut.",
            "tracks": tracks}


# ---------- 2-3. transcript time -> (file, src) -> timeline ----------
class VoiceMap:
    def __init__(self, cfg, raw: dict, tracks: list[dict], transcript_duration: float | None):
        self.cur = [s for t in tracks for s in t["segments"] if s["role"] in VOICE_ROLES and s["volume"] > 0]
        self.by_key = defaultdict(list)
        for s in self.cur:
            self.by_key[vkey(s["file"])].append(s)
        for v in self.by_key.values():
            v.sort(key=lambda s: s["source_in_us"])
        self.by_flat = {s["flat_id"]: s for s in self.cur}
        rv = [p for p in common.flatten(cfg, raw, VOICE_ROLES) if p["volume"] > 0]
        if not rv:
            raise SystemExit("raw draft: no voice pieces (cfg.sources voice/screencasts)")
        if any(abs(p["speed"] - 1.0) > 1e-9 for p in rv):
            raise SystemExit("raw draft has sped voice pieces: it is not the transcribed timeline (--raw)")
        for p, q in zip(rv, rv[1:]):
            if q["start"] < p["end"] - 1:
                raise SystemExit(f"raw draft: voice pieces overlap at {q['start'] / 1e6:.3f} s (transcript time ambiguous)")
        end = max(p["end"] for p in rv)
        if transcript_duration is not None and abs(transcript_duration - end / 1e6) > 0.1:
            raise SystemExit(f"raw draft voice ends at {end / 1e6:.3f} s, transcript is {transcript_duration:.3f} s: "
                             "not the transcribed timeline (--raw)")
        self.raw = [{"file": common.uncensored_name(p["path"]), "tl_in": p["start"], "tl_out": p["end"], "src_in": p["src"]}
                    for p in rv]
        self.starts = [s["tl_in"] for s in self.raw]

    def to_src(self, us):
        i = bisect.bisect_right(self.starts, us) - 1
        if i < 0 or us >= self.raw[i]["tl_out"]:
            return None, None
        s = self.raw[i]
        return s["file"], s["src_in"] + (us - s["tl_in"])

    def to_timeline_all(self, us):
        """every (timeline us, piece) where the transcript instant us plays now; [] if cut"""
        f, src = self.to_src(us)
        if f is None:
            return []
        return [(s["timeline_in_us"] + (src - s["source_in_us"]) / s["speed"], s) for s in self.by_key.get(f.lower(), [])
                if s["source_in_us"] <= src < s["source_out_us"]]


def map_words(T: dict, vm: VoiceMap):
    words_out, dropped, total = [], [], 0
    for sg in T["segments"]:
        for w in sg["words"]:
            total += 1
            a, b = int(round(w["start"] * 1e6)), int(round(w["end"] * 1e6))
            if b <= a:
                b = a + STEP
            # sample the word every 10 ms; consecutive samples in the same flat piece form a run
            runs = {}  # flat_id -> [first_src, last_src, first_tl, last_tl, n]
            for p in list(range(a, b, STEP)) + [b - 1]:
                for tl, s in vm.to_timeline_all(p):
                    key = s["flat_id"]
                    if key in runs and p - runs[key][1] <= STEP:
                        runs[key][1], runs[key][3] = p, tl
                        runs[key][4] += 1
                    elif key not in runs:
                        runs[key] = [p, p, tl, tl, 1]
            f, src0 = vm.to_src(a)
            if not runs:
                dropped.append({"word": w["word"], "src_start": w["start"], "src_end": w["end"], "reason": "cut", "file": f,
                                "file_start": round(src0 / 1e6, 3) if src0 is not None else None})
                continue
            items = sorted(runs.items(), key=lambda kv: -(kv[1][1] - kv[1][0]))  # main = longest run
            best = items[0][1]
            if (best[1] - best[0] + STEP) / (b - a) < 0.5:
                dropped.append({"word": w["word"], "src_start": w["start"], "src_end": w["end"], "reason": "cut_edge",
                                "kept_ms": int((best[1] - best[0] + STEP) / 1e3), "tl": round(best[2] / 1e6, 3)})
                continue
            for n, (fid, run) in enumerate(items):
                seg = vm.by_flat[fid]
                full = (run[1] - run[0] + STEP) >= (b - a) - STEP
                if n > 0 and not full:
                    continue  # a partial duplicate is not needed
                tl_a = max(run[2], seg["timeline_in_us"])
                tl_b = min(run[3] + STEP / seg["speed"], seg["timeline_out_us"])
                fa, srca = vm.to_src(run[0])
                rec = {"word": w["word"], "start": round(tl_a / 1e6, 3), "end": round(tl_b / 1e6, 3),
                       "src_start": round(w["start"], 3), "src_end": round(w["end"], 3),
                       "file": fa, "file_start": round(srca / 1e6, 3), "segment_id": seg["segment_id"], "flat_id": fid,
                       "speed": seg["speed"], "compound": seg["compound"]}
                if not full:
                    rec["partial"] = "start" if run[0] > a else "end"
                if n > 0:
                    rec["duplicate"] = True
                words_out.append(rec)
    words_out.sort(key=lambda w: (w["start"], w["end"]))
    return words_out, dropped, total


def phrases(words: list[dict]) -> list[list[dict]]:
    """break on a pause > 1 s, 25 words, or a splice (source goes back or jumps > 1.5 s)"""
    out, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > 1.0 or len(cur) >= 25 or w["src_start"] < cur[-1]["src_start"]
                    or w["src_start"] - cur[-1]["src_end"] > 1.5):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


# ---------- 4. chapters ----------
def chapters_timeline(cfg, d: dict, T: dict, body: list[dict]) -> tuple[list[dict], list[dict]]:
    ix = common.index(d["materials"])
    plates = []
    for t in d["tracks"]:
        if t["type"] != "text":
            continue
        for s in t["segments"]:
            m = ix.get(s.get("material_id"), (None, {}))[1]
            try:
                txt = json.loads(m["content"])["text"].replace("\n", " | ") if "content" in m else ""
            except (ValueError, KeyError, TypeError):
                txt = ""
            plates.append({"start": round(s["target_timerange"]["start"] / 1e6, 3), "end": round(common.seg_end(s) / 1e6, 3),
                           "text": txt, "track": t.get("name")})
    plates.sort(key=lambda p: p["start"])
    chp = cfg.work_dir / "stage1" / "chapters.json"
    CH = json.loads(chp.read_text(encoding="utf-8")) if chp.is_file() else []
    starts = [sg["start"] for sg in T["segments"]]
    chapters = []
    for c in CH:
        sent = min(starts, key=lambda x: abs(x - c["start_transcript_s"]))  # snap to a transcript sentence start
        w = next((w for w in body if w["src_start"] >= sent - 0.01), None)
        start = 0.0 if c["n"] == 1 else (w["start"] if w else None)
        rec = {"n": c["n"], "title": c["title"], "start": start, "first_word": w["word"] if w else None, "src_start": sent}
        if start is not None and plates:
            p = min(plates, key=lambda p: abs(p["start"] - start))
            rec.update(plate=p["text"], plate_start=p["start"], plate_delta_s=round(p["start"] - start, 3))
        chapters.append(rec)
    for a, b in zip(chapters, chapters[1:]):
        a["end"] = b["start"]
    if chapters:
        chapters[-1]["end"] = round(d["duration"] / 1e6, 3)
    return chapters, plates


# ---------- 5. checks ----------
def log_check(cfg, body: list[dict]) -> str:
    """STAGE_3 §2: expected timeline time of every word from the cut logs vs the project."""
    wd = cfg.work_dir
    p1 = wd / "stage1" / "cuts_applied.json"
    if not p1.is_file():
        return "сверка с логами резки: stage1/cuts_applied.json нет — не сверялось"
    cuts1 = sorted((c["start_us"], c["end_us"]) for c in json.loads(p1.read_text(encoding="utf-8"))["cuts"])
    ev2 = []
    p2 = wd / "stage2" / "cuts2_applied.json"
    if p2.is_file():
        A2 = json.loads(p2.read_text(encoding="utf-8"))
        ev2 = sorted([(c["timeline_start_us"], c["timeline_end_us"], c["timeline_end_us"] - c["timeline_start_us"])
                      for c in A2["cuts"]] +
                     [(s["timeline_start_us"], s["timeline_end_us"],
                       s["timeline_end_us"] - s["timeline_start_us"] - s["new_duration_us"]) for s in A2["speedups"]])
    p3 = wd / "stage3" / "ripple_cuts.json"
    rip = [[(common.us(a), common.us(b)) for a, b in e["cuts"]] for e in json.loads(p3.read_text(encoding="utf-8"))] \
        if p3.is_file() else []

    def expect(t):
        x = common.map_through_cuts(t, cuts1)
        out = x
        for a, b, loss in ev2:
            if x <= a:
                break
            out -= loss if x >= b else loss * (x - a) / (b - a)
        x = out
        for cuts in rip:
            x = common.map_through_cuts(x, cuts)
        return x

    ws = [w for w in body if not w.get("partial")]
    if not ws:
        return "сверка с логами резки: нет слов"
    diffs = [abs(expect(common.us(w["src_start"])) - common.us(w["start"])) for w in ws]
    frame = 1e6 / cfg.fps
    return (f"сверка с логами резки ({len(ws)} слов): макс. расхождение проекта с логами {max(diffs) / 1e3:.1f} мс, "
            f"> 1 кадра: {sum(1 for x in diffs if x > frame)} (ручные правки/хук после логов дают расхождение)")


def assembly_check(cfg, d: dict) -> tuple[list[str], str | None]:
    """STAGE_3 §2: layout/assembly.json pairs (camera_time = voice_time + offset_us). At the middle of every overlap
    of a camera piece with a voice piece of its pair (any volume, any speed, inside compounds too) the camera source
    time must equal voice source time + offset, ±1 frame. -> (errors, note); ([], None) if the file is absent."""
    p = cfg.work_dir / "layout" / "assembly.json"
    if not p.is_file():
        return [], None
    pairs = [x for x in json.loads(p.read_text(encoding="utf-8")).get("pairs") or [] if x.get("ok", True)]
    off = {(common.uncensored_name(x["camera"]).lower(), common.uncensored_name(x["voice"]).lower()): int(x["offset_us"])
           for x in pairs}
    pieces = common.flatten(cfg, d, ("camera",) + VOICE_ROLES)
    cams = [x for x in pieces if x["role"] == "camera"]
    voices = [x for x in pieces if x["role"] in VOICE_ROLES]
    frame = 1e6 / cfg.fps
    errs, n = [], 0
    for c in cams:
        ck = common.uncensored_name(c["path"]).lower()
        for v in voices:
            key = (ck, common.uncensored_name(v["path"]).lower())
            a, b = max(c["start"], v["start"]), min(c["end"], v["end"])
            if key not in off or b - a < frame:  # touching neighbours (rounding) are not an overlap
                continue
            t = (a + b) / 2
            vs = v["src"] + (t - v["start"]) * v["speed"]
            cs = c["src"] + (t - c["start"]) * c["speed"]
            n += 1
            diff = cs - (vs + off[key])
            if abs(diff) > frame:
                errs.append(f"синхрон камеры: {Path(c['path']).name} / {Path(v['path']).name} на "
                            f"{a / 1e6:.3f}–{b / 1e6:.3f}: сдвиг {diff / 1e3:+.1f} мс от offset assembly.json")
    note = f"сверка с layout/assembly.json: {n} перекрытий камера↔голос, рассинхрон > 1 кадра: {len(errs)}"
    if len(errs) > 20:
        errs = errs[:20] + [f"синхрон камеры: ещё {len(errs) - 20} расхождений"]
    return errs, note


def checks(cfg, d, tmap, vm: VoiceMap, words, chapters, expect_us):
    errs, notes = [], []
    tracks = tmap["tracks"]
    dur = d["duration"]
    frame = 1e6 / cfg.fps
    main = next((t for t in tracks if t["type"] == "video" and t["top_level_segments"]), None)
    tops = main["top_level_segments"] if main else []
    if not tops:
        errs.append("нет главной видеодорожки")
    else:
        sum_top = sum(s["timeline_out_us"] - s["timeline_in_us"] for s in tops)
        main_end = tops[-1]["timeline_out_us"]
        if tops[0]["timeline_in_us"] != 0:
            errs.append("главная дорожка не с нуля")
        for p, q in zip(tops, tops[1:]):
            if abs(q["timeline_in_us"] - p["timeline_out_us"]) > 1:
                errs.append(f"главная дорожка: разрыв/перекрытие на {p['timeline_out_us'] / 1e6:.3f}")
        if abs(main_end - dur) > 1:
            notes.append(f"главная дорожка заканчивается на {main_end / 1e6:.3f}, проект — на {dur / 1e6:.3f}; "
                         f"сумма её сегментов {sum_top / 1e6:.3f}")
    if expect_us is not None and abs(dur - expect_us) > frame:
        errs.append(f"duration проекта {dur / 1e6:.3f} != ожидаемой {expect_us / 1e6:.3f}")
    ends = [s["timeline_out_us"] for t in tracks for s in t["top_level_segments"]]
    if ends and abs(max(ends) - dur) > 1:
        errs.append(f"конец самой длинной дорожки {max(ends) / 1e6:.3f} != duration {dur / 1e6:.3f}")
    cv = sorted(vm.cur, key=lambda s: s["timeline_in_us"])
    if not cv:
        errs.append("на таймлайне нет голоса (voice/screencasts из cfg.sources, volume > 0)")
    for p, q in zip(cv, cv[1:]):
        if q["timeline_in_us"] < p["timeline_out_us"] - 1:
            errs.append(f"перекрытие голоса на {q['timeline_in_us'] / 1e6:.3f} ({p['compound']} / {q['compound']})")
    if cv:
        gaps = [(p["timeline_out_us"] / 1e6, q["timeline_in_us"] / 1e6) for p, q in zip(cv, cv[1:])
                if q["timeline_in_us"] - p["timeline_out_us"] > 2_000_000]
        if cv[0]["timeline_in_us"] > 0:
            gaps.insert(0, (0.0, cv[0]["timeline_in_us"] / 1e6))
        if cv[-1]["timeline_out_us"] < dur:
            gaps.append((cv[-1]["timeline_out_us"] / 1e6, dur / 1e6))
        notes.append("участки без голоса > 2 с: " + (", ".join(f"{a:.3f}–{b:.3f}" for a, b in gaps) or "нет"))
    for w in words:  # every word inside its piece
        s = vm.by_flat[w["flat_id"]]
        if not (s["timeline_in_us"] / 1e6 - 2e-3 <= w["start"] and w["end"] <= s["timeline_out_us"] / 1e6 + 2e-3):
            errs.append(f"слово '{w['word']}' @ {w['start']} вне сегмента")
    if words and words[-1]["end"] > dur / 1e6 + 1e-3:
        errs.append("последнее слово за концом таймлайна")
    rnd = random.Random(7)  # back-calculation timeline -> source == file_start
    for w in rnd.sample(words, min(10, len(words))):
        s = vm.by_flat[w["flat_id"]]
        src = (w["start"] * 1e6 - s["timeline_in_us"]) * s["speed"] + s["source_in_us"]
        if abs(src / 1e6 - w["file_start"]) > 0.003 or common.uncensored_name(s["file"]) != w["file"]:
            errs.append(f"обратный расчёт: {w['word']} {src / 1e6:.3f} vs {w['file_start']}")
    for c in chapters[1:]:
        if c.get("plate_delta_s") is None or abs(c["plate_delta_s"]) > 3.0:
            notes.append(f"глава {c['n']} «{c['title']}» start {c['start']} — своей заставки нет "
                         f"(ближайшая {c.get('plate')} @ {c.get('plate_start')}, Δ {c.get('plate_delta_s')} с)")
    missing = sorted({s["file"] for t in tracks for s in t["segments"]
                      if s["file"] and not s["file"].startswith("##_draftpath") and not os.path.exists(s["file"])})
    errs += [f"нет файла {f}" for f in missing]
    return errs, notes


def audio_verify(tt: dict, vm: VoiceMap, errs: list, notes: list) -> list[dict]:
    """5 phrases: source by the transcript (raw draft) vs source by the map from timeline time — same range, same
    RMS envelope (ffmpeg), whisper base hears the phrase."""
    import difflib
    import re

    import numpy as np

    def pcm(path, start, dur):
        p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", path, "-vn", "-ac", "1",
                            "-ar", "16000", "-f", "s16le", "-"], capture_output=True)
        return np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768

    def env(x, hop=160):
        n = len(x) // hop
        return np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12)

    if shutil.which("ffmpeg") is None:
        notes.append("audio check skipped: ffmpeg not found")
        return []
    try:
        from faster_whisper import WhisperModel
        wm = WhisperModel("base", device="cpu", compute_type="int8")
    except Exception as e:  # noqa: BLE001 - optional dependency
        wm = None
        notes.append(f"faster-whisper недоступен ({e}); только RMS-сравнение")
    cands = [s for s in tt["segments"] if len(s["words"]) >= 5 and len({w["flat_id"] for w in s["words"]}) == 1
             and not any(w.get("duplicate") or w.get("partial") for w in s["words"])]
    path_of = {}
    for s in vm.cur:
        path_of.setdefault(common.uncensored_name(s["file"]), s["file"])
    norm = lambda s: " ".join(re.findall(r"\w+", s.lower().replace("ё", "е")))  # noqa: E731
    rows = []
    for ph in random.Random(11).sample(cands, min(5, len(cands))):
        w0, w1 = ph["words"][0], ph["words"][-1]
        fa, a0 = w0["file"], w0["file_start"]          # A: transcript -> raw draft -> file
        a1 = w1["file_start"] + (w1["src_end"] - w1["src_start"])
        tl0, tl1 = w0["start"], w1["end"]              # B: timeline -> map -> file
        seg = next((s for s in vm.cur if s["timeline_in_us"] / 1e6 - 1e-3 <= tl0 < s["timeline_out_us"] / 1e6),
                   vm.by_flat[w0["flat_id"]])  # independent lookup in the map; the word's own piece as fallback
        fb = common.uncensored_name(seg["file"])
        b0 = (seg["source_in_us"] + (tl0 * 1e6 - seg["timeline_in_us"]) * seg["speed"]) / 1e6
        b1 = (seg["source_in_us"] + (tl1 * 1e6 - seg["timeline_in_us"]) * seg["speed"]) / 1e6
        try:
            xa, xb = pcm(path_of.get(fa, seg["file"]), a0, a1 - a0), pcm(seg["file"], b0, b1 - b0)
        except FileNotFoundError:
            notes.append("audio check skipped: ffmpeg not found")
            return rows
        n = min(len(xa), len(xb))
        corr = float(np.corrcoef(env(xa[:n]), env(xb[:n]))[0, 1]) if n > 1600 else 0.0
        same = fa == fb and abs(a0 - b0) < 0.02 and abs(a1 - b1) < 0.02
        row = {"tl": f"{tl0:.3f}–{tl1:.3f}", "text": ph["text"][:70], "A": f"{fa} {a0:.3f}–{a1:.3f}",
               "B": f"{fb} {b0:.3f}–{b1:.3f}", "same_range": same, "rms_corr": round(corr, 4)}
        if wm is not None:
            with tempfile.TemporaryDirectory() as tmp:
                wav = os.path.join(tmp, "chk.wav")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{b0:.3f}", "-t", f"{b1 - b0:.3f}", "-i", seg["file"],
                                "-vn", "-ac", "1", "-ar", "16000", wav], capture_output=True)
                segs_w, _ = wm.transcribe(wav, language="ru", beam_size=1)
                heard = " ".join(x.text.strip() for x in segs_w)
            row["whisper"] = heard[:80]
            row["word_overlap"] = round(difflib.SequenceMatcher(None, norm(ph["text"]), norm(heard)).ratio(), 2)
        rows.append(row)
        ok = same and corr > 0.95 and row.get("word_overlap", 1.0) >= 0.4
        print(("  OK  " if ok else "  FAIL") + f" {row['tl']} «{row['text'][:40]}» A={row['A']} B={row['B']} "
              f"corr={row['rms_corr']} overlap={row.get('word_overlap')}")
        if not ok:
            errs.append(f"аудиопроверка: {row}")
    return rows


# ---------- 6. report ----------
def hms(x):
    m, s = divmod(int(x), 60)
    return f"{m:02d}:{s:02d}"


def report(cfg, d, tmap, vm, chapters, counts, rows, errs, notes) -> str:
    main = next((t for t in tmap["tracks"] if t["type"] == "video" and t["top_level_segments"]), None)
    tops = main["top_level_segments"] if main else []
    L = [f"# Этап 3 — отчёт\n\nПроект: `{cfg.project_dir}`\n"
         f"Длительность: {hms(d['duration'] / 1e6)} ({d['duration'] / 1e6:.3f} с).\n",
         "## Главная дорожка (верхний уровень)\n\n| Таймлайн | Материал | Источник | Скорость |\n|---|---|---|---|"]
    for s in tops:
        src = f"{s['source_in_us'] / 1e6:.3f}–{s['source_out_us'] / 1e6:.3f}" if s["source_in_us"] is not None else "—"
        L.append(f"| {s['timeline_in_us'] / 1e6:.3f}–{s['timeline_out_us'] / 1e6:.3f} | {s['material']} | {src} | "
                 f"{float(s['speed']):.2f} |")
    L.append(f"\nПлоских сегментов после раскрытия compound: {sum(len(t['segments']) for t in tmap['tracks'])}; "
             f"голосовых: {len(vm.cur)}.\n")
    L.append("## Главы\n\n| № | Старт | Название | Первое слово | Заставка | Δ, с |\n|---|---|---|---|---|---|")
    for c in chapters:
        st = f"{hms(c['start'])} ({c['start']})" if c["start"] is not None else "—"
        L.append(f"| {c['n']} | {st} | {c['title']} | {c['first_word']} | {c.get('plate', '—')} @ "
                 f"{c.get('plate_start', '—')} | {c.get('plate_delta_s', '—')} |")
    if not chapters:
        L.append("\nstage1/chapters.json нет — главы не пересчитаны.")
    L.append(f"\n## Слова\n- В транскрипте {counts['transcript_words']}; на таймлайне {counts['kept']} (уникальных "
             f"{counts['kept_unique']}, дублей {counts['duplicates']}, обрезанных склейкой {counts['partial']}).\n"
             f"- Вырезано: {counts['dropped']} — `transcript_timeline.json` → `dropped_words`.")
    if rows:
        L.append("\n## Аудиопроверка (5 фраз)\nA = исходник по транскрипту (raw), B = по timeline_map.\n\n"
                 "| Таймлайн | Фраза | A | B | Диапазон | corr RMS | whisper (B) | overlap |\n|---|---|---|---|---|---|---|---|")
        L += [f"| {x['tl']} | {x['text']} | {x['A']} | {x['B']} | {x['same_range']} | {x['rms_corr']} | "
              f"{x.get('whisper', '—')} | {x.get('word_overlap', '—')} |" for x in rows]
    L.append(f"\n## Валидация: {'OK' if not errs else 'FAIL'}")
    L += [f"- {e}" for e in errs]
    L.append("\n## Замечания")
    L += [f"- {n}" for n in notes]
    return "\n".join(L) + "\n"


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def run(cfg, raw: str | None = None, expect_us: int | None = None, audio_check: bool = True, dry: bool = False) -> dict:
    d = common.read_draft(cfg)
    raw_path = find_raw(cfg, raw)
    T = json.loads((cfg.work_dir / "transcript" / "transcript.json").read_text(encoding="utf-8"))
    tmap = timeline_map(cfg, d)
    print(f"timeline_map: duration {d['duration'] / 1e6:.3f} s, tracks {len(tmap['tracks'])}, "
          f"flat segments {sum(len(t['segments']) for t in tmap['tracks'])}")
    vm = VoiceMap(cfg, json.loads(raw_path.read_text(encoding="utf-8")), tmap["tracks"], T.get("duration"))
    print(f"raw draft (transcript time): {raw_path}")
    words, dropped, total = map_words(T, vm)
    reasons = defaultdict(int)
    for x in dropped:
        reasons[x["reason"]] += 1
    dups = [w for w in words if w.get("duplicate")]
    counts = {"transcript_words": total, "kept": len(words), "kept_unique": len(words) - len(dups),
              "duplicates": len(dups), "partial": sum(1 for w in words if w.get("partial")), "dropped": dict(reasons)}
    tt = {"duration": round(d["duration"] / 1e6, 3),
          "note": "start/end = timeline seconds; src_* = transcript time (= timeline before stage 1); file/file_start = "
                  "source file and seconds in it; speed = speed of the piece (words in sped pieces kept, shorter on the "
                  "timeline); partial = word clipped by a splice (kept if >= 50 % survives); duplicate = the same source "
                  "placed on the timeline a second time. Cut words are not in segments — see dropped_words (cut | cut_edge).",
          "counts": counts,
          "segments": [{"id": i + 1, "start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(w["word"] for w in s),
                        "words": s} for i, s in enumerate(phrases(words))],
          "dropped_words": dropped}
    print(f"transcript_timeline: kept {len(words)} / {total} words (dups {len(dups)}, partial {counts['partial']}); "
          f"dropped {dict(reasons)}")
    body = [w for w in words if not w.get("duplicate")]
    chapters, plates = chapters_timeline(cfg, d, T, body)
    errs, notes = checks(cfg, d, tmap, vm, words, chapters, expect_us)
    notes.append(log_check(cfg, body))
    a_errs, a_note = assembly_check(cfg, d)
    errs += a_errs
    if a_note:
        notes.append(a_note)
    rows = audio_verify(tt, vm, errs, notes) if audio_check and words else []
    print("VALIDATION:", "OK" if not errs else "FAIL")
    for e in errs[:20]:
        print("  -", e)
    for n in notes:
        print("  note:", n)
    if not dry:
        out = cfg.work_dir / "stage3"
        out.mkdir(parents=True, exist_ok=True)
        _dump(out / "timeline_map.json", tmap)
        _dump(out / "transcript_timeline.json", tt)
        (out / "transcript_timeline.txt").write_text(
            "".join(f"[{hms(s['start'])}] {s['text']}\n" for s in tt["segments"]), encoding="utf-8")
        _dump(out / "chapters_timeline.json", {"chapters": chapters, "plates": plates})
        (out / "report.md").write_text(report(cfg, d, tmap, vm, chapters, counts, rows, errs, notes), encoding="utf-8")
        print("written:", out)
    else:
        print("dry run, nothing written")
    return {"errs": errs, "notes": notes, "counts": counts, "duration_us": d["duration"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 3: timeline map + transcript in timeline time (read-only)")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--raw", help="the transcribed (pre-stage-1) draft: file or project/backup dir")
    ap.add_argument("--expect", type=float, help="expected duration, s (±1 frame)")
    ap.add_argument("--no-audio-check", action="store_true")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    res = run(cfg, a.raw, common.us(a.expect) if a.expect is not None else None, not a.no_audio_check, a.dry)
    if res["errs"]:
        raise SystemExit(1)
    return res


if __name__ == "__main__":
    main()
