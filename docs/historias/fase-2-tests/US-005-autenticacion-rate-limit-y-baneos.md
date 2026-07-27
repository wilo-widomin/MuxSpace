# US-005 · Autenticación: rate limit, sesiones y baneos

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 5 | fase-2-tests | S1 |

## Historia

Como responsable del panel, quiero **tests sobre `auth.py`**, porque ahí
viven las tres piezas que aguantan un ataque de fuerza bruta contra la puerta
que da shell: el límite de intentos, la caducidad de sesiones y la lista
negra de IPs.

El módulo hace bien un par de cosas que suelen fallar —el rate limit se
persiste en disco (un reinicio no lo resetea) y cubre también la vía HTTP
Basic, que es el agujero clásico de este patrón—, así que el objetivo es
fijarlas.

## Criterios de aceptación

**Rate limit del login**:

- [ ] 5 fallos desde la misma IP en menos de 60 s → el sexto intento
      devuelve **429**, no 401.
- [ ] Pasados 60 s (con el tiempo simulado), la ventana se resetea y se
      vuelve a poder intentar.
- [ ] Un login **correcto** resetea el contador de la ventana, pero
      **conserva** el histórico (`total_failures`, `first_seen`,
      `last_seen`).
- [ ] El registro **sobrevive a recargar el módulo**: escribe fallos,
      `importlib.reload(auth)`, y el contador sigue ahí. Es lo que impide
      resetear el límite tirando el backend.
- [ ] **HTTP Basic incorrecto penaliza igual**: 5 peticiones a un endpoint
      autenticado con `Authorization: Basic` erróneo → la sexta da 429.
- [ ] Una petición **sin** credenciales no penaliza (no consume intentos).
- [ ] Al superar `_MAX_TRACKED_IPS`, se descartan las IPs de actividad más
      antigua y el archivo no crece sin límite.
- [ ] El archivo de fallos queda a **0600**.

**Sesiones**:

- [ ] Login correcto → cookie `muxspace_session` con `HttpOnly`,
      `SameSite=Lax` y `Secure`.
- [ ] Con la cookie, un endpoint autenticado responde 200.
- [ ] Sesión **expirada** (TTL vencido, con el tiempo simulado) → 401, y el
      token desaparece del registro en memoria.
- [ ] `logout` invalida el token: la misma cookie ya no vale.
- [ ] Un token inventado → 401.

**Baneo por IP**:

- [ ] `banned_ips.json` con una IP suelta bloquea a esa IP con **403** en
      HTTP.
- [ ] Una entrada **CIDR** (`198.51.100.0/24`) bloquea una IP de dentro del
      rango y deja pasar una de fuera.
- [ ] **Recarga en caliente**: cambiar el archivo (y su mtime) hace efecto
      sin reiniciar.
- [ ] JSON corrupto o a medio editar → se **conserva la lista anterior**, no
      se queda todo el mundo desbaneado.
- [ ] Entrada malformada en la lista → se ignora esa entrada, las demás
      siguen aplicando.
- [ ] El WebSocket también rechaza a una IP baneada (cierre 1008).

**Modo PAM**:

- [ ] En modo `pam`, un usuario distinto del usuario del backend se rechaza
      **sin llegar a llamar a PAM** (hay un `compare_digest` previo).
      Simula el módulo `pam`; no valides contra el sistema real.

## Alcance técnico

- `backend/tests/test_auth.py`.
- El tiempo se controla con `monkeypatch.setattr(auth.time, "time", ...)` o
  con `freezegun` si se añade a `requirements-dev.txt`. Prefiere el
  monkeypatch: una dependencia menos.
- Las rutas `_FAILURES_PATH` y `_BANNED_PATH` apuntan a `tmp_path`
  (conftest de US-001).
- Para el mtime de `banned_ips.json`, escribe y fuerza un mtime distinto con
  `os.utime`: dos escrituras en el mismo segundo pueden dar el mismo mtime y
  el test saldría inestable.
- Para PAM, `monkeypatch` sobre el import diferido dentro de `_pam_verify`.

## Fuera de alcance

- Que toda ruta exija autenticación (US-002).
- Validar PAM contra el sistema real: el despliegue lo hace su dueño, no el
  CI.
- Cambiar `auth.py`. Si un caso falla, **para y avisa**.
- El TTL deslizante y `/api/logout-all`: son US-020, de la fase 5.

## Dependencias

US-001.

## Rigor

`exhaustivo`.

## Concurrencia

`compartida`. Solo crea `test_auth.py`.

## Notas para el agente

- El test de **persistencia entre recargas** es el que más valor tiene: es
  la propiedad menos obvia del módulo y la que un refactor "para
  simplificar" se lleva por delante.
- Cuidado con el estado global entre tests: `auth._login_failures` y
  `auth._sessions` son diccionarios de módulo. Limpia en un fixture o los
  tests se contaminan entre sí y fallarán en otro orden.
- Objetivo de cobertura para `auth.py`: **≥85%**.
