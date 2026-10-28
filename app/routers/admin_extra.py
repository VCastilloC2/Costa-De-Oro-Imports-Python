"""Endpoints administrativos complementarios migrados desde los controladores Spring.
Las operaciones CRUD genéricas están en los routers de cada entidad.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.dependencies import admin_user
from app.models import (Usuario, Rol, Empresa, Categoria, SubCategoria, Producto, Compra,
                        DetalleVenta, Historia, FacturaProveedor, DetalleFactura, Comentario, Peticion)

router = APIRouter(tags=["Administración"])
ADMIN = [Depends(admin_user)]


def payload_model(model: Any, data: dict):
    allowed = {c.name for c in model.__table__.columns if not c.primary_key and not c.computed}
    return {k: v for k, v in data.items() if k in allowed and k != "password"}


def set_active(db: Session, model: Any, pk_name: str, item_id: int, field: str = "activo"):
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(404, "Registro no encontrado")
    if not hasattr(item, field):
        field = "is_enabled" if hasattr(item, "is_enabled") else field
    setattr(item, field, not bool(getattr(item, field)))
    db.commit()
    db.refresh(item)
    return {"success": True, "mensaje": "Estado actualizado", "id": item_id, "activo": getattr(item, field)}

# Aliases and actions used by Spring's admin controllers.
@router.patch("/admin/categoria/{item_id}/disable", dependencies=ADMIN)
def disable_categoria(item_id: int, db: Session = Depends(get_db)):
    return set_active(db, Categoria, "categoria_id", item_id)

@router.patch("/admin/producto/{item_id}/disable", dependencies=ADMIN)
def disable_producto(item_id: int, db: Session = Depends(get_db)):
    return set_active(db, Producto, "producto_id", item_id)

@router.get("/admin/producto/opciones", dependencies=ADMIN)
def opciones_producto(db: Session = Depends(get_db)):
    return {"categorias": list(db.scalars(select(Categoria).where(Categoria.activo.is_(True)))),
            "subcategorias": list(db.scalars(select(SubCategoria))), "tipos": ["CAJA", "COMBO", "PACK", "UNIDAD"]}

@router.get("/admin/producto/subcategorias/{categoria_id}", dependencies=ADMIN)
def subcategorias_categoria(categoria_id: int, db: Session = Depends(get_db)):
    return list(db.scalars(select(SubCategoria).where(SubCategoria.categoria_id == categoria_id)))

@router.get("/admin/blog", dependencies=ADMIN)
def listar_blog(db: Session = Depends(get_db)):
    return list(db.scalars(select(Historia).order_by(desc(Historia.fecha))))

@router.get("/admin/blog/{item_id}", dependencies=ADMIN)
def obtener_blog(item_id: int, db: Session = Depends(get_db)):
    item = db.get(Historia, item_id)
    if not item: raise HTTPException(404, "Blog no encontrado")
    return item

@router.post("/admin/blog", status_code=201, dependencies=ADMIN)
def crear_blog(data: dict, db: Session = Depends(get_db)):
    item = Historia(**payload_model(Historia, data)); db.add(item)
    try: db.commit(); db.refresh(item)
    except Exception as exc: db.rollback(); raise HTTPException(409, "No se pudo crear el blog; verifica los campos obligatorios") from exc
    return {"success": True, "mensaje": "Blog creado", "id": item.historia_id}

@router.put("/admin/blog/{item_id}", dependencies=ADMIN)
def actualizar_blog(item_id: int, data: dict, db: Session = Depends(get_db)):
    item = db.get(Historia, item_id)
    if not item: raise HTTPException(404, "Blog no encontrado")
    for k,v in payload_model(Historia,data).items(): setattr(item,k,v)
    try: db.commit()
    except Exception as exc: db.rollback(); raise HTTPException(409,"No se pudo actualizar el blog") from exc
    return {"success":True,"mensaje":"Blog actualizado"}

@router.patch("/admin/blog/{item_id}/disable", dependencies=ADMIN)
def disable_blog(item_id: int, db: Session = Depends(get_db)):
    return set_active(db, Historia, "historia_id", item_id, "is_enabled")

@router.delete("/admin/blog/{item_id}", dependencies=ADMIN)
def eliminar_blog(item_id: int, db: Session = Depends(get_db)):
    item=db.get(Historia,item_id)
    if not item: raise HTTPException(404,"Blog no encontrado")
    try: db.delete(item); db.commit()
    except Exception as exc: db.rollback(); raise HTTPException(409,"El blog tiene registros relacionados") from exc
    return {"success":True,"mensaje":"Blog eliminado","id":item_id}

@router.get("/admin/clientes", dependencies=ADMIN)
def listar_clientes(db: Session = Depends(get_db)):
    roles = select(Rol.rol_id).where(Rol.rol.in_(["PERSONA_CONTACTO","PERSONA_JURIDICA","PERSONA_NATURAL","INVITADO"]))
    users = list(db.scalars(select(Usuario).where(Usuario.rol_id.in_(roles))))
    result=[]
    for u in users:
        purchases=list(db.scalars(select(Compra).where(Compra.usuario_id==u.usuario_id)))
        result.append({"usuario_id":u.usuario_id,"correo":u.correo,"nombres":u.nombres,"apellidos":u.apellidos,
                       "telefono":u.telefono,"activo":u.is_enabled,"cantidad_compras":len(purchases),
                       "gasto_total":sum(float(c.total or 0) for c in purchases if c.estado=="PAGADO")})
    return result

@router.get("/admin/clientes/{item_id}", dependencies=ADMIN)
def obtener_cliente(item_id: int, db: Session = Depends(get_db)):
    u=db.get(Usuario,item_id)
    if not u: raise HTTPException(404,"Cliente no encontrado")
    role=db.get(Rol,u.rol_id) if u.rol_id else None
    return {"usuario_id":u.usuario_id,"correo":u.correo,"nombres":u.nombres,"apellidos":u.apellidos,
            "telefono":u.telefono,"direccion":u.direccion,"tipo_identificacion":u.tipo_identificacion,
            "numero_identificacion":u.numero_identificacion,"is_enabled":u.is_enabled,"rol":role.rol if role else None}

@router.post("/admin/clientes", status_code=201, dependencies=ADMIN)
def crear_cliente(data: dict, db: Session = Depends(get_db)):
    from app.core.security import hash_password
    email=data.get("correo")
    if not email or not data.get("password"): raise HTTPException(422,"correo y password son obligatorios")
    if db.scalar(select(Usuario).where(Usuario.correo==email)): raise HTTPException(409,"Correo ya registrado")
    role_name=data.get("rol","PERSONA_NATURAL")
    if role_name=="ADMIN": raise HTTPException(400,"Crea administradores mediante el procedimiento de seguridad")
    role=db.scalar(select(Rol).where(Rol.rol==role_name))
    if not role: raise HTTPException(400,"El rol indicado no existe")
    raw_password = data["password"]
    data=payload_model(Usuario,data); data["password"]=hash_password(raw_password); data["rol_id"]=role.rol_id
    data.setdefault("is_enabled",False if role_name!="PERSONA_NATURAL" else True)
    data.setdefault("account_non_expired",True);data.setdefault("account_non_locked",True);data.setdefault("credentials_non_expired",True)
    u=Usuario(**data);db.add(u)
    try: db.commit();db.refresh(u)
    except Exception as exc: db.rollback();raise HTTPException(409,"No se pudo crear cliente") from exc
    return {"success":True,"mensaje":"Cliente creado; si requiere validación, queda pendiente de activación","id":u.usuario_id}

@router.put("/admin/clientes/{item_id}", dependencies=ADMIN)
def actualizar_cliente(item_id:int,data:dict,db:Session=Depends(get_db)):
    u=db.get(Usuario,item_id)
    if not u: raise HTTPException(404,"Cliente no encontrado")
    from app.core.security import hash_password
    for k,v in payload_model(Usuario,data).items():
        if k=="password": v=hash_password(v)
        setattr(u,k,v)
    try:db.commit()
    except Exception as exc:db.rollback();raise HTTPException(409,"No se pudo actualizar cliente") from exc
    return {"success":True,"mensaje":"Cliente actualizado"}

@router.patch("/admin/clientes/{item_id}/disable", dependencies=ADMIN)
def disable_cliente(item_id:int,db:Session=Depends(get_db)):
    return set_active(db,Usuario,"usuario_id",item_id,"is_enabled")

@router.delete("/admin/clientes/{item_id}", dependencies=ADMIN)
def eliminar_cliente(item_id:int,db:Session=Depends(get_db)):
    u=db.get(Usuario,item_id)
    if not u:raise HTTPException(404,"Cliente no encontrado")
    u.is_enabled=False;db.commit()
    return {"success":True,"mensaje":"Cliente deshabilitado para preservar historial","id":item_id}

@router.get("/admin/provedores", dependencies=ADMIN)
def listar_proveedores(db:Session=Depends(get_db)):
    role_ids=select(Rol.rol_id).where(Rol.rol=="PROVEEDOR")
    users=list(db.scalars(select(Usuario).where(Usuario.rol_id.in_(role_ids))))
    return [{"usuario_id":u.usuario_id,"correo":u.correo,"nombres":u.nombres,"apellidos":u.apellidos,"telefono":u.telefono,
             "empresa_id":u.empresa_id,"activo":u.is_enabled,"facturas":db.scalar(select(func.count()).select_from(FacturaProveedor).where(FacturaProveedor.usuario_id==u.usuario_id)) or 0} for u in users]

@router.get("/admin/provedores/{item_id}", dependencies=ADMIN)
def obtener_proveedor(item_id:int,db:Session=Depends(get_db)):
    u=db.get(Usuario,item_id)
    if not u:raise HTTPException(404,"Proveedor no encontrado")
    e=db.get(Empresa,u.empresa_id) if u.empresa_id else None
    return {"usuario_id":u.usuario_id,"correo":u.correo,"nombres":u.nombres,"apellidos":u.apellidos,"telefono":u.telefono,"activo":u.is_enabled,
            "empresa":{"empresa_id":e.empresa_id,"nit":e.nit,"razon_social":e.razon_social,"correo":e.correo} if e else None}

@router.get("/admin/provedores/productos/{proveedor_id}", dependencies=ADMIN)
def productos_proveedor(proveedor_id:int,db:Session=Depends(get_db)):
    return list(db.scalars(select(FacturaProveedor).where(FacturaProveedor.usuario_id==proveedor_id)))

@router.post("/admin/provedores", status_code=201, dependencies=ADMIN)
def crear_proveedor(data:dict,db:Session=Depends(get_db)):
    from app.core.security import hash_password
    email=data.get("correo")
    if not email or not data.get("password"):raise HTTPException(422,"correo y password son obligatorios")
    if db.scalar(select(Usuario).where(Usuario.correo==email)):raise HTTPException(409,"Correo ya registrado")
    role=db.scalar(select(Rol).where(Rol.rol=="PROVEEDOR"))
    if not role:raise HTTPException(409,"No existe el rol PROVEEDOR en la base de datos")
    empresa = None
    if data.get("nit") and data.get("razon_social"):
        required_empresa = ["nit", "razon_social", "ciudad", "direccion_empresa", "telefono_empresa", "correo_empresa"]
        missing = [key for key in required_empresa if not data.get(key)]
        if missing: raise HTTPException(422, detail={"mensaje":"Faltan datos de empresa", "campos":missing})
        empresa = Empresa(nit=data["nit"], razon_social=data["razon_social"], ciudad=data["ciudad"],
                          direccion=data["direccion_empresa"], telefono=data["telefono_empresa"],
                          correo=data["correo_empresa"], imagen=data.get("imagen_empresa"), activo=True)
        db.add(empresa)
        try: db.flush()
        except Exception as exc: db.rollback(); raise HTTPException(409,"NIT, correo o teléfono de empresa duplicado") from exc
    u=Usuario(correo=email,password=hash_password(data["password"]),nombres=data.get("nombres"),apellidos=data.get("apellidos"),telefono=data.get("telefono"),direccion=data.get("direccion"),tipo_identificacion=data.get("tipo_identificacion"),numero_identificacion=data.get("numero_identificacion"),imagen=data.get("imagen"),empresa_id=empresa.empresa_id if empresa else None,rol_id=role.rol_id,is_enabled=True,account_non_expired=True,account_non_locked=True,credentials_non_expired=True)
    db.add(u)
    try:db.commit();db.refresh(u)
    except Exception as exc:db.rollback();raise HTTPException(409,"No se pudo crear proveedor") from exc
    return {"success":True,"mensaje":"Proveedor creado","id":u.usuario_id,"empresaId":u.empresa_id}

@router.put("/admin/provedores/{item_id}", dependencies=ADMIN)
def actualizar_proveedor(item_id:int,data:dict,db:Session=Depends(get_db)):
    u=db.get(Usuario,item_id)
    if not u:raise HTTPException(404,"Proveedor no encontrado")
    for k,v in payload_model(Usuario,data).items():
        if k!="password":setattr(u,k,v)
    try:db.commit()
    except Exception as exc:db.rollback();raise HTTPException(409,"No se pudo actualizar proveedor") from exc
    return {"success":True,"mensaje":"Proveedor actualizado"}

@router.patch("/admin/provedores/{item_id}/disable", dependencies=ADMIN)
def disable_proveedor(item_id:int,db:Session=Depends(get_db)):
    return set_active(db,Usuario,"usuario_id",item_id,"is_enabled")

@router.delete("/admin/provedores/{item_id}", dependencies=ADMIN)
def eliminar_proveedor(item_id:int,db:Session=Depends(get_db)):
    return disable_proveedor(item_id,db)

@router.post("/admin/provedores/compras", status_code=201, dependencies=ADMIN)
def crear_factura_proveedor(data:dict,db:Session=Depends(get_db)):
    proveedor_id = data.get("proveedorId", data.get("usuario_id"))
    if proveedor_id is None: raise HTTPException(422,"proveedorId es obligatorio")
    item=FacturaProveedor(numero_factura=data.get("numeroFactura", data.get("numero_factura")),
        fecha_emision=data.get("fechaEmision", data.get("fecha_emision")), total=float(data.get("totalCompra", data.get("total", 0))),
        usuario_id=int(proveedor_id), activo=True, fecha_registro=datetime.utcnow())
    db.add(item)
    try:
        db.flush()
        for detail in data.get("detalles", []):
            db.add(DetalleFactura(cantidad=int(detail["cantidad"]), precio_compra=int(detail["precioCompra"] if "precioCompra" in detail else detail["precio_compra"]),
                                  subtotal=int(detail.get("subtotal", int(detail["cantidad"])*int(detail.get("precioCompra",detail.get("precio_compra",0))))),
                                  factura_id=item.factura_id, producto_id=int(detail["productoId"] if "productoId" in detail else detail["producto_id"])))
        db.commit();db.refresh(item)
    except Exception as exc:db.rollback();raise HTTPException(409,"No se pudo registrar factura/detalles; verifica proveedor, productos y campos requeridos") from exc
    return {"success":True,"mensaje":"Factura de proveedor registrada","id":item.factura_id}

@router.get("/admin/compra", dependencies=ADMIN)
def compras_admin(db:Session=Depends(get_db),offset:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500)):
    return list(db.scalars(select(Compra).order_by(desc(Compra.fecha)).offset(offset).limit(limit)))

@router.get("/admin/compra/{item_id}", dependencies=ADMIN)
def detalle_compra_admin(item_id:int,db:Session=Depends(get_db)):
    c=db.get(Compra,item_id)
    if not c:raise HTTPException(404,"Compra no encontrada")
    details=list(db.scalars(select(DetalleVenta).where(DetalleVenta.compra_id==item_id)))
    return {"compra":c,"detalles":details}

@router.patch("/admin/compra/{item_id}/estado", dependencies=ADMIN)
def cambiar_estado_compra(item_id:int,data:dict,db:Session=Depends(get_db)):
    c=db.get(Compra,item_id)
    if not c:raise HTTPException(404,"Compra no encontrada")
    estado=data.get("estado")
    allowed={"CANCELADO","PAGADO","PENDIENTE","RECHAZADO"}
    if estado not in allowed:raise HTTPException(422,"Estado no válido")
    c.estado=estado
    try:db.commit()
    except Exception as exc:db.rollback();raise HTTPException(409,"No se pudo cambiar el estado") from exc
    return {"success":True,"mensaje":"Estado de compra actualizado","id":item_id,"estado":estado}

@router.get("/admin/pqrs", dependencies=ADMIN)
def listar_pqrs(db:Session=Depends(get_db)):
    return list(db.scalars(select(Peticion).order_by(desc(Peticion.fecha))))

@router.patch("/admin/pqrs/{item_id}/estado", dependencies=ADMIN)
def estado_pqrs(item_id:int,data:dict,db:Session=Depends(get_db)):
    p=db.get(Peticion,item_id)
    if not p:raise HTTPException(404,"PQRS no encontrada")
    estado=data.get("estado")
    if estado not in {"EN_PROCESO","PENDIENTE","RESUELTO"}:raise HTTPException(422,"Estado no válido")
    p.estado=estado;db.commit()
    return {"success":True,"mensaje":"Estado de PQRS actualizado","estado":estado}

@router.delete("/admin/pqrs/{item_id}", dependencies=ADMIN)
def eliminar_pqrs(item_id:int,db:Session=Depends(get_db)):
    p=db.get(Peticion,item_id)
    if not p:raise HTTPException(404,"PQRS no encontrada")
    p.activo=False;db.commit()
    return {"success":True,"mensaje":"PQRS desactivada","id":item_id}

@router.get("/admin/resenna", dependencies=ADMIN)
def listar_resenas(db:Session=Depends(get_db)):
    return list(db.scalars(select(Comentario).order_by(desc(Comentario.fecha))))

@router.patch("/admin/resenna/{item_id}/disable", dependencies=ADMIN)
def disable_resena(item_id:int,db:Session=Depends(get_db)):
    return set_active(db,Comentario,"comentario_id",item_id)

@router.delete("/admin/resenna/{item_id}", dependencies=ADMIN)
def eliminar_resena(item_id:int,db:Session=Depends(get_db)):
    c=db.get(Comentario,item_id)
    if not c:raise HTTPException(404,"Reseña no encontrada")
    c.activo=False;db.commit()
    return {"success":True,"mensaje":"Reseña desactivada","id":item_id}

@router.get("/admin/principal", dependencies=ADMIN)
def dashboard_admin(db:Session=Depends(get_db)):
    return {"totalProductos":db.scalar(select(func.count()).select_from(Producto)) or 0,
            "totalClientes":db.scalar(select(func.count()).select_from(Usuario)) or 0,
            "totalCompras":db.scalar(select(func.count()).select_from(Compra)) or 0,
            "totalProveedores":db.scalar(select(func.count()).select_from(FacturaProveedor)) or 0,
            "ventasTotales":float(db.scalar(select(func.coalesce(func.sum(Compra.total),0)).where(Compra.estado=="PAGADO")) or 0),
            "comprasPendientes":db.scalar(select(func.count()).select_from(Compra).where(Compra.estado=="PENDIENTE")) or 0}

@router.get("/api/graficas/dashboard", dependencies=ADMIN)
def grafica_dashboard(db:Session=Depends(get_db)):
    return dashboard_admin(db)

@router.get("/api/graficas/ventas-totales", dependencies=ADMIN)
def ventas_totales(db:Session=Depends(get_db)):
    total=db.scalar(select(func.coalesce(func.sum(Compra.total),0)).where(Compra.estado=="PAGADO")) or 0
    return {"ventasTotales":float(total)}

@router.get("/api/graficas/ingresos-gastos", dependencies=ADMIN)
def ingresos_gastos(db:Session=Depends(get_db)):
    ingresos=db.scalar(select(func.coalesce(func.sum(Compra.total),0)).where(Compra.estado=="PAGADO")) or 0
    gastos=db.scalar(select(func.coalesce(func.sum(FacturaProveedor.total),0)).where(FacturaProveedor.activo.is_(True))) or 0
    return {"ingresos":float(ingresos),"gastos":float(gastos),"balance":float(ingresos)-float(gastos)}

@router.get("/api/graficas/stock-compras", dependencies=ADMIN)
def stock_compras(db:Session=Depends(get_db)):
    return {"stockTotal":db.scalar(select(func.coalesce(func.sum(Producto.stock),0))) or 0,
            "comprasPendientes":db.scalar(select(func.count()).select_from(Compra).where(Compra.estado=="PENDIENTE")) or 0}

@router.get("/api/graficas/historico-ventas", dependencies=ADMIN)
def historico_ventas(db:Session=Depends(get_db)):
    rows=db.execute(select(func.date(Compra.fecha),func.sum(Compra.total)).where(Compra.estado=="PAGADO").group_by(func.date(Compra.fecha)).order_by(func.date(Compra.fecha))).all()
    return [{"fecha":str(fecha),"total":float(total or 0)} for fecha,total in rows]

@router.get("/api/graficas/mapa-ventas", dependencies=ADMIN)
def mapa_ventas(db:Session=Depends(get_db)):
    return {"mensaje":"El modelo actual no almacena ciudad o coordenadas por compra; agrega esos campos para generar un mapa geográfico real","datos":[]}

@router.get("/api/reportes/ventas-clientes", dependencies=ADMIN)
def reporte_ventas_clientes(db:Session=Depends(get_db)):
    rows=db.execute(select(Usuario.usuario_id,Usuario.correo,Usuario.nombres,func.count(Compra.compra_id),func.coalesce(func.sum(Compra.total),0)).join(Compra,Compra.usuario_id==Usuario.usuario_id).where(Compra.estado=="PAGADO").group_by(Usuario.usuario_id,Usuario.correo,Usuario.nombres)).all()
    return {"datos":[{"usuarioId":r[0],"correo":r[1],"nombre":r[2],"compras":r[3],"total":float(r[4])} for r in rows]}

@router.get("/api/reportes/ventas-producto", dependencies=ADMIN)
def reporte_ventas_producto(db:Session=Depends(get_db)):
    rows=db.execute(select(Producto.producto_id,Producto.nombre,func.sum(DetalleVenta.cantidad),func.sum(DetalleVenta.subtotal)).join(DetalleVenta,DetalleVenta.producto_id==Producto.producto_id).group_by(Producto.producto_id,Producto.nombre)).all()
    return {"datos":[{"productoId":r[0],"producto":r[1],"unidades":int(r[2] or 0),"ventas":float(r[3] or 0)} for r in rows]}

@router.get("/api/reportes/ventas-cliente-producto", dependencies=ADMIN)
def reporte_cliente_producto(db:Session=Depends(get_db)):
    rows=db.execute(select(Usuario.correo,Producto.nombre,func.sum(DetalleVenta.cantidad),func.sum(DetalleVenta.subtotal)).join(Compra,Compra.usuario_id==Usuario.usuario_id).join(DetalleVenta,DetalleVenta.compra_id==Compra.compra_id).join(Producto,Producto.producto_id==DetalleVenta.producto_id).group_by(Usuario.correo,Producto.nombre)).all()
    return {"datos":[{"cliente":r[0],"producto":r[1],"cantidad":int(r[2] or 0),"total":float(r[3] or 0)} for r in rows]}

@router.get("/api/reportes/rentabilidad-producto", dependencies=ADMIN)
def reporte_rentabilidad(db:Session=Depends(get_db)):
    return {"datos":[],"mensaje":"La tabla detalle_venta no contiene costo histórico; la rentabilidad requiere relacionar el costo de compra con cada venta."}

@router.get("/api/reportes/cuentas-pagar", dependencies=ADMIN)
def reporte_cuentas_pagar(db:Session=Depends(get_db)):
    rows=list(db.scalars(select(FacturaProveedor).where(FacturaProveedor.activo.is_(True))))
    return {"total":sum(float(x.total or 0) for x in rows),"cantidad":len(rows),"datos":rows}

@router.get("/api/reportes/reporte-compras", dependencies=ADMIN)
def reporte_compras(db:Session=Depends(get_db)):
    rows=list(db.scalars(select(Compra).order_by(desc(Compra.fecha))))
    return {"total":sum(float(x.total or 0) for x in rows if x.estado=="PAGADO"),"cantidad":len(rows),"datos":rows}

@router.get("/api/search/universal", dependencies=ADMIN)
def busqueda_universal(q:str=Query(...,min_length=1),db:Session=Depends(get_db)):
    term=f"%{q.strip()}%"
    productos=list(db.scalars(select(Producto).where(Producto.nombre.ilike(term)).limit(20)))
    categorias=list(db.scalars(select(Categoria).where(Categoria.nombre.ilike(term)).limit(20)))
    usuarios=list(db.scalars(select(Usuario).where(Usuario.correo.ilike(term)).limit(20)))
    return {"productos":productos,"categorias":categorias,"usuarios":[{"usuario_id":u.usuario_id,"correo":u.correo,"nombres":u.nombres} for u in usuarios]}

@router.get("/admin/prediccion", dependencies=ADMIN)
def prediccion_config():
    return {"disponible":False,"mensaje":"Configura PREDICCION_API_URL para habilitar el motor de predicciones externo"}

@router.get("/admin/prediccion/datos-grafica", dependencies=ADMIN)
def prediccion_datos(db:Session=Depends(get_db)):
    return historico_ventas(db)

@router.post("/admin/prediccion/generar", dependencies=ADMIN)
def generar_prediccion(data:dict):
    raise HTTPException(503,"Motor de predicciones no configurado; no se generan predicciones ficticias")
