import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 30
THUMBNAIL_TIMEOUT_SECONDS = 30
THUMBNAIL_MAX_BYTES = 200 * 1024
THUMBNAIL_WIDTH = 320
DURATION_PATTERN = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
SIZE_PATTERN = re.compile(r"Video:.*?(?<!\d)(\d{2,5})x(\d{2,5})(?!\d)")
ROTATION_PATTERN = re.compile(r"rotate\s*:\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True, slots=True)
class VideoInfo:
    duration: int | None
    width: int | None
    height: int | None
    thumbnail: Path | None


@lru_cache(maxsize=1)
def ffmpeg_executable() -> str | None:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


async def run_ffmpeg(
    args: list[str],
    timeout: float,
) -> tuple[int, bytes, bytes] | None:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        log.warning("video_ffmpeg_start_failed error=%s", type(exc).__name__)
        return None
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        log.warning("video_ffmpeg_timeout")
        return None
    return process.returncode, stdout, stderr


def parse_video_info(output: str) -> VideoInfo | None:
    duration_match = DURATION_PATTERN.search(output)
    size_match = SIZE_PATTERN.search(output)
    if duration_match is None and size_match is None:
        return None
    duration = None
    width = None
    height = None
    if duration_match is not None:
        hours, minutes, seconds = duration_match.groups()
        total_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        duration = max(0, round(total_seconds))
    if size_match is not None:
        width = int(size_match.group(1))
        height = int(size_match.group(2))
        rotation_match = ROTATION_PATTERN.search(output)
        if rotation_match is not None and abs(int(float(rotation_match.group(1)))) % 180 == 90:
            width, height = height, width
    if not width or not height:
        width = None
        height = None
    return VideoInfo(duration=duration, width=width, height=height, thumbnail=None)


async def create_thumbnail(executable: str, path: Path, output: Path) -> Path | None:
    args = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "0",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        f"scale=w='min({THUMBNAIL_WIDTH},iw)':h=-2",
        "-q:v",
        "6",
        str(output),
    ]
    result = await run_ffmpeg(args, THUMBNAIL_TIMEOUT_SECONDS)
    if result is None or result[0] != 0:
        output.unlink(missing_ok=True)
        return None
    try:
        if not output.is_file() or output.stat().st_size > THUMBNAIL_MAX_BYTES:
            output.unlink(missing_ok=True)
            return None
    except OSError:
        output.unlink(missing_ok=True)
        return None
    return output


async def probe_video(path: Path, thumbnail_path: Path) -> VideoInfo | None:
    executable = ffmpeg_executable()
    if executable is None:
        log.warning("video_probe_unavailable")
        return None
    result = await run_ffmpeg(
        [executable, "-hide_banner", "-i", str(path)],
        PROBE_TIMEOUT_SECONDS,
    )
    if result is None:
        return None
    output = result[2].decode(errors="replace")
    info = parse_video_info(output)
    thumbnail = await create_thumbnail(executable, path, thumbnail_path)
    if info is None:
        if thumbnail is None:
            log.warning("video_probe_failed")
            return None
        info = VideoInfo(duration=None, width=None, height=None, thumbnail=thumbnail)
    else:
        info = VideoInfo(
            duration=info.duration,
            width=info.width,
            height=info.height,
            thumbnail=thumbnail,
        )
    log.info(
        "video_metadata duration=%s width=%s height=%s thumbnail=%s",
        info.duration or 0,
        info.width or 0,
        info.height or 0,
        thumbnail is not None,
    )
    return info
