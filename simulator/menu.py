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
from . import settings


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


def run_menu(renderer, wheel=None, last=None):
    """Devuelve dict con la selección, o None si el usuario sale.

    `wheel` (opcional) permite navegar el menú con el MANDO. `last` es la
    última selección guardada, para recuperarla al arrancar."""
    W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
    cars = garage.list_cars()
    tracks = _list_tracks()
    conds = garage.CONDITION_ORDER
    if not cars:
        return {"car": None, "track": cfg.TRACK_FILE, "cond": "SECO"}

    i_car = min(2, len(cars) - 1)   # DEPORTIVO por defecto
    i_trk = 0
    i_cnd = 0
    # recuperar la ultima seleccion guardada (coche/circuito/asfalto)
    if last:
        for k, c in enumerate(cars):
            if c[1] == last.get("car"):
                i_car = k
                break
        for k, t in enumerate(tracks):
            if t[1] == last.get("track"):
                i_trk = k
                break
        if last.get("cond") in conds:
            i_cnd = conds.index(last["cond"])
    wheels_cache = {}

    def wheels_for(i):
        path = cars[i][1]
        if path not in wheels_cache:
            wheels_cache[path] = garage.wheel_options(path)
        return wheels_cache[path]

    def serie_idx(i):
        """Índices de la montura de serie de cada eje en la lista."""
        specs = garage.car_wheel_specs(cars[i][1])
        opts = [o[0] for o in wheels_for(i)]
        return tuple(opts.index(s) if s in opts else 0 for s in specs)

    def aplicar_coche():
        """Carga el coche seleccionado en cfg (con la configuracion global y
        el reglaje vivo encima), para que la pantalla de AJUSTES parta SIEMPRE
        de los valores reales del coche elegido. Cambiar de coche descarta el
        reglaje del anterior (settings.set_car_path)."""
        path = cars[i_car][1]
        settings.set_car_path(path)
        try:
            garage.load_car(path)
        except (OSError, ValueError):
            return
        settings.apply_config()
        settings.apply_car()

    i_wf, i_wr = serie_idx(i_car)   # monturas delante / detrás
    aplicar_coche()                 # deja cfg reflejando el coche elegido
    row = 0
    rows = 7
    rect = sdl2.SDL_Rect()
    event = sdl2.SDL_Event()

    # teclado y mando producen las MISMAS seis acciones, procesadas en un
    # solo sitio: asi el menu funciona igual con flechas o con la cruceta
    def cambiar(step):
        nonlocal i_car, i_wf, i_wr, i_trk, i_cnd
        if row == 0:
            i_car = (i_car + step) % len(cars)
            i_wf, i_wr = serie_idx(i_car)       # su rueda de serie
            aplicar_coche()                     # y su reglaje/valores en cfg
        elif row in (1, 2):
            whl = wheels_for(i_car)
            if whl:
                if row == 1:
                    i_wf = (i_wf + step) % len(whl)
                else:
                    i_wr = (i_wr + step) % len(whl)
        elif row == 3:
            i_trk = (i_trk + step) % len(tracks)
        elif row == 4:
            i_cnd = (i_cnd + step) % len(conds)

    def activar():
        """None = seguir en el menu; dict = EMPEZAR con esa seleccion."""
        nonlocal row
        if row == 5:                            # AJUSTES AVANZADOS
            from .tuning import run_tuning
            run_tuning(renderer, wheel)
            return None
        if row == rows - 1:                     # EMPEZAR
            whl = wheels_for(i_car)
            s_f, s_r = serie_idx(i_car)
            cambia = whl and (i_wf != s_f or i_wr != s_r)
            return {"car": cars[i_car], "track": tracks[i_trk],
                    "cond": conds[i_cnd],
                    "wheel": whl[i_wf][0] if cambia else None,
                    "wheel_rear": whl[i_wr][0] if cambia else None}
        row = (row + 1) % rows
        return None

    _TECLAS = {
        sdl2.SDLK_ESCAPE: "back", sdl2.SDLK_UP: "up", sdl2.SDLK_DOWN: "down",
        sdl2.SDLK_RETURN: "ok", sdl2.SDLK_KP_ENTER: "ok",
        sdl2.SDLK_LEFT: "left", sdl2.SDLK_RIGHT: "right",
    }

    while True:
        acciones = []
        while sdl2.SDL_PollEvent(ctypes.byref(event)):
            if event.type == sdl2.SDL_QUIT:
                return None
            if event.type == sdl2.SDL_KEYDOWN:
                a = _TECLAS.get(event.key.keysym.sym)
                # las DIRECCIONES admiten repeticion del teclado (mantener
                # pulsado = moverse rapido); ok/back solo en el flanco
                if a and not (event.key.repeat and a in ("ok", "back")):
                    acciones.append(a)
        if wheel is not None:
            acciones.extend(wheel.menu_nav(0.016))  # cruceta/stick del mando

        for a in acciones:
            if a == "back":
                return None
            if a == "up":
                row = (row - 1) % rows
            elif a == "down":
                row = (row + 1) % rows
            elif a == "left":
                cambiar(-1)
            elif a == "right":
                cambiar(1)
            elif a == "ok":
                sel = activar()
                if sel is not None:
                    return sel

        # ------------------------------------------------ dibujo
        sdl2.SDL_SetRenderDrawColor(renderer, 14, 18, 26, 255)
        sdl2.SDL_RenderClear(renderer)
        font.draw_text(renderer, "CAR DRIVING SIMULATOR", W // 2 - 250, 70, 4,
                       (235, 60, 50, 255))
        font.draw_text(renderer, cfg.VERSION, W // 2 - 250, 116, 2,
                       (150, 150, 150, 255))

        whl = wheels_for(i_car)
        wf_txt = whl[i_wf][1] if whl else "(sin catalogo)"
        wr_txt = whl[i_wr][1] if whl else "(sin catalogo)"
        labels = ["COCHE", "RUEDAS DELANTE", "RUEDAS DETRAS", "CIRCUITO",
                  "ASFALTO", "AJUSTES AVANZADOS", "EMPEZAR"]
        values = [cars[i_car][0], wf_txt, wr_txt, tracks[i_trk][0],
                  f"{conds[i_cnd]} ({garage.CONDITIONS[conds[i_cnd]]['desc'].upper()})",
                  "(ENTER: EDITAR PARAMETROS)", ""]
        y = 190
        for r in range(rows):
            sel = (r == row)
            if sel:
                _fill(renderer, rect, 120, y - 8, W - 240, 38, (40, 55, 80))
            font.draw_text(renderer, labels[r], 150, y, 2,
                           (255, 200, 60, 255) if sel else (170, 170, 170, 255))
            font.draw_text(renderer, values[r], 500 if r != 5 else 620, y,
                           2, (255, 255, 255, 255) if sel else (190, 190, 190, 255))
            if sel and r < 5:
                font.draw_text(renderer, "<", 470, y, 2, (255, 200, 60, 255))
                font.draw_text(renderer, ">", W - 170, y, 2, (255, 200, 60, 255))
            y += 50

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

        ayuda = "FLECHAS: ELEGIR   ENTER: CONTINUAR   ESC: SALIR"
        if wheel is not None and getattr(wheel, "es_mando", False):
            ayuda = "CRUCETA/STICK: ELEGIR   A: CONTINUAR   B: SALIR"
        font.draw_text(renderer, ayuda, 150, H - 60, 2, (150, 150, 150, 255))
        sdl2.SDL_RenderPresent(renderer)
        sdl2.SDL_Delay(16)
