// Agrupa una ráfaga de avisos en una sola recarga.
//
// Un alta con token publica dos eventos seguidos, y la pestaña que hizo el
// cambio recibe además el suyo. Sin esto, cada uno pediría el listado entero.
//
// La recarga arranca `espera` ms después del PRIMER aviso, no del último: una
// ráfaga larga no puede aplazarla para siempre. Mientras corre no se lanza otra
// encima, porque dos respuestas podrían llegar cambiadas de orden y dejar en
// pantalla la más vieja; lo que llegue entre medias provoca una sola más al
// terminar, que ya verá lo último.
export function coalesce(recargar, espera = 150) {
  let temporizador = null
  let corriendo = false
  let pendiente = false

  const disparar = () => {
    if (corriendo) {
      pendiente = true
      return
    }
    if (temporizador !== null) return
    temporizador = setTimeout(async () => {
      temporizador = null
      corriendo = true
      try {
        await recargar()
      } finally {
        corriendo = false
        if (pendiente) {
          pendiente = false
          disparar()
        }
      }
    }, espera)
  }

  disparar.cancelar = () => {
    clearTimeout(temporizador)
    temporizador = null
    pendiente = false
  }

  return disparar
}
