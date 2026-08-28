---
dominio: jornada
accion: pausas
actualizado: 2026-08-28
archivos:
  - backend/worklog.py
  - backend/main.py
  - frontend/src/useWorkPause.js
  - frontend/src/components/PauseQuestion.jsx
  - frontend/src/components/Dashboard.jsx
---

# Pausas

La pausa es el único dato que el sistema no puede deducir, y solo tiene sentido
en modo `workday`: si la jornada se cuenta entera, lo que hay que declarar es
la **ausencia**. Los controles de pausa solo aparecen en ese modo.

## Flujos

- **Me voy / vuelvo**: botón del sidebar → `useWorkPause.js` →
  `POST /api/worklog/pause` y `/resume` → `worklog.pausar()` / `reanudar()`.
- **Declarar a posteriori**: `useWorkPause` sondea las pausas cada 60 s y al
  recuperar el foco; si han pasado 30 min o más desde la última ranura, ese
  hueco no está ya cubierto y no se preguntó por él, aparece el banner
  `PauseQuestion` (no bloquea). Responder «fuera» hace
  `POST /api/worklog/pauses`; responder «trabajando» **no escribe nada**.
- **Borrar**: la lista del dashboard → `DELETE /api/worklog/pauses/{inicio}`.

## Reglas

- `pausar()` no toca la pausa abierta si ya hay una: pulsar dos veces no pierde
  el inicio real.
- `reanudar()` cierra en `ranura + 30 s` y nunca deja un fin anterior al
  inicio.
- Declarar una pausa es un UPSERT por `start`: volver a marcar el mismo inicio
  corrige, no duplica. El rango se valida (`end >= start`, si no 400).

## Trampas

- **Una pausa abierta no se cierra sola al leer.** Si nadie pulsa «vuelvo», ahí
  sigue.
- La pregunta se dispara por hueco desde la **última ranura**, no por hora del
  día: una tarde entera sin tocar el panel produce una sola pregunta.
- Los inicios se cuajan a ranura de 30 s también al borrar, así que el `start`
  que se manda tiene que ser el que devolvió la API, no el que se vio en
  pantalla.
