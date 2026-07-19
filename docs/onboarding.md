# Onboarding — MuxSpace en 5 minutos

Guía para recién llegados (o para ti mismo en otra máquina): clonar el
repo y tener el panel funcionando en local. Si buscas el porqué del
diseño, mira [`muxspace.md`](muxspace.md); la referencia de la API
está en el [`README.md`](../README.md).

## 0. Qué vas a obtener

Un único proceso que sirve, en **un puerto local**, una web con:

- El catálogo de tus sesiones de tmux y un *grid* de terminales en vivo.
- Una biblioteca de **comandos** y **proyectos** reutilizables.

El panel no crea un servidor tmux mágico: usa **tu** servidor tmux (el del
usuario que arranca el backend). Por eso las sesiones que veas son las
**tuyas**.

## 1. Requisitos

| Requisito | Por qué | Cómo instalarlo |
|-----------|---------|-----------------|
| `tmux` | El panel lo controla | `apt install tmux` / `dnf install tmux` / `pacman -S tmux` |
| `python3` (3.10+) | Backend | `apt install python3 python3-venv` / `dnf install python3` / … |
| `node` 18+ + `npm` | Solo si hay que compilar el frontend | `apt install nodejs npm` / NodeSource / `nvm` |

> En Debian/Ubuntu hace falta el paquete `python3-venv` además de
> `python3` (sin él, `python3 -m venv` falla).

Comprueba rápido:

```bash
tmux -V && python3 --version && (command -v npm && npm -v) || true
```

## 2. Clonar y configurar

```bash
git clone <url-del-repo> muxspace
cd muxspace

# Configuración: copia la plantilla genérica y edítala si quieres
cp backend/.env.example backend/.env
```

`backend/.env` es lo único específico de tu máquina (está fuera de git).
Valores por defecto suficientes para local: `127.0.0.1:8000`, usuario
`admin`, raíces de directorios `["~"]`. **Tienes que poner una contraseña**
en `MUXSPACE_PASSWORD` (`openssl rand -base64 24`): el backend no arranca
si la dejas vacía o en `admin`, porque el panel da acceso a una shell.

## 3. Arrancar

```bash
./start.sh
```

`start.sh` hace todo: verifica prerequisitos, crea el venv, instala las
deps de Python, compila el frontend si falta y arranca uvicorn sirviendo
**API + frontend** en `http://127.0.0.1:8000`.

Abre <http://127.0.0.1:8000> y entra con `admin` y la contraseña que
pusiste en `backend/.env`.

## 4. Tu primera sesión

El panel lista las sesiones que **ya existan** en tu tmux. Crea una para
probar, desde tu terminal habitual:

```bash
tmux new -d -s trabajo          # sesión detached
```

Pulsa *Recargar* en el panel (o espera al refresco de 8 s): aparecerá
**trabajo** en el sidebar. Haz clic y se abre en el grid con una terminal
xterm.js en vivo. Escribe ahí como en tu terminal.

- La **X** del tile retira la vista (la sesión de tmux sigue viva).
- **Cerrar / Destruir** desde el menú de la sesión sí termina la sesión.

## 5. Biblioteca: comandos y proyectos

- **Comando** = una línea de shell. Ej.: `htop` o `cd ~/proyectos/x && nvim`.
  Guárdalo en el sidebar (sección *Comandos*) y lánzalo con un clic: abre
  una sesión nueva llamada como su *label* (con sufijo ` (N)` si ya existe).
- **Proyecto** = título + directorio + secuencia de comandos. Ej.
  `demo`, `~/proyectos/api`, `["npm install", "npm run dev"]`. Al
  *ejecutarlo* crea una sesión, hace `cd <cwd>` y lanza los comandos en
  orden dentro del mismo shell.

Tanto comandos como proyectos se guardan en `backend/data/*.json` y
sobreviven a reinicios del backend.

## 6. Copia al portapapeles

- Seleccionar con el ratón + `Ctrl/Cmd+C` copia; `Ctrl/Cmd+V` (o clic
  central) pega.
- Si una app dentro de tmux (vim, etc.) fija el portapapeles por **OSC
  52**, también llega al del sistema. El backend activa `allow-passthrough
  on` y `set-clipboard on` en cada sesión (ignora errores en tmux viejos).

## 7. Desarrollo (opcional)

Si vas a tocar frontend y quieres HMR:

```bash
./scripts/dev.sh
```

Backend en `:8000` (docs en `/docs`) y Vite en `:5173` (con proxy de
`/api` al backend). Tras cambios de UI en producción, recompila:
`cd frontend && npm run build`.

## 8. Mantenerlo arrancado (opcional)

Para que sobreviva a reinicios, envuélvelo en un servicio de systemd de
usuario. Ejemplo mínimo `~/.config/systemd/user/proj-tmux.service`:

```ini
[Unit]
Description=MuxSpace
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/proyectos/muxspace
Environment=PATH=/home/<tu-usuario>/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/proyectos/muxspace/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now proj-tmux.service
journalctl --user -u proj-tmux.service -f   # ver logs
```

Para exponerlo al exterior con TLS, pon un *reverse proxy* (Caddy/Nginx)
delante; entonces usa `MUXSPACE_HOST=0.0.0.0` en el `.env`. Eso queda
fuera del alcance del propio panel.

## 9. Troubleshooting

| Síntoma | Causa / solución |
|---------|------------------|
| `Falta dependencia: tmux` | Instala `tmux` (tabla de requisitos). |
| `ModuleNotFoundError` al crear el venv | En Debian/Ubuntu falta `python3-venv`: `apt install python3-venv`. |
| El puerto 8000 está ocupado | Edita `MUXSPACE_PORT` en `backend/.env` o para lo que lo use. |
| No puedo acceder desde otro PC | Por defecto el backend enlaza a `127.0.0.1`. Usa `0.0.0.0` (+ proxy) solo si lo necesitas. |
| El panel no ve mis sesiones | El backend corre como tu usuario; usa el mismo `tmux`. Si lo arranca otro usuario, verá **sus** sesiones, no las tuyas. |
| La terminal no se redimensiona | Se ajusta al tile al abrir y al mover; comprueba que el tile tiene tamaño y que tu tmux ≥ 3.3 para el *passthrough* del portapapeles. |
| No puedo copiar/pegar | La copia con `navigator.clipboard` requiere contexto seguro: `http://localhost`/`127.0.0.1` o HTTPS. Por IP cruda en HTTP no funciona. |
| Cambios en `.env` no aplican | Reinicia el backend; las variables se leen al arrancar. |
| Quiero resetear la biblioteca | Borra `backend/data/*.json` (se recrean vacíos). |

## 10. Dónde seguir

- Arquitectura y alcance: [`muxspace.md`](muxspace.md)
- Referencia de endpoints: [`README.md`](../README.md#api)
- Código de entrada: `backend/main.py` (API) y `frontend/src/App.jsx` (UI).