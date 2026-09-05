"""Pruebas del modelo 3D del coche: importacion del .glb y pintado en la GPU.

  - tools/importar_modelo.py convierte el .glb de Sketchfab a .npz: mide
    el coche, reconoce las cuatro ruedas (delante/detras, izquierda/
    derecha) con su centro y su radio, y decodifica las texturas,
  - modelo3d.cargar lee el .npz versionado y devuelve None si no existe,
  - la escena de la GPU pinta el modelo en la vista de coche completo
    (cambia la imagen respecto a la misma vista sin coche), las ruedas
    ruedan con la velocidad, y sin modelo no pasa nada.

    python tests/test_modelo3d.py
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np                                    # noqa: E402

from simulator import config as cfg                   # noqa: E402
from simulator import modelo3d                        # noqa: E402

RAIZ = os.path.join(os.path.dirname(__file__), "..")
GLB = os.path.join(RAIZ, "simulator", "models", "free__formula_one_lp-830_sdc.glb")


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return bool(cond)


def main():
    r = []
    # --- importacion ---------------------------------------------------------
    if os.path.exists(GLB):
        import importar_modelo
        carpeta = tempfile.mkdtemp(prefix="modelo_")
        try:
            ruta, d = importar_modelo.convertir(GLB, "prueba", carpeta=carpeta)
            m = d["medidas"]
            r.append(check("el F1 mide lo que un F1 (1,8 x 1,1 x 4,9 m)",
                           1.6 < m[0] < 2.1 and 0.8 < m[1] < 1.3 and 4.5 < m[2] < 5.2,
                           f"{m[0]:.2f} x {m[1]:.2f} x {m[2]:.2f}"))
            r.append(check("31.176 triangulos, todos con normal y coordenadas",
                           len(d["idx"]) // 3 == 31176
                           and d["nrm"].shape == d["pos"].shape
                           and d["uv"].shape == (len(d["pos"]), 2)))
            r.append(check("el suelo queda en y = 0 y el coche centrado en x/z",
                           abs(d["pos"][:, 1].min()) < 1e-4
                           and abs(d["pos"][:, 0].min() + d["pos"][:, 0].max()) < 1e-3
                           and abs(d["pos"][:, 2].min() + d["pos"][:, 2].max()) < 1e-3))
            c, rad = d["centros"], d["radios"]
            r.append(check("reconoce las 4 ruedas: delanteras en +z, traseras "
                           "en -z, izquierdas en -x",
                           c[1][2] > 0.5 and c[2][2] > 0.5 and c[3][2] < -0.5
                           and c[4][2] < -0.5 and c[1][0] < -0.3 and c[3][0] < -0.3
                           and c[2][0] > 0.3 and c[4][0] > 0.3,
                           f"DI {c[1].round(2)} TD {c[4].round(2)}"))
            r.append(check("...con radios de rueda de F1 (0,3 a 0,4 m)",
                           all(0.28 < rad[k] < 0.42 for k in range(1, 5)),
                           str(rad[1:].round(2))))
            r.append(check("...y la carroceria es la pieza grande",
                           (d["parte"] == 0).sum() > 4 * (d["parte"] == 1).sum()))
            texs = [d.get(f"tex{i}") for i in range(int(d["n_texturas"]))]
            r.append(check("decodifica las 3 texturas a 1024 px como mucho",
                           len(texs) == 3 and all(t is not None and t.ndim == 3
                                                  and max(t.shape[:2]) <= 1024
                                                  for t in texs),
                           str([t.shape for t in texs if t is not None])))
            r.append(check("el .npz cabe en el repositorio (< 3 MB)",
                           os.path.getsize(ruta) < 3e6,
                           f"{os.path.getsize(ruta) / 1e6:.2f} MB"))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)
    else:
        print("[AVISO] sin el .glb original: se salta la importacion")

    # --- carga ----------------------------------------------------------------
    f1 = modelo3d.cargar("f1")
    r.append(check("modelo3d.cargar('f1') lee el modelo versionado",
                   f1 is not None and len(f1["idx"]) // 3 == 31176))
    r.append(check("...y un nombre inexistente da None (coche de cajas)",
                   modelo3d.cargar("no_existe") is None
                   and modelo3d.cargar("") is None))
    r.append(check("...y se cachea", modelo3d.cargar("f1") is f1))

    # --- pintado en la GPU ---------------------------------------------------
    import ctypes
    import sdl2
    from simulator import gpu
    from simulator import render as render_mod
    from simulator.physics import Car
    from simulator.track import Track
    W, H = 640, 400
    cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT, cfg.WINDOW_AUTO = W, H, False
    sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
    win = sdl2.SDL_CreateWindow(b"t", 0, 0, W, H, sdl2.SDL_WINDOW_HIDDEN)
    ren = sdl2.SDL_CreateRenderer(win, -1, 0)
    escena = gpu.GpuScene(ren, W, H, msaa=4)
    if not escena.ok or f1 is None:
        print(f"[AVISO] sin OpenGL aqui ({escena.motivo}): se salta el pintado")
    else:
        def leer():
            buf = (ctypes.c_uint8 * (W * H * 4))()
            sdl2.SDL_RenderReadPixels(ren, None, sdl2.SDL_PIXELFORMAT_ABGR8888,
                                      buf, W * 4)
            return np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 4).astype(int)
        cfg.TRACK_FILE = "tracks/c-90.csv"
        pista = Track()
        scene = render_mod.Renderer(ren)
        scene.gpu = escena
        st = Car().state
        st.s, st.vx = 3000.0, 30.0
        st.omega[:] = [80.0, 80.0, 80.0, 80.0]
        cfg.GFX_GPU_ASYNC = False
        cfg.CAR_MODEL_3D = "f1"
        sdl2.SDL_RenderClear(ren)
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=None)
        sdl2.SDL_RenderPresent(ren)
        sin = leer()
        coche = scene.modelo_coche(0.3, 1 / 60.0)
        r.append(check("modelo_coche devuelve los datos del modelo",
                       coche is not None and coche["datos"] is f1))
        sdl2.SDL_RenderClear(ren)
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=coche)
        sdl2.SDL_RenderPresent(ren)
        con = leer()
        r.append(check("la escena dice que ha pintado el modelo",
                       scene.coche_gpu and escena.coche_dibujado))
        dif = (np.abs(con - sin)[:, :, :3].sum(axis=2) > 30)
        r.append(check("el coche se ve: miles de pixeles cambian respecto a la "
                       "vista sin coche", dif.sum() > 3000, f"{dif.sum()} px"))
        ys, xs = np.nonzero(dif)
        r.append(check("...abajo, en el centro (donde esta el coche desde la "
                       "camara de persecucion)",
                       len(xs) > 0 and abs(xs.mean() - W / 2) < W * 0.12
                       and ys.mean() > H * 0.5,
                       f"centro ({xs.mean():.0f}, {ys.mean():.0f})"))
        r.append(check("...y con la textura/materiales, no de un solo color",
                       len(np.unique(con[dif][:, :3] // 16, axis=0)) > 12))
        mg = escena._modelo_gpu
        ang0 = mg.ang.copy()
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=scene.modelo_coche(0.0, 0.05))
        r.append(check("las ruedas ruedan con la velocidad de la fisica "
                       "(80 rad/s x 0,05 s = 4 rad)",
                       np.allclose((mg.ang - ang0) % (2 * np.pi), 4.0 % (2 * np.pi),
                                   atol=1e-6), str((mg.ang - ang0).round(3))))
        r.append(check("el modelo se pinta rapido (GL < 40 ms incluso por "
                       "software)", escena.ms_gl < 40.0,
                       f"{escena.ms_gl:.1f} ms"))
        # sin modelo: coche de cajas, como siempre
        cfg.CAR_MODEL_3D = ""
        r.append(check("con CAR_MODEL_3D vacio no hay modelo",
                       scene.modelo_coche(0.0, 0.0) is None))
        sdl2.SDL_RenderClear(ren)
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=None)
        r.append(check("...y la escena no marca coche pintado",
                       not scene.coche_gpu))
        cfg.CAR_MODEL_3D = "f1"
        escena.close()

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
