"""Voice loudness by source, as heard on the timeline: mic (cfg.sources.voice) vs screencast audio (rules.md «Звук»:
the two must match ±1 LU; +4.5 dB of the reference is for the mic mp3 only).

    python -X utf8 scripts/stage9/measure_lufs.py --config config.json

Each source: its leaf pieces on the timeline x their volume (compound chain included), sped pieces muted
(effects.voice_pcm) -> integrated LUFS. Prints the gain the mic needs to match the screencast; writes
<work_dir>/stage9/work/lufs.json. Exit 1 when both exist and differ by more than 1 LU. Read-only for the project.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402
import effects  # noqa: E402

TOL = 1.0


def run(cfg, log=print) -> dict:
    d = common.read_draft(cfg)
    res = {}
    for role in ("voice", "screencast"):
        x, got = effects.voice_pcm(cfg, d, 0, d["duration"], roles=(role,))
        lu = effects.loudness(x)["I"] if got else None
        res[role] = {"integrated_lufs": lu if lu is not None and lu > -69.9 else None,
                     "pieces": sum(1 for p in common.flatten(cfg, d, (role,)) if p["volume"] > 0)}
        log(f"{'mic' if role == 'voice' else 'screencast'}: {res[role]['integrated_lufs']} LUFS "
            f"({res[role]['pieces']} pieces with volume > 0)")
    a, b = res["voice"]["integrated_lufs"], res["screencast"]["integrated_lufs"]
    res["mic_gain_db_to_match"] = round(b - a, 2) if a is not None and b is not None else None
    res["ok"] = res["mic_gain_db_to_match"] is None or abs(res["mic_gain_db_to_match"]) <= TOL
    if res["mic_gain_db_to_match"] is not None:
        log(f"mic {res['mic_gain_db_to_match']:+.1f} dB to match the screencast -> "
            + ("OK (±1 LU)" if res["ok"] else "FAIL: change the mic compound volume"))
    p = cfg.work_dir / "stage9" / "work" / "lufs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 9: voice LUFS, mic vs screencast (read-only)")
    ap.add_argument("--config", default="config.json")
    a = ap.parse_args(argv)
    if not run(common.load_config(a.config))["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
