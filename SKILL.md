---
name: video-edit
description: Монтаж ролика — монтаж длинного YouTube-ролика в CapCut по этапам 0–10 (транскрипция, смысловая и техническая резка, сборка compound/кружок/голос, раскладка S/F, хук, цензура, зумы+SFX, HTML-графика, музыка, экспорт) и короткие версии из него (YouTube Shorts, Instagram Reels, TikTok). Применять, когда пользователь даёт папку исходников ролика (camera/screencasts/voice) и/или проект CapCut и просит смонтировать, продолжить этап, сделать шортсы/рилсы/тиктоки, графику, музыку, субтитры .srt, главы, проверить громкость. Триггеры: «смонтируй ролик», «новый ролик», «этап N», «CapCut», «шортсы», «рилсы», «тикток», «draft_content.json».
---

# Монтаж ролика (CapCut) + короткие версии

Две части: **long** (этапы 0–10 + LAYOUT, CapCut) и **short** (Shorts/Reels/TikTok из исходников по картам long-части).
Скилл ведёт этапы автономно. Пользователь не ставит эталонов и не синхронизирует руками — всё делают скрипты из шаблонов `assets/templates/`.

## Когда применять
- Новый ролик: «вот исходники, вот проект» / «вот исходники».
- Продолжение: «дальше», «этап N», правки по просмотру черновика/экспорта.
- Короткие: шортсы, рилсы, тиктоки из готового ролика.
- Рилс с нуля из сырья и сценария (микрофон m4a + камера MOV по кускам, без CapCut и без длинного ролика) — references/reel.md.
- Вне скилла: превью (thumbnail), загрузка на площадки.

## Вход
1. Папка исходников `E:\CAPCUT\длинные_ролики\<ролик>\` с `camera/`, `screencasts/`, `voice/` (микрофон, может отсутствовать). Работать прямо с этими путями, ничего не копировать и не переименовывать.
2. Проект CapCut: проект-свалка от пользователя (исходники разбросаны по дорожкам, без синхронизации, масок, эффектов) — основной путь. Автосоздание `scripts/capcut_new_project.py` — EXPERIMENTAL (CapCut показывает проект в списке, открытие не подтверждено): только если пользователь согласен проверить проект глазами. Имя или путь проекта.

## Конфиг ролика
Первым шагом создать рабочую папку ролика (рядом с исходниками или указанную) и `config.json`. Скрипты принимают `--config`, по умолчанию ищут в cwd.
cwd = рабочая папка ролика (там `config.json`); скрипты запускать `python -X utf8 ~/.claude/skills/video-edit/scripts/<путь> --config config.json`. Порядок скриптов, входы и выходы каждого шага — блок «Скрипты» в файле этапа.

```json
{
  "project_dir": "C:/Users/.../com.lveditor.draft/<имя>",
  "timeline_id": "<авто: единственная папка в Timelines/>",
  "sources": {"camera": "...", "screencasts": "...", "voice": "..."},
  "fps": 30, "width": 1920, "height": 1080,
  "compounds": {"mic": null, "cam_full": [], "screencast": null, "circle": null},
  "sfx_dir": "...", "music_dir": "...",
  "description_md": "<ролик>/description.md",
  "master_render": "<экспорт мастера, для шортсов>",
  "tiktok_channel": null, "tiktok_thumbnail": null, "reels_word": null,
  "master_maps": null
}
```
- `fps`/`width`/`height` — из драфта проекта (`init_video.py`); повторный запуск `init_video.py` дописывает конфиг, не затирая (`--force` — перезаписать).
- `compounds` заполняет этап 2 §7 после сборки.
- `sfx_dir`, `music_dir` неизвестны → спросить один раз.
- Короткие (shorts.md): `tiktok_channel` / `tiktok_thumbnail` — концовка TikTok, `reels_word` — кодовое слово рилса, `master_maps` — карты таймлайна мастера, если он доделан в копии проекта (по умолчанию `stage3`). `audio_profile` — звук шортсов: `ref` (эталон монтажёра, по умолчанию) / `legacy`. `color_profile` — цвет камеры в шортсах: `ref` (`assets/ref_joint.cube`, look монтажёра, по умолчанию; `master_render` не нужен) / `master` (калибровка `cam_lut.py` по рендеру мастера). Эталон целиком — references/reference-style.md.
- Рабочая папка: `transcript/`, `stage1/` … `stage12_shorts/`, `backups/`, `PROGRESS.md`.

## Порядок
0 → 1 → 2 (+ §7 сборка) → 3 (**ок пользователя** по черновику) → LAYOUT → 4 → 5 → 6 → 7 → 8 (**тестовая графика → ок пользователя**) → 9 → 10 → shorts (спека → **первый шортс → ок** → пачка → `--reels` / `--tiktok`).

Каждый этап: прочитать PROGRESS.md → файл этапа → бэкап → `--dry` → применить → проверки этапа + validation.md → раздел в PROGRESS.md.
После любой структурной правки (вставка, вырезка, сдвиг): `scripts/stage3/build_maps.py` + validation.

## Железные правила
1. Перед записью в проект: `Stop-Process -Name CapCut -Force`, `Get-Process CapCut` = 0. Закрытый проект при живом процессе не защищает.
2. Писать в ОБА файла: `Timelines/<id>/draft_content.json` (настоящий) и корневой `draft_content.json` (зеркало) — через `scripts/common.py`.
3. Бэкап папки проекта до каждой записи; guard mtime после записи.
4. Материалы и эффекты — только клоны шаблонов/существующих записей, не с нуля.
5. Голос: микрофон во вступлении (если есть), дальше и без микрофона — звук скринкаста. Звук камеры никогда (volume 0).
6. Уровни: голос mp3 = скринкаст ±1 LU; SFX = голос −12 LU; музыка = голос −13 LU; финал −14 LUFS, TP ≤ −1.
7. Графика только HTML → Playwright → ProRes 4444 MOV. Текст CapCut, PIL, Remotion — запрещены.
8. Маска кружка: type "mask", path существует; аудио-compound после правки — удалить `_audio.aac` пререндер.
9. После этапа 3 все таймкоды — время таймлайна (`stage3/transcript_timeline.json`, `timeline_map.json`).
10. Провал проверки → не идти дальше, отчёт.

## Стоп-точки
«Стоп» в файле этапа → решать самому, консервативно, по данным (кадры, замеры). В proposal-файл и PROGRESS.md: «утверждено автоматически» + причина. Не задавать вопросов, на которые можно ответить по данным.
Ок пользователя обязателен только в трёх местах: черновик этапа 3, тестовая графика (этапы 7–8), первый шортс/рилс/тикток.
Длинные задачи — в фоне с логом, прогресс проверить в течение минуты.

## Бриф этапа (субагенту)
Тяжёлые этапы — субагентом, чтобы держать контекст малым. Шаблон:

```
Этап <N> ролика <имя>. Скилл: ~/.claude/skills/video-edit.
Конфиг: <рабочая папка>/config.json. Состояние: <рабочая папка>/PROGRESS.md (последние разделы).
Прочитать: references/rules.md, references/stages/STAGE_<N>.md, references/validation.md
(+ capcut-format.md для записи в проект; graphics.md для 7–8; shorts.md для коротких).
Скрипты: scripts/<этап>/… (--config, сначала --dry).
Стоп-точки решать самому, «утверждено автоматически» + причина. Исключения: <ок пользователя, если есть>.
Перед записью: kill CapCut, бэкап, оба draft_content.json.
В конце: проверки фактически, раздел в PROGRESS.md, краткое резюме.
```

## Этапы → reference → скрипты
| Этап | Reference | Скрипты |
|---|---|---|
| Ролик и проект | — | `scripts/init_video.py` (рабочая папка + config.json), `scripts/capcut_new_project.py` (EXPERIMENTAL) |
| Общие модули | references/capcut-format.md | `scripts/common.py` (конфиг, запись в оба draft, проверки), `scripts/effects.py` (эффекты из шаблонов), `scripts/harvest_templates.py` (снять шаблоны с проекта) |
| 0 Транскрипция | references/stages/STAGE_0.md | `scripts/stage0/transcribe.py` |
| 1 Смысловая резка | references/stages/STAGE_1.md | `scripts/stage1/{build_proposal,apply_cuts}.py` |
| 2 Техническая резка + сборка | references/stages/STAGE_2.md | `scripts/stage2/{analyze,verify,apply,assemble,make_compound}.py`, `scripts/layout/{xcorr,add_camera,fix_circle,wb_fix}.py` |
| 3 Карта таймкодов | references/stages/STAGE_3.md | `scripts/stage3/{build_maps,ripple_cut}.py` |
| LAYOUT S/F | references/stages/STAGE_LAYOUT.md | `scripts/layout/{candidates,apply_layout,make_compound_f}.py` |
| 4 Хук и концовка | references/stages/STAGE_4.md | `scripts/stage4/apply_hook.py` |
| 5 Цензура | references/stages/STAGE_5.md | `scripts/stage5/{extract_frames,run_ocr,scan_patterns,build_findings,apply_censor,verify_censor}.py` |
| 6 Зумы + SFX | references/stages/STAGE_6.md | `scripts/stage6/{find_focus,apply_zooms,check_zooms}.py` (фокус-зум на скринкасте — только в compound без кружка: сначала разделить) |
| 7 Иллюстрации | references/stages/STAGE_7.md, references/graphics.md | `scripts/graphics/{gfx_build,render,preview,apply_graphics,apply_sfx}.py` |
| 8 Фразы и заставки | references/stages/STAGE_8.md, references/graphics.md | то же |
| 9 Музыка | references/stages/STAGE_9.md | `scripts/stage9/{prepare,beats,build_voice,apply_music,music_gain,measure_lufs,check_mix}.py` |
| 10 Экспорт и YouTube | references/stages/STAGE_10.md | `scripts/stage10/{build_srt,loudnorm}.py` |
| Shorts | references/shorts.md | `scripts/shorts/{build,build_render,voice_ref,cam_lut,rmap,scheme}.py` (scheme — полноэкранная схема «кто есть кто») |
| Reels | references/reels.md | `scripts/shorts/build.py --reels` |
| TikTok | references/tiktok.md | `scripts/shorts/build.py --tiktok` |
| Рилс с нуля | references/reel.md | `scripts/reel/{build_reel,validate_reel}.py` (спека + whisper-слова → mp4; схема, UI-макеты, стикеры, мемы, музыка, −17.5 LUFS) |

Общие правила — [references/rules.md](references/rules.md). Эталон монтажёра (звук/цвет/дизайн, профили `ref`) — [references/reference-style.md](references/reference-style.md). Проверки — [references/validation.md](references/validation.md). Формат CapCut и подводные камни — [references/capcut-format.md](references/capcut-format.md). Графика — [references/graphics.md](references/graphics.md).
Шаблоны JSON CapCut — `assets/templates/`, шрифт — `assets/Unbounded-var.ttf`, образцы графики — `assets/examples/html/`, образец спеки — `assets/examples/specs/example.json`.
