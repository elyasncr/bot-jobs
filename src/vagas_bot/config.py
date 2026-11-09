"""Configuration: config.yaml (behaviour) + environment / .env (secrets)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchConfig(_Strict):
    queries: list[str] = Field(min_length=1)
    country: str = "br"
    date_posted: Literal["all", "today", "3days", "week", "month"] = "3days"
    pages_per_query: int = Field(default=1, ge=1)
    publishers: list[str] = Field(default_factory=list)
    remote_only: bool = False  # envia work_from_home=true à JSearch
    include_international_remote: bool = True


class FiltersConfig(_Strict):
    modalities: list[Literal["remote", "hybrid", "onsite"]] = Field(
        default_factory=lambda: ["remote", "hybrid"]
    )
    hybrid_allowed_cities: list[str] = Field(default_factory=list)
    exclude_title_keywords: list[str] = Field(default_factory=list)
    include_uncertain_contract: bool = True


class OllamaEmbeddingConfig(_Strict):
    model: str = "bge-m3"


class SentenceTransformersConfig(_Strict):
    model: str = "BAAI/bge-m3"
    device: Literal["cuda", "cpu"] = "cuda"
    batch_size: int = Field(default=16, ge=1)
    query_prefix: str = ""
    passage_prefix: str = ""


class EmbeddingsConfig(_Strict):
    provider: Literal["ollama", "sentence-transformers"] = "ollama"
    top_n: int = Field(default=40, ge=1)
    cv_representation: Literal["blocks_mean", "compact"] = "blocks_mean"
    ollama: OllamaEmbeddingConfig = Field(default_factory=OllamaEmbeddingConfig)
    sentence_transformers: SentenceTransformersConfig = Field(
        default_factory=SentenceTransformersConfig
    )


class OllamaLLMConfig(_Strict):
    host: str = "http://localhost:11434"
    model: str = "qwen3.5:9b"
    num_ctx: int = Field(default=16384, ge=2048)
    temperature: float = Field(default=0, ge=0)
    think: bool = False
    keep_alive: str = "10m"
    request_timeout_s: float = Field(default=180, gt=0)


class AnthropicLLMConfig(_Strict):
    model: str = "claude-haiku-5-5"


class LLMConfig(_Strict):
    provider: Literal["ollama", "anthropic"] = "ollama"
    max_calls_per_run: int = Field(default=60, ge=0)
    ollama: OllamaLLMConfig = Field(default_factory=OllamaLLMConfig)
    anthropic: AnthropicLLMConfig = Field(default_factory=AnthropicLLMConfig)


class ScoringConfig(_Strict):
    min_score_to_email: int = Field(default=50, ge=0, le=100)


class EmailConfig(_Strict):
    send_when_empty: bool = False
    max_jobs: int = Field(default=30, ge=1)


class StateConfig(_Strict):
    prune_after_days: int = Field(default=60, ge=1)


class AppConfig(_Strict):
    search: SearchConfig
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    state: StateConfig = Field(default_factory=StateConfig)


class Secrets(BaseSettings):
    """Secrets come only from the environment or .env — never from config.yaml."""

    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    rapidapi_key: SecretStr | None = None
    gmail_user: str | None = None
    gmail_app_password: SecretStr | None = None
    email_to: str | None = None
    ollama_host: str | None = None
    anthropic_api_key: SecretStr | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@dataclass(frozen=True)
class Settings:
    root: Path
    config: AppConfig
    secrets: Secrets

    @property
    def ollama_host(self) -> str:
        return self.secrets.ollama_host or self.config.llm.ollama.host

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def cv_path(self) -> Path:
        return self.data_dir / "cv.md"

    @property
    def seen_path(self) -> Path:
        return self.data_dir / "seen.json"

    @property
    def history_path(self) -> Path:
        return self.data_dir / "history.jsonl"

    @property
    def query_stats_path(self) -> Path:
        return self.data_dir / "query_stats.jsonl"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def preview_path(self) -> Path:
        return self.root / "preview.html"


class ConfigError(Exception):
    """Invalid or missing configuration, with a user-facing message in Portuguese."""


def load_app_config(path: Path) -> AppConfig:
    if not path.is_file():
        raise ConfigError(f"Arquivo de configuração não encontrado: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(raw)


def load_settings(config_path: Path, env_file: Path | None = None) -> Settings:
    """Load config.yaml and secrets. The project root is the folder of config.yaml."""
    config_path = config_path.resolve()
    root = config_path.parent
    env_path = env_file if env_file is not None else root / ".env"
    secrets = Secrets(_env_file=env_path if env_path.is_file() else None)  # type: ignore[call-arg]
    return Settings(root=root, config=load_app_config(config_path), secrets=secrets)


def required_env(
    cfg: AppConfig, *, collect: bool, send_email: bool, use_llm: bool
) -> list[str]:
    """Env vars required by the configured providers for this kind of run."""
    names: list[str] = []
    if collect:
        names.append("RAPIDAPI_KEY")
    if send_email:
        names += ["GMAIL_USER", "GMAIL_APP_PASSWORD", "EMAIL_TO"]
    if use_llm and cfg.llm.provider == "anthropic":
        names.append("ANTHROPIC_API_KEY")
    return names


def missing_env(settings: Settings, names: list[str]) -> list[str]:
    return [name for name in names if getattr(settings.secrets, name.lower()) is None]
