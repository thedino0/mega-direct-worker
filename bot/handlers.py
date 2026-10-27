import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from secrets import token_urlsafe

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from .config import Config
from .download import Downloader, DownloadError, DownloadExpired, safe_filename
from .formatting import (
    DIVIDER,
    error_text,
    file_caption,
    format_duration,
    format_size,
    html_text,
    progress_text,
)
from .media import send_media
from .mega_crypto import DownloadKey, MegaKeyError, MegaKeyResolver
from .menu import (
    Menu,
    MenuError,
    MenuFile,
    MenuStore,
    clamp_page,
    file_info_keyboard,
    file_info_text,
    files_from_result,
    find_file,
    folder_file_indices,
    folder_name,
    menu_keyboard,
    menu_text,
    node_by_id,
)
from .privacy import extract_mega_link, redact_link
from .worker import WorkerClient, WorkerError

log = logging.getLogger(__name__)
router = Router(name="mega")
WELCOME = (
    "<b>✦ MEGA Direct</b>\n"
    "Send a public MEGA file or folder link.\n"
    "Browse folders, choose a file, and receive it here."
)
PROGRESS_INTERVAL = 2.0
ERROR_DELETE_SECONDS = 10.0
EMPTY_KEYBOARD = InlineKeyboardMarkup(inline_keyboard=[])


def is_owner(message: Message, config: Config) -> bool:
    return message.from_user is not None and message.from_user.id == config.my_user_id


def is_owner_callback(callback: CallbackQuery, config: Config) -> bool:
    return callback.from_user.id == config.my_user_id


async def resolve_result(
    worker: WorkerClient,
    keys: MegaKeyResolver,
    link: str,
) -> dict:
    try:
        return await worker.resolve(link)
    except WorkerError as exc:
        if exc.code != "folder_too_large":
            raise
        log.warning("worker_folder_limit_fallback")
        try:
            return await keys.folder_result(link)
        except MegaKeyError as fallback_exc:
            raise WorkerError(str(fallback_exc), "folder_too_large", 413) from fallback_exc
        except Exception as fallback_exc:
            log.error("folder_fallback_failed error=%s", type(fallback_exc).__name__)
            raise WorkerError(
                "Could not load that large folder. Try again.",
                "folder_too_large",
                413,
            ) from fallback_exc


def cancel_keyboard(operation: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data=f"x:{operation}",
                )
            ]
        ]
    )


async def edit_status(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            log.warning("edit_failed error=%s", type(exc).__name__)
    except Exception as exc:
        log.warning("edit_failed error=%s", type(exc).__name__)


async def delete_status(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    except Exception as exc:
        log.warning("delete_failed error=%s", type(exc).__name__)


async def delete_later(message: Message, delay: float, label: str) -> None:
    try:
        await asyncio.sleep(delay)
        await delete_status(message)
        log.info("%s_cleanup", label)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("%s_cleanup_failed error=%s", label, type(exc).__name__)


def schedule_delete(message: Message, label: str) -> None:
    asyncio.create_task(delete_later(message, ERROR_DELETE_SECONDS, label))


async def pin_status(message: Message, label: str) -> bool:
    try:
        await message.bot.pin_chat_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
            disable_notification=True,
        )
        log.info("%s_pinned", label)
        return True
    except TelegramBadRequest as exc:
        log.warning("%s_pin_failed error=%s", label, type(exc).__name__)
    except Exception as exc:
        log.warning("%s_pin_failed error=%s", label, type(exc).__name__)
    return False


async def unpin_status(message: Message, label: str) -> None:
    try:
        await message.bot.unpin_chat_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
        )
        log.info("%s_unpinned", label)
    except TelegramBadRequest:
        pass
    except Exception as exc:
        log.warning("%s_unpin_failed error=%s", label, type(exc).__name__)


def batch_header(
    folder_title: str,
    file_name: str,
    position: int,
    total: int,
    uploaded: int,
    failed: int,
    skipped: int,
    uploaded_bytes: int,
    total_bytes: int,
) -> str:
    counts = f"✅ <code>{uploaded}</code> | ❌ <code>{failed}</code>"
    if skipped:
        counts = f"{counts} | ⏭ <code>{skipped}</code>"
    return "\n".join(
        [
            f"📥 <b>Folder Download</b> · <code>{html_text(folder_title)}</code>",
            f"📄 <b>{position}/{total}:</b> <code>{html_text(file_name)}</code>",
            f"{counts} | ⚖️ <code>{format_size(uploaded_bytes)} / {format_size(total_bytes)}</code>",
        ]
    )


def batch_final_text(
    folder_title: str,
    total: int,
    uploaded: int,
    failed: int,
    skipped: int,
    uploaded_bytes: int,
    total_bytes: int,
    elapsed: float,
    average_speed: float,
) -> str:
    if uploaded == total:
        title = "✅ <b>Folder Download Complete</b>"
    elif uploaded:
        title = "⚠️ <b>Folder Download Finished with Errors</b>"
    elif skipped == total:
        title = "⏭️ <b>Folder Download Skipped</b>"
    else:
        title = "❌ <b>Folder Download Failed</b>"
    lines = [
        DIVIDER,
        title,
        DIVIDER,
        f"📂 <b>Name:</b> <code>{html_text(folder_title)}</code>",
        f"📄 <b>Total Files:</b> <code>{total}</code>",
        f"✅ <b>Uploaded:</b> <code>{uploaded}</code>",
        f"❌ <b>Failed:</b> <code>{failed}</code>",
    ]
    if skipped:
        lines.append(f"⏭ <b>Skipped:</b> <code>{skipped}</code>")
    lines.extend(
        [
            f"⚖️ <b>Uploaded Size:</b> <code>{format_size(uploaded_bytes)}</code> / <code>{format_size(total_bytes)}</code>",
            f"⏱ <b>Elapsed:</b> <code>{format_duration(elapsed)}</code>",
            f"⚡ <b>Average Speed:</b> <code>{format_size(average_speed)}/s</code>",
            DIVIDER,
        ]
    )
    return "\n".join(lines)


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


class CancelRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[object]] = {}

    def register(self, operation: str) -> bool:
        task = asyncio.current_task()
        if task is None:
            return False
        self._tasks[operation] = task
        return True

    def release(self, operation: str) -> None:
        self._tasks.pop(operation, None)

    def cancel(self, operation: str) -> bool:
        task = self._tasks.get(operation)
        if task is None:
            return False
        task.cancel()
        return True


class TransferProgress:
    def __init__(
        self,
        message: Message,
        stage: str,
        total: int,
        edit: Callable[..., Awaitable[None]],
        markup: InlineKeyboardMarkup,
        header: str | None = None,
    ):
        self._message = message
        self._stage = stage
        self._total = max(0, total)
        self._written = 0
        self._shown = -1
        self._started = time.monotonic()
        self._edit = edit
        self._markup = markup
        self._header = header
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._render()
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

    async def _render(self) -> None:
        written = self._written
        self._shown = written
        text = progress_text(self._stage, written, self._total, self._started)
        if self._header:
            text = f"{self._header}\n{text}"
        await self._edit(self._message, text, self._markup)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(PROGRESS_INTERVAL)
            if self._written == self._shown:
                continue
            await self._render()


async def fetch_with_progress(
    downloader: Downloader,
    file: MenuFile,
    status: Message,
    key: DownloadKey,
    operation: str,
    header: str | None = None,
) -> Path:
    progress = TransferProgress(
        status,
        "Downloading",
        file.size,
        edit_status,
        cancel_keyboard(operation),
        header=header,
    )
    await progress.start()
    try:
        return await downloader.fetch(
            file.url,
            file.name,
            file.size,
            on_progress=progress.update,
            key=key,
        )
    finally:
        await progress.stop()


async def refresh_file(
    worker: WorkerClient,
    keys: MegaKeyResolver,
    menus: MenuStore,
    menu: Menu,
    file: MenuFile,
    status: Message,
    operation: str,
    header: str | None = None,
) -> MenuFile:
    log.info("download_refresh_start")
    refresh_text = "🔄 <b>Refreshing the download link...</b>"
    if header:
        refresh_text = f"{header}\n{refresh_text}"
    await edit_status(status, refresh_text, cancel_keyboard(operation))
    try:
        result = await resolve_result(worker, keys, menu.source_url)
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
    keys: MegaKeyResolver,
    operation: str,
    header: str | None = None,
) -> tuple[Path, MenuFile]:
    try:
        key = await keys.resolve(menu.source_url, file.path, file.name)
    except MegaKeyError as exc:
        log.error("mega_key_failed error=%s", type(exc).__name__)
        raise DownloadError(str(exc)) from exc
    try:
        path = await fetch_with_progress(
            downloader,
            file,
            status,
            key,
            operation,
            header,
        )
    except DownloadExpired:
        log.info("download_expired")
        file = await refresh_file(
            worker,
            keys,
            menus,
            menu,
            file,
            status,
            operation,
            header,
        )
        path = await fetch_with_progress(
            downloader,
            file,
            status,
            key,
            operation,
            header,
        )
    return path, file


async def upload_path(
    message: Message,
    path: Path,
    file: MenuFile,
    status: Message,
    operation: str,
    header: str | None = None,
) -> str:
    upload_size = path.stat().st_size
    log.info("upload_start size=%s", upload_size)
    progress = TransferProgress(
        status,
        "Uploading",
        upload_size,
        edit_status,
        cancel_keyboard(operation),
        header=header,
    )
    await progress.start()
    try:
        return await send_media(
            message,
            path,
            safe_filename(file.name),
            upload_size,
            on_progress=progress.update,
            caption=file_caption(file.name),
        )
    finally:
        await progress.stop()


async def show_menu(message: Message, menu: Menu, node_id: int, page: int) -> None:
    try:
        await message.edit_text(
            menu_text(menu, page, node_id),
            parse_mode="HTML",
            reply_markup=menu_keyboard(menu, page, node_id),
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            log.warning("menu_edit_failed error=%s", type(exc).__name__)
    except Exception as exc:
        log.warning("menu_edit_failed error=%s", type(exc).__name__)


@router.message(CommandStart())
async def on_start(message: Message, config: Config) -> None:
    if not is_owner(message, config):
        return
    log.info("start command")
    await message.answer(WELCOME, parse_mode="HTML")


@router.message(Command("help"))
async def on_help(message: Message, config: Config) -> None:
    if not is_owner(message, config):
        return
    await message.answer(WELCOME, parse_mode="HTML")


@router.message(F.text)
async def on_text(
    message: Message,
    config: Config,
    worker: WorkerClient,
    keys: MegaKeyResolver,
    menus: MenuStore,
) -> None:
    if not is_owner(message, config):
        return
    text = message.text or ""
    link = extract_mega_link(text)
    if link is None:
        if not text.startswith("/"):
            await message.answer(
                "Send a MEGA file or folder link.",
                parse_mode="HTML",
            )
        return
    log.info("received link=%s", redact_link(link))
    status = await message.answer("Checking the link...", parse_mode="HTML")
    try:
        result = await resolve_result(worker, keys, link)
    except WorkerError as exc:
        log.error("worker_failed code=%s status=%s", exc.code, exc.status)
        await edit_status(status, error_text("Worker Error", str(exc)))
        return
    except Exception as exc:
        log.error("worker_failed unexpected=%s", type(exc).__name__)
        await edit_status(status, error_text("Worker Error", "Please try again."))
        return
    try:
        menu = menus.put(config.my_user_id, result, link)
    except MenuError as exc:
        log.error("menu_failed reason=%s", exc)
        await edit_status(status, error_text("Link Error", str(exc)))
        return
    await delete_status(status)
    log.info("menu_built kind=%s files=%s", menu.kind, len(menu.files))
    await message.answer(
        menu_text(menu, 0, 0),
        reply_markup=menu_keyboard(menu, 0, 0),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    log.info("menu_sent kind=%s files=%s", menu.kind, len(menu.files))


@router.callback_query(F.data.startswith("n:"))
async def on_navigate(callback: CallbackQuery, config: Config, menus: MenuStore) -> None:
    if not is_owner_callback(callback, config):
        await callback.answer()
        return
    if callback.data is None or not isinstance(callback.message, Message):
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    try:
        node_id = int(parts[2])
        requested = int(parts[3])
    except ValueError:
        await callback.answer()
        return
    menu = menus.get(parts[1], config.my_user_id)
    if menu is None:
        await callback.answer("That menu expired. Send the link again.", show_alert=True)
        return
    node = node_by_id(menu, node_id)
    if node is None:
        await callback.answer("That folder is no longer available.", show_alert=True)
        return
    page = clamp_page(menu, requested, node_id)
    await callback.answer()
    await show_menu(callback.message, menu, node_id, page)
    log.info("menu_nav node=%s page=%s", node_id, page + 1)


@router.callback_query(F.data.startswith("p:"))
async def on_page(callback: CallbackQuery, config: Config, menus: MenuStore) -> None:
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
        requested = int(parts[2])
    except ValueError:
        await callback.answer()
        return
    menu = menus.get(parts[1], config.my_user_id)
    if menu is None:
        await callback.answer("That menu expired. Send the link again.", show_alert=True)
        return
    page = clamp_page(menu, requested, 0)
    await callback.answer()
    await show_menu(callback.message, menu, 0, page)


@router.callback_query(F.data.startswith("i:"))
async def on_info(callback: CallbackQuery, config: Config, menus: MenuStore) -> None:
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
    await callback.answer()
    try:
        await callback.message.edit_text(
            file_info_text(menu.files[index]),
            parse_mode="HTML",
            reply_markup=file_info_keyboard(menu, index),
            disable_web_page_preview=True,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            log.warning("file_info_edit_failed error=%s", type(exc).__name__)
    except Exception as exc:
        log.warning("file_info_edit_failed error=%s", type(exc).__name__)
    log.info("file_info index=%s", index)


@router.callback_query(F.data.startswith("f:"))
async def on_pick(
    callback: CallbackQuery,
    config: Config,
    menus: MenuStore,
    downloader: Downloader,
    worker: WorkerClient,
    guard: DownloadGuard,
    cancels: CancelRegistry,
    keys: MegaKeyResolver,
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
    operation = token_urlsafe(6)
    cancels.register(operation)
    status = None
    path = None
    delivered = False
    try:
        await callback.answer()
        status = await callback.message.answer(
            progress_text("Downloading", 0, file.size, time.monotonic()),
            parse_mode="HTML",
            reply_markup=cancel_keyboard(operation),
            disable_web_page_preview=True,
        )
        log.info("download_start size=%s", file.size)
        path, file = await download_file(
            downloader,
            worker,
            menus,
            menu,
            file,
            status,
            keys,
            operation,
        )
        upload_size = path.stat().st_size
        kind = await upload_path(
            callback.message,
            path,
            file,
            status,
            operation,
        )
        log.info("upload_done size=%s kind=%s", upload_size, kind)
        await delete_status(status)
        await delete_status(callback.message)
        delivered = True
        log.info("progress_cleanup")
        log.info("menu_cleanup")
    except asyncio.CancelledError:
        log.info("download_cancelled")
        raise
    except DownloadError as exc:
        log.error("download_failed message=%s", exc)
        if status is not None:
            await edit_status(
                status,
                error_text("Download Failed", str(exc)),
                EMPTY_KEYBOARD,
            )
            schedule_delete(status, "download_error")
    except Exception as exc:
        log.error("upload_failed error=%s", type(exc).__name__)
        if status is not None:
            await edit_status(
                status,
                error_text("Upload Failed", "Please try again."),
                EMPTY_KEYBOARD,
            )
            schedule_delete(status, "upload_error")
    finally:
        cancels.release(operation)
        guard.release(config.my_user_id)
        if path is not None:
            path.unlink(missing_ok=True)
            log.info("temp_cleanup")
        if not delivered and status is not None:
            log.info("progress_pending_cleanup")


@router.callback_query(F.data.startswith("a:"))
async def on_batch(
    callback: CallbackQuery,
    config: Config,
    menus: MenuStore,
    downloader: Downloader,
    worker: WorkerClient,
    guard: DownloadGuard,
    cancels: CancelRegistry,
    keys: MegaKeyResolver,
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
        node_id = int(parts[2])
    except ValueError:
        await callback.answer()
        return
    menu = menus.get(parts[1], config.my_user_id)
    if menu is None:
        await callback.answer("That menu expired. Send the link again.", show_alert=True)
        return
    node = node_by_id(menu, node_id)
    if node is None:
        await callback.answer("That folder is no longer available.", show_alert=True)
        return
    indices = folder_file_indices(menu, node_id)
    if not indices:
        await callback.answer("There are no files in that folder.", show_alert=True)
        return
    selected = tuple(menu.files[index] for index in indices)
    folder_title = folder_name(menu, node)
    total_bytes = sum(file.size for file in selected)
    if not guard.acquire(config.my_user_id):
        await callback.answer("A download is already running.", show_alert=True)
        return
    operation = token_urlsafe(6)
    cancels.register(operation)
    status = None
    path = None
    pinned = False
    uploaded = 0
    failed = 0
    skipped = 0
    uploaded_bytes = 0
    started = time.monotonic()
    try:
        await callback.answer()
        first = selected[0]
        initial_header = batch_header(
            folder_title,
            first.name,
            1,
            len(selected),
            0,
            0,
            0,
            0,
            total_bytes,
        )
        status = await callback.message.answer(
            f"{initial_header}\n⏳ <b>Preparing folder download...</b>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard(operation),
            disable_web_page_preview=True,
        )
        pinned = await pin_status(status, "batch")
        log.info("batch_start files=%s bytes=%s", len(selected), total_bytes)
        for position, target in enumerate(selected, 1):
            current = menus.get(menu.token, config.my_user_id)
            if current is not None:
                menu = current
            if time.monotonic() >= menu.expires_at:
                try:
                    result = await resolve_result(worker, keys, menu.source_url)
                    menu = menus.put(menu.user_id, result, menu.source_url)
                    log.info("batch_menu_refreshed files=%s", len(menu.files))
                except WorkerError as exc:
                    log.error("batch_refresh_failed code=%s status=%s", exc.code, exc.status)
                    failed += len(selected) - position + 1
                    break
                except Exception as exc:
                    log.error("batch_refresh_failed error=%s", type(exc).__name__)
                    failed += len(selected) - position + 1
                    break
            file = find_file(menu.files, target)
            if file is None:
                failed += 1
                log.error("batch_file_missing position=%s", position)
                continue
            if file.size > config.max_file_bytes:
                skipped += 1
                log.info("batch_file_skipped position=%s size=%s", position, file.size)
                continue
            header = batch_header(
                folder_title,
                file.name,
                position,
                len(selected),
                uploaded,
                failed,
                skipped,
                uploaded_bytes,
                total_bytes,
            )
            path = None
            try:
                path, file = await download_file(
                    downloader,
                    worker,
                    menus,
                    menu,
                    file,
                    status,
                    keys,
                    operation,
                    header,
                )
                upload_size = path.stat().st_size
                kind = await upload_path(
                    callback.message,
                    path,
                    file,
                    status,
                    operation,
                    header,
                )
                uploaded += 1
                uploaded_bytes += upload_size
                log.info(
                    "batch_file_done position=%s size=%s kind=%s",
                    position,
                    upload_size,
                    kind,
                )
            except asyncio.CancelledError:
                raise
            except DownloadError as exc:
                failed += 1
                log.error("batch_download_failed position=%s error=%s", position, type(exc).__name__)
            except Exception as exc:
                failed += 1
                log.error("batch_upload_failed position=%s error=%s", position, type(exc).__name__)
            finally:
                if path is not None:
                    path.unlink(missing_ok=True)
                    path = None
                    log.info("batch_temp_cleanup")
        elapsed = max(time.monotonic() - started, 0.001)
        average_speed = uploaded_bytes / elapsed
        final_text = batch_final_text(
            folder_title,
            len(selected),
            uploaded,
            failed,
            skipped,
            uploaded_bytes,
            total_bytes,
            elapsed,
            average_speed,
        )
        if status is not None:
            await unpin_status(status, "batch")
            pinned = False
        await callback.message.answer(
            final_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        if status is not None:
            await delete_status(status)
        log.info(
            "batch_done files=%s uploaded=%s failed=%s skipped=%s seconds=%.1f",
            len(selected),
            uploaded,
            failed,
            skipped,
            elapsed,
        )
    except asyncio.CancelledError:
        log.info("batch_cancelled")
        raise
    except Exception as exc:
        log.error("batch_failed error=%s", type(exc).__name__)
        if status is not None:
            await edit_status(
                status,
                error_text("Folder Download Failed", "Please try again."),
                EMPTY_KEYBOARD,
            )
            schedule_delete(status, "batch_error")
    finally:
        if pinned and status is not None:
            await unpin_status(status, "batch")
        cancels.release(operation)
        guard.release(config.my_user_id)
        if path is not None:
            path.unlink(missing_ok=True)
            log.info("batch_temp_cleanup")


@router.callback_query(F.data.startswith("x:"))
async def on_cancel(
    callback: CallbackQuery,
    config: Config,
    cancels: CancelRegistry,
) -> None:
    if not is_owner_callback(callback, config):
        await callback.answer()
        return
    if callback.data is None:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 2 or not parts[1]:
        await callback.answer()
        return
    found = cancels.cancel(parts[1])
    if not found:
        await callback.answer("No active download.", show_alert=True)
        return
    await callback.answer("Cancelling download...")
    log.info("download_cancel_requested")
    if isinstance(callback.message, Message):
        await delete_status(callback.message)
