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
            cam_forward=0.0, cam_back=0.0, cam_pitch=0.0, cam_orto=None):
    return SimpleNamespace(f=f, extra_y=extra_y, pitch_px=pitch_px, psi_c=psi,
                           mesh_dx=mesh_dx, cam_forward=cam_forward,
                           cam_back=cam_back, onboard=(cam_back == 0.0),
                           cam_pitch=cam_pitch, cam_near=None, cam_orto=cam_orto)


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
        cfg.SKY_CLOUDS = 0.0             # las nubes derivan: fotogramas iguales
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
        cfg.TRACK_TREES = False        # un arbol en la columna tapaba el horizonte
        escena.dibujar(ov, st, cam, True, pal)
        cfg.TRACK_TREES = True
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

        # --- mobiliario: biondas, hitos kilometricos y senales de curva -----
        e = escena.eje(c90, 0.0)
        r.append(check("la c-90 lleva bionda en el exterior de sus curvas de "
                       "radio < 250 m (y no en las rectas)",
                       escena._bionda.sum() > 50
                       and escena._bionda.sum() < 0.5 * escena.N
                       and np.all(escena._lado_bionda[escena._bionda] != 0.0),
                       f"{int(escena._bionda.sum())} segmentos de {escena.N}"))
        k = escena.kap
        cur = np.nonzero(np.abs(k) >= 1.0 / 250.0)[0]
        lado_ok = np.all(escena._lado_bionda[cur] == np.where(k[cur] > 0, 1.0, -1.0))
        r.append(check("...a la derecha en las curvas a izquierdas y viceversa "
                       "(el exterior)", lado_ok))
        sen = escena._senales
        entradas = np.abs(k) >= 1.0 / 200.0
        n_ent = int((entradas & ~np.roll(entradas, 1)).sum())
        r.append(check("hay una senal de curva peligrosa 120 m antes de cada "
                       "entrada en curva de radio < 200 m",
                       len(sen) == n_ent and n_ent > 0,
                       f"{len(sen)} senales, {n_ent} entradas"))
        # geometria de la bionda al pasar por una curva con ella
        s_b = float(np.nonzero(escena._bionda)[0][10] * cfg.SEGMENT_LENGTH)
        e = escena.eje(c90, s_b)
        # (calzada llana y sin peralte: asi las alturas son sobre el asfalto)
        llano = np.zeros_like(e["elev"])
        mob = escena._mobiliario(s_b, e["rels"], e["x"], e["z"], e["hx"], e["hz"],
                                 llano, llano + 1.0, llano, e["hw"], cfg.KERB_WIDTH,
                                 e["sm"], 0.0)
        alturas = None if mob is None else mob[0]["pos"][:, 1]
        r.append(check("la bionda se construye: banda metalica entre 0,5 y "
                       "0,8 m sobre el asfalto y postes de 0,8 m",
                       mob is not None and len(mob[1]) // 6 > 20
                       and abs(alturas.max() - 0.8) < 1e-6 and alturas.min() >= 0.0
                       and (np.abs(alturas - 0.5) < 1e-6).any()
                       and (np.abs(alturas - 0.62) < 1e-6).any(),
                       f"{0 if mob is None else len(mob[1]) // 6} cuadrilateros"))
        # hitos: en s0 = 22900 el km 23 queda 100 m por delante (franja roja)
        cfg.CHEVRON_MAX_RADIUS = 0.0
        cfg.TRACK_POLES = False
        e = escena.eje(c90, 22900.0)
        escena._frame_s0 = 22900.0
        bill = escena._balizas(np.eye(4), e["x"], e["z"], e["hx"], e["hz"],
                               e["elev"], e["cb"], e["sb"], e["hw"], e["rels"],
                               e["seg_idx"], e["sm"], cfg.KERB_WIDTH)
        rojos = 0 if bill is None else int(((bill[0]["col"][:, 0, 0] == 205)
                                            & (bill[0]["col"][:, 0, 1] == 35)).sum())
        blancos = 0 if bill is None else int((bill[0]["col"][:, 0, 0] == 245).sum())
        r.append(check("hitos: desde s = 22900 se ven el hito del km 23 (franja "
                       "roja) y los hectometricos (blancos) cada 100 m",
                       rojos == 1 and blancos >= 6,
                       f"{rojos} franjas rojas, {blancos} hitos blancos"))
        cfg.TRACK_POLES = True
        cfg.CHEVRON_MAX_RADIUS = 200.0

        # --- estado_gpu.txt: por que se usa (o no) la GPU, legible en Modo Juego
        cfg.GFX_GPU = True
        gpu._escena = None
        esc_o = gpu.obtener(ren)
        txt = open(gpu.ESTADO_GPU, encoding="utf-8").read() if os.path.exists(gpu.ESTADO_GPU) else ""
        r.append(check("obtener() deja en estado_gpu.txt el render de GPU y la "
                       "version de moderngl del ultimo arranque",
                       esc_o is not None and "Render GPU:" in txt and "moderngl:" in txt,
                       txt.strip().replace(chr(10), " | ")[:120]))
        if esc_o is not None:
            esc_o.close()
        gpu._escena = None

        # --- grano procedural en asfalto y hierba (GFX_TEXTURAS) -------------
        st.s, st.vx = 3000.0, 25.0
        cfg.SKY_CLOUDS = 0.0
        cfg.GFX_TEXTURAS = False
        escena.dibujar(c90, st, cam, False, pal)       # sin trazada: solo suelo
        sdl2.SDL_RenderPresent(ren)
        liso = leer().astype(float)
        cfg.GFX_TEXTURAS = True
        escena.dibujar(c90, st, cam, False, pal)
        sdl2.SDL_RenderPresent(ren)
        con_grano = leer().astype(float)
        # asfalto cerca (mitad baja, centro) y hierba cerca (mitad baja, borde)
        za = (slice(int(H * 0.75), int(H * 0.95)), slice(int(W * 0.4), int(W * 0.6)))
        zh = (slice(int(H * 0.50), int(H * 0.60)), slice(0, int(W * 0.08)))
        sd_a0, sd_a1 = liso[za][:, :, 0].std(), con_grano[za][:, :, 0].std()
        sd_h0, sd_h1 = liso[zh][:, :, 1].std(), con_grano[zh][:, :, 1].std()
        dif = np.abs(con_grano - liso).mean(axis=2)[H // 2:].mean()
        r.append(check("con GFX_TEXTURAS el asfalto cercano tiene grano (liso "
                       "es plano, dispersion 0) y la hierba tambien, y la mitad "
                       "baja de la pantalla cambia",
                       sd_a1 > sd_a0 + 1.0 and sd_h1 > sd_h0 + 1.0 and dif > 1.0,
                       f"asfalto {sd_a0:.1f} -> {sd_a1:.1f}, hierba {sd_h0:.1f} -> "
                       f"{sd_h1:.1f}, dif {dif:.2f}"))
        r.append(check("...sin cambiar el tono medio (el grano modula, no tine)",
                       abs(con_grano[za].mean() - liso[za].mean()) < 6.0,
                       f"{liso[za].mean():.1f} -> {con_grano[za].mean():.1f}"))
        v = escena._vertices
        tipos = np.unique(v["col"][:, :, :, 3])
        r.append(check("las bandas llevan su tipo en el alfa: asfalto (254), "
                       "hierba (253) y liso (255: pianos y trazada)",
                       set(tipos.tolist()) == {253, 254, 255}, str(tipos)))
        # la estacion de cada vertice es la ABSOLUTA (modulo el periodo), asi
        # el grano queda fijo al mundo y no a la pantalla
        e = escena.eje(c90, st.s)
        s_esp = np.mod(np.mod(st.s + e["rels"], c90.length), gpu.PERIODO_TEX)
        r.append(check("...y la estacion absoluta modulo 1024 m en uv.x (grano "
                       "fijo al mundo), con el semiancho en uv.z",
                       np.allclose(v["uv"][4, :, 0, 0], s_esp[:-1], atol=1e-3)
                       and np.allclose(v["uv"][4, :, 0, 2], e["hw"][:-1], atol=1e-3)
                       and np.allclose(v["uv"][4, :, 0, 1], -e["hw"][:-1] + 0.42, atol=1e-3),
                       f"uv[0] {v['uv'][4, 0, 0]} esperado s {s_esp[0]:.2f}"))

        # --- vista ELEVADA: inclinacion real de la camara --------------------
        # con la camara a 9 m, 12 m atras y 28 grados hacia abajo, el
        # horizonte sube en pantalla y el cielo (sombreador) y la calzada
        # (malla) tienen que coincidir: la fila donde el cielo se vuelve
        # suelo en una columna sin carretera es la misma que la del punto
        # del eje a 600 m proyectado con la matriz de vista
        st.s, st.vx = 3000.0, 25.0
        cfg.SKY_CLOUDS = 0.0
        cam_e = _camara(extra_y=9.0, cam_back=12.0, psi=0.0,
                        cam_pitch=math.radians(28.0))
        escena.dibujar(c90, st, cam_e, True, pal)
        sdl2.SDL_RenderPresent(ren)
        alta = leer().astype(int)
        # horizonte del sombreador del cielo con la camara inclinada theta:
        # el rayo (ny/f) deshecha la inclinacion queda horizontal cuando
        # ny = f*tan(theta)  ->  fila = H/2 - ny*H/2
        fila_h = H / 2 - 1.2 * math.tan(math.radians(28.0)) * H / 2
        p_lejos = escena.world_to_screen(c90, st.s + 600.0, 0.0, 0.0)
        arriba = alta[int(fila_h) - 40, W // 2, :3]
        abajo = alta[int(fila_h) + 60, 30, :3]
        r.append(check("vista elevada: el horizonte sube (por encima del 40 % "
                       "de la pantalla), el eje a 600 m se proyecta junto a el "
                       "(+-8 px) y encima hay cielo y debajo suelo",
                       0 < fila_h < H * 0.4 and p_lejos is not None
                       and abs(p_lejos[1] - fila_h) < 8
                       and arriba[2] > arriba[1] + 20 and abajo[1] > abajo[2] + 20,
                       f"horizonte en la fila {fila_h:.0f}, eje a 600 m en "
                       f"{None if p_lejos is None else round(p_lejos[1])}, "
                       f"arriba {arriba} abajo {abajo}"))
        p_coche = escena.world_to_screen(c90, st.s, 0.0, 0.0)
        r.append(check("...y el coche queda algo por debajo del centro, con "
                       "carretera por delante",
                       p_coche is not None and H * 0.5 < p_coche[1] < H * 0.8,
                       str(p_coche)))
        # ORBITA: en una curva a la izquierda la camara se va al lado
        # interior (izquierda) y mira al coche, que sigue centrado; la
        # carretera de delante queda entonces a la DERECHA en pantalla
        segs = c90.segments
        s_izq = next(i for i in range(len(segs))
                     if sum(segs[(i + 2 + j) % len(segs)].kappa
                            for j in range(22)) / 22 > 1.0 / 150.0) * cfg.SEGMENT_LENGTH
        orb = render_mod.orbita_elevada(c90, s_izq, 45.0)
        r.append(check("orbita_elevada: curva a la izquierda -> angulo negativo "
                       "(camara a la izquierda) y como mucho 45 grados",
                       -math.radians(45.0) - 1e-9 <= orb < -math.radians(10.0),
                       f"{math.degrees(orb):.1f} grados en s={s_izq:.0f}"))
        kap = np.array([sg.kappa for sg in segs])
        k_del = np.array([abs(np.roll(kap, -(i + 2))[:22].mean()) for i in range(0, len(segs), 10)])
        s_recta = int(np.argmin(k_del)) * 10 * cfg.SEGMENT_LENGTH
        r.append(check("...y en la recta se queda detras (menos de 2 grados)",
                       abs(render_mod.orbita_elevada(c90, s_recta, 45.0)) < math.radians(2.0),
                       f"{math.degrees(render_mod.orbita_elevada(c90, s_recta, 45.0)):.1f} "
                       f"grados en s={s_recta:.0f}"))
        st.s = s_izq
        cam_o = _camara(extra_y=9.0, cam_back=12.0, psi=orb,
                        cam_pitch=math.radians(28.0))
        escena.dibujar(c90, st, cam_o, True, pal)
        p_c = escena.world_to_screen(c90, st.s, 0.0, 0.0)
        p_a = escena.world_to_screen(c90, st.s + 40.0, 0.0, 0.0)
        r.append(check("con la orbita el coche sigue centrado y el eje 40 m por "
                       "delante cae a la derecha de la pantalla",
                       p_c is not None and abs(p_c[0] - W / 2) < 3
                       and p_a is not None and p_a[0] > W * 0.6,
                       f"coche x={None if p_c is None else round(p_c[0])}, "
                       f"delante x={None if p_a is None else round(p_a[0])}"))
        st.s = 3000.0

        # --- vista de PLANTA (perspectiva casi cenital) y vista ISOMETRICA ---
        st.s, st.vx = 3000.0, 25.0
        cam_p = _camara(extra_y=26.0, cam_back=12.0, cam_pitch=math.radians(60.0))
        escena.dibujar(c90, st, cam_p, True, pal)
        sdl2.SDL_RenderPresent(ren)
        planta = leer().astype(int)
        arriba = planta[4, W // 2, :3]
        p_c = escena.world_to_screen(c90, st.s, 0.0, 0.0)
        r.append(check("planta (26 m, 60 grados): el horizonte queda fuera por "
                       "arriba (la primera fila ya es suelo) y el coche sigue "
                       "en pantalla",
                       arriba[1] > arriba[2] + 20 and p_c is not None
                       and H * 0.4 < p_c[1] < H * 0.9, f"arriba {arriba}, coche {p_c}"))
        # isometrica: ortografica de 60 m de alto (96 m de ancho a 640x400),
        # mirada 30 grados a un lado y con el punto de mira 12 m por delante
        # (en el tramo mas recto: en curva la seccion lateral gira con el
        # eje y su proyeccion cambia aunque la escala sea la misma)
        segs_i = c90.segments
        kap_i = np.array([sg.kappa for sg in segs_i])
        k_i = np.array([abs(np.roll(kap_i, -i)[:60].mean()) for i in range(0, len(segs_i), 10)])
        st.s = int(np.argmin(k_i)) * 10 * cfg.SEGMENT_LENGTH
        cam_i = _camara(extra_y=0.0, cam_back=gpu.ORTO_DISTANCIA, psi=math.radians(30.0),
                        cam_forward=12.0, cam_orto=dict(alto=60.0, pitch=math.radians(40.0)))
        escena.dibujar(c90, st, cam_i, True, pal)
        sdl2.SDL_RenderPresent(ren)
        iso = leer().astype(int)
        p_c = escena.world_to_screen(c90, st.s, 0.0, 0.0)
        p_l = escena.world_to_screen(c90, st.s, -5.0, 0.0)
        p_r = escena.world_to_screen(c90, st.s, 5.0, 0.0)
        p_far = escena.world_to_screen(c90, st.s + 200.0, -5.0, 0.0)
        p_far2 = escena.world_to_screen(c90, st.s + 200.0, 5.0, 0.0)
        d_cerca = math.hypot(p_r[0] - p_l[0], p_r[1] - p_l[1])
        d_lejos = math.hypot(p_far2[0] - p_far[0], p_far2[1] - p_far[1])
        r.append(check("isometrica: sin punto de fuga, 10 m miden lo mismo bajo "
                       "el coche que 200 m mas alla (+-8 %: lo que cambia es la "
                       "orientacion del tramo; en perspectiva seria 15 veces menos)",
                       abs(d_cerca - d_lejos) < 0.08 * d_cerca and d_cerca > 30.0,
                       f"{d_cerca:.1f} px cerca, {d_lejos:.1f} px lejos"))
        r.append(check("...el coche queda por debajo del centro (la mira va 12 m "
                       "por delante) y arriba no hay cielo, todo es suelo",
                       p_c is not None and H * 0.5 < p_c[1] < H * 0.95
                       and iso[4, W // 2, 1] > iso[4, W // 2, 2] + 20
                       and iso[4, 10, 1] > iso[4, 10, 2] + 20,
                       f"coche {p_c}, arriba {iso[4, W // 2, :3]}"))
        # de vuelta a la perspectiva normal
        st.s = 3000.0
        escena.dibujar(c90, st, cam, True, pal)

        # --- cielo con nubes y montes con laderas ----------------------------
        st.s, st.vx = 3000.0, 25.0
        cfg.SKY_CLOUDS = 0.0
        escena.dibujar(c90, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        limpio = leer().astype(int)
        cfg.SKY_CLOUDS = 0.6
        escena.dibujar(c90, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
        nublado = leer().astype(int)
        cfg.SKY_CLOUDS = 0.0
        dif_nube = (np.abs(nublado - limpio).sum(axis=2) > 20)
        ys_n = np.nonzero(dif_nube)[0]
        r.append(check("con SKY_CLOUDS hay nubes: cambian miles de pixeles, todos "
                       "en el cielo (mitad alta) y mas claros que el azul",
                       dif_nube.sum() > 2000 and ys_n.max() < H * 0.55
                       and nublado[dif_nube].mean() > limpio[dif_nube].mean(),
                       f"{dif_nube.sum()} px, hasta la fila {ys_n.max() if len(ys_n) else -1}"))
        # los montes: en la franja justo sobre el horizonte hay laderas claras
        # y oscuras (sombreado por el sol), no un color plano
        fila_h = int(H * 0.5) - 4
        franja = limpio[fila_h - 12:fila_h, :, :3]
        lum = franja.mean(axis=2)
        r.append(check("los montes tienen laderas claras y oscuras (rango de "
                       "luminancia > 25 en la franja sobre el horizonte)",
                       lum.max() - lum.min() > 25,
                       f"luminancia {lum.min():.0f}..{lum.max():.0f}"))

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
        # (el primer fotograma de un circuito incluye su precalculo: arboles,
        # biondas, senales; el coste por fotograma es el del segundo)
        escena.dibujar(c50, st, cam, True, pal)
        sdl2.SDL_RenderPresent(ren)
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
