# Avisos de atención

Una sesión puede **reclamar** al usuario: un agente que espera una respuesta,
un script largo que ha terminado. El panel lo enseña como un punto ámbar que
late en el tile y en el sidebar, toca una campanilla corta y pone un contador
en el título de la pestaña. La marca se apaga cuando el usuario atiende esa
terminal.

No hay voz y no hay notificación del sistema. La voz se descartó porque tres
avisos seguidos se pisan y obligan a esperar a que terminen; la marca, en
cambio, dice lo mismo llegue una vez o diez. La notificación del sistema queda
pendiente: en el escritorio funcionaría, pero en Android no llega con el
navegador cerrado sin montar el panel como PWA.

## Cómo se marca

Desde dentro de la sesión, en el host:

```sh
scripts/muxspace-attention.sh "espera tu respuesta"
```

El script pregunta a tmux en qué sesión está (`tmux display-message -p '#S'`),
lee el secreto de `backend/data/attention_token` y hace un `POST` al backend
por su puerto local. La etiqueta es opcional y se recorta a 120 caracteres.

Como hook de Claude Code, en `.claude/settings.json` del proyecto:

```json
{
  "hooks": {
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/ruta/a/muxspace/scripts/muxspace-attention.sh 'Claude espera tu respuesta'"
          }
        ]
      }
    ]
  }
}
```

Variables que acepta el script: `MUXSPACE_URL` (por defecto
`http://127.0.0.1:8000`) y `MUXSPACE_TOKEN_FILE`.

## El secreto

Marcar exige el secreto de `backend/data/attention_token` (0600, generado
solo la primera vez) o una sesión del panel. El secreto **solo** autoriza a
marcar: no sirve para listar sesiones, ni para apagar marcas, ni para nada
más. Se rota borrando el fichero y reiniciando el backend.

El hook habla con el puerto local del backend y no con el dominio del panel:
delante hay mTLS y un script del host no tiene certificado de dispositivo.

## Por qué el estado vive en el servidor

Todo lo demás del grid es estado de cliente (ver `space_store`). Un aviso no:
es un hecho del servidor, y de ahí salen las dos cosas que se notan.

- **Sobrevive.** Si el tile está cerrado, si se recarga la página, o si el
  panel se abre media hora después, el aviso sigue ahí. Va en
  `GET /api/sessions`, junto al espacio y el proyecto de cada sesión.
- **Se apaga en todas partes.** Atenderlo en el portátil quita la marca
  también en la tablet, porque el pendiente era uno solo.

Los avisos viven **en memoria**: reiniciar el backend los borra, igual que
las sesiones de login. Resucitar la reclamación de un proceso que ya no
existe sería peor que perderla.

## Cómo llega al navegador

El listado de sesiones se sondea cada 8 s, pero ese sondeo **se para con la
pestaña oculta**, que es cuando hace falta enterarse. Por eso hay un
WebSocket aparte, `/api/events`, uno por pestaña y no por terminal: llega el
aviso aunque el tile esté cerrado y aunque el panel esté en segundo plano.

Ese bus no guarda nada. Quien no está conectado en el instante del evento se
entera con el siguiente sondeo: perder la conexión retrasa el aviso, nunca lo
pierde.

## Qué apaga la marca

Enfocar el tile o teclear en su terminal. **No** basta con que se vea: en un
grid de cuatro ventanas hay varias a la vista y verlas de refilón no es
atenderlas. También se puede apagar todo de golpe con
`DELETE /api/attention`.

## La campanilla

Se sintetiza en el navegador (`src/lib/chime.js`), sin fichero de audio: tres
notas ascendentes con su octava por encima, que es lo que le da timbre de
campana y lo que la hace oírse desde la habitación de al lado sin recurrir a
una onda cuadrada, que suena a alarma. Suena solo cuando la marca se
**enciende** —no al refrescarse—, nunca en la terminal
que ya tenía el foco, y como mucho una vez cada tres segundos.

El navegador no deja sonar hasta que el usuario ha tocado la página, así que
el audio se prepara con el primer clic o la primera tecla del panel. Si se
abre el panel y no se toca nada, la primera campanilla puede no sonar: la
marca visual sí aparece.
