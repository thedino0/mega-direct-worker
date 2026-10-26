import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, Message

from .formatting import format_size

log = logging.getLogger(__name__)

PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
ANIMATION_EXTENSIONS = frozenset({".gif"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"})
AUDIO_EXTENSIONS = frozenset({".mp3", ".m4a", ".aac", ".flac", ".wav"})
VOICE_EXTENSIONS = frozenset({".ogg", ".opus", ".oga"})
STICKER_LIMITS = {".webp": 512 * 1024, ".tgs": 64 * 1024}

PHOTO_MAX_BYTES = 10 * 1024 * 1024
MEDIA_MAX_BYTES = 50 * 1024 * 1024


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


def upload(path: Path, name: str) -> FSInputFile:
    return FSInputFile(path, filename=name)


async def send_media(message: Message, path: Path, name: str, size: int) -> str:
    kind = media_kind(name, size)
    caption = format_size(size)
    log.info("upload_kind kind=%s", kind)
    try:
        if kind == "photo":
            await message.answer_photo(upload(path, name), caption=caption)
        elif kind == "animation":
            await message.answer_animation(upload(path, name), caption=caption)
        elif kind == "video":
            await message.answer_video(upload(path, name), caption=caption, supports_streaming=True)
        elif kind == "audio":
            await message.answer_audio(upload(path, name), caption=caption)
        elif kind == "voice":
            await message.answer_voice(upload(path, name), caption=caption)
        elif kind == "sticker":
            await message.answer_sticker(upload(path, name))
        else:
            await message.answer_document(upload(path, name), caption=caption)
    except TelegramBadRequest as exc:
        if kind == "document":
            raise
        log.warning("upload_rejected kind=%s error=%s", kind, exc)
        await message.answer_document(upload(path, name), caption=caption)
        log.info("upload_fallback kind=%s document=true", kind)
        return "document"
    return kind
