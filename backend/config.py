"""Configuración central del backend.

Los valores se leen de variables de entorno (ver `.env.example`) con
valores por defecto razonables para desarrollo local.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Carga SIEMPRE el .env que vive junto a este módulo (backend/.env),
# independientemente del directorio desde el que se arranque uvicorn
# (start.sh arranca desde la raíz del repo; load_dotenv() sin ruta solo
# busca hacia arriba desde el cwd y no lo encontraría). Así los valores
# del entorno (dominio CORS, raíces de directorios, etc.) viven en .env
# y no hardcodeados en el código. Si el archivo no existe (instalación
# limpia sin .env), se usan los valores por defecto de más abajo.
load_dotenv(Path(__file__).resolve().parent / ".env")


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_str_list(name: str, default: list[str]) -> list[str]:
    """Lee una lista de strings de una variable de entorno.

    Acepta JSON (`["~", "/srv"]`) o, si no es JSON válido, una
    lista separada por comas. Elimina vacíos y de espacios.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return list(default)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except (json.JSONDecodeError, ValueError):
        pass
    return [x.strip() for x in raw.split(",") if x.strip()]


# --- Autenticación (login con sesión; HTTP Basic como alternativa CLI) ---
AUTH_ENABLED: bool = _get_bool("MUXSPACE_AUTH_ENABLED", True)

# Cómo se validan las credenciales del login:
#   env -> usuario/contraseña fijados abajo (MUXSPACE_USERNAME/PASSWORD).
#   pam -> contra el sistema (PAM): se entra con el usuario y la contraseña
#          de Linux del usuario que ejecuta el backend. Sin root, PAM solo
#          puede verificar la contraseña de ese usuario, que es exactamente
#          el dueño de las terminales que expone el panel.
AUTH_MODE: str = os.getenv("MUXSPACE_AUTH_MODE", "env").strip().lower()
if AUTH_MODE not in {"env", "pam"}:
    raise ValueError(
        f"MUXSPACE_AUTH_MODE inválido: {AUTH_MODE!r} (usa 'env' o 'pam')."
    )

# Servicio PAM con el que se valida (solo en modo pam). 'login' existe en
# prácticamente cualquier distro; en RHEL/Fedora también 'system-auth'.
PAM_SERVICE: str = os.getenv("MUXSPACE_PAM_SERVICE", "login")

AUTH_USERNAME: str = os.getenv("MUXSPACE_USERNAME", "admin")
AUTH_PASSWORD: str = os.getenv("MUXSPACE_PASSWORD", "admin")

# Horas de validez de la sesión iniciada en /api/login (cookie HttpOnly).
SESSION_TTL_HOURS: int = int(os.getenv("MUXSPACE_SESSION_TTL_HOURS", "168"))

# Marca la cookie de sesión como `Secure` (solo viaja por HTTPS). Actívalo
# cuando sirvas el panel tras un reverse proxy con TLS.
COOKIE_SECURE: bool = _get_bool("MUXSPACE_COOKIE_SECURE", False)

# --- Servidor ---
# 127.0.0.1 = solo acceso local (default seguro). Usa 0.0.0.0 (via .env)
# si vas a poner un reverse proxy delante para alcanzarlo desde fuera.
HOST: str = os.getenv("MUXSPACE_HOST", "127.0.0.1")
PORT: int = int(os.getenv("MUXSPACE_PORT", "8000"))

# Binario de tmux (por si no está en el PATH estándar).
TMUX_BINARY: str = os.getenv("MUXSPACE_TMUX_BINARY", "tmux")

# Orígenes permitidos para CORS. En producción el frontend lo sirve el
# propio backend (mismo origen), así que CORS casi no hace falta; estos
# valores por defecto cubren solo el modo desarrollo (Vite en :5173).
# Si expones el panel tras un dominio/proxy, añádelo aquí o en .env.
CORS_ORIGINS: list[str] = os.getenv(
    "MUXSPACE_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

# Raíces de directorio bajo las que se ofrecen sugerencias de autocompletado
# al escribir un "directorio" en el frontend. Se expande `~` al home del
# usuario que ejecuta el backend, de modo que las sugerencias siempre
# arrancan "a partir de mi usuario". Acepta JSON (`["~", "/srv"]`) o
# una lista separada por comas. Ver `.env.example`.
DIR_SUGGESTION_ROOTS: list[str] = _get_str_list(
    "MUXSPACE_DIR_SUGGESTION_ROOTS", ["~"]
)
