import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

from .config import ConfigError, load_config
from .download import Downloader
from .handlers import router
from .menu import MenuStore
from .worker import WorkerClient

log = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


async def run() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        log.error("config_error %s", exc)
        return 1
    try:
        config.temp_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.error("temp_dir_failed path=%s", config.temp_dir)
        return 1
    session = AiohttpSession(
        api=TelegramAPIServer.from_base(config.local_api_url),
        timeout=30,
    )
    bot = Bot(token=config.bot_token, session=session)
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        log.error("local_api_rejected url=%s", config.local_api_url)
        await session.close()
        return 1
    except TelegramNetworkError:
        log.error("local_api_unreachable url=%s", config.local_api_url)
        await session.close()
        return 1
    except Exception as exc:
        log.error("local_api_failed url=%s error=%s", config.local_api_url, type(exc).__name__)
        await session.close()
        return 1
    log.info("local_api_ok bot_id=%s username=%s", me.id, me.username or "")
    worker_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=90, connect=10, sock_read=90)
    )
    worker = WorkerClient(config, worker_session)
    download_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=900, connect=15, sock_read=90)
    )
    downloader = Downloader(config, download_session)
    menus = MenuStore()
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(
            bot,
            config=config,
            worker=worker,
            downloader=downloader,
            menus=menus,
        )
    finally:
        await worker.close()
        await downloader.close()
    return 0


def main() -> None:
    setup_logging()
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
