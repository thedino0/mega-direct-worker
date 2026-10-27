import json
import logging

import aiohttp

from .config import Config

log = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 8_000_000


class WorkerError(RuntimeError):
    def __init__(self, message: str, code: str = "worker_error", status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class WorkerClient:
    def __init__(self, config: Config, session: aiohttp.ClientSession):
        self._url = config.worker_resolve_url
        self._key = config.worker_key
        self._session = session

    async def resolve(self, link: str) -> dict:
        log.info("worker_call status=start")
        timeout = aiohttp.ClientTimeout(total=90, connect=10, sock_read=90)
        try:
            async with self._session.post(
                self._url,
                json={"url": link},
                headers={"X-Key": self._key},
                timeout=timeout,
            ) as response:
                status = response.status
                log.info("worker_call status=%s", status)
                body = await response.text()
        except TimeoutError as exc:
            raise WorkerError("Worker took too long. Try again.") from exc
        except aiohttp.ClientError as exc:
            log.error("worker_unreachable error=%s", type(exc).__name__)
            raise WorkerError("Worker could not be reached. Try again.") from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise WorkerError("Worker returned too much data.")
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise WorkerError("Worker returned an unreadable response.") from exc
        if status >= 400:
            error = data.get("error") if isinstance(data, dict) else None
            if isinstance(error, dict):
                message = str(error.get("message") or "Worker rejected the link.")
                code = str(error.get("code") or "worker_error")
            else:
                message = "Worker rejected the link."
                code = "worker_error"
            raise WorkerError(message, code, status)
        if not isinstance(data, dict) or data.get("kind") not in {"file", "folder"}:
            raise WorkerError("Worker returned an unexpected result.")
        return data

    async def close(self) -> None:
        await self._session.close()
