"""Tablas propias del servicio de Machine Learning de predicciones.

Son tablas NUEVAS e independientes del esquema transaccional existente. La
aplicación no ejecuta ``create_all`` en MySQL: créalas con
``app/prediction/sql/ml_tables.sql`` o con
``python -m app.prediction.scripts_pred --create-ml-tables``.
"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import PK_ID


class PrediccionModelo(Base):
    """Registro de cada versión entrenada del modelo TensorFlow."""
    __tablename__ = "prediccion_modelo"
    modelo_id: Mapped[int] = mapped_column(PK_ID, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    granularidad: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False)  # ACTIVO | INACTIVO | FALLIDO
    fecha_entrenamiento: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    epocas_ejecutadas: Mapped[int | None] = mapped_column(Integer)
    loss_entrenamiento: Mapped[float | None] = mapped_column(Float)
    loss_validacion: Mapped[float | None] = mapped_column(Float)
    mae: Mapped[float | None] = mapped_column(Float)
    mse: Mapped[float | None] = mapped_column(Float)
    rmse: Mapped[float | None] = mapped_column(Float)
    mape: Mapped[float | None] = mapped_column(Float)
    porcentaje_acierto: Mapped[float | None] = mapped_column(Float)
    muestras_entrenamiento: Mapped[int | None] = mapped_column(Integer)
    muestras_validacion: Mapped[int | None] = mapped_column(Integer)
    muestras_prueba: Mapped[int | None] = mapped_column(Integer)
    fuente_datos: Mapped[str | None] = mapped_column(String(30))
    ruta_artefactos: Mapped[str | None] = mapped_column(String(500))
    resumen_json: Mapped[str | None] = mapped_column(Text)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.usuario_id"))

    __table_args__ = (Index("ix_prediccion_modelo_gran_ver", "granularidad", "version", unique=True),)


class PrediccionHistorial(Base):
    """Cada predicción generada por el servicio (historial consultable)."""
    __tablename__ = "prediccion_historial"
    prediccion_id: Mapped[int] = mapped_column(PK_ID, primary_key=True, autoincrement=True)
    fecha_generacion: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    modelo_version: Mapped[int] = mapped_column(Integer, nullable=False)
    granularidad: Mapped[str] = mapped_column(String(20), nullable=False)
    periodo: Mapped[str] = mapped_column(String(20), nullable=False)
    tipo_prediccion: Mapped[str] = mapped_column(String(20), nullable=False, default="sales")
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[date] = mapped_column(Date, nullable=False)
    ventas_estimadas: Mapped[float] = mapped_column(Float, nullable=False)
    ventas_periodo_anterior: Mapped[float | None] = mapped_column(Float)
    variacion_porcentual: Mapped[float | None] = mapped_column(Float)
    detalle_json: Mapped[str | None] = mapped_column(Text)
    variables_json: Mapped[str | None] = mapped_column(Text)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)  # JWT | API_KEY
    solicitante: Mapped[str | None] = mapped_column(String(150))
    clave_solicitud: Mapped[str | None] = mapped_column(String(64), index=True)
    ventas_reales: Mapped[float | None] = mapped_column(Float)
    error_porcentual: Mapped[float | None] = mapped_column(Float)
    fecha_evaluacion: Mapped[datetime | None] = mapped_column(DateTime)


class PrediccionEvaluacion(Base):
    """Evaluaciones: PRELIMINAR (conjunto de prueba) o POSTERIOR (vs ventas reales)."""
    __tablename__ = "prediccion_evaluacion"
    evaluacion_id: Mapped[int] = mapped_column(PK_ID, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # PRELIMINAR | POSTERIOR
    modelo_version: Mapped[int | None] = mapped_column(Integer)
    granularidad: Mapped[str] = mapped_column(String(20), nullable=False)
    fecha_evaluacion: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    muestras: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mae: Mapped[float | None] = mapped_column(Float)
    mse: Mapped[float | None] = mapped_column(Float)
    rmse: Mapped[float | None] = mapped_column(Float)
    mape: Mapped[float | None] = mapped_column(Float)
    porcentaje_acierto: Mapped[float | None] = mapped_column(Float)
    detalle_json: Mapped[str | None] = mapped_column(Text)


class PrediccionApiCliente(Base):
    """Credenciales de servicio (API Keys) para integraciones entre sistemas.

    Sólo se guarda el hash SHA-256 de la clave; la clave en claro se muestra una única vez.
    """
    __tablename__ = "prediccion_api_cliente"
    cliente_id: Mapped[int] = mapped_column(PK_ID, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    prefijo: Mapped[str] = mapped_column(String(20), nullable=False)
    clave_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    permisos: Mapped[str] = mapped_column(String(255), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ultimo_uso: Mapped[datetime | None] = mapped_column(DateTime)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.usuario_id"))


class PrediccionAcceso(Base):
    """Registro de accesos a la API de predicciones."""
    __tablename__ = "prediccion_acceso"
    acceso_id: Mapped[int] = mapped_column(PK_ID, primary_key=True, autoincrement=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    metodo: Mapped[str] = mapped_column(String(10), nullable=False)
    ruta: Mapped[str] = mapped_column(String(255), nullable=False)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    solicitante: Mapped[str | None] = mapped_column(String(150))
    ip: Mapped[str | None] = mapped_column(String(64))
    resultado: Mapped[str] = mapped_column(String(20), nullable=False)  # PERMITIDO | DENEGADO


ML_TABLES = [
    PrediccionModelo.__table__, PrediccionHistorial.__table__, PrediccionEvaluacion.__table__,
    PrediccionApiCliente.__table__, PrediccionAcceso.__table__,
]
