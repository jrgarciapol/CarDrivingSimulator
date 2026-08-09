#!/usr/bin/env python3
"""Vista previa fiel de la esfera usando las fuentes y coordenadas reales.
Genera un PNG con el modo INTERACTIVO y los ALWAYS-ON en verde y rojo."""
from PIL import Image, ImageDraw, ImageFont

SRC = "/home/user/CarDrivingSimulator/garmin-watchface/fonts-src"
OUT = "/home/user/CarDrivingSimulator/garmin-watchface/preview/preview.png"

S = 454                      # pantalla
ACCENT = (30, 155, 255)      # 0x1E9BFF
WHITE = (255, 255, 255)
GRAY = (170, 170, 170)       # 0xAAAAAA
GREEN = (0, 255, 0)          # 0x00FF00
RED = (255, 0, 0)            # 0xFF0000

# fuentes (mismos tamaños que el código / BMFont)
f_time_bold = ImageFont.truetype(f"{SRC}/RobotoMono-Bold.ttf", 130)   # interactivo
f_aod = ImageFont.truetype(f"{SRC}/RobotoMono-Bold.ttf", 156)         # AOD grande
f_sec = ImageFont.truetype(f"{SRC}/RobotoMono-Bold.ttf", 56)
f_date = ImageFont.truetype(f"{SRC}/RobotoMono-Medium.ttf", 32)

Y_DATE, Y_TIME, Y_LINE, Y_SEC = 0.30, 0.50, 0.685, 0.79


def draw_aod_time(d, cx, cy, color):
    """Dibuja HH : MM en tres bloques con ':' ceñido (como el código)."""
    hh, mm = "10", "24"
    wB = f_aod.getlength(hh)
    colonSlot = int(f_aod.getlength(":") * 0.5)
    totalW = wB * 2 + colonSlot
    x0 = cx - totalW / 2
    d.text((x0, cy), hh, font=f_aod, fill=color, anchor="lm")
    d.text((x0 + wB + colonSlot / 2, cy), ":", font=f_aod, fill=color, anchor="mm")
    d.text((x0 + wB + colonSlot, cy), mm, font=f_aod, fill=color, anchor="lm")


def face(mode, aod_color=None):
    img = Image.new("RGB", (S, S), (0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = S // 2

    if mode == "interactive":
        d.text((cx, int(S * Y_DATE)), "SAB 09 AGO", font=f_date, fill=GRAY, anchor="mm")
        d.text((cx, int(S * Y_TIME)), "10:24", font=f_time_bold, fill=WHITE, anchor="mm")
        half = int(S * 0.16)
        ly = int(S * Y_LINE)
        d.rectangle([cx - half, ly, cx + half, ly + 3], fill=ACCENT)
        d.text((cx, int(S * Y_SEC)), "37", font=f_sec, fill=ACCENT, anchor="mm")
    else:  # always-on: solo la hora, grande, con desplazamiento de ejemplo
        ox, oy = 8, -8
        draw_aod_time(d, cx + ox, S // 2 + oy, aod_color)

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, S - 1, S - 1], fill=255)
    img.putalpha(mask)
    return img


def watch(mode, aod_color=None):
    pad = 34
    W = S + pad * 2
    canvas = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.ellipse([0, 0, W - 1, W - 1], fill=(58, 60, 66, 255))
    d.ellipse([6, 6, W - 7, W - 7], fill=(74, 77, 82, 255))
    d.ellipse([pad - 4, pad - 4, pad + S + 3, pad + S + 3], fill=(20, 21, 24, 255))
    tick = ImageFont.truetype(f"{SRC}/RobotoMono-Bold.ttf", 20)
    for txt, (tx, ty) in {"60": (W // 2, 20), "15": (W - 26, W // 2),
                          "30": (W // 2, W - 20), "45": (24, W // 2)}.items():
        d.text((tx, ty), txt, font=tick, fill=(200, 203, 209), anchor="mm")
    canvas.alpha_composite(face(mode, aod_color), (pad, pad))
    return canvas


# Composición: tres relojes
items = [
    ("interactive", None, "INTERACTIVO", "Roboto Mono Bold - brillo max."),
    ("aod", GREEN, "ALWAYS-ON - VERDE", "solo hora, Bold 156 (~9%)"),
    ("aod", RED, "ALWAYS-ON - ROJO", "solo hora, Bold 156 (~9%)"),
]
watches = [watch(m, c) for (m, c, _, _) in items]
gap, margin, label_h = 50, 40, 70
w0 = watches[0].width
CW = w0 * 3 + gap * 2 + margin * 2
CH = watches[0].height + margin + label_h
out = Image.new("RGB", (CW, CH), (18, 18, 22))
d = ImageDraw.Draw(out)
lab = ImageFont.truetype(f"{SRC}/RobotoMono-Medium.ttf", 28)
sub = ImageFont.truetype(f"{SRC}/RobotoMono-Regular.ttf", 18)
for i, (w, (_, _, title, subt)) in enumerate(zip(watches, items)):
    x = margin + i * (w0 + gap)
    out.paste(w, (x, margin), w)
    ly = margin + w.height + 12
    d.text((x + w0 // 2, ly), title, font=lab, fill=WHITE, anchor="ma")
    d.text((x + w0 // 2, ly + 32), subt, font=sub, fill=GRAY, anchor="ma")

out.save(OUT)
print("preview escrito:", OUT, out.size)
