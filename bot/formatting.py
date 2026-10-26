MAX_MESSAGE_CHARS = 3800
MAX_NAME_CHARS = 220


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
