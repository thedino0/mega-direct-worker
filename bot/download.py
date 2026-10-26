import logging
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import aiohttp

from .config import Config

log = logging.getLogger(__name__)
CHUNK_SIZE = 256 * 1024


class DownloadError(RuntimeError):
    pass


def safe_filename(value: object) -> str:
    name = Path(str(value or "file")).name
    name = "".join(char for char in name if char >= " " and char != "\x7f")
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")
    if not name:
        name = "file"
    if len(name) > 180:
        suffix = Path(name).suffix[:20]
        name = f"{name[: 180 - len(suffix)]}{suffix}"
    return name


class Downloader:
    def __init__(self, config: Config, session: aiohttp.ClientSession):
        self._dir = config.temp_dir
        self._max = config.max_file_bytes
        self._session = session

    async def fetch(self, url: str, name: str, expected_size: int) -> Path:
        if expected_size > self._max:
            raise DownloadError("That file is too large for phase 2.")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise DownloadError("Worker returned an invalid download URL.")
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{uuid4().hex}-{safe_filename(name)}"
        written = 0
        total = max(0, expected_size)
        next_percent = 10
        timeout = aiohttp.ClientTimeout(total=900, connect=15, sock_read=90)
        try:
            async with self._session.get(url, timeout=timeout) as response:
                if response.status in {401, 403, 404, 410}:
                    raise DownloadError("MEGA link expired or was denied. Send the link again.")
                if response.status == 429:
                    raise DownloadError("MEGA is rate-limiting downloads. Try again shortly.")
                if response.status != 200:
                    raise DownloadError("MEGA download failed. Try again.")
                declared = int(response.content_length or 0)
                if declared > self._max:
                    raise DownloadError("That file is too large for phase 2.")
                total = max(total, declared)
                with path.open("wb") as handle:
                    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > self._max:
                            raise DownloadError("That file is too large for phase 2.")
                        handle.write(chunk)
                        if total > 0:
                            percent = int(written * 100 / total)
                            if percent >= next_percent:
                                log.info("download_progress percent=%s bytes=%s", min(percent, 100), written)
                                next_percent = (percent // 10 + 1) * 10
        except DownloadError:
            path.unlink(missing_ok=True)
            raise
        except TimeoutError as exc:
            path.unlink(missing_ok=True)
            raise DownloadError("MEGA download timed out. Try again.") from exc
        except aiohttp.ClientError as exc:
            path.unlink(missing_ok=True)
            log.error("download_unreachable error=%s", type(exc).__name__)
            raise DownloadError("MEGA download failed. Try again.") from exc
        except OSError as exc:
            path.unlink(missing_ok=True)
            log.error("download_write_failed error=%s", type(exc).__name__)
            raise DownloadError("Could not save the downloaded file.") from exc
        log.info("download_done bytes=%s", written)
        return path

    async def close(self) -> None:
        await self._session.close()
