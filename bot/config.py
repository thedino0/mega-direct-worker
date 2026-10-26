import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Config:
    bot_token: str
    my_user_id: int
    worker_url: str
    worker_key: str
    api_id: int
    api_hash: str
    local_api_url: str
    temp_dir: Path

    @property
    def worker_resolve_url(self) -> str:
        base = self.worker_url.rstrip("/")
        if base.endswith("/bot/resolve"):
            return base
        return f"{base}/bot/resolve"


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is missing.")
    return value


def http_url(name: str, value: str, local_http: bool = False) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{name} must be a full http or https URL.")
    if (
        local_http
        and parsed.scheme == "http"
        and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
    ):
        raise ConfigError(f"{name} must use https.")
    return value.rstrip("/")


def positive_int(name: str, value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc
    if number <= 0:
        raise ConfigError(f"{name} must be greater than zero.")
    return number


def load_config() -> Config:
    bot_token = required("BOT_TOKEN")
    my_user_id = positive_int("MY_USER_ID", required("MY_USER_ID"))
    worker_url = http_url("WORKER_URL", required("WORKER_URL"), local_http=True)
    worker_key = required("WORKER_KEY")
    api_id = positive_int("API_ID", required("API_ID"))
    api_hash = required("API_HASH")
    if len(api_hash) != 32 or any(char not in "0123456789abcdefABCDEF" for char in api_hash):
        raise ConfigError("API_HASH must be 32 hex characters.")
    local_api_url = http_url("LOCAL_API_URL", required("LOCAL_API_URL"))
    temp_label = os.getenv("TEMP_DIR", "").strip() or "./tmp"
    temp_dir = Path(temp_label).expanduser().resolve()
    return Config(
        bot_token=bot_token,
        my_user_id=my_user_id,
        worker_url=worker_url,
        worker_key=worker_key,
        api_id=api_id,
        api_hash=api_hash,
        local_api_url=local_api_url,
        temp_dir=temp_dir,
    )
