"""Shorts / Reels / TikTok from the long video: words of the stage3 timeline -> pieces of the SOURCES -> vertical
1080x1920 (build_render.py: camera through cam.cube, ffmpeg, graphics HTML -> Playwright -> MOV, final mix).

    python -X utf8 scripts/shorts/build.py <id> [<id> ...] [--config config.json] [--plan] [--no-render]
                                           [--reels | --tiktok]
  --plan        plan only (pieces, words, captions) -> work/<id>/plan.json, no ffmpeg
  --no-render   do not re-render the graphics (reuse work/<id>/gfx*.mov) — never after a plan change
  --reels       Instagram Reels: spec block "reels" (own ranges), 4-s CTA card «Напиши «СЛОВО» в комментариях»,
                <= 30 s with the card -> out/reels/<id>_<slug>.mp4
  --tiktok      TikTok teaser: spec block "tiktok", dynamic mode, 2.5-s end card «Полное видео на YouTube»,
                <= 15 s with the card -> out/tiktok/<id>_<slug>.mp4
Spec: <work_dir>/stage12_shorts/specs/<id>.json (format: references/shorts.md, sample assets/examples/specs/example.json).
Times in the spec = stage3 timeline (stage3/transcript_timeline.json, timeline_map.json). Output: <work_dir>/
stage12_shorts/out/<id>_<slug>.mp4, frames work/<id>/check/*.png, loudness work/<id>/report.json.
One short -> the user's OK -> only then the batch.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import common  # noqa: E402
import rmap  # noqa: E402
import build_render as R  # noqa: E402
from build_render import CAM_H, fr, q, strip  # noqa: E402

MAXGAP = 0.30          # a pause longer than this is cut
GAP_KEEP_BEFORE, GAP_KEEP_AFTER = 0.08, 0.12
FILLERS = {'так', 'значит', 'короче', 'соответственно', 'ну', 'вот', 'блин'}
END_DUR = {'shorts': 2.5, 'reels': 4.0, 'tiktok': 2.5}      # end card / CTA, s
LIMIT = {'shorts': 60.0, 'reels': 30.0, 'tiktok': 15.0}      # whole video incl. the card, s
HOOK_DUR = 2.4
DYN_GAP, DYN_HOOK = 0.12, 1.5   # --tiktok dynamic mode: pauses 0.12 s, hook 1.5 s, punch-in x1.18 on every 2nd cut
DYN_MAXPIECE = 2.6              # dynamic mode: a longer piece is split on a word boundary (punch-in every ~2 s)
HOOK_TOP = {'stack': CAM_H + 50, 'full': 1120, 'scfull': 380}   # text never on the face: stack -> on the screencast
CAP_TOP = {'stack': 790, 'full': 1500, 'scfull': 1560}
CAP_MAXCH = 18
# approved shorts timings (entry 0.22 s, exit 0.25 s); the shared anim.js defaults differ (0.25 / 0.2)
ANIM = ' data-dur="0.22" data-odur="0.25"'
VIDEO_ROLES = ('camera', 'screencast')


@dataclass
class Ctx:
    cfg: common.Config
    mode: str                      # shorts | reels | tiktok
    words: list                    # stage3 words (timeline s)
    main: list                     # segments of the main video track (screencast / camera on full screen)
    cams: list                     # camera segments of the other video tracks (circle, F), in track order
    mic: list                      # voice (mic) segments
    frows: list                    # layout/layout.json F rows [(a, b)] s
    edges: list                    # sorted segment / layout boundaries, s
    master: rmap.Master
    dyn: bool = False
    end_dur: float = 2.5
    speed: float = R.SPEED
    fix: dict = field(default_factory=dict)
    cam_cx: object = field(default_factory=dict)
    missing: set = field(default_factory=set)
    dropped: list = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.cfg.work_dir / "stage12_shorts"


def load(config_path=None, mode: str = 'shorts') -> Ctx:
    cfg = common.load_config(config_path)
    d = cfg.work_dir / "stage3"
    tm = rmap.load_json(d / "timeline_map.json", "карта таймлайна")
    tt = rmap.load_json(d / "transcript_timeline.json", "транскрипт в времени таймлайна")

    def role(s):
        return s.get("role") or (common.source_role(cfg, s["file"]) if s.get("file") else None)
    vids = [t for t in tm["tracks"] if t.get("type") == "video"]
    main = [dict(s, role=role(s)) for s in (vids[0]["segments"] if vids else []) if role(s) in VIDEO_ROLES]
    cams = [dict(s, role="camera") for t in vids[1:] for s in t["segments"] if role(s) == "camera"]
    mic = [dict(s, role="voice") for t in tm["tracks"] if t.get("type") == "audio" for s in t["segments"]
           if role(s) == "voice"]
    rows = common.read_layout(cfg)
    frows = [(r["start"], r["end"]) for r in rows if r.get("layout") == "F"]
    edges = sorted({e for segs in (main, cams, mic) for s in segs for e in (s["timeline_in_us"] / 1e6, s["timeline_out_us"] / 1e6)}
                   | {e for r in rows for e in (r["start"], r["end"])})
    return Ctx(cfg=cfg, mode=mode, words=[w for s in tt["segments"] for w in s["words"]], main=main, cams=cams, mic=mic,
               frows=frows, edges=edges, master=rmap.Master(cfg), dyn=mode == 'tiktok', end_dur=END_DUR[mode])


def mode_spec(ctx: Ctx, spec: dict) -> dict:
    """reels / tiktok: the spec with its own block on top (ranges, cards, code_word …)."""
    return {**spec, **spec[ctx.mode]} if ctx.mode in ('reels', 'tiktok') and ctx.mode in spec else spec


def hook_dur(ctx): return DYN_HOOK if ctx.dyn else HOOK_DUR


def seg_at(segs, t):
    us = int(round(t * 1e6))
    for s in segs:
        if s['timeline_in_us'] <= us < s['timeline_out_us']: return s
    return None


def in_f(ctx, t): return any(a <= t < b for a, b in ctx.frows)


def fix_word(ctx, ww): return ctx.fix.get(ww.strip(',.!?'), ww.strip(',.!?')) + re.sub(r'^[^,.!?]*', '', ww)


# ---------------- plan ----------------
def plan(ctx: Ctx, spec: dict) -> dict:
    ctx.fix = dict(spec.get('fix', {})); ctx.cam_cx = spec.get('cam_cx', {})
    ctx.speed = spec.get('speed', R.SPEED)
    SPEED = ctx.speed
    kw = [k.lower() for k in spec.get('keywords', [])]
    drop_fill = spec.get('fillers', True)
    pieces = []      # {'tl0','tl1','s0','dur', 'sc','cam','aud'}
    words_out = []   # words in short time
    cur = 0.0
    for rng in spec['ranges']:
        t0, t1 = rng['tl'][0], rng['tl'][1]; cur0 = cur
        # lead: the word began before tl[0], the sound is cut exactly at tl[0] (a cough before the word)
        ws = [w for w in ctx.words if w['start'] >= t0 - rng.get('lead', 0.05) and w['end'] <= t1 + 0.05]
        if not ws: raise SystemExit(f'нет слов в {t0}-{t1}')
        keep = []
        for i, w in enumerate(ws):
            prev_end = re.search(r'[.!?,]$', ws[i - 1]['word']) if i else True
            if drop_fill and strip(w['word']) in FILLERS and (w['end'] - w['start']) < 0.6 and re.search(r'[,.]$', w['word']) and prev_end:
                continue
            if not ctx.master.find(w) and not any(abs(w['start'] - t) < 0.05 for t in spec.get('force_tl', [])):
                ctx.dropped.append(w['word']); continue    # cut in the master (force_tl: keep it)
            keep.append(w)
        if not keep: raise SystemExit(f'в {t0}-{t1} не осталось слов (все вырезаны в мастере / паразиты)')
        # intervals
        ivs = []
        s, e = max(t0, keep[0]['start'] - GAP_KEEP_BEFORE), keep[0]['end']
        for w in keep[1:]:
            if w['start'] - e <= (DYN_GAP if ctx.dyn else MAXGAP): e = max(e, w['end'])
            else:
                ivs.append([s, e + GAP_KEEP_AFTER]); s, e = w['start'] - GAP_KEEP_BEFORE, w['end']
        ivs.append([s, min(t1 + 0.05, e + rng.get('tail', GAP_KEEP_AFTER))])
        # cut on the boundaries of the main track, camera, mic segments and layout rows
        for a, b in ivs:
            cuts = sorted({a, b} | set(ctx.edges[bisect.bisect_right(ctx.edges, a):bisect.bisect_left(ctx.edges, b)]))
            # drop inner boundaries that give a piece shorter than 2 frames (the word would fall out); a segment
            # boundary is a change of source and must stay: move the neighbouring interval edge instead
            clean = [cuts[0]]
            for c in cuts[1:]:
                if (c - clean[-1]) / SPEED < 2 / R.FPS:
                    if len(clean) == 1: clean[0] = c; continue          # interval start -> to the segment boundary
                    if c == cuts[-1]: clean.pop()                       # interval end -> to the previous boundary
                    else: clean[-1] = c                                 # (rare) two boundaries in a row
                clean.append(c)
            cuts = clean
            for x, y in zip(cuts, cuts[1:]):
                dur = q((y - x) / SPEED)
                if dur < 2 / R.FPS: continue
                sc = seg_at(ctx.main, x + 0.001); cam = seg_at(ctx.cams, x + 0.001); mic = seg_at(ctx.mic, x + 0.001)

                def src(sg):
                    if not sg: return None
                    if not Path(sg['file']).exists():
                        ctx.missing.add(sg['file']); return None
                    return dict(file=sg['file'], start=sg['source_in_us'] / 1e6 + (x - sg['timeline_in_us'] / 1e6) * sg['speed'],
                                speed=sg['speed'], name=sg.get('name') or Path(sg['file']).name)
                p = dict(tl0=x, tl1=y, s0=cur, dur=dur, src_dur=y - x, zoom=rng.get('zoom'), layout=rng.get('layout', 'stack'))
                if rng.get('keys'):   # animated screencast zoom: [{tl, zoom:[x,y,w,h], ease}] — where the cursor points
                    p['keys'] = [dict(t=(k['tl'] - x) / SPEED, zoom=k['zoom'], ease=k.get('ease', 0.6)) for k in rng['keys']]
                mutes = [[(max(a_, x) - x) / SPEED, (min(b_, y) - x) / SPEED] for a_, b_ in spec.get('mute', []) if a_ < y and b_ > x]
                if mutes: p['mute'] = mutes      # silence on a word without a cut (a slip)
                scs = src(sc)
                if scs and sc['role'] == 'camera':      # camera on full screen on the main track
                    p['cam'] = scs; p['sc'] = None; p['layout'] = 'full'
                else:
                    p['sc'] = scs; p['cam'] = src(cam)
                    if not p['cam']: p['layout'] = 'scfull'
                    elif in_f(ctx, x + 0.001): p['layout'] = 'full'; p['sc'] = None    # layout F of the project
                if rng.get('layout') == 'full' and p.get('cam'): p['layout'] = 'full'; p['sc'] = None
                if rng.get('sc'):     # the screencast replaced by another file (runs on continuously in short time)
                    o = rng['sc']; p['sc'] = dict(file=o['file'], start=o['start'] + (cur - cur0) * o.get('speed', 1.0), speed=o.get('speed', 1.0), name=Path(o['file']).name)
                    if p['layout'] == 'full': p['layout'] = 'stack' if p.get('cam') else 'scfull'
                ms = src(mic)
                if ms: p['aud'] = dict(ms, gain=mic['volume'])
                # else the screencast's own sound; the camera's sound is never used (rules.md «Звук»)
                else: p['aud'] = dict(scs, gain=1.0) if scs and sc['role'] == 'screencast' else None
                pieces.append(p)
                # 1st piece of the range: the word may have begun before tl[0] (lead)
                lo = x - (rng.get('lead', 0.05) if not any(pp['tl0'] >= t0 for pp in pieces[:-1]) else 0.001)
                for w in keep:
                    if lo <= w['start'] < y:
                        if any(a_ - 0.02 <= w['start'] < b_ for a_, b_ in spec.get('mute', [])): continue   # muted -> no caption
                        ww = w['word']
                        if words_out and words_out[-1]['word'] == ww and abs(words_out[-1]['start'] - (cur + (w['start'] - x) / SPEED)) < 0.08: continue
                        if ww[:1] in ',.-' and words_out:     # «2» + «,5» -> «2,5»
                            words_out[-1]['word'] += ww; words_out[-1]['end'] = cur + (min(w['end'], y) - x) / SPEED; continue
                        words_out.append(dict(word=fix_word(ctx, ww), start=cur + max(0, w['start'] - x) / SPEED, end=cur + (min(w['end'], y) - x) / SPEED))
                cur += dur
                for ext in spec.get('extend_src', []):            # pull the piece on from the source (cut in the edit)
                    if abs(ext['after_tl'] - y) < 0.05 and p['aud']:
                        cur += extend_piece(ctx, p, ext['to'], cur, pieces, words_out)
    total = cur
    caps = captions(words_out, kw)
    hd = spec.get('hook', {}).get('dur', hook_dur(ctx)) + 0.25 if spec.get('hook') else 0
    caps = [c for c in caps if c['t_out'] > hd + 0.3]
    for c in caps: c['t_in'] = max(c['t_in'], hd)
    if ctx.dyn:
        pieces = split_long(ctx, pieces, words_out)
        for i, p in enumerate(pieces): p['punch'] = bool(i % 2) and p['layout'] != 'full' and not p.get('keys')
    return dict(id=spec['id'], total=total, total_with_end=total + ctx.end_dur, pieces=pieces, words=words_out, captions=caps)


def split_long(ctx, pieces, words_out):
    """Split pieces longer than DYN_MAXPIECE at the word start nearest the middle (stack / screencast without keys/mute;
    the source runs on, the sound is untouched)."""
    out = []
    for p in pieces:
        parts = [p]
        while True:
            q_ = parts[-1]
            if q_['dur'] <= DYN_MAXPIECE or q_['layout'] == 'full' or q_.get('keys') or q_.get('mute'): break
            mid = q_['s0'] + q_['dur'] / 2
            cands = [w['start'] for w in words_out if q_['s0'] + 0.8 < w['start'] < q_['s0'] + q_['dur'] - 0.8]
            if not cands: break
            at = q(min(cands, key=lambda t: abs(t - mid)) - q_['s0'])
            if at < 0.5 or q_['dur'] - at < 0.5: break
            a = dict(q_); b = dict(q_)
            a['dur'] = at; a['src_dur'] = at * ctx.speed; a['tl1'] = q_['tl0'] + at * ctx.speed
            b['s0'] = q_['s0'] + at; b['dur'] = q_['dur'] - at; b['src_dur'] = q_['src_dur'] - at * ctx.speed; b['tl0'] = a['tl1']
            for k in ('sc', 'cam', 'aud'):
                if q_.get(k): b[k] = dict(q_[k], start=q_[k]['start'] + at * ctx.speed * q_[k]['speed'])
            parts[-1] = a; parts.append(b)
        out.extend(parts)
    return out


def extend_piece(ctx, p, to, cur, pieces, words_out):
    """Continue the sources of piece p (same file, no cut) to file time `to` (by the voice). Words: the master
    transcript by file_start."""
    a = p['aud']; e0 = a['start'] + p['src_dur'] * a['speed']
    src_dur = (to - e0) / a['speed']; dur = q(src_dur / ctx.speed)

    def shift(sx):
        return dict(sx, start=sx['start'] + p['src_dur'] * sx['speed']) if sx else None
    np_ = dict(p, tl0=p['tl1'], tl1=p['tl1'], s0=cur, dur=dur, src_dur=src_dur, sc=shift(p.get('sc')), cam=shift(p.get('cam')), aud=dict(shift(a), gain=a['gain']))
    # keys / mute are relative to the piece start: shift by the original piece, mutes clipped to the new piece
    if p.get('keys'): np_['keys'] = [dict(k, t=k['t'] - p['dur']) for k in p['keys']]
    np_.pop('mute', None)
    mutes = [[max(m0 - p['dur'], 0.0), min(m1 - p['dur'], dur)] for m0, m1 in p.get('mute', []) if m1 - p['dur'] > 0 and m0 - p['dur'] < dur]
    if mutes: np_['mute'] = mutes
    pieces.append(np_)
    name = Path(a['file']).name
    for w in ctx.master.CW:
        if w.get('file') == name and e0 - 0.05 <= w['file_start'] < to:
            st = cur + max(0, w['file_start'] - e0) / a['speed'] / ctx.speed
            words_out.append(dict(word=fix_word(ctx, w['word']), start=st, end=st + (w['end'] - w['start']) / ctx.speed))
    return dur


def captions(words, kw):
    groups, g = [], []

    def flush():
        if g: groups.append(list(g)); g.clear()
    for w in words:
        if g and len(' '.join(x['word'] for x in g)) + 1 + len(w['word']) > CAP_MAXCH: flush()
        g.append(w)
        if re.search(r'[.!?,;:]$', w['word']) or len(g) >= 3: flush()
    flush()
    caps = []
    for i, grp in enumerate(groups):
        t_in = grp[0]['start']
        t_out = groups[i + 1][0]['start'] if i + 1 < len(groups) else grp[-1]['end'] + 0.4
        if t_out - grp[-1]['end'] > 0.6: t_out = grp[-1]['end'] + 0.35
        toks = []
        for x in grp:
            w = x['word']; s = strip(w)
            orange = bool(re.search(r'[\d×%]', s)) or any(k in s for k in kw)     # digits always + spec keywords
            toks.append((w, orange))
        caps.append(dict(t_in=round(t_in, 3), t_out=round(t_out, 3), toks=toks))
    return caps


def check_duration(ctx, pl):
    """Hard platform limits incl. the end card: Shorts 60, Reels 30, TikTok 15 s."""
    lim = LIMIT[ctx.mode]
    if pl['total_with_end'] > lim + 1e-6:
        raise SystemExit(f"{ctx.mode}: {pl['total_with_end']:.2f} с с концовкой > {lim:.0f} с — сократить диапазоны "
                         f"({'reels' if ctx.mode == 'reels' else 'tiktok' if ctx.mode == 'tiktok' else 'ranges'} в спеке)")


# ---------------- graphics HTML ----------------
def esc(s): return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def piece_at(pl, t):
    for p in pl['pieces']:
        if p['s0'] - 0.001 <= t < p['s0'] + p['dur']: return p
    return pl['pieces'][-1]


def html_hook(ctx, spec, pl):
    hk = spec.get('hook')
    if not hk: return ''
    tout = hk.get('dur', hook_dur(ctx))
    parts = []
    if hk.get('kicker'): parts.append(f'<span class="kicker" data-in="0.1" data-out="{tout}" data-fx="slide-left" data-dist="40"{ANIM}>{esc(hk["kicker"])}</span>')
    for i, line in enumerate(hk['lines']):
        parts.append(f'<span class="plate" data-in="{0.12 + i * 0.1:.2f}" data-out="{tout + i * 0.03:.2f}" data-fx="pop" data-ofx="slide-left" data-dist="40"{ANIM}>{line}</span>')
    top = HOOK_TOP[piece_at(pl, 0.5)['layout']]       # rule: text never on the face
    return f'<div class="hook" style="top:{top}px">' + ''.join(parts) + '</div>'


def html_caps(ctx, pl):
    out = []
    for c in pl['captions']:
        top = CAP_TOP[piece_at(pl, c['t_in'])['layout']]
        txt = ' '.join(f'<span class="or">{esc(w)}</span>' if o else esc(w) for w, o in c['toks'])
        fx, dur = ('pop', 0.1) if ctx.dyn else ('cut', 0.01)
        out.append(f'<div class="cap{" dyn" if ctx.dyn else ""}" style="top:{top}px"><span class="plate" data-in="{c["t_in"]}" data-out="{c["t_out"]}" data-fx="{fx}" data-dist="20" data-dur="{dur}" data-ofx="cut" data-odur="0.01">{txt}</span></div>')
    return '\n'.join(out)


def tl2s(ctx, pl, t):
    for p in pl['pieces']:
        if p['tl0'] - 0.001 <= t <= p['tl1'] + 0.001: return p['s0'] + (t - p['tl0']) / ctx.speed
    # between pieces: the nearest edge
    best = min(pl['pieces'], key=lambda p: min(abs(p['tl0'] - t), abs(p['tl1'] - t)))
    return best['s0'] if abs(best['tl0'] - t) < abs(best['tl1'] - t) else best['s0'] + best['dur']


def html_cards(ctx, spec, pl):
    out = []
    for c in spec.get('cards', []):
        tin = tl2s(ctx, pl, c['tl_in']); tout = tl2s(ctx, pl, c['tl_out'])
        if spec.get('hook'): tin = max(tin, spec['hook'].get('dur', hook_dur(ctx)) + 0.35)      # only after the hook is gone
        top = c.get('top', 920)
        rows = []
        if c.get('title'):
            rows.append(f'<span class="plate" data-in="{tin:.2f}" data-out="{tout:.2f}" data-fx="slide-left" data-dist="40"{ANIM}>{c["title"]}</span>')
        for i, it in enumerate(c.get('items', [])):
            at = tl2s(ctx, pl, it['at']) if 'at' in it else tin + 0.25 * (i + 1)
            at = max(at, tin + 0.15 * (i + 1))
            n = it.get('n', f'{i + 1:02d}')
            rows.append(f'<div class="row" data-in="{at:.2f}" data-out="{tout + 0.03 * i:.2f}" data-fx="slide-left" data-dist="40"{ANIM}><div class="n {it.get("ncls", "")}">{n}</div><span class="plate">{it["text"]}</span></div>')
        if c.get('html'): rows.append(c['html'].replace('{in}', f'{tin:.2f}').replace('{out}', f'{tout:.2f}'))
        out.append(f'<div class="card" style="top:{top}px">' + ''.join(rows) + '</div>')
    return '\n'.join(out)


def reels_word(ctx, spec):
    w = spec.get('code_word') or ctx.cfg.reels_word
    if not w:
        raise SystemExit('--reels: нет кодового слова — "code_word" в спеке или reels_word в config.json (на каждый ролик своё)')
    return w


def html_end(ctx, spec, pl):
    t = pl['total']; e = spec.get('end', {})
    dim = f'<div class="dim" data-in="{t:.2f}" data-fx="fade" data-dist="0" data-dur="0.3"></div>'
    if ctx.mode == 'tiktok':   # no link before 1000 followers -> lead to YouTube search: thumbnail + title + channel
        ch = ctx.cfg.tiktok_channel
        th = ctx.cfg.tiktok_thumbnail
        img = ''
        if th and Path(th).is_file():
            img = f'<img class="yt" src="{Path(th).resolve().as_uri()}" data-in="{t + 0.25:.2f}" data-fx="pop" data-dist="60"{ANIM}>'
        else:
            print(f'  ВНИМАНИЕ: tiktok_thumbnail {"не найден: " + th if th else "не задан"} — концовка без скрина превью YouTube')
        if ch:
            return (dim + '<div class="end tiktok">' + img +
                    f'<span class="plate" data-in="{t + 0.1:.2f}" data-fx="pop" data-dist="40"{ANIM}>Полное видео на YouTube: {esc(ch)}</span></div>')
        print('  ВНИМАНИЕ: config.json → tiktok_channel не задан — на карточке «ИЩИ ПО НАЗВАНИЮ ↑», имя канала не выдумывать')
        return (dim + f'<div class="end tiktok"><span class="kicker" data-in="{t + 0.1:.2f}" data-fx="slide-left" data-dist="40"{ANIM}>ПОЛНОЕ ВИДЕО НА YOUTUBE</span>'
                + img + f'<span class="plate" data-in="{t + 0.7:.2f}" data-fx="pop" data-dist="40"{ANIM}>ИЩИ ПО НАЗВАНИЮ ↑</span></div>')
    if ctx.mode == 'reels':    # CTA: write the code word in the comments
        word = esc(reels_word(ctx, spec))
        return (dim + f'<div class="end reels"><span class="plate" data-in="{t + 0.1:.2f}" data-fx="pop" data-dist="40"{ANIM}>Напиши <span class="or">«{word}»</span></span>'
                f'<span class="plate" data-in="{t + 0.25:.2f}" data-fx="pop" data-dist="40"{ANIM}>в комментариях</span>'
                f'<span class="plate w" data-in="{t + 0.8:.2f}" data-fx="slide-left" data-dist="40"{ANIM}>и я пришлю тебе</span>'
                f'<span class="plate w" data-in="{t + 0.95:.2f}" data-fx="slide-left" data-dist="40"{ANIM}>полный урок</span></div>')
    return (dim + f'<div class="end"><span class="kicker" data-in="{t + 0.1:.2f}" data-fx="slide-left" data-dist="40"{ANIM}>{e.get("kicker", "ПОЛНОЕ ВИДЕО")}</span>'
            f'<span class="plate" data-in="{t + 0.25:.2f}" data-fx="pop" data-dist="40"{ANIM}>{e.get("line", "В ПРОФИЛЕ ↑")}</span></div>')


def build_html(ctx, spec, pl, wd, suffix=''):
    body = '\n'.join([html_hook(ctx, spec, pl), html_caps(ctx, pl), html_cards(ctx, spec, pl), html_end(ctx, spec, pl)])
    css = (HERE / 'shorts.css').as_uri(); anim = (HERE.parent / 'graphics' / 'html' / 'anim.js').as_uri()
    html = (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><link rel="stylesheet" href="{css}">'
            f'<script src="{anim}"></script></head><body>\n' + body + '\n</body></html>')
    p = wd / f'gfx{suffix}.html'
    p.write_text(html, encoding='utf-8')
    return p


# ---------------- main ----------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="shorts / reels / tiktok from the long video")
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--plan", action="store_true", help="plan only (work/<id>/plan.json)")
    ap.add_argument("--no-render", action="store_true", help="reuse the rendered graphics (never after a plan change)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--reels", action="store_true")
    g.add_argument("--tiktok", action="store_true")
    a = ap.parse_args(argv)
    mode = 'reels' if a.reels else 'tiktok' if a.tiktok else 'shorts'
    ctx = load(a.config, mode)
    out = ctx.root / 'out' / ({'shorts': '', 'reels': 'reels', 'tiktok': 'tiktok'}[mode])
    suffix = '' if mode == 'shorts' else '_' + mode
    for sid in a.ids:
        sp = ctx.root / 'specs' / f'{sid}.json'
        if not sp.is_file(): raise SystemExit(f'нет спеки {sp} (формат — references/shorts.md)')
        spec = mode_spec(ctx, json.loads(sp.read_text(encoding='utf-8')))
        wd = ctx.root / 'work' / sid; wd.mkdir(parents=True, exist_ok=True)
        ctx.missing.clear(); ctx.dropped.clear()
        pl = plan(ctx, spec)
        (wd / 'plan.json').write_text(json.dumps(pl, ensure_ascii=False, indent=1), encoding='utf-8')
        if ctx.missing: print('  НЕТ ФАЙЛОВ (кусок без исходника):', *sorted(ctx.missing))
        if ctx.dropped: print('  нет в мастере (выкинуто):', ' '.join(ctx.dropped))
        print(f"[{sid}] {mode} {spec.get('title', '')}: {len(pl['pieces'])} кусков, {pl['total']:.1f} с (+{ctx.end_dur} концовка), "
              f"{len(pl['captions'])} субтитров")
        check_duration(ctx, pl)
        if a.plan: continue
        if mode == 'reels': reels_word(ctx, spec)
        out.mkdir(parents=True, exist_ok=True)
        t = time.time(); R.extract(ctx, pl, wd, spec)
        (wd / 'plan.json').write_text(json.dumps(pl, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'  куски: {time.time() - t:.0f} с')
        html = build_html(ctx, spec, pl, wd, suffix)
        mov = wd / f'gfx{suffix}.mov'
        if not a.no_render or not mov.exists():
            R.render(html, fr(pl['total'] + ctx.end_dur), mov)
        wfinal = wd / f'final{suffix}.mp4'
        rep = R.mix(ctx, spec, pl, wd, wfinal, mov)
        (wd / f'report{suffix}.json').write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')
        final = wfinal
        T = pl['total'] + ctx.end_dur
        ts = [0.5, 1.5] + [min(pl['total'] - 0.5, x) for x in (5, 12, 20, 30, 40)] + [pl['total'] + 1.5, T - 0.5]
        R.preview_frames(wd, final, sorted(set(round(x, 2) for x in ts if 0 <= x < T)))
        final = R.deliver(wfinal, out / f"{sid}_{spec['slug']}.mp4", rep)     # out of norm -> exit 1, stays in work/
        print(f"  -> {final}  I={rep['final_I']} LUFS TP={rep['final_TP']}  (голос до: {rep['voice_lufs_pre']:.1f}"
              + (f", музыка {rep['gain_music']:+.1f} dB" if rep['gain_music'] is not None else ', без музыки') + ')')


if __name__ == '__main__':
    main()
