"""Local dataset export and model inspection helpers.

Usage: python -m app.prediction.scripts_pred --export-csv app/prediction/data/sales.csv
       python -m app.prediction.scripts_pred --train
       python -m app.prediction.scripts_pred --create-ml-tables
       python -m app.prediction.scripts_pred --train-tf --granularity monthly
"""
from __future__ import annotations

import argparse
import json
import secrets
from pathlib import Path

from app.core.database import SessionLocal
from app.prediction.data_handler import load_from_database
from app.prediction.engine import generate_forecast


def main() -> None:
    parser = argparse.ArgumentParser(description="Herramientas del motor de predicción interno")
    parser.add_argument("--export-csv", type=Path, help="Exporta ventas pagadas desde la base de datos")
    parser.add_argument("--train", action="store_true", help="Entrena y muestra la proyección actual")
    parser.add_argument("--generate-key", action="store_true", help="Genera una clave aleatoria de ejemplo")
    parser.add_argument("--create-ml-tables", action="store_true",
                        help="Crea SOLO las tablas nuevas del servicio ML (prediccion_*) si no existen")
    parser.add_argument("--train-tf", action="store_true", help="Entrena una nueva versión del modelo TensorFlow")
    parser.add_argument("--granularity", choices=["daily", "weekly", "monthly"], default="monthly")
    parser.add_argument("--data-source", choices=["auto", "database", "csv"], default="auto")
    args = parser.parse_args()
    if args.generate_key:
        print(secrets.token_urlsafe(48))
        return
    if args.create_ml_tables:
        from app.core.database import engine
        from app.models import ML_TABLES
        from app.core.database import Base
        Base.metadata.create_all(engine, tables=ML_TABLES, checkfirst=True)
        print("Tablas ML verificadas/creadas:", ", ".join(t.name for t in ML_TABLES))
        return
    if not args.export_csv and not args.train and not args.train_tf:
        parser.error("indica --export-csv, --train, --train-tf, --create-ml-tables o --generate-key")

    with SessionLocal() as db:
        if args.export_csv:
            data = load_from_database(db)
            args.export_csv.parent.mkdir(parents=True, exist_ok=True)
            data.to_csv(args.export_csv, index=False, encoding="utf-8")
            print(f"{len(data)} compras exportadas a {args.export_csv}")
        if args.train:
            print(json.dumps(generate_forecast(db), ensure_ascii=False, indent=2))
        if args.train_tf:
            from app.prediction.training_service import TrainingParams, training_service
            state = training_service.start(
                db, TrainingParams(granularity=args.granularity, data_source=args.data_source),
                {"user_id": None, "name": "cli"}, wait=True)
            state.pop("epochs", None)
            print(json.dumps(state, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
