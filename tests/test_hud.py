"""Pruebas del HUD: la fuente en atlas y la esfera del velocimetro cacheada.

Lo que se reporto: al activar el velocimetro de aguja o la telemetria F2 el
juego perdia fluidez. Medido a 1080p: la esfera costaba 20 ms por fotograma
(casi 6.000 FillRect, porque los discos se pintan fila a fila) y cada letra
hasta 35 FillRect. Ahora la fuente es UNA textura (una copia por letra) y la
esfera se pinta una vez en una textura y se copia. Aqui se comprueba que:

  - el atlas dibuja EXACTAMENTE los mismos pixeles que el metodo lento,
  - el texto y la esfera cuestan una fraccion de lo que costaban,
  - el panel F1 dice por que no hay render de GPU cuando no lo hay.

    python tests/test_hud.py
"""

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np                                    # noqa: E402
import sdl2                                           # noqa: E402

from simulator import config as cfg                   # noqa: E402
from simulator import font                            # noqa: E402


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return bool(cond)


def main():
    r = []
    W, H = 640, 400
    cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT, cfg.WINDOW_AUTO = W, H, False
    sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
    win = sdl2.SDL_CreateWindow(b"t", 0, 0, W, H, sdl2.SDL_WINDOW_HIDDEN)
    ren = sdl2.SDL_CreateRenderer(win, -1, 0)
    sdl2.SDL_SetRenderDrawBlendMode(ren, sdl2.SDL_BLENDMODE_BLEND)

    def leer():
        buf = (ctypes.c_uint8 * (W * H * 4))()
        sdl2.SDL_RenderReadPixels(ren, None, sdl2.SDL_PIXELFORMAT_ABGR8888,
                                  buf, W * 4)
        return np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 4).copy()

    def limpiar():
        sdl2.SDL_SetRenderDrawColor(ren, 0, 0, 0, 255)
        sdl2.SDL_RenderClear(ren)

    # --- el atlas pinta lo mismo que el metodo pixel a pixel --------------
    texto = "ABC 0123 KM/H %.-:'"
    limpiar()
    font._draw_text_lento(ren, texto, 20, 30, 3, (255, 200, 60, 255))
    lento = leer()
    limpiar()
    font.draw_text(ren, texto, 20, 30, 3, (255, 200, 60, 255))
    rapido = leer()
    r.append(check("el atlas de fuente se ha creado", bool(font._ATLAS)))
    mascara_l = lento[:, :, 0] > 100
    mascara_r = rapido[:, :, 0] > 100
    iguales = (mascara_l == mascara_r).all()
    r.append(check("el atlas dibuja EXACTAMENTE los mismos pixeles que el "
                   "metodo lento", iguales,
                   f"{(mascara_l != mascara_r).sum()} pixeles distintos"))
    r.append(check("y con el color pedido",
                   tuple(rapido[mascara_r][0][:3]) == (255, 200, 60)))
    r.append(check("el texto no esta vacio", mascara_r.sum() > 100))

    # --- y cuesta una fraccion --------------------------------------------
    def mide(fn, n=30):
        fn()
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        return (time.perf_counter() - t0) / n * 1000.0
    frase = "VELOCIDAD 123 KM/H MARCHA 4 RPM 6500"
    t_lento = mide(lambda: font._draw_text_lento(ren, frase, 10, 10, 2,
                                                 (255, 255, 255, 255)))
    t_atlas = mide(lambda: font.draw_text(ren, frase, 10, 10, 2))
    r.append(check("el texto con atlas es al menos 4 veces mas barato",
                   t_atlas * 4.0 < t_lento,
                   f"{t_lento:.2f} ms -> {t_atlas:.3f} ms"))

    # --- la esfera del velocimetro se cachea ------------------------------
    from simulator import render as render_mod
    from simulator.physics import Car
    hud = render_mod.Hud(ren)
    st = Car().state
    st.vx = 30.0
    cfg.SPEEDO_DIAL = True
    limpiar()
    hud.draw_speedo(st)
    r.append(check("la esfera queda cacheada en una textura",
                   getattr(hud, "_speedo_cache", None) is not None))
    img = leer()
    d = int(getattr(cfg, "SPEEDO_SIZE", 250))
    zona = img[H - 28 - d:H - 28, 28:28 + d, :3]
    r.append(check("la esfera se ve (fondo, marcas y aguja)",
                   zona.max() > 200 and (zona.sum(axis=2) > 30).mean() > 0.4,
                   f"max {zona.max()}"))
    t_speedo = mide(lambda: hud.draw_speedo(st))
    r.append(check("dibujar el velocimetro cuesta menos de 1 ms",
                   t_speedo < 1.0, f"{t_speedo:.3f} ms"))
    # cambiar el tamano rehace la cache sin fallar
    cfg.SPEEDO_SIZE = 180
    hud.draw_speedo(st)
    r.append(check("cambiar SPEEDO_SIZE rehace la cache",
                   hud._speedo_cache[0][0] == 90))
    cfg.SPEEDO_SIZE = d

    # --- minimapa y telemetria por lotes -----------------------------------
    # Medidos en un PC con el registro F3: el minimapa costaba 12 ms por
    # fotograma (1.500 puntos de uno en uno) y la telemetria F2 unos 6 ms.
    from simulator.track import Track
    cfg.TRACK_FILE = "tracks/c-50.csv"
    pista = Track()
    st.s = 1200.0
    limpiar()
    hud.draw_minimap(pista, st)
    img = leer()
    caja = img[16:16 + 176, 16:16 + 236, :3]
    r.append(check("el minimapa se ve (trazado, tramo ambar y coche)",
                   (caja.max(axis=2) > 150).sum() > 300
                   and ((caja[:, :, 0] > 200) & (caja[:, :, 1] > 150)
                        & (caja[:, :, 2] < 100)).sum() > 5,
                   f"{(caja.max(axis=2) > 150).sum()} px claros"))
    r.append(check("...con la parte fija cacheada en una textura",
                   getattr(hud, "_mapa_cache", None) is not None
                   and hud._mapa_cache[0] is pista))
    t_mapa = mide(lambda: hud.draw_minimap(pista, st))
    r.append(check("dibujar el minimapa cuesta menos de 1 ms",
                   t_mapa < 1.0, f"{t_mapa:.3f} ms"))
    limpiar()
    for k in range(40):                   # unos fotogramas: estela de 2 s
        hud.draw_telemetry(st, 0.3, k * 0.05)
    img = leer()
    r.append(check("la telemetria se ve (aros de temperatura y coche cenital)",
                   (img[96:96 + 344, :, :3].max(axis=2) > 150).sum() > 800))
    t_tel = mide(lambda: hud.draw_telemetry(st, 0.3, 3.0))
    r.append(check("dibujar la telemetria cuesta menos de 1,5 ms",
                   t_tel < 1.5, f"{t_tel:.3f} ms"))

    # --- el panel F1 explica la ausencia de GPU ---------------------------
    from simulator.wheel import WheelInput
    from simulator import gpu
    cfg.GFX_GPU = False
    limpiar()
    try:
        hud.draw_debug(WheelInput(), st, "road", None)
        ok = True
    except Exception as e:                            # noqa: BLE001
        ok = False
        print("   ", type(e).__name__, e)
    r.append(check("el panel F1 se dibuja sin GPU y sin fallar", ok))
    r.append(check("...y explica el motivo",
                   "APAGADO" in gpu.estado(), gpu.estado()))

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
