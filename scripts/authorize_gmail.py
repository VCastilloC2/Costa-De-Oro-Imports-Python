"""Authorize this application to send mail from the configured Gmail account."""
from __future__ import annotations

from app.core.config import settings


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not settings.gmail_credentials_file.is_file():
        raise SystemExit(f"No se encontró el JSON OAuth: {settings.gmail_credentials_file}")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(settings.gmail_credentials_file),
        ["https://www.googleapis.com/auth/gmail.send"],
    )
    flow.redirect_uri = settings.gmail_oauth_redirect_uri
    credentials = flow.run_local_server(
        host="localhost", port=8765, open_browser=True, authorization_prompt_message="Autoriza Gmail en el navegador: {url}",
        success_message="Autorización completada. Puedes cerrar esta pestaña.",
    )
    settings.gmail_token_file.parent.mkdir(parents=True, exist_ok=True)
    settings.gmail_token_file.write_text(credentials.to_json(), encoding="utf-8")
    try:
        settings.gmail_token_file.chmod(0o600)
    except OSError:
        pass
    print(f"Token OAuth guardado en {settings.gmail_token_file}")


if __name__ == "__main__":
    main()
