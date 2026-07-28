# US-018 · Registro de auditoría de comandos ejecutados (S8)

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 3 | fase-5-deuda | S1 |

## Historia

Como responsable del panel, quiero **una traza de qué comando se ejecutó, en
qué sesión, cuándo y desde qué IP**, porque hoy no queda ninguna y en un
panel que da shell es precisamente el log que hace falta el día que pase
algo.

## Criterios de aceptación

- [ ] `backend/data/audit.log`: **un JSON por línea** (JSONL), con los campos
      `{ts, ip, user, action, target, detail}`.
- [ ] `ts` en ISO 8601 con zona horaria (UTC). Nada de epoch pelado.
- [ ] `ip` es la IP real del cliente (la que ya se usa para el rate limit,
      respetando `X-Forwarded-For` de los proxies de confianza).
- [ ] Se registran, como mínimo: `send-command`, `launch` (comando de la
      biblioteca), `run-project`, `create-session`, `kill-session`,
      `rename-session` y `upload`.
- [ ] `detail` lleva lo que hace falta para reconstruir qué pasó: el comando
      enviado, la ruta subida, el nombre nuevo al renombrar.
- [ ] El fichero se crea a **0600** dentro de `data/` (usa `datafiles`).
- [ ] **Rotación simple por tamaño**: al superar un tope (p. ej. 5 MB) el
      fichero pasa a `audit.log.1` y se abre uno nuevo. Se conserva **solo**
      la rotación anterior; sin librerías de logging externas.
- [ ] Escribir en el log **nunca** tumba una petición: si el disco falla, se
      traga el error y la acción sigue. Hay un test que lo demuestra.
- [ ] Tests: cada acción de la lista produce **exactamente una** línea con
      los campos esperados; la rotación se dispara al superar el tope; un
      fallo de escritura no propaga.
- [ ] El README documenta dónde está el log, qué formato tiene y que **no**
      se rota por tiempo.

## Alcance técnico

- Módulo nuevo `backend/audit.py` con una función `record(...)` y su lock.
  No metas la lógica en `main.py`.
- Llamadas desde los endpoints de `main.py` correspondientes.
- Tests en `backend/tests/test_audit.py`.

Cuidado con dos cosas:

1. **No registres credenciales.** El login puede registrarse (éxito/fallo),
   pero jamás la contraseña ni el token de sesión.
2. Los endpoints son síncronos y corren en un threadpool: el escritor
   necesita un `threading.Lock`, como el resto de stores.

## Fuera de alcance

- Logging estructurado general de la aplicación (Q6 del análisis): esto es
  el log de auditoría, no el de la app.
- Métricas, dashboards o envío a un servicio externo.
- Rotación por tiempo o compresión.

## Dependencias

US-001.

## Rigor

`estándar`.

## Concurrencia

`compartida` con las demás US de la fase 5, salvo que otra toque los mismos
endpoints de `main.py`.

## Notas para el agente

- El criterio "escribir en el log nunca tumba una petición" es el que
  distingue un log de auditoría útil de una nueva forma de caerse. Pruébalo.
- Un JSONL se lee con `jq` desde el propio panel; ese es el consumidor real.
  Diseña los campos pensando en `jq 'select(.action=="send-command")'`.

## Registro de ejecución

> Generado por `servidor-pipeline`. Tiempos de la última ejecución.

- Inicio: 2026-07-28 11:23:15 UTC
- Fin:    2026-07-28 14:43:45 UTC
- Tiempo transcurrido: 03:20:30 (HH:mm:ss)
- PR:     (sin PR)
- Estado: in-review
