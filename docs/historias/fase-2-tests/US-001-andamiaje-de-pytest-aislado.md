# US-001 · Andamiaje de pytest aislado de los datos reales

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 3 | fase-2-tests | S1 |

## Historia

Como responsable del panel, quiero **poder escribir tests del backend sin
riesgo de tocar mis datos reales**, para que la red de seguridad que viene
detrás (US-002 a US-007) no me cueste la biblioteca de comandos ni el
historial de subidas.

Hoy el proyecto tiene 0 tests. Esta US no prueba nada del producto: monta el
suelo sobre el que se apoyan las seis siguientes. Si el aislamiento sale mal,
todas las demás heredan el fallo.

## Criterios de aceptación

- [ ] `backend/venv/bin/python -m pytest -q` corre desde la raíz del repo y
      termina en verde.
- [ ] Existe `backend/requirements-dev.txt` con `pytest`, `pytest-cov` y
      `httpx` (lo necesita `TestClient`), **separado** de
      `requirements.txt`, que no engorda.
- [ ] `conftest.py` fija las variables `MUXSPACE_*` **antes** de importar
      nada del backend (`config.py` lee el entorno en import time).
- [ ] `conftest.py` apunta a un `tmp_path` los cuatro stores
      (`library_store`, `space_store`, `upload_store`), el registro de
      `auth` (`_FAILURES_PATH`, `_BANNED_PATH`), `_PASTE_DIR` de `main` y
      `MUXSPACE_DIR_SUGGESTION_ROOTS`.
- [ ] **El primer test del andamiaje verifica el aislamiento**: recorre esas
      rutas y falla si alguna cae bajo `backend/data/`. Es el guardián de la
      regla, no un comentario en un README.
- [ ] Ese test de aislamiento **falla si se rompe el conftest** (compruébalo
      a mano quitando una línea antes de darlo por bueno).
- [ ] Hay un fixture `client` (`TestClient`) y un fixture que permite elegir
      si la app se levanta con la autenticación activada o desactivada; los
      tests de US-002 y US-005 necesitan ambos.
- [ ] Tras `pytest`, `git status` está limpio y `backend/data/` no ha
      cambiado (ni mtime de sus ficheros).
- [ ] `pytest.ini` o la sección `[tool.pytest.ini_options]` de
      `pyproject.toml` fija `testpaths` y deja `pytest` ejecutable sin
      argumentos.

## Alcance técnico

Archivos a crear:

- `backend/requirements-dev.txt`
- `backend/tests/__init__.py` (si hace falta para los imports)
- `backend/tests/conftest.py`
- `backend/tests/test_aislamiento.py`
- `pyproject.toml` (o `pytest.ini`) en la raíz, solo con la config de pytest.

Puntos delicados:

1. **Import time.** `config.py` hace `load_dotenv(backend/.env)` y luego
   `os.getenv(...)` al importarse. `load_dotenv` **no** hace override, así
   que basta con poner las variables en `os.environ` antes del primer
   `import config`. Hazlo en el propio `conftest.py`, arriba del todo,
   antes de cualquier import del backend.
2. **Rutas de módulo.** Los `_STORE_PATH` son constantes de módulo
   calculadas en import time (`Path(__file__).parent / "data" / ...`). No
   se pueden cambiar por entorno: hay que hacer `monkeypatch.setattr` sobre
   el atributo del módulo ya importado, o recargar con `importlib.reload`
   tras cambiar `__file__`. Elige uno y documenta por qué en el conftest.
3. **`sys.path`.** El backend importa en plano (`import config`, no
   `from backend import config`), porque uvicorn arranca con
   `--app-dir backend`. El conftest tiene que añadir `backend/` al
   `sys.path` para reproducirlo.
4. **`backend/.env` es el despliegue real del usuario.** Ni se lee ni se
   modifica. Fija el entorno y ya.

Añade al PR: `"test": "backend/venv/bin/python -m pytest -q"` en el bloque
`verify` de `.claude/us-pipeline.config.json`.

## Fuera de alcance

- Cualquier test del producto (van en US-002 a US-007).
- Cobertura mínima y `--cov-fail-under` (los fija US-009 con el CI).
- Instalar tmux en el entorno de pruebas (lo trae US-007).
- Tests del frontend (US-017).

## Dependencias

Ninguna.

## Rigor

`estándar`. Es andamiaje, pero un aislamiento mal hecho corrompe datos
reales: el criterio de "el test de aislamiento falla si rompes el conftest"
no es negociable.

## Concurrencia

`exclusiva`. Crea la estructura de la que dependen todas las US de la fase 2;
ninguna otra puede correr a la vez.

## Notas para el agente

- El objetivo real de esta US es que **US-004 pueda plantar un symlink y
  subir un archivo sin que exista la más mínima posibilidad de que eso pase
  en el home del usuario**. Diseña el aislamiento pensando en ese caso.
- No inventes una capa de abstracción para "hacer los stores testeables".
  El repo es deliberadamente plano: `monkeypatch` sobre el atributo de
  módulo es suficiente y no toca producción.
- Un `pytest -q` que tarde más de un par de segundos en esta fase es señal
  de que algo está tocando la red o el disco real.
