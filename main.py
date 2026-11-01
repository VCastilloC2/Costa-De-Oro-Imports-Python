"""API de predicciones de Costa De Oro Imports (FastAPI).

Local:    python -m uvicorn main:app --reload --port 8000
Pruebas:  python -m pytest
"""
import logging
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Query

from app import servicio
from app.config import ConfiguracionError, get_settings
from app.schemas import GraficaResponse, ModeloResponse, PrediccionResponse, VentaRequest

logger = logging.getLogger("prediccion")

app = FastAPI(title="Costa De Oro Imports - API de Predicciones", version="3.0.0")


def verificar_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Solo el backend Spring debe llamar a esta API. La clave viene del .env."""
    try:
        clave = get_settings().api_key
    except ConfiguracionError as e:
        logger.error("Configuración incompleta: %s", e)
        raise HTTPException(status_code=500, detail="Servicio mal configurado")
    if not secrets.compare_digest(x_api_key or "", clave):
        raise HTTPException(status_code=401, detail="API key inválida")


@app.get("/")
async def health_check():
    return "The Health Check is Successful!"

@app.get(
    "/api/prediccion/datos-grafica",
    response_model=GraficaResponse,
    dependencies=[Depends(verificar_api_key)],
)
def datos_grafica(
    anios: int = Query(6, ge=1, le=10, description="Años de historia (meses = anios * 12)"),
    proyeccion_meses: int = Query(0, ge=0, le=24, description="Meses futuros a proyectar"),
):
    try:
        return servicio.construir_grafica(anios=anios, proyeccion_meses=proyeccion_meses)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Error generando datos de la gráfica")
        raise HTTPException(status_code=503, detail="No se pudo generar la predicción")


@app.post(
    "/api/prediccion/generar",
    response_model=PrediccionResponse,
    dependencies=[Depends(verificar_api_key)],
)
def generar(body: VentaRequest):
    try:
        valor = servicio.predecir_mes(body.anno, body.mes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Error generando predicción mensual")
        raise HTTPException(status_code=503, detail="No se pudo generar la predicción")

    return PrediccionResponse(resultado=valor, mensaje="Predicción generada exitosamente", success=True)


@app.get(
    "/api/prediccion/modelo",
    response_model=ModeloResponse,
    dependencies=[Depends(verificar_api_key)],
)
def modelo():
    try:
        return servicio.coeficientes()
    except Exception:
        logger.exception("Error consultando el modelo")
        raise HTTPException(status_code=503, detail="No se pudo consultar el modelo")
