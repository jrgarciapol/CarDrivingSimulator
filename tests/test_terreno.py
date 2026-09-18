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
                   and np.mean(de[sec == terreno.PUENTE] > terreno.TERRAPLEN_MAX) > 0.7
                   and np.mean(de[sec == terreno.TUNEL] < -terreno.DESMONTE_MAX) > 0.7))
    r.append(check("...y todo tramo con d > 10 m es puente y todo tramo con d < -30 m "
                   "es tunel (no hay terraplenes ni desmontes fuera de norma)",
                   np.all(sec[de > terreno.TERRAPLEN_MAX] == terreno.PUENTE)
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
    r.append(check("longitudes minimas: tuneles >= 60 m y puentes >= 40 m, salvo "
                   "los encajonados entre la otra estructura (un puente pegado a "
                   "un tunel: cresta y valle seguidos)",
                   all(bloqueado(k, m, terreno.PUENTE, lambda d: d > terreno.TERRAPLEN_MAX)
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
                   np.allclose(terreno.generar(track, amplitud=50.0, semilla=1)["alturas"],
                               t.alturas.astype(np.float32), atol=1e-3)))
    # la C-50 no trae terreno: sigue como estaba
    cfg.TRACK_FILE = "tracks/c-50.csv"
    r.append(check("la C-50 no tiene terreno y carga como siempre",
                   Track().terreno is None))
    n_ok = sum(1 for v in r if v)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
