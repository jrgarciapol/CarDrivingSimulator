"""Tests del corte de par en el cambio (SHIFT_CUT_TIME) y del diferencial.

    python tests/test_transmision.py
"""

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


def _ax_tras_cambio(cut_time):
    """Acelera en 2a a fondo, sube a 3a y mide la ax 30 ms DESPUES del
    cambio. Con corte, el par (y la ax) cae en ese instante."""
    prev = cfg.SHIFT_CUT_TIME
    cfg.SHIFT_CUT_TIME = cut_time
    flat = FlatTrack()
    c = Car()
    for _ in range(400):
        c.step(DT, 0.0, 0.0, 0.0, flat)
    # llevar el coche a 2a rodando a fondo
    c.state.gear = 2
    for _ in range(int(2.5 / DT)):
        c.step(DT, 0.0, 1.0, 0.0, flat)
    c.shift_up()                                 # -> 3a, arranca el corte
    for _ in range(int(0.03 / DT)):
        c.step(DT, 0.0, 1.0, 0.0, flat)
    ax = c.state.ax
    cfg.SHIFT_CUT_TIME = prev
    return ax


def main():
    flat = FlatTrack()
    r = []

    # ---- CORTE DE CAMBIO --------------------------------------------
    ax_sin = _ax_tras_cambio(0.0)
    ax_con = _ax_tras_cambio(0.12)
    r.append(check("el corte de par baja la aceleracion justo tras el cambio",
                   ax_con < ax_sin - 0.5,
                   f"ax sin corte={ax_sin:.2f}  con corte={ax_con:.2f} m/s2"))

    # ---- DIFERENCIAL (unitario sobre _diff_torques) -----------------
    c = Car()
    I = c.I_w[RL]
    prev_type = cfg.DIFF_TYPE

    cfg.DIFF_TYPE = "open"
    tl, tr = c._diff_torques(300.0, 40.0, 20.0, DT, I)
    r.append(check("diferencial ABIERTO reparte 50/50 pase lo que pase",
                   abs(tl - 150.0) < 1e-6 and abs(tr - 150.0) < 1e-6,
                   f"izq={tl:.0f} der={tr:.0f}"))

    cfg.DIFF_TYPE = "lsd"
    # rueda IZQUIERDA girando más rápido (patina): el LSD manda par a la
    # derecha (la que agarra, más lenta)
    tl, tr = c._diff_torques(300.0, 45.0, 15.0, DT, I)
    r.append(check("el LSD transfiere par a la rueda que AGARRA (la lenta)",
                   tr > tl, f"izq(patina)={tl:.0f} der(agarra)={tr:.0f}"))

    # rampa de ACELERACION bloquea más que la de RETENCION (para el mismo
    # |par| y la misma diferencia de giro)
    _, tr_pow = c._diff_torques(300.0, 45.0, 15.0, DT, I)
    _, tr_coast = c._diff_torques(-300.0, 45.0, 15.0, DT, I)
    lock_pow = tr_pow - 150.0
    lock_coast = tr_coast - (-150.0)
    r.append(check("bloquea mas ACELERANDO que RETENIENDO (rampas distintas)",
                   lock_pow > lock_coast,
                   f"bloqueo power={lock_pow:.0f} coast={lock_coast:.0f}"))

    # el tope DIFF_MAX_LOCK satura el bloqueo con par de eje enorme
    prev_cap = cfg.DIFF_MAX_LOCK
    cfg.DIFF_MAX_LOCK = 200.0
    tl, tr = c._diff_torques(5000.0, 30.0, 0.0, DT, I)
    transfer = tr - 2500.0
    r.append(check("DIFF_MAX_LOCK satura el bloqueo con par enorme",
                   abs(transfer) <= cfg.DIFF_MAX_LOCK + 1.0,
                   f"transferencia={transfer:.0f} <= tope={cfg.DIFF_MAX_LOCK:.0f}"))
    cfg.DIFF_MAX_LOCK = prev_cap
    cfg.DIFF_TYPE = prev_type

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
