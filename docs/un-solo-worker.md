# Un solo worker: por qué, y qué se descartó

> Estado: **vigente**. Decidido en US-023 (fase 5, deuda técnica).

MuxSpace corre con **un único proceso worker de uvicorn**. No es un default
que nadie tocó: es un requisito del diseño actual, y romperlo corrompe datos
sin dar ningún error.

## El porqué

Los tres stores del panel —`library_store`, `space_store` y `upload_store`—
persisten en un JSON plano que se **reescribe entero** en cada mutación
(read-modify-write). La exclusión mutua la da un `threading.Lock` por módulo,
que protege **entre hilos del mismo proceso** y no entre procesos.

Con dos workers, la secuencia es esta:

1. El worker A recibe "crear comando X". Lee `library.json` (10 comandos).
2. El worker B recibe "crear comando Y". Lee el mismo `library.json` (10).
3. A escribe 11 comandos: los 10 + X.
4. B escribe 11 comandos: los 10 + Y. **X desaparece.**

Ninguno de los dos locks se entera, porque cada uno vive en su proceso. No
hay excepción, no hay log, no hay 500: el usuario ve que su comando se creó y
al refrescar ya no está.

`auth.py` es todavía peor, porque el problema no es solo el lock: las
sesiones viven en un **diccionario en memoria**, y la memoria no se comparte
entre procesos. Con N workers:

- Quien hace login contra el worker A recibe **401** en la siguiente petición
  si el balanceo la manda al B, que no conoce ese token.
- El rate limit de login permite **N veces** los intentos configurados: cada
  worker lleva su propia cuenta de fallos.

Los intentos fallidos sí persisten en `data/login_failures.json`, así que ahí
reaparece además el mismo read-modify-write de los stores.

## Cómo se protege

Tres capas, porque una sola se salta sin enterarse:

1. **`start.sh`** pasa `--workers 1` explícito (aunque sea el default) y hace
   `unset WEB_CONCURRENCY`, para que quitarlo tenga que ser una decisión.
2. **Los docstrings** de `library_store`, `space_store`, `upload_store` y
   `auth` lo explican junto a su `Lock`. Es donde lo lee quien está a punto
   de romperlo; en el README no lo leería.
3. **Aviso en arranque**: `main.py` calcula los workers pedidos y, si son más
   de uno, emite un `warning` por el logger `uvicorn.error` explicando qué se
   va a corromper. Sale una vez por worker, y eso es deliberado: N copias del
   aviso son la señal de que hay N procesos peleándose por los mismos
   ficheros.

### Cómo se detecta el número de workers

`main._workers_configurados()` lee `sys.argv` (`--workers N`, `--workers=N`,
`-w N`) y, si no hay bandera, la variable `WEB_CONCURRENCY` —que uvicorn usa
como default (`uvicorn/config.py`)—.

Lo que **no** se usa, aunque sea lo primero que uno prueba, es
`multiprocessing.parent_process()`. Medido con uvicorn 0.x sobre este mismo
backend:

| Arranque | `parent_process()` | `argv` lleva la bandera | `WEB_CONCURRENCY` |
|---|---|---|---|
| `uvicorn app` (1 worker) | `None` | no | no |
| `uvicorn app --workers 2` | **no `None`** | **sí** | no |
| `WEB_CONCURRENCY=3 uvicorn app` | **no `None`** | no | **sí** |
| `uvicorn app --reload` (1 worker) | **no `None`** | no | no |

La última fila es la que descarta la vía fácil: `--reload` levanta el
servidor en un subproceso con **un** worker, así que `parent_process()`
avisaría de una corrupción que no existe cada vez que alguien desarrolla. La
bandera y la variable, en cambio, distinguen los cuatro casos.

El detalle que hace que `argv` funcione: uvicorn lanza los workers con
`spawn`, y `multiprocessing.spawn` **restaura el `sys.argv` del padre en el
hijo**, así que la bandera llega intacta al proceso que sirve las peticiones.

## La alternativa descartada: `fcntl.flock`

La forma canónica de arreglar esto de verdad es sustituir los
`threading.Lock` por un lock **de fichero** (`fcntl.flock` sobre el propio
JSON, o sobre un `.lock` al lado), que sí es visible entre procesos. Con eso
el panel escalaría a N workers sin corromper los stores.

**No se hace ahora**, y estas son las razones:

- **No hay problema que resolver.** El panel es de un solo usuario en una
  máquina personal. Un worker sirve de sobra: la carga son unas pocas
  peticiones por minuto y un refresco de sesiones cada 8 s.
- **No arreglaría `auth`.** Las sesiones en memoria seguirían sin compartirse
  entre procesos, así que aun con `flock` haría falta mover las sesiones a un
  almacén compartido (fichero, Redis…). Eso es un rediseño, no un candado.
- **Añade modos de fallo nuevos.** Un `flock` mal liberado —proceso que muere
  con el lock cogido en un NFS, timeouts— cuelga el panel; hoy no hay ninguna
  ruta que pueda colgarse así.
- **`flock` no es portable a Windows** y no funciona de forma fiable sobre
  NFS. Hoy el panel no depende de ninguna de las dos cosas y no conviene que
  empiece.

Si algún día hace falta más de un worker, el orden correcto es: (1) mover las
sesiones de `auth` a un almacén compartido, (2) `flock` en los tres stores,
(3) quitar el aviso de `main.py` y esta página. Hacer solo (2) da una falsa
sensación de seguridad y deja a los usuarios deslogueándose solos.
