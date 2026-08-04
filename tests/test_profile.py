"""Pruebas del núcleo de geometría del alzado (sin GUI):
  python tests/test_profile.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import profile_geom as pg


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def main():
    ok = []

    # --- ajuste de rasante: recupera pendiente e ordenada -------------
    g_true, b_true = 0.042, 15.0
    pts = [(s, g_true * s + b_true + (0.05 if s % 8 else -0.05))
           for s in range(0, 300, 20)]
    g, b = pg.fit_grade(pts)
    ok.append(check("fit_grade recupera la pendiente",
                    abs(g - g_true) < 1e-3 and abs(b - b_true) < 1.0,
                    f"g={g*100:.2f}% b={b:.2f}"))

    # --- ensamblado: dos rasantes + acuerdo parabólico ----------------
    step = 4.0
    L = 1000.0
    r1 = pg.build_rasante([(60, 0.05 * 60), (300, 0.05 * 300)])   # +5%
    r2 = pg.build_rasante([(600, 0.05 * 900 - 0.05 * 600 + 45 - 0.05 * 600),
                           (900, 0.0)])                            # se ajusta
    # rasante 2 explícita: pendiente -5%
    r2 = pg.build_rasante([(600, 30.0), (900, 30.0 - 0.05 * 300)])
    grades = pg.assemble_grade([r1, r2], L, step)

    # pendiente constante dentro de cada rasante
    i_mid1 = int(180 / step)
    i_mid2 = int(750 / step)
    ok.append(check("pendiente constante en la rasante 1 (+5%)",
                    abs(grades[i_mid1] - 0.05) < 1e-6,
                    f"g={grades[i_mid1]*100:.2f}%"))
    ok.append(check("pendiente constante en la rasante 2 (-5%)",
                    abs(grades[i_mid2] + 0.05) < 1e-6,
                    f"g={grades[i_mid2]*100:.2f}%"))

    # en el acuerdo [300,600] la pendiente varía LINEALMENTE (parábola):
    # a la mitad debe estar a medio camino entre +5% y -5% -> 0
    i_gapmid = int(450 / step)
    ok.append(check("acuerdo: pendiente lineal (parábola), 0% en el centro",
                    abs(grades[i_gapmid]) < 2e-3, f"g={grades[i_gapmid]*100:.2f}%"))

    # curvatura vertical CONSTANTE en el acuerdo (d²z/ds² = cte, parábola)
    z = pg.integrate_elevation(grades, step, close=False)
    def curv(i):
        return (z[i + 1] - 2 * z[i] + z[i - 1]) / step ** 2
    c1, c2 = curv(int(360 / step)), curv(int(540 / step))
    ok.append(check("acuerdo es una parábola (curvatura vertical constante)",
                    abs(c1 - c2) < 1e-6 and abs(c1) > 1e-7,
                    f"c={c1:.2e} vs {c2:.2e}"))

    # tangencia: en los extremos del acuerdo la pendiente iguala a la rasante
    g_bvc = (z[int(300 / step) + 1] - z[int(300 / step)]) / step
    ok.append(check("acuerdo tangente a la rasante en el inicio (C1)",
                    abs(g_bvc - 0.05) < 2e-3, f"g_BVC={g_bvc*100:.2f}%"))

    # --- cierre del bucle: z_fin ≈ z_ini ------------------------------
    zc = pg.integrate_elevation(grades, step, close=True)
    ok.append(check("cierre: la cota vuelve al inicio",
                    abs(zc[-1] - zc[0]) < 1e-6,
                    f"Δz={zc[-1]-zc[0]:.4f} m"))

    # --- vértice (PIV): intersección de las dos rasantes --------------
    v = pg.piv(r1, r2)
    ok.append(check("PIV = intersección de las rasantes",
                    v is not None and 300 <= v[0] <= 650,
                    f"PIV s={v[0]:.0f} z={v[1]:.1f}"))

    print(f"\n{sum(ok)}/{len(ok)} pruebas correctas")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
