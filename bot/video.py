import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 30
THUMBNAIL_MAX_BYTES = 200 * 1024
THUMBNAIL_MAX_SIDE = 320
THUMBNAIL_QUALITIES = (85, 70, 55, 40)


@dataclass(frozen=True, slots=True)
class VideoInfo:
    duration: int | None
    width: int | None
    height: int | None
    thumbnail: Path | None


def error_text(path: Path, exc: Exception) -> str:
    text = str(exc).replace(str(path), "[file]").replace("\n", " ").strip()
    return text[:300]


def duration_seconds(container, stream) -> int | None:
    seconds = None
    if stream.duration is not None and stream.time_base is not None:
        seconds = float(stream.duration * stream.time_base)
    if (seconds is None or seconds <= 0) and container.duration is not None:
        seconds = container.duration / 1_000_000
    if seconds is None or seconds <= 0:
        return None
    return round(seconds)


def save_thumbnail(frame, output: Path) -> Path | None:
    image = frame.to_image()
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.thumbnail((THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE))
    for quality in THUMBNAIL_QUALITIES:
        image.save(output, "JPEG", quality=quality, optimize=True)
        if output.stat().st_size <= THUMBNAIL_MAX_BYTES:
            return output
    output.unlink(missing_ok=True)
    return None


def probe_video_sync(path: Path, thumbnail_path: Path) -> VideoInfo | None:
    import av

    with av.open(str(path)) as container:
        streams = container.streams.video
        if not streams:
            log.warning("video_probe_no_stream")
            return None
        stream = streams[0]
        width = stream.codec_context.width or None
        height = stream.codec_context.height or None
        if not width or not height:
            width = None
            height = None
        duration = duration_seconds(container, stream)
        thumbnail = None
        try:
            frame = next(container.decode(stream))
        except StopIteration:
            log.warning("video_probe_no_frame")
        except Exception as exc:
            log.warning(
                "video_frame_failed error=%s message=%s",
                type(exc).__name__,
                error_text(path, exc),
            )
        else:
            try:
                thumbnail = save_thumbnail(frame, thumbnail_path)
            except Exception as exc:
                thumbnail_path.unlink(missing_ok=True)
                log.warning(
                    "video_thumbnail_failed error=%s message=%s",
                    type(exc).__name__,
                    error_text(path, exc),
                )
    if duration is None and width is None and thumbnail is None:
        return None
    return VideoInfo(
        duration=duration,
        width=width,
        height=height,
        thumbnail=thumbnail,
    )


async def probe_video(path: Path, thumbnail_path: Path) -> VideoInfo | None:
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(probe_video_sync, path, thumbnail_path),
            PROBE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        thumbnail_path.unlink(missing_ok=True)
        log.warning("video_probe_timeout")
        return None
    except ImportError as exc:
        log.warning("video_probe_unavailable error=%s", type(exc).__name__)
        return None
    except Exception as exc:
        thumbnail_path.unlink(missing_ok=True)
        log.warning(
            "video_probe_failed error=%s message=%s",
            type(exc).__name__,
            error_text(path, exc),
        )
        return None
    if info is None:
        log.warning("video_probe_failed")
        return None
    log.info(
        "video_metadata duration=%s width=%s height=%s thumbnail=%s",
        info.duration or 0,
        info.width or 0,
        info.height or 0,
        info.thumbnail is not None,
    )
    return info
