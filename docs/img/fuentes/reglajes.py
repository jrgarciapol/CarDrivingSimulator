import os
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle

_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
fig, ax = plt.subplots(1, 3, figsize=(16.5, 5.0))

# ---------------- 1. ALTURA LIBRE Y RAKE ----------------
a = ax[0]
a.set_xlim(-0.5, 5.0); a.set_ylim(-0.35, 2.6); a.axis("off")
a.set_title("1. ALTURA LIBRE y RAKE", fontweight="bold")
a.plot([-0.3, 4.9], [0, 0], color="#444", lw=2.5)          # asfalto
a.text(4.85, -0.22, "asfalto", fontsize=8, color="#444", ha="right")
# carroceria inclinada: morro bajo, cola alta
h_del, h_tra = 0.45, 0.95
xs = np.array([0.55, 4.10])
ys = np.array([h_del, h_tra])
cuerpo = np.array([[0.35, h_del-0.03], [4.35, h_tra-0.03],
                   [4.35, h_tra+0.62], [2.6, h_tra+0.78],
                   [1.7, h_del+0.80], [0.35, h_del+0.45]])
a.add_patch(plt.Polygon(cuerpo, closed=True, fc="#c8d4e8", ec="#33507d", lw=2))
for x, r in ((1.15, 0.42), (3.65, 0.46)):
    a.add_patch(plt.Circle((x, r), r, fc="#2a2a2a", ec="#111", lw=1.5))
    a.add_patch(plt.Circle((x, r), r*0.42, fc="#8f8f8f", ec="#555", lw=1))
# cotas de altura libre
for x, h, lbl, col in ((0.55, h_del, "altura libre\nDELANTE", "#d62728"),
                       (4.30, h_tra, "altura libre\nDETRAS", "#1f4fd0")):
    a.annotate("", xy=(x, 0), xytext=(x, h),
               arrowprops=dict(arrowstyle="<->", color=col, lw=2))
    a.text(x + (0.12 if x < 2 else -0.12), h/2, lbl, fontsize=8.5, color=col,
           ha="left" if x < 2 else "right", va="center", fontweight="bold")
# linea de referencia y angulo de rake
a.plot([0.35, 4.45], [h_del, h_del], "--", color="#999", lw=1.2)
a.plot([0.35, 4.45], [h_del, h_tra + (h_tra-h_del)*0.02], ":", color="#e07b00", lw=2)
a.annotate("RAKE\n(la cola mas alta\nque el morro)", (3.2, 0.86), (2.05, 1.95),
           fontsize=9, color="#e07b00", fontweight="bold", ha="center",
           arrowprops=dict(arrowstyle="->", color="#e07b00"))
a.annotate("", xy=(0.9, 0), xytext=(0.9, -0.28),
           arrowprops=dict(arrowstyle="->", color="#2ca02c", lw=2))
a.text(0.35, 2.38, "bajarlo -> menos transferencia de carga\n"
                   "subir el rake -> reparte carga aero atras",
       fontsize=8.5, color="#444", style="italic")

# ---------------- 2. TOPES DE RECORRIDO ----------------
b = ax[1]
rec = np.linspace(0, 110, 400)          # mm de compresion
k = 50.0                                # N/mm del muelle
hueco = 65.0                            # mm libres hasta el tope
k_tope = 900.0                          # N/mm del tope (muy rigido)
exceso = np.maximum(rec - hueco, 0.0)
F = k * rec + k_tope * exceso**1.5 / 30.0
F_sin = k * rec
b.plot(rec, F_sin/1000, "--", color="#999", lw=1.8,
       label="solo el muelle (lineal)")
b.plot(rec, F/1000, color="#1f4fd0", lw=2.6, label="muelle + TOPE")
b.axvline(hueco, color="#d62728", ls=":", lw=1.8)
b.fill_between(rec, F_sin/1000, F/1000, where=rec > hueco,
               color="#d62728", alpha=0.15)
b.text(hueco+2, 0.6, "empieza a tocar\nEL TOPE", color="#d62728",
       fontsize=9, fontweight="bold")
b.annotate("aqui la suspension deja de\nser un muelle y se vuelve\ncasi RIGIDA",
           (95, F[np.argmin(abs(rec-95))]/1000), (18, 7.4),
           fontsize=9, color="#1f4fd0",
           arrowprops=dict(arrowstyle="->", color="#1f4fd0"))
b.annotate("", xy=(0, 1.2), xytext=(hueco, 1.2),
           arrowprops=dict(arrowstyle="<->", color="#2ca02c", lw=2))
b.text(hueco/2, 1.45, "hueco libre", ha="center", fontsize=8.5,
       color="#2ca02c", fontweight="bold")
b.set_title("2. TOPES DE RECORRIDO (bump stops)", fontweight="bold")
b.set_xlabel("compresion de la suspension [mm]")
b.set_ylabel("fuerza en la rueda [kN]")
b.grid(alpha=0.25); b.legend(fontsize=8, loc="upper left")
b.set_ylim(0, 9)

# ---------------- 3. RAMPAS DE LSD Y PRECARGA ----------------
c = ax[2]
T = np.linspace(-450, 450, 400)          # par del motor (+ acelerar, - retener)
precarga = 60.0                          # Nm siempre presentes
rampa_acc, rampa_ret = 0.45, 0.20        # fraccion bloqueada
bloq = precarga + np.where(T >= 0, rampa_acc*T, rampa_ret*(-T))
c.plot(T, bloq, color="#1f4fd0", lw=2.8)
c.axvline(0, color="#aaa", lw=1)
c.fill_between(T, 0, precarga, color="#2ca02c", alpha=0.18)
c.axhline(precarga, color="#2ca02c", ls="--", lw=1.6)
c.annotate(f"PRECARGA = {precarga:.0f} Nm\n(bloqueo que hay SIEMPRE,\naunque no pises nada)",
           (-330, precarga), (-430, 148), fontsize=8.5, color="#2ca02c",
           fontweight="bold", arrowprops=dict(arrowstyle="->", color="#2ca02c"))
c.annotate("rampa de ACELERACION\n(pisando: bloquea mucho,\ntraccion a la salida)",
           (300, precarga+rampa_acc*300), (40, 232), fontsize=8.5,
           color="#d62728", fontweight="bold",
           arrowprops=dict(arrowstyle="->", color="#d62728"))
c.annotate("rampa de RETENCION\n(soltando: bloquea poco,\ndeja entrar el coche)",
           (-330, precarga+rampa_ret*330), (-435, 236), fontsize=8.5,
           color="#e07b00", fontweight="bold",
           arrowprops=dict(arrowstyle="->", color="#e07b00"))
c.text(150, 12, "ACELERANDO -->", fontsize=9, color="#d62728", fontweight="bold")
c.text(-390, 12, "<-- RETENIENDO", fontsize=9, color="#e07b00", fontweight="bold")
c.set_title("3. RAMPAS del DIFERENCIAL y PRECARGA", fontweight="bold")
c.set_xlabel("par que pasa por el diferencial  [Nm]")
c.set_ylabel("par de BLOQUEO entre ruedas  [Nm]")
c.grid(alpha=0.25); c.set_ylim(0, 290)

plt.tight_layout()
plt.savefig(os.path.join(_OUT, "reglajes.png"), dpi=110)
print("guardado")
