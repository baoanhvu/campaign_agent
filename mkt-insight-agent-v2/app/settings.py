"""Environment-driven configuration via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MKT_DATABASE__")
    url: str = ""
    pool_size_ro: int = 5
    pool_size_trace: int = 2
    pool_size_admin: int = 2
    query_timeout_s: int = 30


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")
    api_key: str = ""
    base_url: str = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
    model: str = "qwen/qwen3.6-flash"
    judge_model: str = "qwen/qwen3.6-flash"
    max_tokens: int = 2048
    temperature: float = 0.0
    rate_limit_rpm: int = 8
    timeout_s: int = 60
    max_retries: int = 3


class AdminSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MKT_ADMIN__")
    token: str = ""


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    profile: str = Field(default="local", validation_alias="APP_PROFILE")
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
