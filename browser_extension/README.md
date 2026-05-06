# Flow Veo Studio Bridge

Unpacked browser extension for running Flow automation inside a normal user browser profile. The current working setup is Yandex Browser.

Current version: `0.2.2`.

Install or update in Yandex Browser:

1. Open `browser://extensions`.
2. Enable developer mode / `Режим разработчика`.
3. Click load unpacked / `Загрузить распакованное расширение`.
4. Select this `browser_extension` folder.
5. Allow site permissions if the browser asks.
6. After updates, reload this extension card and refresh the Flow tab with `Ctrl+R`.

Runtime:

- Keep `http://127.0.0.1:8765` running.
- Open the target Flow project tab in the browser where the extension is installed.
- Start and stop the mode from the local Flow Veo Studio UI.
- Use the extension popup to move from submit to download, then from download to regenerate or complete.
- Do not touch the Flow tab while the extension is submitting/downloading.

Implementation notes:

- Submit uses debugger-assisted `Control+A`, `Input.insertText`, and `Enter`.
- The extension does not click global submit/generate buttons.
- Downloads fetch authorized media bytes in the browser extension context and send them to the local server, which writes `<frames>\clip_####.mp4`.
- Downloader version `0.1.4+` matches media inside the nearest Flow card with exactly one `#NNN`; do not use ordinal matching between download buttons and media URLs.
- Version `0.1.5` filters downloads to currently submitted indexes and syncs server state from existing local `clip_####.mp4` files.
- Version `0.1.6` stops resubmitting timed-out prompts during the main queue; older submitted items stay in the Flow search/download queue, and the content script performs a project sweep roughly every 3 minutes.
- Version `0.1.11` keeps the extension run alive when Flow shows a warning such as `We noticed some unusual activity`: the extension reports the warning, reloads the Flow page, waits 10 seconds after reload, and then continues automatically instead of stopping the job.
- Version `0.1.14` uses Flow's current Archive action. Archive replaces the removed Delete/Trash action and does not require a confirmation dialog.
- Version `0.1.15` archives cards while they are still visible during the scroll pass and adds a positional fallback for icon-only Archive buttons near the download/reuse controls.
- Version `0.1.16` archives only after a newly saved download. It does not archive `skipped_existing` cards or old local `downloaded_indexes`, and processes downloads one card at a time to avoid Flow DOM lag.
- Version `0.2.0` changes the main run shape: submit all ready prompts in batches of 25 with 1-2 second gaps and 20-30 second waits between batches, then download bottom-up, then archive only cards downloaded in that pass. Not-downloaded prompts are retried for up to 3 full cycles, then unresolved prompts are marked `failed`.
- Version `0.2.1` disables archiving entirely. It no longer marks not-downloaded submitted cards as failed just because a scan missed them.
- Version `0.2.2` splits the run into manual phases: submit all ready prompts first, wait for the popup button to start downloading, run up to 5 download passes, then wait for a manual regenerate or complete action. Regeneration is capped by `FLOW_EXTENSION_REGEN_MAX` (default `2`) through per-prompt `regen_count`.
- On start, the local server revives prompts falsely failed by the retired auto-fail logic (`not_downloaded_after_cycle_*`, `final_not_generated`, `final_retry_exhausted`) back to `prompt_ready`.
- The local server rejects exact duplicate mp4 SHA256 hashes and moves duplicate files to `_flow_veo_studio\duplicate_downloads`.
