"""Captura de pantalla SIN VENTANA, para revisar la maquetación del HUD.

Dibuja una escena completa (pista + coche + HUD + telemetría) en un
renderizador por software y la guarda en PNG. Sirve para comprobar de un
vistazo que los paneles no se solapan, sin necesidad de arrancar el juego
ni de tener volante.

    python3 tools/captura.py salida.png [--telemetria] [--contrario]
                                        [--s 120] [--coche 3_deportivo]

Se apoya en el driver de vídeo "dummy" de SDL, así que funciona por SSH y
en integración continua.
"""

import argparse
import ctypes
import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import sdl2                                              # noqa: E402
import sdl2.sdlimage as sdlimage                         # noqa: E402

from simulator import config as cfg                      # noqa: E402
from simulator import garage                             # noqa: E402
from simulator.physics import Car                        # noqa: E402
from simulator.render import Renderer, Hud               # noqa: E402
from simulator.track import Track                        # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("salida", help="archivo PNG de salida")
    p.add_argument("--telemetria", action="store_true",
                   help="mostrar la superposición F2")
    p.add_argument("--contrario", action="store_true",
                   help="simular que se circula en sentido contrario")
    p.add_argument("--sin-cronometrar", action="store_true",
                   help="simular vuelta invalidada")
    p.add_argument("--s", type=float, default=0.0,
                   help="posición en el circuito (m); 0 = línea de meta")
    p.add_argument("--v", type=float, default=32.0, help="velocidad (m/s)")
    p.add_argument("--volante", type=float, default=0.18,
                   help="posición del volante (-1..1)")
    p.add_argument("--coche", default="3_deportivo", help="archivo .car")
    p.add_argument("--circuito", default="", help="CSV de circuito")
    args = p.parse_args(argv)

    if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO) != 0:
        print("Error al iniciar SDL:", sdl2.SDL_GetError().decode())
        return 1
    W, H = cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT
    window = sdl2.SDL_CreateWindow(b"captura", 0, 0, W, H,
                                   sdl2.SDL_WINDOW_HIDDEN)
    renderer = sdl2.SDL_CreateRenderer(
        window, -1, sdl2.SDL_RENDERER_SOFTWARE | sdl2.SDL_RENDERER_TARGETTEXTURE)
    sdl2.SDL_SetRenderDrawBlendMode(renderer, sdl2.SDL_BLENDMODE_BLEND)

    car_path = args.coche
    if not os.path.isabs(car_path) and not car_path.endswith(".car"):
        car_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "simulator", "cars", car_path + ".car")
    car_name = garage.load_car(car_path)
    cfg.TRACK_FILE = args.circuito

    track = Track()
    car = Car()
    scene = Renderer(renderer)
    hud = Hud(renderer)

    # asentar la suspensión y colocar el coche donde se pida, rodando
    st = car.state
    for _ in range(int(1.0 * cfg.PHYSICS_HZ)):
        car.step(1.0 / cfg.PHYSICS_HZ, 0.0, 0.0, 0.0, track)
    st = car.state
    st.s = args.s
    st.vx = args.v
    for i in range(4):
        st.omega[i] = args.v / cfg.CAR_WHEEL_RADIUS
    st.gear = 4
    for _ in range(int(0.6 * cfg.PHYSICS_HZ)):
        car.step(1.0 / cfg.PHYSICS_HZ, args.volante, 0.35, 0.0, track)
    st = car.state
    st.s = args.s          # recolocar exacto tras el asentamiento

    sdl2.SDL_SetRenderDrawColor(renderer, 0, 0, 0, 255)
    sdl2.SDL_RenderClear(renderer)
    scene.draw_background(H // 2, 0.0)
    scene.draw_road(track, st, show_line=cfg.RACING_LINE)
    scene.draw_car(st, args.volante)
    hud.draw(st, 42.7, 88.4, 3, True, "T300RS", False, 1.0, track,
             car_name, "SECO",
             wrong_way=args.contrario,
             lap_valid=not args.sin_cronometrar)
    if cfg.MINIMAP:
        hud.draw_minimap(track, st)
    if cfg.MAP_AHEAD:
        hud.draw_plan_ahead(track, st)
    if args.telemetria:
        hud.draw_telemetry(st, args.volante, 12.0)

    # volcar el back buffer a PNG
    surf = sdl2.SDL_CreateRGBSurfaceWithFormat(
        0, W, H, 32, sdl2.SDL_PIXELFORMAT_ARGB8888)
    sdl2.SDL_RenderReadPixels(renderer, None, sdl2.SDL_PIXELFORMAT_ARGB8888,
                              surf.contents.pixels, surf.contents.pitch)
    sdlimage.IMG_Init(sdlimage.IMG_INIT_PNG)
    if sdlimage.IMG_SavePNG(surf, args.salida.encode()) != 0:
        print("Error al guardar:", sdl2.SDL_GetError().decode())
        return 1
    print("guardado", args.salida)
    sdl2.SDL_FreeSurface(surf)
    sdl2.SDL_DestroyRenderer(renderer)
    sdl2.SDL_DestroyWindow(window)
    sdl2.SDL_Quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
