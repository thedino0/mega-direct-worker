# MEGA Worker Bot Progress

Last updated: 2026-10-27

## Phase 1 - Link resolution and file listing - complete

- Added the protected `POST /bot/resolve` worker endpoint with `X-Key` authentication.
- Added a Python aiogram bot that talks to a local Telegram Bot API server.
- The bot accepts public MEGA file and folder links and returns file names, sizes, and folder contents.
- Added owner-only message handling, startup validation for the local API server, and log redaction.
- Verified worker auth responses, fake local API behavior, real worker resolution, real MEGA file and folder links, startup failures, and secret redaction.
- Phase 1 was published on branch `python-bot-phase-1`.

## Phase 2 - Inline picker and small downloads - complete

- Added an inline keyboard file picker for folders.
- Added pagination with six files per page and Previous/Next buttons.
- Added a 20-minute in-memory menu cache with per-user ownership checks.
- Added a configurable download cap through `MAX_DOWNLOAD_MB` (default: 100 MB).
- Added streaming downloads to `TEMP_DIR`, safe output filenames, and cleanup after success or failure.
- Added file upload through the local Bot API with download, upload, and cleanup logging.
- Added native media delivery for photos (JPG/JPEG/PNG), GIF animations, videos (MP4/M4V/MOV/WEBM/MKV/AVI), audio (MP3/M4A/AAC/FLAC/WAV), voice notes (OGG/OPUS/OGA), and stickers (WEBP/TGS).
- Added automatic document fallback when Telegram rejects a media type or a file exceeds the media method limit.
- Added a clear alert for files above the phase 2 limit.
- Verified the picker, callback flow, pagination, over-limit alert, media method dispatch, document fallback, and temp cleanup with a fake local Bot API.
- Verified real MEGA byte transfer through the worker for a 73 KB file and a 13.8 MB folder file; decryption was not applied until the later payload fix.
- Verified no direct MEGA URLs, link keys, worker keys, or bot tokens appear in bot logs.
- Static checks passed with `ruff` and `python -m compileall`.
- Deployed the Update 2 bot files to `/home/azure/megabot` on the VPS and restarted the bot; startup validation and local Bot API connectivity passed.

## Phase 3 - Large files and live progress - complete

- Raised the default transfer cap to 2000 MB through the local Bot API.
- Rejected `MAX_DOWNLOAD_MB` values above 2000 and updated the env template.
- Added throttled status edits with percentage, transferred size, and speed during downloads.
- Added streamed upload progress through a progress-aware input file and the same status reporter.
- Increased Bot API and download timeouts to two hours for large transfers.
- Kept pagination, file selection, media dispatch, document fallback, and temp cleanup unchanged.
- Verified download and upload progress updates, 2 GB default configuration, limit rejection, temp cleanup, and secret redaction with a fake local Bot API.
- Re-ran phase 2, navigation, media, media fallback, real file download, and real folder download tests successfully.

## Phase 4 - Hardening - complete

- Removed stale files from `TEMP_DIR` during startup and logged the cleanup count.
- Stored the original MEGA link with each menu so expired download URLs can be resolved again.
- Added one automatic URL refresh per download, with menu URL updates for later clicks.
- Added a per-user download guard that rejects rapid repeat callbacks while a download is running.
- Added clear failure messages when refreshed URLs expire or files disappear.
- Verified startup cleanup, expired URL refresh, menu reuse after refresh, duplicate callback rejection, double-expiry cleanup, and temp cleanup after failures.
- Re-ran phase 2, navigation, media, media fallback, phase 3 progress, real file, and real folder tests successfully.
- Static checks passed with `ruff` and `python -m compileall`.
- Deployed the Update 2 bot files to `/home/azure/megabot` on the VPS and restarted the bot; startup validation and local Bot API connectivity passed.

## Large media delivery fix - verified locally

- Raised the native media ceiling from 50 MB to 2000 MB for animations, video, audio, and voice notes through the local Bot API.
- Kept the 10 MB photo limit and sticker limits, with document fallback for oversized or unsupported media.
- Verified 96 MB, 181 MB, and 350 MB media selection and dispatch for MP4, MKV, MOV, WEBM, MP3, FLAC, OGG, OPUS, and GIF, including the 2000 MB boundary.
- Added video probing and JPEG thumbnail generation through PyAV and Pillow, passing duration, width, height, and thumbnail to `sendVideo`.
- Added startup media-limit logging, per-upload size/suffix/limit diagnostics, and detailed video-probe failure messages.
- Re-ran media dispatch, media fallback, and phase 3 progress tests successfully; static checks passed.
- Real local Bot API confirmation for the reported 181 MB and 350 MB files still requires deployment and a process restart.

## MEGA payload decryption fix - implemented

- Confirmed the worker's download URL returns MEGA AES-CTR ciphertext; the bot was uploading encrypted bytes, which caused `0:00` videos, missing thumbnails, and unreadable documents.
- Added `bot/mega_crypto.py` to parse the original link key, resolve folder node keys through the MEGA API, cache file keys, and derive the per-file AES key and nonce.
- Added streaming AES-CTR decryption to `Downloader` before writing to the temp file.
- Resolved decryption keys for single-file links, folder files, and folder `/file/<handle>` selections before download.
- Verified a real 33,915,264-byte folder MP4 decrypts to a valid `ftyp` file and probes as a 266-second 1280x720 video with a JPEG thumbnail.
- Verified the reported 136,803,541-byte MP4 decrypts and probes as a 730-second 1280x720 video with a JPEG thumbnail on the VPS.
- Verified the full bot flow on the VPS with a fake Telegram API: real folder link, key resolution, decryption, 33 MB video upload, duration/thumbnail fields, and temp cleanup.
- Existing synthetic media E2E fixtures use keyless fake links and must be updated before reuse.

## Update 1 - Premium UI and folder tree - implemented and locally verified

- Replaced the flat folder picker with a real tree derived from worker file paths; folders and files are rendered as hierarchical entries.
- Added same-message folder navigation, Back, Prev/Next pagination, six entries per page, recursive folder statistics, and safe root-boundary handling.
- Added file buttons with `📄 Truncated Name (Size)` labels capped at 35 name characters while preserving the extension; folder buttons use `📂 Name`.
- Added a premium HTML File Resolved screen with name, size, type, a download button, and a Back button that returns to the file's containing folder.
- Updated every bot message to HTML parse mode with escaping for file names, paths, and errors.
- Added exact HTML file captions to delivered media.
- Replaced the status text with a live progress bar, percentage, speed, ETA, transferred size, and elapsed time; the same message is used for download and upload.
- Added a cancellation registry and Cancel button; cancellation kills the transfer task, removes the progress message, and cleans any partial temp file.
- Added successful transfer auto-delete for the File Resolved/menu and progress messages, leaving only the delivered file.
- Added failure auto-delete after ten seconds, with clear Download Failed and Upload Failed messages and removed controls.
- Verified tree navigation, pagination, file info, Back, long labels, progress, caption HTML, final delete button, success auto-delete, cancel cleanup, and error auto-delete with fake Telegram/worker end-to-end tests.
- Verified the decryption path remains active in the updated flow; the worker was not changed.
- Deployed the updated bot files to `/home/azure/megabot` on the VPS and restarted the bot; startup validation and local Bot API connectivity passed.

## Update 2 - Folder batch download - implemented and locally verified

- Added a `📥 Download All (N)` button inside folder views; N includes all files in the current folder and its subfolders.
- Batch downloads run sequentially, edit one pinned status message, and keep it pinned until every selected file has been processed.
- The pinned status shows the folder name, current file position, uploaded/failed/skipped counts, aggregate uploaded size, and per-file progress.
- After the batch, the status is unpinned and deleted, and a final HTML summary is sent with folder name, total files, uploaded/failed/skipped counts, uploaded/total size, elapsed time, and average speed.
- Per-file failures are counted and the batch continues; oversized files are skipped and reported in the final summary.
- Cancelling a batch stops the active transfer, cleans temp files, unpins/deletes the status, and leaves the folder menu available.
- Removed the inline `🗑 Delete File` button and its callback handler from delivered media.
- Verified recursive batch selection, pin/unpin lifecycle, three sequential uploads, progress edits, final summary, temp cleanup, no delete-button markup, and single-file cancellation/error regressions with fake Telegram/worker E2E tests.
- Static checks passed with `ruff` and `python -m compileall`.
- Deployed the Update 2 bot files to `/home/azure/megabot` on the VPS and restarted the bot; startup validation and local Bot API connectivity passed.

## Update 3 - Large folder fallback - implemented and locally verified

- Raised the Worker source caps from 500 to 2,000 files and 5,000 to 10,000 nodes; rebuilt `mega-direct-worker.js`.
- Raised the bot Worker response allowance to 8 MB and the direct MEGA resolver node/response caps to 20,000 nodes and 32 MB.
- Added a bot-side fallback for Worker `folder_too_large` responses: the bot resolves folder nodes directly from MEGA, decrypts names/keys, fetches download URLs in 100-file batches, and builds the same menu result format.
- Populated the existing MEGA key cache from fallback results so downloads and batch runs do not fetch the folder node list again.
- Applied the fallback to initial link resolution, expired-download refresh, and long batch menu refresh paths.
- Verified a real public folder resolves directly with downloadable URLs and a `206` range response.
- Verified an end-to-end fallback run where the fake Worker returns `413 folder_too_large` and the bot still builds the folder menu with `Download All`.
- Existing tree, single-download, batch, cancel, and error E2Es still pass.
- Deployed the bot-side fallback to `/home/azure/megabot` and restarted the bot; startup validation and local Bot API connectivity passed.
- The live Worker still has the old 500-file cap; its rebuilt bundle with the higher cap is ready but has not been deployed. The deployed bot bypasses the cap through the direct fallback.
