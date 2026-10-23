"""Stage 10: subtitles.srt + chapters.txt from the stage 3 maps; the timecode block of the user's description.

    python -X utf8 scripts/stage10/build_srt.py --config config.json [--dry]

srt (from stage3/transcript_timeline.json, timeline time = time in the export): line <= 42 chars, <= 2 lines, block
1–7 s, words never broken; blocks split at pauses >= 0.7 s and at sentence / comma ends; hook (hook / duplicate
words) and body never share a block. Whisper tokens like «что -то», «2 ,5» are glued. Optional recognition fixes:
<work_dir>/stage10/srt_fixes.json {"words": {"ядро": "замена"}, "phrases": [[["чат", "gpt"], "ChatGPT"]]}
(lower-case word cores, punctuation kept). Spelling is checked by eye — the script cannot.
chapters.txt (stage3/chapters_timeline.json): `мм:сс Название` (ч:мм:сс from 1 h); first 00:00, >= 3, each >= 10 s.
Description: cfg.description_md exists -> ONLY its timecode block (consecutive lines «мм:сс …») is replaced with
chapters.txt (backup in <work_dir>/backups); no block -> appended at the end, reported; no file -> reported, not
generated. Chapter problems -> the description is not touched. No thumbnail, no upload.
Writes <work_dir>/stage10/subtitles.srt, chapters.txt. Exit 1 on a failed check. Read-only for the project.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common  # noqa: E402

MAX_LINE = 42
MAX_DUR = 7.0
MIN_DUR = 1.0
GAP_BREAK = 0.7
PAD = 0.25
MIN_GAP = 0.04
TC_RE = re.compile(r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}\s+\S")


# ---------- words ----------
def load_words(cfg) -> tuple[list[dict], float | None]:
    p = cfg.work_dir / "stage3" / "transcript_timeline.json"
    if not p.is_file():
        raise SystemExit(f"нет {p}: сначала этап 3 (build_maps.py)")
    d = json.loads(p.read_text(encoding="utf-8"))
    words = [{"t": w["word"].strip(), "s": w["start"], "e": w["end"], "hook": bool(w.get("hook") or w.get("duplicate"))}
             for seg in d["segments"] for w in seg["words"] if w["word"].strip()]
    return sorted(words, key=lambda w: w["s"]), d.get("duration")


def merge_fragments(words: list[dict]) -> list[dict]:
    """Glue tokens like «-то», «.00», «,5» to the previous word."""
    out = []
    for w in words:
        if out and re.match(r"^[-.,]\S", w["t"]) and w["s"] - out[-1]["e"] < 0.6 and out[-1]["hook"] == w["hook"]:
            out[-1]["t"] += w["t"]
            out[-1]["e"] = w["e"]
        else:
            out.append(dict(w))
    return out


def core(t: str) -> str:
    return re.sub(r"^[^\w]+|[^\w]+$", "", t, flags=re.U).lower()


def apply_fixes(words: list[dict], fixes: dict) -> tuple[list[dict], list[tuple]]:
    gl = {k.lower(): v for k, v in (fixes.get("words") or {}).items()}
    phrases = [([x.lower() for x in seq], rep) for seq, rep in fixes.get("phrases") or []]
    log, out, i = [], [], 0
    while i < len(words):
        hit = next(((len(seq), rep) for seq, rep in phrases
                    if [core(x["t"]) for x in words[i:i + len(seq)]] == seq
                    and len({x["hook"] for x in words[i:i + len(seq)]}) == 1), None)
        if hit:
            n, rep = hit
            pre = re.match(r"^[^\w]*", words[i]["t"]).group(0)
            post = re.search(r"[^\w]*$", words[i + n - 1]["t"]).group(0)
            new = {**words[i], "t": pre + rep + post, "e": words[i + n - 1]["e"]}
            log.append((words[i]["s"], " ".join(x["t"] for x in words[i:i + n]), new["t"]))
            out.append(new)
            i += n
            continue
        w = dict(words[i])
        c = core(w["t"])
        if c in gl and gl[c] != c:
            rep = gl[c]
            if c and w["t"].lstrip("«\"(")[:1].isupper() and rep[:1].islower():
                rep = rep[0].upper() + rep[1:]
            new = re.sub(re.escape(re.sub(r"^[^\w]+|[^\w]+$", "", w["t"])), rep, w["t"], count=1)
            log.append((w["s"], w["t"], new))
            w["t"] = new
        out.append(w)
        i += 1
    return out, log


# ---------- blocks ----------
def wrap(text: str) -> list[str] | None:
    """<= 2 lines of <= MAX_LINE, words not broken; None if it does not fit."""
    if len(text) <= MAX_LINE:
        return [text]
    ws = text.split(" ")
    best = None
    for k in range(1, len(ws)):
        a, b = " ".join(ws[:k]), " ".join(ws[k:])
        if len(a) <= MAX_LINE and len(b) <= MAX_LINE:
            score = abs(len(a) - len(b)) - (6 if a[-1] in ",.?!;:—" else 0)
            if best is None or score < best[0]:
                best = (score, [a, b])
    return best[1] if best else None


def fits(ws: list[dict]) -> bool:
    return wrap(" ".join(w["t"] for w in ws)) is not None


def build_blocks(words: list[dict]) -> list[list[dict]]:
    blocks, cur = [], []
    for i, w in enumerate(words):
        if cur and not fits(cur + [w]):
            j = None   # back off to the last punctuation, not to leave a 1–2 word tail
            for puncts in (".?!", ",;:—"):
                for k in range(len(cur) - 2, -1, -1):
                    if (cur[k]["t"][-1:] in puncts and fits(cur[k + 1:] + [w])
                            and cur[k]["e"] - cur[0]["s"] >= MIN_DUR + 0.2):
                        j = k
                        break
                if j is not None:
                    break
            blocks.append(cur[:j + 1] if j is not None else cur)
            cur = cur[j + 1:] if j is not None else []
        if cur and (w["e"] + PAD - cur[0]["s"] > MAX_DUR or cur[-1]["hook"] != w["hook"]):
            blocks.append(cur)
            cur = []
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            break
        text = " ".join(x["t"] for x in cur)
        dur = w["e"] - cur[0]["s"]
        if ((nxt["s"] - w["e"] >= GAP_BREAK and dur >= 0.6) or (w["t"][-1:] in ".?!" and (len(text) >= 36 or dur >= 2.5))
                or (w["t"][-1:] in ",;:—" and len(text) >= 60) or nxt["hook"] != w["hook"]):
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def time_blocks(blocks: list[list[dict]]) -> list[tuple[float, float, list[dict]]]:
    res = []
    for i, b in enumerate(blocks):
        s = b[0]["s"]
        nxt = blocks[i + 1][0]["s"] - MIN_GAP if i + 1 < len(blocks) else float("inf")
        e = min(b[-1]["e"] + PAD, nxt)
        if e - s < MIN_DUR:
            e = min(s + MIN_DUR, nxt)
        res.append((s, min(e, s + MAX_DUR), b))
    merged, i = [], 0
    while i < len(res):   # a block still < 1 s -> into a neighbour (same hook flag, fits, <= 7 s)
        s, e, b = res[i]
        if (e - s < MIN_DUR and merged and merged[-1][2][-1]["hook"] == b[0]["hook"] and fits(merged[-1][2] + b)
                and e - merged[-1][0] <= MAX_DUR):
            ps, _, pb = merged.pop()
            merged.append((ps, e, pb + b))
        elif (e - s < MIN_DUR and i + 1 < len(res) and res[i + 1][2][0]["hook"] == b[-1]["hook"]
              and fits(b + res[i + 1][2]) and res[i + 1][1] - s <= MAX_DUR):
            merged.append((s, res[i + 1][1], b + res[i + 1][2]))
            i += 1
        else:
            merged.append((s, e, b))
        i += 1
    return merged


def fmt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(blocks) -> tuple[str, list[str]]:
    out, bad = [], []
    for n, (s, e, b) in enumerate(blocks, 1):
        text = " ".join(w["t"] for w in b)
        lines = wrap(text)
        if lines is None:
            bad.append(f"блок {n}: не влезает в 2 строки по {MAX_LINE}: {text}")
        if not MIN_DUR - 1e-6 <= e - s <= MAX_DUR + 1e-6:
            bad.append(f"блок {n}: длительность {e - s:.2f} с: {text}")
        if n > 1 and s < blocks[n - 2][1] - 1e-6:
            bad.append(f"блок {n}: перекрытие с предыдущим")
        out.append(f"{n}\n{fmt(s)} --> {fmt(e)}\n" + "\n".join(lines or [text]) + "\n")
    return "\n".join(out), bad


# ---------- chapters / description ----------
def tc(t: float) -> str:
    t = int(t)
    h, r = divmod(t, 3600)
    return f"{h}:{r // 60:02d}:{r % 60:02d}" if h else f"{r // 60:02d}:{r % 60:02d}"


def chapters(cfg, dur: float | None) -> tuple[list[str], list[str]]:
    p = cfg.work_dir / "stage3" / "chapters_timeline.json"
    if not p.is_file():
        return [], [f"нет {p.name} (этап 3) — главы не построены"]
    raw = json.loads(p.read_text(encoding="utf-8"))
    ch = sorted((c for c in (raw.get("chapters", []) if isinstance(raw, dict) else raw) if c.get("start") is not None),
                key=lambda c: c["start"])
    probs = []
    if len(ch) < 3:
        probs.append(f"глав {len(ch)}, нужно минимум 3")
    if ch and ch[0]["start"] > 0.5:
        probs.append(f"первая глава не с 00:00 ({ch[0]['start']:.1f} с)")
    for i, c in enumerate(ch):
        end = ch[i + 1]["start"] if i + 1 < len(ch) else c.get("end", dur)
        if end is not None and end - c["start"] < 10:
            probs.append(f"глава {c.get('n', i + 1)} «{c['title']}» короче 10 с ({end - c['start']:.1f} с)")
    lines = [f"{tc(0 if i == 0 else c['start'])} {c['title']}" for i, c in enumerate(ch)]
    return lines, probs


def update_description(cfg, lines: list[str], dry: bool) -> tuple[str, str]:
    """-> (status, message); status: missing | replaced | appended | unchanged."""
    p = Path(cfg.description_md) if cfg.description_md else None
    if p is None or not p.is_file():
        return "missing", "description.md не найден, не генерирую"
    raw = p.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    rows = raw.split(nl)
    runs, i = [], 0
    while i < len(rows):
        if TC_RE.match(rows[i]):
            j = i
            while j < len(rows) and TC_RE.match(rows[j]):
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    run = next(((a, b) for a, b in runs if b - a >= 2 or rows[a].strip().startswith("00:00")), None)
    if run:
        new = nl.join(rows[:run[0]] + lines + rows[run[1]:])
        status, msg = "replaced", f"description.md: блок таймкодов (строки {run[0] + 1}–{run[1]}) заменён на chapters.txt"
    else:
        new = raw.rstrip("\r\n") + nl + nl + "Таймкоды:" + nl + nl.join(lines) + nl
        status, msg = "appended", "description.md: блока таймкодов не было — добавлен в конец, проверьте место"
    if new == raw:
        return "unchanged", "description.md: таймкоды уже актуальны"
    if not dry:
        bk = cfg.work_dir / "backups" / f"description-before-{time.strftime('%Y%m%d-%H%M%S')}.md"
        bk.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, bk)
        p.write_bytes(new.encode("utf-8"))
    return status, msg


def run(cfg, dry: bool = False, log=print) -> dict:
    words, dur = load_words(cfg)
    fp = cfg.work_dir / "stage10" / "srt_fixes.json"
    fixes = json.loads(fp.read_text(encoding="utf-8")) if fp.is_file() else {}
    words, fixlog = apply_fixes(merge_fragments(words), fixes)
    blocks = time_blocks(build_blocks(words))
    text, bad = srt(blocks)
    ch_lines, ch_probs = chapters(cfg, dur)
    out = cfg.work_dir / "stage10"
    durs = [e - s for s, e, _ in blocks]
    log(f"srt: {len(words)} words, {len(blocks)} blocks ({min(durs):.2f}–{max(durs):.2f} s), fixes {len(fixlog)}; "
        f"last block ends {fmt(blocks[-1][1])}" + (f", timeline {dur} s" if dur else ""))
    for b in bad:
        log("  srt problem:", b)
    log("chapters:\n  " + "\n  ".join(ch_lines))
    for p in ch_probs:
        log("  chapter problem:", p)
    if ch_probs:
        desc = ("skipped", "description.md не тронут: главы не прошли проверку")
    else:
        desc = update_description(cfg, ch_lines, dry)
    log(desc[1])
    if not dry:
        out.mkdir(parents=True, exist_ok=True)
        (out / "subtitles.srt").write_text(text, encoding="utf-8")
        if ch_lines:
            (out / "chapters.txt").write_text("\n".join(ch_lines) + "\n", encoding="utf-8")
        log("written:", out / "subtitles.srt", out / "chapters.txt" if ch_lines else "")
    else:
        log("dry run, nothing written")
    return {"blocks": len(blocks), "problems": bad + ch_probs, "description": desc[0], "fixes": fixlog}


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 10: subtitles.srt + chapters.txt (+ timecodes in description.md)")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    if run(common.load_config(a.config), a.dry)["problems"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
