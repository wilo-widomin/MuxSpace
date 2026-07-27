# US-023 · Documentar (y proteger) el requisito de un solo worker

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 1 | fase-5-deuda | S2 |

## Historia

Como responsable del panel, quiero que **quede escrito que el backend corre
con un único worker de uvicorn**, porque los locks de los stores son
`threading.Lock` —de proceso— y con `--workers 4` se corrompe la biblioteca
de comandos por read-modify-write concurrente.

Hoy es un requisito **implícito**: no está en ninguna parte y la próxima
persona que quiera "escalar el panel" lo descubre perdiendo datos.

## Criterios de aceptación

- [ ] El README documenta el requisito, **con el porqué** (locks de proceso)
      y qué pasa si se ignora (biblioteca corrupta, no "puede haber
      problemas").
- [ ] `start.sh` deja claro que arranca con un solo worker, con un comentario
      que apunte al mismo motivo.
- [ ] Los módulos con estado compartido (`library_store`, `space_store`,
      `upload_store`, `auth`) lo mencionan en su docstring, junto al `Lock`.
      Es donde lo va a leer quien esté a punto de romperlo.
- [ ] **Aviso en arranque**: si se detecta más de un worker, el backend lo
      registra de forma visible. Un `WEB_CONCURRENCY` o `--workers > 1` no
      puede pasar en silencio. Si detectarlo resulta poco fiable, documenta
      por qué y quédate solo con la documentación — pero pruébalo antes de
      descartarlo.
- [ ] `docs/` recoge la alternativa descartada (locking de fichero con
      `fcntl.flock`) y por qué no se hace ahora: el panel es de un solo
      usuario y un solo worker basta.

## Alcance técnico

- `README.md`, `start.sh`, docstrings de los cuatro módulos, `docs/`.
- Si haces el aviso: el `lifespan` de `main.py` es el sitio.

## Fuera de alcance

- Implementar locking de fichero. Es la alternativa documentada, no el
  trabajo de esta US.
- Cambiar los stores.

## Dependencias

Ninguna.

## Rigor

`ligero`.

## Concurrencia

`compartida`.

## Notas para el agente

- Es una US de documentación, así que el listón es que **alguien que llegue
  nuevo no pueda romperlo sin haber leído el aviso**. Si tu documentación
  vive solo en el README, no cumple: por eso los docstrings.
- Un comentario que diga "no usar más de un worker" sin explicar el porqué
  se borra en el primer refactor. El porqué es lo que hay que escribir.
