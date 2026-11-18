# Библиотека скринкастов Writelo

`C:\Users\shara\Videos\рилсики\_screencasts\` — готовые скринкасты сервиса, чтобы рилс про Writelo
собирался без досъёмки. Все записи: iPhone, Safari, вертикально (888x1920 или 1080x2336).
Три поверхности: приложение writelo.io (W), ChatGPT с коннектором Writelo (G), Claude с коннектором (C),
плюс ролики с лендинга (L).

## Перед монтажом рилса про сервис
1. `python -X utf8 scripts/screencasts/lib.py list`: что есть. Для каждой фразы сценария, где что-то
   показывают, ищем кусок: `lib.py list --action <глагол>` («поиск», «фильтр», «листаем», «голосовой ввод»,
   «ответ», «Разобрать»). Ниша клипа = ниша рилса; если нужной нет, бери `niche: any`.
2. В layout: `sys.path.insert(0, <skill>/scripts/screencasts)`, `path, t0, t1 = get("W6-psy-search/type")`,
   дальше как обычный скринкаст (`cast()` / `chain()`: ×≤2.4, зависания вырезать).
3. Смотреть `labels.privacy` (staging-адрес, «Hey, shara», системные диалоги) и прятать: полоса внизу
   телефона, кроп или другой кусок.
4. После рендера: `mark_used("<id>/<кусок>", "<папка рилса>")`. Один и тот же кусок не ставить в соседние рилсы
   (`find()` и так ставит неиспользованные первыми).
5. Нужного нет → не рисовать макет интерфейса: пустой слот + строчка в `RECORDING_LIST.md`.

## Новые записи
Пользователь кидает сырые файлы в `inbox\`. `python -X utf8 scripts/screencasts/ingest.py`:
- срезает шторку «Пункта управления» в конце (провал резкости в последних 3 с);
- `clips/new-<имя>.mp4` без звука, `work/<id>/sheet.jpg` (2 fps с временем);
- `auto`: куски still/scroll/change + текст с экрана раз в секунду (tesseract rus+eng, `assets/tessdata`).

Дальше вручную: смотрю сетку и текст, заполняю `labels` (surface, scenario, niche, theme, query,
segments с `name`/`action`/`desc`, privacy, stale_after), `lib.py rename new-… <id>`. Повторный прогон
(`--redo <id>`) labels не трогает. Импорт уже использованного скринкаста из папки рилса:
`ingest.py --copy --src <файл> --id <id>`.

Ниши аудитории: building (стройка и ремонт), cars, restaraunt, psychology, cosmetology (+ clothing из старых записей).
Ключи совпадают с категориями каталога Writelo. Свежие тренды и ChatGPT-ответы с датами стареют:
`stale_after`, и `find()` их пропускает.
