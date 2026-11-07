-- Passkeys (WebAuthn) — tablas NUEVAS; no modifican la tabla usuario.
-- Ejecutar una vez:  mysql -u <usuario> -p db_beer < app/sql/passkeys.sql

CREATE TABLE IF NOT EXISTS passkey_credencial (
    passkey_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    usuario_id BIGINT NOT NULL,
    credential_id VARCHAR(512) NOT NULL,      -- base64url del rawId
    public_key TEXT NOT NULL,                 -- clave pública COSE en base64url
    user_handle VARCHAR(128) NOT NULL,        -- identificador opaco WebAuthn del usuario (base64url)
    sign_count BIGINT NOT NULL DEFAULT 0,
    transports VARCHAR(255) NULL,             -- JSON: ["internal","hybrid"]
    aaguid VARCHAR(64) NULL,
    device_type VARCHAR(20) NULL,             -- single_device | multi_device
    backed_up TINYINT(1) NOT NULL DEFAULT 0,  -- passkey sincronizada (iCloud / Google)
    device_name VARCHAR(60) NULL,
    activo TINYINT(1) NOT NULL DEFAULT 1,
    fecha_creacion DATETIME NOT NULL,
    ultimo_uso DATETIME NULL,
    UNIQUE KEY uq_passkey_credencial_credential_id (credential_id),
    KEY ix_passkey_credencial_usuario (usuario_id),
    KEY ix_passkey_credencial_user_handle (user_handle),
    CONSTRAINT fk_passkey_credencial_usuario FOREIGN KEY (usuario_id)
        REFERENCES usuario (usuario_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Respaldo de challenges cuando Valkey no está disponible (un solo uso, con expiración).
CREATE TABLE IF NOT EXISTS passkey_challenge (
    challenge_id VARCHAR(64) NOT NULL PRIMARY KEY,
    tipo VARCHAR(20) NOT NULL,
    datos_json TEXT NOT NULL,
    expira_en DATETIME NOT NULL,
    KEY ix_passkey_challenge_expira (expira_en)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
