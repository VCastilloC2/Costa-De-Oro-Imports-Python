from functools import lru_cache
from pathlib import Path
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)
    app_name: str = Field("Costa De Oro Imports API", validation_alias=AliasChoices("NombreAplicacion", "APP_NAME"))
    port: int = Field(8080, validation_alias=AliasChoices("PORT", "PuertoServidor"))
    db_url: str = Field("mysql+pymysql://localhost:3306/db_beer", validation_alias=AliasChoices("DATABASE_URL", "DB_URL", "SPRING_DATASOURCE_URL"))
    db_username: str = Field("", validation_alias=AliasChoices("DB_USERNAME", "SPRING_DATASOURCE_USERNAME"))
    db_password: str = Field("", validation_alias=AliasChoices("DB_PASSWORD", "SPRING_DATASOURCE_PASSWORD"))
    valkey_url: str | None = Field(default=None, validation_alias=AliasChoices("VALKEY_URL", "REDIS_URL"))
    valkey_cache_ttl_seconds: int = Field(300, ge=1, le=86400, validation_alias=AliasChoices("VALKEY_CACHE_TTL_SECONDS"))
    valkey_auth_ttl_seconds: int = Field(300, ge=1, le=86400, validation_alias=AliasChoices("VALKEY_AUTH_TTL_SECONDS"))
    prediction_data_source: str = Field("database", validation_alias=AliasChoices("PREDICTION_DATA_SOURCE"))
    prediction_dataset_csv: Path = Field(PROJECT_ROOT / "app" / "prediction" / "data" / "costa_de_oro_ventas.csv", validation_alias=AliasChoices("PREDICTION_DATASET_CSV"))
    # --- Servicio ML de predicciones (TensorFlow) ---
    prediction_model_dir: Path = Field(PROJECT_ROOT / "app" / "prediction" / "artifacts", validation_alias=AliasChoices("PREDICTION_MODEL_DIR"))
    prediction_min_training_samples: int = Field(18, ge=6, le=10000, validation_alias=AliasChoices("PREDICTION_MIN_TRAINING_SAMPLES"))
    prediction_max_concurrent: int = Field(4, ge=1, le=64, validation_alias=AliasChoices("PREDICTION_MAX_CONCURRENT"))
    prediction_inference_timeout_seconds: float = Field(30.0, ge=1, le=600, validation_alias=AliasChoices("PREDICTION_INFERENCE_TIMEOUT_SECONDS"))
    prediction_dedup_window_seconds: int = Field(300, ge=0, le=86400, validation_alias=AliasChoices("PREDICTION_DEDUP_WINDOW_SECONDS"))
    prediction_training_lock_ttl_seconds: int = Field(3600, ge=60, le=86400, validation_alias=AliasChoices("PREDICTION_TRAINING_LOCK_TTL_SECONDS"))
    prediction_allowed_roles: str = Field("ADMIN", validation_alias=AliasChoices("PREDICTION_ALLOWED_ROLES"))
    prediction_access_log_enabled: bool = Field(True, validation_alias=AliasChoices("PREDICTION_ACCESS_LOG_ENABLED"))
    spring_jpa_hibernate_ddl_auto: str = "validate"
    prediccion_api_url: str | None = None
    prediccion_api_key: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_allowed_client_ids: str | None = None
    apple_allowed_client_ids: str | None = None
    remember_me_key: str | None = None
    remember_me_token: str | None = None
    password_url_recaptcha: str = "https://www.google.com/recaptcha/api/siteverify"
    password_key_recaptcha: str | None = None
    mail_username: str | None = None
    mail_password: str | None = None
    cloud_name: str | None = None
    cloud_api_key: str | None = None
    cloud_api_secret: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    mercado_pago_access_token: str | None = None
    jwt_secret_ecommerce: str = Field("REPLACE_THIS_SECRET", validation_alias=AliasChoices("JWT_SECRET_ECOMMERCE", "JWT_SECRET"))
    jwt_issuer_ecommerce: str = "CostaDeOroImports"
    frontend_url: str = "http://localhost:3000"
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:8080,https://costa-de-oro-imports-python.onrender.com,https://costa-de-oro-imports-python-vatg.vercel.app"
    springdoc_api_docs_enabled: bool = True
    springdoc_swagger_ui_enabled: bool = True
    mcp_client_enabled: bool = False

    @property
    def cors_origins(self) -> list[str]:
        return [x.strip() for x in self.cors_allowed_origins.split(",") if x.strip()]

    @property
    def prediction_roles(self) -> set[str]:
        return {x.strip().upper() for x in self.prediction_allowed_roles.split(",") if x.strip()} or {"ADMIN"}

@lru_cache
def get_settings() -> Settings:
    return Settings()
settings = get_settings()
