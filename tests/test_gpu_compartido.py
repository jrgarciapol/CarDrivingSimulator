"""Pruebas del contexto OpenGL COMPARTIDO con SDL (gpu.py, modo compartido).

Con el renderizador 'opengl' de SDL, moderngl se engancha a su contexto y
pinta la escena directamente en la textura de fondo: no hay que leer el
fotograma de la GPU (que costaba 15 ms en un Intel Arc). Aqui se comprueba:

  - que con el renderizador de OpenGL la escena entra en modo compartido,
  - que el fotograma sale bien (cielo, asfalto, hierba) y no se lee nada,
  - que SDL sigue pintando correctamente DESPUES de moderngl (el HUD se ve
    encima de la escena y con su color), fotograma tras fotograma,
  - que con el renderizador por software se vuelve al contexto propio.

Necesita una ventana con OpenGL: sin DISPLAY se relanza dentro de Xvfb
(xvfb-run) y, si no lo hay, se salta con aviso.

    python tests/test_gpu_compartido.py
"""

import ctypes
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return bool(cond)


def _relanzar_en_xvfb():
    """Sin pantalla, ejecutar este mismo archivo dentro de xvfb-run."""
    if os.environ.get("DISPLAY") or os.environ.get("_EN_XVFB"):
        return None
    if sys.platform != "linux" or not shutil.which("xvfb-run"):
        return None
    env = dict(os.environ, _EN_XVFB="1")
    env.pop("SDL_VIDEODRIVER", None)
    p = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1024x768x24",
                        sys.executable, os.path.abspath(__file__)], env=env)
    return p.returncode


def main():
    rc = _relanzar_en_xvfb()
    if rc is not None:
        return rc
    if not os.environ.get("DISPLAY") and sys.platform == "linux":
        print("[AVISO] sin pantalla ni xvfb-run: se saltan las pruebas del "
              "contexto compartido")
        print("\n0/0 pruebas correctas")
        return 0
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import numpy as np                                # noqa: E402
    import sdl2                                       # noqa: E402
    from simulator import config as cfg               # noqa: E402
    from simulator import gpu                         # noqa: E402
    from simulator import render as render_mod        # noqa: E402
    from simulator.physics import Car                 # noqa: E402
    from simulator.track import Track                 # noqa: E402

    if gpu.moderngl is None:
        print("[AVISO] sin moderngl: se saltan las pruebas")
        print("\n0/0 pruebas correctas")
        return 0

    r = []
    W, H = 640, 400
    cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT, cfg.WINDOW_AUTO = W, H, False
    sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_DRIVER, b"opengl")
    sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
    win = sdl2.SDL_CreateWindow(b"t", 0, 0, W, H, sdl2.SDL_WINDOW_HIDDEN)
    ren = sdl2.SDL_CreateRenderer(win, -1, sdl2.SDL_RENDERER_ACCELERATED)
    sdl2.SDL_SetRenderDrawBlendMode(ren, sdl2.SDL_BLENDMODE_BLEND)
    info = sdl2.SDL_RendererInfo()
    sdl2.SDL_GetRendererInfo(ren, ctypes.byref(info))
    nombre = info.name.decode() if info.name else "?"
    r.append(check("SDL ha creado el renderizador de OpenGL", nombre == "opengl",
                   nombre))

    def leer():
        buf = (ctypes.c_uint8 * (W * H * 4))()
        sdl2.SDL_RenderReadPixels(ren, None, sdl2.SDL_PIXELFORMAT_ABGR8888,
                                  buf, W * 4)
        return np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 4).astype(int)

    cfg.GFX_GPU_COMPARTIDO = True
    cfg.SKY_CLOUDS = 0.0             # el pixel de cielo que se mira debe ser azul
    escena = gpu.GpuScene(ren, W, H, msaa=4)
    r.append(check("la escena entra en modo COMPARTIDO", escena.ok and escena.compartido,
                   escena.motivo_compartido or escena.motivo))
    if not (escena.ok and escena.compartido):
        n_ok = sum(1 for x in r if x)
        print(f"\n{n_ok}/{len(r)} pruebas correctas")
        return 1
    print("   GL:", escena.info.get("GL_RENDERER"), escena.info.get("GL_VERSION"))

    cfg.TRACK_FILE = "tracks/c-90.csv"
    c90 = Track()
    pal = render_mod.paleta()
    st = Car().state
    st.s, st.vx = 3000.0, 25.0
    from types import SimpleNamespace
    cam = SimpleNamespace(f=cfg.CAMERA_DEPTH, extra_y=cfg.CAMERA_HEIGHT,
                          pitch_px=0.0, psi_c=0.0, mesh_dx=0.0,
                          cam_forward=cfg.CAMERA_FORWARD, cam_back=0.0,
                          onboard=True)
    sdl2.SDL_ClearError()
    hud_ok = True
    for k in range(4):                # varios fotogramas: el estado no se degrada
        sdl2.SDL_SetRenderDrawColor(ren, 0, 0, 0, 255)
        sdl2.SDL_RenderClear(ren)
        escena.dibujar(c90, st, cam, True, pal)
        # HUD con SDL encima de la escena, como en el juego
        sdl2.SDL_SetRenderDrawColor(ren, 255, 255, 0, 255)
        sdl2.SDL_RenderFillRect(ren, sdl2.SDL_Rect(20, 20, 40, 40))
        sdl2.SDL_SetRenderDrawColor(ren, 0, 0, 0, 128)
        sdl2.SDL_RenderFillRect(ren, sdl2.SDL_Rect(W - 100, 20, 60, 60))
        sdl2.SDL_RenderPresent(ren)
        img = leer()
        if not (tuple(img[40, 40, :3]) == (255, 255, 0)):
            hud_ok = False
    err = sdl2.SDL_GetError()
    arriba = img[8, W // 2]
    abajo = img[H - 8, W // 2 + 60]
    esquina = img[int(H * 0.56), 6]
    r.append(check("arriba hay cielo (azul)", arriba[2] > arriba[0] + 40,
                   str(arriba[:3])))
    r.append(check("abajo en el centro hay asfalto (gris oscuro)",
                   abajo[:3].max() - abajo[:3].min() < 14 and abajo[0] < 120,
                   str(abajo[:3])))
    r.append(check("a los lados, bajo el horizonte, hay hierba (verde)",
                   esquina[1] > esquina[0] + 40 and esquina[1] > esquina[2],
                   str(esquina[:3])))
    r.append(check("el HUD de SDL se pinta ENCIMA de la escena y con su color, "
                   "en 4 fotogramas seguidos", hud_ok, str(img[40, 40, :3])))
    semi = img[50, W - 70]
    r.append(check("...y la mezcla alfa de SDL sigue funcionando (negro al 50%)",
                   30 < semi[2] < 160 and semi[2] < arriba[2],
                   f"{semi[:3]} sobre cielo {arriba[:3]}"))
    r.append(check("SDL no ha registrado errores", not err, err))
    r.append(check("no se lee el fotograma (lectura 0 ms, subida solo la copia)",
                   escena.ms_lectura < 0.05 and escena.ms_subida < 5.0,
                   f"lect {escena.ms_lectura:.2f} sub {escena.ms_subida:.2f}"))
    r.append(check("el fotograma se pinta en la GPU en poco tiempo",
                   escena.ms_gl < 60.0, f"GL {escena.ms_gl:.1f} ms"))
    # --- con el modelo 3D del coche (texturas propias) varios fotogramas ---
    # SDL recuerda que textura dejo enlazada: tras pintar el coche con las
    # suyas, copiaba el fondo con la textura de la RUEDA a pantalla completa
    # a partir del segundo fotograma. Se comprueba que el cielo sigue siendo
    # cielo y el coche se ve, fotograma tras fotograma.
    from simulator import modelo3d
    datos = modelo3d.cargar("f1")
    scene = render_mod.Renderer(ren)
    scene.gpu = escena
    cielo_ok = coche_ok = True
    for k in range(4):
        sdl2.SDL_SetRenderDrawColor(ren, 0, 0, 0, 255)
        sdl2.SDL_RenderClear(ren)
        scene.draw_scene(c90, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d={"datos": datos, "steering": 0.2, "dt": 0.01})
        sdl2.SDL_SetRenderDrawColor(ren, 255, 255, 0, 255)
        sdl2.SDL_RenderFillRect(ren, sdl2.SDL_Rect(20, 20, 40, 40))
        sdl2.SDL_RenderPresent(ren)
        img = leer()
        top = img[8, W // 2]
        if not (top[2] > top[0] + 40):
            cielo_ok = False
        zona = img[int(H * 0.55):int(H * 0.95), int(W * 0.3):int(W * 0.7), :3]
        if (zona.max(axis=2) > 90).sum() < 500 or tuple(img[40, 40, :3]) != (255, 255, 0):
            coche_ok = False
    r.append(check("con el modelo 3D del coche, el fondo sigue siendo la "
                   "escena en 4 fotogramas seguidos (no la textura de la rueda)",
                   cielo_ok and scene.coche_gpu, str(img[8, W // 2, :3])))
    r.append(check("...y el coche y el HUD se ven en todos", coche_ok))
    # el punto en la calzada 15 m por delante se proyecta con la camara
    p = escena.world_to_screen(c90, st.s + 15.0, 0.0, 0.0)
    r.append(check("world_to_screen proyecta el eje 15 m por delante bajo el "
                   "horizonte, centrado", p is not None and abs(p[0] - W / 2) < 40
                   and H / 2 < p[1] < H, str(p)))
    escena.close()

    # --- sin renderizador de OpenGL: contexto propio + lectura -------------
    sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_DRIVER, b"software")
    win2 = sdl2.SDL_CreateWindow(b"t2", 0, 0, W, H, sdl2.SDL_WINDOW_HIDDEN)
    ren2 = sdl2.SDL_CreateRenderer(win2, -1, sdl2.SDL_RENDERER_SOFTWARE)
    escena2 = gpu.GpuScene(ren2, W, H, msaa=4)
    r.append(check("con el renderizador por software se vuelve al contexto "
                   "propio (y explica por que)",
                   escena2.ok and not escena2.compartido
                   and "software" in escena2.motivo_compartido,
                   escena2.motivo_compartido or escena2.motivo))
    escena2.close()

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
