"""Stage 5, steps 3b–4: findings + censor_proposal.md (then **Стоп** until approved).

    python -X utf8 scripts/stage5/build_findings.py --config config.json [--dry]

Inputs (<work_dir>/stage5/): pattern_hits.json (scan_patterns.py); manual_findings.json (optional — the visual
check of step 3: [{file, src_start, src_end, bbox: [x, y, w, h] | boxes: [{t, bbox}], what, decision, apply}],
source seconds and source px); segment_starts.json (extract_frames.py: the frames to look at).
OCR hits: e-mail, keys/tokens, passwords, address-bar tokens, card numbers (Luhn) -> hide (apply true);
phones and long hex/base64 strings -> «под вопросом» (apply false: often public content — competitors' contacts,
ids in public links; STAGE_5: public accounts are content). Consecutive seconds (gap <= 2 s) of the same match in a
file make one finding with a bbox per second (moving text).
Output: censor_findings.json [{file, src_start, src_end, bbox, boxes|null, apply, what, decision, type, timeline}]
(timeline = [[a, b]] timeline seconds now) and censor_proposal.md. Edit apply / decision in the json to approve.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

HIDE = {"email": "e-mail", "key": "ключ/токен", "password": "поле пароля", "urltoken": "токен в адресной строке",
        "card": "номер карты"}
REVIEW = {"phone": "телефон — публичный контакт или личный?", "hexb64": "длинная строка (id/токен?) — посмотреть кадр"}
RUN_GAP = 2


def to_timeline(pieces: list[dict], name: str, a: float, b: float) -> list[list[float]]:
    """Source seconds [a, b] of file `name` -> timeline ranges [[t0, t1]] where the timeline shows it."""
    out = []
    for p in pieces:
        if common.uncensored_name(p["path"]).lower() != name.lower() or p["src"] is None:
            continue
        si, so = p["src"] / 1e6, p["src_end"] / 1e6
        lo, hi = max(a, si), min(b, so)
        if hi > lo:
            t0 = p["start"] / 1e6 + (lo - si) / p["speed"]
            out.append([round(t0, 2), round(t0 + (hi - lo) / p["speed"], 2)])
    return sorted(out)


def group_hits(hits: list[dict], names: dict[str, str]) -> list[dict]:
    """OCR hits -> findings (one per run of seconds of the same match in a file)."""
    groups = collections.defaultdict(list)
    for h in hits:
        if h["type"] not in HIDE and h["type"] not in REVIEW:
            continue
        key = re.sub(r"\D", "", h["match"]) if h["type"] in ("phone", "card") else re.sub(r"\W", "", h["match"].lower())[:28]
        groups[(h["type"], key, h["file"])].append(h)
    findings = []
    for (t, _k, stem), hs in sorted(groups.items()):
        secs = sorted({h["sec"] for h in hs})
        runs, cur = [], [secs[0]]
        for s in secs[1:]:
            if s - cur[-1] <= RUN_GAP:
                cur.append(s)
            else:
                runs.append(cur)
                cur = [s]
        runs.append(cur)
        for run in runs:
            boxes = [{"t": float(s), "bbox": next(h["bbox"] for h in hs if h["sec"] == s)} for s in run]
            hide = t in HIDE
            findings.append({"file": names.get(stem, stem + ".mp4"), "src_start": float(run[0]),
                             "src_end": float(run[-1]) + 1.0, "bbox": boxes[0]["bbox"],
                             "boxes": boxes if len(boxes) > 1 else None, "apply": hide, "type": t,
                             "what": f"OCR {t}: {hs[0]['match']}",
                             "decision": ("скрыть — " + HIDE[t]) if hide else ("под вопросом — " + REVIEW[t])})
    return findings


def mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def proposal(findings: list[dict], starts: list[dict]) -> str:
    L = ["# Этап 5 — предложение по цензуре (анализ, проект не тронут)", "",
         "Привязка — к исходнику (файл + секунды), bbox в px исходника; таймкоды таймлайна — на сейчас.",
         "Публичные аккаунты, конкуренты, ролики — это контент, не скрывать без решения пользователя.", "",
         "| № | Таймкод таймлайна | Файл и время исходника | Что найдено | bbox [x,y,w,h] | Решение |",
         "|---|---|---|---|---|---|"]
    for i, f in enumerate(findings, 1):
        tl = ", ".join(f"{mmss(a)}–{mmss(b)}" for a, b in f["timeline"][:3]) or "не используется в таймлайне"
        if len(f["timeline"]) > 3:
            tl += f" (+{len(f['timeline']) - 3})"
        bb = json.dumps(f["bbox"]) if not f.get("boxes") else f"движется: {len(f['boxes'])} bbox по 1 с"
        L.append(f"| {i} | {tl} | {f['file']} {f['src_start']:.2f}–{f['src_end']:.2f} | {f['what']} | {bb} | "
                 f"{f['decision']}{'' if f.get('apply') else ' (не применяется)'} |")
    L += ["", f"Скрыть: {sum(1 for f in findings if f.get('apply'))}, под вопросом / не скрывать: "
              f"{sum(1 for f in findings if not f.get('apply'))}.", "",
          "## Визуально (шаг 3): первые кадры кусков скринкаста",
          "Уведомления мессенджеров, личные вкладки, закладки, аватарки чужих людей в личных чатах → "
          "stage5/manual_findings.json, затем этот скрипт заново.", ""]
    L += [f"- {s['timeline']:.2f} с: {s['file']} @ {s['src']:.2f} → {s['frame']}" for s in starts]
    L += ["", "**Стоп до утверждения.** Утвердить: apply/decision в censor_findings.json, затем apply_censor.py."]
    return "\n".join(L)


def run(cfg, dry: bool = False) -> list[dict]:
    root = cfg.work_dir / "stage5"
    hp = root / "pattern_hits.json"
    hits = json.loads(hp.read_text(encoding="utf-8")) if hp.is_file() else []
    if not hp.is_file():
        print(f"note: no {hp} (scan_patterns.py not run) — manual findings only")
    d = common.read_draft(cfg)
    pieces = common.flatten(cfg, d, ("screencast",))
    names = {Path(common.uncensored_name(p["path"])).stem: common.uncensored_name(p["path"]) for p in pieces}
    findings = group_hits(hits, names)
    mp = root / "manual_findings.json"
    manual = json.loads(mp.read_text(encoding="utf-8")) if mp.is_file() else []
    for m in manual:
        m.setdefault("apply", True)
        m.setdefault("type", "manual")
        m.setdefault("boxes", None)
    findings = manual + findings
    for f in findings:
        f["timeline"] = to_timeline(pieces, f["file"], f["src_start"], f["src_end"])
    sp = root / "segment_starts.json"
    starts = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else []
    md = proposal(findings, starts)
    print(f"findings: {len(findings)} (apply {sum(1 for f in findings if f.get('apply'))}); OCR hits {len(hits)}, "
          f"manual {len(manual)}")
    if not findings:
        print("nothing found: no censorship needed (still look at the segment start frames)")
    if not dry:
        root.mkdir(parents=True, exist_ok=True)
        (root / "censor_findings.json").write_text(json.dumps(findings, ensure_ascii=False, indent=1), encoding="utf-8")
        (root / "censor_proposal.md").write_text(md, encoding="utf-8")
        print("written:", root / "censor_proposal.md")
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 5: censor findings + proposal")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.dry)


if __name__ == "__main__":
    main()
