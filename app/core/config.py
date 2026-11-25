import base64
from functools import lru_cache
from pathlib import Path
import re
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve_runtime_file(configured_path: Path) -> Path:
    """Resolve configured files from the project or Render's mounted secret directory."""
    path = Path(configured_path).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.append(PROJECT_ROOT / path)
    # Render Secret Files are mounted read-only at /etc/secrets/<filename>.
    candidates.append(Path("/etc/secrets") / path.name)
    unique_candidates = list(dict.fromkeys(candidates))
    return next((candidate for candidate in unique_candidates if candidate.is_file()), unique_candidates[0])

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)
    app_name: str = Field("Costa De Oro Imports API", validation_alias=AliasChoices("NombreAplicacion", "APP_NAME"))
    port: int = Field(8080, validation_alias=AliasChoices("PORT", "PuertoServidor"))
    db_url: str = Field("mysql+pymysql://jdbc:mysql://localhost:3306/db_beer?createDatabaseIfNotExist=true&useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=UTC", validation_alias=AliasChoices("DATABASE_URL", "DB_URL", "SPRING_DATASOURCE_URL"))
    db_username: str = Field("", validation_alias=AliasChoices("DB_USERNAME", "SPRING_DATASOURCE_USERNAME"))
    db_password: str = Field("", validation_alias=AliasChoices("DB_PASSWORD", "SPRING_DATASOURCE_PASSWORD"))
    # Render/MySQL plans often cap a DB user at five connections. Keep a small per-instance pool.
    db_pool_size: int = Field(2, ge=1, le=10, validation_alias=AliasChoices("DB_POOL_SIZE"))
    db_max_overflow: int = Field(0, ge=0, le=10, validation_alias=AliasChoices("DB_MAX_OVERFLOW"))
    valkey_url: str | None = Field(default=None, validation_alias=AliasChoices("VALKEY_URL", "REDIS_URL"))
    valkey_cache_ttl_seconds: int = Field(300, ge=1, le=86400, validation_alias=AliasChoices("VALKEY_CACHE_TTL_SECONDS"))
    valkey_auth_ttl_seconds: int = Field(300, ge=1, le=86400, validation_alias=AliasChoices("VALKEY_AUTH_TTL_SECONDS"))
    prediction_data_source: str = Field("database", validation_alias=AliasChoices("PREDICTION_DATA_SOURCE"))
    prediction_train_before_startup: bool = Field(
        False, validation_alias=AliasChoices("PREDICTION_TRAIN_BEFORE_STARTUP"))
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
    prediction_cache_ttl_seconds: int = Field(300, ge=10, le=86400, validation_alias=AliasChoices("PREDICTION_CACHE_TTL_SECONDS"))
    # --- Passkeys (WebAuthn / FIDO2) ---
    # Vacío = passkeys desactivadas (los endpoints responden 503), igual que PASSKEY_RP_ID en Flutter.
    passkey_rp_id: str = Field("", validation_alias=AliasChoices("PASSKEY_RP_ID"))
    passkey_rp_name: str = Field("Costa de Oro Imports", validation_alias=AliasChoices("PASSKEY_RP_NAME"))
    # Orígenes aceptados en clientDataJSON: https://<rp_id> (iOS/web) y android:apk-key-hash:<hash> (Android).
    passkey_expected_origins: str = Field("", validation_alias=AliasChoices("PASSKEY_EXPECTED_ORIGINS"))
    passkey_android_package_name: str = Field(
        "", validation_alias=AliasChoices("PASSKEY_ANDROID_PACKAGE_NAME"))
    passkey_android_sha256_fingerprints: str = Field(
        "", validation_alias=AliasChoices("PASSKEY_ANDROID_SHA256_CERT_FINGERPRINTS"))
    passkey_challenge_ttl_seconds: int = Field(300, ge=30, le=900, validation_alias=AliasChoices("PASSKEY_CHALLENGE_TTL_SECONDS"))
    passkey_cache_ttl_seconds: int = Field(3600, ge=60, le=604800, validation_alias=AliasChoices("PASSKEY_CACHE_TTL_SECONDS"))
    passkey_session_ttl_seconds: int = Field(3600, ge=300, le=86400, validation_alias=AliasChoices("PASSKEY_SESSION_TTL_SECONDS"))
    passkey_ceremony_timeout_ms: int = Field(120000, ge=30000, le=600000, validation_alias=AliasChoices("PASSKEY_CEREMONY_TIMEOUT_MS"))
    # --- OpenStreetMap Nominatim (búsqueda puntual de ciudades, nunca autocompletado) ---
    nominatim_enabled: bool = Field(True, validation_alias=AliasChoices("NOMINATIM_ENABLED"))
    nominatim_base_url: str = Field("https://nominatim.openstreetmap.org", validation_alias=AliasChoices("NOMINATIM_BASE_URL"))
    nominatim_user_agent: str = Field(
        "CostaDeOroImportsFastAPI/1.0 (https://costa-de-oro-imports-python.onrender.com)",
        validation_alias=AliasChoices("NOMINATIM_USER_AGENT"),
    )
    nominatim_timeout_seconds: float = Field(8.0, ge=2, le=30, validation_alias=AliasChoices("NOMINATIM_TIMEOUT_SECONDS"))
    nominatim_cache_seconds: int = Field(604800, ge=60, le=2592000, validation_alias=AliasChoices("NOMINATIM_CACHE_SECONDS"))
    spring_jpa_hibernate_ddl_auto: str = "validate"
    prediccion_api_url: str | None = None
    prediccion_api_key: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_allowed_client_ids: str | None = None
    apple_allowed_client_ids: str | None = None
    apple_android_package_name: str = Field(
        "com.example.costa_de_oro_imports",
        validation_alias=AliasChoices("APPLE_ANDROID_PACKAGE_NAME"),
    )
    remember_me_key: str | None = None
    remember_me_token: str | None = None
    password_url_recaptcha: str = "https://www.google.com/recaptcha/api/siteverify"
    password_key_recaptcha: str | None = None
    gmail_credentials_file: Path = Field(PROJECT_ROOT / "credentials.json", validation_alias=AliasChoices("GMAIL_CREDENTIALS_FILE"))
    gmail_token_file: Path = Field(PROJECT_ROOT / "gmail-token.json", validation_alias=AliasChoices("GMAIL_TOKEN_FILE"))
    gmail_sender: str = Field("costadeoroimports2@gmail.com", validation_alias=AliasChoices("GMAIL_SENDER"))
    gmail_oauth_redirect_uri: str = Field("http://localhost:8765/", validation_alias=AliasChoices("GMAIL_OAUTH_REDIRECT_URI"))
    frontend_url: str = Field("http://localhost:3000", validation_alias=AliasChoices("FRONTEND_URL"))
    cloud_name: str | None = None
    cloud_api_key: str | None = None
    cloud_api_secret: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = Field("gemini-3.5-flash-lite", validation_alias=AliasChoices("GEMINI_MODEL"))
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
        # Android Credential Manager reports the signing certificate hash as
        # android:apk-key-hash:<base64url(SHA-256 certificate)>.
        # Derive these from the same fingerprints published in assetlinks.json
        # so debug/release signing changes cannot silently desynchronize origins.
        for fingerprint in self.passkey_android_sha256_fingerprints.split(","):
            normalized = fingerprint.strip().replace(":", "")
            if re.fullmatch(r"[0-9a-fA-F]{64}", normalized):
                digest = base64.urlsafe_b64encode(bytes.fromhex(normalized)).decode("ascii").rstrip("=")
                origins.append(f"android:apk-key-hash:{digest}")
        return list(dict.fromkeys(origins))

    @property
    def prediction_roles(self) -> set[str]:
        return {x.strip().upper() for x in self.prediction_allowed_roles.split(",") if x.strip()} or {"ADMIN"}

@lru_cache
def get_settings() -> Settings:
    return Settings()
settings = get_settings()
