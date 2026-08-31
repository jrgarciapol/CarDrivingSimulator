"""Figura de CALIBRACION del neumatico: dibuja las curvas REALES del modelo
(con los valores de config.py), no una Pacejka ilustrativa. Compara el modo
'legacy' (curva compartida) con 'brush' (curvas long/lat separadas) y valida
que las magnitudes son las de un neumatico de verdad (pico ~ mu*Fz).

    python docs/img/fuentes/curvas_neumatico.py
"""
import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", ".."))
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from simulator import config as cfg

_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

MU = cfg.TIRE_MU
FZ = 3300.0                                  # N (~carga estatica delantera)
PS = cfg.TIRE_PEAK_SLIP_RATIO
PA = math.radians(cfg.TIRE_PEAK_SLIP_ANGLE_DEG)
RL = cfg.TIRE_LONG_GRIP_RATIO
CAP = MU * FZ                                # techo teorico de agarre


def force(slip, alpha, model):
    s_n = slip / PS
    a_n = alpha / PA
    s_e = s_n / RL
    rho = math.hypot(s_e, a_n)
    if rho < 1e-9:
        return 0.0, 0.0
    if model == "brush":
        w = (s_e * s_e) / (rho * rho)
        B = w * cfg.TIRE_B_LONG + (1 - w) * cfg.TIRE_B_LAT
        C = w * cfg.TIRE_C_LONG + (1 - w) * cfg.TIRE_C_LAT
    else:
        B, C = cfg.TIRE_B, cfg.TIRE_C
    ft = MU * FZ * math.sin(C * math.atan(B * rho))
    return ft * (s_e / rho) * RL, -ft * (a_n / rho)


COL = {"legacy": "#888888", "brush": "#1f4fd0"}
fig, ax = plt.subplots(2, 2, figsize=(12, 9))

# --- Panel 1: LONGITUDINAL Fx(slip) ---------------------------------------
slips = np.linspace(0, 0.40, 300)
for m in ("legacy", "brush"):
    fx = [force(s, 0.0, m)[0] / 1000 for s in slips]
    ax[0, 0].plot(slips * 100, fx, color=COL[m], lw=2.4, label=m)
    ipk = int(np.argmax(fx))
    ax[0, 0].plot(slips[ipk] * 100, fx[ipk], "o", color=COL[m], ms=7)
ax[0, 0].axhline(CAP * RL / 1000, color="#d62728", ls="--", lw=1,
                 label="mu*Fz*ratio_long (techo)")
ax[0, 0].set_title("1. LONGITUDINAL  Fx(deslizamiento)", fontweight="bold")
ax[0, 0].set_xlabel("deslizamiento  [%]")
ax[0, 0].set_ylabel("Fx  [kN]")
ax[0, 0].legend(fontsize=8)
ax[0, 0].grid(alpha=0.25)

# --- Panel 2: LATERAL Fy(deriva) ------------------------------------------
alfas = np.linspace(0, 16, 300)
for m in ("legacy", "brush"):
    fy = [abs(force(0.0, math.radians(a), m)[1]) / 1000 for a in alfas]
    ax[0, 1].plot(alfas, fy, color=COL[m], lw=2.4, label=m)
    ipk = int(np.argmax(fy))
    ax[0, 1].plot(alfas[ipk], fy[ipk], "o", color=COL[m], ms=7)
ax[0, 1].axhline(CAP / 1000, color="#d62728", ls="--", lw=1, label="mu*Fz (techo)")
ax[0, 1].set_title("2. LATERAL  Fy(deriva)", fontweight="bold")
ax[0, 1].set_xlabel("deriva  [grados]")
ax[0, 1].set_ylabel("Fy  [kN]")
ax[0, 1].legend(fontsize=8)
ax[0, 1].grid(alpha=0.25)

# --- Panel 3: ELIPSE DE FRICCION (combinada) ------------------------------
# para cada direccion, el maximo de fuerza combinada -> envolvente
for m in ("legacy", "brush"):
    xs, ys = [], []
    for phi in np.linspace(0, 2 * math.pi, 240):
        best = 0.0
        bx = by = 0.0
        for rho in np.linspace(0.3, 3.0, 60):
            s_e = rho * math.cos(phi)
            a_n = rho * math.sin(phi)
            slip = s_e * RL * PS
            alpha = a_n * PA
            fx, fy = force(slip, alpha, m)
            mag = math.hypot(fx, fy)
            if mag > best:
                best, bx, by = mag, fx, fy
        xs.append(bx / 1000)
        ys.append(by / 1000)
    ax[1, 0].plot(xs, ys, color=COL[m], lw=2.2, label=m)
th = np.linspace(0, 2 * math.pi, 200)
ax[1, 0].plot(CAP * RL / 1000 * np.cos(th), CAP / 1000 * np.sin(th),
              color="#d62728", ls="--", lw=1, label="elipse mu*Fz")
ax[1, 0].set_title("3. ELIPSE DE FRICCION (no se puede el maximo en ambos ejes)",
                   fontweight="bold")
ax[1, 0].set_xlabel("Fx  [kN]")
ax[1, 0].set_ylabel("Fy  [kN]")
ax[1, 0].set_aspect("equal")
ax[1, 0].legend(fontsize=8)
ax[1, 0].grid(alpha=0.25)

# --- Panel 4: TEMPERATURA (multiplicador de mu) ---------------------------
T = np.linspace(10, 130, 300)
mult = np.maximum(0.72, 1.0 - cfg.TIRE_TEMP_SENS * (T - cfg.TIRE_TEMP_OPT) ** 2)
ax[1, 1].plot(T, mult, color="#e07b00", lw=2.4)
ax[1, 1].axvline(cfg.TIRE_TEMP_OPT, color="#2ca02c", ls=":", lw=1.2,
                 label=f"optimo {cfg.TIRE_TEMP_OPT:.0f}C")
ax[1, 1].axvline(cfg.TIRE_TEMP_AMB, color="#1f4fd0", ls=":", lw=1.2,
                 label=f"frio {cfg.TIRE_TEMP_AMB:.0f}C (x{mult[np.argmin(abs(T-cfg.TIRE_TEMP_AMB))]:.2f})")
ax[1, 1].set_title("4. TEMPERATURA: multiplicador de agarre", fontweight="bold")
ax[1, 1].set_xlabel("temperatura de la goma  [C]")
ax[1, 1].set_ylabel("mu / mu_optimo")
ax[1, 1].set_ylim(0.6, 1.05)
ax[1, 1].legend(fontsize=8)
ax[1, 1].grid(alpha=0.25)

fig.suptitle(f"Curvas del neumatico del CarDrivingSimulator  "
             f"(Fz={FZ:.0f} N, mu={MU:.2f})", fontweight="bold", fontsize=13)
plt.tight_layout(rect=(0, 0, 1, 0.97))
plt.savefig(os.path.join(_OUT, "curvas_neumatico.png"), dpi=110)
print("OK -> docs/img/curvas_neumatico.png")
