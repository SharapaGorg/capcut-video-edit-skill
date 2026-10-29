"""Reel FROM SCRATCH: raw sources (mic m4a + camera MOV) + a script spec -> 1080x1920 H.264 reel, no CapCut.
Format of the spec and the rules: references/reel.md. The look is the editor's reference (references/reference-style.md):
camera through SRC_VF + ref_joint.cube (shorts/cam_lut.py), voice spectrum by shorts/voice_ref.match_fx, speed x1.10
(video setpts, voice rubberband with the pitch kept), captions word by word without a plate, full-screen scheme
(shorts/scheme.py), dark UI cards, stickers / memes near the shoulders, music from the hook end, final −17.5 LUFS / TP −1.

    python -X utf8 scripts/reel/build_reel.py reel_spec.json [--plan] [--gfx-only] [--skip-gfx] [--no-validate]

Paths of the spec are relative to the spec's folder. Output: spec "out"; work files in work/<id>/ next to the spec:
plan.json, wordmap.json, voice.wav, video.mp4, gfx.html, gfx.mov, mix_final.m4a, final.mp4, sheet.jpg, compare.jpg,
VALIDATION.md (--no-validate skips the surface checks).
--plan: the plan + wordmap + gfx.html only (no media decode). Library use: plan(spec, words) -> plan dict (pure:
spec + whisper words, no media), gfx_html(plan, spec) -> page text.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS / 'shorts'))
sys.path.insert(0, str(SCRIPTS / 'stage10'))
import cam_lut  # noqa: E402
import footage  # noqa: E402
import peephole  # noqa: E402  (full-screen motion-graphic sections: "footage")
import scheme  # noqa: E402
import voice_ref  # noqa: E402
import build_render  # noqa: E402  (render: Playwright -> ProRes 4444; final_loop; profile; TOYUV)
from loudnorm import measure  # noqa: E402

FPS, W, H = 30, 1080, 1920
SPEED = 1.20                             # the reference reel: words 1.20x faster than the mic, pitch kept
GAP_MAX, GAP_KEEP = 0.35, 0.15          # a pause longer than GAP_MAX inside a section is cut down to GAP_KEEP
SIL_DB, SIL_MIN, SNAP_PRE, SNAP_POST = -40, 0.12, 0.05, 0.08   # speech by energy: silencedetect; range edges snap outside the speech
ACCENT, TEXT = '#F8DE03', '#FBFBFB'      # reference: yellow accent with a glow, white text with a shadow, no plate
UI_ACCENT, UI_BG = '#E8622A', '#0D0D0D'  # dark UI cards with orange accents (the reference's "service screens")
SFX_PEAK = -22.0                         # dBFS peak of every SFX hit before the final gain (as build_render.SFX_PEAK)
MUSIC_REL, MUSIC_FADE_IN, MUSIC_FADE_OUT, MUSIC_HS = -16.0, 0.3, 1.0, 'highshelf=g=-8:f=4000'
STICKER_STAGGER = 3 / FPS
UI_SUBCUT = 1.0                          # the UI card alternates its state every ~1 s (a "new screen" per second)
# Caption slot per camera angle (y of the phrase centre, px); the angle comes from spec section "angle" or the camera file.
# cap_box = (left, width, align): the reference puts the phrase next to the head, never on the face / chest.
ANGLES = {
    'mic':   dict(cap_y=1330, cap_box=(60, 700, 'left'), hook_y=200, stickers=[(905, 1360), (150, 1440), (330, 1640), (780, 1620)]),
    'high':  dict(cap_y=440, cap_box=(0, W, 'center'), hook_y=330, stickers=[(150, 1500), (930, 1500)]),   # face right-centre, text above the head
    'arms':  dict(cap_y=440, cap_box=(0, W, 'center'), hook_y=330, memes=[(50, 250), (730, 250)], stickers=[(150, 1200), (930, 1200)],
                  images=[(760, 760)]),
    'desk':  dict(cap_y=440, cap_box=(600, 460, 'left'), hook_y=330, stickers=[(150, 480), (150, 700)], cta_y=1150),   # head centre-left, painting top centre: text on the wall right of the head above the sword
    'couch': dict(cap_y=400, cap_box=(430, 620, 'left'), hook_y=330, stickers=[(160, 1120), (920, 1120)], cta_y=1150),   # KURS above the Reels UI strip (bottom ~25 %)   # head top-left -> text right of it
}
ZOOM_IN, ZOOM_HOLD, ZOOM_OUT, ZOOM_SCALE = 0.2, 0.7, 0.3, 1.12
ZP_UP = 4                                # upscale before zoompan (sub-pixel crop steps, no jitter)   # punch-in on an accent word (output s): ease in, hold, ease out
ZOOM_ANCHOR = {'mic': (0.5, 0.34), 'high': (0.6, 0.3), 'arms': (0.5, 0.3), 'couch': (0.35, 0.32)}   # face centre, fraction of the frame
VOICE_COMP = 'acompressor=threshold=-21dB:ratio=3.5:attack=4:release=90:makeup=1:knee=4,highshelf=g=-1.5:f=4500'   # the reference voice is dense (LRA ~ 4 LU)
DEFAULT_ANGLE = 'high'


def fr(t): return int(round(t * FPS))
def q(t): return round(fr(t) / FPS, 4)
def strip(w): return re.sub(r'[^\wа-яё]+', '', w.lower(), flags=re.I)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError(' '.join(map(str, cmd[:14])) + '\n' + r.stderr[-2000:])
    return r


# ---------------- plan (pure) ----------------
def ranges_of(sec):
    v = sec['v']
    return [list(map(float, r)) for r in (v if isinstance(v[0], (list, tuple)) else [v])]


_SPEECH = {}


def speech_segments(path):
    """[(a, b)] of speech by energy (ffmpeg silencedetect, SIL_DB / SIL_MIN), cached per file. Whisper word times are
    NOT used for the cuts: whisper merges retakes and shortens word ends («бигтехов» got cut at 10.95 while the voice
    ran to 11.32)."""
    path = Path(path)
    key = str(path.resolve())
    if key in _SPEECH: return _SPEECH[key]
    r = subprocess.run(['ffmpeg', '-v', 'info', '-i', str(path), '-af', f'silencedetect=n={SIL_DB}dB:d={SIL_MIN}', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    dur = float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)]).stdout.strip())
    ev = [(m.group(1), float(m.group(2))) for m in re.finditer(r'silence_(start|end): ([0-9.]+)', r.stderr)]
    segs, cur = [], 0.0
    for kind, t in ev:
        if kind == 'start':
            if t - cur > 0.01: segs.append((cur, t))
        else:
            cur = t
    if dur - cur > 0.01: segs.append((cur, dur))
    _SPEECH[key] = segs
    return segs


def snap_range(segs, a, b):
    """Edges of [a, b] moved OUT of the speech: a start inside a speech segment goes to its start − SNAP_PRE, an end
    inside a segment goes to its end + SNAP_POST (a phrase is never cut mid-word)."""
    for s0, s1 in segs:
        if s0 < a < s1:
            a = max(0.0, s0 - SNAP_PRE) if a - s0 <= 0.4 else s1 + 0.02   # deep inside a blob = a false start / breath before the phrase: skip it
        if s0 < b < s1:
            if s1 - b <= 0.8: b = s1 + SNAP_POST
            else: print(f'  ВНИМАНИЕ: конец {b:.2f} внутри речи {s0:.2f}–{s1:.2f} — оставлен как есть')
    return a, b


def cut_silences(segs, a, b, gap_max=GAP_MAX, gap_keep=GAP_KEEP):
    """Source pieces [(a0, b0), …] of the range [a, b] with every silence (by energy) longer than gap_max shortened to
    gap_keep around its middle."""
    inside = [(max(s0, a), min(s1, b)) for s0, s1 in segs if s0 < b and s1 > a]
    if not inside:
        return [(a, b)]
    pieces, cur_a = [], a
    for (_, e0), (s1, _) in zip(inside, inside[1:]):
        g = s1 - e0
        if g > gap_max:
            mid = (e0 + s1) / 2
            pieces.append((cur_a, mid - gap_keep / 2)); cur_a = mid + gap_keep / 2
    pieces.append((cur_a, b))
    return [(round(x, 4), round(y, 4)) for x, y in pieces if y - x > 0.02]


def align_script(words, text):
    """Script words with the whisper times: every letter of the whisper words gets a time (linear inside the word), the
    letters of the script are matched to them (difflib, blocks >= 2 letters), a script word = [first, last] matched
    letter; words without a match are interpolated between their neighbours. The caption then shows the SCRIPT text
    (whisper mishears: «аниме» for «а не мы», «Rayteo» for «writelo»)."""
    import difflib
    wch, wt = [], []
    for w in words:
        ch = strip(w['word']); n = max(len(ch), 1)
        for i, c in enumerate(ch):
            wch.append(c); wt.append((w['start'] + (w['end'] - w['start']) * i / n, w['start'] + (w['end'] - w['start']) * (i + 1) / n))
    toks = text.split()
    sch, owner = [], []
    for ti, t in enumerate(toks):
        for c in strip(t): sch.append(c); owner.append(ti)
    sm = difflib.SequenceMatcher(None, ''.join(wch), ''.join(sch), autojunk=False)
    t0 = {}; t1 = {}
    for a, b, n in sm.get_matching_blocks():
        if n < 2: continue
        for k in range(n):
            ti = owner[b + k]
            t0[ti] = min(t0.get(ti, 9e9), wt[a + k][0]); t1[ti] = max(t1.get(ti, -1), wt[a + k][1])
    out = [dict(word=t, start=t0.get(i), end=t1.get(i),
                proper=bool(i and t[:1].isupper() and not toks[i - 1].rstrip()[-1:] in '.!?')) for i, t in enumerate(toks)]
    # interpolate the unmatched words between the neighbours (equal share of the free span), clamp to the audio range
    lo = words[0]['start'] if words else 0.0; hi = words[-1]['end'] if words else 0.0
    i = 0
    while i < len(out):
        if out[i]['start'] is not None: i += 1; continue
        j = i
        while j < len(out) and out[j]['start'] is None: j += 1
        a = out[i - 1]['end'] if i else lo; b = out[j]['start'] if j < len(out) else hi
        if b < a: b = a
        step = (b - a) / (j - i)
        for k in range(i, j):
            out[k]['start'] = a + step * (k - i); out[k]['end'] = a + step * (k - i + 1)
        i = j
    for a, b in zip(out, out[1:]):            # monotonic, no overlap
        if b['start'] < a['end']: b['start'] = a['end']
        if b['end'] < b['start']: b['end'] = b['start']
    for w in out: w['start'] = round(w['start'], 3); w['end'] = round(w['end'], 3)
    return out


def plan(spec, words_all, speed=None, voice_dir=None, base=None):
    """spec + whisper words {file: [{word,start,end}]} -> plan: sections (out in/out), pieces (src/cam/out times, speed),
    words (out times), total. Output times are on the frame grid; the speed is applied per piece. voice_dir given ->
    the range edges snap outside the speech and the pauses are cut by energy (speech_segments); without it (tests) the
    ranges are taken as written and the pauses come from the word gaps."""
    speed = float(speed or spec.get('speed', SPEED))
    out_t, pieces, words, sections = 0.0, [], [], []
    for si, sec in enumerate(spec['sections']):
        if sec.get('clip'):                 # ready-made video with its own sound (e.g. a hook from Claude Design): one piece, no words
            cdur = clip_duration(Path(base) / sec['clip']) if base else float(sec.get('clip_dur', 3.0))
            dur = q(cdur)
            p = dict(section=sec['id'], idx=len(pieces), src=None, clip=sec['clip'], src_in=0.0, src_out=dur * speed, speed=speed,
                     out_in=out_t, out_out=q(out_t + dur), dur=dur, camera=None, cam_in=None)
            pieces.append(p); out_t = p['out_out']
            sections.append(dict(id=sec['id'], idx=si, out_in=p['out_in'], out_out=out_t, camera=None, angle=None, n_words=0, clip=True))
            continue
        wsrc = words_all.get(sec['voice'])
        if wsrc is None:
            raise SystemExit(f"{sec['id']}: нет слов для {sec['voice']} в words.json")
        segs = speech_segments(Path(voice_dir) / sec['voice']) if voice_dir else None
        rng = ranges_of(sec)
        if segs is not None:
            rng = [list(snap_range(segs, a, b)) for a, b in rng]
            sec['v_snapped'] = rng
        if sec.get('script'):
            inside = [w for w in wsrc if any(w['start'] < b and w['end'] > a for a, b in rng)]
            wsrc = align_script(inside, sec['script'])
        s_in = out_t
        sec_words = []
        for a, b in rng:
            if segs is None:
                segs_w = [(w['start'], w['end']) for w in wsrc]
                cuts = cut_silences(segs_w, a, b)
            else:
                cuts = cut_silences(segs, a, b, float(sec.get('gap_max', GAP_MAX)), float(sec.get('gap_keep', GAP_KEEP)))
            for pa, pb in cuts:
                dur = q((pb - pa) / speed)
                p = dict(section=sec['id'], idx=len(pieces), src=sec['voice'], src_in=pa, src_out=pb, speed=speed,
                         out_in=out_t, out_out=q(out_t + dur), dur=dur, camera=sec.get('camera'),
                         cam_in=(pa + float(sec.get('cam_offset', 0))) if sec.get('camera') else None)
                first_a = rng[0][0]
                for w in wsrc:
                    mid = (w['start'] + w['end']) / 2
                    if mid < first_a < w['end']: mid = first_a                 # whisper started the word before the range: first piece
                    if pa - 1e-6 <= mid < pb:      # the word belongs to the piece holding its middle
                        o0 = out_t + (max(w['start'], pa) - pa) / speed
                        o1 = out_t + (min(w['end'], pb) - pa) / speed
                        ww = dict(section=sec['id'], word=w['word'], src_start=w['start'], src_end=w['end'],
                                  start=round(o0, 3), end=round(o1, 3), piece=p['idx'], proper=bool(w.get('proper')))
                        words.append(ww); sec_words.append(ww)
                pieces.append(p); out_t = p['out_out']
        sections.append(dict(id=sec['id'], idx=si, out_in=s_in, out_out=out_t, camera=sec.get('camera'),
                             angle=sec.get('angle') or angle_of(sec.get('camera')), n_words=len(sec_words)))
    return dict(speed=speed, total=out_t, sections=sections, pieces=pieces, words=words)


def clip_duration(path):
    return float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)]).stdout.strip().strip(','))


def angle_of(camera):
    """Angle preset by the camera file name (spec "angle" overrides): no camera -> none."""
    if not camera:
        return None
    n = Path(camera).stem.lower()
    for key, names in (('mic', ('1',)), ('high', ('2',)), ('couch', ('cta',))):
        if n in names: return key
    return 'arms' if n.startswith('img') else DEFAULT_ANGLE


def word_time(pl, section, name, after=0.0, missing='end'):
    """Out time (start) of the first word of the section whose stripped text starts with `name` (stripped), at or after
    `after`. Not found: 'end' -> the section's end − 0.3 (with a warning), 'none' -> None, 'raise' -> error."""
    key = strip(name)
    for w in pl['words']:
        if w['section'] == section and w['start'] >= after - 0.002 and strip(w['word']).startswith(key):
            return w['start']
    sec = next(s for s in pl['sections'] if s['id'] == section)
    if missing == 'raise':
        raise SystemExit(f"{section}: слово «{name}» не найдено в транскрипте секции")
    if missing == 'none':
        return None
    print(f"  ВНИМАНИЕ: {section}: слово «{name}» не найдено — ставлю в конец секции ({sec['out_out'] - 0.3:.2f} с)")
    return max(sec['out_in'], sec['out_out'] - 0.3)


# ---------------- graphics ----------------
def fix_word(w, fixes):
    for k, v in (fixes or {}).items():
        if k.lower() in w.lower():
            return v
    return w


def is_accent(w, accents):
    s = strip(w)
    return any(s == strip(a) or (len(strip(a)) > 2 and s.startswith(strip(a))) for a in accents or [])


def phrases_of(words, max_words=4, max_gap=0.6):
    """Caption phrases: 1–4 words, cut at punctuation . , ! ? and at a gap > max_gap."""
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w['start'] - cur[-1]['end'] > max_gap):
            out.append(cur); cur = []
        cur.append(w)
        if re.search(r'[.,!?:;]$', w['word']) and len(cur) >= 1:
            out.append(cur); cur = []
    if cur: out.append(cur)
    return out


def display(w, fixes):
    """Caption text of a word: script spelling, lowercase as in the reference — except Latin words and proper nouns
    (capitalised in the script mid-sentence: «Егор»), marked by align_script."""
    proper = isinstance(w, dict) and w.get('proper')
    t = fix_word(w['word'] if isinstance(w, dict) else w, fixes)
    t = t.rstrip('.,!?:;').lstrip('-')
    return t if proper or re.search(r'[A-Za-z]', t) or t == 'IT' else t.lower()


CSS = f'''
.rl {{ position:absolute; font-family:'Unbounded', sans-serif; font-weight:700; color:{TEXT}; text-shadow:0 2px 6px rgba(0,0,0,.6); text-transform:none; }}
.rhook {{ left:0; top:0; width:{W}px; display:flex; flex-direction:column; align-items:center; gap:4px; }}
.rhook .ln {{ font-weight:900; font-size:86px; line-height:1.1; letter-spacing:-.02em; text-shadow:0 4px 14px rgba(0,0,0,.7); white-space:nowrap; }}
.rhook .ln.acc {{ color:{ACCENT}; text-shadow:0 0 22px {ACCENT}99, 0 4px 14px rgba(0,0,0,.6); }}
.capl {{ left:0; width:{W}px; display:flex; justify-content:center; gap:16px; flex-wrap:wrap; padding:0 40px; box-sizing:border-box; }}
.capl.left {{ justify-content:flex-start; }}
.capl .w {{ font-size:46px; line-height:1.25; white-space:nowrap; }}
.capl .w.acc {{ color:{ACCENT}; font-weight:800; font-size:54px; text-shadow:0 0 18px {ACCENT}99, 0 2px 6px rgba(0,0,0,.6); }}
.capl.one .w {{ font-size:50px; }}
.capl.ftgcap {{ z-index:6; }}
.stk {{ position:absolute; transform-origin:center; background:#FFFFFF; color:#111; font-family:'Unbounded', sans-serif; font-weight:800; font-size:34px;
  padding:14px 26px 16px; border-radius:22px; box-shadow:0 6px 18px rgba(0,0,0,.35); white-space:nowrap; }}
.stk.app {{ width:150px; height:150px; padding:0; border-radius:34px; overflow:hidden; display:flex; align-items:center; justify-content:center; }}
.stk.app img {{ width:100%; height:100%; object-fit:cover; display:block; }}
.meme {{ position:absolute; width:300px; display:flex; flex-direction:column; align-items:center; gap:14px; }}
.meme .tile {{ width:300px; height:300px; border-radius:28px; background:#F1EDE6; display:flex; align-items:center; justify-content:center; font-size:170px;
  box-shadow:0 8px 22px rgba(0,0,0,.35); font-family:'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif; position:relative; overflow:visible; }}
.meme .tile img {{ width:100%; height:100%; object-fit:cover; border-radius:28px; display:block; }}
.meme .tile svg.cap {{ position:absolute; left:-30px; top:-70px; width:220px; height:150px; }}
.meme .txt {{ font-size:34px; line-height:1.2; text-align:center; width:340px; font-weight:800; }}
.img {{ position:absolute; display:flex; align-items:center; justify-content:center; }}
.img img, .img svg {{ width:100%; height:100%; object-fit:contain; display:block; filter:drop-shadow(0 6px 14px rgba(0,0,0,.4)); }}
.cta {{ left:0; width:{W}px; text-align:center; font-weight:900; font-size:170px; line-height:1; letter-spacing:-.03em; color:{ACCENT};
  text-shadow:0 0 36px {ACCENT}AA, 0 0 90px {ACCENT}55, 0 6px 16px rgba(0,0,0,.5); }}
.pin {{ left:0; width:{W}px; z-index:6; display:flex; flex-direction:column; align-items:center; gap:2px; }}
.pin .ln {{ font-weight:800; font-size:58px; line-height:1.15; letter-spacing:-.02em; color:{ACCENT}; white-space:nowrap;
  text-shadow:0 0 24px {ACCENT}99, 0 4px 14px rgba(0,0,0,.7); }}
.dev {{ position:absolute; z-index:3; filter:drop-shadow(0 24px 40px rgba(0,0,0,.55)); }}
.dev .scr {{ position:absolute; overflow:hidden; background:linear-gradient(160deg,#1A1A1A 0%,#0A0A0A 60%,#141414 100%); display:flex; align-items:flex-start; justify-content:center; }}
.dev .scr img, .dev .scr video {{ width:100%; height:100%; object-fit:cover; display:block; }}
.dev .scr .logo {{ width:34%; margin-top:22%; aspect-ratio:1; border-radius:22%; overflow:hidden; box-shadow:0 10px 30px rgba(0,0,0,.6); }}
.dev .scr .logo img {{ width:100%; height:100%; object-fit:cover; }}
.dev .frm {{ position:absolute; left:0; top:0; display:block; }}
.dev .scr .seq {{ position:absolute; inset:0; }}
.dev .scr .seq img.sf {{ position:absolute; left:0; top:0; width:100%; height:100%; display:none; }}
.dev .scr .seq img.sf.on {{ display:block; }}
.ui {{ position:absolute; left:0; top:0; width:{W}px; height:{H}px; background:{UI_BG}; z-index:4; overflow:hidden; font-family:'Unbounded', sans-serif; color:#EDEDED; }}
.ui .top {{ height:150px; display:flex; align-items:center; padding:0 60px; gap:24px; border-bottom:2px solid #1F1F1F; font-size:40px; font-weight:800; }}
.ui .top .dot {{ width:22px; height:22px; border-radius:50%; background:{UI_ACCENT}; }}
.ui .search {{ margin:50px 60px 0; height:110px; border-radius:26px; background:#171717; border:2px solid #262626; display:flex; align-items:center; padding:0 36px; font-size:34px; color:#9A9A9A; }}
.ui .rows {{ margin:50px 60px 0; display:flex; flex-direction:column; gap:26px; }}
.ui .row {{ height:150px; border-radius:26px; background:#151515; border:2px solid #222; display:flex; align-items:center; padding:0 40px; gap:30px; font-size:40px; font-weight:700; }}
.ui .row .ic {{ width:70px; height:70px; border-radius:18px; background:#242424; flex:none; }}
.ui .row.hi {{ border-color:{UI_ACCENT}; box-shadow:0 0 0 3px {UI_ACCENT}55 inset; }}
.ui .row.hi .ic {{ background:{UI_ACCENT}; }}
.ui .row .val {{ margin-left:auto; color:{UI_ACCENT}; font-weight:800; }}
.ui .tiles {{ margin:50px 60px 0; display:grid; grid-template-columns:1fr 1fr; gap:26px; }}
.ui .tile {{ height:420px; border-radius:26px; background:linear-gradient(180deg,#1C1C1C,#111); border:2px solid #222; position:relative; }}
.ui .tile .bd {{ position:absolute; left:20px; top:20px; background:{UI_ACCENT}; color:#111; font-weight:800; font-size:28px; padding:8px 16px; border-radius:14px; }}
.ui .tile .ft {{ position:absolute; left:20px; bottom:20px; font-size:28px; color:#BDBDBD; }}
.ui .cursor {{ position:absolute; width:90px; height:90px; border-radius:50%; border:6px solid {UI_ACCENT}; box-shadow:0 0 24px {UI_ACCENT}99; }}
.ui .ucap {{ position:absolute; left:0; top:1660px; width:{W}px; text-align:center; font-size:50px; font-weight:700; color:{TEXT}; text-shadow:0 2px 6px rgba(0,0,0,.6); }}
'''


def _el(cls, t_in, t_out=None, fx='cut', dur=0.01, ofx='cut', odur=0.01, style='', extra=''):
    o = f' data-out="{t_out:.3f}"' if t_out is not None else ''
    return f'<div class="{cls}" data-in="{t_in:.3f}"{o} data-fx="{fx}" data-dur="{dur}" data-ofx="{ofx}" data-odur="{odur}" style="{style}" {extra}>'


def caption_html(words, fixes, accents, y, t_end, one=False, cls='', box=None, skip=(), size=None):
    """Phrases of 1–4 words at y (centre) inside box=(left, width, align); every word slides up 30 px into its final
    slot at its spoken time; the phrase is cut at the next phrase's first word (or t_end). Phrases inside a `skip`
    interval (memes on screen) are not shown — the meme caption is the subtitle then."""
    o = []
    left, width, align = box or (0, W, 'center')
    phs = phrases_of(words, 1 if one else 4)
    for i, ph in enumerate(phs):
        t0 = ph[0]['start']; t1 = phs[i + 1][0]['start'] if i + 1 < len(phs) else t_end
        if t1 <= t0: continue
        if any(a <= t0 < b for a, b in skip): continue
        for a_, b_ in skip:                        # a phrase running into the memes is cut at their pop
            if t0 < a_ < t1: t1 = a_
        o.append(_el(f'rl capl {cls}{" one" if one else ""}{" left" if align == "left" else ""}', t0, t1, style=f'top:{y - 30}px;left:{left}px;width:{width}px;'))
        for w in ph:
            txt = display(w, fixes)
            acc = ' acc' if is_accent(w['word'], accents) or is_accent(txt, accents) else ''
            fs = f' style="font-size:{int(size * 1.12 if acc else size)}px"' if size else ''
            o.append(f'<span class="w{acc}" data-in="{w["start"]:.3f}" data-fx="slide-up" data-dist="30" data-dur="0.1"{fs}>{_html.escape(txt)}</span>')
        o.append('</div>')
    return '\n'.join(o)


CAP_SVG = ('<svg class="cap" viewBox="0 0 220 150"><path d="M110 10 L210 60 L110 110 L10 60Z" fill="#111"/>'
           '<path d="M60 84 V118 Q110 148 160 118 V84" fill="none" stroke="#111" stroke-width="18"/>'
           '<path d="M210 60 V110" stroke="#111" stroke-width="8"/><circle cx="210" cy="118" r="10" fill="#F8DE03"/></svg>')
FORMULA_SVG = ('<svg viewBox="0 0 420 300" xmlns="http://www.w3.org/2000/svg">'
               '<g stroke="#FBFBFB" stroke-width="3" opacity=".8">'
               + ''.join(f'<line x1="60" y1="{60 + i * 60}" x2="210" y2="{40 + j * 44}"/>' for i in range(4) for j in range(6))
               + ''.join(f'<line x1="210" y1="{40 + j * 44}" x2="360" y2="{90 + k * 60}"/>' for j in range(6) for k in range(3))
               + '</g>' + ''.join(f'<circle cx="60" cy="{60 + i * 60}" r="14" fill="#FBFBFB"/>' for i in range(4))
               + ''.join(f'<circle cx="210" cy="{40 + j * 44}" r="14" fill="#F8DE03"/>' for j in range(6))
               + ''.join(f'<circle cx="360" cy="{90 + k * 60}" r="14" fill="#FBFBFB"/>' for k in range(3))
               + '<text x="20" y="290" font-family="Unbounded" font-weight="800" font-size="34" fill="#F8DE03">y = σ(Wx + b)</text></svg>')
def _person(x, y, c):
    return (f'<circle cx="{x}" cy="{y}" r="22" fill="{c}"/>'
            f'<path d="M{x - 40} {y + 100} q0 -56 40 -56 q40 0 40 56 z" fill="{c}"/>')


def people_svg(n_total=10, n_acc=0, acc='#F8DE03', base='#FBFBFB'):
    """10 figures in one row 900x130; the first n_acc are the accent colour (the rest base), the others invisible when
    n_acc > 0 so the overlay sits exactly on the white row."""
    o = ['<svg viewBox="0 0 900 130" xmlns="http://www.w3.org/2000/svg">']
    for i in range(n_total):
        x = 45 + i * 90
        if n_acc and i >= n_acc: continue
        o.append(_person(x, 36, acc if n_acc else base))
    return ''.join(o) + '</svg>'


CLOCK_SVG = ('<svg viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg">'
             '<circle cx="150" cy="130" r="100" fill="none" stroke="#FBFBFB" stroke-width="14"/>'
             + ''.join(f'<line x1="150" y1="40" x2="150" y2="54" stroke="#FBFBFB" stroke-width="8" transform="rotate({a} 150 130)"/>' for a in range(0, 360, 90))
             + '<path d="M150 130 L150 60 A70 70 0 0 1 210 95 Z" fill="#F8DE03" opacity=".9"/>'
             '<line x1="150" y1="130" x2="150" y2="62" stroke="#FBFBFB" stroke-width="12" stroke-linecap="round"/>'
             '<line x1="150" y1="130" x2="205" y2="100" stroke="#FBFBFB" stroke-width="12" stroke-linecap="round"/>'
             '<circle cx="150" cy="130" r="10" fill="#F8DE03"/>'
             '<text x="150" y="290" text-anchor="middle" font-family="Unbounded" font-weight="800" font-size="56" fill="#F8DE03">1–2 ч</text></svg>')
FEED_SVG = ('<svg viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg">'
            '<rect x="70" y="10" width="160" height="280" rx="28" fill="none" stroke="#FBFBFB" stroke-width="12"/>'
            '<rect x="90" y="40" width="120" height="70" rx="12" fill="#FBFBFB" opacity=".35"/>'
            '<rect x="90" y="120" width="120" height="70" rx="12" fill="#F8DE03"/>'
            '<rect x="90" y="200" width="120" height="70" rx="12" fill="#FBFBFB" opacity=".35"/>'
            '<path d="M250 150 l0 -70 m-16 20 l16 -20 l16 20" fill="none" stroke="#F8DE03" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/></svg>')
BUILTIN_IMAGES = {'formula': FORMULA_SVG, 'people10': people_svg(10, 0), 'people8': people_svg(10, 8), 'clock12': CLOCK_SVG, 'feed': FEED_SVG}


def image_html(src, t, t_out, x, y, w, h, base):
    """An illustration / logo: a builtin svg (BUILTIN_IMAGES) or a png/svg/jpg file (path from the spec folder)."""
    if src in BUILTIN_IMAGES:
        inner = BUILTIN_IMAGES[src]
    else:
        p = Path(src) if Path(src).is_absolute() else base / src
        if not p.is_file(): raise SystemExit(f'картинка не найдена: {p}')
        inner = f'<img src="{p.resolve().as_uri()}" alt="">'
    return (f'<div class="img" data-in="{t:.3f}" data-out="{t_out:.3f}" data-fx="slide-up" data-dist="36" data-dur="0.5" data-ofx="fade" data-odur="0.35" '
            f'style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">{inner}</div>')


def meme_tile(m, base):
    icon = m.get('icon', 'dog')
    if icon in ('dog', 'cat'):
        inner = {'dog': '🐶', 'cat': '🐱'}[icon]
    else:
        p = Path(icon) if Path(icon).is_absolute() else base / icon
        if not p.is_file(): raise SystemExit(f'мем не найден: {p}')
        inner = f'<img src="{p.resolve().as_uri()}" alt="">'
    return inner + (CAP_SVG if m.get('cap') else '')


def sticker_html(text, t, x, y, t_end, i, icon=None, base=None):
    """A sticker at (x, y) centre: the text on a white plate, or — `icon` (png/jpg/svg path from the spec folder) —
    an app-icon tile 150 px, no label (the reference: company logos popping one by one around the mic)."""
    rot = (-8, 7, -5, 9)[i % 4]
    if not icon:
        return (f'<div class="stk" data-in="{t:.3f}" data-out="{t_end:.3f}" data-fx="pop" data-dur="0.25" data-ofx="fade" data-odur="0.15" '
                f'style="left:{x - 90}px;top:{y - 36}px;rotate:{rot}deg">{_html.escape(text)}</div>')
    p = Path(icon) if Path(icon).is_absolute() else Path(base or '.') / icon
    if not p.is_file(): raise SystemExit(f'логотип не найден: {p}')
    return (f'<div class="stk app" data-in="{t:.3f}" data-out="{t_end:.3f}" data-fx="pop" data-dur="0.25" data-ofx="fade" data-odur="0.15" '
            f'style="left:{x - 75}px;top:{y - 75}px;rotate:{rot}deg"><img src="{p.resolve().as_uri()}" alt=""></div>')


DEVICE_FRAMES = {   # frame png -> (outer box, screen hole) in png px: MockUPhone iPhone 13 Pro Max (1684x3178, transparent screen)
    'iphone13promax': dict(box=(134, 133, 1414, 2908), screen=(201, 203, 1284, 2776), radius=0.09),
}


def screen_frames_html(video, w, h, t0, t_out):
    """Frames of `video` for the phone screen: <video>.frames_<w>x<h>/%04d.jpg at FPS (cached by mtime), as hidden
    <img> elements with data-fi; the page shows the one for floor((t - t0) * FPS), clamped to the last frame."""
    fdir = video.parent / f'{video.stem}.frames_{w}x{h}'
    stamp = fdir / 'stamp.txt'; want = f'{video.stat().st_mtime_ns} {w} {h} {FPS}'
    if not (stamp.is_file() and stamp.read_text() == want):
        if fdir.is_dir():
            for f in fdir.glob('*.jpg'): f.unlink()
        fdir.mkdir(exist_ok=True)
        run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-vf', f'fps={FPS},scale={w}:{h}:flags=lanczos', '-q:v', '2', str(fdir / '%04d.jpg')])
        stamp.write_text(want)
    frames = sorted(fdir.glob('*.jpg'))
    if not frames: raise SystemExit(f'экран: нет кадров из {video}')
    n_need = fr(t_out - t0) + 1
    imgs = ''.join(f'<img class="sf" data-fi="{i}" src="{f.resolve().as_uri()}" alt="">' for i, f in enumerate(frames[:n_need]))
    return f'<div class="seq" data-t0="{t0:.4f}" data-fps="{FPS}" data-n="{min(len(frames), n_need)}">{imgs}</div>'


def device_html(d, t, t_out, base):
    """A phone mockup: spec section "device" {frame: png path, model: iphone13promax, at_word, out_word?, x, y, w,
    screen?: image/video path shown inside the screen hole, logo?: app tile on a dark screen}. Entry: the phone
    slides up 140 px (0.45 s) while popping from its bottom edge; the screen lights up 0.15 s later."""
    geo = DEVICE_FRAMES[d.get('model', 'iphone13promax')]
    fp = Path(d['frame']) if Path(d['frame']).is_absolute() else base / d['frame']
    if not fp.is_file(): raise SystemExit(f'рамка не найдена: {fp}')
    bx, by, bw, bh = geo['box']; sx, sy, sw, sh = geo['screen']
    w = int(d.get('w', 400)); k = w / bw; h = int(bh * k)
    x, y = int(d.get('x', W - w - 50)), int(d.get('y', 600))
    scr = d.get('screen')
    if scr:
        sp = Path(scr) if Path(scr).is_absolute() else base / scr
        if not sp.is_file(): raise SystemExit(f'экран не найден: {sp}')
        if sp.suffix.lower() in ('.mp4', '.mov', '.webm'):
            # a video is not seekable from seek(t) in a screenshot page: it becomes a jpg sequence (one per output
            # frame, sized to the screen hole, the last frame held till t_out) toggled by seekExtra in the page
            inner = screen_frames_html(sp, int(round(sw * k)), int(round(sh * k)), t + 0.15, t_out)
        else:
            inner = f'<img src="{sp.resolve().as_uri()}" alt="">'
    elif d.get('logo'):
        lp = Path(d['logo']) if Path(d['logo']).is_absolute() else base / d['logo']
        if not lp.is_file(): raise SystemExit(f'логотип не найден: {lp}')
        inner = f'<div class="logo"><img src="{lp.resolve().as_uri()}" alt=""></div>'
    else:
        inner = ''
    r = int(sw * k * geo['radius'])
    return (f'<div class="dev" data-in="{t:.3f}" data-out="{t_out:.3f}" data-fx="slide-up" data-dist="{d.get('dist', 140)}" data-dur="{d.get('dur', 0.45)}" data-ofx="slide-down" data-odur="0.3" '
            f'style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
            f'<div data-in="{t:.3f}" data-fx="pop" data-dur="0.35" style="position:absolute;left:0;top:0;width:100%;height:100%;transform-origin:50% 100%">'
            f'<div class="scr" data-in="{t + 0.15:.3f}" data-fx="fade" data-dur="0.25" style="left:{(sx - bx) * k:.1f}px;top:{(sy - by) * k:.1f}px;'
            f'width:{sw * k:.1f}px;height:{sh * k:.1f}px;border-radius:{r}px">{inner}</div>'
            f'<img class="frm" src="{fp.resolve().as_uri()}" style="left:-{bx * k:.1f}px;top:-{by * k:.1f}px;width:{1684 * k:.1f}px;height:{3178 * k:.1f}px" alt="">'
            f'</div></div>')


def ui_card_html(card, t0, t1, cap_words, fixes, n):
    """Full-screen dark UI mock (opaque): title bar, rows / tiles, a cursor ring; the state (highlighted row, cursor)
    alternates every UI_SUBCUT s = a 'new screen'; one caption word per visible word under the UI."""
    o = [_el('ui', t0, t1)]
    o.append(f'<div class="top"><div class="dot"></div>{_html.escape(card["title"])}</div>')
    lines = card.get('lines') or []
    numeric = all(re.search(r'\d', s) for s in lines) and lines
    k = 0
    for st in range(int((t1 - t0) / UI_SUBCUT) + 1):
        sa = t0 + st * UI_SUBCUT; sb = min(t1, sa + UI_SUBCUT)
        if sb <= sa: continue
        hi = st % max(len(lines), 1)
        o.append(_el('sub', sa, sb, style='position:absolute;left:0;top:150px;width:1080px;height:1500px;'))
        if numeric:
            o.append('<div class="tiles">' + ''.join(
                f'<div class="tile"{" style=\'border-color:" + UI_ACCENT + "\'" if j == hi else ""}><div class="bd">{_html.escape(v)}</div><div class="ft">reel {j + 1}</div></div>'
                for j, v in enumerate(lines)) + '</div>')
        else:
            o.append(f'<div class="search">{_html.escape(card.get("query", "Поиск"))}</div><div class="rows">' + ''.join(
                f'<div class="row{" hi" if j == hi else ""}"><div class="ic"></div>{_html.escape(v)}<span class="val">{(j + 1) * 7 + n * 3}%</span></div>'
                for j, v in enumerate(lines)) + '</div>')
        cx, cy = (300 + (st % 3) * 240, 420 + hi * 176) if not numeric else (330 + (hi % 2) * 480, 520 + (hi // 2) * 440)
        o.append(f'<div class="cursor" style="left:{cx}px;top:{cy}px"></div></div>')
    for i, w in enumerate(cap_words):
        wt1 = cap_words[i + 1]['start'] if i + 1 < len(cap_words) else t1
        o.append(f'<div class="ucap" data-in="{w["start"]:.3f}" data-out="{wt1:.3f}" data-fx="slide-up" data-dist="30" data-dur="0.1" data-ofx="cut" data-odur="0.01">{_html.escape(display(w, fixes))}</div>')
    o.append('</div>')
    return '\n'.join(o)


def scheme_card(sec, sp, pl):
    """Spec section "scheme" -> a scheme.py card in OUTPUT seconds: node pops / pans / words at the spoken words."""
    st = dict(scheme.STYLE); st.update(sp.get('style') or {})
    s_in, s_out = sp['out_in'], sp['out_out']
    nodes, cursor = [], s_in
    offs = [[0, 0], [830, 900], [-440, 960]]
    for i, n in enumerate(sec['scheme']['nodes']):
        nd = dict(id=n['id'], icon=n.get('icon', 'avatar'), offset=n.get('offset') or offs[i % 3] if i else [0, 0])
        if n.get('shape'): nd['shape'] = n['shape']
        for k in ('anim', 'badge'):
            if n.get(k): nd[k] = n[k]
        phrases = []
        if n.get('label_words'):
            ws = [[w, word_time(pl, sec['id'], w, cursor, 'raise')] for w in n['label_words']]
            cursor = ws[-1][1]; phrases.append(dict(words=ws))
        if n.get('label2_words'):
            ws = [[w, word_time(pl, sec['id'], w, cursor, 'raise')] for w in n['label2_words']]
            cursor = ws[-1][1]; phrases.append(dict(words=ws))
        for ph in n.get('phrases') or []:
            ws = [[w, word_time(pl, sec['id'], w, cursor, 'raise')] for w in ph]
            cursor = ws[-1][1]; phrases.append(dict(words=ws))
        if n.get('number'):
            t_num = word_time(pl, sec['id'], n['number']['at_word'], cursor, 'raise'); cursor = t_num
            ph = dict(number=[n['number']['text'], t_num], words=[], line3=[])
            lines = n.get('number_lines') or []
            if lines:
                ph['words'] = [[w, word_time(pl, sec['id'], w, cursor, 'raise')] for w in lines[0]]; cursor = ph['words'][-1][1]
            if len(lines) > 1:
                ph['line3'] = [[w, word_time(pl, sec['id'], w, cursor, 'raise')] for w in lines[1]]; cursor = ph['line3'][-1][1]
            phrases.append(ph)
        for ph in phrases:                       # the word display: as spoken (fixes) and lowercase
            for lst in ('words', 'line3'):
                if ph.get(lst): ph[lst] = [[display(w, sec.get('caption_fix')), t] for w, t in ph[lst]]
        nd['phrases'] = phrases
        if i == 0:
            nd['at'] = s_in + 0.05
        else:
            tw = word_time(pl, sec['id'], n['pan_before_word'], s_in, 'raise') if n.get('pan_before_word') else phrases[0]['words'][0][1]
            nd['pan_at'] = max(s_in, tw - st['pan']); nd['at'] = tw
        # phrases of a node start no earlier than its pop; the first phrase of the node is cut at the next phrase
        for ph in phrases:
            for lst in ('words', 'line3'):
                for item in ph.get(lst) or []:
                    item[1] = max(item[1], nd['at'])
            if ph.get('number'): ph['number'][1] = max(ph['number'][1], nd['at'])
        nodes.append(nd)
    card = dict(id=f'scheme_{sec["id"]}', type='scheme', start=s_in, end=s_out, style=sp.get('style') or {}, nodes=nodes)
    card = scheme.normalize(card)
    bad = scheme.validate(card)
    if bad: raise SystemExit('схема: ' + '; '.join(bad))
    return card


SEQ_JS = """(function(){const prev=window.seekExtra;window.seekExtra=function(t){if(prev)prev(t);
document.querySelectorAll('.seq').forEach(q=>{const t0=+q.dataset.t0,fps=+q.dataset.fps,n=+q.dataset.n;
let i=Math.floor((t-t0)*fps+1e-6);if(i<0)i=0;if(i>n-1)i=n-1;
q.querySelectorAll('img.sf').forEach(im=>im.classList.toggle('on',+im.dataset.fi===i));});};})();"""


def gfx_html(pl, spec, css_href=None, anim_href=None, base=None):
    """The one 1080x1920 page of the reel (anim.js data-in / seek(t) in output seconds). Returns (html, events) where
    events = [(kind, t)] for the SFX: tick / whoosh."""
    base = Path(base or '.')
    css_href = css_href or (SCRIPTS / 'shorts' / 'shorts.css').as_uri()
    anim_href = anim_href or (SCRIPTS / 'graphics' / 'html' / 'anim.js').as_uri()
    o = [f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><link rel="stylesheet" href="{css_href}"><script src="{anim_href}"></script>',
         f'<style>{CSS}</style><script>{SEQ_JS}</script></head><body>']
    events = []
    secs = {s['id']: s for s in pl['sections']}
    for si, sec in enumerate(spec['sections']):
        sp = secs[sec['id']]; s_in, s_out = sp['out_in'], sp['out_out']
        words = [w for w in pl['words'] if w['section'] == sec['id']]
        ang = ANGLES.get(sp['angle'] or '', ANGLES[DEFAULT_ANGLE])
        accents = sec.get('accents') or []
        fixes = sec.get('caption_fix')
        if si: events.append(('whoosh', s_in))
        if sec.get('clip'): continue          # the clip carries its own graphics and sound
        if sec.get('hook_text'):
            t_out = word_time(pl, sec['id'], sec['hook_until_word'], s_in, 'raise') if sec.get('hook_until_word') else s_out
            o.append(_el('rl rhook', s_in, t_out, fx='pop', dur=0.25, ofx='fade', odur=0.12, style=f'top:{ang["hook_y"]}px;'))
            lines = sec['hook_text']
            for li, ln in enumerate(lines):
                acc = ' acc' if li == len(lines) - 1 else ''
                o.append(f'<div class="ln{acc}" data-in="{s_in + li * 0.12:.3f}" data-fx="pop" data-dur="0.22">{_html.escape(ln)}</div>')
            o.append('</div>')
            cap_words = [w for w in words if w['start'] >= t_out - 1e-6]
        else:
            cap_words = words
        if sec.get('footage'):            # full-screen motion graphic instead of the camera (footage.py)
            fg = sec['footage']
            wt = lambda name: word_time(pl, sec['id'], name, s_in, 'none') if name else None
            frag, ev = footage.survey_html(fg, sec, sp, pl, wt, ACCENT, TEXT)
            o.append(frag); events += ev
            o.append(caption_html(cap_words, fixes, accents, sec.get('cap_y', 330), s_out, box=sec.get('cap_box') or (0, W, 'center'),
                                  size=sec.get('cap_size'), cls='ftgcap'))
            continue
        if sec.get('scheme'):
            card = scheme_card(sec, sp, pl)
            o.append(scheme.html_fragment(card, tmap=lambda t: t, icon_base=base))
            if sec.get('pin_title'):             # a term that stays on screen above the scheme once it is spoken
                pt = sec['pin_title']
                t = word_time(pl, sec['id'], pt['at_word'], s_in, 'raise')
                o.append(_el('rl pin', t, s_out, fx='pop', dur=0.3, ofx='fade', odur=0.15, style=f'top:{pt.get("y", 300)}px;'))
                for li, ln in enumerate(pt['lines']):
                    o.append(f'<div class="ln" data-in="{t + li * 0.08:.3f}" data-fx="slide-up" data-dist="40" data-dur="0.2">{_html.escape(ln)}</div>')
                o.append('</div>'); events.append(('tick', t))
            for kind, t in scheme.events(card):
                events.append(('tick' if kind == 'node' else 'whoosh', t))
            for n in card['nodes']:
                for ph in n['phrases']:
                    if ph.get('number'): events.append(('tick', ph['number'][1]))
            continue
        if sec.get('ui_cards'):
            cards = sec['ui_cards']
            ts = [word_time(pl, sec['id'], c['at_word'], s_in, 'raise') for c in cards]
            ts[0] = s_in
            for ci, c in enumerate(cards):
                t0 = ts[ci]; t1 = ts[ci + 1] if ci + 1 < len(cards) else s_out
                cw = [w for w in words if t0 - 1e-6 <= w['start'] < t1]
                o.append(ui_card_html(c, t0, t1, cw, fixes, ci))
                for st in range(int((t1 - t0) / UI_SUBCUT) + 1):
                    if t0 + st * UI_SUBCUT < t1: events.append(('tick', t0 + st * UI_SUBCUT))
            continue
        skip = []
        if sec.get('memes'):
            m_in = min(word_time(pl, sec['id'], m['at_word'], s_in, 'raise') for m in sec['memes'])
            m_out = word_time(pl, sec['id'], sec['memes_out_word'], s_in, 'raise') if sec.get('memes_out_word') else s_out
            skip.append((m_in, m_out))
        if sp['camera']:
            o.append(caption_html(cap_words, fixes, accents, sec.get('cap_y', ang['cap_y']), s_out, box=sec.get('cap_box') or ang.get('cap_box'),
                                  skip=skip, size=sec.get('cap_size')))
        if sec.get('device'):
            d = sec['device']
            t = word_time(pl, sec['id'], d['at_word'], s_in, 'raise')
            t_out = word_time(pl, sec['id'], d['out_word'], t, 'raise') if d.get('out_word') else s_out
            o.append(device_html(d, t, t_out, base)); events.append(('whoosh', t))
        for i, im in enumerate(sec.get('images') or []):
            t = word_time(pl, sec['id'], im['at_word'], s_in, 'raise')
            t_out = word_time(pl, sec['id'], im['out_word'], t, 'raise') if im.get('out_word') else s_out
            slots = ang.get('images') or [(W // 2 - 210, 760)]
            dx, dy = slots[i % len(slots)]
            x, y, w, h = im.get('x', dx), im.get('y', dy), im.get('w', 420), im.get('h', 300)
            o.append(image_html(im['src'], t, t_out, x, y, w, h, base)); events.append(('tick', t))
        last = -9.0
        for i, stk in enumerate(sec.get('stickers') or []):
            t = word_time(pl, sec['id'], stk['at_word'], s_in); x, y = ang['stickers'][i % len(ang['stickers'])]
            if t - last < STICKER_STAGGER: t = last + STICKER_STAGGER          # same word -> stagger 3 frames
            last = t
            x, y = stk.get('x', x), stk.get('y', y)
            o.append(sticker_html(stk.get('text', ''), t, x, y, s_out, i, stk.get('icon'), base)); events.append(('tick', t))
        if sec.get('memes'):
            t_out = word_time(pl, sec['id'], sec['memes_out_word'], s_in, 'raise') if sec.get('memes_out_word') else s_out
            pos = ang.get('memes') or ANGLES['arms']['memes']
            for i, m in enumerate(sec['memes']):
                t = word_time(pl, sec['id'], m['at_word'], s_in, 'raise'); x, y = pos[i % len(pos)]
                o.append(f'<div class="meme" data-in="{t:.3f}" data-out="{t_out:.3f}" data-fx="pop" data-dur="0.25" data-ofx="fade" data-odur="0.2" style="left:{x}px;top:{y}px">'
                         f'<div class="tile">{meme_tile(m, base)}</div><div class="rl txt" style="position:static">{_html.escape(m["text"])}</div></div>')
                events.append(('tick', t))
        if sec.get('cta_word'):
            t = word_time(pl, sec['id'], sec['cta_word'], s_in, 'raise')
            o.append(f'<div class="rl cta" data-in="{t:.3f}" data-fx="pop" data-dur="0.25" style="top:{ang.get("cta_y", 1500)}px">{_html.escape(sec.get("cta_big") or sec["cta_word"].upper())}</div>')
            events.append(('tick', t))
    o.append('</body></html>')
    return '\n'.join(o), sorted(events, key=lambda e: e[1])


# ---------------- media ----------------
def camlut(cube):
    return f"{cam_lut.SRC_VF},lut3d=file='{Path(cube).as_posix().replace(':', chr(92) + ':')}':interp=tetrahedral"


def zoom_keys(pl, spec):
    """Spec sections[].zooms [{at_word, scale, in, hold, out}] -> [(t0, scale, din, hold, dout, fx, fy)] in output s."""
    keys = []
    secs = {s['id']: s for s in pl['sections']}
    for sec in spec['sections']:
        sp = secs[sec['id']]
        fx, fy = ZOOM_ANCHOR.get(sp['angle'] or '', (0.5, 0.35))
        for z in sec.get('zooms') or []:
            t = word_time(pl, sec['id'], z['at_word'], sp['out_in'], 'raise') + float(z.get('offset', 0))   # offset: into the word (stressed syllable)
            keys.append((t, float(z.get('scale', ZOOM_SCALE)), float(z.get('in', ZOOM_IN)), float(z.get('hold', ZOOM_HOLD)),
                         float(z.get('out', ZOOM_OUT)), float(z.get('fx', fx)), float(z.get('fy', fy))))
    return sorted(keys)


def zoom_vf(p, keys):
    """ffmpeg scale/crop filters with a per-frame zoom expression (t = piece-local output s) for the keys inside the piece."""
    ks = [k for k in keys if k[0] < p['out_out'] and k[0] + k[2] + k[3] + k[4] > p['out_in']]
    if not ks: return ''
    ease = lambda e: f'({e})*({e})*(3-2*({e}))'
    z, fx, fy = '1', ks[0][5], ks[0][6]
    for t0, sc, din, hold, dout, _, _ in reversed(ks):
        a = t0 - p['out_in']; b = a + din; c = b + hold; d = c + dout
        pin = ease(f'min(1,max(0,(t-{a:.4f})/{din:.4f}))'); pout = ease(f'min(1,max(0,({d:.4f}-t)/{dout:.4f}))')
        z = f'if(between(t,{a:.4f},{d:.4f}),1+{sc - 1:.4f}*if(lt(t,{b:.4f}),{pin},if(lt(t,{c:.4f}),1,{pout})),{z})'
    return (f",scale=w='trunc({W}*({z})/2)*2':h='trunc({H}*({z})/2)*2':eval=frame:flags=bicubic,"
            f"crop={W}:{H}:x='(iw-{W})*{fx:.3f}':y='(ih-{H})*{fy:.3f}'")


def face_track(src, cam_in, dur_out, speed, step=0.25):
    """Face centre (fractions of the frame) every `step` output s of a camera piece: OpenCV haar on 270x480 frames,
    median-smoothed over 3 samples, gaps filled from the neighbours. Returns [(t_local, fx, fy)]."""
    import cv2, numpy as np, tempfile
    n = int(dur_out / step) + 2
    tmp = Path(tempfile.mkdtemp(prefix='face_'))
    run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{cam_in:.3f}', '-t', f'{dur_out * speed + 0.5:.3f}', '-i', str(src),
         '-vf', f'fps=1/{step * speed:.4f},scale=270:480', '-frames:v', str(n), str(tmp / 'f%03d.png')])
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    pts = []
    for i in range(1, n + 1):
        f = tmp / f'f{i:03d}.png'
        if not f.is_file(): break
        g = cv2.cvtColor(cv2.imread(str(f)), cv2.COLOR_BGR2GRAY)
        faces = casc.detectMultiScale(g, 1.1, 4, minSize=(30, 30))
        if len(faces):
            x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
            pts.append(((x + w / 2) / 270, (y + h / 2) / 480))
        else:
            pts.append(None)
    shutil.rmtree(tmp, ignore_errors=True)
    if not any(pts): raise SystemExit(f'лицо не найдено: {src}')
    mx = float(np.median([q[0] for q in pts if q])); my = float(np.median([q[1] for q in pts if q]))
    pts = [q if q and abs(q[0] - mx) < 0.12 and abs(q[1] - my) < 0.12 else None for q in pts]   # outliers (hand, mic) -> gap
    # fill gaps from the nearest found sample, then median of 3
    last = next(p_ for p_ in pts if p_)
    filled = []
    for p_ in pts:
        if p_: last = p_
        filled.append(last)
    out = []
    for i in range(len(filled)):
        win = filled[max(0, i - 1):i + 2]
        out.append((round(i * step, 3), float(np.median([w[0] for w in win])), float(np.median([w[1] for w in win]))))
    return out


def _lerp_expr(samples, idx):
    """Piecewise-linear ffmpeg expression over t (local s) through [(t, v1, v2)] samples."""
    e = f'{samples[-1][idx]:.4f}'
    for (t0, *v0), (t1, *v1) in reversed(list(zip(samples, samples[1:]))):
        a, b = v0[idx - 1], v1[idx - 1]
        e = f'if(lt(t,{t1:.3f}),{a:.4f}+{b - a:.4f}*(t-{t0:.3f})/{t1 - t0:.3f},{e})'
    return e


def static_keys(pl, spec):
    """Spec section "zoom": {scale, fx, fy} or a list [{at_word?, scale, fx, fy}, ...] (hard cuts between framings
    at the words) -> {section: [(t_out, scale, fx, fy)]}; the first framing starts at the section start."""
    out = {}
    secs = {s['id']: s for s in pl['sections']}
    for sec in spec['sections']:
        z = sec.get('zoom')
        if not z: continue
        zs = z if isinstance(z, list) else [z]
        keys = []
        for i, k in enumerate(zs):
            t = word_time(pl, sec['id'], k['at_word'], secs[sec['id']]['out_in'], 'raise') if k.get('at_word') else secs[sec['id']]['out_in']
            key = (t, float(k.get('scale', 1.4)), float(k.get('fx', 0.5)), float(k.get('fy', 0.5)))
            if k.get('to'):                                   # slow zoom-in a -> to over the section
                key = key + (float(k['to']),)
                out[('dur', sec['id'])] = secs[sec['id']]['out_out'] - secs[sec['id']]['out_in']
                if k.get('track'): out[('track', sec['id'])] = k.get('target', [0.5, 0.45])   # keep the face at this screen point
            keys.append(key)
        out[sec['id']] = sorted(keys)
    return out


def static_vf(p, statics):
    """Piecewise-constant framing of a piece: scale/crop expressions over t (piece-local output s)."""
    keys = statics.get(p['section'])
    if not keys: return ''
    def expr(idx):
        e = f'{keys[0][idx]:.4f}'
        for t, sc, fx, fy in keys[1:]:
            e = f'if(gte(t,{t - p["out_in"]:.4f}),{(sc, fx, fy)[idx - 1]:.4f},{e})'
        return e
    if len(keys) == 1 and len(keys[0]) == 5:         # (t, a, fx, fy, b): slow push-in a -> b over the section
        t0, a, fx, fy, b = keys[0]; dur = max(0.1, statics.get(('dur', p['section']), p['dur']))
        z = f'({a:.4f}+{b - a:.4f}*min(1,max(0,(t+{p["out_in"] - t0:.4f})/{dur:.4f})))'
        tgt = statics.get(('track', p['section']))
        if tgt:                                        # face tracked: the crop follows the face so it stays at tgt
            tr = face_track(statics[('base', 0)] / p['camera'], p['cam_in'], p['dur'], p['speed'])
            ex, ey = _lerp_expr(tr, 1), _lerp_expr(tr, 2)
            return (f",scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame:flags=bicubic,"
                    f"crop={W}:{H}:x='min(max(0,({ex})*iw-{tgt[0] * W:.1f}),iw-{W})':y='min(max(0,({ey})*ih-{tgt[1] * H:.1f}),ih-{H})'")
        return (f",scale=w='trunc({W}*{z}/2)*2':h='trunc({H}*{z}/2)*2':eval=frame:flags=bicubic,"
                f"crop={W}:{H}:x='(iw-{W})*{fx:.3f}':y='(ih-{H})*{fy:.3f}'")
    if len(keys) == 1:
        _, sc, fx, fy = keys[0]
        return f",scale={int(W * sc) // 2 * 2}:{int(H * sc) // 2 * 2}:flags=bicubic,crop={W}:{H}:x='(iw-{W})*{fx:.3f}':y='(ih-{H})*{fy:.3f}'"
    z = expr(1); fx = expr(2); fy = expr(3)
    return (f",scale=w='trunc({W}*({z})/2)*2':h='trunc({H}*({z})/2)*2':eval=frame:flags=bicubic,"
            f"crop={W}:{H}:x='(iw-{W})*({fx})':y='(ih-{H})*({fy})'")


def zoompan_vf(p, statics, zooms):
    """ONE zoompan filter for the piece: zoom = static framing / slow push-in (spec "zoom") x punch-ins (spec "zooms"),
    evaluated per frame (T = on/FPS, piece-local output s) about a fixed anchor (fx, fy). scale+crop with eval=frame
    did NOT work: crop takes the input size once at init, so the anchor was ignored (found 2026-10-28)."""
    T = f'(on/{FPS})'
    keys = (statics or {}).get(p['section']) or []
    zs, fx, fy = '1', None, None
    if keys and len(keys) == 1 and len(keys[0]) == 5:        # slow push-in a -> b over the section
        t0, a, fx, fy, b = keys[0]; dur = max(0.1, statics.get(('dur', p['section']), p['dur']))
        zs = f'({a:.4f}+{b - a:.4f}*min(1,max(0,({T}+{p["out_in"] - t0:.4f})/{dur:.4f})))'
    elif keys:                                               # constant framing(s), hard cuts at the key times
        zs = f'{keys[0][1]:.4f}'; fx, fy = keys[0][2], keys[0][3]
        for t, sc, _, _ in keys[1:]:
            zs = f'if(gte({T},{t - p["out_in"]:.4f}),{sc:.4f},{zs})'
    ks = [k for k in zooms if k[0] < p['out_out'] and k[0] + k[2] + k[3] + k[4] > p['out_in']]
    zp = '1'
    if ks:
        ease = lambda e: f'({e})*({e})*(3-2*({e}))'
        if fx is None: fx, fy = ks[0][5], ks[0][6]
        for t0, sc, din, hold, dout, _, _ in reversed(ks):
            a = t0 - p['out_in']; b = a + din; c = b + hold; d = c + dout
            pin = ease(f'min(1,max(0,({T}-{a:.4f})/{din:.4f}))'); pout = ease(f'min(1,max(0,({d:.4f}-{T})/{dout:.4f}))')
            zp = f'if(between({T},{a:.4f},{d:.4f}),1+{sc - 1:.4f}*if(lt({T},{b:.4f}),{pin},if(lt({T},{c:.4f}),1,{pout})),{zp})'
    if zs == '1' and zp == '1': return ''
    fx = 0.5 if fx is None else fx; fy = 0.5 if fy is None else fy
    # zoompan rounds the crop origin to whole input pixels -> visible jitter on a slow push-in; upscale x4 first
    # (the crop step becomes a quarter pixel of the output), lanczos both ways
    return (f",scale={W * ZP_UP}:{H * ZP_UP}:flags=lanczos,zoompan=z='({zs})*({zp})':x='(iw-iw/zoom)*{fx:.3f}':y='(ih-ih/zoom)*{fy:.3f}'"
            f":d=1:s={W}x{H}:fps={FPS}")


def piece_video(p, base, cube, out, zooms=(), statics=None):
    n = fr(p['dur'])
    if p.get('clip'):
        cmd = ['ffmpeg', '-v', 'error', '-y', '-i', str((statics or {}).get(('spec_base', 0), base) / p['clip']),
               '-vf', f"fps={FPS},scale={W}:{H}:flags=lanczos,setsar=1,format=yuv420p"]
    elif p['camera']:
        src = base / p['camera']
        fe = (statics or {}).get(('fisheye', p['section']))
        pre = f"setpts=PTS/{p['speed']:.6f},{camlut(cube)},{build_render.TOYUV},fps={FPS},scale={W}:{H}:flags=lanczos,setsar=1"
        cmd = ['ffmpeg', '-v', 'error', '-y', '-ss', f"{p['cam_in']:.6f}", '-t', f"{p['dur'] * p['speed'] + 0.5:.6f}", '-i', str(src)]
        if fe:                                   # section "fisheye": peephole (peephole.py) + blurred fill, then the zoom
            mx, my, mm = peephole.build(out.parent, fe.get('alpha', 140), fe.get('rmax', 760))
            fc = (f"[0:v]{pre},split[a][b];[a]scale=1.3*iw:-1,crop={W}:{H},gblur=sigma={fe.get('blur', 30)}[bg];[b][1][2]remap[fe];"
                  f"[3]format=gray,gblur=sigma=4[m];[fe][m]alphamerge[fa];[bg][fa]overlay=format=auto,format=yuv420p{zoompan_vf(p, statics, zooms)}[v]")
            cmd += ['-i', mx, '-i', my, '-i', mm, '-filter_complex', fc, '-map', '[v]']
        else:
            cmd += ['-vf', pre + zoompan_vf(p, statics, zooms)]
    else:
        cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=black:s={W}x{H}:r={FPS}']
    run(cmd + ['-frames:v', str(n), '-r', str(FPS), '-c:v', 'libx264', '-preset', 'fast', '-crf', '14', '-pix_fmt', 'yuv420p', '-g', '30', str(out)])
    got = int(run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', str(out)]).stdout.strip().strip(','))
    if got != n: raise RuntimeError(f'{out.name}: {got} кадров, ждали {n}')


def piece_audio(p, base, out, denoise=False):
    """Raw mic piece at speed 1 (the whole voice is sped once by rubberband after the concat). denoise: section
    "denoise" (far / noisy take, 14/hook: noise floor −46 dB vs −83 on the other takes) -> afftdn."""
    d = p['src_out'] - p['src_in']
    if p.get('clip'):                       # the clip's sound goes into the mix as its own track; the voice lane gets silence
        run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=mono', '-t', f'{d:.6f}', '-c:a', 'pcm_f32le', str(out)])
        return
    dn = (denoise + ',') if isinstance(denoise, str) else ('afftdn=nf=-32:nr=14,' if denoise else '')   # str = custom filter chain (section "voice_fx")
    run(['ffmpeg', '-v', 'error', '-y', '-ss', f"{p['src_in']:.6f}", '-t', f'{d:.6f}', '-i', str(base / p['src']), '-af',
         f'aresample=48000,pan=mono|c0=0.5*c0+0.5*c1,{dn}apad,atrim=end={d:.6f},afade=t=in:d=0.006,afade=t=out:st={max(0, d - 0.008):.6f}:d=0.008',
         '-c:a', 'pcm_f32le', str(out)])


def level_sections(pl, wd):
    """Equalise the voice level between sections (different takes / mic distance: 14/hook was 5–7 LU under the rest):
    every section is measured on voice_src.wav (speed 1) and gained to the loudest one. Writes voice_src.wav in place."""
    secs = {}
    t = 0.0
    for p in pl['pieces']:
        d = p['src_out'] - p['src_in']
        if not p.get('clip'):
            secs.setdefault(p['section'], [t, t]); secs[p['section']][1] = t + d
        t += d
    lv = {}
    for sid, (a, b) in secs.items():
        run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{a:.4f}', '-to', f'{b:.4f}', '-i', str(wd / 'voice_src.wav'), '-c:a', 'pcm_f32le', str(wd / '_sec.wav')])
        lv[sid] = measure(wd / '_sec.wav')['I']
    top = max(lv.values())
    gains = {sid: top - v for sid, v in lv.items()}
    print('  голос по секциям (LUFS): ' + ' '.join(f'{sid} {v:.1f}({gains[sid]:+.1f})' for sid, v in lv.items()))
    if max(gains.values()) < 0.5: return
    af = ','.join(f"volume={gains[sid]:.2f}dB:enable='between(t,{a:.4f},{b:.4f})'" for sid, (a, b) in secs.items() if gains[sid] >= 0.5)
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(wd / 'voice_src.wav'), '-af', af, '-c:a', 'pcm_f32le', str(wd / '_lv.wav')])
    shutil.move(wd / '_lv.wav', wd / 'voice_src.wav')


def build_media(pl, spec, base, wd, cube):
    vdir = base / spec.get('camera_dir', '.'); adir = base / spec.get('voice_dir', '.')
    pdir = wd / 'pieces'
    if pdir.exists(): shutil.rmtree(pdir)
    pdir.mkdir()
    for p in pl['pieces']:
        if p.get('clip'):
            if not (base / p['clip']).is_file(): raise SystemExit(f'нет клипа: {base / p["clip"]}')
            continue
        if p['camera'] and not (vdir / p['camera']).is_file(): raise SystemExit(f'нет камеры: {vdir / p["camera"]}')
        if not (adir / p['src']).is_file(): raise SystemExit(f'нет голоса: {adir / p["src"]}')
    t = time.time()
    with ThreadPoolExecutor(4) as ex:
        dnz = {sec['id']: (sec.get('voice_fx') or bool(sec.get('denoise'))) for sec in spec['sections']}
        list(ex.map(lambda p: piece_audio(p, adir, pdir / f"a{p['idx']:03d}.wav", dnz.get(p['section'])), pl['pieces']))
    build_render.concat_list(wd / 'audio.txt', [pdir / f"a{p['idx']:03d}.wav" for p in pl['pieces']])
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(wd / 'audio.txt'), '-c', 'copy', str(wd / 'voice_src.wav')])
    level_sections(pl, wd)
    T = pl['total']
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(wd / 'voice_src.wav'), '-af',
         f"atempo={pl['speed']:.4f},apad,atrim=end={T:.6f}", '-c:a', 'pcm_f32le', str(wd / 'voice_raw.wav')])
    print(f'  голос: {len(pl["pieces"])} кусков, x{pl["speed"]}, {T:.2f} с ({time.time() - t:.0f} с)')
    t = time.time()
    with ThreadPoolExecutor(3) as ex:
        zooms = zoom_keys(pl, spec)
        statics = static_keys(pl, spec); statics[('base', 0)] = vdir; statics[('spec_base', 0)] = base
        for sec in spec['sections']:
            if sec.get('fisheye'): statics[('fisheye', sec['id'])] = sec['fisheye']
        list(ex.map(lambda p: piece_video(p, vdir, cube, pdir / f"v{p['idx']:03d}.mp4", zooms, statics), pl['pieces']))
    build_render.concat_list(wd / 'video.txt', [pdir / f"v{p['idx']:03d}.mp4" for p in pl['pieces']])
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(wd / 'video.txt'), '-c', 'copy', str(wd / 'video.mp4')])
    print(f'  видео: {fr(T)} кадров ({time.time() - t:.0f} с)')


def mix(pl, spec, base, wd, events):
    T = pl['total']
    prof = build_render.profile(spec.get('audio_profile', 'ref'))
    comp = spec.get('voice_comp', VOICE_COMP)                # the density first, the EQ match on the compressed voice
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(wd / 'voice_raw.wav'), '-af', comp or 'anull', '-c:a', 'pcm_f32le', str(wd / 'voice_comp.wav')])
    fx = voice_ref.match_fx(wd / 'voice_comp.wav', report=wd / 'voice_match.json')
    info = voice_ref.match_fx.last
    print('  EQ по спектру (dB): ' + ' '.join(f"{k}:{g:+.1f}" for k, g in info['gains'].items()) + ('  в допуске' if info['ok'] else '  ВНЕ допуска ±2 dB'))
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(wd / 'voice_comp.wav'), '-af', fx, str(wd / 'voice.wav')])
    v = measure(wd / 'voice.wav')['I']; gv = prof['voice_lufs'] - v
    ins = ['-i', str(wd / 'voice.wav')]
    parts = [f"[0:a]volume={gv:.2f}dB,apad=whole_dur={T:.3f}[v]"]; labels = ['[v]']
    secs = {s['id']: s for s in pl['sections']}
    m_in = spec.get('music_in', 'after_hook')
    if m_in == 'after_hook':
        m_in = secs[spec['sections'][0]['id']]['out_out']
    elif isinstance(m_in, str) and m_in.startswith('after:'):     # "after:<section id>"
        m_in = secs[m_in[6:]]['out_out']
    m_in = min(max(float(m_in), 0.0), max(T - 2.0, 0.0))
    music = base / spec['music'] if spec.get('music') else None
    gm = None
    if music:
        if not music.is_file(): raise SystemExit(f'музыка не найдена: {music}')
        ins += ['-stream_loop', '-1', '-i', str(music)]; k = ins.count('-i') - 1
        rel = float(spec.get('music_rel_lu', MUSIC_REL))
        gm = prof['voice_lufs'] + rel - measure(music)['I']
        delay = f",adelay={int(round(m_in * 1000))}:all=1" if m_in > 0 else ''
        parts.append(f"[{k}:a]aformat=channel_layouts=stereo,atrim=end={T - m_in:.3f},{MUSIC_HS},volume={gm:.2f}dB,afade=t=in:d={MUSIC_FADE_IN},"
                     f"afade=t=out:st={T - m_in - MUSIC_FADE_OUT:.3f}:d={MUSIC_FADE_OUT}{delay}[m]"); labels.append('[m]')
    for i, mx in enumerate(spec.get('music_extra') or []):   # a second music bed over one section: {file, section, rel_lu, fade_in, fade_out, tail}
        mf = base / mx['file']
        if not mf.is_file(): raise SystemExit(f'music_extra не найдена: {mf}')
        s_ = secs[mx['section']]; a0, a1 = s_['out_in'], min(T, s_['out_out'] + float(mx.get('tail', 0.0)))
        fi, fo = float(mx.get('fade_in', 0.05)), float(mx.get('fade_out', 0.25))
        ins += ['-stream_loop', '-1', '-ss', f"{float(mx.get('in', 0.0)):.3f}", '-i', str(mf)]; k = ins.count('-i') - 1   # "in" = start offset in the track
        g = prof['voice_lufs'] + float(mx.get('rel_lu', MUSIC_REL)) - measure(mf)['I']
        parts.append(f"[{k}:a]aformat=channel_layouts=stereo:sample_rates=48000,atrim=end={a1 - a0:.3f},volume={g:.2f}dB,afade=t=in:d={fi},"
                     f"afade=t=out:st={a1 - a0 - fo:.3f}:d={fo},adelay={int(round(a0 * 1000))}:all=1[mx{i}]"); labels.append(f'[mx{i}]')
        print(f"  music_extra {mx['file']} на {mx['section']} {a0:.2f}–{a1:.2f}: {g:+.1f} dB")
    for p in pl['pieces']:                 # ready clips: their own sound at the voice level (section "clip_lu" = offset in LU)
        if not p.get('clip'): continue
        sec = next(s for s in spec['sections'] if s['id'] == p['section'])
        cf = base / p['clip']
        ins += ['-i', str(cf)]; k = ins.count('-i') - 1
        gc = prof['voice_lufs'] + float(sec.get('clip_lu', 0)) - measure(cf)['I']
        t0 = int(round(p['out_in'] * 1000))
        parts.append(f"[{k}:a]aformat=channel_layouts=stereo:sample_rates=48000,atrim=end={p['dur']:.3f},volume={gc:.2f}dB,adelay={t0}|{t0}[clip{p['idx']}]")
        labels.append(f"[clip{p['idx']}]")
        print(f"  клип {p['clip']}: {gc:+.1f} dB")
    sfx = spec.get('sfx') or {}
    n_hits = {}
    for kind in ('tick', 'whoosh'):
        f = sfx.get(kind)
        hits = [t for k_, t in events if k_ == kind and 0 <= t < T - 0.05]
        if not f or not hits:
            if hits: print(f'  ВНИМАНИЕ: sfx.{kind} не задан — {len(hits)} событий без звука')
            continue
        f = base / f
        if not f.is_file(): raise SystemExit(f'SFX не найден: {f}')
        ins += ['-i', str(f)]; k = ins.count('-i') - 1
        g = SFX_PEAK - measure(f)['TP']
        for n, t in enumerate(hits):
            parts.append(f"[{k}:a]aformat=channel_layouts=stereo,volume={g:.2f}dB,adelay={int(t * 1000)}|{int(t * 1000)}[{kind[0]}{n}]"); labels.append(f'[{kind[0]}{n}]')
        n_hits[kind] = len(hits)
    fc = ';'.join(parts) + ';' + ''.join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first[a]"
    run(['ffmpeg', '-v', 'error', '-y', *ins, '-filter_complex', fc, '-map', '[a]', '-t', f'{T:.3f}', '-c:a', 'pcm_f32le', str(wd / 'mix_pre.wav')])
    loud = build_render.final_loop(wd / 'mix_pre.wav', wd / 'mix_final.m4a', prof=prof)
    return dict(voice_lufs_pre=round(v, 2), gain_voice=round(gv, 2), gain_music=None if gm is None else round(gm, 2), music_in=m_in,
                sfx_hits=n_hits, voice_match=info['gains'], voice_match_ok=info['ok'], loop=loud, profile=prof['name'])


def mux(wd, final, gfx):
    ins = ['-i', str(wd / 'video.mp4')]
    fc = '[0:v]null[vo]'
    if gfx:
        ins += ['-i', str(gfx)]; fc = '[0:v][1:v]overlay=format=auto:shortest=1[vo]'
    ins += ['-i', str(wd / 'mix_final.m4a')]
    run(['ffmpeg', '-v', 'error', '-y', *ins, '-filter_complex', fc, '-map', '[vo]', '-map', f'{len(ins) // 2 - 1}:a', '-c:v', 'libx264', '-preset', 'medium',
         '-crf', '18', '-pix_fmt', 'yuv420p', '-r', str(FPS), '-c:a', 'copy', '-movflags', '+faststart', str(final)])


# ---------------- main ----------------
def load_words(base, spec):
    p = base / spec.get('words', 'transcript/words.json')
    if not p.is_file(): raise SystemExit(f'нет транскрипта: {p} (whisper word times per file)')
    return json.loads(p.read_text(encoding='utf-8'))


def apply_palette(spec):
    """Spec "palette": {accent, text, cap_font, cap_size, cap_color, cap_upper} -> module colours / caption style
    (writelo: accent #D4683F, text #EDE8DE, captions Oswald 700 uppercase 92 px orange). Call before gfx_html."""
    global ACCENT, TEXT, CSS
    pal = spec.get('palette')
    if not pal: return
    acc, txt = pal.get('accent', ACCENT), pal.get('text', TEXT)
    CSS = CSS.replace(ACCENT, acc).replace(TEXT, txt)
    scheme.STYLE['accent'] = acc
    for k in list(BUILTIN_IMAGES): BUILTIN_IMAGES[k] = BUILTIN_IMAGES[k].replace(ACCENT, acc).replace('#FBFBFB', txt)
    ACCENT, TEXT = acc, txt
    if pal.get('cap_font') or pal.get('cap_size') or pal.get('cap_color'):
        f = pal.get('cap_font', 'Unbounded'); sz = int(pal.get('cap_size', 46)); col = pal.get('cap_color', txt)
        up = 'text-transform:uppercase;' if pal.get('cap_upper', True) else ''
        CSS += f"""
.capl .w {{ font-family:'{f}', sans-serif; font-weight:700; font-size:{sz}px; line-height:1.05; letter-spacing:.01em; {up} color:{col};
  text-shadow:2px 0 0 #141414, -2px 0 0 #141414, 0 2px 0 #141414, 0 -2px 0 #141414, 0 5px 0 #141414, 0 10px 26px rgba(0,0,0,.65); }}
.capl .w.acc {{ color:{txt}; font-size:{int(sz * 1.12)}px; text-shadow:2px 0 0 #141414, -2px 0 0 #141414, 0 2px 0 #141414, 0 -2px 0 #141414, 0 5px 0 #141414, 0 0 24px {acc}CC, 0 10px 26px rgba(0,0,0,.65); }}
.capl.one .w {{ font-size:{int(sz * 1.08)}px; }}
.capl {{ gap:22px; }}
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description='reel from raw sources + a script spec (no CapCut)')
    ap.add_argument('spec')
    ap.add_argument('--plan', action='store_true', help='plan + wordmap + gfx.html only')
    ap.add_argument('--gfx-only', action='store_true', help='re-render the graphics and remux (video.mp4 / mix_final.m4a kept)')
    ap.add_argument('--skip-gfx', action='store_true', help='reuse work gfx.mov')
    ap.add_argument('--no-validate', action='store_true')
    a = ap.parse_args(argv)
    sp = Path(a.spec).resolve(); base = sp.parent
    spec = json.loads(sp.read_text(encoding='utf-8'))
    apply_palette(spec)
    wd = base / 'work' / spec['id']; wd.mkdir(parents=True, exist_ok=True)
    pl = plan(spec, load_words(base, spec), voice_dir=base / spec.get('voice_dir', '.'), base=base)
    for sec in spec['sections']:
        if sec.get('v_snapped'): print(f"  {sec['id']}: диапазоны по энергии {sec['v_snapped']}")
    (wd / 'plan.json').write_text(json.dumps(pl, ensure_ascii=False, indent=1), encoding='utf-8')
    (wd / 'wordmap.json').write_text(json.dumps(dict(speed=pl['speed'], total=pl['total'], pieces=pl['pieces'], words=pl['words']), ensure_ascii=False, indent=1), encoding='utf-8')
    html, events = gfx_html(pl, spec, base=base)
    (wd / 'gfx.html').write_text(html, encoding='utf-8')
    (wd / 'events.json').write_text(json.dumps(events, ensure_ascii=False), encoding='utf-8')
    print(f"план: {len(pl['pieces'])} кусков, {len(pl['words'])} слов, {pl['total']:.2f} с; SFX {len(events)}; {wd / 'gfx.html'}")
    for s in pl['sections']:
        print(f"  {s['id']:8} {s['out_in']:6.2f}–{s['out_out']:6.2f}  {s['camera'] or '—':14} {s['angle'] or ''}  {s['n_words']} слов")
    if a.plan: return
    cube = cam_lut.REF_CUBE
    if not a.gfx_only:
        build_media(pl, spec, base, wd, cube)
    if not a.skip_gfx:
        build_render.render(wd / 'gfx.html', fr(pl['total']), wd / 'gfx.mov')
    rep = None
    if not a.gfx_only or not (wd / 'mix_final.m4a').is_file():
        rep = mix(pl, spec, base, wd, events)
        (wd / 'report.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
    final = wd / 'final.mp4'
    mux(wd, final, wd / 'gfx.mov')
    fin = measure(final)
    out = base / spec['out']; out.parent.mkdir(parents=True, exist_ok=True); shutil.copy(final, out)
    print(f"готово: {out}  {pl['total']:.2f} с  I {fin['I']} LUFS  TP {fin['TP']}")
    if not a.no_validate:
        import validate_reel
        validate_reel.run_all(spec, pl, base, wd, out, rep)


if __name__ == '__main__':
    main()
