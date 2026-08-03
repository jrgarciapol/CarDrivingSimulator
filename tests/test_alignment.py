"""Pruebas del núcleo de geometría del editor de alineaciones (sin GUI):
  python tests/test_alignment.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import alignment_geom as ag


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def main():
    ok = []

    # --- ajuste de círculo con ruido -----------------------------------
    cx, cy, R = 120.0, -40.0, 200.0
    import random
    random.seed(1)
    pts = []
    for a in [0.2 + 0.09 * k for k in range(12)]:   # arco amplio (~57°)
        pts.append((cx + R * math.cos(a) + random.uniform(-0.4, 0.4),
                    cy + R * math.sin(a) + random.uniform(-0.4, 0.4)))
    c, Rf = ag.fit_circle(pts)
    ok.append(check("círculo de mejor ajuste recupera centro y radio",
                    math.dist(c, (cx, cy)) < 1.5 and abs(Rf - R) < 1.5,
                    f"R={Rf:.1f} centro=({c[0]:.1f},{c[1]:.1f})"))

    # --- ajuste de recta con ruido -------------------------------------
    d0 = (math.cos(0.6), math.sin(0.6))
    line_pts = [(3 + 5 * k * d0[0] + random.uniform(-0.3, 0.3),
                 7 + 5 * k * d0[1] + random.uniform(-0.3, 0.3))
                for k in range(10)]
    p, d = ag.fit_line(line_pts)
    ang = abs(math.atan2(d[1], d[0]) - 0.6) % math.pi
    ok.append(check("recta de mejor ajuste recupera la dirección",
                    min(ang, math.pi - ang) < 0.02,
                    f"ang={math.degrees(math.atan2(d[1],d[0])):.1f}"))

    # --- trazado sintético: recta - clotoide - arco - clotoide - recta --
    # construimos la traza REAL integrando un κ(s) conocido y luego
    # "pinchamos" puntos sobre ella para recuperar los elementos
    step = 4.0
    L = 1600.0
    n = int(L / step)
    ktrue = []
    for i in range(n):
        s = i * step
        if s < 400:               # recta
            k = 0.0
        elif s < 500:             # clotoide de entrada (0 -> 1/200)
            k = (s - 400) / 100 * (1 / 200)
        elif s < 900:             # arco derecha R=200
            k = 1 / 200
        elif s < 1000:            # clotoide de salida
            k = (1000 - s) / 100 * (1 / 200)
        else:                     # recta
            k = 0.0
        ktrue.append(k)
    xy = ag.integrate_xy(ktrue, step)
    stations = ag.polyline_stations(xy)

    # pinchar puntos de recta 1, arco y recta 2 (como haría el usuario)
    def pts_between(a, b, m=8):
        return [xy[int((a + (b - a) * t / (m - 1)) / step)]
                for t in range(m)]
    # se pincha cerca de los puntos de tangencia (uso real): las zonas
    # claramente rectas y claramente circulares, dejando la transición
    # para la clotoide
    line1 = ag.build_element("line", pts_between(20, 398), xy, stations)
    arc = ag.build_element("arc", pts_between(502, 898), xy, stations)
    line2 = ag.build_element("line", pts_between(1002, 1580), xy, stations)

    ok.append(check("el arco ajustado da R~200 y signo derecha (+)",
                    arc["kappa"] > 0 and abs(1 / arc["kappa"] - 200) < 8,
                    f"R={1/arc['kappa']:.1f} κ={arc['kappa']:+.5f}"))

    # ensamblar y comparar con la traza real (desviación lateral local)
    ks = ag.assemble_kappa([line1, arc, line2], L, step, close=False)
    rec = ag.integrate_xy(ks, step)

    def local_dev(a, b, win=30):
        worst = 0.0
        for st in range(0, min(len(a), len(b)) - win, win // 2):
            # re-anclar: trasladar para que coincidan al inicio de ventana
            ox, oy = b[st][0] - a[st][0], b[st][1] - a[st][1]
            for i in range(st, st + win):
                worst = max(worst, math.hypot(a[i][0] + ox - b[i][0],
                                              a[i][1] + oy - b[i][1]))
        return worst

    dev = local_dev(rec, xy)
    ok.append(check("el ensamblado reproduce la traza sintética",
                    dev < 3.0, f"desv local {dev:.2f} m"))

    # una curva a IZQUIERDAS debe dar κ negativa
    kleft = [-(1 / 150) if 300 < i * step < 700 else 0.0 for i in range(n)]
    xyl = ag.integrate_xy(kleft, step)
    stl = ag.polyline_stations(xyl)
    arcl = ag.build_element("arc", [xyl[int(s / step)]
                                    for s in range(320, 680, 40)], xyl, stl)
    ok.append(check("una curva a izquierdas da κ negativa",
                    arcl["kappa"] < 0, f"κ={arcl['kappa']:+.5f}"))

    print(f"\n{sum(ok)}/{len(ok)} pruebas correctas")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
