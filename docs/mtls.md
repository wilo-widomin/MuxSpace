# Acceso por certificado (mTLS)

Objetivo: que al panel solo se pueda llegar presentando un **certificado de
cliente** emitido por nuestra propia CA. Quien no lo tenga ni siquiera
completa el handshake TLS: no ve el login, ni la API, ni el WebSocket. La
fuerza bruta de contraseñas desaparece como categoría de ataque.

> **¿Solo quieres conectar un dispositivo nuevo?** Salta a [Alta de un
> dispositivo nuevo](#alta-de-un-dispositivo-nuevo). El resto del documento
> es el montaje inicial, que ya está hecho.

## Los dos certificados que no hay que confundir

Casi todos los fallos al dar de alta un dispositivo salen de mezclar estas
dos cosas, que son independientes y viajan por caminos distintos:

| | **CA del dominio** | **Certificado de cliente** |
| :--- | :--- | :--- |
| Para qué | Que el navegador se fíe del `https://` | Que el proxy te deje pasar |
| Quién lo emite | Quien firme el cert del servidor (aquí `mkcert`, **en el host**) | Nuestra CA de mTLS, en la VM |
| Archivo | `rootCA.pem` (público) | `<dispositivo>.p12` (contiene clave privada) |
| Si falta | «El sitio no es seguro» | `ERR_BAD_SSL_CLIENT_AUTH_CERT` |

Ninguno sustituye al otro: **hacen falta los dos**. Y la CA del dominio es
la del **host**, no la de la VM — si la VM también tiene `mkcert`
instalado, su `rootCA.pem` es otra CA distinta que no firma nada de esto.

## Alta de un dispositivo nuevo

### 1. Emitir el certificado (en la VM)

```bash
./scripts/mtls-client-cert.sh <nombre-dispositivo>
```

Deja `<nombre-dispositivo>.p12` en `~/certs/muxspace-mtls/`, protegido con
la contraseña de exportación que te pida.

### 2. Reunir los dos archivos

- **`<nombre>.p12`** — el que acabas de emitir, en la VM.
- **`rootCA.pem`** — en el **host**, dentro de la ruta que devuelve
  `mkcert -CAROOT` allí.

Junta los dos en la misma máquina. Si el dispositivo está en la LAN y la
VM no (caso típico: la VM vive en una red interna detrás del host), el
punto de reunión tiene que ser **el host**, porque es el único que ve las
dos redes:

```bash
# En el host
scp <usuario>@<ip-de-la-vm>:~/certs/muxspace-mtls/<nombre>.p12 ~/
cp "$(mkcert -CAROOT)/rootCA.pem" ~/
```

### 3. Pasarlos al dispositivo

Cable, correo, o un servidor de usar y tirar en el host:

```bash
cd ~ && python3 -m http.server 8765   # abrir http://<ip-del-host>:8765/
```

**Córtalo en cuanto termines**: sirve el `$HOME` entero a la LAN.

### 4. Instalar

Ver [Instalar el `.p12` en cada dispositivo](#3-instalar-el-p12-en-cada-dispositivo)
más abajo — el camino cambia bastante según el sistema, y el de Android
tiene trampa.

### 5. Comprobar

Al abrir el panel, el navegador **debe preguntar qué certificado usar**.
Si no pregunta y falla directamente, el certificado de cliente no está
donde el navegador lo busca.

Para comprobar desde la VM que un certificado recién emitido es válido de
verdad, sin depender del dispositivo:

```bash
curl --resolve <dominio>:443:<ip-del-host> -k \
     --cert <nombre>.crt --key <nombre>.key https://<dominio>/
```

Debe devolver 200. Usa el par `.crt`/`.key`, no el `.p12`: los `.p12` en
formato legacy no los lee `curl` con OpenSSL 3.

## Dónde se aplica

El mTLS se verifica **donde se termina TLS**. En este despliegue:

```
navegador ──HTTPS──▶ Caddy del HOST (<ip-del-host>)   ◀── aquí va el mTLS
                        │ HTTP
                        ▼
                     Caddy de la VM (:80, sin TLS)
                        │ HTTP
                        ▼
                     backend uvicorn (:8000)
```

El Caddy de esta VM sirve `http://` plano (el TLS lo maneja el host), así
que el bloque `client_auth` hay que ponerlo en el **Caddyfile del host**.

## 1. Generar la CA y los certificados de dispositivo

En esta VM (la CA vive en `~/certs/muxspace-mtls/`, fuera del repo):

```bash
# Un certificado por dispositivo; la CA se crea sola la primera vez.
./scripts/mtls-client-cert.sh mi-portatil
./scripts/mtls-client-cert.sh mi-movil
```

Produce `ca.crt` (público, para el proxy) y `<nombre>.p12` (clave +
certificado del dispositivo, protegido con la contraseña de exportación
que pidas). **`ca.key` no sale nunca de esta máquina**: con ella se emiten
certificados válidos.

## 2. Configurar el Caddy del host

Copia la CA pública al host y añade `client_auth` al site del panel:

```bash
scp ~/certs/muxspace-mtls/ca.crt root@<ip-del-host>:/etc/caddy/muxspace-ca.crt
```

En el Caddyfile del host, dentro del site `panel.example.com` (dejando
el `reverse_proxy` hacia esta VM tal y como esté):

```caddyfile
panel.example.com {
    tls {
        client_auth {
            mode require_and_verify
            trusted_ca_cert_file /etc/caddy/muxspace-ca.crt
        }
    }
    reverse_proxy <ip-de-esta-vm>:80
}
```

Y recargar: `caddy reload --config /etc/caddy/Caddyfile` (o el path que use).

Desde ese momento, `https://panel.example.com` rechaza la conexión a
cualquier cliente sin certificado de nuestra CA. El resto de sites del
host no se ven afectados.

## 3. Instalar el .p12 en cada dispositivo

- **Chrome/Edge (Linux):** Ajustes → Privacidad y seguridad → Seguridad →
  Gestionar certificados → Tus certificados → Importar el `.p12`.
- **Firefox:** Ajustes → Privacidad & Seguridad → Certificados → Ver
  certificados → Sus certificados → Importar.
- **iOS:** enviarse el `.p12` (AirDrop/Files) → Ajustes → Perfil
  descargado → Instalar.

Al entrar por primera vez el navegador pregunta qué certificado usar; se
elige una vez y queda recordado.

### Android

Android necesita **dos** certificados distintos, y se instalan por
caminos distintos. Si falta el primero el navegador avisa de que el
dominio no es de fiar; si falta el segundo el handshake muere con
`ERR_BAD_SSL_CLIENT_AUTH_CERT`.

El teléfono debe tener **bloqueo de pantalla** (PIN, patrón o huella):
sin él Android se niega a guardar credenciales.

1. **La CA que firma el certificado del dominio** (la de quien emite el
   cert del servidor en el host — con `mkcert`, el `rootCA.pem` que
   devuelve `mkcert -CAROOT` **en el host**, no en la VM).
   Copiar al teléfono y: Ajustes → Seguridad → Más ajustes de seguridad →
   Cifrado y credenciales → Instalar un certificado → **Certificado de
   CA**. Android avisa de que «la red puede estar monitorizada»: es
   normal con una CA propia. Chrome sí confía en las CA instaladas por el
   usuario.

2. **El `.p12` del dispositivo** (el que emite este script): mismo menú →
   Instalar un certificado → **Certificado de VPN y apps**. Ojo: *no*
   «Certificado de Wi-Fi», que es el que ofrece por defecto en varias
   capas de fabricante y deja el certificado donde Chrome no lo ve.

Después, al abrir el panel, Chrome debe preguntar qué certificado usar.
**Si no pregunta y falla directamente, el `.p12` no está en el almacén
correcto**: repetir el paso 2.

El certificado de cliente tiene que ser **X.509 v3 con `clientAuth`**
(este script ya los emite así). Los `.p12` emitidos antes de agosto de
2026 eran de versión 1, sin extensiones: funcionan en escritorio pero
Android no los ofrece nunca. Si el teléfono no muestra el picker con un
certificado antiguo, reemítelo con este script.

## 4. ¿Y la contraseña del panel?

Con el mTLS activo puedes desactivar el login
(`MUXSPACE_AUTH_ENABLED=false` en `backend/.env`), **pero solo si antes
cierras los caminos que se saltan el proxy del host**, porque el mTLS
protege únicamente el camino HTTPS:

1. **El backend escucha en `0.0.0.0:8000`**: cualquiera de la LAN puede
   atacar `http://<ip-vm>:8000` directamente. Cambia a
   `MUXSPACE_HOST=127.0.0.1` (el Caddy de la VM le llega por localhost).
2. **El Caddy de la VM escucha en `:80` para toda la LAN**: restringe el
   site del panel al host con un matcher de IP en el Caddyfile de la VM:

   ```caddyfile
   http://panel.example.com {
       @fromhost remote_ip <ip-del-host>
       handle @fromhost {
           reverse_proxy localhost:8000
       }
       respond 403
   }
   ```

Hasta que esos dos puntos estén cerrados, deja `AUTH_ENABLED=true`: el
certificado controla quién llega desde fuera y la sesión sigue cubriendo
la LAN. (Mantener ambos tampoco es mala opción permanente: algo que
tienes + algo que sabes.)

## Revocar un dispositivo

La forma simple con esta CA casera: borrar su `.crt`/`.p12`, regenerar la
CA (`rm ~/certs/muxspace-mtls/ca.*` y volver a emitir el resto de
certificados) y actualizar `ca.crt` en el host. Con pocos dispositivos es
un minuto; si algún día hay muchos, se monta una CRL o se pasa a `step-ca`.
