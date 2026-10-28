from datetime import date, datetime
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Rol(Base):
    __tablename__="rol"
    rol_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rol: Mapped[str|None]=mapped_column(Enum("ADMIN","INVITADO","PERSONA_CONTACTO","PERSONA_JURIDICA","PERSONA_NATURAL","PROVEEDOR", name="rol_enum"), unique=True)

class Empresa(Base):
    __tablename__="empresa"
    empresa_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    activo: Mapped[bool]=mapped_column(Boolean, nullable=False, default=True)
    nit: Mapped[str]=mapped_column(String(12), unique=True, nullable=False)
    telefono: Mapped[str]=mapped_column(String(20), unique=True, nullable=False)
    correo: Mapped[str]=mapped_column(String(100), unique=True, nullable=False)
    razon_social: Mapped[str]=mapped_column(String(175), unique=True, nullable=False)
    ciudad: Mapped[str]=mapped_column(String(255), nullable=False)
    direccion: Mapped[str]=mapped_column(String(255), nullable=False)
    imagen: Mapped[str|None]=mapped_column(String(255))
    e_sector: Mapped[str|None]=mapped_column(Enum("BAR","CAFE","CATERING","HOTEL","NIGHTCLUB","RESTAURANT", name="sector_enum"))

class Usuario(Base):
    __tablename__="usuario"
    usuario_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_non_expired: Mapped[bool|None]=mapped_column(Boolean)
    account_non_locked: Mapped[bool|None]=mapped_column(Boolean)
    credentials_non_expired: Mapped[bool|None]=mapped_column(Boolean)
    is_enabled: Mapped[bool|None]=mapped_column(Boolean)
    empresa_id: Mapped[int|None]=mapped_column(ForeignKey("empresa.empresa_id"), unique=True)
    rol_id: Mapped[int|None]=mapped_column(ForeignKey("rol.rol_id"))
    numero_identificacion: Mapped[str|None]=mapped_column(String(15))
    telefono: Mapped[str|None]=mapped_column(String(20), unique=True)
    correo: Mapped[str]=mapped_column(String(100), unique=True, nullable=False)
    direccion: Mapped[str|None]=mapped_column(String(100))
    password: Mapped[str|None]=mapped_column(String(100))
    apellidos: Mapped[str|None]=mapped_column(String(175))
    nombres: Mapped[str|None]=mapped_column(String(175))
    imagen: Mapped[str|None]=mapped_column(String(255))
    tipo_identificacion: Mapped[str|None]=mapped_column(Enum("CC","CE","DE","NIT","PP","TE","TI", name="identificacion_enum"))

class Categoria(Base):
    __tablename__="categoria"
    categoria_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    activo: Mapped[bool]=mapped_column(Boolean, nullable=False, default=True)
    nombre: Mapped[str]=mapped_column(String(175), unique=True, nullable=False)
    descripcion: Mapped[str]=mapped_column(String(500), nullable=False)
    imagen: Mapped[str|None]=mapped_column(String(255))

class SubCategoria(Base):
    __tablename__="sub_categorias"
    subcategoria_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    categoria_id: Mapped[int|None]=mapped_column(ForeignKey("categoria.categoria_id"))
    nombre: Mapped[str|None]=mapped_column(String(255))

class Producto(Base):
    __tablename__="producto"
    producto_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    activo: Mapped[bool]=mapped_column(Boolean, nullable=False, default=True)
    precio: Mapped[float]=mapped_column(Float, nullable=False)
    precio_regular: Mapped[float|None]=mapped_column(Float, default=0)
    stock: Mapped[int]=mapped_column(Integer, nullable=False, default=0)
    categoria_id: Mapped[int|None]=mapped_column(ForeignKey("categoria.categoria_id"))
    subcategoria_id: Mapped[int|None]=mapped_column(ForeignKey("sub_categorias.subcategoria_id"))
    usuario_id: Mapped[int|None]=mapped_column(ForeignKey("usuario.usuario_id"))
    descripcion: Mapped[str|None]=mapped_column(String(700))
    codigo_producto: Mapped[str|None]=mapped_column(String(255), unique=True)
    imagen: Mapped[str|None]=mapped_column(String(255))
    marca: Mapped[str|None]=mapped_column(String(255))
    nombre: Mapped[str|None]=mapped_column(String(255))
    pais: Mapped[str|None]=mapped_column(String(255))
    tipo: Mapped[str|None]=mapped_column(Enum("CAJA","COMBO","PACK","UNIDAD", name="producto_tipo_enum"))

class Compra(Base):
    __tablename__="compra"
    compra_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    iva: Mapped[float]=mapped_column(Float, nullable=False)
    subtotal: Mapped[float]=mapped_column(Float, nullable=False)
    total: Mapped[float]=mapped_column(Float, nullable=False)
    fecha: Mapped[datetime|None]=mapped_column(DateTime)
    usuario_id: Mapped[int|None]=mapped_column(ForeignKey("usuario.usuario_id"))
    cupon_descuento: Mapped[str|None]=mapped_column(String(255))
    estado: Mapped[str|None]=mapped_column(Enum("CANCELADO","PAGADO","PENDIENTE","RECHAZADO", name="compra_estado_enum"))
    metodo_pago: Mapped[str|None]=mapped_column(Enum("DAVIPLATA","MERCADO_PAGO","NEQUI","PAYPAL","PSE","TARJETA_CREDITO","TARJETA_DEBITO","TRANSFERENCIA", name="metodo_pago_enum"))

class DetalleVenta(Base):
    __tablename__="detalle_venta"
    detalle_venta_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cantidad: Mapped[int]=mapped_column(Integer, nullable=False)
    precio_unitario: Mapped[int|None]=mapped_column(Integer)
    subtotal: Mapped[int]=mapped_column(Integer, nullable=False)
    compra_id: Mapped[int|None]=mapped_column(ForeignKey("compra.compra_id"))
    producto_id: Mapped[int|None]=mapped_column(ForeignKey("producto.producto_id"))

class Historia(Base):
    __tablename__="historia"
    historia_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fecha: Mapped[date]=mapped_column(Date, nullable=False)
    is_enabled: Mapped[bool|None]=mapped_column(Boolean)
    titulo: Mapped[str]=mapped_column(String(100), nullable=False)
    descripcion: Mapped[str]=mapped_column(String(1000), nullable=False)
    historia_completa: Mapped[str]=mapped_column(Text, nullable=False)
    imagen: Mapped[str]=mapped_column(String(255), nullable=False)

class FacturaProveedor(Base):
    __tablename__="factura_proveedor"
    factura_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    activo: Mapped[bool]=mapped_column(Boolean, nullable=False)
    fecha_emision: Mapped[date|None]=mapped_column(Date)
    total: Mapped[float]=mapped_column(Float, nullable=False)
    fecha_registro: Mapped[datetime|None]=mapped_column(DateTime)
    usuario_id: Mapped[int|None]=mapped_column(ForeignKey("usuario.usuario_id"))
    numero_factura: Mapped[str|None]=mapped_column(String(255))

class DetalleFactura(Base):
    __tablename__="detalle_factura"
    detalle_factura_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cantidad: Mapped[int]=mapped_column(Integer, nullable=False)
    precio_compra: Mapped[int]=mapped_column(Integer, nullable=False)
    subtotal: Mapped[int]=mapped_column(Integer, nullable=False)
    factura_id: Mapped[int|None]=mapped_column(ForeignKey("factura_proveedor.factura_id"))
    producto_id: Mapped[int|None]=mapped_column(ForeignKey("producto.producto_id"))

class Comentario(Base):
    __tablename__="comentario"
    comentario_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    activo: Mapped[bool]=mapped_column(Boolean, nullable=False)
    calificacion: Mapped[int]=mapped_column(Integer, nullable=False)
    fecha: Mapped[date]=mapped_column(Date, nullable=False)
    historia_id: Mapped[int|None]=mapped_column(ForeignKey("historia.historia_id"))
    usuario_id: Mapped[int|None]=mapped_column(ForeignKey("usuario.usuario_id"))
    titulo: Mapped[str]=mapped_column(String(100), nullable=False)
    mensaje: Mapped[str]=mapped_column(String(1000), nullable=False)

class Peticion(Base):
    __tablename__="peticiones"
    peticion_id: Mapped[int]=mapped_column(BigInteger, primary_key=True, autoincrement=True)
    activo: Mapped[bool]=mapped_column(Boolean, nullable=False)
    fecha: Mapped[date|None]=mapped_column(Date)
    usuario_id: Mapped[int|None]=mapped_column(ForeignKey("usuario.usuario_id"))
    asunto: Mapped[str|None]=mapped_column(Text)
    mensaje: Mapped[str|None]=mapped_column(Text)
    estado: Mapped[str|None]=mapped_column(Enum("EN_PROCESO","PENDIENTE","RESUELTO", name="peticion_estado_enum"))
    tipo: Mapped[str|None]=mapped_column(Enum("PETICION","QUEJA","RECLAMO","SUGERENCIA", name="peticion_tipo_enum"))
