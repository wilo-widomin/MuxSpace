---
name: alta-dispositivo
description: Da de alta un dispositivo nuevo (móvil, tablet, portátil) para que pueda abrir el panel de muxspace por HTTPS, y diagnostica por qué un dispositivo no entra. El panel está detrás de mTLS, así que cada aparato necesita DOS certificados distintos que se instalan por caminos distintos. Úsala cuando el usuario diga "no me deja entrar desde la tablet", "la conexión no es privada", "quiero entrar desde el móvil", "dar de alta un dispositivo", "instalar el certificado", "ERR_BAD_SSL_CLIENT_AUTH_CERT", o cuando haya que revocar un aparato perdido.
---

# Alta de un dispositivo en el panel

Documentación de fondo: `docs/mtls.md` (procedimiento publicable) y
`docs/mtls.local.md` (**el mismo con las IPs, rutas y contraseña reales** —
está en `.gitignore`; **léelo siempre antes de dar un comando concreto**, y
no copies nunca sus valores a un archivo versionado).

## Lo primero: diagnosticar por el síntoma

Hay **dos certificados independientes** y hacen falta los dos. Casi todos los
fallos salen de confundirlos:

| Síntoma en el dispositivo | Qué falta | Archivo |
| :--- | :--- | :--- |
| «La conexión no es privada» / `ERR_CERT_AUTHORITY_INVALID` | La **CA del dominio** | `rootCA.pem` del **host** |
| `ERR_BAD_SSL_CLIENT_AUTH_CERT`, o la página no carga sin preguntar nada | El **certificado de cliente** | `<nombre>.p12` de la VM |
| El navegador **pregunta qué certificado usar** | Nada: eso es lo correcto | — |

Los dos se instalan de todas formas en un alta nueva; el síntoma solo dice por
dónde empezar a mirar cuando algo ya estaba puesto.

**Trampa nº 1:** la CA del dominio es la de `mkcert` **del host**. La VM
también tiene `mkcert` instalado y su `rootCA.pem` es otra CA distinta que no
firma nada de esto. Si el usuario dice que ya instaló la CA y sigue el aviso,
lo más probable es que instalara la de la VM.

## Reparto del trabajo

- **En la VM** (esta máquina): emitir el certificado. Lo haces tú.
- **En el host**: reunir los archivos y servirlos. **Lo hace el usuario** —
  no entres por SSH al host, es una regla del despliegue.
- **En el dispositivo**: instalar. Lo hace el usuario; tú le das los pasos
  exactos de su sistema operativo.

Dile los tres pasos de golpe y marca cuáles son suyos, para que no tenga que
volver a preguntar entre uno y otro.

## 1. Emitir (VM)

```bash
cd ~/proyectos/muxspace
P12_PASS=<la contraseña de docs/mtls.local.md> ./scripts/mtls-client-cert.sh <nombre>
```

`<nombre>` en minúsculas y descriptivo (`tablet`, `movil-willy`). El script
falla a propósito si ese nombre ya existe: elige otro o borra el anterior.
Deja `.crt`, `.key` y `.p12` en `~/certs/muxspace-mtls/`. La CA se crea sola
la primera vez y **`ca.key` no sale nunca de la VM**.

Comprueba el certificado desde la VM antes de que el usuario se pelee con el
aparato — usa el par `.crt`/`.key`, **no** el `.p12` (los `.p12` legacy no los
lee `curl` con OpenSSL 3). El comando con los valores reales está en
`docs/mtls.local.md`; debe devolver 200.

## 2. Reunir y servir (host — pasos para el usuario)

Los dos archivos tienen que juntarse en el host, porque es la única máquina
que ve la LAN y la red interna a la vez:

```bash
scp <usuario>@<ip-vm>:~/certs/muxspace-mtls/<nombre>.p12 ~/
cp "$(mkcert -CAROOT)/rootCA.pem" ~/
cd ~ && python3 -m http.server 8765
```

**Recuérdale que corte el servidor al terminar**: sirve su `$HOME` entero a
la LAN.

## 3. Instalar (dispositivo)

**Android** — los dos certificados van por menús distintos, y el teléfono
necesita bloqueo de pantalla o se niega a guardar credenciales.
Ajustes → Seguridad → Cifrado y credenciales → Instalar un certificado:

1. `rootCA.pem` → **Certificado de CA**. Avisa de que «la red puede estar
   monitorizada»: es lo normal con una CA propia.
2. `<nombre>.p12` → **Certificado de VPN y apps**. **Trampa nº 2:** *no*
   «Certificado de Wi-Fi», que es el que varias capas de fabricante ofrecen
   por defecto y deja el certificado donde Chrome no lo ve.

**iOS/iPadOS**: instalar los dos perfiles (Ajustes → Perfil descargado) y
además **activar la confianza** de la CA en Ajustes → General → Información →
Ajustes de confianza de certificados. Sin ese interruptor el aviso sigue.

**Escritorio**: Chrome/Edge → Ajustes → Privacidad y seguridad → Seguridad →
Gestionar certificados → Tus certificados → Importar. Firefox tiene su propio
almacén: Ajustes → Privacidad & Seguridad → Certificados → Ver certificados.

## 4. Comprobar

Al abrir el panel el navegador **debe preguntar qué certificado usar**; se
elige una vez y queda recordado. Si no pregunta y falla directo, el `.p12` no
está en el almacén correcto (repetir el paso 2 de Android).

Después queda el **login del panel**: usuario y contraseña están en
`docs/mtls.local.md`. El mTLS y el login son capas distintas; que pase una no
significa que pase la otra.

## Certificados viejos que no funcionan en Android

Los `.p12` emitidos antes de agosto de 2026 son X.509 v1, sin extensiones:
valen en escritorio pero el almacén de Android nunca los ofrece. Si un
certificado antiguo no hace aparecer el selector, **reemítelo** con el script
actual (que ya emite v3 con `clientAuth`) en vez de investigar el dispositivo.

## Revocar un dispositivo

Con esta CA casera no hay CRL: borrar su `.crt`/`.p12`, regenerar la CA
(`rm ~/certs/muxspace-mtls/ca.*`, reemitir el resto de certificados) y
actualizar `ca.crt` en el host. Con pocos aparatos es un minuto, pero
**invalida a todos los demás**: avisa antes de tocarlo, y no lo hagas por
iniciativa propia.
