import time
from html import escape
from pathlib import Path

MAX_MESSAGE_CHARS = 3800
MAX_NAME_CHARS = 220
BUTTON_NAME_CHARS = 35
DIVIDER = "━━━━━━━━━━━━━━━"


def clean_text(value: object) -> str:
    text = "".join(char for char in str(value) if char >= " " and char != "\x7f")
    text = " ".join(text.split())
    if not text:
        return "Unnamed"
    if len(text) > MAX_NAME_CHARS:
        return f"{text[: MAX_NAME_CHARS - 3]}..."
    return text


def as_size(value: object) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, size)


def format_size(value: object) -> str:
    size = float(as_size(value))
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = 0
    while size >= 1024 and unit < len(units) - 1:
        size /= 1024
        unit += 1
    digits = 0 if unit == 0 else 0 if size >= 100 else 1 if size >= 10 else 2
    return f"{size:.{digits}f} {units[unit]}"


def compact_size(value: object) -> str:
    return format_size(value).replace(" ", "")


def truncate_filename(value: object, limit: int = BUTTON_NAME_CHARS) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    suffix = Path(text).suffix
    if not suffix or len(suffix) >= limit - 8:
        suffix = ""
    budget = limit - len(suffix) - 3
    if budget < 8:
        return f"{text[: max(0, limit - 3)]}..."
    head = max(4, (budget + 1) // 2)
    tail = budget - head
    if tail < 4:
        head = budget - 4
        tail = 4
    stem = text[: -len(suffix)] if suffix else text
    return f"{stem[:head]}...{stem[-tail:]}{suffix}"


def html_text(value: object) -> str:
    return escape(clean_text(value), quote=False)


def file_caption(name: object) -> str:
    return f"<b>📄 File Name:</b> <code>{escape(str(name), quote=False)}</code>"


def format_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def progress_bar(percent: int) -> str:
    filled = max(0, min(10, percent // 10))
    return f"[{'█' * filled}{'░' * (10 - filled)}]"


def progress_text(stage: str, written: int, total: int, started: float) -> str:
    elapsed = max(time.monotonic() - started, 0.001)
    speed = max(0.0, written / elapsed)
    speed_label = f"{format_size(speed)}/s"
    elapsed_label = format_duration(elapsed)
    icon = "⬆️" if stage.lower() == "uploading" else "⬇️"
    header = f"{icon} <b>{escape(stage)}</b>"
    if total > 0:
        percent = max(0, min(100, int(written * 100 / total)))
        if written >= total:
            eta_label = "00:00"
        elif speed > 0:
            eta_label = format_duration(max(0.0, (total - written) / speed))
        else:
            eta_label = "--:--"
        return (
            f"{header}\n"
            f"{progress_bar(percent)} {percent}%\n"
            f"⚡ Speed: {speed_label} | ⏳ ETA: {eta_label}\n"
            f"📦 {format_size(written)} / {format_size(total)} | ⏱ Elapsed: {elapsed_label}"
        )
    return (
        f"{header}\n"
        f"{progress_bar(0)} --%\n"
        f"⚡ Speed: {speed_label} | ⏳ ETA: --:--\n"
        f"📦 {format_size(written)} / -- | ⏱ Elapsed: {elapsed_label}"
    )


def error_text(title: str, reason: object) -> str:
    message = clean_text(reason)
    if len(message) > 300:
        message = f"{message[:297]}..."
    return f"❌ <b>{escape(title)}:</b> {escape(message, quote=False)}"


def split_messages(lines: list[str]) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in lines:
        if len(line) > MAX_MESSAGE_CHARS:
            line = f"{line[: MAX_MESSAGE_CHARS - 3]}..."
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > MAX_MESSAGE_CHARS:
            if current:
                chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def format_file(result: dict) -> list[str]:
    lines = [
        "File",
        f"Name: {clean_text(result.get('name'))}",
        f"Size: {format_size(result.get('size'))}",
        f"Type: {clean_text(result.get('ext') or 'unknown')}",
    ]
    expires = as_size(result.get("expires_in"))
    if expires:
        lines.append(f"Link expires in: {expires // 60} min")
    return lines


def format_folder(result: dict) -> list[str]:
    files = result.get("files")
    if not isinstance(files, list):
        files = []
    total = as_size(result.get("size"))
    lines = [
        f"Folder: {clean_text(result.get('name'))}",
        f"Files: {len(files)}",
        f"Total: {format_size(total)}",
        "",
    ]
    if not files:
        lines.append("No files in this folder.")
        return lines
    for index, item in enumerate(files, start=1):
        if not isinstance(item, dict):
            continue
        size = format_size(item.get("size"))
        path = clean_text(item.get("path") or item.get("name"))
        lines.append(f"{index}. {path}  [{size}]")
    return lines


def format_result(result: dict) -> list[str]:
    if result.get("kind") == "file":
        return split_messages(format_file(result))
    if result.get("kind") == "folder":
        return split_messages(format_folder(result))
    return ["Worker returned an unexpected result."]
