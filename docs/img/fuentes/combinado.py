import os
_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyArrowPatch

OUT = _OUT + os.sep
fig, ax = plt.subplots(1, 3, figsize=(16, 5.0))

# ---------------- Panel 1: elipse de friccion ----------------
ratio = 1.10          # TIRE_LONG_GRIP_RATIO
mu, Fz = 1.3, 4000.0
Fy_max = mu*Fz/1000.0
Fx_max = Fy_max*ratio
a0 = ax[0]
th = np.linspace(0, 2*np.pi, 400)
a0.plot(Fy_max*np.sin(th), Fx_max*np.cos(th), color="#1f4fd0", lw=2.5)
a0.axhline(0, color="#bbb", lw=0.8); a0.axvline(0, color="#bbb", lw=0.8)

def arrow(x, y, txt, col, dx=0.25, dy=0.25):
    a0.add_patch(FancyArrowPatch((0,0), (x,y), color=col, lw=2.2,
                                 arrowstyle="-|>", mutation_scale=14))
    a0.text(x+dx, y+dy, txt, color=col, fontsize=9, fontweight="bold")

arrow(0, -Fx_max, "solo FRENAR\n(100% long.)", "#d62728", dx=-1.6, dy=-0.9)
arrow(Fy_max, 0, "solo GIRAR\n(100% lat.)", "#2ca02c", dx=-0.9, dy=0.45)
ang = np.radians(52)
arrow(Fy_max*np.sin(ang), -Fx_max*np.cos(ang), "COMBINADO\n(frenada en curva)", "#e07b00",
      dx=0.15, dy=-0.9)
a0.plot([Fy_max*np.sin(ang)], [-Fx_max*np.cos(ang)], "o", color="#e07b00", ms=7)
a0.text(-Fy_max*0.95, Fx_max*0.72, "DENTRO = agarra\n(margen)", fontsize=9, color="#555")
a0.text(Fy_max*0.30, Fx_max*0.80, "FUERA = imposible\n(desliza)", fontsize=9, color="#d62728")
a0.set_title("1. Elipse de friccion: el presupuesto de agarre", fontweight="bold")
a0.text(-Fy_max*1.28, -Fx_max*1.32, "aqui casi circular:\nTIRE_LONG_GRIP_RATIO = 1.10\n(10% mas capacidad longitudinal)",
        fontsize=8, color="#1f4fd0", style="italic")
a0.set_xlabel("fuerza LATERAL  Fy  [kN]"); a0.set_ylabel("fuerza LONGITUDINAL  Fx  [kN]")
a0.set_xlim(-Fy_max*1.35, Fy_max*1.55); a0.set_ylim(-Fx_max*1.45, Fx_max*1.25)
a0.grid(alpha=0.22); a0.set_aspect("equal")

# ---------------- Panel 2: transferencia de carga ----------------
a1 = ax[1]
a1.set_xlim(-1.6, 1.6); a1.set_ylim(-2.2, 2.6); a1.axis("off")
a1.set_title("2. Transferencia de carga (frenando + girando dcha)", fontweight="bold")
# chasis
a1.add_patch(plt.Rectangle((-0.62, -1.55), 1.24, 3.1, fc="#eef1f6", ec="#8892a4", lw=1.5))
a1.annotate("", xy=(0, 2.35), xytext=(0, 1.75),
            arrowprops=dict(arrowstyle="-|>", color="#444", lw=1.6))
a1.text(0.07, 2.05, "avance", fontsize=8, color="#444")
# cargas por rueda (kN) tipicas: frenada fuerte + curva a derechas
loads = {(-0.62, 1.15): 5.6, (0.62, 1.15): 2.4, (-0.62, -1.15): 2.6, (0.62, -1.15): 1.1}
lbl   = {(-0.62, 1.15): "DEL-IZQ\n(exterior)", (0.62, 1.15): "DEL-DCH\n(interior)",
         (-0.62, -1.15): "TRA-IZQ\n(exterior)", (0.62, -1.15): "TRA-DCH\n(interior)"}
mx = max(loads.values())
for (x, y), v in loads.items():
    f = v/mx
    col = plt.cm.Blues(0.20 + 0.72*f)
    w, h = 0.26, 0.52
    a1.add_patch(plt.Rectangle((x-w/2, y-h/2), w, h, fc=col, ec="#333", lw=1.4))
    a1.text(x + (0.30 if x > 0 else -0.30), y+0.10, f"{v:.1f} kN",
            fontsize=10, fontweight="bold", ha="left" if x > 0 else "right")
    a1.text(x + (0.30 if x > 0 else -0.30), y-0.26, lbl[(x, y)],
            fontsize=7.5, color="#555", ha="left" if x > 0 else "right")
a1.annotate("", xy=(0, 1.62), xytext=(0, -1.62),
            arrowprops=dict(arrowstyle="-|>", color="#d62728", lw=2.6))
a1.text(0.06, 0.30, "el peso se va\nADELANTE\n(frenada)", fontsize=8.5, color="#d62728")
a1.annotate("", xy=(-0.72, 0.0), xytext=(0.72, 0.0),
            arrowprops=dict(arrowstyle="-|>", color="#1f4fd0", lw=2.6))
a1.text(-1.55, 0.16, "y hacia FUERA\n(curva)", fontsize=8.5, color="#1f4fd0")
a1.text(0, -2.05, "reparto estatico: 3.0 kN en cada rueda", fontsize=8.5,
        ha="center", style="italic", color="#666")

# ---------------- Panel 3: por que transferir PIERDE agarre ----------------
a2 = ax[2]
LS = 0.10                    # TIRE_LOAD_SENS
fz_ref = 3.0                 # kN
fz = np.linspace(0.4, 6.2, 300)
mu_f = mu*np.clip(1 - LS*(fz - fz_ref)/fz_ref, 0.6, 1.3)
a2.plot(fz, mu_f*fz, color="#1f4fd0", lw=2.5, label="agarre de UNA rueda  mu(Fz)*Fz")
# lineal ideal (si mu fuese constante)
a2.plot(fz, mu*fz, "--", color="#aaa", lw=1.4, label="si mu fuese constante (lineal)")
def grip(x):
    return mu*np.clip(1 - LS*(x - fz_ref)/fz_ref, 0.6, 1.3)*x
# eje sin transferir: 3+3 ; con transferencia: 5+1
for (l, r, col, nm, yo) in [(3.0, 3.0, "#2ca02c", "SIN transferir (3+3)", 0.55),
                            (5.0, 1.0, "#d62728", "CON transferencia (5+1)", -0.75)]:
    tot = grip(l) + grip(r)
    a2.plot([l, r], [grip(l), grip(r)], "o", color=col, ms=8)
    a2.plot([l, r], [grip(l), grip(r)], "-", color=col, lw=1.4, alpha=0.55)
    mid = ((l+r)/2, (grip(l)+grip(r))/2)
    a2.plot(*mid, "s", color=col, ms=7)
    a2.annotate(f"{nm}\nagarre del eje = {tot:.2f} kN", mid,
                (mid[0]-1.9, mid[1]+yo), color=col, fontsize=8.5, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=col))
a2.set_title("3. Por que transferir peso PIERDE agarre", fontweight="bold")
a2.set_xlabel("carga vertical de la rueda  Fz  [kN]")
a2.set_ylabel("fuerza maxima disponible  [kN]")
a2.legend(fontsize=8, loc="upper left"); a2.grid(alpha=0.22)
g0, g1 = 2*grip(3.0), grip(5.0)+grip(1.0)
a2.text(3.3, 2.05, f"transferir 3+3 -> 5+1\ncuesta {100*(g0-g1)/g0:.1f}% del agarre del eje",
        fontsize=9, color="#d62728", fontweight="bold")
a2.text(3.3, 0.55, "la curva es CONCAVA:\nla media de los extremos\nqueda por DEBAJO del centro",
        fontsize=8.5, color="#555", style="italic")

plt.tight_layout()
plt.savefig(os.path.join(_OUT, "combinado_transferencia.png"), dpi=110)
print("OK")
