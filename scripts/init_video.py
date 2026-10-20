"""Create the work folder of a video: subdirs, config.json, PROGRESS.md.

python -X utf8 init_video.py --sources E:/video --project "<name or path>" [--work DIR] [--sfx DIR] [--music DIR]
No --config flag: this script creates config.json (in the work dir).
"""
import argparse
import json
from pathlib import Path

from common import PROJECTS_ROOT, detect_timeline_id

SUBDIRS = ["transcript"] + [f"stage{i}" for i in range(1, 11)] + ["layout", "graphics", "stage12_shorts", "backups"]
STAGES = ["0", "1", "2", "3", "LAYOUT", "4", "5", "6", "7", "8", "9", "10", "shorts"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--work")
    ap.add_argument("--sfx")
    ap.add_argument("--music")
    a = ap.parse_args(argv)
    src = Path(a.sources).resolve()
    proj = Path(a.project)
    if not proj.is_absolute():
        proj = PROJECTS_ROOT / a.project
    work = Path(a.work).resolve() if a.work else src / "edit"
    for s in SUBDIRS:
        (work / s).mkdir(parents=True, exist_ok=True)
    tid = detect_timeline_id(proj) if (proj / "Timelines").is_dir() else None
    voice = src / "voice"
    cfg = {
        "project_dir": str(proj),
        "timeline_id": tid,
        "sources": {"camera": str(src / "camera"), "screencasts": str(src / "screencasts"),
                    "voice": str(voice) if voice.is_dir() else None},
        "fps": 30, "width": 1920, "height": 1080,
        "compounds": {"mic": None, "cam_full": [], "screencast": None, "circle": None},
        "sfx_dir": a.sfx, "music_dir": a.music,
        "description_md": str(work / "description.md"),
        "master_render": None,
        "work_dir": str(work),
        "tiktok_channel": None,
    }
    cp = work / "config.json"
    cp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    pg = work / "PROGRESS.md"
    if not pg.exists():
        rows = "\n".join(f"| {s} | — | |" for s in STAGES)
        pg.write_text(f"# Прогресс монтажа\n\nПроект CapCut: `{proj}`\nИсходники: `{src}`\n\n"
                      f"| Этап | Статус | Заметки |\n|---|---|---|\n{rows}\n", encoding="utf-8")
    print(cp)


if __name__ == "__main__":
    main()
