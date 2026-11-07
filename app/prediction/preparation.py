"""FASE 1 — Preparación de datos, preprocesamiento y validación.

Flujo (respetando el orden temporal y evitando fuga de información):

1. Extracción de compras PAGADAS desde MySQL (o del CSV de respaldo).
2. Identificación de variables disponibles y valores nulos.
3. Limpieza: fechas inválidas/futuras, ventas nulas o no positivas, duplicados.
4. Tratamiento de nulos en variables auxiliares (imputación por mediana / categoría por defecto).
5. Agrupación de ventas por período (día, semana o mes) rellenando con 0 los períodos sin ventas.
6. Determinación de la partición cronológica entrenamiento / validación / prueba.
7. Tratamiento de valores atípicos (IQR) con límites calculados SÓLO con datos de entrenamiento.
8. Variables temporales (calendario) y variables históricas/rezagadas calculadas sólo con el pasado
   (``shift``), de modo que ninguna fila use información de su propio período o del futuro.
9. Validación de suficiencia y consistencia de los datos y resumen del proceso.

La normalización con ``StandardScaler`` se ajusta exclusivamente con el conjunto de entrenamiento en
la FASE 2 (``app.prediction.transformation``).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Categoria, Compra, DetalleVenta, Empresa, Producto, Usuario
from app.prediction.data_handler import DEFAULT_CSV, normalize_city

logger = logging.getLogger(__name__)

TARGET = "ventas"
TRANSACTION_COLUMNS = [
    "compra_id", "usuario_id", "fecha", "venta_total", "cantidad_productos",
    "total_unidades", "precio_promedio", "categoria_principal", "ciudad_cliente",
]
VARIABLE_DESCRIPTIONS = {
    "fecha": "Fecha de la compra (convertida a datetime)",
    "venta_total": "Valor total pagado de la compra (COP)",
    "cantidad_productos": "Productos distintos en la compra",
    "total_unidades": "Unidades vendidas en la compra",
    "precio_promedio": "Precio unitario promedio de la compra",
    "categoria_principal": "Categoría con mayor valor en la compra",
    "ciudad_cliente": "Ciudad de la empresa del cliente",
    "compra_id": "Identificador de la compra",
    "usuario_id": "Cliente que realizó la compra",
}
SPLIT_RATIOS = {"entrenamiento": 0.70, "validacion": 0.15, "prueba": 0.15}
MIN_SPLIT_SIZE = 3
MIN_TRAIN_SIZE = 6
OUTLIER_IQR_FACTOR = 3.0


class DataPreparationError(ValueError):
    """Los datos no permiten entrenar o predecir; incluye el resumen de la preparación."""

    def __init__(self, message: str, summary: dict | None = None) -> None:
        super().__init__(message)
        self.summary = summary or {}


@dataclass(frozen=True)
class GranularityConfig:
    name: str
    period_freq: str
    lags: tuple[int, ...]
    window: int
    unit: str

    @property
    def warmup(self) -> int:
        return max(max(self.lags), self.window)


GRANULARITIES: dict[str, GranularityConfig] = {
    "daily": GranularityConfig("daily", "D", (1, 2, 3, 7, 14), 7, "días"),
    "weekly": GranularityConfig("weekly", "W-SUN", (1, 2, 3, 4), 4, "semanas"),
    "monthly": GranularityConfig("monthly", "M", (1, 2, 3), 3, "meses"),
}


def get_granularity(name: str) -> GranularityConfig:
    try:
        return GRANULARITIES[name]
    except KeyError as exc:
        raise DataPreparationError(f"Granularidad no soportada: {name}. Usa {sorted(GRANULARITIES)}") from exc


def feature_names(cfg: GranularityConfig) -> list[str]:
    """Orden canónico de las variables predictoras (se persiste con el scaler)."""
    calendar = ["periodo_indice", "mes_sin", "mes_cos"]
    if cfg.name == "daily":
        calendar += ["dia_semana_sin", "dia_semana_cos", "es_fin_de_semana", "dia_mes"]
    elif cfg.name == "weekly":
        calendar += ["semana_sin", "semana_cos"]
    history = [f"ventas_lag_{lag}" for lag in cfg.lags]
    history += [f"ventas_media_movil_{cfg.window}", f"ventas_desv_movil_{cfg.window}"]
    return calendar + history


FEATURE_DESCRIPTIONS = {
    "periodo_indice": "Índice de tendencia: períodos transcurridos desde el inicio de la serie",
    "mes_sin": "Estacionalidad mensual (componente seno)",
    "mes_cos": "Estacionalidad mensual (componente coseno)",
    "dia_semana_sin": "Día de la semana (componente seno)",
    "dia_semana_cos": "Día de la semana (componente coseno)",
    "es_fin_de_semana": "1 si es sábado o domingo",
    "dia_mes": "Día del mes",
    "semana_sin": "Semana ISO del año (componente seno)",
    "semana_cos": "Semana ISO del año (componente coseno)",
}


def describe_feature(name: str) -> str:
    if name in FEATURE_DESCRIPTIONS:
        return FEATURE_DESCRIPTIONS[name]
    if name.startswith("ventas_lag_"):
        return f"Ventas de hace {name.rsplit('_', 1)[-1]} período(s) (rezago)"
    if name.startswith("ventas_media_movil_"):
        return f"Promedio de ventas de los {name.rsplit('_', 1)[-1]} períodos anteriores"
    if name.startswith("ventas_desv_movil_"):
        return f"Desviación estándar de ventas de los {name.rsplit('_', 1)[-1]} períodos anteriores"
    return name


# --------------------------------------------------------------------------- extracción

def extract_transactions_from_database(db: Session) -> pd.DataFrame:
    """Extrae compras PAGADAS (una fila por compra) desde MySQL sin filtrar nulos en SQL,
    para poder contabilizar en Pandas los registros descartados."""
    query = (
        select(
            Compra.compra_id, Compra.usuario_id, Compra.fecha, Compra.total,
            DetalleVenta.producto_id, DetalleVenta.cantidad, DetalleVenta.precio_unitario,
            DetalleVenta.subtotal, Categoria.nombre.label("categoria"), Empresa.ciudad,
        )
        .outerjoin(DetalleVenta, DetalleVenta.compra_id == Compra.compra_id)
        .outerjoin(Producto, Producto.producto_id == DetalleVenta.producto_id)
        .outerjoin(Categoria, Categoria.categoria_id == Producto.categoria_id)
        .outerjoin(Usuario, Usuario.usuario_id == Compra.usuario_id)
        .outerjoin(Empresa, Empresa.empresa_id == Usuario.empresa_id)
        .where(Compra.estado == "PAGADO")
    )
    rows = db.execute(query).mappings().all()
    if not rows:
        return pd.DataFrame(columns=TRANSACTION_COLUMNS)
    raw = pd.DataFrame(rows)
    for column in ("total", "cantidad", "precio_unitario", "subtotal"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw["precio_detalle"] = raw["precio_unitario"].where(
        raw["precio_unitario"].notna(), raw["subtotal"] / raw["cantidad"].clip(lower=1))
    grouped = raw.groupby("compra_id", sort=False)
    categories = (
        raw.assign(categoria=raw["categoria"].fillna("Sin_categoria"))
        .groupby(["compra_id", "categoria"], sort=False)["subtotal"].sum(min_count=1).fillna(0)
        .reset_index().sort_values("subtotal").drop_duplicates("compra_id", keep="last")
        .set_index("compra_id")["categoria"]
    )
    tx = pd.DataFrame({
        "usuario_id": grouped["usuario_id"].first(),
        "fecha": grouped["fecha"].first(),
        "venta_total": grouped["total"].first(),
        "cantidad_productos": grouped["producto_id"].nunique(),
        "total_unidades": grouped["cantidad"].sum(min_count=1),
        "precio_promedio": grouped["precio_detalle"].mean(),
        "ciudad_cliente": grouped["ciudad"].first().map(normalize_city),
    })
    tx["categoria_principal"] = categories.reindex(tx.index)
    return tx.reset_index()[TRANSACTION_COLUMNS]


def extract_transactions_from_csv(path: Path | None = None) -> pd.DataFrame:
    """El CSV de respaldo sólo trae año y mes: la fecha se fija al primer día del mes."""
    csv_path = Path(path or settings.prediction_dataset_csv or DEFAULT_CSV)
    if not csv_path.is_absolute():
        csv_path = Path(__file__).resolve().parents[2] / csv_path
    data = pd.read_csv(csv_path, dtype={"dia_semana": str, "categoria_principal": str, "ciudad_cliente": str})
    required = {"venta_total", "anno", "mes"}
    if missing := required - set(data.columns):
        raise DataPreparationError(f"El CSV no contiene las columnas requeridas: {sorted(missing)}")
    years = pd.to_numeric(data["anno"], errors="coerce")
    months = pd.to_numeric(data["mes"], errors="coerce")
    fecha = pd.to_datetime(
        pd.DataFrame({"year": years, "month": months, "day": 1}), errors="coerce")
    frame = pd.DataFrame({
        "compra_id": np.arange(1, len(data) + 1),
        "usuario_id": None,
        "fecha": fecha,
        "venta_total": data["venta_total"],
    })
    for column in ("cantidad_productos", "total_unidades", "precio_promedio", "categoria_principal", "ciudad_cliente"):
        frame[column] = data[column] if column in data.columns else None
    return frame[TRANSACTION_COLUMNS]


@dataclass
class ExtractionResult:
    transactions: pd.DataFrame
    source: str
    has_exact_dates: bool
    warnings: list[str] = field(default_factory=list)


def load_transactions(db: Session | None, source: str = "auto") -> ExtractionResult:
    """``auto`` respeta PREDICTION_DATA_SOURCE y usa el CSV si MySQL falla o no tiene ventas."""
    source = (source or "auto").lower()
    configured = settings.prediction_data_source.strip().lower()
    if source == "auto":
        source = "csv" if configured == "csv" else "auto_database"
    if source == "csv":
        return ExtractionResult(extract_transactions_from_csv(), "csv", False)
    if source not in {"database", "auto_database"}:
        raise DataPreparationError("data_source debe ser auto, database o csv")

    warnings: list[str] = []
    if db is not None:
        try:
            tx = extract_transactions_from_database(db)
            if not tx.empty:
                return ExtractionResult(tx, "database", True)
            warnings.append("MySQL no devolvió compras pagadas")
        except Exception as exc:  # noqa: BLE001 - se informa y, si procede, se usa el respaldo
            logger.warning("No se pudieron extraer ventas de MySQL", exc_info=True)
            warnings.append(f"No se pudieron extraer ventas de MySQL: {type(exc).__name__}")
    else:
        warnings.append("No se recibió sesión de base de datos")
    if source == "database":
        raise DataPreparationError("No hay ventas disponibles en MySQL. " + "; ".join(warnings))
    warnings.append("Se usó el CSV de respaldo (sólo admite granularidad mensual)")
    return ExtractionResult(extract_transactions_from_csv(), "csv", False, warnings)


# --------------------------------------------------------------------------- limpieza

def clean_transactions(tx: pd.DataFrame, reference: datetime | None = None) -> tuple[pd.DataFrame, dict]:
    """Limpieza, conversión de fechas, duplicados y tratamiento de nulos."""
    reference = pd.Timestamp(reference or datetime.now())
    frame = tx.copy()
    report: dict = {
        "registros_originales": int(len(frame)),
        "variables_disponibles": [
            {"nombre": c, "tipo": str(frame[c].dtype), "descripcion": VARIABLE_DESCRIPTIONS.get(c, c)}
            for c in frame.columns
        ],
        "valores_nulos_identificados": {c: int(frame[c].isna().sum()) for c in frame.columns},
    }
    frame["fecha"] = pd.to_datetime(frame["fecha"], errors="coerce")
    frame["venta_total"] = pd.to_numeric(frame["venta_total"], errors="coerce")
    for column in ("cantidad_productos", "total_unidades", "precio_promedio"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    discarded: dict[str, int] = {}
    mask = frame["fecha"].isna()
    discarded["fecha_nula_o_invalida"] = int(mask.sum())
    frame = frame[~mask]
    mask = frame["fecha"] > reference
    discarded["fecha_futura"] = int(mask.sum())
    frame = frame[~mask]
    mask = frame["venta_total"].isna() | (frame["venta_total"] <= 0) | ~np.isfinite(frame["venta_total"])
    discarded["venta_nula_o_no_positiva"] = int(mask.sum())
    frame = frame[~mask]

    # Duplicados: misma compra repetida, o mismo cliente con idéntica fecha-hora y total.
    duplicated = frame.duplicated(subset=["compra_id"], keep="first")
    with_user = frame["usuario_id"].notna()
    duplicated |= with_user & frame.duplicated(subset=["usuario_id", "fecha", "venta_total"], keep="first")
    identical_rows = int(frame.drop(columns=["compra_id"]).duplicated().sum())
    discarded["duplicados"] = int(duplicated.sum())
    frame = frame[~duplicated]

    imputed: dict[str, int] = {}
    for column in ("cantidad_productos", "total_unidades", "precio_promedio"):
        nulls = int(frame[column].isna().sum())
        if nulls:
            median = frame[column].median()
            frame[column] = frame[column].fillna(0 if pd.isna(median) else median)
        imputed[column] = nulls
    for column, default in (("categoria_principal", "Sin_categoria"), ("ciudad_cliente", "Sin_empresa")):
        imputed[column] = int(frame[column].isna().sum())
        frame[column] = frame[column].fillna(default).astype(str)

    frame = frame.sort_values("fecha", kind="mergesort").reset_index(drop=True)
    report.update({
        "registros_procesados": int(len(frame)),
        "registros_descartados": int(sum(discarded.values())),
        "detalle_descartes": discarded,
        "duplicados_identificados": discarded["duplicados"],
        "filas_identicas_sin_identificador": identical_rows,
        "valores_nulos_imputados": imputed,
    })
    return frame, report


def outlier_bounds(values: pd.Series, factor: float = OUTLIER_IQR_FACTOR) -> tuple[float, float] | None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if len(values) < 4:
        return None
    q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
    iqr = q3 - q1
    if iqr <= 0:
        return None
    return max(0.0, q1 - factor * iqr), q3 + factor * iqr


def apply_outlier_bounds(tx: pd.DataFrame, bounds: tuple[float, float] | None) -> tuple[pd.DataFrame, int]:
    if not bounds:
        return tx, 0
    lower, upper = bounds
    clipped = tx["venta_total"].clip(lower=lower, upper=upper)
    changed = int((clipped != tx["venta_total"]).sum())
    return tx.assign(venta_total=clipped), changed


# --------------------------------------------------------------------------- series y variables

def aggregate_by_period(
    tx: pd.DataFrame,
    cfg: GranularityConfig,
    reference: datetime | None = None,
    drop_incomplete: bool = True,
) -> pd.DataFrame:
    """Agrupa ventas por período y rellena con 0 los períodos intermedios sin ventas.

    Se descarta el último período si aún no ha terminado respecto a ``reference`` (datos parciales).
    """
    if tx.empty:
        return pd.DataFrame(columns=["periodo", "fecha_periodo", TARGET, "num_compras", "unidades"])
    periods = tx["fecha"].dt.to_period(cfg.period_freq)
    grouped = tx.groupby(periods).agg(
        ventas=("venta_total", "sum"), num_compras=("venta_total", "size"), unidades=("total_unidades", "sum"))
    full_range = pd.period_range(grouped.index.min(), grouped.index.max(), freq=cfg.period_freq)
    series = grouped.reindex(full_range, fill_value=0)
    series.index.name = "periodo"
    series = series.reset_index()
    if drop_incomplete and not series.empty:
        reference_ts = pd.Timestamp(reference or datetime.now())
        if series["periodo"].iloc[-1].end_time >= reference_ts:
            series = series.iloc[:-1]
    series["fecha_periodo"] = series["periodo"].dt.start_time
    series[TARGET] = series[TARGET].astype(float)
    return series[["periodo", "fecha_periodo", TARGET, "num_compras", "unidades"]].reset_index(drop=True)


def period_offset(period: pd.Period, origin: pd.Period) -> int:
    return int((period - origin).n)


def build_features(series: pd.DataFrame, cfg: GranularityConfig, origin: pd.Period) -> pd.DataFrame:
    """Variables temporales e históricas. Todas las variables históricas usan ``shift`` para que
    cada fila sólo vea períodos anteriores (sin fuga de información)."""
    frame = series.copy()
    dates = pd.to_datetime(frame["fecha_periodo"])
    frame["periodo_indice"] = [period_offset(p, origin) for p in frame["periodo"]]
    month = dates.dt.month
    frame["mes_sin"] = np.sin(2 * math.pi * (month - 1) / 12)
    frame["mes_cos"] = np.cos(2 * math.pi * (month - 1) / 12)
    if cfg.name == "daily":
        dow = dates.dt.day_of_week
        frame["dia_semana_sin"] = np.sin(2 * math.pi * dow / 7)
        frame["dia_semana_cos"] = np.cos(2 * math.pi * dow / 7)
        frame["es_fin_de_semana"] = (dow >= 5).astype(float)
        frame["dia_mes"] = dates.dt.day.astype(float)
    elif cfg.name == "weekly":
        week = dates.dt.isocalendar().week.astype(float).to_numpy()
        frame["semana_sin"] = np.sin(2 * math.pi * (week - 1) / 52)
        frame["semana_cos"] = np.cos(2 * math.pi * (week - 1) / 52)
    target = frame[TARGET].astype(float)
    for lag in cfg.lags:
        frame[f"ventas_lag_{lag}"] = target.shift(lag)
    previous = target.shift(1)
    frame[f"ventas_media_movil_{cfg.window}"] = previous.rolling(cfg.window, min_periods=cfg.window).mean()
    frame[f"ventas_desv_movil_{cfg.window}"] = previous.rolling(cfg.window, min_periods=cfg.window).std(ddof=0)
    return frame


def split_sizes(n: int) -> dict[str, int]:
    n_test = max(MIN_SPLIT_SIZE, int(round(n * SPLIT_RATIOS["prueba"])))
    n_val = max(MIN_SPLIT_SIZE, int(round(n * SPLIT_RATIOS["validacion"])))
    return {"entrenamiento": n - n_val - n_test, "validacion": n_val, "prueba": n_test}


# --------------------------------------------------------------------------- orquestación

@dataclass
class PreparationResult:
    granularity: str
    dataset: pd.DataFrame
    series: pd.DataFrame
    feature_names: list[str]
    target: str
    splits: dict[str, pd.DataFrame]
    origin: str
    outlier_bounds: tuple[float, float] | None
    source: str
    summary: dict

    @property
    def config(self) -> GranularityConfig:
        return GRANULARITIES[self.granularity]


def _validations(cfg, has_exact_dates, usable, sizes, dataset, splits, names) -> list[dict]:
    checks = [
        {"validacion": "granularidad_compatible_con_fechas",
         "aprobada": has_exact_dates or cfg.name == "monthly",
         "detalle": "Las granularidades diaria y semanal requieren fechas exactas (MySQL)"},
        {"validacion": "registros_suficientes",
         "aprobada": usable >= settings.prediction_min_training_samples,
         "detalle": f"{usable} períodos utilizables; mínimo requerido {settings.prediction_min_training_samples}"},
        {"validacion": "tamano_conjuntos",
         "aprobada": sizes["entrenamiento"] >= MIN_TRAIN_SIZE and sizes["validacion"] >= MIN_SPLIT_SIZE
         and sizes["prueba"] >= MIN_SPLIT_SIZE,
         "detalle": f"Mínimos: entrenamiento {MIN_TRAIN_SIZE}, validación {MIN_SPLIT_SIZE}, prueba {MIN_SPLIT_SIZE}"},
    ]
    if not dataset.empty:
        values = dataset[names + [TARGET]].to_numpy(dtype=float)
        checks.append({"validacion": "sin_nulos_en_variables", "aprobada": not np.isnan(values).any(),
                       "detalle": "Variables predictoras y objetivo sin valores nulos"})
        checks.append({"validacion": "valores_finitos", "aprobada": bool(np.isfinite(values).all()),
                       "detalle": "Sin infinitos tras la transformación"})
    if all(len(part) for part in splits.values()):
        train, val, test = splits["entrenamiento"], splits["validacion"], splits["prueba"]
        ordered = (train["fecha_periodo"].max() < val["fecha_periodo"].min()
                   and val["fecha_periodo"].max() < test["fecha_periodo"].min())
        checks.append({"validacion": "orden_temporal_sin_solapamiento", "aprobada": bool(ordered),
                       "detalle": "entrenamiento < validación < prueba en el tiempo"})
        checks.append({"validacion": "variabilidad_objetivo_entrenamiento",
                       "aprobada": float(train[TARGET].std(ddof=0)) > 0,
                       "detalle": "La variable objetivo de entrenamiento no es constante"})
    return checks


def prepare_sales_data(
    extraction: ExtractionResult,
    granularity: str = "monthly",
    reference: datetime | None = None,
    raise_on_invalid: bool = True,
) -> PreparationResult:
    cfg = get_granularity(granularity)
    reference = reference or datetime.now()
    clean, report = clean_transactions(extraction.transactions, reference)
    names = feature_names(cfg)

    # Partición determinada por posición temporal (no depende de los valores de venta).
    preliminary = aggregate_by_period(clean, cfg, reference)
    usable = max(0, len(preliminary) - cfg.warmup)
    sizes = split_sizes(usable) if usable else {"entrenamiento": 0, "validacion": 0, "prueba": 0}

    bounds = None
    adjusted = 0
    if sizes["entrenamiento"] > 0:
        train_last_period = preliminary["periodo"].iloc[cfg.warmup + sizes["entrenamiento"] - 1]
        train_tx = clean[clean["fecha"].dt.to_period(cfg.period_freq) <= train_last_period]
        bounds = outlier_bounds(train_tx["venta_total"])
        clean, adjusted = apply_outlier_bounds(clean, bounds)

    series = aggregate_by_period(clean, cfg, reference)
    if series.empty:
        origin = pd.Period(pd.Timestamp(reference), freq=cfg.period_freq)
        dataset = pd.DataFrame(columns=["periodo", "fecha_periodo", TARGET, *names])
    else:
        origin = series["periodo"].iloc[0]
        featured = build_features(series, cfg, origin)
        dataset = featured.iloc[cfg.warmup:].reset_index(drop=True)

    n_train, n_val = sizes["entrenamiento"], sizes["validacion"]
    splits = {
        "entrenamiento": dataset.iloc[:n_train] if n_train > 0 else dataset.iloc[0:0],
        "validacion": dataset.iloc[n_train:n_train + n_val] if n_train > 0 else dataset.iloc[0:0],
        "prueba": dataset.iloc[n_train + n_val:] if n_train > 0 else dataset.iloc[0:0],
    }
    checks = _validations(cfg, extraction.has_exact_dates, usable, sizes, dataset, splits, names)
    valid = all(check["aprobada"] for check in checks)

    def date_range(frame):
        if frame.empty:
            return None
        return {"desde": frame["fecha_periodo"].min().date().isoformat(),
                "hasta": frame["fecha_periodo"].max().date().isoformat()}

    summary = {
        **report,
        "fuente_datos": extraction.source,
        "fechas_exactas": extraction.has_exact_dates,
        "advertencias": list(extraction.warnings),
        "granularidad": cfg.name,
        "variable_objetivo": {"nombre": TARGET, "descripcion": "Suma de ventas pagadas (COP) del período"},
        "variables_predictoras": [{"nombre": n, "descripcion": describe_feature(n)} for n in names],
        "variables_excluidas": [
            {"nombre": "num_compras / unidades del período",
             "motivo": "Sólo se conocen al terminar el período; usarlas sería fuga de información"},
            {"nombre": "categoria_principal / ciudad_cliente",
             "motivo": "Atributos por compra, no del período agregado"},
        ],
        "valores_atipicos": {
            "metodo": f"IQR x{OUTLIER_IQR_FACTOR} sobre venta_total por compra (límites del entrenamiento)",
            "limite_inferior": round(bounds[0], 2) if bounds else None,
            "limite_superior": round(bounds[1], 2) if bounds else None,
            "registros_ajustados": adjusted,
        },
        "periodos_generados": int(len(series)),
        "periodos_descartados_por_rezagos": int(min(len(series), cfg.warmup)),
        "registros_utilizables": int(len(dataset)),
        "rango_fechas": date_range(series),
        "normalizacion": "StandardScaler ajustado sólo con el conjunto de entrenamiento (FASE 2)",
        "registros_entrenamiento": int(len(splits["entrenamiento"])),
        "registros_validacion": int(len(splits["validacion"])),
        "registros_prueba": int(len(splits["prueba"])),
        "rangos_conjuntos": {name: date_range(part) for name, part in splits.items()},
        "validaciones": checks,
        "estado_validacion": "VALIDO" if valid else "INVALIDO",
    }
    if not valid and raise_on_invalid:
        failed = [c["detalle"] for c in checks if not c["aprobada"]]
        raise DataPreparationError("Datos insuficientes o inválidos para entrenar: " + "; ".join(failed), summary)
    return PreparationResult(
        granularity=cfg.name, dataset=dataset, series=series, feature_names=names, target=TARGET,
        splits=splits, origin=str(origin), outlier_bounds=bounds, source=extraction.source, summary=summary,
    )


def build_history_series(
    extraction: ExtractionResult,
    granularity: str,
    bounds: tuple[float, float] | None,
    reference: datetime | None = None,
) -> pd.DataFrame:
    """Serie histórica para predicción con EXACTAMENTE la limpieza y los límites de atípicos del
    entrenamiento (los límites se leen del artefacto, no se recalculan)."""
    cfg = get_granularity(granularity)
    clean, _ = clean_transactions(extraction.transactions, reference)
    clean, _ = apply_outlier_bounds(clean, bounds)
    return aggregate_by_period(clean, cfg, reference)

