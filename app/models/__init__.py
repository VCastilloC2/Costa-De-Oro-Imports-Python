"""SQLAlchemy ORM models exposed through the application's model package."""
from .entities import (
    Rol, Empresa, Usuario, Categoria, SubCategoria, Producto, Compra,
    DetalleVenta, Historia, FacturaProveedor, DetalleFactura, Comentario, Peticion,
)
from .ml_entities import (
    ML_TABLES, PrediccionAcceso, PrediccionApiCliente, PrediccionEvaluacion,
    PrediccionHistorial, PrediccionModelo,
)
from .passkey import PasskeyChallenge, PasskeyCredencial

__all__ = [
    "PasskeyChallenge", "PasskeyCredencial",
    "ML_TABLES", "PrediccionAcceso", "PrediccionApiCliente", "PrediccionEvaluacion",
    "PrediccionHistorial", "PrediccionModelo",
    "Rol", "Empresa", "Usuario", "Categoria", "SubCategoria", "Producto", "Compra",
    "DetalleVenta", "Historia", "FacturaProveedor", "DetalleFactura", "Comentario", "Peticion",
]
