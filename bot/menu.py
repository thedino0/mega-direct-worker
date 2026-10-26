import time
from dataclasses import dataclass, replace
from secrets import token_urlsafe

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .formatting import as_size, clean_text, format_size

PAGE_SIZE = 6
MAX_MENUS = 500
DEFAULT_TTL = 1200
MAX_BUTTON_CHARS = 64


class MenuError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MenuFile:
    name: str
    size: int
    ext: str
    path: str
    url: str


@dataclass(frozen=True, slots=True)
class Menu:
    token: str
    user_id: int
    kind: str
    name: str
    total: int
    files: tuple[MenuFile, ...]
    expires_at: float
    source_url: str


def files_from_result(result: dict) -> tuple[str, tuple[MenuFile, ...]]:
    files: list[MenuFile] = []
    kind = result.get("kind")
    if kind == "file":
        url = result.get("url")
        if not isinstance(url, str) or not url:
            raise MenuError("Worker did not return a download URL.")
        files.append(
            MenuFile(
                name=clean_text(result.get("name")),
                size=as_size(result.get("size")),
                ext=clean_text(result.get("ext") or "unknown"),
                path=clean_text(result.get("name")),
                url=url,
            )
        )
    elif kind == "folder":
        raw_files = result.get("files")
        if not isinstance(raw_files, list):
            raw_files = []
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str) or not url:
                continue
            files.append(
                MenuFile(
                    name=clean_text(item.get("name")),
                    size=as_size(item.get("size")),
                    ext=clean_text(item.get("ext") or "unknown"),
                    path=clean_text(item.get("path") or item.get("name")),
                    url=url,
                )
            )
    else:
        raise MenuError("Worker returned an unexpected result.")
    return kind, tuple(files)


def find_file(files: tuple[MenuFile, ...], target: MenuFile) -> MenuFile | None:
    for file in files:
        if file.path == target.path and file.name == target.name and file.size == target.size:
            return file
    for file in files:
        if file.name == target.name and file.size == target.size:
            return file
    return None


def short(text: object, limit: int) -> str:
    value = clean_text(text)
    if len(value) <= limit:
        return value
    return f"{value[: max(0, limit - 3)]}..."


class MenuStore:
    def __init__(self, max_menus: int = MAX_MENUS, ttl_seconds: int = DEFAULT_TTL):
        self._items: dict[str, Menu] = {}
        self._max_menus = max_menus
        self._ttl = ttl_seconds

    def _cleanup(self, now: float) -> None:
        expired = [token for token, menu in self._items.items() if menu.expires_at <= now]
        for token in expired:
            self._items.pop(token, None)

    def _trim(self) -> None:
        while len(self._items) >= self._max_menus:
            oldest = min(self._items, key=lambda token: self._items[token].expires_at)
            self._items.pop(oldest, None)

    def _ttl_for(self, result: dict) -> int:
        return max(60, min(self._ttl, as_size(result.get("expires_in")) or self._ttl))

    def put(self, user_id: int, result: dict, source_url: str) -> Menu:
        now = time.monotonic()
        self._cleanup(now)
        self._trim()
        kind, files = files_from_result(result)
        if not files:
            raise MenuError("There are no downloadable files in that link.")
        token = token_urlsafe(9)
        while token in self._items:
            token = token_urlsafe(9)
        menu = Menu(
            token=token,
            user_id=user_id,
            kind=kind,
            name=clean_text(result.get("name")),
            total=as_size(result.get("size")),
            files=files,
            expires_at=now + self._ttl_for(result),
            source_url=source_url,
        )
        self._items[token] = menu
        return menu

    def refresh(self, token: str, user_id: int, result: dict) -> Menu | None:
        now = time.monotonic()
        self._cleanup(now)
        menu = self._items.get(token)
        if menu is None or menu.user_id != user_id or menu.expires_at <= now:
            return None
        _, fresh_files = files_from_result(result)
        if not fresh_files:
            raise MenuError("There are no downloadable files in that link.")
        updated: list[MenuFile] = []
        for old_file in menu.files:
            match = find_file(fresh_files, old_file)
            updated.append(match if match is not None else old_file)
        refreshed = replace(
            menu,
            files=tuple(updated),
            total=as_size(result.get("size")) or menu.total,
            expires_at=now + self._ttl_for(result),
        )
        self._items[token] = refreshed
        return refreshed

    def get(self, token: str, user_id: int) -> Menu | None:
        now = time.monotonic()
        self._cleanup(now)
        menu = self._items.get(token)
        if menu is None or menu.user_id != user_id or menu.expires_at <= now:
            return None
        return menu


def page_count(menu: Menu) -> int:
    return max(1, (len(menu.files) + PAGE_SIZE - 1) // PAGE_SIZE)


def clamp_page(menu: Menu, page: int) -> int:
    return max(0, min(page, page_count(menu) - 1))


def menu_text(menu: Menu, page: int = 0) -> str:
    if menu.kind == "file":
        file = menu.files[0]
        return "\n".join(
            [
                "File",
                f"Name: {file.name}",
                f"Size: {format_size(file.size)}",
                f"Type: {file.ext}",
            ]
        )
    current = clamp_page(menu, page)
    total_pages = page_count(menu)
    return "\n".join(
        [
            f"Folder: {menu.name}",
            f"Files: {len(menu.files)}",
            f"Total: {format_size(menu.total)}",
            f"Page {current + 1}/{total_pages}",
            "Choose a file below.",
        ]
    )


def menu_keyboard(menu: Menu, page: int = 0) -> InlineKeyboardMarkup:
    if menu.kind == "file":
        file = menu.files[0]
        label = short(f"Download ({format_size(file.size)})", MAX_BUTTON_CHARS)
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"f:{menu.token}:0")]
            ]
        )
    current = clamp_page(menu, page)
    total_pages = page_count(menu)
    start = current * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(menu.files))
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(start, end):
        file = menu.files[index]
        label = short(f"{index + 1}. {file.path} ({format_size(file.size)})", MAX_BUTTON_CHARS)
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"f:{menu.token}:{index}")]
        )
    navigation: list[InlineKeyboardButton] = []
    if current > 0:
        navigation.append(
            InlineKeyboardButton(text="Prev", callback_data=f"p:{menu.token}:{current - 1}")
        )
    if current < total_pages - 1:
        navigation.append(
            InlineKeyboardButton(text="Next", callback_data=f"p:{menu.token}:{current + 1}")
        )
    if navigation:
        rows.append(navigation)
    return InlineKeyboardMarkup(inline_keyboard=rows)
