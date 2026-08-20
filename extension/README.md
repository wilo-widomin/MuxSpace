# Extensión de navegador

Abre un proyecto de MuxSpace como **grupo de pestañas**: el panel en el
espacio del proyecto a la izquierda del todo, y detrás los enlaces que ese
proyecto tenga guardados. Si el grupo ya existe, no crea otro: te lleva a él
y abre solo lo que falte.

## Cómo llega a los proyectos

**La extensión nunca habla con el backend.** El panel está detrás de un
certificado de cliente y de una cookie de sesión que pertenecen a la pestaña,
no a la extensión. Así que quien pide `/api/projects` es **siempre una
pestaña del panel**: la extensión inyecta la petición en una que ya tengas
abierta —sin tocarla— o abre una, pregunta y la reutiliza como pestaña del
grupo.

De ahí sale el único permiso que pide: leer la dirección de tu panel. No está
en el manifiesto para «todos los sitios»; se pide en las opciones, solo para
la dirección que escribas, y Chrome te lo confirma en ese momento.

La dirección **no está en el repositorio** y no puede estarlo: es la red de
quien usa el panel. Se escribe en las opciones y se guarda en el navegador.

## Instalar

1. `chrome://extensions` → activar **Modo de desarrollador**.
2. **Cargar descomprimida** → elegir esta carpeta (`extension/`).
3. Abrir las **opciones** de la extensión y escribir la dirección del panel.
   Chrome pedirá permiso para esa dirección: hay que concederlo.

## Usar

Pinchar el icono y elegir un proyecto. Se abre su grupo.

El popup pinta la lista guardada de la última vez y en paralelo se la vuelve
a pedir al panel, así que la primera vez tarda lo que tarde en responder.

## Revertir

Quitar la extensión en `chrome://extensions`. No deja nada en el panel: todo
lo que guarda —la dirección, la copia de la lista de proyectos y a qué grupo
fue cada uno— vive en el almacenamiento de la extensión y se va con ella.

## Navegadores

Chrome y Edge. Es Manifest V3, así que Brave debería ir igual, y Firefox
necesitaría un manifiesto propio.

## Desarrollo

```sh
cd extension
bun install
bun run test
```

Las pruebas cubren la lógica que no necesita navegador: normalizar la
dirección del panel, decidir qué pestañas le tocan a un grupo y cuáles ya
están abiertas. Lo que habla con Chrome (`background.js`, `popup.js`,
`options.js`) se prueba a mano cargando la extensión.
