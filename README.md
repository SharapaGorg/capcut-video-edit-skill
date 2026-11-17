# video-edit — Claude Code skill for CapCut

Скилл для [Claude Code](https://docs.anthropic.com/claude-code), который монтирует длинный YouTube-ролик в CapCut по этапам и режет из него короткие версии (Shorts / Reels / TikTok).

Вход: папка исходников (`camera/`, `screencasts/`, `voice/`) и проект CapCut. Выход: собранный таймлайн в `draft_content.json`, графика, музыка, `.srt`, экспорт и наборы шортсов.

## Этапы

| № | Что |
|---|---|
| 0 | Транскрипция (faster-whisper) |
| 1 | Смысловая резка |
| 2 | Техническая резка, compound clips, кружок камеры, голос |
| 3 | Чекпоинт, карта таймкодов |
| 4 | Хук и концовка |
| 5 | Цензура |
| 6 | Зумы + SFX |
| 7 | Иллюстрации (HTML-графика) |
| 8 | Ключевые фразы, заставки глав |
| 9 | Музыка |
| 10 | Экспорт, YouTube (главы, .srt) |

Короткие версии: `scripts/shorts/` по спекам `specs/<id>.json`, флаги `--reels`, `--tiktok`.

## Рилсы без CapCut

- **Рилс с нуля** (`references/reel.md`, `scripts/reel/build_reel.py`): сырьё (микрофон + камера по кускам сценария) и спека → готовый mp4.
- **«Слова за головой»** (`references/captions.md`, `scripts/captions/run.py`): проход поверх чернового рендера рилса — пословные субтитры в два шрифта, крупное слово за головой (маска человека, Robust Video Matting), чёрный силуэт на кремовом с лентой и светящимися глазами, рамка трекинга лица, печатающаяся ссылка, полноэкранные сцены для секций без камеры, саунд-дизайн. Стиль разобран по рилсу @viashaan и гайду автора; правила — в `references/captions/`, примеры раскладок и раскадровки — в `assets/examples/captions/`.

```
python -X utf8 ~/.claude/skills/video-edit/scripts/captions/run.py <рилс>/auto prep --base out/rough_v1.mp4 --name captions_v1
python -X utf8 ~/.claude/skills/video-edit/scripts/captions/run.py <рилс>/auto stills --stills 10,45,90
python -X utf8 ~/.claude/skills/video-edit/scripts/captions/run.py <рилс>/auto render --sfx-dir <папка пака SFX>
```

Руками пишется один файл — `<рилс>/auto/captions/layout.py`. Пак звуков в репозиторий не входит: имена файлов — словарь `S` в `scripts/captions/audio.py`.

## Установка

```
git clone https://github.com/SharapaGorg/capcut-video-edit-skill ~/.claude/skills/video-edit
```

Зависимости: Python 3.11+, ffmpeg, faster-whisper, CapCut (Windows, автообновление выключено). Для рилсов дополнительно: playwright (chromium), onnxruntime, opencv, numpy, pillow.

## Использование

В Claude Code: «смонтируй ролик, исходники в `<папка>`, проект `<имя>`». Скилл сам создаёт рабочую папку с `config.json` и ведёт этапы по порядку. Скрипты запускаются из рабочей папки:

```
python -X utf8 ~/.claude/skills/video-edit/scripts/<stage>/<script>.py --config config.json
```

Подробности: `SKILL.md`, правила этапов в `references/stages/`, формат CapCut в `references/capcut-format.md`.

## Структура

- `SKILL.md` — точка входа для Claude Code
- `scripts/` — скрипты этапов, графики, шортсов
- `references/` — правила, этапы, формат проекта CapCut
- `assets/templates/` — эталонные фрагменты JSON (эффекты, маска, зумы), шрифт Unbounded
- `assets/captions/` — шрифты, модель маски и музыка стиля «слова за головой» (лицензии — `assets/captions/NOTICE.md`)
- `tests/` — `python -X utf8 -m pytest tests -q`

## Важно

- CapCut должен быть полностью закрыт перед правкой проекта (`Get-Process CapCut` = 0), иначе он перезапишет файл из памяти.
- Скрипты пишут и в корневой `draft_content.json`, и в `Timelines/<id>/draft_content.json`.
- Перед правкой делайте бэкап папки проекта.
