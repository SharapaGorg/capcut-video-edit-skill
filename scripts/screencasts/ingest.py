"""Screencast library: ingest raw phone screencasts into <LIB>/clips + catalog.json.

    python -X utf8 ingest.py                                  # every new file in <LIB>/inbox
    python -X utf8 ingest.py --src <file> --id <id> [--copy]  # one file with a chosen id (existing reel screencasts: --copy)
    python -X utf8 ingest.py --redo <id>                      # re-run the analysis of a clip already in the catalog

Per file: trims the iOS Control Center pull-down at the end (how a screen recording is stopped), writes
clips/<id>.mp4 (no audio), work/<id>/sheet.jpg (2 fps, time on every frame), and a catalog entry with
`auto` = motion segments (still / scroll / change) + OCR text every second. `labels` (surface, scenario,
niche, query, named segments, privacy) are filled by hand after looking at the sheet — see
references/screencasts.md. Labels are never overwritten by a re-run.
"""
import argparse, hashlib, json, shutil, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

LIB = Path(r"C:\Users\shara\Videos\рилсики\_screencasts")
TESS = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
TESSDATA = Path(__file__).resolve().parents[2] / "assets" / "tessdata"   # rus+eng; ASCII path: tesseract cannot open Cyrillic paths
FPS = 6          # analysis rate
W = 180          # analysis width
VIDEO = {".mp4", ".mov", ".m4v"}


def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate:format=duration:format_tags=creation_time",
                        "-of", "json", str(f)], capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    s, fm = j["streams"][0], j["format"]
    num, den = s["r_frame_rate"].split("/")
    created = (fm.get("tags") or {}).get("creation_time")
    if not created:
        created = datetime.fromtimestamp(Path(f).stat().st_mtime).isoformat()
    return {"width": s["width"], "height": s["height"], "fps": round(int(num) / int(den), 2),
            "duration": round(float(fm["duration"]), 3), "recorded": created[:10]}


def frames(f, w, h):
    hh = round(h * W / w / 2) * 2
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(f), "-vf",
                        f"fps={FPS},scale={W}:{hh},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True, check=True)
    a = np.frombuffer(p.stdout, np.uint8)
    return a.reshape(-1, hh, W)


def analyse(fr):
    """per frame: sharpness, % of changed pixels vs previous, vertical shift (px of the analysis frame)"""
    n = len(fr)
    sharp = np.array([cv2.Laplacian(x, cv2.CV_64F).var() for x in fr])
    diff, dy, resp = np.zeros(n), np.zeros(n), np.zeros(n)
    win = cv2.createHanningWindow(fr.shape[1:][::-1], cv2.CV_64F)
    for i in range(1, n):
        a, b = fr[i - 1].astype(np.float64), fr[i].astype(np.float64)
        d = np.abs(a - b)
        diff[i] = (d > 12).mean() * 100              # % of pixels that changed: local changes (typing, a tap) count too
        if diff[i] > 0.2:
            (sx, sy), r = cv2.phaseCorrelate(a, b, win)
            dy[i], resp[i] = sy, r
    return sharp, diff, dy, resp


def tail_cut(sharp, bright, dur):
    """end of the useful part: the Control Center blurs and darkens everything behind it"""
    # The pull-down blurs the whole screen for 1–2 analysis frames (sharpness 0.1–0.3 of the clip's median); the
    # Control Center itself is sharp again, so only the DIP is a reliable mark. Bright content alone is not
    # (a white reel card at the end of the landing clip). No dip in the last 3 s -> nothing is trimmed.
    n = len(sharp)
    base = np.median(sharp[: max(1, int(n * 0.8))])
    for i in range(max(1, n - 3 * FPS), n):
        if sharp[i] < 0.5 * base:
            return round(max(0.5, i / FPS - 0.2), 2)
    return round(dur, 2)


def segments(diff, dy, resp, end):
    n = min(len(diff), int(end * FPS))
    cls = []
    for i in range(n):
        if abs(dy[i]) >= 0.8 and resp[i] > 0.15 and diff[i] > 2:
            cls.append("scroll")
        elif diff[i] < 0.25:
            cls.append("still")
        else:
            cls.append("change")
    sm = cls[:]
    for i in range(1, n - 1):                      # majority over 3 frames
        if cls[i - 1] == cls[i + 1] != cls[i]:
            sm[i] = cls[i - 1]
    runs, s = [], 0
    for i in range(1, n + 1):
        if i == n or sm[i] != sm[s]:
            runs.append([sm[s], s, i]); s = i
    out = []
    for r in runs:                                  # runs shorter than 0.5 s join the previous one
        if out and (r[2] - r[1]) / FPS < 0.5:
            out[-1][2] = r[2]
        elif out and out[-1][0] == r[0]:
            out[-1][2] = r[2]
        else:
            out.append(r)
    res = []
    for kind, a, b in out:
        seg = {"kind": kind, "t0": round(a / FPS, 2), "t1": round(min(b / FPS, end), 2)}
        if kind == "scroll":
            seg["dir"] = "down" if np.median(dy[a:b]) < 0 else "up"   # content moves up = scrolling down
        res.append(seg)
    return res


def ocr(clip, end, tessdata):
    out = []
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(clip), "-vf", "fps=1", "-t", str(end),
                        str(Path(d) / "%04d.png")], check=True)
        for k, p in enumerate(sorted(Path(d).glob("*.png"))):
            im = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if im.mean() < 128: im = 255 - im           # dark theme: tesseract wants dark text on light
            im = cv2.resize(im, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
            cv2.imwrite(str(p), im)
            r = subprocess.run([str(TESS), str(p), "-", "--tessdata-dir", str(tessdata), "-l", "rus+eng", "--psm", "3"],
                               capture_output=True, text=True, encoding="utf-8")
            txt = " ".join(r.stdout.split())
            out.append({"t": k + 0.5, "text": txt[:500]})
    return out


def sheet(clip, end, dst, per_row=10, h=400):
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(clip), "-vf", f"fps=2,scale=-2:{h}",
                        "-t", str(end), str(Path(d) / "%04d.png")], check=True)
        ims = [cv2.imread(str(p)) for p in sorted(Path(d).glob("*.png"))]
    if not ims:
        return
    for k, im in enumerate(ims):
        t = k * 0.5
        cv2.rectangle(im, (0, h - 34), (96, h), (0, 0, 0), -1)
        cv2.putText(im, f"{t:.1f}s", (6, h - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (64, 106, 212), 2)
    w = ims[0].shape[1]
    rows = [ims[i:i + per_row] for i in range(0, len(ims), per_row)]
    blank = np.zeros_like(ims[0])
    grid = np.vstack([np.hstack(r + [blank] * (per_row - len(r))) for r in rows])
    Path(dst).write_bytes(cv2.imencode(".jpg", grid, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes())   # cv2.imwrite cannot write Cyrillic paths


def guess(ocr_list, bright):
    txt = " ".join(o["text"].lower() for o in ocr_list)
    surface = ("chatgpt" if "chatgpt" in txt else "claude" if "claude" in txt else
               "writelo" if "writelo" in txt or "тренды" in txt else None)
    return {"surface": surface, "theme": "light" if np.median(bright) > 128 else "dark"}


def load_catalog(lib):
    p = lib / "catalog.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"clips": []}


def save_catalog(lib, cat):
    cat["clips"].sort(key=lambda c: c["id"])
    (lib / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")


def fingerprint(f):
    st = Path(f).stat()
    return hashlib.sha1(f"{Path(f).name}|{st.st_size}".encode()).hexdigest()[:12]


def ingest(lib, src, cid, copy):
    src = Path(src).resolve()
    cat = load_catalog(lib)
    fp = fingerprint(src)
    old = next((c for c in cat["clips"] if c["id"] == cid or c.get("fingerprint") == fp), None)
    if old and old["id"] != cid:
        print(f"skip {src.name}: already in the catalog as {old['id']}"); return
    info = probe(src)
    fr = frames(src, info["width"], info["height"])
    sharp, diff, dy, resp = analyse(fr)
    bright = fr.reshape(len(fr), -1).mean(1)
    end = tail_cut(sharp, bright, info["duration"])
    clip = lib / "clips" / f"{cid}.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-t", str(end), "-an",
                    "-c:v", "copy", "-movflags", "+faststart", str(clip)], check=True)
    work = lib / "work" / cid
    work.mkdir(parents=True, exist_ok=True)
    sheet(clip, end, work / "sheet.jpg")
    o = ocr(clip, end, TESSDATA)
    g = guess(o, bright)
    if not copy and src.parent == lib / "inbox":     # keep the raw file: the catalog points at it for --redo
        (lib / "inbox" / "_done").mkdir(exist_ok=True)
        src = Path(shutil.move(str(src), lib / "inbox" / "_done" / src.name))
    entry = old or {"id": cid, "labels": {"surface": g["surface"], "scenario": None, "niche": None, "theme": g["theme"],
                                          "query": None, "segments": [], "privacy": [], "notes": ""},
                    "used_in": []}
    entry.update({"file": f"clips/{cid}.mp4", "source": str(src), "fingerprint": fp, **info,
                  "trim_end": end, "auto": {"segments": segments(diff, dy, resp, end), "ocr": o}})
    cat["clips"] = [c for c in cat["clips"] if c["id"] != cid] + [entry]
    save_catalog(lib, cat)
    print(f"{cid}: {info['duration']:.1f}s -> {end:.1f}s, {len(entry['auto']['segments'])} motion segments, "
          f"surface={entry['labels']['surface']}, theme={entry['labels']['theme']}, sheet {work / 'sheet.jpg'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=str(LIB))
    ap.add_argument("--src")
    ap.add_argument("--id")
    ap.add_argument("--copy", action="store_true", help="keep the source where it is (screencasts already used in reels)")
    ap.add_argument("--redo")
    a = ap.parse_args()
    lib = Path(a.lib)
    for d in ("inbox", "clips", "work"):
        (lib / d).mkdir(parents=True, exist_ok=True)
    if a.redo:
        c = next(c for c in load_catalog(lib)["clips"] if c["id"] == a.redo)
        ingest(lib, c["source"], a.redo, True); return
    if a.src:
        if not a.id: sys.exit("--src needs --id")
        ingest(lib, a.src, a.id, a.copy); return
    new = [p for p in sorted((lib / "inbox").iterdir()) if p.suffix.lower() in VIDEO]
    if not new:
        print("inbox is empty"); return
    for p in new:                                    # temporary id; renamed by hand after labelling (lib.py rename)
        ingest(lib, p, "new-" + p.stem.lower(), False)


if __name__ == "__main__":
    main()
