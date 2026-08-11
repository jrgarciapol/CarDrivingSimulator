import os
_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- Magic Formula (Pacejka) para Fy(alpha) ---
mu = 1.3
Fz = 4000.0          # N
D = mu * Fz
C = 1.5
B = 0.55             # rigidez
E = 1.02
a = np.linspace(0, 16, 400)   # deriva en grados
Fy = D * np.sin(C * np.arctan(B*a - E*(B*a - np.arctan(B*a))))

# pico
ipk = int(np.argmax(Fy))
a_pk = a[ipk]

# --- avances (trails) esquematicos ---
# avance mecanico (caster): casi constante
t_mech = 0.030 * np.ones_like(a)              # 30 mm
# avance neumatico: parte en ~30 mm, cae a 0 y algo negativo cerca/pasado el pico
t_pneu = 0.030 * (1 - (a/(a_pk*1.05))**2)
t_pneu = np.clip(t_pneu, -0.008, None)
Mz = Fy * (t_mech + t_pneu)                   # par autoalineante
imz = int(np.argmax(Mz))

fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))

# Panel 1: Fy vs alpha
ax[0].plot(a, Fy/1000, color="#1f4fd0", lw=2.5)
# zona lineal (tangente en 0)
k = np.gradient(Fy, a)[0]
al = np.linspace(0, 6, 2)
ax[0].plot(al, k*al/1000, "--", color="#888", lw=1.3)
ax[0].annotate("zona lineal\n(rigidez de deriva)", (3, k*3/1000), (4.5, 1.2),
               color="#555", fontsize=9,
               arrowprops=dict(arrowstyle="->", color="#999"))
ax[0].plot(a_pk, Fy[ipk]/1000, "o", color="#d62728", ms=8)
ax[0].annotate("PICO de agarre\n(la zona que desliza\nempieza a mandar)",
               (a_pk, Fy[ipk]/1000), (a_pk+1.5, Fy[ipk]/1000-1.6),
               color="#d62728", fontsize=9,
               arrowprops=dict(arrowstyle="->", color="#d62728"))
ax[0].axvspan(0, 6, color="#1f4fd0", alpha=0.05)
ax[0].axvspan(a_pk, 16, color="#d62728", alpha=0.05)
ax[0].text(11, 0.6, "casi toda\nla huella\ndesliza", color="#d62728", fontsize=9)
ax[0].set_title("1. Curva de Pacejka: Fy(alpha)", fontweight="bold")
ax[0].set_xlabel("deriva  alpha  [grados]")
ax[0].set_ylabel("fuerza lateral  Fy  [kN]")
ax[0].grid(alpha=0.25)

# Panel 2: avances
ax[1].plot(a, t_mech*1000, color="#2ca02c", lw=2, label="avance MECANICO (carrito)")
ax[1].plot(a, t_pneu*1000, color="#9467bd", lw=2, label="avance NEUMATICO (deformacion)")
ax[1].axhline(0, color="#aaa", lw=0.8)
ax[1].axvline(a_pk, color="#d62728", ls=":", lw=1.2)
ax[1].text(a_pk+0.2, 26, "pico Fy", color="#d62728", fontsize=8, rotation=90, va="top")
ax[1].fill_between(a, 0, t_pneu*1000, color="#9467bd", alpha=0.10)
ax[1].set_title("2. Los dos avances (brazos de palanca)", fontweight="bold")
ax[1].set_xlabel("deriva  alpha  [grados]")
ax[1].set_ylabel("avance  [mm]")
ax[1].legend(fontsize=8, loc="upper right")
ax[1].grid(alpha=0.25)
ax[1].annotate("se DERRUMBA\ncerca del limite", (a_pk*0.85, t_pneu[int(ipk*0.85)]*1000),
               (2, -6), color="#9467bd", fontsize=8,
               arrowprops=dict(arrowstyle="->", color="#9467bd"))

# Panel 3: Mz vs alpha, comparado con Fy
ax[2].plot(a, Mz/np.max(Mz), color="#e07b00", lw=2.5, label="par autoalineante Mz")
ax[2].plot(a, Fy/np.max(Fy), color="#1f4fd0", lw=1.8, ls="--", label="Fy (normalizado)")
ax[2].plot(a[imz], 1.0, "o", color="#e07b00", ms=8)
ax[2].axvline(a[imz], color="#e07b00", ls=":", lw=1)
ax[2].axvline(a_pk, color="#1f4fd0", ls=":", lw=1)
ax[2].annotate("Mz cae ANTES\nque Fy  ->  el volante\nse aligera = AVISO",
               (a[imz], 1.0), (a[imz]+1.5, 0.72),
               color="#e07b00", fontsize=9,
               arrowprops=dict(arrowstyle="->", color="#e07b00"))
ax[2].set_title("3. Por que se aligera el volante antes del limite", fontweight="bold")
ax[2].set_xlabel("deriva  alpha  [grados]")
ax[2].set_ylabel("valor normalizado")
ax[2].legend(fontsize=8, loc="lower right")
ax[2].grid(alpha=0.25)

plt.tight_layout()
plt.savefig(os.path.join(_OUT, "pacejka.png"), dpi=110)
print("OK")
