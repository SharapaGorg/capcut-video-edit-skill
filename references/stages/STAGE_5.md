# Этап 5. Цензура
«Я/мне» в тексте = пользователь; при делегированной автономии — решать самому, см. rules.md.
Место: после этапа 4, до зумов (зумы увеличат незамазанное).
Цель: скрыть личные данные на скринкасте.

Способ: блюр вшивается в исходник скринкаста через ffmpeg, в проекте подменяется путь материала. Не слоем поверх — зумы этапа 6 сдвинут слой относительно картинки.

## Шаги
1. Кадры только используемых диапазонов скринкаста (timeline_map) раз в 1 с → OCR (tesseract rus+eng; нет rus → `config.json` → `tessdata`: папка с rus/eng.traineddata).
2. Паттерны: e-mail; ключи и токены (sk-, pk-, ghp_, Bearer, eyJ…); hex/base64 ≥ 20 символов; телефоны; номера карт; поля пароля; токены в адресной строке (token=, key=).
3. Визуально (смотреть кадры начала каждого куска скринкаста): уведомления мессенджеров, личные вкладки, закладки, аватарки чужих людей в личных чатах.
4. censor_proposal.md: № | таймкод таймлайна | файл и время исходника | что найдено | bbox.
   Публичные аккаунты, конкуренты, ролики — это контент, не скрывать без моего слова.
5. **Стоп** до утверждения.
6. Применение:
   - ffmpeg boxblur (сила 20) на bbox +10 px, от первого до последнего кадра показа ±0,5 с. Область двигается (скролл) → bbox по OCR каждые 0,5 с.
   - Новый файл `<work_dir>/stage5/censored/<имя>_censored.mp4` (исходники не трогать): то же разрешение, fps; CRF 16; звук копировать без перекодирования.
   - Кодировать только файлы с находками, в фоне.
   - Подменить путь материала в проекте. Сегменты не трогать.

## Скрипты
cwd = рабочая папка ролика (там `config.json`); запуск `python -X utf8 ~/.claude/skills/video-edit/scripts/<путь> --config config.json`; пишущие в проект — сначала `--dry`. По порядку:

| № | Команда | Вход | Выход |
|---|---|---|---|
| 1 | `stage5/extract_frames.py [--only SUBSTR]` | проект (используемые куски скринкаста) | `stage5/frames/<stem>/<сек>.jpg`, `stage5/segment_starts.json` |
| 2 | `stage5/run_ocr.py [--jobs 8]` (в фоне) | `stage5/frames/` | `stage5/ocr/*.tsv` |
| 3 | `stage5/scan_patterns.py`; агент смотрит кадры `segment_starts.json` | `stage5/ocr/` | `stage5/pattern_hits.json`; `stage5/manual_findings.json` (визуальные находки, опц.) |
| 4 | `stage5/build_findings.py` | `pattern_hits.json`, `manual_findings.json`, `segment_starts.json` | `stage5/censor_findings.json`, `censor_proposal.md` |
| 5 | **Стоп** → `apply: true/false` в `censor_findings.json` | — | — |
| 6 | `stage5/apply_censor.py --encode-only` (в фоне), затем `--dry`, затем без флагов | `censor_findings.json` (apply true), исходники | `stage5/censored/<stem>_censored.mp4`, пути в проекте и draft_meta_info, `stage5/censor_applied.json` |
| 7 | `stage5/verify_censor.py` | `censor_applied.json`, копии и исходники | `stage5/verify/NN_{before,after}.png`, `report.json` (exit 1 при проблеме) |

## Проверка
- VALIDATION.md.
- Длительность и fps `_censored` = исходник. Иначе стоп.
- Повторный OCR по тем же кадрам из `_censored` — паттерны не находятся.
- Кадр каждой находки до/после (png) — блюр покрывает целиком.
- Отчёт: таймкоды и что скрыто.