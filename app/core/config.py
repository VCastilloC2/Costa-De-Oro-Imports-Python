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
    # Cuánto se reutiliza una predicción ya calculada para Spring (/api/prediccion/*): entrenar es caro.
    prediction_cache_ttl_seconds: int = Field(3600, ge=10, le=86400, validation_alias=AliasChoices("PREDICTION_CACHE_TTL_SECONDS"))
    # --- Passkeys (WebAuthn / FIDO2) ---
    # Vacío = passkeys desactivadas (los endpoints responden 503), igual que PASSKEY_RP_ID en Flutter.
    passkey_rp_id: str = Field("", validation_alias=AliasChoices("PASSKEY_RP_ID"))
    passkey_rp_name: str = Field("Costa de Oro Imports", validation_alias=AliasChoices("PASSKEY_RP_NAME"))
    # Orígenes aceptados en clientDataJSON: https://<rp_id> (iOS/web) y android:apk-key-hash:<hash> (Android).
    passkey_expected_origins: str = Field("", validation_alias=AliasChoices("PASSKEY_EXPECTED_ORIGINS"))
    passkey_challenge_ttl_seconds: int = Field(300, ge=30, le=900, validation_alias=AliasChoices("PASSKEY_CHALLENGE_TTL_SECONDS"))
    passkey_cache_ttl_seconds: int = Field(3600, ge=60, le=604800, validation_alias=AliasChoices("PASSKEY_CACHE_TTL_SECONDS"))
    passkey_session_ttl_seconds: int = Field(3600, ge=300, le=86400, validation_alias=AliasChoices("PASSKEY_SESSION_TTL_SECONDS"))
    passkey_ceremony_timeout_ms: int = Field(120000, ge=30000, le=600000, validation_alias=AliasChoices("PASSKEY_CEREMONY_TIMEOUT_MS"))
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
    # --- Gemini: cliente compartido, límites y asistentes ---
    gemini_timeout_seconds: float = Field(30.0, ge=5, le=300, validation_alias=AliasChoices("GEMINI_TIMEOUT_SECONDS"))
    gemini_max_retries: int = Field(2, ge=0, le=5, validation_alias=AliasChoices("GEMINI_MAX_RETRIES"))
    gemini_max_output_tokens: int = Field(800, ge=64, le=8192, validation_alias=AliasChoices("GEMINI_MAX_OUTPUT_TOKENS"))
    chatbot_context_cache_seconds: int = Field(60, ge=0, le=3600, validation_alias=AliasChoices("CHATBOT_CONTEXT_CACHE_SECONDS"))
    chatbot_rate_limit_per_minute: int = Field(20, ge=1, le=600, validation_alias=AliasChoices("CHATBOT_RATE_LIMIT_PER_MINUTE"))
    shop_assistant_enabled: bool = Field(True, validation_alias=AliasChoices("SHOP_ASSISTANT_ENABLED"))
    shop_assistant_rate_limit_per_minute: int = Field(10, ge=1, le=600, validation_alias=AliasChoices("SHOP_ASSISTANT_RATE_LIMIT_PER_MINUTE"))
    shop_assistant_daily_limit: int = Field(2000, ge=1, le=1000000, validation_alias=AliasChoices("SHOP_ASSISTANT_DAILY_LIMIT"))
    shop_assistant_max_output_tokens: int = Field(500, ge=64, le=4096, validation_alias=AliasChoices("SHOP_ASSISTANT_MAX_OUTPUT_TOKENS"))
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
    def passkey_origins(self) -> list[str]:
        origins = [x.strip() for x in self.passkey_expected_origins.split(",") if x.strip()]
        if not origins and self.passkey_rp_id:
            origins = [f"https://{self.passkey_rp_id.strip()}"]
        return origins

    @property
    def prediction_roles(self) -> set[str]:
        return {x.strip().upper() for x in self.prediction_allowed_roles.split(",") if x.strip()} or {"ADMIN"}

@lru_cache
def get_settings() -> Settings:
    return Settings()
settings = get_settings()
