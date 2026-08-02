"""Genera el circuito OVALO: un óvalo de velocidad con curvas peraltadas.

Uso:  python tools/make_oval.py

Escribe simulator/tracks/ovalo.csv en el formato interno del simulador
(columnas por segmento de 4 m: kappa, elevación, piano, peralte_rad).
Es un óvalo a izquierdas estilo americano: dos rectas de 450 m y dos
curvas de 180 grados con radio 190 m y peralte que crece hasta 18
grados en el centro de la curva. En las curvas, la gravedad aporta
parte del giro y la carga extra multiplica el agarre: se pueden tomar
mucho más rápido que su radio en llano.
"""

import math
import os

SEG = 4.0             # m por segmento (formato interno)
STRAIGHT = 450.0      # m de cada recta
RADIUS = 190.0        # m de radio de las curvas
BANK_MAX_DEG = 18.0   # peralte máximo en el centro de la curva
RAMP = 130.0          # m de transición del peralte/curvatura


def rows():
    curve_len = math.pi * RADIUS          # 180 grados
    out = []
    for part in range(4):                 # recta, curva, recta, curva
        is_curve = part % 2 == 1
        length = curve_len if is_curve else STRAIGHT
        n = int(round(length / SEG))
        for i in range(n):
            d = (i + 0.5) * SEG
            if is_curve:
                # entrada y salida suavizadas (curvatura y peralte a la vez)
                ease = min(1.0, d / RAMP, (length - d) / RAMP)
                kappa = -ease / RADIUS    # óvalo a izquierdas
                bank = -math.radians(BANK_MAX_DEG) * ease
                kerb = 1
            else:
                kappa, bank, kerb = 0.0, 0.0, 0
            out.append((kappa, 0.0, kerb, bank))
    return out


def main():
    path = os.path.join(os.path.dirname(__file__), "..",
                        "simulator", "tracks", "ovalo.csv")
    with open(path, "w") as f:
        f.write("# OVALO generado por tools/make_oval.py\n")
        f.write("# kappa_1_per_m, elev_m, kerb, peralte_rad\n")
        for kappa, elev, kerb, bank in rows():
            f.write(f"{kappa:.6f},{elev:.2f},{kerb},{bank:.4f}\n")
    n = len(rows())
    print(f"ovalo.csv: {n} segmentos, {n * SEG:.0f} m")


if __name__ == "__main__":
    main()
