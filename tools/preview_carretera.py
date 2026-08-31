"""Dibuja la CARRETERA generada: planta coloreada por tipo de via (segun el
radio, con los R_min de la Norma 3.1-IC) y perfil longitudinal (rasante y
pendiente). Guarda docs/img/carretera.png.

    python tools/preview_carretera.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SEG = 4.0
RMIN = {"A-120": 687.0, "C-90": 339.0, "C-50": 84.0}
COL = {"A-120": "#1f77b4", "C-90": "#2ca02c", "C-50": "#d62728", "recta": "#999999"}


def zone(k):
    if abs(k) < 1e-6:
        return "recta"
    R = 1.0 / abs(k)
    if R >= RMIN["A-120"]:
        return "A-120"
    if R >= RMIN["C-90"]:
        return "C-90"
    return "C-50"


def load(path):
    kap, elev, ban = [], [], []
    for ln in open(path):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        c = ln.split(",")
        kap.append(float(c[0]))
        elev.append(float(c[1]))
        ban.append(float(c[3]))
    return kap, elev, ban


def main():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    kap, elev, ban = load(os.path.join(root, "simulator/tracks/carretera.csv"))
    n = len(kap)
    # integrar planta
    h = 0.0
    xs, ys = [0.0], [0.0]
    for k in kap:
        x = xs[-1] + math.cos(h) * SEG
        y = ys[-1] + math.sin(h) * SEG
        xs.append(x)
        ys.append(y)
        h += k * SEG

    fig = plt.figure(figsize=(13, 7))
    ax = fig.add_axes([0.02, 0.08, 0.60, 0.86])
    # pintar por tramos de tipo
    i = 0
    while i < n:
        z = zone(kap[i])
        j = i
        while j < n and zone(kap[j]) == z:
            j += 1
        ax.plot(xs[i:j + 1], ys[i:j + 1], color=COL[z], lw=3.2, solid_capstyle="round")
        i = j
    ax.plot(xs[0], ys[0], "ko", ms=9)
    ax.annotate("meta", (xs[0], ys[0]), textcoords="offset points",
                xytext=(8, 8), fontweight="bold")
    ax.set_aspect("equal")
    ax.set_title("CARRETERA  (Norma 3.1-IC)  -  planta", fontweight="bold")
    ax.set_xlabel("m")
    ax.grid(alpha=0.2)
    from matplotlib.lines import Line2D
    leg = [Line2D([0], [0], color=COL[t], lw=3,
                  label=f"{t}  (R>={RMIN[t]:.0f} m)") for t in ("A-120", "C-90", "C-50")]
    ax.legend(handles=leg, loc="upper left", fontsize=9)

    # perfil longitudinal
    s = [i * SEG / 1000.0 for i in range(n)]
    ax2 = fig.add_axes([0.68, 0.57, 0.29, 0.37])
    ax2.plot(s, elev, color="#8c564b", lw=1.8)
    ax2.fill_between(s, elev, min(elev) - 2, color="#8c564b", alpha=0.12)
    ax2.set_title("perfil (rasante)", fontweight="bold", fontsize=10)
    ax2.set_ylabel("cota [m]")
    ax2.grid(alpha=0.25)

    grade = [0.0] + [(elev[i] - elev[i - 1]) / SEG * 100 for i in range(1, n)]
    ax3 = fig.add_axes([0.68, 0.10, 0.29, 0.37])
    ax3.plot(s, grade, color="#e07b00", lw=1.2)
    ax3.axhline(4, color="#1f77b4", ls="--", lw=0.8)
    ax3.axhline(-4, color="#1f77b4", ls="--", lw=0.8)
    ax3.set_title("pendiente [%]  (limite 4%)", fontweight="bold", fontsize=10)
    ax3.set_xlabel("estacion [km]")
    ax3.grid(alpha=0.25)

    out = os.path.join(root, "docs/img/carretera.png")
    plt.savefig(out, dpi=110)
    print("OK ->", os.path.normpath(out))


if __name__ == "__main__":
    main()
