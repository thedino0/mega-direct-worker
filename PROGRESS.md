# MEGA Worker Bot Progress

Last updated: 2026-10-26

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
- Verified real MEGA downloads through the worker for a 73 KB file and a 13.8 MB folder file, including video delivery and cleanup.
- Verified no direct MEGA URLs, link keys, worker keys, or bot tokens appear in bot logs.
- Static checks passed with `ruff` and `python -m compileall`.

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

## Large media delivery fix - verified locally

- Raised the native media ceiling from 50 MB to 2000 MB for animations, video, audio, and voice notes through the local Bot API.
- Kept the 10 MB photo limit and sticker limits, with document fallback for oversized or unsupported media.
- Verified 96 MB, 181 MB, and 350 MB media selection and dispatch for MP4, MKV, MOV, WEBM, MP3, FLAC, OGG, OPUS, and GIF, including the 2000 MB boundary.
- Added video probing and JPEG thumbnail generation through PyAV and Pillow, passing duration, width, height, and thumbnail to `sendVideo`.
- Added startup media-limit logging, per-upload size/suffix/limit diagnostics, and detailed video-probe failure messages.
- Re-ran media dispatch, media fallback, and phase 3 progress tests successfully; static checks passed.
- Real local Bot API confirmation for the reported 181 MB and 350 MB files still requires deployment and a process restart.
