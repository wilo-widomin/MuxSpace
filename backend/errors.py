"""Errores de aplicación con código traducible.

El backend es agnóstico al idioma: en vez de un mensaje en español, cada
error viaja como `{code, params, technical}` y es el cliente quien lo
traduce (ver `frontend/src/i18n/`). Así el catálogo de traducciones vive
en un único sitio y ningún fallo mezcla idiomas.

  - `code`: clave del catálogo, p. ej. "err.session_exists".
  - `params`: valores a interpolar en el mensaje ({"name": "sesion-1"}).
  - `technical`: texto SIN traducir (típicamente el stderr de tmux, que
    sale en el idioma del sistema). El cliente lo pinta como detalle
    secundario en vez de sustituir al mensaje localizado.
"""
from __future__ import annotations

from fastapi import HTTPException


class AppError(RuntimeError):
    """Error de dominio identificado por un código de traducción."""

    def __init__(
        self,
        code: str,
        params: dict | None = None,
        technical: str | None = None,
    ) -> None:
        self.code = code
        self.params = params or {}
        self.technical = (technical or "").strip() or None
        super().__init__(code)

    @property
    def detail(self) -> dict:
        """Cuerpo del `detail` de la respuesta de error."""
        return error_detail(self.code, self.technical, **self.params)


def error_detail(code: str, technical: str | None = None, **params) -> dict:
    detail: dict = {"code": code}
    if params:
        detail["params"] = params
    if technical:
        detail["technical"] = technical
    return detail


def http_error(
    status_code: int,
    code: str,
    technical: str | None = None,
    **params,
) -> HTTPException:
    """`HTTPException` con el `detail` en formato `{code, params}`."""
    return HTTPException(
        status_code=status_code,
        detail=error_detail(code, technical, **params),
    )


def http_from(status_code: int, exc: AppError) -> HTTPException:
    """Traslada un `AppError` de la capa de dominio a la respuesta HTTP."""
    return HTTPException(status_code=status_code, detail=exc.detail)
