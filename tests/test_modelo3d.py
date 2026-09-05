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
MODELOS = os.path.join(RAIZ, "simulator", "models")
GLB_2CV = os.path.join(MODELOS, "free_2cv_charleston_1986 (1).glb")
GLB_BUS = os.path.join(MODELOS, "japanese_bus_nagoya_city_bus_aichi.glb")
GLB_BUGATTI = os.path.join(MODELOS, "1936_bugatti_type_57sc_atlantic.glb")


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return bool(cond)


def main():
    r = []
    # --- importacion: tres modelos de Sketchfab, cada uno a su manera ---------
    if all(os.path.exists(g) for g in (GLB_2CV, GLB_BUS, GLB_BUGATTI)):
        import importar_modelo
        carpeta = tempfile.mkdtemp(prefix="modelo_")
        try:
            # 2CV: en centimetros, morro hacia -z, las 4 ruedas en UNA malla
            ruta, d = importar_modelo.convertir(GLB_2CV, "p2cv", carpeta=carpeta,
                                                escala=0.01, frente="-z",
                                                max_tri=100000)
            m = d["medidas"]
            r.append(check("2CV: de centimetros a metros (1,7 x 1,6 x 4,0 m)",
                           1.5 < m[0] < 1.9 and 1.4 < m[1] < 1.8 and 3.7 < m[2] < 4.3,
                           f"{m[0]:.2f} x {m[1]:.2f} x {m[2]:.2f}"))
            r.append(check("...simplificado por debajo del tope pedido",
                           len(d["idx"]) // 3 <= 100000 and d["celda"] > 0,
                           f"{len(d['idx']) // 3} tri, celda {d['celda'] * 100:.1f} cm"))
            r.append(check("...el suelo en y = 0 (a menos de 5 mm, lo que mueve "
                           "la simplificacion) y centrado en x/z",
                           abs(d["pos"][:, 1].min()) < 5e-3
                           and abs(d["pos"][:, 0].min() + d["pos"][:, 0].max()) < 1e-3
                           and abs(d["pos"][:, 2].min() + d["pos"][:, 2].max()) < 1e-3))
            c, rad = d["centros"], d["radios"]
            r.append(check("...la malla de cuatro ruedas se parte en cuartos: "
                           "delanteras +z, traseras -z, izquierdas -x",
                           d["metodo_ruedas"].startswith("malla de cuatro")
                           and c[1][2] > 0.5 and c[2][2] > 0.5 and c[3][2] < -0.5
                           and c[4][2] < -0.5 and c[1][0] < -0.3 and c[2][0] > 0.3
                           and all(0.25 < rad[k] < 0.40 for k in range(1, 5)),
                           f"DI {c[1].round(2)} TD {c[4].round(2)} r {rad[1:].round(2)}"))
            texs = [d.get(f"tex{i}") for i in range(int(d["n_texturas"]))]
            usadas = [t for t in texs if t is not None]
            r.append(check("...solo decodifica las texturas que usa, a 1024 px "
                           "como mucho", 0 < len(usadas) < len(texs)
                           and all(max(t.shape[:2]) <= 1024 for t in usadas),
                           f"{len(usadas)} de {len(texs)}"))
            # autobus: una sola malla, morro hacia +x, lejos del origen
            ruta, d = importar_modelo.convertir(GLB_BUS, "pbus", carpeta=carpeta,
                                                frente="+x")
            m = d["medidas"]
            r.append(check("autobus: girado de +x a +z y recentrado "
                           "(2,9 x 3,1 x 10,9 m)",
                           2.7 < m[0] < 3.1 and 2.9 < m[1] < 3.3 and 10.5 < m[2] < 11.2
                           and abs(d["pos"][:, 2].min() + d["pos"][:, 2].max()) < 1e-3,
                           f"{m[0]:.2f} x {m[1]:.2f} x {m[2]:.2f}"))
            r.append(check("...de una sola malla: va entero, sin trocearlo en "
                           "ruedas (antes salia hecho pedazos)",
                           d["metodo_ruedas"].startswith("sin ruedas")
                           and (d["parte"] == 0).all()))
            # bugatti: 861.000 triangulos, morro +x, TRES ruedas sueltas
            ruta, d = importar_modelo.convertir(GLB_BUGATTI, "pbug", carpeta=carpeta,
                                                frente="+x", max_tri=150000)
            c, rad = d["centros"], d["radios"]
            r.append(check("bugatti: de 861.000 a menos de 150.000 triangulos",
                           len(d["idx"]) // 3 <= 150000, f"{len(d['idx']) // 3}"))
            r.append(check("...las 4 ruedas del mismo radio (0,34 m), la cuarta "
                           "en espejo, y no los tambores de freno (0,22)",
                           d["metodo_ruedas"] == "ruedas sueltas"
                           and all(abs(rad[k] - 0.34) < 0.03 for k in range(1, 5))
                           and abs(c[1][0] + c[2][0]) < 0.02,
                           f"r {rad[1:].round(2)}"))
            r.append(check("...y con el suelo en las ruedas el coche mide 1,4 m "
                           "de alto", 1.3 < d["medidas"][1] < 1.5,
                           f"{d['medidas'][1]:.2f}"))
        finally:
            shutil.rmtree(carpeta, ignore_errors=True)
    else:
        print("[AVISO] sin los .glb originales: se salta la importacion")

    # --- cada coche tiene su modelo y el archivo existe --------------------
    from simulator import garage
    faltan = []
    for f in sorted(os.listdir(garage.CARS_DIR)):
        if not f.endswith(".car"):
            continue
        garage.load_car(os.path.join(garage.CARS_DIR, f))
        nom = getattr(cfg, "CAR_MODEL_3D", "")
        if not nom or not os.path.exists(modelo3d.ruta(nom)):
            faltan.append(f"{f}:{nom or '(sin modelo)'}")
    r.append(check("los 8 coches tienen modelo 3D y su .npz existe",
                   not faltan, str(faltan)))
    garage.load_car(os.path.join(garage.CARS_DIR, "8_autobus.car"))
    r.append(check("el autobus aleja y sube la camara exterior (16 m, 5 m)",
                   cfg.CAMERA_BACK_CHASE == 16.0 and cfg.CAMERA_HEIGHT_CHASE == 5.0))
    garage.load_car(os.path.join(garage.CARS_DIR, "3_deportivo.car"))
    r.append(check("...y al cambiar de coche la camara vuelve a la de serie",
                   cfg.CAMERA_BACK_CHASE == 6.5 and cfg.CAR_MODEL_3D == "bugatti"))
    # la tecla C pasa por tres camaras sobre la misma escena; las dos
    # exteriores tienen altura y distancia propias, y son claves del coche
    r.append(check("la camara trasera cercana tiene altura y distancia propias",
                   0.0 < cfg.CAMERA_HEIGHT_REAR < cfg.CAMERA_HEIGHT_CHASE
                   and 0.0 < cfg.CAMERA_BACK_REAR < cfg.CAMERA_BACK_CHASE,
                   f"trasera {cfg.CAMERA_HEIGHT_REAR}/{cfg.CAMERA_BACK_REAR} m, "
                   f"exterior {cfg.CAMERA_HEIGHT_CHASE}/{cfg.CAMERA_BACK_CHASE} m"))
    r.append(check("...y las cuatro son ajustes del coche (se guardan en el .car)",
                   {"CAMERA_HEIGHT_REAR", "CAMERA_BACK_REAR", "CAMERA_HEIGHT_CHASE",
                    "CAMERA_BACK_CHASE"} <= garage.CAR_KEYS))

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
        st.omega[:] = [8.0, 8.0, 8.0, 8.0]
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
        # cada grupo de pintado lleva SOLO triangulos de su pieza: con el
        # Rolls (67 texturas) la clave pieza*16+textura desbordaba y dos
        # tercios de la carroceria giraban con las ruedas delanteras
        rolls = modelo3d.cargar("rolls")
        if rolls is not None:
            with escena._gl():
                mg_r = modelo3d.ModeloGpu(escena.ctx, rolls)
            tri_r = rolls["idx"].reshape(-1, 3)
            parte_r = rolls["parte"][tri_r[:, 0]].astype(int)
            n_cuerpo = int((parte_r == 0).sum())
            n_grupos_cuerpo = sum(n // 3 for pieza, _t, _p, n, _a in mg_r.grupos
                                  if pieza == 0)
            r.append(check("el Rolls (67 texturas) pinta toda su carroceria con "
                           "la matriz de la carroceria, no con la de una rueda",
                           n_grupos_cuerpo == n_cuerpo and len(mg_r.grupos) > 20,
                           f"{n_grupos_cuerpo} de {n_cuerpo} triangulos, "
                           f"{len(mg_r.grupos)} grupos"))
            with escena._gl():
                mg_r.release()
        ang0 = mg.ang.copy()
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=scene.modelo_coche(0.0, 0.05))
        r.append(check("las ruedas ruedan con la velocidad de la fisica "
                       "(8 rad/s x 0,05 s = 0,4 rad)",
                       np.allclose((mg.ang - ang0) % (2 * np.pi), 0.4, atol=1e-6),
                       str((mg.ang - ang0).round(3))))
        # y a mucha velocidad TAMBIEN (se probo congelarla por el efecto
        # estroboscopico y el resultado era "las ruedas no giran")
        st.omega[:] = [80.0, 80.0, 80.0, 80.0]
        ang1 = mg.ang.copy()
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=scene.modelo_coche(0.0, 0.05))
        r.append(check("...y a 80 rad/s siguen girando (4 rad en 0,05 s)",
                       np.allclose((mg.ang - ang1) % (2 * np.pi), 4.0 % (2 * np.pi),
                                   atol=1e-6)))
        # con bote, cabeceo y balanceo de la suspension, las ruedas siguen
        # apoyadas en el asfalto (solo se mueve la carroceria)
        st.omega[:] = [0.0, 0.0, 0.0, 0.0]
        st.heave, st.pitch, st.roll = 0.10, 0.08, 0.10
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=scene.modelo_coche(0.4, 0.0))
        mats = escena._mats_coche
        inv_base = np.linalg.inv(escena._base_coche)
        apoyadas = True
        for k in range(1, 5):
            c = np.r_[mg.centros[k], 1.0]
            p = inv_base @ mats[k] @ c          # centro de la rueda respecto
            # al chasis en el suelo: fijo en x/z, y solo se mueve con el
            # bache del firme bajo ella (a lo sumo 6 cm)
            if (abs(p[0] - c[0]) > 1e-6 or abs(p[2] - c[2]) > 1e-6
                    or abs(p[1] - c[1]) > 0.06):
                apoyadas = False
        cuerpo = inv_base @ mats[0]
        cuerpo_sube = cuerpo[1, 3] > 0.02
        r.append(check("con la suspension comprimida/cabeceando las ruedas "
                       "siguen en el asfalto y solo se mueve la carroceria",
                       apoyadas and cuerpo_sube))
        st.heave = st.pitch = st.roll = 0.0
        # --- sombra proyectada por el sol ----------------------------------
        # el sol esta por delante y algo a la derecha del rumbo (mismo
        # azimut que el disco del cielo), asi que la sombra se alarga hacia
        # ATRAS y a la izquierda del coche, mas alla del mapa de contacto
        sx, sz = mg.semi_sombra
        xmin, zmin, xmax, zmax = mg.rect_sombra
        r.append(check("con sol la sombra se alarga hacia atras (lado opuesto "
                       "al sol) mas alla del mapa de contacto",
                       zmin < -sz - 0.5 and zmax <= sz + 0.36 and xmin < -sx - 0.2,
                       f"rect {np.round(mg.rect_sombra, 2)} contacto +-{sx:.2f}/+-{sz:.2f}"))
        # la textura se lee con el contexto de la escena activo: fuera de
        # _gl() (contexto propio no activo) se leia basura
        with escena._gl():
            sil = np.frombuffer(mg.tex_proy.read(), dtype=np.uint8).reshape(
                modelo3d.SILUETA_PX, modelo3d.SILUETA_PX, 4)[:, :, 3]
        frac = (sil > 0).mean()
        r.append(check("la silueta del coche ocupa una parte razonable de su "
                       "textura (10..70 %)", 0.10 < frac < 0.70, f"{frac:.0%}"))
        # con el coche al reves (psi = pi) la sombra cae hacia su delante
        st.psi = np.pi
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=scene.modelo_coche(0.0, 0.0))
        xmin2, zmin2, xmax2, zmax2 = mg.rect_sombra
        r.append(check("...y girando el coche 180 grados la sombra gira con el "
                       "(ahora se alarga hacia su delante)",
                       zmax2 > sz + 0.5 and zmin2 >= -sz - 0.36,
                       f"rect {np.round(mg.rect_sombra, 2)}"))
        st.psi = 0.0
        # con lluvia no hay sol: solo la sombra de contacto
        render_mod.SUN_VISIBLE = False
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=scene.modelo_coche(0.0, 0.0))
        r.append(check("sin sol (lluvia) queda solo la sombra de contacto",
                       np.allclose(mg.rect_sombra, (-sx, -sz, sx, sz))))
        render_mod.SUN_VISIBLE = True
        scene.draw_scene(pista, st, True, 2.5, 6.5, 0.35, 0.0, None, 0.0,
                         coche3d=scene.modelo_coche(0.0, 0.0))
        r.append(check("el modelo se pinta rapido (GL < 80 ms incluso por "
                       "software; en una GPU real, menos de 1 ms)",
                       escena.ms_gl < 80.0, f"{escena.ms_gl:.1f} ms"))
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
