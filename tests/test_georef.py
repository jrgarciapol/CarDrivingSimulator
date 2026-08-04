"""Prueba de georref: round-trip con datos geográficos reales (Spa).
  python tests/test_georef.py

Convierte un trazado lat/lon real a metros (como el CSV de TUMFTM), lo
georreferencia de vuelta con 2 puntos de control y comprueba que reconstruye
las coordenadas originales. No necesita red.
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import georef as gr


def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}")
    return cond


def synth_latlon():
    """Trazado lat/lon sintético alrededor de Spa (~5 km), sin depender de
    ficheros: un óvalo inclinado."""
    lat0, lon0 = 50.437, 5.971
    pts = []
    for k in range(400):
        a = 2 * math.pi * k / 400
        # óvalo de ~1.5 x 1.0 km, girado
        ex = 1500 * math.cos(a)
        ny = 1000 * math.sin(a)
        rot = math.radians(35)
        e = ex * math.cos(rot) - ny * math.sin(rot)
        n = ex * math.sin(rot) + ny * math.cos(rot)
        lat = lat0 + n / gr.MLAT
        lon = lon0 + e / gr._mlon(lat0)
        pts.append((lat, lon))
    return pts


def main():
    ok = []
    truth = synth_latlon()                 # [(lat, lon)]

    # simular el CSV de TUMFTM: pasar a METROS con origen/giro arbitrarios
    lat0, lon0 = truth[0]
    ang = math.radians(-63.0)              # giro arbitrario del sistema local
    off = (12345.0, -6789.0)               # traslación arbitraria
    ca, sa = math.cos(ang), math.sin(ang)
    xy = []
    for (lat, lon) in truth:
        e, n = gr.latlon_to_en(lat, lon, lat0, lon0)
        xy.append((off[0] + ca * e - sa * n, off[1] + sa * e + ca * n))

    # 2 puntos de control: sus (x,y) del "CSV" y su lat/lon real
    iA, iB = 0, len(xy) // 3
    rec = gr.georef_points(xy, xy[iA], truth[iA], xy[iB], truth[iB])

    # error en metros entre reconstruido y verdad
    errs = []
    for (la, lo), (tla, tlo) in zip(rec, truth):
        e = (lo - tlo) * gr._mlon(tla)
        n = (la - tla) * gr.MLAT
        errs.append(math.hypot(e, n))
    ok.append(check("la georref reconstruye lat/lon reales (2 controles)",
                    max(errs) < 1.0, f"error max {max(errs):.3f} m"))

    # la escala CSV->m debe salir ~1 (el 'CSV' estaba en metros)
    _, _, _, scale, _ = gr.similarity(xy[iA], truth[iA], xy[iB], truth[iB])
    ok.append(check("escala recuperada ≈ 1 (CSV ya en metros)",
                    abs(scale - 1.0) < 1e-3, f"escala={scale:.5f}"))

    # con un CSV NORMALIZADO (escala 0.001) la semejanza debe recuperar la
    # escala y seguir reconstruyendo
    xy_n = [(x * 0.001, y * 0.001) for (x, y) in xy]
    rec2 = gr.georef_points(xy_n, xy_n[iA], truth[iA], xy_n[iB], truth[iB])
    errs2 = [math.hypot((lo - tlo) * gr._mlon(tla), (la - tla) * gr.MLAT)
             for (la, lo), (tla, tlo) in zip(rec2, truth)]
    _, _, _, scale2, _ = gr.similarity(xy_n[iA], truth[iA], xy_n[iB], truth[iB])
    ok.append(check("funciona con CSV normalizado (recupera la escala)",
                    max(errs2) < 1.0 and abs(scale2 - 1000.0) < 1.0,
                    f"error max {max(errs2):.3f} m, escala={scale2:.1f}"))

    print(f"\n{sum(ok)}/{len(ok)} pruebas correctas")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
