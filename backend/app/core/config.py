from functools import lru_cache

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration. Values come from the environment (.env); secrets have no defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "dev"
    log_level: str = "INFO"

    # Database
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    # Model artifacts / replay data (Lane B outputs, mounted read-only)
    artifacts_dir: str = "/opt/sentinel/ml/artifacts"
    replay_dir: str = "/opt/sentinel/data/replay"
    model_version: str = "v1"

    # Policy bands on the 0-1000 score: APPROVE < step_up <= STEP_UP < review <= REVIEW < decline <= DECLINE
    threshold_step_up: int = 300
    threshold_review: int = 650
    threshold_decline: int = 850

    # Graph uplift (DESIGN §3)
    uplift_known_fraud_2hop: float = 0.15
    uplift_component_size: float = 0.10
    uplift_component_size_min: int = 5
    uplift_names_per_device: float = 0.05
    uplift_names_per_device_min: int = 3
    graph_max_nodes: int = 200

    # Drift (DESIGN §7)
    drift_tighten_delta: int = 75
    adwin_delta: float = 0.002
    label_lag_events: int = 200
    replay_rate_per_sec: float = 20.0

    # Security (DESIGN §13)
    jwt_secret: SecretStr | None = None
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    demo_analyst_username: str | None = None
    demo_analyst_password: SecretStr | None = None
    demo_admin_username: str | None = None
    demo_admin_password: SecretStr | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    rate_limit_default: str = "120/minute"
    rate_limit_login: str = "10/minute"
    max_body_bytes: int = 64 * 1024

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        pw = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{pw}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
