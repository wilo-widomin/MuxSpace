# US-002 · Contrato de autenticación sobre todas las rutas

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 3 | fase-2-tests | S1 |

## Historia

Como responsable del panel, quiero que **sea imposible añadir un endpoint
`/api` sin autenticación por descuido**, porque en un panel que da shell el
control de acceso es el 100% del perímetro y no hay una segunda línea que
limite el daño.

Hoy la cobertura es correcta: recorriendo `app.routes`, las únicas rutas
`/api` sin `require_auth` son `health`, `login` y `logout`. Este test no
arregla nada — existe para que siga siendo verdad con el endpoint número 40.
Es el test más importante de la fase 2.

## Criterios de aceptación

- [ ] Un test recorre `app.routes` y, para toda `APIRoute` cuyo `path`
      empiece por `/api`, exige `require_auth` entre las dependencias, salvo
      la lista explícita `{"/api/health", "/api/login", "/api/logout"}`.
- [ ] El mensaje de fallo **nombra la ruta culpable** (`f"{r.path} sin
      autenticación"`), no un `assert` mudo.
- [ ] La lista de rutas públicas está definida como constante visible en el
      test: ampliarla tiene que ser un cambio consciente y revisable en el
      diff.
- [ ] Un segundo test recorre **las rutas reales con `TestClient`** sin
      cookie ni cabecera `Authorization` y exige **401** en todas las no
      públicas. Cubre el caso de que `require_auth` esté declarado pero no
      llegue a aplicarse.
- [ ] Ese recorrido usa el método correcto de cada ruta y sustituye los
      parámetros de path por valores de relleno; un 404 o un 422 **no**
      cuentan como aprobado (solo 401).
- [ ] Un tercer test comprueba el **WebSocket** `/api/terminal/{name}` sin
      cookie: cierre con código **1008**.
- [ ] Los tres tests corren con la autenticación **activada**
      (`MUXSPACE_AUTH_ENABLED=true`), que es el estado que el despliegue va a
      tener a partir de la fase 0.2.
- [ ] Un test comprueba que `/api/health` sigue respondiendo 200 sin
      credenciales (si no, el healthcheck del despliegue se rompe en
      silencio).
- [ ] **Prueba de que el test muerde**: quita temporalmente `_auth` de un
      endpoint y verifica que los tests fallan. Deja constancia en el PR; no
      dejes el cambio.

## Alcance técnico

- `backend/tests/test_auth_contract.py`.
- `from fastapi.routing import APIRoute` y `r.dependant.dependencies`, con
  `d.call.__name__` para localizar `require_auth`.
- Ojo: hay rutas que **no** son `/api` (el `StaticFiles` montado en `/`) y
  rutas `/api` que son WebSocket (`APIWebSocketRoute`, no `APIRoute`): el
  WebSocket se cubre con su propio test, no con el recorrido de `app.routes`.
- Para el WebSocket, `TestClient.websocket_connect` lanza
  `WebSocketDisconnect`; comprueba `exc.code == 1008`.

## Fuera de alcance

- Probar la lógica interna de `auth.py` (rate limit, sesiones, baneos): eso
  es US-005.
- El guard de Origin/CSRF (se cubre donde toca en US-004).
- Cambiar el código de producción. Si el test encuentra una ruta sin
  proteger, **para y avisa**: es un hallazgo de seguridad, no un arreglo
  que se cuela en el PR de un test.

## Dependencias

US-001.

## Rigor

`exhaustivo`. Es el test que sostiene el perímetro entero.

## Concurrencia

`compartida`. Solo crea `test_auth_contract.py`.

## Notas para el agente

- El valor de esta US está en **el día que alguien añada el endpoint 40**.
  Escribe el test para ese momento: que el fallo se lea solo y diga qué
  ruta falta.
- No uses una lista blanca "por prefijo" (`/api/pub/*`). Rutas concretas,
  enumeradas.
- El recorrido con `TestClient` es el que de verdad prueba el
  comportamiento; el de `app.routes` es el que da un mensaje legible. Los
  dos, no uno.

## Registro de ejecución

> Generado por `servidor-pipeline`. Tiempos de la última ejecución.

- Inicio: 2026-07-27 14:49:29 UTC
- Fin:    2026-07-27 15:09:51 UTC
- Tiempo transcurrido: 00:20:22 (HH:mm:ss)
- PR:     #4
- Estado: in-review
