import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message

from .config import Config
from .download import Downloader, DownloadError, safe_filename
from .formatting import format_size
from .menu import MenuError, MenuStore, clamp_page, menu_keyboard, menu_text
from .privacy import extract_mega_link, redact_link
from .worker import WorkerClient, WorkerError

log = logging.getLogger(__name__)
router = Router(name="mega")
WELCOME = (
    "Send a public MEGA file or folder link.\n"
    "Folder links show a picker. Choose a file to download it here."
)


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
        menu = menus.put(config.my_user_id, result)
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
            f"Too large for phase 2: {format_size(file.size)}.",
            show_alert=True,
        )
        return
    await callback.answer()
    status = await callback.message.answer(f"Downloading {file.name}...")
    path = None
    try:
        log.info("download_start size=%s", file.size)
        path = await downloader.fetch(file.url, file.name, file.size)
        await edit_status(status, "Uploading...")
        log.info("upload_start size=%s", file.size)
        await callback.message.answer_document(
            FSInputFile(path, filename=safe_filename(file.name)),
            caption=format_size(file.size),
        )
        log.info("upload_done size=%s", file.size)
        await edit_status(status, "Sent.")
    except DownloadError as exc:
        log.error("download_failed message=%s", exc)
        await edit_status(status, f"Download failed: {exc}")
    except Exception as exc:
        log.error("upload_failed error=%s", type(exc).__name__)
        await edit_status(status, "Upload failed. Try again.")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
            log.info("temp_cleanup")
