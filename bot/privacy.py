import re
from urllib.parse import urlsplit

MEGA_HOSTS = {"mega.nz", "mega.io", "mega.co.nz"}
HANDLE_RE = re.compile(r"^[A-Za-z0-9_-]{8}$")
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
TRAILING = ".,;:!?)]}>'\""


def mega_parts(value: str) -> tuple[str, str, str] | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]
    if host not in MEGA_HOSTS or len(parts) < 2:
        return None
    kind = parts[0].lower()
    handle = parts[1]
    if kind not in {"file", "folder"} or HANDLE_RE.fullmatch(handle) is None:
        return None
    return parsed.scheme, host, f"{kind}/{handle}"


def extract_mega_link(text: str) -> str | None:
    for match in URL_RE.finditer(text):
        candidate = match.group(0).rstrip(TRAILING)
        if mega_parts(candidate):
            return candidate
    return None


def redact_link(value: str) -> str:
    parts = mega_parts(value)
    if not parts:
        return "(not a mega link)"
    scheme, host, path = parts
    return f"{scheme}://{host}/{path}"
