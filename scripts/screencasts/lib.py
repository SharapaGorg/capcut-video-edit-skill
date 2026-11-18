"""Screencast library lookup for reel layouts and specs.

    from lib import get, find, mark_used          # sys.path.insert(0, <skill>/scripts/screencasts)
    path, t0, t1 = get("G3-psy-ideas-dark/answer")   # a named segment (labels.segments[].name) or the whole clip
    for clip, seg in find(surface="writelo", action="фильтр", niche="cars", min_dur=3): ...
    mark_used("W6-cars-search/results", "ноябрь/8-…")

CLI:  python -X utf8 lib.py list [--surface S] [--niche N] [--action A]
      python -X utf8 lib.py show <id>
      python -X utf8 lib.py rename <old> <new>       # after labelling a new-… clip from the inbox
"""
import argparse, os, json, sys
from datetime import date
from pathlib import Path

LIB = Path(os.environ.get("WRITELO_SCREENCASTS", Path.home() / "Videos" / "рилсики" / "_screencasts"))


def load(lib=LIB):
    return json.loads((Path(lib) / "catalog.json").read_text(encoding="utf-8"))


def save(cat, lib=LIB):
    cat["clips"].sort(key=lambda c: c["id"])
    (Path(lib) / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")


def _clip(cat, cid):
    for c in cat["clips"]:
        if c["id"] == cid:
            return c
    raise KeyError(f"no clip {cid!r} in the screencast library")


def get(ref, lib=LIB):
    """'id' -> whole trimmed clip, 'id/segment' -> that labelled segment. Returns (Path, t0, t1) in clip time."""
    cid, _, seg = ref.partition("/")
    c = _clip(load(lib), cid)
    path = Path(lib) / c["file"]
    if not seg:
        return path, 0.0, c["trim_end"]
    for s in c["labels"]["segments"]:
        if s["name"] == seg:
            return path, s["t0"], s["t1"]
    raise KeyError(f"{cid} has no segment {seg!r}: {[s['name'] for s in c['labels']['segments']]}")


def stale(c, today=None):
    d = c["labels"].get("stale_after")
    return bool(d) and (today or date.today().isoformat()) > d


def find(surface=None, scenario=None, niche=None, theme=None, action=None, min_dur=0.0, skip_used_in=None,
         allow_stale=False, lib=LIB):
    """labelled segments that match; `action` is a substring of the segment's action/desc (the script's verb:
    «листаем», «фильтр», «поиск», «вводим запрос», «ответ»…). Fresh and unused clips first."""
    out = []
    for c in load(lib)["clips"]:
        L = c["labels"]
        if surface and L.get("surface") != surface: continue
        if scenario and L.get("scenario") != scenario: continue
        if niche and L.get("niche") not in (niche, "any"): continue
        if theme and L.get("theme") != theme: continue
        if not allow_stale and stale(c): continue
        if skip_used_in and any(u["reel"] == skip_used_in for u in c.get("used_in", [])): continue
        for s in L.get("segments", []):
            if s["t1"] - s["t0"] < min_dur: continue
            if action and action.lower() not in (s.get("action", "") + " " + s.get("desc", "")).lower(): continue
            out.append((c, s))
    out.sort(key=lambda cs: (len(cs[0].get("used_in", [])), cs[0].get("recorded", "")), reverse=False)
    return out


def mark_used(ref, reel, lib=LIB):
    cat = load(lib)
    c = _clip(cat, ref.partition("/")[0])
    c.setdefault("used_in", []).append({"ref": ref, "reel": reel, "date": date.today().isoformat()})
    save(cat, lib)


def rename(old, new, lib=LIB):
    cat = load(lib)
    c = _clip(cat, old)
    lib = Path(lib)
    (lib / c["file"]).rename(lib / "clips" / f"{new}.mp4")
    if (lib / "work" / old).exists():
        (lib / "work" / old).rename(lib / "work" / new)
    c["id"], c["file"] = new, f"clips/{new}.mp4"
    save(cat, lib)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "show", "rename"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--surface"); ap.add_argument("--niche"); ap.add_argument("--action")
    a = ap.parse_args()
    if a.cmd == "rename":
        rename(*a.args); return
    cat = load()
    if a.cmd == "show":
        print(json.dumps(_clip(cat, a.args[0]), ensure_ascii=False, indent=1)); return
    if a.action or a.niche:
        for c, s in find(surface=a.surface, niche=a.niche, action=a.action, allow_stale=True):
            print(f"{c['id']}/{s['name']:<14} {s['t0']:6.1f}–{s['t1']:<6.1f} {s.get('action', '')} — {s.get('desc', '')}")
        return
    for c in cat["clips"]:
        L = c["labels"]
        if a.surface and L.get("surface") != a.surface: continue
        flag = " STALE" if stale(c) else ""
        print(f"{c['id']:<28} {L.get('surface') or '?':<8} {L.get('niche') or '-':<11} {L.get('theme'):<5} "
              f"{c['trim_end']:5.1f}s  segs {len(L.get('segments', []))}  used {len(c.get('used_in', []))}{flag}  "
              f"{L.get('query') or ''}")


if __name__ == "__main__":
    sys.exit(main())
