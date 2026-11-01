"""Load and shape sales data from SQLAlchemy or the bundled training CSV."""
from __future__ import annotations

import unicodedata
import logging
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Compra, DetalleVenta, Producto, Categoria, Usuario, Empresa

PREDICTION_COLUMNS = [
    "venta_total", "anno", "mes", "dia_semana", "categoria_principal",
    "ciudad_cliente", "cantidad_productos", "total_unidades", "precio_promedio",
]
DAYS = {0: "LUN", 1: "MAR", 2: "MIE", 3: "JUE", 4: "VIE", 5: "SAB", 6: "DOM"}
KNOWN_CITIES = {"Bogota", "Medellin", "Cartagena", "Cali", "Barranquilla"}
DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "costa_de_oro_ventas.csv"
logger = logging.getLogger(__name__)


def normalize_city(value) -> str:
    if value is None or pd.isna(value) or not str(value).strip():
        return "Sin_empresa"
    clean = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().strip().title()
    return clean if clean in KNOWN_CITIES else "Otras"


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)
    frame = frame.dropna(subset=PREDICTION_COLUMNS)
    frame = frame[(frame["venta_total"] > 0) & frame["mes"].between(1, 12)]
    return frame[PREDICTION_COLUMNS].reset_index(drop=True)


def load_from_csv(path: Path | None = None) -> pd.DataFrame:
    csv_path = path or settings.prediction_dataset_csv or DEFAULT_CSV
    if not csv_path.is_absolute():
        csv_path = Path(__file__).resolve().parents[2] / csv_path
    data = pd.read_csv(csv_path, dtype={"dia_semana": str, "categoria_principal": str, "ciudad_cliente": str})
    missing = set(PREDICTION_COLUMNS) - set(data.columns)
    if missing:
        raise ValueError(f"El CSV no contiene las columnas requeridas: {sorted(missing)}")
    data = data[PREDICTION_COLUMNS].copy()
    for column in ("venta_total", "anno", "mes", "cantidad_productos", "total_unidades", "precio_promedio"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return _clean(data)


def load_from_database(db: Session, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    query = (
        select(
            Compra.compra_id, Compra.fecha, Compra.total, DetalleVenta.producto_id,
            DetalleVenta.cantidad, DetalleVenta.precio_unitario, DetalleVenta.subtotal,
            Categoria.nombre.label("categoria"), Empresa.ciudad,
        )
        .join(DetalleVenta, DetalleVenta.compra_id == Compra.compra_id)
        .join(Producto, Producto.producto_id == DetalleVenta.producto_id)
        .outerjoin(Categoria, Categoria.categoria_id == Producto.categoria_id)
        .outerjoin(Usuario, Usuario.usuario_id == Compra.usuario_id)
        .outerjoin(Empresa, Empresa.empresa_id == Usuario.empresa_id)
        .where(Compra.estado == "PAGADO", Compra.fecha.is_not(None), Compra.total > 0)
    )
    query = query.where(Compra.fecha >= (start or date(2019, 1, 1)))
    if end:
        query = query.where(Compra.fecha < end)
    rows = db.execute(query).mappings().all()
    if not rows:
        return pd.DataFrame(columns=PREDICTION_COLUMNS)

    raw = pd.DataFrame(rows)
    raw["fecha"] = pd.to_datetime(raw["fecha"], errors="coerce")
    raw["precio_detalle"] = raw["precio_unitario"].where(raw["precio_unitario"].notna(), raw["subtotal"] / raw["cantidad"].clip(lower=1))
    records = []
    for _, purchase in raw.groupby("compra_id", sort=False):
        dated = purchase["fecha"].iloc[0]
        if pd.isna(dated):
            continue
        category_totals = purchase.assign(categoria=purchase["categoria"].fillna("Sin_categoria")).groupby("categoria")["subtotal"].sum()
        prices = purchase["precio_detalle"].dropna()
        records.append({
            "venta_total": float(purchase["total"].iloc[0]),
            "anno": int(dated.year),
            "mes": int(dated.month),
            "dia_semana": DAYS[int(dated.day_of_week)],
            "categoria_principal": str(category_totals.idxmax()) if not category_totals.empty else "Sin_categoria",
            "ciudad_cliente": normalize_city(purchase["ciudad"].iloc[0]),
            "cantidad_productos": int(purchase["producto_id"].nunique()),
            "total_unidades": int(purchase["cantidad"].fillna(0).sum()),
            "precio_promedio": float(prices.mean()) if not prices.empty else 0.0,
        })
    return _clean(pd.DataFrame(records, columns=PREDICTION_COLUMNS))


def load_dataset(db: Session | None = None, today: date | None = None) -> pd.DataFrame:
    """Prefer live MySQL/PostgreSQL sales; fall back to the bundled CSV on failure or no rows."""
    source = settings.prediction_data_source.strip().lower()
    if source == "csv":
        return load_from_csv()
    if source not in {"db", "database", "mysql", "postgresql"}:
        raise ValueError("PREDICTION_DATA_SOURCE debe ser database o csv")

    if db is not None:
        try:
            database_data = load_from_database(db, end=today)
            if not database_data.empty:
                return database_data
            logger.warning("MySQL no devolvió ventas; se usará el CSV de respaldo")
        except Exception:
            logger.warning("No se pudieron leer ventas de MySQL; se usará el CSV de respaldo", exc_info=True)
    else:
        logger.warning("No se recibió sesión de base de datos; se usará el CSV de respaldo")

    try:
        fallback_data = load_from_csv()
    except Exception as exc:
        logger.exception("No fue posible cargar ventas desde MySQL ni desde el CSV de respaldo")
        raise ValueError("No fue posible obtener ventas de la base de datos y el CSV de respaldo tampoco pudo cargarse") from exc
    if fallback_data.empty:
        raise ValueError("La base de datos no devolvió ventas y el CSV de respaldo está vacío")
    return fallback_data


def historical_dashboard_data(db: Session, today: date | None = None) -> dict:
    sales = load_dataset(db, today)
    monthly = sales.groupby(["anno", "mes"], as_index=False)["venta_total"].sum().sort_values(["anno", "mes"])
    monthly_rows = [
        {"fecha": f"{int(row.anno):04d}-{int(row.mes):02d}", "ventas": round(float(row.venta_total), 2)}
        for row in monthly.itertuples()
    ]
    stock_query = (
        select(Producto.producto_id, Producto.nombre, Producto.stock,
               func.coalesce(func.sum(case((Compra.estado == "PAGADO", DetalleVenta.cantidad), else_=0)), 0).label("unidades_vendidas"))
        .outerjoin(DetalleVenta, DetalleVenta.producto_id == Producto.producto_id)
        .outerjoin(Compra, Compra.compra_id == DetalleVenta.compra_id)
        .group_by(Producto.producto_id, Producto.nombre, Producto.stock)
        .order_by(Producto.nombre)
    )
    try:
        stock_vs_sales = [
            {"productoId": int(row.producto_id), "producto": row.nombre,
             "stock": int(row.stock or 0), "unidadesVendidas": int(row.unidades_vendidas or 0)}
            for row in db.execute(stock_query)
        ]
    except Exception:
        logger.warning("No se pudo cargar el inventario de MySQL; se omite la serie stock_vs_ventas", exc_info=True)
        stock_vs_sales = []
    cities = sales.groupby("ciudad_cliente", as_index=False)["venta_total"].sum().sort_values("venta_total", ascending=False)
    return {
        "ventas_mensuales": monthly_rows,
        "stock_vs_ventas": stock_vs_sales,
        "ventas_por_ciudad": [{"ciudad": row.ciudad_cliente, "ventas": round(float(row.venta_total), 2)} for row in cities.itertuples()],
        "total_ventas": round(float(sales["venta_total"].sum()), 2) if not sales.empty else 0.0,
        "cantidad_compras": int(len(sales)),
    }
