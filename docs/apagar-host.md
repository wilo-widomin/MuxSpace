# Apagar el ordenador host desde el panel

El panel corre en una máquina virtual. Con esta función, Willy puede apagar desde
el panel el ordenador donde esa máquina virtual vive. Apagar el host **apaga
también la máquina virtual y el panel**, y desde aquí no se puede volver a
encender: hay que hacerlo a mano en el ordenador.

## Cómo funciona

- En el host corre un servicio mínimo (`host-agent/`) que acepta **una sola
  orden**: `POST /poweroff` con un token. No ejecuta nada que venga en la
  petición; la orden de apagado es fija.
- El panel (`backend/host_poweroff.py`) llama a ese servicio cuando alguien con
  sesión abierta lo pide en **Ajustes** y escribe la palabra de confirmación.
- Cada intento queda en la auditoría (`audit.log`, acción `host-poweroff`) con
  quién, cuándo y el resultado.

El servicio solo responde a las direcciones que se le indican al instalarlo, exige
el token (comparado en tiempo constante) y guarda en el registro del sistema quién
lo ha llamado.

## Levantar

**En el host**, con el repositorio clonado y como administrador:

```sh
sudo bash host-agent/install.sh --allow-from <dirección-de-la-máquina-virtual>
```

`--allow-from` es obligatorio: solo esa dirección podrá pedir el apagado. Opcionales:
`--bind` (dónde escuchar; por defecto la dirección del host que ve a la máquina
virtual) y `--port` (por defecto, uno al azar que se conserva al reinstalar).

El instalador genera el token si no existe, lo imprime **una sola vez** y arranca
el servicio. Al terminar imprime las dos líneas para el panel.

**En la máquina virtual**, pega esas dos líneas en `backend/.env` (no se versiona):

```sh
MUXSPACE_HOST_POWEROFF_URL=<la que imprimió el instalador>
MUXSPACE_HOST_POWEROFF_TOKEN=<el token que imprimió el instalador>
```

y reinicia el backend: `systemctl --user restart proj-tmux`. Con las dos variables
puestas aparece en Ajustes la fila «Apagar el ordenador host». Con cualquiera
vacía, la función no existe y el botón no se muestra.

Comprobar sin apagar nada: en el host, `systemctl status muxspace-host-agent`, y
`journalctl -u muxspace-host-agent -f` para ver quién llama. Una petición con un
token equivocado debe dar 401, y no apaga.

## Desplegar

Actualizar el agente es repetir `install.sh` con el mismo `--allow-from`: copia el
programa nuevo, conserva el token y el puerto y reinicia el servicio. Para rotar el
token, borra `/etc/muxspace-host-agent/token`, repite `install.sh` y actualiza
`MUXSPACE_HOST_POWEROFF_TOKEN` en el panel.

## Revertir

- **Dejar de ofrecerlo en el panel**: quita las dos variables de `backend/.env` y
  reinicia el backend.
- **Quitar el agente del host**: `sudo bash host-agent/uninstall.sh` (borra el
  servicio, el programa y el token).

## Pruebas

`backend/tests/test_host_agent.py` y `backend/tests/test_host_poweroff.py`. El
agente se prueba contra un servidor local con la orden de apagado sustituida por
un registro; el panel, con el cliente sustituido. Ningún test apaga nada ni sale a
la red.
