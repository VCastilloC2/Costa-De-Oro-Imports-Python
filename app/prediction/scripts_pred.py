"""Local dataset export and model inspection helpers.

Usage: python -m app.prediction.scripts_pred --export-csv app/prediction/data/sales.csv
       python -m app.prediction.scripts_pred --train
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
    args = parser.parse_args()
    if args.generate_key:
        print(secrets.token_urlsafe(48))
        return
    if not args.export_csv and not args.train:
        parser.error("indica --export-csv, --train o --generate-key")

    with SessionLocal() as db:
        if args.export_csv:
            data = load_from_database(db)
            args.export_csv.parent.mkdir(parents=True, exist_ok=True)
            data.to_csv(args.export_csv, index=False, encoding="utf-8")
            print(f"{len(data)} compras exportadas a {args.export_csv}")
        if args.train:
            print(json.dumps(generate_forecast(db), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
