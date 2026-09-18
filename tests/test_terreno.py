"""Pruebas del terreno de montana y del circuito M-50.

  - la M-50 sale del generador con rampas del 10 % y peralte del 10 %,
  - el campo de alturas queda CLAVADO a la rasante bajo el eje (sin relieve
    ni desplazamiento, la diferencia es cero salvo en los cruces, donde el
    terreno va con la carretera de arriba),
  - la clasificacion respeta las reglas 10/30 m y las longitudes minimas,
  - el circuito carga su terreno solo, y la C-50 no ha cambiado.

    python tests/test_terreno.py
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import config as cfg                            # noqa: E402
from simulator import terreno                                  # noqa: E402
from simulator.track import Track                              # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
TRACKS = os.path.join(AQUI, "..", "simulator", "tracks")


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return bool(cond)


def main():
    r = []
    L = cfg.SEGMENT_LENGTH
    # --- la M-50 --------------------------------------------------------------
    d = np.loadtxt(os.path.join(TRACKS, "m-50.csv"), delimiter=",", comments="#")
    kap, elev, _, per, hw = d.T
    pend = np.abs(np.diff(elev)) / L * 100.0
    r.append(check("M-50: 25 km, rampas hasta el 10 % (y mas del 7 % de la C-50)",
                   24000 < len(d) * L < 26500 and 9.9 < pend.max() <= 10.05,
                   f"{len(d) * L / 1000:.1f} km, pendiente max {pend.max():.2f} %"))
    en_85 = np.abs(np.abs(kap) - 1.0 / 85.0) < 0.0003      # arcos de R = 85 m
    r.append(check("...peralte del 10 % (5,7 grados) en las curvas de 85 m "
                   "(las glorietas, de 63 m, van al 2 %)",
                   en_85.any()
                   and abs(np.tan(np.abs(per[en_85]).max()) * 100 - 10.0) < 0.1
                   and np.tan(np.abs(per).max()) * 100 < 10.1,
                   f"{np.tan(np.abs(per[en_85]).max()) * 100:.1f} % en R 85, "
                   f"maximo {np.tan(np.abs(per).max()) * 100:.1f} %"))
    c50 = np.loadtxt(os.path.join(TRACKS, "c-50.csv"), delimiter=",", comments="#")
    r.append(check("la C-50 sigue con el 7 % de rampa y el 7 % de peralte",
                   np.abs(np.diff(c50[:, 1])).max() / L * 100 < 7.05
                   and np.tan(np.abs(c50[:, 3]).max()) * 100 < 7.05))

    # --- carga del circuito con su terreno --------------------------------------
    cfg.TRACK_FILE = "tracks/m-50.csv"
    track = Track()
    t = track.terreno
    r.append(check("Track carga m-50.terreno.npz y clasifica las secciones",
                   t is not None and t.seccion is not None
                   and len(t.seccion) == len(track.segments)))
    x, y, h = terreno.planta(track)
    r.append(check("la planta se cierra (el ultimo segmento vuelve al origen)",
                   np.hypot(x[-1] + np.sin(h[-1]) * L - x[0],
                            y[-1] + np.cos(h[-1]) * L - y[0]) < 1.0))
    r.append(check("la rejilla cubre el circuito con margen",
                   t.x0 < x.min() - 100 and t.y0 < y.min() - 100
                   and t.x0 + t.alturas.shape[1] * t.paso > x.max() + 100
                   and t.y0 + t.alturas.shape[0] * t.paso > y.max() + 100))
    # --- el campo sigue a la rasante ---------------------------------------------
    plano = terreno.generar(track, amplitud=0.0, semilla=1, desplazamiento=0.0)
    tp = terreno.Terreno(plano, track)
    dd = tp.d_eje
    r.append(check("sin relieve, el terreno bajo el eje es la rasante (95 % de los "
                   "segmentos a menos de 3 m) y nunca queda por debajo de la "
                   "carretera mas de 3 m (en los cruces va con la de arriba)",
                   np.mean(np.abs(dd) < 3.0) > 0.95 and dd.max() < 3.0,
                   f"{100 * np.mean(np.abs(dd) < 3.0):.1f} %, d max {dd.max():.1f}, "
                   f"d min {dd.min():.1f}"))
    # --- reglas de seccion ----------------------------------------------------------
    sec, de = t.seccion, t.d_eje
    r.append(check("reglas: puente solo con d > 10 m (o alargado), tunel solo con "
                   "d < -30 m (o alargado); terraplen con d > 0 y desmonte con d < 0",
                   np.all(de[sec == terreno.TERRAPLEN] > 0.0)
                   and np.all(de[sec == terreno.DESMONTE] < 0.0)
                   and np.all(np.abs(de[sec == terreno.A_NIVEL]) <= terreno.UMBRAL_NIVEL)
                   and np.mean(t.d_puente[sec == terreno.PUENTE] > terreno.TERRAPLEN_MAX) > 0.7
                   and np.mean(de[sec == terreno.TUNEL] < -terreno.DESMONTE_MAX) > 0.7))
    r.append(check("...y todo tramo con relleno > 10 m (bajo el eje o a 8 m, en media "
                   "ladera) es puente y todo tramo con d < -20 m es tunel",
                   np.all(sec[(t.d_puente > terreno.TERRAPLEN_MAX) & (de > -terreno.UMBRAL_NIVEL)]
                          == terreno.PUENTE)
                   and np.all(sec[de < -terreno.DESMONTE_MAX] == terreno.TUNEL)))
    tun = t.tramos(terreno.TUNEL)
    pue = t.tramos(terreno.PUENTE)
    n = len(sec)

    def bloqueado(k, m, otro, umbral):
        """Un tramo corto solo se admite si a los dos lados hay algo que
        impide alargarlo: la otra estructura o terreno que no admite esta."""
        antes, despues = sec[(k - 1) % n], sec[(k + m) % n]
        d_a, d_d = de[(k - 1) % n], de[(k + m) % n]
        return ((antes == otro or umbral(d_a)) and (despues == otro or umbral(d_d)))
    cortos_tun = [(k, m) for k, m in tun if m * L < terreno.TUNEL_MIN - 1e-6]
    cortos_pue = [(k, m) for k, m in pue if m * L < terreno.PUENTE_MIN - 1e-6]
    dp = t.d_puente
    r.append(check("longitudes minimas: tuneles >= 60 m y puentes >= 40 m, salvo "
                   "los encajonados entre la otra estructura (un puente pegado a "
                   "un tunel: cresta y valle seguidos)",
                   all(((sec[(k - 1) % n] == terreno.PUENTE or dp[(k - 1) % n] > terreno.TERRAPLEN_MAX)
                        and (sec[(k + m) % n] == terreno.PUENTE or dp[(k + m) % n] > terreno.TERRAPLEN_MAX))
                       for k, m in cortos_tun)
                   and all(bloqueado(k, m, terreno.TUNEL, lambda d: d < -terreno.DESMONTE_MAX)
                           for k, m in cortos_pue),
                   f"tuneles {[m * L for _, m in tun]}, puentes "
                   f"{[m * L for _, m in pue]}"))
    r.append(check("reparto de montana: entre 3 y 12 % en tunel, entre 5 y 15 % en "
                   "puente, la mayoria en desmonte o terraplen",
                   0.03 <= np.mean(sec == terreno.TUNEL) <= 0.12
                   and 0.05 <= np.mean(sec == terreno.PUENTE) <= 0.15
                   and np.mean((sec == terreno.DESMONTE) | (sec == terreno.TERRAPLEN)) > 0.6,
                   f"tunel {100 * np.mean(sec == terreno.TUNEL):.1f} %, puente "
                   f"{100 * np.mean(sec == terreno.PUENTE):.1f} %, {len(tun)} tuneles, "
                   f"{len(pue)} puentes"))
    r.append(check("el terreno es determinista (misma semilla, mismo campo)",
                   np.allclose(terreno.generar(track, amplitud=t.amplitud, semilla=t.semilla,
                                               desplazamiento=t.desplazamiento)["alturas"],
                               t.alturas.astype(np.float32), atol=1e-3)))
    # --- los arboles se plantan sobre el suelo que se pinta -------------------
    from simulator import gpu
    t.perfiles(track)
    hw_kw = np.array([s.half_w for s in track.segments]) + cfg.KERB_WIDTH
    elev = np.array([s.y for s in track.segments])
    hondo = np.nonzero((sec == terreno.DESMONTE) & (de < -12.0)
                       & (t.perfil_lat[:, 12] > hw_kw + 1.0 + 15.0)
                       & (t.perfil_lat[:, 7] < -(hw_kw + 1.0 + 15.0)))[0]
    i = int(hondo[len(hondo) // 2])
    o = np.array([12.0, -12.0])
    h = gpu.cota_perfil(t, np.array([i * L, i * L]), o)
    esperado = elev[i] + (12.0 - hw_kw[i] - terreno.BERMA) / terreno.TALUD_DESMONTE
    natural = t.altura(*[np.array(v) for v in
                         (t.planta_xyh[0][i] + o * np.cos(t.planta_xyh[2][i]),
                          t.planta_xyh[1][i] - o * np.sin(t.planta_xyh[2][i]))])
    r.append(check("en un desmonte hondo, a 12 m del eje el arbol se planta en el "
                   "TALUD (cota de la rasante + 5H:4V), no en la cresta del terreno",
                   np.allclose(h, esperado, atol=0.05) and np.all(h < natural - 3.0),
                   f"talud {h[0]:.1f}/{h[1]:.1f} m, terreno natural "
                   f"{natural[0]:.1f}/{natural[1]:.1f} m, rasante {elev[i]:.1f} m"))
    lleno = np.nonzero((sec == terreno.TERRAPLEN) & (de > 5.0))[0]
    j = int(lleno[len(lleno) // 2])
    hj = gpu.cota_perfil(t, np.array([j * L]), np.array([12.0]))[0]
    r.append(check("...y en un terraplen queda por debajo de la rasante",
                   hj < elev[j] - 1.0, f"{hj:.1f} < {elev[j]:.1f}"))
    # la C-50 no trae terreno: sigue como estaba
    cfg.TRACK_FILE = "tracks/c-50.csv"
    r.append(check("la C-50 no tiene terreno y carga como siempre",
                   Track().terreno is None))
    # --- pintado: laderas, puentes y tuneles en la escena de la GPU ----------
    import ctypes
    import sdl2
    from simulator import gpu
    from simulator import render as render_mod
    from simulator.physics import Car
    W, H = 640, 400
    cfg.WINDOW_WIDTH, cfg.WINDOW_HEIGHT, cfg.WINDOW_AUTO = W, H, False
    cfg.GFX_GPU_ASYNC = False
    cfg.SKY_CLOUDS = 0.0
    sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO)
    win = sdl2.SDL_CreateWindow(b"t", 0, 0, W, H, sdl2.SDL_WINDOW_HIDDEN)
    ren = sdl2.SDL_CreateRenderer(win, -1, 0)
    escena = gpu.GpuScene(ren, W, H, msaa=4)
    if not escena.ok:
        print(f"[AVISO] sin OpenGL aqui ({escena.motivo}): se salta el pintado")
    else:
        def leer():
            buf = (ctypes.c_uint8 * (W * H * 4))()
            sdl2.SDL_RenderReadPixels(ren, None, sdl2.SDL_PIXELFORMAT_ABGR8888, buf, W * 4)
            return np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 4)[:, :, :3].astype(int)
        scene = render_mod.Renderer(ren)
        scene.gpu = escena
        cfg.TRACK_FILE = "tracks/m-50.csv"
        pista = Track()
        st = Car().state
        st.vx = 15.0

        def fotograma(s_pos):
            st.s = s_pos
            sdl2.SDL_RenderClear(ren)
            scene.draw_scene(pista, st, False, cam_height=1.35, cam_back=0.0,
                             yaw_gain=None, cam_forward=0.5)
            sdl2.SDL_RenderPresent(ren)
            return leer()
        # desmonte: hay cuadrilateros de roca (talud 1H:1V) a la vista
        i_des = int(np.nonzero(sec == terreno.DESMONTE)[0][100])
        im_des = fotograma(i_des * L)
        vb, _ = escena._montana_bloque
        tipos = vb["col"][:, 0, 3]
        r.append(check("en desmonte la escena de montana pinta miles de cuadrilateros "
                       "y entre ellos taludes de ROCA",
                       escena.montana_dibujada > 1000 and (tipos == gpu.TIPO_ROCA).sum() > 20,
                       f"{escena.montana_dibujada} cuadrilateros, "
                       f"{int((tipos == gpu.TIPO_ROCA).sum())} de roca"))
        # puente: pilas (tablas grises lisas) y caras del tablero
        k_p, m_p = max(t.tramos(terreno.PUENTE), key=lambda km: km[1])
        im_pue = fotograma((k_p + m_p // 2) * L)
        vb, _ = escena._montana_bloque
        lisos = (vb["col"][:, 0, 3] == gpu.TIPO_LISO)
        pilas = lisos & (vb["col"][:, 0, 0] == 140)
        r.append(check("en el puente mas largo se pintan pilas hasta el terreno y las "
                       "caras del tablero",
                       pilas.sum() >= 4 and (lisos & ~pilas).sum() > 20,
                       f"{int(pilas.sum())} tablas de pila, {int((lisos & ~pilas).sum())} caras"))
        # tunel: dentro, arriba hay boveda (nada de azul) y la imagen es mucho
        # mas oscura que fuera; en la boca de salida vuelve a verse el cielo
        k_t, m_t = max(t.tramos(terreno.TUNEL), key=lambda km: km[1])
        fuera = fotograma((k_t - 60) * L)
        dentro = fotograma((k_t + m_t // 2) * L)
        arriba = dentro[6, W // 2]
        r.append(check("dentro del tunel no se ve cielo (boveda encima) y la imagen es "
                       "mucho mas oscura que fuera",
                       not (arriba[2] > arriba[1] + 20) and dentro.mean() < 0.6 * fuera.mean(),
                       f"arriba {arriba}, media dentro {dentro.mean():.0f} fuera {fuera.mean():.0f}"))
        vb, _ = escena._montana_bloque
        r.append(check("...el tubo (hastiales y boveda) y el asfalto van con los "
                       "materiales del tunel",
                       (vb["col"][:, 0, 3] == gpu.TIPO_PARED_TUNEL).sum() > 200
                       and (escena._vertices["col"][:, :, 0, 3] == gpu.TIPO_ASFALTO_TUNEL).any()))
        salida = fotograma((k_t + m_t - 4) * L)
        zona = salida[int(H * 0.3):int(H * 0.7), int(W * 0.35):int(W * 0.65)]
        azul = ((zona[:, :, 2] > zona[:, :, 1] + 20) & (zona[:, :, 2] > zona[:, :, 0] + 40)).sum()
        r.append(check("a 16 m de la boca de salida se ve el cielo por el arco (pixeles "
                       "azules en el centro de la imagen)", azul > 50, f"{azul} px"))
        # en la C-90 no hay montana
        cfg.TRACK_FILE = "tracks/c-90.csv"
        c90 = Track()
        st.s = 3000.0
        scene.draw_scene(c90, st, False, cam_height=1.35, cam_back=0.0,
                         yaw_gain=None, cam_forward=0.5)
        r.append(check("en la C-90 (sin terreno) no se pinta nada de montana",
                       escena.montana_dibujada == 0))
        escena.close()

    n_ok = sum(1 for v in r if v)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
