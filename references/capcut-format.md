# Формат проекта CapCut: что добыто болью

## Файлы и запись
- Проект: `com.lveditor.draft/<имя>/` — `draft_content.json`, `draft_meta_info.json`, `Timelines/<id>/draft_content.json`, `subdraft/`, `Resources/`. `<id>` — единственная папка в `Timelines/` (`config.json` → `timeline_id`).
- Настоящий таймлайн — `Timelines/<id>/draft_content.json`. Корневой — зеркало, CapCut перезаписывает его при открытии. Правка только корня молча откатывается. Писать ОБА, после записи сверить md5/длительность обоих.
- CapCut.exe держит драфт в памяти и пересохраняет его через 1–20 мин даже при закрытом проекте. Перед записью: `Get-Process CapCut` → `Stop-Process -Name CapCut -Force` → проверить 0. Флаг «проект закрыт» не использовать. Длинное ожидание — фоновый вотчер: процесс = 0 → запуск apply-скрипта.
- Время — микросекунды. Сравнение с допуском ±1 кадр.

## Compound clip
- Compound = внешний сегмент с материалом videos/audios; вложенный драфт — `materials.drafts[i].draft`; папка `subdraft/<id>/`; запись в `draft_meta_info.json`. Эталон — `scripts/stage2/make_compound.py`.
- Вложенные сегменты — `draft.tracks[-1].segments`; время внутри = внешний `source_timerange`.
- Имя вложенного драфта CapCut переписывает (например, на имя файла первого клипа) → искать драфт по ссылке сегмента (material_id → drafts), не по имени.
- Аудио-compound пререндерится в `Resources/combination/<combination_id>_audio.aac` (`subdraft/<id>/sub_draft_config.json` → audio_path). После правки внутри: удалить .aac и очистить audio_path, иначе старый звук → рассинхрон. Видео-compound не пререндерится.

## Маска
- `common_mask`: type "mask", category "video", path — существующая папка `Cache/effect/<resource_id>/<hash>`. type "none" или мёртвый path → маска молча игнорируется (прямоугольник). Путь машинно-зависим: искать актуальную папку по resource_id в кэше; нет → стоп с инструкцией, какой эффект один раз применить руками.

## Эффекты и цвет
- Шкала temperature в JSON: значение = UI × 0.02 (UI −18 → −0.36; −27 → −0.54).
- Отдельный эффект temperature можно добавить поверх общего Adjust (точечная коррекция).
- Автобаланс белого iPhone уходит в жёлтый, когда на экране за спиной/перед камерой белое: скан R/B стены по кадрам (норма ≈1.07, ушедший ≈1.25) → список диапазонов исходника → точечно temperature на эти сегменты (`scripts/layout/wb_fix.py`, `--temp N`, повторный запуск перезаписывает). Пользователь проверяет на глаз.
- Deep (музыка): путь эффекта в `Cache/effect/<resource_id>/` может отсутствовать — CapCut подтягивает по resource_id не всегда. После применения проверить в CapCut; «эффект потерян» → найти кэш (применить Deep руками один раз) и переприменить.

## Цензура
- Блюр вшивается в копию исходника `<имя>_censored.mp4`, в проекте подменяется path материала (оба draft_content.json + draft_meta_info.json). `build_maps` нормализует `_censored.mp4` → `.mp4` при сопоставлении файлов, иначе слова этих файлов теряются.

## Громкость
- KFTypeVolume (ключи громкости) CapCut-проекты не используют. Рампы — «передачей» между двумя дорожками с перекрытием: уходящий кусок fade_out 300 мс, приходящий (тот же файл, то же место, новая громкость) начинается на 150 мс раньше с fade_in 300 мс → линейная рампа. Склейки петель — перекрытие 60 мс. Смена трека на границе главы — кроссфейд 2 с.
- Фейды — материал audio_fades (клон шаблона).

## Скорость
- Сегмент с speed ≠ 1: source_timerange.duration = target.duration × speed. Ripple-резка, переписывающая source как длину на таймлайне, усекает источник, и CapCut при открытии сбрасывает speed в 1.0. После любой ripple-резки проверить ускоренные куски.
- После ripple-резки файлы с таймкодами (comps.json, sfx.json, music.json) содержат СТАРЫЕ времена → пересчитать, `build_maps` заново.

## Камера iPhone
- `*.MOV` камеры — HEVC 10 бит, HLG (arib-std-b67), BT.2020. CapCut конвертирует сам, ffmpeg — нет (shorts.md §1).

## Создание проекта (scripts/capcut_new_project.py) — EXPERIMENTAL

Снято с пустого проекта CapCut 9.5 (draft_content 4 КБ) и проекта с 1 видео + 1 аудио.

**Папка проекта.** `draft_content.json` (= `Timelines/<tid>/draft_content.json`, `id` драфта = `<tid>`), `draft_meta_info.json`, `draft_settings` (INI: draft_create_time, draft_last_edit_time в секундах), `draft_agency_config.json`, `draft_biz_config.json` (пустой), `performance_opt_info.json`, `attachment_pc_common.json`, `common_attachment/attachment_pc_timeline.json`, `timeline_layout.json` (dockItems → timelineIds [tid]), `Timelines/project.json` (main_timeline_id = tid, timelines[] {id, name "Timeline 01"}), `Timelines/<tid>/attachment_editing.json`, `attachment_pc_common.json`; пустые папки adjust_mask, matting, qr_upload, smart_crop, subdraft, Resources/{audioAlg,videoAlg}. `draft_cover.jpg`, `*.bak`, `template*.tmp` CapCut создаёт сам при открытии — не нужны.

**draft_content.** Верх: id, version 360000, new_version, duration (µs, = длина самой длинной дорожки), fps 30.0, canvas_config {ratio "original", width, height}, materials (все ключи-списки, пустые допустимы), tracks.
- `materials.videos[]`: id, type "video", path (абсолютный, прямые слэши), material_name (имя файла), duration µs, width/height (как отображается, с учётом поворота), has_audio, crop (единичный квадрат), остальное — шаблон.
- `materials.audios[]`: type "extract_music", name, path, duration.
- Сегмент видео: source_timerange {0, dur}, target_timerange {start, dur}, speed 1.0, volume (0.0 = заглушён — камера), material_id, extra_material_refs → по одному новому: speeds, placeholder_infos, canvases, sound_channel_mappings, material_colors, vocal_separations. Сегмент аудио: speeds, placeholder_infos, beats, sound_channel_mappings, vocal_separations. track_render_index/render_index = номер дорожки; главная дорожка attribute 1.
- Шаблоны всех объектов — `templates/capcut_new/templates.json` (клонированы из реальных проектов, пути/id/device_id обнулены).

**draft_meta_info.** draft_id (НЕ равен id таймлайна), draft_name, draft_fold_path (прямые слэши), draft_root_path, tm_draft_create/modified (µs), tm_duration, draft_timeline_materials_size_, `draft_materials` = группы type 0,1,2,3,6,7,8; импорт — в группу 0: {id (uuid lower), file_Path, extra_info (имя), duration µs, width, height, metetype "video"/"music", create_time (с), import_time (с), import_time_ms (µs), roughcut_time_range}.

**root_meta_info.json** (в com.lveditor.draft): {all_draft_store[], draft_ids (int-счётчик), root_path}. Запись: draft_id (= draft_meta_info.draft_id), draft_name, draft_fold_path, draft_json_file и draft_cover (`<fold>\draft_content.json` — с обратным слэшем, как пишет CapCut), draft_root_path, draft_timeline_materials_size, tm_draft_create/modified (µs), tm_duration; остальные поля — шаблон. Новый проект — в начало списка, draft_ids += 1. Бэкап `root_meta_info.json.bak-<stamp>` рядом. Писать только при `Get-Process CapCut` = 0 (скрипт убивает CapCut через ensure_capcut_closed; `--no-kill` — вместо этого ошибка). Сбой после создания папки → папка удаляется.

**draft_root_path — разная форма, как у CapCut:** в `draft_meta_info.json` с обратными слэшами (`C:\Users\...`), в `root_meta_info.json` — с прямыми (`C:/Users/...`). draft_fold_path в обоих — прямые.

**Проверка 2026-10-20 (CapCut 9.5, zz-autotest-1: 2 скринкаста + камера + m4a).** После запуска CapCut проект виден на главном экране: имя zz-autotest-1, «25.0K | 00:06» (длительность верная), обложка чёрная. CapCut за 30 с не переписал root_meta_info.json и ни один файл проекта. Открыть проект в редакторе не удалось проверить (без доступа к UI; пользователь работал за машиной). После закрытия CapCut запись в root_meta_info на месте.
**STATUS: EXPERIMENTAL.** Не проверено: открытие в редакторе, клипы на дорожках/превью, что CapCut не «починит» драфт при открытии, проигрывание звука m4a как extract_music. Fallback — свалка от пользователя.

## Шаблоны эффектов (assets/templates, scripts/effects.py)

Сняты `scripts/harvest_templates.py --project <dir>` с готового проекта первого ролика. Файл: `name`, `category` (ключ `materials.<category>`), `resource_id`, `cache_id` (имя папки в `Cache/effect`), `material`, `extra` [{category, material}], `segment` (шаблон сегмента или null), `notes`. Плейсхолдеры: `{{ID}}` → новый id; `{{CACHE}}/<cache_id>/<hash>/…` → актуальная папка кэша; `{{CAPCUT_APP}}/…` → новейшая `CapCut/Apps/<версия>`; `{{PATH}}`/`{{NAME}}` — файл аудио.

| Шаблон | materials.<category> | resource_id / cache_id | Что |
|---|---|---|---|
| voice_crisper | audio_effects | 7491147795483659521 / то же | Voice Crisper, strength 1.0 |
| reduce_noise | realtime_denoises | — / модель в `{{CAPCUT_APP}}/Resources/audiosami` | Reduce noise (denoise_rate 0.85) |
| deep_effect | audio_effects | 7021052537344102913 / то же | Deep (музыка) |
| mask_circle | common_mask | 7374021188315517456 / **1068046525** | круг, type mask, category video, config = положение |
| adjust_circle | effects (+extra effects saturation, hsl) | 7501974767453474064 / то же | Adjust на клипе: temperature −0.36, saturation 0.2 |
| adjustment_block | placeholders (type adjust) + effects×2 + hsl | — | блок на дорожке type adjust, сегмент source_timerange null |
| keyframes_zoom | — | — | форма записи `common_keyframes` и ключа (curveType Line) |
| sfx_segment | audios (extract_music) + speeds, placeholder_infos, beats, sound_channel_mappings, loudnesses, vocal_separations | — | материал + сегмент SFX |
| music_segment | audios + те же + audio_fades | — | материал + сегмент музыки; Deep отдельно |

- `effects.make(name, draft, cache_root=None, **overrides) -> id` — клон primary + extra, overrides (ключи через точку) — в primary. `make_all` → все id (adjust_circle, adjustment_block). `attach(seg, id)` → `extra_material_refs`.
- Поиск кэша: `find_effect_cache(cache_id)` → папка `Cache/effect/<cache_id>`; подпапка-хэш из шаблона, если есть, иначе первая существующая. Не найдено → `EffectCacheMissing` («примените его в CapCut один раз вручную»), в драфт ничего не добавлено. Для маски `cache_id` ≠ `resource_id`.
- `zoom_keyframes(seg, t_in, t_hold, t_out, scale, cx, cy)` — секунды от начала сегмента; ключи t_in (1.0) → t_in+ramp (scale) → t_hold (scale) → t_out (1.0), ramp = t_out − t_hold; Position X/Y — только при cx/cy ≠ 0; всё вне сегмента → ValueError.
- Значения Adjust в шаблонах выставлены по правилам (−18 / 10), в исходном проекте блок был другим (temperature −0.08, vignetting 0.1).
