"""Profile «ref» (references/shorts.md §5): spectrum matching of the voice to the editor's reference, profile constants."""
import json
import subprocess
import types
from pathlib import Path

import numpy as np
import pytest

import build_render
import common
import voice_ref

SR = 48000


def bright_voice(path: Path, seconds=6.0, tilt_db_per_oct=-2.0, seed=5) -> Path:
    """Pink-ish noise (−3 dB/oct) with a speech envelope and pauses: 5–7 dB brighter than the reference at 2–8 kHz
    (as screencast audio is), yet inside the ±8 dB reach of the fit. tilt: extra dB/oct above 500 Hz."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    f1 = np.maximum(f, 20.0)
    mag = f1 ** -0.5                                                  # pink: −3 dB/oct in power
    mag *= 10 ** (tilt_db_per_oct * np.maximum(np.log2(f1 / 500.0), 0) / 20)   # tilt above 500 Hz only
    mag[f < 20] = 0
    x = np.fft.irfft(spec * mag, n)
    t = np.arange(n) / SR
    env = np.clip(np.sin(2 * np.pi * 2.5 * t), 0, None) ** 1.5       # syllables
    env *= (np.sin(2 * np.pi * 0.4 * t) > -0.6)                       # pauses
    x = x * env
    x = 0.3 * x / (np.max(np.abs(x)) + 1e-9)
    raw = path.with_suffix(".f32")
    x.astype(np.float32).tofile(raw)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", str(raw),
                    "-c:a", "pcm_s16le", str(path)], check=True)
    raw.unlink()
    return path


def band_diff(meas, target=voice_ref.REF_BANDS, lo=80, hi=8000):
    return {k: round(meas[k] - t, 1) for k, t in target.items()
            if int(k.split('-')[0]) >= lo and int(k.split('-')[1]) <= hi}


def test_ref_bands_are_the_mean_of_the_two_reference_shorts():
    # REPORT.md §2, rows «ref A» / «ref B», dB rel. 500–1000 Hz
    a = {'80-160': 0.1, '160-250': 5.1, '250-500': 6.9, '1000-2000': -10.2, '2000-4000': -13.9, '4000-6000': -20.9, '6000-8000': -23.8, '8000-12000': -29.4}
    b = {'80-160': 2.9, '160-250': 7.6, '250-500': 6.6, '1000-2000': -8.8, '2000-4000': -14.1, '4000-6000': -21.6, '6000-8000': -20.9, '8000-12000': -25.8}
    for k in a:
        assert abs(voice_ref.REF_BANDS[k] - (a[k] + b[k]) / 2) <= 0.06, k


def test_match_fx_lands_on_the_target_spectrum(tmp_path):
    src = bright_voice(tmp_path / "voice_raw.wav")
    before = voice_ref.spectrum_of(src)
    assert any(abs(d) > 2 for d in band_diff(before).values()), before     # the source does need a fit
    fx = voice_ref.match_fx(src, report=tmp_path / "voice_match.json")
    info = voice_ref.match_fx.last
    assert fx.startswith("highpass=f=70") and "deesser" in fx and "acompressor" in fx and fx.endswith("pan=stereo|c0=c0|c1=c0")
    assert 1 <= len(info["passes"]) <= 2
    out = tmp_path / "voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af", fx, str(out)], check=True)
    after = voice_ref.spectrum_of(out)
    diff = band_diff(after)
    assert all(abs(d) <= 2.0 for d in diff.values()), (diff, info["gains"])
    assert info["ok"] and all(abs(g) <= voice_ref.MAX_GAIN for g in info["gains"].values())
    rep = json.loads((tmp_path / "voice_match.json").read_text(encoding="utf-8"))
    assert set(rep) >= {"source", "target", "passes", "gains", "after", "ok", "fx"} and rep["target"] == voice_ref.REF_BANDS
    # output = stereo dual mono at 48 k
    pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=channels,sample_rate", "-of", "csv=p=0", str(out)],
                        capture_output=True, text=True, check=True).stdout.strip()
    assert pr == "48000,2"


def test_gain_clip_and_eq_string():
    gains = {k: 0.0 for k in voice_ref.REF_BANDS}
    assert voice_ref.eq_string(gains) == "" and voice_ref.chain(gains) == ",".join(voice_ref.FIXED)
    gains["4000-6000"] = -3.5
    s = voice_ref.eq_string(gains)
    assert s == "equalizer=f=4899:t=o:w=0.58:g=-3.50"
    # a huge source/target difference is clipped to ±max_gain
    fake = {k: 30.0 for k in voice_ref.REF_BANDS}
    assert not voice_ref.within(fake)
    assert all(abs(voice_ref.residual(fake)[k]) > 8 for k in fake)


def test_profiles_pick_constants_and_legacy_is_unchanged():
    leg = build_render.profile("legacy")
    assert leg["voice_fx"] == build_render.VOICE_FX and leg["voice_lufs"] == build_render.VOICE_LUFS == -19.0
    assert leg["music_rel"] == build_render.MUSIC_REL == -13.0 and leg["music_in"] is None and leg["music_fade_in"] == 0.8
    assert (leg["final_i"], leg["final_tol"], leg["final_tp"]) == (build_render.FINAL_I, build_render.FINAL_TOL, build_render.FINAL_TP) == (-14.0, 0.5, -1.1)
    ref = build_render.profile("ref")
    assert ref["voice_fx"] is None and ref["voice_lufs"] == -17.5 and ref["music_rel"] == -16.0
    assert (ref["final_i"], ref["final_tol"], ref["final_tp"]) == (-17.5, 0.5, -1.0) and ref["music_in"] == "hook" and ref["music_fade_in"] == 0.3
    assert build_render.profile(None)["name"] == build_render.DEFAULT_PROFILE == "ref"
    with pytest.raises(SystemExit, match="audio_profile"):
        build_render.profile("nope")
    # in_norm defaults to legacy (existing tests), the ref profile moves the window
    assert build_render.in_norm(-14.2, -1.2) and not build_render.in_norm(-17.5, -1.0)
    assert build_render.in_norm(-17.5, -1.0, ref) and not build_render.in_norm(-14.0, -1.1, ref)


def test_config_audio_profile(tmp_path):
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps({"project_dir": str(tmp_path / "nope"), "timeline_id": "abc", "sources": {}}), encoding="utf-8")
    assert common.load_config(str(cp)).audio_profile == "ref"
    cp.write_text(json.dumps({"project_dir": str(tmp_path / "nope"), "timeline_id": "abc", "sources": {}, "audio_profile": "legacy"}), encoding="utf-8")
    assert common.load_config(str(cp)).audio_profile == "legacy"


def test_music_in_defaults_to_the_hook_end():
    ctx = types.SimpleNamespace(dyn=False)
    ref, leg = build_render.profile("ref"), build_render.profile("legacy")
    assert build_render.hook_end(ctx, {}) == 0.0
    assert build_render.hook_end(ctx, {"hook": {"lines": ["x"]}}) == build_render.HOOK_DUR == 2.4
    assert build_render.hook_end(types.SimpleNamespace(dyn=True), {"hook": {"lines": []}}) == build_render.DYN_HOOK == 1.5
    assert build_render.hook_end(ctx, {"hook": {"dur": 3.1}}) == 3.1
    assert build_render.music_in_s(ctx, {"hook": {"dur": 3.1}}, ref, 30.0) == 3.1
    assert build_render.music_in_s(ctx, {"hook": {"dur": 3.1}, "music_in": 7.5}, ref, 30.0) == 7.5
    assert build_render.music_in_s(ctx, {"music_in": 0}, ref, 30.0) == 0.0
    assert build_render.music_in_s(ctx, {"music_in": 99}, ref, 30.0) == 28.0          # clamped: at least 2 s of music
    assert build_render.music_in_s(ctx, {"hook": {"dur": 3.1}, "music_in": 7.5}, leg, 30.0) == 0.0   # legacy: from 0 s


def test_final_loop_ref_profile(tmp_path):
    src = bright_voice(tmp_path / "pre.wav", seconds=4.0)
    prof = build_render.profile("ref")
    r = build_render.final_loop(src, tmp_path / "mix_final.m4a", prof=prof)
    m = build_render.measure(tmp_path / "mix_final.m4a")
    assert r["ok"] and abs(m["I"] + 17.5) <= 0.5 and m["TP"] <= -1.0, (r, m)
    with pytest.raises(SystemExit, match=r"-17\.5"):
        build_render.deliver(tmp_path / "pre.wav", tmp_path / "out" / "x.mp4", {"in_norm": False, "final_I": -20, "final_TP": -3, "profile": "ref"})
