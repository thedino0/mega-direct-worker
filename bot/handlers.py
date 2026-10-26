import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .config import Config
from .download import Downloader, DownloadError, DownloadExpired, safe_filename
from .formatting import format_size
from .media import send_media
from .menu import (
    Menu,
    MenuError,
    MenuFile,
    MenuStore,
    clamp_page,
    files_from_result,
    find_file,
    menu_keyboard,
    menu_text,
)
from .privacy import extract_mega_link, redact_link
from .worker import WorkerClient, WorkerError

log = logging.getLogger(__name__)
router = Router(name="mega")
WELCOME = (
    "Send a public MEGA file or folder link.\n"
    "Folder links show a picker. Choose a file to download it here."
)
PROGRESS_INTERVAL = 3.0


def is_owner(message: Message, config: Config) -> bool:
    return message.from_user is not None and message.from_user.id == config.my_user_id


def is_owner_callback(callback: CallbackQuery, config: Config) -> bool:
    return callback.from_user.id == config.my_user_id


async def edit_status(message: Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except TelegramBadRequest:
        pass


async def delete_status(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


def progress_text(stage: str, written: int, total: int, started: float) -> str:
    elapsed = max(time.monotonic() - started, 0.001)
    speed = written / elapsed
    if total > 0:
        percent = max(0, min(100, int(written * 100 / total)))
        return (
            f"{stage} {percent}% ({format_size(written)} / {format_size(total)})\n"
            f"{format_size(speed)}/s"
        )
    return f"{stage} {format_size(written)}\n{format_size(speed)}/s"


class DownloadGuard:
    def __init__(self) -> None:
        self._active: set[int] = set()

    def acquire(self, user_id: int) -> bool:
        if user_id in self._active:
            return False
        self._active.add(user_id)
        return True

    def release(self, user_id: int) -> None:
        self._active.discard(user_id)


class TransferProgress:
    def __init__(
        self,
        message: Message,
        stage: str,
        total: int,
        edit: Callable[[Message, str], Awaitable[None]],
    ):
        self._message = message
        self._stage = stage
        self._total = max(0, total)
        self._written = 0
        self._shown = -1
        self._started = time.monotonic()
        self._edit = edit
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def update(self, written: int, total: int) -> None:
        self._written = max(0, written)
        if total > 0:
            self._total = total

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(PROGRESS_INTERVAL)
            written = self._written
            if written == self._shown:
                continue
            self._shown = written
            try:
                await self._edit(
                    self._message,
                    progress_text(self._stage, written, self._total, self._started),
                )
            except Exception as exc:
                log.warning("progress_failed error=%s", type(exc).__name__)


async def fetch_with_progress(
    downloader: Downloader,
    file: MenuFile,
    status: Message,
) -> Path:
    progress = TransferProgress(status, "Downloading", file.size, edit_status)
    progress.start()
    try:
        return await downloader.fetch(
            file.url,
            file.name,
            file.size,
            on_progress=progress.update,
        )
    finally:
        await progress.stop()


async def refresh_file(
    worker: WorkerClient,
    menus: MenuStore,
    menu: Menu,
    file: MenuFile,
    status: Message,
) -> MenuFile:
    log.info("download_refresh_start")
    await edit_status(status, "Refreshing the download link...")
    try:
        result = await worker.resolve(menu.source_url)
    except WorkerError as exc:
        log.error("download_refresh_failed code=%s status=%s", exc.code, exc.status)
        raise DownloadError(f"Could not refresh the link: {exc}") from exc
    except Exception as exc:
        log.error("download_refresh_failed unexpected=%s", type(exc).__name__)
        raise DownloadError("Could not refresh the link. Try again.") from exc
    try:
        _, fresh_files = files_from_result(result)
        match = find_file(fresh_files, file)
        if match is None:
            raise DownloadError("That file is no longer available.")
        refreshed = menus.refresh(menu.token, menu.user_id, result)
    except MenuError as exc:
        raise DownloadError(str(exc)) from exc
    if refreshed is None:
        raise DownloadError("That menu expired. Send the link again.")
    log.info("download_refresh_done")
    return match


async def download_file(
    downloader: Downloader,
    worker: WorkerClient,
    menus: MenuStore,
    menu: Menu,
    file: MenuFile,
    status: Message,
) -> tuple[Path, MenuFile]:
    try:
        path = await fetch_with_progress(downloader, file, status)
    except DownloadExpired:
        log.info("download_expired")
        file = await refresh_file(worker, menus, menu, file, status)
        path = await fetch_with_progress(downloader, file, status)
    return path, file


@router.message(CommandStart())
async def on_start(message: Message, config: Config) -> None:
    if not is_owner(message, config):
        return
    log.info("start command")
    await message.answer(WELCOME)


@router.message(Command("help"))
async def on_help(message: Message, config: Config) -> None:
    if not is_owner(message, config):
        return
    await message.answer(WELCOME)


@router.message(F.text)
async def on_text(
    message: Message,
    config: Config,
    worker: WorkerClient,
    menus: MenuStore,
) -> None:
    if not is_owner(message, config):
        return
    text = message.text or ""
    link = extract_mega_link(text)
    if link is None:
        if not text.startswith("/"):
            await message.answer("Send a MEGA file or folder link.")
        return
    log.info("received link=%s", redact_link(link))
    status = await message.answer("Checking the link...")
    try:
        result = await worker.resolve(link)
    except WorkerError as exc:
        log.error("worker_failed code=%s status=%s", exc.code, exc.status)
        await edit_status(status, f"Worker error: {exc}")
        return
    except Exception as exc:
        log.error("worker_failed unexpected=%s", type(exc).__name__)
        await edit_status(status, "Worker failed. Try again.")
        return
    try:
        menu = menus.put(config.my_user_id, result, link)
    except MenuError as exc:
        log.error("menu_failed reason=%s", exc)
        await edit_status(status, str(exc))
        return
    await delete_status(status)
    log.info("menu_built kind=%s files=%s", menu.kind, len(menu.files))
    await message.answer(
        menu_text(menu, 0),
        reply_markup=menu_keyboard(menu, 0),
        disable_web_page_preview=True,
    )
    log.info("menu_sent kind=%s files=%s", menu.kind, len(menu.files))


@router.callback_query(F.data.startswith("p:"))
async def on_page(callback: CallbackQuery, config: Config, menus: MenuStore) -> None:
    if not is_owner_callback(callback, config):
        await callback.answer()
        return
    if callback.data is None:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        requested = int(parts[2])
    except ValueError:
        await callback.answer()
        return
    menu = menus.get(parts[1], config.my_user_id)
    if menu is None:
        await callback.answer("That menu expired. Send the link again.", show_alert=True)
        return
    page = clamp_page(menu, requested)
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(
            menu_text(menu, page),
            reply_markup=menu_keyboard(menu, page),
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        pass


@router.callback_query(F.data.startswith("f:"))
async def on_pick(
    callback: CallbackQuery,
    config: Config,
    menus: MenuStore,
    downloader: Downloader,
    worker: WorkerClient,
    guard: DownloadGuard,
) -> None:
    if not is_owner_callback(callback, config):
        await callback.answer()
        return
    if callback.data is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        index = int(parts[2])
    except ValueError:
        await callback.answer()
        return
    menu = menus.get(parts[1], config.my_user_id)
    if menu is None:
        await callback.answer("That menu expired. Send the link again.", show_alert=True)
        return
    if index < 0 or index >= len(menu.files):
        await callback.answer("That file is no longer available.", show_alert=True)
        return
    file = menu.files[index]
    if file.size > config.max_file_bytes:
        await callback.answer(
            f"Too large: {format_size(file.size)}. Limit: {format_size(config.max_file_bytes)}.",
            show_alert=True,
        )
        return
    if not guard.acquire(config.my_user_id):
        await callback.answer("A download is already running.", show_alert=True)
        return
    status = None
    path = None
    try:
        await callback.answer()
        status = await callback.message.answer(f"Downloading {file.name}...")
        log.info("download_start size=%s", file.size)
        path, file = await download_file(
            downloader,
            worker,
            menus,
            menu,
            file,
            status,
        )
        upload_size = path.stat().st_size
        await edit_status(status, f"Uploading {format_size(upload_size)}...")
        log.info("upload_start size=%s", upload_size)
        upload_progress = TransferProgress(status, "Uploading", upload_size, edit_status)
        upload_progress.start()
        try:
            kind = await send_media(
                callback.message,
                path,
                safe_filename(file.name),
                upload_size,
                on_progress=upload_progress.update,
            )
        finally:
            await upload_progress.stop()
        log.info("upload_done size=%s kind=%s", upload_size, kind)
        await edit_status(status, "Sent.")
    except DownloadError as exc:
        log.error("download_failed message=%s", exc)
        if status is not None:
            await edit_status(status, f"Download failed: {exc}")
    except Exception as exc:
        log.error("upload_failed error=%s", type(exc).__name__)
        if status is not None:
            await edit_status(status, "Upload failed. Try again.")
    finally:
        guard.release(config.my_user_id)
        if path is not None:
            path.unlink(missing_ok=True)
            log.info("temp_cleanup")
