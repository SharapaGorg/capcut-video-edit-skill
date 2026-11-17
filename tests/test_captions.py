"""«Слова за головой»: the scripts find their assets inside the skill, nothing points at the old standalone skill."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAP = ROOT / "scripts" / "captions"
ASSETS = ROOT / "assets" / "captions"


def test_assets_present():
    for f in ("rvm.onnx", "music/Hyperfun.mp3", "NOTICE.md", "fonts/Inter.ttf", "fonts/Playfair-Italic.ttf",
              "fonts/Oswald.ttf", "fonts/JetBrainsMono.ttf"):
        assert (ASSETS / f).is_file(), f


def test_template_fonts_exist():
    html = (CAP / "template.html").read_text(encoding="utf-8")
    fonts = re.findall(r"/\*FONTS\*//([\w.-]+\.ttf)", html)
    assert fonts
    assert not [f for f in fonts if not (ASSETS / "fonts" / f).is_file()]


def test_scripts_parse_and_use_skill_assets():
    for p in CAP.glob("*.py"):
        ast.parse(p.read_text(encoding="utf-8"))
    assert 'HERE.parent.parent / "assets" / "captions"' in (CAP / "run.py").read_text(encoding="utf-8")
    assert 'HERE.parent.parent / "assets" / "captions" / "fonts"' in (CAP / "kit.py").read_text(encoding="utf-8")
    old = "reel-" + "captions"
    files = list(CAP.glob("*")) + list((ROOT / "references" / "captions").glob("*.md")) + [ROOT / "references" / "captions.md"]
    for p in files:
        if p.is_file() and p.suffix in {".py", ".md", ".html"}:
            assert old not in p.read_text(encoding="utf-8"), p.name


def test_example_layouts_use_only_kit_blocks():
    methods = set(re.findall(r"^    def (\w+)\(", (CAP / "kit.py").read_text(encoding="utf-8"), re.M))
    layouts = list((ROOT / "assets" / "examples" / "captions").glob("layout_*.py"))
    assert layouts
    for p in layouts:
        used = set(re.findall(r"\bL\.(\w+)\(", p.read_text(encoding="utf-8")))
        assert not used - methods, (p.name, sorted(used - methods))
