"""Add clearly marked test purchases to smooth 2025–2026 monthly sales in the local test DB.

Dry-run by default. Apply with:
    python -m app.prediction.scripts_balance_synthetic_sales --apply

Each target month is set to approximately 102% of the same month in 2024. Existing rows
are preserved; inserted purchases are marked in ``cupon_descuento`` and have matching
``detalle_venta`` rows. Re-running is idempotent because current tagged rows count toward
the monthly target.
"""
from __future__ import annotations

import argparse
import calendar
import math
from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, extract, func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Compra, DetalleVenta, Producto, Usuario

VAT_RATE = 0.19
TARGET_FACTOR = 1.02
MARKER_PREFIX = "ML_TEST_BALANCE_V1_"
BALANCE_MONTHS = [(2025, month) for month in range(1, 13)] + [(2026, month) for month in range(1, 11)]


def _monthly_sales(db: Session) -> dict[tuple[int, int], tuple[float, int]]:
    rows = db.execute(
        select(extract("year", Compra.fecha), extract("month", Compra.fecha),
               func.sum(Compra.total), func.count(Compra.compra_id))
        .where(Compra.estado == "PAGADO", Compra.fecha.is_not(None), Compra.total > 0)
        .group_by(extract("year", Compra.fecha), extract("month", Compra.fecha))
    ).all()
    return {(int(year), int(month)): (float(total or 0), int(count or 0))
            for year, month, total, count in rows}


def _build_plan(db: Session) -> list[dict]:
    monthly = _monthly_sales(db)
    products = db.execute(
        select(Producto.producto_id, Producto.precio)
        .where(Producto.activo.is_(True), Producto.precio > 0)
        .order_by(func.abs(Producto.precio - 45000))
    ).all()
    if not products:
        raise RuntimeError("No hay productos activos con precio para crear los detalles sintéticos")
    product_id, raw_price = products[0]
    unit_price = int(round(float(raw_price)))
    if unit_price <= 0 or abs(float(raw_price) - unit_price) > 0.01:
        raise RuntimeError("El producto elegido no tiene un precio unitario entero compatible con detalle_venta")

    customers = list(db.scalars(
        select(Usuario.usuario_id).where(Usuario.empresa_id.is_not(None)).order_by(Usuario.usuario_id)
    ))
    if not customers:
        customers = list(db.scalars(select(Compra.usuario_id).where(Compra.usuario_id.is_not(None)).distinct()))
    if not customers:
        raise RuntimeError("No hay usuarios existentes para asociar las compras sintéticas")

    plan = []
    for year, month in BALANCE_MONTHS:
        baseline, baseline_count = monthly.get((2024, month), (0.0, 0))
        current, current_count = monthly.get((year, month), (0.0, 0))
        if baseline <= 0 or baseline_count <= 0:
            raise RuntimeError(f"No hay ventas PAGADO de referencia en 2024-{month:02d}")
        target = round(baseline * TARGET_FACTOR)
        gap = max(0.0, target - current)
        if gap < unit_price * (1 + VAT_RATE) / 2:
            continue

        subtotal_units = max(1, int(round(gap / ((1 + VAT_RATE) * unit_price))))
        average_ticket_2024 = baseline / baseline_count
        expected_receipts = max(1, int(math.ceil(gap / average_ticket_2024)))
        receipt_count = min(expected_receipts, subtotal_units)
        base_units, extra_units = divmod(subtotal_units, receipt_count)
        quantities = [base_units + (1 if i < extra_units else 0) for i in range(receipt_count)]
        synthetic_total = sum(qty * unit_price * (1 + VAT_RATE) for qty in quantities)
        plan.append({
            "year": year, "month": month, "target": target, "before": current,
            "baseline_2024": baseline, "paid_count_before": current_count,
            "product_id": int(product_id), "unit_price": unit_price,
            "quantities": quantities, "synthetic_total": synthetic_total,
            "expected_after": current + synthetic_total,
            "customers": customers,
        })
    return plan


def _insert_plan(db: Session, plan: list[dict]) -> int:
    purchases: list[Compra] = []
    details: list[DetalleVenta] = []
    for month_plan in plan:
        year, month = month_plan["year"], month_plan["month"]
        day_limit = calendar.monthrange(year, month)[1]
        marker = f"{MARKER_PREFIX}{year}_{month:02d}"
        month_purchases = []
        for index, quantity in enumerate(month_plan["quantities"]):
            subtotal = month_plan["unit_price"] * quantity
            iva = round(subtotal * VAT_RATE, 2)
            # Deterministic spread of transactions through the month.
            day = 1 + ((index * 13 + month * 7 + year) % day_limit)
            purchase = Compra(
                fecha=datetime(year, month, day, 12, 0),
                usuario_id=month_plan["customers"][index % len(month_plan["customers"])],
                estado="PAGADO", metodo_pago="TRANSFERENCIA",
                subtotal=float(subtotal), iva=float(iva), total=float(subtotal + iva),
                cupon_descuento=marker,
            )
            purchases.append(purchase)
            month_purchases.append(purchase)
        db.add_all(month_purchases)
        db.flush()
        for purchase, quantity in zip(month_purchases, month_plan["quantities"]):
            subtotal = month_plan["unit_price"] * quantity
            details.append(DetalleVenta(
                compra_id=purchase.compra_id,
                producto_id=month_plan["product_id"],
                cantidad=quantity,
                precio_unitario=month_plan["unit_price"],
                subtotal=subtotal,
            ))
    db.add_all(details)
    return len(purchases)


def main() -> None:
    parser = argparse.ArgumentParser(description="Equilibra la serie mensual SOLO en una base de prueba")
    parser.add_argument("--apply", action="store_true", help="Inserta compras/detalles sintéticos (por defecto solo vista previa)")
    parser.add_argument("--remove-synthetic", action="store_true", help="Elimina solo filas con la marca sintética de este script")
    args = parser.parse_args()
    if args.apply and args.remove_synthetic:
        parser.error("usa --apply o --remove-synthetic, no ambos")

    with SessionLocal() as db:
        database_name = db.scalar(func.database())
        hostname = db.execute(select(func.current_user())).scalar_one()
        if database_name != "db_beer":
            raise RuntimeError(f"Se esperaba la base local db_beer; conexión actual: {database_name}")
        if args.remove_synthetic:
            synthetic_ids = select(Compra.compra_id).where(
                Compra.cupon_descuento.like(f"{MARKER_PREFIX}%"))
            try:
                removed_details = db.execute(delete(DetalleVenta).where(
                    DetalleVenta.compra_id.in_(synthetic_ids))).rowcount or 0
                removed_purchases = db.execute(delete(Compra).where(
                    Compra.cupon_descuento.like(f"{MARKER_PREFIX}%"))).rowcount or 0
                db.commit()
            except Exception:
                db.rollback()
                raise
            print(f"Eliminadas {removed_purchases} compras sintéticas y {removed_details} detalles marcados.")
            return
        plan = _build_plan(db)
        print(f"Base: {database_name} · conexión MySQL: {hostname}")
        print(f"Meta: 102% del mismo mes de 2024; producto/compra conserva IVA del 19%.")
        for row in plan:
            print(f"{row['year']}-{row['month']:02d}: antes=${row['before']:,.0f}; "
                  f"meta=${row['target']:,.0f}; nuevos={len(row['quantities'])}; "
                  f"despues_aprox=${row['expected_after']:,.0f}")
        if not args.apply:
            print("Vista previa solamente. Usa --apply para insertar filas etiquetadas de prueba.")
            db.rollback()
            return

        try:
            inserted = _insert_plan(db, plan)
            db.commit()
        except Exception:
            db.rollback()
            raise
        print(f"Insertadas {inserted} compras y {inserted} detalles sintéticos.")


if __name__ == "__main__":
    main()
