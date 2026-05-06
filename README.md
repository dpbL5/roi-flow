# Flow Veo Studio

Локальный Windows-инструмент для Google Flow / Veo. Он читает `sentences.json` из выбранной папки `frames`, генерирует индексированные Veo-промпты через OpenAI, отправляет готовые промпты в Flow, скачивает клипы и хранит состояние рядом с исходной папкой проекта.

## Быстрый Старт

Запуск:

```text
C:\Users\oldje\Documents\flow-veo-studio\run.bat
```

Локальный интерфейс:

```text
http://127.0.0.1:8765
```

Библиотека каналов:

```text
D:\MyChannelsIRL
```

Обычный сценарий:

1. Запустить `run.bat`.
2. Открыть `http://127.0.0.1:8765`.
3. Выбрать `Канал`.
4. Выбрать `Серия`.
5. Проверить, что `Папка frames` стала нужной: `D:\MyChannelsIRL\<channel>\<series>\frames`.
6. Выбрать `Стиль канала`.
7. Нажать `Проверить сценарий`.
8. Если нужно, нажать `Сгенерировать все промпты`.
9. Для визуала вставить/сохранить URL проекта Flow, открыть этот проект в Яндекс Браузере с установленным расширением и нажать `Сгенерировать через расширение`.

Перед запуском визуального режима всегда проверяйте, что второй worker не активен:

```text
GET /api/flow/visual/status
GET /api/extension/status
```

## Каналы, Серии И Стили

Интерфейс автоматически сканирует:

```text
D:\MyChannelsIRL
```

Каждая папка первого уровня считается каналом:

```text
D:\MyChannelsIRL\erifan
D:\MyChannelsIRL\history
D:\MyChannelsIRL\jiang
```

Внутри канала каждая папка серии ведет к рабочей папке:

```text
D:\MyChannelsIRL\<channel>\<series>\frames
```

Если добавить новый канал в `D:\MyChannelsIRL`, он появится в UI автоматически. Если для него еще нет собственного стиля, будет использован базовый универсальный стиль.

Текущие стили:

- `erifan_garden` для `erifan`;
- `history_documentary` для реалистичных историко-природных сюжетов;
- `history_mystery` для легкой исторической загадочности;
- `jiang_geopolitics` для политики, геополитики, карт, досок, схем и стратегических визуализаций.

Стили лежат в:

```text
channels\*.json
```

Чтобы привязать стиль к папке канала, используйте поле:

```json
{
  "library_channel_id": "history"
}
```

Один канал может иметь несколько стилей. Они появятся в селекторе `Стиль канала`.

## Подготовка Промптов

В блоке подготовки сценария оставлены две основные кнопки:

- `Проверить сценарий` — читает `sentences.json`, показывает выбранный диапазон, пути, статусы промптов и количество `.mp4`;
- `Сгенерировать все промпты` — догенерирует все отсутствующие промпты и сохранит их в `veo_prompts.json`.

Старые кнопки `Сгенерировать следующую пачку` и `Сгенерировать текущий диапазон` убраны из видимого интерфейса, чтобы не путать основной рабочий поток.

## Файловая Модель

Рабочая папка проекта:

```text
<frames>
```

Внутри нее:

```text
sentences.json
veo_prompts.json
clip_0000.mp4
clip_0001.mp4
_flow_veo_studio\
```

Назначение:

- `sentences.json` — исходные фрагменты сценария, массив объектов с `index` и `text`;
- `veo_prompts.json` — локальная очередь промптов и их статусы;
- `clip_####.mp4` — итоговые скачанные видео;
- `_flow_veo_studio\downloads` — служебные загрузки и невалидные файлы;
- `_flow_veo_studio\duplicate_downloads` — старые дубликаты;
- `_flow_veo_studio\flow_scan.json` и `flow_scan.png` — диагностика страницы Flow;
- `_flow_veo_studio\visual_job_status.json` — состояние фонового worker;
- `_flow_veo_studio\visual_job_stop.flag` — флаг остановки;
- `_flow_veo_studio\visual_worker.out.log` и `visual_worker.err.log` — логи worker;
- `_flow_veo_studio\veo_prompts.before_*.json` — safety backups.

Финальные клипы сохраняются прямо в `<frames>`, не в отдельную папку.

## Формат `veo_prompts.json`

Пример элемента:

```json
{
  "index": 0,
  "source_text": "...",
  "title_slug": "seasoned_gardener_reflects_in_summer_plot",
  "flow_title": "000_seasoned_gardener_reflects_in_summer_plot",
  "veo_prompt": "#000, extreme close-up ... no music, no dialogue, no voiceover.",
  "status": "downloaded",
  "attempts": 1,
  "downloaded_path": "D:\\MyChannelsIRL\\erifan\\18\\frames\\clip_0000.mp4"
}
```

Маркер `#000` в начале `veo_prompt` обязателен. Flow может менять порядок карточек, поэтому локальный `index` остается источником истины.

Статусы:

- `prompt_ready` — промпт готов к отправке;
- `submitted` — промпт отправлен в Flow и ждет генерации/скачивания;
- `downloaded` — итоговый mp4 есть на диске;
- `failed` — финальные повторы исчерпаны или ошибка необратима; такие промпты нужно переписать вручную или сбросить позже вручную.

## Google Flow

Current state as of 2026-05-03:

- The supported visual generation path is `Сгенерировать через расширение` in the normal browser profile with the unpacked `Flow Veo Studio Bridge` extension.
- The old Chrome/CDP path (`Открыть Flow`, manual CDP submit/download/scan, `Сгенерировать визуал`) has been retired from the main UI.
- Retired Chrome/CDP API endpoints return `410 Gone`: `/api/flow/open`, `/api/flow/current-url`, `/api/flow/submit-batch`, `/api/flow/scan`, `/api/flow/download-visible`, `/api/flow/download-all`, `/api/flow/visual/start`.
- `GET /api/flow/visual/status` and `POST /api/flow/visual/stop` remain only for inspecting/stopping leftover legacy worker state.
- Use the extension flow: save/paste the Flow project URL in the UI, open that project in Yandex Browser with the extension installed, then click `Сгенерировать через расширение`.

Есть один основной режим визуальной автоматизации:

- `Сгенерировать через расширение` — основной рабочий режим для обычного браузера пользователя, сейчас используется через Яндекс Браузер.

Перед визуалом:

1. Вставить или сохранить URL проекта Flow в локальном UI.
2. Открыть этот проект в обычном браузере с установленным расширением.
3. Нажать `Сгенерировать через расширение`.
4. Не трогать вкладку Flow, пока расширение отправляет промпты и скачивает клипы.

Старые кнопки `Открыть Flow`, `Зафиксировать текущий URL`, `Отправить готовую пачку`, `Скачать готовые с прокруткой`, `Сканировать Flow` и `Сгенерировать визуал` больше не являются основным workflow и убраны из UI.

## Browser Extension

Расширение лежит в проекте:

```text
C:\Users\oldje\Documents\flow-veo-studio\browser_extension
```

Режим расширения подключает локальный сервер к обычной вкладке Flow в обычном профиле браузера. Это снижает риск `We noticed some unusual activity`, потому что Flow открыт не в отдельном CDP-профиле, а в нормальном пользовательском браузере. На 2026-04-26 рабочий вариант проверен через Яндекс Браузер.

Текущая версия расширения после фикса downloader-дублей, перезагрузки при Flow warning, отключения архивирования и разделения submit/download на ручные фазы: `0.2.2`. После любых правок в `browser_extension` нужно обновить карточку расширения в браузере и обновить вкладку Flow.

Установка в Яндекс Браузере:

1. Открыть `browser://extensions`.
2. Включить `Режим разработчика`.
3. Нажать `Загрузить распакованное расширение`.
4. Выбрать папку `browser_extension`.
5. Разрешить доступ к сайтам, если браузер спросит.

Обновление после правок:

1. Открыть `browser://extensions`.
2. На карточке `Flow Veo Studio Bridge` нажать обновление/перезагрузку расширения.
3. Проверить версию на карточке.
4. Обновить вкладку Flow через `Ctrl+R`.

Обычный workflow через расширение:

1. Запустить `run.bat` и открыть локальный UI.
2. Выбрать `channel -> series -> frames`.
3. Проверить сценарий и подготовить промпты.
4. Вставить/сохранить URL проекта Flow.
5. Открыть этот проект Flow в Яндекс Браузере с установленным расширением.
6. Нажать `Сгенерировать через расширение`.
7. Дождаться, пока расширение отправит все `prompt_ready`, затем в локальном UI или popup расширения нажать `Начать скачивание`.
8. После download-фазы в локальном UI или popup нажать `Регенерировать N` или `Завершить`, если останутся нескачанные индексы.
9. Не трогать вкладку Flow, пока идет активная отправка или скачивание.

Поведение расширения:

- расширение само подключается к открытой вкладке `https://labs.google/.../flow/project/...`;
- сервер хранит состояние режима в памяти и отдает очередь через `/api/extension/*`;
- перед стартом проверяется, что старый visual worker не активен;
- лимит пачки считается по свежим `submitted`, а старые `submitted` остаются в очереди поиска/скачивания Flow и не блокируют новые промпты бесконечно;
- отправка идет через фокус нижнего composer, `Ctrl+A`, настоящий `Input.insertText` и `Enter` через Chrome debugger API;
- расширение не кликает глобальные кнопки `Generate/Create/Создать/Сгенерировать`, потому что похожие кнопки есть на старых Flow-карточках;
- скачивание идет через media URL: расширение получает авторизованный media response в браузере и передает base64 на локальный сервер;
- локальный сервер сохраняет финальные файлы прямо в `<frames>\clip_####.mp4`.
- начиная с версии `0.1.4`, расширение не сопоставляет media URL по порядку кнопок; оно ищет media внутри ближайшей Flow-карточки с ровно одним маркером `#NNN`;
- начиная с версии `0.1.5`, расширение качает только индексы, которые сервер сейчас считает `submitted`, и сервер сверяет статусы с уже существующими `clip_####.mp4`;
- начиная с версии `0.1.6`, старые `submitted` больше не отправляются заново автоматически: они остаются в очереди поиска/скачивания Flow, новые промпты могут идти дальше, а расширение примерно раз в 3 минуты делает более широкий sweep по проекту Flow;
- начиная с версии `0.1.11`, page-level предупреждения Flow вроде `We noticed some unusual activity` больше не останавливают весь запуск: расширение сообщает серверу о предупреждении, перезагружает страницу Flow, ждёт 10 секунд после reload и автоматически продолжает работу, когда предупреждение исчезает;
- начиная с версии `0.1.14`, расширение перешло с `Удалить/Trash` на `Архив`; подтверждение больше не ожидается, потому что новый Flow архивирует карточку без диалога;
- начиная с версии `0.1.15`, скачивание и архивирование выполняются сразу на текущем видимом участке Flow до следующей прокрутки; это снижает лаги и не дает Flow виртуализировать уже найденные DOM-карточки до клика по архиву;
- начиная с версии `0.1.16`, архивирование выполняется только после нового успешного сохранения клипа в текущем проходе; `skipped_existing` и старые локальные `downloaded_indexes` не архивируются автоматически;
- начиная с версии `0.2.0`, основной цикл расширения сначала отправляет все готовые промпты батчами по 25 с паузами 1-2 секунды между отправками и 20-30 секунд между батчами, затем качает снизу вверх все доступные `submitted`, отдельным проходом архивирует только реально скачанные в этом проходе карточки, возвращает несохраненные на retry и повторяет до 3 циклов;
- начиная с версии `0.2.1`, архивирование полностью отключено: расширение только скачивает снизу вверх и помечает видимые error-карточки для retry/failed; обычные `submitted`, которые проход не скачал, больше не переводятся в `failed` автоматически;
- начиная с версии `0.2.2`, отправка и скачивание разделены на ручные фазы: расширение сначала отправляет все `prompt_ready`, затем ждет кнопку `Начать скачивание` в локальном UI или popup, после download-проходов ждет `Регенерировать N` или `Завершить`;
- при старте расширения auto-failed индексы с `flow_error=not_downloaded_after_cycle_*`, `final_not_generated` или `final_retry_exhausted` возвращаются в `prompt_ready`, чтобы исправить ложные failed из старой логики;
- регенерация выполняется только по кнопке popup и ограничена `regen_count < FLOW_EXTENSION_REGEN_MAX` (по умолчанию 2); после исчерпания лимита prompt переводится в `failed`;
- отсутствие карточки в Flow во время основного прохода не считается поводом сразу пересылать prompt; пересылка разрешена только в финальном recovery;
- сервер дополнительно проверяет SHA256 нового mp4: если такой же клип уже есть под другим `clip_####.mp4`, новый файл переносится в `_flow_veo_studio\duplicate_downloads` и не считается валидно скачанным.

Важный инцидент 2026-04-26: прежний extension downloader мог ошибочно скачать один и тот же Flow media под разными именами (`clip_0068.mp4`, `clip_0069.mp4`, `clip_0070.mp4` и другие). После фикса `0.1.4` уже созданные точные дубли были перенесены в `_flow_veo_studio\duplicate_downloads`, а их индексы возвращены в `prompt_ready`. Backup очереди перед cleanup:

```text
D:\MyChannelsIRL\erifan\19\frames\_flow_veo_studio\veo_prompts.before_duplicate_cleanup_20260426_151310.json
```

Во время работы расширения можно пользоваться другими программами. Саму вкладку Flow и окно браузера с Flow лучше не трогать. Самый безопасный вариант: Flow работает в отдельном окне Яндекс Браузера, а пользовательские дела идут в другом браузере или окне.

## Visual Worker

Legacy note: this Chrome/CDP visual worker is retired as of 2026-05-03. The main UI no longer exposes `Сгенерировать визуал`, and `POST /api/flow/visual/start` returns `410 Gone`. Keep this section only as historical/debugging context for old state files and cleanup.

`Сгенерировать визуал` запускает отдельный процесс:

```text
python -u app.py --visual-worker <project_path> <batch_count> <status_path> <stop_path> [flow_project_url]
```

Логика:

1. Открыть или переиспользовать Flow.
2. Если есть `submitted`, сначала скачать их.
3. Не отправлять новую пачку, пока `submitted > 0`.
4. Когда `submitted = 0`, отправить следующую пачку `prompt_ready`.
5. Подождать 60 секунд.
6. Скачать готовые клипы с прокруткой.
7. Повторять до завершения, паузы, stop-запроса или ошибки.

Остановка:

```text
POST /api/flow/visual/stop
```

Остановка не обрывает текущую операцию мгновенно; worker остановится после ближайшей безопасной точки.

## Chrome И Flow

Legacy note: the Chrome/CDP Flow path is retired for normal work. Do not use `start-flow-chrome.bat` or the CDP worker for new visual generation unless the user explicitly asks to revive old fallback behavior.

Старый fallback-режим Flow работает через внешний обычный Google Chrome по CDP. Основной рекомендуемый режим для текущих запусков — `Сгенерировать через расширение` в обычном Яндекс Браузере.

Параметры:

- CDP порт: `9223`;
- env override: `FLOW_CHROME_CDP_PORT`;
- Chrome user-data-dir: `%LOCALAPPDATA%\FlowVeoStudio\ChromeUserData`;
- env override: `FLOW_CHROME_USER_DATA_DIR`;
- запуск Chrome: `start-flow-chrome.bat`;
- старый `projects\flow_browser_profile` не использовать.

Fallback на Playwright Chrome/Chromium для Flow не нужен и не должен возвращаться.

## Downloader

Current supported downloader is the browser-extension downloader. The Chrome/CDP downloader notes below are retained only as historical context; do not restore click-based or ordinal extension mapping.

Обычный downloader работает через media URL, а не через клики по кнопкам скачивания:

1. Находит видимые Flow-карточки с download-кнопками.
2. Собирает media URL из `video`, `source`, `img`.
3. Убирает `mediaUrlType`.
4. Сопоставляет порядок карточек и media URL.
5. Скачивает через `self.context.request.get(media_url)`.
6. Сохраняет MP4 или распаковывает MP4 из ZIP.
7. Пишет файл как `<frames>\clip_####.mp4`.
8. Валидные существующие MP4 пропускает.
9. Невалидные целевые файлы переносит в service folder.

Это защищает от старой проблемы, когда click-based downloader попадал в `redo / Использовать текстовый запрос повторно` и вставлял старый prompt в поле Flow.

Extension downloader использует тот же итоговый контракт файлов, но получает media bytes из обычного браузера через расширение. Это нужно, потому что прямой запрос локального сервера к Flow media URL может получить `401 Unauthorized`, если не передать браузерную авторизацию.

Для extension downloader нельзя возвращать ordinal-маппинг вида "N-я download-кнопка = N-й media URL": Flow DOM может менять порядок карточек, кнопок и media-элементов. Корректный путь: искать ближайшую карточку с одним `#NNN`, брать media URL внутри нее, затем проверять mp4-хэш на сервере.

## API

Health/library:

```text
GET /api/health
GET /api/channels
GET /api/library
GET /api/flow/status
```

Project/prompt:

```text
POST /api/sentences/preview
POST /api/project/status
POST /api/prompts/generate
POST /api/channel/save
```

Flow:

```text
POST /api/flow/queue
```

Visual worker:

```text
GET  /api/flow/visual/status
POST /api/flow/visual/stop
```

Retired Flow/Chrome-CDP endpoints returning `410 Gone`:

```text
POST /api/flow/open
POST /api/flow/current-url
POST /api/flow/submit-batch
POST /api/flow/scan
POST /api/flow/download-visible
POST /api/flow/download-all
POST /api/flow/visual/start
```

Browser extension:

```text
GET  /api/extension/status
GET  /api/extension/unresolved
POST /api/extension/start
POST /api/extension/stop
POST /api/extension/connect
POST /api/extension/next-prompt
POST /api/extension/phase-action
POST /api/extension/audio-cue/ack
POST /api/extension/report-phase-done
POST /api/extension/mark-submitted
POST /api/extension/download-media
POST /api/extension/flow-error
```

## Разработка

Важные файлы:

- `app.py` — HTTP API, скан библиотеки, очередь, OpenAI, browser-extension orchestration, и guard для retired Chrome/CDP endpoints;
- `src\flow_automation.py` — legacy Playwright/CDP automation, оставлен для справки/cleanup; не основной путь визуальной генерации;
- `browser_extension\manifest.json`, `content.js`, `background.js` — мост расширения между обычной вкладкой Flow и локальным сервером;
- `web\index.html`, `web\app.js`, `web\styles.css` — локальный UI;
- `channels\*.json` — стили каналов и дефолты;
- `run.bat` — запуск сервера и UI.

Проверка:

```powershell
python -m py_compile app.py src\flow_automation.py
node --check web\app.js
```

OpenAI API key должен быть в переменной окружения Windows:

```text
OPENAI_API_KEY
```

Проект сейчас не является git repository, поэтому перед широкими изменениями нужна особая аккуратность.

## Следующие Улучшения

- сделать статус extension-режима еще понятнее;
- добавить режим `тест: один prompt`;
- добавить редактирование/сохранение стилей из UI, если понадобится;
- улучшить подсказки для каналов без собственного стиля;
- показывать последние скачанные/возвращенные индексы;
- решить, оставлять `clip_####.mp4` или переходить на `<flow_title>.mp4`;
- улучшить диагностику extension scan/download.
