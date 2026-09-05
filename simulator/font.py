"""Fuente bitmap 5x7 mínima para el HUD (sin dependencias externas)."""

import ctypes

import sdl2

GLYPHS = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "11011", "10001"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
    ".": ["00000", "00000", "00000", "00000", "00000", "00110", "00110"],
    ":": ["00000", "00110", "00110", "00000", "00110", "00110", "00000"],
    "-": ["00000", "00000", "00000", "01110", "00000", "00000", "00000"],
    "/": ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    "%": ["11001", "11010", "00010", "00100", "01000", "01011", "10011"],
    "'": ["00100", "00100", "00000", "00000", "00000", "00000", "00000"],
}


#: Orden fijo de los glifos dentro del atlas.
_ORDEN = {ch: i for i, ch in enumerate(GLYPHS)}
#: Atlas por renderizador: {direccion del renderer: textura}
_ATLAS = {}


def _clave(renderer):
    return ctypes.cast(renderer, ctypes.c_void_p).value


def _atlas(renderer):
    """La fuente entera en UNA textura, hecha una sola vez por renderizador.

    Antes cada letra se pintaba pixel a pixel con SDL_RenderFillRect: hasta
    35 llamadas por letra, ~2.500 por fotograma con la telemetria abierta,
    y cada una cruza de Python a C. Con el atlas una letra es UNA copia de
    textura, escalada por SDL con vecino mas proximo (asi los pixeles de la
    fuente siguen siendo bloques nitidos). El color se aplica con la
    modulacion de la textura, sin tocar el atlas."""
    k = _clave(renderer)
    tex = _ATLAS.get(k)
    if tex is not None:
        return tex
    n = len(_ORDEN)
    w, h = 6 * n, 7
    surf = sdl2.SDL_CreateRGBSurfaceWithFormat(0, w, h, 32,
                                               sdl2.SDL_PIXELFORMAT_RGBA32)
    if not surf:
        _ATLAS[k] = False
        return False
    pitch = surf.contents.pitch
    buf = (ctypes.c_uint8 * (pitch * h)).from_address(surf.contents.pixels)
    for ch, i in _ORDEN.items():
        for row, bits in enumerate(GLYPHS[ch]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    o = row * pitch + (i * 6 + col) * 4
                    buf[o] = buf[o + 1] = buf[o + 2] = buf[o + 3] = 255
    sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_SCALE_QUALITY, b"0")   # nitido
    tex = sdl2.SDL_CreateTextureFromSurface(renderer, surf)
    sdl2.SDL_FreeSurface(surf)
    if not tex:
        _ATLAS[k] = False
        return False
    sdl2.SDL_SetTextureBlendMode(tex, sdl2.SDL_BLENDMODE_BLEND)
    _ATLAS[k] = tex
    return tex


def draw_text(renderer, text, x, y, scale=2, color=(255, 255, 255, 255)):
    # SDL_Rect exige enteros: aceptar coordenadas con decimales
    x, y, scale = int(x), int(y), int(scale)
    tex = _atlas(renderer)
    if not tex:
        return _draw_text_lento(renderer, text, x, y, scale, color)
    sdl2.SDL_SetTextureColorMod(tex, color[0], color[1], color[2])
    sdl2.SDL_SetTextureAlphaMod(tex, color[3] if len(color) > 3 else 255)
    src = sdl2.SDL_Rect(0, 0, 5, 7)
    dst = sdl2.SDL_Rect(0, y, 5 * scale, 7 * scale)
    cx = x
    for ch in text.upper():
        i = _ORDEN.get(ch)
        if i is not None and ch != " ":
            src.x = i * 6
            dst.x = cx
            sdl2.SDL_RenderCopy(renderer, tex, src, dst)
        cx += 6 * scale
    return cx


def _draw_text_lento(renderer, text, x, y, scale, color):
    """Pixel a pixel: solo si no se pudo crear el atlas."""
    sdl2.SDL_SetRenderDrawColor(renderer, *color)
    cx = x
    rect = sdl2.SDL_Rect()
    for ch in text.upper():
        glyph = GLYPHS.get(ch)
        if glyph is None:
            cx += 6 * scale
            continue
        for row, bits in enumerate(glyph):
            for col, bit in enumerate(bits):
                if bit == "1":
                    rect.x = cx + col * scale
                    rect.y = y + row * scale
                    rect.w = scale
                    rect.h = scale
                    sdl2.SDL_RenderFillRect(renderer, rect)
        cx += 6 * scale
    return cx


def text_width(text, scale=2):
    return len(text) * 6 * scale
