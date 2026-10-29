"""Reel from scratch (scripts/reel/build_reel.py): spec parsing -> plan, word map, silence cut, graphics HTML (pure,
no media)."""
import json
import re

import pytest

import build_reel as br
import validate_reel


def words(seq, t0=0.0, gap=0.05):
    """[(word, dur)] -> whisper-like word list from t0, one gap between words (a tuple (word, dur, gap) sets its own gap)."""
    out, t = [], t0
    for item in seq:
        w, d = item[0], item[1]
        out.append(dict(word=w, start=round(t, 3), end=round(t + d, 3), p=1.0))
        t += d + (item[2] if len(item) > 2 else gap)
    return out


WORDS = {
    'a.m4a': words([('Мы', .3), ('создали', .4), ('Айограм.', .5), ('Меня', .3), ('зовут', .3), ('Егор,', .3, 1.0), ('более', .3), ('6', .2), ('лет.', .3),
                    ('от', .2), ('фриланса', .5), ('до', .2), ('стартапов', .5)], t0=2.0),
    'b.m4a': words([('Мой', .3), ('коллега', .4), ('Алексей', .4), ('Завар,', .4), ('создатель', .5), ('Айограма,', .6), ('с', .1), ('более', .2), ('чем', .2),
                    ('миллионом', .4), ('активных', .4), ('пользователей', .6), ('и', .2), ('продукты', .4), ('FunPay', .5), ('более', .3), ('чем', .2), ('на', .1),
                    ('50', .3), ('тысяч', .4)], t0=0.0),
    'c.m4a': words([('Мы', .2), ('команда', .4), ('Рэйтео.', .5), ('можете', .3), ('искать', .4), ('свежий', .4), ('контент', .4)], t0=0.0),
    'd.m4a': words([('Я', .2), ('бакалавр', .5), ('и', .1), ('партнер', .4), ('программист.', .6), ('Мы', .2), ('пришли', .3), ('войти', .3), ('задолго', .5),
                    ('до', .2), ('курс', .4), ('GPT.', .4)], t0=1.0),
}
SPEC = {
    'id': 't', 'out': 'out/t.mp4', 'speed': 1.1, 'voice_dir': 'voice', 'camera_dir': 'camera',
    'sfx': {'tick': 'tick.wav', 'whoosh': 'whoosh.wav'},
    'sections': [
        {'id': 'hook', 'voice': 'a.m4a', 'v': [1.9, 9.0], 'camera': '1.MOV', 'cam_offset': 5.0, 'hook_text': ['МЫ СОЗДАЛИ', 'AYUGRAM'],
         'hook_until_word': 'Меня', 'accents': ['6', 'лет'], 'stickers': [{'at_word': 'фриланса', 'text': 'freelance'}, {'at_word': 'стартапов', 'text': 'startups'}]},
        {'id': 'scheme', 'voice': 'b.m4a', 'v': [0.0, 8.5], 'camera': None,
         'scheme': {'nodes': [
             {'id': 'alex', 'icon': 'avatar', 'label_words': ['Мой', 'коллега'], 'label2_words': ['Алексей', 'Завар,']},
             {'id': 'ayu', 'icon': 'ayugram', 'pan_before_word': 'создатель', 'phrases': [['создатель', 'Айограма,'], ['с', 'более', 'чем']],
              'number': {'text': '1 000 000', 'at_word': 'миллионом'}, 'number_lines': [['активных', 'пользователей']]},
             {'id': 'fp', 'icon': 'funpay', 'shape': 'plate', 'pan_before_word': 'продукты', 'phrases': [['и', 'продукты'], ['более', 'чем', 'на']],
              'number': {'text': '50 000', 'at_word': '50'}, 'number_lines': [['тысяч']]}]}},
        {'id': 'service', 'voice': 'c.m4a', 'v': [0.0, 3.0], 'camera': None, 'caption_fix': {'Рэйтео.': 'service.'},
         'ui_cards': [{'at_word': 'Мы', 'title': 'app', 'lines': ['Тренды', 'Ниши']}, {'at_word': 'искать', 'title': 'поиск', 'lines': ['2.4M', '374K']}]},
        {'id': 'team', 'voice': 'd.m4a', 'v': [[1.0, 3.0], [3.0, 6.0]], 'camera': 'IMG_1.MOV', 'cam_offset': 2.0, 'caption_fix': {'войти': 'в IT'},
         'memes': [{'at_word': 'бакалавр', 'text': 'Я бакалавр', 'icon': 'dog'}, {'at_word': 'партнер', 'text': 'партнёр', 'icon': 'cat'}],
         'memes_out_word': 'Мы', 'accents': ['задолго'], 'cta_word': 'курс', 'cta_big': 'КУРС'},
    ],
}


def test_cut_silences_only_long_gaps():
    ws = WORDS['a.m4a']
    pieces = br.cut_silences(ws, 1.9, 9.0)
    assert len(pieces) == 2                                   # the one 1.0-s pause (after «Егор,»)
    (a0, b0), (a1, b1) = pieces
    assert a0 == 1.9 and b1 == 9.0
    assert b0 - ws[5]['end'] == pytest.approx(0.425, abs=1e-3) and ws[6]['start'] - a1 == pytest.approx(0.425, abs=1e-3)
    assert a1 - b0 == pytest.approx(br.GAP_KEEP, abs=1e-3)
    assert br.cut_silences(ws, 1.9, 5.0) == [(1.9, 5.0)]      # no gap > 0.35 inside -> one piece
    assert br.cut_silences([], 0, 2) == [(0, 2)]


def test_plan_pieces_words_and_speed():
    pl = br.plan(SPEC, WORDS)
    assert pl['speed'] == 1.1 and len(pl['pieces']) == 2 + 1 + 1 + 2
    p0 = pl['pieces'][0]
    assert p0['camera'] == '1.MOV' and p0['cam_in'] == pytest.approx(1.9 + 5.0) and p0['out_in'] == 0
    assert p0['dur'] == pytest.approx((p0['src_out'] - p0['src_in']) / 1.1, abs=1 / 30)
    # out times are frame-aligned and contiguous; sections follow the spec order
    for a, b in zip(pl['pieces'], pl['pieces'][1:]):
        assert a['out_out'] == b['out_in'] and abs(b['out_in'] * 30 - round(b['out_in'] * 30)) < 2e-3   # q() rounds to 4 decimals
    assert [s['id'] for s in pl['sections']] == ['hook', 'scheme', 'service', 'team']
    assert pl['total'] == pl['pieces'][-1]['out_out']
    # word map: a word's out time = piece out_in + (src − piece src_in) / speed; the pause does not count
    w6 = next(w for w in pl['words'] if w['word'] == 'более' and w['section'] == 'hook')
    p1 = pl['pieces'][1]
    assert w6['piece'] == 1 and w6['start'] == pytest.approx(p1['out_in'] + (w6['src_start'] - p1['src_in']) / 1.1, abs=1e-3)
    assert all(w['start'] >= 0 and w['end'] <= pl['total'] + 1e-6 for w in pl['words'])
    # second range of team starts a new piece; a word is reported once
    assert [w['word'] for w in pl['words'] if w['section'] == 'team'] == [w['word'] for w in WORDS['d.m4a']]
    # angle presets by file name, scheme has no camera
    assert [s['angle'] for s in pl['sections']] == ['mic', None, None, 'arms']


def test_word_time_and_missing_word(capsys):
    pl = br.plan(SPEC, WORDS)
    t = br.word_time(pl, 'hook', 'фриланса')
    w = next(w for w in pl['words'] if w['word'] == 'фриланса')
    assert t == w['start']
    assert br.word_time(pl, 'hook', 'зовут', after=w['start']) == pytest.approx(pl['sections'][0]['out_out'] - 0.3)   # earlier than `after` -> fallback
    assert 'не найдено' in capsys.readouterr().out
    assert br.word_time(pl, 'hook', 'нет-такого', missing='none') is None
    with pytest.raises(SystemExit):
        br.word_time(pl, 'hook', 'нет-такого', missing='raise')


def test_gfx_html_has_words_in_time_and_the_blocks():
    pl = br.plan(SPEC, WORDS)
    html, events = br.gfx_html(pl, SPEC)
    # hook: two lines, the last one the accent; gone at «Меня»
    t_menya = br.word_time(pl, 'hook', 'Меня')
    assert re.search(r'class="rl rhook" data-in="0.000" data-out="%.3f"' % t_menya, html)
    assert re.search(r'<div class="ln" data-in="0.000"[^>]*>МЫ СОЗДАЛИ</div>', html) and re.search(r'<div class="ln acc"[^>]*>AYUGRAM</div>', html)
    # captions: every camera word after the hook is a .w span with its out time; accents are yellow; lowercase
    for w in pl['words']:
        if w['section'] == 'hook' and w['start'] >= t_menya:
            txt = br.display(w['word'], None)
            assert re.search(r'<span class="w( acc)?" data-in="%.3f"[^>]*>%s</span>' % (w['start'], re.escape(txt)), html), w
    assert re.search(r'<span class="w acc" data-in="[\d.]+"[^>]*>6</span>', html) and 'зовут' in html and 'Зовут' not in html
    assert html.count('class="stk"') == 2 and 'freelance' in html and 'startups' in html
    # scheme: the panel (opaque, full frame) with the words at the spoken times and the two numbers
    assert 'class="scheme s' in html and '1 000 000' in html and '50 000' in html
    t_mil = br.word_time(pl, 'scheme', 'миллионом')
    assert re.search(r'<span class="num word" data-in="%.3f"[^>]*>1 000 000</span>' % t_mil, html)
    assert html.count('class="pop"') == 3 and html.count('<path class="dash"') == 2
    # service: two opaque UI cards; the caption fix applied («service»), one word per caption
    assert html.count('class="ui"') == 2 and '>service<' in html and 'Рэйтео' not in html and 'class="ucap"' in html
    # team: two memes (dog / cat), fade out together at «Мы»; the CTA word big; the caption fix «в IT»
    t_my = br.word_time(pl, 'team', 'Мы')
    assert len(re.findall(r'class="meme" data-in="[\d.]+" data-out="%.3f"' % t_my, html)) == 2 and '🐶' in html and '🐱' in html
    assert re.search(r'class="rl cta" data-in="%.3f"[^>]*>КУРС<' % br.word_time(pl, 'team', 'курс'), html)
    assert '>в IT<' in html
    # SFX events: whoosh on every section boundary (3) + 2 scheme pans; ticks on stickers, nodes, numbers, ui cuts, memes, cta
    wh = [t for k, t in events if k == 'whoosh']
    assert len(wh) == 5 and all(s['out_in'] in wh for s in pl['sections'][1:])
    ticks = [t for k, t in events if k == 'tick']
    assert len(ticks) >= 2 + 3 + 2 + 2 + 2 + 1 and events == sorted(events, key=lambda e: e[1])
    assert all(0 <= t <= pl['total'] for _, t in events)


def test_phrases_and_display():
    ws = words([('а', .1), ('б', .1), ('в,', .1), ('г', .1), ('д', .1), ('е', .1), ('ж', .1), ('з', .1, 1.0), ('и', .1)])
    phs = br.phrases_of(ws)
    assert [[w['word'] for w in p] for p in phs] == [['а', 'б', 'в,'], ['г', 'д', 'е', 'ж'], ['з'], ['и']]
    assert br.display('Юграм', {'Юграм': 'AyuGram'}) == 'AyuGram' and br.display('Привет,', None) == 'привет' and br.display('-сайенсам', None) == 'сайенсам'
    assert br.is_accent('формул.', ['формул.']) and br.is_accent('6', ['6']) and not br.is_accent('и', ['искать'])


def test_validation_helpers():
    import numpy as np
    img = np.zeros((20, 20, 3), np.uint8); img[..., 0] = 150; img[..., 1] = 120; img[..., 2] = 100
    st = validate_reel.color_stats(img)
    assert st['mids_rg'] == pytest.approx(30) and st['mids_bg'] == pytest.approx(-20) and 16 <= st['y50'] <= 235
    assert set(st) == set(validate_reel.REF_COLOR)
