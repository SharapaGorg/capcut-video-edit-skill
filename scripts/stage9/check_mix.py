"""Stage 9 check by fact: render the music tracks of the draft (volume, source range, linear fades) and the timeline
voice, measure ebur128 short-term (3 s) every 100 ms.

    python -X utf8 scripts/stage9/check_mix.py --config config.json      (exit 1 on a failure)

Checks (STAGE_9.md «Проверка»):
- under speech the music is 13 ±2 LU below the voice: median of (voice S − music S) over 3-s speech windows that lie
  inside a speech level piece of stage9/music.json, per track region; the share of windows within ±2 LU is reported;
- last 20 s: 10 ±2 LU (speech windows there, if any);
- the end fades out: RMS of the last 250 ms >= 20 dB below the level before the fade;
- loop seams: from loop_end (or a bar start) to loop_start ±2 ms, no click (max sample step at the seam <= 3x the
  99.9th percentile of the steps in the second before).
Writes <work_dir>/stage9/check/report.json and mix_<a>-<b>.m4a windows to listen to. Read-only for the project.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import effects  # noqa: E402
import apply_music  # noqa: E402
import build_voice  # noqa: E402
import prepare  # noqa: E402

SR = effects.SR
TOL = 2.0


def render_music(d: dict, sr: int = SR) -> np.ndarray:
    """Sum of the music tracks' segments as CapCut plays them (linear fades), length = draft duration."""
    ix = common.index(d["materials"])
    out = np.zeros(int(round(d["duration"] * sr / 1e6)), np.float32)
    cache: dict[str, np.ndarray] = {}
    for t in d["tracks"]:
        if not apply_music.is_music_track(t):
            continue
        for s in t["segments"]:
            path = common.mat_path(ix, s)
            if path not in cache:
                cache[path] = effects.pcm(path, sr=sr)
            x = cache[path]
            i0 = int(round(s["target_timerange"]["start"] * sr / 1e6))
            n = int(round(s["target_timerange"]["duration"] * sr / 1e6))
            s0 = int(round(s["source_timerange"]["start"] * sr / 1e6))
            y = np.zeros(n, np.float32)
            part = x[s0:s0 + n]
            y[:len(part)] = part
            env = np.ones(n, np.float32)
            fade = next((ix[e][1] for e in s.get("extra_material_refs") or [] if e in ix and ix[e][0] == "audio_fades"), {})
            fi = min(n, int(round(fade.get("fade_in_duration", 0) * sr / 1e6)))
            fo = min(n, int(round(fade.get("fade_out_duration", 0) * sr / 1e6)))
            if fi:
                env[:fi] = np.linspace(0, 1, fi, endpoint=False)
            if fo:
                env[n - fo:] = np.minimum(env[n - fo:], np.linspace(1, 0, fo, endpoint=False))
            seg = y * env * float(s.get("volume", 1.0))
            m = min(n, len(out) - i0)
            out[i0:i0 + m] += seg[:m]
    return out


def _rms_db(x) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9)) if len(x) else -180.0


def _stats(dd) -> dict:
    if not len(dd):
        return {"n": 0}
    return {"n": int(len(dd)), "median": round(float(np.median(dd)), 2), "p5": round(float(np.percentile(dd, 5)), 2),
            "p95": round(float(np.percentile(dd, 95)), 2), "share_within_2": round(float((np.abs(dd - np.median(dd)) <= TOL).mean()), 3)}


def seams(M: dict, music: np.ndarray, sr: int = SR) -> list[dict]:
    out = []
    ps = M["pieces"]
    for p in ps:
        if p.get("right") != "seam":
            continue
        tc = p["t1"] - M["seam_s"] / 2
        q = next((q for q in ps if q.get("left") == "seam" and q["track_key"] == p["track_key"]
                  and abs(q["t0"] + M["seam_s"] / 2 - tc) < 1e-3), None)
        L = M["tracks"][p["track_key"]]
        src_end = p["src0"] + (tc - p["t0"])
        src_start = q["src0"] + (tc - q["t0"]) if q else None
        i, w = int(tc * sr), int(0.005 * sr)
        step = float(np.abs(np.diff(music[i - w:i + w])).max()) if i - w > 0 else 0.0
        ref = float(np.percentile(np.abs(np.diff(music[max(0, i - sr):i - w])), 99.9)) if i - w > 1 else 0.0
        out.append({"t": round(tc, 3), "track": p["track_key"], "src_end": round(src_end, 3),
                    "src_start": round(src_start, 3) if src_start is not None else None,
                    "to_loop_start": src_start is not None and abs(src_start - L["loop_start"]) <= 2e-3,
                    "from_loop_end": abs(src_end - L["loop_end"]) <= 2e-3,
                    "step_ratio": round(step / (ref + 1e-9), 2)})
    return out


def run(cfg, log=print) -> dict:
    d = common.read_draft(cfg)
    mp = cfg.work_dir / "stage9" / "music.json"
    if not mp.is_file():
        raise SystemExit(f"нет {mp}: сначала apply_music.py")
    M = json.loads(mp.read_text(encoding="utf-8"))
    dur = d["duration"] / 1e6
    voice = build_voice.build(cfg, d, log)
    music = render_music(d)
    voice = np.pad(voice, (0, max(0, len(music) - len(voice))))[:len(music)]
    Tv, Sv = effects.short_term(voice)
    Tm, Sm = effects.short_term(music)
    n = min(len(Tv), len(Tm))
    T, Sv, Sm = Tv[:n], Sv[:n], Sm[:n]
    sp = prepare.speech_windows(T, common.timeline_words(cfg), dur) & np.isfinite(Sv) & np.isfinite(Sm)

    def inside(kind):
        m = np.zeros(n, bool)
        for a, b, _, k in M["levels"]:
            if k == kind:
                m |= (T - prepare.WIN >= a - 1e-6) & (T <= b + 1e-6)
        return m

    fails, rep = [], {"music_I": effects.loudness(music)["I"], "regions": []}
    under = sp & inside("speech")
    for r in M["regions"]:
        st = _stats((Sv - Sm)[under & (T > r["start"]) & (T <= r["end"])])
        rep["regions"].append({"track": r["track"], "t": [r["start"], r["end"]], **st})
        if st["n"] and abs(st["median"] + M["under_speech_lu"]) > TOL:
            fails.append(f"{r['track']}: голос − музыка {st['median']} LU (норма {-M['under_speech_lu']:g} ±{TOL:g})")
    rep["under_speech"] = _stats((Sv - Sm)[under])
    if not rep["under_speech"]["n"]:
        fails.append("нет окон речи для замера")
    end = _stats((Sv - Sm)[sp & inside("ending")])
    rep["ending"] = end
    if end["n"] and abs(end["median"] + M["ending_rel_lu"]) > TOL:
        fails.append(f"концовка: голос − музыка {end['median']} LU (норма {-M['ending_rel_lu']:g} ±{TOL:g})")
    fe = M["fade_end_s"]
    env = {"before_fade": _rms_db(music[int((dur - fe - 0.5) * SR):int((dur - fe) * SR)]),
           "last_250ms": _rms_db(music[int((dur - 0.25) * SR):])}
    rep["ending_env_db"] = env
    if env["before_fade"] - env["last_250ms"] < 20:
        fails.append(f"конец музыки — не затухание ({env['before_fade']:.1f} → {env['last_250ms']:.1f} dB)")
    rep["seams"] = seams(M, music)
    bad = [s for s in rep["seams"] if not s["to_loop_start"] or s["step_ratio"] > 3]
    if bad:
        fails.append(f"склейки петель не на начале петли или со щелчком: {[s['t'] for s in bad]}")
    out = cfg.work_dir / "stage9" / "check"
    wins = [(a, min(a + 60, dur)) for a in np.linspace(0, max(0, dur - 60), 3)] if dur > 120 else [(0.0, dur)]
    if dur > 120:
        wins.append((dur - 40, dur))
    rep["windows"] = []
    for a, b in wins:
        i0, i1 = int(a * SR), int(b * SR)
        f = effects.encode(voice[i0:i1] + music[i0:i1], out / f"mix_{int(a)}-{int(b)}.m4a", args=("-c:a", "aac", "-b:a", "160k"))
        rep["windows"].append({"window": [round(a, 1), round(b, 1)], "file": f.name,
                               "voice_I": effects.loudness(voice[i0:i1])["I"], "music_I": effects.loudness(music[i0:i1])["I"]})
    rep["fails"], rep["ok"] = fails, not fails
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    us_ = rep["under_speech"]
    log(f"under speech: voice − music median {us_.get('median')} LU (p5 {us_.get('p5')}, p95 {us_.get('p95')}, "
        f"{us_.get('share_within_2')} of windows within ±2), ending {end.get('median')} LU, "
        f"fade {env['before_fade']:.1f} → {env['last_250ms']:.1f} dB, seams {len(rep['seams'])}")
    log("VALIDATION:", "OK" if not fails else "FAIL")
    for f in fails:
        log("  -", f)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 9: check the music mix by fact (read-only)")
    ap.add_argument("--config", default="config.json")
    a = ap.parse_args(argv)
    if not run(common.load_config(a.config))["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
