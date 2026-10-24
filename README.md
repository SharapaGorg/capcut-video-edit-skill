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

## Установка

```
git clone https://github.com/SharapaGorg/capcut-video-edit-skill ~/.claude/skills/video-edit
```

Зависимости: Python 3.11+, ffmpeg, faster-whisper, CapCut (Windows, автообновление выключено).

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
- `tests/` — `python -X utf8 -m pytest tests -q`

## Важно

- CapCut должен быть полностью закрыт перед правкой проекта (`Get-Process CapCut` = 0), иначе он перезапишет файл из памяти.
- Скрипты пишут и в корневой `draft_content.json`, и в `Timelines/<id>/draft_content.json`.
- Перед правкой делайте бэкап папки проекта.
