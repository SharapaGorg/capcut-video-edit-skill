"""Voice loudness by source, as heard on the timeline: mic (cfg.sources.voice) vs screencast audio (rules.md «Звук»:
the two must match ±1 LU; +4.5 dB of the reference is for the mic mp3 only, a fallback when nothing can be measured).

    python -X utf8 scripts/stage9/measure_lufs.py --config config.json [--set-mic [--dry]]

Each source: its leaf pieces on the timeline x their volume (compound chain included), sped pieces muted
(effects.role_lufs) -> integrated LUFS. Prints the gain the mic needs to match the screencast; writes
<work_dir>/stage9/work/lufs.json. Exit 1 when both exist and differ by more than 1 LU.
Read-only for the project, except --set-mic: the volume of every piece of the mic compound (cfg.compounds.mic) is
set so the two match (effects.match_mic), written through common.write_draft (CapCut killed, backup, both drafts),
the mic compound's audio pre-render (if any) deleted; then measured again.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stage2"))
import common  # noqa: E402
import effects  # noqa: E402
import make_compound as mc  # noqa: E402

TOL = effects.MIC_TOL_LU


def run(cfg, log=print, draft: dict | None = None) -> dict:
    d = draft or common.read_draft(cfg)
    res = {}
    for role in ("voice", "screencast"):
        res[role] = {"integrated_lufs": effects.role_lufs(cfg, d, role),
                     "pieces": sum(1 for p in common.flatten(cfg, d, (role,)) if p["volume"] > 0)}
        log(f"{'mic' if role == 'voice' else 'screencast'}: {res[role]['integrated_lufs']} LUFS "
            f"({res[role]['pieces']} pieces with volume > 0)")
    a, b = res["voice"]["integrated_lufs"], res["screencast"]["integrated_lufs"]
    res["mic_gain_db_to_match"] = round(b - a, 2) if a is not None and b is not None else None
    res["ok"] = res["mic_gain_db_to_match"] is None or abs(res["mic_gain_db_to_match"]) <= TOL
    if res["mic_gain_db_to_match"] is not None:
        log(f"mic {res['mic_gain_db_to_match']:+.1f} dB to match the screencast -> "
            + ("OK (±1 LU)" if res["ok"] else "FAIL: run with --set-mic"))
    p = cfg.work_dir / "stage9" / "work" / "lufs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


def set_mic(cfg, dry: bool, guard_seconds: float = 5, log=print) -> dict:
    """Mic compound volume so mic = screencast (±1 LU); written via common.write_draft. -> match_mic result."""
    nid = (cfg.compounds or {}).get("mic")
    if not nid:
        raise SystemExit("cfg.compounds.mic is empty: no mic compound (no voice/ or stage 2 §7 not run)")
    d = common.read_draft(cfg)
    ps = mc.pieces(d, nid)
    if not ps:
        raise SystemExit(f"mic compound {nid} not found on the timeline (cfg.compounds stale?)")
    g = effects.match_mic(cfg, d, [p[2] for p in ps], log=log)
    if dry:
        log("dry run, not written")
        return g
    stale = [r for p in ps if (r := mc.stale_prerender(cfg, p[3]))]
    common.write_draft(cfg, d, "stage9-mic-gain", dry=False, guard_seconds=guard_seconds)
    for sub, ap in dict.fromkeys(stale):
        mc.clear_prerender(cfg, sub, ap)
        log(f"cleared audio pre-render {ap}")
    log("written")
    return g


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 9: voice LUFS, mic vs screencast (--set-mic: fix the mic volume)")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--set-mic", action="store_true", help="set the mic compound volume to match the screencast")
    ap.add_argument("--dry", action="store_true", help="with --set-mic: show the gain, write nothing")
    a = ap.parse_args(argv)
    cfg = common.load_config(a.config)
    if a.set_mic:
        set_mic(cfg, a.dry)
        if a.dry:
            return
    if not run(cfg)["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
