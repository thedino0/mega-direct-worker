import base64
import hashlib
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

import aiohttp
from Crypto.Cipher import AES

from .formatting import clean_text

log = logging.getLogger(__name__)
MEGA_API = "https://g.api.mega.co.nz/cs"
ALLOWED_HOSTS = frozenset({"mega.nz", "mega.io", "mega.co.nz"})
HANDLE_RE = re.compile(r"^[A-Za-z0-9_-]{8}$")
MAX_FOLDER_NODES = 5000
MAX_FOLDER_DEPTH = 64
MAX_API_BYTES = 8 * 1024 * 1024
KEY_CACHE_SECONDS = 1200
MAX_KEY_CACHE = 20


class MegaKeyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadKey:
    aes_key: bytes
    nonce: bytes
    kind: str

    @property
    def nonce_int(self) -> int:
        return int.from_bytes(self.nonce, "big") << 64


@dataclass(frozen=True, slots=True)
class MegaLink:
    kind: str
    handle: str
    key: str
    selection_type: str | None
    selection_handle: str | None


@dataclass(slots=True)
class _Entry:
    handle: str
    parent: str
    name: str
    size: int
    is_folder: bool
    key: DownloadKey | None
    children: list["_Entry"] = field(default_factory=list)


def decode_key(value: str) -> bytes:
    try:
        normalized = value.replace("-", "+").replace("_", "/")
        padding = "=" * ((4 - len(normalized) % 4) % 4)
        return base64.b64decode(normalized + padding, validate=True)
    except (ValueError, TypeError) as exc:
        raise MegaKeyError("The MEGA decryption key is malformed.") from exc


def aes_ecb_decrypt(key: bytes, data: bytes) -> bytes:
    return AES.new(key, AES.MODE_ECB).decrypt(data)


def aes_cbc_decrypt(key: bytes, data: bytes) -> bytes:
    return AES.new(key, AES.MODE_CBC, b"\0" * 16).decrypt(data)


def decrypt_attrs(encoded: str, key: bytes) -> dict:
    try:
        ciphertext = decode_key(encoded)
    except MegaKeyError as exc:
        raise MegaKeyError("Could not read the MEGA file metadata.") from exc
    if not ciphertext or len(ciphertext) % 16 != 0:
        raise MegaKeyError("Could not read the MEGA file metadata.")
    plaintext = aes_cbc_decrypt(key, ciphertext)
    if plaintext[:4] != b"MEGA":
        raise MegaKeyError("The MEGA decryption key does not match this link.")
    end = len(plaintext)
    while end > 4 and plaintext[end - 1] == 0:
        end -= 1
    try:
        attrs = json.loads(plaintext[4:end])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MegaKeyError("Could not read the MEGA file metadata.") from exc
    if not isinstance(attrs, dict):
        raise MegaKeyError("Could not read the MEGA file metadata.")
    return attrs


def file_key(raw: bytes) -> DownloadKey:
    if len(raw) != 32:
        raise MegaKeyError("The MEGA file key has the wrong length.")
    key = bytes(raw[index] ^ raw[index + 16] for index in range(16))
    return DownloadKey(key, raw[16:24], "file")


def folder_key(value: str) -> bytes:
    raw = decode_key(value)
    if len(raw) != 16:
        raise MegaKeyError("The MEGA folder key has the wrong length.")
    return raw


def parse_link(value: str) -> MegaLink:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise MegaKeyError("That is not a valid MEGA link.") from exc
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host not in ALLOWED_HOSTS:
        raise MegaKeyError("That is not a valid MEGA link.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] not in {"file", "folder"} or not HANDLE_RE.fullmatch(parts[1]):
        raise MegaKeyError("That is not a valid MEGA link.")
    fragment = parsed.fragment
    if not fragment:
        raise MegaKeyError("The link does not contain a decryption key.")
    if "!" in fragment:
        raise MegaKeyError("Password-protected MEGA links are not supported.")
    fragment_parts = fragment.split("/")
    key = fragment_parts[0]
    selection_type = None
    selection_handle = None
    if (
        parts[0] == "folder"
        and len(fragment_parts) >= 3
        and fragment_parts[1] in {"folder", "file"}
        and HANDLE_RE.fullmatch(fragment_parts[2])
    ):
        selection_type = fragment_parts[1]
        selection_handle = fragment_parts[2]
    return MegaLink(parts[0], parts[1], key, selection_type, selection_handle)


def select_node_key(node: dict, root_handle: str) -> str:
    encoded = node.get("k")
    if not isinstance(encoded, str):
        raise MegaKeyError("MEGA did not provide a file key.")
    alternatives = encoded.split("/")
    selected = next(
        (
            alt
            for alt in alternatives
            if len(alt) > 8 and alt[:8] == root_handle and alt[8] == ":"
        ),
        None,
    )
    if selected is None:
        selected = next(
            (
            alt
            for alt in alternatives
            if len(alt) > 8 and alt[:8] == node.get("h") and alt[8] == ":"
        ),
            None,
        )
    if selected is None:
        if len(alternatives) != 1:
            raise MegaKeyError("MEGA provided an unexpected file key.")
        selected = alternatives[0]
    if ":" not in selected:
        raise MegaKeyError("MEGA provided an unexpected file key.")
    encoded_key = selected.split(":", 1)[1]
    if not encoded_key:
        raise MegaKeyError("MEGA provided an unexpected file key.")
    return encoded_key


def decrypt_node_key(node: dict, key: bytes, root_handle: str) -> bytes:
    encoded = select_node_key(node, root_handle)
    try:
        ciphertext = decode_key(encoded)
    except MegaKeyError as exc:
        raise MegaKeyError("Could not decrypt the MEGA file key.") from exc
    expected = 16 if node.get("t") == 1 else 32
    if len(ciphertext) != expected:
        raise MegaKeyError("Could not decrypt the MEGA file key.")
    return aes_ecb_decrypt(key, ciphertext)


def find_public_root(nodes: list[dict]) -> dict:
    handles = {node.get("h") for node in nodes}
    for node in nodes:
        encoded = node.get("k")
        if not isinstance(encoded, str):
            continue
        if any(
            len(alt) > 8 and alt[:8] == node.get("h") and alt[8] == ":"
            for alt in encoded.split("/")
        ):
            return node
    for node in nodes:
        if node.get("p") not in handles:
            return node
    raise MegaKeyError("MEGA did not return the folder root.")


def find_folder_root(nodes: list[dict], start_handle: str | None) -> dict:
    if start_handle is None:
        return find_public_root(nodes)
    for node in nodes:
        if node.get("h") == start_handle and node.get("t") == 1:
            return node
    raise MegaKeyError("That MEGA subfolder is no longer available.")


def node_attr_key(node_key: bytes, node_type: object) -> bytes:
    if node_type == 1:
        return node_key
    if len(node_key) != 32:
        raise MegaKeyError("Could not decrypt the MEGA file metadata.")
    return bytes(node_key[index] ^ node_key[index + 16] for index in range(16))


def build_entries(
    nodes: list[dict],
    key: bytes,
    public_root: dict,
    root: dict,
) -> dict[str, _Entry]:
    entries: dict[str, _Entry] = {}
    for node in nodes:
        if node.get("t") not in {0, 1}:
            continue
        handle = node.get("h")
        if not isinstance(handle, str) or not HANDLE_RE.fullmatch(handle):
            continue
        node_key = decrypt_node_key(node, key, public_root["h"])
        name = handle
        attributes = node.get("a")
        if isinstance(attributes, str) and attributes:
            attrs = decrypt_attrs(attributes, node_attr_key(node_key, node.get("t")))
            if isinstance(attrs.get("n"), str) and attrs["n"]:
                name = clean_text(attrs["n"])
        size = 0
        key_result = None
        if node.get("t") == 0:
            try:
                size = int(node.get("s"))
            except (TypeError, ValueError) as exc:
                raise MegaKeyError("MEGA returned an invalid file size.") from exc
            if size < 0:
                raise MegaKeyError("MEGA returned an invalid file size.")
            key_result = file_key(node_key)
        entries[handle] = _Entry(
            handle=handle,
            parent=str(node.get("p") or ""),
            name=name,
            size=size,
            is_folder=node.get("t") == 1,
            key=key_result,
        )
    root_entry = entries.get(root["h"])
    if root_entry is None:
        raise MegaKeyError("MEGA did not return the folder contents.")
    for entry in entries.values():
        if entry.handle == root["h"]:
            continue
        parent = entries.get(entry.parent)
        if parent is not None and parent.is_folder:
            parent.children.append(entry)
        elif root["h"] == public_root["h"]:
            root_entry.children.append(entry)
    return entries


def sort_entries(entries: list[_Entry]) -> None:
    entries.sort(key=lambda entry: (0 if entry.is_folder else 1, entry.name.lower()))


def walk_files(root: _Entry) -> list[tuple[str, _Entry]]:
    output: list[tuple[str, _Entry]] = []
    seen = {root.handle}

    def walk(folder: _Entry, path: str, depth: int) -> None:
        if depth > MAX_FOLDER_DEPTH:
            raise MegaKeyError("That MEGA folder is nested too deeply.")
        sort_entries(folder.children)
        for child in folder.children:
            if child.handle in seen:
                continue
            seen.add(child.handle)
            child_path = f"{path}/{child.name}" if path else child.name
            if child.is_folder:
                walk(child, child_path, depth + 1)
            else:
                output.append((child_path, child))

    walk(root, "", 0)
    return output


class MegaKeyResolver:
    def __init__(self, session: aiohttp.ClientSession | None = None):
        self._session = session or aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30, connect=10, sock_read=30)
        )
        self._owns_session = session is None
        self._cache: dict[bytes, tuple[float, dict[str, DownloadKey], dict[str, DownloadKey]]] = {}

    def _cache_token(self, link: MegaLink) -> bytes:
        material = (
            f"{link.kind}:{link.handle}:{link.key}:"
            f"{link.selection_type}:{link.selection_handle}"
        )
        return hashlib.sha256(material.encode()).digest()

    def _cache_get(
        self, token: bytes
    ) -> tuple[dict[str, DownloadKey], dict[str, DownloadKey]] | None:
        now = time.monotonic()
        cached = self._cache.get(token)
        if cached is None:
            return None
        expires_at, paths, handles = cached
        if expires_at <= now:
            self._cache.pop(token, None)
            return None
        return paths, handles

    def _cache_put(
        self,
        token: bytes,
        paths: dict[str, DownloadKey],
        handles: dict[str, DownloadKey],
    ) -> None:
        now = time.monotonic()
        expired = [key for key, value in self._cache.items() if value[0] <= now]
        for key in expired:
            self._cache.pop(key, None)
        while len(self._cache) >= MAX_KEY_CACHE:
            oldest = min(self._cache, key=lambda key: self._cache[key][0])
            self._cache.pop(oldest, None)
        self._cache[token] = (now + KEY_CACHE_SECONDS, paths, handles)

    async def _fetch_nodes(self, handle: str) -> list[dict]:
        request_id = secrets.randbelow(999_999_999) + 1
        url = f"{MEGA_API}?id={request_id}&n={quote(handle)}"
        timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=30)
        try:
            async with self._session.post(
                url,
                json=[{"a": "f", "c": 1, "r": 1, "ca": 1}],
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=timeout,
            ) as response:
                if response.status != 200:
                    log.error("mega_folder_failed status=%s", response.status)
                    raise MegaKeyError("MEGA did not return the folder contents.")
                declared = int(response.content_length or 0)
                if declared > MAX_API_BYTES:
                    raise MegaKeyError("MEGA returned too much data.")
                body = await response.read()
        except MegaKeyError:
            raise
        except TimeoutError as exc:
            raise MegaKeyError("MEGA timed out. Try again.") from exc
        except aiohttp.ClientError as exc:
            log.error("mega_folder_unreachable error=%s", type(exc).__name__)
            raise MegaKeyError("Could not reach MEGA. Try again.") from exc
        if len(body) > MAX_API_BYTES:
            raise MegaKeyError("MEGA returned too much data.")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MegaKeyError("MEGA returned an unreadable response.") from exc
        if not isinstance(payload, list) or not payload:
            raise MegaKeyError("MEGA returned an unreadable response.")
        if isinstance(payload[0], int):
            log.error("mega_folder_rejected code=%s", payload[0])
            raise MegaKeyError("MEGA rejected the folder request.")
        item = payload[0]
        nodes = item.get("f") if isinstance(item, dict) else None
        if not isinstance(nodes, list):
            raise MegaKeyError("MEGA did not return the folder contents.")
        if len(nodes) > MAX_FOLDER_NODES:
            raise MegaKeyError("That MEGA folder is too large.")
        log.info("mega_folder_nodes nodes=%s", len(nodes))
        return [node for node in nodes if isinstance(node, dict)]

    def _keys_from_nodes(self, nodes: list[dict], key: bytes, link: MegaLink) -> tuple[
        dict[str, DownloadKey], dict[str, DownloadKey]
    ]:
        public_root = find_public_root(nodes)
        start_handle = link.selection_handle if link.selection_type == "folder" else None
        root = find_folder_root(nodes, start_handle)
        entries = build_entries(nodes, key, public_root, root)
        if link.selection_type == "file":
            entry = entries.get(link.selection_handle or "")
            if entry is None or entry.is_folder or entry.key is None:
                raise MegaKeyError("That MEGA file is no longer available.")
            return {entry.name: entry.key}, {entry.handle: entry.key}
        root_entry = entries[root["h"]]
        paths: dict[str, DownloadKey] = {}
        handles: dict[str, DownloadKey] = {}
        for path, entry in walk_files(root_entry):
            if entry.key is None:
                continue
            paths[path] = entry.key
            handles[entry.handle] = entry.key
        return paths, handles

    async def resolve(self, source_url: str, file_path: str, file_name: str) -> DownloadKey:
        link = parse_link(source_url)
        if link.kind == "file":
            key = file_key(decode_key(link.key))
            log.info("mega_key_resolved kind=file")
            return key
        token = self._cache_token(link)
        cached = self._cache_get(token)
        if cached is None:
            nodes = await self._fetch_nodes(link.handle)
            paths, handles = self._keys_from_nodes(nodes, folder_key(link.key), link)
            self._cache_put(token, paths, handles)
            log.info("mega_key_resolved kind=folder handles=%s", len(handles))
        else:
            paths, handles = cached
            log.info("mega_key_cache_hit kind=folder handles=%s", len(handles))
        if link.selection_type == "file":
            key = next(iter(handles.values()), None)
            if key is None:
                raise MegaKeyError("That MEGA file is no longer available.")
            return key
        key = paths.get(file_path)
        if key is None:
            matches = [candidate for path, candidate in paths.items() if path.rsplit("/", 1)[-1] == file_name]
            if len(matches) == 1:
                key = matches[0]
            elif len(matches) > 1:
                key = next(
                    (
                        candidate
                        for path, candidate in paths.items()
                        if path == file_name
                    ),
                    None,
                )
        if key is None:
            log.error("mega_key_missing files=%s", len(paths))
            raise MegaKeyError("Could not find that MEGA file's decryption key.")
        return key

    async def close(self) -> None:
        if self._owns_session:
            await self._session.close()
