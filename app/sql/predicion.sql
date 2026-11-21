-- Tablas del servicio de Machine Learning de predicciones (Costa De Oro Imports).
-- Son tablas NUEVAS: no modifican el esquema transaccional existente.
-- Ejecutar una vez en MySQL:  mysql -u <usuario> -p db_beer < app/prediction/sql/ml_tables.sql
-- Alternativa: python -m app.prediction.scripts_pred --create-ml-tables

CREATE TABLE IF NOT EXISTS prediccion_modelo (
    modelo_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL,
    version INT NOT NULL,
    granularidad VARCHAR(20) NOT NULL,
    estado VARCHAR(20) NOT NULL,
    fecha_entrenamiento DATETIME NOT NULL,
    epocas_ejecutadas INT NULL,
    loss_entrenamiento DOUBLE NULL,
    loss_validacion DOUBLE NULL,
    mae DOUBLE NULL,
    mse DOUBLE NULL,
    rmse DOUBLE NULL,
    mape DOUBLE NULL,
    porcentaje_acierto DOUBLE NULL,
    muestras_entrenamiento INT NULL,
    muestras_validacion INT NULL,
    muestras_prueba INT NULL,
    fuente_datos VARCHAR(30) NULL,
    ruta_artefactos VARCHAR(500) NULL,
    resumen_json TEXT NULL,
    usuario_id BIGINT NULL,
    UNIQUE KEY ix_prediccion_modelo_gran_ver (granularidad, version),
    CONSTRAINT fk_prediccion_modelo_usuario FOREIGN KEY (usuario_id) REFERENCES usuario (usuario_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prediccion_historial (
    prediccion_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    fecha_generacion DATETIME NOT NULL,
    modelo_version INT NOT NULL,
    granularidad VARCHAR(20) NOT NULL,
    periodo VARCHAR(20) NOT NULL,
    tipo_prediccion VARCHAR(20) NOT NULL DEFAULT 'sales',
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,
    ventas_estimadas DOUBLE NOT NULL,
    ventas_periodo_anterior DOUBLE NULL,
    variacion_porcentual DOUBLE NULL,
    detalle_json TEXT NULL,
    variables_json TEXT NULL,
    canal VARCHAR(20) NOT NULL,
    solicitante VARCHAR(150) NULL,
    clave_solicitud VARCHAR(64) NULL,
    ventas_reales DOUBLE NULL,
    error_porcentual DOUBLE NULL,
    fecha_evaluacion DATETIME NULL,
    KEY ix_prediccion_historial_clave_solicitud (clave_solicitud)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prediccion_evaluacion (
    evaluacion_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    tipo VARCHAR(20) NOT NULL,
    modelo_version INT NULL,
    granularidad VARCHAR(20) NOT NULL,
    fecha_evaluacion DATETIME NOT NULL,
    muestras INT NOT NULL DEFAULT 0,
    mae DOUBLE NULL,
    mse DOUBLE NULL,
    rmse DOUBLE NULL,
    mape DOUBLE NULL,
    porcentaje_acierto DOUBLE NULL,
    detalle_json TEXT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prediccion_api_cliente (
    cliente_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL,
    prefijo VARCHAR(20) NOT NULL,
    clave_hash VARCHAR(64) NOT NULL UNIQUE,
    permisos VARCHAR(255) NOT NULL,
    activo TINYINT(1) NOT NULL DEFAULT 1,
    fecha_creacion DATETIME NOT NULL,
    ultimo_uso DATETIME NULL,
    creado_por BIGINT NULL,
    CONSTRAINT fk_prediccion_api_cliente_usuario FOREIGN KEY (creado_por) REFERENCES usuario (usuario_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prediccion_acceso (
    acceso_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    fecha DATETIME NOT NULL,
    metodo VARCHAR(10) NOT NULL,
    ruta VARCHAR(255) NOT NULL,
    canal VARCHAR(20) NOT NULL,
    solicitante VARCHAR(150) NULL,
    ip VARCHAR(64) NULL,
    resultado VARCHAR(20) NOT NULL,
    KEY ix_prediccion_acceso_fecha (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
