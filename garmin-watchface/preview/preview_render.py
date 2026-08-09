#!/usr/bin/env python3
"""Vista previa fiel de la esfera usando las fuentes y coordenadas reales.
Genera un PNG con los dos modos: INTERACTIVO y ALWAYS-ON."""
from PIL import Image, ImageDraw, ImageFont

SRC = "/home/user/CarDrivingSimulator/garmin-watchface/fonts-src"
OUT = "/home/user/CarDrivingSimulator/garmin-watchface/preview/preview.png"

S = 454                      # pantalla
ACCENT = (30, 155, 255)      # 0x1E9BFF
WHITE = (255, 255, 255)
GRAY = (170, 170, 170)       # 0xAAAAAA
DIM = (136, 136, 136)        # 0x888888

# fuentes (mismos tamaños que el código / BMFont)
f_time_bold = ImageFont.truetype(f"{SRC}/RobotoMono-Bold.ttf", 130)
f_time_thin = ImageFont.truetype(f"{SRC}/RobotoMono-Light.ttf", 130)
f_sec = ImageFont.truetype(f"{SRC}/RobotoMono-Bold.ttf", 56)
f_date = ImageFont.truetype(f"{SRC}/RobotoMono-Medium.ttf", 32)

Y_DATE, Y_TIME, Y_LINE, Y_SEC = 0.30, 0.50, 0.685, 0.79


def face(mode):
    """Dibuja una pantalla 454x454 (RGB) en el modo dado."""
    img = Image.new("RGB", (S, S), (0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = S // 2
    date_txt = "SAB 09 AGO"

    if mode == "interactive":
        d.text((cx, int(S * Y_DATE)), date_txt, font=f_date, fill=GRAY, anchor="mm")
        d.text((cx, int(S * Y_TIME)), "10:24", font=f_time_bold, fill=WHITE, anchor="mm")
        half = int(S * 0.16)
        ly = int(S * Y_LINE)
        d.rectangle([cx - half, ly, cx + half, ly + 3], fill=ACCENT)
        d.text((cx, int(S * Y_SEC)), "37", font=f_sec, fill=ACCENT, anchor="mm")
    else:  # always-on (con desplazamiento de píxeles de ejemplo)
        ox, oy = 8, -8
        d.text((cx + ox, int(S * Y_DATE) + oy), date_txt, font=f_date, fill=DIM, anchor="mm")
        d.text((cx + ox, int(S * Y_TIME) + oy), "10:24", font=f_time_thin, fill=WHITE, anchor="mm")

    # recorte circular
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, S - 1, S - 1], fill=255)
    img.putalpha(mask)
    return img


def watch(mode):
    """Envuelve la pantalla en un bisel tipo Epix Pro."""
    pad = 34
    W = S + pad * 2
    canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    # bisel
    d.ellipse([0, 0, W - 1, W - 1], fill=(58, 60, 66, 255))
    d.ellipse([6, 6, W - 7, W - 7], fill=(74, 77, 82, 255))
    d.ellipse([pad - 4, pad - 4, pad + S + 3, pad + S + 3], fill=(20, 21, 24, 255))
    # marcas del bisel
    tick = ImageFont.truetype(f"{SRC}/RobotoMono-Bold.ttf", 20)
    for txt, (tx, ty) in {"60": (W // 2, 20), "15": (W - 26, W // 2),
                          "30": (W // 2, W - 20), "45": (24, W // 2)}.items():
        d.text((tx, ty), txt, font=tick, fill=(200, 203, 209), anchor="mm")
    canvas.alpha_composite(face(mode), (pad, pad))
    return canvas


# Composición final: dos relojes + etiquetas
w1 = watch("interactive")
w2 = watch("always-on")
gap = 60
margin = 40
label_h = 70
CW = w1.width * 2 + gap + margin * 2
CH = w1.height + margin + label_h
out = Image.new("RGB", (CW, CH), (18, 18, 22))
out.paste(w1, (margin, margin), w1)
out.paste(w2, (margin + w1.width + gap, margin), w2)

d = ImageDraw.Draw(out)
lab = ImageFont.truetype(f"{SRC}/RobotoMono-Medium.ttf", 30)
sub = ImageFont.truetype(f"{SRC}/RobotoMono-Regular.ttf", 20)
y = margin + w1.height + 12
d.text((margin + w1.width // 2, y), "INTERACTIVO", font=lab, fill=WHITE, anchor="ma")
d.text((margin + w1.width // 2, y + 34), "Roboto Mono Bold - brillo max.",
       font=sub, fill=GRAY, anchor="ma")
cx2 = margin + w1.width + gap + w2.width // 2
d.text((cx2, y), "ALWAYS-ON", font=lab, fill=WHITE, anchor="ma")
d.text((cx2, y + 34), "Roboto Mono Light - anti burn-in (~4%)",
       font=sub, fill=GRAY, anchor="ma")

out.save(OUT)
print("preview escrito:", OUT, out.size)
