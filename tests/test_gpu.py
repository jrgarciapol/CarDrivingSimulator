"""Pruebas de la escena 3D en la GPU (simulator/gpu.py).

Dos bloques:

  - GEOMETRIA, sin OpenGL: que la proyeccion de la GPU reproduzca EXACTAMENTE
    la del render de SDL (misma perspectiva, mismo cabeceo), y que el eje de
    la carretera integrado en numpy coincida con la geometria exacta de una
    recta y de un arco de circulo.

  - FOTOGRAMAS REALES, con OpenGL si lo hay (Mesa por software vale): se
    pinta la C-90 y se comprueban los pixeles: cielo arriba, asfalto abajo en
    el centro, hierba en la esquina, el sol donde se calculo, y en el ovalo
    peraltado el horizonte inclinado hacia el lado correcto. Si no hay
    OpenGL, ese bloque se salta y lo dice.

    python tests/test_gpu.py
"""

import ctypes
import math
import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

import numpy as np                                    # noqa: E402
import sdl2                                           # noqa: E402

from simulator import config as cfg                   # noqa: E402
from simulator import gpu                             # noqa: E402
from simulator.track import Segment                   # noqa: E402


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return bool(cond)


class _Circuito:
    """Circuito minimo con curvatura constante, para la geometria."""

    def __init__(self, kappa, n=600, y=0.0, bank=0.0):
        self.segments = [Segment(i, kappa, y, False, bank) for i in range(n)]
        self.length = n * cfg.SEGMENT_LENGTH
        self.line_n = [0.0] * n
        self.line_v_allowed = [50.0] * n
        self.half_w = cfg.ROAD_HALF_WIDTH


def _camara(f=1.2, pitch_px=0.0, psi=0.0, extra_y=1.35, mesh_dx=0.0,
            cam_forward=0.0, cam_back=0.0):
    return SimpleNamespace(f=f, extra_y=extra_y, pitch_px=pitch_px, psi_c=psi,
                           mesh_dx=mesh_dx, cam_forward=cam_forward,
                           cam_back=cam_back, onboard=(cam_back == 0.0))


def main():
    r = []
    W, H = 640, 400
    guardado = {k: getattr(cfg, k) for k in
                ("WINDOW_WIDTH", "WINDOW_HEIGHT", "WINDOW_AUTO", "GFX_GPU",
                 "TRACK_FILE", "TRACK_POLES", "CHEVRON_MAX_RADIUS",
                 "GFX_FOG_DIST", "GFX_SUN_SHADE", "DRAW_DISTANCE")}
    cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT, cfg.WINDOW_AUTO = W, H, False

    # ================================================================
    # 1. La proyeccion es la del render de SDL, punto por punto
    # ================================================================
    f, pitch_px = 1.2, 23.0
    P = gpu._mat_proyeccion(f, pitch_px / (H / 2.0))
    rng = np.random.default_rng(7)
    pts = rng.uniform([-30.0, -6.0, 1.0], [30.0, 6.0, 900.0], (300, 3))
    clip = (P @ np.c_[pts, np.ones(len(pts))].T).T
    ndc = clip[:, :3] / clip[:, 3:4]
    sx = W / 2 + ndc[:, 0] * (W / 2)
    sy = H / 2 + ndc[:, 1] * (H / 2)            # y volteada: fila de imagen
    esp_x = W / 2 + f * pts[:, 0] / pts[:, 2] * (W / 2)
    esp_y = H / 2 - f * pts[:, 1] / pts[:, 2] * (H / 2) + pitch_px
    r.append(check("la proyeccion reproduce sx = W/2 + f*x/z*W/2",
                   np.allclose(sx, esp_x, atol=1e-6)))
    r.append(check("...y sy = H/2 - f*y/z*H/2 + pitch_px (cabeceo incluido)",
                   np.allclose(sy, esp_y, atol=1e-6)))
    zs = np.array([gpu.Z_CERCA, 1.0, 10.0, 100.0, gpu.Z_LEJOS])
    prof = (P @ np.c_[np.zeros(5), np.zeros(5), zs, np.ones(5)].T).T
    prof = prof[:, 2] / prof[:, 3]
    r.append(check("la profundidad va de -1 (cerca) a +1 (lejos) y crece",
                   abs(prof[0] + 1) < 1e-9 and abs(prof[-1] - 1) < 1e-9
                   and np.all(np.diff(prof) > 0), str(np.round(prof, 3))))

    # ================================================================
    # 2. El eje integrado coincide con la geometria exacta
    # ================================================================
    esc = gpu.GpuScene(None, W, H, sin_gl=True)
    recta = _Circuito(0.0)
    e = esc.eje(recta, 500.0)
    j0 = int(np.argmin(np.abs(e["rels"])))
    r.append(check("recta: las secciones quedan sobre el eje z",
                   np.abs(e["x"]).max() < 1e-9
                   and np.allclose(e["z"], e["rels"])))
    r.append(check("el coche esta exactamente en el origen",
                   e["x"][j0] == 0.0 and e["z"][j0] == 0.0
                   and e["rels"][j0] == 0.0))
    r.append(check("la malla llega 40 m por detras y DRAW_DISTANCE por delante",
                   e["rels"][0] == -40.0
                   and e["rels"][-1] >= cfg.DRAW_DISTANCE * cfg.SEGMENT_LENGTH - 4.0,
                   f"{e['rels'][0]} .. {e['rels'][-1]}"))
    R = 100.0
    esc2 = gpu.GpuScene(None, W, H, sin_gl=True)
    e = esc2.eje(_Circuito(1.0 / R), 500.0)
    d = e["rels"]
    esp_x = R * (1.0 - np.cos(d / R))
    esp_z = R * np.sin(d / R)
    err = np.hypot(e["x"] - esp_x, e["z"] - esp_z)
    r.append(check("arco de 100 m: el eje sigue el circulo (error < 0.1 m)",
                   err.max() < 0.1, f"error maximo {err.max():.4f} m"))
    r.append(check("curva a la derecha: el eje se va hacia +x",
                   e["x"][-1] > 0 and e["x"][0] > 0))
    # el vector derecha gira con el rumbo: perpendicular a la tangente
    tang = np.stack([np.gradient(e["x"], d), np.gradient(e["z"], d)], 1)
    tang /= np.linalg.norm(tang, axis=1)[:, None]
    dere = np.stack([e["hx"], e["hz"]], 1)
    prod = np.abs((tang * dere).sum(1))
    r.append(check("el vector derecha es perpendicular a la tangente",
                   prod[5:-5].max() < 0.02, f"max |t.r| {prod[5:-5].max():.4f}"))

    # ================================================================
    # 3. Rumbo con el cierre repartido: sin salto en la meta
    # ================================================================
    esc3 = gpu.GpuScene(None, W, H, sin_gl=True)
    # un "circuito" que no cierra: 3/4 de vuelta
    n = 600
    abierto = _Circuito(2 * math.pi * 0.75 / (n * cfg.SEGMENT_LENGTH), n)
    esc3._preparar(abierto)
    salto = abs((esc3.rumbo[-1] + abierto.segments[-1].kappa * cfg.SEGMENT_LENGTH
                 - esc3.rumbo[0] + math.pi) % (2 * math.pi) - math.pi)
    r.append(check("el rumbo del cielo no da un salto al cruzar la meta",
                   salto < 0.02, f"salto {math.degrees(salto):.2f} grados"))

    # ================================================================
    # 4. Coste de la geometria (lo que antes hacia un bucle de Python)
    # ================================================================
    from simulator.track import Track
    cfg.TRACK_FILE = "tracks/c-90.csv"
    c90 = Track()
    esc4 = gpu.GpuScene(None, W, H, sin_gl=True)
    esc4.eje(c90, 3000.0)
    t0 = time.perf_counter()
    for i in range(50):
        esc4.eje(c90, 3000.0 + i * 0.4)
    ms = (time.perf_counter() - t0) / 50 * 1000
    r.append(check("el eje de la C-90 se construye en menos de 5 ms",
                   ms < 5.0, f"{ms:.2f} ms"))

    # ================================================================
    # 5. Fotogramas reales (si hay OpenGL)
    # ================================================================
    sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
    win = sdl2.SDL_CreateWindow(b"t", 0, 0, W, H, sdl2.SDL_WINDOW_HIDDEN)
    ren = sdl2.SDL_CreateRenderer(win, -1, 0)
    sdl2.SDL_SetRenderDrawBlendMode(ren, sdl2.SDL_BLENDMODE_BLEND)
    from simulator import render as render_mod
    from simulator.physics import Car

    def leer():
        buf = (ctypes.c_uint8 * (W * H * 4))()
        sdl2.SDL_RenderReadPixels(ren, None, sdl2.SDL_PIXELFORMAT_ABGR8888,
                                  buf, W * 4)
        return np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 4).copy()

    escena = gpu.GpuScene(ren, W, H, msaa=4)
    if not escena.ok:
        print(f"[AVISO] sin OpenGL aqui ({escena.motivo}): se saltan las "
              "pruebas de fotogramas reales")
    else:
        pal = render_mod.paleta()
        st = Car().state
        st.s, st.vx = 3000.0, 25.0
        cam = _camara(cam_forward=cfg.CAMERA_FORWARD)
        cfg.GFX_GPU_ASYNC = False        # aqui se comprueba fotograma a fotograma
        sdl2.SDL_RenderClear(ren)
        escena.dibujar(c90, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        img = leer().astype(int)
        img_c90 = img.copy()
        st_c90 = (st.s, st.vx)
        arriba = img[8, W // 2]
        abajo = img[H - 8, W // 2 + 60]
        # la hierba se ve a los lados justo bajo el horizonte; el rincon
        # inferior de la pantalla es asfalto (con el ojo a 1,35 m, la fila
        # de abajo esta a 1,6 m del coche, dentro de la calzada)
        esquina = img[int(H * 0.56), 6]
        r.append(check("arriba hay cielo (azul)", arriba[2] > arriba[0] + 40,
                       str(arriba[:3])))
        r.append(check("abajo en el centro hay asfalto (gris oscuro)",
                       abajo[:3].max() - abajo[:3].min() < 14 and abajo[0] < 120,
                       str(abajo[:3])))
        r.append(check("a los lados, bajo el horizonte, hay hierba (verde)",
                       esquina[1] > esquina[0] + 40 and esquina[1] > esquina[2],
                       str(esquina[:3])))
        r.append(check("la imagen no es plana", img[:, :, :3].std() > 20))
        # el sol esta donde se calculo (con el peralte de la camara incluido)
        # y es REDONDO en pixeles, aunque la proyeccion no sea isotropa
        sol = escena._sol_px
        if sol is not None and 40 < sol[0] < W - 40 and 40 < sol[1] < H - 40:
            sx_, sy_ = int(sol[0]), int(sol[1])
            centro = img[sy_, sx_]
            r.append(check("el sol es blanco donde se calculo",
                           centro[:3].min() > 235, str(centro[:3])))
            blanco = ((img[:, :, 0] > 245) & (img[:, :, 1] > 240)
                      & (img[:, :, 2] > 225))[: H // 2]
            ys_, xs_ = np.nonzero(blanco)
            ancho = xs_.max() - xs_.min() + 1
            alto = ys_.max() - ys_.min() + 1
            r.append(check("y es redondo: mismo ancho que alto en pixeles",
                           abs(ancho - alto) <= max(2, 0.1 * alto)
                           and abs(xs_.mean() - sx_) < 3
                           and abs(ys_.mean() - sy_) < 3,
                           f"{ancho}x{alto} px, centro "
                           f"({xs_.mean():.0f}, {ys_.mean():.0f})"))
        else:
            print(f"[AVISO] el sol no esta en pantalla en s=3000 ({sol})")

        # world_to_screen: un punto 60 m por delante, en el eje, cae en el
        # centro horizontal y a la altura que da la formula
        p = escena.world_to_screen(c90, st.s + 60.0, 0.0, 0.0)
        r.append(check("world_to_screen devuelve el punto de delante",
                       p is not None))
        if p is not None:
            # en una carretera casi recta el punto esta a x~0; la altura la
            # da la elevacion relativa, que aqui no se conoce: se comprueba
            # solo la coherencia con la caché
            r.append(check("...centrado horizontalmente (curvatura leve)",
                           abs(p[0] - W / 2) < W * 0.25, f"sx={p[0]:.0f}"))
            r.append(check("...con la escala de pixeles por metro f/z*W/2",
                           abs(p[2] - cam.f / 60.0 * (W / 2)) / p[2] < 0.15,
                           f"{p[2]:.2f} px/m"))

        # --- ovalo peraltado: el horizonte se inclina hacia el lado bueno ---
        cfg.TRACK_FILE = "tracks/ovalo.csv"
        ov = Track()
        bancos = np.array([s.bank for s in ov.segments])
        i_max = int(np.argmax(np.abs(bancos)))       # la curva mas peraltada
        st.s = i_max * cfg.SEGMENT_LENGTH + 2.0
        sdl2.SDL_RenderClear(ren)
        escena.dibujar(ov, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        img = leer().astype(int)

        def horizonte(col):
            """Primera fila desde arriba que ya no es cielo (b <= g)."""
            for y in range(H):
                px = img[y, col]
                if px[2] <= px[1]:
                    return y
            return H
        izq, der = horizonte(40), horizonte(W - 40)
        # peralte > 0 = borde izquierdo alto: el coche se inclina a la derecha
        # y el horizonte sube por la derecha (fila menor). Con peralte < 0,
        # al reves. El ovalo tiene sus curvas a izquierdas: peralte negativo.
        if bancos[i_max] > 0:
            bien = der < izq
        else:
            bien = izq < der
        r.append(check("en la curva peraltada el horizonte se inclina hacia "
                       "el lado correcto",
                       abs(bancos[i_max]) > 0.05 and bien,
                       f"peralte {math.degrees(bancos[i_max]):.1f} grados, "
                       f"horizonte izq fila {izq}, der fila {der}"))

        # --- arboles en la hierba y balizas a estaciones fijas --------------
        st.s, st.vx = 3000.0, 25.0
        cfg.TRACK_TREES = False
        escena.dibujar(c90, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        sin_arb = leer().astype(int)
        cfg.TRACK_TREES = True
        escena.dibujar(c90, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        con_arb = leer().astype(int)
        dif_arb = (np.abs(con_arb - sin_arb).sum(axis=2) > 30)
        r.append(check("con TRACK_TREES hay arboles a la vista (cambian pixeles "
                       "sobre la hierba y contra el cielo)", dif_arb.sum() > 300,
                       f"{dif_arb.sum()} px"))
        arb = escena._arboles_track
        r.append(check("...plantados con semilla fija: los mismos cada vez",
                       arb is not None and len(arb["s"]) > 50
                       and np.allclose(arb["s"], escena._plantar(c90)["s"])))
        cfg.TRACK_POLES = True
        cfg.CHEVRON_MAX_RADIUS = 0.0          # solo balizas en esta prueba
        e = escena.eje(c90, st.s)
        rels = e["rels"]
        # balizas: una cada 6 m exactos aunque la malla vaya a 1, 2 o 4 m
        escena._frame_s0 = st.s
        bill = escena._balizas(np.eye(4), e["x"], e["z"], e["hx"], e["hz"],
                               e["elev"], e["cb"], e["sb"], e["hw"], rels,
                               e["seg_idx"], e["sm"], cfg.KERB_WIDTH)
        r.append(check("las balizas se generan", bill is not None))
        if bill is not None:
            vb, _ = bill
            amarillas = (vb["col"][:, 0, 0] == 255) & (vb["col"][:, 0, 1] == 215)
            pts = vb["pos"][amarillas][:, 0, :]        # pie de cada baliza
            pts = np.unique(np.round(pts[:, [0, 2]], 2), axis=0)
            pts = pts[np.argsort(pts[:, 1])][:14]       # las 14 mas cercanas
            pasos = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
            n_esperado = int(700.0 / 6.0)
            r.append(check("...a estaciones equiespaciadas (6 m de cuerda), "
                           "sin grupos, y una cada 6 m hasta 700 m",
                           len(pasos) >= 12 and np.abs(pasos - 6.0).max() < 0.35
                           and abs(int(amarillas.sum()) - n_esperado) <= 2,
                           f"pasos {np.round(pasos[:6], 2)}, "
                           f"{int(amarillas.sum())} balizas (esperadas {n_esperado})"))

        # --- huellas de neumatico en el asfalto ------------------------------
        # anotadas como en main: cada rueda con su (s, n) e intensidad; se
        # guardan cada HUELLA_PASO m y un trazo se corta al dejar de derrapar
        st.s, st.vx = 3000.0, 25.0
        escena.dibujar(c90, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        sin_hue = leer().astype(int)
        L = c90.length
        for k in range(300):                       # 30 m de frenada a 0,1 m
            for i, dn in enumerate((0.8, -0.8, 0.8, -0.8)):
                escena.marcar_huella(i, 3004.0 + k * 0.1 + (1.3 if i < 2 else -1.3),
                                     dn, 1.0, L)
        n1 = escena._huellas_n
        r.append(check("las huellas se guardan como minimo cada 12 cm por rueda, "
                       "no cada fotograma (con muestras a 0,1 m queda una de "
                       "cada dos: 4 x 30 m / 0,2 = 600 puntos de 1200)",
                       580 <= n1 <= 620, f"{n1} puntos"))
        for i in range(4):
            escena.marcar_huella(i, 3040.0, 0.0, 0.0, L)      # deja de derrapar
        escena.marcar_huella(0, 3050.0, 0.8, 0.7, L)
        r.append(check("...y al dejar de derrapar el siguiente punto abre un "
                       "trazo nuevo (no se une con una linea al anterior)",
                       escena._huellas[escena._huellas_n - 1, 3]
                       != escena._huellas[0, 3]))
        escena.dibujar(c90, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        con_hue = leer().astype(int)
        dif_hue = (np.abs(con_hue - sin_hue).sum(axis=2) > 12)
        ys, xs = np.nonzero(dif_hue)
        r.append(check("con huellas cambian pixeles del asfalto por delante "
                       "(oscurecido, no en la hierba ni el cielo)",
                       escena.huellas_dibujadas > 500 and dif_hue.sum() > 200
                       and (con_hue[dif_hue][:, :3].mean()
                            < sin_hue[dif_hue][:, :3].mean())
                       and ys.min() > H * 0.45,
                       f"{escena.huellas_dibujadas} cuadrilateros, "
                       f"{dif_hue.sum()} px, filas {ys.min() if len(ys) else -1}.."))
        e = escena.eje(c90, st.s)
        geo = escena._huellas_geo(c90, st.s, e["rels"], e["x"], e["z"], e["hx"],
                                  e["hz"], e["elev"], e["cb"], e["sb"])
        v, _ = geo
        anchos = np.linalg.norm(v["pos"][:, 1] - v["pos"][:, 0], axis=1)
        cerca = v["pos"][:, 0, 2] < 6.0            # a menos de 6 m: eje ~ recto
        lat = 0.5 * (v["pos"][cerca, 0, 0] + v["pos"][cerca, 1, 0])   # x = lateral
        r.append(check("...cada cuadrilatero tiene el ancho del neumatico y "
                       "va a la posicion lateral de su rueda (+-0,8 m)",
                       np.allclose(anchos, 2 * gpu.HUELLA_SEMIANCHO, atol=1e-3)
                       and len(lat) > 4 and np.abs(np.abs(lat) - 0.8).max() < 0.25,
                       f"ancho {anchos.mean():.3f} m, |lat| "
                       f"{np.abs(lat).min():.2f}..{np.abs(lat).max():.2f}"))
        cfg.TRACK_SKID_MARKS = False
        escena.dibujar(c90, st, cam, True, pal)
        r.append(check("con TRACK_SKID_MARKS apagado no se pintan",
                       escena.huellas_dibujadas == 0))
        cfg.TRACK_SKID_MARKS = True
        # el anillo: al llenarse se olvidan las mas viejas, sin fallar
        viejo = gpu.HUELLAS_MAX
        gpu.HUELLAS_MAX = 64
        esc_h = gpu.GpuScene(None, W, H, sin_gl=True)
        for k in range(100):
            esc_h.marcar_huella(0, 3010.0 + k * 0.5, 0.5, 1.0, L)
        geo_h = esc_h._huellas_geo(c90, st.s, e["rels"], e["x"], e["z"], e["hx"],
                                   e["hz"], e["elev"], e["cb"], e["sb"])
        gpu.HUELLAS_MAX = viejo
        r.append(check("el anillo de huellas se llena y sigue: quedan las 64 "
                       "ultimas (63 tramos)",
                       esc_h._huellas_n == 64 and geo_h is not None
                       and len(geo_h[1]) // 6 == 63,
                       f"{esc_h._huellas_n} puntos, "
                       f"{0 if geo_h is None else len(geo_h[1]) // 6} tramos"))

        # --- peralte: el suelo bajo el coche queda a la altura del coche ---
        # Se reporto que en el ovalo "la pista se queda arriba y el coche
        # sigue a la misma cota": la camara iba a la cota del EJE, y con el
        # coche a n metros del eje en un peralte fuerte el asfalto bajo el
        # esta n*tan(peralte) mas alto o mas bajo. Un punto de la calzada
        # 8 m por delante, en la misma posicion lateral que el coche, debe
        # proyectarse a la misma fila de pantalla que en un tramo llano.
        st.s, st.vx = 3000.0, 25.0
        st.n = 0.0
        cam_c = _camara(cam_forward=cfg.CAMERA_FORWARD)
        cam_c.mesh_dx = 0.0
        escena.dibujar(c90, st, cam_c, True, pal)
        fila_llano = escena.world_to_screen(c90, st.s + 8.0, 0.0, 0.0)[1]
        filas = []
        for n_lat in (6.0, -6.0):
            st.s = i_max * cfg.SEGMENT_LENGTH + 2.0
            st.n = n_lat
            cam_b = _camara(cam_forward=cfg.CAMERA_FORWARD)
            cam_b.mesh_dx = -n_lat
            escena.dibujar(ov, st, cam_b, True, pal)
            filas.append(escena.world_to_screen(ov, st.s + 8.0, n_lat, 0.0)[1])
        r.append(check("en el peralte, el asfalto bajo el coche queda a su "
                       "altura tanto por el lado alto como por el bajo",
                       all(abs(f - fila_llano) < 12 for f in filas),
                       f"fila llano {fila_llano:.0f}, peralte "
                       f"{filas[0]:.0f} / {filas[1]:.0f}"))
        st.n = 0.0

        # --- balizas y chevrons por la GPU: se dibujan y quedan a la vista ---
        cfg.TRACK_FILE = "tracks/c-50.csv"
        c50 = Track()
        cfg.TRACK_POLES = True
        cfg.CHEVRON_MAX_RADIUS = 200.0
        st.s, st.vx = 1450.0, 18.0
        sdl2.SDL_RenderClear(ren)
        escena.dibujar(c50, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        r.append(check("cambiar de circuito borra las huellas de neumatico",
                       escena._huellas_n == 0))
        img = leer().astype(int)
        amarillo = ((img[:, :, 0] > 200) & (img[:, :, 1] > 170)
                    & (img[:, :, 2] < 90)).sum()
        rojo = ((img[:, :, 0] > 150) & (img[:, :, 1] < 80)
                & (img[:, :, 2] < 80)).sum()
        r.append(check("hay balizas amarillas en pantalla", amarillo > 20,
                       f"{amarillo} px"))
        r.append(check("hay galones rojos de chevron en pantalla", rojo > 20,
                       f"{rojo} px"))
        # (tope holgado: en la maquina de pruebas, cargada, ronda los 5-9 ms;
        # lo que se vigila es que no se dispare a decenas)
        r.append(check("el coste de la malla con balizas sigue bajo",
                       escena.ms_malla < 12.0, f"{escena.ms_malla:.1f} ms"))
        img_c50 = img.copy()

        # --- lectura ASINCRONA: un fotograma de retraso, y nunca uno viejo --
        st.s, st.vx = st_c90
        sdl2.SDL_RenderClear(ren)
        escena.dibujar(c90, st, cam, True, pal)      # referencia, al momento
        sdl2.SDL_RenderPresent(ren)
        img_c90 = leer().astype(int)
        cfg.GFX_GPU_ASYNC = True
        sdl2.SDL_RenderClear(ren)
        escena.dibujar(c90, st, cam, True, pal)      # primer fotograma
        sdl2.SDL_RenderPresent(ren)                  # asincrono: no hay
        a = leer().astype(int)                       # anterior, se lee ya
        r.append(check("asincrona: el primer fotograma se lee al momento "
                       "(no hay anterior que mostrar)",
                       np.array_equal(a, img_c90)))
        st.s, st.vx = 3300.0, 30.0                   # mismo circuito, otro sitio
        sdl2.SDL_RenderClear(ren)
        escena.dibujar(c90, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        b = leer().astype(int)
        r.append(check("asincrona: el siguiente muestra el fotograma ANTERIOR",
                       np.array_equal(b, img_c90) and escena.asincrono))
        r.append(check("...y world_to_screen proyecta con la camara del "
                       "fotograma que se ve", escena._frame[0] == st_c90[0],
                       f"s0={escena._frame[0]}"))
        sdl2.SDL_RenderClear(ren)
        escena.dibujar(c90, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        c = leer().astype(int)
        r.append(check("...y al siguiente ya sale el nuevo sitio",
                       not np.array_equal(c, img_c90)
                       and escena._frame[0] == 3300.0))
        cfg.GFX_GPU_ASYNC = False
        st.s, st.vx = 1450.0, 18.0
        sdl2.SDL_RenderClear(ren)
        escena.dibujar(c50, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        d = leer().astype(int)
        r.append(check("con GFX_GPU_ASYNC=False vuelve la lectura al momento "
                       "(mismo fotograma que antes)",
                       np.array_equal(d, img_c50) and not escena.asincrono))
        r.append(check("la lectura se mide aparte (ms_lectura)",
                       escena.ms_lectura > 0.0, f"{escena.ms_lectura:.2f} ms"))
        escena.close()

    # ================================================================
    # 6. Sin GPU, el juego sigue con SDL y la misma interfaz
    # ================================================================
    cfg.GFX_GPU = False
    gpu._escena = None
    cfg.TRACK_FILE = "tracks/c-90.csv"
    esc_sdl = render_mod.Renderer(ren)
    r.append(check("con GFX_GPU apagado el Renderer no tiene GPU",
                   esc_sdl.gpu is None))
    st = Car().state
    st.s, st.vx = 3000.0, 25.0
    sdl2.SDL_RenderClear(ren)
    esc_sdl.draw_scene(c90, st, True, cfg.CAMERA_HEIGHT, 0.0, None,
                       cfg.CAMERA_FORWARD, H // 2, 0.0)
    p = esc_sdl.world_to_screen(c90, st.s + 60.0, 0.0, 0.0)
    r.append(check("el render de SDL dibuja y proyecta como siempre",
                   p is not None and abs(p[0] - W / 2) < W * 0.25))
    r.append(check("obtener() respeta GFX_GPU apagado",
                   gpu.obtener(ren) is None))
    from simulator.wheel import WheelInput
    hud = render_mod.Hud(ren)
    try:
        hud.draw_debug(WheelInput(), st, "road", escena if escena.ok else None)
        hud.draw_debug(WheelInput(), st, "road", None)
        ok_debug = True
    except Exception as e:                            # noqa: BLE001
        ok_debug = False
        print("   ", type(e).__name__, e)
    r.append(check("el panel F1 muestra el coste de la GPU sin fallar", ok_debug))

    # el preset de rendimiento no apaga la bruma cuando va por la GPU
    from simulator.main import preset_rendimiento
    cfg.GFX_GPU, cfg.GFX_FOG_DIST = True, 600.0
    preset_rendimiento()
    con_gpu = cfg.GFX_FOG_DIST
    cfg.GFX_GPU, cfg.GFX_FOG_DIST = False, 600.0
    preset_rendimiento()
    sin_gpu = cfg.GFX_FOG_DIST
    r.append(check("el preset de la Deck conserva la bruma con GPU y la "
                   "apaga sin ella", con_gpu == 600.0 and sin_gpu == 0.0))

    gpu._escena = None
    for k, v in guardado.items():
        setattr(cfg, k, v)
    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
