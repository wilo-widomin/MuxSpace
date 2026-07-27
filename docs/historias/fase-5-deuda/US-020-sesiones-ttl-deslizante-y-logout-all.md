# US-020 · Sesiones: TTL deslizante de 24 h y `POST /api/logout-all` (S10)

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 3 | fase-5-deuda | S2 |

## Historia

Como responsable del panel, quiero **caducidad por inactividad y una forma de
revocar todas las sesiones**, porque hoy el TTL es de 7 días fijos, no hay
límite de sesiones concurrentes y la única manera de invalidarlas todas es
reiniciar el backend.

## Criterios de aceptación

**TTL deslizante**:

- [ ] La sesión caduca a las **24 h de inactividad**, no 168 h desde el
      login. Cada petición autenticada renueva la ventana.
- [ ] El valor sale de configuración (`MUXSPACE_SESSION_IDLE_HOURS`, default
      24) y está documentado en `.env.example`.
- [ ] Se mantiene un **tope absoluto**: por muy activa que esté, una sesión
      no vive más allá de `MUXSPACE_SESSION_TTL_HOURS`. Renovar sin techo
      convierte una cookie robada en permanente.
- [ ] La cookie del navegador se re-emite con el `Max-Age` actualizado, o se
      documenta explícitamente por qué no hace falta.
- [ ] Tests con tiempo simulado: actividad dentro de la ventana mantiene la
      sesión viva; 24 h sin actividad → 401; el tope absoluto corta aunque
      haya actividad continua.

**Revocación global**:

- [ ] `POST /api/logout-all` invalida **todas** las sesiones, incluida la de
      quien la llama.
- [ ] Exige autenticación (y por tanto sale en la lista de US-002 como ruta
      protegida).
- [ ] Test: dos sesiones activas, una llama a `logout-all`, las dos quedan
      en 401.
- [ ] Documentado en el README: para qué sirve y cuándo usarlo (sospecha de
      cookie comprometida).

**Frontend**:

- [ ] Hay una forma de invocarlo desde el panel, o se documenta que es un
      endpoint de emergencia para `curl`. Decide y **justifícalo en el PR**;
      lo que no vale es un endpoint que nadie sabe que existe.
- [ ] Si añades UI, sus cadenas van en los 6 idiomas.

## Alcance técnico

- `backend/auth.py`: la estructura de sesión pasa a guardar
  `(username, expira_absoluto, ultimo_uso)`.
- `backend/main.py`: endpoint nuevo.
- `backend/config.py` y `backend/.env.example`.
- Tests en `backend/tests/test_auth.py`.

## Fuera de alcance

- Persistir las sesiones en disco. Viven en memoria a propósito: un
  reinicio obliga a volver a entrar, y para un panel personal está bien.
- Límite de sesiones concurrentes (el análisis lo menciona, el plan no lo
  pide).
- 2FA o cualquier otro factor.

## Dependencias

US-005.

## Rigor

`exhaustivo`. Toca el camino de autenticación del panel en producción: un
fallo aquí deja al usuario fuera o deja sesiones vivas de más.

## Concurrencia

`exclusiva` respecto a cualquier otra US que toque `auth.py`.

## Notas para el agente

- El **tope absoluto** es la parte que se olvida. Un TTL deslizante sin
  techo es peor que el TTL fijo que sustituye.
- El despliegue real usa PAM y `SESSION_TTL_HOURS=168`. Bajar la
  inactividad a 24 h significa que el dueño va a volver a hacer login más a
  menudo: dilo en el PR, es un cambio de comportamiento observable.
