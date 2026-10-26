import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .config import Config
from .formatting import format_result
from .privacy import extract_mega_link, redact_link
from .worker import WorkerClient, WorkerError

log = logging.getLogger(__name__)
router = Router(name="mega")
WELCOME = (
    "Send a public MEGA file or folder link.\n"
    "I will return the file list, file sizes, and total size."
)


def is_owner(message: Message, config: Config) -> bool:
    return message.from_user is not None and message.from_user.id == config.my_user_id


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
async def on_text(message: Message, config: Config, worker: WorkerClient) -> None:
    if not is_owner(message, config):
        return
    text = message.text or ""
    link = extract_mega_link(text)
    if link is None:
        if not text.startswith("/"):
            await message.answer("Send a MEGA file or folder link.")
        return
    log.info("received link=%s", redact_link(link))
    await message.answer("Checking the link...")
    try:
        result = await worker.resolve(link)
    except WorkerError as exc:
        log.error("worker_failed code=%s status=%s", exc.code, exc.status)
        await message.answer(f"Worker error: {exc}")
        return
    except Exception as exc:
        log.error("worker_failed unexpected=%s", type(exc).__name__)
        await message.answer("Worker failed. Try again.")
        return
    try:
        chunks = format_result(result)
    except Exception as exc:
        log.error("format_failed kind=%s error=%s", result.get("kind"), type(exc).__name__)
        await message.answer("Worker returned an unexpected result.")
        return
    log.info("list_built kind=%s messages=%s", result.get("kind"), len(chunks))
    for chunk in chunks:
        await message.answer(chunk, disable_web_page_preview=True)
    log.info("list_sent kind=%s messages=%s", result.get("kind"), len(chunks))
