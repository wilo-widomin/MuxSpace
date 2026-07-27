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

# Quien entra al panel ejecuta comandos como el usuario que corre el
# backend, y esta contraseña de ejemplo está publicada en el README y en
# .env.example. Arrancar con ella sería dejar la puerta abierta, así que
# no arrancamos. Solo aplica al modo env (en pam la contraseña la valida
# el sistema) y con la auth activada.
if AUTH_ENABLED and AUTH_MODE == "env" and AUTH_PASSWORD in {"admin", ""}:
    raise ValueError(
        "MUXSPACE_PASSWORD está vacía o es la contraseña de ejemplo "
        "('admin'). Ponle una en backend/.env antes de arrancar: el panel "
        "da acceso a "
        "una shell como el usuario que ejecuta el backend. "
        "(Alternativas: MUXSPACE_AUTH_MODE=pam para validar contra el "
        "sistema, o MUXSPACE_AUTH_ENABLED=false si el acceso ya está "
        "protegido por otra capa, p. ej. mTLS.)"
    )

# Horas de validez de la sesión iniciada en /api/login (cookie HttpOnly).
SESSION_TTL_HOURS: int = int(os.getenv("MUXSPACE_SESSION_TTL_HOURS", "168"))

# Marca la cookie de sesión como `Secure` (solo viaja por HTTPS). El
# default es True porque el despliegue normal del panel es tras un proxy
# con TLS: si el default fuera False, la cookie que abre una shell saldría
# en claro por olvidar una variable. Ponlo a false SOLO para desarrollo
# contra http://localhost (con Secure el navegador no guarda la cookie y
# el login no llega a funcionar).
COOKIE_SECURE: bool = _get_bool("MUXSPACE_COOKIE_SECURE", True)

# Publica /docs, /redoc y /openapi.json. Default False: FastAPI las sirve
# SIN autenticación (son rutas de Starlette, no del router de la API, así
# que ni pasan por `require_auth` ni las ve el contrato de rutas), y lo que
# ahí se publica es el mapa completo de un panel que ejecuta comandos como
# el usuario que corre el backend: `send-command`, `launch`, `run` y las
# rutas de subida, con sus esquemas. Es reconocimiento gratis para quien
# llegue al puerto. Actívalo en desarrollo si te hace falta el explorador.
DOCS_ENABLED: bool = _get_bool("MUXSPACE_DOCS_ENABLED", False)

# --- Servidor ---
# 127.0.0.1 = solo acceso local (default seguro). Usa 0.0.0.0 (via .env)
# si vas a poner un reverse proxy delante para alcanzarlo desde fuera.
HOST: str = os.getenv("MUXSPACE_HOST", "127.0.0.1")
PORT: int = int(os.getenv("MUXSPACE_PORT", "8000"))

# IPs de los reverse proxies en los que confiamos para leer la IP real del
# cliente en la cabecera X-Forwarded-For (uvicorn --forwarded-allow-ips).
# Por defecto 127.0.0.1: el caso normal, con el proxy en la misma máquina.
# Si el proxy vive en OTRO host, tienes que añadir su IP aquí o el rate
# limit y los baneos verán siempre la IP del proxy en vez de la del cliente:
# dejarían de proteger, y los 5 fallos de un solo atacante bloquearían el
# login de todo el mundo.
# Añade solo IPs de proxies reales: quien esté en esta lista puede falsear
# su IP a placer vía X-Forwarded-For y saltarse los baneos. Nunca uses '*'
# si el backend es alcanzable sin pasar por el proxy.
TRUSTED_PROXIES: list[str] = _get_str_list(
    "MUXSPACE_TRUSTED_PROXIES", ["127.0.0.1"]
)

# Binario de tmux (por si no está en el PATH estándar).
TMUX_BINARY: str = os.getenv("MUXSPACE_TMUX_BINARY", "tmux")

# Orígenes permitidos para CORS. En producción el frontend lo sirve el
# propio backend (mismo origen), así que CORS casi no hace falta; estos
# valores por defecto cubren solo el modo desarrollo (Vite en :5173).
# Si expones el panel tras un dominio/proxy, añádelo aquí o en .env.
# Se lee con `_get_str_list` (y no con un `.split(",")` propio) porque esta
# lista alimenta DOS controles: el CORS de arriba y el guard de Origin de
# `main.py`, que sí normalizaba espacios. Un espacio tras una coma
# desalineaba ambos y rompía el CORS en silencio.
CORS_ORIGINS: list[str] = _get_str_list(
    "MUXSPACE_CORS_ORIGINS",
    ["http://localhost:5173", "http://127.0.0.1:5173"],
)

# Raíces de directorio bajo las que se ofrecen sugerencias de autocompletado
# al escribir un "directorio" en el frontend. Se expande `~` al home del
# usuario que ejecuta el backend, de modo que las sugerencias siempre
# arrancan "a partir de mi usuario". Acepta JSON (`["~", "/srv"]`) o
# una lista separada por comas. Ver `.env.example`.
DIR_SUGGESTION_ROOTS: list[str] = _get_str_list(
    "MUXSPACE_DIR_SUGGESTION_ROOTS", ["~"]
)
