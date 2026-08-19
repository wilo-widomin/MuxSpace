---
name: alta-dispositivo
description: Da de alta un dispositivo nuevo (móvil, tablet, portátil) para que pueda abrir el panel de muxspace por HTTPS, lista los dispositivos ya dados de alta, y diagnostica por qué uno no entra. El panel está detrás de mTLS y cada aparato necesita DOS certificados que se instalan por caminos distintos. Úsala cuando el usuario diga "no me deja entrar desde la tablet", "la conexión no es privada", "quiero entrar desde el móvil", "dar de alta un dispositivo", "instalar el certificado", "qué dispositivos tienen acceso", "ERR_BAD_SSL_CLIENT_AUTH_CERT", o cuando haya que revocar un aparato perdido.
---

# Alta de un dispositivo en el panel

## Cómo se comunica esto (lo más importante de esta skill)

El usuario **solo quiere saber qué tiene que hacer él**. Todo lo demás —cómo
funciona el mTLS, qué firma qué, por qué hacen falta dos certificados— le
sobra salvo que lo pida.

Reglas de la respuesta, sin excepciones:

1. **Haz primero tu parte, sin contarla.** Emite y verifica el certificado
   con las herramientas antes de escribir nada. Luego una sola línea de
   resultado: «Certificado de la tablet listo y probado.» Ni comandos de la
   VM, ni rutas, ni salidas de `openssl`.
2. **Después, solo sus pasos, numerados y en orden**, cada uno con el
   comando o el menú exacto que tiene que tocar. Nada de «ahora te toca a
   ti» repartido entre explicaciones.
3. **Un bloque por máquina** y di en el título dónde está: «En el host» /
   «En la tablet». Él no tiene por qué deducir dónde se ejecuta cada cosa.
4. **Nada de tablas comparativas, diagramas ni «trampa nº1»** en la
   respuesta. Esas trampas son para que TÚ no las cometas y para que le des
   el paso ya correcto: el aviso va inline y en una frase, donde se pisa.
5. **Frases cortas.** Si un paso necesita un párrafo de justificación, es
   que no está bien resumido.
6. **Termina con la señal de éxito**, una sola: qué debe ver cuando funciona.
7. Solo cuando algo falle, saca la parte de diagnóstico — y aun entonces,
   pregúntale el síntoma y dale **la mitad que falta**, no el alta entera.

Documentación de fondo: `docs/mtls.md` (publicable) y **`docs/mtls.local.md`**
(IPs, usuarios, dominio y contraseña reales; está en `.gitignore`). **Léelo
siempre antes de dar un comando concreto** y pon los valores reales ya
sustituidos en lo que le escribas: nunca le des un comando con `<placeholders>`
para que los rellene él. Y no copies esos valores a ningún archivo del repo.

## Ver quién tiene acceso

```bash
./scripts/mtls-devices.sh
```

Un dispositivo por línea, con fecha de alta, caducidad y estado. Enséñale la
tabla tal cual: ya está pensada para leerse.

- `v1-viejo` → certificado anterior a agosto de 2026: funciona en escritorio
  pero **el almacén de Android no lo ofrece nunca**. Si ese aparato falla,
  reemítelo en vez de investigar el móvil.
- Para poner nombres humanos («tablet: la Samsung del salón»), edita
  `~/certs/muxspace-mtls/notas.txt`, una línea `nombre: descripción`.

**Lo que no se puede saber desde aquí:** cuándo se conectó cada dispositivo
por última vez. El mTLS se corta en el Caddy del host y al panel solo le
llega HTTP plano, así que ese dato está en el log del host. No se lo
prometas; si lo pide, se resuelve añadiendo el subject del cliente al log
del Caddy del host, y eso lo tiene que hacer él.

## Reparto del trabajo

- **VM** (esta máquina): emitir y verificar el certificado. **Lo haces tú, y
  antes de responder.**
- **Host**: reunir los archivos y servirlos. Lo hace el usuario — **no entres
  por SSH al host**, es una regla del despliegue.
- **Dispositivo**: instalar. Lo hace el usuario, con los menús de SU sistema.
  Si no sabes si es Android o iPad, **pregúntalo antes** de escribir los
  pasos, en vez de darle los dos caminos.

## 1. Emitir (tu parte, en la VM)

```bash
cd ~/proyectos/muxspace
P12_PASS=<la contraseña de docs/mtls.local.md> ./scripts/mtls-client-cert.sh <nombre>
```

`<nombre>` en minúsculas y descriptivo (`tablet`, `movil-willy`). El script
falla a propósito si ya existe. Deja `.crt`, `.key` y `.p12` en
`~/certs/muxspace-mtls/`; **`ca.key` no sale nunca de la VM**.

Verifica antes de responder, con el par `.crt`/`.key` (**no** el `.p12`: los
legacy no los lee `curl` con OpenSSL 3). El comando con los valores reales
está en `docs/mtls.local.md` y debe devolver 200. Si no da 200, **no le
mandes instalar nada**: arréglalo tú primero.

## 2. Los pasos del usuario

Escríbeselos ya con sus valores reales, en dos bloques.

**En el host** — traer los dos archivos y servirlos a la LAN:

```bash
scp <usuario>@<ip-vm>:~/certs/muxspace-mtls/<nombre>.p12 ~/
cp "$(mkcert -CAROOT)/rootCA.pem" ~/
cd ~ && python3 -m http.server 8765
```

Añade, en una línea: que lo corte con Ctrl-C al terminar, porque sirve su
`$HOME` entero.

**En el dispositivo** — abrir `http://<ip-host>:8765/`, bajar los dos
archivos e instalarlos:

- **Android** — Ajustes → Seguridad → Cifrado y credenciales → Instalar un
  certificado. `rootCA.pem` como **Certificado de CA** (avisa de que «la red
  puede estar monitorizada»: normal). `<nombre>.p12` como **Certificado de
  VPN y apps** — dile en la misma línea que *no* elija «Wi-Fi», que es lo que
  ofrecen por defecto muchas capas de fabricante y deja el certificado donde
  Chrome no lo ve. Dale la contraseña del `.p12` ahí mismo. Necesita bloqueo
  de pantalla activo.
- **iOS/iPadOS** — instalar los dos perfiles desde Ajustes → Perfil
  descargado, y luego **activar la confianza** de la CA en Ajustes → General
  → Información → Ajustes de confianza de certificados. Ese interruptor es el
  que casi todo el mundo se salta.
- **Escritorio** — Chrome/Edge: Ajustes → Privacidad y seguridad → Seguridad
  → Gestionar certificados → Tus certificados → Importar. Firefox tiene su
  propio almacén: Ajustes → Privacidad & Seguridad → Certificados.

## 3. La señal de éxito

Al abrir el panel, el navegador **pregunta qué certificado usar**. Se elige
una vez y queda recordado. Luego, login con el usuario y la contraseña de
`docs/mtls.local.md`.

## Si algo falla: por el síntoma, no de nuevo desde el principio

Pregúntale **qué error exacto sale** y ataca solo lo que falta:

| Lo que ve | Lo que le falta |
| :--- | :--- |
| «La conexión no es privada» / `ERR_CERT_AUTHORITY_INVALID` | El `rootCA.pem`, y tiene que ser **el del host** — la VM tiene otro `mkcert` distinto que no sirve |
| `ERR_BAD_SSL_CLIENT_AUTH_CERT`, o falla sin preguntar nada | El `.p12`, o está en el almacén equivocado (Android: «Wi-Fi» en vez de «VPN y apps») |
| Pide usuario y contraseña | Nada: eso ya es el panel, mTLS superado |

## Revocar un dispositivo

Con esta CA casera no hay CRL: hay que borrar su `.crt`/`.p12`, regenerar la
CA y reemitir **todos** los demás certificados. **Avísale de que eso echa
fuera a todos los aparatos** y espera su confirmación antes de tocar nada.
Nunca por iniciativa propia.
