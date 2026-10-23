"""Skill-wide hygiene: no first-video hardcodes, SKILL.md size/frontmatter/links, apply scripts' CLI."""
import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# Strings split so this file does not match itself.
FORBIDDEN = ["Гайд" + " конкуренты", "E87" + "DC4D2", "IMG" + "_E02", "AiVideo" + "Editing",
             "4-гайд-на-" + "анализ-конкурентов", "write" + "lo", "stage11" + "_intro", "illustrations" + "/"]
FORBIDDEN_RE = re.compile("Compound" + r" clip\d")
TEXT = {".py", ".md", ".json", ".js", ".css", ".html", ".txt", ".cube", ".yml", ".yaml", ".toml", ".cfg", ".ini"}
SKIP_DIRS = {".git", ".superpowers", "__pycache__", ".pytest_cache"}

# Scripts with a CLI that write into the CapCut project of config.json (call write_draft).
# Every one must have --dry and --config (default ./config.json).
# Exempt by design (checked below so the list stays honest):
#   init_video.py          creates config.json, there is none yet
#   capcut_new_project.py  creates a NEW project folder (EXPERIMENTAL), not an edit of config's project
NO_CONFIG = {"init_video.py", "capcut_new_project.py", "beats.py"}   # beats.py: library + debug print, no argparse


def _skill_files():
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if not p.is_file() or SKIP_DIRS & set(rel.parts):
            continue
        if rel.parts[:2] == ("assets", "examples"):
            continue
        if p.suffix.lower() in TEXT:
            yield p, rel


def test_no_first_video_hardcodes():
    bad = []
    for p, rel in _skill_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        if p.name == Path(__file__).name:
            text = text.replace(text[text.index("FORBIDDEN = ["):text.index("FORBIDDEN_RE")], "")
        bad += [f"{rel}: {f}" for f in FORBIDDEN if f in text]
        if FORBIDDEN_RE.search(text):
            bad.append(f"{rel}: Compound clipN")
    assert not bad, bad


def test_skill_md_under_500_lines_with_frontmatter():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 500
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "frontmatter"
    fm = m.group(1)
    assert re.search(r"^name: video-edit$", fm, re.M)
    desc = re.search(r"^description: (.+)$", fm, re.M).group(1).lower()
    for trig in ("монтаж ролика", "capcut", "шортс", "рилс", "тикток"):
        assert trig in desc, trig


def test_every_reference_linked_from_skill_md():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    missing = [p.relative_to(ROOT).as_posix() for p in (ROOT / "references").rglob("*.md")
               if p.relative_to(ROOT).as_posix() not in text]
    assert not missing, missing


def test_every_script_in_skill_md_exists_and_vice_versa():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    named = set()
    for m in re.finditer(r"`(scripts/[^`]+?)`", text):
        s = m.group(1).split()[0]
        b = re.match(r"(.*)\{(.+)\}(\.py)$", s)
        named |= {f"{b.group(1)}{n}{b.group(3)}" for n in b.group(2).split(",")} if b else {s}
    named = {n for n in named if n.endswith(".py")}
    real = {p.relative_to(ROOT).as_posix() for p in SCRIPTS.rglob("*.py") if "__pycache__" not in p.parts}
    assert not named - real, sorted(named - real)
    assert not real - named, sorted(real - named)


def _cli_scripts():
    for p in sorted(SCRIPTS.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        if "__main__" in src:
            yield p, src


def _writes_project(src):
    return re.search(r"\bwrite_draft\(", src) is not None


def _config_default(src):
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument" \
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "--config":
            for kw in node.keywords:
                if kw.arg == "default":
                    return kw.value.value if isinstance(kw.value, ast.Constant) else "<expr>"
            return None
    return "<absent>"


APPLY = [p for p, src in _cli_scripts() if _writes_project(src)]


def test_apply_scripts_classified():
    names = {p.name for p in APPLY}
    for must in ("assemble.py", "apply_graphics.py", "apply_music.py", "apply_zooms.py", "ripple_cut.py"):
        assert must in names
    for p, src in _cli_scripts():
        if p.name in NO_CONFIG:
            assert not _writes_project(src), p.name
        else:
            assert _config_default(src) in ("config.json", None), (p.name, _config_default(src))


@pytest.mark.parametrize("script", APPLY, ids=lambda p: p.relative_to(SCRIPTS).as_posix())
def test_every_script_has_dry_and_config(script):
    assert _config_default(script.read_text(encoding="utf-8")) in ("config.json", None)
    r = subprocess.run([sys.executable, "-X", "utf8", str(script), "--help"], capture_output=True, text=True,
                       encoding="utf-8", cwd=str(script.parent), timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "--dry" in r.stdout and "--config" in r.stdout, r.stdout


def test_local_overlap_checks_use_common():
    """add_camera / apply_cuts / stage2 apply / make_compound validate overlaps through common.overlap_errors."""
    sys.path.insert(0, str(SCRIPTS)); sys.path.insert(1, str(SCRIPTS / "stage2"))
    import common
    import make_compound

    def sg(a, b):
        return {"id": f"s{a}", "material_id": "m", "target_timerange": {"start": a, "duration": b - a}}
    tr = {"type": "video", "segments": [sg(0, 10), sg(5, 20)]}
    assert common.overlap_errors(tr, "track 0") == ["overlap on track 0 at 0.000"]
    assert common.overlap_errors({"type": "video", "segments": [sg(0, 10), sg(9, 20)]}, "x") == []   # 1 us rounding
    c = make_compound.Compound(nid="n", cid="c", name="cmp", kind="main",
                               nested={"duration": 20, "tracks": [tr]}, outer={})
    errs = make_compound.errors({"materials": {}, "tracks": []}, [c])
    assert any("overlap on cmp (inside)" in e for e in errs), errs
    for f in ("layout/add_camera.py", "stage1/apply_cuts.py", "stage2/apply.py", "stage2/make_compound.py"):
        src = (SCRIPTS / f).read_text(encoding="utf-8")
        assert "overlap_errors" in src or "draft_overlaps" in src, f
        assert 'q["target_timerange"]["start"] + 1' not in src, f
