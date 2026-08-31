"""Tests del INTEGRADOR: convergencia temporal y no creación de energía.

Responden a dos preguntas de ingeniería sobre el paso de integración
(Euler semi-implícito a 480 Hz):

  1. CONVERGENCIA: ¿el resultado depende de la frecuencia de física? Si al
     doblarla apenas cambia, el integrador está convergido y no hace falta
     uno de mayor orden (predictor-corrector).
  2. ENERGÍA: ¿el integrador crea energía artificial? Un coche soltado solo
     puede frenar; una suspensión perturbada debe amortiguar; un corrugado
     no debe amplificarse. Si algo de eso crece, el integrador está
     inyectando energía.

    python tests/test_integrador.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulator import config as cfg
from simulator.physics import Car, FL


class FlatTrack:
    def surface_at(self, n, s):
        return "road", cfg.TIRE_MU

    def kappa_at(self, s):
        return 0.0

    def grade_at(self, s):
        return 0.0

    def vcurv_at(self, s):
        return 0.0

    def bank_at(self, s):
        return 0.0

    def bump_at(self, s, n, surface):
        return 0.0


class BumpTrack(FlatTrack):
    def bump_at(self, s, n, surface):
        return 0.03 * math.exp(-((s - 60.0) ** 2) / 4.0)   # bache de 3 cm


class CorrugatedTrack(FlatTrack):
    def bump_at(self, s, n, surface):
        return 0.015 * math.sin(s * 6.0)


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def _maniobra(hz):
    """Misma maniobra (acelerar, volantazo, bache, frenar) a una frecuencia
    de física dada. Devuelve el estado final."""
    dt = 1.0 / hz
    b = BumpTrack()
    c = Car()
    for _ in range(int(1.0 * hz)):
        c.step(dt, 0, 0, 0, b)
    c.state.vx = 25.0
    for i in range(4):
        c.state.omega[i] = 25.0 / cfg.CAR_WHEEL_RADIUS
    c.state.gear = 4
    for _ in range(int(1.5 * hz)):
        c.auto_shift(1.0)
        c.step(dt, 0.0, 1.0, 0, b)
    for _ in range(int(1.0 * hz)):
        c.step(dt, 0.5, 0.5, 0, b)
    for _ in range(int(1.5 * hz)):
        c.step(dt, 0.0, 0.0, 1.0, b)
    st = c.state
    return {"vx": st.vx, "yaw": st.yaw_rate, "n": st.n, "fz": st.fz[FL]}


def main():
    r = []

    # ---- CONVERGENCIA TEMPORAL --------------------------------------
    R = {hz: _maniobra(hz) for hz in (480, 960, 1920)}
    ref = R[1920]

    def dif(hz):
        a = R[hz]
        return (abs(a["vx"] - ref["vx"]) / max(1.0, abs(ref["vx"])),
                abs(a["n"] - ref["n"]),
                abs(a["yaw"] - ref["yaw"]))

    d480, d960 = dif(480), dif(960)
    r.append(check("480 Hz esta convergido (dif con 1920 Hz pequena)",
                   d480[0] < 0.03 and d480[1] < 0.08,
                   f"vx_rel={d480[0]:.4f} n={d480[1]:.3f} m yaw={d480[2]:.5f}"))
    r.append(check("doblar a 960 Hz acerca a la referencia (converge)",
                   d960[1] <= d480[1] + 1e-6,
                   f"n: 480->{d480[1]:.3f}  960->{d960[1]:.3f} m"))
    r.append(check("las FUERZAS (Fz) convergen entre 480 y 1920 Hz",
                   abs(R[480]["fz"] - ref["fz"]) < 30.0,
                   f"FzFL 480={R[480]['fz']:.0f} vs 1920={ref['fz']:.0f} N"))

    # ---- ENERGIA: coasting solo puede frenar ------------------------
    flat = FlatTrack()
    DT = 1.0 / cfg.PHYSICS_HZ
    c = Car()
    for _ in range(400):
        c.step(DT, 0, 0, 0, flat)
    c.state.vx = 40.0
    for i in range(4):
        c.state.omega[i] = 40.0 / cfg.CAR_WHEEL_RADIUS
    c.state.gear = 6
    subidas = 0
    prev = c.state.vx
    for _ in range(int(8.0 / DT)):
        c.step(DT, 0.0, 0.0, 0.0, flat)     # ni gas ni freno: solo disipa
        if c.state.vx > prev + 1e-5:
            subidas += 1
        prev = c.state.vx
    r.append(check("coasting: la velocidad nunca sube sola (no crea energia)",
                   subidas == 0, f"pasos con v subiendo={subidas}"))

    # ---- ENERGIA: la suspension perturbada AMORTIGUA ----------------
    c = Car()
    for _ in range(2000):
        c.step(DT, 0, 0, 0, flat)
    c.state.heave = 0.05                     # levantar 5 cm y soltar
    picos = []
    prev_v = 0.0
    for _ in range(int(3.0 / DT)):
        c.step(DT, 0, 0, 0, flat)
        st = c.state
        if prev_v > 0 and st.heave_v <= 0:
            picos.append(abs(st.heave))
        prev_v = st.heave_v
    decae = all(picos[i + 1] < picos[i] + 1e-4 for i in range(len(picos) - 1))
    r.append(check("la suspension perturbada amortigua (no se amplifica)",
                   decae and len(picos) >= 1,
                   f"picos={[round(p, 4) for p in picos[:5]]}"))

    # ---- ENERGIA: corrugado acotado ---------------------------------
    corr = CorrugatedTrack()
    c = Car()
    for _ in range(400):
        c.step(DT, 0, 0, 0, corr)
    c.state.vx = 30.0
    for i in range(4):
        c.state.omega[i] = 30.0 / cfg.CAR_WHEEL_RADIUS
    c.state.gear = 5
    zu_max = 0.0
    for _ in range(int(6.0 / DT)):
        c.step(DT, 0, 0.3, 0, corr)
        zu_max = max(zu_max, abs(c.state.zu[FL]))
    r.append(check("sobre corrugado la masa no suspendida queda ACOTADA",
                   zu_max < 0.05, f"|zu| max={zu_max * 1000:.1f} mm"))

    n_ok = sum(1 for x in r if x)
    print(f"\n{n_ok}/{len(r)} pruebas correctas")
    return 0 if n_ok == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
