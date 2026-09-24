"""Конфигурация приложения из переменных окружения и .env."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .envfile import read_env_value
from .logging import get_logger
from .vault import get_vault, migrate_env_secrets

log = get_logger(__name__)

FIELD_TO_ENV = {
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "owner_telegram_id": "OWNER_TELEGRAM_ID",
    "cookie_secret": "COOKIE_SECRET",
    "secret_path": "SECRET_PATH",
    "opencode_server_password": "OPENCODE_SERVER_PASSWORD",
}


def _default_data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "./data")).expanduser().resolve()


def _default_log_dir() -> Path:
    return Path(os.getenv("LOG_DIR", "~/Library/Logs/AIHub")).expanduser().resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Telegram
    telegram_bot_token: str = ""
    owner_telegram_id: int = 0

    # Public
    public_url: str = ""

    # Secrets
    cookie_secret: str = ""
    secret_path: str = ""

    # DSH
    dsh_home: Path = Path.home() / ".dsh"
    dsh_web_log: Path = Path.home() / ".dsh" / "web.log"
    dsh_web_host: str = "127.0.0.1"
    dsh_web_port: int = 3080

    # OpenCode
    opencode_serve_host: str = "127.0.0.1"
    opencode_serve_port: int = 4096
    opencode_server_username: str = ""
    opencode_server_password: str = ""

    # Gatekeeper
    gatekeeper_host: str = "0.0.0.0"
    gatekeeper_port: int = 8787

    # Aggregator sidecar
    aggregator_port: int = 8789

    # Env
    env: str = "production"
    # off | loopback | lan — кому доступен /auth/dev без Telegram
    local_login: str = "loopback"
    # tailscale = mesh only (no public Funnel); cloudflare = quick tunnel
    network_mode: str = "hybrid"
    # hybrid = LAN (HTTP) + Tailscale HTTPS; tailscale = только mesh; cloudflare = public tunnel
    log_dir: Path = Field(default_factory=_default_log_dir)
    log_level: str = "INFO"
    data_dir: Path = Field(default_factory=_default_data_dir)

    # Derived — .kill в cwd репозитория или ~/AIHub/.kill
    kill_file: Path = Field(default=Path(".kill"))

    @field_validator("dsh_home", "dsh_web_log", "log_dir", "data_dir", mode="before")
    @classmethod
    def expand_path(cls, v: object) -> Path:
        if isinstance(v, Path):
            return v.expanduser().resolve()
        return Path(str(v)).expanduser().resolve()

    @property
    def dsh_web_base(self) -> str:
        return f"http://{self.dsh_web_host}:{self.dsh_web_port}"

    @property
    def opencode_base(self) -> str:
        return f"http://{self.opencode_serve_host}:{self.opencode_serve_port}"

    @property
    def is_kill_switch_active(self) -> bool:
        candidates = [
            Path(".kill"),
            Path("~/AIHub/.kill").expanduser(),
            self.kill_file.expanduser(),
        ]
        return any(p.exists() for p in candidates)

    def ensure_secrets(self) -> None:
        """Секреты — в vault (не в .env). Плюс миграция legacy .env."""
        vault = get_vault()
        try:
            migrated = migrate_env_secrets(vault, Path(".env"))
            if migrated:
                log.info("secrets_migrated_to_vault", keys=migrated)
        except Exception:
            log.warning("vault_migrate_failed")

        if not self.cookie_secret:
            self.cookie_secret = secrets.token_urlsafe(32)
            try:
                vault.set("COOKIE_SECRET", self.cookie_secret)
            except Exception:
                log.warning("vault_unavailable")

        if not self.secret_path or self.secret_path in ("/p/xxxxxxxx", "/p/"):
            self.secret_path = "/p/" + secrets.token_urlsafe(12)
            try:
                vault.set("SECRET_PATH", self.secret_path)
            except Exception:
                log.warning("vault_unavailable")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "state.json").touch(exist_ok=True)


def _apply_vault(s: Settings) -> None:
    """Секреты из vault, если нет явной переменной окружения."""
    try:
        vault = get_vault()
        data = vault.load() if vault.exists() else {}
    except Exception:
        # vault недоступен — работаем без секретов (без текста исключения)
        log.warning("vault_unavailable")
        return
    for field, env_name in FIELD_TO_ENV.items():
        if env_name in os.environ:
            continue
        value = data.get(env_name)
        if value is None or value == "":
            continue
        if field == "owner_telegram_id":
            try:
                setattr(s, field, int(value))
            except ValueError:
                log.warning("vault_bad_owner_id")
            continue
        setattr(s, field, value)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    _apply_vault(s)
    s.ensure_dirs()
    return s


def clear_settings_cache() -> None:
    """Сброс после записи PUBLIC_URL сторожем / смены .env."""
    get_settings.cache_clear()


def reload_settings() -> Settings:
    clear_settings_cache()
    return get_settings()


def read_public_url_live() -> str:
    """Актуальный PUBLIC_URL: сначала .env на диске, потом settings (обход lru stale)."""
    val = read_env_value(Path(".env"), "PUBLIC_URL")
    if val:
        return val
    return get_settings().public_url or ""
