import os
from pathlib import Path

import redis
from dotenv import load_dotenv

# Cargar variables del archivo .env
ruta_env = Path(__file__).resolve().parent / ".env"
load_dotenv(ruta_env, override=True)

url = os.getenv("VALKEY_URL")

if not url:
    raise RuntimeError("No se encontró VALKEY_URL en el archivo .env")

cliente = redis.Redis.from_url(
    url,
    decode_responses=True,
    socket_connect_timeout=10,
    socket_timeout=10,
)

try:
    print("1. Probando autenticación...")
    print("PING:", cliente.ping())

    print("\n2. Probando escritura...")
    cliente.set("prueba:costa-de-oro", "conexion-correcta", ex=60)

    print("\n3. Probando lectura...")
    valor = cliente.get("prueba:costa-de-oro")
    print("Valor:", valor)

    print("\n4. Probando eliminación...")
    cliente.delete("prueba:costa-de-oro")

    print("\nVALKEY FUNCIONA CORRECTAMENTE")

except redis.exceptions.RedisError as error:
    print("\nERROR DE REDIS/VALKEY:")
    print(type(error).__name__, str(error))

finally:
    cliente.close()