"""
config/settings.py
Application configuration loaded from environment variables.
Uses pydantic-settings for type-safe config with .env file support.
"""
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: str = Field(default="development")
    app_port: int = Field(default=8000)
    app_host: str = Field(default="127.0.0.1")
    log_level: str = Field(default="INFO")

    # Database
    database_path: str = Field(default="./database/application.db")

    # Ollama
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3.2")
    ollama_concurrency: int = Field(default=1)
    ollama_timeout: int = Field(default=120)

    # Agent Behavior — Hard Non-Negotiable Safety Policy
    dry_run: bool = Field(default=True)
    auto_submit: bool = Field(default=False)
    final_submission_allowed: bool = Field(default=False)
    real_applications_enabled: bool = Field(default=False)
    min_match_score: int = Field(default=65)
    max_applications_per_day: int = Field(default=25)
    action_delay_seconds: float = Field(default=2.0)

    def model_post_init(self, __context):
        """Force overrides to guarantee safety in code."""
        object.__setattr__(self, "auto_submit", False)
        object.__setattr__(self, "final_submission_allowed", False)
        object.__setattr__(self, "real_applications_enabled", False)
        object.__setattr__(self, "dry_run", True)

    # Browser
    browser_headless: bool = Field(default=False)
    browser_slow_mo_ms: int = Field(default=500)

    # Paths
    applications_dir: str = Field(default="./applications")
    resume_generated_dir: str = Field(default="./resume/generated")
    logs_dir: str = Field(default="./logs")

    # Webhooks & n8n Integration
    webhook_enabled: bool = Field(default=False)
    webhook_url: str = Field(default="")
    webhook_secret: str = Field(default="")
    webhook_events: list[str] = Field(
        default=["APPLICATION_SUBMITTED", "HANDOFF_REQUIRED", "DAILY_LIMIT_REACHED", "AGENT_STATE_CHANGED"]
    )

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"

    @property
    def database_path_resolved(self) -> Path:
        return Path(self.database_path).resolve()

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


# Singleton — import this everywhere
settings = Settings()
