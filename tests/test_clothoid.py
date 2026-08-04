"""Pruebas del núcleo de clotoides (sin GUI):
  python tests/test_clothoid.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import clothoid as cl


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def main():
    ok = []

    # --- Fresnel: valores conocidos y límite en el infinito ------------
    C05, S05 = cl.fresnel(0.5)
    ok.append(check("Fresnel C(0.5),S(0.5) correctos",
                    abs(C05 - 0.492344) < 1e-4 and abs(S05 - 0.064732) < 1e-4,
                    f"C={C05:.5f} S={S05:.5f}"))
    C1, S1 = cl.fresnel(1.0)       # valores tabulados C(1)=0.7799 S(1)=0.4383
    ok.append(check("Fresnel C(1),S(1) correctos",
                    abs(C1 - 0.779893) < 1e-4 and abs(S1 - 0.438259) < 1e-4,
                    f"C={C1:.5f} S={S1:.5f}"))

    # --- clotoide: ángulo τ = L/(2R) -----------------------------------
    L, R = 80.0, 250.0
    x, y, th = cl.clothoid_endpoint(L, R, sign=1.0)
    ok.append(check("ángulo de la clotoide τ = L/2R",
                    abs(th - L / (2 * R)) < 1e-4, f"θ={th:.5f} L/2R={L/(2*R):.5f}"))

    # --- integrador directo vs forma cerrada de Fresnel ----------------
    xf, yf, thf = cl.clothoid_endpoint_fresnel(L, R, sign=1.0)
    ok.append(check("endpoint por integración == por Fresnel",
                    math.hypot(x - xf, y - yf) < 0.05,
                    f"dxy={math.hypot(x-xf,y-yf):.4f} m"))

    # --- signo: a la izquierda (sign=-1) el extremo cae con y<0 --------
    _, yL, thL = cl.clothoid_endpoint(L, R, sign=-1.0)
    ok.append(check("clotoide a la izquierda: y<0 y θ<0",
                    yL < 0 and thL < 0, f"y={yL:.2f} θ={thL:.4f}"))

    # --- retranqueo: exacto ~ aproximación de manual L²/24R ------------
    p, xc, tau = cl.clothoid_shift(L, R, sign=1.0)
    p_aprox = L * L / (24.0 * R)
    ok.append(check("retranqueo p ≈ L²/24R (aprox. de manual)",
                    abs(p - p_aprox) / p_aprox < 0.02,
                    f"p={p:.3f} m  L²/24R={p_aprox:.3f} m"))
    ok.append(check("retroceso de la tangente xc ≈ L/2",
                    abs(xc - L / 2.0) / (L / 2.0) < 0.02,
                    f"xc={xc:.2f} m  L/2={L/2:.2f} m"))

    # --- el círculo tangente al final de la clotoide encaja: su centro
    #     dista R del extremo y (R+p) de la recta de entrada -------------
    cx = xc
    cy = 1.0 * (R + p)
    dist_extremo = math.hypot(cx - x, cy - y)
    ok.append(check("centro del círculo a R del extremo de la clotoide",
                    abs(dist_extremo - R) < 0.05,
                    f"dist={dist_extremo:.3f} R={R:.1f}"))

    print(f"\n{sum(ok)}/{len(ok)} pruebas correctas")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
