# Búsqueda de ciudades con OpenStreetMap Nominatim

FastAPI ofrece una búsqueda puntual de ciudades y municipios de Colombia a través de Nominatim. Puede usarse para seleccionar una ciudad de sucursal o conseguir coordenadas para centrar un mapa.

## Endpoint

`GET /api/ubicacion/ciudades?q=Medellín&departamento=Antioquia`

Ejemplo de respuesta:

```json
{
  "resultados": [
    {
      "nombre": "Medellín",
      "departamento": "Antioquia",
      "pais": "Colombia",
      "latitud": 6.2442,
      "longitud": -75.5812,
      "nombre_completo": "Medellín, Antioquia, Colombia",
      "osm_type": "relation",
      "osm_id": 123456
    }
  ],
  "atribucion": "© OpenStreetMap contributors — https://www.openstreetmap.org/copyright",
  "licencia": "ODbL"
}
```

Los resultados reales y sus coordenadas dependen de los datos vigentes de OpenStreetMap. En Flutter, llama el endpoint cuando la persona confirme una búsqueda de ciudad (por ejemplo, al pulsar Buscar); no lo consultes en cada tecla para crear autocompletado. Muestra la atribución de OpenStreetMap junto al mapa o a los resultados.

## Privacidad y límites

- La búsqueda está limitada a ciudades colombianas y devuelve hasta cinco resultados.
- No envíes domicilios, nombres de personas, teléfonos, pedidos ni coordenadas GPS personales. Este endpoint es solo para nombres de ciudades o municipios.
- FastAPI guarda resultados en caché durante siete días por defecto, limita a diez búsquedas por IP cada minuto y separa al menos un segundo entre consultas no cacheadas a Nominatim. Con `VALKEY_URL`, el límite de proveedor se comparte entre instancias; sin Valkey, el límite global solo puede aplicarse por proceso.
- El `User-Agent` identifica esta aplicación. Puedes personalizar `NOMINATIM_USER_AGENT`, desactivar la función o cambiar el servidor compatible sin modificar el contrato de Flutter.
- El servicio público de Nominatim tiene capacidad limitada. Para uso comercial de mayor volumen, evalúa un proveedor contratado o una instancia propia.

Variables de configuración: `NOMINATIM_ENABLED`, `NOMINATIM_BASE_URL`, `NOMINATIM_USER_AGENT`, `NOMINATIM_TIMEOUT_SECONDS` y `NOMINATIM_CACHE_SECONDS`.

La política pública de Nominatim prohíbe el autocompletado, establece un máximo de una petición por segundo, exige identificar la aplicación, atribución visible y caché, y pide no enviar datos personales. Consulta la [política vigente](https://operations.osmfoundation.org/policies/nominatim/) antes de aumentar el tráfico.
