"""Genera una clave aleatoria para PREDICCION_API_KEY.

Uso:  python scripts/generar_clave.py
Copia el resultado en tu .env. No lo pegues en chats, issues ni commits.
"""
import secrets

if __name__ == "__main__":
    print(secrets.token_urlsafe(48))
