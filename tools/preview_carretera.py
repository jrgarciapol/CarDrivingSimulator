"""Dibuja las TRES carreteras generadas (a-120, c-90, c-50): planta a escala
comun y perfil longitudinal. Guarda docs/img/carreteras.png.

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
TRACKS = [("A-120", "a-120.csv", "#1f77b4"),
          ("C-90", "c-90.csv", "#2ca02c"),
          ("C-50", "c-50.csv", "#d62728")]


def load(path):
    kap, elev = [], []
    for ln in open(path):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        c = ln.split(",")
        kap.append(float(c[0]))
        elev.append(float(c[1]))
    return kap, elev


def plan(kap):
    h, x, y = 0.0, [0.0], [0.0]
    for k in kap:
        x.append(x[-1] + math.cos(h) * SEG)
        y.append(y[-1] + math.sin(h) * SEG)
        h += k * SEG
    return x, y


def main():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    fig, axes = plt.subplots(2, 3, figsize=(15, 8),
                             gridspec_kw={"height_ratios": [3, 1]})
    data = []
    for name, fn, col in TRACKS:
        kap, elev = load(os.path.join(root, "simulator/tracks", fn))
        x, y = plan(kap)
        data.append((name, col, kap, elev, x, y))

    for j, (name, col, kap, elev, x, y) in enumerate(data):
        ax = axes[0][j]
        ax.plot(x, y, color=col, lw=1.6, solid_capstyle="round")
        ax.plot(x[0], y[0], "ko", ms=6)
        ax.set_aspect("equal")
        Rs = [1 / abs(k) for k in kap if abs(k) > 1e-6]
        ax.set_title(f"{name}   {len(kap)*SEG/1000:.2f} km\n"
                     f"R minimo usado {min(Rs):.0f} m",
                     fontweight="bold", color=col)
        ax.grid(alpha=0.2)
        ax.tick_params(labelsize=7)

        ax2 = axes[1][j]
        s = [i * SEG / 1000 for i in range(len(elev))]
        ax2.plot(s, elev, color="#8c564b", lw=1.4)
        ax2.fill_between(s, elev, min(elev) - 1, color="#8c564b", alpha=0.12)
        ax2.set_title("perfil [m] vs km", fontsize=8)
        ax2.grid(alpha=0.25)
        ax2.tick_params(labelsize=7)

    fig.suptitle("Tres carreteras (~30 min a Vp)  -  Norma 3.1-IC   "
                 "(A-120 autovia · C-90 puerto · C-50 montana)  -  curvas izq/dcha",
                 fontweight="bold", fontsize=13)
    plt.tight_layout(rect=(0, 0, 1, 0.96))
    out = os.path.join(root, "docs/img/carreteras.png")
    plt.savefig(out, dpi=110)
    print("OK ->", os.path.normpath(out))


if __name__ == "__main__":
    main()
