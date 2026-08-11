import os
_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np, math

fig = plt.figure(figsize=(15, 5.2))

# ---- Panel 1: una rueda vista desde arriba: apunta vs va ----
ax = fig.add_subplot(1, 3, 1); ax.set_aspect("equal"); ax.axis("off")
ax.set_title("1. UNA RUEDA (vista de pajaro)", fontsize=11, weight="bold")
# rueda (rectangulo) apuntando hacia +x
w, l = 0.5, 1.4
ax.add_patch(plt.Rectangle((-l/2, -w/2), l, w, fc="0.25", ec="k"))
# direccion a la que APUNTA (plano de la rueda) = +x
ax.annotate("", xy=(2.4, 0), xytext=(0, 0),
            arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#1a7d1a"))
ax.text(2.45, 0, "hacia donde\nAPUNTA\n(plano de la rueda)", color="#1a7d1a",
        fontsize=9, va="center")
# direccion a la que VA (velocidad del punto de contacto), girada un angulo alpha
al = math.radians(20)
vx, vy = 2.1*math.cos(-al), 2.1*math.sin(-al)
ax.annotate("", xy=(vx, vy), xytext=(0, 0),
            arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#c0392b"))
ax.text(vx*1.02, vy-0.35, "hacia donde\nVA (velocidad\ndel contacto)",
        color="#c0392b", fontsize=9, va="top")
# arco del angulo alpha
th = np.linspace(-al, 0, 30)
ax.plot(1.2*np.cos(th), 1.2*np.sin(th), "k", lw=1)
ax.text(1.35, -0.22, r"$\alpha$ = DERIVA", fontsize=11, weight="bold")
# fuerza lateral resultante (perpendicular a la velocidad, hacia el lado apuntado)
ax.annotate("", xy=(0.9, 1.15), xytext=(0.9, 0),
            arrowprops=dict(arrowstyle="-|>", lw=3, color="#2c3e99"))
ax.text(1.0, 0.9, "Fy\n(fuerza\nlateral)", color="#2c3e99", fontsize=9)
ax.set_xlim(-1.2, 5.0); ax.set_ylim(-1.8, 1.6)

# ---- Panel 2: por que? el cepillo (brush model) ----
ax = fig.add_subplot(1, 3, 2); ax.axis("off")
ax.set_title("2. POR QUE: la goma se deforma en la huella",
             fontsize=11, weight="bold")
# huella de contacto (rectangulo), el neumatico entra por la derecha y sale izq
ax.add_patch(plt.Rectangle((0, -1), 6, 2, fc="0.9", ec="0.5"))
ax.text(3, 1.25, "sentido de avance -->", ha="center", fontsize=9, color="0.4")
ax.text(0.2, -1.35, "ENTRA", fontsize=8, color="0.4")
ax.text(5.2, -1.35, "SALE", fontsize=8, color="0.4")
# linea central de la rueda (a donde apunta)
ax.plot([0, 6], [0, 0], "--", color="#1a7d1a", lw=1)
# los tacos de goma se van deflectando (como cerdas de un cepillo arrastradas)
xs = np.linspace(0.4, 5.6, 12)
for i, x in enumerate(xs):
    t = i/(len(xs)-1)
    defl = 0.9*t if t < 0.72 else 0.9*0.72   # crece y luego desliza (satura)
    color = "#c0392b" if t >= 0.72 else "#2c3e99"
    ax.plot([x, x], [0, defl], color=color, lw=2.5)
    ax.plot(x, defl, "o", color=color, ms=4)
ax.annotate("", xy=(5.6, 1.15), xytext=(0.4, 0.02),
            arrowprops=dict(arrowstyle="-", lw=1, color="0.6", ls=":"))
ax.text(2.0, 0.95, "los tacos se deflectan mas y mas\n(zona de agarre, azul)",
        color="#2c3e99", fontsize=8.5)
ax.text(4.2, -0.55, "aqui ya deslizan\n(zona roja)", color="#c0392b", fontsize=8.5)
ax.text(3, -1.75, "La suma de todas esas deflexiones elasticas = la fuerza lateral",
        ha="center", fontsize=9, style="italic")
ax.set_xlim(-0.3, 6.3); ax.set_ylim(-2.0, 1.5)

# ---- Panel 3: tres angulos distintos en el coche ----
ax = fig.add_subplot(1, 3, 3); ax.set_aspect("equal"); ax.axis("off")
ax.set_title("3. EN EL COCHE: tres angulos distintos",
             fontsize=11, weight="bold")
# cuerpo del coche, apuntando +x, girando a la izquierda (curva)
bx, by, bl, bw = 0, 0, 2.4, 1.0
ax.add_patch(plt.Rectangle((-bl/2, -bw/2), bl, bw, fc="none", ec="k", lw=1.5))
ax.plot([-bl/2, bl/2+1.4], [0, 0], "-", color="k", lw=1)  # eje del coche
ax.text(bl/2+1.45, 0, "eje del coche\n(el 'morro')", fontsize=8.5, va="center")
# velocidad del CG, con beta respecto al eje
be = math.radians(-8)
ax.annotate("", xy=(2.3*math.cos(be), 2.3*math.sin(be)), xytext=(0,0),
            arrowprops=dict(arrowstyle="-|>", lw=2, color="#c0392b"))
ax.text(2.3*math.cos(be), 2.3*math.sin(be)-0.3, "velocidad del coche",
        color="#c0392b", fontsize=8.5, va="top")
ax.text(1.15, -0.28, r"$\beta$ (deriva del", fontsize=9, color="#c0392b")
ax.text(1.15, -0.52, r"chasis)", fontsize=9, color="#c0392b")
# ruedas delanteras giradas (steer) un angulo delta
for sy in (0.5, -0.5):
    ax.add_patch(plt.Rectangle((bl/2-0.35, sy-0.12), 0.5, 0.24, angle=18,
                 fc="#1a7d1a", ec="k"))
ax.text(bl/2+0.1, 0.85, r"$\delta$ (giro del volante)", fontsize=9, color="#1a7d1a")
# ruedas traseras rectas
for sy in (0.5, -0.5):
    ax.add_patch(plt.Rectangle((-bl/2-0.15, sy-0.12), 0.5, 0.24, fc="#555", ec="k"))
ax.text(-bl/2-1.7, -0.9, "cada rueda tiene\nSU deriva propia",
        fontsize=8.5, color="0.3")
ax.set_xlim(-2.2, 4.2); ax.set_ylim(-1.8, 1.6)

plt.tight_layout()
out = os.path.join(_OUT, "deriva.png")
plt.savefig(out, dpi=95, facecolor="white"); print("guardado", out)
