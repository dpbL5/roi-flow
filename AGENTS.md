# Flow Veo Studio

## Context

User language: Russian.

Project root:

```text
C:\Users\oldje\Documents\flow-veo-studio
```

Launch file:

```text
C:\Users\oldje\Documents\flow-veo-studio\run.bat
```

Local app:

```text
http://127.0.0.1:8765
```

Content library root:

```text
D:\MyChannelsIRL
```

Current reference project:

```text
D:\MyChannelsIRL\erifan\18\frames
```

The UI supports selecting `channel -> series -> frames` from `D:\MyChannelsIRL`. The active project path should still be the `frames` folder, not a specific `sentences.json` file. Generated prompts and final downloaded clips must live directly in that same `frames` folder.

Configured channel styles:

- `erifan_garden` for folder `erifan`;
- `history_documentary` and `history_mystery` for folder `history`;
- `jiang_geopolitics` for folder `jiang`;
- folders without a config still appear in the UI with a generic fallback style.

## Current Operating State

Most recent documentation cleanup: 2026-05-03.
Most recent UI/library update: 2026-04-26.
Most recent browser-extension visual mode update: 2026-04-26.
Most recent browser-extension downloader duplicate fix: 2026-04-26 (`Flow Veo Studio Bridge` version `0.1.4`).
Most recent browser-extension queue speed/recovery fix: 2026-04-26 (`Flow Veo Studio Bridge` version `0.1.5`).
Most recent browser-extension Flow search/sweep fix: 2026-04-26 (`Flow Veo Studio Bridge` version `0.1.6`).
Most recent browser-extension final retry fix: 2026-04-26 (`Flow Veo Studio Bridge` version `0.1.6`).
Most recent old Chrome/CDP UI retirement: 2026-05-03.
Most recent browser-extension Flow-warning reload fix: 2026-05-03 (`Flow Veo Studio Bridge` version `0.1.11`).
Most recent browser-extension no-archive submit/download loop: 2026-05-06 (`Flow Veo Studio Bridge` version `0.2.1`).
Most recent browser-extension manual submit/download phase split: 2026-05-06 (`Flow Veo Studio Bridge` version `0.2.2`).

The automation may be actively running. Before starting or changing a visual job, always check:

```text
GET /api/flow/visual/status
GET /api/extension/status
```

Do not start a second visual worker while one is active. The old Chrome/CDP visual path has been retired from the main UI and its start/open/scan/download endpoints return `410 Gone`; use the browser-extension visual mode. Use UI `Остановить расширение`, or:

```text
POST /api/extension/stop
```

Current Flow project URL for the reference erifan project:

```text
https://labs.google/fx/ru/tools/flow/project/cf31982c-f9c1-4429-8f72-e6a5238cfc73
```

Reference project facts from the last completed erifan run:

- total prompts: 261;
- `downloaded`: 261;
- `submitted`: 0;
- `prompt_ready`: 0;
- `failed`: 0;
- root `frames` folder has 261 `.mp4` files;
- counts can change in future runs; use live status/queue before acting;
- final files are currently named `clip_0000.mp4`, `clip_0001.mp4`, etc.;
- `flow_title` remains in `veo_prompts.json`, but current downloader uses `clip_####`;
- root `frames` folder should not contain `*_flow_clip.mp4` as normal output.

Current erifan 19 duplicate-cleanup facts from 2026-04-26:

- project: `D:\MyChannelsIRL\erifan\19\frames`;
- extension downloader bug produced exact duplicate mp4 files under different `clip_####.mp4` names;
- examples included `clip_0068.mp4`, `clip_0069.mp4`, `clip_0070.mp4`;
- 29 duplicate mp4 files from 16 duplicate-hash groups were moved to `_flow_veo_studio\duplicate_downloads`;
- affected indexes were returned to `prompt_ready`;
- backup before cleanup: `D:\MyChannelsIRL\erifan\19\frames\_flow_veo_studio\veo_prompts.before_duplicate_cleanup_20260426_151310.json`;
- post-cleanup check found no duplicate SHA256 groups among root `clip_*.mp4`;
- after cleanup at that moment: root `frames` had 37 mp4 files, queue counts were `downloaded=37`, `submitted=20`, `prompt_ready=157`, `failed=0`;
- after later extension-mode progress at the latest documentation update: root `frames` had 208 mp4 files, queue counts were `downloaded=208`, `submitted=6`, `prompt_ready=0`, `failed=0`;
- the remaining submitted indexes at that moment were `144`, `176`, `186`, `189`, `207`, `211`; these may be retried by final recovery or later marked `failed`;
- counts can change after future runs; always use live status/queue before acting.

## Current Workflow

1. Run `run.bat`.
2. Open/check `http://127.0.0.1:8765`.
3. Choose a channel folder from `D:\MyChannelsIRL`.
4. Choose a series folder; UI auto-fills `<channel>\<series>\frames`.
5. Choose `Стиль канала` if the channel has more than one style.
6. Use `Проверить сценарий` to validate `sentences.json`, prompt status counts, mp4 count, and target paths.
7. Use `Сгенерировать все промпты` only when the user explicitly wants prompt generation.
8. Do not generate more prompts unless the user asks.
9. Paste/save the Flow project URL in the local UI.
10. Open that Flow project in the normal browser profile where the unpacked extension is installed, currently tested through Yandex Browser.
11. Click `Сгенерировать через расширение`.
12. Use `Остановить расширение` to request a pause after the current operation.
13. Do not use the retired old Chrome/CDP path for new visual jobs.

Manual fallback:

The old local UI buttons for opening Flow through Chrome/CDP, submitting a batch, scanning Flow, downloading through Playwright/CDP, and `Сгенерировать визуал` were removed from the main interface on 2026-05-03. The corresponding retired API endpoints now return `410 Gone`.

1. Use Flow manually in the normal browser if needed.
2. Wait for Flow generation.
3. Let the extension scan/download generated clips, or download manually and sync local files.

`Сканировать Flow` in the old Chrome/CDP path is retired.

Prompt-preparation UI intentionally exposes only two main actions:

- `Проверить сценарий`;
- `Сгенерировать все промпты`.

Older buttons for next batch/current range were removed from the visible UI.

## Library And Styles

`GET /api/library` scans the library root and returns channel folders, series folders, and style configs.

Defaults:

```text
FLOW_VEO_LIBRARY_ROOT=D:\MyChannelsIRL
```

Rules:

- first-level folders under `D:\MyChannelsIRL` are channels;
- subfolders under a channel are series;
- selected series resolves to `<series>\frames`;
- new channel folders should appear without code changes;
- channels without custom configs use a generic fallback style;
- channel style configs live in `channels/*.json`;
- `library_channel_id` maps a style config to a channel folder;
- one channel can have multiple styles, shown in `Стиль канала`;
- keep style prompt text in channel config files, not hardcoded in Python.

Current style files:

- `channels\erifan_garden.json`;
- `channels\history_documentary.json`;
- `channels\history_mystery.json`;
- `channels\jiang_geopolitics.json`.

## Core Data Contract

Generated prompts are saved in:

```text
<frames>\veo_prompts.json
```

Example:

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

The `#000` style marker inside `veo_prompt` is mandatory. Google Flow can reorder cards; local `index` is the source of truth.

Statuses:

- `prompt_ready`: generated locally and ready to send;
- `submitted`: sent to Flow and waiting for generation/download;
- `downloaded`: final mp4 exists;
- `failed`: final retry exhausted or unrecoverable; these prompts need manual rewrite or later manual reset.

## Important Files

- `app.py`: HTTP API, library scan, queue state, OpenAI prompt generation, browser-extension orchestration. The retired Chrome/CDP API paths are still present as guarded legacy code and return `410 Gone` for new UI/API calls.
- `src\flow_automation.py`: retired Playwright/CDP automation code kept for reference only; do not use it for new Flow work unless the user explicitly asks to resurrect a fallback.
- `browser_extension\manifest.json`, `browser_extension\content.js`, `browser_extension\background.js`: unpacked browser extension bridge for the normal user browser Flow tab.
- `web\app.js`, `web\index.html`, `web\styles.css`: local UI.
- `channels\*.json`: channel style presets and defaults.
- `run.bat`: starts server and opens UI unless called with `--no-open`.

Service folder:

```text
<frames>\_flow_veo_studio
```

Key service files:

- `downloads\`: raw media downloads and bad target files;
- `duplicate_downloads\`: old duplicate click-downloaded files;
- `flow_scan.json`, `flow_scan.png`: diagnostic scan output;
- `visual_job_status.json`: persisted worker status;
- `visual_job_stop.flag`: stop request flag;
- `visual_worker.out.log`, `visual_worker.err.log`: worker subprocess logs;
- `veo_prompts.before_*.json`: safety backups.

## Retired Chrome/CDP Flow Path

The old external Google Chrome/CDP automation path is retired as of 2026-05-03. Do not start it for normal visual generation.

Retired endpoints that now return `410 Gone`:

```text
POST /api/flow/open
POST /api/flow/current-url
POST /api/flow/submit-batch
POST /api/flow/scan
POST /api/flow/download-visible
POST /api/flow/download-all
POST /api/flow/visual/start
```

`GET /api/flow/visual/status` and `POST /api/flow/visual/stop` remain available only to inspect/stop any leftover legacy worker state.

Historical notes below are kept only for context.

Flow automation used external regular Google Chrome through CDP. Do not fall back to Playwright Chrome/Chromium for Flow work.

Chrome/CDP:

- browser label should be `Google Chrome (external regular profile via CDP)`;
- default CDP port is `9223`;
- dedicated user-data-dir defaults to `%LOCALAPPDATA%\FlowVeoStudio\ChromeUserData`;
- `FLOW_CHROME_USER_DATA_DIR` may override user-data-dir;
- `FLOW_CHROME_CDP_PORT` may override port;
- `start-flow-chrome.bat` starts Chrome for Flow;
- optional profile: `start-flow-chrome.bat "Profile 1"`;
- legacy `projects\flow_browser_profile` is a bad old profile and must not be used.

While automation runs, the user may use other apps/browsers, but should not touch the Flow Chrome window: do not close it, switch projects, type into it, or click Flow buttons.

If Flow shows unsupported country or reCAPTCHA/connectivity issues, check VPN/region and the regular Chrome profile.

## Browser Extension Mode

`Сгенерировать через расширение` is the preferred current visual mode when the user can open Flow in a normal trusted browser profile. It was added on 2026-04-26 and has been tested successfully in Yandex Browser.

Current extension version: `0.2.2`. Version `0.1.4` fixes the duplicate-download bug by changing card/media matching and adding server-side duplicate hash rejection. Version `0.1.11` keeps extension mode running when Flow shows a page-level warning such as `We noticed some unusual activity`: the content script reports the warning, reloads the Flow page, waits 10 seconds after reload via `sessionStorage`, and resumes automatically if the warning disappears. Version `0.2.1` disables Flow archiving entirely; submitted cards are not marked `failed` just because a scan missed them. Version `0.2.2` splits extension mode into manual phases: submit all `prompt_ready`, wait for popup `Начать скачивание`, run up to 5 download passes, then wait for popup `Регенерировать N` or `Завершить`. On extension start, prompts auto-failed by the retired `not_downloaded_after_cycle_*` / `final_not_generated` / `final_retry_exhausted` logic are revived to `prompt_ready`. After any extension code change, the browser extension card must be reloaded and the Flow tab refreshed with `Ctrl+R`.

Extension folder:

```text
C:\Users\oldje\Documents\flow-veo-studio\browser_extension
```

Install/update in Yandex Browser:

1. Open `browser://extensions`.
2. Enable `Режим разработчика`.
3. Use `Загрузить распакованное расширение`.
4. Select `C:\Users\oldje\Documents\flow-veo-studio\browser_extension`.
5. After code changes, reload the extension card and refresh the Flow tab with `Ctrl+R`.

Operating rules:

- The user opens the correct Flow project in the normal browser tab.
- The local UI starts extension mode through `POST /api/extension/start`.
- The extension connects from the Flow tab through `POST /api/extension/connect`.
- The server exposes the same `veo_prompts.json` queue through `/api/extension/*`.
- Do not run extension mode and the old Chrome/CDP visual worker at the same time.
- If an old visual worker is somehow still active, extension start should be blocked until it is stopped; otherwise use extension mode only.
- While extension mode runs, the user may use other programs, but should not touch the Flow tab or browser window that contains Flow.
- Safest setup: Flow in a separate Yandex Browser window; normal work in another browser/window.

Extension queue/recovery behavior (version `0.2.2`, manual no-archive submit/download phases):

1. The server syncs queue state from local `clip_####.mp4` files before issuing new work.
2. **Submit all:** the extension sends all currently ready prompts through `/api/extension/next-prompt` in batches of 25. It waits 1-2 seconds between prompts, occasionally clicks an empty screen area, and waits 20-30 seconds between batches.
3. When `prompt_ready=0` and submitted clips remain, the server enters `awaiting_download`, sets audio cue `submit_done`, and the local UI plus popup show `Начать скачивание`. The content script sleeps in this phase.
4. `Начать скачивание` calls `/api/extension/phase-action` with `start_download`; the extension enters `downloading`.
5. **Download bottom-up:** the extension runs up to 5 full bottom-up passes, 20 seconds apart, and stops early after 2 consecutive passes without downloaded-count progress.
6. If unresolved prompts remain after download, the server enters `awaiting_regen`, sets audio cue `download_done`, and the local UI plus popup show `Регенерировать N` / `Завершить`.
7. `Регенерировать N` increments per-prompt `regen_count`, returns regenerable unresolved prompts to `prompt_ready`, and starts a new submit phase. Default cap: `FLOW_EXTENSION_REGEN_MAX=2`; exhausted prompts become `failed`.
8. If everything is downloaded or the user completes, the server enters `completed` and sets audio cue `all_done`.
9. If Flow shows a page-level warning (`We noticed some unusual activity`, reCAPTCHA/region-like warning), the extension reports it, reloads the page, waits 10 seconds, and resumes the previous phase.
10. The extension does not click `Архив`, `Удалить`, or any Flow cleanup action. Downloaded cards remain in Flow.
11. Visible generation-error cards are marked through `/api/extension/mark-retry-failed`; submitted cards still not downloaded after a pass stay unresolved for the manual regen decision instead of being auto-failed.
12. On start, false failed prompts from the retired auto-fail logic are revived to `prompt_ready` before queue counts are used.

Default env variables:

- extension content-script batch size is 25 prompts per submit batch.
- `FLOW_EXTENSION_REGEN_MAX=2` — manual regeneration cap per prompt.

Extension submit behavior:

1. Find the bottom Flow composer.
2. Focus/click the composer through debugger-assisted input.
3. Select old text with `Control+A`.
4. Insert prompt with Chrome debugger `Input.insertText`.
5. Submit with real `Enter`.
6. Do not click global submit/generate buttons; Flow card buttons are visually similar and can cause wrong actions.
7. If Flow says the prompt is empty or the prompt remains in the composer, pause/error rather than marking it submitted.

Extension downloader behavior:

1. Find visible Flow cards with download controls and `#NNN` prompt markers.
2. For extension version `0.1.4+`, do not map by ordinal button/media order. The previous ordinal mapping caused the same media to be saved as several different `clip_####.mp4` files.
3. Find the nearest card/container that contains exactly one `#NNN`.
4. Collect the media URL from `video`, `source`, or thumbnail `img` elements inside that same card/container.
5. Remove `mediaUrlType`.
6. Fetch media bytes inside the extension/background context with browser authorization.
7. Send base64 media payload to `POST /api/extension/download-media`.
8. Server saves MP4 or extracts MP4 from ZIP to `<frames>\clip_####.mp4`.
9. Server checks SHA256 against existing root `clip_*.mp4`; exact duplicate media is moved to `_flow_veo_studio\duplicate_downloads` and rejected as a valid download.
10. Existing valid MP4 files are skipped; invalid target files are moved aside under `_flow_veo_studio\downloads`.
11. For version `0.1.6+`, the extension also performs periodic project sweeps for `search_indexes` instead of relying only on the currently visible cards.
12. Do not treat a missing Flow card as proof that a prompt should be resent during the main queue; resubmission is allowed only in final recovery when `prompt_ready=0`.

Why browser-side fetch is required: direct server-side media URL fetch can return `401 Unauthorized` because the local Python process does not have the browser's Flow/Google authorization context.

Never restore extension downloader logic that assumes "N-th download button equals N-th media URL". Flow DOM ordering is not reliable enough for that.

## Submit Behavior

This is the current working path and should be preserved.

`src\flow_automation.py::submit_prompt()`:

1. Find the bottom Flow composer, usually by placeholder `Что вы хотите создать?` / `What do you want to create?`.
2. Click the prompt input.
3. Select old text with real keyboard events: `Control+A`.
4. Paste through clipboard `writeText` + `Control+V`.
5. Fall back to `keyboard.insert_text` if clipboard fails.
6. Use `locator.fill(prompt)` only as last-resort recovery.
7. Submit with plain `Enter` from the focused prompt input.
8. If the prompt text remains in the input, pause and do not mark it as `submitted`.

Do not restore global button-click submit selectors for `Generate`, `Create`, `Создать`, `Сгенерировать`, etc. Those labels also appear on old Flow cards and already caused clicks on repeat/reuse controls instead of submitting a new prompt.

Submit exceptions are pause-worthy. Do not blindly loop-retry every 10 seconds.

Keep short random pauses between focus/select/paste/submit. Do not solve unusual activity primarily by long cooldowns or shrinking batch size unless the user explicitly changes the speed/safety priority.

## Legacy Visual Worker

Legacy only. The `Сгенерировать визуал` UI button was removed on 2026-05-03 and `/api/flow/visual/start` now returns `410 Gone`. This section documents old behavior for reference and cleanup/debugging only.

Historically, `Сгенерировать визуал` started:

```text
python -u app.py --visual-worker <project_path> <batch_count> <status_path> <stop_path> [flow_project_url]
```

The job:

1. opens/reuses Flow;
2. if any prompts are `submitted`, downloads those first;
3. never submits a new batch while `submitted > 0`;
4. when `submitted = 0`, sends the next `prompt_ready` batch;
5. waits 60 seconds;
6. downloads with scroll;
7. repeats until no work remains or it pauses/stops/errors.

Retry policy:

- downloadable `submitted` clips are saved and marked `downloaded`;
- if Flow no longer shows submitted clips, they return to `prompt_ready`;
- if Flow shows a submitted card but it cannot be downloaded after the short retry path, it also returns to `prompt_ready` with `flow_error = "stuck_in_flow_download"`;
- this is intentional: the user prefers fast regeneration over waiting repeatedly for broken/missing Flow material.

Blocking states:

- `We noticed some unusual activity`;
- Russian unusual-activity variants;
- unsupported-country Flow page;
- reCAPTCHA/connectivity warnings;
- browser/page closed;
- wrong Flow project URL.

Recovery is capped at 5 minutes. If the blocker remains, the job pauses.

## Downloader

Legacy Chrome/CDP download actions are retired from the main UI. The extension downloader is the supported path. Historical Chrome/CDP downloader notes below are kept only to explain why click-based downloading must not be restored.

Normal legacy UI download actions used `download_visible_from_media_src` / `download_all_visible_with_scroll`, not old click-based `download_visible`.

Reliable download approach:

1. find visible Flow cards with download buttons;
2. collect Flow media URLs from hidden `video`, `source`, or thumbnail `img` elements;
3. map visible card ordinal to media URL ordinal;
4. remove `mediaUrlType`;
5. fetch with `self.context.request.get(media_url)`;
6. save actual MP4, or unpack MP4 from ZIP if Flow returns ZIP;
7. name output as `clip_####.mp4`;
8. skip existing valid MP4 files;
9. move invalid existing targets aside before redownloading.

This avoids click-based download accidentally hitting `redo / Использовать текстовый запрос повторно` and putting old prompts into the Flow prompt box.

This ordinal media mapping note applies to the old CDP/Playwright downloader. The browser-extension downloader must not use global ordinal mapping; it must match media inside the nearest single-`#NNN` Flow card and then rely on server-side SHA256 duplicate rejection.

## Current Behavior To Preserve

- Final clips go directly into `<frames>`.
- Service files go into `<frames>\_flow_veo_studio`.
- Raw media downloads go into `<frames>\_flow_veo_studio\downloads`.
- Duplicate downloads go into `<frames>\_flow_veo_studio\duplicate_downloads`.
- Existing valid MP4 files are skipped.
- Existing invalid target files are moved aside under the service folder before redownloading.
- Extension downloads must reject exact duplicate SHA256 media under different `clip_####` names.
- Extension mode uses manual no-archive phases: send all ready prompts in batches of 25, wait for popup `Начать скачивание`, then scan/download unresolved cards bottom-up.
- Error cards (no media, error text) are marked through `mark-retry-failed` and wait for the manual regen decision; per-prompt `regen_count` is capped by `FLOW_EXTENSION_REGEN_MAX`.
- Downloaded cards are not archived or deleted from Flow.
- Retry should not repeat the same index in a tight loop and should not consume the download count limit.
- Reopening Flow after the user closes the browser/tab should create/reuse a valid Playwright page/context without sync-inside-async errors.
- The retired `Сгенерировать визуал` path must not be restored as the main workflow.
- Flow page-level warnings must not stop the extension run; extension mode should reload the Flow page, wait 10 seconds after reload, and resume automatically.
- Captured/saved Flow project URL must be respected; if the extension is in the wrong project tab, it should pause as `wrong_project`.
- `GET /api/library` should remain generic and should not require code edits for every new channel folder.

## Development Rules

- Keep channel-specific style in `channels/*.json`, not hardcoded in Python.
- Use `library_channel_id` when a style config belongs to a folder whose name differs from the style id.
- Keep generated project state beside the source script folder when a `frames` path is provided.
- Use `<frames>` itself as the final clip folder.
- Do not put API keys in this repository. Use Windows environment variable `OPENAI_API_KEY`.
- Prefer structured JSON output from the model instead of parsing chat-like text.
- When testing Flow/Playwright on this machine, server/browser commands may need elevated execution outside the sandbox.
- The project directory is currently not a git repository; use extra care before broad edits.

## API Notes

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
GET  /api/flow/visual/status
POST /api/flow/visual/stop
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

Retired Flow endpoints that return `410 Gone`:

```text
POST /api/flow/open
POST /api/flow/current-url
POST /api/flow/submit-batch
POST /api/flow/scan
POST /api/flow/download-visible
POST /api/flow/download-all
POST /api/flow/visual/start
```

## Next Improvements

Likely next work is UI/UX, style management, or small workflow refinements, not core recovery:

- make extension mode status/actions clearer and add recent downloaded/submitted indexes;
- add a `test one prompt` mode;
- add style editing/saving from UI if needed;
- improve handling for channels with no custom style;
- show recent downloaded/reset indexes in UI;
- improve status/next-action text;
- decide whether to keep `clip_####.mp4` or switch to `<flow_title>.mp4`;
- improve extension scan/download diagnostics if needed.

## Before Acting

1. Check `/api/flow/visual/status`.
2. Check `/api/extension/status`.
3. If any visual mode is active, do not launch another one; old Chrome/CDP should not be used for new work.
4. Confirm the selected UI path is the intended `<channel>\<series>\frames`.
5. Confirm Flow is in the intended project.
6. Confirm VPN/region if Flow shows unsupported country.
7. Verify submit still targets the bottom composer and sends with `Enter`.
8. Verify downloader does not insert prompts into the Flow prompt box.
9. Verify final MP4 files appear directly in `frames`.
