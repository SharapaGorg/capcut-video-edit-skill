"""Stages 9–10: music under the voice (−13 LU, pauses +6 dB, ending −10 LU + fade, Deep), export loudnorm, srt/chapters."""
import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

import common
import effects
from test_layout import S, TID, make_project, seg, snapshot, vmat, wav  # noqa: F401

SR = 48000
DEEP = "7021052537344102913"


@pytest.fixture
def cache(tmp_path):
    root = tmp_path / "capcut" / "User Data" / "Cache" / "effect"
    (root / DEEP / "h").mkdir(parents=True)
    return root


def words_json(path: Path, spans, dur):
    """transcript_timeline.json with 0.3-s words over each (a, b) speech span."""
    words = []
    for a, b in spans:
        t = a
        while t + 0.3 <= b:
            words.append({"word": "слово", "start": round(t, 3), "end": round(t + 0.3, 3)})
            t += 0.35
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"duration": dur, "segments": [{"id": 1, "start": words[0]["start"], "end": words[-1]["end"],
                                                               "text": "", "words": words}]}, ensure_ascii=False),
                    encoding="utf-8")


def music_track(path: Path, seconds=20.0, bpm=120):
    """Pad chord + a click on every beat (accent on the bar), so librosa finds a beat grid."""
    t = np.arange(int(seconds * SR)) / SR
    x = 0.05 * (np.sin(2 * np.pi * 220 * t) + np.sin(2 * np.pi * 277.2 * t) + np.sin(2 * np.pi * 329.6 * t))
    beat = 60.0 / bpm
    rng = np.random.default_rng(5)
    n = int(0.08 * SR)
    env = np.exp(-np.arange(n) / (0.015 * SR))
    for k in range(int(seconds / beat)):
        i = int(k * beat * SR)
        amp = 0.5 if k % 4 == 0 else 0.25
        click = amp * env * (np.sin(2 * np.pi * 90 * np.arange(n) / SR) + 0.3 * rng.standard_normal(n))
        x[i:i + n] += click[: len(x) - i]
    return wav(path, x.astype(np.float32))


def music_project(make_project, tmp_path, music=True):
    """60 s screencast with voice except a 4-s pause 30–34 s; 3 chapters (0, 20, 40); one 20-s music track."""
    rng = np.random.default_rng(2)
    t = np.arange(60 * SR) / SR
    v = 0.1 * np.sin(2 * np.pi * 200 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)) + 0.005 * rng.standard_normal(len(t))
    v[30 * SR:34 * SR] = 0.0
    sc = wav(tmp_path / "src" / "screencasts" / "s1.wav", v.astype(np.float32))
    d = {"id": TID, "duration": 60 * S, "materials": {"videos": [vmat("MSC", sc.as_posix())]},
         "tracks": [{"id": "T0", "type": "video", "name": "", "segments": [seg("SC", "MSC", 0, 60 * S, 0)]}]}
    cfg = make_project(d)
    words_json(cfg.work_dir / "stage3" / "transcript_timeline.json", [(0.2, 30.0), (34.0, 59.8)], 60.0)
    (cfg.work_dir / "stage3" / "chapters_timeline.json").write_text(json.dumps({"chapters": [
        {"n": 1, "title": "Вступление", "start": 0.0, "end": 20.0},
        {"n": 2, "title": "Середина", "start": 20.0, "end": 40.0},
        {"n": 3, "title": "Итог", "start": 40.0, "end": 60.0}]}, ensure_ascii=False), encoding="utf-8")
    if music:
        mdir = tmp_path / "music"
        music_track(mdir / "track.wav")
        cfg.music_dir = str(mdir)
    return cfg


def lufs(x):
    return effects.loudness(x)["I"]


# ---------- stage 9 ----------
def test_music_level_minus_13(make_project, tmp_path, cache):
    import apply_music
    import build_voice
    import check_mix
    cfg = music_project(make_project, tmp_path)
    res = apply_music.run(cfg, dry=False, cache_root=cache, guard_seconds=0, log=lambda *a: None)
    d = common.read_draft(cfg)
    assert not common.check_refs(d) and not common.draft_overlaps(d)
    mus = [t for t in d["tracks"] if apply_music.is_music_track(t)]
    assert [t["name"] for t in mus][:1] == ["Музыка"]
    segs = [s for t in mus for s in t["segments"]]
    ix = common.index(d["materials"])
    # Deep on every piece; one audio material per file
    for s in segs:
        assert any(ix[e][0] == "audio_effects" and ix[e][1]["name"] == "Deep" for e in s["extra_material_refs"])
    assert len({s["material_id"] for s in segs}) == 1
    # the 20-s track is looped to cover 60 s; ends with a 2-s fade, not a cut
    assert max(common.seg_end(s) for s in segs) == d["duration"]
    assert min(s["target_timerange"]["start"] for s in segs) == 0
    last = max(segs, key=common.seg_end)
    fade = next(ix[e][1] for e in last["extra_material_refs"] if ix[e][0] == "audio_fades")
    assert fade["fade_out_duration"] == 2 * S
    assert any(p["right"] == "seam" for p in res["pieces"])

    voice = build_voice.build(cfg, d)
    music = check_mix.render_music(d)
    w = lambda x, a, b: x[int(a * SR):int(b * SR)]  # noqa: E731
    diff = lufs(w(voice, 4, 19)) - lufs(w(music, 4, 19))
    assert abs(diff - 13.0) <= 1.0, diff
    boost = lufs(w(music, 30.6, 33.4)) - lufs(w(music, 22, 29))
    assert abs(boost - 6.0) <= 1.5, boost
    end = lufs(w(voice, 41, 56)) - lufs(w(music, 41, 56))
    assert abs(end - 10.0) <= 1.5, end
    tail = w(music, 59.75, 60)
    assert np.sqrt(np.mean(tail ** 2)) < 0.1 * np.sqrt(np.mean(w(music, 56, 57.5) ** 2))

    rep = check_mix.run(cfg, log=lambda *a: None)
    assert rep["ok"], rep["fails"]
    # re-run replaces the music, does not stack it
    apply_music.run(cfg, dry=False, cache_root=cache, guard_seconds=0, log=lambda *a: None)
    d2 = common.read_draft(cfg)
    assert sum(len(t["segments"]) for t in d2["tracks"] if apply_music.is_music_track(t)) == len(segs)
    assert len(d2["materials"]["audios"]) == 1
    # all music +3 dB; the voice by source (only the screencast here -> nothing to match)
    import measure_lufs
    import music_gain
    v0 = {s["id"]: s["volume"] for t in d2["tracks"] if apply_music.is_music_track(t) for s in t["segments"]}
    music_gain.run(cfg, 3.0, guard_seconds=0, log=lambda *a: None)
    d3 = common.read_draft(cfg)
    for t in d3["tracks"]:
        if apply_music.is_music_track(t):
            for s in t["segments"]:
                assert s["volume"] == pytest.approx(v0[s["id"]] * 10 ** (3 / 20), rel=1e-4)
    lu = measure_lufs.run(cfg, log=lambda *a: None)
    assert lu["voice"]["integrated_lufs"] is None and lu["screencast"]["integrated_lufs"] < -20 and lu["ok"]


def test_music_needs_music_dir_and_deep_cache(make_project, tmp_path, cache):
    import apply_music
    cfg = music_project(make_project, tmp_path, music=False)
    before = snapshot(cfg)
    with pytest.raises(SystemExit, match="music_dir"):
        apply_music.run(cfg, dry=False, cache_root=cache, guard_seconds=0, log=lambda *a: None)
    cfg = music_project(make_project, tmp_path)
    with pytest.raises(effects.EffectCacheMissing):
        apply_music.run(cfg, dry=False, cache_root=tmp_path / "nocache", guard_seconds=0, log=lambda *a: None)
    apply_music.run(cfg, dry=True, cache_root=cache, log=lambda *a: None)
    assert snapshot(cfg) == before


def test_dry_plan_is_not_the_record(make_project, tmp_path, cache):
    """--dry writes music.dry.json; check_mix / music_gain refuse a record that is not the music in the draft."""
    import apply_music
    import check_mix
    import music_gain
    cfg = music_project(make_project, tmp_path)
    quiet = lambda *a: None  # noqa: E731
    apply_music.run(cfg, dry=True, cache_root=cache, log=quiet)
    st = cfg.work_dir / "stage9"
    assert (st / "music.dry.json").is_file() and not (st / "music.json").exists()
    for f in (lambda: check_mix.run(cfg, log=quiet), lambda: music_gain.run(cfg, 3.0, guard_seconds=0, log=quiet)):
        with pytest.raises(SystemExit, match="без --dry"):
            f()
    apply_music.run(cfg, dry=False, cache_root=cache, guard_seconds=0, log=quiet)
    rec = (st / "music.json").read_text(encoding="utf-8")
    # a later --dry leaves the record alone
    apply_music.run(cfg, dry=True, cache_root=cache, log=quiet)
    assert (st / "music.json").read_text(encoding="utf-8") == rec
    # applied: false -> refused
    (st / "music.json").write_text(json.dumps({**json.loads(rec), "applied": False}), encoding="utf-8")
    for f in (lambda: check_mix.run(cfg, log=quiet), lambda: music_gain.run(cfg, 3.0, guard_seconds=0, log=quiet)):
        with pytest.raises(SystemExit, match="applied = false"):
            f()
    # the draft no longer holds the recorded segments -> refused, draft untouched
    (st / "music.json").write_text(rec, encoding="utf-8")
    d = common.read_draft(cfg)
    d["tracks"] = [t for t in d["tracks"] if not apply_music.is_music_track(t)]
    common.write_draft(cfg, d, "test", dry=False, guard_seconds=0)
    before = snapshot(cfg)
    for f in (lambda: check_mix.run(cfg, log=quiet), lambda: music_gain.run(cfg, 3.0, guard_seconds=0, log=quiet)):
        with pytest.raises(SystemExit, match="не совпадает"):
            f()
    assert snapshot(cfg) == before


def test_default_one_track_of_a_library(make_project, tmp_path, cache):
    """A folder with several tracks: default = the first one only (printed); --tracks N / --files choose more."""
    import apply_music
    cfg = music_project(make_project, tmp_path)
    music_track(Path(cfg.music_dir) / "zz_second.wav", seconds=20.0, bpm=100)
    logs = []
    res = apply_music.run(cfg, dry=True, cache_root=cache, log=lambda *a: logs.append(" ".join(map(str, a))))
    assert {p["track_key"] for p in res["pieces"]} == {"track.wav"}
    assert any("track.wav" in x and "1 of 2" in x and "--files" in x for x in logs), logs
    res = apply_music.run(cfg, n_tracks=2, dry=True, cache_root=cache, log=lambda *a: None)
    assert [r["track"] for r in res["regions"]] == ["track.wav", "zz_second.wav"]
    res = apply_music.run(cfg, names=["zz_second.wav"], dry=True, cache_root=cache, log=lambda *a: None)
    assert {p["track_key"] for p in res["pieces"]} == {"zz_second.wav"}


def test_music_plan_short_video_and_no_chapters(make_project, tmp_path, cache):
    """Video shorter than the track: no loop seam; no chapters file -> one region."""
    import apply_music
    cfg = music_project(make_project, tmp_path)
    (cfg.work_dir / "stage3" / "chapters_timeline.json").unlink()
    long = tmp_path / "music_long"
    music_track(long / "long.wav", seconds=75.0)
    cfg.music_dir = str(long)
    res = apply_music.run(cfg, dry=True, cache_root=cache, log=lambda *a: None)
    assert not any(p["right"] == "seam" for p in res["pieces"])
    assert {p["track_key"] for p in res["pieces"]} == {"long.wav"}
    assert res["pieces"][-1]["fade_out"] == 2.0


def test_regions_change_track_only_at_chapter_bounds():
    import apply_music
    ch = [{"n": i + 1, "start": 60.0 * i, "end": 60.0 * (i + 1)} for i in range(8)]
    reg = apply_music.regions(ch, ["a", "b", "c"])
    assert [r["track"] for r in reg] == ["a", "b", "c"]
    assert reg[0]["start"] == 0 and reg[-1]["end"] == 480.0
    bounds = {c["start"] for c in ch}
    assert all(r["start"] in bounds for r in reg)
    assert apply_music.regions(ch[:2], ["a", "b", "c"])[-1]["track"] == "b"


# ---------- stage 10 ----------
def synth_export(path: Path, seconds=10, amp=0.02):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=1920x1080:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={seconds}",
                    "-af", f"volume={amp}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(path)], check=True)
    return path


def test_loudnorm_synthetic(make_project, tmp_path):
    import loudnorm
    cfg = music_project(make_project, tmp_path, music=False)
    tt = cfg.work_dir / "stage3" / "transcript_timeline.json"
    tt.write_text(json.dumps({**json.loads(tt.read_text(encoding="utf-8")), "duration": 10.0}), encoding="utf-8")
    src = synth_export(tmp_path / "exp" / "export.mp4")
    before = loudnorm.measure(src)
    assert before["I"] < -20
    code, rep, final = loudnorm.run(src, cfg, no_whisper=True, log=lambda *a: None)
    assert final.name == "export_final.mp4" and final.is_file()
    m = loudnorm.measure(final)
    assert abs(m["I"] + 14.0) <= 0.5, m
    assert m["TP"] <= -1.0, m
    assert code == 0, rep.read_text(encoding="utf-8")
    assert rep == cfg.work_dir / "stage10" / "export_report.md"
    txt = rep.read_text(encoding="utf-8")
    assert "export_final.mp4" in txt and "1920x1080" in txt
    assert len(list((cfg.work_dir / "stage10" / "export_frames").glob("*.png"))) == 1
    si = loudnorm.stream_info(final)
    assert abs(si["a_dur"] - si["v_dur"]) <= 1 / 30 + 1e-6
    # already in norm -> no new file, the final is the input
    code2, _, final2 = loudnorm.run(final, cfg, no_whisper=True, log=lambda *a: None)
    assert code2 == 0 and final2 == final and not (final.parent / "export_final_final.mp4").exists()


def test_loudnorm_flags_black_frames_and_dry(make_project, tmp_path):
    import loudnorm
    cfg = music_project(make_project, tmp_path, music=False)
    src = tmp_path / "black.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:size=1920x1080:rate=30:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4", "-af", "volume=0.02",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)],
                   check=True)
    code, rep, final = loudnorm.run(src, cfg, dry=True, no_whisper=True, log=lambda *a: None)
    assert code == 1 and final == src
    assert not (tmp_path / "black_final.mp4").exists()
    txt = rep.read_text(encoding="utf-8")
    assert "чёрн" in txt and "--dry" in txt


def srt_words(path: Path):
    """Long sentences with a pause; one 7+ s run without punctuation."""
    text = ("Сегодня разберём как анализировать конкурентов в инстаграме, и зачем это вообще нужно. "
            "Сначала выберем нишу и соберём список аккаунтов которые растут быстрее всего за последний месяц "
            "и посмотрим какие форматы у них работают лучше всего и почему так происходит на самом деле. "
            "Дальше считаем медиану просмотров. Итог простой.")
    words, t = [], 0.5
    for i, w in enumerate(text.split()):
        words.append({"word": w, "start": round(t, 3), "end": round(t + 0.32, 3)})
        t += 0.4 + (1.2 if i == 12 else 0.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"duration": round(t + 30, 3), "segments": [{"id": 1, "words": words}]},
                               ensure_ascii=False), encoding="utf-8")
    return words, t + 30


def parse_srt(p: Path):
    out = []
    for b in re.split(r"\n\s*\n", p.read_text(encoding="utf-8").strip()):
        ls = b.split("\n")
        m = re.match(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", ls[1])
        g = list(map(int, m.groups()))
        out.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1e3, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1e3, ls[2:]))
    return out


def test_srt_line_len_le_42(make_project, tmp_path):
    import build_srt
    cfg = music_project(make_project, tmp_path, music=False)
    words, dur = srt_words(cfg.work_dir / "stage3" / "transcript_timeline.json")
    (cfg.work_dir / "stage3" / "chapters_timeline.json").write_text(json.dumps({"chapters": [
        {"n": 1, "title": "Вступление", "start": 0.0, "end": 12.0},
        {"n": 2, "title": "Ниша", "start": 12.0, "end": 25.0},
        {"n": 3, "title": "Итог", "start": 25.0, "end": dur}]}, ensure_ascii=False), encoding="utf-8")
    desc = tmp_path / "description.md"
    desc.write_text("Описание ролика.\n\nТаймкоды:\n00:00 Старое\n01:10 Старое 2\n\nСсылки: x\n", encoding="utf-8")
    cfg.description_md = str(desc)
    res = build_srt.run(cfg, log=lambda *a: None)
    assert not res["problems"], res["problems"]
    blocks = parse_srt(cfg.work_dir / "stage10" / "subtitles.srt")
    assert blocks
    for s, e, lines in blocks:
        assert 1 <= len(lines) <= 2
        assert all(len(x) <= 42 for x in lines), lines
        assert 1.0 - 1e-6 <= e - s <= 7.0 + 1e-6, (s, e, lines)
    assert all(b[0] >= a[1] for a, b in zip(blocks, blocks[1:]))
    # every word, whole and in order
    assert " ".join(x for _, _, ls in blocks for x in ls).split() == [w["word"] for w in words]
    assert (cfg.work_dir / "stage10" / "chapters.txt").read_text(encoding="utf-8") == "00:00 Вступление\n00:12 Ниша\n00:25 Итог\n"
    assert desc.read_text(encoding="utf-8") == (
        "Описание ролика.\n\nТаймкоды:\n00:00 Вступление\n00:12 Ниша\n00:25 Итог\n\nСсылки: x\n")


def test_srt_description_cases(make_project, tmp_path):
    import build_srt
    cfg = music_project(make_project, tmp_path, music=False)
    srt_words(cfg.work_dir / "stage3" / "transcript_timeline.json")
    logs = []
    cfg.description_md = str(tmp_path / "nope.md")
    res = build_srt.run(cfg, log=lambda *a: logs.append(" ".join(map(str, a))))
    assert "description.md не найден, не генерирую" in "\n".join(logs)
    assert not (tmp_path / "nope.md").exists()
    # chapters from the 3-chapter fixture (0/20/40): ok; no timecode block -> appended
    desc = tmp_path / "d.md"
    desc.write_text("Текст без таймкодов.\n", encoding="utf-8")
    cfg.description_md = str(desc)
    res = build_srt.run(cfg, log=lambda *a: None)
    assert res["description"] == "appended"
    assert desc.read_text(encoding="utf-8").startswith("Текст без таймкодов.\n")
    assert desc.read_text(encoding="utf-8").rstrip().endswith("00:40 Итог")
    # bad chapters (one < 10 s, < 3) -> problems, description untouched
    (cfg.work_dir / "stage3" / "chapters_timeline.json").write_text(json.dumps({"chapters": [
        {"n": 1, "title": "А", "start": 0.0, "end": 5.0}, {"n": 2, "title": "Б", "start": 5.0, "end": 60.0}]}),
        encoding="utf-8")
    before = desc.read_text(encoding="utf-8")
    res = build_srt.run(cfg, log=lambda *a: None)
    assert any("10 с" in p for p in res["problems"]) and any("3" in p for p in res["problems"])
    assert desc.read_text(encoding="utf-8") == before


def test_loudnorm_srt_sync_rms(make_project, tmp_path):
    """Continuous speech-like bursts (0.15-s breaths, never a 1.5-s silence) with srt lines on phrase starts:
    --no-whisper -> the RMS onset is the rising edge at the line, not the previous phrase still sounding."""
    import loudnorm
    cfg = music_project(make_project, tmp_path, music=False)
    tt = cfg.work_dir / "stage3" / "transcript_timeline.json"
    tt.write_text(json.dumps({**json.loads(tt.read_text(encoding="utf-8")), "duration": 12.0}), encoding="utf-8")
    t = np.arange(12 * SR) / SR
    a = np.zeros(len(t), np.float32)
    starts = [1.0, 3.65, 6.3, 8.95]
    for s in starts:
        m = (t >= s) & (t < s + 2.5)
        a[m] = 0.2 * np.sin(2 * np.pi * 300 * t[m]) * (0.7 + 0.3 * np.sin(2 * np.pi * 5 * t[m]))
    aud = wav(tmp_path / "a.wav", a)
    src = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=12",
                    "-i", str(aud), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(src)], check=True)
    srt = cfg.work_dir / "stage10" / "subtitles.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    srt.write_text("\n".join(f"{i + 1}\n00:00:{s:06.3f} --> 00:00:{s + 2.5:06.3f}\nраз два три четыре\n".replace(".", ",")
                             for i, s in enumerate(starts)), encoding="utf-8")
    code, rep, final = loudnorm.run(src, cfg, no_whisper=True, log=lambda *a: None)
    txt = rep.read_text(encoding="utf-8")
    assert "совпало: 4 из 4" in txt and "RMS" in txt, txt
    assert code == 0, txt


def test_srt_empty_transcript_and_bom_description(make_project, tmp_path):
    import build_srt
    cfg = music_project(make_project, tmp_path, music=False)
    tt = cfg.work_dir / "stage3" / "transcript_timeline.json"
    srt_words(tt)
    desc = tmp_path / "bom.md"
    bom = b"\xef\xbb\xbf"
    desc.write_bytes(bom + "00:00 Старое\n00:30 Старое 2\n\nТекст\n".encode("utf-8"))
    cfg.description_md = str(desc)
    assert build_srt.run(cfg, log=lambda *a: None)["description"] == "replaced"
    assert desc.read_bytes() == bom + "00:00 Вступление\n00:20 Середина\n00:40 Итог\n\nТекст\n".encode("utf-8")
    tt.write_text(json.dumps({"duration": 10.0, "segments": []}), encoding="utf-8")
    with pytest.raises(SystemExit, match="нет слов"):
        build_srt.run(cfg, log=lambda *a: None)
