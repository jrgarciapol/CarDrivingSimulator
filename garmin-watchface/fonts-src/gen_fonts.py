#!/usr/bin/env python3
"""Genera fuentes BMFont (.fnt + .png) compatibles con Connect IQ a partir de
Roboto Mono TTF. Glifos en blanco con cobertura en canal alfa (CIQ los tinta
con setColor). Empaquetado tipo 'shelf' en un atlas RGBA.
"""
import os
from PIL import Image, ImageDraw, ImageFont

import os
BASE = "/home/user/CarDrivingSimulator/garmin-watchface"
SRC_DIR = os.path.join(BASE, "fonts-src")        # TTF de origen
FONT_DIR = os.path.join(BASE, "resources/fonts") # salida .fnt + .png

# (id, archivo ttf, tamaño px, caracteres)
DIGITS = "0123456789"
TIME_CHARS = DIGITS + ":"
DATE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" + DIGITS + " "

JOBS = [
    ("TimeBold", "RobotoMono-Bold.ttf",   130, TIME_CHARS),   # hora interactiva
    ("TimeAod",  "RobotoMono-Bold.ttf",   156, TIME_CHARS),   # hora AOD (grande, ~9%)
    ("SecBold",  "RobotoMono-Bold.ttf",    56, DIGITS),       # segundos
    ("DateMed",  "RobotoMono-Medium.ttf",  32, DATE_CHARS),   # fecha
]

PAD = 2  # separación entre glifos en el atlas


def build(job):
    fid, ttf, size, chars = job
    font = ImageFont.truetype(os.path.join(SRC_DIR, ttf), size)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    base = ascent

    # Render de cada glifo -> recorte a su caja de tinta
    glyphs = []  # (char, sub_image, w, h, xoffset, yoffset, xadvance)
    for c in chars:
        # lienzo temporal amplio; dibujamos con baseline en y=ascent
        tmp = Image.new("L", (size * 2, line_height + size), 0)
        d = ImageDraw.Draw(tmp)
        d.text((size // 2, base), c, font=font, fill=255, anchor="ls")
        bbox = tmp.getbbox()
        xadvance = round(font.getlength(c))
        if bbox is None:  # espacio: sin tinta
            glyphs.append((c, None, 0, 0, 0, 0, xadvance))
            continue
        ix0, iy0, ix1, iy1 = bbox
        w, h = ix1 - ix0, iy1 - iy0
        sub = tmp.crop(bbox)
        xoffset = ix0 - (size // 2)   # desde el origen del cursor
        yoffset = iy0                 # desde el borde superior de la línea
        glyphs.append((c, sub, w, h, xoffset, yoffset, xadvance))

    # Empaquetado en estanterías dentro de un ancho máximo
    max_w = 480
    x = y = 0
    row_h = 0
    placed = []
    for g in glyphs:
        c, sub, w, h, xo, yo, xa = g
        if sub is None:
            placed.append((c, 0, 0, 0, 0, xo, yo, xa))
            continue
        if x + w + PAD > max_w:
            x = 0
            y += row_h + PAD
            row_h = 0
        placed.append((c, x, y, w, h, xo, yo, xa))
        x += w + PAD
        row_h = max(row_h, h)
    atlas_w = max_w
    atlas_h = y + row_h + PAD

    # Componer atlas RGBA (blanco + alfa=cobertura)
    atlas = Image.new("RGBA", (atlas_w, atlas_h), (255, 255, 255, 0))
    for (c, gx, gy, w, h, xo, yo, xa), g in zip(placed, glyphs):
        sub = g[1]
        if sub is None:
            continue
        rgba = Image.new("RGBA", sub.size, (255, 255, 255, 0))
        rgba.putalpha(sub)
        atlas.paste(rgba, (gx, gy))

    png_name = fid + ".png"
    atlas.save(os.path.join(FONT_DIR, png_name))

    # Escribir descriptor .fnt (formato texto BMFont)
    lines = []
    lines.append(
        'info face="%s" size=%d bold=0 italic=0 charset="" unicode=1 '
        'stretchH=100 smooth=1 aa=1 padding=0,0,0,0 spacing=1,1 outline=0'
        % (fid, size))
    lines.append(
        'common lineHeight=%d base=%d scaleW=%d scaleH=%d pages=1 packed=0 '
        'alphaChnl=1 redChnl=0 greenChnl=0 blueChnl=0'
        % (line_height, base, atlas_w, atlas_h))
    lines.append('page id=0 file="%s"' % png_name)
    lines.append('chars count=%d' % len(placed))
    for (c, gx, gy, w, h, xo, yo, xa) in placed:
        lines.append(
            'char id=%-3d x=%-4d y=%-4d width=%-4d height=%-4d '
            'xoffset=%-4d yoffset=%-4d xadvance=%-4d page=0 chnl=15'
            % (ord(c), gx, gy, w, h, xo, yo, xa))
    with open(os.path.join(FONT_DIR, fid + ".fnt"), "w") as f:
        f.write("\n".join(lines) + "\n")

    # Info para verificar encaje en pantalla
    def strwidth(s):
        adv = {c: xa for (c, *_rest, xa) in
               [(p[0],) + tuple(p[1:]) for p in placed]}
        return sum(adv.get(ch, 0) for ch in s)

    sample = "10:24" if ":" in chars else ("SAB 09 AGO" if " " in chars else "37")
    print("%-9s size=%3d atlas=%dx%d lineH=%d base=%d  '%s'=%dpx"
          % (fid, size, atlas_w, atlas_h, line_height, base, sample, strwidth(sample)))


for job in JOBS:
    build(job)
