"""Tests del motor con INERCIA de cigüeñal + embrague (ENGINE_MODEL='inertia').

Comprueban los comportamientos que el modo 'legacy' (régimen pegado a las
ruedas con un filtro) NO puede reproducir, y que el modelo es estable:

  - acelerón LIBRE en punto muerto (blip),
  - patinaje/flare del embrague en la salida desde parado,
  - aceleración 0-100 razonable (no se rompe respecto a legacy),
  - 20 s de conducción variada sin divergencia.

    python tests/test_motor_inercia.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import config as cfg
from simulator.physics import Car, RL, RR

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


def main():
    flat = FlatTrack()
    prev = getattr(cfg, "ENGINE_MODEL", "legacy")
    cfg.ENGINE_MODEL = "inertia"
    r = []
    try:
        # --- acelerón libre en punto muerto ---------------------------
        c = Car()
        c.state.gear = 0
        for _ in range(500):
            c.step(DT, 0.0, 0.0, 0.0, flat)
        rpm_idle = c.state.rpm
        for _ in range(int(0.6 / DT)):          # gas a fondo en punto muerto
            c.step(DT, 0.0, 1.0, 0.0, flat)
        rpm_blip = c.state.rpm
        for _ in range(int(1.5 / DT)):          # soltar: debe caer
            c.step(DT, 0.0, 0.0, 0.0, flat)
        rpm_back = c.state.rpm
        r.append(check("acelera en PUNTO MUERTO (legacy no puede)",
                       rpm_blip > rpm_idle + 2000.0,
                       f"ralenti={rpm_idle:.0f} -> blip={rpm_blip:.0f}"))
        r.append(check("al soltar en punto muerto el regimen CAE",
                       rpm_back < rpm_blip - 800.0,
                       f"blip={rpm_blip:.0f} -> {rpm_back:.0f}"))

        # --- flare de embrague en la salida ---------------------------
        c = Car()
        for _ in range(500):
            c.step(DT, 0.0, 0.0, 0.0, flat)
        flare = False
        for _ in range(int(3.0 / DT)):
            c.auto_shift(1.0)
            c.step(DT, 0.0, 1.0, 0.0, flat)
            st = c.state
            ratio = c._drive_ratio(st.gear)
            om = (st.omega[RL] + st.omega[RR]) / 2.0
            rpm_wheels = abs(om) * abs(ratio) * 60.0 / (2.0 * math.pi)
            if st.speed_kmh < 15.0 and st.rpm > rpm_wheels + 400.0:
                flare = True
        r.append(check("el embrague PATINA en la salida (rpm motor > rueda)",
                       flare, f"v={c.state.speed_kmh:.0f} km/h"))

        # --- 0-100 razonable ------------------------------------------
        c = Car()
        for _ in range(500):
            c.step(DT, 0.0, 0.0, 0.0, flat)
        t = 0.0
        while c.state.speed_kmh < 100.0 and t < 15.0:
            c.auto_shift(1.0)
            c.step(DT, 0.0, 1.0, 0.0, flat)
            t += DT
        r.append(check("0-100 razonable en modo inercia",
                       3.0 < t < 12.0, f"{t:.1f} s"))

        # --- estabilidad ----------------------------------------------
        c = Car()
        estable = True
        for k in range(int(20.0 / DT)):
            thr = 1.0 if (k * DT) % 4 < 2 else 0.0
            br = 1.0 if (k * DT) % 7 < 0.5 else 0.0
            c.auto_shift(thr)
            c.step(DT, 0.2 * math.sin(k * DT), thr, br, flat)
            st = c.state
            if not (math.isfinite(st.vx) and math.isfinite(st.rpm)
                    and st.rpm <= cfg.ENGINE_LIMITER_RPM + 1.0
                    and st.speed_kmh < 400.0):
                estable = False
                break
        r.append(check("20 s de conduccion variada sin divergir", estable,
                       f"v={c.state.speed_kmh:.0f} km/h rpm={c.state.rpm:.0f}"))
    finally:
        cfg.ENGINE_MODEL = prev

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
