---
dominio: jornada
actualizado: 2026-08-29
archivos:
  - backend/worklog.py
  - backend/worklog_signals.py
  - backend/main.py
  - frontend/src/worklog.js
  - frontend/src/useWorkClock.js
  - frontend/src/useWorkPause.js
  - frontend/src/components/Dashboard.jsx
depende_de: [espacios/_dominio, biblioteca/_dominio]
---

# Jornada

Mide **horas del usuario por proyecto**, no horas transcurridas: el panel late
mientras hay entrada real y el servidor lo cuaja en ranuras de 30 s. Sobre esos
mismos datos ofrece dos formas de contar el día, pausas declarables y un
dashboard que deriva todos los totales al leer, sin acumulados guardados.

## Modelo de datos

En **SQLite**, `backend/data/worklog.db` (no JSON: ~1000 ranuras por jornada).
Todos los instantes son **epoch en segundos UTC**.

- `work_slots` — `slot_start` es **clave primaria** y múltiplo de 30. Que sea
  PK es el invariante estructural: una ranura de reloj solo puede trabajarse
  una vez, así que dos pestañas o dos dispositivos colapsan en la misma y la
  suma nunca supera el tiempo real. Además `space` (`"unassigned"` si viene
  vacío), `session`, `command` (`pane_current_command`, lo que permite separar
  las horas con agente delante) y `source`.
- `work_pauses` — `start` PK, `end` **NULL significa pausa abierta**, `source`
  `manual` (botón) o `answer` (declarada a posteriori).
- `work_claims` — `start` PK, `end`. Huecos largos reclamados como trabajo. Se
  guarda el reclamo y no la ausencia: la ausencia es la norma y se deduce al
  leer.
- `transcript_slots` / `transcript_files` — ranuras derivadas de los `.jsonl`
  de Claude Code, con escaneo incremental por offset y mtime.
- Un **bloque no se persiste**: se deriva al leer agrupando ranuras
  consecutivas del mismo espacio, tolerando un hueco de 2 ranuras porque un
  latido se puede perder.

## Invariantes

- **La hora la pone el servidor**, nunca el cliente, y el `INSERT OR IGNORE`
  hace que la primera pestaña se quede la ranura.
- **La salida del PTY no es actividad.** Contarla invertiría el dato: se mide
  al usuario, no al programa.
- **Un hueco sin ninguna señal no es trabajo.** Por encima de 30 min se
  descuenta sin preguntar; lo excepcional se reclama a mano.
- Los datos del worklog son los únicos irreconstruibles: el esquema se migra
  con `ALTER TABLE`, nunca recreando la tabla.

## Acciones documentadas

- [Contar la jornada](contar-la-jornada.md)
- [Pausas y ausencias](pausas.md)

## Trampas

- La base y la API hablan en **segundos**; el frontend, en **milisegundos**, y
  convierte solo en `api.js`. El dashboard multiplica por 1000 al borrar una
  pausa porque la capa de API vuelve a dividir: es ida y vuelta intencionada.
- `GET /dashboard` sirve el HTML **sin auth** (es solo la cáscara; los datos
  van por `/api/worklog/*`, que sí la exige). Hace falta una ruta explícita
  porque los estáticos dan 404 para lo que no es un archivo.
- El latido está desactivado mientras miras el dashboard: mirarlo no es
  trabajar.
- Un latido que falla no se reintenta: cuesta 30 s y el instante ya pasó.
- Las preferencias de lectura (modo, puente) viven en `localStorage`, no en el
  servidor: dos dispositivos pueden ver el mismo dato contado distinto.
