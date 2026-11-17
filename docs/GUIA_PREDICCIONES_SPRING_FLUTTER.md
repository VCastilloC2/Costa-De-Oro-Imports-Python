# Guía del módulo de predicción

## Arquitectura

Flutter y el navegador llaman a Spring Boot. Spring verifica la sesión del usuario y consulta FastAPI usando la clave de servicio configurada en `FASTAPI_API_KEY`. FastAPI es el único servicio que prepara los datos y calcula pronósticos. Java no carga ni ejecuta modelos locales; WEKA se retiró de la aplicación Spring.

Swagger presenta todas las operaciones bajo una única etiqueta **Predicción**. Siguen existiendo endpoints separados porque cada uno cumple una operación diferente; no es necesario llamar a todos para generar una proyección. La pantalla histórica/proyección usa Holt-Winters amortiguado o una referencia estacional que repite el año anterior. FastAPI compara ambos con un backtest rodante: predice cada mes con los datos anteriores y elige el método con menor WMAPE. La métrica mide el pronóstico a un mes actualizado mes a mes; no es una garantía para 12 o 24 meses. `POST /api/v1/predictions/demand` es otro estimador por compra que combina regresión y TensorFlow/Keras. El entrenamiento versionado de `/model/train` es otro modelo neuronal temporal con rezagos. Esos modelos tienen objetivos y variables distintos y la UI ya no muestra una curva de pérdida vacía.

## Pasos de minería de datos

1. **Extracción:** el endpoint del dashboard lee en cada solicitud los totales de `compra` directamente desde MySQL, filtrando `estado = PAGADO`, fecha válida y total positivo. No depende de que existan filas relacionadas en `detalle_venta` ni usa el CSV para este gráfico. Otras operaciones de minería pueden usar la fuente que tengan configurada. En el conjunto a nivel de compra se derivan fecha/año/mes, día de semana, categoría principal, ciudad, productos, unidades y precio promedio.
2. **Limpieza:** elimina filas sin campos requeridos, ventas no positivas y meses inválidos. La serie mensual rellena con cero los meses sin ventas, porque un mes sin compra es distinto de un dato ausente.
3. **Preparación de variables:** el ensamble a nivel de compra tiene `venta_total` como objetivo `y` y ocho entradas `X`: `anno`, `mes`, `cantidad_productos`, `total_unidades`, `precio_promedio`, `dia_semana`, `categoria_principal` y `ciudad_cliente`. El `ColumnTransformer` escala columnas numéricas con `StandardScaler` y codifica categorías con `OneHotEncoder(handle_unknown="ignore")`. El objetivo nunca debe ponerse dentro de `X`.
4. **Separación:** el endpoint de demanda evalúa dejando fuera años completos; el entrenamiento versionado usa particiones cronológicas entrenamiento/validación/prueba y evita mezclar futuro en el pasado.
5. **Entrenamiento:** el ensamble de demanda promedia regresión lineal de Scikit-Learn y una red Keras. El modelo versionado usa TensorFlow/Keras, capas densas ReLU y salida lineal, optimizador Adam, pérdida MSE y EarlyStopping sobre `val_loss`.
6. **Evaluación:** MAE es el error absoluto promedio en COP por mes; MSE promedia errores al cuadrado y se expresa en COP². WMAPE = suma de errores absolutos / suma de ventas reales × 100, y precisión = max(0, 100 − WMAPE), en escala de 0 a 100%. WMAPE puede superar 100% si el modelo se equivoca más que el total vendido; la precisión entonces es 0%. No se debe subir artificialmente ese valor a 1–50, porque dejaría de representar la evaluación. Si la suma real es cero, el porcentaje se devuelve como no disponible, nunca se divide por cero. La UI compacta MAE/MSE para legibilidad y conserva el MAE exacto en el tooltip.
7. **Publicación:** FastAPI devuelve JSON; Spring lo proxyfica. La UI presenta la serie, métricas y el historial guardado por época.

## Endpoints

- **Spring para web/Flutter:** `GET /api/v1/predicciones/ventas?meses=12` (meses entre 0 y 24; requiere usuario autenticado). Responde con `serie`, `metricas`, `historial_entrenamiento`, `variables_utilizadas` y `herramientas`.
- **FastAPI detrás del proxy:** `GET /api/prediccion/datos-grafica?anios=6&proyeccion_meses=12` con `X-API-Key` de lectura.
- **Entrenar modelo versionado con ventas MySQL actuales:** `POST /api/v1/predictions/model/train` con `{"granularity":"monthly","data_source":"database","wait":true}`. Requiere permiso de administración; la respuesta debe confirmar `preparation.fuente_datos = database`.
- **Consultar estado y épocas mientras entrena:** `GET /api/v1/predictions/model/train/status`.
- **Consultar métricas y curva ya guardadas:** `GET /api/v1/predictions/model/metrics?granularity=monthly`.
- **Predicción por compra con el ensamble:** `POST /api/v1/predictions/demand`.

El conteo que se ve en una consulta SQL a `compra` incluye estados como `PENDIENTE` y `CANCELADO`; el pronóstico suma exclusivamente compras `PAGADO`. La tabla puede mostrar miles de órdenes sin que todas representen ventas realizadas. Además, la proyección usa los importes `compra.total`, por lo que un total pagado se cuenta aunque falten detalles de producto.

## Cómo se dibuja la curva

La curva se conserva como dato para clientes que la necesiten, pero se quitó de esta pantalla porque el entrenamiento mensual no estaba completado y el gráfico vacío confundía. Para graficarla en otra interfaz, use `GET /api/v1/predictions/model/metrics?granularity=monthly` o consulte épocas en `/model/train/status`. Empareje `epocas[i]` con `loss[i]`; esa pérdida está en objetivo normalizado, no en COP².

## Consumo desde Flutter

Flutter debe llamar al endpoint de Spring, no a FastAPI directamente. Envíe `GET /api/v1/predicciones/ventas?meses=12` con la cookie/token de autenticación de Spring y `Accept: application/json`. Lea `serie` para la gráfica principal, `metricas.validacion.mae`, `metricas.validacion.mse` y `metricas.validacion.porcentaje_prediccion` para las tarjetas, y empareje `historial_entrenamiento.epocas[i]` con `loss[i]` para la gráfica de entrenamiento. `variables_utilizadas` y `herramientas` sirven para mostrar el detalle informativo. Si `loss` viene vacío, aún no existe un entrenamiento mensual versionado; consulte el estado y ejecute el entrenamiento administrativo en FastAPI. No incruste `FASTAPI_API_KEY` en Flutter.

## Herramientas

Python, FastAPI, Pandas, NumPy, Scikit-Learn (`ColumnTransformer`, `StandardScaler`, `OneHotEncoder`, regresión lineal), TensorFlow/Keras, SQLAlchemy, Spring Boot, JavaScript y ApexCharts. Flutter puede usar cualquier paquete de gráficos que acepte listas de puntos XY.
