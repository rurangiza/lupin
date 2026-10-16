from enum import StrEnum
from functools import lru_cache

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramMode(StrEnum):
    POLLING = "polling"
    WEBHOOK = "webhook"
    DISABLED = "disabled"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://lupin:lupin@localhost:5432/lupin"

    openai_api_key: SecretStr
    openai_model: str = "gpt-5-mini"
    tavily_api_key: SecretStr | None = None

    owner_name: str = "Owner"
    owner_timezone: str = "Europe/Brussels"
    history_limit: int = 30
    max_tool_rounds: int = 5
    tool_timeout_seconds: float = 20.0

    telegram_mode: TelegramMode = TelegramMode.POLLING
    telegram_bot_token: SecretStr | None = None
    telegram_owner_user_id: int | None = None
    telegram_webhook_secret: SecretStr | None = None
    # Public base URL of the app, e.g. a named tunnel or a load balancer.
    # When unset in webhook mode, the URL is read from cloudflared's quick tunnel.
    public_base_url: str | None = None
    cloudflared_metrics_url: str | None = None

    debug_api_enabled: bool = False

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # `KEY=` in .env means "not set", not "set to an empty string".
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _check_telegram(self) -> "Settings":
        if self.telegram_mode is TelegramMode.DISABLED:
            return self
        if self.telegram_bot_token is None or self.telegram_owner_user_id is None:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_OWNER_USER_ID are required "
                "unless TELEGRAM_MODE=disabled"
            )
        if self.telegram_mode is TelegramMode.WEBHOOK:
            if self.telegram_webhook_secret is None:
                raise ValueError("TELEGRAM_WEBHOOK_SECRET is required in webhook mode")
            if self.public_base_url is None and self.cloudflared_metrics_url is None:
                raise ValueError("Webhook mode needs PUBLIC_BASE_URL or CLOUDFLARED_METRICS_URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
