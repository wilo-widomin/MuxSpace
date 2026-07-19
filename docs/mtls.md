# Acceso por certificado (mTLS)

Objetivo: que al panel solo se pueda llegar presentando un **certificado de
cliente** emitido por nuestra propia CA. Quien no lo tenga ni siquiera
completa el handshake TLS: no ve el login, ni la API, ni el WebSocket. La
fuerza bruta de contraseñas desaparece como categoría de ataque.

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
- **Android:** copiar el `.p12` → Ajustes → Seguridad → Instalar
  certificado → Certificado de usuario (VPN y apps).
- **iOS:** enviarse el `.p12` (AirDrop/Files) → Ajustes → Perfil
  descargado → Instalar.

Al entrar por primera vez el navegador pregunta qué certificado usar; se
elige una vez y queda recordado.

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
