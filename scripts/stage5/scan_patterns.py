"""Stage 5, step 3a: personal-data patterns in the OCR (stage5/ocr/*.tsv) -> stage5/pattern_hits.json.

    python -X utf8 scripts/stage5/scan_patterns.py --config config.json [--dry]

Patterns (STAGE_5 step 2): e-mail; keys and tokens (sk-, pk-, ghp_, Bearer, eyJ…, AKIA, xox?-); hex/base64 >= 20;
phones (10–13 digits); card numbers (Luhn); password fields; tokens in the address bar (token=, key=…).
A hit = {file (stem), sec, psm, type, match, line, bbox [x, y, w, h] px of the source frame}.
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

PATS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "key": re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|pk_[A-Za-z0-9_-]{8,}|pk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{10,}|"
                      r"eyJ[A-Za-z0-9_-]{10,}|Bearer\s+\S{8,}|AKIA[A-Z0-9]{12,}|xox[bap]-[A-Za-z0-9-]{10,})"),
    "hexb64": re.compile(r"\b(?=[A-Za-z0-9+/_-]*[0-9])(?=[A-Za-z0-9+/_-]*[A-Za-z])[A-Za-z0-9+/_-]{20,}={0,2}\b"),
    "phone": re.compile(r"(?<![\d.])(?:\+?\d[\d\s().-]{8,}\d)(?![\d.])"),
    "card": re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
    "password": re.compile(r"(?i)(пароль|password|passwd)"),
    "urltoken": re.compile(r"(?i)[?&](token|key|api_key|apikey|access_token|auth)=\S+"),
}
SECRET = ("email", "key", "urltoken", "password")   # verify_censor: these must be gone after the blur
NAME_RE = re.compile(r"(.+?)_(\d+)(\.psm11)?\.tsv$")


def luhn(s: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", s)][::-1]
    return len(d) >= 13 and sum(x if i % 2 == 0 else (x * 2 - 9 if x * 2 > 9 else x * 2) for i, x in enumerate(d)) % 10 == 0


def keep(name: str, s: str) -> bool:
    if name == "phone":
        return 10 <= len(re.sub(r"\D", "", s)) <= 13
    if name == "card":
        return luhn(s)
    return True


def lines_of(rows: list[dict]) -> list[dict]:
    """OCR words grouped into lines (block, par, line): text + words [(l, t, w, h, text)] + bbox."""
    lines = collections.OrderedDict()
    for r in rows:
        L = lines.setdefault((r["block"], r["par"], r["line"]), {"words": []})
        L["words"].append(r)
    out = []
    for L in lines.values():
        ws = sorted(L["words"], key=lambda r: r["l"])
        out.append({"text": " ".join(w["text"] for w in ws), "words": ws,
                    "bbox": [min(w["l"] for w in ws), min(w["t"] for w in ws),
                             max(w["l"] + w["w"] for w in ws) - min(w["l"] for w in ws),
                             max(w["t"] + w["h"] for w in ws) - min(w["t"] for w in ws)]})
    return out


def scan_rows(rows: list[dict]) -> list[dict]:
    """Pattern hits of one OCR page: [{type, match, line, bbox}] — bbox of the words that hold the match."""
    hits = []
    for L in lines_of(rows):
        for name, pat in PATS.items():
            for m in pat.finditer(L["text"]):
                s = m.group(0)
                if not keep(name, s):
                    continue
                ws = [w for w in L["words"] if w["text"] in s or s in w["text"] or any(p in w["text"] for p in s.split()[:1])]
                if ws:
                    x0, y0 = min(w["l"] for w in ws), min(w["t"] for w in ws)
                    bb = [x0, y0, max(w["l"] + w["w"] for w in ws) - x0, max(w["t"] + w["h"] for w in ws) - y0]
                else:
                    bb = L["bbox"]
                hits.append({"type": name, "match": s, "line": L["text"][:200], "bbox": bb})
    return hits


def run(cfg, dry: bool = False) -> list[dict]:
    root = cfg.work_dir / "stage5"
    hits = []
    for tsv in sorted((root / "ocr").glob("*.tsv")):
        m = NAME_RE.match(tsv.name)
        if not m:
            continue
        rows = common.read_tsv(tsv)
        for h in scan_rows(rows):
            hits.append(dict(h, file=m.group(1), sec=int(m.group(2)), psm="11" if m.group(3) else "3"))
    cnt = collections.Counter(h["type"] for h in hits)
    print("hits by type:", dict(cnt))
    uniq = collections.defaultdict(set)
    for h in hits:
        uniq[h["type"]].add(h["match"])
    for t, s in uniq.items():
        print(f"== {t} ({len(s)} unique): " + ", ".join(sorted(s)[:20]))
    if not dry:
        root.mkdir(parents=True, exist_ok=True)
        (root / "pattern_hits.json").write_text(json.dumps(hits, ensure_ascii=False, indent=0), encoding="utf-8")
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="stage 5: personal-data patterns in the OCR")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    run(common.load_config(a.config), a.dry)


if __name__ == "__main__":
    main()
