"""Pruebas del solver de cierre del trazado (sin GUI):
  python tests/test_solver.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import alignment_geom as ag
import alignment_solver as sv


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def stadium_trace(R=60.0, straight=200.0, step=2.0):
    """Traza sintética de un 'stadium' (2 rectas + 2 semicírculos a derechas,
    κ=+1/R). Cierra girando 360°."""
    ks = []
    seg = [("line", straight), ("arc", math.pi * R),
           ("line", straight), ("arc", math.pi * R)]
    for kind, Ln in seg:
        n = int(round(Ln / step))
        for _ in range(n):
            ks.append(1.0 / R if kind == "arc" else 0.0)
    xy = ag.integrate_xy(ks, step)
    return xy, ag.polyline_stations(xy), R, straight


def main():
    ok = []
    step = 2.0
    xy, st, R, straight = stadium_trace(R=60.0, straight=200.0, step=step)
    L = st[-1]

    # "pinchar" puntos sobre la traza para recrear rectas y arcos
    def pts(a, b, m):
        return [xy[min(len(xy) - 1, int(s / step))]
                for s in [a + (b - a) * k / (m - 1) for k in range(m)]]

    s_arc = math.pi * R
    e_line1 = ag.build_element("line", pts(15, straight - 15, 6), xy, st)
    e_arc1 = ag.build_element("arc", pts(straight + 12, straight + s_arc - 12, 7),
                              xy, st)
    e_line2 = ag.build_element("line",
                               pts(straight + s_arc + 15, 2 * straight + s_arc - 15, 6),
                               xy, st)
    e_arc2 = ag.build_element("arc",
                              pts(2 * straight + s_arc + 12, 2 * straight + 2 * s_arc - 12, 7),
                              xy, st)
    els = [e_line1, e_arc1, e_line2, e_arc2]

    ok.append(check("los arcos recuperan R~60 y signo derecha (+)",
                    all(e["kappa"] > 0 and abs(1 / e["kappa"] - R) < 3
                        for e in (e_arc1, e_arc2)),
                    f"R1={1/e_arc1['kappa']:.1f} R2={1/e_arc2['kappa']:.1f}"))

    res = sv.solve(els, xy, st, step=4.0)

    turn_deg = math.degrees(res["turn"])
    ok.append(check("el trazado resuelto cierra a ±360°",
                    abs(abs(turn_deg) - 360.0) < 1.5, f"giro={turn_deg:.2f}°"))

    ok.append(check("radio mínimo ≈ R dibujado (radios exactos)",
                    abs(res["rmin"] - R) < 2.0, f"R_min={res['rmin']:.1f}"))

    # la planta cierra en posición
    close = math.hypot(res["plan"][-1][0] - res["plan"][0][0],
                       res["plan"][-1][1] - res["plan"][0][1])
    ok.append(check("la planta resuelta cierra en posición",
                    close < 1.0, f"cierre={close:.3f} m"))

    # hay clotoides con longitud > 0 entre recta y arco
    clo = [ln for s, ln in zip(res["segs"], res["lengths"])
           if s["tipo"] == "clo"]
    ok.append(check("se generan clotoides entre alineaciones",
                    all(c > 0 for c in clo) and max(clo) > 5.0,
                    f"L_clo max={max(clo):.1f} m"))

    # retranqueo local pequeño y coherente (p ≈ L²/24R)
    rl = res["retranqueos_local"]
    ok.append(check("retranqueo local coherente (>0, pocos metros)",
                    rl and all(0 <= d["p_in"] < 0.5 * R for d in rl),
                    f"p_max={max(max(d['p_in'], d['p_out']) for d in rl):.2f} m"))

    print(f"\n{sum(ok)}/{len(ok)} pruebas correctas")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
