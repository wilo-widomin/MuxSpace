"""Las cabeceras de seguridad que el backend pone en TODA respuesta.

Van aquí y no en `test_auth.py` porque no son autenticación: son lo que el
navegador hace por su cuenta antes y después de que el panel diga nada. Y son
fáciles de perder sin que nada se rompa —una cabecera que desaparece no da
error, solo deja de proteger—, así que lo que se fija es su presencia y la
condición de cada una.

El caso que más importa es el negativo: `Strict-Transport-Security` NO debe
salir por http. Emitirla en desarrollo contra `http://localhost` dejaría el
localhost del usuario exigiendo TLS durante un año a todos sus proyectos, y
eso no se arregla borrando la línea que la puso.
"""
from __future__ import annotations

import pytest

import main


@pytest.fixture
def cliente_https(data_dir):
    """Cliente que habla con la app como si viniera por HTTPS.

    `base_url` decide el `scheme` del scope ASGI, que es de donde sale el
    `request.url.scheme` del middleware. En producción ese esquema lo pone
    uvicorn a partir de `X-Forwarded-Proto` porque `start.sh` arranca con
    `--proxy-headers`; sin eso, detrás del proxy toda petición parecería http
    y la cabecera no saldría nunca.
    """
    from fastapi.testclient import TestClient

    with TestClient(main.app, base_url="https://testserver") as c:
        yield c


@pytest.mark.parametrize(
    ("cabecera", "esperado"),
    [
        ("X-Frame-Options", "DENY"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ],
)
def test_las_cabeceras_de_siempre_salen_por_http_y_por_https(
    client, cliente_https, cabecera: str, esperado: str
) -> None:
    """Todas menos HSTS no dependen del esquema."""
    for cliente in (client, cliente_https):
        resp = cliente.get("/api/health")
        assert resp.headers.get(cabecera) == esperado


def test_la_csp_prohibe_enmarcar_el_panel(client) -> None:
    """`frame-ancestors 'none'` es la que impide el clickjacking.

    En un panel que da shell, un clic inducido dentro de un iframe invisible
    —con el certificado mTLS presentado solo por el navegador— equivale a
    ejecución remota. El guard de Origin no cubre ese caso: dentro del iframe
    todo es same-origin.
    """
    csp = client.get("/api/health").headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'self'" in csp


def test_hsts_sale_por_https(cliente_https) -> None:
    """Un año, para que el navegador no vuelva a intentar http."""
    resp = cliente_https.get("/api/health")

    assert resp.headers.get("Strict-Transport-Security") == "max-age=31536000"


def test_hsts_no_sale_por_http(client) -> None:
    """El caso que protege el desarrollo local, y el motivo de la condición.

    Es el reverso del anterior y el que de verdad hay que fijar: si esta
    cabecera se emitiera en `http://localhost:8000`, el navegador recordaría
    durante un año que ese host va por TLS y rompería en silencio cualquier
    otro proyecto del usuario servido ahí.
    """
    resp = client.get("/api/health")

    assert "strict-transport-security" not in {
        k.lower() for k in resp.headers
    }, "HSTS emitida por http: el localhost del usuario se queda exigiendo TLS"


def test_las_cabeceras_salen_tambien_en_una_respuesta_de_error(client) -> None:
    """El middleware envuelve a los demás, no solo al camino feliz.

    Se declara el último a propósito para que las cabeceras salgan también en
    los 403 del guard de Origin y del baneo por IP. Un 401 sirve igual para
    comprobarlo y no necesita montar un origen falso.
    """
    resp = client.get("/api/sessions")

    assert resp.status_code == 401
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "frame-ancestors 'none'" in resp.headers.get(
        "Content-Security-Policy", ""
    )
