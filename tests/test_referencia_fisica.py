"""Tests de FÍSICA DE REFERENCIA: comprueban que las MAGNITUDES del modelo
coinciden con cálculos de primeros principios, no solo que el coche "hace X".

A diferencia de test_physics.py (que valida comportamientos: 0-100, frenada,
subviraje...), aquí se contrasta el simulador contra la teoría clásica de
dinámica vehicular:

  - carga estática por rueda = reparto del peso,
  - transferencia longitudinal  ΔFz = m·a·h/L,
  - transferencia lateral       ΔFz = m·a·h/vía,
  - conservación de carga vertical  ΣFz = m·g + downforce.

Idea propuesta al revisar el proyecto: separar "¿el modelo es correcto?" de
"¿qué valores lleva este coche?". Estos tests responden a lo primero.

    python tests/test_referencia_fisica.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import config as cfg
from simulator.physics import Car, FL, FR, RL, RR

G = 9.81
DT = 1.0 / cfg.PHYSICS_HZ


class FlatTrack:
    """Recta llana de asfalto infinito, sin peralte ni rasante."""

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


def _rel(a, b):
    """Error relativo respecto a b (referencia)."""
    return abs(a - b) / abs(b) if b else abs(a)


def main():
    flat = FlatTrack()
    m = cfg.CAR_MASS
    h = cfg.CAR_CG_HEIGHT
    L = cfg.WHEELBASE
    tw = cfg.CAR_TRACK_WIDTH
    wf = cfg.WEIGHT_DIST_FRONT
    r = []

    # ------------------------------------------------------------------
    # 1) CARGA ESTÁTICA: el reparto de peso en reposo
    # ------------------------------------------------------------------
    print("--- Carga estatica ---")
    car = Car()
    for _ in range(4000):
        car.step(DT, 0.0, 0.0, 0.0, flat)
    fz = car.state.fz
    front = fz[FL] + fz[FR]
    rear = fz[RL] + fz[RR]
    r.append(check("la suma de cargas = peso del coche (m*g)",
                   _rel(sum(fz), m * G) < 0.005,
                   f"suma={sum(fz):.0f} N vs m*g={m * G:.0f} N"))
    r.append(check("reparto delantero = WEIGHT_DIST_FRONT",
                   _rel(front, m * G * wf) < 0.02,
                   f"front={front:.0f} N vs teoria={m * G * wf:.0f} N"))
    r.append(check("reparto trasero = 1 - WEIGHT_DIST_FRONT",
                   _rel(rear, m * G * (1.0 - wf)) < 0.02,
                   f"rear={rear:.0f} N vs teoria={m * G * (1.0 - wf):.0f} N"))
    r.append(check("las dos ruedas de un eje cargan igual en recta",
                   _rel(fz[FL], fz[FR]) < 0.01 and _rel(fz[RL], fz[RR]) < 0.01,
                   f"FL={fz[FL]:.0f} FR={fz[FR]:.0f} RL={fz[RL]:.0f} RR={fz[RR]:.0f}"))

    # ------------------------------------------------------------------
    # 2) TRANSFERENCIA LONGITUDINAL: frenada fuerte  ΔFz = m·a·h/L
    # ------------------------------------------------------------------
    print("--- Transferencia longitudinal (frenada) ---")
    car = Car()
    for _ in range(1500):
        car.step(DT, 0.0, 0.0, 0.0, flat)
    for _ in range(int(6.0 / DT)):          # acelerar a buena velocidad
        car.auto_shift(1.0)
        car.step(DT, 0.0, 1.0, 0.0, flat)
    axs, fzf, fzr = [], [], []
    for _ in range(int(1.5 / DT)):          # frenada a fondo
        car.step(DT, 0.0, 0.0, 1.0, flat)
        st = car.state
        axs.append(st.ax)
        fzf.append(st.fz[FL] + st.fz[FR])
        fzr.append(st.fz[RL] + st.fz[RR])
    ax = sum(axs[-40:]) / 40
    dFf = sum(fzf[-40:]) / 40 - m * G * wf
    dFr = sum(fzr[-40:]) / 40 - m * G * (1.0 - wf)
    dFz_teo = m * abs(ax) * h / L
    r.append(check("la transferencia longitudinal = m*|a|*h/L",
                   _rel(abs(dFf), dFz_teo) < 0.12,
                   f"modelo={dFf:+.0f} N vs teoria={dFz_teo:.0f} N (a={abs(ax) / G:.2f} g)"))
    r.append(check("lo que gana el eje delantero lo pierde el trasero",
                   _rel(abs(dFf), abs(dFr)) < 0.10,
                   f"front={dFf:+.0f} N  rear={dFr:+.0f} N"))

    # ------------------------------------------------------------------
    # 3) TRANSFERENCIA LATERAL: curva estable  ΔFz = m·a·h/vía
    # ------------------------------------------------------------------
    print("--- Transferencia lateral (curva) ---")
    car = Car()
    for _ in range(1500):
        car.step(DT, 0.0, 0.0, 0.0, flat)
    t = 0.0
    while car.state.speed_kmh < 90.0 and t < 12.0:
        car.auto_shift(1.0)
        car.step(DT, 0.0, 1.0, 0.0, flat)
        t += DT
    ays, ext, inte, tot, vxs = [], [], [], [], []
    for _ in range(int(3.0 / DT)):          # volante constante, gas de mantener
        car.step(DT, 0.30, 0.28, 0.0, flat)
        st = car.state
        ays.append(st.ay)
        ext.append(st.fz[FL] + st.fz[RL])   # exterior (curva a derechas)
        inte.append(st.fz[FR] + st.fz[RR])  # interior
        tot.append(sum(st.fz))
        vxs.append(st.vx)
    ay = sum(ays[-40:]) / 40
    ext_m = sum(ext[-40:]) / 40
    inte_m = sum(inte[-40:]) / 40
    transfer = (ext_m - inte_m) / 2.0
    dFz_teo = m * abs(ay) * h / tw
    r.append(check("la transferencia lateral = m*|a|*h/via",
                   _rel(transfer, dFz_teo) < 0.15,
                   f"modelo={transfer:.0f} N/lado vs teoria={dFz_teo:.0f} N (a={abs(ay) / G:.2f} g)"))
    r.append(check("la rueda exterior carga y la interior descarga",
                   ext_m > m * G * 0.5 and inte_m < m * G * 0.5,
                   f"exterior={ext_m:.0f} N  interior={inte_m:.0f} N"))

    # ------------------------------------------------------------------
    # 4) CONSERVACIÓN: la transferencia no crea ni destruye carga total.
    #    En curva ΣFz = m*g + downforce (la aero SÍ suma; el reparto entre
    #    ruedas, no).
    # ------------------------------------------------------------------
    vx = sum(vxs[-40:]) / 40
    downforce = cfg.AERO_DOWNFORCE * vx * vx
    sigma = sum(tot[-40:]) / 40
    esperado = m * G + downforce
    r.append(check("carga total en curva = m*g + downforce (aero incluida)",
                   _rel(sigma, esperado) < 0.03,
                   f"suma={sigma:.0f} N vs m*g+DF={esperado:.0f} N "
                   f"(downforce={downforce:.0f} N a {vx * 3.6:.0f} km/h)"))

    # ------------------------------------------------------------------
    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
