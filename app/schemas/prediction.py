from pydantic import BaseModel, Field


class ForecastRequest(BaseModel):
    anios: int = Field(default=6, ge=1, le=10)
    proyeccion_meses: int = Field(default=12, ge=0, le=24)
