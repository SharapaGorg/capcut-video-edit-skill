"""Stage 9: background music on its own audio tracks («Музыка», «Музыка 2», …). Re-run = replace.

    python -X utf8 scripts/stage9/apply_music.py --config config.json [--files a.mp3 b.mp3] [--tracks N] [--dry]

Tracks: cfg.music_dir (prepare.music_files; unset -> stop and ask). Default: the first file only (a music folder is
often a library); --files NAME … picks tracks, --tracks N the first N; the chosen files are printed. N tracks (at most
one per chapter) take contiguous groups of chapters, balanced by duration; a track changes ONLY at a chapter boundary, with
a 2-s crossfade. Each track plays from its start, then loops its bar-aligned loop (beats.loop_region); loop seams
overlap 60 ms (no click).
Levels (references/stages/STAGE_9.md), relative to the voice (median short-term LUFS of the speech windows of each
chapter, prepare.voice_levels); the music is calibrated on its loop's short-term median:
  under speech       voice − 13 LU
  no speech >= 2 s   +6 dB (pauses, sped parts)
  last 20 s          voice − 10 LU, fade-out 2 s at the very end (not a cut)
Level changes = hand-over between two tracks: the outgoing piece fades out over 300 ms, the incoming one (same file,
same source time, new volume) starts 150 ms earlier with a 300-ms fade-in -> a linear 300-ms ramp
(references/capcut-format.md, «Громкость»). Level changes closer than 300 ms to a loop seam move to the seam.
Every piece: material audios (one per file), Deep (effects.make('deep_effect'); not in the CapCut cache ->
EffectCacheMissing, nothing written), audio_fades. Existing music tracks are removed first (their materials too).
Writes both drafts (common.write_draft) and <work_dir>/stage9/music.json (--dry: music.dry.json; music.json — the
record check_mix / music_gain rely on — is left alone).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import effects  # noqa: E402
import beats  # noqa: E402
import prepare  # noqa: E402

UNDER_SPEECH = -13.0     # LU vs voice
GAP_BOOST = 6.0          # dB over the under-speech level
ENDING_REL = -10.0       # LU vs voice, last ENDING_LEN s
ENDING_LEN = 20.0
FADE_END = 2.0
RAMP = 0.3
SEAM = 0.06
XFADE = 2.0
MIN_GAP = 2.0
MIN_PIECE = 0.6
MAX_VOLUME = 10.0        # CapCut: +20 dB
TRACK = "Музыка"
DEFAULT_TRACKS = 1       # without --files / --tracks: the first file of music_dir only (a library folder holds many)


def record_path(cfg, dry: bool = False) -> Path:
    """stage9/music.json = the music applied to the draft; a --dry plan goes to music.dry.json."""
    return cfg.work_dir / "stage9" / ("music.dry.json" if dry else "music.json")


def read_record(cfg, d: dict) -> dict:
    """music.json if it describes the music in the draft (applied, its segment ids present), else SystemExit."""
    p = record_path(cfg)
    if not p.is_file():
        raise SystemExit(f"нет {p}: сначала apply_music.py без --dry")
    M = json.loads(p.read_text(encoding="utf-8"))
    if not M.get("applied"):
        raise SystemExit(f"{p.name}: applied = false (план --dry) — сначала apply_music.py без --dry")
    ids = {s["id"] for t in d["tracks"] if is_music_track(t) for s in t["segments"]}
    rec = {x.get("segment_id") for x in M.get("pieces", [])}
    if not rec or rec != ids:
        raise SystemExit(f"{p.name} не совпадает с музыкой в проекте ({len(rec & ids)} из {len(rec)} сегментов на месте, "
                         f"в проекте {len(ids)}) — проект менялся после apply_music: запустите apply_music.py снова")
    return M


def is_music_track(t: dict) -> bool:
    return t.get("type") == "audio" and re.fullmatch(rf"{TRACK}( \d+)?", t.get("name") or "") is not None


# ---------- plan ----------
def gaps(words: list[dict], dur: float, bounds: list[float], end0: float) -> list[tuple[float, float]]:
    """No speech >= MIN_GAP s (between words, before the first, after the last), clipped at the ending, split at
    chapter bounds; pieces >= MIN_PIECE."""
    out, prev = [], 0.0
    for w in sorted(words, key=lambda w: w["start"]):
        if w["start"] - prev >= MIN_GAP:
            out.append((prev, w["start"]))
        prev = max(prev, w["end"])
    if dur - prev >= MIN_GAP:
        out.append((prev, dur))
    res = []
    for a, b in out:
        b = min(b, end0)
        pts = [a] + [x for x in bounds if a < x < b] + [b]
        res += [(p, q) for p, q in zip(pts, pts[1:]) if q - p >= MIN_PIECE]
    return res


def levels(chapters: list[dict], gp, dur: float, vch: dict) -> list[list]:
    """Piecewise-constant target loudness of the music: [[t0, t1, lufs, kind]], kind speech | gap | ending."""
    end0 = max(0.0, dur - ENDING_LEN)
    out = []
    for c in chapters:
        base = vch[c["n"]] + UNDER_SPEECH
        t0, t1 = c["start"], min(c["end"], end0)
        if t1 <= t0:
            continue
        cur = t0
        for g0, g1 in gp:
            if g0 >= t0 - 1e-9 and g1 <= t1 + 1e-9:
                if g0 > cur:
                    out.append([cur, g0, base, "speech"])
                out.append([g0, g1, base + GAP_BOOST, "gap"])
                cur = g1
        if cur < t1:
            out.append([cur, t1, base, "speech"])
    if end0 < dur:
        last = next((c for c in reversed(chapters) if c["start"] <= end0), chapters[0])
        out.append([end0, dur, vch[last["n"]] + ENDING_REL, "ending"])
    merged = []
    for p in out:                         # too short -> into the previous piece
        if merged and (p[1] - p[0] < MIN_PIECE or abs(p[2] - merged[-1][2]) < 1e-6):
            merged[-1][1] = p[1]
        else:
            merged.append(p)
    if len(merged) > 1 and merged[0][1] - merged[0][0] < MIN_PIECE:
        merged[1][0] = merged[0][0]
        merged.pop(0)
    return merged


def regions(chapters: list[dict], keys: list[str]) -> list[dict]:
    """Contiguous chapter groups, one per track, cut at the chapter starts closest to equal shares of the duration."""
    n = min(len(keys), len(chapters))
    dur = chapters[-1]["end"]
    cuts, prev = [], 0
    for k in range(1, n):
        cand = range(prev + 1, len(chapters) - (n - k) + 1)
        j = min(cand, key=lambda j: abs(chapters[j]["start"] - k * dur / n))
        cuts.append(j)
        prev = j
    idx = [0] + cuts + [len(chapters)]
    return [{"track": keys[i], "chapters": [chapters[a]["n"], chapters[b - 1]["n"]],
             "start": chapters[a]["start"], "end": chapters[b - 1]["end"]} for i, (a, b) in enumerate(zip(idx, idx[1:]))]


def region_pieces(L: dict, T0: float, T1: float, tail: float) -> list[tuple[float, float, float]]:
    """(t0, t1, src0) of a track on [T0, T1): the file from 0, then its loop [loop_start, loop_end) again and again.
    The last piece keeps >= tail s (room for its fade): otherwise the previous loop ends at an earlier bar.
    A region that fits into the file is played straight through (no loop)."""
    ls, le = L["loop_start"], L["loop_end"]
    if T1 - T0 <= L["dur"] - beats.EDGE:
        return [(T0, T1, 0.0)]
    bars = [b for b in L.get("bar_starts") or [] if ls < b < le]
    out, t, src = [], T0, 0.0
    while t < T1 - 1e-9:
        end = t + (le - src)
        if end >= T1 - 1e-9:
            out.append((t, T1, src))
            break
        if T1 - end < tail:
            ok = [b for b in bars if b > src + tail and T1 - (t + b - src) >= tail]
            if ok:
                end = t + (max(ok) - src)
            elif T1 - t <= L["dur"] - beats.EDGE - src:   # the file goes on past the loop: play through
                out.append((t, T1, src))
                break
        out.append((t, end, src))
        t, src = end, ls
    return out


def split_levels(pieces, lv: list[list], T0: float, T1: float, Tb0: float, Tb1: float, first: bool, last: bool) -> list[dict]:
    lo = T0 + (RAMP if first else XFADE + RAMP)
    hi = T1 - ((FADE_END if last else XFADE) + RAMP)
    cuts = sorted({p[0] for p in lv[1:]})
    cuts = [c for c in cuts if lo < c < hi]

    def level_at(t):
        t = min(max(t, Tb0), Tb1 - 1e-6)
        p = next((p for p in lv if p[0] <= t < p[1]), lv[-1])
        return p[2], p[3]

    out = []
    for t0, t1, src0 in pieces:
        pts = [t0] + [c for c in cuts if t0 + RAMP <= c <= t1 - RAMP] + [t1]
        for a, b in zip(pts, pts[1:]):
            lufs, kind = level_at((a + b) / 2)
            q = {"t0": a, "t1": b, "src0": src0 + (a - t0), "lufs": lufs, "kind": kind}
            p = out[-1] if out else None
            if p and abs(p["lufs"] - lufs) < 1e-6 and abs(p["src0"] + p["t1"] - p["t0"] - q["src0"]) < 1e-6:
                p["t1"] = b
            else:
                out.append(q)
    for p, q in zip(out, out[1:]):
        cont = abs(p["src0"] + p["t1"] - p["t0"] - q["src0"]) < 1e-6
        p["right"] = q["left"] = "level" if cont else "seam"
    out[0]["left"] = None if first else "xfade_in"
    out[-1]["right"] = "fade_end" if last else "xfade_out"
    return out


def plan(tracks: dict, vl: dict, chapters: list[dict], words: list[dict], dur: float, keys: list[str]) -> dict:
    vch = {c["n"]: c["voice_S_median"] for c in vl["chapters"]}
    end0 = max(0.0, dur - ENDING_LEN)
    gp = gaps(words, dur, [c["start"] for c in chapters[1:]], end0)
    lv = levels(chapters, gp, dur, vch)
    regs = regions(chapters, keys)
    pieces = []
    for i, r in enumerate(regs):
        first, last = i == 0, i == len(regs) - 1
        T0 = r["start"] - (0 if first else XFADE / 2)
        T1 = r["end"] + (0 if last else XFADE / 2)
        L = tracks[r["track"]]
        tail = (FADE_END if last else XFADE) + RAMP
        ps = split_levels(region_pieces(L, T0, T1, tail), lv, T0, T1, r["start"], r["end"], first, last)
        for p in ps:
            p["track_key"] = r["track"]
        pieces += ps
    ovl = {"level": RAMP, "seam": SEAM}
    segs, warn = [], []
    for p in pieces:
        t0, t1, fi, fo = p["t0"], p["t1"], 0.0, 0.0
        if p["left"] in ovl:
            t0 -= ovl[p["left"]] / 2
            fi = ovl[p["left"]]
        if p["right"] in ovl:
            t1 += ovl[p["right"]] / 2
            fo = ovl[p["right"]]
        fi = XFADE if p["left"] == "xfade_in" else fi
        fo = XFADE if p["right"] == "xfade_out" else FADE_END if p["right"] == "fade_end" else fo
        L = tracks[p["track_key"]]
        src0 = p["src0"] - (p["t0"] - t0)
        if src0 < -1e-6 or src0 + (t1 - t0) > L["dur"] + 1e-6:
            raise SystemExit(f"кусок {t0:.3f}-{t1:.3f} выходит за файл {p['track_key']} (src {src0:.3f})")
        if fi + fo > t1 - t0 + 1e-6:
            raise SystemExit(f"кусок {t0:.3f}-{t1:.3f}: фейды {fi}+{fo} с длиннее куска — события слишком близко")
        gain = p["lufs"] - L["loop_S_median"]
        vol = 10 ** (gain / 20)
        if vol > MAX_VOLUME:
            warn.append(f"{p['track_key']} {t0:.1f}: нужно {gain:+.1f} dB, CapCut даёт максимум +20 dB")
            vol = MAX_VOLUME
        segs.append({**p, "t0": t0, "t1": t1, "src0": max(src0, 0.0), "volume": round(vol, 6), "gain_db": round(gain, 2),
                     "target_lufs": round(p["lufs"], 2), "fade_in": fi, "fade_out": fo})
    lanes: list[float] = []
    for s in sorted(segs, key=lambda s: s["t0"]):
        li = next((i for i, end in enumerate(lanes) if end <= s["t0"] + 1e-9), None)
        if li is None:
            lanes.append(0.0)
            li = len(lanes) - 1
        lanes[li] = s["t1"]
        s["lane"] = li
    return {"gaps": gp, "levels": lv, "regions": regs, "pieces": segs, "lanes": len(lanes), "warnings": warn}


# ---------- draft ----------
def remove_music(d: dict) -> int:
    """Drop the music tracks and the materials only they use. -> number of removed segments."""
    gone = [t for t in d["tracks"] if is_music_track(t)]
    ids = {m for t in gone for s in t["segments"] for m in [s.get("material_id")] + list(s.get("extra_material_refs") or [])}
    d["tracks"] = [t for t in d["tracks"] if not is_music_track(t)]
    keep = {m for t in d["tracks"] for s in t["segments"] for m in [s.get("material_id")] + list(s.get("extra_material_refs") or [])}
    drop = ids - keep
    for k, v in d["materials"].items():
        if isinstance(v, list):
            d["materials"][k] = [m for m in v if not (isinstance(m, dict) and m.get("id") in drop)]
    return sum(len(t["segments"]) for t in gone)


def apply(d: dict, pl: dict, tracks: dict, cache_root=None) -> list[str]:
    removed = remove_music(d)
    T = [effects.new_sfx_track(d, TRACK if i == 0 else f"{TRACK} {i + 1}") for i in range(pl["lanes"])]
    mats: dict[str, str] = {}
    D = d["duration"]
    for s in sorted(pl["pieces"], key=lambda s: s["t0"]):
        L = tracks[s["track_key"]]
        t0 = common.us(s["t0"])
        t1 = D if abs(common.us(s["t1"]) - D) <= 2 else common.us(s["t1"])
        tr = T[s["lane"]]
        sid = effects.music_segment(d, tr, L["file"], t0, t1 - t0, s["volume"])
        seg = next(x for x in tr["segments"] if x["id"] == sid)
        ix = common.index(d["materials"])
        if L["file"] in mats:
            d["materials"]["audios"] = [m for m in d["materials"]["audios"] if m["id"] != seg["material_id"]]
            seg["material_id"] = mats[L["file"]]
        else:
            mats[L["file"]] = seg["material_id"]
            ix[seg["material_id"]][1]["duration"] = common.us(L["dur"])
        seg["source_timerange"]["start"] = common.us(s["src0"])
        fade = next(ix[e][1] for e in seg["extra_material_refs"] if ix[e][0] == "audio_fades")
        fade.update(fade_in_duration=common.us(s["fade_in"]), fade_out_duration=common.us(s["fade_out"]))
        effects.attach(seg, effects.make("deep_effect", d, cache_root=cache_root))
        s["segment_id"] = sid
    for tr in T:
        tr["segments"] = common.by_start(tr["segments"])
    return [f"removed {removed} old music segments"] if removed else []


def report(pl: dict, tracks: dict, vl: dict, log) -> None:
    log(f"music: {len(pl['pieces'])} pieces on {pl['lanes']} tracks, pauses >= {MIN_GAP:g} s: {len(pl['gaps'])}")
    log(f"  voice (median short-term of speech): {vl['all']:.1f} LUFS; levels: under speech voice {UNDER_SPEECH:+g} LU, "
        f"pauses {GAP_BOOST:+g} dB, last {ENDING_LEN:g} s voice {ENDING_REL:+g} LU + fade {FADE_END:g} s")
    for r in pl["regions"]:
        ps = [p for p in pl["pieces"] if p["track_key"] == r["track"]]
        L = tracks[r["track"]]
        by = {}
        for p in ps:
            by.setdefault(p["kind"], []).append(p["gain_db"])
        dbs = ", ".join(f"{k} {min(v):+.1f}…{max(v):+.1f} dB" if max(v) - min(v) > 0.05 else f"{k} {v[0]:+.1f} dB"
                        for k, v in by.items())
        log(f"  {r['track']}: chapters {r['chapters'][0]}–{r['chapters'][1]} ({r['start']:.1f}–{r['end']:.1f} s), "
            f"loop {L['loop_start']:.2f}–{L['loop_end']:.2f} ({L['bars']} bars), music S {L['loop_S_median']:.1f} LUFS; "
            f"volume: {dbs}")
    for w in pl["warnings"]:
        log("  warning:", w)


def run(cfg, names=None, n_tracks: int | None = None, dry: bool = False, cache_root=None, guard_seconds: float = 5,
        log=print) -> dict:
    d = common.read_draft(cfg)
    files = prepare.music_files(cfg, names)
    keys = [f.name for f in files][: n_tracks or (len(files) if names else DEFAULT_TRACKS)]
    log(f"tracks ({len(keys)} of {len(files)} in {'--files' if names else 'music_dir'}): {', '.join(keys)}"
        + ("" if names or n_tracks or len(files) <= len(keys) else " — other tracks: --files NAME … or --tracks N"))
    tracks, vl, ch, words = prepare.run(cfg, d, keys, log)
    pl = plan(tracks, vl, ch, words, d["duration"] / 1e6, keys)
    report(pl, tracks, vl, log)
    notes = apply(d, pl, tracks, cache_root)
    errs = common.check_refs(d) + common.draft_overlaps(d)
    ends = [common.seg_end(s) for t in d["tracks"] if is_music_track(t) for s in t["segments"]]
    if max(ends) != d["duration"]:
        errs.append(f"music ends at {max(ends)} us, timeline {d['duration']} us")
    for n in notes:
        log(" ", n)
    log("VALIDATION:", "OK" if not errs else "FAIL")
    if errs:
        raise SystemExit("музыка не вставлена:\n  - " + "\n  - ".join(errs))
    out = {"applied": not dry, "under_speech_lu": UNDER_SPEECH, "gap_boost_db": GAP_BOOST, "ending_rel_lu": ENDING_REL,
           "ending_len_s": ENDING_LEN, "fade_end_s": FADE_END, "ramp_s": RAMP, "seam_s": SEAM, "xfade_s": XFADE,
           "voice_levels": vl, "tracks": {k: {kk: vv for kk, vv in tracks[k].items() if kk not in ("key", "bar_starts")}
                                          for k in keys},
           **{k: pl[k] for k in ("regions", "gaps", "levels", "pieces", "warnings")}}
    p = record_path(cfg, dry)
    p.parent.mkdir(parents=True, exist_ok=True)
    if dry:
        log(f"dry run, project not written; plan -> {p.name} (music.json = what is in the draft, untouched)")
    else:
        out["backup"] = str(common.write_draft(cfg, d, "stage9-music", dry=False, guard_seconds=guard_seconds))
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 9: background music (voice −13 LU, pauses +6 dB, ending −10 LU)")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--files", nargs="+", help="file names in music_dir, in play order (default: the first file of music_dir by name, choice printed)")
    ap.add_argument("--tracks", type=int, help="use the first N files of music_dir (or of --files)")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    try:
        run(common.load_config(a.config), a.files, a.tracks, a.dry)
    except effects.EffectCacheMissing as e:   # Deep not in the CapCut cache: nothing was written
        raise SystemExit(f"{e}\nмузыка не применена, проект не изменён")


if __name__ == "__main__":
    main()
