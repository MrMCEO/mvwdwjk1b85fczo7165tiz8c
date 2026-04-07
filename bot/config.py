from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
    )

    bot_token: str
    admin_ids: list[int] = []
    db_url: str = "postgresql+asyncpg://bothost_db_f856fb47afb1:sww8k3UMA_XkaJper6w4HyX1UARVG15toVC7lCnfkAg@node1.pghost.ru:15540/bothost_db_f856fb47afb1"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | list | int | None) -> list[int]:
        if not v and v != 0:
            return []
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            return [int(i.strip()) for i in v.split(",") if i.strip()]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
