---
dominio: jornada
accion: pausas
actualizado: 2026-08-29
archivos:
  - backend/worklog.py
  - backend/main.py
  - frontend/src/useWorkPause.js
  - frontend/src/useGapQuestion.js
  - frontend/src/components/GapQuestion.jsx
  - frontend/src/components/Dashboard.jsx
---

# Pausas y ausencias

Hay dos formas de que un rato no cuente, y la diferencia es quién lo decide:

- **La ausencia** la deduce el servidor: un hueco sin ninguna señal más largo
  que `WORKLOG_ABSENCE_MIN` (30 min) no se cuenta. Nadie declara nada. El
  panel puede avisar de ese descuento, pero solo si se le enciende el
  interruptor (ver abajo): por defecto está callado.
- **La pausa** la declara el usuario, y cubre lo que el umbral no ve: la
  ausencia corta. Solo tiene sentido en modo `workday`, así que sus controles
  solo aparecen en ese modo.

## Flujos

- **Me voy / vuelvo**: botón del sidebar → `useWorkPause.js` →
  `POST /api/worklog/pause` y `/resume` → `worklog.pausar()` / `reanudar()`.
- **Declarar a posteriori**: `POST /api/worklog/pauses` desde el dashboard.
- **Borrar**: la lista del dashboard → `DELETE /api/worklog/pauses/{inicio}`.
- **Ver y recuperar ausencias**: `GET /api/worklog/gaps` las lista (derivadas,
  no guardadas); `POST /api/worklog/gaps` responde a una (`worked` decide si
  vuelve a contar) y `DELETE /api/worklog/gaps/{inicio}` borra la respuesta.
  Lo que se guarda es la **respuesta** (`work_claims`), no la ausencia: las
  ausencias son la norma y se deducen solas.
- **La pregunta en caliente**: `useGapQuestion.js` sondea los huecos sin
  responder cada 60 s y al recuperar el foco, y enseña `GapQuestion` con el
  más reciente. Contestar hace `POST /api/worklog/gaps`; «no preguntar más»
  apaga el interruptor.

## Reglas

- `pausar()` no toca la pausa abierta si ya hay una: pulsar dos veces no pierde
  el inicio real.
- `reanudar()` cierra en `ranura + 30 s` y nunca deja un fin anterior al
  inicio.
- Declarar una pausa es un UPSERT por `start`: volver a marcar el mismo inicio
  corrige, no duplica. El rango se valida (`end >= start`, si no 400).

## El interruptor de la pregunta

Vive en `localStorage` (`muxspace.worklog.preguntar`), **apagado por defecto**:
interrumpir es algo que hay que pedir. Se enciende en el dashboard y se apaga
también desde el propio banner. Es preferencia por aparato a propósito — la
tableta de la mesa no tiene por qué interrumpir como el portátil.

Dos reglas lo mantienen fuera del ruido:

- **Pregunta solo la ventana con el foco** (`document.hasFocus()`). Con cuatro
  ventanas abiertas, el mismo banner en todas es la misma pregunta cuatro
  veces.
- **La respuesta es del servidor, no de la pestaña.** Por eso el «estaba
  fuera» también se guarda (`worked = 0`) aunque no cambie ningún total: sin
  esa fila, contestar en una ventana no serviría en la siguiente.

## Trampas

- **Una pausa abierta no se cierra sola al leer.** Si nadie pulsa «vuelvo», ahí
  sigue.
- Los inicios se cuajan a ranura de 30 s también al borrar, así que el `start`
  que se manda tiene que ser el que devolvió la API, no el que se vio en
  pantalla. Vale igual para reclamar un hueco: el `start` es el de la API.
- Una ausencia **nunca borra tiempo medido**: por definición, dentro de un
  hueco «sin ninguna señal» no hay señal que borrar. Por eso el descuento es
  seguro aunque el umbral se afine.
- Ignorar la pregunta no pierde nada: el hueco sigue descontado y se puede
  recuperar luego desde el dashboard. Por eso el banner no bloquea.
- La noche entre dos días no es una ausencia: `_ausencias` solo mira huecos
  dentro de un mismo día local, y para eso necesita el `tz` del cliente.
