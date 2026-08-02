"""Menú de arranque: elegir coche, circuito y estado del asfalto.

Controles: flechas arriba/abajo cambian de fila, izquierda/derecha cambian
el valor, ENTER empieza a correr, ESC sale. Muestra la descripción del
coche y el récord guardado para la combinación elegida.
"""

import ctypes
import os

import sdl2

from . import config as cfg
from . import font
from . import garage


def _list_tracks():
    tracks = []
    tdir = os.path.join(os.path.dirname(__file__), "tracks")
    if os.path.isdir(tdir):
        for fn in sorted(os.listdir(tdir)):
            if fn.endswith(".csv"):
                tracks.append((os.path.splitext(fn)[0].upper(),
                               "tracks/" + fn))
    tracks.append(("CIRCUITO DE PRUEBAS", ""))
    return tracks


def _fill(renderer, rect, x, y, w, h, color):
    sdl2.SDL_SetRenderDrawColor(renderer, color[0], color[1], color[2],
                                color[3] if len(color) > 3 else 255)
    rect.x, rect.y, rect.w, rect.h = int(x), int(y), int(w), int(h)
    sdl2.SDL_RenderFillRect(renderer, rect)


def run_menu(renderer):
    """Devuelve dict con la selección, o None si el usuario sale."""
    W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
    cars = garage.list_cars()
    tracks = _list_tracks()
    conds = garage.CONDITION_ORDER
    if not cars:
        return {"car": None, "track": cfg.TRACK_FILE, "cond": "SECO"}

    i_car = min(2, len(cars) - 1)   # DEPORTIVO por defecto
    i_trk = 0
    i_cnd = 0
    row = 0
    rows = 4
    rect = sdl2.SDL_Rect()
    event = sdl2.SDL_Event()

    while True:
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_QUIT:
                return None
            if event.type == sdl2.SDL_KEYDOWN and not event.key.repeat:
                sym = event.key.keysym.sym
                if sym == sdl2.SDLK_ESCAPE:
                    return None
                if sym == sdl2.SDLK_UP:
                    row = (row - 1) % rows
                elif sym == sdl2.SDLK_DOWN:
                    row = (row + 1) % rows
                elif sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
                    if row == rows - 1:
                        return {"car": cars[i_car], "track": tracks[i_trk],
                                "cond": conds[i_cnd]}
                    row = (row + 1) % rows
                elif sym in (sdl2.SDLK_LEFT, sdl2.SDLK_RIGHT):
                    step = 1 if sym == sdl2.SDLK_RIGHT else -1
                    if row == 0:
                        i_car = (i_car + step) % len(cars)
                    elif row == 1:
                        i_trk = (i_trk + step) % len(tracks)
                    elif row == 2:
                        i_cnd = (i_cnd + step) % len(conds)

        # ------------------------------------------------ dibujo
        sdl2.SDL_SetRenderDrawColor(renderer, 14, 18, 26, 255)
        sdl2.SDL_RenderClear(renderer)
        font.draw_text(renderer, "CAR DRIVING SIMULATOR", W // 2 - 250, 70, 4,
                       (235, 60, 50, 255))
        font.draw_text(renderer, cfg.VERSION, W // 2 - 250, 116, 2,
                       (150, 150, 150, 255))

        labels = ["COCHE", "CIRCUITO", "ASFALTO", "EMPEZAR"]
        values = [cars[i_car][0], tracks[i_trk][0],
                  f"{conds[i_cnd]} ({garage.CONDITIONS[conds[i_cnd]]['desc'].upper()})",
                  ""]
        y = 210
        for r in range(rows):
            sel = (r == row)
            if sel:
                _fill(renderer, rect, 120, y - 8, W - 240, 40, (40, 55, 80))
            font.draw_text(renderer, labels[r], 150, y, 2,
                           (255, 200, 60, 255) if sel else (170, 170, 170, 255))
            font.draw_text(renderer, values[r], 400, y,
                           2, (255, 255, 255, 255) if sel else (190, 190, 190, 255))
            if sel and r < 3:
                font.draw_text(renderer, "<", 370, y, 2, (255, 200, 60, 255))
                font.draw_text(renderer, ">", W - 170, y, 2, (255, 200, 60, 255))
            y += 56

        # descripción del coche y récord de la combinación
        font.draw_text(renderer, cars[i_car][2], 150, y + 8, 2,
                       (140, 200, 255, 255))
        rec = garage.record_get(tracks[i_trk][0], cars[i_car][0], conds[i_cnd])
        if rec is not None:
            mins = int(rec // 60)
            rec_txt = f"RECORD: {mins:02d}:{rec - mins * 60:04.1f}"
        else:
            rec_txt = "RECORD: --:--.-  (SIN VUELTAS TODAVIA)"
        font.draw_text(renderer, rec_txt, 150, y + 40, 2, (120, 230, 120, 255))

        font.draw_text(renderer,
                       "FLECHAS: ELEGIR   ENTER: CONTINUAR   ESC: SALIR",
                       150, H - 60, 2, (150, 150, 150, 255))
        sdl2.SDL_RenderPresent(renderer)
        sdl2.SDL_Delay(16)
