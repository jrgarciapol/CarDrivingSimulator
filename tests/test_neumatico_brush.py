"""Tests del neumático de curvas separadas (TIRE_MODEL='brush').

En 'legacy' la curva longitudinal y la lateral comparten forma (B, C); solo
cambia la escala de la elipse. En 'brush' cada eje tiene SU propia curva y la
forma se interpola con la dirección del deslizamiento. Se comprueba que:

  - las curvas long y lat son REALMENTE distintas,
  - el coche sigue siendo conducible y estable,
  - la cadena de cargas (referencia) no se ve afectada por el modelo de goma.

    python tests/test_neumatico_brush.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import config as cfg
from simulator.physics import Car

G = 9.81
DT = 1.0 / cfg.PHYSICS_HZ


class FlatTrack:
    def surface_at(self, n, s):
        return "road", cfg.TIRE_MU

    def kappa_at(self, s):
        return 0.0

    def grade_at(self, s):
        return 0.0

    def vcurv_at(self, s):
        return 0.0

    def bump_at(self, s, n, surface):
        return 0.0

    def bank_at(self, s):
        return 0.0


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def _curva(rho, w):
    bb = w * cfg.TIRE_B_LONG + (1.0 - w) * cfg.TIRE_B_LAT
    cc = w * cfg.TIRE_C_LONG + (1.0 - w) * cfg.TIRE_C_LAT
    return math.sin(cc * math.atan(bb * rho))


def main():
    flat = FlatTrack()
    prev = getattr(cfg, "TIRE_MODEL", "legacy")
    cfg.TIRE_MODEL = "brush"
    r = []
    try:
        # --- las curvas long y lat son distintas ----------------------
        long_bajo = _curva(0.5, 1.0)      # longitudinal a medio slip
        lat_bajo = _curva(0.5, 0.0)       # lateral a medio slip
        long_alto = _curva(3.0, 1.0)      # longitudinal muy pasado el pico
        lat_alto = _curva(3.0, 0.0)       # lateral muy pasado el pico
        r.append(check("la curva LONGITUDINAL es mas rigida al inicio",
                       long_bajo > lat_bajo + 0.05,
                       f"long@0.5={long_bajo:.3f} > lat@0.5={lat_bajo:.3f}"))
        r.append(check("la curva LATERAL cae menos pasado el pico",
                       lat_alto > long_alto + 0.05,
                       f"lat@3={lat_alto:.3f} > long@3={long_alto:.3f}"))

        # --- 0-100 razonable ------------------------------------------
        c = Car()
        for _ in range(500):
            c.step(DT, 0.0, 0.0, 0.0, flat)
        t = 0.0
        while c.state.speed_kmh < 100.0 and t < 15.0:
            c.auto_shift(1.0)
            c.step(DT, 0.0, 1.0, 0.0, flat)
            t += DT
        r.append(check("0-100 razonable en modo brush", 3.0 < t < 12.0,
                       f"{t:.1f} s"))

        # --- agarre lateral máximo plausible (~1 g) -------------------
        c = Car()
        for _ in range(500):
            c.step(DT, 0.0, 0.0, 0.0, flat)
        tt = 0.0
        while c.state.speed_kmh < 90.0 and tt < 12.0:
            c.auto_shift(1.0)
            c.step(DT, 0.0, 1.0, 0.0, flat)
            tt += DT
        ay_max = 0.0
        for _ in range(int(3.0 / DT)):
            c.step(DT, 0.32, 0.28, 0.0, flat)
            ay_max = max(ay_max, abs(c.state.ay))
        r.append(check("agarre lateral maximo plausible (0.7-1.4 g)",
                       0.7 * G < ay_max < 1.4 * G, f"{ay_max / G:.2f} g"))

        # --- estabilidad ----------------------------------------------
        c = Car()
        estable = True
        for k in range(int(20.0 / DT)):
            thr = 1.0 if (k * DT) % 4 < 2 else 0.0
            br = 1.0 if (k * DT) % 7 < 0.5 else 0.0
            c.auto_shift(thr)
            c.step(DT, 0.25 * math.sin(k * DT), thr, br, flat)
            st = c.state
            if not (math.isfinite(st.vx) and math.isfinite(st.vy)
                    and st.speed_kmh < 400.0):
                estable = False
                break
        r.append(check("20 s de conduccion variada sin divergir", estable,
                       f"v={c.state.speed_kmh:.0f} km/h"))

        # --- la cadena de cargas no depende del modelo de goma --------
        # (Fz se calcula ANTES que las fuerzas de neumatico). En recta
        # estable, SumaFz = m*g + downforce, igual que en legacy.
        c = Car()
        for _ in range(2500):
            c.step(DT, 0.0, 0.4, 0.0, flat)     # crucero recto estable
        df = cfg.AERO_DOWNFORCE * c.state.vx * c.state.vx
        r.append(check("la cadena de cargas no depende del modelo de goma",
                       abs(sum(c.state.fz) - (cfg.CAR_MASS * G + df))
                       < 0.02 * cfg.CAR_MASS * G,
                       f"SumaFz={sum(c.state.fz):.0f} vs m*g+DF="
                       f"{cfg.CAR_MASS * G + df:.0f} N"))
    finally:
        cfg.TIRE_MODEL = prev

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
