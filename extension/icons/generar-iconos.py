#!/usr/bin/env python3
"""Recorta el emblema de `extension/logo.jpeg` y genera los iconos.

Se guarda el script y no solo el resultado porque los números de aquí abajo
—centro y radios del aro— salen de medir la imagen, y sin ellos volver a
generar los iconos es empezar de cero a ojo.

El emblema **no es circular en el original**: la imagen viene estirada en
horizontal (1393 x 1323 px), así que se recorta como elipse y al llevarlo a un
lienzo cuadrado recupera su forma redonda.

Uso (Pillow no es dependencia del proyecto; se instala aparte):

    python -m pip install pillow
    python extension/icons/generar-iconos.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent
ORIGEN = RAIZ.parent / "logo.jpeg"

# Centro y radios del aro dorado, medidos sobre el JPEG original.
CX, CY = 1411.5, 732.5
RH, RV = 696.5, 661.5
# El borde del oro está difuminado: se corta un pelo por fuera para no comérselo.
HOLGURA = 8
# Margen exterior transparente, en tanto por uno del radio.
MARGEN = 0.06
# Supermuestreo de la máscara: sin esto el borde queda escalonado, y se nota
# justo donde más duele, al reducirlo a 16 px.
ESCALA = 4

TAMANOS = (16, 32, 48, 128)


def main() -> None:
    imagen = Image.open(ORIGEN).convert("RGB")

    rh, rv = RH + HOLGURA, RV + HOLGURA
    mh, mv = rh * MARGEN, rv * MARGEN
    izq, arriba = round(CX - rh - mh), round(CY - rv - mv)
    ancho, alto = round(2 * (rh + mh)), round(2 * (rv + mv))
    recorte = imagen.crop((izq, arriba, izq + ancho, arriba + alto))

    mascara = Image.new("L", (ancho * ESCALA, alto * ESCALA), 0)
    ImageDraw.Draw(mascara).ellipse(
        [
            round(mh * ESCALA),
            round(mv * ESCALA),
            round((mh + 2 * rh) * ESCALA),
            round((mv + 2 * rv) * ESCALA),
        ],
        fill=255,
    )
    mascara = mascara.resize((ancho, alto), Image.LANCZOS)

    logo = recorte.convert("RGBA")
    logo.putalpha(mascara)

    logo.resize((512, 512), Image.LANCZOS).save(RAIZ / "logo.png")
    for tam in TAMANOS:
        logo.resize((tam, tam), Image.LANCZOS).save(RAIZ / f"icon-{tam}.png")
    print(f"Iconos generados en {RAIZ}")


if __name__ == "__main__":
    main()
