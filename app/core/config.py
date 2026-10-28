from functools import lru_cache
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)
    app_name: str = Field("Costa De Oro Imports API", validation_alias=AliasChoices("NombreAplicacion", "APP_NAME"))
    port: int = Field(8080, validation_alias=AliasChoices("PORT", "PuertoServidor"))
    db_url: str = Field("mysql+pymysql://localhost:3306/db_beer", validation_alias=AliasChoices("DATABASE_URL", "DB_URL", "SPRING_DATASOURCE_URL"))
    db_username: str = Field("", validation_alias=AliasChoices("DB_USERNAME", "SPRING_DATASOURCE_USERNAME"))
    db_password: str = Field("", validation_alias=AliasChoices("DB_PASSWORD", "SPRING_DATASOURCE_PASSWORD"))
    spring_jpa_hibernate_ddl_auto: str = "validate"
    prediccion_api_url: str | None = None
    prediccion_api_key: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_allowed_client_ids: str | None = None
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
    cors_allowed_origins: str = "http://localhost:3000,http://localhost:8080"
    springdoc_api_docs_enabled: bool = True
    springdoc_swagger_ui_enabled: bool = True
    mcp_client_enabled: bool = False

    @property
    def cors_origins(self) -> list[str]:
        return [x.strip() for x in self.cors_allowed_origins.split(",") if x.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
settings = get_settings()
