import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message

from .formatting import file_caption
from .video import probe_video

log = logging.getLogger(__name__)

PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
ANIMATION_EXTENSIONS = frozenset({".gif"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".aac", ".flac", ".wav"})
VOICE_EXTENSIONS = frozenset({".ogg", ".opus", ".oga"})
STICKER_LIMITS = {".webp": 512 * 1024, ".tgs": 64 * 1024}

PHOTO_MAX_BYTES = 10 * 1024 * 1024
MEDIA_MAX_BYTES = 2000 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
UploadProgress = Callable[[int, int], Awaitable[None]]


def media_kind(name: str, size: int) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in PHOTO_EXTENSIONS and size <= PHOTO_MAX_BYTES:
        return "photo"
    if suffix in ANIMATION_EXTENSIONS and size <= MEDIA_MAX_BYTES:
        return "animation"
    if suffix in VIDEO_EXTENSIONS and size <= MEDIA_MAX_BYTES:
        return "video"
    if suffix in AUDIO_EXTENSIONS and size <= MEDIA_MAX_BYTES:
        return "audio"
    if suffix in VOICE_EXTENSIONS and size <= MEDIA_MAX_BYTES:
        return "voice"
    sticker_limit = STICKER_LIMITS.get(suffix)
    if sticker_limit is not None and size <= sticker_limit:
        return "sticker"
    return "document"


class ProgressInputFile(FSInputFile):
    def __init__(
        self,
        path: Path,
        name: str,
        size: int,
        on_progress: UploadProgress,
    ):
        super().__init__(path, filename=name, chunk_size=UPLOAD_CHUNK_BYTES)
        self._size = max(0, size)
        self._on_progress = on_progress
        self._written = 0

    async def read(self, bot):
        async for chunk in super().read(bot):
            self._written += len(chunk)
            await self._on_progress(self._written, self._size)
            yield chunk


def upload(
    path: Path,
    name: str,
    size: int,
    on_progress: UploadProgress | None,
) -> FSInputFile:
    if on_progress is None:
        return FSInputFile(path, filename=name, chunk_size=UPLOAD_CHUNK_BYTES)
    return ProgressInputFile(path, name, size, on_progress)


async def send_media(
    message: Message,
    path: Path,
    name: str,
    size: int,
    on_progress: UploadProgress | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    caption: str | None = None,
) -> str:
    suffix = Path(name).suffix.lower()
    kind = media_kind(name, size)
    caption_text = caption if caption is not None else file_caption(name)
    log.info(
        "upload_kind kind=%s size=%s suffix=%s limit=%s",
        kind,
        size,
        suffix,
        MEDIA_MAX_BYTES,
    )
    thumbnail_path = None
    video_info = None
    if kind == "video":
        thumbnail_path = path.with_name(f"{path.name}.thumb.jpg")
        video_info = await probe_video(path, thumbnail_path)
    try:
        if kind == "photo":
            await message.answer_photo(
                upload(path, name, size, on_progress),
                caption=caption_text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        elif kind == "animation":
            await message.answer_animation(
                upload(path, name, size, on_progress),
                caption=caption_text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        elif kind == "video":
            video_kwargs = {}
            if video_info is not None:
                if video_info.duration is not None:
                    video_kwargs["duration"] = video_info.duration
                if video_info.width is not None:
                    video_kwargs["width"] = video_info.width
                if video_info.height is not None:
                    video_kwargs["height"] = video_info.height
                if video_info.thumbnail is not None:
                    video_kwargs["thumbnail"] = FSInputFile(video_info.thumbnail)
            await message.answer_video(
                upload(path, name, size, on_progress),
                caption=caption_text,
                parse_mode="HTML",
                supports_streaming=True,
                reply_markup=reply_markup,
                **video_kwargs,
            )
        elif kind == "audio":
            await message.answer_audio(
                upload(path, name, size, on_progress),
                caption=caption_text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        elif kind == "voice":
            await message.answer_voice(
                upload(path, name, size, on_progress),
                reply_markup=reply_markup,
            )
        elif kind == "sticker":
            await message.answer_sticker(
                upload(path, name, size, on_progress),
                reply_markup=reply_markup,
            )
        else:
            await message.answer_document(
                upload(path, name, size, on_progress),
                caption=caption_text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
    except TelegramBadRequest as exc:
        if kind == "document":
            raise
        log.warning("upload_rejected kind=%s error=%s", kind, exc)
        await message.answer_document(
            upload(path, name, size, on_progress),
            caption=caption_text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        log.info("upload_fallback kind=%s document=true", kind)
        return "document"
    finally:
        if thumbnail_path is not None:
            thumbnail_path.unlink(missing_ok=True)
    return kind
