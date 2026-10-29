"""Full-screen scheme card (scripts/shorts/scheme.py + build.py cards type: scheme): spec -> HTML, time mapping,
validation, SFX events, Playwright smoke render."""
import json
import re
from pathlib import Path

import pytest

import build
import build_render
import scheme
from test_shorts import shorts_work

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "assets" / "examples" / "specs" / "scheme_example.json"


def example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_html_words_in_order_number_accent():
    """Every word of the spec is in the HTML with data-in, in spoken order (composition seconds from the card start);
    the number is a .num span in the accent colour; the panel is an opaque full-frame block with cut in/out."""
    card = scheme.normalize(build.scheme.pick_card(example()))
    assert scheme.validate(card) == []
    h = scheme.html_fragment(card)
    spans = re.findall(r'<span class="(w|num) word" data-in="([\d.]+)"[^>]*>([^<]+)</span>', h)
    ws = sorted(scheme.words(card), key=lambda x: x[1])            # spoken order = time order
    assert [s[2] for s in spans] == [w for w, _, _ in ws]
    assert [float(s[1]) for s in spans] == pytest.approx([t - card["start"] for _, t, _ in ws], abs=1e-3)
    assert [s[2] for s in spans if s[0] == "num"] == ["1 000 000", "50 000"]
    assert "color:#F8DE03" in h and "radial-gradient" in h and "#60260A" in h and "108px 108px" in h
    assert re.search(r'class="scheme s\w+" data-in="0.000" data-out="10.000" data-fx="cut" data-ofx="cut"', h)
    assert h.count('class="pop"') == 3 and h.count('<path class="dash"') == 2
    assert [k for k, _ in scheme.events(card)] == ["node", "node", "pan", "node", "pan"]


def test_normalize_defaults_and_errors(tmp_path):
    c = scheme.normalize({"id": "x", "tl_in": 10, "tl_out": 14, "nodes": [
        {"icon": "avatar", "phrases": [{"words": [["а", 10.2]]}, {"words": [["б", 11.0]]}]},
        {"icon": "funpay", "at": 12.5, "phrases": [{"number": ["5", 12.8]}]}]})
    assert c["start"] == 10 and c["end"] == 14 and c["style"]["accent"] == "#F8DE03"
    assert c["nodes"][0]["at"] == 10 and c["nodes"][0]["phrases"][0]["out"] == 11.0      # cut to the next phrase
    assert c["nodes"][1]["shape"] == "plate" and c["nodes"][1]["pan_at"] == pytest.approx(12.05)
    assert c["nodes"][1]["offset"] == [830, 900]
    bad = scheme.validate(scheme.normalize({"id": "y", "start": 10, "end": 12, "nodes": [{"phrases": [{"words": [["поздно", 13.0]]}]}]}))
    assert bad and "поздно" in bad[0]
    with pytest.raises(ValueError, match="shape"):
        scheme.normalize({"start": 0, "end": 1, "nodes": [{"shape": "hex"}]})
    with pytest.raises(ValueError, match="иконка"):
        scheme.html_fragment(scheme.normalize({"start": 0, "end": 1, "nodes": [{"icon": "logo.png"}]}), icon_base=tmp_path)
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    assert 'logo.png" alt=""' in scheme.html_fragment(scheme.normalize({"start": 0, "end": 1, "nodes": [{"icon": "logo.png"}]}), icon_base=tmp_path)


def test_plan_maps_words_suppresses_captions_and_sfx(tmp_path):
    """Scheme in a shorts spec: word times go through the piece mapping (cut pauses), captions inside the scheme are
    dropped, SFX events (node / pan) in short time; a word in a cut pause or under the hook -> SystemExit naming it."""
    ctx = build.load(shorts_work(tmp_path))
    ws = [w for w in ctx.words if 20.0 <= w["start"] <= 40.0]
    # the fixture: a 0.6-s pause after every 8th word -> the planner cuts it
    gaps = [(a["end"], b["start"]) for a, b in zip(ws, ws[1:]) if b["start"] - a["end"] > 0.3]
    assert gaps
    t0 = ws[2]["start"]; t1 = ws[-2]["end"]
    card = {"type": "scheme", "id": "s1", "start": t0, "end": t1, "nodes": [
        {"icon": "avatar", "at": t0, "phrases": [{"words": [[ws[2]["word"], ws[2]["start"]], [ws[3]["word"], ws[3]["start"]]]}]},
        {"icon": "ayugram", "at": ws[10]["start"], "pan_at": ws[9]["start"], "phrases": [{"number": ["7", ws[11]["start"]]}]}]}
    spec = {"id": "t", "slug": "t", "ranges": [{"tl": [10.0, 50.0]}], "hook": {"lines": ["x"]}, "cards": [card]}
    pl = build.plan(ctx, spec)
    s = pl["schemes"][0]
    assert s["s_in"] == pytest.approx(build.tl2s(ctx, pl, t0), abs=1e-3) and s["s_out"] > s["s_in"] + 5
    assert not any(s["s_in"] <= c["t_in"] < s["s_out"] for c in pl["captions"])
    assert all(c["t_out"] <= s["s_in"] + 1e-6 or c["t_in"] >= s["s_out"] for c in pl["captions"])
    kinds = [e["kind"] for e in s["sfx"]]
    assert kinds == ["node", "node", "pan"] and s["sfx"][2]["t"] < s["sfx"][1]["t"]
    # word times land on the spoken word after the cut pause (same map as the plan words)
    w11 = next(w for w in pl["words"] if w["word"] == ws[11]["word"])
    assert s["sfx"][1]["t"] == pytest.approx(build.tl2s(ctx, pl, ws[10]["start"]), abs=1e-3)
    assert build.tl2s(ctx, pl, ws[11]["start"]) == pytest.approx(w11["start"], abs=1e-3)
    assert build_render.scheme_hits(pl, "pan") == [s["sfx"][2]["t"]]
    html = build.html_cards(ctx, spec, pl)
    assert 'class="scheme' in html and f'data-in="{s["s_in"]:.3f}"' in html
    # a word in the cut pause
    bad = json.loads(json.dumps(card)); bad["nodes"][0]["phrases"][0]["words"].append(["пауза", round(gaps[0][0] + 0.3, 3)])
    with pytest.raises(SystemExit, match="пауза"):
        build.plan(ctx, dict(spec, cards=[bad]))
    # under the hook
    early = dict(card, start=ws[0]["start"]); early["nodes"] = [dict(card["nodes"][0], at=ws[0]["start"])]
    with pytest.raises(SystemExit, match="хук"):
        build.plan(ctx, dict(spec, ranges=[{"tl": [t0 - 0.5, 50.0]}], cards=[early]))


def test_tick_file(tmp_path, capsys):
    ctx = build.load(shorts_work(tmp_path))
    ctx.cfg.sfx_dir = None
    assert build_render.tick_file(ctx, {}) is None and "без тика" in capsys.readouterr().out
    d = tmp_path / "sfx"; d.mkdir(); (d / "вуш.wav").write_bytes(b"")
    ctx.cfg.sfx_dir = str(d)
    assert build_render.tick_file(ctx, {}) is None
    (d / "ui click 2.wav").write_bytes(b"")
    assert build_render.tick_file(ctx, {}).name == "ui click 2.wav"
    with pytest.raises(SystemExit, match="тик"):
        build_render.tick_file(ctx, {"tick": "нет.wav"})


def test_render_smoke(tmp_path):
    """Playwright: the panel is opaque over the whole frame at three moments (node, pan, number)."""
    pytest.importorskip("playwright")
    import numpy as np
    from PIL import Image
    from playwright.sync_api import sync_playwright
    card = scheme.normalize(build.scheme.pick_card(example()))
    page = tmp_path / "s.html"; page.write_text(scheme.standalone_html(card), encoding="utf-8")
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(); pg = b.new_page(viewport={"width": 1080, "height": 1920})
            pg.goto(page.as_uri()); pg.evaluate("document.fonts.ready")
            assert pg.evaluate("document.fonts.check('700 40px Unbounded')")
            for t in (0.4, 1.7, 4.3):
                pg.evaluate(f"seek({t})"); pg.screenshot(path=str(tmp_path / f"{t}.png"), omit_background=True)
            b.close()
    except Exception as e:          # no chromium installed
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e): pytest.skip(str(e)[:80])
        raise
    for t in (0.4, 1.7, 4.3):
        a = np.asarray(Image.open(tmp_path / f"{t}.png").convert("RGBA"))
        assert a.shape[:2] == (1920, 1080) and a[..., 3].min() == 255, t           # opaque everywhere
        assert a[..., :3].max() > 200                                               # something drawn (text / icon)
    before = np.asarray(Image.open(tmp_path / "0.4.png").convert("RGBA"))
    assert (before[..., :3].astype(int).sum(-1) > 600).sum() > 500                 # white text / icon pixels
