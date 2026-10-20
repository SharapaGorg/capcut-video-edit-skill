import json
from pathlib import Path

import pytest

import effects

FIX = Path(__file__).parent / "fixtures" / "mini_project" / "draft_content.json"
TPL = Path(__file__).resolve().parent.parent / "assets" / "templates"
NAMES = ["voice_crisper", "reduce_noise", "deep_effect", "mask_circle", "adjust_circle",
         "adjustment_block", "keyframes_zoom", "sfx_segment", "music_segment"]
FORBIDDEN = ["writelo", "Гайд", "IMG_E02", "E87DC4D2", "AiVideoEditing", "4-гайд", "shara"]


@pytest.fixture
def draft():
    return json.loads(FIX.read_text(encoding="utf-8"))


@pytest.fixture
def cache(tmp_path):
    """Fake CapCut layout: <tmp>/User Data/Cache/effect/<id>/<hash>, <tmp>/Apps/9.9/Resources/audiosami/."""
    root = tmp_path / "User Data" / "Cache" / "effect"
    for rid, h in [("7491147795483659521", "afa899afa9b93e99cce244324bffe563"),
                   ("1068046525", "otherhash"),
                   ("7501974767453474064", "e7194e6f595ab73d826a78becfe33a61")]:
        (root / rid / h).mkdir(parents=True)
    (tmp_path / "Apps" / "9.9.0" / "Resources" / "audiosami").mkdir(parents=True)
    return root


def test_all_templates_exist_and_clean():
    for n in NAMES:
        text = (TPL / f"{n}.json").read_text(encoding="utf-8")
        assert not [f for f in FORBIDDEN if f in text], n
        assert ":/" not in text.replace("{{", ""), n


def test_make_voice_crisper_adds_material_with_cache_path(draft, cache):
    mid = effects.make("voice_crisper", draft, cache_root=cache)
    mats = draft["materials"]["audio_effects"]
    assert [m["id"] for m in mats] == [mid]
    m = mats[0]
    assert m["name"] == "Voice Crisper" and m["resource_id"] == "7491147795483659521"
    assert Path(m["path"]) == cache / "7491147795483659521" / "afa899afa9b93e99cce244324bffe563"
    assert "{{" not in json.dumps(m)
    assert mid != effects.make("voice_crisper", draft, cache_root=cache)


def test_make_raises_when_cache_missing(draft, tmp_path):
    empty = tmp_path / "effect"
    empty.mkdir()
    with pytest.raises(effects.EffectCacheMissing) as e:
        effects.make("voice_crisper", draft, cache_root=empty)
    assert e.value.resource_id == "7491147795483659521" and e.value.name == "voice_crisper"
    assert "примените его в CapCut один раз вручную" in str(e.value)
    assert "audio_effects" not in draft["materials"]


def test_mask_circle_type_is_mask_and_category_video(draft, cache):
    mid = effects.make("mask_circle", draft, cache_root=cache, **{"config.centerX": 0.5})
    m = draft["materials"]["common_mask"][0]
    assert m["id"] == mid and m["type"] == "mask" and m["category"] == "video"
    # cache dir name differs from resource_id; hash dir falls back to the one existing subdir
    assert Path(m["path"]) == cache / "1068046525" / "otherhash"
    assert m["config"]["centerX"] == 0.5


def test_adjust_circle_values_and_make_all(draft, cache):
    ids = effects.make_all("adjust_circle", draft, cache_root=cache)
    ix = {m["id"]: m for k in ("effects", "hsl") for m in draft["materials"].get(k, [])}
    got = {ix[i]["type"]: ix[i].get("value") for i in ids}
    assert got["temperature"] == pytest.approx(-0.36) and got["saturation"] == pytest.approx(0.2) and "hsl" in got


def test_reduce_noise_resolves_app_dir(draft, cache):
    effects.make("reduce_noise", draft, cache_root=cache)
    p = draft["materials"]["realtime_denoises"][0]["path"]
    assert "9.9.0" in p and p.endswith("unet_denoise_44k_music_model_v1.0.model")


def test_attach_is_idempotent(draft):
    seg = draft["tracks"][0]["segments"][0]
    n = len(seg["extra_material_refs"])
    effects.attach(seg, "X")
    effects.attach(seg, "X")
    assert seg["extra_material_refs"][n:] == ["X"]


def test_zoom_keyframes_inside_segment(draft):
    seg = draft["tracks"][0]["segments"][0]  # 5 s
    effects.zoom_keyframes(seg, 1.0, 3.0, 3.5, 1.2, cx=0.1, cy=-0.1)
    kf = {c["property_type"]: c["keyframe_list"] for c in seg["common_keyframes"]}
    assert set(kf) == {"KFTypeScaleX", "KFTypeScaleY", "KFTypePositionX", "KFTypePositionY"}
    sx = [(k["time_offset"], k["values"][0]) for k in kf["KFTypeScaleX"]]
    assert sx == [(1_000_000, 1.0), (1_500_000, 1.2), (3_000_000, 1.2), (3_500_000, 1.0)]
    assert [k["values"][0] for k in kf["KFTypePositionX"]] == [0.0, 0.1, 0.1, 0.0]
    dur = seg["target_timerange"]["duration"]
    assert all(0 <= k["time_offset"] <= dur for lst in kf.values() for k in lst)
    assert len({k["id"] for lst in kf.values() for k in lst}) == 16


def test_zoom_keyframes_without_center_has_no_position(draft):
    seg = draft["tracks"][0]["segments"][0]
    effects.zoom_keyframes(seg, 0.0, 2.0, 2.5, 1.1)
    assert {c["property_type"] for c in seg["common_keyframes"]} == {"KFTypeScaleX", "KFTypeScaleY"}


def test_zoom_keyframes_raises_when_out_beyond_segment(draft):
    seg = draft["tracks"][0]["segments"][0]
    with pytest.raises(ValueError):
        effects.zoom_keyframes(seg, 1.0, 4.8, 5.3, 1.2)
    assert not seg.get("common_keyframes")


def test_sfx_and_music_segment(draft):
    track = {"type": "audio", "segments": []}
    sid = effects.sfx_segment(draft, track, "D:/sfx/click.wav", 1_000_000, 200_000, 0.5)
    mid = effects.music_segment(draft, track, "D:/m/beat.mp3", 0, 3_000_000, 0.2)
    from common import check_refs, index
    draft["tracks"].append(track)
    assert not check_refs(draft)
    ix = index(draft["materials"])
    s1, s2 = track["segments"]
    assert s1["id"] == sid and s2["id"] == mid
    assert s1["target_timerange"] == {"start": 1_000_000, "duration": 200_000} and s1["volume"] == 0.5
    assert ix[s1["material_id"]][1]["path"] == "D:/sfx/click.wav"
    assert ix[s2["material_id"]][1]["name"] == "beat.mp3"
    assert "audio_fades" in {ix[e][0] for e in s2["extra_material_refs"]}
