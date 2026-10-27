import time
from dataclasses import dataclass, field, replace
from secrets import token_urlsafe

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .formatting import (
    BUTTON_NAME_CHARS,
    DIVIDER,
    as_size,
    clean_text,
    compact_size,
    format_size,
    html_text,
    truncate_filename,
)

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
class MenuNode:
    id: int
    name: str
    path: str
    parent_id: int | None
    folders: tuple[int, ...]
    files: tuple[int, ...]


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
    tree: tuple[MenuNode, ...] = field(default_factory=tuple)


@dataclass(slots=True)
class _BuildNode:
    name: str
    path: str
    parent_id: int | None
    folders: dict[str, int]
    files: list[int]


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


def build_tree(files: tuple[MenuFile, ...]) -> tuple[MenuNode, ...]:
    nodes: list[_BuildNode] = [
        _BuildNode(name="", path="", parent_id=None, folders={}, files=[])
    ]
    for index, file in enumerate(files):
        parts = [part for part in file.path.split("/") if part]
        parent = 0
        current_path = ""
        for raw_part in parts[:-1]:
            part = clean_text(raw_part)
            current_path = f"{current_path}/{part}" if current_path else part
            child_id = nodes[parent].folders.get(part)
            if child_id is None:
                child_id = len(nodes)
                nodes.append(
                    _BuildNode(
                        name=part,
                        path=current_path,
                        parent_id=parent,
                        folders={},
                        files=[],
                    )
                )
                nodes[parent].folders[part] = child_id
            parent = child_id
        nodes[parent].files.append(index)
    tree: list[MenuNode] = []
    for node_id, node in enumerate(nodes):
        folder_ids = tuple(
            sorted(node.folders.values(), key=lambda item: nodes[item].name.casefold())
        )
        file_ids = tuple(
            sorted(node.files, key=lambda item: files[item].name.casefold())
        )
        tree.append(
            MenuNode(
                id=node_id,
                name=node.name,
                path=node.path,
                parent_id=node.parent_id,
                folders=folder_ids,
                files=file_ids,
            )
        )
    return tuple(tree)


def tree_nodes(menu: Menu) -> tuple[MenuNode, ...]:
    return menu.tree or build_tree(menu.files)


def node_by_id(menu: Menu, node_id: int) -> MenuNode | None:
    nodes = tree_nodes(menu)
    if node_id < 0 or node_id >= len(nodes):
        return None
    return nodes[node_id]


def file_parent_id(menu: Menu, index: int) -> int:
    for node in tree_nodes(menu):
        if index in node.files:
            return node.id
    return 0


def folder_stats(menu: Menu, node_id: int) -> tuple[int, int]:
    nodes = tree_nodes(menu)
    if node_id < 0 or node_id >= len(nodes):
        return 0, 0

    def visit(current_id: int) -> tuple[int, int]:
        node = nodes[current_id]
        count = len(node.files)
        size = sum(menu.files[index].size for index in node.files)
        for child_id in node.folders:
            child_count, child_size = visit(child_id)
            count += child_count
            size += child_size
        return count, size

    return visit(node_id)


def folder_file_indices(menu: Menu, node_id: int) -> tuple[int, ...]:
    nodes = tree_nodes(menu)
    if node_id < 0 or node_id >= len(nodes):
        return ()
    indices: list[int] = []

    def visit(current_id: int) -> None:
        node = nodes[current_id]
        indices.extend(node.files)
        for child_id in node.folders:
            visit(child_id)

    visit(node_id)
    return tuple(indices)


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
            tree=build_tree(files),
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
            tree=build_tree(tuple(updated)),
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


def entry_count(menu: Menu, node_id: int = 0) -> int:
    node = node_by_id(menu, node_id)
    if node is None:
        return 0
    return len(node.folders) + len(node.files)


def page_count(menu: Menu, node_id: int = 0) -> int:
    return max(1, (entry_count(menu, node_id) + PAGE_SIZE - 1) // PAGE_SIZE)


def clamp_page(menu: Menu, page: int, node_id: int = 0) -> int:
    return max(0, min(page, page_count(menu, node_id) - 1))


def folder_name(menu: Menu, node: MenuNode) -> str:
    return node.name or menu.name or "Folder"


def file_info_text(file: MenuFile) -> str:
    return "\n".join(
        [
            DIVIDER,
            "✦ <b>File Resolved</b>",
            DIVIDER,
            f"📄 <b>Name:</b> <code>{html_text(file.name)}</code>",
            f"⚖️ <b>Size:</b> <code>{format_size(file.size)}</code>",
            f"🗂 <b>Type:</b> <code>{html_text(file.ext)}</code>",
            DIVIDER,
        ]
    )


def folder_text(menu: Menu, node_id: int = 0, page: int = 0) -> str:
    node = node_by_id(menu, node_id)
    if node is None:
        return "<b>That folder is no longer available.</b>"
    current = clamp_page(menu, page, node_id)
    total_pages = page_count(menu, node_id)
    _, size = folder_stats(menu, node_id)
    lines = [
        DIVIDER,
        "✦ <b>Folder Contents</b>",
        DIVIDER,
        f"📂 <b>Name:</b> <code>{html_text(folder_name(menu, node))}</code>",
        f"📁 <b>Folders:</b> <code>{len(node.folders)}</code>",
        f"📄 <b>Files:</b> <code>{len(node.files)}</code>",
        f"⚖️ <b>Size:</b> <code>{format_size(size)}</code>",
        DIVIDER,
        f"<b>Page</b> <code>{current + 1}/{total_pages}</code>",
    ]
    return "\n".join(lines)


def menu_text(menu: Menu, page: int = 0, node_id: int = 0) -> str:
    if menu.kind == "file":
        return file_info_text(menu.files[0])
    return folder_text(menu, node_id, page)


def back_button(menu: Menu, node: MenuNode) -> InlineKeyboardButton | None:
    if node.parent_id is None:
        return None
    return InlineKeyboardButton(
        text="🔙 Back",
        callback_data=f"n:{menu.token}:{node.parent_id}:0",
    )


def file_info_keyboard(menu: Menu, index: int) -> InlineKeyboardMarkup:
    file = menu.files[index]
    rows = [
        [
            InlineKeyboardButton(
                text=f"⬇️ Download ({compact_size(file.size)})",
                callback_data=f"f:{menu.token}:{index}",
            )
        ]
    ]
    if menu.kind == "folder":
        parent = node_by_id(menu, file_parent_id(menu, index))
        if parent is not None:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🔙 Back",
                        callback_data=f"n:{menu.token}:{parent.id}:0",
                    )
                ]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def menu_keyboard(menu: Menu, page: int = 0, node_id: int = 0) -> InlineKeyboardMarkup:
    if menu.kind == "file":
        return file_info_keyboard(menu, 0)
    node = node_by_id(menu, node_id)
    if node is None:
        return InlineKeyboardMarkup(inline_keyboard=[])
    nodes = tree_nodes(menu)
    entries: list[tuple[bool, int]] = [
        (True, child_id) for child_id in node.folders
    ] + [(False, index) for index in node.files]
    current = clamp_page(menu, page, node_id)
    total_pages = page_count(menu, node_id)
    start = current * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(entries))
    rows: list[list[InlineKeyboardButton]] = []
    for is_folder, item in entries[start:end]:
        if is_folder:
            label = f"📂 {truncate_filename(nodes[item].name, BUTTON_NAME_CHARS)}"
            callback_data = f"n:{menu.token}:{item}:0"
        else:
            file = menu.files[item]
            label = (
                f"📄 {truncate_filename(file.name, BUTTON_NAME_CHARS)} "
                f"({compact_size(file.size)})"
            )
            callback_data = f"i:{menu.token}:{item}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label[:MAX_BUTTON_CHARS],
                    callback_data=callback_data,
                )
            ]
        )
    navigation: list[InlineKeyboardButton] = []
    if current > 0:
        navigation.append(
            InlineKeyboardButton(
                text="⬅️ Prev",
                callback_data=f"n:{menu.token}:{node_id}:{current - 1}",
            )
        )
    if current < total_pages - 1:
        navigation.append(
            InlineKeyboardButton(
                text="Next ➡️",
                callback_data=f"n:{menu.token}:{node_id}:{current + 1}",
            )
        )
    if navigation:
        rows.append(navigation)
    file_count, _ = folder_stats(menu, node_id)
    if file_count:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📥 Download All ({file_count})",
                    callback_data=f"a:{menu.token}:{node_id}",
                )
            ]
        )
    button = back_button(menu, node)
    if button is not None:
        rows.append([button])
    return InlineKeyboardMarkup(inline_keyboard=rows)
